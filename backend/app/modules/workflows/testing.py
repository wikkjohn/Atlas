"""Generated path tests for stored workflow definitions (Phase 20).

Every stored definition — hand-written or generated from a template — gets test cases
derived from its graph, run through the real engine:

- **happy**: the default input, every approval approved;
- **route**: one case per route (a transition, a fallback `next`, an `on_failure`, a
  timeout), planned along the shortest path that ends with it;
- **approval**: at each approval, the initiator (four-eyes) and a person without the
  permissions are refused before an authorised colleague decides.

Planning a route turns the conditions along its path into requirements: an input value (a
condition on `input.*`), an approval decision (`<approval>.approved`), an output field of
a service step (added to that step's real output), a signal payload, or a failure injected
at a step (an `on_failure` route). Input values are synthesised from the input JSON Schema
(`examples`, `enum`, bounds, simple patterns); fields that library handlers look up get
real synthetic records — a customer, an account with funds — created for the case.

Each case runs in a savepoint that is rolled back, so testing leaves nothing behind but
the run's record. A case passes when the execution ends at a completion or failure step
(not stalled, unrouted or crashed), visits the steps of its planned path, ends with an
outcome the definition declares, never moves money without a granted approval, and (for
approval cases) the refusals happen. Routes no case could be planned for are reported as
uncovered, with the reason.
"""

import itertools
import re
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import DomainError, PermissionDeniedError
from app.core.permissions import ROLE_PERMISSIONS, SERVICE_ROLES, RoleCode, permissions_for
from app.modules.identity.models import User
from app.modules.identity.service import AuthenticatedUser, get_role
from app.modules.workflows import engine, library, store
from app.modules.workflows.definition import (
    Condition,
    StepDefinition,
    StepType,
    WorkflowDefinition,
)
from app.modules.workflows.models import (
    ExecutionStatus,
    RunStatus,
    WorkflowDefinitionRecord,
    WorkflowExecution,
    WorkflowStepRun,
    WorkflowTestRun,
)

MAX_DRIVE_ROUNDS = 60
BAD_ENDINGS = frozenset({"no_route", "stalled", "unexpected_error", "handler_missing"})
UNUSABLE_PASSWORD = "!generated-test-user"  # not a password hash: nobody can sign in


class Infeasible(Exception):
    """A route's requirements cannot be met by planning (reported as uncovered)."""


# --- The graph ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Route:
    source: str
    target: str
    kind: Literal["transition", "next", "failure", "timeout", "branch", "join"]
    index: int = 0  # the transition's position

    @property
    def label(self) -> str:
        extra = f"[{self.index}]" if self.kind == "transition" else ""
        return f"{self.source} → {self.target} ({self.kind}{extra})"


def routes(d: WorkflowDefinition) -> list[Route]:
    out: list[Route] = []
    for s in d.steps:
        for i, t in enumerate(s.transitions):
            out.append(Route(s.id, t.to, "transition", i))
        if s.next:
            out.append(Route(s.id, s.next, "next"))
        if s.on_failure:
            out.append(Route(s.id, s.on_failure, "failure"))
        if s.timeout and s.timeout.to:
            out.append(Route(s.id, s.timeout.to, "timeout"))
        for b in s.branches:
            out.append(Route(s.id, b, "branch"))
        if s.join:
            out.append(Route(s.id, s.join, "join"))
    return list(dict.fromkeys(out))


def _path_to(d: WorkflowDefinition, target: str) -> list[Route] | None:
    """The shortest sequence of routes from the start to `target`."""
    if target == d.start:
        return []
    outgoing: dict[str, list[Route]] = {}
    for r in routes(d):
        outgoing.setdefault(r.source, []).append(r)
    parent: dict[str, Route] = {}
    queue, seen = deque([d.start]), {d.start}
    while queue:
        current = queue.popleft()
        for r in outgoing.get(current, []):
            if r.target in seen:
                continue
            seen.add(r.target)
            parent[r.target] = r
            if r.target == target:
                path = [r]
                while path[0].source != d.start:
                    path.insert(0, parent[path[0].source])
                return path
            queue.append(r.target)
    return None


# --- Requirements ---------------------------------------------------------------------------


