from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import AgentAction, EngineeringMetricSnapshot, GitLabProject, IncidentCorrelation, ObservabilityEvent, PipelineSnapshot, RiskAssessment


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed(db):
    checkout = GitLabProject(
        gitlab_project_id="101",
        project_path="demo/checkout-service",
        name="checkout-service",
        namespace="demo",
        web_url="https://gitlab.com/demo/checkout-service",
        default_branch="main",
        visibility="private",
        open_merge_requests_count=2,
        failed_pipelines_count=1,
        latest_pipeline_id="9001",
        latest_pipeline_status="failed",
    )
    search = GitLabProject(
        gitlab_project_id="102",
        project_path="demo/search-api",
        name="search-api",
        namespace="demo",
        web_url="https://gitlab.com/demo/search-api",
        default_branch="main",
        visibility="private",
        open_merge_requests_count=1,
        failed_pipelines_count=0,
        latest_pipeline_id="9002",
        latest_pipeline_status="success",
    )
    db.add_all([checkout, search])
    db.flush()
    db.add_all(
        [
            PipelineSnapshot(
                gitlab_project_id="101",
                project_path="demo/checkout-service",
                pipeline_id="9001",
                status="failed",
                ref="main",
                sha="abc",
                web_url="",
            ),
            PipelineSnapshot(
                gitlab_project_id="101",
                project_path="demo/checkout-service",
                pipeline_id="9000",
                status="success",
                ref="main",
                sha="def",
                web_url="",
            ),
            PipelineSnapshot(
                gitlab_project_id="102",
                project_path="demo/search-api",
                pipeline_id="9002",
                status="success",
                ref="main",
                sha="ghi",
                web_url="",
            ),
            RiskAssessment(
                project_path="demo/checkout-service",
                merge_request_iid="7",
                deployment_ref="",
                score=92,
                level="critical",
                summary="Checkout risk is critical.",
                reasons=["auth files changed"],
                recommendations=["Require owner review."],
            ),
            ObservabilityEvent(
                provider="grafana",
                event_uid="grafana:checkout",
                project_path="demo/checkout-service",
                service_name="checkout-service",
                environment="production",
                severity="critical",
                signal_type="metric_alert",
                title="checkout 5xx spike",
                message="5xx spike",
                metric_name="http_5xx_rate",
                payload={},
            ),
            IncidentCorrelation(
                project_path="demo/checkout-service",
                title="checkout correlation",
                severity="critical",
                status="open",
                summary="checkout alert",
                suspected_cause="Checkout risk is critical.",
                confidence=0.8,
                timeline=[],
                related_observability_event_ids=[],
                related_pipeline_ids=["9001"],
                related_risk_ids=[],
                related_incident_ids=[],
                recommendations=["Inspect checkout deploy."],
            ),
            AgentAction(
                project_path="demo/checkout-service",
                action_type="slack_alert",
                channel="slack",
                title="Alert",
                summary="Alert checkout",
                status="pending_approval",
                requires_approval=True,
                payload_preview={},
                execution_context={},
                last_result={},
            ),
            AgentAction(
                project_path="demo/search-api",
                action_type="gitlab_comment",
                channel="gitlab_comment",
                title="Comment",
                summary="Comment search",
                status="dry_run",
                requires_approval=True,
                payload_preview={},
                execution_context={},
                last_result={},
            ),
        ]
    )
    db.commit()
    return checkout, search


def test_metrics_summary_and_project_rankings():
    db = _session()
    _seed(db)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        summary = client.get("/api/metrics/summary")
        projects = client.get("/api/metrics/projects")
    finally:
        app.dependency_overrides.clear()
        db.close()

    assert summary.status_code == 200
    assert projects.status_code == 200
    payload = summary.json()
    ranked = projects.json()
    assert payload["project_count"] == 2
    assert payload["failed_pipelines"] == 1
    assert payload["observability_alerts"] == 1
    assert payload["projects_at_risk"] >= 1
    assert payload["riskiest_projects"][0]["project_path"] == "demo/checkout-service"
    assert ranked[0]["health_score"] <= ranked[-1]["health_score"]
    assert ranked[0]["top_reasons"]


def test_metric_snapshot_refresh_is_idempotent():
    db = _session()
    _seed(db)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        first = client.post("/api/metrics/snapshots/refresh")
        second = client.post("/api/metrics/snapshots/refresh")
        snapshots = client.get("/api/metrics/snapshots").json()
    finally:
        app.dependency_overrides.clear()
        db.close()

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(first.json()) == 3
    assert len(second.json()) == 3
    assert db.query(EngineeringMetricSnapshot).count() == 3
    assert any(item["scope_type"] == "organization" for item in snapshots)


def test_metrics_mcp_context_and_snapshot_tool():
    db = _session()
    _seed(db)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        context = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 20,
                "method": "tools/call",
                "params": {"name": "get_metrics_context", "arguments": {"limit": 5}},
            },
        )
        refresh = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 21,
                "method": "tools/call",
                "params": {"name": "refresh_metric_snapshots", "arguments": {}},
            },
        )
    finally:
        app.dependency_overrides.clear()
        db.close()

    assert context.status_code == 200
    assert refresh.status_code == 200
    context_text = context.json()["result"]["content"][0]["text"]
    refresh_text = refresh.json()["result"]["content"][0]["text"]
    assert "average_health_score" in context_text
    assert "demo/checkout-service" in context_text
    assert "engineering_metric_snapshots" in refresh_text
