import hashlib
import hmac
import json
import time
from dataclasses import replace
from urllib.parse import urlencode

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.database import Base, get_db
from app.main import app
from app import main as main_module
from app.models import AgentAction, GitLabProject, Recommendation, RiskAssessment


SECRET = "slack-test-secret"


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
        latest_pipeline_id="9001",
        latest_pipeline_status="failed",
        open_merge_requests_count=2,
        failed_pipelines_count=1,
    )
    risk = RiskAssessment(
        project_path="demo/checkout-service",
        merge_request_iid="7",
        deployment_ref="",
        score=91,
        level="critical",
        summary="Deployment risk is critical.",
        reasons=["Auth files changed."],
        recommendations=["Require owner review."],
    )
    recommendation = Recommendation(
        project_path="demo/checkout-service",
        source_type="risk",
        source_id="1",
        channel="gitlab_comment",
        message="Deployment risk is critical.",
        status="dry_run",
    )
    db.add_all([project, risk, recommendation])
    db.flush()
    action = AgentAction(
        recommendation_id=recommendation.id,
        project_path="demo/checkout-service",
        action_type="gitlab_comment",
        channel="gitlab_comment",
        title="Deployment risk detected",
        summary="Require owner review before deployment.",
        status="pending_approval",
        requires_approval=True,
        payload_preview={"body": "Require owner review."},
        execution_context={"merge_request_iid": "7"},
        last_result={},
        error="",
    )
    db.add(action)
    db.commit()
    return project, action


def _signed_headers(body: bytes, secret: str = SECRET) -> dict[str, str]:
    timestamp = str(int(time.time()))
    base = b"v0:" + timestamp.encode("utf-8") + b":" + body
    signature = "v0=" + hmac.new(secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    return {
        "X-Slack-Request-Timestamp": timestamp,
        "X-Slack-Signature": signature,
        "Content-Type": "application/x-www-form-urlencoded",
    }


def _client(monkeypatch, db):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("APP_PUBLIC_URL", "http://localhost:3000")
    get_settings.cache_clear()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_slack_command_requires_valid_signature(monkeypatch):
    db = _session()
    _seed(db)
    client = _client(monkeypatch, db)
    body = urlencode({"text": "risks"}).encode("utf-8")
    headers = _signed_headers(body, secret="wrong-secret")
    try:
        response = client.post("/slack/commands", content=body, headers=headers)
    finally:
        app.dependency_overrides.clear()
        db.close()
        get_settings.cache_clear()

    assert response.status_code == 403


def test_slack_risks_and_project_commands(monkeypatch):
    db = _session()
    _seed(db)
    client = _client(monkeypatch, db)
    risks_body = urlencode({"text": "risks", "user_name": "ammar"}).encode("utf-8")
    project_body = urlencode({"text": "project checkout", "user_name": "ammar"}).encode("utf-8")
    try:
        risks = client.post("/slack/commands", content=risks_body, headers=_signed_headers(risks_body)).json()
        project = client.post("/slack/commands", content=project_body, headers=_signed_headers(project_body)).json()
    finally:
        app.dependency_overrides.clear()
        db.close()
        get_settings.cache_clear()

    assert risks["response_type"] == "ephemeral"
    assert "Deployment risk is critical" in risks["text"]
    assert "demo/checkout-service" in project["text"]
    assert "failed" in project["text"]


def test_slack_actions_command_and_interaction_approval(monkeypatch):
    db = _session()
    _, action = _seed(db)
    client = _client(monkeypatch, db)
    actions_body = urlencode({"text": "actions", "user_name": "ammar"}).encode("utf-8")
    payload = {
        "user": {"username": "ammar"},
        "actions": [{"action_id": "approve_action", "value": f"approve:{action.id}"}],
    }
    interaction_body = urlencode({"payload": json.dumps(payload)}).encode("utf-8")
    try:
        listed = client.post("/slack/commands", content=actions_body, headers=_signed_headers(actions_body)).json()
        approved = client.post("/slack/interactions", content=interaction_body, headers=_signed_headers(interaction_body)).json()
        db.refresh(action)
    finally:
        app.dependency_overrides.clear()
        db.close()
        get_settings.cache_clear()

    assert "Pending Panopticon approvals" in listed["text"]
    assert listed["blocks"]
    assert "Approved action" in approved["text"]
    assert action.status == "approved"


def test_slack_events_url_verification(monkeypatch):
    db = _session()
    _seed(db)
    client = _client(monkeypatch, db)
    body = json.dumps({"type": "url_verification", "challenge": "challenge-token"}).encode("utf-8")
    headers = _signed_headers(body)
    headers["Content-Type"] = "application/json"
    try:
        response = client.post("/slack/events", content=body, headers=headers)
    finally:
        app.dependency_overrides.clear()
        db.close()
        get_settings.cache_clear()

    assert response.status_code == 200
    assert response.json() == {"challenge": "challenge-token"}


def test_slack_status_reports_app_configuration(monkeypatch):
    monkeypatch.setattr(
        main_module,
        "settings",
        replace(
            main_module.settings,
            slack_webhook_url="https://hooks.slack.test/services/demo",
            slack_signing_secret="secret",
            slack_bot_token="xoxb-test",
            slack_default_channel="#panopticon",
            dry_run_actions=True,
        ),
    )
    db = _session()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).get("/api/integrations/slack")
    finally:
        app.dependency_overrides.clear()
        db.close()

    status = response.json()
    assert status["webhook_configured"] is True
    assert status["signing_secret_configured"] is True
    assert status["bot_token_configured"] is True
    assert status["default_channel"] == "#panopticon"
