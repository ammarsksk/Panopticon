import hashlib
import json
import re
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app import models, schemas
from app.config import get_settings
from app.database import get_db, init_db
from app.event_handlers.gitlab import process_gitlab_event
from app.integrations.gitlab import verify_gitlab_webhook
from app.integrations.slack import parse_slack_form, verified_slack_body
from app.memory.repository import OperationalMemory
from app.services.agent_actions import AgentActionService
from app.services.agent_tools import AgentToolService, mcp_text_result
from app.services.auth import AuthService, RequestContext, assign_workspace, clear_session_cookie, get_current_context, require_role, set_session_cookie, workspace_filter
from app.services.chat import ChatService
from app.services.chat_validation import contains_failure_notice
from app.services.fix_plans import FixPlanService
from app.services.gitlab_sync import GitLabProjectSyncService
from app.services.grounded_recommendations import GroundedRecommendationEngine
from app.services.metrics import MetricsService
from app.services.observability import ObservabilityService
from app.services.oauth import OAuthService, gitlab_client_for_workspace
from app.services.repo_context import RepoContextService
from app.services.slack_app import SlackAppService, parse_interaction_payload

settings = get_settings()

app = FastAPI(title=settings.app_name, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_HEADER = "X-Panopticon-CSRF"
_rate_limits: dict[tuple[str, str], list[float]] = {}


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    current_settings = get_settings()
    rate_limited = _rate_limit_response(request, current_settings)
    if rate_limited is not None:
        return _with_security_headers(rate_limited)

    if _requires_csrf(request, current_settings) and not _valid_csrf(request, current_settings):
        return _with_security_headers(JSONResponse({"detail": "CSRF token missing or invalid"}, status_code=403))

    response = await call_next(request)
    return _with_security_headers(response)


def _requires_csrf(request: Request, current_settings) -> bool:
    if not current_settings.csrf_required:
        return False
    if request.method.upper() not in UNSAFE_METHODS:
        return False
    path = request.url.path
    if not path.startswith("/api/"):
        return False
    if path == "/api/auth/csrf":
        return False
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        return False
    return True


def _valid_csrf(request: Request, current_settings) -> bool:
    cookie_token = request.cookies.get(current_settings.csrf_cookie_name, "")
    header_token = request.headers.get(CSRF_HEADER, "")
    return bool(cookie_token and header_token and secrets.compare_digest(cookie_token, header_token))


def _rate_limit_response(request: Request, current_settings):
    if not current_settings.rate_limit_enabled:
        return None
    bucket, limit = _rate_limit_bucket(request, current_settings)
    if not bucket or limit <= 0:
        return None
    now_ts = time.monotonic()
    window_start = now_ts - max(1, current_settings.rate_limit_window_seconds)
    key = (_client_key(request), bucket)
    hits = [hit for hit in _rate_limits.get(key, []) if hit >= window_start]
    if len(hits) >= limit:
        _rate_limits[key] = hits
        return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)
    hits.append(now_ts)
    _rate_limits[key] = hits
    return None


def _rate_limit_bucket(request: Request, current_settings) -> tuple[str, int]:
    path = request.url.path
    if path == "/api/auth/login":
        return "login", current_settings.rate_limit_login_per_window
    if path == "/api/auth/signup":
        return "signup", current_settings.rate_limit_signup_per_window
    if path == "/api/chat":
        return "chat", current_settings.rate_limit_chat_per_window
    if path.startswith("/api/agent/tools") or path == "/mcp":
        return "tool", current_settings.rate_limit_tool_per_window
    return "", 0


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def _with_security_headers(response: Response) -> Response:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    if get_settings().is_production:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


def _frontend_redirect(target: str) -> str:
    if target.startswith("http://") or target.startswith("https://"):
        return target
    return f"{get_settings().app_public_url.rstrip('/')}{target if target.startswith('/') else '/' + target}"


def _redirect_after_from_request(request: Request, redirect_after: str) -> str:
    if redirect_after.startswith("http://") or redirect_after.startswith("https://"):
        return redirect_after
    referer = request.headers.get("Referer", "")
    parsed = urlparse(referer)
    if parsed.scheme and parsed.netloc:
        host = "localhost" if parsed.hostname == "127.0.0.1" else parsed.hostname
        port = f":{parsed.port}" if parsed.port else ""
        origin = f"{parsed.scheme}://{host}{port}"
        if origin in (get_settings().allowed_origins or []):
            path = redirect_after if redirect_after.startswith("/") else f"/{redirect_after}"
            return f"{origin}{path}"
    return redirect_after


@app.on_event("startup")
def on_startup() -> None:
    settings.validate_for_startup()
    if not settings.is_production:
        init_db()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": settings.app_name, "environment": settings.app_env}


@app.get("/api/auth/me", response_model=schemas.AuthSessionOut)
def auth_me(context: RequestContext = Depends(get_current_context)) -> dict:
    return {"user": context.user, "workspace": context.workspace, "role": context.role, "auth_required": get_settings().auth_required}


@app.get("/api/auth/csrf")
def auth_csrf(response: Response) -> dict:
    current_settings = get_settings()
    token = secrets.token_urlsafe(32)
    response.set_cookie(
        key=current_settings.csrf_cookie_name,
        value=token,
        max_age=current_settings.session_ttl_hours * 3600,
        httponly=False,
        secure=current_settings.is_production,
        samesite="none" if current_settings.is_production else "lax",
    )
    return {"csrf_token": token}


@app.post("/api/auth/signup", response_model=schemas.AuthSessionOut)
def auth_signup(request: schemas.AuthRequestIn, response: Response, db: Session = Depends(get_db)) -> dict:
    try:
        session, token = AuthService(db).signup(email=request.email, password=request.password, name=request.name, workspace_name=request.workspace_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    set_session_cookie(response, token)
    user = db.get(models.User, session.user_id)
    workspace = db.get(models.Workspace, session.workspace_id)
    return {"user": user, "workspace": workspace, "role": "owner", "auth_required": settings.auth_required}


@app.post("/api/auth/login", response_model=schemas.AuthSessionOut)
def auth_login(request: schemas.AuthRequestIn, response: Response, db: Session = Depends(get_db)) -> dict:
    try:
        session, token = AuthService(db).login(email=request.email, password=request.password)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from None
    set_session_cookie(response, token)
    user = db.get(models.User, session.user_id)
    workspace = db.get(models.Workspace, session.workspace_id)
    membership = db.scalar(
        select(models.WorkspaceMember)
        .where(models.WorkspaceMember.user_id == user.id)
        .where(models.WorkspaceMember.workspace_id == workspace.id)
    )
    return {"user": user, "workspace": workspace, "role": membership.role if membership else "viewer", "auth_required": settings.auth_required}


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    AuthService(db).logout(request.cookies.get(settings.session_cookie_name))
    clear_session_cookie(response)
    return {"status": "logged_out"}


@app.get("/api/auth/google/start")
def google_oauth_start(request: Request, db: Session = Depends(get_db), redirect_after: str = "/"):
    try:
        url = OAuthService(db).google_auth_url(redirect_after=_redirect_after_from_request(request, redirect_after))
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    return RedirectResponse(url)


@app.get("/api/auth/google/callback")
def google_oauth_callback(code: str = "", state: str = "", db: Session = Depends(get_db)):
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing OAuth callback code or state")
    try:
        result = OAuthService(db).complete_google_callback(code=code, state=state)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Google OAuth failed: {exc}") from None
    response = RedirectResponse(_frontend_redirect(result.redirect_url))
    if result.session_token:
        set_session_cookie(response, result.session_token)
    return response


@app.get("/api/integrations/gitlab/status", response_model=schemas.OAuthIntegrationStatusOut)
def gitlab_oauth_status(db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context)) -> dict:
    return OAuthService(db).gitlab_status(workspace_id=context.workspace.id)


