"""Sign-in sessions, multi-factor authentication, simulated SSO and scoped access

Phase 84 (roadmap Milestone H, step 1). `auth_sessions` holds one row per sign-in: how it
was made (password or SSO), whether its second factor is satisfied, when it was last used,
and when and why it was revoked; every access token names its session, so revoking the
session ends the token. `users` gains a TOTP factor (secret, enrolment time, last used time
step, hashed one-time recovery codes). `sso_requests` holds the state and nonce of each
sign-in sent to the simulated identity provider, used at most once. `user_scopes` limits a
user to countries and departments.

Revision ID: 0056_sessions_mfa_scopes
Revises: 0055_reviewer_calibrations
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0056_sessions_mfa_scopes"
down_revision: str | None = "0055_reviewer_calibrations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("method", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("mfa", sa.String(length=20), nullable=False),
        sa.Column("failed_mfa_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(length=40), nullable=True),
        sa.CheckConstraint("method IN ('password', 'sso')", name="method"),
        sa.CheckConstraint(
            "mfa IN ('not_required', 'pending', 'verified', 'enrolment_required')", name="mfa"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_auth_sessions_user_active",
        "auth_sessions",
        ["user_id"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    op.add_column("users", sa.Column("mfa_secret", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("mfa_pending_secret", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("mfa_enabled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("mfa_last_step", sa.BigInteger(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "mfa_recovery_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )

    op.create_table(
        "sso_requests",
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("nonce", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("state"),
    )

    op.create_table(
        "user_scopes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("value", sa.String(length=200), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("kind IN ('country', 'department')", name="kind"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "kind", "value", name="uq_user_scopes"),
    )


def downgrade() -> None:
    op.drop_table("user_scopes")
    op.drop_table("sso_requests")
    for column in (
        "mfa_recovery_codes", "mfa_last_step", "mfa_enabled_at", "mfa_pending_secret",
        "mfa_secret",
    ):  # fmt: skip
        op.drop_column("users", column)
    op.drop_index("ix_auth_sessions_user_active", table_name="auth_sessions")
    op.drop_table("auth_sessions")
