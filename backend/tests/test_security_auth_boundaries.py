from fastapi import Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.config import get_settings
from app.database import Base, get_db
from app.main import app
from app.services.auth import set_session_cookie


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _client(db):
    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def _csrf(client: TestClient) -> dict:
    response = client.get("/api/auth/csrf")
    assert response.status_code == 200
    return {"X-Panopticon-CSRF": response.json()["csrf_token"]}


def _signup(client: TestClient, email: str, workspace: str) -> dict:
    response = client.post(
        "/api/auth/signup",
        json={"email": email, "password": "password-123", "name": email.split("@", 1)[0], "workspace_name": workspace},
        headers=_csrf(client),
    )
    assert response.status_code == 200
    return response.json()


def _workspace_id(db, email: str) -> int:
    user = db.scalar(select(models.User).where(models.User.email == email))
    membership = db.scalar(select(models.WorkspaceMember).where(models.WorkspaceMember.user_id == user.id))
    return membership.workspace_id


def test_auth_required_rejects_unauthenticated_api_requests(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()
    db = _session()
    try:
        client = _client(db)
        response = client.get("/api/projects")
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()
        db.close()
        get_settings.cache_clear()


def test_chat_rejects_cross_workspace_project_id(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()
    db = _session()
    first = _client(db)
    second = _client(db)
    try:
        _signup(first, "one@example.com", "One Workspace")
        _signup(second, "two@example.com", "Two Workspace")
        workspace_one = _workspace_id(db, "one@example.com")
        project = models.GitLabProject(
            workspace_id=workspace_one,
            gitlab_project_id="101",
            project_path="team-one/app",
            name="app",
            namespace="team-one",
            web_url="https://gitlab.com/team-one/app",
        )
        db.add(project)
        db.commit()

        response = second.post("/api/chat", json={"project_id": project.id, "message": "Why did the pipeline fail?"}, headers=_csrf(second))

        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
        db.close()
        get_settings.cache_clear()


def test_chat_thread_messages_reject_cross_workspace_reads(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()
    db = _session()
    first = _client(db)
    second = _client(db)
    try:
        _signup(first, "one@example.com", "One Workspace")
        _signup(second, "two@example.com", "Two Workspace")
        workspace_one = _workspace_id(db, "one@example.com")
        thread = models.ChatThread(workspace_id=workspace_one, project_path="", title="Private thread")
        db.add(thread)
        db.flush()
        db.add(models.ChatMessage(workspace_id=workspace_one, thread_id=thread.id, role="assistant", content="private"))
        db.commit()

        response = second.get(f"/api/chat/threads/{thread.id}")

        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
        db.close()
        get_settings.cache_clear()


def test_production_session_cookie_is_http_only_secure_and_cross_site(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    get_settings.cache_clear()
    try:
        response = Response()
        set_session_cookie(response, "session-token")
        header = response.headers["set-cookie"].lower()
        assert "httponly" in header
        assert "secure" in header
        assert "samesite=none" in header
    finally:
        get_settings.cache_clear()


def test_csrf_required_for_browser_state_changing_requests(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    monkeypatch.setenv("CSRF_REQUIRED", "true")
    get_settings.cache_clear()
    db = _session()
    try:
        client = _client(db)
        response = client.post(
            "/api/auth/signup",
            json={"email": "secure@example.com", "password": "password-123", "name": "Secure", "workspace_name": "Secure"},
        )
        assert response.status_code == 403

        response = client.post(
            "/api/auth/signup",
            json={"email": "secure@example.com", "password": "password-123", "name": "Secure", "workspace_name": "Secure"},
            headers=_csrf(client),
        )
        assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()
        db.close()
        get_settings.cache_clear()


def test_security_headers_are_added_to_responses():
    db = _session()
    try:
        client = _client(db)
        response = client.get("/health")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_login_rotates_existing_sessions(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()
    db = _session()
    try:
        client = _client(db)
        _signup(client, "rotate@example.com", "Rotate Workspace")

        response = client.post(
            "/api/auth/login",
            json={"email": "rotate@example.com", "password": "password-123"},
            headers=_csrf(client),
        )

        assert response.status_code == 200
        user = db.scalar(select(models.User).where(models.User.email == "rotate@example.com"))
        active_sessions = db.scalars(
            select(models.UserSession)
            .where(models.UserSession.user_id == user.id)
            .where(models.UserSession.revoked_at.is_(None))
        ).all()
        assert len(active_sessions) == 1
    finally:
        app.dependency_overrides.clear()
        db.close()
        get_settings.cache_clear()


def test_viewer_cannot_run_admin_sync(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()
    db = _session()
    try:
        client = _client(db)
        _signup(client, "viewer@example.com", "Viewer Workspace")
        user = db.scalar(select(models.User).where(models.User.email == "viewer@example.com"))
        membership = db.scalar(select(models.WorkspaceMember).where(models.WorkspaceMember.user_id == user.id))
        membership.role = "viewer"
        db.commit()

        response = client.post("/api/gitlab/projects/sync", headers=_csrf(client))

        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()
        db.close()
        get_settings.cache_clear()


def test_login_rate_limit_can_block_repeated_attempts(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_LOGIN_PER_WINDOW", "1")
    get_settings.cache_clear()
    db = _session()
    try:
        client = _client(db)
        headers = _csrf(client)
        first = client.post("/api/auth/login", json={"email": "none@example.com", "password": "password-123"}, headers=headers)
        second = client.post("/api/auth/login", json={"email": "none@example.com", "password": "password-123"}, headers=headers)

        assert first.status_code == 401
        assert second.status_code == 429
    finally:
        app.dependency_overrides.clear()
        db.close()
        get_settings.cache_clear()


def test_gitlab_webhook_requires_configured_secret(monkeypatch):
    monkeypatch.setenv("GITLAB_WEBHOOK_SECRET", "expected-secret")
    get_settings.cache_clear()
    db = _session()
    try:
        client = _client(db)
        response = client.post("/webhooks/gitlab", json={"object_kind": "pipeline"})
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()
        db.close()
        get_settings.cache_clear()


def test_agent_runtime_bearer_token_uses_agent_workspace(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    monkeypatch.setenv("AGENT_RUNTIME_TOKEN", "agent-runtime-test-token")
    monkeypatch.setenv("AGENT_RUNTIME_WORKSPACE_SLUG", "agent-runtime")
    get_settings.cache_clear()
    db = _session()
    try:
        client = _client(db)
        response = client.get("/api/agent/tools", headers={"Authorization": "Bearer agent-runtime-test-token"})

        assert response.status_code == 200
        workspace = db.scalar(select(models.Workspace).where(models.Workspace.slug == "agent-runtime"))
        assert workspace is not None
        assert response.json()["tools"]
    finally:
        app.dependency_overrides.clear()
        db.close()
        get_settings.cache_clear()
