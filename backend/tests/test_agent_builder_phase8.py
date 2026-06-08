import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.config import get_settings
from app.database import Base, get_db
from app.main import app
from panopticon_agent.runtime import PanopticonAgentRuntime


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


def _enable_agent_auth(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    monkeypatch.setenv("AGENT_RUNTIME_TOKEN", "phase8-agent-token")
    monkeypatch.setenv("AGENT_RUNTIME_WORKSPACE_SLUG", "phase8-workspace")
    monkeypatch.setenv("AGENT_RUNTIME_USER_EMAIL", "phase8-agent@panopticon.dev")
    get_settings.cache_clear()


def _clear_agent_auth(monkeypatch):
    monkeypatch.delenv("AUTH_REQUIRED", raising=False)
    monkeypatch.delenv("AGENT_RUNTIME_TOKEN", raising=False)
    monkeypatch.delenv("AGENT_RUNTIME_WORKSPACE_SLUG", raising=False)
    monkeypatch.delenv("AGENT_RUNTIME_USER_EMAIL", raising=False)
    get_settings.cache_clear()


def test_agent_runtime_bearer_token_resolves_workspace_context(monkeypatch):
    _enable_agent_auth(monkeypatch)
    db = _session()
    client = _client(db)
    try:
        response = client.get("/api/auth/me", headers={"Authorization": "Bearer phase8-agent-token"})

        assert response.status_code == 200
        payload = response.json()
        assert payload["user"]["email"] == "phase8-agent@panopticon.dev"
        assert payload["workspace"]["slug"] == "phase8-workspace"
        assert payload["role"] == "admin"
    finally:
        app.dependency_overrides.clear()
        _clear_agent_auth(monkeypatch)
        db.close()


def test_agent_runtime_token_is_workspace_scoped(monkeypatch):
    _enable_agent_auth(monkeypatch)
    db = _session()
    client = _client(db)
    try:
        workspace_id = client.get("/api/auth/me", headers={"Authorization": "Bearer phase8-agent-token"}).json()["workspace"]["id"]
        other_workspace = models.Workspace(name="Other", slug="other")
        db.add(other_workspace)
        db.flush()
        db.add_all(
            [
                models.GitLabProject(
                    workspace_id=workspace_id,
                    gitlab_project_id="101",
                    project_path="phase8/visible",
                    name="visible",
                    namespace="phase8",
                    web_url="https://gitlab.com/phase8/visible",
                ),
                models.GitLabProject(
                    workspace_id=other_workspace.id,
                    gitlab_project_id="202",
                    project_path="phase8/hidden",
                    name="hidden",
                    namespace="phase8",
                    web_url="https://gitlab.com/phase8/hidden",
                ),
            ]
        )
        db.commit()

        response = client.get("/api/projects", headers={"Authorization": "Bearer phase8-agent-token"})

        assert response.status_code == 200
        assert [item["project_path"] for item in response.json()] == ["phase8/visible"]
    finally:
        app.dependency_overrides.clear()
        _clear_agent_auth(monkeypatch)
        db.close()


def test_mcp_tool_calls_are_audited_for_agent_runtime(monkeypatch):
    _enable_agent_auth(monkeypatch)
    db = _session()
    client = _client(db)
    try:
        workspace_id = client.get("/api/auth/me", headers={"Authorization": "Bearer phase8-agent-token"}).json()["workspace"]["id"]
        db.add(
            models.GitLabProject(
                workspace_id=workspace_id,
                gitlab_project_id="101",
                project_path="phase8/audited",
                name="audited",
                namespace="phase8",
                web_url="https://gitlab.com/phase8/audited",
            )
        )
        db.commit()

        response = client.post(
            "/mcp",
            headers={"Authorization": "Bearer phase8-agent-token"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "search_projects", "arguments": {"query": "audited"}},
            },
        )

        audit = db.scalar(select(models.AuditLog).where(models.AuditLog.event_type == "agent.tool_call"))
        assert response.status_code == 200
        assert response.json()["result"]["isError"] is False
        assert audit is not None
        assert audit.workspace_id == workspace_id
        assert audit.target_id == "search_projects"
        assert audit.metadata_json["success"] is True
        assert audit.metadata_json["argument_keys"] == ["query"]
    finally:
        app.dependency_overrides.clear()
        _clear_agent_auth(monkeypatch)
        db.close()


def test_agent_builder_runtime_queries_grounded_panopticon_tools(monkeypatch):
    calls = []

    class FakeClient:
        def call_tool(self, name, arguments):
            calls.append((name, arguments))
            if name == "get_chat_context":
                return {"project": {"project_path": "phase8/app"}, "pipelines": [{"status": "failed"}]}
            if name == "generate_grounded_recommendation":
                return {
                    "grounded_recommendation": {
                        "summary": "Pipeline failed because the deploy job timed out.",
                        "evidence": ["Pipeline 9001 failed on deploy."],
                        "next_actions": ["Inspect deploy job logs."],
                    }
                }
            raise AssertionError(name)

    monkeypatch.setattr(PanopticonAgentRuntime, "_client", lambda self, trace_id: FakeClient())

    response = PanopticonAgentRuntime(api_base_url="http://panopticon.test", token="token").query("Why did the pipeline fail?", project_id=7)

    assert response["runtime"] == "panopticon-agent-builder-runtime"
    assert "deploy job timed out" in response["answer"]
    assert "Pipeline 9001" in response["answer"]
    assert [name for name, _ in calls] == ["get_chat_context", "generate_grounded_recommendation"]
    assert calls[0][1]["project_id"] == 7
    assert calls[1][1]["intent"] == "pipeline_failure"


def test_agent_tool_manifest_documents_workspace_scoped_mcp_contract():
    manifest_path = Path(__file__).resolve().parents[2] / "panopticon_agent" / "tool_manifest.json"
    manifest = json.loads(manifest_path.read_text())

    assert manifest["transport"] == "mcp-json-rpc"
    assert manifest["auth"]["type"] == "bearer"
    assert manifest["auth"]["workspace_scoped"] is True
    assert "generate_grounded_recommendation" in manifest["tools"]
