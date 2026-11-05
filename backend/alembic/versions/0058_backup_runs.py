"""The backup and recovery-drill record

Phase 87 (roadmap Milestone H, step 4).

- `backup_runs`: every backup, verification, restore and recovery drill taken with
  `python -m app.cli backup`, whether it passed, where the backup is and what was measured
  (sizes, row counts, timings, the recovery point).

Revision ID: 0058_backup_runs
Revises: 0057_ratelimit_audit_retention
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0058_backup_runs"
down_revision: str | None = "0057_ratelimit_audit_retention"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backup_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_number", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("location", sa.String(length=500), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_number", name=op.f("uq_backup_runs_run_number")),
    )


def downgrade() -> None:
    op.drop_table("backup_runs")
