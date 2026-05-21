"""Add fix plan tables.

Revision ID: 0005_fix_plans
Revises: 0004_chat
Create Date: 2026-05-21
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0005_fix_plans"
down_revision: str | None = "0004_chat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fix_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("gitlab_projects.id"), nullable=True),
        sa.Column("project_path", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=80), nullable=False),
        sa.Column("source_id", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=60), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.Column("fix_type", sa.String(length=80), nullable=False),
        sa.Column("base_branch", sa.String(length=255), nullable=False),
        sa.Column("branch_name", sa.String(length=255), nullable=False),
        sa.Column("merge_request_iid", sa.String(length=80), nullable=False),
        sa.Column("merge_request_url", sa.String(length=500), nullable=False),
        sa.Column("plan_payload", sa.JSON(), nullable=False),
        sa.Column("last_result", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_fix_plans_id", "fix_plans", ["id"])
    op.create_index("ix_fix_plans_project_id", "fix_plans", ["project_id"])
    op.create_index("ix_fix_plans_project_path", "fix_plans", ["project_path"])
    op.create_index("ix_fix_plans_source_type", "fix_plans", ["source_type"])
    op.create_index("ix_fix_plans_status", "fix_plans", ["status"])
    op.create_index("ix_fix_plans_fix_type", "fix_plans", ["fix_type"])
    op.create_index("ix_fix_plans_created_at", "fix_plans", ["created_at"])
    op.create_index("ix_fix_plans_updated_at", "fix_plans", ["updated_at"])

    op.create_table(
        "fix_plan_approvals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fix_plan_id", sa.Integer(), sa.ForeignKey("fix_plans.id"), nullable=False),
        sa.Column("decision", sa.String(length=40), nullable=False),
        sa.Column("actor", sa.String(length=120), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_fix_plan_approvals_id", "fix_plan_approvals", ["id"])
    op.create_index("ix_fix_plan_approvals_fix_plan_id", "fix_plan_approvals", ["fix_plan_id"])
    op.create_index("ix_fix_plan_approvals_decision", "fix_plan_approvals", ["decision"])
    op.create_index("ix_fix_plan_approvals_created_at", "fix_plan_approvals", ["created_at"])


def downgrade() -> None:
    op.drop_table("fix_plan_approvals")
    op.drop_table("fix_plans")
