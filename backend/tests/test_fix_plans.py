from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.database import Base, get_db
from app.main import app
from app.models import ChatMessage, FixPlan, FixPlanApproval, GitLabProject, PipelineInsight, RepoFileIndex
from app.services.fix_plans import FixPlanService, _patch_ci_timeout


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
    db.flush()
    repo_file = RepoFileIndex(
        project_id=project.id,
        project_path="demo/checkout-service",
        file_path=".gitlab-ci.yml",
        ref="main",
        file_type="ci",
        language="yaml",
        size_bytes=120,
        content_sha="sha-ci",
        last_commit_id="abc123",
        content_excerpt="deploy:\n  script: kubectl rollout status deployment/checkout\n",
        signals={"risk_flags": ["deployment", "timeout"]},
    )
    db.add(repo_file)
    db.add_all(
        [
            RepoFileIndex(
                project_id=project.id,
                project_path="demo/checkout-service",
                file_path="services/checkout/auth.py",
                ref="main",
                file_type="source",
                language="python",
                size_bytes=80,
                content_sha="sha-auth",
                last_commit_id="abc123",
                content_excerpt="def login(email, password):\n    return issue_token(email)\n",
                signals={"risk_flags": ["authentication"]},
            ),
            RepoFileIndex(
                project_id=project.id,
                project_path="demo/checkout-service",
                file_path="services/discounts/discounts.py",
                ref="main",
                file_type="source",
                language="python",
                size_bytes=140,
                content_sha="sha-discounts",
                last_commit_id="abc123",
                content_excerpt='def apply_coupon(total, coupon):\n    if coupon == "SAVE10":\n        return total - 10\n    return total\n',
                signals={"risk_flags": ["discount", "coupon"]},
            ),
            RepoFileIndex(
                project_id=project.id,
                project_path="demo/checkout-service",
                file_path="services/inventory/reservations.py",
                ref="main",
                file_type="source",
                language="python",
                size_bytes=90,
                content_sha="sha-inventory",
                last_commit_id="abc123",
                content_excerpt="def reserve_stock(available, requested):\n    return available - requested\n",
                signals={"risk_flags": ["inventory", "stock"]},
            ),
            RepoFileIndex(
                project_id=project.id,
                project_path="demo/checkout-service",
                file_path="services/shipping/estimate.py",
                ref="main",
                file_type="source",
                language="python",
                size_bytes=120,
                content_sha="sha-shipping",
                last_commit_id="abc123",
                content_excerpt="def estimate_delivery_days(country, expedited=False):\n    if expedited:\n        return 2\n    return 5\n",
                signals={"risk_flags": ["shipping", "delivery"]},
            ),
            RepoFileIndex(
                project_id=project.id,
                project_path="demo/checkout-service",
                file_path="README.md",
                ref="main",
                file_type="docs",
                language="markdown",
                size_bytes=80,
                content_sha="sha-readme",
                last_commit_id="abc123",
                content_excerpt="# Checkout Service\n\nRuns checkout.\n",
                signals={"risk_flags": []},
            ),
            RepoFileIndex(
                project_id=project.id,
                project_path="demo/checkout-service",
                file_path="config/service.yaml",
                ref="main",
                file_type="config",
                language="yaml",
                size_bytes=80,
                content_sha="sha-config",
                last_commit_id="abc123",
                content_excerpt="retries: 1\n",
                signals={"risk_flags": []},
            ),
        ]
    )
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
    assert created.json()["plan_payload"]["diff_preview"]
    assert created.json()["plan_payload"]["validation"]["branch_safe"] is True
    assert created.json()["plan_payload"]["validation"]["destructive_changes"] is False
    assert created.json()["plan_payload"]["test_plan"]["commands"]
    assert created.json()["plan_payload"]["rollback"]
    assert any(file["path"] == ".gitlab-ci.yml" and file["commit_action"] == "update" for file in created.json()["plan_payload"]["files"])
    assert created.json()["plan_payload"]["files"][0]["path"] == ".gitlab-ci.yml"
    assert created.json()["plan_payload"]["diff_preview"][0]["path"] == ".gitlab-ci.yml"
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
            "diff_preview": [{"path": "../.env", "commit_action": "create", "diff": "+SECRET=1"}],
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


