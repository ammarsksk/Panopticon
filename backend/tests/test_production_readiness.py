from pathlib import Path

import pytest

from app.config import Settings


ROOT = Path(__file__).resolve().parents[2]


def test_production_settings_reject_incomplete_configuration():
    settings = Settings(app_env="production", database_url="sqlite:///./panopticon.db")

    with pytest.raises(RuntimeError) as exc:
        settings.validate_for_startup()

    message = str(exc.value)
    assert "DATABASE_URL must use PostgreSQL" in message
    assert "AUTH_REQUIRED=true" in message
    assert "GOOGLE_GENAI_USE_VERTEXAI=true" in message


def test_production_settings_accept_required_controls():
    settings = Settings(
        app_env="production",
        database_url="postgresql+psycopg://user:pass@host:5432/panopticon",
        allowed_origins=["https://panopticon.example.com"],
        auth_required=True,
        gitlab_webhook_secret="webhook-secret",
        gitlab_oauth_client_id="gitlab-client",
        gitlab_oauth_client_secret="gitlab-secret",
        google_oauth_client_id="google-client",
        google_oauth_client_secret="google-secret",
        oauth_token_encryption_key="encryption-key",
        slack_signing_secret="slack-secret",
        slack_oauth_client_id="slack-client",
        slack_oauth_client_secret="slack-secret",
        gemini_enabled=True,
        google_genai_use_vertexai=True,
        google_cloud_project="panopticon-495816",
        agent_runtime_token="agent-runtime-token",
    )

    settings.validate_for_startup()


def test_cloud_run_backend_uses_cloud_sql_and_secret_manager():
    manifest = (ROOT / "infrastructure" / "cloud-run-backend.yaml").read_text(encoding="utf-8")

    assert "run.googleapis.com/cloudsql-instances" in manifest
    assert "panopticon-495816:us-central1:panopticon-postgres" in manifest
    assert "serviceAccountName: panopticon-runtime@panopticon-495816.iam.gserviceaccount.com" in manifest
    assert "secretKeyRef" in manifest
    assert "panopticon-database-url" in manifest
    assert "AUTH_REQUIRED" in manifest
    assert 'value: "true"' in manifest


def test_sensitive_local_env_files_are_ignored():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "cloud-sql.env" in gitignore
    assert "infrastructure/cloud-sql.env" in gitignore


def test_production_runbooks_exist():
    assert (ROOT / "docs" / "CLOUD_SQL_MIGRATION.md").exists()
    assert (ROOT / "docs" / "PRODUCTION_SETUP.md").exists()
    assert (ROOT / "docs" / "RUN_LOCAL_COMMANDS.md").exists()
