"""The workflow engine, exercised with small purpose-built test workflows."""

import threading
from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.audit import AuditEvent, record_audit_event
from app.core.database import get_sessionmaker
from app.core.errors import ConflictError, PermissionDeniedError
from app.core.permissions import RoleCode
from app.modules.workflows import engine, registry
from app.modules.workflows.definition import Condition, WorkflowDefinition
from app.modules.workflows.engine import RetryableStepError, StepError, WorkflowInputError
from app.modules.workflows.models import WorkflowEvent, WorkflowExecution, WorkflowStepRun
from tests.factories import make_user, principal

T0 = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
CALLS: Counter[str] = Counter()
_lock = threading.Lock()


class Empty(BaseModel):
    note: str = ""


def _count(name: str) -> None:
    with _lock:
        CALLS[name] += 1


@registry.service_task("test.ok")
def _ok(ctx):
    _count(f"{ctx.execution.id}:{ctx.step.id}")
    return {"value": ctx.step.id}


@registry.service_task("test.flaky")
def _flaky(ctx):
    # Fails on the first two attempts, then succeeds.
    if ctx.run.attempt < 3:
        raise RetryableStepError("unavailable", f"dependency down (attempt {ctx.run.attempt})")
    return {"attempts": ctx.run.attempt}


@registry.service_task("test.broken")
def _broken(ctx):
    raise RuntimeError("boom")


@registry.service_task("test.rejects")
def _rejects(ctx):
    raise StepError("not_allowed", "business rule says no", {"why": "test"})


@registry.service_task("test.writes_then_fails")
def _writes_then_fails(ctx):
    record_audit_event(
        ctx.db, actor_id=None, action="test.partial_write", entity_type="t", entity_id=None
    )
    raise StepError("after_write", "failed after writing")


@registry.service_task("test.route")
def _route(ctx):
    return {"amount": int(ctx.input["note"] or 0)}


@registry.ai_task("test.ai")
def _ai(ctx):
    return {"recommendation": "escalate", "confidence": 0.42}


def _definition(
    workflow_id: str, steps: list[dict], start: str | None = None
) -> WorkflowDefinition:
    return WorkflowDefinition.model_validate(
        {
            "workflow_id": workflow_id,
            "name": f"Test {workflow_id}",
            "version": 1,
            "description": "test",
            "business_owner": "QA",
            "start": start or steps[0]["id"],
            "steps": steps,
        }
    )


@pytest.fixture
def define():
    registered: list[str] = []

    def _register(workflow_id: str, steps: list[dict], start: str | None = None):
        definition = _definition(workflow_id, steps, start)
        registry.register_definition(definition, Empty)
        registered.append(workflow_id)
        return definition

    yield _register
    for workflow_id in registered:
        registry.unregister_definition(workflow_id, 1)


@pytest.fixture
def starter(db: Session):
    return principal(make_user(db, RoleCode.BANKING_EMPLOYEE))


def _runs(db: Session, execution) -> list[WorkflowStepRun]:
    return list(
        db.execute(
            select(WorkflowStepRun)
            .where(WorkflowStepRun.execution_id == execution.id)
            .order_by(WorkflowStepRun.sequence)
        ).scalars()
    )


END = {"id": "done", "type": "completion", "name": "Done", "outcome": "ok"}


# --- Definitions and conditions ------------------------------------------------------------


