import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import models
from app.config import get_settings
from app.database import get_db


PBKDF2_ITERATIONS = 210_000
SESSION_COOKIE_SAMESITE = "lax"


@dataclass(frozen=True)
class RequestContext:
    user: models.User
    workspace: models.Workspace
    role: str
    session: models.UserSession | None = None


SCOPED_MODELS = (
    models.OperationalEvent,
    models.WebhookReceipt,
    models.GitLabProject,
    models.ProjectSyncRun,
    models.RepoIndexRun,
    models.RepoFileIndex,
    models.MergeRequestSnapshot,
    models.PipelineSnapshot,
    models.JobSnapshot,
    models.RiskAssessment,
    models.PipelineInsight,
    models.MergeRequestSignal,
    models.IncidentRecord,
    models.ObservabilityEvent,
    models.IncidentCorrelation,
    models.EngineeringMetricSnapshot,
    models.Recommendation,
    models.ActionDispatch,
    models.AgentAction,
    models.ActionApproval,
    models.OAuthConnection,
    models.FixPlan,
    models.FixPlanApproval,
    models.ChatThread,
    models.ChatMessage,
    models.MemoryRecord,
)


class AuthService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()

    def signup(self, *, email: str, password: str, name: str = "", workspace_name: str = "") -> tuple[models.UserSession, str]:
        normalized = _normalize_email(email)
        if not normalized:
            raise ValueError("email is required")
        if len(password) < 8:
            raise ValueError("password must be at least 8 characters")
        existing = self.db.scalar(select(models.User).where(models.User.email == normalized))
        if existing:
            raise ValueError("email is already registered")

        user = models.User(email=normalized, name=name.strip() or normalized.split("@", 1)[0], password_hash=hash_password(password))
        self.db.add(user)
        self.db.flush()

        slug = unique_workspace_slug(self.db, workspace_name or user.name or "workspace")
        workspace = models.Workspace(name=(workspace_name.strip() or f"{user.name}'s Workspace"), slug=slug)
        self.db.add(workspace)
        self.db.flush()

        self.db.add(models.WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
        session, raw_token = self.create_session(user=user, workspace=workspace)
        self.audit(workspace_id=workspace.id, user_id=user.id, event_type="auth.signup", target_type="user", target_id=str(user.id))
        self.db.commit()
        return session, raw_token

    def login(self, *, email: str, password: str) -> tuple[models.UserSession, str]:
        normalized = _normalize_email(email)
        user = self.db.scalar(select(models.User).where(models.User.email == normalized))
        if not user or not user.is_active or not verify_password(password, user.password_hash):
            raise PermissionError("invalid email or password")
        membership = self.db.scalar(select(models.WorkspaceMember).where(models.WorkspaceMember.user_id == user.id).order_by(models.WorkspaceMember.id))
        if not membership:
            raise PermissionError("user has no workspace")
        workspace = self.db.get(models.Workspace, membership.workspace_id)
        if not workspace:
            raise PermissionError("workspace not found")
        session, raw_token = self.create_session(user=user, workspace=workspace)
        self.audit(workspace_id=workspace.id, user_id=user.id, event_type="auth.login", target_type="user", target_id=str(user.id))
        self.db.commit()
        return session, raw_token

    def logout(self, token: str | None) -> None:
        if not token:
            return
        session = self.db.scalar(select(models.UserSession).where(models.UserSession.token_hash == token_hash(token)))
        if session and not session.revoked_at:
            session.revoked_at = now()
            self.audit(workspace_id=session.workspace_id, user_id=session.user_id, event_type="auth.logout", target_type="session", target_id=str(session.id))
            self.db.commit()

    def create_session(self, *, user: models.User, workspace: models.Workspace) -> tuple[models.UserSession, str]:
        raw_token = secrets.token_urlsafe(48)
        session = models.UserSession(
            user_id=user.id,
            workspace_id=workspace.id,
            token_hash=token_hash(raw_token),
            expires_at=now() + timedelta(hours=self.settings.session_ttl_hours),
        )
        self.db.add(session)
        self.db.flush()
        return session, raw_token

    def context_from_token(self, token: str) -> RequestContext | None:
        session = self.db.scalar(select(models.UserSession).where(models.UserSession.token_hash == token_hash(token)))
        if not session or session.revoked_at or _as_aware(session.expires_at) <= now():
            return None
        user = self.db.get(models.User, session.user_id)
        workspace = self.db.get(models.Workspace, session.workspace_id)
        if not user or not user.is_active or not workspace:
            return None
        membership = self.db.scalar(
            select(models.WorkspaceMember)
            .where(models.WorkspaceMember.user_id == user.id)
            .where(models.WorkspaceMember.workspace_id == workspace.id)
        )
        if not membership:
            return None
        return RequestContext(user=user, workspace=workspace, role=membership.role, session=session)

    def local_dev_context(self) -> RequestContext:
        slug = self.settings.default_workspace_slug
        user = self.db.scalar(select(models.User).where(models.User.email == "local@panopticon.dev"))
        if not user:
            user = models.User(email="local@panopticon.dev", name="Local Developer", password_hash="")
            self.db.add(user)
            self.db.flush()
        workspace = self.db.scalar(select(models.Workspace).where(models.Workspace.slug == slug))
        if not workspace:
            workspace = models.Workspace(name="Local Development", slug=slug)
            self.db.add(workspace)
            self.db.flush()
        membership = self.db.scalar(
            select(models.WorkspaceMember)
            .where(models.WorkspaceMember.user_id == user.id)
            .where(models.WorkspaceMember.workspace_id == workspace.id)
        )
        if not membership:
            membership = models.WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner")
            self.db.add(membership)
            self.db.flush()
        self.db.commit()
        return RequestContext(user=user, workspace=workspace, role=membership.role, session=None)

    def agent_runtime_context(self) -> RequestContext:
        slug = self.settings.agent_runtime_workspace_slug or self.settings.default_workspace_slug
        email = _normalize_email(self.settings.agent_runtime_user_email or "agent@panopticon.dev")
        user = self.db.scalar(select(models.User).where(models.User.email == email))
        if not user:
            user = models.User(email=email, name="Panopticon Agent Runtime", password_hash="")
            self.db.add(user)
            self.db.flush()
        workspace = self.db.scalar(select(models.Workspace).where(models.Workspace.slug == slug))
        if not workspace:
            workspace = models.Workspace(name="Agent Runtime Workspace", slug=slug)
            self.db.add(workspace)
            self.db.flush()
        membership = self.db.scalar(
            select(models.WorkspaceMember)
            .where(models.WorkspaceMember.user_id == user.id)
            .where(models.WorkspaceMember.workspace_id == workspace.id)
        )
        if not membership:
            membership = models.WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="admin")
            self.db.add(membership)
            self.db.flush()
        self.db.commit()
        return RequestContext(user=user, workspace=workspace, role=membership.role, session=None)

    def audit(self, *, workspace_id: int | None, user_id: int | None, event_type: str, target_type: str = "", target_id: str = "", metadata: dict | None = None) -> models.AuditLog:
        entry = models.AuditLog(
            workspace_id=workspace_id,
            user_id=user_id,
            event_type=event_type,
            target_type=target_type,
            target_id=target_id,
            metadata_json=metadata or {},
        )
        self.db.add(entry)
        self.db.flush()
        return entry


