import base64
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app import models
from app.config import get_settings
from app.integrations.gitlab import GitLabClient


TEXT_EXTENSIONS = {
    ".bat",
    ".cfg",
    ".conf",
    ".css",
    ".dockerfile",
    ".env",
    ".go",
    ".gradle",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".lock",
    ".md",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".sql",
    ".tf",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

BINARY_EXTENSIONS = {
    ".7z",
    ".avif",
    ".bin",
    ".bmp",
    ".dll",
    ".exe",
    ".gif",
    ".ico",
    ".jar",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".pyc",
    ".so",
    ".webp",
    ".zip",
}

SECRET_LINE_RE = re.compile(r"(secret|token|password|passwd|private[_-]?key|api[_-]?key|client[_-]?secret)", re.IGNORECASE)


class RepoContextService:
    def __init__(self, db: Session, client: GitLabClient | None = None, workspace_id: int | None = None) -> None:
        self.db = db
        self.client = client or GitLabClient()
        self.workspace_id = workspace_id
        self.settings = get_settings()

    def index_project(self, project: models.GitLabProject, *, ref: str | None = None, limit: int | None = None) -> models.RepoIndexRun:
        branch = ref or project.default_branch or "main"
        file_limit = limit or self.settings.repo_index_file_limit
        run = models.RepoIndexRun(
            workspace_id=project.workspace_id,
            project_id=project.id,
            project_path=project.project_path,
            ref=branch,
            status="running",
        )
        self.db.add(run)
        self.db.flush()

        try:
            if not self.client.configured:
                raise RuntimeError("GitLab is not connected. Configure GitLab OAuth or GITLAB_TOKEN.")

            tree = self.client.list_repository_tree(project.project_path, branch, recursive=True, limit=min(max(file_limit * 3, 30), 100))
            blobs = [item for item in tree if str(item.get("type") or "") == "blob"]
            run.files_seen = len(blobs)
            selected = _select_files(blobs, file_limit, self.settings.repo_index_max_file_bytes)

            for item in selected:
                path = str(item.get("path") or "")
                if not path:
                    run.files_skipped += 1
                    continue
                try:
                    payload = self.client.get_repository_file(project.project_path, path, branch)
                    content = _decode_gitlab_content(payload)
                    if not content:
                        run.files_skipped += 1
                        continue
                    excerpt = _redacted_excerpt(content, self.settings.repo_index_max_file_bytes)
                    self._upsert_file(project, path=path, ref=branch, payload=payload, excerpt=excerpt)
                    run.files_indexed += 1
                except Exception as exc:
                    run.files_skipped += 1
                    run.error = _append_error(run.error, f"{path}: {exc}")

            run.status = "completed_with_errors" if run.error else "completed"
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)[:4000]
        finally:
            run.finished_at = _now()
            self.db.commit()

        return run

    def latest_run(self, project: models.GitLabProject) -> models.RepoIndexRun | None:
        stmt = (
            select(models.RepoIndexRun)
            .where(models.RepoIndexRun.project_id == project.id)
            .where(models.RepoIndexRun.workspace_id == project.workspace_id)
            .order_by(desc(models.RepoIndexRun.started_at))
            .limit(1)
        )
        return self.db.scalar(stmt)

    def files(self, project: models.GitLabProject, *, limit: int = 30) -> list[models.RepoFileIndex]:
        stmt = (
            select(models.RepoFileIndex)
            .where(models.RepoFileIndex.project_id == project.id)
            .where(models.RepoFileIndex.workspace_id == project.workspace_id)
            .order_by(desc(models.RepoFileIndex.indexed_at), models.RepoFileIndex.file_path)
            .limit(limit)
        )
        return self.db.scalars(stmt).all()

    def summary(self, project: models.GitLabProject, *, limit: int = 30) -> dict[str, Any]:
        files = self.files(project, limit=limit)
        types = Counter(item.file_type for item in files)
        languages = Counter(item.language for item in files if item.language)
        latest = self.latest_run(project)
        priority_files = sorted(files, key=lambda item: (_file_priority(item.file_path), item.file_path))[:8]
        return {
            "indexed_files": len(files),
            "by_type": dict(types),
            "by_language": dict(languages),
            "latest_run": latest,
            "priority_files": priority_files,
        }

    def search(self, project: models.GitLabProject | None = None, *, query: str = "", limit: int = 10) -> list[models.RepoFileIndex]:
        stmt = select(models.RepoFileIndex)
        if self.workspace_id is not None:
            stmt = stmt.where(models.RepoFileIndex.workspace_id == self.workspace_id)
        if project:
            stmt = stmt.where(models.RepoFileIndex.project_id == project.id)
        if query:
            like = f"%{query.lower()}%"
            stmt = stmt.where(models.RepoFileIndex.file_path.ilike(like) | models.RepoFileIndex.content_excerpt.ilike(like))
        return self.db.scalars(stmt.order_by(desc(models.RepoFileIndex.indexed_at)).limit(limit)).all()

    def _upsert_file(self, project: models.GitLabProject, *, path: str, ref: str, payload: dict, excerpt: str) -> models.RepoFileIndex:
        stmt = (
            select(models.RepoFileIndex)
            .where(models.RepoFileIndex.workspace_id == project.workspace_id)
            .where(models.RepoFileIndex.project_id == project.id)
            .where(models.RepoFileIndex.file_path == path)
            .where(models.RepoFileIndex.ref == ref)
        )
        record = self.db.scalar(stmt)
        if not record:
            record = models.RepoFileIndex(
                workspace_id=project.workspace_id,
                project_id=project.id,
                project_path=project.project_path,
                file_path=path,
                ref=ref,
            )
            self.db.add(record)

        record.workspace_id = project.workspace_id
        record.project_id = project.id
        record.project_path = project.project_path
        record.file_path = path
        record.ref = ref
        record.file_type = classify_file_type(path)
        record.language = detect_language(path)
        record.size_bytes = int(payload.get("size") or len(excerpt.encode("utf-8")))
        record.content_sha = str(payload.get("content_sha256") or payload.get("blob_id") or "")
        record.last_commit_id = str(payload.get("last_commit_id") or "")
        record.content_excerpt = excerpt
        record.signals = extract_signals(path, excerpt)
        record.indexed_at = _now()
        self.db.flush()
        return record