@pytest.mark.parametrize(
    ("steps", "message"),
    [
        (
            [
                {
                    "id": "a",
                    "type": "service_task",
                    "name": "A",
                    "handler": "test.ok",
                    "next": "ghost",
                },
                END,
            ],
            "unknown step",
        ),
        (
            [{"id": "a", "type": "service_task", "name": "A", "next": "done"}, END],
            "needs a handler",
        ),
        (
            [
                {
                    "id": "a",
                    "type": "service_task",
                    "name": "A",
                    "handler": "test.ok",
                    "next": "done",
                },
                {
                    "id": "orphan",
                    "type": "service_task",
                    "name": "O",
                    "handler": "test.ok",
                    "next": "done",
                },
                END,
            ],
            "Unreachable",
        ),
        (
            [{"id": "p", "type": "parallel", "name": "P", "branches": ["done"]}, END],
            r"2\+ branches",
        ),
        (
            [
                {
                    "id": "a",
                    "type": "approval",
                    "name": "A",
                    "next": "done",
                    "approval": {"permissions": ["accounts:approve"]},
                },
                END,
            ],
            "approve/reject",
        ),
        (
            [{"id": "a", "type": "service_task", "name": "A", "handler": "test.ok", "next": "a"}],
            "completion step",
        ),
    ],
)
def test_invalid_definitions_are_rejected(steps: list[dict], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        _definition("WF-9001", steps)


def test_definition_versions_are_immutable(define) -> None:
    define(
        "WF-9002",
        [
            {"id": "a", "type": "service_task", "name": "A", "handler": "test.ok", "next": "done"},
            END,
        ],
    )
    changed = _definition(
        "WF-9002",
        [
            {
                "id": "a",
                "type": "service_task",
                "name": "Renamed",
                "handler": "test.ok",
                "next": "done",
            },
            END,
        ],
    )

    with pytest.raises(ValueError, match="bump the version"):
        registry.register_definition(changed, Empty)


def test_conditions() -> None:
    ctx = {"risk": {"rating": "high", "score": 7}, "flags": ["pep"], "empty": ""}
    c = Condition.model_validate

    assert c({"path": "risk.rating", "op": "eq", "value": "high"}).evaluate(ctx)
    assert c({"path": "risk.score", "op": "gte", "value": 7}).evaluate(ctx)
    assert c({"path": "risk.rating", "op": "in", "value": ["high", "medium"]}).evaluate(ctx)
    assert not c({"path": "missing.path", "op": "eq", "value": None}).evaluate(ctx)
    assert not c({"path": "empty", "op": "truthy"}).evaluate(ctx)
    assert c({"path": "flags", "op": "exists"}).evaluate(ctx)
    assert c(
        {"any": [{"path": "risk.score", "op": "lt", "value": 0}, {"path": "flags", "op": "truthy"}]}
    ).evaluate(ctx)
    assert not c(
        {"all": [{"path": "risk.score", "op": "gt", "value": 1}], "negate": True}
    ).evaluate(ctx)
    assert not c({"path": "risk.score", "op": "gt", "value": "x"}).evaluate(ctx)  # type mismatch
    with pytest.raises(ValidationError):
        c({"path": "x"})


# --- Execution -----------------------------------------------------------------------------


def test_linear_workflow_completes_with_history_and_timings(db: Session, define, starter) -> None:
    define(
        "WF-9010",
        [
            {
                "id": "first",
                "type": "service_task",
                "name": "First",
                "handler": "test.ok",
                "next": "second",
            },
            {
                "id": "second",
                "type": "service_task",
                "name": "Second",
                "handler": "test.ok",
                "next": "done",
            },
            END,
        ],
    )

    execution, replayed = engine.start(
        db, workflow_id="WF-9010", payload={}, initiator=starter, now=T0
    )

    assert not replayed
    assert (execution.status, execution.outcome) == ("completed", "ok")
    assert execution.context["second"] == {"value": "second"}
    assert [r.step_id for r in _runs(db, execution)] == ["first", "second", "done"]
    assert all(r.status == "completed" and r.duration_ms == 0 for r in _runs(db, execution))
    events = (
        db.execute(
            select(WorkflowEvent.event_type)
            .where(WorkflowEvent.execution_id == execution.id)
            .order_by(WorkflowEvent.seq)
        )
        .scalars()
        .all()
    )
    assert events[0] == "execution.started" and events[-1] == "execution.completed"
    assert events.count("step.completed") == 3


def test_invalid_input_is_rejected(db: Session, define, starter) -> None:
    define(
        "WF-9011",
        [
            {"id": "a", "type": "service_task", "name": "A", "handler": "test.ok", "next": "done"},
            END,
        ],
    )

    with pytest.raises(WorkflowInputError):
        engine.start(
            db, workflow_id="WF-9011", payload={"note": ["not", "a", "string"]}, initiator=starter
        )


def test_decision_routes_and_fails_without_a_matching_transition(
    db: Session, define, starter
) -> None:
    define(
        "WF-9012",
        [
            {
                "id": "read",
                "type": "service_task",
                "name": "Read",
                "handler": "test.route",
                "next": "route",
            },
            {
                "id": "route",
                "type": "decision",
                "name": "Route",
                "transitions": [
                    {"to": "big", "when": {"path": "read.amount", "op": "gt", "value": 100}},
                    {"to": "done", "when": {"path": "read.amount", "op": "lte", "value": 10}},
                ],
            },
            {
                "id": "big",
                "type": "service_task",
                "name": "Big",
                "handler": "test.ok",
                "next": "done",
            },
            END,
        ],
    )

    big, _ = engine.start(
        db, workflow_id="WF-9012", payload={"note": "500"}, initiator=starter, now=T0
    )
    small, _ = engine.start(
        db, workflow_id="WF-9012", payload={"note": "5"}, initiator=starter, now=T0
    )
    stuck, _ = engine.start(
        db, workflow_id="WF-9012", payload={"note": "50"}, initiator=starter, now=T0
    )

    assert "big" in big.context and big.status == "completed"
    assert "big" not in small.context and small.status == "completed"
    assert stuck.status == "failed"
    assert stuck.error["code"] == "no_route"


def test_transient_failures_are_retried_with_backoff(db: Session, define, starter) -> None:
    define(
        "WF-9013",
        [
            {
                "id": "call",
                "type": "service_task",
                "name": "Call",
                "handler": "test.flaky",
                "retry": {"max_attempts": 3, "backoff_seconds": 30},
                "next": "done",
            },
            END,
        ],
    )

    execution, _ = engine.start(db, workflow_id="WF-9013", payload={}, initiator=starter, now=T0)
    [run] = _runs(db, execution)
    assert (execution.status, run.status, run.attempt) == ("running", "pending", 1)
    assert run.not_before == T0 + timedelta(seconds=30)
    assert run.error["code"] == "unavailable"

    engine.advance(db, execution.id, now=T0 + timedelta(seconds=10))  # too early: nothing runs
    assert run.attempt == 1
    engine.advance(db, execution.id, now=T0 + timedelta(seconds=30))
    assert (run.attempt, run.not_before) == (2, T0 + timedelta(seconds=90))  # backoff doubles
    engine.advance(db, execution.id, now=T0 + timedelta(seconds=90))

    assert execution.status == "completed"
    assert (run.status, run.attempt, run.output) == ("completed", 3, {"attempts": 3})
    retries = db.execute(
        select(func.count()).where(
            WorkflowEvent.execution_id == execution.id,
            WorkflowEvent.event_type == "step.retry_scheduled",
        )
    ).scalar_one()
    assert retries == 2


def test_exhausted_retries_follow_the_failure_policy(db: Session, define, starter) -> None:
    define(
        "WF-9014",
        [
            {
                "id": "call",
                "type": "service_task",
                "name": "Call",
                "handler": "test.broken",
                "retry": {"max_attempts": 2, "backoff_seconds": 0},
                "on_failure": "fallback",
                "next": "done",
            },
            {"id": "fallback", "type": "failure", "name": "Escalated to operations"},
            END,
        ],
    )
    define(
        "WF-9015",
        [
            {
                "id": "call",
                "type": "service_task",
                "name": "Call",
                "handler": "test.rejects",
                "next": "done",
            },
            END,
        ],
    )

    routed, _ = engine.start(db, workflow_id="WF-9014", payload={}, initiator=starter, now=T0)
    immediate, _ = engine.start(db, workflow_id="WF-9015", payload={}, initiator=starter, now=T0)

    [call, fallback] = _runs(db, routed)
    assert (call.status, call.attempt) == ("failed", 2)
    assert call.error == {
        "code": "unexpected_error",
        "message": "RuntimeError: boom",
        "details": None,
    }
    assert fallback.step_id == "fallback"
    assert routed.status == "failed"
    assert routed.error["step"] == "call"
    # Business errors are not retried.
    [run] = _runs(db, immediate)
    assert (run.attempt, run.status) == (1, "failed")
    assert immediate.error == {
        "step": "call",
        "code": "not_allowed",
        "message": "business rule says no",
        "details": {"why": "test"},
    }


def test_a_failed_step_leaves_no_partial_writes(db: Session, define, starter) -> None:
    define(
        "WF-9016",
        [
            {
                "id": "write",
                "type": "service_task",
                "name": "Write",
                "handler": "test.writes_then_fails",
                "next": "done",
            },
            END,
        ],
    )

    execution, _ = engine.start(db, workflow_id="WF-9016", payload={}, initiator=starter, now=T0)

    assert execution.status == "failed"
    partial = db.execute(
        select(func.count()).where(AuditEvent.action == "test.partial_write")
    ).scalar_one()
    assert partial == 0


def test_parallel_branches_join_once(db: Session, define, starter) -> None:
    define(
        "WF-9017",
        [
            {
                "id": "fork",
                "type": "parallel",
                "name": "Fork",
                "branches": ["left", "right"],
                "join": "merge",
            },
            {
                "id": "left",
                "type": "service_task",
                "name": "Left",
                "handler": "test.ok",
                "next": "left_more",
            },
            {
                "id": "left_more",
                "type": "service_task",
                "name": "Left 2",
                "handler": "test.ok",
                "next": "merge",
            },
            {
                "id": "right",
                "type": "service_task",
                "name": "Right",
                "handler": "test.ok",
                "next": "merge",
            },
            {"id": "merge", "type": "join", "name": "Merge", "next": "after"},
            {
                "id": "after",
                "type": "service_task",
                "name": "After",
                "handler": "test.ok",
                "next": "done",
            },
            END,
        ],
    )

    execution, _ = engine.start(db, workflow_id="WF-9017", payload={}, initiator=starter, now=T0)

    steps = [(r.step_id, r.branch) for r in _runs(db, execution)]
    assert execution.status == "completed"
    assert steps.count(("merge", None)) == 1
    assert ("left_more", "left") in steps and ("right", "right") in steps
    assert steps.index(("merge", None)) > max(
        steps.index(("left_more", "left")), steps.index(("right", "right"))
    )


def test_human_tasks_validate_forms_and_cannot_complete_twice(db: Session, define, starter) -> None:
    define(
        "WF-9018",
        [
            {
                "id": "collect",
                "type": "human_task",
                "name": "Collect income",
                "next": "done",
                "approval": {"permissions": ["customers:manage"], "distinct_from": []},
                "form": [
                    {"name": "income", "type": "integer"},
                    {"name": "comment", "required": False},
                ],
            },
            END,
        ],
    )
    execution, _ = engine.start(db, workflow_id="WF-9018", payload={}, initiator=starter, now=T0)
    [task] = _runs(db, execution)
    clerk = principal(make_user(db, RoleCode.BANKING_EMPLOYEE))

    assert (execution.status, task.status) == ("waiting", "waiting")
    with pytest.raises(WorkflowInputError):
        engine.complete_task(db, task.id, clerk, data={"income": "lots"}, now=T0)
    with pytest.raises(PermissionDeniedError):
        engine.complete_task(
            db, task.id, principal(make_user(db, RoleCode.AUDITOR)), data={"income": 1}
        )

    engine.complete_task(db, task.id, clerk, data={"income": 52_000}, now=T0 + timedelta(minutes=5))

    assert execution.status == "completed"
    assert task.output["income"] == 52_000
    assert task.duration_ms == 5 * 60 * 1000
    with pytest.raises(ConflictError):
        engine.complete_task(db, task.id, clerk, data={"income": 1})


def test_wait_states_resume_on_signal_or_time_out(db: Session, define, starter) -> None:
    define(
        "WF-9019",
        [
            {
                "id": "wait",
                "type": "wait",
                "name": "Wait for docs",
                "signal": "docs",
                "timeout": {"after_seconds": 3600, "action": "transition", "to": "expired"},
                "next": "done",
            },
            {"id": "expired", "type": "failure", "name": "Expired", "outcome": "expired"},
            END,
        ],
    )
    signalled, _ = engine.start(db, workflow_id="WF-9019", payload={}, initiator=starter, now=T0)
    abandoned, _ = engine.start(db, workflow_id="WF-9019", payload={}, initiator=starter, now=T0)

    with pytest.raises(ConflictError):
        engine.signal(db, signalled.id, "wrong-signal", {}, None, now=T0)
    engine.signal(db, signalled.id, "docs", {"pages": 3}, starter.id, now=T0 + timedelta(minutes=1))
    assert signalled.status == "completed"
    assert signalled.context["wait"] == {"signal": "docs", "pages": 3}

    assert engine.process_timers(db, abandoned, T0 + timedelta(minutes=59)) == 0
    assert engine.process_timers(db, abandoned, T0 + timedelta(hours=1)) == 1
    assert (abandoned.status, abandoned.outcome) == ("failed", "expired")


def test_ai_task_steps_call_registered_adapters(db: Session, define, starter) -> None:
    define(
        "WF-9020",
        [
            {
                "id": "assess",
                "type": "ai_task",
                "name": "AI assessment",
                "handler": "test.ai",
                "next": "done",
            },
            END,
        ],
    )

    execution, _ = engine.start(db, workflow_id="WF-9020", payload={}, initiator=starter, now=T0)

    assert execution.context["assess"] == {"recommendation": "escalate", "confidence": 0.42}


def test_cancel_and_idempotent_start(db: Session, define, starter) -> None:
    define(
        "WF-9021",
        [
            {"id": "wait", "type": "wait", "name": "Wait", "signal": "go", "next": "done"},
            END,
        ],
    )
    first, replayed_first = engine.start(
        db, workflow_id="WF-9021", payload={}, initiator=starter, idempotency_key="k1", now=T0
    )
    again, replayed_again = engine.start(
        db, workflow_id="WF-9021", payload={}, initiator=starter, idempotency_key="k1", now=T0
    )

    assert (replayed_first, replayed_again) == (False, True)
    assert again.id == first.id
    engine.cancel(db, first.id, starter.id, "customer withdrew", now=T0)
    assert first.status == "cancelled"
    assert all(r.status == "cancelled" for r in _runs(db, first))
    with pytest.raises(ConflictError):
        engine.signal(db, first.id, "go", {}, None)


def test_history_is_append_only(db: Session, define, starter) -> None:
    define(
        "WF-9022",
        [
            {"id": "a", "type": "service_task", "name": "A", "handler": "test.ok", "next": "done"},
            END,
        ],
    )
    execution, _ = engine.start(db, workflow_id="WF-9022", payload={}, initiator=starter, now=T0)

    for statement in (
        f"UPDATE workflow_events SET event_type = 'x' WHERE execution_id = '{execution.id}'",
        f"DELETE FROM workflow_events WHERE execution_id = '{execution.id}'",
    ):
        with pytest.raises(DBAPIError, match="append-only"), db.begin_nested():
            db.execute(text(statement))


# --- Durability (committed transactions, separate sessions) -------------------------------


@pytest.fixture
def committed_starter():
    with get_sessionmaker()() as session, session.begin():
        return principal(make_user(session, RoleCode.BANKING_EMPLOYEE))


def test_execution_resumes_after_a_restart(define, committed_starter) -> None:
    define(
        "WF-9030",
        [
            {
                "id": "one",
                "type": "service_task",
                "name": "One",
                "handler": "test.ok",
                "next": "two",
            },
            {
                "id": "two",
                "type": "service_task",
                "name": "Two",
                "handler": "test.ok",
                "next": "three",
            },
            {
                "id": "three",
                "type": "service_task",
                "name": "Three",
                "handler": "test.ok",
                "next": "done",
            },
            END,
        ],
    )
    # The process "dies" after the first step: only that much was committed.
    with get_sessionmaker()() as session, session.begin():
        execution, _ = engine.start(
            session, workflow_id="WF-9030", payload={}, initiator=committed_starter, max_steps=1
        )
        execution_id = execution.id

    report = engine.run_due(get_sessionmaker())  # a fresh process picks up the work

    with get_sessionmaker()() as session:
        resumed = session.get(WorkflowExecution, execution_id)
        runs = _runs(session, resumed)
    assert report.executions >= 1
    assert resumed.status == "completed"
    assert [r.step_id for r in runs] == ["one", "two", "three", "done"]
    assert all(CALLS[f"{execution_id}:{step}"] == 1 for step in ("one", "two", "three"))


def test_concurrent_workers_never_run_a_step_twice(define, committed_starter) -> None:
    steps = [
        {
            "id": f"s{i}",
            "type": "service_task",
            "name": f"S{i}",
            "handler": "test.ok",
            "next": f"s{i + 1}" if i < 5 else "done",
        }
        for i in range(1, 6)
    ]
    define("WF-9031", [*steps, END])
    with get_sessionmaker()() as session, session.begin():
        execution, _ = engine.start(
            session, workflow_id="WF-9031", payload={}, initiator=committed_starter, max_steps=0
        )
        execution_id = execution.id

    barrier = threading.Barrier(4)
    errors: list[Exception] = []

    def worker() -> None:
        try:
            barrier.wait(timeout=10)
            with get_sessionmaker()() as session, session.begin():
                engine.advance(session, execution_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert errors == []
    assert [CALLS[f"{execution_id}:s{i}"] for i in range(1, 6)] == [1, 1, 1, 1, 1]
    with get_sessionmaker()() as session:
        assert session.get(WorkflowExecution, execution_id).status == "completed"