@app.get("/api/integrations/gitlab/connect")
def gitlab_oauth_connect(request: Request, db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context), redirect_after: str = "/projects"):
    try:
        url = OAuthService(db).gitlab_auth_url(user_id=context.user.id, workspace_id=context.workspace.id, redirect_after=_redirect_after_from_request(request, redirect_after))
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    return RedirectResponse(url)


@app.get("/api/integrations/gitlab/callback")
def gitlab_oauth_callback(code: str = "", state: str = "", db: Session = Depends(get_db)):
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing OAuth callback code or state")
    try:
        result = OAuthService(db).complete_gitlab_callback(code=code, state=state)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"GitLab OAuth failed: {exc}") from None
    return RedirectResponse(_frontend_redirect(result.redirect_url))


@app.post("/webhooks/gitlab")
async def gitlab_webhook(request: Request, db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context)) -> dict:
    verify_gitlab_webhook(request)
    payload = await request.json()
    created = process_gitlab_event(payload, db, event_uid=_event_uid(request, payload))
    _attach_created_records(db, context.workspace.id)
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
def list_events(db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context), limit: int = 50):
    return db.scalars(
        select(models.OperationalEvent)
        .where(workspace_filter(models.OperationalEvent, context.workspace.id))
        .order_by(desc(models.OperationalEvent.created_at))
        .limit(limit)
    ).all()


@app.post("/api/gitlab/projects/sync", response_model=schemas.ProjectSyncRunOut)
def sync_gitlab_projects(db: Session = Depends(get_db), context: RequestContext = Depends(require_role("owner", "admin")), limit: int = 50):
    capped_limit = max(1, min(limit, 100))
    client = gitlab_client_for_workspace(db, context.workspace.id)
    return GitLabProjectSyncService(db, client=client, workspace_id=context.workspace.id).sync(limit=capped_limit)


@app.get("/api/projects", response_model=list[schemas.GitLabProjectOut])
def list_projects(db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context), limit: int = 100):
    return db.scalars(
        select(models.GitLabProject)
        .where(workspace_filter(models.GitLabProject, context.workspace.id))
        .order_by(desc(models.GitLabProject.last_activity_at))
        .limit(limit)
    ).all()


@app.get("/api/projects/sync-runs", response_model=list[schemas.ProjectSyncRunOut])
def list_project_sync_runs(db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context), limit: int = 20):
    return db.scalars(
        select(models.ProjectSyncRun)
        .where(workspace_filter(models.ProjectSyncRun, context.workspace.id))
        .order_by(desc(models.ProjectSyncRun.started_at))
        .limit(limit)
    ).all()


@app.get("/api/projects/{project_id}", response_model=schemas.GitLabProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context)):
    project = _get_project_or_404(db, project_id, context)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.get("/api/projects/{project_id}/merge-requests", response_model=list[schemas.MergeRequestSnapshotOut])
def list_project_merge_requests(project_id: int, db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context), limit: int = 50):
    project = _get_project_or_404(db, project_id, context)
    return db.scalars(
        select(models.MergeRequestSnapshot)
        .where(models.MergeRequestSnapshot.gitlab_project_id == project.gitlab_project_id)
        .where(workspace_filter(models.MergeRequestSnapshot, context.workspace.id))
        .order_by(desc(models.MergeRequestSnapshot.updated_at_gitlab))
        .limit(limit)
    ).all()


@app.get("/api/projects/{project_id}/pipelines", response_model=list[schemas.PipelineSnapshotOut])
def list_project_pipelines(project_id: int, db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context), limit: int = 50):
    project = _get_project_or_404(db, project_id, context)
    return db.scalars(
        select(models.PipelineSnapshot)
        .where(models.PipelineSnapshot.gitlab_project_id == project.gitlab_project_id)
        .where(workspace_filter(models.PipelineSnapshot, context.workspace.id))
        .order_by(desc(models.PipelineSnapshot.updated_at_gitlab))
        .limit(limit)
    ).all()


@app.get("/api/projects/{project_id}/jobs", response_model=list[schemas.JobSnapshotOut])
def list_project_jobs(project_id: int, db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context), limit: int = 50):
    project = _get_project_or_404(db, project_id, context)
    return db.scalars(
        select(models.JobSnapshot)
        .where(models.JobSnapshot.gitlab_project_id == project.gitlab_project_id)
        .where(workspace_filter(models.JobSnapshot, context.workspace.id))
        .order_by(desc(models.JobSnapshot.synced_at))
        .limit(limit)
    ).all()


@app.post("/api/projects/{project_id}/pipelines/{pipeline_id}/jobs/refresh", response_model=list[schemas.JobSnapshotOut])
def refresh_pipeline_jobs(project_id: int, pipeline_id: str, db: Session = Depends(get_db), context: RequestContext = Depends(require_role("owner", "admin")), limit: int = 50):
    project = _get_project_or_404(db, project_id, context)
    client = gitlab_client_for_workspace(db, context.workspace.id)
    return GitLabProjectSyncService(db, client=client, workspace_id=context.workspace.id).refresh_pipeline_jobs(project, pipeline_id, job_limit=max(1, min(limit, 100)))


@app.post("/api/projects/{project_id}/repo-index/refresh", response_model=schemas.RepoIndexRunOut)
def refresh_project_repo_index(project_id: int, db: Session = Depends(get_db), context: RequestContext = Depends(require_role("owner", "admin"))):
    project = _get_project_or_404(db, project_id, context)
    client = gitlab_client_for_workspace(db, context.workspace.id)
    return RepoContextService(db, client=client, workspace_id=context.workspace.id).index_project(project)


@app.get("/api/projects/{project_id}/repo-index/files", response_model=list[schemas.RepoFileIndexOut])
def list_project_repo_files(project_id: int, db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context), limit: int = 50):
    project = _get_project_or_404(db, project_id, context)
    return RepoContextService(db, workspace_id=context.workspace.id).files(project, limit=max(1, min(limit, 100)))


@app.get("/api/projects/{project_id}/repo-index/tree")
def list_project_repo_tree(project_id: int, db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context), limit: int = 200):
    project = _get_project_or_404(db, project_id, context)
    return RepoContextService(db, workspace_id=context.workspace.id).list_tree(project, limit=max(1, min(limit, 500)))


@app.get("/api/projects/{project_id}/repo-index/files/content", response_model=schemas.RepoFileContentOut | None)
def read_project_repo_file(project_id: int, file_path: str, db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context)):
    project = _get_project_or_404(db, project_id, context)
    return RepoContextService(db, workspace_id=context.workspace.id).read_file(project, file_path=file_path)


