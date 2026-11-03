"""Phase 66: workflow steps call their applications as they run, so an outage delays or
fails real executions."""

import copy
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.customers.models import Customer
from app.modules.itops import gateway, simulated
from app.modules.itops import service as itops
from app.modules.itops.models import Application
from app.modules.workflows import authoring, engine
from app.modules.workflows.models import WorkflowEvent, WorkflowStepRun
from tests.factories import funded_account, make_org_tree, make_staff, principal
from tests.test_workflow_library import example

T = datetime(2026, 11, 3, 10, tzinfo=UTC)


@pytest.fixture
def statements(db: Session):
    """WF-1002 under a test id, its find_customer step retried (3 attempts, 30 s then 60 s),
    the bank's core systems, and a request."""
    staff = make_staff(db)
    make_org_tree(db)
    itops.ensure_applications(db)
    document = copy.deepcopy(example("WF-1002", as_id="WF-1912"))
    for step in document["steps"]:
        if step["id"] == "find_customer":
            step["retry"] = {"max_attempts": 3, "backoff_seconds": 30}
    authoring.import_definition(db, document, staff.admin.id)
    authoring.import_definition(db, example("WF-1002", as_id="WF-1913"), staff.admin.id)
    account = funded_account(db, staff, balance=10_000)
    customer = db.get(Customer, account.customer_id)
    request = {"customer_number": customer.customer_number, "months": 3, "delivery": "email",
               "account_number": account.account_number}  # fmt: skip
    return staff, request


def _app(db: Session, name: str) -> Application:
    return db.execute(select(Application).where(Application.name == name)).scalar_one()


def _run(db: Session, execution, step_id: str) -> WorkflowStepRun:
    db.flush()
    return db.execute(select(WorkflowStepRun).where(
        WorkflowStepRun.execution_id == execution.id,
        WorkflowStepRun.step_id == step_id)).scalar_one()  # fmt: skip


def _completed(db: Session, execution, step_id: str) -> dict:
    db.flush()
    events = db.execute(select(WorkflowEvent).where(
        WorkflowEvent.execution_id == execution.id,
        WorkflowEvent.event_type == "step.completed")).scalars()  # fmt: skip
    return next(e.data for e in events if e.data.get("step") == step_id)


def test_steps_call_their_applications_and_take_their_time(db: Session, statements) -> None:
    staff, request = statements
    execution, _ = engine.start(db, workflow_id="WF-1913", payload=request,
                                initiator=principal(staff.employee), now=T)  # fmt: skip
    assert (execution.status, execution.outcome) == ("completed", "sent")
    ledger, archive = _app(db, "Core Banking Ledger"), _app(db, "Document Archive")
    find_customer = _completed(db, execution, "find_customer")
    assert [c["application"] for c in find_customer["applications"]] == [
        ledger.application_number, archive.application_number]  # fmt: skip
    assert all(c["ok"] for c in find_customer["applications"])
    assert find_customer["application_ms"] > 0
    # Simulated time stands still within an advance: the duration is the calls' latency.
    assert _run(db, execution, "find_customer").duration_ms == int(
        find_customer["application_ms"])  # fmt: skip
    # core.* steps call nothing.
    assert "applications" not in _completed(db, execution, "assign_key")

    # The same execution, step and attempt draw the same latencies.
    again = gateway.Gateway(db).call(workflow_id="WF-1913", step_id="find_customer",
                                     handler="customers.lookup", execution_id=execution.id,
                                     attempt=1, at=T)  # fmt: skip
    assert again.calls == find_customer["applications"]


