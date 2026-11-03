"""The customer generator: segments and the generator run on customers

Phase 72 (roadmap Milestone F, step 4). `customers` gains the segment the generator drew
(mass, student, affluent, senior, private or sme; checked; NULL for customers onboarded one
at a time) and the generator run that made the customer.

Revision ID: 0048_customer_generator
Revises: 0047_task_routing
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0048_customer_generator"
down_revision: str | None = "0047_task_routing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("segment", sa.String(length=20), nullable=True))
    op.add_column("customers", sa.Column("generated_from", sa.String(length=40), nullable=True))
    op.create_index(
        op.f("ix_customers_generated_from"), "customers", ["generated_from"], unique=False
    )
    op.create_index(op.f("ix_customers_segment"), "customers", ["segment"], unique=False)

    op.create_check_constraint(
        op.f("ck_customers_segment_valid"),
        "customers",
        "segment IS NULL OR segment IN ('mass', 'student', 'affluent', 'senior', 'private', 'sme')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_customers_segment_valid"), "customers", type_="check")
    op.drop_index(op.f("ix_customers_segment"), table_name="customers")
    op.drop_index(op.f("ix_customers_generated_from"), table_name="customers")
    op.drop_column("customers", "generated_from")
    op.drop_column("customers", "segment")
