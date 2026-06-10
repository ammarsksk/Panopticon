import base64

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import GitLabProject, PipelineSnapshot, RepoCodeChunk, RepoFileContent, RepoFileIndex, RepoSymbolIndex
from app.services.agent_tools import AgentToolService
from app.services.chat import _citation, _llm_evidence
from app.services.embeddings import RepositoryEmbeddingService
from app.services.repo_context import RepoContextService, classify_file_type, detect_language, extract_signals
from app.config import get_settings


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
    assert db.query(RepoFileContent).count() == 3
    assert db.query(RepoCodeChunk).count() >= 3
    assert db.query(RepoSymbolIndex).count() >= 1

    payment_file = db.query(RepoFileIndex).filter(RepoFileIndex.file_path == "services/api/payment.py").one()
    assert payment_file.file_type == "source"
    assert payment_file.language == "python"
    assert "[REDACTED SECRET-LIKE LINE]" in payment_file.content_excerpt
    assert "payment" in payment_file.signals["risk_flags"]
    stored_content = db.query(RepoFileContent).filter(RepoFileContent.file_path == "services/api/payment.py").one()
    assert stored_content.redaction_summary["redacted_line_count"] == 1
    assert "def charge" in stored_content.content_text
    symbol = db.query(RepoSymbolIndex).filter(RepoSymbolIndex.symbol_name == "charge").one()
    assert symbol.file_path == "services/api/payment.py"


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


def test_repo_context_stores_vertex_embedding_metadata(monkeypatch):
    monkeypatch.setenv("REPO_EMBEDDING_PROVIDER", "vertex")
    monkeypatch.setenv("REPO_EMBEDDING_MODEL", "gemini-embedding-001")
    monkeypatch.setenv("REPO_EMBEDDING_DIMENSIONS", "8")
    monkeypatch.setenv("REPO_EMBEDDING_FALLBACK_TO_LOCAL", "false")
    monkeypatch.setenv("REPO_PGVECTOR_ENABLED", "false")
    get_settings.cache_clear()

    def fake_vertex(self, texts):
        return [[1.0] + [0.0] * 7 for _ in texts]

    monkeypatch.setattr(RepositoryEmbeddingService, "_vertex_embeddings", fake_vertex)
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
    chunk = db.query(RepoCodeChunk).filter(RepoCodeChunk.file_path == ".gitlab-ci.yml").first()

    assert chunk is not None
    assert chunk.embedding_provider == "vertex"
    assert chunk.embedding_model == "gemini-embedding-001"
    assert chunk.embedding_status == "ready"
    assert len(chunk.embedding) == 8
    get_settings.cache_clear()


def test_repo_context_falls_back_when_vertex_embedding_fails(monkeypatch):
    monkeypatch.setenv("REPO_EMBEDDING_PROVIDER", "vertex")
    monkeypatch.setenv("REPO_EMBEDDING_MODEL", "gemini-embedding-001")
    monkeypatch.setenv("REPO_EMBEDDING_FALLBACK_TO_LOCAL", "true")
    monkeypatch.setenv("REPO_PGVECTOR_ENABLED", "false")
    get_settings.cache_clear()

    def failing_vertex(self, texts):
        raise RuntimeError("quota unavailable")

    monkeypatch.setattr(RepositoryEmbeddingService, "_vertex_embeddings", failing_vertex)
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
    chunk = db.query(RepoCodeChunk).filter(RepoCodeChunk.file_path == "services/api/payment.py").first()

    assert chunk is not None
    assert chunk.embedding_provider == "local_fallback"
    assert chunk.embedding_status == "fallback"
    assert "quota unavailable" in chunk.embedding_error
    assert chunk.embedding
    get_settings.cache_clear()


def test_repo_context_tools_read_chunks_symbols_and_draft_patch():
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
    tools = AgentToolService(db, workspace_id=7)

    tree = tools.call_tool("list_project_tree", {"project_id": project.id, "limit": 20})
    content = tools.call_tool("read_repo_file", {"project_id": project.id, "file_path": "services/api/payment.py"})
    line_range = tools.call_tool("read_repo_file_range", {"project_id": project.id, "file_path": "services/api/payment.py", "start_line": 1, "end_line": 3})
    chunks = tools.call_tool("search_code", {"project_id": project.id, "query": "payment charge", "limit": 5})
    symbols = tools.call_tool("get_symbols", {"project_id": project.id, "query": "charge", "limit": 5})
    pack = tools.call_tool("build_context_pack", {"project_id": project.id, "query": "kubectl deploy payment", "limit": 5})
    patch = tools.call_tool("draft_patch", {"project_id": project.id, "file_path": ".gitlab-ci.yml", "instructions": "add timeout guidance"})

    assert any(item["path"] == "services/api" for item in tree["tree"])
    assert content["file"]["redaction_summary"]["redacted_line_count"] == 1
    assert line_range["found"] is True
    assert chunks["chunks"][0]["file_path"] in {".gitlab-ci.yml", "services/api/payment.py"}
    assert symbols["symbols"][0]["symbol_name"] == "charge"
    assert pack["chunks"]
    assert patch["status"] == "draft_only"
    assert patch["requires_approval"] is True


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


def test_chat_uses_repository_context_when_failed_job_trace_is_missing(monkeypatch):
    from app.agents.gemini import GeminiReasoner
    from app.services.chat import ChatService

    monkeypatch.setattr(
        GeminiReasoner,
        "chat_answer",
        lambda self, *, question, intent, subject, evidence, deterministic_draft: deterministic_draft,
    )
    db = _session()
    project = GitLabProject(
        workspace_id=7,
        gitlab_project_id="202",
        project_path="demo/api",
        name="api",
        default_branch="main",
    )
    db.add(project)
    db.flush()
    db.add(
        PipelineSnapshot(
            workspace_id=7,
            gitlab_project_id="202",
            project_path="demo/api",
            pipeline_id="9001",
            status="failed",
            ref="main",
            sha="abc",
            web_url="https://gitlab.com/demo/api/-/pipelines/9001",
        )
    )
    db.commit()
    RepoContextService(db, client=FakeRepoClient(), workspace_id=7).index_project(project, limit=10)

    result = ChatService(db, workspace_id=7).answer(project_id=project.id, message="why did deploy pipeline fail around kubectl?")
    answer = result["assistant_message"].content

    assert "Repository context to inspect" in answer
    assert ".gitlab-ci.yml" in answer
    assert "No parsed failed job trace is stored yet" in answer


def test_repo_context_classifies_common_file_types():
    assert classify_file_type(".gitlab-ci.yml") == "ci"
    assert classify_file_type("deploy/kubernetes/deployment.yaml") == "deployment"
    assert classify_file_type("package.json") == "dependency"
    assert classify_file_type("tests/test_checkout.py") == "test"
    assert detect_language("app/page.tsx") == "typescript"
    assert "authentication" in extract_signals("services/auth.py", "def login(): pass")["risk_flags"]
