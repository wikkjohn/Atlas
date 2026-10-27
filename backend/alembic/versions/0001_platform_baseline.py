"""Platform baseline: system_properties table.

Revision ID: 0001_platform_baseline
Revises:
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_platform_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "system_properties",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_system_properties")),
    )
    # Record when this installation's schema was first created.
    op.execute(
        "INSERT INTO system_properties (key, value) "
        "VALUES ('platform.initialized_at', to_char(now() AT TIME ZONE 'UTC', "
        '\'YYYY-MM-DD"T"HH24:MI:SS"Z"\'))'
    )


def downgrade() -> None:
    op.drop_table("system_properties")
