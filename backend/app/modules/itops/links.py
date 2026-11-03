"""The application ↔ workflow dependency graph (Phase 65, roadmap Milestone E step 3).

Every step of a workflow runs a handler, and a handler's namespace says which of the bank's
core systems it uses: `accounts.*` the Core Banking Ledger, `compliance.*` Sanctions
Screening and AML Monitoring, `wf0002.*` the Payments Gateway, and so on. Where the
simulated estate exists (Phase 63), each such step also calls one of the estate's critical
(tier 1 or 2) applications in the step's business domain, chosen deterministically from the
workflow and step, so the same workflow always calls the same applications.

The graph is derived, never stored: it is read from the latest active version of each
workflow definition, so it is always current. With it:

- **which workflows call an application**, and through which steps;
- **which applications a workflow calls**;
- **what an outage stops:** a down application fails every application that waits on it
  synchronously (Phase 64), and so every workflow step that calls any of them;
- **wiring:** how much of the estate the bank's workflows depend on, directly or through
  what they call.
"""

import hashlib
import uuid
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.modules.itops import simulated
from app.modules.itops.models import Application, ApplicationDependency

# Handler namespace -> (the core applications its steps use, the estate domain they call).
NAMESPACES: dict[str, tuple[tuple[str, ...], str]] = {
    "accounts": (("Core Banking Ledger",), "Ledger"),
    "customers": (("Core Banking Ledger", "Document Archive"), "Customer"),
    "compliance": (("Sanctions Screening", "AML Monitoring"), "Compliance"),
    "lending": (("Loan Origination", "Core Banking Ledger"), "Lending"),
    "cards": (("Card Authorisation",), "Cards"),
    "clearing": (("Payments Gateway",), "Payments"),
    "retail": (("Retail Banking Platform", "Core Banking Ledger"), "Channels"),
    "mortgages": (("Mortgage Platform",), "Lending"),
    "commercial": (("Commercial Lending Platform",), "Lending"),
    "trade": (("Trade Finance System",), "Trade"),
    "treasury": (("Treasury Dealing System",), "Treasury"),
    "wealth": (("Wealth Platform",), "Wealth"),
    "risk": (("Risk Engine",), "Risk"),
    "finance": (
        ("Core Banking Ledger", "Regulatory Reporting", "Enterprise Data Warehouse"),
        "Finance",
    ),
    "service": (("Service Desk CRM",), "Customer"),
    "collections": (("Collections System",), "Collections"),
    "hr": (("HR System",), "HR"),
    "procurement": (("Procurement Suite",), "Procurement"),
    "itops": (("IT Service Management",), "Data"),
    "backoffice": (("Workflow Factory",), "Reporting"),
    "ai": (("AI Innovation Lab Console",), "Data"),
    "wf0001": (("Core Banking Ledger", "Sanctions Screening"), "Customer"),
    "wf0002": (("Payments Gateway", "Core Banking Ledger"), "Payments"),
    "wf0003": (("Loan Origination",), "Lending"),
    "wf0004": (("Loan Origination", "Core Banking Ledger"), "Collections"),
}  # `core.*` handlers (values, checks, outcomes) call no application.


@dataclass(frozen=True)
class Link:
    workflow_id: str
    version: int
    workflow: str
    department: str
    step_id: str
    step: str
    handler: str
    application_id: uuid.UUID
    source: str  # core (by namespace) or estate (chosen from the domain)


def _definitions(db: Session) -> list[tuple[str, int, str, dict[str, Any]]]:
    """The latest active version of every workflow."""
    rows = db.execute(text(
        "SELECT DISTINCT ON (workflow_id) workflow_id, version, name, definition "
        "FROM workflow_definitions WHERE status = 'active' "
        "ORDER BY workflow_id, version DESC")).all()  # fmt: skip
    return [(r[0], r[1], r[2], r[3]) for r in rows]


def _pick(candidates: list[Application], workflow_id: str, step_id: str) -> Application:
    digest = hashlib.sha256(f"{workflow_id}:{step_id}".encode()).digest()
    return candidates[int.from_bytes(digest[:8], "big") % len(candidates)]


def links(db: Session) -> list[Link]:
    """Every step of every active workflow and the applications it calls."""
    apps = list(db.execute(select(Application).where(Application.status == "active")
                           .order_by(Application.application_number)).scalars())  # fmt: skip
    by_name = {a.name: a for a in apps}
    estate: dict[str, list[Application]] = defaultdict(list)
    for a in apps:
        if a.generated_from and a.tier <= 2:
            estate[a.name.split(" ", 1)[0]].append(a)
    result: list[Link] = []
    for workflow_id, version, name, document in _definitions(db):
        department = document.get("business_owner") or "Unassigned"
        for step in document.get("steps") or []:
            handler = step.get("handler") or ""
            namespace = handler.split(".", 1)[0]
            if namespace not in NAMESPACES:
                continue
            core, domain = NAMESPACES[namespace]
            called = [(by_name[n], "core") for n in core if n in by_name]
            if estate.get(domain):
                called.append((_pick(estate[domain], workflow_id, step["id"]), "estate"))
            result.extend(Link(workflow_id, version, name, department, step["id"],
                               step.get("name") or step["id"], handler, app.id, source)
                          for app, source in called)  # fmt: skip
    return result


def _numbers(db: Session, ids) -> dict[uuid.UUID, Application]:
    ids = list(ids)
    if not ids:
        return {}
    return {a.id: a for a in db.execute(select(Application).where(Application.id.in_(ids)))
            .scalars()}  # fmt: skip


