"""The slow-query log: statements over `slow_query_ms`, from the API and every worker.

SQLAlchemy engine events time each statement. A slow one is logged at once (structured,
with its route or job and correlation ID) and queued; a background thread writes the queue
to `slow_queries` every few seconds on its own connection, so recording never adds to the
transaction being measured. Statements are stored without their parameters, which may hold
(synthetic) personal data. The table keeps the newest `KEEP` rows.
"""

import logging
import re
import threading
import time
from collections import deque
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, event, insert, text

from app.core.logging import correlation_id_var
from app.observability.models import SlowQuery

logger = logging.getLogger("atlas.slow_query")

KEEP = 5_000
MAX_STATEMENT = 4_000
FLUSH_SECONDS = 5.0
_PENDING_LIMIT = 1_000  # dropped beyond this if the database cannot keep up

# What the current statement runs for: "GET /api/v1/customers" or "job ledger.reconcile".
# Requests store a dict holding their ASGI scope; the route is read when a query is slow.
query_context: ContextVar[Any] = ContextVar("query_context", default=None)

_WHITESPACE = re.compile(r"\s+")


def _context() -> str | None:
    value = query_context.get()
    if isinstance(value, dict):  # a request: method and route template (once routed)
        from app.observability.middleware import route_template

        scope = value["scope"]
        path = route_template(scope) or scope.get("path", "")
        return f"{scope.get('method', '')} {path}"[:200]
    return value[:200] if value else None


class SlowQueryLog:
    def __init__(self) -> None:
        self.pending: deque[dict[str, Any]] = deque(maxlen=_PENDING_LIMIT)
        self.threshold_ms = 0
        self.source = "api"
        self._engines: set[int] = set()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._flushes = 0

    def install(
        self, engine: Engine, *, source: str, threshold_ms: int, writer: bool = True
    ) -> None:
        """Time every statement on `engine` (once per engine) and start the writer."""
        self.source = source
        self.threshold_ms = threshold_ms
        if threshold_ms <= 0 or id(engine) in self._engines:
            return
        self._engines.add(id(engine))
        event.listen(engine, "before_cursor_execute", self._before)
        event.listen(engine, "after_cursor_execute", self._after)
        if writer and (self._thread is None or not self._thread.is_alive()):
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, args=(engine,), name="slow-query-writer", daemon=True
            )
            self._thread.start()

    def _before(self, conn, cursor, statement, parameters, context, executemany) -> None:
        conn.info.setdefault("atlas_query_started", []).append(time.perf_counter())

    def _after(self, conn, cursor, statement, parameters, context, executemany) -> None:
        started = conn.info.get("atlas_query_started")
        if not started:
            return
        elapsed_ms = (time.perf_counter() - started.pop()) * 1000
        if conn.info.get("atlas_slow_query_writer") or elapsed_ms < self.threshold_ms:
            return
        entry = {
            "occurred_at": datetime.now(UTC),
            "duration_ms": round(elapsed_ms),
            "statement": _WHITESPACE.sub(" ", statement).strip()[:MAX_STATEMENT],
            "source": self.source[:100],
            "context": _context(),
            "correlation_id": correlation_id_var.get(),
        }
        self.pending.append(entry)
        logger.warning(
            "slow query",
            extra={
                "duration_ms": entry["duration_ms"],
                "context": entry["context"],
                "statement": entry["statement"][:500],
            },
        )

    def drain(self) -> list[dict[str, Any]]:
        entries = []
        while self.pending:
            entries.append(self.pending.popleft())
        return entries

    def write(self, conn, entries: list[dict[str, Any]]) -> None:
        """Store entries (on a connection that is not itself timed) and trim old rows."""
        if not entries:
            return
        conn.execute(insert(SlowQuery), entries)
        self._flushes += 1
        if self._flushes % 20 == 1:
            conn.execute(
                text(
                    "DELETE FROM slow_queries WHERE id <= "
                    "(SELECT id FROM slow_queries ORDER BY id DESC OFFSET :keep LIMIT 1)"
                ),
                {"keep": KEEP},
            )

    def flush(self, engine: Engine) -> int:
        entries = self.drain()
        if not entries:
            return 0
        try:
            with engine.begin() as conn:
                conn.info["atlas_slow_query_writer"] = True
                try:
                    self.write(conn, entries)
                finally:
                    conn.info.pop("atlas_slow_query_writer", None)
        except Exception:  # the log must never take the application down
            logger.exception("could not store slow queries")
            return 0
        return len(entries)

    def _run(self, engine: Engine) -> None:
        while not self._stop.wait(FLUSH_SECONDS):
            self.flush(engine)

    def uninstall(self, engine: Engine) -> None:
        if id(engine) in self._engines:
            self._engines.discard(id(engine))
            event.remove(engine, "before_cursor_execute", self._before)
            event.remove(engine, "after_cursor_execute", self._after)

    def stop(self, engine: Engine | None = None) -> None:
        self._stop.set()
        if engine is not None:
            self.flush(engine)


SLOW_QUERIES = SlowQueryLog()
