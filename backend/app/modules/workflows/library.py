"""The step-handler library: generic handlers that stored definitions may use.

A stored definition (imported as data, see store.py) cannot ship code, so its service
tasks name handlers from this library and configure them with `params`. Each handler
declares a params model, checked when the definition is imported, and the context paths
it reads, checked against what the workflow can know at that point.

Phase 17 added the generic `core.*` handlers; Phase 18 the domain handlers that read
and change banking records (`customers.*`, `compliance.*`, `accounts.*`) and the advisory
AI call (`ai.review`). Each declares its effect. A handler that moves money must be
behind an approval: validation refuses a definition in which any path reaches it without
passing an approval step.
"""

import re
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from app.modules.workflows import registry
from app.modules.workflows.definition import Condition, StepType
from app.modules.workflows.engine import StepContext, StepError

# What a handler does beyond computing its output.
Effect = Literal["none", "reads", "writes", "moves_money", "advisory"]


@dataclass(frozen=True)
class LibraryHandler:
    name: str
    step_type: StepType
    summary: str
    params_model: type[BaseModel]
    output: str
    # The context paths a step with these params reads (checked on import).
    reads: Callable[[Any], list[str]]
    effect: Effect = "none"
    # Every path to the step must pass an approval step (checked on import).
    requires_approval: bool = False
    # Checks needing the database, e.g. that a named AI tool exists: (db, params) -> errors.
    check: Callable[[Any, Any], list[str]] | None = None
    # Context paths that must name real records, and which (Phase 20's generated tests
    # create them): {path: "customer.customer_number" | "customer.name" | "customer.id" |
    # "account.account_number"}.
    fixtures: Callable[[Any], dict[str, str]] | None = None

    def params_schema(self) -> dict[str, Any]:
        return self.params_model.model_json_schema()


LIBRARY: dict[str, LibraryHandler] = {}


@dataclass(frozen=True)
class Forced:
    """Set only by the generated workflow tests (testing.py), for the steps of one test
    case: fail a step, or add fields to its output, to steer the case down a route."""

    fail: frozenset[str] = frozenset()
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)


# A context variable, so forcing never leaks into other requests or threads.
FORCED: ContextVar[Forced | None] = ContextVar("workflow_test_forced", default=None)


def _library_handler(
    name: str,
    summary: str,
    params_model: type[BaseModel],
    output: str,
    reads: Callable[[Any], list[str]] = lambda params: [],
    *,
    effect: Effect = "none",
    requires_approval: bool = False,
    check: Callable[[Any, Any], list[str]] | None = None,
    step_type: StepType = StepType.SERVICE_TASK,
    fixtures: Callable[[Any], dict[str, str]] | None = None,
) -> Callable[[Callable[[StepContext, Any], dict[str, Any]]], None]:
    def register(func: Callable[[StepContext, Any], dict[str, Any]]) -> None:
        def run(ctx: StepContext) -> dict[str, Any]:
            forced = FORCED.get()
            if forced and ctx.step.id in forced.fail:
                raise StepError("injected_failure", f"Test: failure injected at '{ctx.step.id}'.")
            output = func(ctx, params_model.model_validate(ctx.step.params or {}))
            if forced and ctx.step.id in forced.outputs:
                output = {**output, **forced.outputs[ctx.step.id]}
            return output

        if step_type == StepType.AI_TASK:
            registry.ai_task(name)(run)
        else:
            registry.service_task(name)(run)
        LIBRARY[name] = LibraryHandler(
            name, step_type, summary, params_model, output, reads, effect,
            requires_approval, check, fixtures,
        )  # fmt: skip

    return register


def get(name: str) -> LibraryHandler | None:
    return LIBRARY.get(name)


Code = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")


class _Strict(BaseModel):
    model_config = {"extra": "forbid"}


class SetValues(_Strict):
    values: dict[str, Any] = Field(min_length=1, max_length=50)


@_library_handler(
    "core.set_values",
    "Record fixed values (product codes, limits, flags) in the context.",
    SetValues,
    "The values, under the step's id.",
)
def _set_values(ctx: StepContext, params: SetValues) -> dict[str, Any]:
    return dict(params.values)