def application_workflows(db: Session, app: Application, limit: int = 50) -> dict[str, Any]:
    """The workflows that call the application directly, and what its outage stops."""
    every = links(db)
    direct: dict[str, dict[str, Any]] = {}
    for link in every:
        if link.application_id == app.id:
            entry = direct.setdefault(link.workflow_id, {
                "workflow_id": link.workflow_id, "name": link.workflow,
                "department": link.department, "steps": []})  # fmt: skip
            if link.step not in entry["steps"]:
                entry["steps"].append(link.step)
    return {
        "calls": len(direct),
        "workflows": sorted(direct.values(), key=lambda w: w["workflow_id"])[:limit],
        "outage": outage_impact(db, app, every=every, limit=limit),
    }


def outage_impact(db: Session, app: Application, *, every: list[Link] | None = None,
                  limit: int = 50) -> dict[str, Any]:  # fmt: skip
    """What stops while the application is down: the applications that fail with it, and
    each workflow with a step that calls any of them (the step fails)."""
    every = links(db) if every is None else every
    down = simulated.failing(db, app)
    hit: dict[str, dict[str, Any]] = {}
    for link in every:
        if link.application_id not in down:
            continue
        entry = hit.setdefault(link.workflow_id, {
            "workflow_id": link.workflow_id, "name": link.workflow,
            "department": link.department, "steps": [], "via": set()})  # fmt: skip
        if link.step not in entry["steps"]:
            entry["steps"].append(link.step)
        entry["via"].add(link.application_id)
    apps = _numbers(db, {v for e in hit.values() for v in e["via"]})
    workflows = []
    for entry in sorted(hit.values(), key=lambda w: (-len(w["steps"]), w["workflow_id"])):
        workflows.append({**entry, "via": sorted(apps[v].application_number
                                                 for v in entry["via"])})  # fmt: skip
    total = len({link.workflow_id for link in every})
    return {
        "applications_failing": len(down),
        "workflows_stopped": len(hit),
        "workflows_linked": total,
        "steps_stopped": sum(len(e["steps"]) for e in hit.values()),
        "by_department": dict(Counter(e["department"] for e in hit.values()).most_common()),
        "workflows": workflows[:limit],
    }


def workflow_applications(db: Session, workflow_id: str) -> dict[str, Any]:
    """The applications a workflow's steps call, each with the steps."""
    calls: dict[uuid.UUID, dict[str, Any]] = {}
    name = None
    for link in links(db):
        if link.workflow_id != workflow_id:
            continue
        name = link.workflow
        entry = calls.setdefault(link.application_id, {"steps": [], "source": link.source})
        if link.step not in entry["steps"]:
            entry["steps"].append(link.step)
    apps = _numbers(db, calls)
    return {
        "workflow_id": workflow_id, "name": name,
        "applications": sorted(({
            "application_number": apps[i].application_number, "name": apps[i].name,
            "tier": apps[i].tier, "source": c["source"], "steps": c["steps"]}
            for i, c in calls.items()), key=lambda a: (a["tier"], a["name"])),
    }  # fmt: skip


def summary(db: Session) -> dict[str, Any]:
    """How much of the estate the workflows depend on: called directly, or relied on
    (any kind of dependency, directly or not) by an application a workflow calls."""
    every = links(db)
    called = {link.application_id for link in every}
    forward: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for a, b in db.execute(select(ApplicationDependency.application_id,
                                  ApplicationDependency.depends_on_id)).all():  # fmt: skip
        forward[a].append(b)
    wired, queue = set(called), deque(called)
    while queue:
        for nxt in forward.get(queue.popleft(), ()):
            if nxt not in wired:
                wired.add(nxt)
                queue.append(nxt)
    active = db.execute(select(Application.id).where(Application.status == "active")).all()
    steps = {(link.workflow_id, link.step_id) for link in every}
    return {
        "workflows_linked": len({link.workflow_id for link in every}),
        "workflows": len(_definitions(db)),
        "steps_linked": len(steps),
        "links": len(every),
        "applications": len(active),
        "called_directly": len(called),
        "wired": len(wired),
        "unwired": len(active) - len(wired & {r[0] for r in active}),
    }


# --- The Milestone E exit (Phase 68) ---------------------------------------------------------

EXIT_APPLICATIONS = 2500


def exit_check(db: Session) -> dict[str, Any]:
    """Roadmap Milestone E's exit: 2,500 applications generated and wired, and one outage's
    impact measured (a completed simulation run with application outages, Phase 67)."""
    from app.simulation.models import SimulationRun

    wiring = summary(db)
    generated = db.execute(select(func.count()).select_from(Application).where(
        Application.generated_from.is_not(None))).scalar_one()  # fmt: skip
    measured = db.execute(
        select(SimulationRun).where(SimulationRun.status == "completed",
                                    SimulationRun.results["applications"].is_not(None))
        .order_by(SimulationRun.completed_at.desc()).limit(1)).scalar_one_or_none()  # fmt: skip
    outage = None
    if measured is not None:
        effects = measured.results["applications"]
        outage = {"run_number": measured.run_number, "scenario_id": measured.scenario_id,
                  "cases": measured.results.get("cases"),
                  "outages": [o["application"] for o in effects["outages"]],
                  "executions_failed": effects["executions_failed"],
                  "executions_delayed": effects["executions_delayed"]}  # fmt: skip
    checks = {
        "generated": generated >= EXIT_APPLICATIONS,
        "wired": wiring["applications"] > 0 and wiring["unwired"] == 0,
        "outage_measured": outage is not None,
    }
    return {"passed": all(checks.values()), "checks": checks, "target": EXIT_APPLICATIONS,
            "generated": generated, "wiring": wiring, "outage": outage}  # fmt: skip
