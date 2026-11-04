"""Experiment portfolios: a tool family across workflows, departments and countries

Phase 78 (roadmap Milestone G, step 3). `ai_tools.family` groups tools into a product line
(the AGB rule-based review assistants are backfilled into one). `experiment_portfolios`
evaluates a family on every scenario it serves, in each chosen country: one repeated-seed
series per cell (`experiment_series.portfolio_id`, `experiment_series.country`), with
statistics across the cells.

Revision ID: 0052_experiment_portfolios
Revises: 0051_experiment_series
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0052_experiment_portfolios"
down_revision: str | None = "0051_experiment_series"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REVIEW_FAMILY = "agb-review-assistants"


def upgrade() -> None:
    op.add_column("ai_tools", sa.Column("family", sa.String(length=64), nullable=True))
    op.create_index(op.f("ix_ai_tools_family"), "ai_tools", ["family"])
    op.execute(
        sa.text(
            "UPDATE ai_tools SET family = :family WHERE adapter LIKE 'rule\\_based\\_%'"
        ).bindparams(family=REVIEW_FAMILY)
    )
    op.create_table(
        "experiment_portfolios",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("portfolio_number", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("family", sa.String(length=64), nullable=False),
        sa.Column("candidate_mode", sa.String(length=20), nullable=False),
        sa.Column("countries", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("seeds", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("applications", sa.Integer(), nullable=False),
        sa.Column("employees", sa.Integer(), nullable=False),
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
            name=op.f("ck_experiment_portfolios_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_experiment_portfolios_created_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_experiment_portfolios")),
        sa.UniqueConstraint(
            "portfolio_number", name=op.f("uq_experiment_portfolios_portfolio_number")
        ),
    )
    op.create_index(op.f("ix_experiment_portfolios_family"), "experiment_portfolios", ["family"])
    op.create_index(op.f("ix_experiment_portfolios_status"), "experiment_portfolios", ["status"])
    op.add_column("experiment_series", sa.Column("country", sa.String(length=2), nullable=True))
    op.add_column("experiment_series", sa.Column("portfolio_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_experiment_series_portfolio_id_experiment_portfolios"),
        "experiment_series",
        "experiment_portfolios",
        ["portfolio_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_experiment_series_portfolio_id"), "experiment_series", ["portfolio_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_experiment_series_portfolio_id"), table_name="experiment_series")
    op.drop_constraint(
        op.f("fk_experiment_series_portfolio_id_experiment_portfolios"),
        "experiment_series",
        type_="foreignkey",
    )
    op.drop_column("experiment_series", "portfolio_id")
    op.drop_column("experiment_series", "country")
    op.drop_index(op.f("ix_experiment_portfolios_status"), table_name="experiment_portfolios")
    op.drop_index(op.f("ix_experiment_portfolios_family"), table_name="experiment_portfolios")
    op.drop_table("experiment_portfolios")
    op.drop_index(op.f("ix_ai_tools_family"), table_name="ai_tools")
    op.drop_column("ai_tools", "family")
