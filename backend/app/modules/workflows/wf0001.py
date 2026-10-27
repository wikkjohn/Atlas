"""WF-0001 Retail Account Opening.

The definition is data; the handlers below orchestrate the existing banking services
(customers, accounts) rather than re-implementing their rules, so the four-eyes,
high-risk and eligibility controls of Phase 3 still apply when the workflow opens an
account. Identity documents and the sanctions list are synthetic.
"""

import re
import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.audit import record_audit_event
from app.core.permissions import permissions_for
from app.modules.accounts.models import AccountType
from app.modules.accounts.service import approve_request, submit_request
from app.modules.countries.models import Country, OperationalStatus
from app.modules.customers.models import CustomerNotification, CustomerType, KycStatus, RiskRating
from app.modules.customers.schemas import CustomerCreate, CustomerReview
from app.modules.customers.service import (
    age_in_years,
    create_customer,
    get_customer,
    review_customer,
)
from app.modules.identity.models import User
from app.modules.identity.service import AuthenticatedUser
from app.modules.workflows.definition import WorkflowDefinition
from app.modules.workflows.engine import StepContext, StepError
from app.modules.workflows.registry import register_definition, service_task

WORKFLOW_ID = "WF-0001"
VERSION = 1
NAME_PATTERN = r"^[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ' -]*$"
IDENTITY_DOCUMENTS = ("passport", "national_id")
DOCUMENT_PREFIX = {"passport": "P", "national_id": "N", "proof_of_address": "A"}
# Fictional names used to exercise sanctions screening. Not real people or entities.
SYNTHETIC_WATCHLIST = frozenset(
    {"darius vantablack", "morgana ledgerworth", "silas offshore", "vera shellcompany"}
)
LARGE_MONTHLY_DEPOSITS = 50_000  # whole units of the applicant's currency


# --- Input --------------------------------------------------------------------------------


class ApplicationDocument(BaseModel):
    document_type: Literal["passport", "national_id", "proof_of_address"]
    document_number: str = Field(pattern=r"^[PNA]\d{8}$")
    name_on_document: str = Field(min_length=2, max_length=200)
    date_of_birth: date | None = None
    expiry_date: date | None = None


class RetailAccountApplication(BaseModel):
    """A synthetic customer's application for a retail account."""

    applicant_name: str = Field(min_length=2, max_length=200, pattern=NAME_PATTERN)
    date_of_birth: date
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    account_type: Literal["current", "savings"] = "current"
    documents: list[ApplicationDocument] = Field(default_factory=list, max_length=10)
    politically_exposed: bool = False
    expected_monthly_deposits: int = Field(default=0, ge=0, le=10**9)


# --- Synthetic document numbers -----------------------------------------------------------


def checksum_digit(digits: str) -> int:
    return sum(int(d) for d in digits) % 10


def synthetic_document_number(document_type: str, serial: int) -> str:
    """A valid synthetic number: prefix, 7 serial digits and a check digit."""
    body = f"{serial % 10**7:07d}"
    return f"{DOCUMENT_PREFIX[document_type]}{body}{checksum_digit(body)}"


def document_number_valid(document_type: str, number: str) -> bool:
    if not re.fullmatch(r"[PNA]\d{8}", number) or number[0] != DOCUMENT_PREFIX[document_type]:
        return False
    return checksum_digit(number[1:8]) == int(number[8])


def _normalize(name: str) -> str:
    return " ".join(name.casefold().split())


# --- Definition ---------------------------------------------------------------------------


def _when(path: str, op: str, value: object = None) -> dict:
    return {"path": path, "op": op, "value": value}


