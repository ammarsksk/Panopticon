"""Add GitLab project sync tables.

Revision ID: 0002_gitlab_project_sync
Revises: 0001_initial
Create Date: 2026-05-16
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0002_gitlab_project_sync"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gitlab_projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("gitlab_project_id", sa.String(length=80), nullable=False),
        sa.Column("project_path", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("namespace", sa.String(length=255), nullable=False),
        sa.Column("web_url", sa.String(length=500), nullable=False),
        sa.Column("default_branch", sa.String(length=160), nullable=False),
        sa.Column("visibility", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("open_merge_requests_count", sa.Integer(), nullable=False),
        sa.Column("failed_pipelines_count", sa.Integer(), nullable=False),
        sa.Column("latest_pipeline_id", sa.String(length=80), nullable=False),
        sa.Column("latest_pipeline_status", sa.String(length=40), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_gitlab_projects_id", "gitlab_projects", ["id"])
    op.create_index("ix_gitlab_projects_gitlab_project_id", "gitlab_projects", ["gitlab_project_id"], unique=True)
    op.create_index("ix_gitlab_projects_project_path", "gitlab_projects", ["project_path"], unique=True)
    op.create_index("ix_gitlab_projects_last_activity_at", "gitlab_projects", ["last_activity_at"])
    op.create_index("ix_gitlab_projects_synced_at", "gitlab_projects", ["synced_at"])

    op.create_table(
        "project_sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("projects_seen", sa.Integer(), nullable=False),
        sa.Column("projects_updated", sa.Integer(), nullable=False),
        sa.Column("merge_requests_seen", sa.Integer(), nullable=False),
        sa.Column("pipelines_seen", sa.Integer(), nullable=False),
        sa.Column("jobs_seen", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_project_sync_runs_id", "project_sync_runs", ["id"])
    op.create_index("ix_project_sync_runs_provider", "project_sync_runs", ["provider"])
    op.create_index("ix_project_sync_runs_status", "project_sync_runs", ["status"])
    op.create_index("ix_project_sync_runs_started_at", "project_sync_runs", ["started_at"])

    op.create_table(
        "merge_request_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("gitlab_project_id", sa.String(length=80), nullable=False),
        sa.Column("project_path", sa.String(length=255), nullable=False),
        sa.Column("merge_request_iid", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("state", sa.String(length=60), nullable=False),
        sa.Column("web_url", sa.String(length=500), nullable=False),
        sa.Column("author_username", sa.String(length=120), nullable=False),
        sa.Column("source_branch", sa.String(length=255), nullable=False),
        sa.Column("target_branch", sa.String(length=255), nullable=False),
        sa.Column("draft", sa.Boolean(), nullable=False),
        sa.Column("created_at_gitlab", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at_gitlab", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_merge_request_snapshots_id", "merge_request_snapshots", ["id"])
    op.create_index("ix_merge_request_snapshots_gitlab_project_id", "merge_request_snapshots", ["gitlab_project_id"])
    op.create_index("ix_merge_request_snapshots_project_path", "merge_request_snapshots", ["project_path"])
    op.create_index("ix_merge_request_snapshots_merge_request_iid", "merge_request_snapshots", ["merge_request_iid"])
    op.create_index("ix_merge_request_snapshots_updated_at_gitlab", "merge_request_snapshots", ["updated_at_gitlab"])
    op.create_index("ix_merge_request_snapshots_synced_at", "merge_request_snapshots", ["synced_at"])

    op.create_table(
        "pipeline_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("gitlab_project_id", sa.String(length=80), nullable=False),
        sa.Column("project_path", sa.String(length=255), nullable=False),
        sa.Column("pipeline_id", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("ref", sa.String(length=255), nullable=False),
        sa.Column("sha", sa.String(length=80), nullable=False),
        sa.Column("web_url", sa.String(length=500), nullable=False),
        sa.Column("created_at_gitlab", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at_gitlab", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_pipeline_snapshots_id", "pipeline_snapshots", ["id"])
    op.create_index("ix_pipeline_snapshots_gitlab_project_id", "pipeline_snapshots", ["gitlab_project_id"])
    op.create_index("ix_pipeline_snapshots_project_path", "pipeline_snapshots", ["project_path"])
    op.create_index("ix_pipeline_snapshots_pipeline_id", "pipeline_snapshots", ["pipeline_id"])
    op.create_index("ix_pipeline_snapshots_status", "pipeline_snapshots", ["status"])
    op.create_index("ix_pipeline_snapshots_updated_at_gitlab", "pipeline_snapshots", ["updated_at_gitlab"])
    op.create_index("ix_pipeline_snapshots_synced_at", "pipeline_snapshots", ["synced_at"])

    op.create_table(
        "job_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("gitlab_project_id", sa.String(length=80), nullable=False),
        sa.Column("project_path", sa.String(length=255), nullable=False),
        sa.Column("pipeline_id", sa.String(length=80), nullable=False),
        sa.Column("job_id", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("stage", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("failure_reason", sa.String(length=255), nullable=False),
        sa.Column("web_url", sa.String(length=500), nullable=False),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("created_at_gitlab", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_job_snapshots_id", "job_snapshots", ["id"])
    op.create_index("ix_job_snapshots_gitlab_project_id", "job_snapshots", ["gitlab_project_id"])
    op.create_index("ix_job_snapshots_project_path", "job_snapshots", ["project_path"])
    op.create_index("ix_job_snapshots_pipeline_id", "job_snapshots", ["pipeline_id"])
    op.create_index("ix_job_snapshots_job_id", "job_snapshots", ["job_id"])
    op.create_index("ix_job_snapshots_status", "job_snapshots", ["status"])
    op.create_index("ix_job_snapshots_synced_at", "job_snapshots", ["synced_at"])


def downgrade() -> None:
    op.drop_table("job_snapshots")
    op.drop_table("pipeline_snapshots")
    op.drop_table("merge_request_snapshots")
    op.drop_table("project_sync_runs")
    op.drop_table("gitlab_projects")
