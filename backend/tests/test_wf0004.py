"""WF-0004 Loan Collections: opened and closed by loan servicing, four-eyes write-off."""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.customers.models import CustomerNotification
from app.modules.lending import servicing
from app.modules.lending.models import LoanStatus
from app.modules.workflows.models import WorkflowExecution
from app.modules.workflows.wf0004 import WORKFLOW_ID, open_case_for
from tests.factories import auth, make_loan, make_staff, make_user, principal, top_up

TASKS = "/api/v1/workflow-tasks"
EXECUTIONS = "/api/v1/workflow-executions"


def _run(db: Session, user, on: date) -> None:
    servicing.run(db, on, principal(user))


def _cases(db: Session, loan) -> list[WorkflowExecution]:
    db.expire_all()
    return list(
        db.execute(
            select(WorkflowExecution)
            .where(
                WorkflowExecution.workflow_id == WORKFLOW_ID,
                WorkflowExecution.business_key == str(loan.id),
            )
            .order_by(WorkflowExecution.started_at)
        ).scalars()
    )


def _task(client: TestClient, user, execution_id) -> dict | None:
    tasks = client.get(f"{TASKS}?actionable=false", headers=auth(user)).json()
    return next((t for t in tasks["items"] if t["execution_id"] == str(execution_id)), None)


def _decide(client: TestClient, user, run_id: str, decision: str):
    return client.post(
        f"{TASKS}/{run_id}/complete",
        json={"decision": decision, "note": "credit committee"},
        headers=auth(user),
    )


def _escalated(db: Session):
    """A loan 92 days past due whose case waits for a write-off review. The platform
    administrator ran servicing, so they opened the case."""
    staff = make_staff(db)
    loan = make_loan(db, staff)
    _run(db, staff.admin, date(2040, 3, 12))
    _run(db, staff.admin, date(2040, 5, 12))
    (case,) = _cases(db, loan)
    assert case.current_steps == ["writeoff_review"]
    return staff, loan, case


def test_a_case_opens_at_thirty_days_and_closes_when_cured(db: Session) -> None:
    staff = make_staff(db)
    loan = make_loan(db, staff)

    _run(db, staff.manager, date(2040, 3, 1))  # 20 days past due: no case yet
    assert _cases(db, loan) == []

    _run(db, staff.manager, date(2040, 3, 12))  # 31 days

    (case,) = _cases(db, loan)
    assert case.status == "waiting" and case.current_steps == ["await_resolution"]
    assert case.context["open_case"]["days_past_due"] == 31
    assert case.context["open_case"]["bucket"] == "30-59"
    assert case.context["open_case"]["subject"].startswith(loan.loan_number)
    assert case.started_at.date() == date(2040, 3, 12)  # the business date is the clock
    letter = db.execute(
        select(CustomerNotification).where(CustomerNotification.workflow_execution_id == case.id)
    ).scalar_one()
    assert letter.customer_id == loan.customer_id and loan.loan_number in letter.subject

    _run(db, staff.manager, date(2040, 3, 20))  # still in arrears: the same case
    assert len(_cases(db, loan)) == 1

    top_up(db, staff, loan, 200_000)
    servicing.repay_arrears(db, loan.id, principal(staff.employee), key="cure")

    (case,) = _cases(db, loan)
    assert (case.status, case.outcome) == ("completed", "cured")
    assert open_case_for(db, loan) is None


def test_ninety_days_escalates_to_a_four_eyes_write_off(client: TestClient, db: Session) -> None:
    staff, loan, case = _escalated(db)
    executive = make_user(db, RoleCode.REGIONAL_EXECUTIVE)

    task = _task(client, executive, case.id)
    assert task["can_act"] is True and task["risk_rating"] == "90+"
    assert _task(client, staff.admin, case.id)["can_act"] is False  # opened the case
    assert _task(client, staff.manager, case.id)["can_act"] is False  # no authority
    assert _decide(client, staff.admin, task["run_id"], "approve").status_code == 403

    done = _decide(client, executive, task["run_id"], "approve")

    assert done.status_code == 200, done.text
    assert (done.json()["status"], done.json()["outcome"]) == ("completed", "written_off")
    db.expire_all()
    assert loan.status == LoanStatus.WRITTEN_OFF and loan.written_off_by == executive.id
    assert loan.closed_on == date(2040, 5, 12)  # booked on the business date
    # A written-off loan is no longer serviced, and no new case opens.
    _run(db, staff.admin, date(2040, 6, 12))
    assert len(_cases(db, loan)) == 1


def test_a_declined_write_off_closes_the_case_and_servicing_reopens_one(
    client: TestClient, db: Session
) -> None:
    staff, loan, case = _escalated(db)
    executive = make_user(db, RoleCode.GLOBAL_EXECUTIVE)
    task = _task(client, executive, case.id)

    done = _decide(client, executive, task["run_id"], "reject").json()

    assert (done["status"], done["outcome"]) == ("completed", "write_off_declined")
    db.expire_all()
    assert loan.status == LoanStatus.ACTIVE

    _run(db, staff.admin, date(2040, 5, 13))

    first, second = _cases(db, loan)
    assert second.id != first.id and second.current_steps == ["writeoff_review"]


def test_a_loan_repaid_during_the_review_closes_as_cured(client: TestClient, db: Session) -> None:
    staff, loan, case = _escalated(db)
    executive = make_user(db, RoleCode.REGIONAL_EXECUTIVE)
    top_up(db, staff, loan, 400_000)
    servicing.repay_arrears(db, loan.id, principal(staff.employee), key="late-cure")

    done = _decide(client, executive, _task(client, executive, case.id)["run_id"], "approve")

    assert done.json()["outcome"] == "cured"
    assert done.json()["context"]["write_off"] == {"written_off": False, "days_past_due": 0}
    db.expire_all()
    assert loan.status == LoanStatus.ACTIVE and loan.write_off_entry_id is None
