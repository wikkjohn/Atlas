"""Rate limits, sign-in lockout, the audit-log archive and data retention

Phase 85 (roadmap Milestone H, step 2).

- `rate_limit_counters`: fixed-window hit counters shared by every API process.
- `users.failed_logins` / `users.locked_until`: a sign-in lockout after repeated wrong
  passwords.
- `audit_archives`: archived audit events, a chain of SHA-256 digests (each archive names
  the previous one's).
- The audit log's append-only trigger now allows DELETE only while an archive is being
  written: inside a transaction that set `atlas.audit_archiving = 'on'` (the archive service
  does, after the file is written and checked). UPDATE and TRUNCATE stay refused.
- `retention_runs`: each application of the retention schedule and what it removed.

Revision ID: 0057_ratelimit_audit_retention
Revises: 0056_sessions_mfa_scopes
Create Date: 2026-11-05
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0057_ratelimit_audit_retention"
down_revision: str | None = "0056_sessions_mfa_scopes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ARCHIVING_FUNCTION = """
CREATE OR REPLACE FUNCTION audit_events_append_only() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' AND current_setting('atlas.audit_archiving', true) = 'on' THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'audit_events is append-only: % is not permitted', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;
"""

ORIGINAL_FUNCTION = """
CREATE OR REPLACE FUNCTION audit_events_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only: % is not permitted', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.create_table(
        "rate_limit_counters",
        sa.Column("bucket", sa.String(length=200), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("bucket", "window_start"),
    )
    op.create_index("ix_rate_limit_counters_window", "rate_limit_counters", ["window_start"])

    op.add_column(
        "users", sa.Column("failed_logins", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("users", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "audit_archives",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("archive_number", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("before", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("events", sa.Integer(), nullable=False),
        sa.Column("location", sa.String(length=300), nullable=False),
        sa.Column("bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("previous_sha256", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verification", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("archive_number", name=op.f("uq_audit_archives_archive_number")),
    )

    op.create_table(
        "retention_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_number", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("applied_by", sa.Uuid(), nullable=True),
        sa.Column(
            "applied_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("results", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["applied_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.execute(ARCHIVING_FUNCTION)

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
                "name": "retention-apply",
                "description": "Apply the data-retention schedule: delete expired sessions, "
                "sign-on requests, rate-limit windows and idempotency keys; archive audit "
                "events older than a year",
                "kind": "retention.apply",
                "payload": {},
                "interval_seconds": 86_400,
                "enabled": True,
                "next_run_at": datetime.now(UTC),
            }
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM jobs WHERE schedule_name = 'retention-apply'")
    op.execute("DELETE FROM job_schedules WHERE name = 'retention-apply'")
    op.execute(ORIGINAL_FUNCTION)
    op.drop_table("retention_runs")
    op.drop_table("audit_archives")
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_logins")
    op.drop_index("ix_rate_limit_counters_window", table_name="rate_limit_counters")
    op.drop_table("rate_limit_counters")