class CopyValues(_Strict):
    # Output name -> dotted context path, e.g. {"country": "input.country"}.
    fields: dict[str, str] = Field(min_length=1, max_length=50)
    required: bool = True


@_library_handler(
    "core.copy_values",
    "Copy values from the input or earlier steps under new names.",
    CopyValues,
    "One key per field; a missing path fails the step when `required`.",
    reads=lambda params: list(params.fields.values()),
)
def _copy_values(ctx: StepContext, params: CopyValues) -> dict[str, Any]:
    output, missing = {}, []
    for name, path in params.fields.items():
        sentinel = object()
        value = ctx.get(path, sentinel)
        if value is sentinel:
            missing.append(path)
        else:
            output[name] = value
    if missing and params.required:
        raise StepError("missing_value", "Required values are missing.", {"paths": missing})
    return output


class Check(_Strict):
    condition: Condition
    code: str = Code
    message: str = Field(min_length=1, max_length=300)


def _condition_paths(condition: Condition) -> list[str]:
    if condition.path is not None:
        return [condition.path]
    return [p for c in (condition.all or condition.any or []) for p in _condition_paths(c)]


@_library_handler(
    "core.check",
    "Fail the step with a business error unless a condition holds (route with on_failure).",
    Check,
    "{passed: true}; otherwise the step fails with `code` and `message` (not retried).",
    reads=lambda params: _condition_paths(params.condition),
)
def _check(ctx: StepContext, params: Check) -> dict[str, Any]:
    if not params.condition.evaluate(ctx.context):
        raise StepError(params.code, params.message)
    return {"passed": True}


class BusinessKey(_Strict):
    path: str = Field(min_length=1, max_length=200)
    prefix: str = Field(default="", max_length=40)


@_library_handler(
    "core.business_key",
    "Set the case's business key (what lists and searches show) from a context value.",
    BusinessKey,
    "{business_key}",
    reads=lambda params: [params.path],
    effect="writes",
)
def _business_key(ctx: StepContext, params: BusinessKey) -> dict[str, Any]:
    sentinel = object()
    value = ctx.get(params.path, sentinel)
    if value is sentinel or value is None:
        raise StepError("missing_value", f"No value at '{params.path}' for the business key.")
    key = f"{params.prefix}{value}"[:100]
    ctx.set_business_key(key)
    return {"business_key": key}


class Notify(_Strict):
    channel: Literal["email", "sms", "letter", "in_app"]
    template: str = Code
    recipient_path: str | None = Field(default=None, max_length=200)


@_library_handler(
    "core.notify",
    "Record a synthetic customer notification (nothing leaves the platform).",
    Notify,
    "{channel, template, recipient, sent_at}",
    reads=lambda params: [params.recipient_path] if params.recipient_path else [],
)
def _notify(ctx: StepContext, params: Notify) -> dict[str, Any]:
    recipient = ctx.get(params.recipient_path) if params.recipient_path else None
    return {
        "channel": params.channel,
        "template": params.template,
        "recipient": recipient,
        "sent_at": ctx.now.isoformat(),
    }


class SetOutcome(_Strict):
    outcome: str = Code


@_library_handler(
    "core.set_outcome",
    "Set the outcome the execution will complete with.",
    SetOutcome,
    "{outcome}",
)
def _set_outcome(ctx: StepContext, params: SetOutcome) -> dict[str, Any]:
    ctx.set_outcome(params.outcome)
    return {"outcome": params.outcome}


# --- Domain handlers (Phase 18) ------------------------------------------------------------


def _required(ctx: StepContext, path: str) -> Any:
    sentinel = object()
    value = ctx.get(path, sentinel)
    if value is sentinel or value is None or value == "":
        raise StepError("missing_value", f"No value at '{path}'.", {"path": path})
    return value