@app.get("/api/projects/{project_id}/repo-index/files/range")
def read_project_repo_file_range(
    project_id: int,
    file_path: str,
    start_line: int = 1,
    end_line: int = 120,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_current_context),
):
    project = _get_project_or_404(db, project_id, context)
    return RepoContextService(db, workspace_id=context.workspace.id).read_file_range(project, file_path=file_path, start_line=start_line, end_line=end_line)


@app.get("/api/projects/{project_id}/repo-index/chunks", response_model=list[schemas.RepoCodeChunkOut])
def search_project_repo_chunks(project_id: int, query: str = "", db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context), limit: int = 20):
    project = _get_project_or_404(db, project_id, context)
    return RepoContextService(db, workspace_id=context.workspace.id).search_chunks(project=project, query=query, limit=max(1, min(limit, 100)))


@app.get("/api/projects/{project_id}/repo-index/symbols", response_model=list[schemas.RepoSymbolIndexOut])
def search_project_repo_symbols(project_id: int, query: str = "", db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context), limit: int = 50):
    project = _get_project_or_404(db, project_id, context)
    return RepoContextService(db, workspace_id=context.workspace.id).symbols(project, query=query, limit=max(1, min(limit, 200)))


@app.get("/api/projects/{project_id}/repo-index/summary", response_model=schemas.RepoContextSummaryOut)
def get_project_repo_index_summary(project_id: int, db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context)):
    project = _get_project_or_404(db, project_id, context)
    return RepoContextService(db, workspace_id=context.workspace.id).summary(project)


@app.get("/api/projects/{project_id}/summary", response_model=schemas.ProjectSummaryOut)
def get_project_summary(project_id: int, db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context)):
    project = _get_project_or_404(db, project_id, context)
    open_merge_requests = db.scalars(
        select(models.MergeRequestSnapshot)
        .where(models.MergeRequestSnapshot.gitlab_project_id == project.gitlab_project_id)
        .where(workspace_filter(models.MergeRequestSnapshot, context.workspace.id))
        .where(models.MergeRequestSnapshot.state == "opened")
        .order_by(desc(models.MergeRequestSnapshot.updated_at_gitlab))
        .limit(10)
    ).all()
    latest_pipelines = db.scalars(
        select(models.PipelineSnapshot)
        .where(models.PipelineSnapshot.gitlab_project_id == project.gitlab_project_id)
        .where(workspace_filter(models.PipelineSnapshot, context.workspace.id))
        .order_by(desc(models.PipelineSnapshot.updated_at_gitlab))
        .limit(10)
    ).all()
    failed_jobs = db.scalars(
        select(models.JobSnapshot)
        .where(models.JobSnapshot.gitlab_project_id == project.gitlab_project_id)
        .where(workspace_filter(models.JobSnapshot, context.workspace.id))
        .where(models.JobSnapshot.status == "failed")
        .order_by(desc(models.JobSnapshot.synced_at))
        .limit(10)
    ).all()
    risks = db.scalars(
        select(models.RiskAssessment)
        .where(models.RiskAssessment.project_path == project.project_path)
        .where(workspace_filter(models.RiskAssessment, context.workspace.id))
        .order_by(desc(models.RiskAssessment.created_at))
        .limit(10)
    ).all()
    incidents = db.scalars(
        select(models.IncidentRecord)
        .where(models.IncidentRecord.project_path == project.project_path)
        .where(workspace_filter(models.IncidentRecord, context.workspace.id))
        .order_by(desc(models.IncidentRecord.created_at))
        .limit(10)
    ).all()
    recommendations = db.scalars(
        select(models.Recommendation)
        .where(models.Recommendation.project_path == project.project_path)
        .where(workspace_filter(models.Recommendation, context.workspace.id))
        .order_by(desc(models.Recommendation.created_at))
        .limit(10)
    ).all()
    recommendation_ids = [item.id for item in recommendations]
    actions = []
    if recommendation_ids:
        actions = db.scalars(
            select(models.ActionDispatch)
            .where(models.ActionDispatch.recommendation_id.in_(recommendation_ids))
            .where(workspace_filter(models.ActionDispatch, context.workspace.id))
            .order_by(desc(models.ActionDispatch.created_at))
            .limit(10)
        ).all()
    memory_records = db.scalars(
        select(models.MemoryRecord)
        .where(models.MemoryRecord.project_path == project.project_path)
        .where(workspace_filter(models.MemoryRecord, context.workspace.id))
        .order_by(desc(models.MemoryRecord.created_at))
        .limit(10)
    ).all()
    repo_service = RepoContextService(db, workspace_id=context.workspace.id)
    repo_summary = repo_service.summary(project)
    return {
        "project": project,
        "open_merge_requests": open_merge_requests,
        "latest_pipelines": latest_pipelines,
        "failed_jobs": failed_jobs,
        "active_risks": _latest_by([risk for risk in risks if risk.score >= 70], lambda risk: f"{risk.project_path}:{risk.merge_request_iid or risk.deployment_ref}:{risk.score}"),
        "recent_incidents": _latest_by(incidents, lambda incident: f"{incident.project_path}:{incident.title}:{incident.probable_root_cause}"),
        "latest_recommendations": _ranked_recommendations(db, recommendations),
        "recent_actions": actions,
        "memory_records": [_shape_memory_record(record) for record in memory_records],
        "repo_files": repo_summary["priority_files"],
        "latest_repo_index_run": repo_summary["latest_run"],
        "repo_context_summary": repo_summary,
    }


@app.get("/api/risks", response_model=list[schemas.RiskAssessmentOut])
def list_risks(db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context), limit: int = 50):
    risks = db.scalars(
        select(models.RiskAssessment)
        .where(workspace_filter(models.RiskAssessment, context.workspace.id))
        .order_by(desc(models.RiskAssessment.created_at))
        .limit(limit * 3)
    ).all()
    return _latest_by(risks, lambda risk: f"{risk.project_path}:{risk.merge_request_iid or risk.deployment_ref}:{risk.score}")[:limit]


@app.get("/api/pipelines", response_model=list[schemas.PipelineInsightOut])
def list_pipelines(db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context), limit: int = 50):
    return db.scalars(
        select(models.PipelineInsight)
        .where(workspace_filter(models.PipelineInsight, context.workspace.id))
        .order_by(desc(models.PipelineInsight.created_at))
        .limit(limit)
    ).all()


@app.get("/api/merge-requests", response_model=list[schemas.MergeRequestSignalOut])
def list_merge_requests(db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context), limit: int = 50):
    return db.scalars(
        select(models.MergeRequestSignal)
        .where(workspace_filter(models.MergeRequestSignal, context.workspace.id))
        .order_by(desc(models.MergeRequestSignal.created_at))
        .limit(limit)
    ).all()


@app.get("/api/incidents", response_model=list[schemas.IncidentRecordOut])
def list_incidents(db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context), limit: int = 50):
    return db.scalars(
        select(models.IncidentRecord)
        .where(workspace_filter(models.IncidentRecord, context.workspace.id))
        .order_by(desc(models.IncidentRecord.created_at))
        .limit(limit)
    ).all()


@app.post("/api/observability/events", response_model=schemas.ObservabilityIngestOut)
def ingest_observability_event(request: schemas.ObservabilityEventIn, db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context)):
    raw = request.model_dump(exclude_none=True)
    provider = raw.pop("provider", "generic") or "generic"
    event, correlation, deduplicated = ObservabilityService(db).ingest(raw, provider=provider)
    for record in (event, correlation):
        if record:
            assign_workspace(record, context.workspace.id)
    db.commit()
    return {"event": event, "correlation": correlation, "deduplicated": deduplicated}


