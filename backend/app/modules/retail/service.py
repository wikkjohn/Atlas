"""Retail banking services (Phase 29): products, arranged overdrafts, standing orders, month
end (interest and fees) and statements. Every amount moves through the ledger.
"""

import calendar as month_calendar
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.audit import diff, record_audit_event
from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.core.money import minor_unit_exponent, to_minor_units
from app.modules.accounts import service as accounts
from app.modules.accounts.models import Account, AccountStatus
from app.modules.countries.models import Country
from app.modules.fx import rates
from app.modules.ledger import service as ledger
from app.modules.ledger.models import Direction, JournalEntry, JournalLine, LedgerAccountType
from app.modules.retail.models import (
    STANDING_ORDER_NUMBER_SEQUENCE,
    STATEMENT_NUMBER_SEQUENCE,
    AccountStatement,
    MonthEndRun,
    RetailProduct,
    StandingOrder,
    StandingOrderFrequency,
    StandingOrderStatus,
)

DAYS_IN_YEAR = 365
# A standing order stops after this many missed payments in a row.
MAX_FAILURES = 3


# --- Products -----------------------------------------------------------------------------------


def get_product(db: Session, account_type: str) -> RetailProduct:
    product = db.get(RetailProduct, account_type)
    if product is None:
        raise NotFoundError(f"No retail product for {account_type} accounts.")
    return product


def list_products(db: Session) -> list[RetailProduct]:
    return list(db.execute(select(RetailProduct).order_by(RetailProduct.account_type)).scalars())


def _usd_to_minor(usd_cents: int, currency: str) -> int:
    """US cents in minor units of `currency` at the FX anchor rate (deterministic)."""
    units = Decimal(usd_cents) / 100 * rates.units_per_usd(currency, rates.ANCHOR_DATE)
    return int((units * 10 ** minor_unit_exponent(currency)).quantize(Decimal(1), ROUND_HALF_UP))


def _two_figures(value: Decimal) -> int:
    whole = int(value)
    if whole < 100:
        return max(whole, 0)
    return round(whole, -(len(str(whole)) - 2))


def monthly_fee(product: RetailProduct, currency: str) -> int:
    return _usd_to_minor(product.monthly_fee_usd_cents, currency)


def max_overdraft(product: RetailProduct, currency: str) -> int:
    """The product's largest arranged overdraft in minor units, two significant figures of
    the converted dollar amount."""
    usd = Decimal(product.max_overdraft_usd) * rates.units_per_usd(currency, rates.ANCHOR_DATE)
    return to_minor_units(_two_figures(usd), currency)


PRODUCT_FIELDS = (
    "name",
    "credit_rate_bps",
    "overdraft_rate_bps",
    "monthly_fee_usd_cents",
    "max_overdraft_usd",
)


def update_product(
    db: Session, account_type: str, changes: dict[str, Any], actor_id: uuid.UUID
) -> RetailProduct:
    product = get_product(db, account_type)
    before = {f: getattr(product, f) for f in PRODUCT_FIELDS}
    for field, value in changes.items():
        if field in PRODUCT_FIELDS and value is not None:
            setattr(product, field, value)
    product.updated_at = datetime.now(UTC)
    product.updated_by = actor_id
    db.flush()
    changed = diff(before, {f: getattr(product, f) for f in PRODUCT_FIELDS})
    if changed:
        record_audit_event(
            db,
            actor_id=actor_id,
            action="retail_product.updated",
            entity_type="retail_product",
            entity_id=account_type,
            metadata={"account_type": account_type, "changes": changed},
        )
    return product


# --- Overdrafts ---------------------------------------------------------------------------------


def set_overdraft(
    db: Session,
    account: Account,
    limit: int,
    actor_id: uuid.UUID | None,
    *,
    approved_by: uuid.UUID | None = None,
    source: str = "api",
) -> tuple[Account, int]:
    """Arrange (or change, or remove with 0) an overdraft. Returns (account, previous)."""
    account = accounts.get_account(db, account.id, for_update=True)
    if account.status != AccountStatus.OPEN:
        raise BusinessRuleViolation(f"The account is {account.status}.")
    product = get_product(db, account.account_type)
    ceiling = max_overdraft(product, account.currency)
    if limit < 0:
        raise BusinessRuleViolation("An overdraft limit cannot be negative.")
    if limit > ceiling:
        raise BusinessRuleViolation(
            f"{product.name} allows an overdraft of at most {ceiling} minor units of "
            f"{account.currency}.",
            {"limit": limit, "maximum": ceiling},
        )
    balance = ledger.balance(db, ledger.get_ledger_account(db, account.ledger_account_id))
    if balance < -limit:
        raise BusinessRuleViolation(
            "The account is overdrawn by more than the new limit; it must be repaid first.",
            {"balance": balance, "limit": limit},
        )
    previous = account.overdraft_limit
    account.overdraft_limit = limit
    db.flush()
    if previous != limit:
        record_audit_event(
            db,
            actor_id=actor_id,
            action="account.overdraft_changed",
            entity_type="account",
            entity_id=account.id,
            metadata={
                "account_number": account.account_number,
                "overdraft_limit": [previous, limit],
                "approved_by": str(approved_by) if approved_by else None,
                "source": source,
            },
        )
    return account, previous


