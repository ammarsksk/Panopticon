from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app import models


ACTION_DONE = {"sent", "dry_run", "dry_run_mr_ready", "mr_opened"}
ACTION_PENDING = {"pending_approval", "approved", "draft", "dry_run_branch_ready", "branch_created"}
SEVERE = {"critical", "high"}


class MetricsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def organization_summary(self) -> dict[str, Any]:
        projects = self.project_health(limit=500)
        total_pipelines = sum(item["pipeline_count"] for item in projects)
        failed_pipelines = sum(item["failed_pipeline_count"] for item in projects)
        active_risks = sum(item["active_risks"] for item in projects)
        open_incidents = sum(item["open_incidents"] for item in projects)
        observability_alerts = sum(item["observability_alerts"] for item in projects)
        pending_actions = sum(item["pending_actions"] for item in projects)
        completed_actions = sum(item["completed_actions"] for item in projects)
        fix_plans = sum(item["fix_plans"] for item in projects)
        average_health = _round(sum(item["health_score"] for item in projects) / len(projects)) if projects else 100.0
        failed_rate = _rate(failed_pipelines, total_pipelines)
        sorted_by_health = sorted(projects, key=lambda item: item["health_score"])
        return {
            "generated_at": _now(),
            "project_count": len(projects),
            "average_health_score": average_health,
            "health_level": _health_level(average_health),
            "failed_pipeline_rate": failed_rate,
            "total_pipelines": total_pipelines,
            "failed_pipelines": failed_pipelines,
            "active_risks": active_risks,
            "open_incidents": open_incidents,
            "observability_alerts": observability_alerts,
            "pending_actions": pending_actions,
            "completed_actions": completed_actions,
            "fix_plans": fix_plans,
            "projects_at_risk": len([item for item in projects if item["health_level"] in {"at_risk", "critical"}]),
            "healthiest_projects": sorted(projects, key=lambda item: item["health_score"], reverse=True)[:5],
            "riskiest_projects": sorted_by_health[:8],
        }

    def project_health(self, *, limit: int = 100) -> list[dict[str, Any]]:
        projects = self.db.scalars(select(models.GitLabProject).order_by(desc(models.GitLabProject.last_activity_at)).limit(limit)).all()
        return sorted([self._project_health(project) for project in projects], key=lambda item: item["health_score"])

    def refresh_snapshots(self, *, snapshot_date: date | None = None) -> list[models.EngineeringMetricSnapshot]:
        day = snapshot_date or _now().date()
        projects = self.project_health(limit=500)
        summary = self.organization_summary()
        snapshots = [self._upsert_snapshot(scope_type="organization", project_path="", snapshot_date=day, health_score=summary["average_health_score"], metrics=summary)]
        for project in projects:
            snapshots.append(
                self._upsert_snapshot(
                    scope_type="project",
                    project_path=project["project_path"],
                    snapshot_date=day,
                    health_score=project["health_score"],
                    metrics=project,
                )
            )
        self.db.commit()
        return snapshots

    def list_snapshots(self, *, project_path: str = "", limit: int = 100) -> list[models.EngineeringMetricSnapshot]:
        stmt = select(models.EngineeringMetricSnapshot)
        if project_path:
            stmt = stmt.where(models.EngineeringMetricSnapshot.project_path == project_path)
        return self.db.scalars(stmt.order_by(desc(models.EngineeringMetricSnapshot.snapshot_date), desc(models.EngineeringMetricSnapshot.updated_at)).limit(limit)).all()

    def _project_health(self, project: models.GitLabProject) -> dict[str, Any]:
        pipelines = self._records(models.PipelineSnapshot, project.project_path, desc(models.PipelineSnapshot.updated_at_gitlab), 200)
        failed_pipelines = [item for item in pipelines if item.status == "failed"]
        pipeline_insights = self._records(models.PipelineInsight, project.project_path, desc(models.PipelineInsight.created_at), 100)
        failed_insights = [item for item in pipeline_insights if item.status == "failed"]
        risks = self._records(models.RiskAssessment, project.project_path, desc(models.RiskAssessment.created_at), 100)
        active_risks = [item for item in risks if item.score >= 70]
        incidents = self._records(models.IncidentRecord, project.project_path, desc(models.IncidentRecord.created_at), 100)
        open_incidents = [item for item in incidents if item.status == "open"]
        correlations = self._records(models.IncidentCorrelation, project.project_path, desc(models.IncidentCorrelation.updated_at), 100)
        open_correlations = [item for item in correlations if item.status == "open"]
        observability_events = self._records(models.ObservabilityEvent, project.project_path, desc(models.ObservabilityEvent.observed_at), 100)
        severe_alerts = [item for item in observability_events if item.severity in SEVERE]
        actions = self._records(models.AgentAction, project.project_path, desc(models.AgentAction.updated_at), 100)
        pending_actions = [item for item in actions if item.status in ACTION_PENDING]
        completed_actions = [item for item in actions if item.status in ACTION_DONE]
        fix_plans = self._records(models.FixPlan, project.project_path, desc(models.FixPlan.updated_at), 100)
        recommendations = self._records(models.Recommendation, project.project_path, desc(models.Recommendation.created_at), 100)

        pipeline_count = len(pipelines) or (1 if project.latest_pipeline_id else 0)
        failed_count = len(failed_pipelines) or project.failed_pipelines_count
        failed_rate = _rate(failed_count, pipeline_count)
        max_risk = max([item.score for item in risks], default=0.0)
        incident_count = len(open_incidents) + len(open_correlations)
        score = _health_score(
            failed_rate=failed_rate,
            active_risks=len(active_risks),
            max_risk=max_risk,
            open_incidents=incident_count,
            observability_alerts=len(severe_alerts),
            pending_actions=len(pending_actions),
            completed_actions=len(completed_actions),
            fix_plans=len(fix_plans),
        )
        reasons = _top_reasons(
            failed_rate=failed_rate,
            active_risks=active_risks,
            failed_insights=failed_insights,
            open_incidents=incident_count,
            severe_alerts=severe_alerts,
            pending_actions=pending_actions,
        )
        return {
            "project_id": project.id,
            "project_path": project.project_path,
            "name": project.name,
            "namespace": project.namespace,
            "health_score": score,
            "health_level": _health_level(score),
            "failed_pipeline_rate": failed_rate,
            "pipeline_count": pipeline_count,
            "failed_pipeline_count": failed_count,
            "open_merge_requests": project.open_merge_requests_count,
            "active_risks": len(active_risks),
            "max_risk_score": _round(max_risk),
            "open_incidents": incident_count,
            "observability_alerts": len(severe_alerts),
            "pending_actions": len(pending_actions),
            "completed_actions": len(completed_actions),
            "fix_plans": len(fix_plans),
            "recommendation_count": len(recommendations),
            "last_activity_at": project.last_activity_at,
            "top_reasons": reasons,
        }

    def _upsert_snapshot(self, *, scope_type: str, project_path: str, snapshot_date: date, health_score: float, metrics: dict[str, Any]) -> models.EngineeringMetricSnapshot:
        snapshot = self.db.scalar(
            select(models.EngineeringMetricSnapshot)
            .where(models.EngineeringMetricSnapshot.scope_type == scope_type)
            .where(models.EngineeringMetricSnapshot.project_path == project_path)
            .where(models.EngineeringMetricSnapshot.snapshot_date == snapshot_date)
        )
        if not snapshot:
            snapshot = models.EngineeringMetricSnapshot(scope_type=scope_type, project_path=project_path, snapshot_date=snapshot_date)
            self.db.add(snapshot)
        snapshot.health_score = health_score
        snapshot.metrics = _jsonable(metrics)
        snapshot.updated_at = _now()
        self.db.flush()
        return snapshot

    def _records(self, model, project_path: str, order_by, limit: int):
        return self.db.scalars(select(model).where(model.project_path == project_path).order_by(order_by).limit(limit)).all()


