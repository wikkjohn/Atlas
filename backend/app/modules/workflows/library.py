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

from pydantic import BaseModel, Field, field_validator, model_validator
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
    # "account.account_number" | "payee.account_number" (a second customer's account) |
    # "blocked_card.card_number" | "authorization.auth_code" (Phase 31)}.
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
    # Synthetic lists to check (Phase 25); default the global watchlist.
    lists: list[str] | None = Field(default=None, min_length=1, max_length=10)

    @field_validator("lists")
    @classmethod
    def _known_lists(cls, value: list[str] | None) -> list[str] | None:
        from app.modules.compliance.screening import SANCTIONS_LISTS

        unknown = [v for v in value or [] if v not in SANCTIONS_LISTS]
        if unknown:
            raise ValueError(f"Unknown sanctions lists: {', '.join(unknown)}.")
        return value


@_library_handler(
    "compliance.screen_name",
    "Screen a name against synthetic sanctions lists (default: the global watchlist).",
    ScreenName,
    "{hit, matched, list, lists}",
    reads=lambda params: [params.name_path],
    effect="reads",
    fixtures=lambda params: {params.name_path: "customer.name"},
)
def _screen_name(ctx: StepContext, params: ScreenName) -> dict[str, Any]:
    from app.modules.compliance.screening import screen_name

    return screen_name(str(_required(ctx, params.name_path)), params.lists)


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


# --- Retail banking (Phase 29) -------------------------------------------------------------------


class SetOverdraft(_Strict):
    account_number_path: str = Field(min_length=1, max_length=200)
    # Minor units of the account's currency; 0 removes the overdraft.
    limit_path: str = Field(min_length=1, max_length=200)


@_library_handler(
    "retail.set_overdraft",
    "Arrange, change or remove an account's overdraft (within its product's maximum).",
    SetOverdraft,
    "{account_number, currency, overdraft_limit, previous_limit}; a limit above the "
    "product's maximum, or below what the account already owes, fails the step.",
    reads=lambda params: [params.account_number_path, params.limit_path],
    effect="writes",
    requires_approval=True,  # credit is extended: a second person decides first
    fixtures=lambda params: {params.account_number_path: "account.account_number"},
)
def _set_overdraft(ctx: StepContext, params: SetOverdraft) -> dict[str, Any]:
    from app.core.errors import DomainError
    from app.modules.accounts.service import find_account
    from app.modules.retail import service as retail

    number = str(_required(ctx, params.account_number_path))
    account = find_account(ctx.db, number)
    if account is None:
        raise StepError("account_not_found", f"No account {number}.")
    limit = _required(ctx, params.limit_path)
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise StepError("invalid_amount", "The limit must be a whole number of minor units.")
    try:
        account, previous = retail.set_overdraft(
            ctx.db, account, limit, ctx.initiator_id, source=ctx.execution.workflow_id
        )
    except DomainError as exc:
        raise StepError("overdraft_refused", exc.message) from exc
    return {
        "account_number": account.account_number,
        "currency": account.currency,
        "overdraft_limit": account.overdraft_limit,
        "previous_limit": previous,
    }


class CreateStandingOrder(_Strict):
    debtor_account_path: str = Field(min_length=1, max_length=200)
    creditor_account_path: str = Field(min_length=1, max_length=200)
    amount_path: str = Field(min_length=1, max_length=200)
    frequency: Literal["weekly", "monthly"] = "monthly"
    # The first payment this many days after the step runs.
    start_in_days: int = Field(default=1, ge=0, le=365)
    reference_path: str = Field(min_length=1, max_length=200)


@_library_handler(
    "retail.create_standing_order",
    "Set up a standing order between two accounts in the payer's currency.",
    CreateStandingOrder,
    "{order_number, amount, currency, frequency, next_date}; different currencies, a "
    "closed account or an amount at or above the high-value threshold fail the step.",
    reads=lambda params: [
        params.debtor_account_path,
        params.creditor_account_path,
        params.amount_path,
        params.reference_path,
    ],
    effect="writes",
    fixtures=lambda params: {
        params.debtor_account_path: "account.account_number",
        params.creditor_account_path: "payee.account_number",
    },
)
def _create_standing_order(ctx: StepContext, params: CreateStandingOrder) -> dict[str, Any]:
    from datetime import timedelta

    from app.core.errors import DomainError
    from app.modules.accounts.service import find_account
    from app.modules.retail import service as retail
    from app.modules.retail.models import StandingOrderFrequency

    found = []
    for path in (params.debtor_account_path, params.creditor_account_path):
        number = str(_required(ctx, path))
        account = find_account(ctx.db, number)
        if account is None:
            raise StepError("account_not_found", f"No account {number}.")
        found.append(account)
    amount = _required(ctx, params.amount_path)
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise StepError("invalid_amount", "The amount must be a whole number of minor units.")
    today = ctx.now.date()
    try:
        order = retail.create_standing_order(
            ctx.db,
            debtor=found[0],
            creditor=found[1],
            amount=amount,
            frequency=StandingOrderFrequency(params.frequency),
            first_date=today + timedelta(days=params.start_in_days),
            end_date=None,
            reference=str(_required(ctx, params.reference_path))[:100],
            actor_id=ctx.initiator_id,
            today=today,
        )
    except DomainError as exc:
        raise StepError("standing_order_refused", exc.message) from exc
    return {
        "order_number": order.order_number,
        "amount": order.amount,
        "currency": order.currency,
        "frequency": order.frequency,
        "next_date": order.next_date.isoformat(),
    }


class AccountProfile(_Strict):
    account_number_path: str = Field(min_length=1, max_length=200)


@_library_handler(
    "retail.account_profile",
    "Read an account's recent history from the ledger: money in, overdrawn days, limits.",
    AccountProfile,
    "{currency, balance, overdraft_limit, max_overdraft, monthly_credits, "
    "months_with_credits, days_overdrawn} over the 90 days before the step (Phase 30).",
    reads=lambda params: [params.account_number_path],
    effect="reads",
    fixtures=lambda params: {params.account_number_path: "account.account_number"},
)
def _account_profile(ctx: StepContext, params: AccountProfile) -> dict[str, Any]:
    from app.modules.accounts.service import find_account
    from app.modules.retail import service as retail

    number = str(_required(ctx, params.account_number_path))
    account = find_account(ctx.db, number)
    if account is None:
        raise StepError("account_not_found", f"No account {number}.")
    return retail.account_profile(ctx.db, account, ctx.now.date())


class IssueStatement(_Strict):
    account_number_path: str = Field(min_length=1, max_length=200)
    # "YYYY-MM"; without it, or with no value there, the last complete month.
    period_path: str | None = Field(default=None, max_length=200)


@_library_handler(
    "retail.issue_statement",
    "Issue (or find) an account's statement for a month.",
    IssueStatement,
    "{statement_number, period_start, period_end, opening_balance, closing_balance, "
    "currency, created}; a month that has not ended fails the step.",
    reads=lambda params: (
        [params.account_number_path] + ([params.period_path] if params.period_path else [])
    ),
    effect="writes",
    fixtures=lambda params: {params.account_number_path: "account.account_number"},
)
def _issue_statement(ctx: StepContext, params: IssueStatement) -> dict[str, Any]:
    from datetime import date as date_type

    from app.modules.accounts.service import find_account
    from app.modules.retail import service as retail

    number = str(_required(ctx, params.account_number_path))
    account = find_account(ctx.db, number)
    if account is None:
        raise StepError("account_not_found", f"No account {number}.")
    today = ctx.now.date()
    given = ctx.get(params.period_path) if params.period_path else None
    if given:
        text = str(given)
        match = re.fullmatch(r"(\d{4})-(\d{2})", text)
        if not match or not 2000 <= int(match[1]) <= 2100 or not 1 <= int(match[2]) <= 12:
            raise StepError("invalid_period", f"{text} is not a month (YYYY-MM).")
        period = date_type(int(match[1]), int(match[2]), 1)
    else:
        period = retail.last_complete_month(today)
    start, end = retail.month_bounds(period)
    if end >= today:
        raise StepError("period_not_over", f"{start:%B %Y} is not over yet.")
    statement, created = retail.issue_statement(ctx.db, account, start, end, ctx.initiator_id)
    return {
        "statement_number": statement.statement_number,
        "period_start": statement.period_start.isoformat(),
        "period_end": statement.period_end.isoformat(),
        "opening_balance": statement.opening_balance,
        "closing_balance": statement.closing_balance,
        "currency": statement.currency,
        "created": created,
    }


# --- Cards (Phase 31) -----------------------------------------------------------------------------


def _card_error(exc: Any, code: str) -> StepError:
    return StepError(code, getattr(exc, "message", str(exc)))


class IssueCard(_Strict):
    account_number_path: str = Field(min_length=1, max_length=200)
    product_code: str = Field(default="debit-standard", max_length=40)


@_library_handler(
    "cards.issue",
    "Issue a debit card on a current account.",
    IssueCard,
    "{card_id, card_last4, product_code, expires_on}; a closed or non-current account, or a "
    "third live card, fails the step.",
    reads=lambda params: [params.account_number_path],
    effect="writes",
    fixtures=lambda params: {params.account_number_path: "account.account_number"},
)
def _issue_card(ctx: StepContext, params: IssueCard) -> dict[str, Any]:
    from app.core.errors import DomainError
    from app.modules.accounts.service import find_account
    from app.modules.cards import service as cards

    number = str(_required(ctx, params.account_number_path))
    account = find_account(ctx.db, number)
    if account is None:
        raise StepError("account_not_found", f"No account {number}.")
    try:
        card = cards.issue_card(ctx.db, account, params.product_code, ctx.initiator_id, now=ctx.now)
    except DomainError as exc:
        raise _card_error(exc, "card_refused") from exc
    return {
        "card_id": str(card.id),
        "card_last4": card.card_number[-4:],
        "product_code": card.product_code,
        "expires_on": card.expires_on.date().isoformat(),
    }


class LookupCard(_Strict):
    card_number_path: str = Field(min_length=1, max_length=200)
    customer_id_path: str | None = Field(default=None, max_length=200)