@app.post("/webhooks/observability/{provider}", response_model=schemas.ObservabilityIngestOut)
async def observability_webhook(provider: str, request: Request, db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context)):
    payload = await _json_or_empty(request)
    event, correlation, deduplicated = ObservabilityService(db).ingest(payload, provider=provider)
    for record in (event, correlation):
        if record:
            assign_workspace(record, context.workspace.id)
    db.commit()
    return {"event": event, "correlation": correlation, "deduplicated": deduplicated}


@app.get("/api/observability/events", response_model=list[schemas.ObservabilityEventOut])
def list_observability_events(db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context), limit: int = 50, project_path: str = ""):
    stmt = select(models.ObservabilityEvent).where(workspace_filter(models.ObservabilityEvent, context.workspace.id))
    if project_path:
        stmt = stmt.where(models.ObservabilityEvent.project_path == project_path)
    return db.scalars(stmt.order_by(desc(models.ObservabilityEvent.observed_at)).limit(max(1, min(limit, 100)))).all()


@app.get("/api/observability/correlations", response_model=list[schemas.IncidentCorrelationOut])
def list_incident_correlations(db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context), limit: int = 50, project_path: str = ""):
    stmt = select(models.IncidentCorrelation).where(workspace_filter(models.IncidentCorrelation, context.workspace.id))
    if project_path:
        stmt = stmt.where(models.IncidentCorrelation.project_path == project_path)
    return db.scalars(stmt.order_by(desc(models.IncidentCorrelation.updated_at)).limit(max(1, min(limit, 100)))).all()


@app.get("/api/metrics/summary", response_model=schemas.MetricsSummaryOut)
def metrics_summary(db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context)):
    return MetricsService(db, workspace_id=context.workspace.id).organization_summary()


@app.get("/api/metrics/projects", response_model=list[schemas.ProjectHealthOut])
def project_metrics(db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context), limit: int = 100):
    return MetricsService(db, workspace_id=context.workspace.id).project_health(limit=max(1, min(limit, 500)))


@app.post("/api/metrics/snapshots/refresh", response_model=list[schemas.EngineeringMetricSnapshotOut])
def refresh_metric_snapshots(db: Session = Depends(get_db), context: RequestContext = Depends(require_role("owner", "admin"))):
    return MetricsService(db, workspace_id=context.workspace.id).refresh_snapshots()


@app.get("/api/metrics/snapshots", response_model=list[schemas.EngineeringMetricSnapshotOut])
def list_metric_snapshots(db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context), limit: int = 100, project_path: str = ""):
    return MetricsService(db, workspace_id=context.workspace.id).list_snapshots(project_path=project_path, limit=max(1, min(limit, 500)))


@app.get("/api/memory", response_model=list[schemas.MemoryRecordOut])
def list_memory(db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context), limit: int = 50):
    records = db.scalars(
        select(models.MemoryRecord)
        .where(workspace_filter(models.MemoryRecord, context.workspace.id))
        .order_by(desc(models.MemoryRecord.created_at))
        .limit(limit)
    ).all()
    return [_shape_memory_record(record) for record in records]


@app.patch("/api/memory/{memory_id}", response_model=schemas.MemoryRecordOut)
def update_memory_record(
    memory_id: int,
    request: schemas.MemoryRecordUpdateIn,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(require_role("owner", "admin")),
):
    record = db.get(models.MemoryRecord, memory_id)
    if not record or record.workspace_id != context.workspace.id:
        raise HTTPException(status_code=404, detail="Memory record not found")
    updates = request.model_dump(exclude_unset=True)
    for field in ("project_path", "memory_type", "signature", "summary"):
        if field in updates and updates[field] is not None:
            setattr(record, field, _string_value(updates[field]))
    if "evidence" in updates and updates["evidence"] is not None:
        record.evidence = _list_of_strings(updates["evidence"])
    if "remediation" in updates and updates["remediation"] is not None:
        record.remediation = _list_of_strings(updates["remediation"])
    db.commit()
    db.refresh(record)
    return _shape_memory_record(record)


@app.delete("/api/memory/{memory_id}", response_model=dict)
def delete_memory_record(memory_id: int, db: Session = Depends(get_db), context: RequestContext = Depends(require_role("owner", "admin"))):
    record = db.get(models.MemoryRecord, memory_id)
    if not record or record.workspace_id != context.workspace.id:
        raise HTTPException(status_code=404, detail="Memory record not found")
    db.delete(record)
    db.commit()
    return {"deleted": True, "id": memory_id}


@app.get("/api/recommendations", response_model=list[schemas.RecommendationOut])
def list_recommendations(
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_current_context),
    limit: int = 50,
    severity: str | None = None,
    status: str | None = None,
    action_type: str | None = None,
):
    recommendations = db.scalars(
        select(models.Recommendation)
        .where(workspace_filter(models.Recommendation, context.workspace.id))
        .order_by(desc(models.Recommendation.created_at))
        .limit(limit * 4)
    ).all()
    shaped = _ranked_recommendations(db, recommendations)
    if severity:
        shaped = [item for item in shaped if item["severity"] == severity]
    if status:
        shaped = [item for item in shaped if item["status"] == status]
    if action_type:
        shaped = [item for item in shaped if item["action_type"] == action_type]
    return shaped[:limit]


@app.post("/api/projects/{project_id}/recommendations/grounded", response_model=schemas.GroundedRecommendationOut)
def generate_grounded_recommendation(
    project_id: int,
    request: schemas.GroundedRecommendationCreateIn,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_current_context),
):
    project = _get_project_or_404(db, project_id, context)
    engine = GroundedRecommendationEngine(db, workspace_id=context.workspace.id)
    bundle = engine.recommend(project=project, question=request.question, intent=request.intent)
    saved = None
    if request.persist:
        saved_record = engine.create_recommendation(
            project=project,
            question=request.question,
            intent=request.intent,
            channel=request.channel,
        )
        saved = _shape_recommendation(db, saved_record)
    return {**bundle, "saved_recommendation": saved}


@app.get("/api/action-dispatches", response_model=list[schemas.ActionDispatchOut])
def list_action_dispatches(db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context), limit: int = 50):
    return db.scalars(
        select(models.ActionDispatch)
        .where(workspace_filter(models.ActionDispatch, context.workspace.id))
        .order_by(desc(models.ActionDispatch.created_at))
        .limit(limit)
    ).all()


@app.post("/api/actions/propose-from-recommendations", response_model=list[schemas.AgentActionOut])
def propose_actions_from_recommendations(db: Session = Depends(get_db), context: RequestContext = Depends(require_role("owner", "admin")), limit: int = 50):
    return AgentActionService(db, workspace_id=context.workspace.id).propose_from_recommendations(limit=max(1, min(limit, 100)))


@app.get("/api/actions", response_model=list[schemas.AgentActionOut])
def list_agent_actions(db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context), limit: int = 50):
    return db.scalars(
        select(models.AgentAction)
        .where(workspace_filter(models.AgentAction, context.workspace.id))
        .order_by(desc(models.AgentAction.created_at))
        .limit(limit)
    ).all()


