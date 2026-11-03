"""A simulation run's own outages

Phase 67 (roadmap Milestone E, step 5). `application_outages.simulation_run_id`: an outage a
scenario declares applies only to that run's executions, and goes with the run.

Revision ID: 0045_run_outages
Revises: 0044_app_outages
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0045_run_outages"
down_revision: str | None = "0044_app_outages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("application_outages", sa.Column("simulation_run_id", sa.Uuid(), nullable=True))
    op.create_index(
        op.f("ix_application_outages_simulation_run_id"),
        "application_outages",
        ["simulation_run_id"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("fk_application_outages_simulation_run_id_simulation_runs"),
        "application_outages",
        "simulation_runs",
        ["simulation_run_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_application_outages_simulation_run_id_simulation_runs"),
        "application_outages",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_application_outages_simulation_run_id"), table_name="application_outages"
    )
    op.drop_column("application_outages", "simulation_run_id")