def _customer(ctx: StepContext, customer_id_path: str):
    from app.modules.customers.models import Customer

    raw = _required(ctx, customer_id_path)
    try:
        customer = ctx.db.get(Customer, uuid.UUID(str(raw)))
    except ValueError:
        customer = None
    if customer is None:
        raise StepError("customer_not_found", f"No customer with id {raw}.")
    return customer


class LookupCustomer(_Strict):
    customer_number_path: str = Field(min_length=1, max_length=200)


@_library_handler(
    "customers.lookup",
    "Find a customer by customer number and record who they are.",
    LookupCustomer,
    "{customer_id, customer_number, name, customer_type, country_code, kyc_status, "
    "risk_rating}; an unknown number fails the step (customer_not_found).",
    reads=lambda params: [params.customer_number_path],
    effect="reads",
    fixtures=lambda params: {params.customer_number_path: "customer.customer_number"},
)
def _lookup_customer(ctx: StepContext, params: LookupCustomer) -> dict[str, Any]:
    from app.modules.customers.models import Customer

    number = str(_required(ctx, params.customer_number_path))
    customer = ctx.db.execute(
        select(Customer).where(Customer.customer_number == number)
    ).scalar_one_or_none()
    if customer is None:
        raise StepError("customer_not_found", f"No customer {number}.")
    return {
        "customer_id": str(customer.id),
        "customer_number": customer.customer_number,
        "name": customer.name,
        "customer_type": customer.customer_type,
        "country_code": customer.country.iso_country_code,
        "kyc_status": customer.kyc_status,
        "risk_rating": customer.risk_rating,
    }


PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_.]*)\}")


class NotifyCustomer(_Strict):
    customer_id_path: str = Field(min_length=1, max_length=200)
    channel: Literal["simulated_email", "simulated_sms", "simulated_letter"] = "simulated_email"
    # {dotted.path} placeholders are filled from the context.
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=2000)


def _placeholders(*texts: str) -> list[str]:
    return [m.group(1) for text in texts for m in PLACEHOLDER.finditer(text)]


def _fill(ctx: StepContext, text: str) -> str:
    return PLACEHOLDER.sub(lambda m: str(ctx.get(m.group(1), "")), text)


@_library_handler(
    "customers.notify",
    "Send the customer a synthetic message, stored in their notifications.",
    NotifyCustomer,
    "{notification_id, channel, subject}",
    reads=lambda params: [params.customer_id_path, *_placeholders(params.subject, params.body)],
    effect="writes",
    fixtures=lambda params: {params.customer_id_path: "customer.id"},
)
def _notify_customer(ctx: StepContext, params: NotifyCustomer) -> dict[str, Any]:
    from app.modules.customers.models import CustomerNotification

    customer = _customer(ctx, params.customer_id_path)
    subject = _fill(ctx, params.subject)[:200]
    notification = CustomerNotification(
        customer_id=customer.id,
        channel=params.channel,
        subject=subject,
        body=_fill(ctx, params.body),
        workflow_execution_id=ctx.execution.id,
    )
    ctx.db.add(notification)
    ctx.db.flush()
    return {"notification_id": str(notification.id), "channel": params.channel, "subject": subject}


class SetRiskRating(_Strict):
    customer_id_path: str = Field(min_length=1, max_length=200)
    rating: Literal["low", "medium", "high"] | None = None
    rating_path: str | None = Field(default=None, max_length=200)
    note: str = Field(default="", max_length=300)

    @model_validator(mode="after")
    def _one_source(self) -> "SetRiskRating":
        if (self.rating is None) == (self.rating_path is None):
            raise ValueError("Give exactly one of rating and rating_path.")
        return self