@app.get("/api/actions/{action_id}", response_model=schemas.AgentActionDetailOut)
def get_agent_action(action_id: int, db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context)):
    service = AgentActionService(db, workspace_id=context.workspace.id)
    action = _agent_action_or_404(service, action_id)
    approvals = db.scalars(
        select(models.ActionApproval)
        .where(models.ActionApproval.agent_action_id == action.id)
        .where(workspace_filter(models.ActionApproval, context.workspace.id))
        .order_by(desc(models.ActionApproval.created_at))
    ).all()
    dispatches = []
    if action.recommendation_id:
        dispatches = db.scalars(
            select(models.ActionDispatch)
            .where(models.ActionDispatch.recommendation_id == action.recommendation_id)
            .where(workspace_filter(models.ActionDispatch, context.workspace.id))
            .order_by(desc(models.ActionDispatch.created_at))
        ).all()
    return {"action": action, "approvals": approvals, "dispatches": dispatches}


@app.post("/api/actions/{action_id}/approve", response_model=schemas.AgentActionOut)
def approve_agent_action(action_id: int, decision: schemas.ActionDecisionIn | None = None, db: Session = Depends(get_db), context: RequestContext = Depends(require_role("owner", "admin"))):
    decision = decision or schemas.ActionDecisionIn()
    try:
        return AgentActionService(db, workspace_id=context.workspace.id).approve(action_id, actor=decision.actor, reason=decision.reason)
    except LookupError:
        raise HTTPException(status_code=404, detail="Action not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.post("/api/actions/{action_id}/reject", response_model=schemas.AgentActionOut)
def reject_agent_action(action_id: int, decision: schemas.ActionDecisionIn | None = None, db: Session = Depends(get_db), context: RequestContext = Depends(require_role("owner", "admin"))):
    decision = decision or schemas.ActionDecisionIn()
    try:
        return AgentActionService(db, workspace_id=context.workspace.id).reject(action_id, actor=decision.actor, reason=decision.reason)
    except LookupError:
        raise HTTPException(status_code=404, detail="Action not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.post("/api/actions/{action_id}/execute", response_model=schemas.AgentActionOut)
def execute_agent_action(action_id: int, db: Session = Depends(get_db), context: RequestContext = Depends(require_role("owner", "admin"))):
    try:
        return AgentActionService(db, workspace_id=context.workspace.id).execute(action_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Action not found") from None
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.post("/api/fix-plans", response_model=schemas.FixPlanOut)
def create_fix_plan(request: schemas.FixPlanCreateIn, db: Session = Depends(get_db), context: RequestContext = Depends(require_role("owner", "admin"))):
    try:
        return FixPlanService(db, workspace_id=context.workspace.id).create(
            project_id=request.project_id,
            project_path=request.project_path,
            source_type=request.source_type,
            source_id=request.source_id,
            problem_statement=request.problem_statement,
            fix_type=request.fix_type,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.get("/api/fix-plans", response_model=list[schemas.FixPlanOut])
def list_fix_plans(db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context), limit: int = 50):
    return FixPlanService(db, workspace_id=context.workspace.id).list(limit=max(1, min(limit, 100)))


@app.get("/api/fix-plans/{plan_id}", response_model=schemas.FixPlanDetailOut)
def get_fix_plan(plan_id: int, db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context)):
    service = FixPlanService(db, workspace_id=context.workspace.id)
    try:
        plan = service.get(plan_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Fix plan not found") from None
    return {"plan": plan, "approvals": service.approvals(plan.id)}


@app.post("/api/fix-plans/{plan_id}/approve", response_model=schemas.FixPlanOut)
def approve_fix_plan(plan_id: int, decision: schemas.FixPlanDecisionIn | None = None, db: Session = Depends(get_db), context: RequestContext = Depends(require_role("owner", "admin"))):
    decision = decision or schemas.FixPlanDecisionIn()
    try:
        return FixPlanService(db, workspace_id=context.workspace.id).approve(plan_id, actor=decision.actor, reason=decision.reason)
    except LookupError:
        raise HTTPException(status_code=404, detail="Fix plan not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.post("/api/fix-plans/{plan_id}/reject", response_model=schemas.FixPlanOut)
def reject_fix_plan(plan_id: int, decision: schemas.FixPlanDecisionIn | None = None, db: Session = Depends(get_db), context: RequestContext = Depends(require_role("owner", "admin"))):
    decision = decision or schemas.FixPlanDecisionIn()
    try:
        return FixPlanService(db, workspace_id=context.workspace.id).reject(plan_id, actor=decision.actor, reason=decision.reason)
    except LookupError:
        raise HTTPException(status_code=404, detail="Fix plan not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.post("/api/fix-plans/{plan_id}/create-branch", response_model=schemas.FixPlanOut)
def create_fix_plan_branch(plan_id: int, db: Session = Depends(get_db), context: RequestContext = Depends(require_role("owner", "admin"))):
    try:
        return FixPlanService(db, workspace_id=context.workspace.id).create_branch(plan_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Fix plan not found") from None
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.post("/api/fix-plans/{plan_id}/open-merge-request", response_model=schemas.FixPlanOut)
def open_fix_plan_merge_request(plan_id: int, db: Session = Depends(get_db), context: RequestContext = Depends(require_role("owner", "admin"))):
    try:
        return FixPlanService(db, workspace_id=context.workspace.id).open_merge_request(plan_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Fix plan not found") from None
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.post("/api/chat", response_model=schemas.ChatResponseOut)
def create_chat_message(request: schemas.ChatRequestIn, db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context)):
    if not request.message.strip():
        raise HTTPException(status_code=422, detail="message is required")
    if request.project_id and not db.scalar(select(models.GitLabProject).where(models.GitLabProject.id == request.project_id).where(workspace_filter(models.GitLabProject, context.workspace.id))):
        raise HTTPException(status_code=404, detail="Project not found")
    response = ChatService(db, workspace_id=context.workspace.id).answer(message=request.message, project_id=request.project_id, thread_id=request.thread_id)
    if isinstance(response, dict):
        return {
            **response,
            "user_message": _shape_chat_message(response["user_message"]),
            "assistant_message": _shape_chat_message(response["assistant_message"]),
        }
    return {
        "thread": response.thread,
        "user_message": _shape_chat_message(response.user_message),
        "assistant_message": _shape_chat_message(response.assistant_message),
        "prepared_actions": response.prepared_actions,
        "prepared_fix_plans": response.prepared_fix_plans,
    }


@app.get("/api/chat/threads", response_model=list[schemas.ChatThreadOut])
def list_chat_threads(db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context), limit: int = 30):
    return db.scalars(
        select(models.ChatThread)
        .where(workspace_filter(models.ChatThread, context.workspace.id))
        .order_by(desc(models.ChatThread.updated_at))
        .limit(limit)
    ).all()


@app.delete("/api/chat/threads", response_model=schemas.ChatHistoryDeleteOut)
def clear_chat_threads(db: Session = Depends(get_db), context: RequestContext = Depends(require_role("owner", "admin"))):
    return _clear_chat_threads_for_workspace(db, context.workspace.id)


@app.post("/api/chat/threads/clear", response_model=schemas.ChatHistoryDeleteOut)
def clear_chat_threads_post(db: Session = Depends(get_db), context: RequestContext = Depends(require_role("owner", "admin"))):
    return _clear_chat_threads_for_workspace(db, context.workspace.id)


def _clear_chat_threads_for_workspace(db: Session, workspace_id: int) -> dict:
    threads = db.scalars(select(models.ChatThread).where(workspace_filter(models.ChatThread, workspace_id))).all()
    thread_ids = [thread.id for thread in threads]
    messages: list[models.ChatMessage] = []
    if thread_ids:
        messages = db.scalars(
            select(models.ChatMessage)
            .where(models.ChatMessage.thread_id.in_(thread_ids))
            .where(workspace_filter(models.ChatMessage, workspace_id))
        ).all()
    for message in messages:
        db.delete(message)
    for thread in threads:
        db.delete(thread)
    db.commit()
    return {"deleted_threads": len(threads), "deleted_messages": len(messages)}


@app.get("/api/chat/threads/{thread_id}", response_model=list[schemas.ChatMessageOut])
def list_chat_messages(thread_id: int, db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context)):
    thread = db.get(models.ChatThread, thread_id)
    if not thread or thread.workspace_id != context.workspace.id:
        raise HTTPException(status_code=404, detail="Thread not found")
    messages = db.scalars(
        select(models.ChatMessage)
        .where(models.ChatMessage.thread_id == thread_id)
        .where(workspace_filter(models.ChatMessage, context.workspace.id))
        .order_by(models.ChatMessage.created_at)
    ).all()
    return [_shape_chat_message(message) for message in messages]


@app.delete("/api/chat/threads/{thread_id}", response_model=schemas.ChatHistoryDeleteOut)
def delete_chat_thread(thread_id: int, db: Session = Depends(get_db), context: RequestContext = Depends(require_role("owner", "admin"))):
    thread = db.get(models.ChatThread, thread_id)
    if not thread or thread.workspace_id != context.workspace.id:
        raise HTTPException(status_code=404, detail="Thread not found")
    messages = db.scalars(
        select(models.ChatMessage)
        .where(models.ChatMessage.thread_id == thread_id)
        .where(workspace_filter(models.ChatMessage, context.workspace.id))
    ).all()
    for message in messages:
        db.delete(message)
    db.delete(thread)
    db.commit()
    return {"deleted_threads": 1, "deleted_messages": len(messages)}


@app.get("/api/integrations/slack")
def slack_integration_status(db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context)) -> dict:
    return _slack_status(db, context)


@app.get("/api/integrations/slack/connect")
def slack_oauth_connect(request: Request, db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context), redirect_after: str = "/"):
    try:
        url = OAuthService(db).slack_auth_url(user_id=context.user.id, workspace_id=context.workspace.id, redirect_after=_redirect_after_from_request(request, redirect_after))
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    return RedirectResponse(url)


@app.get("/api/integrations/slack/callback")
def slack_oauth_callback(code: str = "", state: str = "", db: Session = Depends(get_db)):
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing OAuth callback code or state")
    try:
        result = OAuthService(db).complete_slack_callback(code=code, state=state)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Slack OAuth failed: {exc}") from None
    return RedirectResponse(_frontend_redirect(result.redirect_url))


@app.post("/slack/commands")
async def slack_commands(request: Request, db: Session = Depends(get_db)) -> dict:
    body = await verified_slack_body(request)
    form = parse_slack_form(body)
    return SlackAppService(db).command(form)


@app.post("/slack/interactions")
async def slack_interactions(request: Request, db: Session = Depends(get_db)) -> dict:
    body = await verified_slack_body(request)
    form = parse_slack_form(body)
    payload = parse_interaction_payload(form)
    return SlackAppService(db).interaction(payload)


@app.post("/slack/events")
async def slack_events(request: Request, db: Session = Depends(get_db)) -> dict:
    body = await verified_slack_body(request)
    payload = json.loads(body.decode("utf-8") or "{}")
    return SlackAppService(db).event(payload)


@app.get("/api/integrations/ai")
def ai_integration_status() -> dict:
    return {
        "gemini_enabled": settings.gemini_enabled,
        "provider": "vertex_ai" if settings.google_genai_use_vertexai else "gemini_api",
        "model": settings.gemini_model,
        "google_cloud_project_configured": bool(settings.google_cloud_project),
        "google_cloud_location": settings.google_cloud_location,
        "chat_mode": "vertex_gemini" if settings.gemini_enabled else "deterministic_fallback",
        "tool_layer": "mcp_compatible_panopticon_tools",
        "mcp_enabled": True,
    }


@app.get("/api/agent/tools")
def list_agent_tools(db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context)) -> dict:
    return {"tools": AgentToolService(db, workspace_id=context.workspace.id).list_tools()}


@app.post("/api/agent/tools/{tool_name}/invoke")
async def invoke_agent_tool(tool_name: str, request: Request, db: Session = Depends(get_db), context: RequestContext = Depends(require_role("owner", "admin"))):
    arguments = await _json_or_empty(request)
    try:
        return AgentToolService(db, workspace_id=context.workspace.id).call_tool(tool_name, arguments)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@app.post("/mcp")
async def mcp_json_rpc(request: Request, db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context)):
    payload = await request.json()
    if isinstance(payload, list):
        return [_mcp_response(item, db, context) for item in payload]
    response = _mcp_response(payload, db, context)
    if response is None:
        return Response(status_code=202)
    return response


