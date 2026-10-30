"""Business calendars: dated lunar holidays; schedules and scenarios on business days

Phase 26 (roadmap Milestone C, step 4). Reference data 2026.2 adds dated holidays of lunar
calendars (Eid, Lunar New Year, Diwali, Vesak, Jewish holidays …) for 2025–2030 to the
countries that observe them; this migration applies it from `0023_reference_data.json` (a
frozen snapshot), refreshing only the holiday rules, notes and data version. Job schedules
gain `business_calendar`: a country whose business days they run on.

Revision ID: 0023_business_calendars
Revises: 0022_country_rules
Create Date: 2026-10-30 19:00:00+00:00
"""

import json
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0023_business_calendars"
down_revision: str | None = "0022_country_rules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SNAPSHOT = Path(__file__).with_name("0023_reference_data.json")
PREVIOUS = Path(__file__).with_name("0020_reference_data.json")


def _apply(snapshot_path: Path) -> None:
    snapshot = json.loads(snapshot_path.read_text())
    countries = sa.table(
        "countries",
        sa.column("iso_country_code", sa.String()),
        sa.column("holiday_rules", postgresql.JSONB()),
        sa.column("reference_notes", postgresql.JSONB()),
        sa.column("reference_version", sa.String()),
    )
    bind = op.get_bind()
    for row in snapshot["countries"]:
        bind.execute(
            countries.update()
            .where(countries.c.iso_country_code == row["iso_country_code"])
            .values(
                holiday_rules=row["holiday_rules"],
                reference_notes=row["reference_notes"],
                reference_version=row["reference_version"],
            )
        )


def upgrade() -> None:
    _apply(SNAPSHOT)
    op.add_column(
        "job_schedules", sa.Column("business_calendar", sa.String(length=2), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("job_schedules", "business_calendar")
    _apply(PREVIOUS)
