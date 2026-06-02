"""Add failed job trace context fields.

Revision ID: 0011_job_trace_context
Revises: 0010_repo_context
Create Date: 2026-06-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0011_job_trace_context"
down_revision: Union[str, None] = "0010_repo_context"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("job_snapshots", sa.Column("failure_signature", sa.String(length=255), nullable=False, server_default=""))
    op.add_column("job_snapshots", sa.Column("trace_summary", sa.Text(), nullable=False, server_default=""))
    op.add_column("job_snapshots", sa.Column("trace_excerpt", sa.Text(), nullable=False, server_default=""))
    op.add_column("job_snapshots", sa.Column("trace_fetched_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_job_snapshots_failure_signature"), "job_snapshots", ["failure_signature"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_job_snapshots_failure_signature"), table_name="job_snapshots")
    op.drop_column("job_snapshots", "trace_fetched_at")
    op.drop_column("job_snapshots", "trace_excerpt")
    op.drop_column("job_snapshots", "trace_summary")
    op.drop_column("job_snapshots", "failure_signature")
