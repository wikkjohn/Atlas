"""The application registry and estate (Phase 63, roadmap Milestone E step 1).

Every application has an owning department and a tier (Phase 59); the registry adds who
answers for it, what it is built on, where it runs, and what it relies on. A dependency says
one application relies on another: when the second stops, the first is affected, and so is
everything that relies on the first. Dependencies never form a cycle.

`generate_estate` builds the bank's simulated estate: a seeded, deterministic set of
applications across the bank's departments, with owners, technologies and a dependency graph
in which every application relies only on ones generated before it (so the graph is acyclic
by construction) and more often on critical ones.
"""

import random
import time
import uuid
from collections import Counter, defaultdict, deque
from typing import Any

from sqlalchemy import func, select, text, true
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.core.permissions import RoleCode
from app.modules.countries.models import Country
from app.modules.identity.models import Role, User
from app.modules.itops.models import Application, ApplicationDependency
from app.modules.organizations.models import Organization, OrganizationType

GENERATOR = "estate-v1"
HOSTING = ("on_premise", "private_cloud", "public_cloud", "saas")
KINDS = ("data", "api", "batch", "auth")
# Technology, its weight in the estate, and where it tends to run.
TECHNOLOGIES = (
    ("java-spring", 22, ("private_cloud", "on_premise", "public_cloud")),
    ("dotnet", 14, ("on_premise", "private_cloud")),
    ("python", 12, ("public_cloud", "private_cloud")),
    ("node", 8, ("public_cloud",)),
    ("cobol-mainframe", 6, ("on_premise",)),
    ("oracle-plsql", 8, ("on_premise", "private_cloud")),
    ("sap", 5, ("private_cloud", "on_premise")),
    ("saas", 15, ("saas",)),
    ("low-code", 5, ("public_cloud", "saas")),
    ("go", 5, ("public_cloud", "private_cloud")),
)
SAAS_VENDORS = ("Synthetic CRM Co", "Example HR Cloud", "Placeholder Analytics", "Demo Docs Ltd",
                "Sample Ticketing Inc", "Fictional Payroll SaaS")  # fmt: skip
DOMAINS = ("Payments", "Ledger", "Cards", "Lending", "Customer", "Risk", "Compliance", "Treasury",
           "Trade", "Wealth", "Finance", "HR", "Procurement", "Data", "Channels", "Branch",
           "Collections", "Reporting", "Identity", "Messaging")  # fmt: skip
FUNCTIONS = ("Gateway", "Engine", "Portal", "Hub", "Service", "Store", "Reconciler", "Scheduler",
             "Monitor", "Archive", "Adapter", "Console", "Feed", "Router", "Workbench")  # fmt: skip
TIER_WEIGHTS = (10, 35, 55)  # % of generated applications in tiers 1, 2 and 3
CRITICAL_PULL = {1: 6, 2: 3, 3: 1}  # how much more often an application relies on each tier
KIND_WEIGHTS = (35, 40, 15, 10)  # data, api, batch, auth


def _rule(message: str, rule: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, {"rule": rule})


def _audit(db, actor_id, action: str, app: Application, **metadata) -> None:
    record_audit_event(db, actor_id=actor_id, action=action, entity_type="application",
                       entity_id=app.id, metadata={"application_number": app.application_number,
                                                   **metadata})  # fmt: skip


# --- Profile and dependencies ------------------------------------------------------------------


def set_profile(db: Session, app: Application, *, owner_username: str | None,
                technology: str, hosting: str, vendor: str | None,
                actor_id: uuid.UUID | None) -> Application:  # fmt: skip
    """Record who answers for the application, what it is built on and where it runs."""
    if hosting not in HOSTING:
        raise _rule(f"Hosting is one of {', '.join(HOSTING)}.", "hosting_invalid")
    if len(technology.strip()) < 2:
        raise _rule("Name the technology.", "technology_required")
    owner = None
    if owner_username:
        owner = db.execute(select(User).where(User.username == owner_username.strip())
                           ).scalar_one_or_none()  # fmt: skip
        if owner is None or not owner.is_active:
            raise NotFoundError(f"No active user {owner_username}.")
    app.owner_id = owner.id if owner else None
    app.technology, app.hosting = technology.strip().lower(), hosting
    app.vendor = (vendor or "").strip() or None
    db.flush()
    _audit(db, actor_id, "itops.application_profiled", app, technology=app.technology,
           hosting=hosting)  # fmt: skip
    return app


