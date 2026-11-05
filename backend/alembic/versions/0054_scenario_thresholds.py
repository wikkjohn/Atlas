"""Scenario-specific success thresholds

Phase 80 (roadmap Milestone G, step 5). `scenario_thresholds` holds versioned success
thresholds per scenario: proposed by one person, approved by a risk approver who is someone
else (`four_eyes`), at most one active version per scenario. Without one, the scenario's
risk tier gives built-in defaults; experiments record which applied
(`configuration.thresholds_source`).

Revision ID: 0054_scenario_thresholds
Revises: 0053_ai_guardrails
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0054_scenario_thresholds"
down_revision: str | None = "0053_ai_guardrails"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scenario_thresholds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scenario_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("risk_tier", sa.String(length=20), nullable=False),
        sa.Column("thresholds", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("proposed_by", sa.Uuid(), nullable=False),
        sa.Column(
            "proposed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('proposed', 'active', 'superseded', 'rejected')",
            name=op.f("ck_scenario_thresholds_status_valid"),
        ),
        sa.CheckConstraint(
            "risk_tier IN ('critical', 'high', 'medium', 'low')",
            name=op.f("ck_scenario_thresholds_risk_tier_valid"),
        ),
        sa.CheckConstraint(
            "decided_by IS NULL OR decided_by <> proposed_by",
            name=op.f("ck_scenario_thresholds_four_eyes"),
        ),
        sa.ForeignKeyConstraint(
            ["proposed_by"],
            ["users.id"],
            name=op.f("fk_scenario_thresholds_proposed_by_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"],
            ["users.id"],
            name=op.f("fk_scenario_thresholds_decided_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scenario_thresholds")),
        sa.UniqueConstraint("scenario_id", "version", name="uq_scenario_thresholds_version"),
    )
    op.create_index(
        op.f("ix_scenario_thresholds_scenario_id"), "scenario_thresholds", ["scenario_id"]
    )
    op.create_index(op.f("ix_scenario_thresholds_status"), "scenario_thresholds", ["status"])
    op.create_index(
        "uq_scenario_thresholds_one_active",
        "scenario_thresholds",
        ["scenario_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("uq_scenario_thresholds_one_active", table_name="scenario_thresholds")
    op.drop_index(op.f("ix_scenario_thresholds_status"), table_name="scenario_thresholds")
    op.drop_index(op.f("ix_scenario_thresholds_scenario_id"), table_name="scenario_thresholds")
    op.drop_table("scenario_thresholds")