@dataclass
class Plan:
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)  # service steps
    forms: dict[str, dict[str, Any]] = field(default_factory=dict)  # human tasks
    signals: dict[str, dict[str, Any]] = field(default_factory=dict)  # waits
    decisions: dict[str, str] = field(default_factory=dict)  # approvals
    fail: set[str] = field(default_factory=set)
    timeouts: set[str] = field(default_factory=set)
    mocked: list[str] = field(default_factory=list)
    # Conditions gathered along the path, solved together by `resolve`:
    # (table, step, field) -> [(predicate, hints)].
    wanted: dict[tuple[str, str, str], list[tuple[Any, list[Any]]]] = field(default_factory=dict)

    def put(self, table: dict, key: str, value: Any) -> None:
        if key in table and table[key] != value:
            raise Infeasible(f"needs {key} to be both {table[key]!r} and {value!r}")
        table[key] = value

    def want(self, where: tuple[str, str, str], predicate, hints: list[Any]) -> None:
        self.wanted.setdefault(where, []).append((predicate, hints))

    def resolve(self, d: WorkflowDefinition) -> "Plan":
        """Choose one value per field that satisfies every condition on it."""
        properties = d.input_schema.get("properties") or {}
        for (table, step, name), conditions in self.wanted.items():
            hints = [h for _, found in conditions for h in found]
            prop = properties.get(name, {}) if table == "inputs" else {}
            extra = [] if table == "inputs" else [True, False, 0, 1, "x"]
            value = _pick(prop, lambda v, cs=conditions: all(p(v) for p, _ in cs), hints + extra)
            if table == "inputs":
                self.put(self.inputs, name, value)
                continue
            target = getattr(self, table).setdefault(step, {})
            self.put(target, name, value)
            if table == "outputs":
                self.mocked.append(f"{step}.{name}={value!r}")
        self.wanted.clear()
        return self


