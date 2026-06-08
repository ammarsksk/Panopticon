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


def _signup(client: TestClient, email: str, workspace: str) -> dict:
    response = client.post(
        "/api/auth/signup",
        json={"email": email, "password": "password-123", "name": email.split("@", 1)[0], "workspace_name": workspace},
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

        response = second.post("/api/chat", json={"project_id": project.id, "message": "Why did the pipeline fail?"})

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


def test_production_session_cookie_is_http_only_secure_and_lax(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    get_settings.cache_clear()
    try:
        response = Response()
        set_session_cookie(response, "session-token")
        header = response.headers["set-cookie"].lower()
        assert "httponly" in header
        assert "secure" in header
        assert "samesite=lax" in header
    finally:
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
