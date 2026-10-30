"""Country rules engine: versioned per-country rules; payment limits and value dates

Phase 25 (roadmap Milestone C, step 3). `country_rules` holds versions of each country's
rules (KYC minimum age and documents, sanctions lists, payment cut-off, high-value
threshold and single-payment limit). Version 1 of every country's rules is loaded from
`0022_country_rules.json` (a frozen snapshot of `app.modules.rules.defaults`). Payments gain
the high-value threshold and value date they were created with.

Revision ID: 0022_country_rules
Revises: 0021_foreign_exchange
Create Date: 2026-10-30 18:27:46.368281+00:00
"""

import json
import uuid
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

SNAPSHOT = Path(__file__).with_name("0022_country_rules.json")

revision: str = "0022_country_rules"
down_revision: str | None = "0021_foreign_exchange"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "country_rules",
        sa.Column("country_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("note", sa.String(length=300), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("version >= 1", name=op.f("ck_country_rules_version_positive")),
        sa.ForeignKeyConstraint(
            ["country_id"],
            ["countries.id"],
            name=op.f("fk_country_rules_country_id_countries"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_country_rules_created_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_country_rules")),
        sa.UniqueConstraint("country_id", "version", name="uq_country_rules_country_version"),
    )
    op.create_index(
        op.f("ix_country_rules_country_id"), "country_rules", ["country_id"], unique=False
    )
    op.add_column("payments", sa.Column("high_value_threshold", sa.BigInteger(), nullable=True))
    op.add_column("payments", sa.Column("value_date", sa.Date(), nullable=True))
    snapshot = json.loads(SNAPSHOT.read_text())
    countries = dict(
        op.get_bind().execute(sa.text("SELECT iso_country_code, id FROM countries")).tuples().all()
    )
    table = sa.table(
        "country_rules",
        sa.column("id", sa.Uuid()),
        sa.column("country_id", sa.Uuid()),
        sa.column("version", sa.Integer()),
        sa.column("effective_from", sa.Date()),
        sa.column("rules", postgresql.JSONB()),
        sa.column("note", sa.String()),
    )
    rows = [
        {
            "id": uuid.uuid4(),
            "country_id": countries[code],
            "version": 1,
            "effective_from": date.fromisoformat(snapshot["effective_from"]),
            "rules": rules,
            "note": "Default rules from the reference data",
        }
        for code, rules in sorted(snapshot["rules"].items())
        if code in countries
    ]
    if rows:
        op.bulk_insert(table, rows)


def downgrade() -> None:
    op.drop_column("payments", "value_date")
    op.drop_column("payments", "high_value_threshold")
    op.drop_index(op.f("ix_country_rules_country_id"), table_name="country_rules")
    op.drop_table("country_rules")
