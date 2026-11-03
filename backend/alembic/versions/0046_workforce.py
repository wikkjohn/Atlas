"""The workforce: grades, skills and the generator run on employees

Phase 69 (roadmap Milestone F, step 1). `employees` gains a grade from 1 to 10 (checked;
NULL for employees from before), skills as a JSON list, and the generator run that made
each generated employee.

Revision ID: 0046_workforce
Revises: 0045_run_outages
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0046_workforce"
down_revision: str | None = "0045_run_outages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("employees", sa.Column("grade", sa.SmallInteger(), nullable=True))
    op.add_column(
        "employees",
        sa.Column(
            "skills",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("employees", sa.Column("generated_from", sa.String(length=40), nullable=True))
    op.create_index(
        op.f("ix_employees_generated_from"), "employees", ["generated_from"], unique=False
    )
    op.create_index(op.f("ix_employees_grade"), "employees", ["grade"], unique=False)
    op.create_check_constraint(
        op.f("ck_employees_grade_valid"), "employees", "grade IS NULL OR grade BETWEEN 1 AND 10"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_employees_grade_valid"), "employees", type_="check")
    op.drop_index(op.f("ix_employees_grade"), table_name="employees")
    op.drop_index(op.f("ix_employees_generated_from"), table_name="employees")
    op.drop_column("employees", "generated_from")
    op.drop_column("employees", "skills")
    op.drop_column("employees", "grade")