DEFINITION = WorkflowDefinition.model_validate(
    {
        "workflow_id": WORKFLOW_ID,
        "name": "Retail Account Opening",
        "version": VERSION,
        "description": "Onboards a synthetic retail customer: validation, identity "
        "verification, sanctions screening, risk rating, compliance routing, four-eyes "
        "approval, account opening and notification.",
        "business_owner": "Retail Banking — Customer Onboarding",
        "trigger_type": "api",
        "start": "receive_application",
        "steps": [
            {
                "id": "receive_application",
                "type": "service_task",
                "name": "Customer submits application",
                "handler": "wf0001.receive_application",
                "next": "validate_application",
            },
            {
                "id": "validate_application",
                "type": "service_task",
                "name": "Validate required information",
                "handler": "wf0001.validate_application",
                "transitions": [
                    {
                        "to": "reject_application",
                        "when": _when("validate_application.status", "eq", "invalid"),
                    },
                    {
                        "to": "await_documents",
                        "when": _when("validate_application.status", "eq", "missing_documents"),
                    },
                    {"to": "register_customer"},
                ],
            },
            {
                "id": "await_documents",
                "type": "wait",
                "name": "Wait for missing documents",
                "signal": "documents_submitted",
                "timeout": {
                    "after_seconds": 72 * 3600,
                    "action": "transition",
                    "to": "reject_application",
                },
                "next": "validate_application",
            },
            {
                "id": "register_customer",
                "type": "service_task",
                "name": "Register synthetic customer",
                "handler": "wf0001.register_customer",
                "next": "checks",
            },
            {
                "id": "checks",
                "type": "parallel",
                "name": "Run identity and sanctions checks",
                "branches": ["identity_verification", "sanctions_screening"],
                "join": "checks_complete",
            },
            {
                "id": "identity_verification",
                "type": "service_task",
                "name": "Synthetic identity verification",
                "handler": "wf0001.identity_verification",
                "retry": {"max_attempts": 3, "backoff_seconds": 30},
                "next": "checks_complete",
            },
            {
                "id": "sanctions_screening",
                "type": "service_task",
                "name": "Sanctions screening (synthetic watchlist)",
                "handler": "wf0001.sanctions_screening",
                "next": "checks_complete",
            },
            {
                "id": "checks_complete",
                "type": "join",
                "name": "Checks complete",
                "next": "assign_risk_rating",
            },
            {
                "id": "assign_risk_rating",
                "type": "service_task",
                "name": "Assign customer risk rating",
                "handler": "wf0001.assign_risk_rating",
                "next": "evaluate_compliance",
            },
            {
                "id": "evaluate_compliance",
                "type": "service_task",
                "name": "Evaluate compliance rules",
                "handler": "wf0001.evaluate_compliance",
                "next": "route_case",
            },
            {
                "id": "route_case",
                "type": "decision",
                "name": "Route the case",
                "transitions": [
                    {
                        "to": "reject_application",
                        "when": _when("identity_verification.hard_fail", "truthy"),
                    },
                    {
                        "to": "compliance_review",
                        "when": _when("evaluate_compliance.requires_review", "truthy"),
                    },
                    {"to": "account_approval"},
                ],
            },
            {
                "id": "compliance_review",
                "type": "approval",
                "name": "Compliance review of a high-risk case",
                "approval": {
                    "permissions": ["customers:review", "accounts:approve"],
                    "distinct_from": ["initiator"],
                },
                "timeout": {"after_seconds": 48 * 3600, "action": "flag"},
                "transitions": [
                    {
                        "to": "open_account",
                        "when": _when("compliance_review.decision", "eq", "approve"),
                    },
                    {"to": "reject_application"},
                ],
            },
            {
                "id": "account_approval",
                "type": "approval",
                "name": "Authorized approval",
                "approval": {"permissions": ["accounts:approve"], "distinct_from": ["initiator"]},
                "timeout": {"after_seconds": 24 * 3600, "action": "flag"},
                "transitions": [
                    {
                        "to": "open_account",
                        "when": _when("account_approval.decision", "eq", "approve"),
                    },
                    {"to": "reject_application"},
                ],
            },
            {
                "id": "open_account",
                "type": "service_task",
                "name": "Create the customer account",
                "handler": "wf0001.open_account",
                "on_failure": "technical_failure",
                "next": "finalize_records",
            },
            {
                "id": "reject_application",
                "type": "service_task",
                "name": "Reject the application",
                "handler": "wf0001.reject_application",
                "next": "finalize_records",
            },
            {
                "id": "finalize_records",
                "type": "service_task",
                "name": "Finalize audit and workflow records",
                "handler": "wf0001.finalize_records",
                "next": "notify_customer",
            },
            {
                "id": "notify_customer",
                "type": "service_task",
                "name": "Send simulated customer notification",
                "handler": "wf0001.notify_customer",
                "next": "complete",
            },
            {"id": "complete", "type": "completion", "name": "Case closed"},
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


def _documents(ctx: StepContext) -> list[dict]:
    docs = list(ctx.input.get("documents", []))
    docs += ctx.get("await_documents.documents") or []
    return docs


@service_task("wf0001.receive_application")
def receive_application(ctx: StepContext) -> dict:
    return {
        "received_at": ctx.now.isoformat(),
        "applicant_name": ctx.input["applicant_name"],
        "documents_received": len(ctx.input.get("documents", [])),
    }


@service_task("wf0001.validate_application")
def validate_application(ctx: StepContext) -> dict:
    app = ctx.input
    reasons: list[str] = []
    country = ctx.db.execute(
        select(Country).where(Country.iso_country_code == app["country_code"])
    ).scalar_one_or_none()
    if country is None:
        reasons.append(f"Country {app['country_code']} is not configured.")
    elif country.operational_status != OperationalStatus.ACTIVE:
        reasons.append(f"{country.country_name} is not an active country.")
    age = age_in_years(date.fromisoformat(app["date_of_birth"]), ctx.now.date())
    if age < 18:
        reasons.append(f"The applicant is {age}; retail accounts require age 18 or over.")
    if reasons:
        return {"status": "invalid", "reasons": reasons}

    documents = _documents(ctx)
    kinds = {d["document_type"] for d in documents}
    missing = []
    if not kinds & set(IDENTITY_DOCUMENTS):
        missing.append("passport or national_id")
    if "proof_of_address" not in kinds:
        missing.append("proof_of_address")
    if missing:
        return {"status": "missing_documents", "missing": missing}
    return {"status": "valid", "documents": documents, "age": age}


@service_task("wf0001.register_customer")
def register_customer(ctx: StepContext) -> dict:
    app = ctx.input
    country = ctx.db.execute(
        select(Country).where(Country.iso_country_code == app["country_code"])
    ).scalar_one()
    customer = create_customer(
        ctx.db,
        CustomerCreate(
            customer_type=CustomerType.INDIVIDUAL,
            name=app["applicant_name"],
            date_of_birth_or_incorporation=date.fromisoformat(app["date_of_birth"]),
            country_id=country.id,
        ),
        actor_id=ctx.initiator_id,
        today=ctx.now.date(),
    )
    review_customer(
        ctx.db, customer, CustomerReview(kyc_status=KycStatus.PENDING, note="WF-0001"), None
    )
    ctx.set_business_key(str(customer.id))
    return {"customer_id": str(customer.id), "customer_number": customer.customer_number}


@service_task("wf0001.identity_verification")
def identity_verification(ctx: StepContext) -> dict:
    app = ctx.input
    documents = ctx.get("validate_application.documents") or []
    identity = next(d for d in documents if d["document_type"] in IDENTITY_DOCUMENTS)
    address = next(d for d in documents if d["document_type"] == "proof_of_address")
    issues: list[str] = []
    hard_fail = False
    for doc in (identity, address):
        if not document_number_valid(doc["document_type"], doc["document_number"]):
            issues.append(f"{doc['document_type']}_number_invalid")
            hard_fail = True
        if _normalize(doc["name_on_document"]) != _normalize(app["applicant_name"]):
            issues.append(f"{doc['document_type']}_name_mismatch")
    if identity.get("date_of_birth") and identity["date_of_birth"] != app["date_of_birth"]:
        issues.append("date_of_birth_mismatch")
        hard_fail = True
    expiry = identity.get("expiry_date")
    if not expiry or date.fromisoformat(expiry) <= ctx.now.date():
        issues.append("identity_document_expired")
    return {"verified": not issues, "issues": issues, "hard_fail": hard_fail}


@service_task("wf0001.sanctions_screening")
def sanctions_screening(ctx: StepContext) -> dict:
    name = _normalize(ctx.input["applicant_name"])
    hit = name in SYNTHETIC_WATCHLIST
    return {"hit": hit, "matched": name if hit else None, "list": "synthetic-watchlist-v1"}


@service_task("wf0001.assign_risk_rating")
def assign_risk_rating(ctx: StepContext) -> dict:
    factors: list[tuple[str, int]] = []
    if ctx.get("sanctions_screening.hit"):
        factors.append(("sanctions_hit", 5))
    if ctx.get("identity_verification.issues"):
        factors.append(("identity_issues", 3))
    if ctx.input.get("politically_exposed"):
        factors.append(("politically_exposed", 3))
    if ctx.input.get("expected_monthly_deposits", 0) > LARGE_MONTHLY_DEPOSITS:
        factors.append(("large_expected_deposits", 2))
    if (ctx.get("validate_application.age") or 99) < 21:
        factors.append(("young_applicant", 1))
    score = sum(points for _, points in factors)
    rating = RiskRating.LOW if score <= 1 else RiskRating.MEDIUM if score <= 3 else RiskRating.HIGH
    customer = get_customer(ctx.db, uuid.UUID(ctx.get("register_customer.customer_id")))
    review_customer(ctx.db, customer, CustomerReview(risk_rating=rating, note="WF-0001"), None)
    return {"score": score, "rating": rating.value, "factors": [name for name, _ in factors]}


@service_task("wf0001.evaluate_compliance")
def evaluate_compliance(ctx: StepContext) -> dict:
    flags = []
    if ctx.get("sanctions_screening.hit"):
        flags.append("sanctions_hit")
    if ctx.get("identity_verification.issues"):
        flags.append("identity_issues")
    if ctx.input.get("politically_exposed"):
        flags.append("politically_exposed")
    high_risk = ctx.get("assign_risk_rating.rating") == RiskRating.HIGH
    return {"flags": flags, "high_risk": high_risk, "requires_review": high_risk or bool(flags)}


def _principal(ctx: StepContext, user_id: str) -> AuthenticatedUser:
    user = ctx.db.get(User, uuid.UUID(user_id))
    if user is None or not user.is_active:
        raise StepError("approver_inactive", "The approving user is no longer active.")
    return AuthenticatedUser(
        id=user.id,
        username=user.username,
        role=user.role.code,
        permissions=permissions_for(user.role.code),
    )


@service_task("wf0001.open_account")
def open_account(ctx: StepContext) -> dict:
    approver_id = ctx.get("compliance_review.actor_id") or ctx.get("account_approval.actor_id")
    if not approver_id:
        raise StepError("no_approval", "No approval was recorded; the account cannot be opened.")
    customer = get_customer(ctx.db, uuid.UUID(ctx.get("register_customer.customer_id")))
    review_customer(
        ctx.db,
        customer,
        CustomerReview(kyc_status=KycStatus.VERIFIED, note="WF-0001 approved"),
        None,
    )
    request = submit_request(
        ctx.db,
        customer_id=customer.id,
        account_type=AccountType(ctx.input["account_type"]),
        currency=None,
        requested_by=ctx.initiator_id,
    )
    # The accounts service re-applies four-eyes, high-risk and eligibility rules.
    account = approve_request(ctx.db, request.id, _principal(ctx, approver_id), "WF-0001")
    ctx.set_outcome("approved")
    return {
        "account_id": str(account.id),
        "account_number": account.account_number,
        "account_request_id": str(request.id),
        "approved_by": approver_id,
    }


@service_task("wf0001.reject_application")
def reject_application(ctx: StepContext) -> dict:
    reasons: list[str] = []
    reasons += ctx.get("validate_application.reasons") or []
    if ctx.get("await_documents.timed_out"):
        reasons.append("Required documents were not received in time.")
    if ctx.get("identity_verification.hard_fail"):
        reasons.append("Identity documents failed verification.")
    for step in ("compliance_review", "account_approval"):
        if ctx.get(f"{step}.decision") == "reject":
            reasons.append(
                f"Declined at {step.replace('_', ' ')}: {ctx.get(f'{step}.note') or 'no note'}"
            )
    customer_id = ctx.get("register_customer.customer_id")
    if customer_id:
        customer = get_customer(ctx.db, uuid.UUID(customer_id))
        if customer.kyc_status == KycStatus.PENDING:
            review_customer(
                ctx.db,
                customer,
                CustomerReview(kyc_status=KycStatus.REJECTED, note="WF-0001 rejected"),
                None,
            )
    ctx.set_outcome("rejected")
    return {"reasons": reasons or ["Application rejected."]}


@service_task("wf0001.finalize_records")
def finalize_records(ctx: StepContext) -> dict:
    summary = {
        "outcome": ctx.get("outcome"),
        "customer_id": ctx.get("register_customer.customer_id"),
        "account_number": ctx.get("open_account.account_number"),
        "risk_rating": ctx.get("assign_risk_rating.rating"),
        "flags": ctx.get("evaluate_compliance.flags") or [],
    }
    record_audit_event(
        ctx.db,
        actor_id=None,
        action="workflow.account_opening_finalized",
        entity_type="workflow_execution",
        entity_id=ctx.execution.id,
        metadata=summary,
    )
    return {"finalized_at": ctx.now.isoformat(), **summary}


@service_task("wf0001.notify_customer")
def notify_customer(ctx: StepContext) -> dict:
    customer_id = ctx.get("register_customer.customer_id")
    if not customer_id:
        return {"sent": False, "reason": "The application never created a customer record."}
    approved = ctx.get("outcome") == "approved"
    subject = "Your account is open" if approved else "Your account application"
    number = ctx.get("open_account.account_number")
    body = (
        f"Your {ctx.input['account_type']} account {number} is open."
        if approved
        else "We could not open an account for you. Reasons: "
        + "; ".join(ctx.get("reject_application.reasons") or [])
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


register_definition(DEFINITION, RetailAccountApplication)
