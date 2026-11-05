"""AI guardrails: an auditable record of every tool call

Phase 79 (roadmap Milestone G, step 4). `ai_tool_invocations.record_hash` is a SHA-256 of
each invocation as it was written (the audit recomputes it); `transcript` holds what a
hosted model was sent and answered, word for word. Calls recorded before this migration
have no hash. Drift and bias checks read the existing records and need no tables.

Revision ID: 0053_ai_guardrails
Revises: 0052_experiment_portfolios
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0053_ai_guardrails"
down_revision: str | None = "0052_experiment_portfolios"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_tool_invocations",
        sa.Column("transcript", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "ai_tool_invocations", sa.Column("record_hash", sa.String(length=64), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("ai_tool_invocations", "record_hash")
    op.drop_column("ai_tool_invocations", "transcript")