@app.get("/api/dashboard/summary", response_model=schemas.DashboardSummary)
def dashboard_summary(db: Session = Depends(get_db), context: RequestContext = Depends(get_current_context)):
    risks = db.scalars(select(models.RiskAssessment).where(workspace_filter(models.RiskAssessment, context.workspace.id)).order_by(desc(models.RiskAssessment.created_at)).limit(200)).all()
    pipelines = db.scalars(select(models.PipelineInsight).where(workspace_filter(models.PipelineInsight, context.workspace.id)).where(models.PipelineInsight.status == "failed").order_by(desc(models.PipelineInsight.created_at)).limit(200)).all()
    merge_requests = db.scalars(select(models.MergeRequestSignal).where(workspace_filter(models.MergeRequestSignal, context.workspace.id)).order_by(desc(models.MergeRequestSignal.created_at)).limit(200)).all()
    incidents = db.scalars(select(models.IncidentRecord).where(workspace_filter(models.IncidentRecord, context.workspace.id)).where(models.IncidentRecord.status == "open").order_by(desc(models.IncidentRecord.created_at)).limit(200)).all()
    recommendations = db.scalars(select(models.Recommendation).where(workspace_filter(models.Recommendation, context.workspace.id)).order_by(desc(models.Recommendation.created_at)).limit(100)).all()
    projects = db.scalars(select(models.GitLabProject).where(workspace_filter(models.GitLabProject, context.workspace.id)).order_by(desc(models.GitLabProject.synced_at)).limit(500)).all()
    latest_sync = db.scalars(
        select(models.ProjectSyncRun)
        .where(workspace_filter(models.ProjectSyncRun, context.workspace.id))
        .order_by(desc(models.ProjectSyncRun.started_at))
        .limit(1)
    ).first()

    visible_recommendations = _ranked_recommendations(db, recommendations)[:6]
    return {
        "active_risks": len(_latest_by([risk for risk in risks if _float_value(risk.score) >= 70], lambda risk: f"{_string_value(risk.project_path)}:{_string_value(risk.merge_request_iid or risk.deployment_ref)}:{_float_value(risk.score)}")),
        "failed_pipelines": len(_latest_by(pipelines, lambda item: f"{_string_value(item.project_path)}:{_string_value(item.pipeline_id)}:{_string_value(item.likely_cause)}")),
        "blocked_merge_requests": len(_latest_by([mr for mr in merge_requests if _string_value(mr.bottleneck_level) in {"blocked", "stale"}], lambda mr: f"{_string_value(mr.project_path)}:{_string_value(mr.merge_request_iid)}")),
        "open_incidents": len(_latest_by(incidents, lambda incident: f"{_string_value(incident.project_path)}:{_string_value(incident.title)}:{_string_value(incident.probable_root_cause)}")),
        "synced_projects": len(projects),
        "latest_project_sync": _shape_project_sync_run(latest_sync) if latest_sync else None,
        "latest_recommendations": visible_recommendations,
        "slack_status": _slack_status(db, context),
        "gitlab_status": OAuthService(db).gitlab_status(workspace_id=context.workspace.id),
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


async def _json_or_empty(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _mcp_response(payload: dict, db: Session, context: RequestContext | None = None) -> dict | None:
    request_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params") or {}
    workspace_id = context.workspace.id if context else None
    service = AgentToolService(db, workspace_id=workspace_id)

    if request_id is None and str(method).startswith("notifications/"):
        return None
    try:
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "panopticon", "version": "0.1.0"},
            }
        elif method == "tools/list":
            result = {"tools": service.list_mcp_tools()}
        elif method == "tools/call":
            tool_name = str(params.get("name") or "")
            result = mcp_text_result(service.call_tool(tool_name, params.get("arguments") or {}))
            _audit_mcp_tool_call(db, context, tool_name, params.get("arguments") or {}, success=True)
        else:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except LookupError as exc:
        if method == "tools/call":
            _audit_mcp_tool_call(db, context, str(params.get("name") or ""), params.get("arguments") or {}, success=False, error=str(exc))
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32004, "message": str(exc)}}
    except Exception as exc:
        if method == "tools/call":
            _audit_mcp_tool_call(db, context, str(params.get("name") or ""), params.get("arguments") or {}, success=False, error=str(exc))
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32603, "message": str(exc)}}