def _health_score(
    *,
    failed_rate: float,
    active_risks: int,
    max_risk: float,
    open_incidents: int,
    observability_alerts: int,
    pending_actions: int,
    completed_actions: int,
    fix_plans: int,
) -> float:
    score = 100.0
    score -= failed_rate * 30
    score -= min(active_risks * 8, 28)
    score -= min(max_risk / 5, 20)
    score -= min(open_incidents * 11, 33)
    score -= min(observability_alerts * 7, 28)
    score -= min(pending_actions * 2, 8)
    score += min(completed_actions * 1.5, 6)
    score += min(fix_plans * 1.0, 4)
    return _round(max(0.0, min(score, 100.0)))


def _health_level(score: float) -> str:
    if score < 45:
        return "critical"
    if score < 70:
        return "at_risk"
    if score < 85:
        return "watch"
    return "healthy"


def _top_reasons(*, failed_rate: float, active_risks, failed_insights, open_incidents: int, severe_alerts, pending_actions) -> list[str]:
    reasons: list[str] = []
    if failed_rate:
        reasons.append(f"Pipeline failure rate is {_round(failed_rate * 100)}%.")
    if active_risks:
        reasons.append(f"{len(active_risks)} active high-risk delivery record(s).")
    if failed_insights:
        reasons.append(failed_insights[0].likely_cause)
    if open_incidents:
        reasons.append(f"{open_incidents} open incident or correlated production symptom(s).")
    if severe_alerts:
        reasons.append(f"{len(severe_alerts)} high-severity observability alert(s).")
    if pending_actions:
        reasons.append(f"{len(pending_actions)} pending approval action(s).")
    return reasons[:5]


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return _round(numerator / denominator)


def _round(value: float) -> float:
    return round(float(value), 2)


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _now() -> datetime:
    return datetime.now(timezone.utc)
