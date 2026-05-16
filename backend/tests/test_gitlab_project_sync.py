from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import GitLabProject, JobSnapshot, MergeRequestSnapshot, PipelineSnapshot
from app.services.gitlab_sync import GitLabProjectSyncService


class FakeGitLabClient:
    configured = True

    def list_projects(self, limit=50):
        return [
            {
                "id": 101,
                "name": "checkout-service",
                "path_with_namespace": "demo/checkout-service",
                "namespace": {"full_path": "demo"},
                "web_url": "https://gitlab.com/demo/checkout-service",
                "default_branch": "main",
                "visibility": "private",
                "description": "Checkout API",
                "last_activity_at": "2026-05-16T06:00:00.000Z",
            }
        ]

    def list_open_merge_requests(self, project_path, limit=20):
        assert project_path == "demo/checkout-service"
        return [
            {
                "iid": 7,
                "title": "Update checkout auth",
                "state": "opened",
                "web_url": "https://gitlab.com/demo/checkout-service/-/merge_requests/7",
                "author": {"username": "ammarsaifeek"},
                "source_branch": "auth-update",
                "target_branch": "main",
                "draft": False,
                "created_at": "2026-05-16T05:00:00.000Z",
                "updated_at": "2026-05-16T06:00:00.000Z",
            }
        ]

    def list_pipelines(self, project_path, limit=10):
        assert project_path == "demo/checkout-service"
        return [
            {
                "id": 9001,
                "status": "failed",
                "ref": "auth-update",
                "sha": "abc123",
                "web_url": "https://gitlab.com/demo/checkout-service/-/pipelines/9001",
                "created_at": "2026-05-16T05:10:00.000Z",
                "updated_at": "2026-05-16T05:20:00.000Z",
            }
        ]

    def get_pipeline_jobs(self, project_path, pipeline_id):
        assert project_path == "demo/checkout-service"
        assert pipeline_id == "9001"
        return [
            {
                "id": 333,
                "name": "test",
                "stage": "test",
                "status": "failed",
                "failure_reason": "script_failure",
                "web_url": "https://gitlab.com/demo/checkout-service/-/jobs/333",
                "duration": 42.5,
                "created_at": "2026-05-16T05:11:00.000Z",
            }
        ]


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_gitlab_project_sync_persists_projects_mrs_pipelines_and_failed_jobs():
    db = _session()

    run = GitLabProjectSyncService(db, client=FakeGitLabClient()).sync()

    assert run.status == "completed"
    assert run.projects_updated == 1
    assert run.merge_requests_seen == 1
    assert run.pipelines_seen == 1
    assert run.jobs_seen == 1
    assert db.query(GitLabProject).count() == 1
    assert db.query(MergeRequestSnapshot).count() == 1
    assert db.query(PipelineSnapshot).count() == 1
    assert db.query(JobSnapshot).count() == 1

    project = db.query(GitLabProject).one()
    assert project.project_path == "demo/checkout-service"
    assert project.open_merge_requests_count == 1
    assert project.failed_pipelines_count == 1
    assert project.latest_pipeline_status == "failed"


def test_projects_api_returns_synced_project_summary():
    db = _session()
    GitLabProjectSyncService(db, client=FakeGitLabClient()).sync()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        projects = client.get("/api/projects").json()
        summary = client.get(f"/api/projects/{projects[0]['id']}/summary").json()
    finally:
        app.dependency_overrides.clear()
        db.close()

    assert projects[0]["project_path"] == "demo/checkout-service"
    assert summary["project"]["project_path"] == "demo/checkout-service"
    assert summary["open_merge_requests"][0]["merge_request_iid"] == "7"
    assert summary["latest_pipelines"][0]["status"] == "failed"
    assert summary["failed_jobs"][0]["name"] == "test"