def classify_file_type(path: str) -> str:
    normalized = path.lower()
    name = PurePosixPath(normalized).name
    if name == ".gitlab-ci.yml" or normalized.startswith(".github/workflows/"):
        return "ci"
    if name in {"dockerfile", "docker-compose.yml", "compose.yml"} or normalized.startswith(("deploy/", "deployment/", "k8s/", "kubernetes/", "helm/", "charts/")):
        return "deployment"
    if name in {"requirements.txt", "pyproject.toml", "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "go.mod", "pom.xml", "build.gradle", "cargo.toml"}:
        return "dependency"
    if normalized.startswith(("test/", "tests/", "__tests__/")) or ".test." in normalized or ".spec." in normalized:
        return "test"
    if normalized.startswith(("docs/", "doc/")) or name in {"readme.md", "readme.txt"}:
        return "docs"
    if name.startswith(".") or PurePosixPath(normalized).suffix in {".yml", ".yaml", ".json", ".toml", ".ini", ".conf", ".cfg"}:
        return "config"
    return "source"


def detect_language(path: str) -> str:
    suffix = PurePosixPath(path.lower()).suffix
    return {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".go": "go",
        ".java": "java",
        ".rb": "ruby",
        ".rs": "rust",
        ".sh": "shell",
        ".sql": "sql",
        ".tf": "terraform",
        ".yml": "yaml",
        ".yaml": "yaml",
        ".json": "json",
        ".md": "markdown",
        ".toml": "toml",
        ".xml": "xml",
        ".html": "html",
        ".css": "css",
    }.get(suffix, "")


def extract_signals(path: str, excerpt: str) -> dict[str, Any]:
    lowered = f"{path}\n{excerpt}".lower()
    flags = []
    for needle, label in [
        ("docker", "container"),
        ("kubernetes", "kubernetes"),
        ("kubectl", "kubernetes"),
        ("deploy", "deployment"),
        ("migration", "database_migration"),
        ("payment", "payment"),
        ("auth", "authentication"),
        ("rollback", "rollback"),
        ("retry", "retry"),
        ("timeout", "timeout"),
        ("test", "test_coverage"),
    ]:
        if needle in lowered and label not in flags:
            flags.append(label)
    return {"file_type": classify_file_type(path), "language": detect_language(path), "risk_flags": flags}


def _select_files(tree: list[dict], limit: int, max_size: int) -> list[dict]:
    candidates = []
    for item in tree:
        path = str(item.get("path") or "")
        size = int(item.get("size") or 0)
        if not _is_indexable_text(path) or (size and size > max_size):
            continue
        candidates.append(((_file_priority(path), path), item))
    candidates.sort(key=lambda pair: pair[0])
    return [item for _, item in candidates[:limit]]


def _is_indexable_text(path: str) -> bool:
    lowered = path.lower()
    name = PurePosixPath(lowered).name
    suffix = PurePosixPath(lowered).suffix
    if suffix in BINARY_EXTENSIONS:
        return False
    if name in {"dockerfile", ".gitlab-ci.yml", "makefile"}:
        return True
    return suffix in TEXT_EXTENSIONS


def _file_priority(path: str) -> int:
    file_type = classify_file_type(path)
    return {"ci": 0, "deployment": 1, "dependency": 2, "config": 3, "source": 4, "test": 5, "docs": 6}.get(file_type, 9)


def _decode_gitlab_content(payload: dict) -> str:
    raw = str(payload.get("content") or "")
    if not raw:
        return ""
    if payload.get("encoding") == "base64":
        try:
            return base64.b64decode(raw).decode("utf-8", errors="replace")
        except Exception:
            return ""
    return raw


def _redacted_excerpt(content: str, max_bytes: int) -> str:
    lines = []
    for line in content.splitlines():
        if SECRET_LINE_RE.search(line) and (":" in line or "=" in line):
            lines.append("[REDACTED SECRET-LIKE LINE]")
        else:
            lines.append(line)
    redacted = "\n".join(lines).strip()
    encoded = redacted.encode("utf-8")[:max_bytes]
    return encoded.decode("utf-8", errors="ignore")


def _append_error(existing: str, message: str) -> str:
    combined = "\n".join(item for item in [existing, message] if item)
    return combined[:4000]


def _now() -> datetime:
    return datetime.now(timezone.utc)
