"""WF-0003 Personal Loan Origination.

An existing, KYC-verified customer applies for an unsecured personal loan. The workflow
pulls a synthetic credit bureau report, prices the loan by score band, assesses
affordability, declines applications that break the credit policy outright and sends the
rest to an underwriter. Loans above the committee limit also need a credit committee
approval by a third person. Disbursement goes through the lending service, which
re-applies the KYC, ownership, limit and four-eyes controls before posting to the ledger.
"""

import uuid
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.audit import record_audit_event
from app.modules.accounts.models import AccountStatus
from app.modules.accounts.service import find_account
from app.modules.customers.models import Customer, CustomerNotification, KycStatus
from app.modules.customers.service import age_in_years
from app.modules.lending import service as lending
from app.modules.lending.models import LoanPurpose
from app.modules.workflows.definition import WorkflowDefinition
from app.modules.workflows.engine import StepContext, StepError
from app.modules.workflows.principals import principal
from app.modules.workflows.registry import (
    Presenter,
    register_definition,
    register_presenter,
    service_task,
)

WORKFLOW_ID = "WF-0003"
VERSION = 1
REFER_SCORE = 640  # below this an approvable application is flagged for the underwriter
REFER_DEBT_TO_INCOME = 0.35


# --- Input --------------------------------------------------------------------------------


class LoanApplication(BaseModel):
    """A synthetic customer's application for a personal loan."""

    customer_number: str = Field(pattern=r"^CUS-\d{7}$")
    disbursement_account_number: str = Field(pattern=r"^[A-Z]{2}\d{12}$")
    amount: int = Field(ge=1, le=10**12, description="Minor units of the account's currency")
    term_months: int = Field(ge=lending.MIN_TERM, le=lending.MAX_TERM)
    purpose: LoanPurpose
    monthly_income: int = Field(ge=0, le=10**12, description="Declared, minor units")
    monthly_debt_payments: int = Field(ge=0, le=10**12, description="Declared, minor units")
    employment_status: Literal["employed", "self_employed", "unemployed", "retired"]


# --- Definition ---------------------------------------------------------------------------


def _when(path: str, op: str, value: object = None) -> dict:
    return {"path": path, "op": op, "value": value}


DEFINITION = WorkflowDefinition.model_validate(
    {
        "workflow_id": WORKFLOW_ID,
        "name": "Personal Loan Origination",
        "version": VERSION,
        "description": "Originates an unsecured personal loan for an existing customer: "
        "validation, synthetic credit bureau check, risk-based pricing, affordability, "
        "credit policy, underwriting, credit committee for large loans, ledger disbursement "
        "and notification.",
        "business_owner": "Retail Lending",
        "trigger_type": "api",
        "start": "receive_application",
        "steps": [
            {
                "id": "receive_application",
                "type": "service_task",
                "name": "Customer submits loan application",
                "handler": "wf0003.receive_application",
                "next": "validate_application",
            },
            {
                "id": "validate_application",
                "type": "service_task",
                "name": "Validate customer, account and product limits",
                "handler": "wf0003.validate_application",
                "transitions": [
                    {
                        "to": "decline_application",
                        "when": _when("validate_application.valid", "eq", False),
                    },
                    {"to": "credit_check"},
                ],
            },
            {
                "id": "credit_check",
                "type": "service_task",
                "name": "Synthetic credit bureau check",
                "handler": "wf0003.credit_check",
                "retry": {"max_attempts": 3, "backoff_seconds": 60},
                "next": "affordability",
            },
            {
                "id": "affordability",
                "type": "service_task",
                "name": "Price the loan and assess affordability",
                "handler": "wf0003.affordability",
                "next": "credit_policy",
            },
            {
                "id": "credit_policy",
                "type": "service_task",
                "name": "Apply the credit policy",
                "handler": "wf0003.credit_policy",
                "transitions": [
                    {
                        "to": "decline_application",
                        "when": _when("credit_policy.decision", "eq", "decline"),
                    },
                    {"to": "underwriting_review"},
                ],
            },
            {
                "id": "underwriting_review",
                "type": "approval",
                "name": "Underwriting review",
                "approval": {"permissions": ["loans:approve"], "distinct_from": ["initiator"]},
                "timeout": {"after_seconds": 24 * 3600, "action": "flag"},
                "transitions": [
                    {
                        "to": "decline_application",
                        "when": _when("underwriting_review.decision", "ne", "approve"),
                    },
                    {
                        "to": "credit_committee",
                        "when": _when("affordability.committee_required", "truthy"),
                    },
                    {"to": "disburse_loan"},
                ],
            },
            {
                "id": "credit_committee",
                "type": "approval",
                "name": "Credit committee approval",
                "approval": {
                    "permissions": ["loans:approve_large"],
                    "distinct_from": ["initiator", "underwriting_review"],
                },
                "timeout": {"after_seconds": 48 * 3600, "action": "flag"},
                "transitions": [
                    {
                        "to": "disburse_loan",
                        "when": _when("credit_committee.decision", "eq", "approve"),
                    },
                    {"to": "decline_application"},
                ],
            },
            {
                "id": "disburse_loan",
                "type": "service_task",
                "name": "Book the loan and disburse the funds",
                "handler": "wf0003.disburse_loan",
                "on_failure": "technical_failure",
                "next": "notify_customer",
            },
            {
                "id": "decline_application",
                "type": "service_task",
                "name": "Decline the application",
                "handler": "wf0003.decline_application",
                "next": "notify_customer",
            },
            {
                "id": "notify_customer",
                "type": "service_task",
                "name": "Send simulated customer notification",
                "handler": "wf0003.notify_customer",
                "next": "complete",
            },
            {"id": "complete", "type": "completion", "name": "Application closed"},
            {
                "id": "technical_failure",
                "type": "failure",
                "name": "Technical failure",
                "outcome": "failed",
            },
        ],
    }
)