@_library_handler(
    "cards.lookup",
    "Find a card and, if asked, check whose it is.",
    LookupCard,
    "{card_id, card_last4, status, blocked_reason, account_id}; an unknown card or another "
    "customer's fails the step.",
    reads=lambda params: (
        [params.card_number_path] + ([params.customer_id_path] if params.customer_id_path else [])
    ),
    effect="reads",
    fixtures=lambda params: {params.card_number_path: "blocked_card.card_number"},
)
def _lookup_card(ctx: StepContext, params: LookupCard) -> dict[str, Any]:
    from app.modules.cards import service as cards

    number = str(_required(ctx, params.card_number_path))
    card = cards.find_card(ctx.db, number)
    if card is None:
        raise StepError("card_not_found", "No such card.")
    if params.customer_id_path and str(card.customer_id) != str(
        _required(ctx, params.customer_id_path)
    ):
        raise StepError("card_not_owned", "The card belongs to another customer.")
    return {"card_id": str(card.id), "card_last4": card.card_number[-4:], "status": card.status,
            "blocked_reason": card.blocked_reason, "account_id": str(card.account_id)}  # fmt: skip


class LookupAuthorization(_Strict):
    auth_code_path: str = Field(min_length=1, max_length=200)
    customer_id_path: str | None = Field(default=None, max_length=200)


@_library_handler(
    "cards.lookup_authorization",
    "Find a card purchase and, if asked, check it was on the customer's card.",
    LookupAuthorization,
    "{authorization_id, auth_code, status, amount, currency, merchant_name}; an unknown "
    "code or another customer's purchase fails the step.",
    reads=lambda params: (
        [params.auth_code_path] + ([params.customer_id_path] if params.customer_id_path else [])
    ),
    effect="reads",
    fixtures=lambda params: {params.auth_code_path: "authorization.auth_code"},
)
def _lookup_authorization(ctx: StepContext, params: LookupAuthorization) -> dict[str, Any]:
    from app.modules.cards import service as cards

    code = str(_required(ctx, params.auth_code_path))
    auth = cards.find_authorization(ctx.db, code)
    if auth is None:
        raise StepError("authorization_not_found", f"No purchase {code}.")
    card = cards.get_card(ctx.db, auth.card_id)
    if params.customer_id_path and str(card.customer_id) != str(
        _required(ctx, params.customer_id_path)
    ):
        raise StepError("authorization_not_owned", "The purchase was on another customer's card.")
    return {"authorization_id": str(auth.id), "auth_code": auth.auth_code, "status": auth.status,
            "amount": auth.amount, "currency": auth.currency,
            "merchant_name": auth.merchant_name}  # fmt: skip


class OpenDispute(_Strict):
    authorization_id_path: str = Field(min_length=1, max_length=200)
    reason_path: str = Field(min_length=1, max_length=200)


@_library_handler(
    "cards.open_dispute",
    "Open a dispute on an approved card purchase.",
    OpenDispute,
    "{dispute_id, dispute_number, amount}; a declined, old or already disputed purchase "
    "fails the step.",
    reads=lambda params: [params.authorization_id_path, params.reason_path],
    effect="writes",
)
def _open_dispute(ctx: StepContext, params: OpenDispute) -> dict[str, Any]:
    from app.core.errors import DomainError
    from app.modules.cards import service as cards
    from app.modules.cards.models import CardAuthorization

    auth = ctx.db.get(
        CardAuthorization, uuid.UUID(str(_required(ctx, params.authorization_id_path)))
    )
    reason = str(_required(ctx, params.reason_path))
    try:
        dispute = cards.open_dispute(ctx.db, auth, reason, None, ctx.initiator_id, now=ctx.now)
    except DomainError as exc:
        raise _card_error(exc, "dispute_refused") from exc
    return {"dispute_id": str(dispute.id), "dispute_number": dispute.dispute_number,
            "amount": dispute.amount}  # fmt: skip


class DecideDispute(_Strict):
    dispute_id_path: str = Field(min_length=1, max_length=200)
    # Who decided: the approval step's actor (the dispute's opener may not decide).
    decided_by_path: str = Field(min_length=1, max_length=200)


@_library_handler(
    "cards.chargeback",
    "Charge a disputed purchase back: refund the amount to the card's account.",
    DecideDispute,
    "{dispute_number, status, amount}; posted from card settlement to the account.",
    reads=lambda params: [params.dispute_id_path, params.decided_by_path],
    effect="moves_money",
    requires_approval=True,
)
def _chargeback(ctx: StepContext, params: DecideDispute) -> dict[str, Any]:
    return _decide(ctx, params, refund=True)


@_library_handler(
    "cards.reject_dispute",
    "Close a dispute without a refund.",
    DecideDispute,
    "{dispute_number, status, amount}",
    reads=lambda params: [params.dispute_id_path, params.decided_by_path],
    effect="writes",
)
def _reject_dispute(ctx: StepContext, params: DecideDispute) -> dict[str, Any]:
    return _decide(ctx, params, refund=False)


def _decide(ctx: StepContext, params: DecideDispute, *, refund: bool) -> dict[str, Any]:
    from app.core.errors import DomainError
    from app.modules.cards import service as cards

    dispute = cards.get_dispute(ctx.db, uuid.UUID(str(_required(ctx, params.dispute_id_path))))
    decider = uuid.UUID(str(_required(ctx, params.decided_by_path)))
    try:
        dispute = cards.decide_dispute(
            ctx.db, dispute, refund, decider, now=ctx.now,
            idempotency_key=f"workflow:{ctx.run.id}" if refund else None,
        )  # fmt: skip
    except DomainError as exc:
        raise _card_error(exc, "dispute_not_decided") from exc
    return {"dispute_number": dispute.dispute_number, "status": dispute.status,
            "amount": dispute.amount}  # fmt: skip


class UnblockCard(_Strict):
    card_id_path: str = Field(min_length=1, max_length=200)


@_library_handler(
    "cards.unblock",
    "Release a card's block.",
    UnblockCard,
    "{card_last4, status}; a card that is not blocked fails the step.",
    reads=lambda params: [params.card_id_path],
    effect="writes",
    requires_approval=True,  # a fraud block is released only after a review
)
def _unblock_card(ctx: StepContext, params: UnblockCard) -> dict[str, Any]:
    from app.core.errors import DomainError
    from app.modules.cards import service as cards

    card = cards.get_card(
        ctx.db, uuid.UUID(str(_required(ctx, params.card_id_path))), for_update=True
    )
    try:
        card = cards.unblock_card(ctx.db, card, ctx.initiator_id)
    except DomainError as exc:
        raise _card_error(exc, "card_not_unblocked") from exc
    return {"card_last4": card.card_number[-4:], "status": card.status}


@_library_handler(
    "cards.fraud_profile",
    "Read what a fraud analyst reviews: the declined purchase and the card's history.",
    UnblockCard,
    "{currency, home_country, daily_limit, blocked, purchases_90d, median_amount, "
    "high_risk_purchases_90d, country_first_seen_hours, attempts_last_hour}; blocked is "
    "null for a manual block (Phase 32).",
    reads=lambda params: [params.card_id_path],
    effect="reads",
)
def _fraud_profile(ctx: StepContext, params: UnblockCard) -> dict[str, Any]:
    from app.modules.cards import service as cards

    card = cards.get_card(ctx.db, uuid.UUID(str(_required(ctx, params.card_id_path))))
    return cards.fraud_profile(ctx.db, card)


# --- Mortgages (Phase 33) --------------------------------------------------------------------


def _mortgage_call(code: str, call, *args, **kwargs):
    from app.core.errors import DomainError

    try:
        return call(*args, **kwargs)
    except DomainError as exc:
        raise StepError(code, getattr(exc, "message", str(exc))) from exc


def _property(ctx: StepContext, path: str):
    from app.modules.mortgages import service as mortgages

    number = str(_required(ctx, path))
    prop = mortgages.find_property(ctx.db, number)
    if prop is None:
        raise StepError("property_not_found", f"No property {number}.")
    return prop


def _offer(ctx: StepContext, path: str):
    from app.modules.mortgages import service as mortgages

    return mortgages.get_offer(ctx.db, uuid.UUID(str(_required(ctx, path))), for_update=True)


class RegisterProperty(_Strict):
    customer_number_path: str = Field(min_length=1, max_length=200)
    property_type_path: str = Field(min_length=1, max_length=200)
    purchase_price_path: str = Field(min_length=1, max_length=200)


@_library_handler(
    "mortgages.register_property",
    "Register the property a customer is buying.",
    RegisterProperty,
    "{property_id, property_number, currency, purchase_price}",
    reads=lambda params: [
        params.customer_number_path,
        params.property_type_path,
        params.purchase_price_path,
    ],  # fmt: skip
    effect="writes",
    fixtures=lambda params: {params.customer_number_path: "customer.customer_number"},
)
def _register_property(ctx: StepContext, params: RegisterProperty) -> dict[str, Any]:
    from app.modules.mortgages import service as mortgages

    number = str(_required(ctx, params.customer_number_path))
    customer = mortgages.find_customer(ctx.db, number)
    if customer is None:
        raise StepError("customer_not_found", f"No customer {number}.")
    prop = _mortgage_call(
        "property_refused", mortgages.register_property, ctx.db, customer,
        str(_required(ctx, params.property_type_path)),
        int(_required(ctx, params.purchase_price_path)), ctx.initiator_id,
    )  # fmt: skip
    return {"property_id": str(prop.id), "property_number": prop.property_number,
            "currency": prop.currency, "purchase_price": prop.purchase_price}  # fmt: skip


class PropertyRef(_Strict):
    property_number_path: str = Field(min_length=1, max_length=200)


