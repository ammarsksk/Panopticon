from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.database import Base, get_db
from app.main import app
from app.models import ActionApproval, AgentAction, Recommendation, RiskAssessment


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed_gitlab_comment_recommendation(db):
    risk = RiskAssessment(
        project_path="demo/project",
        merge_request_iid="7",
        deployment_ref="",
        score=90,
        level="critical",
        summary="Deployment risk is critical.",
        reasons=["Sensitive files changed."],
        recommendations=["Require owner review."],
    )
    db.add(risk)
    db.flush()
    recommendation = Recommendation(
        project_path="demo/project",
        source_type="risk",
        source_id=str(risk.id),
        channel="gitlab_comment",
        message="Deployment risk is critical.",
        status="pending",
    )
    db.add(recommendation)
    db.commit()
    return recommendation


def test_agent_action_requires_approval_before_execution(monkeypatch):
    monkeypatch.setenv("DRY_RUN_ACTIONS", "true")
    monkeypatch.setenv("DISPATCH_ACTIONS", "true")
    get_settings.cache_clear()
    db = _session()
    _seed_gitlab_comment_recommendation(db)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        proposed = client.post("/api/actions/propose-from-recommendations").json()
        action_id = proposed[0]["id"]

        blocked = client.post(f"/api/actions/{action_id}/execute")
        approved = client.post(f"/api/actions/{action_id}/approve", json={"actor": "tester", "reason": "looks safe"})
        executed = client.post(f"/api/actions/{action_id}/execute")
        detail = client.get(f"/api/actions/{action_id}").json()
    finally:
        app.dependency_overrides.clear()
        db.close()
        get_settings.cache_clear()

    assert proposed[0]["status"] == "pending_approval"
    assert proposed[0]["action_type"] == "gitlab_comment"
    assert proposed[0]["payload_preview"]["target"] == "demo/project!7"
    assert blocked.status_code == 403
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert executed.status_code == 200
    assert executed.json()["status"] == "dry_run"
    assert detail["approvals"][0]["decision"] == "approved"
    assert detail["approvals"][0]["actor"] == "tester"
    assert detail["dispatches"][0]["status"] == "dry_run"


def test_agent_action_rejects_and_dedupes_proposals(monkeypatch):
    monkeypatch.setenv("DRY_RUN_ACTIONS", "true")
    get_settings.cache_clear()
    db = _session()
    _seed_gitlab_comment_recommendation(db)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        first = client.post("/api/actions/propose-from-recommendations").json()
        second = client.post("/api/actions/propose-from-recommendations").json()
        rejected = client.post(f"/api/actions/{first[0]['id']}/reject", json={"actor": "tester", "reason": "not needed"})
    finally:
        app.dependency_overrides.clear()
        db.close()
        get_settings.cache_clear()

    assert first[0]["id"] == second[0]["id"]
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert db.query(AgentAction).count() == 1
    assert db.query(ActionApproval).count() == 1
