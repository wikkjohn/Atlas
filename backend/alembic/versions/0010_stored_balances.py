"""Stored balances and reconciliation history

Revision ID: 0010_stored_balances
Revises: 0009_loan_servicing
Create Date: 2026-10-29 15:17:00.651630+00:00

Every ledger account's running debit and credit totals are kept in `ledger_balances` by a
trigger on `journal_lines`, in the same transaction as each posting. Journal lines are
immutable, so the totals are exact; reading a balance no longer scans every line. A guard
trigger refuses any other write to the table. Existing lines are backfilled.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010_stored_balances"
down_revision: str | None = "0009_loan_servicing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copy of BALANCE_SHARDS (8): the shard is the low three bits of a hash of the line.
FUNCTIONS = """
CREATE FUNCTION journal_lines_maintain_balance() RETURNS trigger AS $$
BEGIN
    INSERT INTO ledger_balances
        (ledger_account_id, shard, debit_total, credit_total, line_count, updated_at)
    VALUES (
        NEW.ledger_account_id,
        hashtext(NEW.id::text) & 7,
        CASE WHEN NEW.direction = 'debit' THEN NEW.amount ELSE 0 END,
        CASE WHEN NEW.direction = 'credit' THEN NEW.amount ELSE 0 END,
        1,
        now()
    )
    ON CONFLICT (ledger_account_id, shard) DO UPDATE SET
        debit_total = ledger_balances.debit_total + EXCLUDED.debit_total,
        credit_total = ledger_balances.credit_total + EXCLUDED.credit_total,
        line_count = ledger_balances.line_count + 1,
        updated_at = EXCLUDED.updated_at;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION ledger_balances_guard() RETURNS trigger AS $$
BEGIN
    -- Depth 1 is a direct statement; the balance trigger writes at depth 2.
    IF pg_trigger_depth() < 2 THEN
        RAISE EXCEPTION 'ledger_balances is maintained by journal line postings only';
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;
"""

TRIGGERS = [
    "CREATE TRIGGER journal_lines_maintain_balance AFTER INSERT ON journal_lines "
    "FOR EACH ROW EXECUTE FUNCTION journal_lines_maintain_balance()",
    "CREATE TRIGGER ledger_balances_guard BEFORE INSERT OR UPDATE OR DELETE ON ledger_balances "
    "FOR EACH ROW EXECUTE FUNCTION ledger_balances_guard()",
    "CREATE TRIGGER ledger_balances_no_truncate BEFORE TRUNCATE ON ledger_balances "
    "FOR EACH STATEMENT EXECUTE FUNCTION ledger_balances_guard()",
]

BACKFILL = """
INSERT INTO ledger_balances
    (ledger_account_id, shard, debit_total, credit_total, line_count, updated_at)
SELECT
    ledger_account_id,
    hashtext(id::text) & 7,
    COALESCE(SUM(amount) FILTER (WHERE direction = 'debit'), 0),
    COALESCE(SUM(amount) FILTER (WHERE direction = 'credit'), 0),
    COUNT(*),
    now()
FROM journal_lines
GROUP BY ledger_account_id, hashtext(id::text) & 7
"""


def upgrade() -> None:
    op.create_table(
        "ledger_balances",
        sa.Column("ledger_account_id", sa.Uuid(), nullable=False),
        sa.Column("shard", sa.SmallInteger(), nullable=False),
        sa.Column("debit_total", sa.Numeric(precision=38, scale=0), nullable=False),
        sa.Column("credit_total", sa.Numeric(precision=38, scale=0), nullable=False),
        sa.Column("line_count", sa.BigInteger(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "debit_total >= 0 AND credit_total >= 0",
            name=op.f("ck_ledger_balances_totals_non_negative"),
        ),
        sa.CheckConstraint("shard >= 0 AND shard < 8", name=op.f("ck_ledger_balances_shard_valid")),
        sa.ForeignKeyConstraint(
            ["ledger_account_id"],
            ["ledger_accounts.id"],
            name=op.f("fk_ledger_balances_ledger_account_id_ledger_accounts"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("ledger_account_id", "shard", name=op.f("pk_ledger_balances")),
    )
    op.create_table(
        "ledger_reconciliations",
        sa.Column("run_number", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entries_checked", sa.BigInteger(), nullable=False),
        sa.Column("lines_checked", sa.BigInteger(), nullable=False),
        sa.Column("duration_ms", sa.BigInteger(), nullable=False),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("run_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "mode IN ('full', 'incremental')", name=op.f("ck_ledger_reconciliations_mode_valid")
        ),
        sa.ForeignKeyConstraint(
            ["run_by"],
            ["users.id"],
            name=op.f("fk_ledger_reconciliations_run_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ledger_reconciliations")),
        sa.UniqueConstraint("run_number", name=op.f("uq_ledger_reconciliations_run_number")),
    )
    op.create_index(
        op.f("ix_ledger_reconciliations_created_at"),
        "ledger_reconciliations",
        ["created_at"],
        unique=False,
    )
    op.execute(FUNCTIONS)
    op.execute(BACKFILL)  # before the guard, which would refuse it
    for statement in TRIGGERS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TRIGGER ledger_balances_no_truncate ON ledger_balances")
    op.execute("DROP TRIGGER ledger_balances_guard ON ledger_balances")
    op.execute("DROP TRIGGER journal_lines_maintain_balance ON journal_lines")
    op.execute("DROP FUNCTION ledger_balances_guard()")
    op.execute("DROP FUNCTION journal_lines_maintain_balance()")
    op.drop_index(op.f("ix_ledger_reconciliations_created_at"), table_name="ledger_reconciliations")
    op.drop_table("ledger_reconciliations")
    op.drop_table("ledger_balances")
