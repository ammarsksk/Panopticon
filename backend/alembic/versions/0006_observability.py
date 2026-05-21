"""Add observability event and correlation tables.

Revision ID: 0006_observability
Revises: 0005_fix_plans
Create Date: 2026-05-21
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0006_observability"
down_revision: str | None = "0005_fix_plans"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "observability_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("event_uid", sa.String(length=160), nullable=False),
        sa.Column("project_path", sa.String(length=255), nullable=False),
        sa.Column("service_name", sa.String(length=255), nullable=False),
        sa.Column("environment", sa.String(length=120), nullable=False),
        sa.Column("severity", sa.String(length=40), nullable=False),
        sa.Column("signal_type", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("metric_name", sa.String(length=255), nullable=False),
        sa.Column("trace_id", sa.String(length=160), nullable=False),
        sa.Column("alert_url", sa.String(length=500), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_observability_events_id", "observability_events", ["id"])
    op.create_index("ix_observability_events_provider", "observability_events", ["provider"])
    op.create_index("ix_observability_events_event_uid", "observability_events", ["event_uid"], unique=True)
    op.create_index("ix_observability_events_project_path", "observability_events", ["project_path"])
    op.create_index("ix_observability_events_service_name", "observability_events", ["service_name"])
    op.create_index("ix_observability_events_environment", "observability_events", ["environment"])
    op.create_index("ix_observability_events_severity", "observability_events", ["severity"])
    op.create_index("ix_observability_events_signal_type", "observability_events", ["signal_type"])
    op.create_index("ix_observability_events_trace_id", "observability_events", ["trace_id"])
    op.create_index("ix_observability_events_observed_at", "observability_events", ["observed_at"])
    op.create_index("ix_observability_events_created_at", "observability_events", ["created_at"])

    op.create_table(
        "incident_correlations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_path", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("severity", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("suspected_cause", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("timeline", sa.JSON(), nullable=False),
        sa.Column("related_observability_event_ids", sa.JSON(), nullable=False),
        sa.Column("related_pipeline_ids", sa.JSON(), nullable=False),
        sa.Column("related_risk_ids", sa.JSON(), nullable=False),
        sa.Column("related_incident_ids", sa.JSON(), nullable=False),
        sa.Column("recommendations", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_incident_correlations_id", "incident_correlations", ["id"])
    op.create_index("ix_incident_correlations_project_path", "incident_correlations", ["project_path"])
    op.create_index("ix_incident_correlations_severity", "incident_correlations", ["severity"])
    op.create_index("ix_incident_correlations_status", "incident_correlations", ["status"])
    op.create_index("ix_incident_correlations_created_at", "incident_correlations", ["created_at"])
    op.create_index("ix_incident_correlations_updated_at", "incident_correlations", ["updated_at"])


def downgrade() -> None:
    op.drop_table("incident_correlations")
    op.drop_table("observability_events")
