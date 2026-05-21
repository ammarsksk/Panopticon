import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app import models


SEVERITY_ORDER = {"info": 1, "low": 2, "warning": 3, "medium": 4, "high": 5, "critical": 6}


class ObservabilityService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def ingest(self, raw: dict[str, Any], *, provider: str = "generic") -> tuple[models.ObservabilityEvent, models.IncidentCorrelation | None, bool]:
        normalized = self._normalize(raw, provider=provider)
        existing = self.db.scalar(select(models.ObservabilityEvent).where(models.ObservabilityEvent.event_uid == normalized["event_uid"]))
        if existing:
            correlation = self._latest_correlation_for_event(existing.id)
            return existing, correlation, True

        event = models.ObservabilityEvent(**normalized)
        self.db.add(event)
        self.db.flush()
        correlation = self.correlate_event(event)
        self.db.commit()
        self.db.refresh(event)
        if correlation:
            self.db.refresh(correlation)
        return event, correlation, False

    def list_events(self, *, project_path: str = "", limit: int = 50) -> list[models.ObservabilityEvent]:
        stmt = select(models.ObservabilityEvent)
        if project_path:
            stmt = stmt.where(models.ObservabilityEvent.project_path == project_path)
        return self.db.scalars(stmt.order_by(desc(models.ObservabilityEvent.observed_at)).limit(limit)).all()

    def list_correlations(self, *, project_path: str = "", limit: int = 50) -> list[models.IncidentCorrelation]:
        stmt = select(models.IncidentCorrelation)
        if project_path:
            stmt = stmt.where(models.IncidentCorrelation.project_path == project_path)
        return self.db.scalars(stmt.order_by(desc(models.IncidentCorrelation.updated_at)).limit(limit)).all()

    def correlate_event(self, event: models.ObservabilityEvent) -> models.IncidentCorrelation:
        project_path = event.project_path or self._infer_project_path(event.service_name)
        pipelines = self._recent_pipelines(project_path)
        risks = self._recent_risks(project_path)
        incidents = self._recent_incidents(project_path)
        failed_jobs = self._recent_failed_jobs(project_path)
        related_events = self._nearby_observability_events(event, project_path)

        timeline = _timeline(event, related_events, pipelines, failed_jobs, risks, incidents)
        severity = _max_severity([event.severity, *(risk.level for risk in risks), *(incident.severity for incident in incidents)])
        suspected_cause = _suspected_cause(event, pipelines, failed_jobs, risks, incidents)
        confidence = _confidence(project_path, pipelines, failed_jobs, risks, incidents, related_events)
        recommendations = _recommendations(event, pipelines, failed_jobs, risks, incidents)
        title = f"{event.service_name or project_path or 'Service'} {event.signal_type} correlation"
        summary = _summary(event, project_path, pipelines, risks, incidents)

        correlation = models.IncidentCorrelation(
            project_path=project_path,
            title=title,
            severity=severity,
            status="open" if severity in {"critical", "high", "medium"} else "monitoring",
            summary=summary,
            suspected_cause=suspected_cause,
            confidence=confidence,
            timeline=timeline,
            related_observability_event_ids=[item.id for item in related_events],
            related_pipeline_ids=[item.pipeline_id for item in pipelines],
            related_risk_ids=[item.id for item in risks],
            related_incident_ids=[item.id for item in incidents],
            recommendations=recommendations,
        )
        self.db.add(correlation)
        self.db.flush()
        return correlation

    def _normalize(self, raw: dict[str, Any], *, provider: str) -> dict[str, Any]:
        payload = dict(raw)
        nested = _first_dict(payload, "alert", "event", "incident", "issue") or {}
        labels = _first_dict(payload, "labels", "commonLabels", "tags") or {}
        annotations = _first_dict(payload, "annotations", "commonAnnotations") or {}

        service_name = _first_value(payload, nested, labels, "service_name", "service", "app", "application", "component")
        project_path = _first_value(payload, nested, labels, "project_path", "gitlab_project", "repository", "repo")
        if not project_path:
            project_path = self._infer_project_path(service_name)

        severity = _severity(_first_value(payload, nested, labels, "severity", "level", "priority") or "info")
        signal_type = _signal_type(provider, payload, nested, labels)
        title = _first_value(payload, nested, annotations, "title", "alertname", "name", "rule", "summary") or f"{signal_type} signal"
        message = _first_value(payload, nested, annotations, "message", "description", "text", "details") or title
        observed_at = _parse_datetime(_first_value(payload, nested, "observed_at", "timestamp", "startsAt", "created_at")) or _now()
        event_uid = _first_value(payload, nested, "event_uid", "fingerprint", "id", "event_id", "incident_id")
        if not event_uid:
            event_uid = _event_uid(provider, payload)

        return {
            "provider": provider or str(payload.get("provider") or "generic"),
            "event_uid": f"{provider}:{event_uid}",
            "project_path": project_path,
            "service_name": service_name,
            "environment": _first_value(payload, nested, labels, "environment", "env", "cluster", "namespace") or "",
            "severity": severity,
            "signal_type": signal_type,
            "title": title,
            "message": message,
            "metric_name": _first_value(payload, nested, labels, "metric_name", "metric", "__name__") or "",
            "trace_id": _first_value(payload, nested, "trace_id", "trace", "traceId") or "",
            "alert_url": _first_value(payload, nested, "alert_url", "url", "permalink", "web_url", "externalURL") or "",
            "payload": payload,
            "observed_at": observed_at,
            "created_at": _now(),
        }

    def _infer_project_path(self, service_name: str) -> str:
        if not service_name:
            return ""
        token = service_name.lower().replace("_", "-")
        projects = self.db.scalars(select(models.GitLabProject).order_by(desc(models.GitLabProject.last_activity_at)).limit(200)).all()
        for project in projects:
            candidates = {
                project.project_path.lower(),
                project.name.lower(),
                project.name.lower().replace("_", "-"),
                project.project_path.lower().split("/")[-1],
            }
            if token in candidates or token in project.project_path.lower():
                return project.project_path
        return ""

    def _recent_pipelines(self, project_path: str) -> list[models.PipelineInsight]:
        if not project_path:
            return []
        return self.db.scalars(
            select(models.PipelineInsight)
            .where(models.PipelineInsight.project_path == project_path)
            .order_by(desc(models.PipelineInsight.created_at))
            .limit(5)
        ).all()

    def _recent_failed_jobs(self, project_path: str) -> list[models.JobSnapshot]:
        if not project_path:
            return []
        return self.db.scalars(
            select(models.JobSnapshot)
            .where(models.JobSnapshot.project_path == project_path)
            .where(models.JobSnapshot.status == "failed")
            .order_by(desc(models.JobSnapshot.synced_at))
            .limit(5)
        ).all()

    def _recent_risks(self, project_path: str) -> list[models.RiskAssessment]:
        if not project_path:
            return []
        return self.db.scalars(
            select(models.RiskAssessment)
            .where(models.RiskAssessment.project_path == project_path)
            .order_by(desc(models.RiskAssessment.created_at))
            .limit(5)
        ).all()

    def _recent_incidents(self, project_path: str) -> list[models.IncidentRecord]:
        if not project_path:
            return []
        return self.db.scalars(
            select(models.IncidentRecord)
            .where(models.IncidentRecord.project_path == project_path)
            .order_by(desc(models.IncidentRecord.created_at))
            .limit(5)
        ).all()

    def _nearby_observability_events(self, event: models.ObservabilityEvent, project_path: str) -> list[models.ObservabilityEvent]:
        window_start = event.observed_at - timedelta(hours=6)
        stmt = (
            select(models.ObservabilityEvent)
            .where(models.ObservabilityEvent.observed_at >= window_start)
            .order_by(desc(models.ObservabilityEvent.observed_at))
            .limit(10)
        )
        if project_path:
            stmt = stmt.where(models.ObservabilityEvent.project_path == project_path)
        events = self.db.scalars(stmt).all()
        if event not in events:
            events.insert(0, event)
        return events

    def _latest_correlation_for_event(self, event_id: int) -> models.IncidentCorrelation | None:
        correlations = self.db.scalars(select(models.IncidentCorrelation).order_by(desc(models.IncidentCorrelation.updated_at)).limit(100)).all()
        for correlation in correlations:
            if event_id in (correlation.related_observability_event_ids or []):
                return correlation
        return None