# --- Handlers -----------------------------------------------------------------------------


def _customer(ctx: StepContext) -> Customer | None:
    return ctx.db.execute(
        select(Customer).where(Customer.customer_number == ctx.input["customer_number"])
    ).scalar_one_or_none()


@service_task("wf0003.receive_application")
def receive_application(ctx: StepContext) -> dict:
    customer = _customer(ctx)
    name = customer.name if customer else ctx.input["customer_number"]
    return {"received_at": ctx.now.isoformat(), "applicant": name}


@service_task("wf0003.validate_application")
def validate_application(ctx: StepContext) -> dict:
    data = ctx.input
    reasons: list[str] = []
    customer = _customer(ctx)
    account = find_account(ctx.db, data["disbursement_account_number"])
    if customer is None:
        reasons.append("The customer does not exist.")
    else:
        if customer.kyc_status != KycStatus.VERIFIED:
            reasons.append("Loans are only made to KYC-verified customers.")
        age = age_in_years(customer.date_of_birth_or_incorporation, ctx.now.date())
        if age < 18:
            reasons.append(f"The applicant is {age}; the minimum age is 18.")
    if account is None:
        reasons.append("The disbursement account does not exist.")
    elif customer is not None:
        if account.customer_id != customer.id:
            reasons.append("The disbursement account belongs to someone else.")
        if account.status != AccountStatus.OPEN:
            reasons.append(f"The disbursement account is {account.status}.")
    if account is not None:
        low, high = lending.principal_limits(account.currency)
        if not low <= data["amount"] <= high:
            reasons.append(
                f"Personal loans range from {lending.format_amount(low, account.currency)} "
                f"to {lending.format_amount(high, account.currency)}."
            )
    if reasons:
        return {"valid": False, "reasons": reasons}
    assert customer is not None and account is not None
    ctx.set_business_key(str(customer.id))
    return {
        "valid": True,
        "customer_id": str(customer.id),
        "account_id": str(account.id),
        "currency": account.currency,
    }


@service_task("wf0003.credit_check")
def credit_check(ctx: StepContext) -> dict:
    customer = ctx.db.get(Customer, uuid.UUID(ctx.get("validate_application.customer_id")))
    if customer is None:
        raise StepError("customer_missing", "The customer record disappeared.")
    return lending.bureau_report(customer.name, customer.date_of_birth_or_incorporation)


@service_task("wf0003.affordability")
def affordability(ctx: StepContext) -> dict:
    data = ctx.input
    currency = ctx.get("validate_application.currency")
    score = ctx.get("credit_check.score")
    rate = lending.rate_for(score)
    payment = (
        lending.monthly_payment(data["amount"], rate, data["term_months"])
        if rate is not None
        else None
    )
    dti = (
        lending.debt_to_income(data["monthly_income"], data["monthly_debt_payments"], payment)
        if payment is not None
        else None
    )
    return {
        "annual_rate_bps": rate,
        "monthly_payment": payment,
        "debt_to_income": round(dti, 4) if dti is not None else None,
        "committee_required": lending.needs_committee(data["amount"], currency),
    }