# --- Standing orders ------------------------------------------------------------------------------


def _add_month(day: date, day_of_month: int) -> date:
    year, month = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
    return date(year, month, min(day_of_month, month_calendar.monthrange(year, month)[1]))


def following(order: StandingOrder, day: date) -> date:
    if order.frequency == StandingOrderFrequency.WEEKLY:
        return day + timedelta(days=7)
    return _add_month(day, order.day_of_month)


def get_standing_order(db: Session, order_id: uuid.UUID) -> StandingOrder:
    order = db.get(StandingOrder, order_id)
    if order is None:
        raise NotFoundError("Standing order not found.")
    return order


def create_standing_order(
    db: Session,
    *,
    debtor: Account,
    creditor: Account,
    amount: int,
    frequency: StandingOrderFrequency,
    first_date: date,
    end_date: date | None,
    reference: str,
    actor_id: uuid.UUID | None,
    today: date | None = None,
) -> StandingOrder:
    from app.modules.payments import service as payments
    from app.modules.rules import service as rules

    today = today or datetime.now(UTC).date()
    if debtor.id == creditor.id:
        raise BusinessRuleViolation("A standing order needs two different accounts.")
    for role, account in (("payer", debtor), ("payee", creditor)):
        if account.status != AccountStatus.OPEN:
            raise BusinessRuleViolation(f"The {role} account is {account.status}.")
    if creditor.currency != debtor.currency:
        raise BusinessRuleViolation(
            "Standing orders pay in the payer's currency; the payee account is in "
            f"{creditor.currency}, not {debtor.currency}."
        )
    if first_date < today:
        raise BusinessRuleViolation("The first payment date cannot be in the past.")
    if end_date is not None and end_date < first_date:
        raise BusinessRuleViolation("The end date is before the first payment.")
    _, country_rules = payments.country_rules_of(db, debtor, today)
    threshold, _ = rules.payment_limits(country_rules, debtor.currency)
    if amount <= 0 or amount >= threshold:
        # Payments from threshold upwards need a second person's approval every time.
        raise BusinessRuleViolation(
            "A standing order must be below the high-value threshold "
            f"({threshold} minor units of {debtor.currency}).",
            {"amount": amount, "high_value_threshold": threshold},
        )
    number = db.execute(STANDING_ORDER_NUMBER_SEQUENCE.next_value()).scalar_one()
    order = StandingOrder(
        order_number=f"SO-{number:07d}",
        debtor_account_id=debtor.id,
        creditor_account_id=creditor.id,
        amount=amount,
        currency=debtor.currency,
        frequency=frequency.value,
        day_of_month=first_date.day,
        next_date=first_date,
        end_date=end_date,
        reference=reference.strip(),
        status=StandingOrderStatus.ACTIVE.value,
        failures=0,
        payments_made=0,
        created_by=actor_id,
    )
    db.add(order)
    db.flush()
    record_audit_event(
        db,
        actor_id=actor_id,
        action="standing_order.created",
        entity_type="standing_order",
        entity_id=order.id,
        metadata={
            "order_number": order.order_number,
            "debtor": debtor.account_number,
            "creditor": creditor.account_number,
            "amount": amount,
            "currency": order.currency,
            "frequency": order.frequency,
            "first_date": first_date.isoformat(),
        },
    )
    return order


def cancel_standing_order(db: Session, order: StandingOrder, actor_id: uuid.UUID) -> StandingOrder:
    if order.status != StandingOrderStatus.ACTIVE:
        raise ConflictError(f"The standing order is {order.status}.")
    order.status = StandingOrderStatus.CANCELLED.value
    order.cancelled_at = datetime.now(UTC)
    db.flush()
    record_audit_event(
        db,
        actor_id=actor_id,
        action="standing_order.cancelled",
        entity_type="standing_order",
        entity_id=order.id,
        metadata={"order_number": order.order_number},
    )
    return order


