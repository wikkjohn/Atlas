"""Task routing: named assignment, delegation and escalation

Phase 71 (roadmap Milestone F, step 3). `workflow_step_runs` gains the person a task is
assigned to, when, and whom it was assigned to before a delegation or an escalation handed
it on (all NULL for shared-queue tasks and for every task from before). `task_delegations`
holds out-of-office periods: while one runs, new tasks for the person go to their delegate.

Revision ID: 0047_task_routing
Revises: 0046_workforce
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0047_task_routing"
down_revision: str | None = "0046_workforce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_delegations",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("delegate_id", sa.Uuid(), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("delegate_id <> user_id", name=op.f("ck_task_delegations_not_self")),
        sa.CheckConstraint("ends_on >= starts_on", name=op.f("ck_task_delegations_dates_ordered")),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_task_delegations_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["delegate_id"],
            ["users.id"],
            name=op.f("fk_task_delegations_delegate_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_task_delegations_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_delegations")),
    )
    op.create_index(
        "ix_task_delegations_user",
        "task_delegations",
        ["user_id", "starts_on", "ends_on"],
        unique=False,
    )
    op.add_column("workflow_step_runs", sa.Column("assignee_id", sa.Uuid(), nullable=True))
    op.add_column(
        "workflow_step_runs", sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("workflow_step_runs", sa.Column("delegated_from_id", sa.Uuid(), nullable=True))
    op.create_index(
        "ix_workflow_step_runs_assignee_waiting",
        "workflow_step_runs",
        ["assignee_id"],
        unique=False,
        postgresql_where=sa.text("status = 'waiting' AND assignee_id IS NOT NULL"),
    )
    op.create_foreign_key(
        op.f("fk_workflow_step_runs_delegated_from_id_users"),
        "workflow_step_runs",
        "users",
        ["delegated_from_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_workflow_step_runs_assignee_id_users"),
        "workflow_step_runs",
        "users",
        ["assignee_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_workflow_step_runs_assignee_id_users"), "workflow_step_runs", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_workflow_step_runs_delegated_from_id_users"),
        "workflow_step_runs",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_workflow_step_runs_assignee_waiting",
        table_name="workflow_step_runs",
        postgresql_where=sa.text("status = 'waiting' AND assignee_id IS NOT NULL"),
    )
    op.drop_column("workflow_step_runs", "delegated_from_id")
    op.drop_column("workflow_step_runs", "assigned_at")
    op.drop_column("workflow_step_runs", "assignee_id")
    op.drop_index("ix_task_delegations_user", table_name="task_delegations")
    op.drop_table("task_delegations")
