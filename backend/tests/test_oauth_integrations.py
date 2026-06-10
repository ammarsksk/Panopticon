from dataclasses import replace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base
from app.services.oauth import OAuthService, decrypt_token, encrypt_token, gitlab_client_for_workspace, slack_credentials_for_workspace


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_google_auth_url_creates_bounded_state_record():
    db = _session()
    try:
        service = OAuthService(db)
        service.settings = replace(
            service.settings,
            google_oauth_client_id="google-client",
            google_oauth_client_secret="google-secret",
            google_oauth_redirect_uri="http://localhost:8000/api/auth/google/callback",
        )

        url = service.google_auth_url(redirect_after="/projects")

        assert "accounts.google.com/o/oauth2/v2/auth" in url
        assert "client_id=google-client" in url
        state = db.scalar(select(models.OAuthState).where(models.OAuthState.provider == "google"))
        assert state is not None
        assert state.redirect_after == "/projects"
    finally:
        db.close()


def test_oauth_state_allows_only_configured_frontend_origins():
    db = _session()
    try:
        service = OAuthService(db)
        service.settings = replace(
            service.settings,
            allowed_origins=["http://localhost:3001"],
            google_oauth_client_id="google-client",
            google_oauth_client_secret="google-secret",
            google_oauth_redirect_uri="http://localhost:8000/api/auth/google/callback",
        )

        service.google_auth_url(redirect_after="http://localhost:3001/dashboard")
        allowed_state = db.scalar(select(models.OAuthState).where(models.OAuthState.provider == "google"))
        assert allowed_state.redirect_after == "http://localhost:3001/dashboard"

        service.google_auth_url(redirect_after="https://attacker.example/dashboard")
        states = db.scalars(select(models.OAuthState).where(models.OAuthState.provider == "google").order_by(models.OAuthState.id)).all()
        assert states[-1].redirect_after == "/"
    finally:
        db.close()


def test_gitlab_workspace_token_builds_bearer_client():
    db = _session()
    try:
        workspace = models.Workspace(name="Team", slug="team")
        user = models.User(email="team@example.com", name="Team", password_hash="")
        db.add_all([workspace, user])
        db.flush()
        connection = models.OAuthConnection(
            provider="gitlab",
            workspace_id=workspace.id,
            user_id=user.id,
            provider_user_id="42",
            account_label="team-user",
            access_token_encrypted=encrypt_token("workspace-token"),
            refresh_token_encrypted="",
            scopes=["api", "read_user"],
            metadata_json={},
        )
        db.add(connection)
        db.commit()

        client = gitlab_client_for_workspace(db, workspace.id)

        assert client.configured is True
        assert client._headers() == {"Authorization": "Bearer workspace-token"}
    finally:
        db.close()


def test_gitlab_auth_url_uses_minimal_api_scopes():
    db = _session()
    try:
        service = OAuthService(db)
        service.settings = replace(
            service.settings,
            gitlab_oauth_client_id="gitlab-client",
            gitlab_oauth_client_secret="gitlab-secret",
            gitlab_oauth_redirect_uri="http://localhost:8000/api/integrations/gitlab/callback",
            gitlab_oauth_scopes=["api", "read_user"],
        )

        url = service.gitlab_auth_url(user_id=1, workspace_id=1)

        assert "scope=api+read_user" in url
        assert "write_repository" not in url
    finally:
        db.close()


def test_encrypt_decrypt_token_roundtrip_in_local_development():
    encrypted = encrypt_token("secret-token")

    assert encrypted != "secret-token"
    assert decrypt_token(encrypted) == "secret-token"


def test_slack_workspace_credentials_use_oauth_connection_metadata():
    db = _session()
    try:
        workspace = models.Workspace(name="Team", slug="team")
        user = models.User(email="team@example.com", name="Team", password_hash="")
        db.add_all([workspace, user])
        db.flush()
        db.add(
            models.OAuthConnection(
                provider="slack",
                workspace_id=workspace.id,
                user_id=user.id,
                provider_user_id="T123",
                account_label="Engineering",
                access_token_encrypted=encrypt_token("xoxb-token"),
                refresh_token_encrypted="",
                scopes=["incoming-webhook", "commands"],
                metadata_json={"incoming_webhook": {"url": "https://hooks.slack.com/services/test", "channel": "#ops"}},
            )
        )
        db.commit()

        credentials = slack_credentials_for_workspace(db, workspace.id)

        assert credentials["webhook_url"] == "https://hooks.slack.com/services/test"
        assert credentials["bot_token"] == "xoxb-token"
        assert credentials["channel"] == "#ops"
    finally:
        db.close()