@_library_handler(
    "mortgages.desktop_valuation",
    "Value a property with the synthetic automated valuation model.",
    PropertyRef,
    "{valuation_number, value, currency, value_to_price_bps}",
    reads=lambda params: [params.property_number_path],
    effect="writes",
    fixtures=lambda params: {params.property_number_path: "property.property_number"},
)
def _desktop_valuation(ctx: StepContext, params: PropertyRef) -> dict[str, Any]:
    from app.modules.mortgages import service as mortgages

    prop = _property(ctx, params.property_number_path)
    valuation = mortgages.value_property(ctx.db, prop, "desktop", today=ctx.now.date())
    return {"valuation_number": valuation.valuation_number, "value": valuation.value,
            "currency": valuation.currency,
            "value_to_price_bps": valuation.value * 10_000 // prop.purchase_price}  # fmt: skip


class ConfirmValue(_Strict):
    property_number_path: str = Field(min_length=1, max_length=200)
    surveyor_path: str = Field(min_length=1, max_length=200)


@_library_handler(
    "mortgages.confirm_value",
    "Record the surveyor's valuation: the inspection confirmed the purchase price.",
    ConfirmValue,
    "{valuation_number, value, currency}",
    reads=lambda params: [params.property_number_path, params.surveyor_path],
    effect="writes",
    requires_approval=True,  # a surveyor's valuation is a person's judgement
    fixtures=lambda params: {params.property_number_path: "property.property_number"},
)
def _confirm_value(ctx: StepContext, params: ConfirmValue) -> dict[str, Any]:
    from app.modules.mortgages import service as mortgages

    prop = _property(ctx, params.property_number_path)
    valuation = mortgages.value_property(
        ctx.db, prop, "surveyor", value=prop.purchase_price, today=ctx.now.date(),
        actor_id=uuid.UUID(str(_required(ctx, params.surveyor_path))),
        notes="Inspection confirmed the purchase price.",
    )  # fmt: skip
    return {"valuation_number": valuation.valuation_number, "value": valuation.value,
            "currency": valuation.currency}  # fmt: skip


class MortgageApplication(_Strict):
    customer_number_path: str = Field(min_length=1, max_length=200)
    property_number_path: str = Field(min_length=1, max_length=200)
    account_number_path: str = Field(min_length=1, max_length=200)
    product_path: str = Field(min_length=1, max_length=200)
    loan_amount_path: str = Field(min_length=1, max_length=200)
    term_years_path: str = Field(min_length=1, max_length=200)
    income_path: str = Field(min_length=1, max_length=200)


def _application(ctx: StepContext, params: MortgageApplication) -> dict[str, Any]:
    from app.modules.accounts.service import find_account
    from app.modules.mortgages import service as mortgages

    number = str(_required(ctx, params.customer_number_path))
    customer = mortgages.find_customer(ctx.db, number)
    if customer is None:
        raise StepError("customer_not_found", f"No customer {number}.")
    account_number = str(_required(ctx, params.account_number_path))
    account = find_account(ctx.db, account_number)
    if account is None:
        raise StepError("account_not_found", f"No account {account_number}.")
    product = _mortgage_call("product_not_found", mortgages.get_product, ctx.db,
                             str(_required(ctx, params.product_path)))  # fmt: skip
    return {
        "customer": customer,
        "prop": _property(ctx, params.property_number_path),
        "product": product,
        "account": account,
        "loan_amount": int(_required(ctx, params.loan_amount_path)),
        "term_years": int(_required(ctx, params.term_years_path)),
        "declared_monthly_income": int(_required(ctx, params.income_path)),
        "today": ctx.now.date(),
    }


def _application_reads(params: MortgageApplication) -> list[str]:
    return [params.customer_number_path, params.property_number_path, params.account_number_path,
            params.product_path, params.loan_amount_path, params.term_years_path,
            params.income_path]  # fmt: skip


def _application_fixtures(params: MortgageApplication) -> dict[str, str]:
    return {params.customer_number_path: "customer.customer_number",
            params.property_number_path: "property.property_number",
            params.account_number_path: "account.account_number"}  # fmt: skip


@_library_handler(
    "mortgages.quote",
    "A decision in principle: every lending rule, passed or failed, with the figures.",
    MortgageApplication,
    "{eligible, failed_rules, failed_detail, ltv_bps, monthly_payment, annual_rate_bps, "
    "currency, credit_score}",
    reads=_application_reads,
    effect="reads",
    fixtures=_application_fixtures,
)
def _quote(ctx: StepContext, params: MortgageApplication) -> dict[str, Any]:
    from app.modules.mortgages import service as mortgages

    result = mortgages.quote(ctx.db, **_application(ctx, params))
    failed = [c for c in result["checks"] if not c["passed"]]
    return {
        "eligible": result["eligible"],
        "failed_rules": ", ".join(c["rule"] for c in failed),
        "failed_detail": "; ".join(c["detail"] for c in failed),
        "ltv_bps": result["ltv_bps"],
        "monthly_payment": result["monthly_payment"],
        "annual_rate_bps": result["annual_rate_bps"],
        "currency": result["currency"],
        "credit_score": result["credit_score"],
    }


@_library_handler(
    "mortgages.request_offer",
    "Apply for the mortgage: refused unless every rule passes; then pending a decision.",
    MortgageApplication,
    "{offer_id, offer_number, monthly_payment, ltv_bps}; a failed rule fails the step.",
    reads=_application_reads,
    effect="writes",
    fixtures=_application_fixtures,
)
def _request_offer(ctx: StepContext, params: MortgageApplication) -> dict[str, Any]:
    from app.modules.mortgages import service as mortgages

    offer = _mortgage_call("application_refused", mortgages.request_offer, ctx.db,
                           requested_by=ctx.initiator_id, **_application(ctx, params))  # fmt: skip
    return {"offer_id": str(offer.id), "offer_number": offer.offer_number,
            "monthly_payment": offer.monthly_payment, "ltv_bps": offer.ltv_bps}  # fmt: skip


class OfferRef(_Strict):
    offer_id_path: str = Field(min_length=1, max_length=200)


@_library_handler(
    "mortgages.application_profile",
    "Read what an underwriter reviews: affordability on declared and estimated income, "
    "credit, the valuation against the model, and age at the end of the term.",
    OfferRef,
    "{loan_amount, term_years, ltv_bps, monthly_payment, payment_to_income_bps, "
    "payment_to_estimate_bps, declared_to_estimate_bps, credit_score, valuation_method, "
    "model_to_price_bps, age_at_term_end, ...} (Phase 34).",
    reads=lambda params: [params.offer_id_path],
    effect="reads",
)
def _application_profile(ctx: StepContext, params: OfferRef) -> dict[str, Any]:
    from app.modules.mortgages import service as mortgages

    offer = mortgages.get_offer(ctx.db, uuid.UUID(str(_required(ctx, params.offer_id_path))))
    return mortgages.application_profile(ctx.db, offer, ctx.now.date())


class OfferDecision(_Strict):
    offer_id_path: str = Field(min_length=1, max_length=200)
    decided_by_path: str = Field(min_length=1, max_length=200)


@_library_handler(
    "mortgages.issue_offer",
    "Issue the mortgage offer (valid for 90 days).",
    OfferDecision,
    "{offer_number, status, expires_on}",
    reads=lambda params: [params.offer_id_path, params.decided_by_path],
    effect="writes",
    requires_approval=True,  # an underwriter other than the requester decides
)
def _issue_offer(ctx: StepContext, params: OfferDecision) -> dict[str, Any]:
    return _decide_offer(ctx, params, approve=True)


@_library_handler(
    "mortgages.decline_offer",
    "Decline the mortgage application.",
    OfferDecision,
    "{offer_number, status, expires_on}",
    reads=lambda params: [params.offer_id_path, params.decided_by_path],
    effect="writes",
)
def _decline_offer(ctx: StepContext, params: OfferDecision) -> dict[str, Any]:
    return _decide_offer(ctx, params, approve=False)


def _decide_offer(ctx: StepContext, params: OfferDecision, *, approve: bool) -> dict[str, Any]:
    from app.modules.mortgages import service as mortgages

    offer = _mortgage_call(
        "offer_not_decided", mortgages.decide_offer, ctx.db,
        _offer(ctx, params.offer_id_path), approve,
        uuid.UUID(str(_required(ctx, params.decided_by_path))), now=ctx.now,
    )  # fmt: skip
    return {"offer_number": offer.offer_number, "status": offer.status,
            "expires_on": offer.expires_on.isoformat() if offer.expires_on else None}  # fmt: skip


class LookupOffer(_Strict):
    offer_number_path: str = Field(min_length=1, max_length=200)
    customer_id_path: str | None = Field(default=None, max_length=200)


@_library_handler(
    "mortgages.lookup_offer",
    "Find a mortgage offer and, if asked, check whose it is.",
    LookupOffer,
    "{offer_id, offer_number, status, expired, loan_amount, currency, monthly_payment}; an "
    "unknown offer or another customer's fails the step.",
    reads=lambda params: (
        [params.offer_number_path] + ([params.customer_id_path] if params.customer_id_path else [])
    ),
    effect="reads",
    fixtures=lambda params: {params.offer_number_path: "mortgage_offer.offer_number"},
)
def _lookup_offer(ctx: StepContext, params: LookupOffer) -> dict[str, Any]:
    from app.modules.mortgages import service as mortgages

    number = str(_required(ctx, params.offer_number_path))
    offer = mortgages.find_offer(ctx.db, number)
    if offer is None:
        raise StepError("offer_not_found", f"No mortgage offer {number}.")
    if params.customer_id_path and str(offer.customer_id) != str(
        _required(ctx, params.customer_id_path)
    ):
        raise StepError("offer_not_owned", "The offer belongs to another customer.")
    return {"offer_id": str(offer.id), "offer_number": offer.offer_number, "status": offer.status,
            "expired": mortgages.expired(offer, ctx.now.date()), "loan_amount": offer.loan_amount,
            "currency": offer.currency, "monthly_payment": offer.monthly_payment}  # fmt: skip


@_library_handler(
    "mortgages.accept_offer",
    "Record the customer's acceptance of the offer.",
    OfferRef,
    "{offer_number, status}; an expired or undecided offer fails the step.",
    reads=lambda params: [params.offer_id_path],
    effect="writes",
)
def _accept_offer(ctx: StepContext, params: OfferRef) -> dict[str, Any]:
    from app.modules.mortgages import service as mortgages

    offer = _mortgage_call("offer_not_accepted", mortgages.accept_offer, ctx.db,
                           _offer(ctx, params.offer_id_path), ctx.initiator_id,
                           now=ctx.now)  # fmt: skip
    return {"offer_number": offer.offer_number, "status": offer.status}


class CompleteMortgage(_Strict):
    offer_id_path: str = Field(min_length=1, max_length=200)
    completed_by_path: str = Field(min_length=1, max_length=200)


@_library_handler(
    "mortgages.complete",
    "Complete: draw the loan down into the applicant's account, charged on the property.",
    CompleteMortgage,
    "{loan_number, principal, currency, monthly_payment}",
    reads=lambda params: [params.offer_id_path, params.completed_by_path],
    effect="moves_money",
    requires_approval=True,
)
def _complete_mortgage(ctx: StepContext, params: CompleteMortgage) -> dict[str, Any]:
    from app.modules.mortgages import service as mortgages

    loan = _mortgage_call(
        "completion_refused", mortgages.complete_offer, ctx.db,
        _offer(ctx, params.offer_id_path),
        uuid.UUID(str(_required(ctx, params.completed_by_path))),
        workflow_execution_id=ctx.execution.id, now=ctx.now,
    )  # fmt: skip
    return {"loan_number": loan.loan_number, "principal": loan.principal,
            "currency": loan.currency, "monthly_payment": loan.monthly_payment}  # fmt: skip


# --- Commercial lending (Phase 35) -----------------------------------------------------------


def _commercial_call(code: str, call, *args, **kwargs):
    from app.core.errors import DomainError

    try:
        return call(*args, **kwargs)
    except DomainError as exc:
        raise StepError(code, getattr(exc, "message", str(exc))) from exc


def _facility(ctx: StepContext, path: str):
    from app.modules.commercial import service as commercial

    return commercial.get_facility(ctx.db, uuid.UUID(str(_required(ctx, path))), for_update=True)


class ProposeFacility(_Strict):
    customer_number_path: str = Field(min_length=1, max_length=200)
    account_number_path: str = Field(min_length=1, max_length=200)
    facility_type_path: str = Field(min_length=1, max_length=200)
    limit_path: str = Field(min_length=1, max_length=200)
    term_path: str = Field(min_length=1, max_length=200)
    purpose_path: str | None = Field(default=None, max_length=200)


@_library_handler(
    "commercial.propose_facility",
    "Propose a term loan or revolving credit for a business customer.",
    ProposeFacility,
    "{facility_id, facility_number, currency, customer_id, customer_name, needs_committee}; a "
    "rule the proposal breaks "
    "fails the step.",
    reads=lambda params: (
        [
            params.customer_number_path,
            params.account_number_path,
            params.facility_type_path,
            params.limit_path,
            params.term_path,
        ]
        + ([params.purpose_path] if params.purpose_path else [])
    ),  # fmt: skip
    effect="writes",
    fixtures=lambda params: {
        params.customer_number_path: "business.customer_number",
        params.account_number_path: "business.account_number",
    },  # fmt: skip
)
def _propose_facility(ctx: StepContext, params: ProposeFacility) -> dict[str, Any]:
    from app.modules.accounts.service import find_account
    from app.modules.commercial import service as commercial

    number = str(_required(ctx, params.customer_number_path))
    customer = commercial.find_customer(ctx.db, number)
    if customer is None:
        raise StepError("customer_not_found", f"No customer {number}.")
    account_number = str(_required(ctx, params.account_number_path))
    account = find_account(ctx.db, account_number)
    if account is None:
        raise StepError("account_not_found", f"No account {account_number}.")
    facility = _commercial_call(
        "proposal_refused", commercial.propose_facility, ctx.db, customer=customer,
        account=account, facility_type=str(_required(ctx, params.facility_type_path)),
        credit_limit=int(_required(ctx, params.limit_path)),
        term_months=int(_required(ctx, params.term_path)),
        purpose=str(ctx.get(params.purpose_path) or "Working capital")
        if params.purpose_path else "Working capital",
        requested_by=ctx.initiator_id,
    )  # fmt: skip
    return {"facility_id": str(facility.id), "facility_number": facility.facility_number,
            "currency": facility.currency, "customer_id": str(customer.id),
            "customer_name": customer.name,
            "needs_committee": commercial.needs_committee(facility)}  # fmt: skip


class FacilityDecision(_Strict):
    facility_id_path: str = Field(min_length=1, max_length=200)
    decided_by_path: str = Field(min_length=1, max_length=200)


def _facility_out(facility) -> dict[str, Any]:
    return {"facility_number": facility.facility_number, "status": facility.status,
            "awaiting_committee": facility.status == "proposed",
            "review_due_on": facility.review_due_on.isoformat()
            if facility.review_due_on else None}  # fmt: skip


@_library_handler(
    "commercial.approve_facility",
    "Record the credit approval; the facility is active unless the committee must approve.",
    FacilityDecision,
    "{facility_number, status, awaiting_committee, review_due_on}",
    reads=lambda params: [params.facility_id_path, params.decided_by_path],
    effect="writes",
    requires_approval=True,  # a credit approver other than the proposer
)
def _approve_facility(ctx: StepContext, params: FacilityDecision) -> dict[str, Any]:
    from app.modules.commercial import service as commercial

    facility = _commercial_call(
        "approval_refused", commercial.approve_facility, ctx.db,
        _facility(ctx, params.facility_id_path),
        uuid.UUID(str(_required(ctx, params.decided_by_path))), now=ctx.now,
    )  # fmt: skip
    return _facility_out(facility)


@_library_handler(
    "commercial.committee_approve",
    "Record the credit committee's approval of a facility above US$1m.",
    FacilityDecision,
    "{facility_number, status, awaiting_committee, review_due_on}",
    reads=lambda params: [params.facility_id_path, params.decided_by_path],
    effect="writes",
    requires_approval=True,
)
def _committee_approve(ctx: StepContext, params: FacilityDecision) -> dict[str, Any]:
    from app.modules.commercial import service as commercial

    facility = _commercial_call(
        "committee_refused", commercial.committee_approve, ctx.db,
        _facility(ctx, params.facility_id_path),
        uuid.UUID(str(_required(ctx, params.decided_by_path))), now=ctx.now,
    )  # fmt: skip
    return _facility_out(facility)


@_library_handler(
    "commercial.decline_facility",
    "Decline the facility proposal.",
    FacilityDecision,
    "{facility_number, status, awaiting_committee, review_due_on}",
    reads=lambda params: [params.facility_id_path, params.decided_by_path],
    effect="writes",
)
def _decline_facility(ctx: StepContext, params: FacilityDecision) -> dict[str, Any]:
    from app.modules.commercial import service as commercial

    facility = _commercial_call(
        "decline_refused", commercial.decline_facility, ctx.db,
        _facility(ctx, params.facility_id_path),
        uuid.UUID(str(_required(ctx, params.decided_by_path))),
    )  # fmt: skip
    return _facility_out(facility)


class LookupFacility(_Strict):
    facility_number_path: str = Field(min_length=1, max_length=200)
    customer_number_path: str | None = Field(default=None, max_length=200)


@_library_handler(
    "commercial.lookup_facility",
    "Find a facility and, if asked, check whose it is.",
    LookupFacility,
    "{facility_id, facility_number, status, credit_limit, drawn, available, currency, "
    "review_due_on, customer_id, customer_name}; an unknown facility or another customer's "
    "fails the step.",
    reads=lambda params: (
        [params.facility_number_path]
        + ([params.customer_number_path] if params.customer_number_path else [])
    ),
    effect="reads",
    fixtures=lambda params: {
        params.facility_number_path: "facility.facility_number",
        **(
            {params.customer_number_path: "business.customer_number"}
            if params.customer_number_path
            else {}
        ),
    },  # fmt: skip
)
def _lookup_facility(ctx: StepContext, params: LookupFacility) -> dict[str, Any]:
    from app.modules.commercial import service as commercial

    number = str(_required(ctx, params.facility_number_path))
    facility = commercial.find_facility(ctx.db, number)
    if facility is None:
        raise StepError("facility_not_found", f"No facility {number}.")
    from app.modules.customers.models import Customer

    customer = ctx.db.get(Customer, facility.customer_id)
    if (
        params.customer_number_path
        and customer.customer_number
        != str(_required(ctx, params.customer_number_path)).strip().upper()
    ):
        raise StepError("facility_not_owned", "The facility belongs to another customer.")
    return {"facility_id": str(facility.id), "facility_number": facility.facility_number,
            "status": facility.status, "credit_limit": facility.credit_limit,
            "drawn": facility.drawn, "available": commercial.available(facility),
            "currency": facility.currency,
            "customer_id": str(customer.id), "customer_name": customer.name,
            "review_due_on": facility.review_due_on.isoformat()
            if facility.review_due_on else None}  # fmt: skip


class CovenantFigures(_Strict):
    facility_id_path: str = Field(min_length=1, max_length=200)
    period_end_path: str = Field(min_length=1, max_length=200)
    ebitda_path: str = Field(min_length=1, max_length=200)
    debt_service_path: str = Field(min_length=1, max_length=200)
    total_debt_path: str = Field(min_length=1, max_length=200)


@_library_handler(
    "commercial.test_covenants",
    "Test the facility's covenants on a year's figures; a breach freezes the facility.",
    CovenantFigures,
    "{test_id, breached, results}; results reads e.g. 'min_dscr 1.10× (needs 1.25×): breached'.",
    reads=lambda params: [
        params.facility_id_path,
        params.period_end_path,
        params.ebitda_path,
        params.debt_service_path,
        params.total_debt_path,
    ],  # fmt: skip
    effect="writes",
)
def _test_covenants(ctx: StepContext, params: CovenantFigures) -> dict[str, Any]:
    from datetime import date as date_type

    from app.modules.commercial import service as commercial

    try:
        period_end = date_type.fromisoformat(str(_required(ctx, params.period_end_path)))
    except ValueError as exc:
        raise StepError("invalid_date", "The period end is not a date (YYYY-MM-DD).") from exc
    test = _commercial_call(
        "test_refused", commercial.run_covenant_test, ctx.db,
        _facility(ctx, params.facility_id_path), period_end=period_end,
        ebitda=int(_required(ctx, params.ebitda_path)),
        debt_service=int(_required(ctx, params.debt_service_path)),
        total_debt=int(_required(ctx, params.total_debt_path)), actor_id=ctx.initiator_id,
    )  # fmt: skip
    results = "; ".join(
        f"{r['kind']} {r['actual_centi'] / 100:.2f}× (limit {r['threshold_centi'] / 100:.2f}×): "
        + ("met" if r["passed"] else "breached")
        for r in test.results
    )
    return {"test_id": str(test.id), "breached": test.breached, "results": results}


class TestRef(_Strict):
    test_id_path: str = Field(min_length=1, max_length=200)


@_library_handler(
    "commercial.breach_profile",
    "Read what the credit committee reviews: the period's ratios, the EBITDA trend, the "
    "facility's use and its earlier breaches.",
    TestRef,
    "{dscr_centi, dscr_threshold_centi, leverage_centi, leverage_threshold_centi, "
    "ebitda_change_bps, previous_ebitda_change_bps, consecutive_declines, utilisation_bps, "
    "periods_tested, previous_breaches, previous_waivers} (Phase 36).",
    reads=lambda params: [params.test_id_path],
    effect="reads",
)
def _breach_profile(ctx: StepContext, params: TestRef) -> dict[str, Any]:
    from app.modules.commercial import service as commercial

    test = commercial.get_test(ctx.db, uuid.UUID(str(_required(ctx, params.test_id_path))))
    return commercial.breach_profile(ctx.db, test)


class WaiveBreach(_Strict):
    test_id_path: str = Field(min_length=1, max_length=200)
    waived_by_path: str = Field(min_length=1, max_length=200)


@_library_handler(
    "commercial.waive_breach",
    "Record the credit committee's waiver of a covenant breach.",
    WaiveBreach,
    "{facility_number, status, awaiting_committee, review_due_on}",
    reads=lambda params: [params.test_id_path, params.waived_by_path],
    effect="writes",
    requires_approval=True,
)
def _waive_breach(ctx: StepContext, params: WaiveBreach) -> dict[str, Any]:
    from app.modules.commercial import service as commercial

    test = commercial.get_test(ctx.db, uuid.UUID(str(_required(ctx, params.test_id_path))))
    facility = _commercial_call(
        "waiver_refused", commercial.waive_breach, ctx.db, test,
        uuid.UUID(str(_required(ctx, params.waived_by_path))), now=ctx.now,
    )  # fmt: skip
    return _facility_out(facility)


class FacilityRef(_Strict):
    facility_id_path: str = Field(min_length=1, max_length=200)


@_library_handler(
    "commercial.open_review",
    "Open the facility's annual review (from 60 days before it is due).",
    FacilityRef,
    "{review_id, review_number, due_on}; too early, or a review already open, fails the step.",
    reads=lambda params: [params.facility_id_path],
    effect="writes",
)
def _open_review(ctx: StepContext, params: FacilityRef) -> dict[str, Any]:
    from app.modules.commercial import service as commercial

    review = _commercial_call(
        "review_refused", commercial.open_review, ctx.db,
        _facility(ctx, params.facility_id_path), ctx.initiator_id, today=ctx.now.date(),
    )  # fmt: skip
    return {"review_id": str(review.id), "review_number": review.review_number,
            "due_on": review.due_on.isoformat()}  # fmt: skip


class ReviewDecision(_Strict):
    review_id_path: str = Field(min_length=1, max_length=200)
    decided_by_path: str = Field(min_length=1, max_length=200)


def _decide_review(ctx: StepContext, params: ReviewDecision, *, renew: bool) -> dict[str, Any]:
    from app.modules.commercial import service as commercial

    review = commercial.get_review(ctx.db, uuid.UUID(str(_required(ctx, params.review_id_path))))
    review = _commercial_call(
        "review_not_decided", commercial.decide_review, ctx.db, review, renew,
        uuid.UUID(str(_required(ctx, params.decided_by_path))), now=ctx.now,
    )  # fmt: skip
    facility = commercial.get_facility(ctx.db, review.facility_id)
    return {"review_number": review.review_number, "outcome": review.outcome,
            **_facility_out(facility)}  # fmt: skip


@_library_handler(
    "commercial.renew_facility",
    "Renew the facility for another year.",
    ReviewDecision,
    "{review_number, outcome, facility_number, status, review_due_on}",
    reads=lambda params: [params.review_id_path, params.decided_by_path],
    effect="writes",
    requires_approval=True,  # a credit approver other than the person who opened the review
)
def _renew_facility(ctx: StepContext, params: ReviewDecision) -> dict[str, Any]:
    return _decide_review(ctx, params, renew=True)


@_library_handler(
    "commercial.terminate_facility",
    "Terminate the facility: no further drawdowns, repayments only.",
    ReviewDecision,
    "{review_number, outcome, facility_number, status, review_due_on}",
    reads=lambda params: [params.review_id_path, params.decided_by_path],
    effect="writes",
)
def _terminate_facility(ctx: StepContext, params: ReviewDecision) -> dict[str, Any]:
    return _decide_review(ctx, params, renew=False)


# --- Trade finance (Phase 37) ----------------------------------------------------------------


def _trade_call(code: str, call, *args, **kwargs):
    from app.core.errors import DomainError

    try:
        return call(*args, **kwargs)
    except DomainError as exc:
        raise StepError(code, getattr(exc, "message", str(exc))) from exc


def _trade_out(instrument) -> dict[str, Any]:
    return {"instrument_number": instrument.instrument_number, "status": instrument.status,
            "awaiting_committee": instrument.status == "requested",
            "margin": instrument.margin, "currency": instrument.currency}  # fmt: skip


class RequestInstrument(_Strict):
    customer_number_path: str = Field(min_length=1, max_length=200)
    account_number_path: str = Field(min_length=1, max_length=200)
    kind_path: str = Field(min_length=1, max_length=200)
    beneficiary_path: str = Field(min_length=1, max_length=200)
    country_path: str = Field(min_length=1, max_length=200)
    amount_path: str = Field(min_length=1, max_length=200)
    expires_in_days_path: str = Field(min_length=1, max_length=200)
    purpose_path: str | None = Field(default=None, max_length=200)


@_library_handler(
    "trade.request_instrument",
    "Request a letter of credit or a guarantee; the beneficiary is screened.",
    RequestInstrument,
    "{instrument_id, instrument_number, customer_id, customer_name, currency, margin, "
    "needs_committee}; a sanctioned beneficiary or a broken rule fails the step.",
    reads=lambda params: (
        [
            params.customer_number_path,
            params.account_number_path,
            params.kind_path,
            params.beneficiary_path,
            params.country_path,
            params.amount_path,
            params.expires_in_days_path,
        ]
        + ([params.purpose_path] if params.purpose_path else [])
    ),  # fmt: skip
    effect="writes",
    fixtures=lambda params: {
        params.customer_number_path: "business.customer_number",
        params.account_number_path: "business.account_number",
    },  # fmt: skip
)
def _request_instrument(ctx: StepContext, params: RequestInstrument) -> dict[str, Any]:
    from datetime import timedelta

    from app.modules.accounts.service import find_account
    from app.modules.trade import service as trade

    number = str(_required(ctx, params.customer_number_path))
    customer = trade.find_customer(ctx.db, number)
    if customer is None:
        raise StepError("customer_not_found", f"No customer {number}.")
    account_number = str(_required(ctx, params.account_number_path))
    account = find_account(ctx.db, account_number)
    if account is None:
        raise StepError("account_not_found", f"No account {account_number}.")
    today = ctx.now.date()
    instrument = _trade_call(
        "request_refused", trade.request_instrument, ctx.db, customer=customer, account=account,
        kind=str(_required(ctx, params.kind_path)),
        beneficiary_name=str(_required(ctx, params.beneficiary_path)),
        beneficiary_country=str(_required(ctx, params.country_path)),
        amount=int(_required(ctx, params.amount_path)),
        expires_on=today + timedelta(days=int(_required(ctx, params.expires_in_days_path))),
        purpose=str(ctx.get(params.purpose_path) or "Trade") if params.purpose_path else "Trade",
        requested_by=ctx.initiator_id, today=today,
    )  # fmt: skip
    return {"instrument_id": str(instrument.id), "instrument_number": instrument.instrument_number,
            "customer_id": str(customer.id), "customer_name": customer.name,
            "currency": instrument.currency, "margin": instrument.margin,
            "needs_committee": trade.needs_committee(instrument)}  # fmt: skip


class InstrumentDecision(_Strict):
    instrument_id_path: str = Field(min_length=1, max_length=200)
    decided_by_path: str = Field(min_length=1, max_length=200)


def _decide_instrument(ctx: StepContext, params: InstrumentDecision, call: str) -> dict[str, Any]:
    from app.modules.trade import service as trade

    instrument = trade.get_instrument(
        ctx.db, uuid.UUID(str(_required(ctx, params.instrument_id_path))), for_update=True
    )
    decider = uuid.UUID(str(_required(ctx, params.decided_by_path)))
    if call == "decline":
        result = _trade_call("decline_refused", trade.decline_instrument, ctx.db, instrument,
                             decider)  # fmt: skip
    else:
        fn = trade.approve_instrument if call == "approve" else trade.committee_approve
        result = _trade_call("issue_refused", fn, ctx.db, instrument, decider, now=ctx.now)
    return _trade_out(result)


@_library_handler(
    "trade.approve_instrument",
    "Record the credit approval; the instrument is issued and its margin taken unless the "
    "committee must approve.",
    InstrumentDecision,
    "{instrument_number, status, awaiting_committee, margin, currency}",
    reads=lambda params: [params.instrument_id_path, params.decided_by_path],
    effect="writes",
    requires_approval=True,
)
def _approve_instrument(ctx: StepContext, params: InstrumentDecision) -> dict[str, Any]:
    return _decide_instrument(ctx, params, "approve")


@_library_handler(
    "trade.committee_approve",
    "Record the credit committee's approval of an instrument above US$1m.",
    InstrumentDecision,
    "{instrument_number, status, awaiting_committee, margin, currency}",
    reads=lambda params: [params.instrument_id_path, params.decided_by_path],
    effect="writes",
    requires_approval=True,
)
def _committee_approve_instrument(ctx: StepContext, params: InstrumentDecision) -> dict[str, Any]:
    return _decide_instrument(ctx, params, "committee")


@_library_handler(
    "trade.decline_instrument",
    "Decline the request.",
    InstrumentDecision,
    "{instrument_number, status, awaiting_committee, margin, currency}",
    reads=lambda params: [params.instrument_id_path, params.decided_by_path],
    effect="writes",
)
def _decline_instrument(ctx: StepContext, params: InstrumentDecision) -> dict[str, Any]:
    return _decide_instrument(ctx, params, "decline")


class LookupInstrument(_Strict):
    instrument_number_path: str = Field(min_length=1, max_length=200)
    customer_number_path: str | None = Field(default=None, max_length=200)
    kind: Literal["letter_of_credit", "guarantee"]


@_library_handler(
    "trade.lookup_instrument",
    "Find an issued letter of credit or guarantee and check whose it is.",
    LookupInstrument,
    "{instrument_id, instrument_number, status, amount, drawn, remaining, currency, "
    "expires_on, customer_id, customer_name}; an unknown instrument, the other kind, or "
    "another customer's fails the step.",
    reads=lambda params: (
        [params.instrument_number_path]
        + ([params.customer_number_path] if params.customer_number_path else [])
    ),
    effect="reads",
    fixtures=lambda params: {
        params.instrument_number_path: f"{params.kind}.instrument_number",
        **(
            {params.customer_number_path: "business.customer_number"}
            if params.customer_number_path
            else {}
        ),
    },  # fmt: skip
)
def _lookup_instrument(ctx: StepContext, params: LookupInstrument) -> dict[str, Any]:
    from app.modules.customers.models import Customer
    from app.modules.trade import service as trade

    number = str(_required(ctx, params.instrument_number_path))
    instrument = trade.find_instrument(ctx.db, number)
    if instrument is None or instrument.kind != params.kind:
        raise StepError("instrument_not_found", f"No {params.kind.replace('_', ' ')} {number}.")
    customer = ctx.db.get(Customer, instrument.customer_id)
    if (
        params.customer_number_path
        and customer.customer_number
        != str(_required(ctx, params.customer_number_path)).strip().upper()
    ):
        raise StepError("instrument_not_owned", "The instrument belongs to another customer.")
    return {"instrument_id": str(instrument.id), "instrument_number": instrument.instrument_number,
            "status": instrument.status, "amount": instrument.amount, "drawn": instrument.drawn,
            "remaining": instrument.amount - instrument.drawn, "currency": instrument.currency,
            "expires_on": instrument.expires_on.isoformat(), "customer_id": str(customer.id),
            "customer_name": customer.name}  # fmt: skip


class ReceiveDemand(_Strict):
    instrument_id_path: str = Field(min_length=1, max_length=200)
    amount_path: str = Field(min_length=1, max_length=200)
    # Letters of credit: the discrepancy the checker found ("none" when compliant).
    discrepancy_path: str | None = Field(default=None, max_length=200)


@_library_handler(
    "trade.receive_demand",
    "Receive documents under a letter of credit, or a claim under a guarantee.",
    ReceiveDemand,
    "{demand_id, demand_number, amount, discrepant, discrepancies}; an expired instrument, "
    "an amount beyond what is left or a demand already being checked fails the step.",
    reads=lambda params: (
        [params.instrument_id_path, params.amount_path]
        + ([params.discrepancy_path] if params.discrepancy_path else [])
    ),  # fmt: skip
    effect="writes",
)
def _receive_demand(ctx: StepContext, params: ReceiveDemand) -> dict[str, Any]:
    from app.modules.trade import service as trade

    instrument = trade.get_instrument(
        ctx.db, uuid.UUID(str(_required(ctx, params.instrument_id_path))), for_update=True
    )
    found = str(ctx.get(params.discrepancy_path) or "none") if params.discrepancy_path else "none"
    demand = _trade_call(
        "demand_refused", trade.receive_demand, ctx.db, instrument,
        amount=int(_required(ctx, params.amount_path)), presented_on=ctx.now.date(),
        discrepancies=[] if found == "none" else [found], received_by=ctx.initiator_id,
    )  # fmt: skip
    return {"demand_id": str(demand.id), "demand_number": demand.demand_number,
            "amount": demand.amount, "discrepant": bool(demand.discrepancies),
            "discrepancies": ", ".join(demand.discrepancies) or "none"}  # fmt: skip


class DemandDecision(_Strict):
    demand_id_path: str = Field(min_length=1, max_length=200)
    decided_by_path: str = Field(min_length=1, max_length=200)
    note: str = Field(default="Not honoured", min_length=3, max_length=200)


@_library_handler(
    "trade.pay_demand",
    "Pay the beneficiary: margin released in proportion, the applicant's account debited.",
    DemandDecision,
    "{demand_number, status, amount, instrument_status}",
    reads=lambda params: [params.demand_id_path, params.decided_by_path],
    effect="moves_money",
    requires_approval=True,
)
def _pay_demand(ctx: StepContext, params: DemandDecision) -> dict[str, Any]:
    from app.modules.trade import service as trade

    demand = trade.get_demand(ctx.db, uuid.UUID(str(_required(ctx, params.demand_id_path))))
    decider = uuid.UUID(str(_required(ctx, params.decided_by_path)))
    demand = _trade_call("payment_refused", trade.pay_demand, ctx.db, demand, decider,
                         now=ctx.now)  # fmt: skip
    instrument = trade.get_instrument(ctx.db, demand.instrument_id)
    return {"demand_number": demand.demand_number, "status": demand.status,
            "amount": demand.amount, "instrument_status": instrument.status}  # fmt: skip


@_library_handler(
    "trade.reject_demand",
    "Reject the documents or the claim; nothing is paid.",
    DemandDecision,
    "{demand_number, status, amount, instrument_status}",
    reads=lambda params: [params.demand_id_path, params.decided_by_path],
    effect="writes",
)
def _reject_demand(ctx: StepContext, params: DemandDecision) -> dict[str, Any]:
    from app.modules.trade import service as trade

    demand = trade.get_demand(ctx.db, uuid.UUID(str(_required(ctx, params.demand_id_path))))
    demand = _trade_call("rejection_refused", trade.reject_demand, ctx.db, demand,
                         uuid.UUID(str(_required(ctx, params.decided_by_path))), params.note,
                         now=ctx.now)  # fmt: skip
    instrument = trade.get_instrument(ctx.db, demand.instrument_id)
    return {"demand_number": demand.demand_number, "status": demand.status,
            "amount": demand.amount, "instrument_status": instrument.status}  # fmt: skip


class DemandRef(_Strict):
    demand_id_path: str = Field(min_length=1, max_length=200)


@_library_handler(
    "trade.presentation_profile",
    "Read what a trade officer weighs before the applicant's waiver: the discrepancy, how much "
    "is drawn, days to expiry, the applicant's funds and the credit's earlier presentations.",
    DemandRef,
    "{discrepancy, discrepancy_count, draw_share_bps, days_to_expiry, funding_cover_bps, "
    "earlier_presentations, earlier_rejected, earlier_same_discrepancy} (Phase 38).",
    reads=lambda params: [params.demand_id_path],
    effect="reads",
)
def _presentation_profile(ctx: StepContext, params: DemandRef) -> dict[str, Any]:
    from app.modules.trade import service as trade

    demand = trade.get_demand(ctx.db, uuid.UUID(str(_required(ctx, params.demand_id_path))))
    return trade.presentation_profile(ctx.db, demand)


# --- Treasury (Phase 39) ---------------------------------------------------------------------


def _treasury_counterparty(ctx: StepContext, path: str):
    from app.modules.treasury import service as treasury

    code = str(_required(ctx, path))
    counterparty = treasury.find_counterparty(ctx.db, code)
    if counterparty is None:
        raise StepError("counterparty_not_found", f"No counterparty {code}.")
    return counterparty


def _deal_out(deal) -> dict[str, Any]:
    return {"deal_id": str(deal.id), "deal_number": deal.deal_number, "kind": deal.kind,
            "status": deal.status, "currency": deal.currency, "principal": deal.principal,
            "interest": deal.interest, "maturity_date": deal.maturity_date.isoformat()}  # fmt: skip


class BookDeal(_Strict):
    counterparty_path: str = Field(min_length=1, max_length=200)
    kind_path: str = Field(min_length=1, max_length=200)
    currency_path: str = Field(min_length=1, max_length=200)
    principal_path: str = Field(min_length=1, max_length=200)
    rate_path: str = Field(min_length=1, max_length=200)
    tenor_path: str = Field(min_length=1, max_length=200)


@_library_handler(
    "treasury.book_deal",
    "Book an interbank placement or borrowing, value today: a placement only with an "
    "investment-grade counterparty and within its limit.",
    BookDeal,
    "{deal_id, deal_number, kind, status, currency, principal, interest, maturity_date}; a "
    "refused booking fails the step.",
    reads=lambda params: [params.counterparty_path, params.kind_path, params.currency_path,
                          params.principal_path, params.rate_path, params.tenor_path],
    effect="writes",
    fixtures=lambda params: {params.counterparty_path: "counterparty.code"},
)  # fmt: skip
def _book_deal(ctx: StepContext, params: BookDeal) -> dict[str, Any]:
    from app.modules.treasury import service as treasury

    deal = _trade_call(
        "booking_refused", treasury.book_deal, ctx.db,
        counterparty=_treasury_counterparty(ctx, params.counterparty_path),
        kind=str(_required(ctx, params.kind_path)),
        currency=str(_required(ctx, params.currency_path)),
        principal=int(_required(ctx, params.principal_path)),
        rate_bps=int(_required(ctx, params.rate_path)),
        tenor_days=int(_required(ctx, params.tenor_path)),
        booked_by=ctx.initiator_id, today=ctx.now.date(),
    )  # fmt: skip
    return _deal_out(deal)


class DealDecision(_Strict):
    deal_id_path: str = Field(min_length=1, max_length=200)
    decided_by_path: str = Field(min_length=1, max_length=200)


def _deal(ctx: StepContext, params: DealDecision):
    from app.modules.treasury import service as treasury

    return treasury.get_deal(ctx.db, uuid.UUID(str(_required(ctx, params.deal_id_path))))


@_library_handler(
    "treasury.confirm_deal",
    "Back office confirms the deal and settles it: a placement pays the counterparty, a "
    "borrowing receives the cash.",
    DealDecision,
    "{deal_id, deal_number, kind, status, currency, principal, interest, maturity_date}",
    reads=lambda params: [params.deal_id_path, params.decided_by_path],
    effect="moves_money",
    requires_approval=True,
)
def _confirm_deal(ctx: StepContext, params: DealDecision) -> dict[str, Any]:
    from app.modules.treasury import service as treasury

    decider = uuid.UUID(str(_required(ctx, params.decided_by_path)))
    deal = _trade_call("settlement_refused", treasury.confirm_deal, ctx.db, _deal(ctx, params),
                       decider, now=ctx.now)  # fmt: skip
    return _deal_out(deal)


@_library_handler(
    "treasury.cancel_deal",
    "Cancel a booked deal.",
    DealDecision,
    "{deal_id, deal_number, kind, status, currency, principal, interest, maturity_date}",
    reads=lambda params: [params.deal_id_path, params.decided_by_path],
    effect="writes",
)
def _cancel_deal(ctx: StepContext, params: DealDecision) -> dict[str, Any]:
    from app.modules.treasury import service as treasury

    decider = uuid.UUID(str(_required(ctx, params.decided_by_path)))
    deal = _trade_call("cancel_refused", treasury.cancel_deal, ctx.db, _deal(ctx, params),
                       decider)  # fmt: skip
    return _deal_out(deal)


class LookupDeal(_Strict):
    deal_number_path: str = Field(min_length=1, max_length=200)


@_library_handler(
    "treasury.lookup_deal",
    "Find a settled money-market deal and whether it is due.",
    LookupDeal,
    "{deal_id, deal_number, kind, status, currency, principal, interest, maturity_date, "
    "counterparty_code, due}; an unknown deal fails the step.",
    reads=lambda params: [params.deal_number_path],
    effect="reads",
    fixtures=lambda params: {params.deal_number_path: "treasury_deal.deal_number"},
)
def _lookup_deal(ctx: StepContext, params: LookupDeal) -> dict[str, Any]:
    from app.modules.treasury import service as treasury

    number = str(_required(ctx, params.deal_number_path))
    deal = treasury.find_deal(ctx.db, number)
    if deal is None:
        raise StepError("deal_not_found", f"No deal {number}.")
    counterparty = treasury.get_counterparty(ctx.db, deal.counterparty_id)
    return {**_deal_out(deal), "counterparty_code": counterparty.code,
            "due": deal.status == "settled" and deal.maturity_date <= ctx.now.date()}  # fmt: skip


@_library_handler(
    "treasury.mature_deal",
    "Settle principal and interest at maturity: a placement is repaid to the bank, a "
    "borrowing is repaid by it.",
    DealDecision,
    "{deal_id, deal_number, kind, status, currency, principal, interest, maturity_date}",
    reads=lambda params: [params.deal_id_path, params.decided_by_path],
    effect="moves_money",
    requires_approval=True,
)
def _mature_deal(ctx: StepContext, params: DealDecision) -> dict[str, Any]:
    from app.modules.treasury import service as treasury

    decider = uuid.UUID(str(_required(ctx, params.decided_by_path)))
    deal = _trade_call("maturity_refused", treasury.mature_deal, ctx.db, _deal(ctx, params),
                       decider, now=ctx.now)  # fmt: skip
    return _deal_out(deal)


class DealRef(_Strict):
    deal_id_path: str = Field(min_length=1, max_length=200)


@_library_handler(
    "treasury.deal_profile",
    "Read what back office checks before confirming: the rate against the reference rate, "
    "the tenor, the counterparty's rating and limit use, liquidity after a placement and "
    "same-day deals with the same terms.",
    DealRef,
    "{kind, currency, rate_bps, reference_rate_bps, rate_against_bank_bps, tenor_days, rating, "
    "limit_utilisation_bps, coverage_after_bps, same_day_duplicates} (Phase 40).",
    reads=lambda params: [params.deal_id_path],
    effect="reads",
)
def _deal_profile(ctx: StepContext, params: DealRef) -> dict[str, Any]:
    from app.modules.treasury import service as treasury

    deal = treasury.get_deal(ctx.db, uuid.UUID(str(_required(ctx, params.deal_id_path))))
    return treasury.deal_profile(ctx.db, deal, ctx.now.date())


class FxPosition(_Strict):
    currency_path: str = Field(min_length=1, max_length=200)


@_library_handler(
    "treasury.fx_position",
    "Read the FX desk's open position in a currency against its limit.",
    FxPosition,
    "{currency, position, value_usd, limit_usd, utilisation_bps, over_limit, excess_usd}",
    reads=lambda params: [params.currency_path],
    effect="reads",
    fixtures=lambda params: {params.currency_path: "fx_long.currency"},
)
def _fx_position(ctx: StepContext, params: FxPosition) -> dict[str, Any]:
    from app.modules.treasury import service as treasury

    row = treasury.position(ctx.db, str(_required(ctx, params.currency_path)), ctx.now.date())
    keys = ("currency", "position", "value_usd", "limit_usd", "utilisation_bps", "over_limit",
            "excess_usd")  # fmt: skip
    return {k: row.get(k) for k in keys}


class BookFxTrade(_Strict):
    counterparty_path: str = Field(min_length=1, max_length=200)
    sell_currency_path: str = Field(min_length=1, max_length=200)
    buy_currency_path: str = Field(min_length=1, max_length=200)
    amount_path: str = Field(min_length=1, max_length=200)


def _fx_trade_out(trade) -> dict[str, Any]:
    return {"trade_id": str(trade.id), "trade_number": trade.trade_number,
            "status": trade.status, "sell": f"{trade.sell_amount} {trade.sell_currency}",
            "buy": f"{trade.buy_amount} {trade.buy_currency}",
            "mid_rate": trade.mid_rate}  # fmt: skip


@_library_handler(
    "treasury.book_fx_trade",
    "Book an interbank spot trade at the day's mid rate that reduces a long position.",
    BookFxTrade,
    "{trade_id, trade_number, status, sell, buy, mid_rate}; a trade that would open or "
    "reverse a position fails the step.",
    reads=lambda params: [params.counterparty_path, params.sell_currency_path,
                          params.buy_currency_path, params.amount_path],
    effect="writes",
    fixtures=lambda params: {params.counterparty_path: "counterparty.code",
                             params.sell_currency_path: "fx_long.currency"},
)  # fmt: skip
def _book_fx_trade(ctx: StepContext, params: BookFxTrade) -> dict[str, Any]:
    from app.modules.treasury import service as treasury

    trade = _trade_call(
        "booking_refused", treasury.book_fx_trade, ctx.db,
        counterparty=_treasury_counterparty(ctx, params.counterparty_path),
        sell_currency=str(_required(ctx, params.sell_currency_path)),
        buy_currency=str(_required(ctx, params.buy_currency_path)),
        sell_amount=int(_required(ctx, params.amount_path)),
        booked_by=ctx.initiator_id, today=ctx.now.date(),
    )  # fmt: skip
    return _fx_trade_out(trade)


class FxTradeDecision(_Strict):
    trade_id_path: str = Field(min_length=1, max_length=200)
    decided_by_path: str = Field(min_length=1, max_length=200)


@_library_handler(
    "treasury.confirm_fx_trade",
    "Back office confirms the spot trade and settles both legs.",
    FxTradeDecision,
    "{trade_id, trade_number, status, sell, buy, mid_rate}",
    reads=lambda params: [params.trade_id_path, params.decided_by_path],
    effect="moves_money",
    requires_approval=True,
)
def _confirm_fx_trade(ctx: StepContext, params: FxTradeDecision) -> dict[str, Any]:
    from app.modules.treasury import service as treasury

    trade = treasury.get_fx_trade(ctx.db, uuid.UUID(str(_required(ctx, params.trade_id_path))))
    decider = uuid.UUID(str(_required(ctx, params.decided_by_path)))
    trade = _trade_call("settlement_refused", treasury.confirm_fx_trade, ctx.db, trade,
                        decider, now=ctx.now)  # fmt: skip
    return _fx_trade_out(trade)


@_library_handler(
    "treasury.cancel_fx_trade",
    "Cancel a booked spot trade.",
    FxTradeDecision,
    "{trade_id, trade_number, status, sell, buy, mid_rate}",
    reads=lambda params: [params.trade_id_path, params.decided_by_path],
    effect="writes",
)
def _cancel_fx_trade(ctx: StepContext, params: FxTradeDecision) -> dict[str, Any]:
    from app.modules.treasury import service as treasury

    trade = treasury.get_fx_trade(ctx.db, uuid.UUID(str(_required(ctx, params.trade_id_path))))
    decider = uuid.UUID(str(_required(ctx, params.decided_by_path)))
    trade = _trade_call("cancel_refused", treasury.cancel_fx_trade, ctx.db, trade, decider)
    return _fx_trade_out(trade)


# --- Payments operations (Phase 41) ----------------------------------------------------------


def _clearing_account(ctx: StepContext, path: str):
    from app.modules.clearing import service as clearing

    number = str(_required(ctx, path))
    account = clearing.find_account(ctx.db, number)
    if account is None:
        raise StepError("account_not_found", f"No account {number}.")
    return account


def _outgoing_out(payment) -> dict[str, Any]:
    return {"payment_id": str(payment.id), "payment_number": payment.payment_number,
            "status": payment.status, "high_value": payment.high_value,
            "amount": payment.amount, "currency": payment.currency}  # fmt: skip


class CreateOutgoing(_Strict):
    account_number_path: str = Field(min_length=1, max_length=200)
    beneficiary_name_path: str = Field(min_length=1, max_length=200)
    bank_path: str = Field(min_length=1, max_length=200)
    beneficiary_account_path: str = Field(min_length=1, max_length=200)
    amount_path: str = Field(min_length=1, max_length=200)
    reference_path: str | None = Field(default=None, max_length=200)


@_library_handler(
    "clearing.create_outgoing",
    "Enter a payment to an account at another bank; high value waits for an approval.",
    CreateOutgoing,
    "{payment_id, payment_number, status, high_value, amount, currency}; an unknown bank, "
    "wrong check digits or an amount beyond the limits fails the step.",
    reads=lambda params: (
        [params.account_number_path, params.beneficiary_name_path, params.bank_path,
         params.beneficiary_account_path, params.amount_path]
        + ([params.reference_path] if params.reference_path else [])
    ),
    effect="writes",
    fixtures=lambda params: {params.account_number_path: "account.account_number"},
)  # fmt: skip
def _create_outgoing(ctx: StepContext, params: CreateOutgoing) -> dict[str, Any]:
    from app.modules.clearing import service as clearing

    payment = _trade_call(
        "payment_refused", clearing.create_outgoing, ctx.db,
        debtor=_clearing_account(ctx, params.account_number_path),
        beneficiary_name=str(_required(ctx, params.beneficiary_name_path)),
        beneficiary_bank=str(_required(ctx, params.bank_path)),
        beneficiary_account=str(_required(ctx, params.beneficiary_account_path)),
        amount=int(_required(ctx, params.amount_path)),
        reference=str(ctx.get(params.reference_path) or "") if params.reference_path else "",
        initiated_by=ctx.initiator_id, today=ctx.now.date(),
    )  # fmt: skip
    return _outgoing_out(payment)


class OutgoingDecision(_Strict):
    payment_id_path: str = Field(min_length=1, max_length=200)
    decided_by_path: str = Field(min_length=1, max_length=200)
    note: str = Field(default="Not approved", min_length=3, max_length=200)


def _outgoing(ctx: StepContext, path: str):
    from app.modules.clearing import service as clearing

    return clearing.get_outgoing(ctx.db, uuid.UUID(str(_required(ctx, path))))


@_library_handler(
    "clearing.approve_outgoing",
    "Approve a high-value payment: it waits for the next clearing cycle.",
    OutgoingDecision,
    "{payment_id, payment_number, status, high_value, amount, currency}",
    reads=lambda params: [params.payment_id_path, params.decided_by_path],
    effect="writes",
    requires_approval=True,
)
def _approve_outgoing(ctx: StepContext, params: OutgoingDecision) -> dict[str, Any]:
    from app.modules.clearing import service as clearing

    decider = uuid.UUID(str(_required(ctx, params.decided_by_path)))
    payment = _trade_call("approval_refused", clearing.approve_outgoing, ctx.db,
                          _outgoing(ctx, params.payment_id_path), decider)  # fmt: skip
    return _outgoing_out(payment)


@_library_handler(
    "clearing.reject_outgoing",
    "Reject the payment before clearing.",
    OutgoingDecision,
    "{payment_id, payment_number, status, high_value, amount, currency}",
    reads=lambda params: [params.payment_id_path, params.decided_by_path],
    effect="writes",
)
def _reject_outgoing(ctx: StepContext, params: OutgoingDecision) -> dict[str, Any]:
    from app.modules.clearing import service as clearing

    decider = uuid.UUID(str(_required(ctx, params.decided_by_path)))
    payment = _trade_call("rejection_refused", clearing.reject_outgoing, ctx.db,
                          _outgoing(ctx, params.payment_id_path), decider, params.note)  # fmt: skip
    return _outgoing_out(payment)


class ReceiveBulk(_Strict):
    account_number_path: str = Field(min_length=1, max_length=200)
    file_name_path: str = Field(min_length=1, max_length=200)
    lines_path: str = Field(min_length=1, max_length=200)


def _bulk_out(bulk) -> dict[str, Any]:
    return {"bulk_id": str(bulk.id), "file_number": bulk.file_number, "status": bulk.status,
            "valid_count": bulk.valid_count, "invalid_count": bulk.invalid_count,
            "valid_total": bulk.valid_total, "currency": bulk.currency}  # fmt: skip


@_library_handler(
    "clearing.receive_bulk",
    "Receive a bulk payment file: every line validated, the valid ones within the funds.",
    ReceiveBulk,
    "{bulk_id, file_number, status, valid_count, invalid_count, valid_total, currency}; no "
    "valid line, or more than the account can pay, fails the step.",
    reads=lambda params: [params.account_number_path, params.file_name_path, params.lines_path],
    effect="writes",
    fixtures=lambda params: {params.account_number_path: "business.account_number"},
)
def _receive_bulk(ctx: StepContext, params: ReceiveBulk) -> dict[str, Any]:
    from app.modules.clearing import service as clearing

    lines = _required(ctx, params.lines_path)
    if not isinstance(lines, list):
        raise StepError("bad_lines", "The file's lines must be a list.")
    bulk = _trade_call(
        "file_refused", clearing.receive_bulk, ctx.db,
        account=_clearing_account(ctx, params.account_number_path),
        file_name=str(_required(ctx, params.file_name_path)),
        lines=[dict(line) for line in lines if isinstance(line, dict)],
        received_by=ctx.initiator_id, today=ctx.now.date(),
    )  # fmt: skip
    return _bulk_out(bulk)


class BulkDecision(_Strict):
    bulk_id_path: str = Field(min_length=1, max_length=200)
    decided_by_path: str = Field(min_length=1, max_length=200)
    note: str = Field(default="Not approved", min_length=3, max_length=200)


def _bulk(ctx: StepContext, path: str):
    from app.modules.clearing import service as clearing

    return clearing.get_bulk(ctx.db, uuid.UUID(str(_required(ctx, path))))


@_library_handler(
    "clearing.release_bulk",
    "Approve the file: each valid line becomes a payment waiting for clearing.",
    BulkDecision,
    "{bulk_id, file_number, status, valid_count, invalid_count, valid_total, currency, payments}",
    reads=lambda params: [params.bulk_id_path, params.decided_by_path],
    effect="writes",
    requires_approval=True,
)
def _release_bulk(ctx: StepContext, params: BulkDecision) -> dict[str, Any]:
    from app.modules.clearing import service as clearing

    decider = uuid.UUID(str(_required(ctx, params.decided_by_path)))
    bulk = _bulk(ctx, params.bulk_id_path)
    created = _trade_call("release_refused", clearing.release_bulk, ctx.db, bulk, decider,
                          today=ctx.now.date())  # fmt: skip
    return {**_bulk_out(_bulk(ctx, params.bulk_id_path)), "payments": len(created)}


@_library_handler(
    "clearing.reject_bulk",
    "Reject the file; no payment is made.",
    BulkDecision,
    "{bulk_id, file_number, status, valid_count, invalid_count, valid_total, currency}",
    reads=lambda params: [params.bulk_id_path, params.decided_by_path],
    effect="writes",
)
def _reject_bulk(ctx: StepContext, params: BulkDecision) -> dict[str, Any]:
    from app.modules.clearing import service as clearing

    decider = uuid.UUID(str(_required(ctx, params.decided_by_path)))
    bulk = _trade_call("rejection_refused", clearing.reject_bulk, ctx.db,
                       _bulk(ctx, params.bulk_id_path), decider, params.note)  # fmt: skip
    return _bulk_out(bulk)


class LookupOutgoing(_Strict):
    payment_number_path: str = Field(min_length=1, max_length=200)


@_library_handler(
    "clearing.lookup_outgoing",
    "Find an outgoing payment and its status.",
    LookupOutgoing,
    "{payment_id, payment_number, status, high_value, amount, currency, settled_on}; an "
    "unknown payment fails the step.",
    reads=lambda params: [params.payment_number_path],
    effect="reads",
    fixtures=lambda params: {params.payment_number_path: "outgoing_payment.payment_number"},
)
def _lookup_outgoing(ctx: StepContext, params: LookupOutgoing) -> dict[str, Any]:
    from app.modules.clearing import service as clearing

    number = str(_required(ctx, params.payment_number_path))
    payment = clearing.find_outgoing(ctx.db, number)
    if payment is None:
        raise StepError("payment_not_found", f"No outgoing payment {number}.")
    settled = payment.settled_on.isoformat() if payment.settled_on else None
    return {**_outgoing_out(payment), "settled_on": settled}


class RequestRecall(_Strict):
    payment_id_path: str = Field(min_length=1, max_length=200)
    reason_path: str = Field(min_length=1, max_length=200)


def _recall_out(recall) -> dict[str, Any]:
    return {"recall_id": str(recall.id), "recall_number": recall.recall_number,
            "status": recall.status, "sent": recall.status == "sent",
            "returned": recall.status == "accepted",
            "outcome": recall.outcome_note or ""}  # fmt: skip


@_library_handler(
    "clearing.request_recall",
    "Ask for a payment back (not while it is in a clearing batch).",
    RequestRecall,
    "{recall_id, recall_number, status, sent, returned, outcome}",
    reads=lambda params: [params.payment_id_path, params.reason_path],
    effect="writes",
)
def _request_recall(ctx: StepContext, params: RequestRecall) -> dict[str, Any]:
    from app.modules.clearing import service as clearing

    recall = _trade_call("recall_refused", clearing.request_recall, ctx.db,
                         _outgoing(ctx, params.payment_id_path),
                         str(_required(ctx, params.reason_path)), ctx.initiator_id)  # fmt: skip
    return _recall_out(recall)


class RecallRef(_Strict):
    recall_id_path: str = Field(min_length=1, max_length=200)


@_library_handler(
    "clearing.recall_profile",
    "Read what back office weighs before sending a recall: the reason's window, the payment's "
    "size, matching duplicates, the payer's history with the beneficiary and its recalls.",
    RecallRef,
    "{reason_code, amount, high_value, days_since_settlement, window_days, days_left, "
    "duplicate_matches, payee_history, payer_recalls_90d, payer_refused_90d} (Phase 42).",
    reads=lambda params: [params.recall_id_path],
    effect="reads",
)
def _recall_profile(ctx: StepContext, params: RecallRef) -> dict[str, Any]:
    from app.modules.clearing import service as clearing

    recall = clearing.get_recall(ctx.db, uuid.UUID(str(_required(ctx, params.recall_id_path))))
    return clearing.recall_profile(ctx.db, recall, ctx.now.date())


class RecallDecision(_Strict):
    recall_id_path: str = Field(min_length=1, max_length=200)
    decided_by_path: str = Field(min_length=1, max_length=200)


def _recall(ctx: StepContext, path: str):
    from app.modules.clearing import service as clearing

    return clearing.get_recall(ctx.db, uuid.UUID(str(_required(ctx, path))))


@_library_handler(
    "clearing.approve_recall",
    "Approve the recall: a payment not yet cleared is cancelled; a settled one is sent to "
    "the beneficiary's bank.",
    RecallDecision,
    "{recall_id, recall_number, status, sent, returned, outcome}",
    reads=lambda params: [params.recall_id_path, params.decided_by_path],
    effect="writes",
    requires_approval=True,
)
def _approve_recall(ctx: StepContext, params: RecallDecision) -> dict[str, Any]:
    from app.modules.clearing import service as clearing

    decider = uuid.UUID(str(_required(ctx, params.decided_by_path)))
    recall = _trade_call("approval_refused", clearing.approve_recall, ctx.db,
                         _recall(ctx, params.recall_id_path), decider, now=ctx.now)  # fmt: skip
    return _recall_out(recall)


@_library_handler(
    "clearing.withdraw_recall",
    "Withdraw a recall that was not approved.",
    RecallDecision,
    "{recall_id, recall_number, status, sent, returned, outcome}",
    reads=lambda params: [params.recall_id_path, params.decided_by_path],
    effect="writes",
)
def _withdraw_recall(ctx: StepContext, params: RecallDecision) -> dict[str, Any]:
    from app.modules.clearing import service as clearing

    decider = uuid.UUID(str(_required(ctx, params.decided_by_path)))
    recall = _trade_call("withdraw_refused", clearing.withdraw_recall, ctx.db,
                         _recall(ctx, params.recall_id_path), decider)  # fmt: skip
    return _recall_out(recall)


@_library_handler(
    "clearing.resolve_recall",
    "Record the beneficiary bank's answer: the money comes back within the reason's window "
    "after settlement, otherwise the recall is refused.",
    RecallDecision,
    "{recall_id, recall_number, status, sent, returned, outcome}",
    reads=lambda params: [params.recall_id_path, params.decided_by_path],
    effect="moves_money",
    requires_approval=True,
)
def _resolve_recall(ctx: StepContext, params: RecallDecision) -> dict[str, Any]:
    from app.modules.clearing import service as clearing

    decider = uuid.UUID(str(_required(ctx, params.decided_by_path)))
    recall = _trade_call("resolution_refused", clearing.resolve_recall, ctx.db,
                         _recall(ctx, params.recall_id_path), decider,
                         today=ctx.now.date())  # fmt: skip
    return _recall_out(recall)


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

    if (ctx.get("_settings") or {}).get("ai_mode") == "off":
        # An experiment's baseline (Phase 30): the case runs without the tool.
        return {"available": False, "skipped": True, "mode": "off", "recommendation": "escalate"}
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
        # Read by the simulation's AI metrics, like the code workflows' AI steps.
        "invocation_status": call.status,
        "recommendation": out.get("recommendation", "escalate"),
        "risk_classification": out.get("risk_classification"),
        "risk_score": out.get("risk_score"),
        "confidence": out.get("confidence"),
        "findings": [f.get("code") for f in out.get("findings", [])],
        "explanation": out.get("explanation"),
    }
