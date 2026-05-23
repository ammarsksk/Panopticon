from app.config import get_settings


def _status(name: str, ok: bool, detail: str) -> str:
    marker = "OK" if ok else "MISSING"
    return f"{marker:7} {name:24} {detail}"


def main() -> None:
    settings = get_settings()
    checks = [
        ("APP_ENV", bool(settings.app_env), settings.app_env),
        ("DATABASE_URL", bool(settings.database_url), _database_detail(settings.database_url)),
        ("ALLOWED_ORIGINS", bool(settings.allowed_origins), ",".join(settings.allowed_origins or [])),
        ("GEMINI_ENABLED", settings.gemini_enabled, str(settings.gemini_enabled)),
        ("GOOGLE_GENAI_USE_VERTEXAI", settings.google_genai_use_vertexai, str(settings.google_genai_use_vertexai)),
        ("GOOGLE_CLOUD_PROJECT", bool(settings.google_cloud_project), settings.google_cloud_project or "set this for Vertex"),
        ("GOOGLE_CLOUD_LOCATION", bool(settings.google_cloud_location), settings.google_cloud_location),
        ("GITLAB_WEBHOOK_SECRET", bool(settings.gitlab_webhook_secret), "required for real GitLab webhooks"),
        ("GOOGLE_OAUTH", bool(settings.google_oauth_client_id and settings.google_oauth_client_secret), "required for Google login"),
        ("GITLAB_OAUTH", bool(settings.gitlab_oauth_client_id and settings.gitlab_oauth_client_secret), "required for per-workspace GitLab sync/actions"),
        ("SLACK_OAUTH", bool(settings.slack_oauth_client_id and settings.slack_oauth_client_secret), "required for per-workspace Slack installs"),
        ("OAUTH_TOKEN_ENCRYPTION_KEY", bool(settings.oauth_token_encryption_key), "required for encrypted OAuth tokens in production"),
        ("GITLAB_TOKEN", bool(settings.gitlab_token), "optional fallback for GitLab API reads/comments"),
        ("SLACK_WEBHOOK_URL", bool(settings.slack_webhook_url), "required for real Slack alerts"),
        ("DRY_RUN_ACTIONS", True, str(settings.dry_run_actions)),
    ]

    print("Panopticon setup check")
    print("======================")
    for name, ok, detail in checks:
        print(_status(name, ok, detail))

    print()
    if settings.dry_run_actions:
        print("Actions are safe: DRY_RUN_ACTIONS=true, so GitLab/Slack writes are simulated.")
    else:
        print("Actions are live: DRY_RUN_ACTIONS=false, so GitLab/Slack writes can be sent.")


def _database_detail(database_url: str) -> str:
    if database_url.startswith("sqlite"):
        return "SQLite local demo database"
    if database_url.startswith("postgresql"):
        return "PostgreSQL configured"
    return "unknown database driver"


if __name__ == "__main__":
    main()
