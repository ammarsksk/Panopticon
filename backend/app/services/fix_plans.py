from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app import models
from app.services.oauth import gitlab_client_for_workspace


SAFE_FIX_TYPES = {
    "pipeline_timeout",
    "test_scaffold",
    "deployment_healthcheck",
    "rollback_runbook",
    "ci_retry_guidance",
}
TERMINAL_STATUSES = {"rejected", "mr_opened", "dry_run_mr_ready"}


class FixPlanService:
    def __init__(self, db: Session, workspace_id: int | None = None) -> None:
        self.db = db
        self.workspace_id = workspace_id

    def create(
        self,
        *,
        project_id: int | None = None,
        project_path: str = "",
        source_type: str = "",
        source_id: str = "",
        problem_statement: str = "",
        fix_type: str = "",
    ) -> models.FixPlan:
        project = self._resolve_project(project_id=project_id, project_path=project_path)
        source = self._resolve_source(source_type, source_id)
        if not project and source and hasattr(source, "project_path"):
            project = self._resolve_project(project_id=None, project_path=source.project_path)
        if not project:
            raise LookupError("Project is required for a fix plan")

        selected_fix_type = _fix_type(fix_type, source, problem_statement)
        base_branch = project.default_branch or "main"
        branch_name = _branch_name(project.project_path, selected_fix_type)
        summary = _summary(source, problem_statement)
        payload = _plan_payload(
            project=project,
            source=source,
            source_type=source_type,
            source_id=source_id,
            problem_statement=problem_statement,
            fix_type=selected_fix_type,
            branch_name=branch_name,
            base_branch=base_branch,
        )
        self._validate_plan_payload(payload, project.default_branch or "main")
        plan = models.FixPlan(
            project_id=project.id,
            workspace_id=self.workspace_id,
            project_path=project.project_path,
            source_type=source_type or _source_type_for(source),
            source_id=source_id,
            title=payload["title"],
            summary=summary,
            status="draft",
            requires_approval=True,
            fix_type=selected_fix_type,
            base_branch=base_branch,
            branch_name=branch_name,
            merge_request_iid="",
            merge_request_url="",
            plan_payload=payload,
            last_result={},
            error="",
        )
        self.db.add(plan)
        self.db.commit()
        self.db.refresh(plan)
        return plan

    def list(self, *, limit: int = 50) -> list[models.FixPlan]:
        stmt = select(models.FixPlan)
        if self.workspace_id is not None:
            stmt = stmt.where(models.FixPlan.workspace_id == self.workspace_id)
        return self.db.scalars(stmt.order_by(desc(models.FixPlan.created_at)).limit(limit)).all()

    def get(self, plan_id: int) -> models.FixPlan:
        plan = self.db.get(models.FixPlan, plan_id)
        if not plan or (self.workspace_id is not None and plan.workspace_id != self.workspace_id):
            raise LookupError("Fix plan not found")
        return plan

    def approvals(self, plan_id: int) -> list[models.FixPlanApproval]:
        stmt = select(models.FixPlanApproval).where(models.FixPlanApproval.fix_plan_id == plan_id)
        if self.workspace_id is not None:
            stmt = stmt.where(models.FixPlanApproval.workspace_id == self.workspace_id)
        return self.db.scalars(stmt.order_by(desc(models.FixPlanApproval.created_at))).all()

    def approve(self, plan_id: int, *, actor: str = "local_user", reason: str = "") -> models.FixPlan:
        plan = self.get(plan_id)
        if plan.status in TERMINAL_STATUSES:
            raise ValueError(f"Fix plan cannot be approved from status {plan.status}")
        self._validate_plan_payload(plan.plan_payload, plan.base_branch)
        plan.status = "approved"
        plan.updated_at = _now()
        self._record_decision(plan, decision="approved", actor=actor, reason=reason)
        self.db.commit()
        return plan

    def reject(self, plan_id: int, *, actor: str = "local_user", reason: str = "") -> models.FixPlan:
        plan = self.get(plan_id)
        if plan.status in {"mr_opened", "dry_run_mr_ready"}:
            raise ValueError(f"Fix plan cannot be rejected from status {plan.status}")
        plan.status = "rejected"
        plan.updated_at = _now()
        self._record_decision(plan, decision="rejected", actor=actor, reason=reason)
        self.db.commit()
        return plan

    def create_branch(self, plan_id: int) -> models.FixPlan:
        plan = self.get(plan_id)
        if plan.status != "approved":
            raise PermissionError("Fix plan must be approved before creating a branch")
        self._validate_plan_payload(plan.plan_payload, plan.base_branch)

        client = gitlab_client_for_workspace(self.db, self.workspace_id)
        branch_result = client.create_branch(plan.project_path, plan.branch_name, plan.base_branch)
        commit_result = client.create_commit(
            plan.project_path,
            plan.branch_name,
            f"Add Panopticon fix plan: {plan.title}",
            _commit_actions(plan.plan_payload),
        )
        dry_run = branch_result.get("status") == "dry_run" or commit_result.get("status") == "dry_run"
        plan.status = "dry_run_branch_ready" if dry_run else "branch_created"
        plan.last_result = {"branch": branch_result, "commit": commit_result}
        plan.error = ""
        plan.updated_at = _now()
        self.db.commit()
        return plan

    def open_merge_request(self, plan_id: int) -> models.FixPlan:
        plan = self.get(plan_id)
        if plan.status not in {"branch_created", "dry_run_branch_ready"}:
            raise PermissionError("Fix plan branch must be prepared before opening a merge request")
        self._validate_plan_payload(plan.plan_payload, plan.base_branch)

        result = gitlab_client_for_workspace(self.db, self.workspace_id).create_merge_request(
            plan.project_path,
            plan.branch_name,
            plan.base_branch,
            plan.title,
            _mr_description(plan),
        )
        plan.merge_request_iid = str(result.get("iid") or result.get("id") or "")
        plan.merge_request_url = str(result.get("web_url") or "")
        plan.status = "dry_run_mr_ready" if result.get("status") == "dry_run" else "mr_opened"
        plan.last_result = {**(plan.last_result or {}), "merge_request": result}
        plan.error = ""
        plan.updated_at = _now()
        self.db.commit()
        return plan

    def _record_decision(self, plan: models.FixPlan, *, decision: str, actor: str, reason: str) -> models.FixPlanApproval:
        approval = models.FixPlanApproval(
            fix_plan_id=plan.id,
            workspace_id=plan.workspace_id or self.workspace_id,
            decision=decision,
            actor=actor or "local_user",
            reason=reason,
        )
        self.db.add(approval)
        self.db.flush()
        return approval

    def _resolve_project(self, *, project_id: int | None, project_path: str) -> models.GitLabProject | None:
        if project_id:
            project = self.db.get(models.GitLabProject, project_id)
            if not project or (self.workspace_id is not None and project.workspace_id != self.workspace_id):
                raise LookupError("Project not found")
            return project
        if project_path:
            stmt = select(models.GitLabProject).where(models.GitLabProject.project_path == project_path)
            if self.workspace_id is not None:
                stmt = stmt.where(models.GitLabProject.workspace_id == self.workspace_id)
            return self.db.scalar(stmt)
        return None

    def _resolve_source(self, source_type: str, source_id: str):
        if not source_type or not source_id:
            return None
        model = {
            "risk": models.RiskAssessment,
            "pipeline": models.PipelineInsight,
            "incident": models.IncidentRecord,
            "recommendation": models.Recommendation,
        }.get(source_type)
        if not model:
            return None
        try:
            record = self.db.get(model, int(source_id))
            if record and self.workspace_id is not None and getattr(record, "workspace_id", None) != self.workspace_id:
                return None
            return record
        except ValueError:
            return None

    def _validate_plan_payload(self, payload: dict[str, Any], default_branch: str) -> None:
        branch = str(payload.get("branch_name") or "")
        base_branch = str(payload.get("base_branch") or "")
        if not branch:
            raise ValueError("Fix plan branch name is required")
        if branch == default_branch or branch in {"main", "master"} and branch == base_branch:
            raise ValueError("Fix plan cannot write to the default branch")
        files = payload.get("files") or []
        if not files:
            raise ValueError("Fix plan must include at least one file change")
        for file_change in files:
            path = str(file_change.get("path") or "")
            action = str(file_change.get("commit_action") or "create")
            content = str(file_change.get("content") or "")
            _validate_safe_path(path)
            if action not in {"create", "update"}:
                raise ValueError(f"Unsupported commit action for {path}: {action}")
            if not content.strip():
                raise ValueError(f"File change for {path} has no content")


