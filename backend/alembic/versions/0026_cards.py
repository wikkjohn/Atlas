"""Cards: debit card products, cards, authorisations, disputes and chargebacks

Phase 31 (roadmap Milestone D, step 3). `card_products` holds the debit products (version 1
loaded here); cards are issued against an account; the synthetic merchant terminal's
authorisations are recorded, approved or declined with their fraud score; disputes end in a
chargeback (refund through the ledger) or a rejection, decided by someone other than the
person who opened them.

Revision ID: 0026_cards
Revises: 0025_retail_banking
Create Date: 2026-10-31 01:59:35.665970+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0026_cards"
down_revision: str | None = "0025_retail_banking"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PRODUCTS = [
    # code, name, daily limit (US dollars), validity (years)
    ("debit-standard", "ATLAS Debit", 1500, 4),
    ("debit-premium", "ATLAS Debit Premium", 5000, 4),
]


def upgrade() -> None:
    for name in ("card_number_seq", "card_authorization_seq", "card_dispute_seq"):
        op.execute(sa.schema.CreateSequence(sa.Sequence(name, start=1)))
    op.create_table(
        "card_products",
        sa.Column("product_code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("daily_limit_usd", sa.Integer(), nullable=False),
        sa.Column("validity_years", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "daily_limit_usd BETWEEN 1 AND 100000", name=op.f("ck_card_products_daily_limit_range")
        ),
        sa.CheckConstraint(
            "validity_years BETWEEN 1 AND 10", name=op.f("ck_card_products_validity_range")
        ),
        sa.PrimaryKeyConstraint("product_code", name=op.f("pk_card_products")),
    )
    op.create_table(
        "cards",
        sa.Column("card_number", sa.String(length=19), nullable=False),
        sa.Column("product_code", sa.String(length=40), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("daily_limit", sa.BigInteger(), nullable=False),
        sa.Column("expires_on", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("blocked_reason", sa.String(length=40), nullable=True),
        sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issued_by", sa.Uuid(), nullable=True),
        sa.Column(
            "issued_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "(status = 'blocked') = (blocked_reason IS NOT NULL)",
            name=op.f("ck_cards_block_reason"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'blocked', 'cancelled')", name=op.f("ck_cards_status_valid")
        ),
        sa.CheckConstraint("daily_limit > 0", name=op.f("ck_cards_daily_limit_positive")),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_cards_account_id_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_cards_customer_id_customers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["issued_by"], ["users.id"], name=op.f("fk_cards_issued_by_users"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["product_code"],
            ["card_products.product_code"],
            name=op.f("fk_cards_product_code_card_products"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cards")),
        sa.UniqueConstraint("card_number", name=op.f("uq_cards_card_number")),
    )
    op.create_index(op.f("ix_cards_account_id"), "cards", ["account_id"], unique=False)
    op.create_index(op.f("ix_cards_customer_id"), "cards", ["customer_id"], unique=False)
    op.create_index(op.f("ix_cards_status"), "cards", ["status"], unique=False)
    op.create_table(
        "card_authorizations",
        sa.Column("auth_code", sa.String(length=20), nullable=False),
        sa.Column("card_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_name", sa.String(length=100), nullable=False),
        sa.Column("merchant_category", sa.String(length=4), nullable=False),
        sa.Column("merchant_country", sa.String(length=2), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("decline_reason", sa.String(length=40), nullable=True),
        sa.Column("fraud_score", sa.Integer(), nullable=False),
        sa.Column("fraud_signals", sa.String(length=300), nullable=False),
        sa.Column("journal_entry_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "(status = 'approved') = (journal_entry_id IS NOT NULL)",
            name=op.f("ck_card_authorizations_approved_has_entry"),
        ),
        sa.CheckConstraint(
            "status IN ('approved', 'declined')", name=op.f("ck_card_authorizations_status_valid")
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_card_authorizations_amount_positive")),
        sa.ForeignKeyConstraint(
            ["card_id"],
            ["cards.id"],
            name=op.f("fk_card_authorizations_card_id_cards"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["journal_entry_id"],
            ["journal_entries.id"],
            name=op.f("fk_card_authorizations_journal_entry_id_journal_entries"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_card_authorizations")),
        sa.UniqueConstraint("auth_code", name=op.f("uq_card_authorizations_auth_code")),
    )
    op.create_index(
        "ix_card_authorizations_card_created",
        "card_authorizations",
        ["card_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_card_authorizations_status"), "card_authorizations", ["status"], unique=False
    )
    op.create_table(
        "card_disputes",
        sa.Column("dispute_number", sa.String(length=20), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("opened_by", sa.Uuid(), nullable=True),
        sa.Column(
            "opened_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refund_entry_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "(status = 'refunded') = (refund_entry_id IS NOT NULL)",
            name=op.f("ck_card_disputes_refund_has_entry"),
        ),
        sa.CheckConstraint(
            "reason IN ('not_recognised', 'not_received', 'duplicate', 'wrong_amount')",
            name=op.f("ck_card_disputes_reason_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('open', 'refunded', 'rejected')", name=op.f("ck_card_disputes_status_valid")
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_card_disputes_amount_positive")),
        sa.CheckConstraint(
            "decided_by IS NULL OR decided_by <> opened_by", name=op.f("ck_card_disputes_four_eyes")
        ),
        sa.ForeignKeyConstraint(
            ["authorization_id"],
            ["card_authorizations.id"],
            name=op.f("fk_card_disputes_authorization_id_card_authorizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"],
            ["users.id"],
            name=op.f("fk_card_disputes_decided_by_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["opened_by"],
            ["users.id"],
            name=op.f("fk_card_disputes_opened_by_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["refund_entry_id"],
            ["journal_entries.id"],
            name=op.f("fk_card_disputes_refund_entry_id_journal_entries"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_card_disputes")),
        sa.UniqueConstraint("dispute_number", name=op.f("uq_card_disputes_dispute_number")),
    )
    op.create_index(op.f("ix_card_disputes_status"), "card_disputes", ["status"], unique=False)
    op.create_index(
        "uq_card_disputes_live_authorization",
        "card_disputes",
        ["authorization_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'rejected'"),
    )
    products = sa.table(
        "card_products",
        sa.column("product_code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("daily_limit_usd", sa.Integer()),
        sa.column("validity_years", sa.Integer()),
    )
    op.bulk_insert(products, [
        {'product_code': c, 'name': n, 'daily_limit_usd': d, 'validity_years': v}
        for c, n, d, v in PRODUCTS
    ])  # fmt: skip


def downgrade() -> None:
    op.drop_index(
        "uq_card_disputes_live_authorization",
        table_name="card_disputes",
        postgresql_where=sa.text("status <> 'rejected'"),
    )
    op.drop_index(op.f("ix_card_disputes_status"), table_name="card_disputes")
    op.drop_table("card_disputes")
    op.drop_index(op.f("ix_card_authorizations_status"), table_name="card_authorizations")
    op.drop_index("ix_card_authorizations_card_created", table_name="card_authorizations")
    op.drop_table("card_authorizations")
    op.drop_index(op.f("ix_cards_status"), table_name="cards")
    op.drop_index(op.f("ix_cards_customer_id"), table_name="cards")
    op.drop_index(op.f("ix_cards_account_id"), table_name="cards")
    op.drop_table("cards")
    op.drop_table("card_products")
    for name in ("card_dispute_seq", "card_authorization_seq", "card_number_seq"):
        op.execute(sa.schema.DropSequence(sa.Sequence(name)))
