"""Workflow engine: definitions, executions, step runs, history; customer notifications.

Revision ID: 0004_workflow_engine
Revises: 0003_banking_core
Create Date: 2026-10-27 23:19:48.920325+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_workflow_engine"
down_revision: str | None = "0003_banking_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


HISTORY_APPEND_ONLY = """
CREATE FUNCTION workflow_events_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'workflow_events is append-only: % is not permitted', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.create_table(
        "workflow_definitions",
        sa.Column("workflow_id", sa.String(length=20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_definitions")),
        sa.UniqueConstraint("workflow_id", "version", name="uq_workflow_definitions_id_version"),
    )
    op.create_table(
        "customer_notifications",
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(length=30), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("workflow_execution_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_customer_notifications_customer_id_customers"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_notifications")),
    )
    op.create_index(
        op.f("ix_customer_notifications_customer_id"),
        "customer_notifications",
        ["customer_id"],
        unique=False,
    )
    op.create_table(
        "workflow_executions",
        sa.Column("workflow_id", sa.String(length=20), nullable=False),
        sa.Column("workflow_version", sa.Integer(), nullable=False),
        sa.Column("definition_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("outcome", sa.String(length=50), nullable=True),
        sa.Column("current_steps", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("business_key", sa.String(length=100), nullable=True),
        sa.Column("initiated_by", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("step_counter", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('running', 'waiting', 'completed', 'failed', 'cancelled')",
            name=op.f("ck_workflow_executions_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["definition_id"],
            ["workflow_definitions.id"],
            name=op.f("fk_workflow_executions_definition_id_workflow_definitions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["initiated_by"],
            ["users.id"],
            name=op.f("fk_workflow_executions_initiated_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_executions")),
        sa.UniqueConstraint(
            "initiated_by", "idempotency_key", name="uq_workflow_executions_idempotency"
        ),
    )
    op.create_index(
        op.f("ix_workflow_executions_business_key"),
        "workflow_executions",
        ["business_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_executions_initiated_by"),
        "workflow_executions",
        ["initiated_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_executions_status"), "workflow_executions", ["status"], unique=False
    )
    op.create_index(
        "ix_workflow_executions_workflow_status",
        "workflow_executions",
        ["workflow_id", "status"],
        unique=False,
    )
    op.create_table(
        "workflow_step_runs",
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("step_id", sa.String(length=64), nullable=False),
        sa.Column("step_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("branch", sa.String(length=64), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("required_permissions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("not_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'waiting', 'completed', 'failed', 'cancelled')",
            name=op.f("ck_workflow_step_runs_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_workflow_step_runs_actor_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["workflow_executions.id"],
            name=op.f("fk_workflow_step_runs_execution_id_workflow_executions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_step_runs")),
        sa.UniqueConstraint("execution_id", "sequence", name="uq_workflow_step_runs_sequence"),
    )
    op.create_index(
        "ix_workflow_step_runs_due",
        "workflow_step_runs",
        ["status", "not_before"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        op.f("ix_workflow_step_runs_execution_id"),
        "workflow_step_runs",
        ["execution_id"],
        unique=False,
    )
    op.create_index(
        "ix_workflow_step_runs_waiting_due",
        "workflow_step_runs",
        ["due_at"],
        unique=False,
        postgresql_where=sa.text("status = 'waiting'"),
    )
    op.create_table(
        "workflow_events",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("step_run_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_workflow_events_actor_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["workflow_executions.id"],
            name=op.f("fk_workflow_events_execution_id_workflow_executions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["step_run_id"],
            ["workflow_step_runs.id"],
            name=op.f("fk_workflow_events_step_run_id_workflow_step_runs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_events")),
        sa.UniqueConstraint("seq", name=op.f("uq_workflow_events_seq")),
    )
    op.create_index(
        op.f("ix_workflow_events_execution_id"), "workflow_events", ["execution_id"], unique=False
    )

    op.execute(HISTORY_APPEND_ONLY)
    op.execute(
        "CREATE TRIGGER workflow_events_no_update_delete BEFORE UPDATE OR DELETE "
        "ON workflow_events FOR EACH ROW EXECUTE FUNCTION workflow_events_append_only()"
    )
    op.execute(
        "CREATE TRIGGER workflow_events_no_truncate BEFORE TRUNCATE ON workflow_events "
        "FOR EACH STATEMENT EXECUTE FUNCTION workflow_events_append_only()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER workflow_events_no_truncate ON workflow_events")
    op.execute("DROP TRIGGER workflow_events_no_update_delete ON workflow_events")
    op.execute("DROP FUNCTION workflow_events_append_only()")
    op.drop_index(op.f("ix_workflow_events_execution_id"), table_name="workflow_events")
    op.drop_table("workflow_events")
    op.drop_index(
        "ix_workflow_step_runs_waiting_due",
        table_name="workflow_step_runs",
        postgresql_where=sa.text("status = 'waiting'"),
    )
    op.drop_index(op.f("ix_workflow_step_runs_execution_id"), table_name="workflow_step_runs")
    op.drop_index(
        "ix_workflow_step_runs_due",
        table_name="workflow_step_runs",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_table("workflow_step_runs")
    op.drop_index("ix_workflow_executions_workflow_status", table_name="workflow_executions")
    op.drop_index(op.f("ix_workflow_executions_status"), table_name="workflow_executions")
    op.drop_index(op.f("ix_workflow_executions_initiated_by"), table_name="workflow_executions")
    op.drop_index(op.f("ix_workflow_executions_business_key"), table_name="workflow_executions")
    op.drop_table("workflow_executions")
    op.drop_index(
        op.f("ix_customer_notifications_customer_id"), table_name="customer_notifications"
    )
    op.drop_table("customer_notifications")
    op.drop_table("workflow_definitions")