def _edges(db: Session) -> list[tuple[uuid.UUID, uuid.UUID]]:
    return list(db.execute(
        select(ApplicationDependency.application_id, ApplicationDependency.depends_on_id)
    ).tuples())  # fmt: skip


def relies_on(db: Session, start: Application, target: Application) -> bool:
    """Whether `start` relies on `target`, directly or through others."""
    graph: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for app_id, depends_on in _edges(db):
        graph[app_id].append(depends_on)
    seen, queue = {start.id}, deque([start.id])
    while queue:
        for nxt in graph[queue.popleft()]:
            if nxt == target.id:
                return True
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return False


def add_dependency(db: Session, app: Application, depends_on: Application, kind: str,
                   actor_id: uuid.UUID | None) -> ApplicationDependency:  # fmt: skip
    """Record that `app` relies on `depends_on`. Never on itself, on a retired application,
    twice, or so as to close a cycle."""
    if kind not in KINDS:
        raise _rule(f"The kind is one of {', '.join(KINDS)}.", "kind_invalid")
    if app.id == depends_on.id:
        raise _rule("An application does not rely on itself.", "not_self")
    if depends_on.status != "active":
        raise _rule(f"{depends_on.name} is retired.", "application_retired")
    exists = db.execute(select(ApplicationDependency.id).where(
        ApplicationDependency.application_id == app.id,
        ApplicationDependency.depends_on_id == depends_on.id)).first()  # fmt: skip
    if exists:
        raise ConflictError(f"{app.name} already relies on {depends_on.name}.")
    if relies_on(db, depends_on, app):
        raise _rule(f"{depends_on.name} already relies on {app.name}: that would be a cycle.",
                    "cycle")  # fmt: skip
    dependency = ApplicationDependency(application_id=app.id, depends_on_id=depends_on.id,
                                       kind=kind)  # fmt: skip
    db.add(dependency)
    db.flush()
    _audit(db, actor_id, "itops.dependency_added", app,
           depends_on=depends_on.application_number, kind=kind)  # fmt: skip
    return dependency


def remove_dependency(db: Session, dependency_id: uuid.UUID,
                      actor_id: uuid.UUID | None) -> None:  # fmt: skip
    dependency = db.get(ApplicationDependency, dependency_id)
    if dependency is None:
        raise NotFoundError("No such dependency.")
    app = db.get(Application, dependency.application_id)
    db.delete(dependency)
    db.flush()
    _audit(db, actor_id, "itops.dependency_removed", app)


def dependencies(db: Session, app: Application) -> list[tuple[ApplicationDependency, Application]]:
    """What the application relies on."""
    return list(db.execute(
        select(ApplicationDependency, Application)
        .join(Application, Application.id == ApplicationDependency.depends_on_id)
        .where(ApplicationDependency.application_id == app.id)
        .order_by(Application.tier, Application.name)
    ).tuples())  # fmt: skip


def dependents(db: Session, app: Application) -> list[tuple[ApplicationDependency, Application]]:
    """What relies on the application directly."""
    return list(db.execute(
        select(ApplicationDependency, Application)
        .join(Application, Application.id == ApplicationDependency.application_id)
        .where(ApplicationDependency.depends_on_id == app.id)
        .order_by(Application.tier, Application.name)
    ).tuples())  # fmt: skip


def impact(db: Session, app: Application, sample: int = 25) -> dict[str, Any]:
    """Everything affected when the application stops: whatever relies on it, directly or
    through others, by tier and department, nearest first."""
    reverse: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for app_id, depends_on in _edges(db):
        reverse[depends_on].append(app_id)
    depth = {app.id: 0}
    queue = deque([app.id])
    while queue:
        current = queue.popleft()
        for nxt in reverse[current]:
            if nxt not in depth:
                depth[nxt] = depth[current] + 1
                queue.append(nxt)
    affected_ids = [a for a in depth if a != app.id]
    # Department names repeat from country to country: label each with its country.
    label = func.concat(Organization.name, " (", func.coalesce(Country.iso_country_code, "—"),
                        ")")  # fmt: skip
    rows = db.execute(
        select(Application, label)
        .join(Organization, Organization.id == Application.department_id)
        .outerjoin(Country, Country.id == Organization.country_id)
        .where(Application.id.in_(affected_ids))
    ).all() if affected_ids else []  # fmt: skip
    by_tier = Counter(a.tier for a, _ in rows)
    departments = Counter(dept for _, dept in rows)
    nearest = sorted(rows, key=lambda r: (depth[r[0].id], r[0].tier, r[0].name))[:sample]
    return {
        "affected": len(rows),
        "direct": sum(1 for a, _ in rows if depth[a.id] == 1),
        "depth": max((depth[a.id] for a, _ in rows), default=0),
        "by_tier": {str(t): by_tier.get(t, 0) for t in (1, 2, 3)},
        "departments": len(departments),
        "top_departments": [{"department": d, "applications": n}
                            for d, n in departments.most_common(5)],
        "sample": [{"application_number": a.application_number, "name": a.name,
                    "tier": a.tier, "depth": depth[a.id], "department": dept}
                   for a, dept in nearest],
    }  # fmt: skip