def _plan_payload(
    *,
    project: models.GitLabProject,
    source,
    source_type: str,
    source_id: str,
    problem_statement: str,
    fix_type: str,
    branch_name: str,
    base_branch: str,
) -> dict[str, Any]:
    title = _title(fix_type, project.project_path)
    evidence = _evidence(source)
    actions = _next_actions(source, fix_type)
    slug = _slug(f"{fix_type}-{source_type or 'manual'}-{source_id or project.id}")
    runbook_path = f"docs/panopticon/{slug}.md"
    guidance_path = f".gitlab/merge_request_templates/panopticon-{slug}.md"
    return {
        "title": title,
        "project_path": project.project_path,
        "source": {"type": source_type or _source_type_for(source), "id": source_id},
        "problem_statement": problem_statement or _summary(source, ""),
        "fix_type": fix_type,
        "base_branch": base_branch,
        "branch_name": branch_name,
        "safety": {
            "approval_required": True,
            "default_branch_write": False,
            "auto_merge": False,
            "destructive_changes": False,
        },
        "files": [
            {
                "path": runbook_path,
                "commit_action": "create",
                "purpose": "Store the investigation, validation steps, and rollback notes beside the project.",
                "content": _runbook_content(project, fix_type, evidence, actions),
            },
            {
                "path": guidance_path,
                "commit_action": "create",
                "purpose": "Give reviewers a ready checklist for this class of operational fix.",
                "content": _mr_template_content(project, fix_type, evidence, actions),
            },
        ],
        "manual_patch_suggestions": _manual_patch_suggestions(fix_type),
        "review_checklist": [
            "Confirm the proposed files do not expose secrets or environment values.",
            "Run the impacted test or CI job before merging.",
            "Verify rollback instructions match the deployed service.",
            "Keep the merge request unmerged until the service owner approves it.",
        ],
    }