def _business_day(db: Session, account: Account, day: date) -> bool:
    from app.modules.reference import calendar

    country = db.get(Country, account.customer.country_id)
    assert country is not None
    return calendar.is_business_day(country.calendar_profile(), day)


def run_standing_orders(db: Session, as_of: date, actor_id: uuid.UUID) -> dict[str, int]:
    """Pay every active order due on or before `as_of`, on business days of the payer's
    country (an order due on a weekend or holiday pays on the next business day). A missed
    payment (no funds) is not retried; the order moves on and stops after three in a row."""
    from app.modules.payments import service as payments

    due = list(
        db.execute(
            select(StandingOrder)
            .where(
                StandingOrder.status == StandingOrderStatus.ACTIVE,
                StandingOrder.next_date <= as_of,
            )
            .order_by(StandingOrder.next_date, StandingOrder.order_number)
            .with_for_update(skip_locked=True)
        ).scalars()
    )
    counts = {"due": len(due), "paid": 0, "missed": 0, "waiting": 0, "ended": 0, "failed": 0}
    now = datetime.combine(as_of, datetime.min.time(), UTC) + timedelta(hours=9)
    for order in due:
        if order.end_date is not None and order.next_date > order.end_date:
            order.status = StandingOrderStatus.ENDED.value
            counts["ended"] += 1
            continue
        debtor = accounts.get_account(db, order.debtor_account_id)
        creditor = accounts.get_account(db, order.creditor_account_id)
        if not _business_day(db, debtor, as_of):
            counts["waiting"] += 1
            continue
        try:
            with db.begin_nested():
                if order.amount > accounts.available(db, debtor):
                    raise BusinessRuleViolation("Insufficient funds.")
                payment = payments.create_payment(
                    db,
                    debtor=debtor,
                    creditor=creditor,
                    amount=order.amount,
                    reference=f"{order.order_number} {order.reference}"[:140],
                    initiated_by=actor_id,
                    now=now,
                )
                payments.release(db, payment.id, approver=None, now=now)
        except (BusinessRuleViolation, ConflictError) as exc:
            order.failures += 1
            order.last_error = exc.message[:300]
            counts["missed"] += 1
            if order.failures >= MAX_FAILURES:
                order.status = StandingOrderStatus.FAILED.value
                counts["failed"] += 1
        else:
            order.failures = 0
            order.last_error = None
            order.payments_made += 1
            order.last_payment_id = payment.id
            counts["paid"] += 1
        if order.status == StandingOrderStatus.ACTIVE:
            order.next_date = following(order, order.next_date)
            while order.next_date <= as_of - timedelta(days=31):  # long gaps: catch up once
                order.next_date = following(order, order.next_date)
            if order.end_date is not None and order.next_date > order.end_date:
                order.status = StandingOrderStatus.ENDED.value
                counts["ended"] += 1
    db.flush()
    return counts


# --- Balances by day ----------------------------------------------------------------------------


def _movements(db: Session, ledger_account_id: uuid.UUID, start: date, end: date) -> dict:
    """Credits minus debits per effective date in [start, end], and the opening balance
    (everything before `start`), for a credit-normal customer deposit account."""
    signed = case(
        (JournalLine.direction == Direction.CREDIT, JournalLine.amount), else_=-JournalLine.amount
    )
    base = (
        select(JournalEntry.effective_date, func.sum(signed))
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
        .where(JournalLine.ledger_account_id == ledger_account_id)
    )
    opening = db.execute(
        select(func.coalesce(func.sum(signed), 0))
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
        .where(
            JournalLine.ledger_account_id == ledger_account_id,
            JournalEntry.effective_date < start,
        )
    ).scalar_one()
    by_day = dict(
        db.execute(
            base.where(JournalEntry.effective_date.between(start, end)).group_by(
                JournalEntry.effective_date
            )
        ).all()
    )
    return {"opening": int(opening), "by_day": {d: int(v) for d, v in by_day.items()}}


def interest(
    db: Session, account: Account, product: RetailProduct, start: date, end: date
) -> tuple[int, int]:
    """(interest earned, overdraft interest owed) for [start, end], in minor units: the
    annual rate on each day's closing balance, divided by 365, summed and rounded once."""
    moves = _movements(db, account.ledger_account_id, start, end)
    balance = moves["opening"]
    earned = owed = Decimal(0)
    day = start
    while day <= end:
        balance += moves["by_day"].get(day, 0)
        if balance > 0:
            earned += Decimal(balance) * product.credit_rate_bps / 10_000 / DAYS_IN_YEAR
        elif balance < 0:
            owed += Decimal(-balance) * product.overdraft_rate_bps / 10_000 / DAYS_IN_YEAR
        day += timedelta(days=1)
    whole = Decimal(1)
    return int(earned.quantize(whole, ROUND_HALF_UP)), int(owed.quantize(whole, ROUND_HALF_UP))


