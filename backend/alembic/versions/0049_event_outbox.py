"""The event outbox, and Information Security's access grants

Phase 74 (roadmap Milestone F, step 6). `domain_events` holds what one department publishes
for the others (append-only, numbered), and `event_deliveries` one row per event and
subscriber: pending, delivered, failed (retried with back-off) or dead (out of attempts).
Both are written in the publisher's transaction. `access_grants` is Information Security's
record of systems access, requested when HR hires and revoked when an employee leaves. The
`events-dispatch` schedule runs the dispatcher every minute.

Revision ID: 0049_event_outbox
Revises: 0048_customer_generator
Create Date: 2026-11-03
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0049_event_outbox"
down_revision: str | None = "0048_customer_generator"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.schema.CreateSequence(sa.Sequence("access_grant_number_seq", start=1)))
    op.create_table(
        "domain_events",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("topic", sa.String(length=80), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("publisher", sa.String(length=40), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_domain_events_actor_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_domain_events")),
        sa.UniqueConstraint("seq", name=op.f("uq_domain_events_seq")),
    )
    op.create_index(
        "ix_domain_events_topic_key", "domain_events", ["topic", "key", "seq"], unique=False
    )
    op.create_table(
        "access_grants",
        sa.Column("grant_number", sa.String(length=20), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("profile", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_event_id", sa.Uuid(), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("granted_by", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(length=200), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status <> 'granted' OR granted_at IS NOT NULL",
            name=op.f("ck_access_grants_granted_dated"),
        ),
        sa.CheckConstraint(
            "status <> 'revoked' OR revoked_at IS NOT NULL",
            name=op.f("ck_access_grants_revoked_dated"),
        ),
        sa.CheckConstraint(
            "status IN ('requested', 'granted', 'revoked')",
            name=op.f("ck_access_grants_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            name=op.f("fk_access_grants_employee_id_employees"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"],
            ["users.id"],
            name=op.f("fk_access_grants_granted_by_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_event_id"],
            ["domain_events.id"],
            name=op.f("fk_access_grants_source_event_id_domain_events"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_access_grants")),
        sa.UniqueConstraint("grant_number", name=op.f("uq_access_grants_grant_number")),
        sa.UniqueConstraint("source_event_id", name=op.f("uq_access_grants_source_event_id")),
    )
    op.create_index(
        op.f("ix_access_grants_employee_id"), "access_grants", ["employee_id"], unique=False
    )
    op.create_index(op.f("ix_access_grants_status"), "access_grants", ["status"], unique=False)
    op.create_index(
        "uq_access_grants_live",
        "access_grants",
        ["employee_id", "profile"],
        unique=True,
        postgresql_where=sa.text("status <> 'revoked'"),
    )
    op.create_table(
        "event_deliveries",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("subscriber", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'delivered', 'failed', 'dead')",
            name=op.f("ck_event_deliveries_status_valid"),
        ),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_event_deliveries_attempts_non_negative")),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["domain_events.id"],
            name=op.f("fk_event_deliveries_event_id_domain_events"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_deliveries")),
        sa.UniqueConstraint("event_id", "subscriber", name="uq_event_deliveries_event_subscriber"),
    )
    op.create_index(
        "ix_event_deliveries_due",
        "event_deliveries",
        ["next_attempt_at"],
        unique=False,
        postgresql_where=sa.text("status IN ('pending', 'failed')"),
    )
    op.create_index(
        "ix_event_deliveries_subscriber_status",
        "event_deliveries",
        ["subscriber", "status"],
        unique=False,
    )

    schedules = sa.table(
        "job_schedules",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("description", sa.String()),
        sa.column("kind", sa.String()),
        sa.column("payload", postgresql.JSONB()),
        sa.column("interval_seconds", sa.Integer()),
        sa.column("enabled", sa.Boolean()),
        sa.column("next_run_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        schedules,
        [
            {
                "id": uuid.uuid4(),
                "name": "events-dispatch",
                "description": "Deliver due outbox events to their subscribers, with retries",
                "kind": "events.dispatch",
                "payload": {},
                "interval_seconds": 60,
                "enabled": True,
                "next_run_at": datetime.now(UTC),
            }
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM job_schedules WHERE name = 'events-dispatch'")
    op.execute("DELETE FROM jobs WHERE schedule_name = 'events-dispatch'")
    op.drop_index("ix_event_deliveries_subscriber_status", table_name="event_deliveries")
    op.drop_index(
        "ix_event_deliveries_due",
        table_name="event_deliveries",
        postgresql_where=sa.text("status IN ('pending', 'failed')"),
    )
    op.drop_table("event_deliveries")
    op.drop_index(
        "uq_access_grants_live",
        table_name="access_grants",
        postgresql_where=sa.text("status <> 'revoked'"),
    )
    op.drop_index(op.f("ix_access_grants_status"), table_name="access_grants")
    op.drop_index(op.f("ix_access_grants_employee_id"), table_name="access_grants")
    op.drop_table("access_grants")
    op.drop_index("ix_domain_events_topic_key", table_name="domain_events")
    op.drop_table("domain_events")
    op.execute(sa.schema.DropSequence(sa.Sequence("access_grant_number_seq")))
