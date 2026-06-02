import base64

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import GitLabProject, RepoFileIndex
from app.services.agent_tools import AgentToolService
from app.services.chat import _citation, _llm_evidence
from app.services.repo_context import RepoContextService, classify_file_type, detect_language, extract_signals


class FakeRepoClient:
    configured = True

    def list_repository_tree(self, project_path, ref, recursive=True, limit=100):
        return [
            {"type": "blob", "path": ".gitlab-ci.yml", "size": 25},
            {"type": "blob", "path": "deploy/kubernetes/deployment.yaml", "size": 50},
            {"type": "blob", "path": "services/api/payment.py", "size": 80},
            {"type": "blob", "path": "assets/logo.png", "size": 3000},
        ]

    def get_repository_file(self, project_path, file_path, ref):
        content = {
            ".gitlab-ci.yml": "deploy:\n  script: kubectl apply -f deploy\n",
            "deploy/kubernetes/deployment.yaml": "kind: Deployment\nmetadata:\n  name: checkout\n",
            "services/api/payment.py": "PAYMENT_API_KEY = 'abc'\ndef charge():\n    return 'ok'\n",
        }[file_path]
        return {
            "encoding": "base64",
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "size": len(content.encode("utf-8")),
            "content_sha256": f"sha-{file_path}",
            "last_commit_id": "commit-123",
        }


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_repo_context_indexes_priority_text_files_and_redacts_secrets():
    db = _session()
    project = GitLabProject(
        workspace_id=1,
        gitlab_project_id="101",
        project_path="demo/checkout",
        name="checkout",
        default_branch="main",
    )
    db.add(project)
    db.commit()

    run = RepoContextService(db, client=FakeRepoClient(), workspace_id=1).index_project(project, limit=10)

    assert run.status == "completed"
    assert run.files_seen == 4
    assert run.files_indexed == 3
    assert run.files_skipped == 0
    assert db.query(RepoFileIndex).count() == 3

    payment_file = db.query(RepoFileIndex).filter(RepoFileIndex.file_path == "services/api/payment.py").one()
    assert payment_file.file_type == "source"
    assert payment_file.language == "python"
    assert "[REDACTED SECRET-LIKE LINE]" in payment_file.content_excerpt
    assert "payment" in payment_file.signals["risk_flags"]


def test_repo_context_agent_tool_searches_indexed_files():
    db = _session()
    project = GitLabProject(
        workspace_id=7,
        gitlab_project_id="202",
        project_path="demo/api",
        name="api",
        default_branch="main",
    )
    db.add(project)
    db.commit()
    RepoContextService(db, client=FakeRepoClient(), workspace_id=7).index_project(project, limit=10)

    result = AgentToolService(db, workspace_id=7).call_tool("search_repo_context", {"project_id": project.id, "query": "kubectl", "limit": 5})

    assert result["project"]["project_path"] == "demo/api"
    assert result["files"]
    assert result["files"][0]["file_path"] == ".gitlab-ci.yml"
    assert "content_excerpt" in result["files"][0]


def test_repo_context_is_available_as_llm_evidence():
    db = _session()
    project = GitLabProject(
        workspace_id=7,
        gitlab_project_id="202",
        project_path="demo/api",
        name="api",
        default_branch="main",
    )
    db.add(project)
    db.commit()
    RepoContextService(db, client=FakeRepoClient(), workspace_id=7).index_project(project, limit=10)
    repo_file = db.query(RepoFileIndex).filter(RepoFileIndex.file_path == ".gitlab-ci.yml").one()

    evidence = _llm_evidence(
        "pipeline_failure",
        {"project": project, "repo_files": [repo_file]},
        [_citation("repo_files", repo_file)],
        [],
    )

    assert evidence[0]["file_path"] == ".gitlab-ci.yml"
    assert "kubectl" in evidence[0]["content_excerpt"]


def test_repo_context_classifies_common_file_types():
    assert classify_file_type(".gitlab-ci.yml") == "ci"
    assert classify_file_type("deploy/kubernetes/deployment.yaml") == "deployment"
    assert classify_file_type("package.json") == "dependency"
    assert classify_file_type("tests/test_checkout.py") == "test"
    assert detect_language("app/page.tsx") == "typescript"
    assert "authentication" in extract_signals("services/auth.py", "def login(): pass")["risk_flags"]
