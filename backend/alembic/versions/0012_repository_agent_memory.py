"""Add repository-aware agent memory tables.

Revision ID: 0012_repository_agent_memory
Revises: 0011_job_trace_context
Create Date: 2026-06-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0012_repository_agent_memory"
down_revision: Union[str, None] = "0011_job_trace_context"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "repo_file_contents" not in tables:
        op.create_table(
            "repo_file_contents",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("workspace_id", sa.Integer(), nullable=True),
            sa.Column("project_id", sa.Integer(), nullable=True),
            sa.Column("repo_file_index_id", sa.Integer(), nullable=True),
            sa.Column("project_path", sa.String(length=255), nullable=False),
            sa.Column("file_path", sa.String(length=600), nullable=False),
            sa.Column("ref", sa.String(length=255), nullable=False),
            sa.Column("content_sha", sa.String(length=160), nullable=False),
            sa.Column("content_text", sa.Text(), nullable=False),
            sa.Column("redaction_summary", sa.JSON(), nullable=False),
            sa.Column("line_count", sa.Integer(), nullable=False),
            sa.Column("is_truncated", sa.Boolean(), nullable=False),
            sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["gitlab_projects.id"]),
            sa.ForeignKeyConstraint(["repo_file_index_id"], ["repo_file_indexes.id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _index("ix_repo_file_contents_content_sha", "repo_file_contents", ["content_sha"])
    _index("ix_repo_file_contents_file_path", "repo_file_contents", ["file_path"])
    _index("ix_repo_file_contents_id", "repo_file_contents", ["id"])
    _index("ix_repo_file_contents_indexed_at", "repo_file_contents", ["indexed_at"])
    _index("ix_repo_file_contents_is_truncated", "repo_file_contents", ["is_truncated"])
    _index("ix_repo_file_contents_project_id", "repo_file_contents", ["project_id"])
    _index("ix_repo_file_contents_project_path", "repo_file_contents", ["project_path"])
    _index("ix_repo_file_contents_ref", "repo_file_contents", ["ref"])
    _index("ix_repo_file_contents_repo_file_index_id", "repo_file_contents", ["repo_file_index_id"])
    _index("ix_repo_file_contents_workspace_id", "repo_file_contents", ["workspace_id"])
    _index(
        "uq_repo_file_content_workspace_project_path_ref",
        "repo_file_contents",
        ["workspace_id", "project_id", "file_path", "ref"],
        unique=True,
    )

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "repo_code_chunks" not in tables:
        op.create_table(
            "repo_code_chunks",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("workspace_id", sa.Integer(), nullable=True),
            sa.Column("project_id", sa.Integer(), nullable=True),
            sa.Column("repo_file_index_id", sa.Integer(), nullable=True),
            sa.Column("project_path", sa.String(length=255), nullable=False),
            sa.Column("file_path", sa.String(length=600), nullable=False),
            sa.Column("ref", sa.String(length=255), nullable=False),
            sa.Column("chunk_index", sa.Integer(), nullable=False),
            sa.Column("start_line", sa.Integer(), nullable=False),
            sa.Column("end_line", sa.Integer(), nullable=False),
            sa.Column("language", sa.String(length=80), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("token_estimate", sa.Integer(), nullable=False),
            sa.Column("keywords", sa.JSON(), nullable=False),
            sa.Column("embedding_model", sa.String(length=120), nullable=False),
            sa.Column("embedding", sa.JSON(), nullable=False),
            sa.Column("content_sha", sa.String(length=160), nullable=False),
            sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["gitlab_projects.id"]),
            sa.ForeignKeyConstraint(["repo_file_index_id"], ["repo_file_indexes.id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _index("ix_repo_code_chunks_chunk_index", "repo_code_chunks", ["chunk_index"])
    _index("ix_repo_code_chunks_content_sha", "repo_code_chunks", ["content_sha"])
    _index("ix_repo_code_chunks_file_path", "repo_code_chunks", ["file_path"])
    _index("ix_repo_code_chunks_id", "repo_code_chunks", ["id"])
    _index("ix_repo_code_chunks_indexed_at", "repo_code_chunks", ["indexed_at"])
    _index("ix_repo_code_chunks_language", "repo_code_chunks", ["language"])
    _index("ix_repo_code_chunks_project_id", "repo_code_chunks", ["project_id"])
    _index("ix_repo_code_chunks_project_path", "repo_code_chunks", ["project_path"])
    _index("ix_repo_code_chunks_ref", "repo_code_chunks", ["ref"])
    _index("ix_repo_code_chunks_repo_file_index_id", "repo_code_chunks", ["repo_file_index_id"])
    _index("ix_repo_code_chunks_workspace_id", "repo_code_chunks", ["workspace_id"])
    _index(
        "uq_repo_code_chunk_workspace_project_path_ref",
        "repo_code_chunks",
        ["workspace_id", "project_id", "file_path", "ref", "chunk_index"],
        unique=True,
    )

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "repo_symbol_indexes" not in tables:
        op.create_table(
            "repo_symbol_indexes",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("workspace_id", sa.Integer(), nullable=True),
            sa.Column("project_id", sa.Integer(), nullable=True),
            sa.Column("repo_file_index_id", sa.Integer(), nullable=True),
            sa.Column("project_path", sa.String(length=255), nullable=False),
            sa.Column("file_path", sa.String(length=600), nullable=False),
            sa.Column("ref", sa.String(length=255), nullable=False),
            sa.Column("symbol_name", sa.String(length=255), nullable=False),
            sa.Column("symbol_type", sa.String(length=80), nullable=False),
            sa.Column("signature", sa.String(length=800), nullable=False),
            sa.Column("start_line", sa.Integer(), nullable=False),
            sa.Column("end_line", sa.Integer(), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["gitlab_projects.id"]),
            sa.ForeignKeyConstraint(["repo_file_index_id"], ["repo_file_indexes.id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _index("ix_repo_symbol_indexes_file_path", "repo_symbol_indexes", ["file_path"])
    _index("ix_repo_symbol_indexes_id", "repo_symbol_indexes", ["id"])
    _index("ix_repo_symbol_indexes_indexed_at", "repo_symbol_indexes", ["indexed_at"])
    _index("ix_repo_symbol_indexes_project_id", "repo_symbol_indexes", ["project_id"])
    _index("ix_repo_symbol_indexes_project_path", "repo_symbol_indexes", ["project_path"])
    _index("ix_repo_symbol_indexes_ref", "repo_symbol_indexes", ["ref"])
    _index("ix_repo_symbol_indexes_repo_file_index_id", "repo_symbol_indexes", ["repo_file_index_id"])
    _index("ix_repo_symbol_indexes_symbol_name", "repo_symbol_indexes", ["symbol_name"])
    _index("ix_repo_symbol_indexes_symbol_type", "repo_symbol_indexes", ["symbol_type"])
    _index("ix_repo_symbol_indexes_workspace_id", "repo_symbol_indexes", ["workspace_id"])
    _index(
        "uq_repo_symbol_workspace_project_path_ref",
        "repo_symbol_indexes",
        ["workspace_id", "project_id", "file_path", "ref", "symbol_name", "start_line"],
        unique=True,
    )


def downgrade() -> None:
    for name in [
        "uq_repo_symbol_workspace_project_path_ref",
        "ix_repo_symbol_indexes_workspace_id",
        "ix_repo_symbol_indexes_symbol_type",
        "ix_repo_symbol_indexes_symbol_name",
        "ix_repo_symbol_indexes_repo_file_index_id",
        "ix_repo_symbol_indexes_ref",
        "ix_repo_symbol_indexes_project_path",
        "ix_repo_symbol_indexes_project_id",
        "ix_repo_symbol_indexes_indexed_at",
        "ix_repo_symbol_indexes_id",
        "ix_repo_symbol_indexes_file_path",
    ]:
        _drop_index(name, "repo_symbol_indexes")
    op.drop_table("repo_symbol_indexes")

    for name in [
        "uq_repo_code_chunk_workspace_project_path_ref",
        "ix_repo_code_chunks_workspace_id",
        "ix_repo_code_chunks_repo_file_index_id",
        "ix_repo_code_chunks_ref",
        "ix_repo_code_chunks_project_path",
        "ix_repo_code_chunks_project_id",
        "ix_repo_code_chunks_language",
        "ix_repo_code_chunks_indexed_at",
        "ix_repo_code_chunks_id",
        "ix_repo_code_chunks_file_path",
        "ix_repo_code_chunks_content_sha",
        "ix_repo_code_chunks_chunk_index",
    ]:
        _drop_index(name, "repo_code_chunks")
    op.drop_table("repo_code_chunks")

    for name in [
        "uq_repo_file_content_workspace_project_path_ref",
        "ix_repo_file_contents_workspace_id",
        "ix_repo_file_contents_repo_file_index_id",
        "ix_repo_file_contents_ref",
        "ix_repo_file_contents_project_path",
        "ix_repo_file_contents_project_id",
        "ix_repo_file_contents_is_truncated",
        "ix_repo_file_contents_indexed_at",
        "ix_repo_file_contents_id",
        "ix_repo_file_contents_file_path",
        "ix_repo_file_contents_content_sha",
    ]:
        _drop_index(name, "repo_file_contents")
    op.drop_table("repo_file_contents")


def _index(name: str, table: str, columns: list[str], *, unique: bool = False) -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {index["name"] for index in inspector.get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns, unique=unique)


def _drop_index(name: str, table: str) -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {index["name"] for index in inspector.get_indexes(table)}
    if name in existing:
        op.drop_index(name, table_name=table)
