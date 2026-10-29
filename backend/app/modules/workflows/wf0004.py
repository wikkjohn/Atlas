"""WF-0004 Loan Collections.

Loan servicing drives this workflow; nobody needs to start it by hand. When a loan reaches
30 days past due a collections case opens: the borrower is reminded and the case waits.
Each later servicing run, repayment or payoff reports the loan's arrears:

- arrears cleared (or the loan closed) → the case closes as **cured**;
- 90 or more days past due → the case escalates to a **write-off review** by someone holding
  `loans:approve_large` other than the person who opened the case (four-eyes). Approval
  writes the loan off through the lending service, which re-checks the authority and the
  90-day rule; a decline closes the case and the next servicing run opens a new one.

The lending business date is the case's clock: every step runs at the business date the
servicing run or repayment reported.
"""

import uuid
from datetime import UTC, date, datetime, time

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.customers.models import Customer, CustomerNotification
from app.modules.identity.service import AuthenticatedUser
from app.modules.lending import servicing
from app.modules.lending.models import Loan, LoanStatus
from app.modules.lending.service import format_amount
from app.modules.workflows import engine
from app.modules.workflows.definition import WorkflowDefinition
from app.modules.workflows.engine import StepContext, StepError
from app.modules.workflows.models import ACTIVE_STATUSES, WorkflowExecution
from app.modules.workflows.principals import principal
from app.modules.workflows.registry import (
    Presenter,
    register_definition,
    register_presenter,
    service_task,
)

WORKFLOW_ID = "WF-0004"
VERSION = 1
SIGNAL = "loan_status"
OUTCOMES = {
    "close_cured": "cured",
    "close_declined": "write_off_declined",
    "close_written_off": "written_off",
}


class CollectionsCase(BaseModel):
    """Opened by loan servicing for a loan 30 or more days past due."""

    loan_id: uuid.UUID
    business_date: date = Field(description="The lending business date the case opened on")


def _when(path: str, op: str, value: object = None) -> dict:
    return {"path": path, "op": op, "value": value}


DEFINITION = WorkflowDefinition.model_validate(
    {
        "workflow_id": WORKFLOW_ID,
        "name": "Loan Collections",
        "version": VERSION,
        "description": "Works a personal loan in arrears: opens at 30 days past due, reminds "
        "the borrower, closes when the arrears are paid, and at 90 days past due asks the "
        "credit committee to approve a write-off (four-eyes).",
        "business_owner": "Retail Lending — Collections",
        "trigger_type": "event",
        "start": "open_case",
        "steps": [
            {
                "id": "open_case",
                "type": "service_task",
                "name": "Open collections case",
                "handler": "wf0004.open_case",
                "next": "remind_borrower",
            },
            {
                "id": "remind_borrower",
                "type": "service_task",
                "name": "Send simulated arrears reminder",
                "handler": "wf0004.remind_borrower",
                "next": "await_resolution",
            },
            {
                "id": "await_resolution",
                "type": "wait",
                "name": "Wait for repayment or escalation",
                "signal": SIGNAL,
                "next": "route_case",
            },
            {
                "id": "route_case",
                "type": "decision",
                "name": "Route the case",
                "transitions": [
                    {
                        "to": "close_cured",
                        "when": _when("await_resolution.status", "eq", "cured"),
                    },
                    {"to": "writeoff_review"},
                ],
            },
            {
                "id": "writeoff_review",
                "type": "approval",
                "name": "Write-off review (credit committee)",
                "approval": {
                    "permissions": ["loans:approve_large"],
                    "distinct_from": ["initiator"],
                },
                "timeout": {"after_seconds": 7 * 24 * 3600, "action": "flag"},
                "transitions": [
                    {
                        "to": "write_off",
                        "when": _when("writeoff_review.decision", "eq", "approve"),
                    },
                    {"to": "close_declined"},
                ],
            },
            {
                "id": "write_off",
                "type": "service_task",
                "name": "Write the loan off",
                "handler": "wf0004.write_off",
                "transitions": [
                    {
                        "to": "close_written_off",
                        "when": _when("write_off.written_off", "truthy"),
                    },
                    {"to": "close_cured"},
                ],
            },
            {
                "id": "close_cured",
                "type": "service_task",
                "name": "Close: arrears cleared",
                "handler": "wf0004.close",
                "next": "complete",
            },
            {
                "id": "close_declined",
                "type": "service_task",
                "name": "Close: write-off declined",
                "handler": "wf0004.close",
                "next": "complete",
            },
            {
                "id": "close_written_off",
                "type": "service_task",
                "name": "Close: written off",
                "handler": "wf0004.close",
                "next": "complete",
            },
            {"id": "complete", "type": "completion", "name": "Case closed"},
        ],
    }
)


# --- Handlers -----------------------------------------------------------------------------


