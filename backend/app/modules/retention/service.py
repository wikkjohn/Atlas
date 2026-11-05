"""The data-retention schedule (Phase 85).

Each class of stored data has a purpose, a retention period and what happens after it:

- `delete`: removed by `apply` (and the daily `retention.apply` job).
- `archive`: moved out of the live database but kept (the audit-log archive; simulation
  history has its own job).
- `keep`: never removed by the platform. Financial records are kept for the regulatory
  period after the relationship ends, and the bank is synthetic, so nothing reaches it.
- `review`: a person decides; the review reports how much is old.

`review()` reports, per class, how many rows exist and how many are past their period.
`apply()` removes or archives what is due and records the run in `retention_runs`.
The schedule is code, versioned with the platform, and documented in
`docs/data-retention.md`.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Uuid, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.config import get_settings
from app.core.audit import record_audit_event
from app.core.database import Base


class RetentionRun(Base):
    __tablename__ = "retention_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_number: Mapped[int] = mapped_column(BigInteger, Identity(always=True), nullable=False)
    applied_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    results: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


@dataclass(frozen=True)
class DataClass:
    id: str
    name: str
    tables: tuple[str, ...]
    purpose: str
    retention: str  # as stated to people
    days: int | None  # None: no period the platform applies
    action: str  # delete, archive, keep, review
    total_sql: str
    due_sql: str | None = None  # rows past the period; :cutoff is now - days
    delete_sql: str | None = None  # for `delete` classes
    applied_by: str | None = None  # where an `archive` class is applied


SCHEDULE: tuple[DataClass, ...] = (
    DataClass(
        "auth_sessions",
        "Sign-in sessions",
        ("auth_sessions",),
        "Who signed in, how and from where; ends tokens when revoked",
        "90 days after the session ended",
        90,
        "delete",
        "SELECT count(*) FROM auth_sessions",
        "SELECT count(*) FROM auth_sessions WHERE coalesce(revoked_at, expires_at) < :cutoff",
        "DELETE FROM auth_sessions WHERE coalesce(revoked_at, expires_at) < :cutoff",
    ),
    DataClass(
        "sso_requests",
        "Single sign-on requests",
        ("sso_requests",),
        "The state and nonce of a sign-in at the identity provider, used once",
        "1 day",
        1,
        "delete",
        "SELECT count(*) FROM sso_requests",
        "SELECT count(*) FROM sso_requests WHERE created_at < :cutoff",
        "DELETE FROM sso_requests WHERE created_at < :cutoff",
    ),
    DataClass(
        "rate_limit_counters",
        "Rate-limit counters",
        ("rate_limit_counters",),
        "Requests counted per window to enforce rate limits",
        "1 day",
        1,
        "delete",
        "SELECT count(*) FROM rate_limit_counters",
        "SELECT count(*) FROM rate_limit_counters WHERE window_start < :cutoff",
        "DELETE FROM rate_limit_counters WHERE window_start < :cutoff",
    ),
    DataClass(
        "idempotency_keys",
        "Idempotency keys",
        ("idempotency_keys",),
        "Replays a retried request instead of acting twice",
        "30 days",
        30,
        "delete",
        "SELECT count(*) FROM idempotency_keys",
        "SELECT count(*) FROM idempotency_keys WHERE created_at < :cutoff",
        "DELETE FROM idempotency_keys WHERE created_at < :cutoff",
    ),
    DataClass(
        "audit_events",
        "Audit log",
        ("audit_events",),
        "Who changed what, when; append-only",
        "1 year online, then the audit-log archive (kept)",
        365,
        "archive",
        "SELECT count(*) FROM audit_events",
        "SELECT count(*) FROM audit_events WHERE timestamp < :cutoff",
        applied_by="the audit-log archive",
    ),
    DataClass(
        "simulation_history",
        "Simulation workflow history",
        ("workflow_executions_simulation", "workflow_step_runs", "workflow_events"),
        "The case-level history of simulation runs",
        "30 days, then compressed archive files (kept, restorable)",
        30,
        "archive",
        "SELECT count(*) FROM simulation_runs",
        "SELECT count(*) FROM simulation_runs WHERE history_state = 'present' "
        "AND status IN ('completed', 'failed') AND created_at < :cutoff",
        applied_by="the simulation.archive_old_history job",
    ),
    DataClass(
        "jobs",
        "Background jobs",
        ("jobs",),
        "What ran in the background, with results and errors",
        "180 days after finishing: reviewed",
        180,
        "review",
        "SELECT count(*) FROM jobs",
        "SELECT count(*) FROM jobs WHERE status IN ('succeeded', 'failed', 'cancelled') "
        "AND created_at < :cutoff",
    ),
    DataClass(
        "ai_tool_invocations",
        "AI tool calls and stored prompts",
        ("ai_tool_invocations",),
        "Each AI tool call: inputs, outputs, hashes and stored prompts (Phase 79)",
        "1 year: reviewed (evidence for experiments)",
        365,
        "review",
        "SELECT count(*) FROM ai_tool_invocations",
        "SELECT count(*) FROM ai_tool_invocations WHERE created_at < :cutoff",
    ),
    DataClass(
        "customers",
        "Customers",
        ("customers",),
        "Synthetic customers and their KYC record",
        "Kept: at least 10 years after the relationship ends",
        None,
        "keep",
        "SELECT count(*) FROM customers",
    ),
    DataClass(
        "accounts_and_ledger",
        "Accounts and the ledger",
        ("accounts", "journal_entries", "journal_lines"),
        "Balances and every posting; the books of the bank",
        "Kept: at least 10 years (accounting and banking records)",
        None,
        "keep",
        "SELECT count(*) FROM journal_entries",
    ),
)


def _cutoff(item: DataClass, now: datetime) -> datetime | None:
    if item.days is None:
        return None
    cutoff = now - timedelta(days=item.days)
    if item.id == "audit_events":
        # Never inside the configured minimum online period, which may be longer than the
        # schedule's year: the archive would refuse the cut-off and roll the whole run back,
        # deletions included (PR #76 review).
        cutoff = min(cutoff, now - timedelta(days=get_settings().audit_min_online_days))
    return cutoff


def review(db: Session, now: datetime | None = None) -> dict[str, Any]:
    """How much of each class exists and how much is past its period."""
    now = now or datetime.now(UTC)
    rows = []
    for item in SCHEDULE:
        cutoff = _cutoff(item, now)
        total = db.execute(text(item.total_sql)).scalar_one()
        due = (
            db.execute(text(item.due_sql), {"cutoff": cutoff}).scalar_one()
            if item.due_sql and cutoff
            else 0
        )
        rows.append({
            "id": item.id, "name": item.name, "tables": list(item.tables),
            "purpose": item.purpose, "retention": item.retention, "days": item.days,
            "action": item.action, "rows": total, "due": due,
            "cutoff": cutoff.isoformat() if cutoff else None, "applied_by": item.applied_by,
        })  # fmt: skip
    last = db.execute(
        select(RetentionRun).order_by(RetentionRun.run_number.desc()).limit(1)
    ).scalar_one_or_none()
    return {
        "as_of": now.isoformat(),
        "classes": rows,
        "due_total": sum(r["due"] for r in rows if r["action"] in ("delete", "archive")),
        "last_run": {
            "run_number": last.run_number,
            "applied_at": last.applied_at.isoformat(),
            "results": last.results,
        }
        if last
        else None,  # fmt: skip
    }


def apply(
    db: Session, actor_id: uuid.UUID | None, *, now: datetime | None = None,
    archive_audit: Callable[[Session, datetime, uuid.UUID | None], Any] | None = None,
) -> RetentionRun:  # fmt: skip
    """Delete what is past its period and archive the audit log's old events."""
    from app.modules.audit import archive

    now = now or datetime.now(UTC)
    results: dict[str, Any] = {}
    for item in SCHEDULE:
        cutoff = _cutoff(item, now)
        if item.action == "delete" and item.delete_sql and cutoff:
            results[item.id] = {"deleted": db.execute(text(item.delete_sql),
                                                      {"cutoff": cutoff}).rowcount}  # fmt: skip
        elif item.id == "audit_events" and cutoff:
            made = (archive_audit or archive.archive_before)(db, cutoff, actor_id)
            results[item.id] = {
                "archived": made.events if made else 0,
                "archive_number": made.archive_number if made else None,
            }
    run = RetentionRun(applied_by=actor_id, applied_at=now, results=results)
    db.add(run)
    db.flush()
    record_audit_event(
        db, actor_id=actor_id, action="retention.applied", entity_type="retention_run",
        entity_id=run.id, metadata=results,
    )  # fmt: skip
    return run
