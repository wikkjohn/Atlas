"""Dashboard drill-down (Phase 88): enterprise → country → department → workflow.

Every figure is a query over workflow executions, each attributed to a country, a
department and a workflow:

- **country:** the execution's own input (`country_code`) when it names one; otherwise the
  workflow's catalogue country, when the catalogue gives exactly one (a country variant);
  otherwise none ("Not attributed");
- **department:** the workflow's catalogue department (a stored entry, else the one
  registered in code), or none ("Unclassified");
- **workflow:** the execution's workflow id.

Each level groups the executions under the chosen path by the next dimension. The last
level (a workflow) breaks the executions down by step and by outcome instead.

**Scopes (Phase 84).** A user limited to countries or departments sees only executions
inside the limit. Here an execution *without* the attribute is left out too: a dashboard
total over unattributed work would otherwise be bank-wide.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import String, and_, case, column, func, literal, select, true, values
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation
from app.core.scope import UNRESTRICTED, Scope
from app.modules.countries.models import Country
from app.modules.workflows import registry
from app.modules.workflows.models import (
    ACTIVE_STATUSES,
    ExecutionStatus,
    RunStatus,
    WorkflowCatalogueEntry,
    WorkflowExecution,
    WorkflowStepRun,
)

LEVELS = ("enterprise", "country", "department", "workflow")
NONE = "none"  # the key of the "not attributed" / "unclassified" group
REALMS = ("all", "live", "simulation")
HUMAN_STEPS = ("approval", "human_task")
MAX_GROUPS = 500


@dataclass(frozen=True)
class Path:
    """Where the user is: each element narrows the one before."""

    country: str | None = None
    department: str | None = None
    workflow_id: str | None = None

    @property
    def level(self) -> str:
        if self.workflow_id is not None:
            return "workflow"
        if self.department is not None:
            return "department"
        if self.country is not None:
            return "country"
        return "enterprise"

    @property
    def child(self) -> str | None:
        """The dimension the current level is broken down by."""
        return {"enterprise": "country", "country": "department", "department": "workflow"}.get(
            self.level
        )


def _registered():
    """The catalogue registered in code (WF-0001 to WF-0004 and other code workflows), as an
    inline table: their classification is not stored unless someone overrides it."""
    from app.modules.workflows import catalog  # noqa: F401  (registers the code catalogue)

    rows = [
        (workflow_id, entry.department, entry.countries[0] if len(entry.countries) == 1 else None)
        for workflow_id, entry in sorted(registry.registered_catalogue().items())
    ] or [("", None, None)]  # VALUES needs a row; no workflow id is empty
    return (
        values(
            column("workflow_id", String), column("department", String),
            column("country", String), name="registered",
        )
        .data(rows)
        .alias("registered")
    )  # fmt: skip


def _attributed():
    """Executions with their country and department (a subquery). The classification is
    the stored catalogue entry when there is one, else the one registered in code, as in
    the catalogue itself (PR #79 review)."""
    e, c, r = WorkflowExecution, WorkflowCatalogueEntry, _registered()
    own = func.upper(e.context["input"]["country_code"].astext)
    stored = c.workflow_id.is_not(None)
    single = case(
        (stored, case((func.cardinality(c.countries) == 1, c.countries[1]), else_=None)),
        else_=r.c.country,
    )
    department = case((stored, c.department), else_=r.c.department)
    return (
        select(
            e.id, e.realm, e.workflow_id, e.status, e.outcome, e.started_at, e.completed_at,
            func.coalesce(func.nullif(own, ""), single).label("country"),
            department.label("department"),
        )
        .select_from(e)
        .outerjoin(c, c.workflow_id == e.workflow_id)
        .outerjoin(r, r.c.workflow_id == e.workflow_id)
        .subquery("attributed")
    )  # fmt: skip


def _match(column, value: str | None):
    if value is None:
        return true()
    if value == NONE:
        return column.is_(None)
    return column == value


def _filters(a, path: Path, realm: str, scope: Scope, since: datetime | None) -> list:
    conditions = [
        _match(a.c.country, path.country),
        _match(a.c.department, path.department),
        _match(a.c.workflow_id, path.workflow_id),
    ]
    if realm != "all":
        conditions.append(a.c.realm == realm)
    if since is not None:
        conditions.append(a.c.started_at >= since)
    if scope.countries is not None:
        conditions.append(a.c.country.in_(sorted(scope.countries)))
    if scope.departments is not None:
        conditions.append(a.c.department.in_(sorted(scope.departments)))
    return conditions


def _measures(a) -> list:
    duration = func.extract("epoch", a.c.completed_at - a.c.started_at)
    return [
        func.count().label("executions"),
        func.count().filter(a.c.status == ExecutionStatus.COMPLETED).label("completed"),
        func.count().filter(a.c.status == ExecutionStatus.FAILED).label("failed"),
        func.count().filter(a.c.status.in_(ACTIVE_STATUSES)).label("active"),
        func.avg(duration).filter(a.c.completed_at.is_not(None)).label("avg_duration_s"),
        func.max(a.c.started_at).label("last_started_at"),
    ]


def _row(values: dict[str, Any]) -> dict[str, Any]:
    executions = int(values["executions"] or 0)
    completed = int(values["completed"] or 0)
    failed = int(values["failed"] or 0)
    finished = completed + failed
    avg = values["avg_duration_s"]
    last = values["last_started_at"]
    return {
        "executions": executions,
        "completed": completed,
        "failed": failed,
        "active": int(values["active"] or 0),
        "failure_rate": round(failed / finished, 4) if finished else None,
        "avg_duration_s": round(float(avg), 3) if avg is not None else None,
        "last_started_at": last.isoformat() if last else None,
    }


def _open_tasks(db: Session, a, conditions: list, group=None) -> dict[Any, int]:
    """Waiting approvals and human tasks, by group (or the one total under key None)."""
    s = WorkflowStepRun
    key = group if group is not None else literal(None)
    rows = db.execute(
        select(key.label("key"), func.count())
        .select_from(s)
        .join(a, and_(a.c.id == s.execution_id, a.c.realm == s.realm))
        .where(*conditions, s.status == RunStatus.WAITING, s.step_type.in_(HUMAN_STEPS))
        .group_by(key)
    ).all()
    return {k: int(n) for k, n in rows}


def _labels(db: Session, dimension: str, keys: list[str | None]) -> dict[str | None, str]:
    labels: dict[str | None, str] = {None: "Not attributed" if dimension == "country"
                                     else "Unclassified" if dimension == "department"
                                     else "Unknown"}  # fmt: skip
    real = [k for k in keys if k is not None]
    if dimension == "country" and real:
        labels |= dict(
            db.execute(
                select(Country.iso_country_code, Country.country_name).where(
                    Country.iso_country_code.in_(real)
                )
            ).all()
        )
    elif dimension == "workflow" and real:
        from app.modules.workflows.models import WorkflowDefinitionRecord as D

        latest = (
            select(D.workflow_id, D.name, func.row_number().over(
                partition_by=D.workflow_id, order_by=D.version.desc()).label("n"))
            .where(D.workflow_id.in_(real)).subquery()
        )  # fmt: skip
        labels |= dict(
            db.execute(select(latest.c.workflow_id, latest.c.name).where(latest.c.n == 1)).all()
        )
    return labels


def _check_path(path: Path) -> None:
    if path.department is not None and path.country is None:
        raise BusinessRuleViolation("Choose a country before a department (or 'none').")
    if path.workflow_id is not None and path.department is None:
        raise BusinessRuleViolation("Choose a department before a workflow (or 'none').")


def drilldown(
    db: Session, path: Path, *, realm: str = "all", days: int | None = None,
    scope: Scope = UNRESTRICTED, now: datetime | None = None,
) -> dict[str, Any]:  # fmt: skip
    """The figures for one place in the hierarchy and its breakdown one level down."""
    if realm not in REALMS:
        raise BusinessRuleViolation(f"realm must be one of {', '.join(REALMS)}.")
    _check_path(path)
    now = now or datetime.now(UTC)
    since = now - timedelta(days=days) if days else None
    a = _attributed()
    conditions = _filters(a, path, realm, scope, since)

    totals = db.execute(select(*_measures(a)).where(*conditions)).one()._mapping
    summary = _row(dict(totals)) | {"open_tasks": _open_tasks(db, a, conditions).get(None, 0)}
    result: dict[str, Any] = {
        "level": path.level,
        "path": _breadcrumbs(db, path),
        "realm": realm,
        "days": days,
        "generated_at": now.isoformat(),
        "scope": scope.describe() if scope.limited else None,
        "summary": summary,
        "breakdown_by": path.child,
        "breakdown": [],
        "steps": None,
        "outcomes": None,
        "attribution": ATTRIBUTION,
    }
    if path.child is not None:
        column = {"country": a.c.country, "department": a.c.department,
                  "workflow": a.c.workflow_id}[path.child]  # fmt: skip
        rows = db.execute(
            select(column.label("key"), *_measures(a))
            .where(*conditions)
            .group_by(column)
            .order_by(func.count().desc(), column)
            .limit(MAX_GROUPS)
        ).all()
        tasks = _open_tasks(db, a, conditions, column)
        labels = _labels(db, path.child, [r.key for r in rows])
        result["breakdown"] = [
            {
                "key": r.key if r.key is not None else NONE,
                "label": labels.get(r.key, r.key),
                **_row(dict(r._mapping)),
                "open_tasks": tasks.get(r.key, 0),
            }
            for r in rows
        ]
        result["truncated"] = len(rows) == MAX_GROUPS
    else:
        result["steps"] = _steps(db, a, conditions)
        result["outcomes"] = {
            (k or "none"): int(n)
            for k, n in db.execute(
                select(a.c.outcome, func.count()).where(*conditions)
                .group_by(a.c.outcome).order_by(func.count().desc())
            ).all()
        }  # fmt: skip
    return result


def _steps(db: Session, a, conditions: list) -> list[dict[str, Any]]:
    """Per step of the workflow: runs, failures, waiting work and time taken."""
    s = WorkflowStepRun
    rows = db.execute(
        select(
            s.step_id, s.step_type,
            func.count().label("runs"),
            func.count().filter(s.status == RunStatus.FAILED).label("failed"),
            func.count().filter(s.status == RunStatus.WAITING).label("waiting"),
            func.avg(s.duration_ms).filter(s.status == RunStatus.COMPLETED).label("avg_ms"),
            func.percentile_cont(0.95).within_group(s.duration_ms)
            .filter(s.status == RunStatus.COMPLETED).label("p95_ms"),
            func.min(s.sequence).label("first"),
        )
        .select_from(s)
        .join(a, and_(a.c.id == s.execution_id, a.c.realm == s.realm))
        .where(*conditions)
        .group_by(s.step_id, s.step_type)
        .order_by(func.min(s.sequence), s.step_id)
    ).all()  # fmt: skip
    return [
        {
            "step_id": r.step_id,
            "step_type": r.step_type,
            "runs": int(r.runs),
            "failed": int(r.failed),
            "waiting": int(r.waiting),
            "avg_ms": round(float(r.avg_ms), 1) if r.avg_ms is not None else None,
            "p95_ms": round(float(r.p95_ms), 1) if r.p95_ms is not None else None,
        }
        for r in rows
    ]


def _breadcrumbs(db: Session, path: Path) -> list[dict[str, str]]:
    crumbs = [{"level": "enterprise", "key": "enterprise", "label": "ATLAS Global Bank"}]
    for level, value in (("country", path.country), ("department", path.department),
                         ("workflow", path.workflow_id)):  # fmt: skip
        if value is None:
            break
        key = None if value == NONE else value
        crumbs.append({"level": level, "key": value,
                       "label": _labels(db, level, [key]).get(key, value)})  # fmt: skip
    return crumbs


ATTRIBUTION = {
    "country": "The execution's input country_code; else the catalogue's single country; "
    "else not attributed.",
    "department": "The workflow's catalogue department; else unclassified.",
    "scoped_users": "Executions without the scoped attribute are left out.",
}