def _loan(ctx: StepContext) -> Loan:
    loan = ctx.db.get(Loan, uuid.UUID(ctx.input["loan_id"]))
    if loan is None:
        raise StepError("loan_missing", "The loan does not exist.")
    return loan


@service_task("wf0004.open_case")
def open_case(ctx: StepContext) -> dict:
    loan = _loan(ctx)
    if loan.status != LoanStatus.ACTIVE:
        raise StepError("loan_closed", f"The loan is {loan.status}.")
    customer = ctx.db.get(Customer, loan.customer_id)
    state = servicing.arrears(ctx.db, loan, date.fromisoformat(ctx.input["business_date"]))
    if state.days_past_due == 0:
        raise StepError("not_in_arrears", f"{loan.loan_number} has nothing overdue.")
    ctx.set_business_key(str(loan.id))
    return {
        "loan_number": loan.loan_number,
        "subject": f"{loan.loan_number} · {customer.name if customer else '?'}",
        **state.as_dict(),
        "arrears": format_amount(state.amount, loan.currency),
    }


@service_task("wf0004.remind_borrower")
def remind_borrower(ctx: StepContext) -> dict:
    loan = _loan(ctx)
    note = CustomerNotification(
        customer_id=loan.customer_id,
        channel="simulated_letter",
        subject=f"Your loan {loan.loan_number} is in arrears",
        body=f"{ctx.get('open_case.arrears')} is overdue on loan {loan.loan_number}. Please "
        "pay the overdue instalments or contact us to agree a plan.",
        workflow_execution_id=ctx.execution.id,
    )
    ctx.db.add(note)
    ctx.db.flush()
    return {"sent": True, "notification_id": str(note.id)}


@service_task("wf0004.write_off")
def write_off(ctx: StepContext) -> dict:
    loan = _loan(ctx)
    # Approvals happen in real time; the write-off is booked on the lending business date.
    on = servicing.current_date(ctx.db)
    state = servicing.arrears(ctx.db, loan, on)
    if loan.status != LoanStatus.ACTIVE or state.days_past_due < servicing.WRITE_OFF_DAYS:
        # Paid while the review was open: nothing to write off.
        return {"written_off": False, "days_past_due": state.days_past_due}
    approver = principal(ctx, ctx.get("writeoff_review.actor_id"))
    servicing.write_off(ctx.db, loan.id, approver, on)
    return {"written_off": True, "days_past_due": state.days_past_due}


@service_task("wf0004.close")
def close(ctx: StepContext) -> dict:
    outcome = OUTCOMES[ctx.step.id]
    ctx.set_outcome(outcome)
    return {"outcome": outcome}


register_definition(DEFINITION, CollectionsCase)
register_presenter(
    WORKFLOW_ID,
    # The risk shown on the write-off review is the bucket the case escalated in.
    Presenter(subject_path="open_case.subject", risk_path="await_resolution.bucket"),
)


# --- Servicing listener ----------------------------------------------------------------------


def _at(on: date) -> datetime:
    """Business dates map to the end of the business day."""
    return datetime.combine(on, time(18, 0), tzinfo=UTC)


def open_case_for(db: Session, loan: Loan) -> WorkflowExecution | None:
    return (
        db.execute(
            select(WorkflowExecution)
            .where(
                WorkflowExecution.workflow_id == WORKFLOW_ID,
                WorkflowExecution.business_key == str(loan.id),
                WorkflowExecution.status.in_(list(ACTIVE_STATUSES)),
            )
            .order_by(WorkflowExecution.started_at.desc())
        )
        .scalars()
        .first()
    )


@servicing.on_arrears_change
def sync_collections(
    db: Session,
    loan: Loan,
    state: servicing.Arrears,
    on: date,
    actor: AuthenticatedUser,
) -> None:
    case = open_case_for(db, loan)
    waiting = case is not None and "await_resolution" in case.current_steps
    if loan.status != LoanStatus.ACTIVE or state.days_past_due == 0:
        if waiting:
            engine.signal(db, case.id, SIGNAL, {"status": "cured"}, actor.id, now=_at(on))
        return
    if case is None and state.days_past_due >= servicing.COLLECTIONS_DAYS:
        case, _ = engine.start(
            db,
            workflow_id=WORKFLOW_ID,
            payload={"loan_id": str(loan.id), "business_date": on.isoformat()},
            initiator=actor,
            now=_at(on),
        )
        waiting = "await_resolution" in case.current_steps
    if waiting and state.days_past_due >= servicing.WRITE_OFF_DAYS:
        engine.signal(
            db,
            case.id,
            SIGNAL,
            {
                "status": "escalate",
                "days_past_due": state.days_past_due,
                "bucket": state.bucket,
            },
            actor.id,
            now=_at(on),
        )
