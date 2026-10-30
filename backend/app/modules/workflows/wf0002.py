"""WF-0002 Domestic Payment.

A customer pays another customer of the bank. The definition is data (unchanged since
Phase 9, so its name still says domestic); since Phase 24 the payee's account may be in
another currency, and the payments service converts at release through an FX deal;
the handlers orchestrate the payments service, which re-applies the money controls itself
(open accounts, funds, four-eyes and the high-value approval rule) when it releases a
payment.

Most payments go straight through. Screening holds the suspicious ones for a fraud
reviewer, and high-value payments need a manager's approval. An optional AI fraud screener
(off, assisted or automated) analyses held payments; in automated mode the policy engine
may release a held payment the screener rates low risk, but only when every policy check
passes. All accounts, payees and watchlists are synthetic.
"""

import uuid
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.money import minor_unit_exponent
from app.modules.accounts.models import AccountStatus
from app.modules.accounts.service import find_account
from app.modules.compliance.screening import SYNTHETIC_WATCHLIST
from app.modules.customers.models import CustomerNotification
from app.modules.fx import rates as fx_rates
from app.modules.ledger import service as ledger
from app.modules.payments import service as payments
from app.modules.payments.models import PaymentStatus
from app.modules.workflows import advisory
from app.modules.workflows.definition import WorkflowDefinition
from app.modules.workflows.engine import StepContext
from app.modules.workflows.models import WorkflowExecution
from app.modules.workflows.principals import policy_engine, principal
from app.modules.workflows.registry import (
    Presenter,
    ai_task,
    on_cancel,
    register_definition,
    register_presenter,
    service_task,
)

WORKFLOW_ID = "WF-0002"
VERSION = 1
ACCOUNT_NUMBER = r"^[A-Z]{2}\d{12}$"
# Synthetic scam phrases screening looks for (fictional, for simulation only).
SCAM_PHRASES = (
    "gift card",
    "crypto",
    "lottery",
    "investment opportunity",
    "release fee",
    "customs fee",
    "safe account",
)
VELOCITY_WINDOW = timedelta(hours=24)
VELOCITY_LIMIT = 3  # other payments from the same account inside the window
DRAIN_SHARE = 0.8  # of the balance in one payment
HOLD_SCORE = 3  # screening score at which a payment is held for review
SIGNAL_POINTS = {
    "sanctions_hit": 5,
    "scam_reference": 3,
    "drains_account": 2,
    "velocity": 2,
    "new_payee": 1,
}
POLICY_ID = "low-risk-payment-release-v1"


# --- Input --------------------------------------------------------------------------------


class PaymentInstruction(BaseModel):
    """A synthetic customer's instruction to pay another account at the bank."""

    debtor_account_number: str = Field(pattern=ACCOUNT_NUMBER)
    creditor_account_number: str = Field(pattern=ACCOUNT_NUMBER)
    amount: int = Field(ge=1, le=10**12, description="Minor units of the currency")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    reference: str = Field(min_length=1, max_length=140)
    channel: Literal["branch", "online", "mobile"] = "online"


def format_amount(amount: int, currency: str) -> str:
    exponent = minor_unit_exponent(currency)
    return f"{amount / 10**exponent:,.{exponent}f} {currency}"


# --- Definition ---------------------------------------------------------------------------


def _when(path: str, op: str, value: object = None) -> dict:
    return {"path": path, "op": op, "value": value}


