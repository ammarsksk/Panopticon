from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.database import Base, get_db
from app.main import app


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


def test_ai_status_reports_vertex_and_mcp_configuration(monkeypatch):
    monkeypatch.setenv("GEMINI_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "panopticon-495816")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-pro")
    get_settings.cache_clear()
    db = _session()
    try:
        response = _client(db).get("/api/integrations/ai")
        payload = response.json()
        assert response.status_code == 200
        assert payload["provider"] == "vertex_ai"
        assert payload["model"] == "gemini-2.5-pro"
        assert payload["mcp_enabled"] is True
    finally:
        app.dependency_overrides.clear()
        db.close()
        get_settings.cache_clear()


def test_dashboard_summary_exposes_actionable_integration_status(monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "slack-secret")
    monkeypatch.setenv("GITLAB_OAUTH_CLIENT_ID", "gitlab-client")
    monkeypatch.setenv("GITLAB_OAUTH_CLIENT_SECRET", "gitlab-secret")
    get_settings.cache_clear()
    db = _session()
    try:
        response = _client(db).get("/api/dashboard/summary")
        payload = response.json()
        assert response.status_code == 200
        assert payload["slack_status"]["configured"] is True
        assert payload["gitlab_status"]["configured"] is True
        assert "connected" in payload["gitlab_status"]
    finally:
        app.dependency_overrides.clear()
        db.close()
        get_settings.cache_clear()
