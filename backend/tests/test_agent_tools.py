from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import GitLabProject, PipelineInsight, Recommendation, RiskAssessment


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed(db):
    project = GitLabProject(
        gitlab_project_id="101",
        project_path="demo/checkout-service",
        name="checkout-service",
        namespace="demo",
        web_url="https://gitlab.com/demo/checkout-service",
        default_branch="main",
        visibility="private",
        failed_pipelines_count=1,
        latest_pipeline_id="9001",
        latest_pipeline_status="failed",
    )
    db.add(project)
    risk = RiskAssessment(
        project_path="demo/checkout-service",
        merge_request_iid="7",
        deployment_ref="",
        score=92,
        level="critical",
        summary="Deployment risk is critical.",
        reasons=["Auth and deployment files changed."],
        recommendations=["Require owner review."],
    )
    pipeline = PipelineInsight(
        project_path="demo/checkout-service",
        pipeline_id="9001",
        status="failed",
        likely_cause="The deploy job timed out.",
        evidence=["Kubernetes rollout exceeded wait limit."],
        recommendations=["Inspect rollout events."],
    )
    db.add_all([risk, pipeline])
    db.flush()
    db.add(
        Recommendation(
            project_path="demo/checkout-service",
            source_type="risk",
            source_id=str(risk.id),
            channel="gitlab_comment",
            message="Require owner review.",
            status="dry_run",
        )
    )
    db.commit()
    return project


def test_agent_tools_are_discoverable_and_invokable():
    db = _session()
    project = _seed(db)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        tools = client.get("/api/agent/tools").json()["tools"]
        summary = client.post(
            "/api/agent/tools/get_project_summary/invoke",
            json={"project_id": project.id},
        ).json()
    finally:
        app.dependency_overrides.clear()
        db.close()

    assert "get_project_summary" in {tool["name"] for tool in tools}
    assert summary["project"]["project_path"] == "demo/checkout-service"
    assert summary["risks"][0]["score"] == 92
    assert summary["pipeline_insights"][0]["likely_cause"] == "The deploy job timed out."


def test_mcp_endpoint_lists_and_calls_tools():
    db = _session()
    _seed(db)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        listed = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()
        called = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "search_projects", "arguments": {"query": "checkout"}},
            },
        ).json()
    finally:
        app.dependency_overrides.clear()
        db.close()

    assert listed["result"]["tools"]
    assert any(tool["name"] == "search_projects" for tool in listed["result"]["tools"])
    text = called["result"]["content"][0]["text"]
    assert "demo/checkout-service" in text
    assert called["result"]["isError"] is False


def test_mcp_priority_and_chat_context_tools():
    db = _session()
    project = _seed(db)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        chat_context = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "get_chat_context", "arguments": {"project_id": project.id}},
            },
        ).json()
        priority_context = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "get_priority_context", "arguments": {}},
            },
        ).json()
    finally:
        app.dependency_overrides.clear()
        db.close()

    chat_text = chat_context["result"]["content"][0]["text"]
    priority_text = priority_context["result"]["content"][0]["text"]
    assert "demo/checkout-service" in chat_text
    assert "The deploy job timed out" in chat_text
    assert "Deployment risk is critical" in priority_text


def test_ai_status_reports_mcp_and_gemini25_pro_model():
    client = TestClient(app)
    status = client.get("/api/integrations/ai").json()

    assert status["mcp_enabled"] is True
    assert status["tool_layer"] == "mcp_compatible_panopticon_tools"
    assert status["model"] == "gemini-2.5-pro"