DEFINITION = WorkflowDefinition.model_validate(
    {
        "workflow_id": WORKFLOW_ID,
        "name": "Domestic Payment",
        "version": VERSION,
        "description": "Pays another account at the bank: validation, funds check, fraud and "
        "sanctions screening, an optional AI fraud screener for held payments, fraud review, "
        "high-value four-eyes approval, ledger posting and notification.",
        "business_owner": "Payments Operations",
        "trigger_type": "api",
        "start": "receive_payment",
        "steps": [
            {
                "id": "receive_payment",
                "type": "service_task",
                "name": "Customer instructs payment",
                "handler": "wf0002.receive_payment",
                "next": "validate_payment",
            },
            {
                "id": "validate_payment",
                "type": "service_task",
                "name": "Validate accounts and amount",
                "handler": "wf0002.validate_payment",
                "transitions": [
                    {
                        "to": "reject_payment",
                        "when": _when("validate_payment.valid", "eq", False),
                    },
                    {"to": "funds_check"},
                ],
            },
            {
                "id": "funds_check",
                "type": "service_task",
                "name": "Check available funds",
                "handler": "wf0002.funds_check",
                "transitions": [
                    {
                        "to": "reject_payment",
                        "when": _when("funds_check.sufficient", "eq", False),
                    },
                    {"to": "screen_payment"},
                ],
            },
            {
                "id": "screen_payment",
                "type": "service_task",
                "name": "Fraud and sanctions screening",
                "handler": "wf0002.screen_payment",
                "next": "route_payment",
            },
            {
                "id": "route_payment",
                "type": "decision",
                "name": "Route the payment",
                "transitions": [
                    {"to": "ai_fraud_review", "when": _when("screen_payment.hold", "truthy")},
                    {
                        "to": "payment_approval",
                        "when": _when("validate_payment.high_value", "truthy"),
                    },
                    {"to": "release_payment"},
                ],
            },
            {
                "id": "ai_fraud_review",
                "type": "ai_task",
                "name": "AI fraud screener review (advisory)",
                "handler": "wf0002.fraud_screener",
                "next": "route_held_payment",
            },
            {
                "id": "route_held_payment",
                "type": "decision",
                "name": "Route the held payment",
                "transitions": [
                    {
                        "to": "policy_release",
                        "when": _when("ai_fraud_review.automation_requested", "truthy"),
                    },
                    {"to": "fraud_review"},
                ],
            },
            {
                "id": "policy_release",
                "type": "service_task",
                "name": "Policy engine: low-risk release check",
                "handler": "wf0002.policy_release",
                "transitions": [
                    {"to": "release_payment", "when": _when("policy_release.approved", "truthy")},
                    {"to": "fraud_review"},
                ],
            },
            {
                "id": "fraud_review",
                "type": "approval",
                "name": "Fraud review of a held payment",
                "approval": {"permissions": ["payments:review"], "distinct_from": ["initiator"]},
                "timeout": {"after_seconds": 4 * 3600, "action": "flag"},
                "transitions": [
                    {
                        "to": "reject_payment",
                        "when": _when("fraud_review.decision", "ne", "approve"),
                    },
                    {
                        "to": "payment_approval",
                        "when": _when("validate_payment.high_value", "truthy"),
                    },
                    {"to": "release_payment"},
                ],
            },
            {
                "id": "payment_approval",
                "type": "approval",
                "name": "High-value approval (four-eyes)",
                "approval": {
                    "permissions": ["payments:approve"],
                    "distinct_from": ["initiator", "fraud_review"],
                },
                "timeout": {"after_seconds": 2 * 3600, "action": "flag"},
                "transitions": [
                    {
                        "to": "release_payment",
                        "when": _when("payment_approval.decision", "eq", "approve"),
                    },
                    {"to": "reject_payment"},
                ],
            },
            {
                "id": "release_payment",
                "type": "service_task",
                "name": "Post the payment to the ledger",
                "handler": "wf0002.release_payment",
                "on_failure": "reject_payment",
                "next": "notify_customer",
            },
            {
                "id": "reject_payment",
                "type": "service_task",
                "name": "Reject the payment",
                "handler": "wf0002.reject_payment",
                "next": "notify_customer",
            },
            {
                "id": "notify_customer",
                "type": "service_task",
                "name": "Send simulated customer notification",
                "handler": "wf0002.notify_customer",
                "next": "complete",
            },
            {"id": "complete", "type": "completion", "name": "Payment closed"},
        ],
    }
)


# --- Handlers -----------------------------------------------------------------------------


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


@service_task("wf0002.receive_payment")
def receive_payment(ctx: StepContext) -> dict:
    data = ctx.input
    return {
        "received_at": ctx.now.isoformat(),
        "summary": f"{format_amount(data['amount'], data['currency'])} to "
        f"{data['creditor_account_number']}",
    }


@service_task("wf0002.validate_payment")
def validate_payment(ctx: StepContext) -> dict:
    data = ctx.input
    reasons: list[str] = []
    debtor = find_account(ctx.db, data["debtor_account_number"])
    creditor = find_account(ctx.db, data["creditor_account_number"])
    if debtor is None:
        reasons.append("The paying account does not exist.")
    if creditor is None:
        reasons.append("The payee account does not exist.")
    if debtor is not None and creditor is not None:
        if debtor.id == creditor.id:
            reasons.append("The paying and receiving accounts are the same.")
        for label, account in (("paying", debtor), ("payee", creditor)):
            if account.status != AccountStatus.OPEN:
                reasons.append(f"The {label} account is {account.status}.")
        if debtor.currency != data["currency"]:
            reasons.append(f"The paying account is not held in {data['currency']}.")
        if creditor.currency != debtor.currency and not (
            fx_rates.supported(debtor.currency) and fx_rates.supported(creditor.currency)
        ):
            reasons.append(
                f"Payments from {debtor.currency} to {creditor.currency} are not offered."
            )
        if data["amount"] > payments.max_amount(data["currency"]):
            reasons.append("The amount exceeds the single-payment limit.")
    if reasons:
        return {"valid": False, "reasons": reasons}
    assert debtor is not None and creditor is not None
    payment = payments.create_payment(
        ctx.db,
        debtor=debtor,
        creditor=creditor,
        amount=data["amount"],
        reference=data["reference"],
        initiated_by=ctx.initiator_id,
        workflow_execution_id=ctx.execution.id,
        now=ctx.now,
    )
    ctx.set_business_key(payment.payment_number)
    return {
        "valid": True,
        "payment_id": str(payment.id),
        "payment_number": payment.payment_number,
        "high_value": payments.is_high_value(payment.amount, payment.currency),
        "debtor_account_id": str(debtor.id),
        "debtor_customer_id": str(debtor.customer_id),
        "creditor_account_id": str(creditor.id),
        "creditor_name": creditor.customer.name,
        "cross_currency": payment.creditor_currency is not None,
        "creditor_currency": creditor.currency,
        "estimated_creditor_amount": payment.creditor_amount,
    }