def get_current_context(request: Request, db: Session = Depends(get_db)) -> RequestContext:
    settings = get_settings()
    service = AuthService(db)
    bearer_token = _bearer_token(request)
    cookie_token = request.cookies.get(settings.session_cookie_name)
    if _is_agent_runtime_token(settings.agent_runtime_token, bearer_token):
        context = service.agent_runtime_context()
    else:
        token = cookie_token or bearer_token
        context = service.context_from_token(token) if token else None
    if context is None:
        if settings.auth_required:
            raise HTTPException(status_code=401, detail="Authentication required")
        context = service.local_dev_context()
    attach_unscoped_records(db, context.workspace.id)
    return context


def require_role(*roles: str):
    allowed = set(roles)

    def dependency(context: RequestContext = Depends(get_current_context)) -> RequestContext:
        if context.role not in allowed:
            raise HTTPException(status_code=403, detail="Insufficient workspace role")
        return context

    return dependency


def set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.is_production,
        samesite=SESSION_COOKIE_SAMESITE,
    )


def clear_session_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(key=settings.session_cookie_name, httponly=True, secure=settings.is_production, samesite=SESSION_COOKIE_SAMESITE)


def workspace_filter(model, workspace_id: int):
    return model.workspace_id == workspace_id


def assign_workspace(record, workspace_id: int):
    if hasattr(record, "workspace_id") and getattr(record, "workspace_id", None) is None:
        setattr(record, "workspace_id", workspace_id)


def attach_unscoped_records(db: Session, workspace_id: int) -> None:
    for model in SCOPED_MODELS:
        db.execute(update(model).where(model.workspace_id.is_(None)).values(workspace_id=workspace_id))
    db.commit()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations)).hex()
    return hmac.compare_digest(digest, expected)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def unique_workspace_slug(db: Session, name: str) -> str:
    base = slugify(name) or "workspace"
    candidate = base
    suffix = 2
    while db.scalar(select(models.Workspace).where(models.Workspace.slug == candidate)):
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def slugify(value: str) -> str:
    chars = [ch.lower() if ch.isalnum() else "-" for ch in value.strip()]
    slug = "".join(chars).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug[:80]


def now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _bearer_token(request: Request) -> str:
    value = request.headers.get("Authorization", "")
    if value.lower().startswith("bearer "):
        return value.split(" ", 1)[1].strip()
    return ""


def _is_agent_runtime_token(expected: str, actual: str) -> bool:
    return bool(expected and actual and hmac.compare_digest(expected, actual))
