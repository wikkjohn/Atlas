"""Request rate limits (Phase 85).

Fixed windows counted in PostgreSQL (`rate_limit_counters`), so every API process and
worker shares them; no Redis needed. A hit is counted in the request's own transaction:
a request refused for its rate leaves no trace, and failed sign-ins, which commit their
audit record before failing, commit their hit with it. Old windows are removed by the
retention schedule.

The limits are per bucket:

| Rule | Key | Limit |
| --- | --- | --- |
| `login.user` | username | 10 password sign-ins a 15 minutes |
| `login.ip` | client address | 100 password sign-ins a 15 minutes |
| `mfa.ip` | client address | 30 second-factor attempts a 15 minutes |
| `sso.ip` | client address | 60 single sign-on steps a 15 minutes |
| `writes.user` | user | 600 changes (POST, PUT, PATCH, DELETE) a minute |
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import DateTime, Index, Integer, String, text
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.config import get_settings
from app.core.database import Base
from app.core.errors import RateLimitedError


class RateLimitCounter(Base):
    __tablename__ = "rate_limit_counters"
    __table_args__ = (Index("ix_rate_limit_counters_window", "window_start"),)

    bucket: Mapped[str] = mapped_column(String(200), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    hits: Mapped[int] = mapped_column(Integer, nullable=False)


@dataclass(frozen=True)
class Rule:
    limit: int
    window: timedelta
    what: str


RULES: dict[str, Rule] = {
    "login.user": Rule(10, timedelta(minutes=15), "sign-in attempts for this account"),
    "login.ip": Rule(100, timedelta(minutes=15), "sign-in attempts from this address"),
    "mfa.ip": Rule(30, timedelta(minutes=15), "second-factor attempts from this address"),
    "sso.ip": Rule(60, timedelta(minutes=15), "single sign-on attempts from this address"),
    "writes.user": Rule(600, timedelta(minutes=1), "changes by this user"),
}

_UPSERT = text(
    "INSERT INTO rate_limit_counters (bucket, window_start, hits) VALUES (:bucket, :start, 1) "
    "ON CONFLICT (bucket, window_start) DO UPDATE SET hits = rate_limit_counters.hits + 1 "
    "RETURNING hits"
)


def _window_start(now: datetime, window: timedelta) -> datetime:
    seconds = int(window.total_seconds())
    epoch = int(now.timestamp())
    return datetime.fromtimestamp(epoch - epoch % seconds, UTC)


def hit(db: Session, rule_name: str, key: str, now: datetime | None = None) -> int:
    """Count one request against `rule_name` for `key`; refuse it (429) over the limit."""
    if not get_settings().rate_limits_enabled:
        return 0
    rule = RULES[rule_name]
    now = now or datetime.now(UTC)
    start = _window_start(now, rule.window)
    bucket = f"{rule_name}:{key}"[:200]
    hits = db.execute(_UPSERT, {"bucket": bucket, "start": start}).scalar_one()
    if hits > rule.limit:
        retry = max(1, int((start + rule.window - now).total_seconds()))
        raise RateLimitedError(
            f"Too many {rule.what}: at most {rule.limit} every "
            f"{int(rule.window.total_seconds() // 60) or 1} minute(s). Try again in "
            f"{retry} seconds.",
            retry,
        )
    return hits


def client_address(request) -> str:
    return request.client.host if request.client else "unknown"