@service_task("wf0002.funds_check")
def funds_check(ctx: StepContext) -> dict:
    # An early check only: the payments service checks again, under a lock, on release.
    debtor = find_account(ctx.db, ctx.input["debtor_account_number"])
    assert debtor is not None
    available = ledger.balance(ctx.db, ledger.get_ledger_account(ctx.db, debtor.ledger_account_id))
    amount = ctx.input["amount"]
    return {
        "sufficient": amount <= available,
        "available": available,
        "share_of_balance": round(amount / available, 4) if available > 0 else None,
    }


@service_task("wf0002.screen_payment")
def screen_payment(ctx: StepContext) -> dict:
    debtor_id = uuid.UUID(ctx.get("validate_payment.debtor_account_id"))
    creditor_id = uuid.UUID(ctx.get("validate_payment.creditor_account_id"))
    payment_id = uuid.UUID(ctx.get("validate_payment.payment_id"))
    reference = _normalize(ctx.input["reference"])
    recent = payments.recent_count(ctx.db, debtor_id, ctx.now - VELOCITY_WINDOW, payment_id)
    share = ctx.get("funds_check.share_of_balance") or 0
    signals = {
        "sanctions_hit": _normalize(ctx.get("validate_payment.creditor_name") or "")
        in SYNTHETIC_WATCHLIST,
        "scam_reference": any(phrase in reference for phrase in SCAM_PHRASES),
        "drains_account": share >= DRAIN_SHARE,
        "velocity": recent >= VELOCITY_LIMIT,
        "new_payee": payments.released_between(ctx.db, debtor_id, creditor_id) == 0,
    }
    flags = [name for name, raised in signals.items() if raised]
    score = sum(SIGNAL_POINTS[name] for name in flags)
    risk = "high" if signals["sanctions_hit"] or score >= 5 else "medium" if score >= 2 else "low"
    return {
        "flags": flags,
        "score": score,
        "risk": risk,
        "hold": signals["sanctions_hit"] or score >= HOLD_SCORE,
        "recent_payments_24h": recent,
        "share_of_balance": share,
        "watchlist": "synthetic-watchlist-v1",
    }


@ai_task("wf0002.fraud_screener")
def fraud_screener(ctx: StepContext) -> dict:
    data = ctx.input
    flags = ctx.get("screen_payment.flags") or []
    payload = {
        "payment": {
            "amount": data["amount"],
            "currency": data["currency"],
            "reference": data["reference"],
            "channel": data.get("channel", "online"),
            "high_value": bool(ctx.get("validate_payment.high_value")),
        },
        "signals": {
            "sanctions_hit": "sanctions_hit" in flags,
            "new_payee": "new_payee" in flags,
            "recent_payments_24h": ctx.get("screen_payment.recent_payments_24h") or 0,
            "share_of_balance": ctx.get("screen_payment.share_of_balance") or 0,
        },
        "as_of": ctx.now.date().isoformat(),
    }
    return advisory.review(ctx, assisted_action="recommend_decision", payload=payload)


