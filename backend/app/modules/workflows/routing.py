"""Who a task goes to (Phase 71, roadmap Milestone F step 3).

Until Phase 71 every open task sat in a shared queue: anyone with the step's permissions who
passed the four-eyes rule could take it. A step's approval policy may now name an assignment
rule, and the task is then given to one person, who alone may complete it:

- ``least_loaded``: the qualified person with the fewest open assigned tasks (ties go to the
  username, so the choice is repeatable);
- ``initiator_manager``: the initiator's line manager, found through the employee records
  (``users.employee_id`` and ``employees.manager_id``), or the next manager up who is
  qualified; else the least loaded.

"Qualified" means what it always did: an active person (not a service account) whose role
holds the step's permissions and who passes the four-eyes rule.

Two things can hand an assigned task on:

- **delegation:** an out-of-office period (``task_delegations``) sends new tasks for a person
  to their delegate while it runs; the assignee (or a workflow manager) can also hand an open
  task to another qualified person;
- **escalation:** a timeout with ``action: escalate`` gives the overdue task to the
  assignee's manager (the initiator's when nobody was assigned); with no qualified manager it
  is flagged overdue, as before.

Routing applies to live cases only. Simulated cases keep their own reviewer model (Phases 5
and 70), so simulation results do not change.
"""

import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.permissions import ROLE_PERMISSIONS, Permission, RoleCode, permissions_for
from app.core.security import UNUSABLE_PASSWORD_HASH
from app.modules.employees.models import Employee
from app.modules.identity.models import Role, User
from app.modules.identity.service import AuthenticatedUser
from app.modules.workflows.definition import StepDefinition
from app.modules.workflows.models import (
    RunStatus,
    TaskDelegation,
    WorkflowExecution,
    WorkflowStepRun,
)

MAX_CHAIN = 12  # how far up the management chain to look


def principal(user: User) -> AuthenticatedUser:
    """The person as the engine sees a caller."""
    return AuthenticatedUser(
        id=user.id,
        username=user.username,
        role=user.role.code,
        permissions=permissions_for(user.role.code),
    )


def _roles_with(db: Session, permissions: list[str]) -> list[uuid.UUID]:
    wanted = {Permission(p) for p in permissions}
    codes = [r.value for r, granted in ROLE_PERMISSIONS.items() if wanted <= granted]
    return list(db.execute(select(Role.id).where(Role.code.in_(codes))).scalars())


def _people(db: Session):
    return select(User).where(User.is_active.is_(True),
                              User.password_hash != UNUSABLE_PASSWORD_HASH)  # fmt: skip


def excluded(db: Session, execution: WorkflowExecution, step: StepDefinition) -> set[uuid.UUID]:
    """Who the four-eyes rule rules out for this step of this case."""
    assert step.approval is not None
    out: set[uuid.UUID] = set()
    steps = [r for r in step.approval.distinct_from if r != "initiator"]
    if "initiator" in step.approval.distinct_from:
        out.add(execution.initiated_by)
    if steps:
        db.flush()
        out |= {a for a in db.execute(select(WorkflowStepRun.actor_id).where(
            WorkflowStepRun.execution_id == execution.id,
            WorkflowStepRun.step_id.in_(steps),
            WorkflowStepRun.status == RunStatus.COMPLETED)).scalars() if a}  # fmt: skip
    return out


def is_qualified(
    db: Session, execution: WorkflowExecution, step: StepDefinition, user: User
) -> bool:
    assert step.approval is not None
    if not user.is_active or user.password_hash == UNUSABLE_PASSWORD_HASH:
        return False
    granted = permissions_for(user.role.code)
    if not {Permission(p) for p in step.approval.permissions} <= granted:
        return False
    return user.id not in excluded(db, execution, step)


