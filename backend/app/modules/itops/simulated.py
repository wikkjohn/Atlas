"""The generic simulated application (Phase 64, roadmap Milestone E step 2).

Every application in the registry answers calls through one contract:

- **Operations:** `read` and `write`. A write takes longer than a read.
- **Latency:** log-normal around a median set by the technology, scaled by where it runs and
  by how many applications it calls synchronously (API and authentication dependencies).
- **Failures:** a small error rate set by the tier (critical applications are engineered to
  fail less) and the technology; a call slower than the timeout fails as a timeout.
- **Outages:** an application is *down* or *degraded* for a window. A down application fails
  every call; so does every application that relies on it synchronously, directly or through
  others. Data and batch dependencies do not fail a call. A degraded application, or one that
  relies on it synchronously, is slower and fails more often.

Calls are deterministic for a given random generator, so a simulation run repeats exactly.
"""

import math
import random
import uuid
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.errors import BusinessRuleViolation, NotFoundError
from app.modules.itops.models import (
    OUTAGE_SEQUENCE,
    Application,
    ApplicationDependency,
    ApplicationOutage,
)

OPERATIONS = ("read", "write")
OUTAGE_KINDS = ("down", "degraded")
SYNCHRONOUS = ("api", "auth")  # a call waits on these; data and batch links do not
TIMEOUT_MS = 5_000
SIGMA = 0.5  # log-normal spread of latency
Z95 = 1.645
# Median latency of a read, in milliseconds, by technology.
MEDIAN_MS = {"cobol-mainframe": 40, "go": 50, "node": 70, "java-spring": 80, "dotnet": 90,
             "python": 110, "oracle-plsql": 120, "low-code": 200, "sap": 250, "saas": 300,
             "unknown": 100}  # fmt: skip
HOSTING_FACTOR = {"on_premise": 1.0, "private_cloud": 1.1, "public_cloud": 1.3, "saas": 1.5}
WRITE_FACTOR = 1.5
PER_SYNC_DEPENDENCY_MS = 20
TIER_ERROR_RATE = {1: 0.001, 2: 0.005, 3: 0.01}
TECHNOLOGY_ERROR_FACTOR = {"low-code": 2.0, "saas": 1.5, "cobol-mainframe": 0.5}
DEGRADED_LATENCY = 4.0
DEGRADED_ERROR_RATE = 0.10


def _now() -> datetime:
    return datetime.now(UTC)


def _rule(message: str, rule: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, {"rule": rule})


@dataclass(frozen=True)
class State:
    status: str  # up, degraded or down
    cause: str | None = None  # the application number whose outage it is
    path: tuple[str, ...] = ()  # from this application to the cause


@dataclass
class CallResult:
    ok: bool
    latency_ms: float
    error: str | None = None  # outage, error or timeout
    cause: str | None = None


@dataclass(frozen=True)
class Contract:
    application_number: str
    median_ms: dict[str, float]
    p95_ms: dict[str, float]
    error_rate: float
    timeout_ms: int
    sync_dependencies: int
    operations: tuple[str, ...] = field(default=OPERATIONS)


def _sync_dependencies(db: Session, app: Application) -> int:
    return len(db.execute(select(ApplicationDependency.id).where(
        ApplicationDependency.application_id == app.id,
        ApplicationDependency.kind.in_(SYNCHRONOUS))).all())  # fmt: skip


def contract(db: Session, app: Application) -> Contract:
    """The application's latency and failure model, with no outage."""
    sync = _sync_dependencies(db, app)
    base = (MEDIAN_MS.get(app.technology, MEDIAN_MS["unknown"])
            * HOSTING_FACTOR.get(app.hosting, 1.0) + sync * PER_SYNC_DEPENDENCY_MS)  # fmt: skip
    median = {"read": base, "write": base * WRITE_FACTOR}
    rate = TIER_ERROR_RATE.get(app.tier, 0.01) * TECHNOLOGY_ERROR_FACTOR.get(app.technology, 1.0)
    return Contract(app.application_number, {k: round(v, 1) for k, v in median.items()},
                    {k: round(v * math.exp(Z95 * SIGMA), 1) for k, v in median.items()},
                    round(rate, 4), TIMEOUT_MS, sync)  # fmt: skip


def _active(db: Session, at: datetime) -> list[ApplicationOutage]:
    return list(db.execute(select(ApplicationOutage).where(
        ApplicationOutage.starts_at <= at,
        or_(ApplicationOutage.ends_at.is_(None),
            ApplicationOutage.ends_at > at))).scalars())  # fmt: skip


