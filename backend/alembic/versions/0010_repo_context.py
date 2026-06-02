"""Add repository context index tables.

Revision ID: 0010_repo_context
Revises: 0009_oauth_connections
Create Date: 2026-05-26
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_repo_context"
down_revision = "0009_oauth_connections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "repo_index_runs" not in tables:
        op.create_table(
            "repo_index_runs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("workspace_id", sa.Integer(), nullable=True),
            sa.Column("project_id", sa.Integer(), nullable=True),
            sa.Column("project_path", sa.String(length=255), nullable=False),
            sa.Column("ref", sa.String(length=255), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("files_seen", sa.Integer(), nullable=False),
            sa.Column("files_indexed", sa.Integer(), nullable=False),
            sa.Column("files_skipped", sa.Integer(), nullable=False),
            sa.Column("error", sa.Text(), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["project_id"], ["gitlab_projects.id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing("ix_repo_index_runs_id", "repo_index_runs", ["id"])
    _create_index_if_missing("ix_repo_index_runs_project_id", "repo_index_runs", ["project_id"])
    _create_index_if_missing("ix_repo_index_runs_project_path", "repo_index_runs", ["project_path"])
    _create_index_if_missing("ix_repo_index_runs_started_at", "repo_index_runs", ["started_at"])
    _create_index_if_missing("ix_repo_index_runs_status", "repo_index_runs", ["status"])
    _create_index_if_missing("ix_repo_index_runs_workspace_id", "repo_index_runs", ["workspace_id"])

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "repo_file_indexes" not in tables:
        op.create_table(
            "repo_file_indexes",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("workspace_id", sa.Integer(), nullable=True),
            sa.Column("project_id", sa.Integer(), nullable=True),
            sa.Column("project_path", sa.String(length=255), nullable=False),
            sa.Column("file_path", sa.String(length=600), nullable=False),
            sa.Column("ref", sa.String(length=255), nullable=False),
            sa.Column("file_type", sa.String(length=80), nullable=False),
            sa.Column("language", sa.String(length=80), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column("content_sha", sa.String(length=160), nullable=False),
            sa.Column("last_commit_id", sa.String(length=160), nullable=False),
            sa.Column("content_excerpt", sa.Text(), nullable=False),
            sa.Column("signals", sa.JSON(), nullable=False),
            sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["gitlab_projects.id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing("ix_repo_file_indexes_content_sha", "repo_file_indexes", ["content_sha"])
    _create_index_if_missing("ix_repo_file_indexes_file_path", "repo_file_indexes", ["file_path"])
    _create_index_if_missing("ix_repo_file_indexes_file_type", "repo_file_indexes", ["file_type"])
    _create_index_if_missing("ix_repo_file_indexes_id", "repo_file_indexes", ["id"])
    _create_index_if_missing("ix_repo_file_indexes_indexed_at", "repo_file_indexes", ["indexed_at"])
    _create_index_if_missing("ix_repo_file_indexes_language", "repo_file_indexes", ["language"])
    _create_index_if_missing("ix_repo_file_indexes_project_id", "repo_file_indexes", ["project_id"])
    _create_index_if_missing("ix_repo_file_indexes_project_path", "repo_file_indexes", ["project_path"])
    _create_index_if_missing("ix_repo_file_indexes_ref", "repo_file_indexes", ["ref"])
    _create_index_if_missing("ix_repo_file_indexes_workspace_id", "repo_file_indexes", ["workspace_id"])
    _create_index_if_missing(
        "uq_repo_file_workspace_project_path_ref",
        "repo_file_indexes",
        ["workspace_id", "project_id", "file_path", "ref"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_repo_file_workspace_project_path_ref", table_name="repo_file_indexes")
    op.drop_index(op.f("ix_repo_file_indexes_workspace_id"), table_name="repo_file_indexes")
    op.drop_index(op.f("ix_repo_file_indexes_ref"), table_name="repo_file_indexes")
    op.drop_index(op.f("ix_repo_file_indexes_project_path"), table_name="repo_file_indexes")
    op.drop_index(op.f("ix_repo_file_indexes_project_id"), table_name="repo_file_indexes")
    op.drop_index(op.f("ix_repo_file_indexes_language"), table_name="repo_file_indexes")
    op.drop_index(op.f("ix_repo_file_indexes_indexed_at"), table_name="repo_file_indexes")
    op.drop_index(op.f("ix_repo_file_indexes_id"), table_name="repo_file_indexes")
    op.drop_index(op.f("ix_repo_file_indexes_file_type"), table_name="repo_file_indexes")
    op.drop_index(op.f("ix_repo_file_indexes_file_path"), table_name="repo_file_indexes")
    op.drop_index(op.f("ix_repo_file_indexes_content_sha"), table_name="repo_file_indexes")
    op.drop_table("repo_file_indexes")

    op.drop_index(op.f("ix_repo_index_runs_workspace_id"), table_name="repo_index_runs")
    op.drop_index(op.f("ix_repo_index_runs_status"), table_name="repo_index_runs")
    op.drop_index(op.f("ix_repo_index_runs_started_at"), table_name="repo_index_runs")
    op.drop_index(op.f("ix_repo_index_runs_project_path"), table_name="repo_index_runs")
    op.drop_index(op.f("ix_repo_index_runs_project_id"), table_name="repo_index_runs")
    op.drop_index(op.f("ix_repo_index_runs_id"), table_name="repo_index_runs")
    op.drop_table("repo_index_runs")


def _create_index_if_missing(name: str, table_name: str, columns: list[str], *, unique: bool = False) -> None:
    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes(table_name)}
    if name not in indexes:
        op.create_index(name, table_name, columns, unique=unique)
