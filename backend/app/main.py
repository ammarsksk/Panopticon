import hashlib
import json
import re

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app import models, schemas
from app.config import get_settings
from app.database import get_db, init_db
from app.event_handlers.gitlab import process_gitlab_event
from app.integrations.gitlab import verify_gitlab_webhook
from app.memory.repository import OperationalMemory
from app.services.gitlab_sync import GitLabProjectSyncService

settings = get_settings()

app = FastAPI(title=settings.app_name, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    settings.validate_for_startup()
    if not settings.is_production:
        init_db()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": settings.app_name, "environment": settings.app_env}


@app.post("/webhooks/gitlab")
async def gitlab_webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    verify_gitlab_webhook(request)
    payload = await request.json()
    created = process_gitlab_event(payload, db, event_uid=_event_uid(request, payload))
    return {"status": "accepted", "created": created}


def _event_uid(request: Request, payload: dict) -> str:
    header_uid = (
        request.headers.get("X-Gitlab-Event-UUID")
        or request.headers.get("X-Gitlab-Delivery")
        or request.headers.get("Idempotency-Key")
    )
    if header_uid:
        return header_uid
    stable_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(stable_payload.encode("utf-8")).hexdigest()


@app.get("/api/events", response_model=list[schemas.OperationalEventOut])
def list_events(db: Session = Depends(get_db), limit: int = 50):
    return db.scalars(select(models.OperationalEvent).order_by(desc(models.OperationalEvent.created_at)).limit(limit)).all()


@app.post("/api/gitlab/projects/sync", response_model=schemas.ProjectSyncRunOut)
def sync_gitlab_projects(db: Session = Depends(get_db), limit: int = 50):
    capped_limit = max(1, min(limit, 100))
    return GitLabProjectSyncService(db).sync(limit=capped_limit)


@app.get("/api/projects", response_model=list[schemas.GitLabProjectOut])
def list_projects(db: Session = Depends(get_db), limit: int = 100):
    return db.scalars(select(models.GitLabProject).order_by(desc(models.GitLabProject.last_activity_at)).limit(limit)).all()


@app.get("/api/projects/sync-runs", response_model=list[schemas.ProjectSyncRunOut])
def list_project_sync_runs(db: Session = Depends(get_db), limit: int = 20):
    return db.scalars(select(models.ProjectSyncRun).order_by(desc(models.ProjectSyncRun.started_at)).limit(limit)).all()


@app.get("/api/projects/{project_id}", response_model=schemas.GitLabProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)):
    project = db.get(models.GitLabProject, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.get("/api/projects/{project_id}/merge-requests", response_model=list[schemas.MergeRequestSnapshotOut])
def list_project_merge_requests(project_id: int, db: Session = Depends(get_db), limit: int = 50):
    project = _get_project_or_404(db, project_id)
    return db.scalars(
        select(models.MergeRequestSnapshot)
        .where(models.MergeRequestSnapshot.gitlab_project_id == project.gitlab_project_id)
        .order_by(desc(models.MergeRequestSnapshot.updated_at_gitlab))
        .limit(limit)
    ).all()


@app.get("/api/projects/{project_id}/pipelines", response_model=list[schemas.PipelineSnapshotOut])
def list_project_pipelines(project_id: int, db: Session = Depends(get_db), limit: int = 50):
    project = _get_project_or_404(db, project_id)
    return db.scalars(
        select(models.PipelineSnapshot)
        .where(models.PipelineSnapshot.gitlab_project_id == project.gitlab_project_id)
        .order_by(desc(models.PipelineSnapshot.updated_at_gitlab))
        .limit(limit)
    ).all()


@app.get("/api/projects/{project_id}/jobs", response_model=list[schemas.JobSnapshotOut])
def list_project_jobs(project_id: int, db: Session = Depends(get_db), limit: int = 50):
    project = _get_project_or_404(db, project_id)
    return db.scalars(
        select(models.JobSnapshot)
        .where(models.JobSnapshot.gitlab_project_id == project.gitlab_project_id)
        .order_by(desc(models.JobSnapshot.synced_at))
        .limit(limit)
    ).all()


@app.get("/api/projects/{project_id}/summary", response_model=schemas.ProjectSummaryOut)
def get_project_summary(project_id: int, db: Session = Depends(get_db)):
    project = _get_project_or_404(db, project_id)
    open_merge_requests = db.scalars(
        select(models.MergeRequestSnapshot)
        .where(models.MergeRequestSnapshot.gitlab_project_id == project.gitlab_project_id)
        .where(models.MergeRequestSnapshot.state == "opened")
        .order_by(desc(models.MergeRequestSnapshot.updated_at_gitlab))
        .limit(10)
    ).all()
    latest_pipelines = db.scalars(
        select(models.PipelineSnapshot)
        .where(models.PipelineSnapshot.gitlab_project_id == project.gitlab_project_id)
        .order_by(desc(models.PipelineSnapshot.updated_at_gitlab))
        .limit(10)
    ).all()
    failed_jobs = db.scalars(
        select(models.JobSnapshot)
        .where(models.JobSnapshot.gitlab_project_id == project.gitlab_project_id)
        .where(models.JobSnapshot.status == "failed")
        .order_by(desc(models.JobSnapshot.synced_at))
        .limit(10)
    ).all()
    risks = db.scalars(
        select(models.RiskAssessment)
        .where(models.RiskAssessment.project_path == project.project_path)
        .order_by(desc(models.RiskAssessment.created_at))
        .limit(10)
    ).all()
    recommendations = db.scalars(
        select(models.Recommendation)
        .where(models.Recommendation.project_path == project.project_path)
        .order_by(desc(models.Recommendation.created_at))
        .limit(10)
    ).all()
    return {
        "project": project,
        "open_merge_requests": open_merge_requests,
        "latest_pipelines": latest_pipelines,
        "failed_jobs": failed_jobs,
        "active_risks": _latest_by([risk for risk in risks if risk.score >= 70], lambda risk: f"{risk.project_path}:{risk.merge_request_iid or risk.deployment_ref}:{risk.score}"),
        "latest_recommendations": [_shape_recommendation(db, item) for item in _latest_by(recommendations, _recommendation_key)],
    }


@app.get("/api/risks", response_model=list[schemas.RiskAssessmentOut])
def list_risks(db: Session = Depends(get_db), limit: int = 50):
    risks = db.scalars(select(models.RiskAssessment).order_by(desc(models.RiskAssessment.created_at)).limit(limit * 3)).all()
    return _latest_by(risks, lambda risk: f"{risk.project_path}:{risk.merge_request_iid or risk.deployment_ref}:{risk.score}")[:limit]


@app.get("/api/pipelines", response_model=list[schemas.PipelineInsightOut])
def list_pipelines(db: Session = Depends(get_db), limit: int = 50):
    return db.scalars(select(models.PipelineInsight).order_by(desc(models.PipelineInsight.created_at)).limit(limit)).all()


@app.get("/api/merge-requests", response_model=list[schemas.MergeRequestSignalOut])
def list_merge_requests(db: Session = Depends(get_db), limit: int = 50):
    return db.scalars(select(models.MergeRequestSignal).order_by(desc(models.MergeRequestSignal.created_at)).limit(limit)).all()


@app.get("/api/incidents", response_model=list[schemas.IncidentRecordOut])
def list_incidents(db: Session = Depends(get_db), limit: int = 50):
    return db.scalars(select(models.IncidentRecord).order_by(desc(models.IncidentRecord.created_at)).limit(limit)).all()


@app.get("/api/memory", response_model=list[schemas.MemoryRecordOut])
def list_memory(db: Session = Depends(get_db), limit: int = 50):
    return db.scalars(select(models.MemoryRecord).order_by(desc(models.MemoryRecord.created_at)).limit(limit)).all()


@app.get("/api/recommendations", response_model=list[schemas.RecommendationOut])
def list_recommendations(db: Session = Depends(get_db), limit: int = 50):
    recommendations = db.scalars(select(models.Recommendation).order_by(desc(models.Recommendation.created_at)).limit(limit * 3)).all()
    return [_shape_recommendation(db, item) for item in _latest_by(recommendations, _recommendation_key)[:limit]]


@app.get("/api/action-dispatches", response_model=list[schemas.ActionDispatchOut])
def list_action_dispatches(db: Session = Depends(get_db), limit: int = 50):
    return db.scalars(select(models.ActionDispatch).order_by(desc(models.ActionDispatch.created_at)).limit(limit)).all()


@app.get("/api/integrations/slack")
def slack_integration_status(db: Session = Depends(get_db)) -> dict:
    return _slack_status(db)


@app.get("/api/dashboard/summary", response_model=schemas.DashboardSummary)
def dashboard_summary(db: Session = Depends(get_db)):
    risks = db.scalars(select(models.RiskAssessment).order_by(desc(models.RiskAssessment.created_at)).limit(200)).all()
    pipelines = db.scalars(select(models.PipelineInsight).where(models.PipelineInsight.status == "failed").order_by(desc(models.PipelineInsight.created_at)).limit(200)).all()
    merge_requests = db.scalars(select(models.MergeRequestSignal).order_by(desc(models.MergeRequestSignal.created_at)).limit(200)).all()
    incidents = db.scalars(select(models.IncidentRecord).where(models.IncidentRecord.status == "open").order_by(desc(models.IncidentRecord.created_at)).limit(200)).all()
    recommendations = db.scalars(select(models.Recommendation).order_by(desc(models.Recommendation.created_at)).limit(100)).all()

    visible_recommendations = _latest_by(recommendations, _recommendation_key)[:6]
    return {
        "active_risks": len(_latest_by([risk for risk in risks if risk.score >= 70], lambda risk: f"{risk.project_path}:{risk.merge_request_iid or risk.deployment_ref}:{risk.score}")),
        "failed_pipelines": len(_latest_by(pipelines, lambda item: f"{item.project_path}:{item.pipeline_id}:{item.likely_cause}")),
        "blocked_merge_requests": len(_latest_by([mr for mr in merge_requests if mr.bottleneck_level in {"blocked", "stale"}], lambda mr: f"{mr.project_path}:{mr.merge_request_iid}")),
        "open_incidents": len(_latest_by(incidents, lambda incident: f"{incident.project_path}:{incident.title}:{incident.probable_root_cause}")),
        "latest_recommendations": [_shape_recommendation(db, item) for item in visible_recommendations],
        "slack_status": _slack_status(db),
    }


def _latest_by(items, key_for):
    seen: set[str] = set()
    latest = []
    for item in items:
        key = key_for(item)
        if key in seen:
            continue
        seen.add(key)
        latest.append(item)
    return latest


def _get_project_or_404(db: Session, project_id: int) -> models.GitLabProject:
    project = db.get(models.GitLabProject, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _recommendation_key(recommendation: models.Recommendation) -> str:
    return f"{recommendation.project_path}:{recommendation.source_type}:{recommendation.channel}:{_summary_part(recommendation.message)}"


def _shape_recommendation(db: Session, recommendation: models.Recommendation) -> dict:
    summary, gemini_analysis = _split_gemini(recommendation.message)
    source = _source_context(db, recommendation)
    return {
        "id": recommendation.id,
        "project_path": recommendation.project_path,
        "source_type": recommendation.source_type,
        "source_id": recommendation.source_id,
        "channel": recommendation.channel,
        "message": recommendation.message,
        "title": _recommendation_title(recommendation),
        "summary": _clean_text(summary),
        "gemini_analysis": _clean_text(gemini_analysis),
        "evidence": source["evidence"],
        "next_actions": source["next_actions"],
        "origin": "demo" if recommendation.project_path.startswith("demo/") else "gitlab",
        "status": recommendation.status,
        "created_at": recommendation.created_at,
    }


def _split_gemini(message: str) -> tuple[str, str]:
    marker = "Vertex Gemini analysis:"
    if marker not in message:
        return message, ""
    summary, gemini = message.split(marker, 1)
    return summary.strip(), gemini.strip()


def _clean_text(value: str) -> str:
    cleaned = re.sub(r"\*\*", "", value or "")
    cleaned = cleaned.replace("`", "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _summary_part(message: str) -> str:
    return _clean_text(message).split("\n", 1)[0][:140]


def _recommendation_title(recommendation: models.Recommendation) -> str:
    if recommendation.source_type == "risk":
        return "Deployment risk detected"
    if recommendation.source_type == "pipeline":
        return "Pipeline failure detected"
    if recommendation.source_type == "incident":
        return "Incident intelligence generated"
    return "Operational recommendation"


def _source_context(db: Session, recommendation: models.Recommendation) -> dict:
    evidence: list[str] = []
    next_actions: list[str] = []
    source_id = _safe_int(recommendation.source_id)
    if recommendation.source_type == "risk" and source_id:
        risk = db.get(models.RiskAssessment, source_id)
        if risk:
            evidence = risk.reasons
            next_actions = risk.recommendations
    elif recommendation.source_type == "pipeline" and source_id:
        pipeline = db.get(models.PipelineInsight, source_id)
        if pipeline:
            evidence = pipeline.evidence
            next_actions = pipeline.recommendations
    elif recommendation.source_type == "incident" and source_id:
        incident = db.get(models.IncidentRecord, source_id)
        if incident:
            evidence = [entry.get("event", "") for entry in incident.timeline if isinstance(entry, dict)]
            next_actions = incident.recommendations
    return {"evidence": evidence, "next_actions": next_actions}


def _safe_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _slack_status(db: Session) -> dict:
    last_dispatch = db.scalars(select(models.ActionDispatch).where(models.ActionDispatch.channel == "slack").order_by(desc(models.ActionDispatch.created_at)).limit(1)).first()
    return {
        "configured": bool(settings.slack_webhook_url),
        "mode": "dry_run" if settings.dry_run_actions else "live",
        "last_status": last_dispatch.status if last_dispatch else "none",
        "last_error": last_dispatch.error if last_dispatch else "",
        "last_checked_at": last_dispatch.created_at if last_dispatch else None,
    }
