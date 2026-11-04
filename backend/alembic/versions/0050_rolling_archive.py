"""Rolling archive of a simulation run's history

Phase 75 (roadmap Milestone F, step 7). A long run can archive the history of its finished
cases while it is still going, so the database holds only the cases in flight;
`simulation_archive_segments` records each part. When the run ends, the segments become
one archive (`simulation_archives`), restorable like any other.

Revision ID: 0050_rolling_archive
Revises: 0049_event_outbox
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0050_rolling_archive"
down_revision: str | None = "0049_event_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "simulation_archive_segments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("shard", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("location", sa.String(length=300), nullable=False),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rows", sa.BigInteger(), nullable=False),
        sa.Column("bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["simulation_runs.id"],
            name=op.f("fk_simulation_archive_segments_run_id_simulation_runs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_simulation_archive_segments")),
        sa.UniqueConstraint("run_id", "shard", "sequence", name="uq_simulation_archive_segments"),
    )
    op.create_index(
        op.f("ix_simulation_archive_segments_run_id"),
        "simulation_archive_segments",
        ["run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_simulation_archive_segments_run_id"), table_name="simulation_archive_segments"
    )
    op.drop_table("simulation_archive_segments")
