"""Phase 74: the durable event pipeline — the outbox, retries, and departments that meet in it."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, func, select
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.access.models import AccessGrant
from app.modules.employees.models import EmploymentStatus
from app.modules.employees.schemas import EmployeeUpdate
from app.modules.employees.service import update_employee
from app.modules.events import outbox
from app.modules.events.models import DomainEvent, EventDelivery
from app.modules.hr import service as hr
from app.modules.lending import servicing
from app.modules.workflows.models import WorkflowExecution
from tests.factories import (
    auth,
    make_loan,
    make_org_tree,
    make_staff,
    make_user,
    principal,
    top_up,
)

MONDAY = date(2041, 3, 4)


@pytest.fixture
def factory(db_connection: Connection):
    def make() -> Session:
        return Session(
            bind=db_connection,
            join_transaction_mode="create_savepoint",
            autoflush=False,
            expire_on_commit=False,
        )

    return make


def _deliveries(db: Session, event: DomainEvent) -> dict[str, EventDelivery]:
    return {
        d.subscriber: d
        for d in db.execute(
            select(EventDelivery).where(EventDelivery.event_id == event.id)
        ).scalars()
    }


class Flaky:
    """A subscriber that fails `failures` times, writing first so a rollback can be seen."""

    def __init__(self, failures: int) -> None:
        self.failures, self.calls, self.seen = failures, 0, []

    def __call__(self, db: Session, event: DomainEvent) -> None:
        self.calls += 1
        db.add(
            DomainEvent(
                topic="test.side_effect",
                key=event.key,
                publisher="test",
                payload={"call": self.calls},
            )
        )
        db.flush()
        if self.calls <= self.failures:
            raise RuntimeError(f"failure {self.calls}")
        self.seen.append(event.payload)


def _topic(handler, name: str) -> str:
    topic = f"test.{name}.{uuid.uuid4().hex[:8]}"
    outbox.subscribe(topic, f"test.{name}", department="test")(handler)
    return topic


def _side_effects(db: Session, key: str) -> int:
    return db.execute(
        select(func.count())
        .select_from(DomainEvent)
        .where(DomainEvent.topic == "test.side_effect", DomainEvent.key == key)
    ).scalar_one()


def test_a_delivered_event_and_a_failing_subscriber(db: Session, factory) -> None:
    ok, flaky = Flaky(0), Flaky(2)
    topic = _topic(ok, "ok")
    outbox.subscribe(topic, "test.flaky", department="test")(flaky)
    event = outbox.publish(db, topic, "k-1", {"n": 1}, publisher="test")
    db.commit()
    got = _deliveries(db, event)
    assert got["test.ok"].status == "delivered" and got["test.ok"].attempts == 1
    # The failing subscriber's own writes were rolled back; the event and the other
    # subscriber's work stand.
    failed = got["test.flaky"]
    assert failed.status == "failed" and failed.attempts == 1
    assert "RuntimeError: failure 1" in failed.last_error
    assert _side_effects(db, "k-1") == 1  # only the successful subscriber's
    assert failed.next_attempt_at > datetime.now(UTC) + timedelta(seconds=20)

    # Not yet due: the dispatcher leaves it. Later: retried with back-off, then delivered.
    assert outbox.dispatch(factory).claimed == 0
    later = datetime.now(UTC) + timedelta(minutes=5)
    report = outbox.dispatch(factory, now=later)
    assert (report.claimed, report.failed) == (1, 1)
    db.expire_all()
    assert db.get(EventDelivery, failed.id).attempts == 2
    report = outbox.dispatch(factory, now=later + timedelta(hours=1))
    assert (report.delivered, report.by_subscriber) == (1, {"test.flaky": 1})
    db.expire_all()
    done = db.get(EventDelivery, failed.id)
    assert (done.status, done.attempts, done.last_error) == ("delivered", 3, None)
    assert flaky.seen == [{"n": 1}] and _side_effects(db, "k-1") == 2


def test_out_of_attempts_a_delivery_is_dead_until_retried(db: Session, factory) -> None:
    always = Flaky(10_000)
    topic = _topic(always, "dead")
    event = outbox.publish(db, topic, "k-2", {}, publisher="test")
    db.commit()
    at = datetime.now(UTC)
    for _ in range(outbox.MAX_ATTEMPTS):
        at += timedelta(days=1)
        outbox.dispatch(factory, now=at)
    db.expire_all()
    delivery = _deliveries(db, event)["test.dead"]
    assert (delivery.status, delivery.attempts) == ("dead", outbox.MAX_ATTEMPTS)
    assert outbox.dispatch(factory, now=at + timedelta(days=30)).claimed == 0
    always.failures = 0  # fixed
    outbox.retry(db, delivery.id)
    db.commit()
    assert outbox.dispatch(factory).delivered == 1
    summary = outbox.summary(db)
    assert summary["events"] >= 1 and any(s["name"] == "test.dead" for s in summary["subscribers"])


def test_without_inline_delivery_the_dispatcher_delivers(db: Session, factory) -> None:
    ok = Flaky(0)
    topic = _topic(ok, "later")
    event = outbox.publish(db, topic, "k-3", {"x": 1}, publisher="test", deliver=False)
    db.commit()
    assert _deliveries(db, event)["test.later"].status == "pending" and ok.calls == 0
    assert outbox.dispatch(factory).delivered == 1 and ok.seen == [{"x": 1}]
    # Delivered once: a second pass finds nothing.
    assert outbox.dispatch(factory).claimed == 0


def test_lending_tells_collections_through_the_outbox(db: Session) -> None:
    staff = make_staff(db)
    loan = make_loan(db, staff)
    topic = servicing.ARREARS_TOPIC

    def events() -> list[DomainEvent]:
        return list(
            db.execute(
                select(DomainEvent)
                .where(DomainEvent.topic == topic, DomainEvent.key == str(loan.id))
                .order_by(DomainEvent.seq)
            ).scalars()
        )

    servicing.run(db, date(2040, 2, 5), principal(staff.manager))  # nothing due yet
    assert events() == []  # a current loan publishes nothing
    servicing.run(db, date(2040, 3, 25), principal(staff.manager))  # two missed: 44 days
    (first,) = events()
    assert first.publisher == "lending" and first.payload["days_past_due"] == 44
    assert _deliveries(db, first)["collections.sync"].status == "delivered"
    case = db.execute(
        select(WorkflowExecution).where(
            WorkflowExecution.workflow_id == "WF-0004",
            WorkflowExecution.business_key == str(loan.id),
        )
    ).scalar_one()
    assert "await_resolution" in case.current_steps
    # Repaying cures the loan: one more event, and collections closes the case.
    top_up(db, staff, loan, first.payload["amount"])
    servicing.repay_arrears(db, loan.id, principal(staff.employee), key="outbox-cure")
    cured = events()[-1]
    assert cured.payload["days_past_due"] == 0
    db.refresh(case)
    assert case.status == "completed"


def _hire(db: Session):
    tree = make_org_tree(db)
    manager = make_user(db, RoleCode.DEPARTMENT_MANAGER)
    executive = make_user(db, RoleCode.REGIONAL_EXECUTIVE)
    row = hr.open_requisition(
        db,
        tree.us_onboarding,
        job_title="Onboarding Adviser",
        role="banking_employee",
        openings=1,
        salary_min=4_000_000,
        salary_max=5_000_000,
        reason="Two advisers left this month.",
        requested_by=manager.id,
    )
    hr.decide_requisition(db, row, executive.id, approve=True)
    candidate = hr.add_candidate(db, row, "Rina", "Okafor")
    hr.make_offer(db, candidate, 4_500_000, MONDAY, manager.id)
    return hr.hire(db, candidate, manager.id), manager


def test_a_joiner_and_a_leaver_across_hr_and_information_security(
    client: TestClient, db: Session
) -> None:
    employee, manager = _hire(db)
    hired = outbox.last_event(db, "hr.employee_hired", str(employee.id))
    assert hired is not None and hired.payload["employee_number"] == employee.employee_number
    assert _deliveries(db, hired)["information_security.request_access"].status == "delivered"
    (grant,) = db.execute(
        select(AccessGrant).where(AccessGrant.employee_id == employee.id)
    ).scalars()
    assert (grant.status, grant.profile, grant.source_event_id) == (
        "requested",
        "role:banking_employee",
        hired.id,
    )
    # A redelivery asks for nothing more (the subscriber is idempotent).
    from app.modules.access.subscribers import request_joiner_access

    request_joiner_access(db, hired)
    assert (
        db.execute(
            select(func.count())
            .select_from(AccessGrant)
            .where(AccessGrant.employee_id == employee.id)
        ).scalar_one()
        == 1
    )
    it_access = next(t for t in hr.onboarding(db, employee.id) if t.code == "it_access")
    assert it_access.completed_at is None

    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    db.commit()
    listed = client.get("/api/v1/access/grants?status=requested", headers=auth(admin)).json()
    assert [g["grant_number"] for g in listed] == [grant.grant_number]
    assert (
        client.post(f"/api/v1/access/grants/{grant.id}/grant", headers=auth(manager)).status_code
        == 403
    )
    granted = client.post(f"/api/v1/access/grants/{grant.id}/grant", headers=auth(admin))
    assert granted.status_code == 200, granted.text
    db.expire_all()
    # Information Security's grant reached HR: the onboarding task is done.
    it_access = next(t for t in hr.onboarding(db, employee.id) if t.code == "it_access")
    assert it_access.completed_at is not None and it_access.completed_by == admin.id

    # The leaver: access revoked through the outbox.
    update_employee(
        db, employee, EmployeeUpdate(employment_status=EmploymentStatus.TERMINATED), manager.id
    )
    db.refresh(grant)
    assert grant.status == "revoked" and grant.revoke_reason == "Left the bank"
    left = outbox.last_event(db, "hr.employee_left", str(employee.id))
    assert _deliveries(db, left)["information_security.revoke_access"].status == "delivered"


def test_the_api_and_the_schedule(client: TestClient, db: Session) -> None:
    from app.jobs.engine import REGISTRY
    from app.jobs.models import JobSchedule

    assert "events.dispatch" in REGISTRY
    schedule = db.execute(
        select(JobSchedule).where(JobSchedule.name == "events-dispatch")
    ).scalar_one()
    assert (schedule.kind, schedule.interval_seconds, schedule.enabled) == (
        "events.dispatch",
        60,
        True,
    )
    flaky = Flaky(1)
    topic = _topic(flaky, "api")
    event = outbox.publish(db, topic, "k-4", {"y": 2}, publisher="test")
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    auditor = make_user(db, RoleCode.AUDITOR)
    db.commit()
    listed = client.get(f"/api/v1/events?topic={topic}", headers=auth(admin)).json()
    assert [e["key"] for e in listed] == ["k-4"]
    (delivery,) = listed[0]["deliveries"]
    assert delivery["status"] == "failed" and "failure 1" in delivery["last_error"]
    failed = client.get("/api/v1/events?status=failed", headers=auth(admin)).json()
    assert str(event.id) in {e["id"] for e in failed}
    summary = client.get("/api/v1/events/summary", headers=auth(admin)).json()
    assert summary["waiting"] >= 1
    retry = f"/api/v1/events/deliveries/{delivery['id']}/retry"
    assert client.post(retry, headers=auth(auditor)).status_code == 403
    again = client.post(retry, headers=auth(admin))
    assert again.status_code == 200 and again.json()["status"] == "pending"