def _candidates(prop: dict[str, Any], hints: list[Any]) -> list[Any]:
    found: list[Any] = [*hints]
    found += list(prop.get("examples") or [])
    found += list(prop.get("enum") or [])
    kind = prop.get("type")
    if kind == "boolean":
        found += [True, False]
    if kind in ("integer", "number"):
        low, high = prop.get("minimum", 1), prop.get("maximum", 1_000_000)
        found += [low, high, (low + high) // 2, low + 1, 0, 1]
        found += [h + 1 for h in hints if isinstance(h, int | float)]
        found += [h - 1 for h in hints if isinstance(h, int | float)]
    if kind == "string" or kind is None:
        found += [_from_pattern(prop.get("pattern"), prop.get("minLength", 1)), "ZZ", "XX"]
        found += [f"{h}x" for h in hints if isinstance(h, str)]
    return [c for c in found if c is not None]


def _valid(prop: dict[str, Any], value: Any) -> bool:
    return not list(Draft202012Validator(prop, format_checker=FormatChecker()).iter_errors(value))


def _pick(prop: dict[str, Any], predicate, hints: list[Any]) -> Any:
    for value in _candidates(prop, hints):
        try:
            if _valid(prop, value) and predicate(value):
                return value
        except TypeError:
            continue
    raise Infeasible("no input value satisfies the condition and the schema")


def _leaf_test(op: str, expected: Any):
    def check(value: Any) -> bool:
        return Condition(path="v", op=op, value=expected).evaluate({"v": value})

    return check


def _require(
    plan: Plan, d: WorkflowDefinition, condition: Condition, want: bool, fixtures: set[str]
) -> None:
    """Add what makes `condition` evaluate to `want`."""
    want = want != condition.negate
    if condition.all is not None:
        if want:
            for c in condition.all:
                _require(plan, d, c, True, fixtures)
        else:
            _require(plan, d, condition.all[0], False, fixtures)
        return
    if condition.any is not None:
        if want:
            _require(plan, d, condition.any[0], True, fixtures)
        else:
            for c in condition.any:
                _require(plan, d, c, False, fixtures)
        return
    root, _, rest = (condition.path or "").partition(".")
    field_name, _, deeper = rest.partition(".")
    op, expected = condition.op or "eq", condition.value
    satisfied = _leaf_test(op, expected)

    def predicate(value: Any) -> bool:
        return satisfied(value) == want

    hints = list(expected) if isinstance(expected, list) else [expected]
    if root == "input":
        if deeper:
            raise Infeasible(f"cannot steer the nested input path '{condition.path}'")
        if f"input.{field_name}" in fixtures:
            raise Infeasible(f"'{condition.path}' is a looked-up record, not a free value")
        if op == "exists" and not want:
            plan.put(plan.inputs, field_name, _ABSENT)
            return
        plan.want(("inputs", "", field_name), predicate, hints)
        return
    step = next((s for s in d.steps if s.id == root), None)
    if step is None or deeper:
        raise Infeasible(f"cannot steer '{condition.path}'")
    if step.type == StepType.APPROVAL:
        if field_name == "approved" or field_name == "decision":
            approve = predicate(True if field_name == "approved" else "approve")
            plan.put(plan.decisions, step.id, "approve" if approve else "reject")
            return
        raise Infeasible(f"cannot steer the approval field '{condition.path}'")
    table = (
        "forms"
        if step.type == StepType.HUMAN_TASK
        else "signals"
        if step.type == StepType.WAIT
        else "outputs"
    )
    plan.want((table, step.id, field_name), predicate, hints)


def plan_for(d: WorkflowDefinition, path: list[Route], fixtures: set[str]) -> Plan:
    plan = Plan()
    by_id = {s.id: s for s in d.steps}
    for route in path:
        step = by_id[route.source]
        if route.kind == "failure":
            plan.fail.add(step.id)
            continue
        if route.kind == "timeout":
            plan.timeouts.add(step.id)
            continue
        if step.type in (StepType.SERVICE_TASK, StepType.AI_TASK):
            _check_requirements(plan, d, step, fixtures)
        if route.kind == "transition":
            for earlier in step.transitions[: route.index]:
                if earlier.when is not None:
                    _require(plan, d, earlier.when, False, fixtures)
            when = step.transitions[route.index].when
            if when is not None:
                _require(plan, d, when, True, fixtures)
        elif route.kind == "next" and step.transitions:
            for t in step.transitions:
                if t.when is None:
                    raise Infeasible(f"'{step.id}' always takes an unconditional transition")
                _require(plan, d, t.when, False, fixtures)
    return plan.resolve(d)


def _check_requirements(plan: Plan, d: WorkflowDefinition, step: StepDefinition, fx) -> None:
    """A `core.check` passed on the way: its condition must hold."""
    if step.handler == "core.check" and step.id not in plan.fail:
        condition = Condition.model_validate((step.params or {}).get("condition"))
        _require(plan, d, condition, True, fx)


_ABSENT = object()


# --- Input synthesis --------------------------------------------------------------------------


def _from_pattern(pattern: str | None, min_length: int = 1) -> str | None:
    """A string matching a simple pattern (anchors, literals, [classes], \\d, quantifiers)."""
    if not pattern:
        return "Test value"[: max(min_length, 10)].ljust(min_length, "x")
    body = pattern.removeprefix("^").removesuffix("$")
    out, i = [], 0
    while i < len(body):
        ch = body[i]
        if ch == "[":
            end = body.index("]", i)
            klass = body[i + 1 : end]
            sample = klass[0] if klass[0] != "^" else None
            if sample is None:
                return None
            i = end + 1
        elif ch == "\\" and i + 1 < len(body):
            sample = {"d": "0", "w": "a", "s": " "}.get(body[i + 1], body[i + 1])
            i += 2
        elif ch in "().|*+?{":
            return None if ch in "()|" else None
        else:
            sample, i = ch, i + 1
        count = 1
        if i < len(body) and body[i] == "{":
            end = body.index("}", i)
            low = body[i + 1 : end].split(",")[0]
            count, i = int(low), end + 1
        elif i < len(body) and body[i] in "+":
            i += 1
        elif i < len(body) and body[i] in "*?":
            count, i = 0, i + 1
        out.append(sample * count)
    value = "".join(out)
    return value if re.fullmatch(pattern, value) else None


def synthesize(
    d: WorkflowDefinition, plan: Plan, fixture_values: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    schema = d.input_schema
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    payload: dict[str, Any] = {}
    problems: list[str] = []
    for name, prop in properties.items():
        if f"input.{name}" in fixture_values:
            payload[name] = fixture_values[f"input.{name}"]
        elif name in plan.inputs:
            if plan.inputs[name] is not _ABSENT:
                payload[name] = plan.inputs[name]
        elif name in required:
            try:
                payload[name] = _pick(prop, lambda v: True, [])
            except Infeasible:
                problems.append(f"no value for required input '{name}'; add `examples`")
    errors = Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload)
    problems += [f"input {'.'.join(map(str, e.absolute_path)) or ''}: {e.message}" for e in errors]
    return payload, problems


def fixture_needs(d: WorkflowDefinition) -> dict[str, str]:
    """{context path: fixture kind} the definition's library handlers look up."""
    needs: dict[str, str] = {}
    for step in d.steps:
        handler = library.get(step.handler or "")
        if handler is None or handler.fixtures is None:
            continue
        try:
            params = handler.params_model.model_validate(step.params or {})
        except Exception:  # noqa: BLE001 - validation reports bad params; skip them here
            continue
        needs.update({p: k for p, k in handler.fixtures(params).items() if p.startswith("input.")})
    return needs


# --- Cases ----------------------------------------------------------------------------------


@dataclass
class Case:
    name: str
    kind: Literal["happy", "route", "approval"]
    route: Route | None
    path: list[Route]
    plan: Plan
    check_approvals: bool = False


@dataclass
class CaseResult:
    name: str
    kind: str
    route: str | None
    status: Literal["passed", "failed", "skipped"]
    detail: str = ""
    outcome: str | None = None
    visited: list[str] = field(default_factory=list)
    mocked: list[str] = field(default_factory=list)
    ms: int = 0

    def as_json(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


def generate_cases(d: WorkflowDefinition) -> tuple[list[Case], list[dict[str, str]]]:
    fixtures = set(fixture_needs(d))
    cases: list[Case] = [Case("happy path", "happy", None, [], Plan())]
    uncovered: list[dict[str, str]] = []
    seen_plans: set[str] = set()
    for route in routes(d):
        path = _path_to(d, route.source)
        if path is None:
            uncovered.append({"route": route.label, "reason": "its step is unreachable"})
            continue
        try:
            plan = plan_for(d, [*path, route], fixtures)
        except Infeasible as exc:
            uncovered.append({"route": route.label, "reason": str(exc)})
            continue
        key = repr(sorted(plan.__dict__.items(), key=str)) + route.label
        if key in seen_plans:
            continue
        seen_plans.add(key)
        cases.append(Case(f"route {route.label}", "route", route, [*path, route], plan))
    for step in d.steps:
        # A probe: can an input reach this step and match none of its routes?
        if step.transitions and not step.next and all(t.when for t in step.transitions):
            path = _path_to(d, step.id)
            if path is not None:
                try:
                    plan = plan_for(d, path, fixtures)
                    for t in step.transitions:
                        _require(plan, d, t.when, False, fixtures)
                    plan.resolve(d)
                except Infeasible:
                    pass  # no input can: the routes are exhaustive as far as planning sees
                else:
                    cases.append(Case(f"no-route probe at {step.id}", "route", None, path, plan))
        if step.type == StepType.APPROVAL:
            path = _path_to(d, step.id)
            if path is None:
                continue
            try:
                plan = plan_for(d, path, fixtures)
            except Infeasible as exc:
                uncovered.append({"route": f"approval {step.id}", "reason": str(exc)})
                continue
            cases.append(Case(f"approval {step.id}: refusals", "approval", None, path, plan, True))
    return cases, uncovered


# --- Running --------------------------------------------------------------------------------


@dataclass
class Fixtures:
    initiator: AuthenticatedUser
    approvers: dict[str, AuthenticatedUser]
    outsider: AuthenticatedUser
    values: dict[str, Any]


def _person(db: Session, role: RoleCode) -> AuthenticatedUser:
    tag = uuid.uuid4().hex[:10]
    user = User(
        username=f"wftest-{tag}",
        email=f"wftest-{tag}@atlasbank.example",
        display_name=f"Generated test {role.value}",
        password_hash=UNUSABLE_PASSWORD,
        role_id=get_role(db, role).id,
        is_active=True,
    )
    db.add(user)
    db.flush()
    return AuthenticatedUser(
        id=user.id, username=user.username, role=role.value, permissions=permissions_for(role)
    )


def _role_for(permissions: list[str]) -> RoleCode:
    preference = [
        RoleCode.DEPARTMENT_MANAGER,
        RoleCode.COMPLIANCE_OFFICER,
        RoleCode.BANKING_EMPLOYEE,
        RoleCode.GLOBAL_EXECUTIVE,
        RoleCode.REGIONAL_EXECUTIVE,
        RoleCode.AI_RESEARCHER,
        RoleCode.AUDITOR,
        RoleCode.PLATFORM_ADMINISTRATOR,
    ]
    for role in preference:
        granted = {p.value for p in ROLE_PERMISSIONS[role]}
        if role not in SERVICE_ROLES and set(permissions) <= granted:
            return role
    return RoleCode.PLATFORM_ADMINISTRATOR


def _fixtures(db: Session, d: WorkflowDefinition, needs: dict[str, str]) -> Fixtures:
    approvers = {
        s.id: _person(db, _role_for(s.approval.permissions))
        for s in d.steps
        if s.approval is not None
    }
    values: dict[str, Any] = {}
    kinds = set(needs.values())
    if kinds:
        customer, account = _customer_and_account(db, "account.account_number" in kinds)
        known = {
            "customer.customer_number": customer.customer_number,
            "customer.name": customer.name,
            "customer.id": str(customer.id),
            "account.account_number": account.account_number if account else None,
        }
        values = {path: known[kind] for path, kind in needs.items()}
    return Fixtures(
        initiator=_person(db, RoleCode.BANKING_EMPLOYEE),
        approvers=approvers,
        outsider=_person(db, RoleCode.AUDITOR),
        values=values,
    )


def _customer_and_account(db: Session, with_account: bool):
    from app.modules.accounts.models import AccountType
    from app.modules.accounts.service import approve_request, deposit, submit_request
    from app.modules.countries.models import Country
    from app.modules.customers.models import CustomerType, KycStatus, RiskRating
    from app.modules.customers.schemas import CustomerCreate, CustomerReview
    from app.modules.customers.service import create_customer, review_customer

    country = db.execute(select(Country).where(Country.iso_country_code == "GB")).scalar_one()
    customer = create_customer(
        db,
        CustomerCreate(
            customer_type=CustomerType.INDIVIDUAL,
            name=f"Generated Test {uuid.uuid4().hex[:6].upper()}",
            date_of_birth_or_incorporation=date(1985, 6, 15),
            country_id=country.id,
        ),
        actor_id=None,
    )
    review_customer(db, customer, CustomerReview(kyc_status=KycStatus.PENDING), None)
    review_customer(
        db,
        customer,
        CustomerReview(kyc_status=KycStatus.VERIFIED, risk_rating=RiskRating.LOW),
        None,
    )
    if not with_account:
        return customer, None
    clerk, manager = (
        _person(db, RoleCode.BANKING_EMPLOYEE),
        _person(db, RoleCode.DEPARTMENT_MANAGER),
    )
    request = submit_request(
        db,
        customer_id=customer.id,
        account_type=AccountType.CURRENT,
        currency=None,
        requested_by=clerk.id,
    )
    account = approve_request(db, request.id, manager)
    deposit(
        db,
        account.id,
        amount=1_000_000,
        memo="Generated test funds",
        idempotency_key=f"wftest-{account.id}",
        actor_id=clerk.id,
    )
    return customer, account


def _form_data(step: StepDefinition, forced: dict[str, Any]) -> dict[str, Any]:
    defaults = {"string": "Generated test", "integer": 1, "boolean": True}
    return {f.name: forced.get(f.name, defaults[f.type]) for f in step.form if f.required} | forced


def _runs(db: Session, execution: WorkflowExecution) -> list[WorkflowStepRun]:
    db.flush()
    return list(
        db.execute(
            select(WorkflowStepRun)
            .where(WorkflowStepRun.execution_id == execution.id)
            .order_by(WorkflowStepRun.sequence)
        ).scalars()
    )


def _drive(
    db: Session,
    d: WorkflowDefinition,
    execution: WorkflowExecution,
    case: Case,
    fx: Fixtures,
    now: datetime,
    notes: list[str],
) -> datetime:
    by_id = {s.id: s for s in d.steps}
    for _ in range(MAX_DRIVE_ROUNDS):
        if execution.status not in (ExecutionStatus.RUNNING, ExecutionStatus.WAITING):
            return now
        runs = _runs(db, execution)
        waiting = [r for r in runs if r.status == RunStatus.WAITING]
        if not waiting:
            # Pending steps wait for a retry back-off: move the clock past it.
            due = [r.not_before for r in runs if r.status == RunStatus.PENDING and r.not_before]
            now = max([now, *due])
            engine.advance(db, execution.id, now=now)
            continue
        run = waiting[0]
        step = by_id[run.step_id]
        if step.id in case.plan.timeouts and step.timeout and run.escalated_at is None:
            now = now + timedelta(seconds=step.timeout.after_seconds + 1)
            engine.process_timers(db, execution, now)
            if step.timeout.action == "flag":
                db.refresh(run)
                if run.escalated_at is None:
                    raise AssertionError(f"'{step.id}' was not flagged overdue after its timeout")
                notes.append(f"{step.id} flagged overdue")
            continue
        if step.type == StepType.APPROVAL:
            if case.check_approvals and step.approval is not None:
                _check_refusals(db, run, step, fx, now, notes)
            decision = case.plan.decisions.get(step.id, "approve")
            engine.complete_task(
                db, run.id, fx.approvers[step.id], decision=decision, note="Generated test", now=now
            )
        elif step.type == StepType.HUMAN_TASK:
            engine.complete_task(
                db,
                run.id,
                fx.approvers[step.id],
                data=_form_data(step, case.plan.forms.get(step.id, {})),
                now=now,
            )
        elif step.type == StepType.WAIT:
            if step.signal:
                engine.signal(
                    db,
                    execution.id,
                    step.signal,
                    case.plan.signals.get(step.id, {}),
                    fx.initiator.id,
                    now=now,
                )
            else:
                now = now + timedelta(
                    seconds=(step.timeout.after_seconds if step.timeout else 0) + 1
                )
                engine.process_timers(db, execution, now)
    raise AssertionError(f"the case did not finish within {MAX_DRIVE_ROUNDS} rounds")


def _check_refusals(db, run, step, fx: Fixtures, now, notes: list[str]) -> None:
    attempts = [("a person without its permissions", fx.outsider)]
    if "initiator" in step.approval.distinct_from:
        attempts.insert(0, ("the initiator (four-eyes)", fx.initiator))
    for who, actor in attempts:
        try:
            with db.begin_nested():
                engine.complete_task(db, run.id, actor, decision="approve", now=now)
        except PermissionDeniedError:
            notes.append(f"{step.id}: refused {who}")
            continue
        raise AssertionError(f"'{step.id}' let {who} approve")


def _declared_outcomes(d: WorkflowDefinition) -> set[str | None]:
    outcomes: set[str | None] = {"failed", "cancelled"}
    for s in d.steps:
        if s.type in (StepType.COMPLETION, StepType.FAILURE):
            outcomes.add(s.outcome)
        if s.handler == "core.set_outcome":
            outcomes.add((s.params or {}).get("outcome"))
    return outcomes


def run_case(db: Session, d: WorkflowDefinition, case: Case, fx: Fixtures) -> CaseResult:
    started = time.perf_counter()
    result = CaseResult(
        case.name,
        case.kind,
        case.route.label if case.route else None,
        "passed",
        mocked=list(case.plan.mocked),
    )
    savepoint = db.begin_nested()
    token = library.FORCED.set(
        library.Forced(fail=frozenset(case.plan.fail), outputs=case.plan.outputs)
    )
    notes: list[str] = []
    try:
        payload, problems = synthesize(d, case.plan, fx.values)
        if problems:
            result.status, result.detail = "skipped", "; ".join(problems)
            return result
        now = datetime.now(UTC)
        execution, _ = engine.start(
            db,
            workflow_id=d.workflow_id,
            version=d.version,
            payload=payload,
            initiator=fx.initiator,
            now=now,
            allow_inactive=True,
        )
        _drive(db, d, execution, case, fx, now, notes)
        runs = _runs(db, execution)
        result.visited = [r.step_id for r in runs]
        result.outcome = execution.outcome
        _assert_case(d, case, execution, runs)
        result.detail = "; ".join(notes)
    except (AssertionError, DomainError) as exc:
        result.status = "failed"
        result.detail = "; ".join([*notes, getattr(exc, "message", None) or str(exc)])
    except Exception as exc:  # noqa: BLE001 - a crash is a failed case, not a failed run
        result.status = "failed"
        result.detail = "; ".join([*notes, f"{type(exc).__name__}: {exc}"])
    finally:
        library.FORCED.reset(token)
        savepoint.rollback()
        result.ms = int((time.perf_counter() - started) * 1000)
    return result


def _assert_case(d, case: Case, execution: WorkflowExecution, runs) -> None:
    if execution.status not in (ExecutionStatus.COMPLETED, ExecutionStatus.FAILED):
        raise AssertionError(f"the execution is still {execution.status}")
    error = execution.error or {}
    if error.get("code") in BAD_ENDINGS:
        raise AssertionError(f"ended badly: {error.get('code')} at {error.get('step')}")
    by_id = {s.id: s for s in d.steps}
    if execution.status == ExecutionStatus.FAILED:
        ended = [r for r in runs if by_id[r.step_id].type == StepType.FAILURE]
        if not ended:
            raise AssertionError(f"failed outside a failure step: {error}")
    visited = {r.step_id for r in runs}
    for route in case.path:
        for step in (route.source, route.target):
            if step not in visited:
                raise AssertionError(f"did not follow the planned route: never reached '{step}'")
    if execution.outcome not in _declared_outcomes(d):
        raise AssertionError(f"ended with the undeclared outcome '{execution.outcome}'")
    approved_at = [
        r.sequence
        for r in runs
        if by_id[r.step_id].type == StepType.APPROVAL and (r.output or {}).get("approved")
    ]
    for r in runs:
        handler = library.get(by_id[r.step_id].handler or "")
        if handler and handler.effect == "moves_money" and r.status == RunStatus.COMPLETED:
            if not any(seq < r.sequence for seq in approved_at):
                raise AssertionError(f"'{r.step_id}' moved money without a granted approval")


# --- Test runs ------------------------------------------------------------------------------


@dataclass
class PathTestReport:
    workflow_id: str
    version: int
    results: list[CaseResult]
    uncovered: list[dict[str, str]]
    step_coverage: float
    route_coverage: float
    duration_ms: int

    def count(self, status: str) -> int:
        return sum(r.status == status for r in self.results)

    @property
    def passed(self) -> bool:
        return self.count("failed") == 0


def run_path_tests(db: Session, d: WorkflowDefinition) -> PathTestReport:
    started = time.perf_counter()
    cases, uncovered = generate_cases(d)
    # Staff and records are made once; each case runs in its own savepoint inside this one.
    outer = db.begin_nested()
    try:
        fx = _fixtures(db, d, fixture_needs(d))
        results = [run_case(db, d, case, fx) for case in cases]
    finally:
        outer.rollback()
    all_routes = routes(d)
    covered_routes = {r.route for r in results if r.status == "passed" and r.route}
    covered_routes |= {
        route.label
        for case, r in zip(cases, results, strict=True)
        if r.status == "passed"
        for route in case.path
    }
    for case, r in zip(cases, results, strict=True):
        if r.status != "passed" and case.route is not None:
            if case.route.label not in covered_routes:
                uncovered.append({"route": case.route.label, "reason": f"case {r.status}"})
    visited = set(itertools.chain.from_iterable(r.visited for r in results if r.status == "passed"))
    return PathTestReport(
        workflow_id=d.workflow_id,
        version=d.version,
        results=results,
        uncovered=uncovered,
        step_coverage=round(len(visited & {s.id for s in d.steps}) / len(d.steps), 4),
        route_coverage=round(
            len(covered_routes & {r.label for r in all_routes}) / max(len(all_routes), 1), 4
        ),
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def record(
    db: Session,
    record_: WorkflowDefinitionRecord,
    report: PathTestReport,
    actor_id: uuid.UUID | None,
) -> WorkflowTestRun:
    run = WorkflowTestRun(
        definition_id=record_.id,
        workflow_id=report.workflow_id,
        version=report.version,
        passed=report.count("passed"),
        failed=report.count("failed"),
        step_coverage=report.step_coverage,
        route_coverage=report.route_coverage,
        cases=[r.as_json() for r in report.results],
        uncovered=report.uncovered,
        duration_ms=report.duration_ms,
        ran_by=actor_id,
    )
    db.add(run)
    db.flush()
    return run


def run_stored(
    db: Session, workflow_id: str, version: int | None, actor_id: uuid.UUID | None
) -> tuple[PathTestReport, WorkflowTestRun]:
    found = store.stored_record(db, workflow_id, version)
    if found is None:
        from app.core.errors import NotFoundError

        suffix = f" v{version}" if version else ""
        raise NotFoundError(f"No stored definition {workflow_id}{suffix}.")
    report = run_path_tests(db, store.parsed(found))
    return report, record(db, found, report, actor_id)
