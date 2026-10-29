"""Search and sort indexes

Measured at one million customers (Phase 13): substring searches (`ILIKE '%text%'`) read
whole tables and the account and request lists sorted them. GIN trigram indexes (pg_trgm,
a trusted extension the database owner may create) serve the searches; two-column btree
indexes serve each list's order.

Revision ID: 0011_search_indexes
Revises: 0010_stored_balances
Create Date: 2026-10-29 16:25:21.459328+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011_search_indexes"
down_revision: str | None = "0010_stored_balances"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_index(
        "ix_account_requests_created_at_id", "account_requests", ["created_at", "id"], unique=False
    )
    op.create_index(
        "ix_accounts_account_number_trgm",
        "accounts",
        ["account_number"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"account_number": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_accounts_opened_at_number", "accounts", ["opened_at", "account_number"], unique=False
    )
    op.create_index(
        "ix_customers_customer_number_trgm",
        "customers",
        ["customer_number"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"customer_number": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_customers_name_trgm",
        "customers",
        ["name"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_ledger_accounts_code_trgm",
        "ledger_accounts",
        ["code"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"code": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_ledger_accounts_name_trgm",
        "ledger_accounts",
        ["name"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_loans_disbursed_at_number", "loans", ["disbursed_at", "loan_number"], unique=False
    )
    op.create_index(
        "ix_loans_loan_number_trgm",
        "loans",
        ["loan_number"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"loan_number": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_payments_created_at_number", "payments", ["created_at", "payment_number"], unique=False
    )
    op.create_index(
        "ix_payments_payment_number_trgm",
        "payments",
        ["payment_number"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"payment_number": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_payments_reference_trgm",
        "payments",
        ["reference"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"reference": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index(
        "ix_payments_reference_trgm",
        table_name="payments",
        postgresql_using="gin",
        postgresql_ops={"reference": "gin_trgm_ops"},
    )
    op.drop_index(
        "ix_payments_payment_number_trgm",
        table_name="payments",
        postgresql_using="gin",
        postgresql_ops={"payment_number": "gin_trgm_ops"},
    )
    op.drop_index("ix_payments_created_at_number", table_name="payments")
    op.drop_index(
        "ix_loans_loan_number_trgm",
        table_name="loans",
        postgresql_using="gin",
        postgresql_ops={"loan_number": "gin_trgm_ops"},
    )
    op.drop_index("ix_loans_disbursed_at_number", table_name="loans")
    op.drop_index(
        "ix_ledger_accounts_name_trgm",
        table_name="ledger_accounts",
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.drop_index(
        "ix_ledger_accounts_code_trgm",
        table_name="ledger_accounts",
        postgresql_using="gin",
        postgresql_ops={"code": "gin_trgm_ops"},
    )
    op.drop_index(
        "ix_customers_name_trgm",
        table_name="customers",
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.drop_index(
        "ix_customers_customer_number_trgm",
        table_name="customers",
        postgresql_using="gin",
        postgresql_ops={"customer_number": "gin_trgm_ops"},
    )
    op.drop_index("ix_accounts_opened_at_number", table_name="accounts")
    op.drop_index(
        "ix_accounts_account_number_trgm",
        table_name="accounts",
        postgresql_using="gin",
        postgresql_ops={"account_number": "gin_trgm_ops"},
    )
    op.drop_index("ix_account_requests_created_at_id", table_name="account_requests")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
