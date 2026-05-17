from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import PipelineInsight, Recommendation, RiskAssessment


def test_dashboard_shapes_recommendations_and_dedupes_repeated_risks():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    risk = RiskAssessment(
        project_path="demo/project",
        merge_request_iid="7",
        deployment_ref="",
        score=85,
        level="critical",
        summary="Deployment risk is critical at 85/100.",
        reasons=["Sensitive operational files changed."],
        recommendations=["Require owner review before deployment."],
    )
    duplicate_risk = RiskAssessment(
        project_path="demo/project",
        merge_request_iid="7",
        deployment_ref="",
        score=85,
        level="critical",
        summary="Deployment risk is critical at 85/100.",
        reasons=["Sensitive operational files changed."],
        recommendations=["Require owner review before deployment."],
    )
    db.add_all([risk, duplicate_risk])
    db.flush()

    message = (
        "Deployment risk is critical at 85/100. Require owner review before deployment.\n\n"
        "Vertex Gemini analysis:\n"
        "**Risk Score:** 95/100\n"
        "**Risk Level:** Critical"
    )
    db.add_all(
        [
            Recommendation(
                project_path="demo/project",
                source_type="risk",
                source_id=str(risk.id),
                channel="gitlab_comment",
                message=message,
                status="dry_run",
            ),
            Recommendation(
                project_path="demo/project",
                source_type="risk",
                source_id=str(risk.id),
                channel="gitlab_comment",
                message=message,
                status="dry_run",
            ),
        ]
    )
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        recommendations = client.get("/api/recommendations").json()
        summary = client.get("/api/dashboard/summary").json()
    finally:
        app.dependency_overrides.clear()
        db.close()

    assert len(recommendations) == 1
    assert recommendations[0]["title"] == "Deployment risk detected"
    assert recommendations[0]["summary"] == "Deployment risk is critical at 85/100. Require owner review before deployment."
    assert recommendations[0]["gemini_analysis"] == "Risk Score: 95/100\nRisk Level: Critical"
    assert recommendations[0]["evidence"] == ["Sensitive operational files changed."]
    assert recommendations[0]["next_actions"] == ["Require owner review before deployment."]
    assert recommendations[0]["origin"] == "demo"
    assert recommendations[0]["severity"] == "critical"
    assert recommendations[0]["confidence"] >= 0.9
    assert recommendations[0]["action_type"] == "gitlab_comment"
    assert recommendations[0]["can_execute"] is True
    assert recommendations[0]["requires_approval"] is True
    assert recommendations[0]["approval_state"] == "dry_run_ready"
    assert recommendations[0]["rank_score"] > 100
    assert summary["active_risks"] == 1


def test_recommendations_are_ranked_and_filterable_by_v2_fields():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    risk = RiskAssessment(
        project_path="demo/project",
        merge_request_iid="8",
        deployment_ref="",
        score=92,
        level="critical",
        summary="Deployment risk is critical.",
        reasons=["Deployment and auth files changed.", "No tests changed."],
        recommendations=["Require owner review.", "Confirm rollback."],
    )
    pipeline = PipelineInsight(
        project_path="demo/project",
        pipeline_id="99",
        status="failed",
        likely_cause="Pipeline timed out.",
        evidence=["Matched timeout signature."],
        recommendations=["Check dependency latency."],
    )
    db.add_all([risk, pipeline])
    db.flush()
    db.add_all(
        [
            Recommendation(
                project_path="demo/project",
                source_type="pipeline",
                source_id=str(pipeline.id),
                channel="slack",
                message="Pipeline failure detected.",
                status="dry_run",
            ),
            Recommendation(
                project_path="demo/project",
                source_type="risk",
                source_id=str(risk.id),
                channel="gitlab_comment",
                message="Deployment risk is critical.",
                status="dry_run",
            ),
        ]
    )
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        all_recommendations = client.get("/api/recommendations").json()
        critical = client.get("/api/recommendations?severity=critical").json()
        slack_alerts = client.get("/api/recommendations?action_type=slack_alert").json()
    finally:
        app.dependency_overrides.clear()
        db.close()

    assert [item["source_type"] for item in all_recommendations] == ["risk", "pipeline"]
    assert all_recommendations[0]["rank_score"] > all_recommendations[1]["rank_score"]
    assert len(critical) == 1
    assert critical[0]["source_type"] == "risk"
    assert len(slack_alerts) == 1
    assert slack_alerts[0]["action_type"] == "slack_alert"
    assert slack_alerts[0]["requires_approval"] is True