def open_load(db: Session, user_ids: list[uuid.UUID] | None = None) -> dict[uuid.UUID, int]:
    """Open assigned tasks per person."""
    query = (
        select(WorkflowStepRun.assignee_id, func.count())
        .where(
            WorkflowStepRun.status == RunStatus.WAITING, WorkflowStepRun.assignee_id.is_not(None)
        )  # fmt: skip
        .group_by(WorkflowStepRun.assignee_id)
    )
    if user_ids is not None:
        query = query.where(WorkflowStepRun.assignee_id.in_(user_ids))
    return dict(db.execute(query).all())


def candidates(
    db: Session, execution: WorkflowExecution, step: StepDefinition
) -> list[tuple[User, int]]:
    """Everyone qualified for this task with their open assigned tasks, least loaded first
    (ties by username, so the order is repeatable)."""
    assert step.approval is not None
    roles = _roles_with(db, step.approval.permissions)
    if not roles:
        return []
    ruled_out = excluded(db, execution, step)
    people = [u for u in db.execute(_people(db).where(User.role_id.in_(roles))).scalars()
              if u.id not in ruled_out]  # fmt: skip
    load = open_load(db, [u.id for u in people]) if people else {}
    ranked = sorted(people, key=lambda u: (load.get(u.id, 0), u.username))
    return [(u, load.get(u.id, 0)) for u in ranked]


def least_loaded(db: Session, execution: WorkflowExecution, step: StepDefinition) -> User | None:
    ranked = candidates(db, execution, step)
    return ranked[0][0] if ranked else None


def managers(db: Session, user_id: uuid.UUID | None) -> list[User]:
    """The person's managers, nearest first, who have user accounts."""
    user = db.get(User, user_id) if user_id else None
    employee = db.get(Employee, user.employee_id) if user and user.employee_id else None
    chain: list[User] = []
    seen: set[uuid.UUID] = set()
    while employee is not None and employee.manager_id and len(seen) < MAX_CHAIN:
        if employee.manager_id in seen:
            break
        seen.add(employee.manager_id)
        employee = db.get(Employee, employee.manager_id)
        if employee is None:
            break
        account = db.execute(_people(db).where(User.employee_id == employee.id)).scalars().first()
        if account is not None:
            chain.append(account)
    return chain


def qualified_manager(
    db: Session, execution: WorkflowExecution, step: StepDefinition, user_id: uuid.UUID | None
) -> User | None:
    return next((m for m in managers(db, user_id) if is_qualified(db, execution, step, m)), None)


def active_delegation(db: Session, user_id: uuid.UUID, day: date) -> TaskDelegation | None:
    return (
        db.execute(
            select(TaskDelegation)
            .where(
                TaskDelegation.user_id == user_id,
                TaskDelegation.starts_on <= day,
                TaskDelegation.ends_on >= day,
            )  # fmt: skip
            .order_by(TaskDelegation.created_at.desc())
        )
        .scalars()
        .first()
    )


def choose(
    db: Session, execution: WorkflowExecution, step: StepDefinition, day: date
) -> tuple[User | None, User | None, str | None]:
    """(assignee, the person it would have gone to before a delegation, the rule used)."""
    assert step.approval is not None and step.approval.assign is not None
    chosen, rule = None, step.approval.assign
    if rule == "initiator_manager":
        chosen = qualified_manager(db, execution, step, execution.initiated_by)
        if chosen is None:
            rule = "least_loaded"
    if chosen is None:
        chosen = least_loaded(db, execution, step)
    if chosen is None:
        return None, None, None
    return (*follow_delegation(db, execution, step, chosen, day), rule)


def follow_delegation(
    db: Session, execution: WorkflowExecution, step: StepDefinition, user: User, day: date
) -> tuple[User, User | None]:
    """The person's delegate while they are away (when the delegate may do the task)."""
    away = active_delegation(db, user.id, day)
    if away is None:
        return user, None
    delegate = db.get(User, away.delegate_id)
    if delegate is None or not is_qualified(db, execution, step, delegate):
        return user, None
    return delegate, user


def is_manager_role(role: str) -> bool:
    return Permission.WORKFLOWS_MANAGE in ROLE_PERMISSIONS.get(RoleCode(role), frozenset())
