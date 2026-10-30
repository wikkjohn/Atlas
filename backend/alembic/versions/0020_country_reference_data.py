"""Country reference data for 120 countries

Phase 23 (roadmap Milestone C, step 1). A `currencies` table (ISO 4217 code, name, minor
units) referenced by `countries.default_currency`, and reference columns on `countries`:
ISO alpha-3, calling code, weekend days, holiday rules (with the Easter computus and how
weekend holidays are observed), banking regulator, identity documents, address format and
notes. The data of version 2026.1 is loaded from `0020_reference_data.json` next to this
file (a frozen snapshot, so the migration stays reproducible): the five existing countries
get their reference fields, 115 more are added as `planned`. Later versions of the data are
applied with `python -m app.cli reference load`.

Revision ID: 0020_country_reference_data
Revises: 0019_catalogue_lifecycle
Create Date: 2026-10-30 17:20:00+00:00
"""

import json
import uuid
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0020_country_reference_data"
down_revision: str | None = "0019_catalogue_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SNAPSHOT = Path(__file__).with_name("0020_reference_data.json")
REFERENCE_COLUMNS = (
    "iso_alpha3",
    "calling_code",
    "weekend_days",
    "easter",
    "holiday_observance",
    "holiday_rules",
    "regulator",
    "identity_documents",
    "address_format",
    "reference_notes",
    "reference_version",
)
JSON_COLUMNS = {
    "holiday_rules",
    "regulator",
    "identity_documents",
    "address_format",
    "reference_notes",
}


def upgrade() -> None:
    snapshot = json.loads(SNAPSHOT.read_text())
    currencies = op.create_table(
        "currencies",
        sa.Column("code", sa.String(length=3), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("minor_units", sa.SmallInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("code ~ '^[A-Z]{3}$'", name=op.f("ck_currencies_code_format")),
        sa.CheckConstraint(
            "minor_units BETWEEN 0 AND 4", name=op.f("ck_currencies_minor_units_range")
        ),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_currencies")),
    )  # fmt: skip
    op.bulk_insert(currencies, snapshot["currencies"])
    # A currency an operator used that the snapshot does not know keeps two decimals.
    op.execute(
        "INSERT INTO currencies (code, name, minor_units) "
        "SELECT DISTINCT default_currency, default_currency, 2 FROM countries "
        "WHERE default_currency NOT IN (SELECT code FROM currencies)"
    )
    op.create_foreign_key(
        op.f("fk_countries_default_currency_currencies"),
        "countries",
        "currencies",
        ["default_currency"],
        ["code"],
    )

    op.add_column("countries", sa.Column("iso_alpha3", sa.String(length=3), nullable=True))
    op.add_column("countries", sa.Column("calling_code", sa.String(length=8), nullable=True))
    op.add_column(
        "countries",
        sa.Column(
            "weekend_days", postgresql.ARRAY(sa.SmallInteger()), nullable=False,
            server_default=sa.text("'{6,7}'"),
        ),
    )  # fmt: skip
    op.add_column(
        "countries",
        sa.Column("easter", sa.String(length=10), nullable=False, server_default="western"),
    )
    op.add_column(
        "countries",
        sa.Column(
            "holiday_observance", sa.String(length=20), nullable=False, server_default="none"
        ),
    )
    for name in ("holiday_rules", "identity_documents", "reference_notes"):
        op.add_column(
            "countries",
            sa.Column(
                name, postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                server_default=sa.text("'[]'"),
            ),
        )  # fmt: skip
    for name in ("regulator", "address_format"):
        op.add_column(
            "countries", sa.Column(name, postgresql.JSONB(astext_type=sa.Text()), nullable=True)
        )
    op.add_column("countries", sa.Column("reference_version", sa.String(length=20), nullable=True))
    op.create_unique_constraint(op.f("uq_countries_iso_alpha3"), "countries", ["iso_alpha3"])
    op.create_check_constraint(
        op.f("ck_countries_iso_alpha3_format"), "countries", "iso_alpha3 ~ '^[A-Z]{3}$'"
    )
    op.create_check_constraint(
        op.f("ck_countries_calling_code_format"), "countries", "calling_code ~ '^\\+[0-9]{1,4}$'"
    )
    op.create_check_constraint(
        op.f("ck_countries_weekend_days"),
        "countries",
        "weekend_days <@ ARRAY[1,2,3,4,5,6,7]::smallint[]",
    )
    op.create_check_constraint(
        op.f("ck_countries_easter_valid"), "countries", "easter IN ('western', 'orthodox')"
    )
    op.create_check_constraint(
        op.f("ck_countries_holiday_observance_valid"),
        "countries",
        "holiday_observance IN ('none', 'next_weekday', 'nearest_weekday', 'sunday_to_next')",
    )

    countries = sa.table(
        "countries",
        sa.column("id", sa.Uuid()),
        sa.column("iso_country_code", sa.String()),
        sa.column("country_name", sa.String()),
        sa.column("region", sa.String()),
        sa.column("default_currency", sa.String()),
        sa.column("default_timezone", sa.String()),
        sa.column("supported_languages", postgresql.ARRAY(sa.String())),
        sa.column("operational_status", sa.String()),
        sa.column("iso_alpha3", sa.String()),
        sa.column("calling_code", sa.String()),
        sa.column("weekend_days", postgresql.ARRAY(sa.SmallInteger())),
        sa.column("easter", sa.String()),
        sa.column("holiday_observance", sa.String()),
        *(sa.column(name, postgresql.JSONB()) for name in sorted(JSON_COLUMNS)),
        sa.column("reference_version", sa.String()),
    )
    bind = op.get_bind()
    existing = dict(
        bind.execute(sa.select(countries.c.iso_country_code, countries.c.country_name)).all()
    )
    names = set(existing.values())
    new_rows = []
    for row in snapshot["countries"]:
        code = row["iso_country_code"]
        if code in existing:
            bind.execute(
                countries.update()
                .where(countries.c.iso_country_code == code)
                .values({k: row[k] for k in REFERENCE_COLUMNS})
            )
        elif row["country_name"] not in names:
            new_rows.append({**row, "id": uuid.uuid4()})
    if new_rows:
        op.bulk_insert(countries, new_rows)


def downgrade() -> None:
    op.execute(
        "DELETE FROM countries WHERE operational_status = 'planned' "
        "AND reference_version IS NOT NULL "
        "AND id NOT IN (SELECT country_id FROM organizations WHERE country_id IS NOT NULL) "
        "AND id NOT IN (SELECT country_id FROM employees) "
        "AND id NOT IN (SELECT country_id FROM customers)"
    )
    for name in (
        "ck_countries_holiday_observance_valid",
        "ck_countries_easter_valid",
        "ck_countries_weekend_days",
        "ck_countries_calling_code_format",
        "ck_countries_iso_alpha3_format",
    ):
        op.drop_constraint(op.f(name), "countries", type_="check")
    op.drop_constraint(op.f("uq_countries_iso_alpha3"), "countries", type_="unique")
    for name in reversed(REFERENCE_COLUMNS):
        op.drop_column("countries", name)
    op.drop_constraint(
        op.f("fk_countries_default_currency_currencies"), "countries", type_="foreignkey"
    )
    op.drop_table("currencies")
