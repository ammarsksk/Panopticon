"""Add OAuth state and connection tables.

Revision ID: 0009_oauth_connections
Revises: 0008_auth_workspaces
Create Date: 2026-05-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_oauth_connections"
down_revision = "0008_auth_workspaces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oauth_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("state_hash", sa.String(length=128), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("redirect_after", sa.String(length=500), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_oauth_states_id"), "oauth_states", ["id"], unique=False)
    op.create_index(op.f("ix_oauth_states_provider"), "oauth_states", ["provider"], unique=False)
    op.create_index(op.f("ix_oauth_states_state_hash"), "oauth_states", ["state_hash"], unique=True)
    op.create_index(op.f("ix_oauth_states_workspace_id"), "oauth_states", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_oauth_states_user_id"), "oauth_states", ["user_id"], unique=False)
    op.create_index(op.f("ix_oauth_states_expires_at"), "oauth_states", ["expires_at"], unique=False)
    op.create_index(op.f("ix_oauth_states_created_at"), "oauth_states", ["created_at"], unique=False)

    op.create_table(
        "oauth_connections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("provider_user_id", sa.String(length=160), nullable=False),
        sa.Column("account_label", sa.String(length=255), nullable=False),
        sa.Column("access_token_encrypted", sa.Text(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_oauth_connections_id"), "oauth_connections", ["id"], unique=False)
    op.create_index(op.f("ix_oauth_connections_provider"), "oauth_connections", ["provider"], unique=False)
    op.create_index(op.f("ix_oauth_connections_workspace_id"), "oauth_connections", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_oauth_connections_user_id"), "oauth_connections", ["user_id"], unique=False)
    op.create_index(op.f("ix_oauth_connections_provider_user_id"), "oauth_connections", ["provider_user_id"], unique=False)
    op.create_index(op.f("ix_oauth_connections_created_at"), "oauth_connections", ["created_at"], unique=False)
    op.create_index(op.f("ix_oauth_connections_updated_at"), "oauth_connections", ["updated_at"], unique=False)
    op.create_index(
        "ix_oauth_connections_provider_workspace_user",
        "oauth_connections",
        ["provider", "workspace_id", "user_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_oauth_connections_provider_workspace_user", table_name="oauth_connections")
    op.drop_index(op.f("ix_oauth_connections_updated_at"), table_name="oauth_connections")
    op.drop_index(op.f("ix_oauth_connections_created_at"), table_name="oauth_connections")
    op.drop_index(op.f("ix_oauth_connections_provider_user_id"), table_name="oauth_connections")
    op.drop_index(op.f("ix_oauth_connections_user_id"), table_name="oauth_connections")
    op.drop_index(op.f("ix_oauth_connections_workspace_id"), table_name="oauth_connections")
    op.drop_index(op.f("ix_oauth_connections_provider"), table_name="oauth_connections")
    op.drop_index(op.f("ix_oauth_connections_id"), table_name="oauth_connections")
    op.drop_table("oauth_connections")

    op.drop_index(op.f("ix_oauth_states_created_at"), table_name="oauth_states")
    op.drop_index(op.f("ix_oauth_states_expires_at"), table_name="oauth_states")
    op.drop_index(op.f("ix_oauth_states_user_id"), table_name="oauth_states")
    op.drop_index(op.f("ix_oauth_states_workspace_id"), table_name="oauth_states")
    op.drop_index(op.f("ix_oauth_states_state_hash"), table_name="oauth_states")
    op.drop_index(op.f("ix_oauth_states_provider"), table_name="oauth_states")
    op.drop_index(op.f("ix_oauth_states_id"), table_name="oauth_states")
    op.drop_table("oauth_states")
