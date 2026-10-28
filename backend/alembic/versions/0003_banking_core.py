"""Banking core: customers, account requests, accounts and the double-entry ledger.

Revision ID: 0003_banking_core
Revises: 0002_enterprise_foundation

Besides the tables, this migration installs the database-level ledger guarantees:
- deferred constraint triggers that reject any committed journal entry that has fewer than
  two lines, does not balance, or uses a ledger account in another currency;
- immutability: journal lines can never be updated or deleted, lines cannot be added to an
  entry from an earlier transaction, and an entry may only change from posted to reversed.
Create Date: 2026-10-27 22:44:33.772984+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_banking_core"
down_revision: str | None = "0002_enterprise_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


LEDGER_FUNCTIONS = """
CREATE FUNCTION journal_entry_must_balance() RETURNS trigger AS $$
DECLARE
    entry_id uuid;
    line_count integer;
    debit_total numeric;
    credit_total numeric;
    foreign_lines integer;
BEGIN
    IF TG_TABLE_NAME = 'journal_lines' THEN
        entry_id := NEW.journal_entry_id;
    ELSE
        entry_id := NEW.id;
    END IF;

    SELECT count(*),
           coalesce(sum(amount) FILTER (WHERE direction = 'debit'), 0),
           coalesce(sum(amount) FILTER (WHERE direction = 'credit'), 0)
      INTO line_count, debit_total, credit_total
      FROM journal_lines WHERE journal_entry_id = entry_id;

    IF line_count < 2 THEN
        RAISE EXCEPTION 'journal entry % has % line(s); at least two are required',
            entry_id, line_count USING ERRCODE = 'check_violation';
    END IF;
    IF debit_total <> credit_total THEN
        RAISE EXCEPTION 'journal entry % is unbalanced: debits % <> credits %',
            entry_id, debit_total, credit_total USING ERRCODE = 'check_violation';
    END IF;

    SELECT count(*) INTO foreign_lines
      FROM journal_lines l
      JOIN ledger_accounts a ON a.id = l.ledger_account_id
      JOIN journal_entries e ON e.id = l.journal_entry_id
     WHERE l.journal_entry_id = entry_id AND a.currency <> e.currency;
    IF foreign_lines > 0 THEN
        RAISE EXCEPTION 'journal entry % has lines in another currency', entry_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION journal_lines_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'journal_lines are immutable: % is not permitted', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION journal_lines_same_transaction() RETURNS trigger AS $$
BEGIN
    -- now() is the transaction start time, as is the entry's posted_at default.
    IF (SELECT posted_at FROM journal_entries WHERE id = NEW.journal_entry_id) <> now() THEN
        RAISE EXCEPTION 'lines can only be added to an entry in the transaction that posts it'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION journal_entries_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP <> 'UPDATE' THEN
        RAISE EXCEPTION 'journal_entries cannot be deleted'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NOT (OLD.status = 'posted' AND NEW.status = 'reversed')
       OR (to_jsonb(OLD) - 'status') <> (to_jsonb(NEW) - 'status') THEN
        RAISE EXCEPTION 'journal entries are immutable except posted -> reversed'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

LEDGER_TRIGGERS = [
    "CREATE CONSTRAINT TRIGGER journal_lines_balanced AFTER INSERT ON journal_lines "
    "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION journal_entry_must_balance()",
    "CREATE CONSTRAINT TRIGGER journal_entries_balanced AFTER INSERT ON journal_entries "
    "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION journal_entry_must_balance()",
    "CREATE TRIGGER journal_lines_no_update_delete BEFORE UPDATE OR DELETE ON journal_lines "
    "FOR EACH ROW EXECUTE FUNCTION journal_lines_immutable()",
    "CREATE TRIGGER journal_lines_no_truncate BEFORE TRUNCATE ON journal_lines "
    "FOR EACH STATEMENT EXECUTE FUNCTION journal_lines_immutable()",
    "CREATE TRIGGER journal_lines_insert_with_entry BEFORE INSERT ON journal_lines "
    "FOR EACH ROW EXECUTE FUNCTION journal_lines_same_transaction()",
    "CREATE TRIGGER journal_entries_guard BEFORE UPDATE OR DELETE ON journal_entries "
    "FOR EACH ROW EXECUTE FUNCTION journal_entries_guard()",
    "CREATE TRIGGER journal_entries_no_truncate BEFORE TRUNCATE ON journal_entries "
    "FOR EACH STATEMENT EXECUTE FUNCTION journal_lines_immutable()",
]

SEQUENCES = ["customer_number_seq", "account_number_seq", "journal_entry_number_seq"]