class Estate:
    """The outages in force at one moment and the synchronous dependency graph, loaded once,
    so a simulation can make many calls cheaply."""

    def __init__(self, db: Session, at: datetime | None = None):
        self.db = db
        self.at = at or _now()
        outages = _active(db, self.at)
        self.kind: dict[uuid.UUID, str] = {}
        for o in outages:  # down outranks degraded
            if self.kind.get(o.application_id) != "down":
                self.kind[o.application_id] = o.kind
        self._edges: dict[uuid.UUID, list[uuid.UUID]] | None = None
        self._states: dict[uuid.UUID, State] = {}
        self._contracts: dict[uuid.UUID, Contract] = {}

    def _graph(self) -> dict[uuid.UUID, list[uuid.UUID]]:
        if self._edges is None:
            self._edges = {}
            for a, b in self.db.execute(select(
                    ApplicationDependency.application_id, ApplicationDependency.depends_on_id)
                    .where(ApplicationDependency.kind.in_(SYNCHRONOUS))).all():  # fmt: skip
                self._edges.setdefault(a, []).append(b)
        return self._edges

    def _number(self, app_id: uuid.UUID) -> str:
        return self.db.get(Application, app_id).application_number

    def state(self, app: Application) -> State:
        """Up, degraded or down: its own outage, or the nearest one it waits on."""
        if app.id in self._states:
            return self._states[app.id]
        if not self.kind:
            return State("up")
        if app.id in self.kind:
            result = State(self.kind[app.id], app.application_number, (app.application_number,))
        else:
            # Breadth first, so the nearest outage is the cause; a down one anywhere wins.
            parents: dict[uuid.UUID, uuid.UUID | None] = {app.id: None}
            queue, found, degraded = deque([app.id]), None, None
            while queue and found is None:
                node = queue.popleft()
                for nxt in self._graph().get(node, ()):
                    if nxt in parents:
                        continue
                    parents[nxt] = node
                    kind = self.kind.get(nxt)
                    if kind == "down":
                        found = nxt
                        break
                    if kind == "degraded" and degraded is None:
                        degraded = nxt
                    queue.append(nxt)
            target = found or degraded
            if target is None:
                result = State("up")
            else:
                path, node = [], target
                while node is not None:
                    path.append(self._number(node))
                    node = parents[node]
                result = State("down" if found else "degraded", path[0], tuple(reversed(path)))
        self._states[app.id] = result
        return result

    def contract(self, app: Application) -> Contract:
        if app.id not in self._contracts:
            self._contracts[app.id] = contract(self.db, app)
        return self._contracts[app.id]

    def call(self, app: Application, operation: str, rng: random.Random) -> CallResult:
        """One call to the application, under the outages in force."""
        if operation not in OPERATIONS:
            raise _rule(f"The operation is one of {', '.join(OPERATIONS)}.", "operation_invalid")
        state = self.state(app)
        terms = self.contract(app)
        if state.status == "down":
            # The caller waits for its connection to be refused or to time out.
            return CallResult(False, float(rng.choice((50, TIMEOUT_MS))), "outage", state.cause)
        latency = rng.lognormvariate(math.log(terms.median_ms[operation]), SIGMA)
        rate = terms.error_rate
        if state.status == "degraded":
            latency *= DEGRADED_LATENCY
            rate += DEGRADED_ERROR_RATE
        if latency > terms.timeout_ms:
            return CallResult(False, float(terms.timeout_ms), "timeout", state.cause)
        if rng.random() < rate:
            return CallResult(False, round(latency, 1), "error", state.cause)
        return CallResult(True, round(latency, 1))


def sample(db: Session, app: Application, operation: str, count: int, seed: int,
           at: datetime | None = None) -> dict[str, Any]:  # fmt: skip
    """Make `count` calls and summarise them: how a caller would see the application now."""
    if not 1 <= count <= 10_000:
        raise _rule("Make 1 to 10,000 calls.", "count_invalid")
    estate = Estate(db, at)
    rng = random.Random(seed)
    results = [estate.call(app, operation, rng) for _ in range(count)]
    latencies = sorted(r.latency_ms for r in results)
    state = estate.state(app)

    def pct(p: float) -> float:
        return latencies[min(len(latencies) - 1, int(p * len(latencies)))]

    return {
        "application_number": app.application_number, "operation": operation, "calls": count,
        "seed": seed, "ok": sum(r.ok for r in results),
        "failed": sum(not r.ok for r in results),
        "errors": dict(Counter(r.error for r in results if r.error)),
        "p50_ms": pct(0.50), "p95_ms": pct(0.95), "max_ms": latencies[-1],
        "state": {"status": state.status, "cause": state.cause, "path": list(state.path)},
    }  # fmt: skip