# --- The estate ---------------------------------------------------------------------------------


def generate_estate(db: Session, count: int, seed: int,
                    actor_id: uuid.UUID | None = None) -> dict[str, Any]:  # fmt: skip
    """Generate `count` applications (with their dependencies) for the seed; running it again
    with the same seed adds only what is missing. Deterministic: the same seed, departments
    and owners give the same estate."""
    if not 1 <= count <= 10_000:
        raise _rule("Generate 1 to 10,000 applications.", "count_invalid")
    started = time.perf_counter()
    rng = random.Random(seed)
    tag = f"{GENERATOR}:{seed}"
    departments = list(db.execute(
        select(Organization.id).outerjoin(Country, Country.id == Organization.country_id)
        .where(Organization.organization_type == OrganizationType.DEPARTMENT,
               Organization.status == "active")
        .order_by(Country.iso_country_code, Organization.name, Organization.id)
    ).scalars())  # fmt: skip
    if not departments:
        raise _rule("There are no departments to own applications.", "no_departments")
    owners = list(db.execute(
        select(User.id).join(Role, Role.id == User.role_id)
        .where(Role.code == RoleCode.DEPARTMENT_MANAGER, User.is_active.is_(True))
        .order_by(User.username)
    ).scalars())  # fmt: skip
    existing = {a.name: a for a in db.execute(
        select(Application).where(Application.generated_from == tag)).scalars()}  # fmt: skip
    # The hand-registered catalogue (the seeded core systems) can be relied on as well.
    # The warehouse (Phase 68) is fed by the estate, never relied on by it: no cycle.
    pool: list[tuple[uuid.UUID, int]] = [(a.id, a.tier) for a in db.execute(
        select(Application).where(Application.generated_from.is_(None),
                                  Application.status == "active",
                                  Application.name != WAREHOUSE)
        .order_by(Application.application_number)).scalars()]  # fmt: skip
    techs = [t for t, _, _ in TECHNOLOGIES]
    tech_weights = [w for _, w, _ in TECHNOLOGIES]
    hosting_for = {t: h for t, _, h in TECHNOLOGIES}

    planned = []
    for index in range(count):
        domain, function = rng.choice(DOMAINS), rng.choice(FUNCTIONS)
        name = f"{domain} {function} {index + 1:04d}"
        tier = rng.choices((1, 2, 3), TIER_WEIGHTS)[0]
        tech = rng.choices(techs, tech_weights)[0]
        hosting = rng.choice(hosting_for[tech])
        vendor = rng.choice(SAAS_VENDORS) if hosting == "saas" else None
        department = departments[rng.randrange(len(departments))]
        owner = owners[rng.randrange(len(owners))] if owners else None
        planned.append((name, domain, function, tier, tech, hosting, vendor, department, owner,
                        rng.random()))  # fmt: skip

    missing = [p for p in planned if p[0] not in existing]
    numbers = list(db.execute(text(
        "SELECT nextval('application_number_seq') FROM generate_series(1, :n)"),
        {"n": len(missing)}).scalars()) if missing else []  # fmt: skip
    created: list[Application] = []
    for (name, domain, function, tier, tech, hosting, vendor, department, owner, _), number \
            in zip(missing, numbers, strict=True):  # fmt: skip
        app = Application(
            application_number=f"APP-{number:05d}", name=name,
            description=f"{domain} {function.lower()} (generated)", department_id=department,
            tier=tier, status="active", owner_id=owner, technology=tech, hosting=hosting,
            vendor=vendor, generated_from=tag,
        )  # fmt: skip
        db.add(app)
        created.append(app)
        existing[name] = app
    db.flush()

    # Dependencies, in generation order: each application relies only on earlier ones, so the
    # graph stays acyclic; critical ones are relied on more often.
    had = {(a, d) for a, d in _edges(db)}
    added = 0
    new_edges = []
    for name, _, _, tier, _, _, _, _, _, roll in planned:
        app = existing[name]
        if pool:
            wanted = 0 if roll < 0.08 else 1 + int(roll * 4) % 4  # 0 to 4, mostly 1–3
            weights = [CRITICAL_PULL[t] for _, t in pool]
            chosen = set()
            for _ in range(wanted):
                target_id, _target_tier = rng.choices(pool, weights)[0]
                if target_id != app.id:
                    chosen.add(target_id)
            for target_id in sorted(chosen, key=str):
                kind = rng.choices(KINDS, KIND_WEIGHTS)[0]
                if (app.id, target_id) not in had:
                    had.add((app.id, target_id))
                    new_edges.append(
                        ApplicationDependency(
                            application_id=app.id, depends_on_id=target_id, kind=kind
                        )
                    )
                    added += 1
        pool.append((app.id, tier))
    db.add_all(new_edges)
    db.flush()
    feeds = wire(db, actor_id)["feeds_added"] if _warehouse(db) else 0
    seconds = round(time.perf_counter() - started, 2)
    record_audit_event(db, actor_id=actor_id, action="itops.estate_generated",
                       entity_type="application", entity_id=None,
                       metadata={"seed": seed, "count": count, "created": len(created),
                                 "dependencies": added, "seconds": seconds})  # fmt: skip
    return {"generator": tag, "requested": count, "created": len(created),
            "existing": count - len(created), "dependencies_added": added,
            "warehouse_feeds_added": feeds, "seconds": seconds}  # fmt: skip


