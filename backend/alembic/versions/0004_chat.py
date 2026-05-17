"""Add chat tables.

Revision ID: 0004_chat
Revises: 0003_agent_actions
Create Date: 2026-05-16
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0004_chat"
down_revision: str | None = "0003_agent_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_threads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("gitlab_projects.id"), nullable=True),
        sa.Column("project_path", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chat_threads_id", "chat_threads", ["id"])
    op.create_index("ix_chat_threads_project_id", "chat_threads", ["project_id"])
    op.create_index("ix_chat_threads_project_path", "chat_threads", ["project_path"])
    op.create_index("ix_chat_threads_created_at", "chat_threads", ["created_at"])
    op.create_index("ix_chat_threads_updated_at", "chat_threads", ["updated_at"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("thread_id", sa.Integer(), sa.ForeignKey("chat_threads.id"), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("prepared_action_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chat_messages_id", "chat_messages", ["id"])
    op.create_index("ix_chat_messages_thread_id", "chat_messages", ["thread_id"])
    op.create_index("ix_chat_messages_role", "chat_messages", ["role"])
    op.create_index("ix_chat_messages_created_at", "chat_messages", ["created_at"])


def downgrade() -> None:
    op.drop_table("chat_messages")
    op.drop_table("chat_threads")