# --- Outages ---------------------------------------------------------------------------


def declare_outage(db: Session, app: Application, kind: str, reason: str,
                   actor_id: uuid.UUID | None, *, starts_at: datetime | None = None,
                   ends_at: datetime | None = None, now: datetime | None = None,
                   open_incident: bool = True) -> ApplicationOutage:  # fmt: skip
    """Take an application down, or degrade it, for a window (open-ended without an end). An
    outage that has started opens an incident against the application, high urgency, its
    impact set by the tier."""
    from app.modules.itops import service

    now = now or _now()
    starts_at = starts_at or now
    if kind not in OUTAGE_KINDS:
        raise _rule(f"The kind is one of {', '.join(OUTAGE_KINDS)}.", "kind_invalid")
    if len(reason.strip()) < 5:
        raise _rule("Say why.", "reason_required")
    if app.status != "active":
        raise _rule(f"{app.name} is retired.", "application_retired")
    if ends_at is not None and ends_at <= starts_at:
        raise _rule("An outage ends after it starts.", "window_invalid")
    overlap = db.execute(select(ApplicationOutage).where(
        ApplicationOutage.application_id == app.id,
        or_(ApplicationOutage.ends_at.is_(None), ApplicationOutage.ends_at > starts_at),
        *([ApplicationOutage.starts_at < ends_at] if ends_at else [])
    )).scalars().first()  # fmt: skip
    if overlap:
        raise _rule(f"{app.name} already has outage {overlap.outage_number} then.",
                    "outage_overlap")  # fmt: skip
    incident = None
    if open_incident and starts_at <= now:
        impact = {1: "high", 2: "medium"}.get(app.tier, "low")
        title = f"{'Outage' if kind == 'down' else 'Degraded service'}: {reason.strip()}"[:200]
        incident = service.open_incident(db, app, title, impact, "high", actor_id, now=now)
    number = db.execute(OUTAGE_SEQUENCE.next_value()).scalar_one()
    outage = ApplicationOutage(
        outage_number=f"OUT-{number:07d}", application_id=app.id, kind=kind,
        reason=reason.strip(), starts_at=starts_at, ends_at=ends_at,
        incident_id=incident.id if incident else None, declared_by=actor_id, created_at=now,
    )  # fmt: skip
    db.add(outage)
    db.flush()
    record_audit_event(db, actor_id=actor_id, action="itops.outage_declared",
                       entity_type="application_outage", entity_id=str(outage.id),
                       metadata={"outage_number": outage.outage_number, "kind": kind,
                                 "application_number": app.application_number})  # fmt: skip
    return outage


def get_outage(db: Session, outage_id: uuid.UUID) -> ApplicationOutage:
    outage = db.get(ApplicationOutage, outage_id)
    if outage is None:
        raise NotFoundError("No such outage.")
    return outage


def end_outage(db: Session, outage: ApplicationOutage, actor_id: uuid.UUID | None,
               now: datetime | None = None) -> ApplicationOutage:  # fmt: skip
    """Restore service now."""
    now = now or _now()
    if outage.starts_at > now or (outage.ends_at is not None and outage.ends_at <= now):
        raise _rule(f"{outage.outage_number} is not in force.", "outage_not_active")
    outage.ends_at = now
    outage.ended_by = actor_id
    db.flush()
    record_audit_event(db, actor_id=actor_id, action="itops.outage_ended",
                       entity_type="application_outage", entity_id=str(outage.id),
                       metadata={"outage_number": outage.outage_number})  # fmt: skip
    return outage


def failing(db: Session, app: Application) -> set[uuid.UUID]:
    """The application and everything that waits on it synchronously, directly or through
    others: what fails while it is down."""
    reverse: dict[uuid.UUID, list[uuid.UUID]] = {}
    for a, b in db.execute(select(ApplicationDependency.application_id,
                                  ApplicationDependency.depends_on_id)
                           .where(ApplicationDependency.kind.in_(SYNCHRONOUS))).all():  # fmt: skip
        reverse.setdefault(b, []).append(a)
    seen, queue = {app.id}, deque([app.id])
    while queue:
        for nxt in reverse.get(queue.popleft(), ()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def blast_radius(db: Session, app: Application) -> dict[str, Any]:
    """What fails if the application goes down, besides itself (a subset of the registry's
    impact, which counts every kind of dependency)."""
    return {"failing": len(failing(db, app)) - 1}
