"""Foreign exchange: rates, conversions, revaluation; cross-currency payments

Phase 24 (roadmap Milestone C, step 2). `fx_rates` holds published daily rates (units per
US dollar), `fx_deals` every conversion with its two journal entries (one per currency,
through the currency position accounts), `fx_revaluations` each revaluation of the open
positions. Payments gain the payee's currency, the amount it received and the deal. The
`fx-daily` schedule publishes the day's rates and revalues the positions.

Revision ID: 0021_foreign_exchange
Revises: 0020_country_reference_data
Create Date: 2026-10-30 17:50:30.463604+00:00
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0021_foreign_exchange"
down_revision: str | None = "0020_country_reference_data"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.schema.CreateSequence(sa.Sequence("fx_deal_number_seq", start=1)))
    op.create_table(
        "fx_rates",
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("units_per_usd", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("units_per_usd > 0", name=op.f("ck_fx_rates_rate_positive")),
        sa.ForeignKeyConstraint(
            ["currency"], ["currencies.code"], name=op.f("fk_fx_rates_currency_currencies")
        ),
        sa.PrimaryKeyConstraint("currency", "rate_date", name=op.f("pk_fx_rates")),
    )
    op.create_index(op.f("ix_fx_rates_rate_date"), "fx_rates", ["rate_date"], unique=False)
    op.create_table(
        "fx_deals",
        sa.Column("deal_number", sa.String(length=20), nullable=False),
        sa.Column("idempotency_key", sa.String(length=300), nullable=False),
        sa.Column("purpose", sa.String(length=30), nullable=False),
        sa.Column("reference", sa.String(length=140), nullable=False),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("sell_currency", sa.String(length=3), nullable=False),
        sa.Column("sell_amount", sa.BigInteger(), nullable=False),
        sa.Column("buy_currency", sa.String(length=3), nullable=False),
        sa.Column("buy_amount", sa.BigInteger(), nullable=False),
        sa.Column("mid_rate", sa.Numeric(precision=30, scale=12), nullable=False),
        sa.Column("customer_rate", sa.Numeric(precision=30, scale=12), nullable=False),
        sa.Column("margin_bps", sa.SmallInteger(), nullable=False),
        sa.Column("base_amount", sa.BigInteger(), nullable=False),
        sa.Column("sell_entry_id", sa.Uuid(), nullable=False),
        sa.Column("buy_entry_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("margin_bps BETWEEN 0 AND 1000", name=op.f("ck_fx_deals_margin_range")),
        sa.CheckConstraint(
            "sell_amount > 0 AND buy_amount > 0", name=op.f("ck_fx_deals_amounts_positive")
        ),
        sa.CheckConstraint(
            "sell_currency <> buy_currency", name=op.f("ck_fx_deals_distinct_currencies")
        ),
        sa.ForeignKeyConstraint(
            ["buy_entry_id"],
            ["journal_entries.id"],
            name=op.f("fk_fx_deals_buy_entry_id_journal_entries"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_fx_deals_created_by_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sell_entry_id"],
            ["journal_entries.id"],
            name=op.f("fk_fx_deals_sell_entry_id_journal_entries"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fx_deals")),
        sa.UniqueConstraint("buy_entry_id", name=op.f("uq_fx_deals_buy_entry_id")),
        sa.UniqueConstraint("deal_number", name=op.f("uq_fx_deals_deal_number")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_fx_deals_idempotency_key")),
        sa.UniqueConstraint("sell_entry_id", name=op.f("uq_fx_deals_sell_entry_id")),
    )
    op.create_index(op.f("ix_fx_deals_buy_currency"), "fx_deals", ["buy_currency"], unique=False)
    op.create_index(op.f("ix_fx_deals_created_at"), "fx_deals", ["created_at"], unique=False)
    op.create_index(op.f("ix_fx_deals_purpose"), "fx_deals", ["purpose"], unique=False)
    op.create_index(op.f("ix_fx_deals_sell_currency"), "fx_deals", ["sell_currency"], unique=False)
    op.create_table(
        "fx_revaluations",
        sa.Column("run_number", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("positions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("total_value", sa.BigInteger(), nullable=False),
        sa.Column("previously_booked", sa.BigInteger(), nullable=False),
        sa.Column("posted", sa.BigInteger(), nullable=False),
        sa.Column("journal_entry_id", sa.Uuid(), nullable=True),
        sa.Column("run_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["journal_entry_id"],
            ["journal_entries.id"],
            name=op.f("fk_fx_revaluations_journal_entry_id_journal_entries"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_by"],
            ["users.id"],
            name=op.f("fk_fx_revaluations_run_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fx_revaluations")),
        sa.UniqueConstraint("journal_entry_id", name=op.f("uq_fx_revaluations_journal_entry_id")),
        sa.UniqueConstraint("run_number", name=op.f("uq_fx_revaluations_run_number")),
    )
    op.create_index(op.f("ix_fx_revaluations_as_of"), "fx_revaluations", ["as_of"], unique=False)
    op.create_index(
        op.f("ix_fx_revaluations_created_at"), "fx_revaluations", ["created_at"], unique=False
    )
    op.add_column("payments", sa.Column("creditor_currency", sa.String(length=3), nullable=True))
    op.add_column("payments", sa.Column("creditor_amount", sa.BigInteger(), nullable=True))
    op.add_column("payments", sa.Column("fx_deal_id", sa.Uuid(), nullable=True))
    op.create_unique_constraint(op.f("uq_payments_fx_deal_id"), "payments", ["fx_deal_id"])
    op.create_foreign_key(
        op.f("fk_payments_fx_deal_id_fx_deals"),
        "payments",
        "fx_deals",
        ["fx_deal_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_payments_released_fx_has_deal"),
        "payments",
        "status <> 'released' OR creditor_currency IS NULL OR fx_deal_id IS NOT NULL",
    )
    schedules = sa.table(
        "job_schedules",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("description", sa.String()),
        sa.column("kind", sa.String()),
        sa.column("payload", postgresql.JSONB()),
        sa.column("interval_seconds", sa.Integer()),
        sa.column("enabled", sa.Boolean()),
        sa.column("next_run_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        schedules,
        [
            {
                "id": uuid.uuid4(),
                "name": "fx-daily",
                "description": "Publish the day's exchange rates and revalue currency positions",
                "kind": "fx.daily",
                "payload": {},
                "interval_seconds": 24 * 3600,
                "enabled": True,
                "next_run_at": datetime.now(UTC),
            }
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM job_schedules WHERE name = 'fx-daily'")
    op.drop_constraint(op.f("ck_payments_released_fx_has_deal"), "payments", type_="check")
    op.drop_constraint(op.f("fk_payments_fx_deal_id_fx_deals"), "payments", type_="foreignkey")
    op.drop_constraint(op.f("uq_payments_fx_deal_id"), "payments", type_="unique")
    op.drop_column("payments", "fx_deal_id")
    op.drop_column("payments", "creditor_amount")
    op.drop_column("payments", "creditor_currency")
    op.drop_index(op.f("ix_fx_revaluations_created_at"), table_name="fx_revaluations")
    op.drop_index(op.f("ix_fx_revaluations_as_of"), table_name="fx_revaluations")
    op.drop_table("fx_revaluations")
    op.drop_index(op.f("ix_fx_deals_sell_currency"), table_name="fx_deals")
    op.drop_index(op.f("ix_fx_deals_purpose"), table_name="fx_deals")
    op.drop_index(op.f("ix_fx_deals_created_at"), table_name="fx_deals")
    op.drop_index(op.f("ix_fx_deals_buy_currency"), table_name="fx_deals")
    op.drop_table("fx_deals")
    op.drop_index(op.f("ix_fx_rates_rate_date"), table_name="fx_rates")
    op.drop_table("fx_rates")
    op.execute(sa.schema.DropSequence(sa.Sequence("fx_deal_number_seq")))
