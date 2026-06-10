from __future__ import annotations

import base64
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.config import Settings, get_settings
from app.integrations.gitlab import GitLabClient
from app.services.auth import AuthService, token_hash, unique_workspace_slug


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_SCOPES = ["openid", "email", "profile"]
GITLAB_SCOPES = ["api", "read_user"]
SLACK_SCOPES = ["incoming-webhook", "commands", "chat:write"]


@dataclass(frozen=True)
class OAuthCallbackResult:
    session_token: str | None = None
    redirect_url: str = "/"


class OAuthService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()

    def google_configured(self) -> bool:
        return bool(self.settings.google_oauth_client_id and self.settings.google_oauth_client_secret)

    def gitlab_configured(self) -> bool:
        return bool(self.settings.gitlab_oauth_client_id and self.settings.gitlab_oauth_client_secret)

    def slack_configured(self) -> bool:
        return bool(self.settings.slack_oauth_client_id and self.settings.slack_oauth_client_secret)

    def google_auth_url(self, *, redirect_after: str = "/") -> str:
        if not self.google_configured():
            raise ValueError("Google OAuth is not configured")
        state = self._create_state(provider="google", redirect_after=redirect_after)
        params = {
            "client_id": self.settings.google_oauth_client_id,
            "redirect_uri": google_redirect_uri(self.settings),
            "response_type": "code",
            "scope": " ".join(GOOGLE_SCOPES),
            "state": state,
            "access_type": "offline",
            "prompt": "select_account",
        }
        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    def gitlab_auth_url(self, *, user_id: int, workspace_id: int, redirect_after: str = "/projects") -> str:
        if not self.gitlab_configured():
            raise ValueError("GitLab OAuth is not configured")
        state = self._create_state(provider="gitlab", user_id=user_id, workspace_id=workspace_id, redirect_after=redirect_after)
        params = {
            "client_id": self.settings.gitlab_oauth_client_id,
            "redirect_uri": gitlab_redirect_uri(self.settings),
            "response_type": "code",
            "scope": " ".join(self.settings.gitlab_oauth_scopes or GITLAB_SCOPES),
            "state": state,
        }
        return f"{self.settings.gitlab_base_url.rstrip('/')}/oauth/authorize?{urlencode(params)}"

    def slack_auth_url(self, *, user_id: int, workspace_id: int, redirect_after: str = "/") -> str:
        if not self.slack_configured():
            raise ValueError("Slack OAuth is not configured")
        state = self._create_state(provider="slack", user_id=user_id, workspace_id=workspace_id, redirect_after=redirect_after)
        params = {
            "client_id": self.settings.slack_oauth_client_id,
            "redirect_uri": slack_redirect_uri(self.settings),
            "scope": ",".join(SLACK_SCOPES),
            "state": state,
        }
        return f"https://slack.com/oauth/v2/authorize?{urlencode(params)}"

    def complete_google_callback(self, *, code: str, state: str) -> OAuthCallbackResult:
        state_record = self._consume_state(provider="google", state=state)
        token_payload = self._exchange_google_code(code)
        access_token = str(token_payload.get("access_token") or "")
        if not access_token:
            raise ValueError("Google did not return an access token")
        userinfo = self._google_userinfo(access_token)
        email = str(userinfo.get("email") or "").strip().lower()
        if not email:
            raise ValueError("Google account did not include an email address")

        user = self.db.scalar(select(models.User).where(models.User.email == email))
        if not user:
            user = models.User(email=email, name=str(userinfo.get("name") or email.split("@", 1)[0]), password_hash="")
            self.db.add(user)
            self.db.flush()

        membership = self.db.scalar(select(models.WorkspaceMember).where(models.WorkspaceMember.user_id == user.id).order_by(models.WorkspaceMember.id))
        if membership:
            workspace = self.db.get(models.Workspace, membership.workspace_id)
        else:
            workspace_name = f"{user.name or email}'s Workspace"
            workspace = models.Workspace(name=workspace_name, slug=unique_workspace_slug(self.db, workspace_name))
            self.db.add(workspace)
            self.db.flush()
            self.db.add(models.WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
            self.db.flush()

        if not workspace:
            raise ValueError("Could not resolve workspace")

        self._upsert_connection(
            provider="google",
            user_id=user.id,
            workspace_id=workspace.id,
            provider_user_id=str(userinfo.get("sub") or ""),
            account_label=email,
            token_payload=token_payload,
            metadata={"email": email, "name": userinfo.get("name") or "", "picture": userinfo.get("picture") or ""},
            scopes=GOOGLE_SCOPES,
        )
        session, raw_token = AuthService(self.db).create_session(user=user, workspace=workspace)
        AuthService(self.db).audit(workspace_id=workspace.id, user_id=user.id, event_type="auth.google_login", target_type="session", target_id=str(session.id))
        self.db.commit()
        return OAuthCallbackResult(session_token=raw_token, redirect_url=state_record.redirect_after or "/")

    def complete_gitlab_callback(self, *, code: str, state: str) -> OAuthCallbackResult:
        state_record = self._consume_state(provider="gitlab", state=state)
        if not state_record.user_id or not state_record.workspace_id:
            raise ValueError("GitLab OAuth state was not linked to a workspace")
        token_payload = self._exchange_gitlab_code(code)
        access_token = str(token_payload.get("access_token") or "")
        if not access_token:
            raise ValueError("GitLab did not return an access token")
        profile = self._gitlab_userinfo(access_token)
        username = str(profile.get("username") or profile.get("name") or "GitLab user")
        self._upsert_connection(
            provider="gitlab",
            user_id=state_record.user_id,
            workspace_id=state_record.workspace_id,
            provider_user_id=str(profile.get("id") or ""),
            account_label=username,
            token_payload=token_payload,
            metadata={"username": username, "name": profile.get("name") or "", "web_url": profile.get("web_url") or ""},
            scopes=str(token_payload.get("scope") or " ".join(self.settings.gitlab_oauth_scopes or GITLAB_SCOPES)).split(),
        )
        AuthService(self.db).audit(
            workspace_id=state_record.workspace_id,
            user_id=state_record.user_id,
            event_type="integrations.gitlab.connected",
            target_type="oauth_connection",
            target_id="gitlab",
            metadata={"account_label": username},
        )
        self.db.commit()
        return OAuthCallbackResult(redirect_url=state_record.redirect_after or "/projects")

    def complete_slack_callback(self, *, code: str, state: str) -> OAuthCallbackResult:
        state_record = self._consume_state(provider="slack", state=state)
        if not state_record.user_id or not state_record.workspace_id:
            raise ValueError("Slack OAuth state was not linked to a workspace")
        token_payload = self._exchange_slack_code(code)
        if not token_payload.get("ok", True):
            raise ValueError(str(token_payload.get("error") or "Slack OAuth failed"))
        access_token = str(token_payload.get("access_token") or "")
        incoming_webhook = token_payload.get("incoming_webhook") or {}
        team = token_payload.get("team") or {}
        account_label = str(team.get("name") or incoming_webhook.get("channel") or "Slack workspace")
        scopes = str(token_payload.get("scope") or ",".join(SLACK_SCOPES)).replace(",", " ").split()
        self._upsert_connection(
            provider="slack",
            user_id=state_record.user_id,
            workspace_id=state_record.workspace_id,
            provider_user_id=str(team.get("id") or ""),
            account_label=account_label,
            token_payload={"access_token": access_token},
            metadata={
                "team": team,
                "bot_user_id": token_payload.get("bot_user_id") or "",
                "incoming_webhook": incoming_webhook,
                "authed_user": token_payload.get("authed_user") or {},
            },
            scopes=scopes,
        )
        AuthService(self.db).audit(
            workspace_id=state_record.workspace_id,
            user_id=state_record.user_id,
            event_type="integrations.slack.connected",
            target_type="oauth_connection",
            target_id="slack",
            metadata={"account_label": account_label, "channel": incoming_webhook.get("channel") or ""},
        )
        self.db.commit()
        return OAuthCallbackResult(redirect_url=state_record.redirect_after or "/")

    def gitlab_status(self, *, workspace_id: int) -> dict:
        connection = gitlab_connection(self.db, workspace_id)
        return {
            "provider": "gitlab",
            "configured": self.gitlab_configured(),
            "connected": bool(connection),
            "account_label": connection.account_label if connection else "",
            "scopes": _scope_list(connection.scopes) if connection else [],
            "expires_at": connection.expires_at if connection else None,
            "base_url": self.settings.gitlab_base_url.rstrip("/"),
        }

    def slack_status(self, *, workspace_id: int) -> dict:
        connection = slack_connection(self.db, workspace_id)
        webhook = ((connection.metadata_json or {}).get("incoming_webhook") or {}) if connection else {}
        return {
            "provider": "slack",
            "configured": self.slack_configured(),
            "connected": bool(connection),
            "account_label": connection.account_label if connection else "",
            "scopes": _scope_list(connection.scopes) if connection else [],
            "expires_at": connection.expires_at if connection else None,
            "base_url": "https://slack.com",
            "channel": webhook.get("channel") or "",
        }

    def gitlab_access_token(self, *, workspace_id: int) -> str:
        connection = gitlab_connection(self.db, workspace_id)
        if not connection:
            return ""
        if connection.expires_at and _as_aware(connection.expires_at) <= _now() + timedelta(minutes=2):
            self._refresh_gitlab_connection(connection)
        return decrypt_token(connection.access_token_encrypted, self.settings)

    def _create_state(self, *, provider: str, user_id: int | None = None, workspace_id: int | None = None, redirect_after: str = "/") -> str:
        raw_state = secrets.token_urlsafe(32)
        record = models.OAuthState(
            provider=provider,
            state_hash=token_hash(raw_state),
            user_id=user_id,
            workspace_id=workspace_id,
            redirect_after=_safe_redirect(redirect_after, self.settings),
            expires_at=_now() + timedelta(minutes=self.settings.oauth_state_ttl_minutes),
        )
        self.db.add(record)
        self.db.commit()
        return raw_state

    def _consume_state(self, *, provider: str, state: str) -> models.OAuthState:
        record = self.db.scalar(select(models.OAuthState).where(models.OAuthState.provider == provider).where(models.OAuthState.state_hash == token_hash(state)))
        if not record or record.consumed_at or _as_aware(record.expires_at) <= _now():
            raise ValueError("OAuth state is invalid or expired")
        record.consumed_at = _now()
        self.db.flush()
        return record

    def _exchange_google_code(self, code: str) -> dict:
        with httpx.Client(timeout=20) as client:
            response = client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": self.settings.google_oauth_client_id,
                    "client_secret": self.settings.google_oauth_client_secret,
                    "redirect_uri": google_redirect_uri(self.settings),
                    "grant_type": "authorization_code",
                },
            )
            response.raise_for_status()
            return response.json()

    def _exchange_slack_code(self, code: str) -> dict:
        with httpx.Client(timeout=20) as client:
            response = client.post(
                "https://slack.com/api/oauth.v2.access",
                data={
                    "code": code,
                    "client_id": self.settings.slack_oauth_client_id,
                    "client_secret": self.settings.slack_oauth_client_secret,
                    "redirect_uri": slack_redirect_uri(self.settings),
                },
            )
            response.raise_for_status()
            return response.json()

    def _exchange_gitlab_code(self, code: str) -> dict:
        with httpx.Client(timeout=20) as client:
            response = client.post(
                f"{self.settings.gitlab_base_url.rstrip('/')}/oauth/token",
                data={
                    "code": code,
                    "client_id": self.settings.gitlab_oauth_client_id,
                    "client_secret": self.settings.gitlab_oauth_client_secret,
                    "redirect_uri": gitlab_redirect_uri(self.settings),
                    "grant_type": "authorization_code",
                },
            )
            response.raise_for_status()
            return response.json()

    def _google_userinfo(self, access_token: str) -> dict:
        with httpx.Client(timeout=20) as client:
            response = client.get(GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
            response.raise_for_status()
            return response.json()

    def _gitlab_userinfo(self, access_token: str) -> dict:
        with httpx.Client(timeout=20) as client:
            response = client.get(f"{self.settings.gitlab_base_url.rstrip('/')}/api/v4/user", headers={"Authorization": f"Bearer {access_token}"})
            response.raise_for_status()
            return response.json()

    def _refresh_gitlab_connection(self, connection: models.OAuthConnection) -> None:
        refresh_token = decrypt_token(connection.refresh_token_encrypted, self.settings)
        if not refresh_token:
            return
        with httpx.Client(timeout=20) as client:
            response = client.post(
                f"{self.settings.gitlab_base_url.rstrip('/')}/oauth/token",
                data={
                    "client_id": self.settings.gitlab_oauth_client_id,
                    "client_secret": self.settings.gitlab_oauth_client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            response.raise_for_status()
            token_payload = response.json()
        self._apply_tokens(connection, token_payload, scopes=str(token_payload.get("scope") or "").split() or _scope_list(connection.scopes))
        self.db.commit()

    def _upsert_connection(
        self,
        *,
        provider: str,
        user_id: int,
        workspace_id: int,
        provider_user_id: str,
        account_label: str,
        token_payload: dict,
        metadata: dict,
        scopes: list[str],
    ) -> models.OAuthConnection:
        stmt = (
            select(models.OAuthConnection)
            .where(models.OAuthConnection.provider == provider)
            .where(models.OAuthConnection.workspace_id == workspace_id)
            .where(models.OAuthConnection.user_id == user_id)
        )
        connection = self.db.scalar(stmt)
        if not connection:
            connection = models.OAuthConnection(provider=provider, workspace_id=workspace_id, user_id=user_id)
            self.db.add(connection)
        connection.provider_user_id = provider_user_id
        connection.account_label = account_label
        connection.metadata_json = metadata
        self._apply_tokens(connection, token_payload, scopes=scopes)
        self.db.flush()
        return connection

    def _apply_tokens(self, connection: models.OAuthConnection, token_payload: dict, *, scopes: list[str]) -> None:
        connection.access_token_encrypted = encrypt_token(str(token_payload.get("access_token") or ""), self.settings)
        refresh_token = str(token_payload.get("refresh_token") or "")
        if refresh_token:
            connection.refresh_token_encrypted = encrypt_token(refresh_token, self.settings)
        expires_in = token_payload.get("expires_in")
        connection.expires_at = _now() + timedelta(seconds=int(expires_in)) if expires_in else None
        connection.scopes = scopes
        connection.updated_at = _now()


def gitlab_connection(db: Session, workspace_id: int) -> models.OAuthConnection | None:
    return db.scalar(
        select(models.OAuthConnection)
        .where(models.OAuthConnection.provider == "gitlab")
        .where(models.OAuthConnection.workspace_id == workspace_id)
        .order_by(models.OAuthConnection.updated_at.desc())
    )


def slack_connection(db: Session, workspace_id: int) -> models.OAuthConnection | None:
    return db.scalar(
        select(models.OAuthConnection)
        .where(models.OAuthConnection.provider == "slack")
        .where(models.OAuthConnection.workspace_id == workspace_id)
        .order_by(models.OAuthConnection.updated_at.desc())
    )


def slack_credentials_for_workspace(db: Session, workspace_id: int | None) -> dict:
    if workspace_id is None:
        return {}
    connection = slack_connection(db, workspace_id)
    if not connection:
        return {}
    metadata = connection.metadata_json or {}
    incoming_webhook = metadata.get("incoming_webhook") or {}
    return {
        "webhook_url": incoming_webhook.get("url") or "",
        "bot_token": decrypt_token(connection.access_token_encrypted),
        "channel": incoming_webhook.get("channel") or "",
    }


def gitlab_client_for_workspace(db: Session, workspace_id: int | None) -> GitLabClient:
    if workspace_id is None:
        return GitLabClient()
    token = OAuthService(db).gitlab_access_token(workspace_id=workspace_id)
    if token:
        return GitLabClient(access_token=token, auth_mode="bearer")
    return GitLabClient()


def encrypt_token(token: str, settings: Settings | None = None) -> str:
    if not token:
        return ""
    cipher = _fernet(settings or get_settings())
    if not cipher:
        return f"plain:{token}"
    return "fernet:" + cipher.encrypt(token.encode("utf-8")).decode("utf-8")


def decrypt_token(value: str, settings: Settings | None = None) -> str:
    if not value:
        return ""
    if value.startswith("plain:"):
        return value.removeprefix("plain:")
    if not value.startswith("fernet:"):
        return value
    cipher = _fernet(settings or get_settings())
    if not cipher:
        return ""
    try:
        return cipher.decrypt(value.removeprefix("fernet:").encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return ""


def google_redirect_uri(settings: Settings) -> str:
    return settings.google_oauth_redirect_uri or f"{settings.app_api_url.rstrip('/')}/api/auth/google/callback"


def gitlab_redirect_uri(settings: Settings) -> str:
    return settings.gitlab_oauth_redirect_uri or f"{settings.app_api_url.rstrip('/')}/api/integrations/gitlab/callback"


def slack_redirect_uri(settings: Settings) -> str:
    return settings.slack_oauth_redirect_uri or f"{settings.app_api_url.rstrip('/')}/api/integrations/slack/callback"


def _fernet(settings: Settings) -> Fernet | None:
    key = settings.oauth_token_encryption_key.strip()
    if not key:
        if settings.is_production:
            return None
        key = base64.urlsafe_b64encode(b"panopticon-local-dev-oauth-key-32"[:32]).decode("utf-8")
    try:
        return Fernet(key.encode("utf-8"))
    except ValueError:
        return None


def _safe_redirect(value: str, settings: Settings) -> str:
    if not value:
        return "/"
    if value.startswith("/"):
        return value
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "/"
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if origin not in (settings.allowed_origins or []):
        return "/"
    return value


def _scope_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.replace(",", " ").split() if item.strip()]
    return [str(value).strip()] if str(value).strip() else []


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
