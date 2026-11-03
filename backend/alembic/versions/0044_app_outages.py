"""Application outages: windows in which a simulated application is down or degraded

Phase 64 (roadmap Milestone E, step 2). `application_outages` records each outage
(`application_outage_number_seq`), open-ended while it has no end, with the incident it
opened.

Revision ID: 0044_app_outages
Revises: 0043_app_registry
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0044_app_outages"
down_revision: str | None = "0043_app_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEQUENCES = ("application_outage_number_seq",)


def upgrade() -> None:
    for name in SEQUENCES:
        op.execute(sa.schema.CreateSequence(sa.Sequence(name, start=1)))
    op.create_table(
        "application_outages",
        sa.Column("outage_number", sa.String(length=20), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("reason", sa.String(length=300), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("incident_id", sa.Uuid(), nullable=True),
        sa.Column("declared_by", sa.Uuid(), nullable=True),
        sa.Column("ended_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('down', 'degraded')", name=op.f("ck_application_outages_kind_valid")
        ),
        sa.CheckConstraint(
            "ends_at IS NULL OR ends_at > starts_at",
            name=op.f("ck_application_outages_window_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name=op.f("fk_application_outages_application_id_applications"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["declared_by"],
            ["users.id"],
            name=op.f("fk_application_outages_declared_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["ended_by"],
            ["users.id"],
            name=op.f("fk_application_outages_ended_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name=op.f("fk_application_outages_incident_id_incidents"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_application_outages")),
        sa.UniqueConstraint("outage_number", name=op.f("uq_application_outages_outage_number")),
    )
    op.create_index(
        op.f("ix_application_outages_application_id"),
        "application_outages",
        ["application_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_application_outages_ends_at"), "application_outages", ["ends_at"], unique=False
    )
    op.create_index(
        op.f("ix_application_outages_starts_at"), "application_outages", ["starts_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_application_outages_starts_at"), table_name="application_outages")
    op.drop_index(op.f("ix_application_outages_ends_at"), table_name="application_outages")
    op.drop_index(op.f("ix_application_outages_application_id"), table_name="application_outages")
    op.drop_table("application_outages")
    for name in SEQUENCES:
        op.execute(sa.schema.DropSequence(sa.Sequence(name)))
