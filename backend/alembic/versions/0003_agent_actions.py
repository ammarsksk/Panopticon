"""Add agent action approval tables.

Revision ID: 0003_agent_actions
Revises: 0002_gitlab_project_sync
Create Date: 2026-05-16
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0003_agent_actions"
down_revision: str | None = "0002_gitlab_project_sync"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("recommendation_id", sa.Integer(), sa.ForeignKey("recommendations.id"), nullable=True),
        sa.Column("project_path", sa.String(length=255), nullable=False),
        sa.Column("action_type", sa.String(length=80), nullable=False),
        sa.Column("channel", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.Column("payload_preview", sa.JSON(), nullable=False),
        sa.Column("execution_context", sa.JSON(), nullable=False),
        sa.Column("last_result", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_actions_id", "agent_actions", ["id"])
    op.create_index("ix_agent_actions_recommendation_id", "agent_actions", ["recommendation_id"])
    op.create_index("ix_agent_actions_project_path", "agent_actions", ["project_path"])
    op.create_index("ix_agent_actions_action_type", "agent_actions", ["action_type"])
    op.create_index("ix_agent_actions_channel", "agent_actions", ["channel"])
    op.create_index("ix_agent_actions_status", "agent_actions", ["status"])
    op.create_index("ix_agent_actions_created_at", "agent_actions", ["created_at"])
    op.create_index("ix_agent_actions_updated_at", "agent_actions", ["updated_at"])

    op.create_table(
        "action_approvals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_action_id", sa.Integer(), sa.ForeignKey("agent_actions.id"), nullable=False),
        sa.Column("decision", sa.String(length=40), nullable=False),
        sa.Column("actor", sa.String(length=120), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_action_approvals_id", "action_approvals", ["id"])
    op.create_index("ix_action_approvals_agent_action_id", "action_approvals", ["agent_action_id"])
    op.create_index("ix_action_approvals_decision", "action_approvals", ["decision"])
    op.create_index("ix_action_approvals_created_at", "action_approvals", ["created_at"])


def downgrade() -> None:
    op.drop_table("action_approvals")
    op.drop_table("agent_actions")
