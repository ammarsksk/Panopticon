import base64

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import ActionDispatch, GitLabProject, IncidentRecord, JobSnapshot, MemoryRecord, MergeRequestSnapshot, PipelineInsight, PipelineSnapshot, Recommendation, RepoFileIndex, RiskAssessment, User, Workspace
from app.services.auth import RequestContext, get_current_context
from app.services.gitlab_sync import GitLabProjectSyncService
from app.services.agent_tools import AgentToolService
from app.integrations.gitlab import _dedupe_projects


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

    def get_job_trace(self, project_path, job_id):
        assert project_path == "demo/checkout-service"
        assert job_id == "333"
        return "Running pytest\nERROR tests/test_checkout.py::test_payment_timeout failed after gateway timeout\nAPI_TOKEN=secret-value\n"

    def list_repository_tree(self, project_path, ref, recursive=True, limit=100):
        assert project_path == "demo/checkout-service"
        assert ref == "main"
        return [
            {"type": "blob", "path": ".gitlab-ci.yml", "size": 60},
            {"type": "blob", "path": "services/checkout/auth.py", "size": 80},
            {"type": "blob", "path": "logo.png", "size": 2000},
        ]

    def get_repository_file(self, project_path, file_path, ref):
        content = {
            ".gitlab-ci.yml": "test:\n  script: pytest\n",
            "services/checkout/auth.py": "API_TOKEN = 'secret'\ndef login():\n    return True\n",
        }[file_path]
        return {
            "file_path": file_path,
            "encoding": "base64",
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "size": len(content.encode("utf-8")),
            "content_sha256": f"sha-{file_path}",
            "last_commit_id": "commit-1",
        }


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
    assert db.query(PipelineInsight).count() == 1
    assert db.query(Recommendation).count() >= 1
    assert db.query(RiskAssessment).count() == 1
    assert db.query(RepoFileIndex).count() == 2

    project = db.query(GitLabProject).one()
    assert project.project_path == "demo/checkout-service"
    assert project.open_merge_requests_count == 1
    assert project.failed_pipelines_count == 1
    assert project.latest_pipeline_status == "failed"
    assert "REDACTED" in db.query(RepoFileIndex).filter(RepoFileIndex.file_path == "services/checkout/auth.py").one().content_excerpt
    job = db.query(JobSnapshot).one()
    assert job.failure_signature in {"timeout", "test_failure"}
    assert "test_payment_timeout" in job.trace_summary
    assert "REDACTED" in job.trace_excerpt


def test_pipeline_job_trace_refresh_can_run_on_demand():
    db = _session()
    project = GitLabProject(
        gitlab_project_id="101",
        project_path="demo/checkout-service",
        name="checkout-service",
        namespace="demo",
        web_url="https://gitlab.com/demo/checkout-service",
        default_branch="main",
    )
    db.add(project)
    db.commit()

    jobs = GitLabProjectSyncService(db, client=FakeGitLabClient()).refresh_pipeline_jobs(project, "9001")

    assert len(jobs) == 1
    assert jobs[0].job_id == "333"
    assert jobs[0].trace_summary
    assert jobs[0].failure_signature in {"timeout", "test_failure"}
    db.close()


def test_mcp_pipeline_job_trace_refresh_tool_uses_project_scope():
    db = _session()
    project = GitLabProject(
        workspace_id=7,
        gitlab_project_id="101",
        project_path="demo/checkout-service",
        name="checkout-service",
        namespace="demo",
        web_url="https://gitlab.com/demo/checkout-service",
        default_branch="main",
    )
    db.add(project)
    db.commit()

    service = AgentToolService(db, workspace_id=7)
    service_client = FakeGitLabClient()
    original = GitLabProjectSyncService.__init__

    def fake_init(self, db, client=None, workspace_id=None):
        original(self, db, client=service_client, workspace_id=workspace_id)

    GitLabProjectSyncService.__init__ = fake_init
    try:
        result = service.call_tool("refresh_pipeline_job_traces", {"project_id": project.id, "pipeline_id": "9001"})
    finally:
        GitLabProjectSyncService.__init__ = original
        db.close()

    assert result["jobs"][0]["job_id"] == "333"
    assert result["jobs"][0]["trace_summary"]


def test_project_listing_dedupes_membership_and_owned_projects():
    projects = _dedupe_projects(
        [
            {"id": 101, "path_with_namespace": "demo/app"},
            {"id": 101, "path_with_namespace": "demo/app"},
            {"id": 202, "path_with_namespace": "demo/api"},
        ]
    )

    assert [project["path_with_namespace"] for project in projects] == ["demo/app", "demo/api"]


def test_projects_api_returns_synced_project_summary():
    db = _session()
    GitLabProjectSyncService(db, client=FakeGitLabClient(), workspace_id=1).sync()
    risk = RiskAssessment(
        workspace_id=1,
        project_path="demo/checkout-service",
        merge_request_iid="7",
        deployment_ref="",
        score=85,
        level="critical",
        summary="Deployment risk is critical at 85/100.",
        reasons=["Auth and deployment files changed."],
        recommendations=["Require owner review."],
    )
    incident = IncidentRecord(
        workspace_id=1,
        project_path="demo/checkout-service",
        title="Checkout rollback",
        severity="critical",
        probable_root_cause="Auth config changed before rollback.",
        timeline=[{"time": "now", "event": "rollback"}],
        recommendations=["Compare deployment config."],
    )
    recommendation = Recommendation(
        workspace_id=1,
        project_path="demo/checkout-service",
        source_type="risk",
        source_id="1",
        channel="gitlab_comment",
        message="Deployment risk is critical.\n\nVertex Gemini analysis:\nAuth config changed before rollback.",
        status="dry_run",
    )
    memory = MemoryRecord(
        workspace_id=1,
        project_path="demo/checkout-service",
        memory_type="incident",
        signature="checkout-auth-rollback",
        summary="Auth changes correlated with rollback.",
        evidence=["Rollback after auth change."],
        remediation=["Add auth config validation."],
    )
    db.add_all([risk, incident, recommendation, memory])
    db.flush()
    db.add(
        ActionDispatch(
            workspace_id=1,
            recommendation_id=recommendation.id,
            channel="gitlab_comment",
            status="dry_run",
            target="demo/checkout-service!7",
            request_payload={"message": recommendation.message},
            response_payload={"status": "dry_run"},
        )
    )
    db.commit()

    def override_db():
        yield db

    def override_context():
        return RequestContext(
            user=User(id=1, email="test@example.com", name="Test User"),
            workspace=Workspace(id=1, name="Test Workspace", slug="test"),
            role="owner",
        )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_context] = override_context
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
    assert summary["failed_jobs"][0]["trace_summary"]
    assert any(item["score"] == 85 for item in summary["active_risks"])
    assert summary["recent_incidents"][0]["title"] == "Checkout rollback"
    assert summary["latest_recommendations"][0]["title"] == "Deployment risk detected"
    assert summary["recent_actions"][0]["status"] == "dry_run"
    assert summary["memory_records"][0]["signature"] == "checkout-auth-rollback"
    assert summary["repo_context_summary"]["indexed_files"] == 2
    assert summary["repo_files"][0]["file_path"] == ".gitlab-ci.yml"
