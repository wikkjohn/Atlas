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
