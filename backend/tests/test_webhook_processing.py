from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.event_handlers.gitlab import process_gitlab_event
from app.config import get_settings
from app.models import ActionDispatch, OperationalEvent, PipelineInsight, Recommendation, RiskAssessment, WebhookReceipt


def test_process_merge_request_and_pipeline_events(monkeypatch):
    monkeypatch.setenv("DRY_RUN_ACTIONS", "true")
    get_settings.cache_clear()

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    mr_result = process_gitlab_event(
        {
            "object_kind": "merge_request",
            "project": {"path_with_namespace": "demo/panopticon"},
            "object_attributes": {"iid": 7, "action": "open", "title": "Checkout deployment change", "state": "opened"},
            "changed_files": ["services/checkout/payment.py", "deploy/kubernetes/deployment.yaml"],
        },
        db,
    )
    pipeline_result = process_gitlab_event(
        {
            "object_kind": "pipeline",
            "project": {"path_with_namespace": "demo/panopticon"},
            "object_attributes": {"id": 99, "status": "failed", "failure_reason": "timeout"},
            "build_log": "Job timeout while pushing docker image",
        },
        db,
    )

    assert mr_result["risk_id"] is not None
    assert pipeline_result["pipeline_insight_id"] is not None
    assert db.query(OperationalEvent).count() == 2
    assert db.query(RiskAssessment).count() == 1
    assert db.query(PipelineInsight).count() == 1
    assert {item.status for item in db.query(Recommendation).all()} == {"dry_run"}
    assert db.query(ActionDispatch).count() == 2


def test_process_duplicate_webhook_event_is_idempotent(monkeypatch):
    monkeypatch.setenv("DRY_RUN_ACTIONS", "true")
    get_settings.cache_clear()

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    payload = {
        "object_kind": "merge_request",
        "project": {"path_with_namespace": "demo/panopticon"},
        "object_attributes": {"iid": 7, "action": "open", "title": "Checkout deployment change", "state": "opened"},
        "changed_files": ["services/checkout/payment.py", "deploy/kubernetes/deployment.yaml"],
    }

    first = process_gitlab_event(payload, db, event_uid="evt-1")
    duplicate = process_gitlab_event(payload, db, event_uid="evt-1")

    assert first["duplicate"] is False
    assert duplicate["duplicate"] is True
    assert db.query(WebhookReceipt).count() == 1
    assert db.query(OperationalEvent).count() == 1