def test_a_short_outage_delays_the_workflow(db: Session, statements) -> None:
    staff, request = statements
    ledger = _app(db, "Core Banking Ledger")
    simulated.declare_outage(db, ledger, "down", "Mainframe IPL overran", staff.admin.id,
                             now=T - timedelta(minutes=5),
                             ends_at=T + timedelta(seconds=75))  # fmt: skip
    execution, _ = engine.start(db, workflow_id="WF-1912", payload=request,
                                initiator=principal(staff.employee), now=T)  # fmt: skip
    run = _run(db, execution, "find_customer")
    assert execution.status == "running" and run.status == "pending"
    assert run.error["code"] == "application_unavailable"
    assert run.error["details"]["application"] == ledger.application_number
    assert run.not_before == T + timedelta(seconds=30)

    engine.advance(db, execution.id, now=T + timedelta(seconds=30))  # still down
    assert run.attempt == 2 and run.not_before == T + timedelta(seconds=90)
    engine.advance(db, execution.id, now=T + timedelta(seconds=90))  # restored at +75 s
    assert (execution.status, execution.outcome) == ("completed", "sent")
    assert run.attempt == 3 and run.status == "completed"
    assert execution.completed_at == T + timedelta(seconds=90)


def test_a_long_outage_fails_the_step_and_a_dependency_s_outage_counts(
    db: Session, statements
) -> None:
    staff, request = statements
    # The Document Archive does not answer: WF-1002's find_customer is tried once, then
    # goes to its on_failure route.
    archive = _app(db, "Document Archive")
    simulated.declare_outage(db, archive, "down", "Storage array failed", staff.admin.id,
                             now=T - timedelta(minutes=5))  # fmt: skip
    rejected, _ = engine.start(db, workflow_id="WF-1913", payload=request,
                               initiator=principal(staff.employee), now=T)  # fmt: skip
    assert rejected.outcome == "rejected"
    failure = rejected.context["_failure"]
    assert failure["code"] == "application_unavailable"
    assert failure["details"]["cause"] == archive.application_number

    # Sanctions Screening down: nothing WF-1002 calls waits on it, so it completes.
    screening = _app(db, "Sanctions Screening")
    simulated.declare_outage(db, screening, "down", "Lists failed to load", staff.admin.id,
                             now=T + timedelta(hours=1))  # fmt: skip
    later = T + timedelta(hours=2)
    for outage in simulated._active(db, later):
        if outage.application_id == archive.id:
            simulated.end_outage(db, outage, staff.admin.id, now=later)
    sent, _ = engine.start(db, workflow_id="WF-1913", payload=request,
                           initiator=principal(staff.employee),
                           now=later + timedelta(minutes=1))  # fmt: skip
    assert sent.outcome == "sent"

    # The ledger behind the Payments Gateway: a ledger outage fails a step calling the
    # gateway, naming the ledger as the cause.
    ledger = _app(db, "Core Banking Ledger")
    simulated.declare_outage(db, ledger, "down", "Mainframe down", staff.admin.id,
                             now=later + timedelta(hours=1))  # fmt: skip
    report = gateway.Gateway(db).call(
        workflow_id="WF-0002", step_id="release_payment", handler="wf0002.release_payment",
        execution_id=sent.id, attempt=1, at=later + timedelta(hours=2))  # fmt: skip
    gateway_app = _app(db, "Payments Gateway")
    assert report.failure["application"] == gateway_app.application_number
    assert report.failure["cause"] == ledger.application_number
    assert report.failure["path"] == [gateway_app.application_number, ledger.application_number]


def test_only_outages_fail_calls_unless_realistic(db: Session, statements) -> None:
    # A low-code SaaS application errs on 2 % of calls; by default that never fails a step.
    staff, _ = statements
    hr = _app(db, "HR System")
    hr.technology, hr.hosting = "low-code", "saas"
    hub = gateway.Gateway(db)

    def failures() -> int:
        return sum(hub.call(workflow_id="WF-1043", step_id=f"s{i}", handler="hr.approve_leave",
                            execution_id=uuid.UUID(int=i), attempt=1, at=T).failure is not None
                   for i in range(1000))  # fmt: skip

    assert failures() == 0
    with gateway.realistic():
        assert 5 <= failures() <= 40  # about 2 % of 1,000 (tier 3: 1 %, low-code: twice that)
