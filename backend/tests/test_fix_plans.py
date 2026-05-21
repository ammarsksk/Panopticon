from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.database import Base, get_db
from app.main import app
from app.models import FixPlan, FixPlanApproval, GitLabProject, PipelineInsight


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
        likely_cause="The deploy job timed out while waiting for rollout.",
        evidence=["deploy job exceeded wait limit"],
        recommendations=["Add a bounded timeout and validate rollout health."],
    )
    db.add_all([project, pipeline])
    db.commit()
    return project, pipeline


def test_fix_plan_lifecycle_is_approval_gated_and_dry_run(monkeypatch):
    monkeypatch.setenv("DRY_RUN_ACTIONS", "true")
    get_settings.cache_clear()
    db = _session()
    project, pipeline = _seed(db)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        created = client.post(
            "/api/fix-plans",
            json={
                "project_id": project.id,
                "source_type": "pipeline",
                "source_id": str(pipeline.id),
                "problem_statement": "Pipeline timed out during deploy.",
            },
        )
        plan_id = created.json()["id"]
        blocked = client.post(f"/api/fix-plans/{plan_id}/create-branch")
        approved = client.post(f"/api/fix-plans/{plan_id}/approve", json={"actor": "tester", "reason": "safe docs only"})
        branch = client.post(f"/api/fix-plans/{plan_id}/create-branch")
        merge_request = client.post(f"/api/fix-plans/{plan_id}/open-merge-request")
        detail = client.get(f"/api/fix-plans/{plan_id}")
    finally:
        app.dependency_overrides.clear()
        db.close()
        get_settings.cache_clear()

    assert created.status_code == 200
    assert created.json()["fix_type"] == "pipeline_timeout"
    assert created.json()["status"] == "draft"
    assert created.json()["branch_name"].startswith("panopticon/")
    assert created.json()["branch_name"] != "main"
    assert created.json()["plan_payload"]["files"]
    assert blocked.status_code == 403
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert branch.status_code == 200
    assert branch.json()["status"] == "dry_run_branch_ready"
    assert merge_request.status_code == 200
    assert merge_request.json()["status"] == "dry_run_mr_ready"
    assert "merge_requests/new" in merge_request.json()["merge_request_url"]
    assert detail.json()["approvals"][0]["actor"] == "tester"


def test_fix_plan_mcp_tool_creates_plan_without_gitlab_write(monkeypatch):
    monkeypatch.setenv("DRY_RUN_ACTIONS", "true")
    get_settings.cache_clear()
    db = _session()
    project, _pipeline = _seed(db)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 8,
                "method": "tools/call",
                "params": {
                    "name": "create_fix_plan",
                    "arguments": {
                        "project_id": project.id,
                        "problem_statement": "Create deployment health validation.",
                        "fix_type": "deployment_healthcheck",
                    },
                },
            },
        )
    finally:
        app.dependency_overrides.clear()
        db.close()
        get_settings.cache_clear()

    assert response.status_code == 200
    text = response.json()["result"]["content"][0]["text"]
    assert "deployment_healthcheck" in text
    assert db.query(FixPlan).count() == 1
    assert db.query(FixPlanApproval).count() == 0


def test_fix_plan_rejects_unsafe_file_paths():
    db = _session()
    project, _pipeline = _seed(db)
    plan = FixPlan(
        project_id=project.id,
        project_path=project.project_path,
        source_type="manual",
        source_id="",
        title="Unsafe plan",
        summary="Unsafe plan",
        status="draft",
        requires_approval=True,
        fix_type="ci_retry_guidance",
        base_branch="main",
        branch_name="panopticon/safe-branch",
        plan_payload={
            "branch_name": "panopticon/safe-branch",
            "base_branch": "main",
            "files": [{"path": "../.env", "commit_action": "create", "content": "SECRET=1"}],
        },
        last_result={},
        error="",
    )
    db.add(plan)
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        response = client.post(f"/api/fix-plans/{plan.id}/approve")
    finally:
        app.dependency_overrides.clear()
        db.close()

    assert response.status_code == 409
    assert "Parent directory traversal" in response.json()["detail"]
