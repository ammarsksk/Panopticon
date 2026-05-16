from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Recommendation, RiskAssessment


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
    assert summary["active_risks"] == 1
