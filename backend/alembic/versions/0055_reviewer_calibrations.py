"""Reviewer calibrations: simulated reviewer behaviour fitted from observed reviews

Phase 82 (roadmap Milestone G, step 7). `reviewer_calibrations` holds, per scenario and
review step, the observed reviews and the parameters fitted from them with intervals; at
most one active calibration a step. Runs record the calibration they simulated
(`simulation_runs.config.calibration`), and `ReviewerModel.accuracy_should_reject` lets a
reviewer be better on one kind of case than the other (configuration only, no column).

Revision ID: 0055_reviewer_calibrations
Revises: 0054_scenario_thresholds
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0055_reviewer_calibrations"
down_revision: str | None = "0054_scenario_thresholds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reviewer_calibrations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("calibration_number", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("scenario_id", sa.String(length=64), nullable=False),
        sa.Column("step_id", sa.String(length=64), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("observations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("observation_count", sa.Integer(), nullable=False),
        sa.Column("data_digest", sa.String(length=64), nullable=False),
        sa.Column("fitted", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('active', 'superseded')",
            name=op.f("ck_reviewer_calibrations_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_reviewer_calibrations_created_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reviewer_calibrations")),
        sa.UniqueConstraint(
            "calibration_number", name=op.f("uq_reviewer_calibrations_calibration_number")
        ),
    )
    op.create_index(
        op.f("ix_reviewer_calibrations_scenario_id"), "reviewer_calibrations", ["scenario_id"]
    )
    op.create_index(
        "uq_reviewer_calibrations_one_active",
        "reviewer_calibrations",
        ["scenario_id", "step_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("uq_reviewer_calibrations_one_active", table_name="reviewer_calibrations")
    op.drop_index(op.f("ix_reviewer_calibrations_scenario_id"), table_name="reviewer_calibrations")
    op.drop_table("reviewer_calibrations")
