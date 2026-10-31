"""Mortgages: products, properties, valuations, offers; loans charged on a property

Phase 33 (roadmap Milestone D, step 5). `mortgage_products` holds the mortgage products
(version 1 loaded here); properties are registered for an applicant and valued (desktop
model or surveyor); a mortgage offer is requested, decided by someone else, accepted and
completed. A completed offer is an ordinary loan with purpose `mortgage`, a term of up to
35 years and `loans.property_id`: a property secures at most one live loan.

Revision ID: 0027_mortgages
Revises: 0026_cards
Create Date: 2026-10-31 11:10:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0027_mortgages"
down_revision: str | None = "0026_cards"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEQUENCES = ("property_number_seq", "valuation_number_seq", "mortgage_offer_number_seq")
PRODUCTS = [
    # code, name, max LTV (bps), rate (bps), max term (years), min and max loan (US dollars)
    ("home-75", "ATLAS Home 75", 7500, 449, 35, 25_000, 1_000_000),
    ("home-90", "ATLAS Home 90", 9000, 579, 35, 25_000, 750_000),
]
LIVE = "status IN ('pending', 'offered', 'accepted')"


def _users(table: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], ["users.id"], name=op.f(f"fk_{table}_{column}_users"), ondelete="RESTRICT"
    )


def upgrade() -> None:
    for name in SEQUENCES:
        op.execute(sa.schema.CreateSequence(sa.Sequence(name, start=1)))
    products = op.create_table(
        "mortgage_products",
        sa.Column("product_code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("max_ltv_bps", sa.Integer(), nullable=False),
        sa.Column("annual_rate_bps", sa.Integer(), nullable=False),
        sa.Column("max_term_years", sa.Integer(), nullable=False),
        sa.Column("min_loan_usd", sa.Integer(), nullable=False),
        sa.Column("max_loan_usd", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "max_ltv_bps BETWEEN 1000 AND 10000", name=op.f("ck_mortgage_products_ltv_range")
        ),
        sa.CheckConstraint(
            "annual_rate_bps BETWEEN 0 AND 3000", name=op.f("ck_mortgage_products_rate_range")
        ),
        sa.CheckConstraint(
            "max_term_years BETWEEN 5 AND 35", name=op.f("ck_mortgage_products_term_range")
        ),
        sa.CheckConstraint(
            "min_loan_usd > 0 AND max_loan_usd >= min_loan_usd",
            name=op.f("ck_mortgage_products_loan_range"),
        ),
        sa.PrimaryKeyConstraint("product_code", name=op.f("pk_mortgage_products")),
    )
    op.bulk_insert(
        products,
        [
            dict(
                zip(
                    (
                        "product_code",
                        "name",
                        "max_ltv_bps",
                        "annual_rate_bps",
                        "max_term_years",
                        "min_loan_usd",
                        "max_loan_usd",
                    ),
                    row,
                    strict=True,
                )
            )
            for row in PRODUCTS
        ],  # fmt: skip
    )
    op.create_table(
        "properties",
        sa.Column("property_number", sa.String(length=20), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("property_type", sa.String(length=10), nullable=False),
        sa.Column("address", sa.String(length=200), nullable=False),
        sa.Column("purchase_price", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "property_type IN ('house', 'flat')", name=op.f("ck_properties_type_valid")
        ),
        sa.CheckConstraint("purchase_price > 0", name=op.f("ck_properties_price_positive")),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_properties_customer_id_customers"),
            ondelete="RESTRICT",
        ),  # fmt: skip
        _users("properties", "created_by"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_properties")),
        sa.UniqueConstraint("property_number", name=op.f("uq_properties_property_number")),
    )
    op.create_index(op.f("ix_properties_customer_id"), "properties", ["customer_id"], unique=False)
    op.create_table(
        "property_valuations",
        sa.Column("valuation_number", sa.String(length=20), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("value", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("valued_on", sa.Date(), nullable=False),
        sa.Column("valued_by", sa.Uuid(), nullable=True),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "method IN ('desktop', 'surveyor')", name=op.f("ck_property_valuations_method_valid")
        ),
        sa.CheckConstraint("value > 0", name=op.f("ck_property_valuations_value_positive")),
        sa.CheckConstraint(
            "(method = 'desktop') = (valued_by IS NULL)",
            name=op.f("ck_property_valuations_surveyor_named"),
        ),
        sa.ForeignKeyConstraint(
            ["property_id"],
            ["properties.id"],
            name=op.f("fk_property_valuations_property_id_properties"),
            ondelete="RESTRICT",
        ),  # fmt: skip
        _users("property_valuations", "valued_by"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_property_valuations")),
        sa.UniqueConstraint(
            "valuation_number", name=op.f("uq_property_valuations_valuation_number")
        ),
    )
    op.create_index(
        op.f("ix_property_valuations_property_id"),
        "property_valuations",
        ["property_id"],
        unique=False,
    )
    op.create_table(
        "mortgage_offers",
        sa.Column("offer_number", sa.String(length=20), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("valuation_id", sa.Uuid(), nullable=False),
        sa.Column("product_code", sa.String(length=40), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("loan_amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("term_months", sa.Integer(), nullable=False),
        sa.Column("annual_rate_bps", sa.Integer(), nullable=False),
        sa.Column("monthly_payment", sa.BigInteger(), nullable=False),
        sa.Column("ltv_bps", sa.Integer(), nullable=False),
        sa.Column("declared_monthly_income", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by", sa.Uuid(), nullable=True),
        sa.Column("loan_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'offered', 'declined', 'accepted', 'completed', 'withdrawn')",
            name=op.f("ck_mortgage_offers_status_valid"),
        ),
        sa.CheckConstraint("loan_amount > 0", name=op.f("ck_mortgage_offers_amount_positive")),
        sa.CheckConstraint(
            "term_months BETWEEN 60 AND 420", name=op.f("ck_mortgage_offers_term_valid")
        ),
        sa.CheckConstraint(
            "decided_by IS NULL OR decided_by <> requested_by",
            name=op.f("ck_mortgage_offers_four_eyes"),
        ),
        sa.CheckConstraint(
            "completed_by IS NULL OR completed_by <> requested_by",
            name=op.f("ck_mortgage_offers_completion_four_eyes"),
        ),
        sa.CheckConstraint(
            "(status = 'completed') = (loan_id IS NOT NULL)",
            name=op.f("ck_mortgage_offers_completed_loan"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_mortgage_offers_account_id_accounts"),
            ondelete="RESTRICT",
        ),  # fmt: skip
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_mortgage_offers_customer_id_customers"),
            ondelete="RESTRICT",
        ),  # fmt: skip
        sa.ForeignKeyConstraint(
            ["loan_id"],
            ["loans.id"],
            name=op.f("fk_mortgage_offers_loan_id_loans"),
            ondelete="RESTRICT",
        ),  # fmt: skip
        sa.ForeignKeyConstraint(
            ["product_code"],
            ["mortgage_products.product_code"],
            name=op.f("fk_mortgage_offers_product_code_mortgage_products"),
            ondelete="RESTRICT",
        ),  # fmt: skip
        sa.ForeignKeyConstraint(
            ["property_id"],
            ["properties.id"],
            name=op.f("fk_mortgage_offers_property_id_properties"),
            ondelete="RESTRICT",
        ),  # fmt: skip
        sa.ForeignKeyConstraint(
            ["valuation_id"],
            ["property_valuations.id"],
            name=op.f("fk_mortgage_offers_valuation_id_property_valuations"),
            ondelete="RESTRICT",
        ),  # fmt: skip
        _users("mortgage_offers", "requested_by"),
        _users("mortgage_offers", "decided_by"),
        _users("mortgage_offers", "completed_by"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mortgage_offers")),
        sa.UniqueConstraint("offer_number", name=op.f("uq_mortgage_offers_offer_number")),
    )
    op.create_index(
        op.f("ix_mortgage_offers_customer_id"), "mortgage_offers", ["customer_id"], unique=False
    )
    op.create_index(
        op.f("ix_mortgage_offers_property_id"), "mortgage_offers", ["property_id"], unique=False
    )
    op.create_index(op.f("ix_mortgage_offers_status"), "mortgage_offers", ["status"], unique=False)
    op.create_index(
        "uq_mortgage_offers_live_property",
        "mortgage_offers",
        ["property_id"],
        unique=True,
        postgresql_where=sa.text(LIVE),
    )
    # Loans: a mortgage runs up to 35 years and is charged on its property.
    op.add_column("loans", sa.Column("property_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_loans_property_id_properties"), "loans", "properties", ["property_id"], ["id"],
        ondelete="RESTRICT",
    )  # fmt: skip
    op.create_index(
        "uq_loans_live_property",
        "loans",
        ["property_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND property_id IS NOT NULL"),
    )
    op.drop_constraint(op.f("ck_loans_term_valid"), "loans", type_="check")
    op.create_check_constraint(
        op.f("ck_loans_term_valid"),
        "loans",
        "term_months BETWEEN 6 AND 84 OR (purpose = 'mortgage' AND term_months BETWEEN 60 AND 420)",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_loans_term_valid"), "loans", type_="check")
    op.create_check_constraint(op.f("ck_loans_term_valid"), "loans", "term_months BETWEEN 6 AND 84")
    op.drop_index(
        "uq_loans_live_property",
        table_name="loans",
        postgresql_where=sa.text("status = 'active' AND property_id IS NOT NULL"),
    )
    op.drop_constraint(op.f("fk_loans_property_id_properties"), "loans", type_="foreignkey")
    op.drop_column("loans", "property_id")
    op.drop_index(
        "uq_mortgage_offers_live_property",
        table_name="mortgage_offers",
        postgresql_where=sa.text(LIVE),
    )
    op.drop_index(op.f("ix_mortgage_offers_status"), table_name="mortgage_offers")
    op.drop_index(op.f("ix_mortgage_offers_property_id"), table_name="mortgage_offers")
    op.drop_index(op.f("ix_mortgage_offers_customer_id"), table_name="mortgage_offers")
    op.drop_table("mortgage_offers")
    op.drop_index(op.f("ix_property_valuations_property_id"), table_name="property_valuations")
    op.drop_table("property_valuations")
    op.drop_index(op.f("ix_properties_customer_id"), table_name="properties")
    op.drop_table("properties")
    op.drop_table("mortgage_products")
    for name in reversed(SEQUENCES):
        op.execute(sa.schema.DropSequence(sa.Sequence(name)))
