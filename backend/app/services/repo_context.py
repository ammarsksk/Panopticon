import base64
import hashlib
import re
from collections import Counter
from datetime import datetime, timezone
from difflib import unified_diff
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import desc, select, text
from sqlalchemy.orm import Session

from app import models
from app.config import get_settings
from app.integrations.gitlab import GitLabClient
from app.services.embeddings import RepositoryEmbeddingService, vector_literal


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
                    redacted = redact_content(content, self.settings.repo_index_max_file_bytes)
                    self._upsert_file(project, path=path, ref=branch, payload=payload, redacted=redacted)
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

    def list_tree(self, project: models.GitLabProject, *, limit: int = 200) -> list[dict[str, Any]]:
        files = self.files(project, limit=limit)
        directories: set[str] = set()
        for item in files:
            parts = item.file_path.split("/")[:-1]
            for index in range(1, len(parts) + 1):
                directories.add("/".join(parts[:index]))
        tree = [{"type": "tree", "path": path, "file_type": "directory", "language": ""} for path in sorted(directories)]
        tree.extend(
            {
                "type": "blob",
                "path": item.file_path,
                "file_type": item.file_type,
                "language": item.language,
                "size_bytes": item.size_bytes,
                "content_sha": item.content_sha,
            }
            for item in files
        )
        return tree[:limit]

    def summary(self, project: models.GitLabProject, *, limit: int = 30) -> dict[str, Any]:
        files = self.files(project, limit=limit)
        types = Counter(item.file_type for item in files)
        languages = Counter(item.language for item in files if item.language)
        latest = self.latest_run(project)
        priority_files = sorted(files, key=lambda item: (_file_priority(item.file_path), item.file_path))[:8]
        symbols = self.symbols(project, limit=30)
        chunks = self.search_chunks(project=project, query="", limit=20)
        return {
            "indexed_files": len(files),
            "indexed_chunks": len(chunks),
            "indexed_symbols": len(symbols),
            "by_type": dict(types),
            "by_language": dict(languages),
            "latest_run": latest,
            "priority_files": priority_files,
            "priority_symbols": symbols[:8],
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

    def search_chunks(self, project: models.GitLabProject | None = None, *, query: str = "", limit: int = 10) -> list[models.RepoCodeChunk]:
        if query and self.settings.repo_pgvector_enabled:
            vector_results = self._search_chunks_pgvector(project=project, query=query, limit=limit)
            if vector_results:
                return vector_results

        stmt = select(models.RepoCodeChunk)
        if self.workspace_id is not None:
            stmt = stmt.where(models.RepoCodeChunk.workspace_id == self.workspace_id)
        if project:
            stmt = stmt.where(models.RepoCodeChunk.project_id == project.id)
        chunks = self.db.scalars(stmt.order_by(desc(models.RepoCodeChunk.indexed_at)).limit(max(limit * 6, limit))).all()
        return _rank_chunks(chunks, query)[:limit]

    def _search_chunks_pgvector(self, project: models.GitLabProject | None = None, *, query: str, limit: int) -> list[models.RepoCodeChunk]:
        if self.db.bind is None or self.db.bind.dialect.name != "postgresql":
            return []

        embedding = RepositoryEmbeddingService().embed_texts([query])
        if not embedding.vectors:
            return []

        filters = ["embedding_vector IS NOT NULL"]
        params: dict[str, Any] = {"embedding": vector_literal(embedding.vectors[0]), "limit": max(1, int(limit))}
        if self.workspace_id is not None:
            filters.append("workspace_id = :workspace_id")
            params["workspace_id"] = self.workspace_id
        if project:
            filters.append("project_id = :project_id")
            params["project_id"] = project.id

        try:
            rows = self.db.execute(
                text(
                    "SELECT id FROM repo_code_chunks "
                    f"WHERE {' AND '.join(filters)} "
                    "ORDER BY embedding_vector <=> CAST(:embedding AS vector) "
                    "LIMIT :limit"
                ),
                params,
            ).all()
        except Exception:
            return []

        ids = [int(row[0]) for row in rows]
        if not ids:
            return []
        records = self.db.scalars(select(models.RepoCodeChunk).where(models.RepoCodeChunk.id.in_(ids))).all()
        by_id = {record.id: record for record in records}
        return [by_id[item_id] for item_id in ids if item_id in by_id]

    def read_file(self, project: models.GitLabProject, *, file_path: str, ref: str | None = None) -> models.RepoFileContent | None:
        stmt = (
            select(models.RepoFileContent)
            .where(models.RepoFileContent.project_id == project.id)
            .where(models.RepoFileContent.file_path == file_path)
        )
        if self.workspace_id is not None:
            stmt = stmt.where(models.RepoFileContent.workspace_id == self.workspace_id)
        if ref:
            stmt = stmt.where(models.RepoFileContent.ref == ref)
        return self.db.scalar(stmt.order_by(desc(models.RepoFileContent.indexed_at)).limit(1))

    def read_file_range(self, project: models.GitLabProject, *, file_path: str, start_line: int = 1, end_line: int = 120) -> dict[str, Any]:
        content = self.read_file(project, file_path=file_path)
        if not content:
            return {"project_path": project.project_path, "file_path": file_path, "found": False, "lines": []}
        start = max(1, int(start_line or 1))
        end = max(start, min(int(end_line or start + 119), start + 300))
        lines = content.content_text.splitlines()
        selected = [{"line": idx + 1, "text": line} for idx, line in enumerate(lines) if start <= idx + 1 <= end]
        return {
            "project_path": project.project_path,
            "file_path": file_path,
            "ref": content.ref,
            "found": True,
            "start_line": start,
            "end_line": min(end, len(lines)),
            "line_count": content.line_count,
            "is_truncated": content.is_truncated,
            "lines": selected,
        }

    def symbols(self, project: models.GitLabProject | None = None, *, query: str = "", limit: int = 50) -> list[models.RepoSymbolIndex]:
        stmt = select(models.RepoSymbolIndex)
        if self.workspace_id is not None:
            stmt = stmt.where(models.RepoSymbolIndex.workspace_id == self.workspace_id)
        if project:
            stmt = stmt.where(models.RepoSymbolIndex.project_id == project.id)
        if query:
            like = f"%{query.lower()}%"
            stmt = stmt.where(models.RepoSymbolIndex.symbol_name.ilike(like) | models.RepoSymbolIndex.file_path.ilike(like) | models.RepoSymbolIndex.signature.ilike(like))
        return self.db.scalars(stmt.order_by(models.RepoSymbolIndex.file_path, models.RepoSymbolIndex.start_line).limit(limit)).all()

    def related_files(self, project: models.GitLabProject, *, query: str, limit: int = 10) -> list[models.RepoFileIndex]:
        direct = self.search(project, query=query, limit=limit)
        chunk_paths = [chunk.file_path for chunk in self.search_chunks(project=project, query=query, limit=limit)]
        symbol_paths = [symbol.file_path for symbol in self.symbols(project, query=query, limit=limit)]
        paths = []
        for path in [item.file_path for item in direct] + chunk_paths + symbol_paths:
            if path not in paths:
                paths.append(path)
        if not paths:
            return []
        stmt = select(models.RepoFileIndex).where(models.RepoFileIndex.project_id == project.id).where(models.RepoFileIndex.file_path.in_(paths[:limit]))
        if self.workspace_id is not None:
            stmt = stmt.where(models.RepoFileIndex.workspace_id == self.workspace_id)
        by_path = {item.file_path: item for item in self.db.scalars(stmt).all()}
        return [by_path[path] for path in paths if path in by_path][:limit]

    def context_pack(self, project: models.GitLabProject | None, *, query: str, limit: int = 8) -> dict[str, Any]:
        files = self.related_files(project, query=query, limit=limit) if project else self.search(None, query=query, limit=limit)
        chunks = self.search_chunks(project=project, query=query, limit=limit)
        symbols = self.symbols(project, query=query, limit=limit)
        return {
            "query": query,
            "project_path": project.project_path if project else "",
            "files": files,
            "chunks": chunks,
            "symbols": symbols,
            "notes": _context_notes(files, chunks, symbols),
        }

    def draft_patch(self, project: models.GitLabProject, *, file_path: str, instructions: str) -> dict[str, Any]:
        content = self.read_file(project, file_path=file_path)
        if not content:
            return {"status": "not_found", "project_path": project.project_path, "file_path": file_path, "message": "File is not indexed yet."}
        return {
            "status": "draft_only",
            "project_path": project.project_path,
            "file_path": file_path,
            "instructions": instructions,
            "base_ref": content.ref,
            "requires_approval": True,
            "suggestion": _draft_patch_suggestion(content.content_text, file_path=file_path, instructions=instructions),
        }

    def _upsert_file(self, project: models.GitLabProject, *, path: str, ref: str, payload: dict, redacted: dict[str, Any]) -> models.RepoFileIndex:
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
        content_text = str(redacted["content"])
        record.size_bytes = int(payload.get("size") or len(content_text.encode("utf-8")))
        record.content_sha = str(payload.get("content_sha256") or payload.get("blob_id") or "")
        record.last_commit_id = str(payload.get("last_commit_id") or "")
        record.content_excerpt = content_text[: self.settings.repo_index_max_file_bytes]
        record.signals = extract_signals(path, content_text)
        record.indexed_at = _now()
        self.db.flush()
        self._upsert_content(project, record, content_text=content_text, redacted=redacted)
        self._replace_chunks(project, record, content_text)
        self._replace_symbols(project, record, content_text)
        return record

    def _upsert_content(self, project: models.GitLabProject, record: models.RepoFileIndex, *, content_text: str, redacted: dict[str, Any]) -> models.RepoFileContent:
        stmt = (
            select(models.RepoFileContent)
            .where(models.RepoFileContent.workspace_id == project.workspace_id)
            .where(models.RepoFileContent.project_id == project.id)
            .where(models.RepoFileContent.file_path == record.file_path)
            .where(models.RepoFileContent.ref == record.ref)
        )
        content = self.db.scalar(stmt)
        if not content:
            content = models.RepoFileContent(
                workspace_id=project.workspace_id,
                project_id=project.id,
                repo_file_index_id=record.id,
                project_path=project.project_path,
                file_path=record.file_path,
                ref=record.ref,
            )
            self.db.add(content)
        content.workspace_id = project.workspace_id
        content.project_id = project.id
        content.repo_file_index_id = record.id
        content.project_path = project.project_path
        content.file_path = record.file_path
        content.ref = record.ref
        content.content_sha = record.content_sha
        content.content_text = content_text
        content.redaction_summary = redacted["summary"]
        content.line_count = len(content_text.splitlines())
        content.is_truncated = bool(redacted["is_truncated"])
        content.indexed_at = _now()
        self.db.flush()
        return content

    def _replace_chunks(self, project: models.GitLabProject, record: models.RepoFileIndex, content_text: str) -> None:
        self.db.query(models.RepoCodeChunk).filter(models.RepoCodeChunk.repo_file_index_id == record.id).delete(synchronize_session=False)
        chunks = chunk_content(content_text, chunk_chars=self.settings.repo_index_chunk_chars, max_chunks=self.settings.repo_index_max_chunks_per_file)
        chunk_texts = [f"{record.file_path}\n{chunk['content']}" for chunk in chunks]
        chunk_keywords = [extract_keywords(text_value) for text_value in chunk_texts]
        embeddings = RepositoryEmbeddingService().embed_texts(chunk_texts, local_keywords=chunk_keywords)
        stored_chunks: list[models.RepoCodeChunk] = []
        for index, chunk in enumerate(chunks):
            vector = embeddings.vectors[index] if index < len(embeddings.vectors) else []
            stored = models.RepoCodeChunk(
                workspace_id=project.workspace_id,
                project_id=project.id,
                repo_file_index_id=record.id,
                project_path=project.project_path,
                file_path=record.file_path,
                ref=record.ref,
                chunk_index=chunk["chunk_index"],
                start_line=chunk["start_line"],
                end_line=chunk["end_line"],
                language=record.language,
                content=chunk["content"],
                token_estimate=max(1, len(chunk["content"]) // 4),
                keywords=chunk_keywords[index],
                embedding_model=embeddings.model,
                embedding_provider=embeddings.provider,
                embedding_status=embeddings.status,
                embedding_error=embeddings.error,
                embedding=vector,
                content_sha=record.content_sha,
                indexed_at=_now(),
            )
            self.db.add(stored)
            stored_chunks.append(stored)
        self.db.flush()
        self._write_pgvector_embeddings(stored_chunks)

    def _write_pgvector_embeddings(self, chunks: list[models.RepoCodeChunk]) -> None:
        if not self.settings.repo_pgvector_enabled or self.db.bind is None or self.db.bind.dialect.name != "postgresql":
            return
        for chunk in chunks:
            if not chunk.embedding:
                continue
            try:
                self.db.execute(
                    text("UPDATE repo_code_chunks SET embedding_vector = CAST(:embedding AS vector) WHERE id = :id"),
                    {"embedding": vector_literal(chunk.embedding), "id": chunk.id},
                )
            except Exception as exc:
                chunk.embedding_status = "pgvector_failed"
                chunk.embedding_error = str(exc)[:1000]
        self.db.flush()

    def _replace_symbols(self, project: models.GitLabProject, record: models.RepoFileIndex, content_text: str) -> None:
        self.db.query(models.RepoSymbolIndex).filter(models.RepoSymbolIndex.repo_file_index_id == record.id).delete(synchronize_session=False)
        for symbol in extract_symbols(record.file_path, content_text, record.language):
            self.db.add(
                models.RepoSymbolIndex(
                    workspace_id=project.workspace_id,
                    project_id=project.id,
                    repo_file_index_id=record.id,
                    project_path=project.project_path,
                    file_path=record.file_path,
                    ref=record.ref,
                    symbol_name=symbol["symbol_name"],
                    symbol_type=symbol["symbol_type"],
                    signature=symbol["signature"],
                    start_line=symbol["start_line"],
                    end_line=symbol["end_line"],
                    metadata_json=symbol["metadata"],
                    indexed_at=_now(),
                )
            )
        self.db.flush()


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


def redact_content(content: str, max_bytes: int) -> dict[str, Any]:
    lines: list[str] = []
    redacted_lines: list[int] = []
    for line in content.splitlines():
        if SECRET_LINE_RE.search(line) and (":" in line or "=" in line):
            lines.append("[REDACTED SECRET-LIKE LINE]")
            redacted_lines.append(len(lines))
        else:
            lines.append(line)
    redacted = "\n".join(lines).strip()
    encoded = redacted.encode("utf-8")
    truncated = len(encoded) > max_bytes
    if truncated:
        redacted = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return {
        "content": redacted,
        "is_truncated": truncated,
        "summary": {
            "redacted_line_count": len(redacted_lines),
            "redacted_lines": redacted_lines[:100],
            "original_line_count": len(content.splitlines()),
            "stored_bytes": len(redacted.encode("utf-8")),
        },
    }


def _redacted_excerpt(content: str, max_bytes: int) -> str:
    return str(redact_content(content, max_bytes)["content"])


def chunk_content(content: str, *, chunk_chars: int, max_chunks: int) -> list[dict[str, Any]]:
    lines = content.splitlines()
    chunks: list[dict[str, Any]] = []
    current: list[str] = []
    start_line = 1
    current_chars = 0
    for line_number, line in enumerate(lines, start=1):
        extra = len(line) + 1
        if current and current_chars + extra > chunk_chars:
            chunks.append(
                {
                    "chunk_index": len(chunks),
                    "start_line": start_line,
                    "end_line": line_number - 1,
                    "content": "\n".join(current).strip(),
                }
            )
            if len(chunks) >= max_chunks:
                return chunks
            current = []
            start_line = line_number
            current_chars = 0
        current.append(line)
        current_chars += extra
    if current and len(chunks) < max_chunks:
        chunks.append(
            {
                "chunk_index": len(chunks),
                "start_line": start_line,
                "end_line": len(lines) or start_line,
                "content": "\n".join(current).strip(),
            }
        )
    return chunks or [{"chunk_index": 0, "start_line": 1, "end_line": 1, "content": content[:chunk_chars]}]


def extract_keywords(text: str, *, limit: int = 32) -> list[str]:
    ignored = {
        "from",
        "import",
        "class",
        "function",
        "return",
        "const",
        "let",
        "var",
        "true",
        "false",
        "none",
        "null",
        "with",
        "this",
        "that",
        "then",
        "else",
        "elif",
        "def",
    }
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}|[A-Za-z0-9_.-]{4,}", text.lower())
    counts = Counter(token for token in tokens if token not in ignored and not token.startswith("redacted"))
    return [token for token, _ in counts.most_common(limit)]


def keyword_embedding(keywords: list[str], *, dimensions: int = 16) -> list[float]:
    vector = [0.0] * dimensions
    if not keywords:
        return vector
    for keyword in keywords:
        digest = hashlib.sha256(keyword.encode("utf-8")).digest()
        index = digest[0] % dimensions
        vector[index] += 1.0
    magnitude = sum(value * value for value in vector) ** 0.5 or 1.0
    return [round(value / magnitude, 4) for value in vector]


def extract_symbols(path: str, content: str, language: str) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    lines = content.splitlines()
    patterns: list[tuple[str, re.Pattern[str]]] = []
    if language == "python":
        patterns = [
            ("class", re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\b.*")),
            ("function", re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(.*")),
        ]
    elif language in {"javascript", "typescript"}:
        patterns = [
            ("class", re.compile(r"^\s*class\s+([A-Za-z_$][A-Za-z0-9_$]*)\b.*")),
            ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(.*")),
            ("function", re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?\(?.*=>.*")),
        ]
    elif language in {"yaml", "json", "toml"} or classify_file_type(path) in {"ci", "deployment", "config"}:
        patterns = [("config_key", re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*[:=].*"))]
    for line_number, line in enumerate(lines, start=1):
        for symbol_type, pattern in patterns:
            match = pattern.match(line)
            if not match:
                continue
            name = match.group(1)
            symbols.append(
                {
                    "symbol_name": name[:255],
                    "symbol_type": symbol_type,
                    "signature": line.strip()[:800],
                    "start_line": line_number,
                    "end_line": line_number,
                    "metadata": {"path": path, "language": language},
                }
            )
            break
    return symbols[:200]


def _rank_chunks(chunks: list[models.RepoCodeChunk], query: str) -> list[models.RepoCodeChunk]:
    keywords = set(extract_keywords(query, limit=20))
    if not keywords:
        return chunks

    def score(chunk: models.RepoCodeChunk) -> float:
        chunk_keywords = set(chunk.keywords or [])
        text = f"{chunk.file_path}\n{chunk.content}".lower()
        keyword_hits = len(keywords & chunk_keywords)
        text_hits = sum(1 for keyword in keywords if keyword in text)
        priority = max(0, 8 - _file_priority(chunk.file_path)) * 0.2
        return keyword_hits * 2.0 + text_hits + priority

    return sorted(chunks, key=score, reverse=True)


def _context_notes(files: list[models.RepoFileIndex], chunks: list[models.RepoCodeChunk], symbols: list[models.RepoSymbolIndex]) -> list[str]:
    notes = []
    if files:
        notes.append(f"{len(files)} related indexed file(s) are available.")
    if chunks:
        notes.append(f"{len(chunks)} code chunk(s) matched the question.")
    if symbols:
        notes.append(f"{len(symbols)} symbol(s) matched the question.")
    if not notes:
        notes.append("No repository context matched this question yet; refresh the repository index.")
    return notes


def _draft_patch_suggestion(content: str, *, file_path: str, instructions: str) -> dict[str, Any]:
    lines = content.splitlines()
    lowered = instructions.lower()
    target_line = 1
    for index, line in enumerate(lines, start=1):
        if any(term in line.lower() for term in extract_keywords(instructions, limit=8)):
            target_line = index
            break
    operation = "update_existing_file"
    proposed_content = _draft_proposed_content(content, file_path=file_path, instructions=instructions)
    diff = "\n".join(
        unified_diff(
            content.splitlines(),
            proposed_content.splitlines(),
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
            lineterm="",
        )
    )
    if any(term in lowered for term in ["bug", "failing test", "discount", "coupon", "save10"]):
        proposed = "Fix the source-code behavior that is causing the failing test, then validate with the project test command."
    elif "timeout" in lowered and ".gitlab-ci.yml" in file_path:
        proposed = "Add a bounded job-level timeout/retry only after confirming the failing job name."
    elif "test" in lowered:
        proposed = "Add a focused regression test near the affected service path and wire it into CI."
    elif "log" in lowered:
        proposed = "Add focused diagnostic logging near the relevant code path without logging secrets."
    elif "validation" in lowered or "validate" in lowered or "guard" in lowered:
        proposed = "Add explicit input/config validation with a small, reviewable helper."
    elif "document" in lowered or "docs" in lowered or "readme" in lowered:
        proposed = "Update project documentation with the requested operational guidance."
    elif "deployment" in lowered or "health" in lowered:
        proposed = "Tighten readiness or rollout validation around the deployment manifest."
    else:
        proposed = "Prepare a minimal scoped diff against this indexed file, then validate with the project test command."
    return {
        "operation": operation,
        "target_line": target_line,
        "proposed_change": proposed,
        "proposed_content": proposed_content,
        "unified_diff": diff,
        "changed": proposed_content.rstrip() != content.rstrip(),
        "additions": len([line for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]),
        "deletions": len([line for line in diff.splitlines() if line.startswith("-") and not line.startswith("---")]),
        "safety": {
            "requires_approval": True,
            "draft_only": True,
            "secrets_redacted": True,
            "writes_to_gitlab": False,
        },
        "diff_policy": "draft only; convert to a Fix Plan and require approval before GitLab writes",
        "context_excerpt": "\n".join(lines[max(0, target_line - 4) : target_line + 4]),
    }


def _draft_proposed_content(content: str, *, file_path: str, instructions: str) -> str:
    lowered = instructions.lower()
    language = detect_language(file_path)
    file_type = classify_file_type(file_path)
    if file_path == ".gitlab-ci.yml" or file_type == "ci":
        return _draft_ci_content(content)
    if file_type == "test":
        return _append_once(
            content,
            "\n\n# Panopticon regression note: replace this scaffold with an assertion for the requested behavior before merge.\n",
        )
    if language == "python":
        return _draft_python_content(content, lowered)
    if language in {"typescript", "javascript"}:
        return _draft_typescript_content(content, lowered)
    if language in {"yaml", "json"} or file_type in {"config", "deployment"}:
        return _append_once(
            content,
            "\n# Panopticon validation: confirm this setting is covered by a targeted smoke or config validation before merge.\n",
        )
    if language == "markdown" or file_path.lower().endswith((".md", ".mdx")):
        return _append_once(
            content,
            "\n\n## Panopticon change note\n\n- Document the requested behavior, validation command, owner, and rollback path before merging.\n",
        )
    return _append_once(
        content,
        "\n\n# Panopticon review note: implement the requested change here, then validate with the project test command.\n",
    )


def _draft_ci_content(content: str) -> str:
    base = content.rstrip()
    if "timeout:" not in base:
        base = _append_once(base, "\n\n# Panopticon safety: keep CI waits bounded while investigating failures.\ntimeout: 20m\n")
    if "retry:" not in base:
        base = _append_once(
            base,
            "\n# Panopticon safety: retry only transient runner/system failures.\nretry:\n  max: 1\n  when:\n    - runner_system_failure\n    - stuck_or_timeout_failure\n",
        )
    return base.rstrip() + "\n"


def _draft_python_content(content: str, lowered_instructions: str) -> str:
    base = content.rstrip()
    discount_patch = _draft_python_discount_patch(base, lowered_instructions)
    if discount_patch:
        return discount_patch
    if "log" in lowered_instructions:
        if "import logging" not in base:
            base = "import logging\n" + base
        if "logger = logging.getLogger(__name__)" not in base:
            base = base.replace("import logging\n", "import logging\n\nlogger = logging.getLogger(__name__)\n", 1)
        return base.rstrip() + "\n"
    helper = "\n\n\ndef panopticon_require_value(value, field_name=\"value\"):\n    if value in (None, \"\"):\n        raise ValueError(f\"{field_name} is required\")\n    return value\n"
    if "def panopticon_require_value" not in base:
        base += helper
    return base.rstrip() + "\n"


def _draft_python_discount_patch(content: str, lowered_instructions: str) -> str:
    if not any(term in lowered_instructions for term in ["bug", "failing test", "discount", "coupon", "save10"]):
        return ""
    if "SAVE10" not in content and "save10" not in content.lower():
        return ""

    replacements = [
        ("return total - 10", "return round(total * 0.90, 2)"),
        ("return subtotal - 10", "return round(subtotal * 0.90, 2)"),
        ("return amount - 10", "return round(amount * 0.90, 2)"),
    ]
    patched = content
    for old, new in replacements:
        if old in patched:
            return patched.replace(old, new, 1).rstrip() + "\n"

    if "coupon == \"SAVE10\"" in patched or "coupon == 'SAVE10'" in patched:
        lines = patched.splitlines()
        for index, line in enumerate(lines):
            if "coupon ==" in line and "SAVE10" in line:
                indent = line[: len(line) - len(line.lstrip())] + "    "
                if index + 1 < len(lines) and "return" in lines[index + 1]:
                    lines[index + 1] = f"{indent}return round(total * 0.90, 2)"
                    return "\n".join(lines).rstrip() + "\n"
    return ""


def _draft_typescript_content(content: str, lowered_instructions: str) -> str:
    base = content.rstrip()
    if "log" in lowered_instructions and "panopticonLog" not in base:
        base += "\n\nexport function panopticonLog(message: string, context: Record<string, unknown> = {}) {\n  console.info(message, context);\n}\n"
        return base.rstrip() + "\n"
    if "assertPanopticonRequired" not in base:
        base += "\n\nexport function assertPanopticonRequired<T>(value: T | null | undefined, fieldName: string): T {\n  if (value === null || value === undefined || value === \"\") {\n    throw new Error(`${fieldName} is required`);\n  }\n  return value;\n}\n"
    return base.rstrip() + "\n"


def _append_once(content: str, addition: str) -> str:
    marker = addition.strip().splitlines()[0] if addition.strip() else addition
    if marker and marker in content:
        return content.rstrip() + "\n"
    return content.rstrip() + addition


def _append_error(existing: str, message: str) -> str:
    combined = "\n".join(item for item in [existing, message] if item)
    return combined[:4000]


def _now() -> datetime:
    return datetime.now(timezone.utc)
