import json
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app import models
from app.config import get_settings
from app.services.agent_actions import AgentActionService
from app.services.chat import ChatService


class SlackAppService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()

    def command(self, form: dict[str, str]) -> dict[str, Any]:
        text = (form.get("text") or "").strip()
        user = form.get("user_name") or form.get("user_id") or "slack_user"
        if not text or text == "help":
            return _ephemeral(_help_text())

        command, _, rest = text.partition(" ")
        command = command.lower()
        rest = rest.strip()

        if command == "risks":
            return self._risks_response()
        if command == "project":
            return self._project_response(rest)
        if command == "ask":
            return self._ask_response(rest, user=user)
        if command == "actions":
            return self._actions_response()
        return _ephemeral(f"Unknown Panopticon command: `{command}`\n\n{_help_text()}")

    def interaction(self, payload: dict[str, Any]) -> dict[str, Any]:
        user = payload.get("user") or {}
        actor = user.get("username") or user.get("name") or user.get("id") or "slack_user"
        actions = payload.get("actions") or []
        if not actions:
            return _ephemeral("No Slack action was provided.")

        action = actions[0]
        action_name = str(action.get("action_id") or "")
        value = str(action.get("value") or "")
        action_id = _action_id(value)
        if not action_id:
            return _ephemeral("Panopticon could not identify the action to update.")

        service = AgentActionService(self.db)
        try:
            if action_name in {"approve_action", "panopticon_approve"} or value.startswith("approve:"):
                updated = service.approve(action_id, actor=actor, reason="Approved from Slack")
                return _ephemeral(f"Approved action #{updated.id}: {updated.title}. Review or execute it in Panopticon: {self._action_url(updated.id)}")
            if action_name in {"reject_action", "panopticon_reject"} or value.startswith("reject:"):
                updated = service.reject(action_id, actor=actor, reason="Rejected from Slack")
                return _ephemeral(f"Rejected action #{updated.id}: {updated.title}.")
        except LookupError:
            return _ephemeral(f"Action #{action_id} was not found.")
        except ValueError as exc:
            return _ephemeral(str(exc))

        return _ephemeral("Unsupported Panopticon Slack action.")

    def event(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("type") == "url_verification":
            return {"challenge": payload.get("challenge", "")}

        event = payload.get("event") or {}
        if event.get("type") == "app_mention":
            text = str(event.get("text") or "").strip()
            return {"ok": True, "handled": "app_mention", "text": text}
        return {"ok": True, "handled": "ignored"}

    def _risks_response(self) -> dict[str, Any]:
        risks = self.db.scalars(select(models.RiskAssessment).order_by(desc(models.RiskAssessment.created_at)).limit(5)).all()
        if not risks:
            return _ephemeral("No risk assessments are currently stored.")

        lines = ["Top Panopticon risks:"]
        for risk in risks[:5]:
            lines.append(f"- {risk.project_path}: {risk.score:.0f}/100 {risk.level}. {risk.summary}")
        return _ephemeral("\n".join(lines), blocks=[_section("\n".join(lines)), _context_link("Open dashboard", self._dashboard_url())])

    def _project_response(self, query: str) -> dict[str, Any]:
        if not query:
            return _ephemeral("Usage: `/panopticon project checkout-service`")
        like = f"%{query.lower()}%"
        project = self.db.scalar(
            select(models.GitLabProject)
            .where(
                models.GitLabProject.project_path.ilike(like)
                | models.GitLabProject.name.ilike(like)
                | models.GitLabProject.namespace.ilike(like)
            )
            .order_by(desc(models.GitLabProject.last_activity_at))
            .limit(1)
        )
        if not project:
            return _ephemeral(f"No synced project matched `{query}`.")
        text = (
            f"{project.project_path}: latest pipeline {project.latest_pipeline_status or 'unknown'}"
            f"{f' #{project.latest_pipeline_id}' if project.latest_pipeline_id else ''}; "
            f"{project.open_merge_requests_count} open MR(s), {project.failed_pipelines_count} failed pipeline(s)."
        )
        return _ephemeral(text, blocks=[_section(text), _context_link("Open project", self._project_url(project.id))])

    def _ask_response(self, question: str, *, user: str) -> dict[str, Any]:
        if not question:
            return _ephemeral("Usage: `/panopticon ask why did the latest pipeline fail`")
        answer = ChatService(self.db).answer(message=question)["assistant_message"].content
        return _ephemeral(answer)

    def _actions_response(self) -> dict[str, Any]:
        actions = self.db.scalars(
            select(models.AgentAction)
            .where(models.AgentAction.status == "pending_approval")
            .order_by(desc(models.AgentAction.created_at))
            .limit(5)
        ).all()
        if not actions:
            return _ephemeral("No actions are currently pending approval.")

        blocks: list[dict[str, Any]] = [_section("Pending Panopticon approvals:")]
        for action in actions:
            blocks.extend(
                [
                    _section(f"*#{action.id} {action.title}*\n{action.summary[:500]}\nProject: `{action.project_path}`"),
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Approve"},
                                "style": "primary",
                                "action_id": "approve_action",
                                "value": f"approve:{action.id}",
                            },
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Reject"},
                                "style": "danger",
                                "action_id": "reject_action",
                                "value": f"reject:{action.id}",
                            },
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Open In Panopticon"},
                                "url": self._action_url(action.id),
                                "action_id": "open_action",
                                "value": f"open:{action.id}",
                            },
                        ],
                    },
                ]
            )
        return {"response_type": "ephemeral", "text": "Pending Panopticon approvals", "blocks": blocks}

    def _dashboard_url(self) -> str:
        return self.settings.app_public_url.rstrip("/")

    def _project_url(self, project_id: int) -> str:
        return f"{self._dashboard_url()}/projects/{project_id}"

    def _action_url(self, action_id: int) -> str:
        return f"{self._dashboard_url()}/actions?action={action_id}"


def parse_interaction_payload(form: dict[str, str]) -> dict[str, Any]:
    raw = form.get("payload") or "{}"
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {}


def _ephemeral(text: str, *, blocks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    response = {"response_type": "ephemeral", "text": text[:3000]}
    if blocks:
        response["blocks"] = blocks
    return response


def _section(text: str) -> dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text[:3000]}}


def _context_link(label: str, url: str) -> dict[str, Any]:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": f"<{url}|{label}>"}]}


def _help_text() -> str:
    return "\n".join(
        [
            "Panopticon commands:",
            "`/panopticon risks` - show current top risks",
            "`/panopticon project <name>` - show a project summary",
            "`/panopticon ask <question>` - ask Panopticon chat",
            "`/panopticon actions` - list pending approvals with buttons",
        ]
    )


def _action_id(value: str) -> int | None:
    raw = value.split(":", 1)[1] if ":" in value else value
    try:
        return int(raw)
    except ValueError:
        return None
