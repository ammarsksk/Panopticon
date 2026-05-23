from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app import models
from app.actions.dispatcher import ActionDispatcher


EXECUTABLE_CHANNELS = {"gitlab_comment", "slack"}


class AgentActionService:
    def __init__(self, db: Session, workspace_id: int | None = None) -> None:
        self.db = db
        self.workspace_id = workspace_id

    def propose_from_recommendations(self, *, limit: int = 50) -> list[models.AgentAction]:
        stmt = select(models.Recommendation).where(models.Recommendation.channel.in_(EXECUTABLE_CHANNELS))
        if self.workspace_id is not None:
            stmt = stmt.where(models.Recommendation.workspace_id == self.workspace_id)
        recommendations = self.db.scalars(stmt.order_by(desc(models.Recommendation.created_at)).limit(limit)).all()
        actions = [self.propose(recommendation) for recommendation in recommendations]
        self.db.commit()
        return actions

    def propose(self, recommendation: models.Recommendation) -> models.AgentAction:
        stmt = select(models.AgentAction).where(models.AgentAction.recommendation_id == recommendation.id)
        if self.workspace_id is not None:
            stmt = stmt.where(models.AgentAction.workspace_id == self.workspace_id)
        existing = self.db.scalar(stmt)
        if existing:
            return existing

        action_type = _action_type(recommendation)
        context = self._execution_context(recommendation)
        action = models.AgentAction(
            recommendation_id=recommendation.id,
            workspace_id=recommendation.workspace_id or self.workspace_id,
            project_path=recommendation.project_path,
            action_type=action_type,
            channel=recommendation.channel,
            title=_title(recommendation),
            summary=_summary(recommendation.message),
            status="pending_approval",
            requires_approval=True,
            payload_preview=self._payload_preview(recommendation, context),
            execution_context=context,
            last_result={},
            error="",
        )
        self.db.add(action)
        self.db.flush()
        return action

    def approve(self, action_id: int, *, actor: str = "local_user", reason: str = "") -> models.AgentAction:
        action = self.get(action_id)
        if action.status in {"rejected", "sent", "dry_run"}:
            raise ValueError(f"Action cannot be approved from status {action.status}")
        action.status = "approved"
        action.updated_at = _now()
        self._record_decision(action, decision="approved", actor=actor, reason=reason)
        self.db.commit()
        return action

    def reject(self, action_id: int, *, actor: str = "local_user", reason: str = "") -> models.AgentAction:
        action = self.get(action_id)
        if action.status in {"sent", "dry_run"}:
            raise ValueError(f"Action cannot be rejected from status {action.status}")
        action.status = "rejected"
        action.updated_at = _now()
        self._record_decision(action, decision="rejected", actor=actor, reason=reason)
        self.db.commit()
        return action

    def execute(self, action_id: int) -> models.AgentAction:
        action = self.get(action_id)
        if action.requires_approval and action.status != "approved":
            raise PermissionError("Action must be approved before execution")
        recommendation = self.db.get(models.Recommendation, action.recommendation_id) if action.recommendation_id else None
        if not recommendation:
            raise ValueError("Recommendation no longer exists")

        action.status = "executing"
        action.updated_at = _now()
        self.db.flush()

        result = ActionDispatcher(self.db, workspace_id=self.workspace_id).dispatch(recommendation, action.execution_context)
        action.last_result = result
        action.status = str(result.get("status", "sent"))
        action.error = str(result.get("error", ""))
        action.updated_at = _now()
        self.db.commit()
        return action

    def get(self, action_id: int) -> models.AgentAction:
        action = self.db.get(models.AgentAction, action_id)
        if not action or (self.workspace_id is not None and action.workspace_id != self.workspace_id):
            raise LookupError("Action not found")
        return action

    def _record_decision(self, action: models.AgentAction, *, decision: str, actor: str, reason: str) -> models.ActionApproval:
        approval = models.ActionApproval(
            agent_action_id=action.id,
            workspace_id=action.workspace_id or self.workspace_id,
            decision=decision,
            actor=actor or "local_user",
            reason=reason,
        )
        self.db.add(approval)
        self.db.flush()
        return approval

    def _execution_context(self, recommendation: models.Recommendation) -> dict:
        if recommendation.channel != "gitlab_comment":
            return {}
        merge_request_iid = ""
        source_id = _safe_int(recommendation.source_id)
        if recommendation.source_type == "risk" and source_id:
            risk = self.db.get(models.RiskAssessment, source_id)
            merge_request_iid = risk.merge_request_iid if risk else ""
        return {"merge_request_iid": merge_request_iid}

    def _payload_preview(self, recommendation: models.Recommendation, context: dict) -> dict:
        if recommendation.channel == "gitlab_comment":
            merge_request_iid = context.get("merge_request_iid") or ""
            return {
                "target": f"{recommendation.project_path}!{merge_request_iid}" if merge_request_iid else recommendation.project_path,
                "body": "\n".join(
                    [
                        "### Panopticon operational intelligence",
                        "",
                        recommendation.message,
                        "",
                        "_Generated by Panopticon. Review the evidence before merging or deploying._",
                    ]
                ),
            }
        if recommendation.channel == "slack":
            return {
                "target": "slack_webhook",
                "title": _title(recommendation),
                "message": recommendation.message,
                "fields": {
                    "Project": recommendation.project_path,
                    "Source": recommendation.source_type,
                },
            }
        return {"message": recommendation.message}


def _action_type(recommendation: models.Recommendation) -> str:
    if recommendation.channel == "gitlab_comment":
        return "gitlab_comment"
    if recommendation.channel == "slack":
        return "slack_alert"
    return "dashboard_note"


def _title(recommendation: models.Recommendation) -> str:
    if recommendation.source_type == "pipeline":
        return "Pipeline failure detected"
    if recommendation.source_type == "incident":
        return "Incident intelligence generated"
    if recommendation.source_type == "risk":
        return "Deployment risk detected"
    return "Operational recommendation"


def _summary(message: str) -> str:
    return message.split("Vertex Gemini analysis:", 1)[0].strip()


def _safe_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _now():
    return datetime.now(timezone.utc)
