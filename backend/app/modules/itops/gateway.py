"""Workflow steps call their applications (Phase 66, roadmap Milestone E step 4).

Before a step's handler runs, the engine asks the gateway to make the step's application
calls: the core systems its handler's namespace uses and, where the estate exists, the estate
application the dependency graph chose for it (Phase 65). Each call goes through the generic
simulated application (Phase 64) at the step's time, the simulation clock or the real one:

- **an application that is down,** or that waits synchronously on one that is, refuses the
  call: the step fails as `application_unavailable`, naming the application and the
  outage's cause. It is retried under the step's retry policy (three attempts, 30 s then
  60 s apart by default), so a short outage delays the workflow and a long one fails it,
  or sends it down its `on_failure` route;
- **otherwise the calls succeed,** and their latencies, one after another, are added to
  the step's recorded duration; a degraded application is slower.

By default only outages fail calls, so a workflow repeats exactly. `realistic()` also
applies each application's own error rate and timeouts: a simulation may opt in.

The application calls are deterministic: a call's random draw comes from the execution, the
step and the attempt.
"""

import hashlib
import random
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.itops import links, simulated
from app.modules.itops.models import Application

REALISTIC: ContextVar[bool] = ContextVar("application_errors", default=False)


@contextmanager
def realistic() -> Iterator[None]:
    """Apply the applications' own error rates and timeouts, not only outages."""
    token = REALISTIC.set(True)
    try:
        yield
    finally:
        REALISTIC.reset(token)


@dataclass
class Report:
    calls: list[dict[str, Any]] = field(default_factory=list)
    latency_ms: float = 0.0
    failure: dict[str, Any] | None = None


@dataclass
class Gateway:
    """One per engine advance: the estate's outages at each moment and the applications each
    namespace and domain resolve to are loaded once."""

    db: Session
    _views: dict[datetime, simulated.Estate] = field(default_factory=dict)
    _core: dict[str, Application] | None = None
    _estate: dict[str, list[Application]] = field(default_factory=dict)

    def _core_apps(self) -> dict[str, Application]:
        if self._core is None:
            names = {n for core, _ in links.NAMESPACES.values() for n in core}
            self._core = {a.name: a for a in self.db.execute(select(Application).where(
                Application.name.in_(names),
                Application.status == "active")).scalars()}  # fmt: skip
        return self._core

    def _domain(self, domain: str) -> list[Application]:
        if domain not in self._estate:
            self._estate[domain] = list(self.db.execute(select(Application).where(
                Application.generated_from.is_not(None), Application.tier <= 2,
                Application.status == "active", Application.name.like(f"{domain} %"))
                .order_by(Application.application_number)).scalars())  # fmt: skip
        return self._estate[domain]

    def applications(self, workflow_id: str, step_id: str, handler: str) -> list[Application]:
        """What the step calls: the same as the dependency graph says (links.links)."""
        namespace = handler.split(".", 1)[0]
        if namespace not in links.NAMESPACES:
            return []
        core, domain = links.NAMESPACES[namespace]
        apps = [self._core_apps()[n] for n in core if n in self._core_apps()]
        candidates = self._domain(domain)
        if candidates:
            apps.append(links._pick(candidates, workflow_id, step_id))
        return apps

    def _view(self, at: datetime) -> simulated.Estate:
        if at not in self._views:
            view = simulated.Estate(self.db, at)  # the outages in force at that moment
            for previous in self._views.values():  # contracts and the graph do not change
                view._contracts = previous._contracts
                view._edges = previous._edges
            self._views = {at: view}
        return self._views[at]

    def call(self, *, workflow_id: str, step_id: str, handler: str, execution_id: uuid.UUID,
             attempt: int, at: datetime) -> Report:  # fmt: skip
        """Make the step's calls in turn; stop at the first that fails."""
        report = Report()
        apps = self.applications(workflow_id, step_id, handler)
        if not apps:
            return report
        view = self._view(at)
        seed = hashlib.sha256(f"{execution_id}:{step_id}:{attempt}".encode()).digest()
        rng = random.Random(int.from_bytes(seed[:8], "big"))
        realistic_ = REALISTIC.get()
        for app in apps:
            operation = "write" if _writes(handler) else "read"
            result = view.call(app, operation, rng)
            # By default only an outage fails a call; random errors count only when realistic.
            ok = result.ok or (not realistic_ and result.error != "outage")
            latency = result.latency_ms
            report.latency_ms += latency
            report.calls.append({"application": app.application_number, "ok": ok,
                                 "latency_ms": latency,
                                 **({} if ok else {"error": result.error})})  # fmt: skip
            if not ok:
                state = view.state(app)
                report.failure = {
                    "application": app.application_number, "name": app.name,
                    "error": result.error, "cause": result.cause or state.cause,
                    "path": list(state.path)}  # fmt: skip
                break
        report.latency_ms = round(report.latency_ms, 1)
        return report


WRITE_VERBS = ("open", "create", "post", "pay", "transfer", "approve", "reject", "register",
               "raise", "book", "disburse", "release", "close", "complete", "record", "submit",
               "write", "settle", "place", "issue", "block", "set", "update", "decide")  # fmt: skip


def _writes(handler: str) -> bool:
    action = handler.split(".", 1)[-1]
    return action.split("_", 1)[0] in WRITE_VERBS
