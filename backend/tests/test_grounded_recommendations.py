from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.gemini import GeminiReasoner
from app.database import Base, get_db
from app.main import app
from app.models import GitLabProject, PipelineInsight, RepoFileIndex, RiskAssessment, User, Workspace
from app.services.auth import RequestContext, get_current_context
from app.services.grounded_recommendations import GroundedRecommendationEngine, validate_recommendation


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
        workspace_id=1,
        gitlab_project_id="101",
        project_path="demo/checkout-service",
        name="checkout-service",
        namespace="demo",
        default_branch="main",
    )
    db.add(project)
    db.flush()
    risk = RiskAssessment(
        workspace_id=1,
        project_path=project.project_path,
        merge_request_iid="7",
        deployment_ref="risk/checkout-auth",
        score=91,
        level="critical",
        summary="Deployment risk is critical because auth and deployment files changed.",
        reasons=["MR !7 changes checkout auth.", "No tests changed."],
        recommendations=["Require service owner review."],
    )
    pipeline = PipelineInsight(
        workspace_id=1,
        project_path=project.project_path,
        pipeline_id="9001",
        status="failed",
        likely_cause="The test job timed out while waiting for payment gateway dependency latency.",
        evidence=["Pipeline 9001 failed.", "Timeout signature matched."],
        recommendations=["Inspect dependency latency before increasing timeout."],
    )
    repo_file = RepoFileIndex(
        workspace_id=1,
        project_id=project.id,
        project_path=project.project_path,
        file_path=".gitlab-ci.yml",
        ref="main",
        file_type="ci",
        language="yaml",
        size_bytes=120,
        content_sha="sha-ci",
        last_commit_id="abc123",
        content_excerpt="test:\n  timeout: 10m\n  script: pytest tests/checkout\n",
        signals={"risk_flags": ["timeout", "test_coverage"]},
    )
    db.add_all([risk, pipeline, repo_file])
    db.commit()
    return project


def _context():
    return RequestContext(
        user=User(id=1, email="test@example.com", name="Test User"),
        workspace=Workspace(id=1, name="Test Workspace", slug="test"),
        role="owner",
    )


def test_grounded_engine_uses_real_pipeline_and_repo_file_evidence():
    db = _session()
    project = _seed(db)

    bundle = GroundedRecommendationEngine(db, workspace_id=1).recommend(
        project=project,
        question="What should we do about the pipeline timeout?",
        intent="pipeline_failure",
        use_live_reasoner=False,
    )

    assert bundle["issue_type"] == "pipeline_failure"
    assert bundle["grounded"] is True
    assert bundle["confidence"] >= 0.7
    assert any(item.get("file_path") == ".gitlab-ci.yml" for item in bundle["evidence"])
    assert "9001" in bundle["recommendation"]
    assert ".gitlab-ci.yml" in bundle["recommendation"]


def test_grounded_engine_handles_weak_evidence_without_root_cause_claim():
    db = _session()
    project = GitLabProject(workspace_id=1, gitlab_project_id="202", project_path="demo/empty", name="empty")
    db.add(project)
    db.commit()

    bundle = GroundedRecommendationEngine(db, workspace_id=1).recommend(
        project=project,
        question="Why did this fail?",
        intent="pipeline_failure",
        use_live_reasoner=False,
    )

    assert bundle["confidence"] < 0.55
    assert "cannot determine a root cause" in bundle["recommendation"]
    assert bundle["proposed_action"]["requires_approval"] is False


def test_grounded_validation_rejects_hallucinated_files_and_weak_root_cause():
    strong_evidence = [{"type": "repo_files", "id": 1, "file_path": ".gitlab-ci.yml", "label": "ci", "summary": "timeout"}]
    weak_evidence = [{"type": "pipelines", "id": 1, "pipeline_id": "9001", "label": "pipeline", "summary": "failed"}]

    unsupported = validate_recommendation("Change deploy/prod.yaml and pipeline 9001.", strong_evidence)
    weak_claim = validate_recommendation("The pipeline failed because Redis was down.", weak_evidence)

    assert unsupported["grounded"] is False
    assert any("Unsupported file" in error for error in unsupported["errors"])
    assert weak_claim["grounded"] is False
    assert any("Root cause" in error for error in weak_claim["errors"])


def test_grounded_recommendation_api_can_persist_recommendation():
    db = _session()
    project = _seed(db)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_context] = _context
    try:
        response = TestClient(app).post(
            f"/api/projects/{project.id}/recommendations/grounded",
            json={"question": "What should we do about the failed pipeline?", "intent": "pipeline_failure", "persist": True},
        )
    finally:
        app.dependency_overrides.clear()
        db.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload["saved_recommendation"]["source_type"] in {"pipeline", "risk"}
    assert payload["saved_recommendation"]["confidence"] >= 0.7


def test_chat_sends_grounded_bundle_to_gemini(monkeypatch):
    db = _session()
    project = _seed(db)
    captured = {}

    def fake_chat_answer(self, *, question, intent, subject, evidence, deterministic_draft):
        captured["evidence"] = evidence
        captured["deterministic_draft"] = deterministic_draft
        return deterministic_draft

    monkeypatch.setattr(GeminiReasoner, "chat_answer", fake_chat_answer)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_context] = _context
    try:
        response = TestClient(app).post(
            "/api/chat",
            json={"project_id": project.id, "message": "why did the pipeline fail and what should I do?"},
        )
    finally:
        app.dependency_overrides.clear()
        db.close()

    assert response.status_code == 200
    assert "Grounded recommendation" in captured["deterministic_draft"]
    grounded = [item for item in captured["evidence"] if item["type"] == "grounded_recommendation"]
    assert grounded
    assert grounded[0]["confidence"] >= 0.7
    assert any(item.get("file_path") == ".gitlab-ci.yml" for item in grounded[0]["evidence"])
