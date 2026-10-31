"""Retail banking: products, overdrafts, standing orders, month end and statements

Phase 29 (roadmap Milestone D, step 1). `retail_products` holds the terms of each account
type (interest on credit and overdrawn balances, monthly fee, largest arranged overdraft),
version 1 loaded here. Accounts gain `overdraft_limit` (0 for every existing account).
Standing orders pay on their dates; month end posts interest and fees and issues
statements. Two schedules run them, both off until an operator enables them.

Revision ID: 0025_retail_banking
Revises: 0024_generated_subsidiaries
Create Date: 2026-10-30 22:10:13.756318+00:00
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0025_retail_banking"
down_revision: str | None = "0024_generated_subsidiaries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PRODUCTS = [
    # account type, name, credit rate, overdraft rate (bps a year), fee (US cents a month),
    # largest arranged overdraft (US dollars)
    ("current", "Everyday Current Account", 0, 1990, 500, 2500),
    ("savings", "Instant Access Savings", 250, 0, 0, 0),
    ("business_current", "Business Current Account", 0, 1490, 1500, 25000),
]
SCHEDULES = [
    ("retail-standing-orders", "Pay the standing orders due today", "retail.standing_orders"),
    ("retail-month-end", "Post interest and fees and issue statements for the last month",
     "retail.month_end"),
]  # fmt: skip


def upgrade() -> None:
    op.execute(sa.schema.CreateSequence(sa.Sequence("statement_number_seq", start=1)))
    op.execute(sa.schema.CreateSequence(sa.Sequence("standing_order_number_seq", start=1)))
    op.create_table(
        "account_statements",
        sa.Column("statement_number", sa.String(length=20), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("opening_balance", sa.BigInteger(), nullable=False),
        sa.Column("closing_balance", sa.BigInteger(), nullable=False),
        sa.Column("total_credits", sa.BigInteger(), nullable=False),
        sa.Column("total_debits", sa.BigInteger(), nullable=False),
        sa.Column("lines", sa.Integer(), nullable=False),
        sa.Column("overdraft_limit", sa.BigInteger(), nullable=False),
        sa.Column(
            "issued_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("issued_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "period_end >= period_start", name=op.f("ck_account_statements_period_ordered")
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_account_statements_account_id_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["issued_by"],
            ["users.id"],
            name=op.f("fk_account_statements_issued_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_statements")),
        sa.UniqueConstraint("account_id", "period_start", name="uq_account_statements_period"),
        sa.UniqueConstraint(
            "statement_number", name=op.f("uq_account_statements_statement_number")
        ),
    )
    op.create_index(
        op.f("ix_account_statements_account_id"), "account_statements", ["account_id"], unique=False
    )
    op.create_table(
        "retail_month_ends",
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("accounts", sa.Integer(), nullable=False),
        sa.Column("statements", sa.Integer(), nullable=False),
        sa.Column("entries", sa.Integer(), nullable=False),
        sa.Column("totals", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_retail_month_ends_created_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_retail_month_ends")),
        sa.UniqueConstraint("period_start", name="uq_retail_month_ends_period"),
    )
    op.create_table(
        "retail_products",
        sa.Column("account_type", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("credit_rate_bps", sa.Integer(), nullable=False),
        sa.Column("overdraft_rate_bps", sa.Integer(), nullable=False),
        sa.Column("monthly_fee_usd_cents", sa.Integer(), nullable=False),
        sa.Column("max_overdraft_usd", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "credit_rate_bps BETWEEN 0 AND 2000", name=op.f("ck_retail_products_credit_rate_range")
        ),
        sa.CheckConstraint(
            "max_overdraft_usd BETWEEN 0 AND 1000000",
            name=op.f("ck_retail_products_overdraft_range"),
        ),
        sa.CheckConstraint(
            "monthly_fee_usd_cents BETWEEN 0 AND 100000", name=op.f("ck_retail_products_fee_range")
        ),
        sa.CheckConstraint(
            "overdraft_rate_bps BETWEEN 0 AND 5000",
            name=op.f("ck_retail_products_overdraft_rate_range"),
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_retail_products_updated_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("account_type", name=op.f("pk_retail_products")),
    )
    op.create_table(
        "standing_orders",
        sa.Column("order_number", sa.String(length=20), nullable=False),
        sa.Column("debtor_account_id", sa.Uuid(), nullable=False),
        sa.Column("creditor_account_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("frequency", sa.String(length=10), nullable=False),
        sa.Column("day_of_month", sa.Integer(), nullable=False),
        sa.Column("next_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("reference", sa.String(length=140), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=300), nullable=True),
        sa.Column("payments_made", sa.Integer(), nullable=False),
        sa.Column("last_payment_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "frequency IN ('weekly', 'monthly')", name=op.f("ck_standing_orders_frequency_valid")
        ),
        sa.CheckConstraint(
            "status IN ('active', 'cancelled', 'ended', 'failed')",
            name=op.f("ck_standing_orders_status_valid"),
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_standing_orders_amount_positive")),
        sa.CheckConstraint(
            "debtor_account_id <> creditor_account_id",
            name=op.f("ck_standing_orders_distinct_accounts"),
        ),
        sa.CheckConstraint("failures >= 0", name=op.f("ck_standing_orders_failures_non_negative")),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_standing_orders_created_by_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["creditor_account_id"],
            ["accounts.id"],
            name=op.f("fk_standing_orders_creditor_account_id_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["debtor_account_id"],
            ["accounts.id"],
            name=op.f("fk_standing_orders_debtor_account_id_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["last_payment_id"],
            ["payments.id"],
            name=op.f("fk_standing_orders_last_payment_id_payments"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_standing_orders")),
        sa.UniqueConstraint("order_number", name=op.f("uq_standing_orders_order_number")),
    )
    op.create_index(
        op.f("ix_standing_orders_debtor_account_id"),
        "standing_orders",
        ["debtor_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_standing_orders_next_date"), "standing_orders", ["next_date"], unique=False
    )
    op.create_index(op.f("ix_standing_orders_status"), "standing_orders", ["status"], unique=False)
    op.add_column(
        "accounts",
        sa.Column("overdraft_limit", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        op.f("ck_accounts_overdraft_non_negative"), "accounts", "overdraft_limit >= 0"
    )
    products = sa.table(
        "retail_products",
        sa.column("account_type", sa.String()),
        sa.column("name", sa.String()),
        sa.column("credit_rate_bps", sa.Integer()),
        sa.column("overdraft_rate_bps", sa.Integer()),
        sa.column("monthly_fee_usd_cents", sa.Integer()),
        sa.column("max_overdraft_usd", sa.Integer()),
    )
    op.bulk_insert(products, [
        {'account_type': t, 'name': n, 'credit_rate_bps': c, 'overdraft_rate_bps': o,
         'monthly_fee_usd_cents': f, 'max_overdraft_usd': m}
        for t, n, c, o, f, m in PRODUCTS
    ])  # fmt: skip
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
    op.bulk_insert(schedules, [
        {'id': uuid.uuid4(), 'name': name, 'description': description, 'kind': kind,
         'payload': {}, 'interval_seconds': 24 * 3600, 'enabled': False,
         'next_run_at': datetime.now(UTC)}
        for name, description, kind in SCHEDULES
    ])  # fmt: skip


def downgrade() -> None:
    op.execute(
        "DELETE FROM job_schedules WHERE name IN ('retail-standing-orders', 'retail-month-end')"
    )
    op.drop_constraint(op.f("ck_accounts_overdraft_non_negative"), "accounts", type_="check")
    op.drop_column("accounts", "overdraft_limit")
    op.drop_index(op.f("ix_standing_orders_status"), table_name="standing_orders")
    op.drop_index(op.f("ix_standing_orders_next_date"), table_name="standing_orders")
    op.drop_index(op.f("ix_standing_orders_debtor_account_id"), table_name="standing_orders")
    op.drop_table("standing_orders")
    op.drop_table("retail_products")
    op.drop_table("retail_month_ends")
    op.drop_index(op.f("ix_account_statements_account_id"), table_name="account_statements")
    op.drop_table("account_statements")
    op.execute(sa.schema.DropSequence(sa.Sequence("standing_order_number_seq")))
    op.execute(sa.schema.DropSequence(sa.Sequence("statement_number_seq")))
