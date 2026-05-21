from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import GitLabProject, IncidentCorrelation, JobSnapshot, ObservabilityEvent, PipelineInsight, RiskAssessment


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
    pipeline = PipelineInsight(
        project_path="demo/checkout-service",
        pipeline_id="9001",
        status="failed",
        likely_cause="Deploy job timed out waiting for rollout.",
        evidence=["rollout exceeded wait limit"],
        recommendations=["Inspect rollout events."],
    )
    job = JobSnapshot(
        gitlab_project_id="101",
        project_path="demo/checkout-service",
        pipeline_id="9001",
        job_id="7001",
        name="deploy-production",
        stage="deploy",
        status="failed",
        failure_reason="script_failure",
        web_url="https://gitlab.com/demo/checkout-service/-/jobs/7001",
    )
    risk = RiskAssessment(
        project_path="demo/checkout-service",
        merge_request_iid="7",
        deployment_ref="risk/checkout-auth",
        score=92,
        level="critical",
        summary="Checkout deployment risk is critical.",
        reasons=["auth and deployment files changed"],
        recommendations=["Require owner review before deployment."],
    )
    db.add_all([project, pipeline, job, risk])
    db.commit()
    return project


def test_observability_ingest_correlates_alert_with_gitlab_records():
    db = _session()
    _seed(db)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/observability/events",
            json={
                "provider": "grafana",
                "event_uid": "alert-1",
                "service_name": "checkout-service",
                "environment": "production",
                "severity": "critical",
                "signal_type": "metric_alert",
                "title": "checkout 5xx spike",
                "message": "5xx rate exceeded threshold after deploy",
                "metric_name": "http_5xx_rate",
            },
        )
        events = client.get("/api/observability/events").json()
        correlations = client.get("/api/observability/correlations").json()
    finally:
        app.dependency_overrides.clear()
        db.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload["deduplicated"] is False
    assert payload["event"]["project_path"] == "demo/checkout-service"
    assert payload["correlation"]["project_path"] == "demo/checkout-service"
    assert payload["correlation"]["severity"] == "critical"
    assert payload["correlation"]["related_pipeline_ids"] == ["9001"]
    assert payload["correlation"]["related_risk_ids"]
    assert any(item["kind"] == "pipeline" for item in payload["correlation"]["timeline"])
    assert len(events) == 1
    assert len(correlations) == 1


def test_observability_webhook_deduplicates_event_uid():
    db = _session()
    _seed(db)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        body = {
            "fingerprint": "same-alert",
            "labels": {"service": "checkout-service", "severity": "high"},
            "annotations": {"summary": "checkout latency spike", "description": "p95 latency is high"},
        }
        first = client.post("/webhooks/observability/prometheus", json=body)
        second = client.post("/webhooks/observability/prometheus", json=body)
    finally:
        app.dependency_overrides.clear()
        db.close()

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["deduplicated"] is False
    assert second.json()["deduplicated"] is True
    assert db.query(ObservabilityEvent).count() == 1
    assert db.query(IncidentCorrelation).count() == 1


def test_observability_mcp_tools_ingest_and_read_context():
    db = _session()
    project = _seed(db)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        ingest = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {
                    "name": "ingest_observability_event",
                    "arguments": {
                        "project_id": project.id,
                        "provider": "sentry",
                        "service_name": "checkout-service",
                        "severity": "high",
                        "signal_type": "exception",
                        "title": "Checkout exception spike",
                        "message": "Payment callback raised errors",
                    },
                },
            },
        )
        context = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {
                    "name": "get_observability_context",
                    "arguments": {"project_id": project.id},
                },
            },
        )
    finally:
        app.dependency_overrides.clear()
        db.close()

    assert ingest.status_code == 200
    assert context.status_code == 200
    ingest_text = ingest.json()["result"]["content"][0]["text"]
    context_text = context.json()["result"]["content"][0]["text"]
    assert "Checkout exception spike" in ingest_text
    assert "incident_correlations" in context_text
    assert "Deploy job timed out" in context_text
