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
    database_url: str = "sqlite:///./panopticon.db"
    allowed_origins: list[str] | None = None
    db_pool_size: int = 5
    db_max_overflow: int = 10
    gitlab_webhook_secret: str = ""
    gitlab_base_url: str = "https://gitlab.com"
    gitlab_token: str = ""
    slack_webhook_url: str = ""
    dry_run_actions: bool = True
    dispatch_actions: bool = True
    gemini_enabled: bool = False
    gemini_model: str = "gemini-3-pro"
    gemini_api_key: str = ""
    google_genai_use_vertexai: bool = False
    google_cloud_project: str = ""
    google_cloud_location: str = "us-central1"

    def __post_init__(self) -> None:
        if self.allowed_origins is None:
            object.__setattr__(self, "allowed_origins", ["http://localhost:3000", "http://127.0.0.1:3000"])

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
        if not self.gitlab_token:
            missing.append("GITLAB_TOKEN")
        if not self.gemini_enabled:
            missing.append("GEMINI_ENABLED=true")
        if not self.google_genai_use_vertexai:
            missing.append("GOOGLE_GENAI_USE_VERTEXAI=true")
        if not self.google_cloud_project:
            missing.append("GOOGLE_CLOUD_PROJECT")
        if not self.allowed_origins or any(origin == "*" for origin in self.allowed_origins):
            missing.append("ALLOWED_ORIGINS must be explicit in production")
        if missing:
            raise RuntimeError("Production configuration is incomplete: " + ", ".join(missing))


@lru_cache
def get_settings() -> Settings:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    load_dotenv(env_path)
    return Settings(
        app_name=os.getenv("APP_NAME", "Panopticon"),
        app_env=os.getenv("APP_ENV", "development"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./panopticon.db"),
        allowed_origins=_csv_env("ALLOWED_ORIGINS", ["http://localhost:3000", "http://127.0.0.1:3000"]),
        db_pool_size=_int_env("DB_POOL_SIZE", 5),
        db_max_overflow=_int_env("DB_MAX_OVERFLOW", 10),
        gitlab_webhook_secret=os.getenv("GITLAB_WEBHOOK_SECRET", ""),
        gitlab_base_url=os.getenv("GITLAB_BASE_URL", "https://gitlab.com"),
        gitlab_token=os.getenv("GITLAB_TOKEN", ""),
        slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL", ""),
        dry_run_actions=_bool_env("DRY_RUN_ACTIONS", True),
        dispatch_actions=_bool_env("DISPATCH_ACTIONS", True),
        gemini_enabled=_bool_env("GEMINI_ENABLED", False),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3-pro"),
        gemini_api_key=os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", ""),
        google_genai_use_vertexai=_bool_env("GOOGLE_GENAI_USE_VERTEXAI", False),
        google_cloud_project=os.getenv("GOOGLE_CLOUD_PROJECT", ""),
        google_cloud_location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
    )
