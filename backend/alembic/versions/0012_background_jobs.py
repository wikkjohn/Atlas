"""Background jobs

A durable job queue (`jobs`) and recurring schedules (`job_schedules`), the scheduler's
service role and its user (who can never sign in), and the default schedules.

Revision ID: 0012_background_jobs
Revises: 0011_search_indexes
Create Date: 2026-10-29 16:45:57.197133+00:00
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012_background_jobs"
down_revision: str | None = "0011_search_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("job_number", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("kind", sa.String(length=60), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column(
            "run_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=200), nullable=True),
        sa.Column("locked_by", sa.String(length=100), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("schedule_name", sa.String(length=60), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "(status = 'running') = (locked_by IS NOT NULL)", name=op.f("ck_jobs_running_is_locked")
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name=op.f("ck_jobs_status_valid"),
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND max_attempts >= 1", name=op.f("ck_jobs_attempts_valid")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_jobs_created_by_users"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        sa.UniqueConstraint("job_number", name=op.f("uq_jobs_job_number")),
    )
    op.create_index(op.f("ix_jobs_created_at"), "jobs", ["created_at"], unique=False)
    op.create_index("ix_jobs_due", "jobs", ["status", "run_at", "priority"], unique=False)
    op.create_index(op.f("ix_jobs_kind"), "jobs", ["kind"], unique=False)
    op.create_index(
        "uq_jobs_active_dedupe_key",
        "jobs",
        ["dedupe_key"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running') AND dedupe_key IS NOT NULL"),
    )
    op.create_table(
        "job_schedules",
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("kind", sa.String(length=60), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_job_id", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("interval_seconds >= 60", name=op.f("ck_job_schedules_interval_valid")),
        sa.ForeignKeyConstraint(
            ["last_job_id"],
            ["jobs.id"],
            name=op.f("fk_job_schedules_last_job_id_jobs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_schedules")),
        sa.UniqueConstraint("name", name=op.f("uq_job_schedules_name")),
    )
    _seed()


def downgrade() -> None:
    op.execute(f"DELETE FROM users WHERE username = '{SCHEDULER_USER}'")
    op.execute(f"DELETE FROM roles WHERE code = '{SCHEDULER_ROLE[0]}'")
    op.drop_table("job_schedules")
    op.drop_index(
        "uq_jobs_active_dedupe_key",
        table_name="jobs",
        postgresql_where=sa.text("status IN ('queued', 'running') AND dedupe_key IS NOT NULL"),
    )
    op.drop_index(op.f("ix_jobs_kind"), table_name="jobs")
    op.drop_index("ix_jobs_due", table_name="jobs")
    op.drop_index(op.f("ix_jobs_created_at"), table_name="jobs")
    op.drop_table("jobs")


SCHEDULER_ROLE = (
    "system_scheduler",
    "System Scheduler",
    "System principal of the job scheduler: runs scheduled reconciliation and loan "
    "servicing. Never assigned to a person.",
)
SCHEDULER_USER = "atlas-scheduler"
# (name, description, kind, payload, interval in seconds, enabled)
SCHEDULES = [
    (
        "ledger-incremental-reconciliation",
        "Check what was posted since the last reconciliation",
        "ledger.reconcile",
        {"mode": "incremental"},
        15 * 60,
        True,
    ),
    (
        "ledger-full-reconciliation",
        "Check the whole ledger and every stored balance",
        "ledger.reconcile",
        {"mode": "full"},
        24 * 3600,
        True,
    ),
    (
        "workflow-timers",
        "Resume due workflow steps and apply timeouts",
        "workflows.run_due",
        {},
        60,
        True,
    ),
    (
        "loan-servicing",
        "Service the loan book up to today (moves the lending business date)",
        "lending.service_loans",
        {},
        24 * 3600,
        False,
    ),
]


def _seed() -> None:
    role_id = uuid.uuid4()
    code, name, description = SCHEDULER_ROLE
    op.bulk_insert(
        sa.table(
            "roles",
            sa.column("id", sa.Uuid()),
            sa.column("code", sa.String()),
            sa.column("name", sa.String()),
            sa.column("description", sa.Text()),
        ),
        [{"id": role_id, "code": code, "name": name, "description": description}],
    )
    op.bulk_insert(
        sa.table(
            "users",
            sa.column("id", sa.Uuid()),
            sa.column("username", sa.String()),
            sa.column("email", sa.String()),
            sa.column("display_name", sa.String()),
            sa.column("password_hash", sa.String()),
            sa.column("role_id", sa.Uuid()),
            sa.column("is_active", sa.Boolean()),
        ),
        [
            {
                "id": uuid.uuid4(),
                "username": SCHEDULER_USER,
                "email": "scheduler@system.atlasbank.example",
                "display_name": "ATLAS Scheduler (system)",
                "password_hash": "!unusable",
                "role_id": role_id,
                "is_active": True,
            }
        ],
    )
    now = datetime.now(UTC)
    op.bulk_insert(
        sa.table(
            "job_schedules",
            sa.column("id", sa.Uuid()),
            sa.column("name", sa.String()),
            sa.column("description", sa.String()),
            sa.column("kind", sa.String()),
            sa.column("payload", postgresql.JSONB()),
            sa.column("interval_seconds", sa.Integer()),
            sa.column("enabled", sa.Boolean()),
            sa.column("next_run_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "id": uuid.uuid4(),
                "name": name,
                "description": description,
                "kind": kind,
                "payload": payload,
                "interval_seconds": interval,
                "enabled": enabled,
                "next_run_at": now,
            }
            for name, description, kind, payload, interval, enabled in SCHEDULES
        ],
    )
