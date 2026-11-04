"""Repeated-seed experiment series

Phase 77 (roadmap Milestone G, step 2). `experiment_series` repeats an experiment over
several seeds; each replicate is an ordinary experiment (`experiments.series_id`), and the
series stores statistics across them: paired differences, confidence intervals and
Holm-adjusted significance tests.

Revision ID: 0051_experiment_series
Revises: 0050_rolling_archive
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0051_experiment_series"
down_revision: str | None = "0050_rolling_archive"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "experiment_series",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("series_number", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("scenario_id", sa.String(length=64), nullable=False),
        sa.Column("scenario_version", sa.Integer(), nullable=False),
        sa.Column("candidate_mode", sa.String(length=20), nullable=False),
        sa.Column("tool_record_id", sa.Uuid(), nullable=True),
        sa.Column("tool_id", sa.String(length=64), nullable=True),
        sa.Column("tool_version", sa.String(length=40), nullable=True),
        sa.Column("seeds", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("configuration", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("statistics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("verdict", sa.String(length=20), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name=op.f("ck_experiment_series_status_valid"),
        ),
        sa.CheckConstraint(
            "confidence > 0.5 AND confidence < 1",
            name=op.f("ck_experiment_series_confidence_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["tool_record_id"],
            ["ai_tools.id"],
            name=op.f("fk_experiment_series_tool_record_id_ai_tools"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_experiment_series_created_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_experiment_series")),
        sa.UniqueConstraint("series_number", name=op.f("uq_experiment_series_series_number")),
    )
    op.create_index(op.f("ix_experiment_series_status"), "experiment_series", ["status"])
    op.create_index(op.f("ix_experiment_series_tool_id"), "experiment_series", ["tool_id"])
    op.add_column("experiments", sa.Column("series_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_experiments_series_id_experiment_series"),
        "experiments",
        "experiment_series",
        ["series_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(op.f("ix_experiments_series_id"), "experiments", ["series_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_experiments_series_id"), table_name="experiments")
    op.drop_constraint(
        op.f("fk_experiments_series_id_experiment_series"), "experiments", type_="foreignkey"
    )
    op.drop_column("experiments", "series_id")
    op.drop_index(op.f("ix_experiment_series_tool_id"), table_name="experiment_series")
    op.drop_index(op.f("ix_experiment_series_status"), table_name="experiment_series")
    op.drop_table("experiment_series")