@service_task("wf0002.policy_release")
def policy_release(ctx: StepContext) -> dict:
    ai = ctx.get("ai_fraud_review") or {}
    flags = set(ctx.get("screen_payment.flags") or [])
    checks = {
        "automation_enabled": (ctx.get("_settings") or {}).get("ai_mode") == "automated",
        "tool_result_available": bool(ai.get("available")),
        "tool_recommends_approval": ai.get("recommendation") == "approve",
        "tool_risk_low": ai.get("risk_classification") == "low",
        "not_high_value": not ctx.get("validate_payment.high_value"),
        "sanctions_clear": "sanctions_hit" not in flags,
        "no_scam_indicators": "scam_reference" not in flags,
    }
    failed = [name for name, passed in checks.items() if not passed]
    result = {"policy": POLICY_ID, "checks": checks, "failed_checks": failed}
    if failed:
        return {**result, "approved": False}
    engine_user = policy_engine(ctx)
    if engine_user is None:
        return {**result, "approved": False, "failed_checks": ["policy_engine_unavailable"]}
    record_audit_event(
        ctx.db,
        actor_id=engine_user.id,
        action="workflow.policy_approved",
        entity_type="workflow_execution",
        entity_id=ctx.execution.id,
        metadata={"policy": POLICY_ID, "tool_invocation": ai.get("invocation_id")},
    )
    # The payments service re-checks: this principal may release low-value payments only.
    return {**result, "approved": True, "approver_id": str(engine_user.id)}


@service_task("wf0002.release_payment")
def release_payment(ctx: StepContext) -> dict:
    approver_id = (
        ctx.get("payment_approval.actor_id")
        or ctx.get("fraud_review.actor_id")
        or ctx.get("policy_release.approver_id")
    )
    approver = principal(ctx, approver_id) if approver_id else None
    payment = payments.release(
        ctx.db,
        uuid.UUID(ctx.get("validate_payment.payment_id")),
        approver=approver,
        now=ctx.now,
    )
    ctx.set_outcome("approved")
    return {
        "payment_number": payment.payment_number,
        "journal_entry_id": str(payment.journal_entry_id),
        "creditor_amount": payment.creditor_amount or payment.amount,
        "creditor_currency": payment.creditor_currency or payment.currency,
        "approved_by": approver_id,
        "straight_through": approver_id is None,
    }


@service_task("wf0002.reject_payment")
def reject_payment(ctx: StepContext) -> dict:
    reasons: list[str] = list(ctx.get("validate_payment.reasons") or [])
    if ctx.get("funds_check.sufficient") is False:
        reasons.append("Insufficient funds.")
    for step in ("fraud_review", "payment_approval"):
        if ctx.get(f"{step}.decision") == "reject":
            reasons.append(
                f"Declined at {step.replace('_', ' ')}: {ctx.get(f'{step}.note') or 'no note'}"
            )
    failure = ctx.get("_failure")
    if failure and failure.get("step") == "release_payment":
        reasons.append(f"Release refused: {failure.get('message')}")
    payment_id = ctx.get("validate_payment.payment_id")
    if payment_id:
        payments.reject(
            ctx.db, uuid.UUID(payment_id), "; ".join(reasons) or "Rejected.", now=ctx.now
        )
    ctx.set_outcome("rejected")
    return {"reasons": reasons or ["Payment rejected."]}


@service_task("wf0002.notify_customer")
def notify_customer(ctx: StepContext) -> dict:
    customer_id = ctx.get("validate_payment.debtor_customer_id")
    if not customer_id:
        return {"sent": False, "reason": "The paying account could not be identified."}
    data = ctx.input
    amount = format_amount(data["amount"], data["currency"])
    approved = ctx.get("outcome") == "approved"
    subject = "Payment sent" if approved else "Payment not sent"
    body = (
        f"Your payment of {amount} to {data['creditor_account_number']} was sent"
        + (
            f" ({format_amount(ctx.get('release_payment.creditor_amount'), converted)} "
            "after conversion)."
            if (converted := ctx.get("release_payment.creditor_currency"))
            not in (None, data["currency"])
            else "."
        )
        if approved
        else f"Your payment of {amount} was not sent. Reasons: "
        + "; ".join(ctx.get("reject_payment.reasons") or [])
    )
    notification = CustomerNotification(
        customer_id=uuid.UUID(customer_id),
        channel="simulated_push",
        subject=subject,
        body=body,
        workflow_execution_id=ctx.execution.id,
    )
    ctx.db.add(notification)
    ctx.db.flush()
    return {"sent": True, "notification_id": str(notification.id), "subject": subject}


@on_cancel(WORKFLOW_ID)
def cancel_payment(db: Session, execution: WorkflowExecution, reason: str, now: datetime) -> None:
    """A cancelled case must not leave its payment pending forever."""
    payment_id = (execution.context.get("validate_payment") or {}).get("payment_id")
    if not payment_id:
        return
    payment = payments.get_payment(db, uuid.UUID(payment_id))
    if payment.status == PaymentStatus.PENDING:
        payments.reject(db, payment.id, f"Workflow cancelled: {reason}", now=now)


register_definition(DEFINITION, PaymentInstruction)
register_presenter(
    WORKFLOW_ID,
    Presenter(
        subject_path="receive_payment.summary",
        risk_path="screen_payment.risk",
        flags_path="screen_payment.flags",
    ),
)
