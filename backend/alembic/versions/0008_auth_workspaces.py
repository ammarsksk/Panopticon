"""Add authentication and workspace scoping.

Revision ID: 0008_auth_workspaces
Revises: 0007_engineering_metrics
Create Date: 2026-05-23
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0008_auth_workspaces"
down_revision: str | None = "0007_engineering_metrics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCOPED_TABLES = [
    "operational_events",
    "webhook_receipts",
    "gitlab_projects",
    "project_sync_runs",
    "merge_request_snapshots",
    "pipeline_snapshots",
    "job_snapshots",
    "risk_assessments",
    "pipeline_insights",
    "merge_request_signals",
    "incident_records",
    "observability_events",
    "incident_correlations",
    "engineering_metric_snapshots",
    "recommendations",
    "action_dispatches",
    "agent_actions",
    "action_approvals",
    "fix_plans",
    "fix_plan_approvals",
    "chat_threads",
    "chat_messages",
    "memory_records",
]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=500), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_id", "users", ["id"])
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_is_active", "users", ["is_active"])
    op.create_index("ix_users_created_at", "users", ["created_at"])

    op.create_table(
        "workspaces",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workspaces_id", "workspaces", ["id"])
    op.create_index("ix_workspaces_slug", "workspaces", ["slug"], unique=True)
    op.create_index("ix_workspaces_created_at", "workspaces", ["created_at"])

    op.create_table(
        "workspace_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workspace_members_id", "workspace_members", ["id"])
    op.create_index("ix_workspace_members_workspace_id", "workspace_members", ["workspace_id"])
    op.create_index("ix_workspace_members_user_id", "workspace_members", ["user_id"])
    op.create_index("ix_workspace_members_role", "workspace_members", ["role"])
    op.create_index("ix_workspace_members_created_at", "workspace_members", ["created_at"])

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_user_sessions_id", "user_sessions", ["id"])
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_workspace_id", "user_sessions", ["workspace_id"])
    op.create_index("ix_user_sessions_token_hash", "user_sessions", ["token_hash"], unique=True)
    op.create_index("ix_user_sessions_expires_at", "user_sessions", ["expires_at"])
    op.create_index("ix_user_sessions_created_at", "user_sessions", ["created_at"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("target_type", sa.String(length=120), nullable=False),
        sa.Column("target_id", sa.String(length=120), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_logs_id", "audit_logs", ["id"])
    op.create_index("ix_audit_logs_workspace_id", "audit_logs", ["workspace_id"])
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_event_type", "audit_logs", ["event_type"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])

    op.drop_index("ix_gitlab_projects_gitlab_project_id", table_name="gitlab_projects")
    op.drop_index("ix_gitlab_projects_project_path", table_name="gitlab_projects")

    for table in SCOPED_TABLES:
        op.add_column(table, sa.Column("workspace_id", sa.Integer(), nullable=True))
        op.create_index(f"ix_{table}_workspace_id", table, ["workspace_id"])

    op.create_index("ix_gitlab_projects_gitlab_project_id", "gitlab_projects", ["gitlab_project_id"])
    op.create_index("ix_gitlab_projects_project_path", "gitlab_projects", ["project_path"])
    op.create_index("uq_gitlab_projects_workspace_gitlab_id", "gitlab_projects", ["workspace_id", "gitlab_project_id"], unique=True)
    op.create_index("uq_gitlab_projects_workspace_project_path", "gitlab_projects", ["workspace_id", "project_path"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_gitlab_projects_workspace_project_path", table_name="gitlab_projects")
    op.drop_index("uq_gitlab_projects_workspace_gitlab_id", table_name="gitlab_projects")
    op.drop_index("ix_gitlab_projects_project_path", table_name="gitlab_projects")
    op.drop_index("ix_gitlab_projects_gitlab_project_id", table_name="gitlab_projects")
    for table in reversed(SCOPED_TABLES):
        op.drop_index(f"ix_{table}_workspace_id", table_name=table)
        op.drop_column(table, "workspace_id")
    op.create_index("ix_gitlab_projects_project_path", "gitlab_projects", ["project_path"], unique=True)
    op.create_index("ix_gitlab_projects_gitlab_project_id", "gitlab_projects", ["gitlab_project_id"], unique=True)
    op.drop_table("audit_logs")
    op.drop_table("user_sessions")
    op.drop_table("workspace_members")
    op.drop_table("workspaces")
    op.drop_table("users")
