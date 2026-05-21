import json
import re
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app import models
from app.services.agent_actions import AgentActionService
from app.services.fix_plans import FixPlanService
from app.services.metrics import MetricsService
from app.services.observability import ObservabilityService


class AgentToolService:
    """Tool boundary used by chat and the MCP-compatible endpoint."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            _tool(
                "search_projects",
                "Search synced GitLab projects by path, namespace, or name.",
                {"query": "string", "limit": "integer"},
            ),
            _tool(
                "get_project_summary",
                "Fetch a project workspace summary with MRs, pipelines, risks, incidents, recommendations, actions, and memory.",
                {"project_id": "integer", "project_path": "string", "limit": "integer"},
            ),
            _tool(
                "get_pipeline_context",
                "Fetch recent pipeline snapshots, failed jobs, and parsed pipeline insights.",
                {"project_id": "integer", "project_path": "string", "limit": "integer"},
            ),
            _tool(
                "get_risk_context",
                "Fetch recent deployment risk assessments and related recommendations.",
                {"project_id": "integer", "project_path": "string", "limit": "integer"},
            ),
            _tool(
                "get_action_context",
                "Fetch recent proposed or executed agent actions.",
                {"project_id": "integer", "project_path": "string", "limit": "integer"},
            ),
            _tool(
                "get_chat_context",
                "Fetch the same broad, ranked operational context used by Panopticon chat.",
                {"project_id": "integer", "project_path": "string", "limit": "integer"},
            ),
            _tool(
                "get_priority_context",
                "Fetch cross-project risks, failures, incidents, and pending approvals for prioritization questions.",
                {"limit": "integer"},
            ),
            _tool(
                "prepare_actions",
                "Create approval-gated action proposals from current recommendations. This never executes live actions.",
                {"project_id": "integer", "project_path": "string", "limit": "integer"},
            ),
            _tool(
                "create_fix_plan",
                "Create a safe, approval-gated code-change plan for a project. This never writes to GitLab.",
                {
                    "project_id": "integer",
                    "project_path": "string",
                    "source_type": "string",
                    "source_id": "string",
                    "problem_statement": "string",
                    "fix_type": "string",
                },
            ),
            _tool(
                "get_fix_plans",
                "Fetch recent safe code-change fix plans.",
                {"project_id": "integer", "project_path": "string", "limit": "integer"},
            ),
            _tool(
                "get_observability_context",
                "Fetch recent observability alerts and GitLab-correlated incident timelines.",
                {"project_id": "integer", "project_path": "string", "limit": "integer"},
            ),
            _tool(
                "ingest_observability_event",
                "Ingest one generic observability alert and correlate it with GitLab records.",
                {
                    "provider": "string",
                    "project_path": "string",
                    "service_name": "string",
                    "severity": "string",
                    "signal_type": "string",
                    "title": "string",
                    "message": "string",
                },
            ),
            _tool(
                "get_metrics_context",
                "Fetch organization and project engineering health metrics.",
                {"limit": "integer"},
            ),
            _tool(
                "refresh_metric_snapshots",
                "Create or update today's derived engineering metric snapshots.",
                {},
            ),
        ]

    def list_mcp_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool["name"],
                "description": tool["description"],
                "inputSchema": {
                    "type": "object",
                    "properties": {key: _json_schema_type(value) for key, value in tool["input_schema"].items()},
                    "additionalProperties": False,
                },
            }
            for tool in self.list_tools()
        ]

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        args = arguments or {}
        limit = _limit(args.get("limit"))
        project = self._resolve_project(args)

        if name == "search_projects":
            return {"projects": [_project(project) for project in self._search_projects(str(args.get("query") or ""), limit)]}
        if name == "get_project_summary":
            return self.project_summary(project=project, limit=limit)
        if name == "get_pipeline_context":
            return self.pipeline_context(project=project, limit=limit)
        if name == "get_risk_context":
            return self.risk_context(project=project, limit=limit)
        if name == "get_action_context":
            return self.action_context(project=project, limit=limit)
        if name == "get_chat_context":
            return _serialize_context(self.chat_context(project, limit=limit))
        if name == "get_priority_context":
            return self.priority_context(limit=limit)
        if name == "prepare_actions":
            return self.prepare_actions(project=project, limit=limit)
        if name == "create_fix_plan":
            plan = FixPlanService(self.db).create(
                project_id=project.id if project else None,
                project_path=str(args.get("project_path") or ""),
                source_type=str(args.get("source_type") or ""),
                source_id=str(args.get("source_id") or ""),
                problem_statement=str(args.get("problem_statement") or ""),
                fix_type=str(args.get("fix_type") or ""),
            )
            return {"fix_plan": _record("fix_plans", plan)}
        if name == "get_fix_plans":
            return self.fix_plan_context(project=project, limit=limit)
        if name == "get_observability_context":
            return self.observability_context(project=project, limit=limit)
        if name == "ingest_observability_event":
            raw = {key: value for key, value in args.items() if key != "provider"}
            if project and not raw.get("project_path"):
                raw["project_path"] = project.project_path
            event, correlation, deduplicated = ObservabilityService(self.db).ingest(raw, provider=str(args.get("provider") or "generic"))
            return {
                "event": _record("observability_events", event),
                "correlation": _record("incident_correlations", correlation) if correlation else None,
                "deduplicated": deduplicated,
            }
        if name == "get_metrics_context":
            service = MetricsService(self.db)
            return {"summary": service.organization_summary(), "projects": service.project_health(limit=limit)}
        if name == "refresh_metric_snapshots":
            snapshots = MetricsService(self.db).refresh_snapshots()
            return {"snapshots": [_record("engineering_metric_snapshots", item) for item in snapshots]}
        raise LookupError(f"Unknown tool: {name}")

    def chat_context(self, project: models.GitLabProject | None, *, limit: int = 12) -> dict[str, Any]:
        project_path = project.project_path if project else None
        return {
            "project": project,
            "merge_requests": self._records(models.MergeRequestSnapshot, project_path, desc(models.MergeRequestSnapshot.updated_at_gitlab), limit),
            "pipelines": self._records(models.PipelineSnapshot, project_path, desc(models.PipelineSnapshot.updated_at_gitlab), limit),
            "pipeline_insights": self._records(models.PipelineInsight, project_path, desc(models.PipelineInsight.created_at), limit),
            "failed_jobs": self._records(models.JobSnapshot, project_path, desc(models.JobSnapshot.synced_at), limit, models.JobSnapshot.status == "failed"),
            "risks": self._records(models.RiskAssessment, project_path, desc(models.RiskAssessment.score), limit),
            "incidents": self._records(models.IncidentRecord, project_path, desc(models.IncidentRecord.created_at), limit),
            "recommendations": self._records(models.Recommendation, project_path, desc(models.Recommendation.created_at), limit),
            "actions": self._records(models.AgentAction, project_path, desc(models.AgentAction.updated_at), limit),
            "fix_plans": self._records(models.FixPlan, project_path, desc(models.FixPlan.updated_at), limit),
            "observability_events": self._records(models.ObservabilityEvent, project_path, desc(models.ObservabilityEvent.observed_at), limit),
            "incident_correlations": self._records(models.IncidentCorrelation, project_path, desc(models.IncidentCorrelation.updated_at), limit),
            "metric_snapshots": self._records(models.EngineeringMetricSnapshot, project_path, desc(models.EngineeringMetricSnapshot.snapshot_date), limit),
            "memory": self._records(models.MemoryRecord, project_path, desc(models.MemoryRecord.created_at), limit),
        }

    def infer_project(self, message: str) -> models.GitLabProject | None:
        text = message.lower()
        projects = self.db.scalars(select(models.GitLabProject).order_by(desc(models.GitLabProject.last_activity_at)).limit(200)).all()
        matches: list[tuple[int, models.GitLabProject]] = []
        for project in projects:
            tokens = {project.project_path.lower(), project.name.lower(), project.namespace.lower()}
            tokens.update(part for part in re.split(r"[/_\-\s]+", project.project_path.lower()) if part)
            tokens.update(part for part in re.split(r"[/_\-\s]+", project.name.lower()) if part)
            tokens.add(project.project_path.lower().replace("-", " "))
            tokens.add(project.name.lower().replace("-", " "))
            score = 0
            for token in tokens:
                if token and token in text:
                    score += len(token)
            if score:
                matches.append((score, project))
        if not matches:
            return None
        matches.sort(key=lambda item: item[0], reverse=True)
        return matches[0][1]

    def project_summary(self, *, project: models.GitLabProject | None, limit: int = 10) -> dict[str, Any]:
        project_path = project.project_path if project else None
        return {
            "project": _project(project) if project else None,
            "merge_requests": [_record("merge_requests", item) for item in self._records(models.MergeRequestSnapshot, project_path, desc(models.MergeRequestSnapshot.updated_at_gitlab), limit)],
            "pipelines": [_record("pipelines", item) for item in self._records(models.PipelineSnapshot, project_path, desc(models.PipelineSnapshot.updated_at_gitlab), limit)],
            "pipeline_insights": [_record("pipeline_insights", item) for item in self._records(models.PipelineInsight, project_path, desc(models.PipelineInsight.created_at), limit)],
            "failed_jobs": [_record("failed_jobs", item) for item in self._records(models.JobSnapshot, project_path, desc(models.JobSnapshot.synced_at), limit, models.JobSnapshot.status == "failed")],
            "risks": [_record("risks", item) for item in self._records(models.RiskAssessment, project_path, desc(models.RiskAssessment.created_at), limit)],
            "incidents": [_record("incidents", item) for item in self._records(models.IncidentRecord, project_path, desc(models.IncidentRecord.created_at), limit)],
            "recommendations": [_record("recommendations", item) for item in self._records(models.Recommendation, project_path, desc(models.Recommendation.created_at), limit)],
            "actions": [_record("actions", item) for item in self._records(models.AgentAction, project_path, desc(models.AgentAction.updated_at), limit)],
            "fix_plans": [_record("fix_plans", item) for item in self._records(models.FixPlan, project_path, desc(models.FixPlan.updated_at), limit)],
            "observability_events": [_record("observability_events", item) for item in self._records(models.ObservabilityEvent, project_path, desc(models.ObservabilityEvent.observed_at), limit)],
            "incident_correlations": [_record("incident_correlations", item) for item in self._records(models.IncidentCorrelation, project_path, desc(models.IncidentCorrelation.updated_at), limit)],
            "metric_snapshots": [_record("engineering_metric_snapshots", item) for item in self._records(models.EngineeringMetricSnapshot, project_path, desc(models.EngineeringMetricSnapshot.snapshot_date), limit)],
            "memory": [_record("memory", item) for item in self._records(models.MemoryRecord, project_path, desc(models.MemoryRecord.created_at), limit)],
        }

    def pipeline_context(self, *, project: models.GitLabProject | None, limit: int = 10) -> dict[str, Any]:
        project_path = project.project_path if project else None
        return {
            "project": _project(project) if project else None,
            "pipeline_insights": [_record("pipeline_insights", item) for item in self._records(models.PipelineInsight, project_path, desc(models.PipelineInsight.created_at), limit)],
            "failed_jobs": [_record("failed_jobs", item) for item in self._records(models.JobSnapshot, project_path, desc(models.JobSnapshot.synced_at), limit, models.JobSnapshot.status == "failed")],
            "pipelines": [_record("pipelines", item) for item in self._records(models.PipelineSnapshot, project_path, desc(models.PipelineSnapshot.updated_at_gitlab), limit)],
        }

    def risk_context(self, *, project: models.GitLabProject | None, limit: int = 10) -> dict[str, Any]:
        project_path = project.project_path if project else None
        return {
            "project": _project(project) if project else None,
            "risks": [_record("risks", item) for item in self._records(models.RiskAssessment, project_path, desc(models.RiskAssessment.created_at), limit)],
            "recommendations": [_record("recommendations", item) for item in self._records(models.Recommendation, project_path, desc(models.Recommendation.created_at), limit)],
        }

    def action_context(self, *, project: models.GitLabProject | None, limit: int = 10) -> dict[str, Any]:
        project_path = project.project_path if project else None
        return {
            "project": _project(project) if project else None,
            "actions": [_record("actions", item) for item in self._records(models.AgentAction, project_path, desc(models.AgentAction.updated_at), limit)],
            "recommendations": [_record("recommendations", item) for item in self._records(models.Recommendation, project_path, desc(models.Recommendation.created_at), limit)],
        }

    def fix_plan_context(self, *, project: models.GitLabProject | None, limit: int = 10) -> dict[str, Any]:
        project_path = project.project_path if project else None
        return {
            "project": _project(project) if project else None,
            "fix_plans": [_record("fix_plans", item) for item in self._records(models.FixPlan, project_path, desc(models.FixPlan.updated_at), limit)],
        }

    def observability_context(self, *, project: models.GitLabProject | None, limit: int = 10) -> dict[str, Any]:
        project_path = project.project_path if project else None
        return {
            "project": _project(project) if project else None,
            "observability_events": [_record("observability_events", item) for item in self._records(models.ObservabilityEvent, project_path, desc(models.ObservabilityEvent.observed_at), limit)],
            "incident_correlations": [_record("incident_correlations", item) for item in self._records(models.IncidentCorrelation, project_path, desc(models.IncidentCorrelation.updated_at), limit)],
        }

    def priority_context(self, *, limit: int = 10) -> dict[str, Any]:
        risks = self.db.scalars(select(models.RiskAssessment).order_by(desc(models.RiskAssessment.score), desc(models.RiskAssessment.created_at)).limit(limit)).all()
        failures = self.db.scalars(select(models.PipelineInsight).where(models.PipelineInsight.status == "failed").order_by(desc(models.PipelineInsight.created_at)).limit(limit)).all()
        jobs = self.db.scalars(select(models.JobSnapshot).where(models.JobSnapshot.status == "failed").order_by(desc(models.JobSnapshot.synced_at)).limit(limit)).all()
        incidents = self.db.scalars(select(models.IncidentRecord).where(models.IncidentRecord.status == "open").order_by(desc(models.IncidentRecord.created_at)).limit(limit)).all()
        actions = self.db.scalars(select(models.AgentAction).where(models.AgentAction.status == "pending_approval").order_by(desc(models.AgentAction.updated_at)).limit(limit)).all()
        return {
            "risks": [_record("risks", item) for item in risks],
            "pipeline_insights": [_record("pipeline_insights", item) for item in failures],
            "failed_jobs": [_record("failed_jobs", item) for item in jobs],
            "incidents": [_record("incidents", item) for item in incidents],
            "actions": [_record("actions", item) for item in actions],
        }

    def prepare_actions(self, *, project: models.GitLabProject | None, limit: int = 10) -> dict[str, Any]:
        actions = self.prepare_action_records(project=project, limit=limit)
        return {"actions": [_record("actions", action) for action in actions]}

    def prepare_action_records(self, *, project: models.GitLabProject | None, limit: int = 10) -> list[models.AgentAction]:
        stmt = select(models.Recommendation).where(models.Recommendation.channel.in_(["gitlab_comment", "slack"]))
        if project:
            stmt = stmt.where(models.Recommendation.project_path == project.project_path)
        recommendations = self.db.scalars(stmt.order_by(desc(models.Recommendation.created_at)).limit(limit)).all()
        service = AgentActionService(self.db)
        actions = [service.propose(recommendation) for recommendation in recommendations]
        self.db.flush()
        return actions

    def _resolve_project(self, args: dict[str, Any]) -> models.GitLabProject | None:
        project_id = args.get("project_id")
        if project_id:
            project = self.db.get(models.GitLabProject, int(project_id))
            if not project:
                raise LookupError(f"Project not found: {project_id}")
            return project
        project_path = str(args.get("project_path") or "").strip()
        if project_path:
            project = self.db.scalar(select(models.GitLabProject).where(models.GitLabProject.project_path == project_path))
            if not project:
                raise LookupError(f"Project not found: {project_path}")
            return project
        return None

    def _search_projects(self, query: str, limit: int) -> list[models.GitLabProject]:
        stmt = select(models.GitLabProject).order_by(desc(models.GitLabProject.last_activity_at)).limit(limit)
        if query:
            like = f"%{query.lower()}%"
            stmt = (
                select(models.GitLabProject)
                .where(
                    models.GitLabProject.project_path.ilike(like)
                    | models.GitLabProject.name.ilike(like)
                    | models.GitLabProject.namespace.ilike(like)
                )
                .order_by(desc(models.GitLabProject.last_activity_at))
                .limit(limit)
            )
        return self.db.scalars(stmt).all()

    def _records(self, model, project_path: str | None, order_by, limit: int, *filters) -> list[Any]:
        stmt = select(model)
        if project_path and hasattr(model, "project_path"):
            stmt = stmt.where(model.project_path == project_path)
        for filter_expr in filters:
            stmt = stmt.where(filter_expr)
        return self.db.scalars(stmt.order_by(order_by).limit(limit)).all()


def mcp_text_result(result: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(result, default=str)}], "isError": False}


def _tool(name: str, description: str, input_schema: dict[str, str]) -> dict[str, Any]:
    return {"name": name, "description": description, "input_schema": input_schema}


def _json_schema_type(value: str) -> dict[str, str]:
    if value == "integer":
        return {"type": "integer"}
    return {"type": "string"}


def _limit(value: Any) -> int:
    if value is None or value == "":
        return 10
    return max(1, min(int(value), 50))


def _project(project: models.GitLabProject) -> dict[str, Any]:
    return {
        "id": project.id,
        "gitlab_project_id": project.gitlab_project_id,
        "project_path": project.project_path,
        "name": project.name,
        "namespace": project.namespace,
        "web_url": project.web_url,
        "default_branch": project.default_branch,
        "visibility": project.visibility,
        "open_merge_requests_count": project.open_merge_requests_count,
        "failed_pipelines_count": project.failed_pipelines_count,
        "latest_pipeline_id": project.latest_pipeline_id,
        "latest_pipeline_status": project.latest_pipeline_status,
        "synced_at": project.synced_at,
    }


def _record(kind: str, record: Any) -> dict[str, Any]:
    data = {"type": kind, "id": record.id}
    for field in [
        "project_path",
        "merge_request_iid",
        "title",
        "state",
        "source_branch",
        "target_branch",
        "pipeline_id",
        "job_id",
        "name",
        "stage",
        "status",
        "failure_reason",
        "likely_cause",
        "summary",
        "score",
        "level",
        "severity",
        "probable_root_cause",
        "source_type",
        "source_id",
        "channel",
        "message",
        "action_type",
        "requires_approval",
        "fix_type",
        "base_branch",
        "branch_name",
        "merge_request_iid",
        "merge_request_url",
        "event_uid",
        "service_name",
        "environment",
        "signal_type",
        "metric_name",
        "trace_id",
        "alert_url",
        "suspected_cause",
        "confidence",
        "scope_type",
        "snapshot_date",
        "health_score",
    ]:
        if hasattr(record, field):
            data[field] = getattr(record, field)
    for json_field in [
        "reasons",
        "recommendations",
        "evidence",
        "timeline",
        "remediation",
        "payload_preview",
        "plan_payload",
        "last_result",
        "payload",
        "related_observability_event_ids",
        "related_pipeline_ids",
        "related_risk_ids",
        "related_incident_ids",
        "metrics",
    ]:
        if hasattr(record, json_field):
            data[json_field] = getattr(record, json_field)
    return data


def _serialize_context(context: dict[str, Any]) -> dict[str, Any]:
    serialized: dict[str, Any] = {}
    for key, value in context.items():
        if key == "project":
            serialized[key] = _project(value) if value else None
        elif isinstance(value, list):
            serialized[key] = [_record(key, item) for item in value]
        else:
            serialized[key] = value
    return serialized
