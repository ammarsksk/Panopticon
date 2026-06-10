from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base, get_db
from app.main import app


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _client(db):
    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def _workspace_id(db, email: str) -> int:
    user = db.scalar(select(models.User).where(models.User.email == email))
    membership = db.scalar(select(models.WorkspaceMember).where(models.WorkspaceMember.user_id == user.id))
    return membership.workspace_id


def test_signup_login_and_workspace_scoped_project_lists():
    db = _session()
    first = _client(db)
    second = _client(db)
    try:
        created = first.post(
            "/api/auth/signup",
            json={"email": "one@example.com", "password": "password-123", "name": "One", "workspace_name": "One Workspace"},
        )
        assert created.status_code == 200
        assert created.json()["workspace"]["slug"] == "one-workspace"

        other = second.post(
            "/api/auth/signup",
            json={"email": "two@example.com", "password": "password-456", "name": "Two", "workspace_name": "Two Workspace"},
        )
        assert other.status_code == 200

        workspace_one = _workspace_id(db, "one@example.com")
        workspace_two = _workspace_id(db, "two@example.com")
        db.add_all(
            [
                models.GitLabProject(
                    workspace_id=workspace_one,
                    gitlab_project_id="101",
                    project_path="team-one/app",
                    name="app",
                    namespace="team-one",
                    web_url="https://gitlab.com/team-one/app",
                ),
                models.GitLabProject(
                    workspace_id=workspace_two,
                    gitlab_project_id="202",
                    project_path="team-two/api",
                    name="api",
                    namespace="team-two",
                    web_url="https://gitlab.com/team-two/api",
                ),
            ]
        )
        db.commit()

        first_projects = first.get("/api/projects").json()
        second_projects = second.get("/api/projects").json()

        assert [item["project_path"] for item in first_projects] == ["team-one/app"]
        assert [item["project_path"] for item in second_projects] == ["team-two/api"]
        assert second.get(f"/api/projects/{first_projects[0]['id']}").status_code == 404
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_local_dev_context_claims_unscoped_legacy_records():
    db = _session()
    client = _client(db)
    try:
        db.add(models.GitLabProject(gitlab_project_id="101", project_path="legacy/app", name="app", namespace="legacy", web_url=""))
        db.commit()

        response = client.get("/api/projects")

        assert response.status_code == 200
        assert response.json()[0]["project_path"] == "legacy/app"
        project = db.scalar(select(models.GitLabProject).where(models.GitLabProject.project_path == "legacy/app"))
        assert project.workspace_id is not None
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_auth_context_skips_duplicate_unscoped_gitlab_projects():
    db = _session()
    client = _client(db)
    try:
        assert client.get("/api/projects").status_code == 200
        workspace = db.scalar(select(models.Workspace).where(models.Workspace.slug == "local-dev"))
        db.add_all(
            [
                models.GitLabProject(
                    workspace_id=workspace.id,
                    gitlab_project_id="82175117",
                    project_path="ammarsaifeek/panopticon",
                    name="panopticon",
                    namespace="ammarsaifeek",
                    web_url="https://gitlab.com/ammarsaifeek/panopticon",
                ),
                models.GitLabProject(
                    workspace_id=None,
                    gitlab_project_id="82175117",
                    project_path="ammarsaifeek/panopticon",
                    name="panopticon",
                    namespace="ammarsaifeek",
                    web_url="https://gitlab.com/ammarsaifeek/panopticon",
                ),
            ]
        )
        db.commit()

        response = client.get("/api/projects")

        assert response.status_code == 200
        assert [item["project_path"] for item in response.json()] == ["ammarsaifeek/panopticon"]
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_auth_context_claims_only_one_duplicate_unscoped_gitlab_project_batch():
    db = _session()
    client = _client(db)
    try:
        db.add_all(
            [
                models.GitLabProject(
                    workspace_id=None,
                    gitlab_project_id="82175117",
                    project_path="ammarsaifeek/panopticon",
                    name="panopticon",
                    namespace="ammarsaifeek",
                    web_url="https://gitlab.com/ammarsaifeek/panopticon",
                ),
                models.GitLabProject(
                    workspace_id=None,
                    gitlab_project_id="82175117",
                    project_path="ammarsaifeek/panopticon",
                    name="panopticon duplicate",
                    namespace="ammarsaifeek",
                    web_url="https://gitlab.com/ammarsaifeek/panopticon",
                ),
            ]
        )
        db.commit()

        response = client.get("/api/projects")

        assert response.status_code == 200
        assert [item["project_path"] for item in response.json()] == ["ammarsaifeek/panopticon"]
        workspace = db.scalar(select(models.Workspace).where(models.Workspace.slug == "local-dev"))
        scoped_count = db.query(models.GitLabProject).filter(models.GitLabProject.workspace_id == workspace.id).count()
        unscoped_count = db.query(models.GitLabProject).filter(models.GitLabProject.workspace_id.is_(None)).count()
        assert scoped_count == 1
        assert unscoped_count == 1
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_memory_endpoint_sanitizes_legacy_json_shapes():
    db = _session()
    client = _client(db)
    try:
        assert client.get("/api/projects").status_code == 200
        workspace = db.scalar(select(models.Workspace).where(models.Workspace.slug == "local-dev"))
        db.add(
            models.MemoryRecord(
                workspace_id=workspace.id,
                project_path="legacy/app",
                memory_type="pipeline_failure",
                signature="legacy-shape",
                summary="Legacy record with non-list JSON fields",
                evidence={"job": "deploy failed"},
                remediation=None,
            )
        )
        db.commit()

        response = client.get("/api/memory")

        assert response.status_code == 200
        payload = response.json()
        assert payload[0]["evidence"] == ["job: deploy failed"]
        assert payload[0]["remediation"] == []
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_dashboard_summary_sanitizes_legacy_oauth_scopes():
    db = _session()
    client = _client(db)
    try:
        assert client.get("/api/projects").status_code == 200
        workspace = db.scalar(select(models.Workspace).where(models.Workspace.slug == "local-dev"))
        user = db.scalar(select(models.User).where(models.User.email == "local@panopticon.dev"))
        db.add(
            models.OAuthConnection(
                provider="gitlab",
                workspace_id=workspace.id,
                user_id=user.id,
                provider_user_id="legacy-user",
                account_label="legacy",
                access_token_encrypted="",
                scopes="api read_user",
                metadata_json={},
            )
        )
        db.commit()

        response = client.get("/api/dashboard/summary")

        assert response.status_code == 200
        assert response.json()["gitlab_status"]["scopes"] == ["api", "read_user"]
    finally:
        app.dependency_overrides.clear()
        db.close()