def _audit_mcp_tool_call(db: Session, context: RequestContext | None, tool_name: str, arguments: dict, *, success: bool, error: str = "") -> None:
    if context is None:
        return
    AuthService(db).audit(
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        event_type="agent.tool_call",
        target_type="mcp_tool",
        target_id=tool_name,
        metadata={
            "success": success,
            "error": error,
            "argument_keys": sorted(arguments.keys()) if isinstance(arguments, dict) else [],
            "runtime": "mcp",
        },
    )
    db.commit()


def _ranked_recommendations(db: Session, recommendations: list[models.Recommendation]) -> list[dict]:
    shaped = [_shape_recommendation(db, item) for item in _latest_by(recommendations, _recommendation_key)]
    return sorted(shaped, key=lambda item: (item["rank_score"], _datetime_sort_value(item["created_at"])), reverse=True)


def _shape_project_sync_run(record: models.ProjectSyncRun) -> dict:
    return {
        "id": record.id,
        "provider": _string_value(record.provider, fallback="gitlab"),
        "status": _string_value(record.status, fallback="unknown"),
        "projects_seen": _int_value(record.projects_seen),
        "projects_updated": _int_value(record.projects_updated),
        "merge_requests_seen": _int_value(record.merge_requests_seen),
        "pipelines_seen": _int_value(record.pipelines_seen),
        "jobs_seen": _int_value(record.jobs_seen),
        "error": _string_value(record.error),
        "started_at": record.started_at or datetime.now(timezone.utc),
        "finished_at": record.finished_at,
    }


def _shape_memory_record(record: models.MemoryRecord) -> dict:
    summary = _string_value(record.summary)
    evidence = _list_of_strings(record.evidence)
    remediation = _list_of_strings(record.remediation)
    if contains_failure_notice(summary):
        summary = (
            "This stale incomplete Gemini memory was hidden. "
            "Ask the question again and Panopticon will answer from current project context."
        )
    evidence = [item for item in evidence if not contains_failure_notice(item)]
    remediation = [item for item in remediation if not contains_failure_notice(item)]
    return {
        "id": record.id,
        "project_path": _string_value(record.project_path),
        "memory_type": _string_value(record.memory_type, fallback="memory"),
        "signature": _string_value(record.signature),
        "summary": summary,
        "evidence": evidence,
        "remediation": remediation,
        "created_at": record.created_at or datetime.now(timezone.utc),
    }


def _shape_chat_message(message: models.ChatMessage) -> dict:
    content = _string_value(message.content)
    if _string_value(message.role) == "assistant" and contains_failure_notice(content):
        content = (
            "This older incomplete Gemini response was removed from the visible chat history. "
            "Send the question again and Panopticon will answer from the current grounded project context."
        )
    return {
        "id": message.id,
        "thread_id": message.thread_id,
        "role": _string_value(message.role, fallback="assistant"),
        "content": content,
        "citations": message.citations if isinstance(message.citations, list) else [],
        "prepared_action_ids": message.prepared_action_ids if isinstance(message.prepared_action_ids, list) else [],
        "created_at": message.created_at or datetime.now(timezone.utc),
    }


def _list_of_strings(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_string_value(item) for item in value if _string_value(item)]
    if isinstance(value, tuple):
        return [_string_value(item) for item in value if _string_value(item)]
    if isinstance(value, dict):
        return [f"{_string_value(key)}: {_string_value(item)}" for key, item in value.items() if _string_value(key) or _string_value(item)]
    text = _string_value(value)
    return [text] if text else []


def _string_value(value, fallback: str = "") -> str:
    if value is None:
        return fallback
    if isinstance(value, str):
        return value.strip() or fallback
    return str(value).strip() or fallback


