"""Generated country subsidiaries: organizations record the blueprint they came from

Phase 27 (roadmap Milestone C, step 5). Launching a country builds its subsidiary from a
versioned blueprint (`app/modules/organizations/blueprint.py`); the organizations it
creates record that blueprint in `generated_from`. Nothing is generated here: existing
organizations were built by hand or by the demo seed and keep a null value.

Revision ID: 0024_generated_subsidiaries
Revises: 0023_business_calendars
Create Date: 2026-10-30 20:30:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0024_generated_subsidiaries"
down_revision: str | None = "0023_business_calendars"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("generated_from", sa.String(40), nullable=True))


def downgrade() -> None:
    op.drop_column("organizations", "generated_from")