@service_task("wf0003.credit_policy")
def credit_policy(ctx: StepContext) -> dict:
    """Hard declines are automatic; everything else goes to an underwriter."""
    score = ctx.get("credit_check.score")
    dti = ctx.get("affordability.debt_to_income")
    declines: list[str] = []
    if score < lending.MIN_SCORE:
        declines.append(f"Credit score {score} is below the minimum of {lending.MIN_SCORE}.")
    if (ctx.get("credit_check.recent_defaults") or 0) >= 2:
        declines.append("Two or more recent defaults on the bureau file.")
    if ctx.input["employment_status"] == "unemployed":
        declines.append("No income from employment or retirement.")
    if dti is None or dti > lending.MAX_DEBT_TO_INCOME:
        declines.append(
            f"Debt-to-income after the new loan exceeds {lending.MAX_DEBT_TO_INCOME:.0%}."
        )
    flags: list[str] = []
    if score < REFER_SCORE:
        flags.append("near_prime_score")
    if dti is not None and dti > REFER_DEBT_TO_INCOME:
        flags.append("high_debt_to_income")
    if ctx.input["employment_status"] == "self_employed":
        flags.append("self_employed_income")
    if ctx.get("affordability.committee_required"):
        flags.append("committee_required")
    risk = "high" if declines else "medium" if flags else "low"
    return {
        "decision": "decline" if declines else "refer",
        "reasons": declines,
        "flags": flags,
        "risk": risk,
    }


@service_task("wf0003.disburse_loan")
def disburse_loan(ctx: StepContext) -> dict:
    underwriter_id = ctx.get("underwriting_review.actor_id")
    if not underwriter_id:
        raise StepError("no_approval", "No underwriting approval was recorded.")
    committee_id = ctx.get("credit_committee.actor_id")
    loan = lending.originate(
        ctx.db,
        customer_id=uuid.UUID(ctx.get("validate_application.customer_id")),
        account_id=uuid.UUID(ctx.get("validate_application.account_id")),
        principal=ctx.input["amount"],
        annual_rate_bps=ctx.get("affordability.annual_rate_bps"),
        term_months=ctx.input["term_months"],
        purpose=ctx.input["purpose"],
        requested_by=ctx.initiator_id,
        underwriter=principal(ctx, underwriter_id),
        committee=principal(ctx, committee_id) if committee_id else None,
        workflow_execution_id=ctx.execution.id,
        now=ctx.now,
    )
    ctx.set_outcome("approved")
    return {
        "loan_id": str(loan.id),
        "loan_number": loan.loan_number,
        "monthly_payment": loan.monthly_payment,
        "disbursement_entry_id": str(loan.disbursement_entry_id),
    }


@service_task("wf0003.decline_application")
def decline_application(ctx: StepContext) -> dict:
    reasons: list[str] = list(ctx.get("validate_application.reasons") or [])
    reasons += ctx.get("credit_policy.reasons") or []
    for step in ("underwriting_review", "credit_committee"):
        if ctx.get(f"{step}.decision") == "reject":
            reasons.append(
                f"Declined at {step.replace('_', ' ')}: {ctx.get(f'{step}.note') or 'no note'}"
            )
    record_audit_event(
        ctx.db,
        actor_id=None,
        action="workflow.loan_declined",
        entity_type="workflow_execution",
        entity_id=ctx.execution.id,
        metadata={"reasons": reasons},
    )
    ctx.set_outcome("rejected")
    return {"reasons": reasons or ["Application declined."]}


@service_task("wf0003.notify_customer")
def notify_customer(ctx: StepContext) -> dict:
    customer_id = ctx.get("validate_application.customer_id")
    if not customer_id:
        customer = _customer(ctx)
        if customer is None:
            return {"sent": False, "reason": "The applicant could not be identified."}
        customer_id = str(customer.id)
    approved = ctx.get("outcome") == "approved"
    subject = "Your loan has been paid out" if approved else "Your loan application"
    if approved:
        currency = ctx.get("validate_application.currency")
        body = (
            f"Loan {ctx.get('disburse_loan.loan_number')} of "
            f"{lending.format_amount(ctx.input['amount'], currency)} was paid into "
            f"{ctx.input['disbursement_account_number']}. Monthly payment: "
            f"{lending.format_amount(ctx.get('disburse_loan.monthly_payment'), currency)}."
        )
    else:
        body = "We cannot offer you this loan. Reasons: " + "; ".join(
            ctx.get("decline_application.reasons") or []
        )
    notification = CustomerNotification(
        customer_id=uuid.UUID(customer_id),
        channel="simulated_email",
        subject=subject,
        body=body,
        workflow_execution_id=ctx.execution.id,
    )
    ctx.db.add(notification)
    ctx.db.flush()
    return {"sent": True, "notification_id": str(notification.id), "subject": subject}


register_definition(DEFINITION, LoanApplication)
register_presenter(
    WORKFLOW_ID,
    Presenter(
        subject_path="receive_application.applicant",
        risk_path="credit_policy.risk",
        flags_path="credit_policy.flags",
    ),
)