def account_profile(db: Session, account: Account, today: date) -> dict[str, Any]:
    """The account's last 90 days before `today` (by effective date): average money in a
    month, in how many of the three 30-day windows any came in, and the days it ended
    overdrawn; with its balance, limit and its product's maximum (Phase 30)."""
    start = today - timedelta(days=90)
    end = today - timedelta(days=1)
    credit = case((JournalLine.direction == Direction.CREDIT, JournalLine.amount), else_=0)
    credits_by_day = dict(
        db.execute(
            select(JournalEntry.effective_date, func.sum(credit))
            .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
            .where(
                JournalLine.ledger_account_id == account.ledger_account_id,
                JournalEntry.effective_date.between(start, end),
            )
            .group_by(JournalEntry.effective_date)
        )
        .tuples()
        .all()
    )
    windows = [0, 0, 0]
    for day, amount in credits_by_day.items():
        windows[min((day - start).days // 30, 2)] += int(amount)
    moves = _movements(db, account.ledger_account_id, start, end)
    balance, overdrawn, day = moves["opening"], 0, start
    while day <= end:
        balance += moves["by_day"].get(day, 0)
        overdrawn += balance < 0
        day += timedelta(days=1)
    product = db.get(RetailProduct, account.account_type)
    return {
        "currency": account.currency,
        "balance": ledger.balance(db, ledger.get_ledger_account(db, account.ledger_account_id)),
        "overdraft_limit": account.overdraft_limit,
        "max_overdraft": max_overdraft(product, account.currency) if product else 0,
        "monthly_credits": sum(windows) // 3,
        "months_with_credits": sum(1 for w in windows if w > 0),
        "days_overdrawn": overdrawn,
    }


# --- Statements ---------------------------------------------------------------------------------


def issue_statement(
    db: Session,
    account: Account,
    start: date,
    end: date,
    actor_id: uuid.UUID | None,
) -> tuple[AccountStatement, bool]:
    """The account's statement for [start, end] (by effective date): issued once per period;
    asking again returns the same statement. Returns (statement, created)."""
    existing = db.execute(
        select(AccountStatement).where(
            AccountStatement.account_id == account.id, AccountStatement.period_start == start
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False
    moves = _movements(db, account.ledger_account_id, start, end)
    signed = case((JournalLine.direction == Direction.CREDIT, JournalLine.amount), else_=0)
    debit = case((JournalLine.direction == Direction.DEBIT, JournalLine.amount), else_=0)
    credits, debits, lines = db.execute(
        select(func.coalesce(func.sum(signed), 0), func.coalesce(func.sum(debit), 0), func.count())
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
        .where(
            JournalLine.ledger_account_id == account.ledger_account_id,
            JournalEntry.effective_date.between(start, end),
        )
    ).one()
    number = db.execute(STATEMENT_NUMBER_SEQUENCE.next_value()).scalar_one()
    statement = AccountStatement(
        statement_number=f"STM-{number:07d}",
        account_id=account.id,
        period_start=start,
        period_end=end,
        currency=account.currency,
        opening_balance=moves["opening"],
        closing_balance=moves["opening"] + sum(moves["by_day"].values()),
        total_credits=int(credits),
        total_debits=int(debits),
        lines=int(lines),
        overdraft_limit=account.overdraft_limit,
        issued_by=actor_id,
    )
    db.add(statement)
    db.flush()
    return statement, True


def statement_lines(db: Session, statement: AccountStatement) -> list[dict[str, Any]]:
    account = accounts.get_account(db, statement.account_id)
    rows = db.execute(
        select(JournalEntry, JournalLine)
        .join(JournalLine, JournalLine.journal_entry_id == JournalEntry.id)
        .where(
            JournalLine.ledger_account_id == account.ledger_account_id,
            JournalEntry.effective_date.between(statement.period_start, statement.period_end),
        )
        .order_by(JournalEntry.effective_date, JournalEntry.entry_number)
    ).all()
    balance = statement.opening_balance
    found = []
    for entry, line in rows:
        amount = line.amount if line.direction == Direction.CREDIT else -line.amount
        balance += amount
        found.append(
            {
                "date": entry.effective_date,
                "entry_number": entry.entry_number,
                "description": entry.description,
                "source": entry.source,
                "amount": amount,
                "balance": balance,
            }
        )
    return found


# --- Month end ----------------------------------------------------------------------------------


def month_bounds(period: date) -> tuple[date, date]:
    start = period.replace(day=1)
    return start, start.replace(day=month_calendar.monthrange(start.year, start.month)[1])


def last_complete_month(today: date) -> date:
    return (today.replace(day=1) - timedelta(days=1)).replace(day=1)


def _bank_account(db: Session, kind: str, currency: str):
    names = {
        "INTEREST-EXPENSE": ("Interest paid to customers", LedgerAccountType.EXPENSE),
        "INTEREST-INCOME": ("Overdraft interest income", LedgerAccountType.INCOME),
    }
    name, account_type = names[kind]
    return ledger.ensure_ledger_account(
        db,
        code=f"{kind}-{currency}",
        name=f"{name} ({currency})",
        account_type=account_type,
        currency=currency,
    )


def _post(
    db: Session, key: str, account: Account, other, amount: int, to_customer: bool, text: str,
    source: str, effective: date, actor_id: uuid.UUID | None,
) -> None:  # fmt: skip
    customer_side = Direction.CREDIT if to_customer else Direction.DEBIT
    other_side = Direction.DEBIT if to_customer else Direction.CREDIT
    ledger.post_entry(
        db,
        idempotency_key=key,
        currency=account.currency,
        description=f"{text} {account.account_number}",
        source=source,
        lines=[
            ledger.LineSpec(account.ledger_account_id, customer_side, amount, text),
            ledger.LineSpec(other.id, other_side, amount, text),
        ],
        actor_id=actor_id,
        effective_date=effective,
    )


def month_end(
    db: Session, period: date, actor_id: uuid.UUID | None, *, today: date | None = None
) -> tuple[MonthEndRun, bool]:
    """Interest, fees and statements for one calendar month, once. Returns (run, created).

    For every open or frozen account of a retail product opened by the month's end:
    interest earned on credit balances (paid from interest expense), overdraft interest on
    overdrawn days (to interest income), and the monthly fee for a whole month's account
    (to fee income), each posted on the last day of the month; then the month's statement.
    """
    today = today or datetime.now(UTC).date()
    start, end = month_bounds(period)
    if end >= today:
        raise BusinessRuleViolation(f"{start:%B %Y} is not over yet.")
    existing = db.execute(
        select(MonthEndRun).where(MonthEndRun.period_start == start)
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False
    products = {p.account_type: p for p in list_products(db)}
    candidates = list(
        db.execute(
            select(Account)
            .where(
                Account.account_type.in_(list(products)),
                Account.status.in_([AccountStatus.OPEN, AccountStatus.FROZEN]),
                func.date(Account.opened_at) <= end,
            )
            .order_by(Account.account_number)
        ).scalars()
    )
    totals: dict[str, dict[str, int]] = {}
    entries = statements = 0
    period_key = f"{start:%Y-%m}"
    for account in candidates:
        product = products[account.account_type]
        opened = account.opened_at.date()
        earned, owed = interest(db, account, product, max(start, opened), end)
        fee = monthly_fee(product, account.currency) if opened < start else 0
        sums = totals.setdefault(
            account.currency, {"interest_paid": 0, "interest_charged": 0, "fees": 0}
        )
        if earned:
            _post(db, f"retail:interest-paid:{account.id}:{period_key}", account,
                  _bank_account(db, "INTEREST-EXPENSE", account.currency), earned, True,
                  "Credit interest", "interest", end, actor_id)  # fmt: skip
            sums["interest_paid"] += earned
            entries += 1
        if owed:
            _post(db, f"retail:interest-charged:{account.id}:{period_key}", account,
                  _bank_account(db, "INTEREST-INCOME", account.currency), owed, False,
                  "Overdraft interest", "interest", end, actor_id)  # fmt: skip
            sums["interest_charged"] += owed
            entries += 1
        if fee:
            _post(db, f"retail:fee:{account.id}:{period_key}", account,
                  accounts.fee_income_account(db, account.currency), fee, False,
                  f"{product.name} monthly fee", "fee", end, actor_id)  # fmt: skip
            sums["fees"] += fee
            entries += 1
        _, created = issue_statement(db, account, start, end, actor_id)
        statements += created
    run = MonthEndRun(
        period_start=start,
        period_end=end,
        accounts=len(candidates),
        statements=statements,
        entries=entries,
        totals=dict(sorted(totals.items())),
        created_by=actor_id,
    )
    db.add(run)
    db.flush()
    record_audit_event(
        db,
        actor_id=actor_id,
        action="retail.month_end",
        entity_type="retail_month_end",
        entity_id=run.id,
        metadata={"period": period_key, "accounts": run.accounts, "entries": entries},
    )
    return run, True