def _commit_actions(payload: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "action": str(file_change.get("commit_action") or "create"),
            "file_path": str(file_change["path"]),
            "content": str(file_change["content"]),
        }
        for file_change in payload.get("files", [])
    ]


def _mr_description(plan: models.FixPlan) -> str:
    payload = plan.plan_payload or {}
    files = payload.get("files") or []
    checklist = payload.get("review_checklist") or []
    lines = [
        "## Panopticon fix plan",
        "",
        plan.summary,
        "",
        "## Planned files",
    ]
    for file_change in files:
        lines.append(f"- `{file_change.get('path')}`: {file_change.get('purpose')}")
    lines.extend(["", "## Safety checklist"])
    for item in checklist:
        lines.append(f"- [ ] {item}")
    lines.extend(["", "_Generated by Panopticon. Review and test before merging._"])
    return "\n".join(lines)


def _runbook_content(project: models.GitLabProject, fix_type: str, evidence: list[str], actions: list[str]) -> str:
    return "\n".join(
        [
            f"# Panopticon Remediation Plan: {project.project_path}",
            "",
            f"Fix type: `{fix_type}`",
            "",
            "## Evidence",
            *(f"- {item}" for item in (evidence or ["No stored evidence was available."])),
            "",
            "## Recommended Actions",
            *(f"- {item}" for item in (actions or ["Review the failing pipeline, affected files, and service owner notes."])),
            "",
            "## Validation",
            "- Run the failed CI job or equivalent local test.",
            "- Confirm deployment health checks pass after the change.",
            "- Ask the service owner to review the merge request before merge.",
            "",
            "## Rollback",
            "- Revert the merge request if the change worsens pipeline or deployment health.",
            "- Restore the previous deployment artifact or GitLab pipeline configuration.",
            "",
        ]
    )


def _mr_template_content(project: models.GitLabProject, fix_type: str, evidence: list[str], actions: list[str]) -> str:
    return "\n".join(
        [
            f"# Panopticon Review Checklist for {project.project_path}",
            "",
            f"Fix type: `{fix_type}`",
            "",
            "## Reviewer Checks",
            "- [ ] The change is scoped to the failing service or pipeline.",
            "- [ ] The service owner agrees with the remediation.",
            "- [ ] CI or a targeted validation command has passed.",
            "- [ ] Rollback instructions are clear.",
            "",
            "## Evidence Summary",
            *(f"- {item}" for item in evidence[:6]),
            "",
            "## Next Actions",
            *(f"- {item}" for item in actions[:6]),
            "",
        ]
    )