@_library_handler(
    "customers.set_risk_rating",
    "Record the customer's risk rating (a fixed rating or one from the context).",
    SetRiskRating,
    "{customer_id, rating, previous}",
    reads=lambda params: (
        [params.customer_id_path] + ([params.rating_path] if params.rating_path else [])
    ),
    effect="writes",
    fixtures=lambda params: {params.customer_id_path: "customer.id"},
)
def _set_risk_rating(ctx: StepContext, params: SetRiskRating) -> dict[str, Any]:
    from app.modules.customers.models import RiskRating
    from app.modules.customers.schemas import CustomerReview
    from app.modules.customers.service import review_customer

    customer = _customer(ctx, params.customer_id_path)
    rating = params.rating or str(_required(ctx, params.rating_path or ""))
    if rating not in ("low", "medium", "high"):
        raise StepError("invalid_rating", f"'{rating}' is not low, medium or high.")
    previous = customer.risk_rating
    note = params.note or f"{ctx.execution.workflow_id} {ctx.step.id}"
    review_customer(
        ctx.db, customer, CustomerReview(risk_rating=RiskRating(rating), note=note), None
    )
    return {"customer_id": str(customer.id), "rating": rating, "previous": previous}


class ScreenName(_Strict):
    name_path: str = Field(min_length=1, max_length=200)


@_library_handler(
    "compliance.screen_name",
    "Screen a name against the synthetic sanctions watchlist.",
    ScreenName,
    "{hit, matched, list}",
    reads=lambda params: [params.name_path],
    effect="reads",
    fixtures=lambda params: {params.name_path: "customer.name"},
)
def _screen_name(ctx: StepContext, params: ScreenName) -> dict[str, Any]:
    from app.modules.compliance.screening import screen_name

    return screen_name(str(_required(ctx, params.name_path)))


class LookupAccount(_Strict):
    account_number_path: str = Field(min_length=1, max_length=200)
    # When given, the account must belong to this customer.
    customer_id_path: str | None = Field(default=None, max_length=200)


@_library_handler(
    "accounts.lookup",
    "Find an account by number (optionally checking whose it is) and record its state.",
    LookupAccount,
    "{account_id, account_number, customer_id, account_type, currency, status, balance}; "
    "an unknown account or another customer's fails the step.",
    reads=lambda params: (
        [params.account_number_path]
        + ([params.customer_id_path] if params.customer_id_path else [])
    ),
    effect="reads",
)
def _lookup_account(ctx: StepContext, params: LookupAccount) -> dict[str, Any]:
    from app.modules.accounts.service import find_account
    from app.modules.ledger import service as ledger

    number = str(_required(ctx, params.account_number_path))
    account = find_account(ctx.db, number)
    if account is None:
        raise StepError("account_not_found", f"No account {number}.")
    if params.customer_id_path and str(account.customer_id) != str(
        _required(ctx, params.customer_id_path)
    ):
        raise StepError("account_not_owned", f"Account {number} belongs to another customer.")
    return {
        "account_id": str(account.id),
        "account_number": account.account_number,
        "customer_id": str(account.customer_id),
        "account_type": account.account_type,
        "currency": account.currency,
        "status": account.status,
        "balance": ledger.balance(
            ctx.db, ledger.get_ledger_account(ctx.db, account.ledger_account_id)
        ),
    }


class ChargeFee(_Strict):
    account_number_path: str = Field(min_length=1, max_length=200)
    # Minor units of the account's currency: a fixed amount or one from the context.
    amount: int | None = Field(default=None, ge=1, le=100_000_000)
    amount_path: str | None = Field(default=None, max_length=200)
    fee_code: str = Code
    memo: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def _one_source(self) -> "ChargeFee":
        if (self.amount is None) == (self.amount_path is None):
            raise ValueError("Give exactly one of amount and amount_path.")
        return self


