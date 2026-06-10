"""Add production vector embedding support.

Revision ID: 0013_pgvector_vertex_embeddings
Revises: 0012_repository_agent_memory
Create Date: 2026-06-09
"""

from __future__ import annotations

import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0013_pgvector_vertex_embeddings"
down_revision: Union[str, None] = "0012_repository_agent_memory"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    _add_column_if_missing("repo_code_chunks", sa.Column("embedding_provider", sa.String(length=80), nullable=False, server_default="local"))
    _add_column_if_missing("repo_code_chunks", sa.Column("embedding_status", sa.String(length=80), nullable=False, server_default="ready"))
    _add_column_if_missing("repo_code_chunks", sa.Column("embedding_error", sa.Text(), nullable=False, server_default=""))
    _index("ix_repo_code_chunks_embedding_provider", "repo_code_chunks", ["embedding_provider"])
    _index("ix_repo_code_chunks_embedding_status", "repo_code_chunks", ["embedding_status"])

    if not _pgvector_enabled():
        return
    if op.get_bind().dialect.name != "postgresql":
        return

    dimensions = _dimensions()
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    columns = _columns("repo_code_chunks")
    if "embedding_vector" not in columns:
        op.execute(sa.text(f"ALTER TABLE repo_code_chunks ADD COLUMN embedding_vector vector({dimensions})"))
    _pg_index(
        "ix_repo_code_chunks_embedding_vector_hnsw",
        f"CREATE INDEX ix_repo_code_chunks_embedding_vector_hnsw ON repo_code_chunks USING hnsw (embedding_vector vector_cosine_ops)",
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        _drop_index("ix_repo_code_chunks_embedding_vector_hnsw", "repo_code_chunks")
        columns = _columns("repo_code_chunks")
        if "embedding_vector" in columns:
            op.execute(sa.text("ALTER TABLE repo_code_chunks DROP COLUMN embedding_vector"))
    _drop_index("ix_repo_code_chunks_embedding_status", "repo_code_chunks")
    _drop_index("ix_repo_code_chunks_embedding_provider", "repo_code_chunks")
    for column in ["embedding_error", "embedding_status", "embedding_provider"]:
        if column in _columns("repo_code_chunks"):
            op.drop_column("repo_code_chunks", column)


def _pgvector_enabled() -> bool:
    return os.getenv("REPO_PGVECTOR_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def _dimensions() -> int:
    try:
        return max(1, min(int(os.getenv("REPO_EMBEDDING_DIMENSIONS", "768")), 16000))
    except ValueError:
        return 768


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def _index(name: str, table: str, columns: list[str], *, unique: bool = False) -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {index["name"] for index in inspector.get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns, unique=unique)


def _pg_index(name: str, sql: str) -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {index["name"] for index in inspector.get_indexes("repo_code_chunks")}
    if name not in existing:
        op.execute(sa.text(sql))


def _drop_index(name: str, table: str) -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {index["name"] for index in inspector.get_indexes(table)}
    if name in existing:
        op.drop_index(name, table_name=table)
