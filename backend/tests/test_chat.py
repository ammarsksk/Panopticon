from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.gemini import GeminiReasoner
from app.database import Base, get_db
from app.main import app
from app.models import ChatMessage, ChatThread, GitLabProject, MergeRequestSnapshot, PipelineInsight, PipelineSnapshot, Recommendation, RiskAssessment


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed_project_context(db):
    project = GitLabProject(
        gitlab_project_id="101",
        project_path="demo/checkout-service",
        name="checkout-service",
        namespace="demo",
        web_url="https://gitlab.com/demo/checkout-service",
        default_branch="main",
        visibility="private",
    )
    db.add(project)
    risk = RiskAssessment(
        project_path="demo/checkout-service",
        merge_request_iid="7",
        deployment_ref="",
        score=90,
        level="critical",
        summary="Deployment risk is critical at 90/100.",
        reasons=["Auth files changed."],
        recommendations=["Require owner review."],
    )
    pipeline = PipelineSnapshot(
        gitlab_project_id="101",
        project_path="demo/checkout-service",
        pipeline_id="9001",
        status="failed",
        ref="main",
        sha="abc123",
        web_url="https://gitlab.com/demo/checkout-service/-/pipelines/9001",
    )
    insight = PipelineInsight(
        project_path="demo/checkout-service",
        pipeline_id="9001",
        status="failed",
        likely_cause="The test job timed out while waiting for the payment gateway.",
        evidence=["Matched timeout signature.", "Job exceeded external service wait limit."],
        recommendations=["Check dependency latency before raising the timeout."],
    )
    mr = MergeRequestSnapshot(
        gitlab_project_id="101",
        project_path="demo/checkout-service",
        merge_request_iid="7",
        title="Risky checkout auth change",
        state="opened",
        web_url="https://gitlab.com/demo/checkout-service/-/merge_requests/7",
        author_username="ammar",
        source_branch="risk/checkout-auth",
        target_branch="main",
        draft=False,
    )
    db.add_all([risk, pipeline, insight, mr])
    db.flush()
    recommendation = Recommendation(
        project_path="demo/checkout-service",
        source_type="risk",
        source_id=str(risk.id),
        channel="gitlab_comment",
        message="Deployment risk is critical.",
        status="dry_run",
    )
    db.add(recommendation)
    db.commit()
    return project


def test_chat_answers_from_project_context_and_cites_records():
    db = _session()
    project = _seed_project_context(db)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/chat",
            json={"project_id": project.id, "message": "Why is this project risky and what should I inspect?"},
        )
    finally:
        app.dependency_overrides.clear()
        db.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload["thread"]["project_path"] == "demo/checkout-service"
    assert payload["assistant_message"]["content"].startswith("Risk analysis")
    assert "Deployment risk is critical" in payload["assistant_message"]["content"]
    assert "Pipeline state" not in payload["assistant_message"]["content"]
    assert payload["assistant_message"]["citations"]
    assert db.query(ChatThread).count() == 1
    assert db.query(ChatMessage).count() == 2


def test_chat_routes_pipeline_questions_to_pipeline_answer():
    db = _session()
    project = _seed_project_context(db)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/chat",
            json={"project_id": project.id, "message": "why did the pipeline fail?"},
        )
    finally:
        app.dependency_overrides.clear()
        db.close()

    assert response.status_code == 200
    payload = response.json()
    answer = payload["assistant_message"]["content"]
    citations = payload["assistant_message"]["citations"]
    assert answer.startswith("Pipeline analysis")
    assert "test job timed out" in answer
    assert "Highest recent risk" not in answer
    assert {citation["type"] for citation in citations} <= {"pipeline_insights", "failed_jobs", "pipelines"}


def test_chat_routes_risk_questions_to_risk_answer():
    db = _session()
    project = _seed_project_context(db)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/chat",
            json={"project_id": project.id, "message": "why is this deployment risky?"},
        )
    finally:
        app.dependency_overrides.clear()
        db.close()

    assert response.status_code == 200
    payload = response.json()
    answer = payload["assistant_message"]["content"]
    citations = payload["assistant_message"]["citations"]
    assert answer.startswith("Risk analysis")
    assert "Deployment risk is critical" in answer
    assert "Pipeline state" not in answer
    assert {citation["type"] for citation in citations} <= {"risks", "recommendations"}


def test_chat_invokes_gemini_reasoner_with_focused_evidence(monkeypatch):
    db = _session()
    project = _seed_project_context(db)
    captured = {}

    def fake_chat_answer(self, *, question, intent, subject, evidence, deterministic_draft):
        captured["question"] = question
        captured["intent"] = intent
        captured["subject"] = subject
        captured["evidence"] = evidence
        captured["deterministic_draft"] = deterministic_draft
        return "LLM answer: the payment gateway wait caused the pipeline failure. Inspect dependency latency."

    monkeypatch.setattr(GeminiReasoner, "chat_answer", fake_chat_answer)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/chat",
            json={"project_id": project.id, "message": "why did the pipeline fail?"},
        )
    finally:
        app.dependency_overrides.clear()
        db.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload["assistant_message"]["content"].startswith("LLM answer")
    assert captured["intent"] == "pipeline_failure"
    assert captured["subject"] == "demo/checkout-service"
    assert "Pipeline analysis" in captured["deterministic_draft"]
    assert {item["type"] for item in captured["evidence"]} <= {"pipeline_insights", "failed_jobs", "pipelines"}


def test_chat_can_prepare_actions_without_executing_them():
    db = _session()
    project = _seed_project_context(db)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/chat",
            json={"project_id": project.id, "message": "Prepare actions for this project."},
        )
        actions = client.get("/api/actions").json()
    finally:
        app.dependency_overrides.clear()
        db.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload["prepared_actions"]
    assert payload["prepared_actions"][0]["status"] == "pending_approval"
    assert payload["assistant_message"]["prepared_action_ids"] == [payload["prepared_actions"][0]["id"]]
    assert "require approval" in payload["assistant_message"]["content"].lower()
    assert actions[0]["status"] == "pending_approval"


def test_chat_rejects_unknown_project_id():
    db = _session()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        response = client.post("/api/chat", json={"project_id": 999, "message": "What is happening?"})
    finally:
        app.dependency_overrides.clear()
        db.close()

    assert response.status_code == 404