def summary(db: Session) -> dict[str, Any]:
    """The estate in numbers: applications by tier, technology and hosting, and dependencies."""

    def grouped(column) -> dict[str, int]:
        return {str(k): n for k, n in db.execute(
            select(column, func.count()).where(Application.status == "active")
            .group_by(column).order_by(func.count().desc())).all()}  # fmt: skip

    total = db.execute(select(func.count()).select_from(Application)
                       .where(Application.status == "active")).scalar_one()  # fmt: skip
    edges = db.execute(select(func.count()).select_from(ApplicationDependency)).scalar_one()
    orphans = db.execute(
        select(func.count()).select_from(Application).where(
            Application.status == "active",
            ~Application.id.in_(select(ApplicationDependency.application_id)),
            ~Application.id.in_(select(ApplicationDependency.depends_on_id)))
    ).scalar_one()  # fmt: skip
    return {
        "applications": total, "dependencies": edges, "unconnected": orphans,
        "generated": db.execute(select(func.count()).select_from(Application)
                                .where(Application.generated_from.is_not(None))).scalar_one(),
        "by_tier": grouped(Application.tier), "by_technology": grouped(Application.technology),
        "by_hosting": grouped(Application.hosting),
    }  # fmt: skip


# --- Wiring (Phase 68, the Milestone E exit) ------------------------------------------------

WAREHOUSE = "Enterprise Data Warehouse"


def _warehouse(db: Session) -> Application | None:
    return db.execute(select(Application).where(Application.name == WAREHOUSE,
                                                Application.status == "active")
                      ).scalar_one_or_none()  # fmt: skip


def wire(db: Session, actor_id: uuid.UUID | None = None) -> dict[str, Any]:
    """Feed the Enterprise Data Warehouse from every application nothing else relies on.

    A generated application relies only on ones generated before it, so the last ones are
    relied on by nothing, and no workflow reaches them unless a step happens to call them.
    The warehouse takes a nightly batch feed from each: every application is then either
    such a top or relied on, directly or not, by one, so a workflow that calls the warehouse
    depends on the whole estate. Batch feeds do not fail calls (Phase 64), so an outage of
    one of these applications stops nothing through the warehouse. Idempotent."""
    warehouse = _warehouse(db)
    if warehouse is None:
        raise NotFoundError(f"No {WAREHOUSE}; it comes with the seeded catalogue.")
    relied_on = {d for _, d in _edges(db)}
    tops = list(db.execute(select(Application).where(
        Application.status == "active", Application.id != warehouse.id,
        Application.id.not_in(relied_on) if relied_on else true())
        .order_by(Application.application_number)).scalars())  # fmt: skip
    for app in tops:
        db.add(ApplicationDependency(application_id=warehouse.id, depends_on_id=app.id,
                                     kind="batch"))  # fmt: skip
    db.flush()
    if tops:
        _audit(db, actor_id, "itops.estate_wired", warehouse, feeds_added=len(tops))
    return {"warehouse": warehouse.application_number, "feeds_added": len(tops)}