def _float_value(value, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _int_value(value, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _datetime_sort_value(value) -> datetime:
    return value if isinstance(value, datetime) else datetime.min.replace(tzinfo=timezone.utc)


def _get_project_or_404(db: Session, project_id: int, context: RequestContext) -> models.GitLabProject:
    project = db.get(models.GitLabProject, project_id)
    if not project or project.workspace_id != context.workspace.id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _agent_action_or_404(service: AgentActionService, action_id: int) -> models.AgentAction:
    try:
        return service.get(action_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Action not found") from None


def _recommendation_key(recommendation: models.Recommendation) -> str:
    return f"{recommendation.project_path}:{recommendation.source_type}:{recommendation.channel}:{_summary_part(recommendation.message)}"


def _shape_recommendation(db: Session, recommendation: models.Recommendation) -> dict:
    summary, gemini_analysis = _split_gemini(_string_value(recommendation.message))
    source = _source_context(db, recommendation)
    severity = _recommendation_severity(recommendation, source)
    confidence = _recommendation_confidence(recommendation, source, gemini_analysis)
    action_type = _recommendation_action_type(recommendation)
    can_execute = action_type in {"gitlab_comment", "slack_alert"}
    requires_approval = can_execute
    status = _string_value(recommendation.status, fallback="pending")
    rank_score = _recommendation_rank_score(severity, confidence, can_execute, status)
    return {
        "id": recommendation.id,
        "project_path": _string_value(recommendation.project_path),
        "source_type": _string_value(recommendation.source_type),
        "source_id": _string_value(recommendation.source_id),
        "channel": _string_value(recommendation.channel, fallback="dashboard"),
        "message": _string_value(recommendation.message),
        "title": _recommendation_title(recommendation),
        "summary": _clean_text(summary),
        "gemini_analysis": _clean_text(gemini_analysis),
        "evidence": source["evidence"],
        "next_actions": source["next_actions"],
        "origin": "demo" if _string_value(recommendation.project_path).startswith("demo/") else "gitlab",
        "severity": severity,
        "confidence": confidence,
        "action_type": action_type,
        "can_execute": can_execute,
        "requires_approval": requires_approval,
        "approval_state": _approval_state(status, requires_approval),
        "rank_score": rank_score,
        "status": status,
        "created_at": recommendation.created_at or datetime.now(timezone.utc),
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
    source_type = _string_value(recommendation.source_type)
    if source_type == "risk":
        return "Deployment risk detected"
    if source_type == "pipeline":
        return "Pipeline failure detected"
    if source_type == "incident":
        return "Incident intelligence generated"
    return "Operational recommendation"


def _source_context(db: Session, recommendation: models.Recommendation) -> dict:
    evidence: list[str] = []
    next_actions: list[str] = []
    source = None
    source_id = _safe_int(recommendation.source_id)
    source_type = _string_value(recommendation.source_type)
    if source_type == "risk" and source_id:
        risk = db.get(models.RiskAssessment, source_id)
        if risk:
            source = risk
            evidence = _list_of_strings(risk.reasons)
            next_actions = _list_of_strings(risk.recommendations)
    elif source_type == "pipeline" and source_id:
        pipeline = db.get(models.PipelineInsight, source_id)
        if pipeline:
            source = pipeline
            evidence = _list_of_strings(pipeline.evidence)
            next_actions = _list_of_strings(pipeline.recommendations)
    elif source_type == "incident" and source_id:
        incident = db.get(models.IncidentRecord, source_id)
        if incident:
            source = incident
            evidence = _list_of_strings([entry.get("event", "") for entry in incident.timeline if isinstance(entry, dict)])
            next_actions = _list_of_strings(incident.recommendations)
    return {"source": source, "evidence": evidence, "next_actions": next_actions}


def _recommendation_severity(recommendation: models.Recommendation, source: dict) -> str:
    source_record = source.get("source")
    if isinstance(source_record, models.RiskAssessment):
        risk_score = _float_value(source_record.score)
        risk_level = _string_value(source_record.level)
        if risk_score >= 85 or risk_level == "critical":
            return "critical"
        if risk_score >= 70 or risk_level == "high":
            return "high"
        if risk_score >= 40 or risk_level == "medium":
            return "medium"
        return "low"
    if isinstance(source_record, models.PipelineInsight):
        return "high" if _string_value(source_record.status) == "failed" else "medium"
    if isinstance(source_record, models.IncidentRecord):
        severity = _string_value(source_record.severity)
        if severity in {"critical", "high"}:
            return severity
        return "medium"
    source_type = _string_value(recommendation.source_type)
    if source_type == "risk":
        return "high"
    if source_type in {"pipeline", "incident"}:
        return "medium"
    return "info"


def _recommendation_confidence(recommendation: models.Recommendation, source: dict, gemini_analysis: str) -> float:
    evidence_count = len(source.get("evidence", []))
    action_count = len(source.get("next_actions", []))
    base = 0.5
    if source.get("source"):
        base += 0.18
    if gemini_analysis:
        base += 0.08
    if _string_value(recommendation.status) in {"sent", "dry_run", "queued"}:
        base += 0.04
    base += min(evidence_count, 4) * 0.05
    base += min(action_count, 3) * 0.03
    source_record = source.get("source")
    if isinstance(source_record, models.RiskAssessment):
        base += min(_float_value(source_record.score), 100) / 500
    return round(min(base, 0.97), 2)


def _recommendation_action_type(recommendation: models.Recommendation) -> str:
    channel = _string_value(recommendation.channel)
    source_type = _string_value(recommendation.source_type)
    if channel == "gitlab_comment":
        return "gitlab_comment"
    if channel == "slack":
        return "slack_alert"
    if source_type == "pipeline":
        return "pipeline_investigation"
    if source_type == "risk":
        return "review_gate"
    if source_type == "incident":
        return "incident_followup"
    return "dashboard_note"


def _approval_state(status: str, requires_approval: bool) -> str:
    if not requires_approval:
        return "not_required"
    if status == "sent":
        return "executed"
    if status == "failed":
        return "failed"
    if status == "dry_run":
        return "dry_run_ready"
    if status == "queued":
        return "pending_approval"
    return "pending_approval"


def _recommendation_rank_score(severity: str, confidence: float, can_execute: bool, status: str) -> float:
    severity_weight = {
        "critical": 100,
        "high": 80,
        "medium": 55,
        "low": 30,
        "info": 10,
    }.get(severity, 10)
    status_weight = {
        "failed": 8,
        "dry_run": 6,
        "queued": 4,
        "pending": 4,
        "sent": -10,
    }.get(status, 0)
    executable_weight = 6 if can_execute else 0
    return round(severity_weight + (confidence * 20) + executable_weight + status_weight, 2)


def _safe_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _attach_created_records(db: Session, workspace_id: int) -> None:
    for model in (
        models.OperationalEvent,
        models.WebhookReceipt,
        models.RiskAssessment,
        models.PipelineInsight,
        models.MergeRequestSignal,
        models.IncidentRecord,
        models.Recommendation,
        models.ActionDispatch,
        models.MemoryRecord,
    ):
        for record in db.scalars(select(model).where(model.workspace_id.is_(None)).limit(200)).all():
            assign_workspace(record, workspace_id)
    db.commit()


def _slack_status(db: Session, context: RequestContext | None = None) -> dict:
    stmt = select(models.ActionDispatch).where(models.ActionDispatch.channel == "slack")
    if context is not None:
        stmt = stmt.where(workspace_filter(models.ActionDispatch, context.workspace.id))
    last_dispatch = db.scalars(stmt.order_by(desc(models.ActionDispatch.created_at)).limit(1)).first()
    oauth_status = OAuthService(db).slack_status(workspace_id=context.workspace.id) if context is not None else {}
    oauth_connected = bool(oauth_status.get("connected"))
    oauth_configured = bool(oauth_status.get("configured"))
    return {
        "configured": bool(settings.slack_webhook_url or settings.slack_bot_token or settings.slack_signing_secret or oauth_connected or oauth_configured),
        "webhook_configured": bool(settings.slack_webhook_url),
        "bot_token_configured": bool(settings.slack_bot_token),
        "signing_secret_configured": bool(settings.slack_signing_secret),
        "default_channel_configured": bool(settings.slack_default_channel),
        "default_channel": settings.slack_default_channel,
        "oauth_configured": oauth_configured,
        "oauth_connected": oauth_connected,
        "oauth_account_label": oauth_status.get("account_label", ""),
        "oauth_channel": oauth_status.get("channel", ""),
        "mode": "dry_run" if settings.dry_run_actions else "live",
        "last_status": last_dispatch.status if last_dispatch else "none",
        "last_error": last_dispatch.error if last_dispatch else "",
        "last_checked_at": last_dispatch.created_at if last_dispatch else None,
    }