@_library_handler(
    "accounts.charge_fee",
    "Charge a service fee to a customer account (posted to fee income; no overdraft).",
    ChargeFee,
    "{entry_number, account_number, amount, currency}; insufficient funds or a closed "
    "account fail the step (route with on_failure).",
    reads=lambda params: (
        [params.account_number_path] + ([params.amount_path] if params.amount_path else [])
    ),
    effect="moves_money",
    requires_approval=True,
    fixtures=lambda params: {params.account_number_path: "account.account_number"},
)
def _charge_fee(ctx: StepContext, params: ChargeFee) -> dict[str, Any]:
    from app.modules.accounts.service import charge_fee, find_account

    number = str(_required(ctx, params.account_number_path))
    account = find_account(ctx.db, number)
    if account is None:
        raise StepError("account_not_found", f"No account {number}.")
    amount = (
        params.amount if params.amount is not None else _required(ctx, params.amount_path or "")
    )
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise StepError("invalid_amount", "The fee must be a positive whole number of minor units.")
    # Keyed by the step run: a retry replays the same posting, a revisit posts again.
    _, entry_number, _ = charge_fee(
        ctx.db, account.id, amount=amount, fee_code=params.fee_code,
        memo=params.memo or f"{ctx.execution.workflow_id} {params.fee_code}",
        idempotency_key=f"workflow:{ctx.run.id}", actor_id=None,
    )  # fmt: skip
    return {
        "entry_number": entry_number,
        "account_number": account.account_number,
        "amount": amount,
        "currency": account.currency,
    }


ADVISORY_ACTIONS = ("analyze_application", "analyze_payment", "analyze_credit_application",
                    "recommend_decision")  # fmt: skip


class AiReview(_Strict):
    tool_id: str = Field(min_length=1, max_length=100)
    action: Literal[
        "analyze_application", "analyze_payment", "analyze_credit_application",
        "recommend_decision",
    ]  # fmt: skip
    # Tool input field -> context path.
    payload: dict[str, str] = Field(min_length=1, max_length=50)


def _check_tool(db: Any, params: AiReview) -> list[str]:
    from app.core.errors import NotFoundError
    from app.modules.ai_tools.service import find_tool

    try:
        tool = find_tool(db, params.tool_id)
    except NotFoundError as exc:
        return [exc.message]
    if params.action not in tool.allowed_actions:
        return [f"{tool.tool_id} {tool.tool_version} is not permitted '{params.action}' "
                f"(allowed: {', '.join(tool.allowed_actions)})."]  # fmt: skip
    return []


@_library_handler(
    "ai.review",
    "Ask a registered AI tool for an advisory analysis; it never decides.",
    AiReview,
    "{available, recommendation, risk_classification, risk_score, confidence, findings, "
    "explanation, tool_id, tool_version, invocation_id}; without a usable answer "
    "{available: false, recommendation: 'escalate'}.",
    reads=lambda params: list(params.payload.values()),
    effect="advisory",
    check=_check_tool,
    step_type=StepType.AI_TASK,
)
def _ai_review(ctx: StepContext, params: AiReview) -> dict[str, Any]:
    from app.core.errors import NotFoundError
    from app.modules.ai_tools.models import InvocationStatus
    from app.modules.ai_tools.service import find_tool, invoke

    def unavailable(code: str, message: str, **extra: Any) -> dict[str, Any]:
        # Safe escalation: without a usable answer the case follows the human path.
        return {"available": False, "recommendation": "escalate",
                "error": {"code": code, "message": message}, **extra}  # fmt: skip

    try:
        tool = find_tool(ctx.db, params.tool_id)
    except NotFoundError as exc:
        return unavailable("tool_missing", exc.message)
    payload = {name: ctx.get(path) for name, path in params.payload.items()}
    call = invoke(
        ctx.db, tool, params.action, payload, actor_id=None, execution_id=ctx.execution.id,
        simulation_run_id=ctx.execution.simulation_run_id, now=ctx.now,
    )  # fmt: skip
    identity = {"tool_id": tool.tool_id, "tool_version": tool.tool_version,
                "invocation_id": str(call.id)}  # fmt: skip
    if call.status != InvocationStatus.SUCCEEDED:
        error = call.error or {}
        return unavailable(error.get("code", call.status), error.get("message", call.status),
                           invocation_status=call.status, **identity)  # fmt: skip
    out = call.output or {}
    return {
        "available": True,
        **identity,
        "recommendation": out.get("recommendation", "escalate"),
        "risk_classification": out.get("risk_classification"),
        "risk_score": out.get("risk_score"),
        "confidence": out.get("confidence"),
        "findings": [f.get("code") for f in out.get("findings", [])],
        "explanation": out.get("explanation"),
    }