def _timeline(
    event: models.ObservabilityEvent,
    related_events: list[models.ObservabilityEvent],
    pipelines: list[models.PipelineInsight],
    failed_jobs: list[models.JobSnapshot],
    risks: list[models.RiskAssessment],
    incidents: list[models.IncidentRecord],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in related_events:
        entries.append(
            {
                "time": item.observed_at.isoformat(),
                "kind": "observability",
                "title": item.title,
                "detail": item.message,
                "severity": item.severity,
                "id": item.id,
            }
        )
    for item in pipelines:
        entries.append(
            {
                "time": item.created_at.isoformat(),
                "kind": "pipeline",
                "title": f"Pipeline {item.pipeline_id} {item.status}",
                "detail": item.likely_cause,
                "severity": "high" if item.status == "failed" else "info",
                "id": item.id,
            }
        )
    for item in failed_jobs:
        entries.append(
            {
                "time": item.synced_at.isoformat(),
                "kind": "job",
                "title": f"Job {item.name} {item.status}",
                "detail": item.failure_reason,
                "severity": "high",
                "id": item.id,
            }
        )
    for item in risks:
        entries.append(
            {
                "time": item.created_at.isoformat(),
                "kind": "risk",
                "title": f"Risk {item.score:.0f}/100 {item.level}",
                "detail": item.summary,
                "severity": item.level,
                "id": item.id,
            }
        )
    for item in incidents:
        entries.append(
            {
                "time": item.created_at.isoformat(),
                "kind": "incident",
                "title": item.title,
                "detail": item.probable_root_cause,
                "severity": item.severity,
                "id": item.id,
            }
        )
    entries.sort(key=lambda entry: str(entry["time"]))
    return entries[:30]


def _summary(event: models.ObservabilityEvent, project_path: str, pipelines, risks, incidents) -> str:
    context = []
    if pipelines:
        context.append(f"{len(pipelines)} recent pipeline signal(s)")
    if risks:
        context.append(f"{len(risks)} delivery risk record(s)")
    if incidents:
        context.append(f"{len(incidents)} existing incident record(s)")
    suffix = f" Correlated with {', '.join(context)}." if context else " No related GitLab records were found yet."
    return f"{event.title} for {project_path or event.service_name or 'unknown service'}.{suffix}"


def _suspected_cause(event: models.ObservabilityEvent, pipelines, failed_jobs, risks, incidents) -> str:
    if risks:
        return risks[0].summary
    if pipelines:
        return pipelines[0].likely_cause
    if failed_jobs:
        return f"Recent failed job {failed_jobs[0].name}: {failed_jobs[0].failure_reason or 'failure reason unavailable'}"
    if incidents:
        return incidents[0].probable_root_cause
    return event.message or "The observability alert has no correlated GitLab cause yet."


def _recommendations(event: models.ObservabilityEvent, pipelines, failed_jobs, risks, incidents) -> list[str]:
    recommendations: list[str] = []
    if risks:
        recommendations.extend(risks[0].recommendations[:2])
    if pipelines:
        recommendations.extend(pipelines[0].recommendations[:2])
    if failed_jobs:
        recommendations.append(f"Inspect failed job {failed_jobs[0].name} before changing production state.")
    if incidents:
        recommendations.extend(incidents[0].recommendations[:2])
    if event.alert_url:
        recommendations.append("Open the source alert and confirm whether the symptom is still active.")
    recommendations.append("If symptoms are live, prepare a fix plan or rollback runbook before taking action.")
    return list(dict.fromkeys(item for item in recommendations if item))[:6]


def _confidence(project_path: str, pipelines, failed_jobs, risks, incidents, related_events) -> float:
    score = 0.25
    if project_path:
        score += 0.15
    if related_events:
        score += min(len(related_events), 4) * 0.05
    if pipelines:
        score += 0.14
    if failed_jobs:
        score += 0.12
    if risks:
        score += 0.16
    if incidents:
        score += 0.08
    return round(min(score, 0.96), 2)


def _max_severity(values) -> str:
    normalized = [_severity(value) for value in values if value]
    if not normalized:
        return "info"
    return max(normalized, key=lambda value: SEVERITY_ORDER.get(value, 1))


def _severity(value: Any) -> str:
    text = str(value or "info").strip().lower()
    aliases = {
        "warn": "warning",
        "warning": "medium",
        "error": "high",
        "fatal": "critical",
        "sev1": "critical",
        "sev2": "high",
        "sev3": "medium",
        "p0": "critical",
        "p1": "high",
        "p2": "medium",
    }
    return aliases.get(text, text if text in SEVERITY_ORDER else "info")


def _signal_type(provider: str, payload: dict[str, Any], nested: dict[str, Any], labels: dict[str, Any]) -> str:
    explicit = _first_value(payload, nested, labels, "signal_type", "type", "event_type")
    if explicit:
        return str(explicit).lower()
    provider_lower = provider.lower()
    if "sentry" in provider_lower:
        return "exception"
    if "prometheus" in provider_lower or "grafana" in provider_lower:
        return "metric_alert"
    return "alert"


def _first_dict(payload: dict[str, Any], *keys: str) -> dict[str, Any] | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return None


def _first_value(*items) -> str:
    sources = []
    keys = []
    for item in items:
        if isinstance(item, dict) and not keys:
            sources.append(item)
        else:
            keys.append(str(item))
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in keys:
            value = source.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return ""


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _event_uid(provider: str, payload: dict[str, Any]) -> str:
    stable_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{provider}:{stable_payload}".encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)
