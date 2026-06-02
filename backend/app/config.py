import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return int(value)


def _csv_env(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    app_name: str = "Panopticon"
    app_env: str = "development"
    app_api_url: str = "http://localhost:8000"
    app_public_url: str = "http://localhost:3000"
    database_url: str = "sqlite:///./panopticon.db"
    allowed_origins: list[str] | None = None
    db_pool_size: int = 5
    db_max_overflow: int = 10
    auth_required: bool = False
    session_cookie_name: str = "panopticon_session"
    session_ttl_hours: int = 168
    default_workspace_slug: str = "local-dev"
    agent_runtime_token: str = ""
    agent_runtime_workspace_slug: str = "local-dev"
    agent_runtime_user_email: str = "agent@panopticon.dev"
    gitlab_webhook_secret: str = ""
    gitlab_base_url: str = "https://gitlab.com"
    gitlab_token: str = ""
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_uri: str = ""
    gitlab_oauth_client_id: str = ""
    gitlab_oauth_client_secret: str = ""
    gitlab_oauth_redirect_uri: str = ""
    gitlab_oauth_scopes: list[str] | None = None
    oauth_token_encryption_key: str = ""
    oauth_state_ttl_minutes: int = 15
    slack_webhook_url: str = ""
    slack_signing_secret: str = ""
    slack_bot_token: str = ""
    slack_default_channel: str = ""
    slack_oauth_client_id: str = ""
    slack_oauth_client_secret: str = ""
    slack_oauth_redirect_uri: str = ""
    dry_run_actions: bool = True
    dispatch_actions: bool = True
    repo_index_on_sync: bool = True
    repo_index_file_limit: int = 80
    repo_index_max_file_bytes: int = 20000
    gemini_enabled: bool = False
    gemini_model: str = "gemini-2.5-pro"
    gemini_api_key: str = ""
    google_genai_use_vertexai: bool = False
    google_cloud_project: str = ""
    google_cloud_location: str = "global"

    def __post_init__(self) -> None:
        if self.allowed_origins is None:
            object.__setattr__(self, "allowed_origins", ["http://localhost:3000", "http://127.0.0.1:3000"])
        if self.gitlab_oauth_scopes is None:
            object.__setattr__(self, "gitlab_oauth_scopes", ["api", "read_user"])

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    def validate_for_startup(self) -> None:
        if not self.is_production:
            return

        missing: list[str] = []
        if self.database_url.startswith("sqlite"):
            missing.append("DATABASE_URL must use PostgreSQL in production")
        if not self.gitlab_webhook_secret:
            missing.append("GITLAB_WEBHOOK_SECRET")
        if not self.gitlab_token and not (self.gitlab_oauth_client_id and self.gitlab_oauth_client_secret):
            missing.append("GITLAB_TOKEN or GitLab OAuth credentials")
        if not self.google_oauth_client_id:
            missing.append("GOOGLE_OAUTH_CLIENT_ID")
        if not self.google_oauth_client_secret:
            missing.append("GOOGLE_OAUTH_CLIENT_SECRET")
        if not self.gitlab_oauth_client_id:
            missing.append("GITLAB_OAUTH_CLIENT_ID")
        if not self.gitlab_oauth_client_secret:
            missing.append("GITLAB_OAUTH_CLIENT_SECRET")
        if not self.oauth_token_encryption_key:
            missing.append("OAUTH_TOKEN_ENCRYPTION_KEY")
        if not self.slack_signing_secret:
            missing.append("SLACK_SIGNING_SECRET")
        if not self.slack_oauth_client_id:
            missing.append("SLACK_OAUTH_CLIENT_ID")
        if not self.slack_oauth_client_secret:
            missing.append("SLACK_OAUTH_CLIENT_SECRET")
        if not self.gemini_enabled:
            missing.append("GEMINI_ENABLED=true")
        if not self.google_genai_use_vertexai:
            missing.append("GOOGLE_GENAI_USE_VERTEXAI=true")
        if not self.google_cloud_project:
            missing.append("GOOGLE_CLOUD_PROJECT")
        if not self.allowed_origins or any(origin == "*" for origin in self.allowed_origins):
            missing.append("ALLOWED_ORIGINS must be explicit in production")
        if not self.auth_required:
            missing.append("AUTH_REQUIRED=true")
        if not self.agent_runtime_token:
            missing.append("AGENT_RUNTIME_TOKEN")
        if missing:
            raise RuntimeError("Production configuration is incomplete: " + ", ".join(missing))


@lru_cache
def get_settings() -> Settings:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    load_dotenv(env_path)
    return Settings(
        app_name=os.getenv("APP_NAME", "Panopticon"),
        app_env=os.getenv("APP_ENV", "development"),
        app_api_url=os.getenv("APP_API_URL", "http://localhost:8000"),
        app_public_url=os.getenv("APP_PUBLIC_URL", "http://localhost:3000"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./panopticon.db"),
        allowed_origins=_csv_env("ALLOWED_ORIGINS", ["http://localhost:3000", "http://127.0.0.1:3000"]),
        db_pool_size=_int_env("DB_POOL_SIZE", 5),
        db_max_overflow=_int_env("DB_MAX_OVERFLOW", 10),
        auth_required=_bool_env("AUTH_REQUIRED", False),
        session_cookie_name=os.getenv("SESSION_COOKIE_NAME", "panopticon_session"),
        session_ttl_hours=_int_env("SESSION_TTL_HOURS", 168),
        default_workspace_slug=os.getenv("DEFAULT_WORKSPACE_SLUG", "local-dev"),
        agent_runtime_token=os.getenv("AGENT_RUNTIME_TOKEN", ""),
        agent_runtime_workspace_slug=os.getenv("AGENT_RUNTIME_WORKSPACE_SLUG", os.getenv("DEFAULT_WORKSPACE_SLUG", "local-dev")),
        agent_runtime_user_email=os.getenv("AGENT_RUNTIME_USER_EMAIL", "agent@panopticon.dev"),
        gitlab_webhook_secret=os.getenv("GITLAB_WEBHOOK_SECRET", ""),
        gitlab_base_url=os.getenv("GITLAB_BASE_URL", "https://gitlab.com"),
        gitlab_token=os.getenv("GITLAB_TOKEN", ""),
        google_oauth_client_id=os.getenv("GOOGLE_OAUTH_CLIENT_ID", ""),
        google_oauth_client_secret=os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", ""),
        google_oauth_redirect_uri=os.getenv("GOOGLE_OAUTH_REDIRECT_URI", ""),
        gitlab_oauth_client_id=os.getenv("GITLAB_OAUTH_CLIENT_ID", ""),
        gitlab_oauth_client_secret=os.getenv("GITLAB_OAUTH_CLIENT_SECRET", ""),
        gitlab_oauth_redirect_uri=os.getenv("GITLAB_OAUTH_REDIRECT_URI", ""),
        gitlab_oauth_scopes=_csv_env("GITLAB_OAUTH_SCOPES", ["api", "read_user"]),
        oauth_token_encryption_key=os.getenv("OAUTH_TOKEN_ENCRYPTION_KEY", ""),
        oauth_state_ttl_minutes=_int_env("OAUTH_STATE_TTL_MINUTES", 15),
        slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL", ""),
        slack_signing_secret=os.getenv("SLACK_SIGNING_SECRET", ""),
        slack_bot_token=os.getenv("SLACK_BOT_TOKEN", ""),
        slack_default_channel=os.getenv("SLACK_DEFAULT_CHANNEL", ""),
        slack_oauth_client_id=os.getenv("SLACK_OAUTH_CLIENT_ID", ""),
        slack_oauth_client_secret=os.getenv("SLACK_OAUTH_CLIENT_SECRET", ""),
        slack_oauth_redirect_uri=os.getenv("SLACK_OAUTH_REDIRECT_URI", ""),
        dry_run_actions=_bool_env("DRY_RUN_ACTIONS", True),
        dispatch_actions=_bool_env("DISPATCH_ACTIONS", True),
        repo_index_on_sync=_bool_env("REPO_INDEX_ON_SYNC", True),
        repo_index_file_limit=_int_env("REPO_INDEX_FILE_LIMIT", 80),
        repo_index_max_file_bytes=_int_env("REPO_INDEX_MAX_FILE_BYTES", 20000),
        gemini_enabled=_bool_env("GEMINI_ENABLED", False),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-pro"),
        gemini_api_key=os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", ""),
        google_genai_use_vertexai=_bool_env("GOOGLE_GENAI_USE_VERTEXAI", False),
        google_cloud_project=os.getenv("GOOGLE_CLOUD_PROJECT", ""),
        google_cloud_location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
    )
