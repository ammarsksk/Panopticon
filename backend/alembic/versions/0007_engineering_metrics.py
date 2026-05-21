"""Add engineering metric snapshots.

Revision ID: 0007_engineering_metrics
Revises: 0006_observability
Create Date: 2026-05-21
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0007_engineering_metrics"
down_revision: str | None = "0006_observability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "engineering_metric_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope_type", sa.String(length=40), nullable=False),
        sa.Column("project_path", sa.String(length=255), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("health_score", sa.Float(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_engineering_metric_snapshots_id", "engineering_metric_snapshots", ["id"])
    op.create_index("ix_engineering_metric_snapshots_scope_type", "engineering_metric_snapshots", ["scope_type"])
    op.create_index("ix_engineering_metric_snapshots_project_path", "engineering_metric_snapshots", ["project_path"])
    op.create_index("ix_engineering_metric_snapshots_snapshot_date", "engineering_metric_snapshots", ["snapshot_date"])
    op.create_index("ix_engineering_metric_snapshots_health_score", "engineering_metric_snapshots", ["health_score"])
    op.create_index("ix_engineering_metric_snapshots_created_at", "engineering_metric_snapshots", ["created_at"])
    op.create_index("ix_engineering_metric_snapshots_updated_at", "engineering_metric_snapshots", ["updated_at"])


def downgrade() -> None:
    op.drop_table("engineering_metric_snapshots")