def test_chat_can_prepare_safe_fix_plan_with_diff_preview(monkeypatch):
    monkeypatch.setattr(
        "app.agents.gemini.GeminiReasoner.chat_answer",
        lambda self, *, question, intent, subject, evidence, deterministic_draft: deterministic_draft,
    )
    db = _session()
    project, _pipeline = _seed(db)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/chat",
            json={"project_id": project.id, "message": "Prepare a safe fix plan for the pipeline timeout."},
        )
    finally:
        app.dependency_overrides.clear()
        db.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload["prepared_fix_plans"]
    assert "Prepared safe fix plan" in payload["assistant_message"]["content"]
    plan = payload["prepared_fix_plans"][0]
    assert plan["plan_payload"]["diff_preview"]
    assert plan["plan_payload"]["validation"]["approval_required"] is True
    assert db.query(FixPlan).count() == 1
    assert db.query(ChatMessage).count() == 2


def test_ci_timeout_patch_updates_job_block_not_file_root():
    patched = _patch_ci_timeout(
        "\n".join(
            [
                "stages:",
                "  - deploy",
                "",
                "deploy-production:",
                "  stage: deploy",
                "  script:",
                "    - kubectl rollout status deployment/checkout",
                "",
            ]
        )
    )

    assert "deploy-production:\n  # Panopticon safety: bound long waits while preserving reviewer visibility.\n  timeout: 20m" in patched
    assert "  retry:\n    max: 1\n    when:\n      - runner_system_failure\n      - stuck_or_timeout_failure" in patched
    assert not patched.startswith("timeout:")


def test_fix_plan_creates_normal_source_code_change_diff():
    db = _session()
    project, _pipeline = _seed(db)

    plan = FixPlanService(db).create(
        project_id=project.id,
        problem_statement="Add validation guard to login code.",
        fix_type="source_validation",
    )

    changed_file = next(item for item in plan.plan_payload["files"] if item["path"] == "services/checkout/auth.py")
    diff = next(item for item in plan.plan_payload["diff_preview"] if item["path"] == "services/checkout/auth.py")["diff"]
    assert "panopticon_require_value" in changed_file["content"]
    assert "+def panopticon_require_value" in diff
    assert plan.plan_payload["validation"]["approval_required"] is True


def test_fix_plan_creates_real_source_bug_fix_diff_from_indexed_code():
    db = _session()
    project, _pipeline = _seed(db)

    plan = FixPlanService(db).create(
        project_id=project.id,
        problem_statement="Fix the failing discount coupon bug. SAVE10 should apply a 10 percent discount.",
        fix_type="source_bug_fix",
    )

    changed_file = next(item for item in plan.plan_payload["files"] if item["path"] == "services/discounts/discounts.py")
    diff = next(item for item in plan.plan_payload["diff_preview"] if item["path"] == "services/discounts/discounts.py")["diff"]
    assert changed_file["content"].count("return round(total * 0.90, 2)") == 1
    assert "-        return total - 10" in diff
    assert "+        return round(total * 0.90, 2)" in diff
    assert plan.fix_type == "source_bug_fix"


def test_fix_plan_creates_multi_file_source_bug_fix_diffs():
    db = _session()
    project, _pipeline = _seed(db)

    plan = FixPlanService(db).create(
        project_id=project.id,
        problem_statement="Fix all failing tests: discount coupon, inventory reservation, and shipping estimate bugs.",
        fix_type="multi_file_bug_fix",
    )

    files = {item["path"]: item["content"] for item in plan.plan_payload["files"]}
    assert "services/discounts/discounts.py" in files
    assert "services/inventory/reservations.py" in files
    assert "services/shipping/estimate.py" in files
    assert "return round(total * 0.90, 2)" in files["services/discounts/discounts.py"]
    assert "requested quantity exceeds available stock" in files["services/inventory/reservations.py"]
    assert "return 1 if expedited else 3" in files["services/shipping/estimate.py"]


def test_fix_plan_creates_docs_and_config_code_change_diffs():
    db = _session()
    project, _pipeline = _seed(db)

    docs_plan = FixPlanService(db).create(
        project_id=project.id,
        problem_statement="Document validation and rollback steps.",
        fix_type="documentation_update",
    )
    config_plan = FixPlanService(db).create(
        project_id=project.id,
        problem_statement="Add config validation guidance.",
        fix_type="config_validation",
    )

    assert any(item["path"] == "README.md" and "Panopticon change note" in item["content"] for item in docs_plan.plan_payload["files"])
    assert any(item["path"] == "config/service.yaml" and "Panopticon validation" in item["content"] for item in config_plan.plan_payload["files"])
    assert any("+## Panopticon change note" in item["diff"] for item in docs_plan.plan_payload["diff_preview"])
    assert any("+# Panopticon validation" in item["diff"] for item in config_plan.plan_payload["diff_preview"])