def _manual_patch_suggestions(fix_type: str) -> list[dict[str, str]]:
    if fix_type in {"pipeline_timeout", "ci_retry_guidance"}:
        return [
            {
                "path": ".gitlab-ci.yml",
                "reason": "Existing CI files should be patched only after reading the live file content.",
                "suggestion": "Add a bounded timeout and retry policy only to the failing job, then validate with a pipeline run.",
            }
        ]
    if fix_type == "test_scaffold":
        return [
            {
                "path": "tests/",
                "reason": "The correct test framework depends on the repository language.",
                "suggestion": "Add a focused regression test around the changed service path before deployment.",
            }
        ]
    if fix_type == "deployment_healthcheck":
        return [
            {
                "path": "deploy/",
                "reason": "Deployment manifests differ by service.",
                "suggestion": "Add or tighten readiness probes and post-deploy smoke checks for the changed service.",
            }
        ]
    return []


def _validate_safe_path(path: str) -> None:
    lowered = path.lower().replace("\\", "/")
    if not path or path.startswith("/") or path.startswith("\\"):
        raise ValueError("Absolute file paths are not allowed")
    if ".." in lowered.split("/"):
        raise ValueError("Parent directory traversal is not allowed")
    blocked = [".env", "secret", "private-key", "credentials", ".git/"]
    if any(part in lowered for part in blocked):
        raise ValueError(f"Unsafe file path is not allowed: {path}")


def _fix_type(requested: str, source, problem_statement: str) -> str:
    if requested in SAFE_FIX_TYPES:
        return requested
    text = f"{problem_statement} {_summary(source, '')}".lower()
    if "timeout" in text or "timed out" in text:
        return "pipeline_timeout"
    if "test" in text or "coverage" in text:
        return "test_scaffold"
    if "deployment" in text or "readiness" in text or "health" in text:
        return "deployment_healthcheck"
    if "rollback" in text or "incident" in text:
        return "rollback_runbook"
    return "ci_retry_guidance"


def _title(fix_type: str, project_path: str) -> str:
    labels = {
        "pipeline_timeout": "Stabilize failing pipeline timeout",
        "test_scaffold": "Add regression test scaffold",
        "deployment_healthcheck": "Improve deployment health validation",
        "rollback_runbook": "Document rollback and incident response",
        "ci_retry_guidance": "Document CI retry and failure guidance",
    }
    return f"{labels.get(fix_type, 'Operational fix')} for {project_path}"


def _summary(source, problem_statement: str) -> str:
    if problem_statement:
        return problem_statement.strip()
    if isinstance(source, models.RiskAssessment):
        return source.summary
    if isinstance(source, models.PipelineInsight):
        return f"Pipeline {source.pipeline_id} is {source.status}: {source.likely_cause}"
    if isinstance(source, models.IncidentRecord):
        return f"{source.title}: {source.probable_root_cause}"
    if isinstance(source, models.Recommendation):
        return source.message.split("Vertex Gemini analysis:", 1)[0].strip()
    return "Prepare a safe, reviewable operational remediation."


def _evidence(source) -> list[str]:
    if isinstance(source, models.RiskAssessment):
        return source.reasons
    if isinstance(source, models.PipelineInsight):
        return source.evidence
    if isinstance(source, models.IncidentRecord):
        return [str(item.get("event", "")) for item in source.timeline if isinstance(item, dict)]
    if isinstance(source, models.Recommendation):
        return [source.message.split("\n", 1)[0]]
    return []


def _next_actions(source, fix_type: str) -> list[str]:
    if isinstance(source, (models.RiskAssessment, models.PipelineInsight, models.IncidentRecord)):
        return source.recommendations
    if fix_type == "pipeline_timeout":
        return ["Inspect the failed job trace.", "Add a bounded retry or timeout fix only to the failing job."]
    return ["Review the evidence.", "Validate the generated branch before opening the merge request."]


def _source_type_for(source) -> str:
    if isinstance(source, models.RiskAssessment):
        return "risk"
    if isinstance(source, models.PipelineInsight):
        return "pipeline"
    if isinstance(source, models.IncidentRecord):
        return "incident"
    if isinstance(source, models.Recommendation):
        return "recommendation"
    return "manual"


def _branch_name(project_path: str, fix_type: str) -> str:
    return f"panopticon/{_slug(project_path)}-{_slug(fix_type)}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower()).strip("-")
    return slug[:80] or "fix"


def _now() -> datetime:
    return datetime.now(timezone.utc)