def upgrade() -> None:
    for sequence in SEQUENCES:
        op.execute(f"CREATE SEQUENCE {sequence} START 1")
    op.create_table(
        "ledger_accounts",
        sa.Column("code", sa.String(length=60), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("account_type", sa.String(length=20), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "account_type IN ('asset', 'liability', 'equity', 'income', 'expense')",
            name=op.f("ck_ledger_accounts_account_type_valid"),
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name=op.f("ck_ledger_accounts_currency_format")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ledger_accounts")),
        sa.UniqueConstraint("code", name=op.f("uq_ledger_accounts_code")),
    )
    op.create_index(
        op.f("ix_ledger_accounts_currency"), "ledger_accounts", ["currency"], unique=False
    )
    op.create_table(
        "customers",
        sa.Column("customer_number", sa.String(length=20), nullable=False),
        sa.Column("customer_type", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("date_of_birth_or_incorporation", sa.Date(), nullable=False),
        sa.Column("country_id", sa.Uuid(), nullable=False),
        sa.Column("risk_rating", sa.String(length=20), nullable=False),
        sa.Column("kyc_status", sa.String(length=20), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "customer_type IN ('individual', 'business')",
            name=op.f("ck_customers_customer_type_valid"),
        ),
        sa.CheckConstraint(
            "kyc_status IN ('not_started', 'pending', 'verified', 'rejected')",
            name=op.f("ck_customers_kyc_status_valid"),
        ),
        sa.CheckConstraint(
            "risk_rating IN ('unrated', 'low', 'medium', 'high')",
            name=op.f("ck_customers_risk_rating_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["country_id"],
            ["countries.id"],
            name=op.f("fk_customers_country_id_countries"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customers")),
        sa.UniqueConstraint("customer_number", name=op.f("uq_customers_customer_number")),
    )
    op.create_index(op.f("ix_customers_country_id"), "customers", ["country_id"], unique=False)
    op.create_index(
        op.f("ix_customers_customer_type"), "customers", ["customer_type"], unique=False
    )
    op.create_index(op.f("ix_customers_kyc_status"), "customers", ["kyc_status"], unique=False)
    op.create_index(op.f("ix_customers_name"), "customers", ["name"], unique=False)
    op.create_index(op.f("ix_customers_risk_rating"), "customers", ["risk_rating"], unique=False)
    op.create_table(
        "accounts",
        sa.Column("account_number", sa.String(length=20), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("account_type", sa.String(length=30), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("ledger_account_id", sa.Uuid(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "(status = 'closed') = (closed_at IS NOT NULL)",
            name=op.f("ck_accounts_closed_has_date"),
        ),
        sa.CheckConstraint(
            "account_type IN ('current', 'savings', 'business_current')",
            name=op.f("ck_accounts_account_type_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('open', 'frozen', 'closed')", name=op.f("ck_accounts_status_valid")
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_accounts_customer_id_customers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["ledger_account_id"],
            ["ledger_accounts.id"],
            name=op.f("fk_accounts_ledger_account_id_ledger_accounts"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_accounts")),
        sa.UniqueConstraint("account_number", name=op.f("uq_accounts_account_number")),
        sa.UniqueConstraint("ledger_account_id", name=op.f("uq_accounts_ledger_account_id")),
    )
    op.create_index(op.f("ix_accounts_customer_id"), "accounts", ["customer_id"], unique=False)
    op.create_index(op.f("ix_accounts_status"), "accounts", ["status"], unique=False)
    op.create_index(
        "uq_accounts_one_live_per_type_currency",
        "accounts",
        ["customer_id", "account_type", "currency"],
        unique=True,
        postgresql_where=sa.text("status <> 'closed'"),
    )
    op.create_table(
        "account_requests",
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("account_type", sa.String(length=30), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.String(length=500), nullable=True),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'approved') = (account_id IS NOT NULL)",
            name=op.f("ck_account_requests_approved_has_account"),
        ),
        sa.CheckConstraint(
            "account_type IN ('current', 'savings', 'business_current')",
            name=op.f("ck_account_requests_account_type_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name=op.f("ck_account_requests_status_valid"),
        ),
        sa.CheckConstraint(
            "decided_by IS NULL OR decided_by <> requested_by",
            name=op.f("ck_account_requests_four_eyes"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_account_requests_account_id_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_account_requests_customer_id_customers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"],
            ["users.id"],
            name=op.f("fk_account_requests_decided_by_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["users.id"],
            name=op.f("fk_account_requests_requested_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_requests")),
        sa.UniqueConstraint("account_id", name=op.f("uq_account_requests_account_id")),
    )
    op.create_index(
        op.f("ix_account_requests_customer_id"), "account_requests", ["customer_id"], unique=False
    )
    op.create_index(
        op.f("ix_account_requests_status"), "account_requests", ["status"], unique=False
    )
    op.create_index(
        "uq_account_requests_one_pending",
        "account_requests",
        ["customer_id", "account_type", "currency"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_table(
        "journal_entries",
        sa.Column("entry_number", sa.String(length=20), nullable=False),
        sa.Column("idempotency_key", sa.String(length=300), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column(
            "posted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("posted_by", sa.Uuid(), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("reversal_of_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name=op.f("ck_journal_entries_currency_format")
        ),
        sa.CheckConstraint(
            "status IN ('posted', 'reversed')", name=op.f("ck_journal_entries_status_valid")
        ),
        sa.ForeignKeyConstraint(
            ["posted_by"],
            ["users.id"],
            name=op.f("fk_journal_entries_posted_by_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reversal_of_id"],
            ["journal_entries.id"],
            name=op.f("fk_journal_entries_reversal_of_id_journal_entries"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_journal_entries")),
        sa.UniqueConstraint("entry_number", name=op.f("uq_journal_entries_entry_number")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_journal_entries_idempotency_key")),
        sa.UniqueConstraint("reversal_of_id", name=op.f("uq_journal_entries_reversal_of_id")),
    )
    op.create_index(
        op.f("ix_journal_entries_posted_at"), "journal_entries", ["posted_at"], unique=False
    )
    op.create_index(op.f("ix_journal_entries_source"), "journal_entries", ["source"], unique=False)
    op.create_table(
        "journal_lines",
        sa.Column("journal_entry_id", sa.Uuid(), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("ledger_account_id", sa.Uuid(), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("memo", sa.String(length=200), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "direction IN ('debit', 'credit')", name=op.f("ck_journal_lines_direction_valid")
        ),
        sa.CheckConstraint(
            "amount > 0 AND amount <= 1000000000000000",
            name=op.f("ck_journal_lines_amount_positive_bounded"),
        ),
        sa.ForeignKeyConstraint(
            ["journal_entry_id"],
            ["journal_entries.id"],
            name=op.f("fk_journal_lines_journal_entry_id_journal_entries"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["ledger_account_id"],
            ["ledger_accounts.id"],
            name=op.f("fk_journal_lines_ledger_account_id_ledger_accounts"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_journal_lines")),
        sa.UniqueConstraint("journal_entry_id", "line_number", name="uq_journal_lines_entry_line"),
    )
    op.create_index(
        op.f("ix_journal_lines_journal_entry_id"),
        "journal_lines",
        ["journal_entry_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_journal_lines_ledger_account_id"),
        "journal_lines",
        ["ledger_account_id"],
        unique=False,
    )

    op.execute(LEDGER_FUNCTIONS)
    for statement in LEDGER_TRIGGERS:
        op.execute(statement)


def downgrade() -> None:
    for trigger, table in [
        ("journal_entries_no_truncate", "journal_entries"),
        ("journal_entries_guard", "journal_entries"),
        ("journal_lines_insert_with_entry", "journal_lines"),
        ("journal_lines_no_truncate", "journal_lines"),
        ("journal_lines_no_update_delete", "journal_lines"),
        ("journal_entries_balanced", "journal_entries"),
        ("journal_lines_balanced", "journal_lines"),
    ]:
        op.execute(f"DROP TRIGGER {trigger} ON {table}")
    for function in (
        "journal_entries_guard",
        "journal_lines_same_transaction",
        "journal_lines_immutable",
        "journal_entry_must_balance",
    ):
        op.execute(f"DROP FUNCTION {function}()")
    op.drop_index(op.f("ix_journal_lines_ledger_account_id"), table_name="journal_lines")
    op.drop_index(op.f("ix_journal_lines_journal_entry_id"), table_name="journal_lines")
    op.drop_table("journal_lines")
    op.drop_index(op.f("ix_journal_entries_source"), table_name="journal_entries")
    op.drop_index(op.f("ix_journal_entries_posted_at"), table_name="journal_entries")
    op.drop_table("journal_entries")
    op.drop_index(
        "uq_account_requests_one_pending",
        table_name="account_requests",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_index(op.f("ix_account_requests_status"), table_name="account_requests")
    op.drop_index(op.f("ix_account_requests_customer_id"), table_name="account_requests")
    op.drop_table("account_requests")
    op.drop_index(
        "uq_accounts_one_live_per_type_currency",
        table_name="accounts",
        postgresql_where=sa.text("status <> 'closed'"),
    )
    op.drop_index(op.f("ix_accounts_status"), table_name="accounts")
    op.drop_index(op.f("ix_accounts_customer_id"), table_name="accounts")
    op.drop_table("accounts")
    op.drop_index(op.f("ix_customers_risk_rating"), table_name="customers")
    op.drop_index(op.f("ix_customers_name"), table_name="customers")
    op.drop_index(op.f("ix_customers_kyc_status"), table_name="customers")
    op.drop_index(op.f("ix_customers_customer_type"), table_name="customers")
    op.drop_index(op.f("ix_customers_country_id"), table_name="customers")
    op.drop_table("customers")
    op.drop_index(op.f("ix_ledger_accounts_currency"), table_name="ledger_accounts")
    op.drop_table("ledger_accounts")
    for sequence in reversed(SEQUENCES):
        op.execute(f"DROP SEQUENCE {sequence}")
