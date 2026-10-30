"""FX service: publish rates, quote, convert, report positions and revalue them."""

import uuid
from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.errors import BusinessRuleViolation, NotFoundError
from app.core.money import minor_unit_exponent
from app.core.pagination import PageParams, paginate
from app.modules.countries.models import Currency
from app.modules.fx import rates
from app.modules.fx.models import FX_DEAL_NUMBER_SEQUENCE, FxDeal, FxRate, FxRevaluation
from app.modules.ledger import service as ledger
from app.modules.ledger.models import Direction, LedgerAccount, LedgerAccountType

DEFAULT_MARGIN_BPS = 50  # the customer rate is 0.50 % less favourable than the mid rate
POSITION_PREFIX = "FX-POSITION"
REVALUATION_ACCOUNT = "FX-REVALUATION-USD"
REVALUATION_INCOME = "FX-REVALUATION-INCOME-USD"
RATE_PLACES = Decimal("0.000000000001")  # deal rates: 12 decimal places


# --- Rates ------------------------------------------------------------------------------------


def publish_rates(db: Session, day: date) -> int:
    """Publish the day's synthetic rate of every known currency; returns how many were new."""
    codes = [c for c in db.execute(select(Currency.code)).scalars() if rates.supported(c)]
    rows = [
        {"currency": c, "rate_date": day, "units_per_usd": rates.units_per_usd(c, day)}
        for c in codes
    ]
    if not rows:
        return 0
    added = db.execute(
        insert(FxRate)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["currency", "rate_date"])
        .returning(FxRate.currency)
    ).all()
    return len(added)


def rates_on(db: Session, day: date) -> dict[str, Decimal]:
    """Every published rate of a day (published on first use)."""
    query = select(FxRate.currency, FxRate.units_per_usd).where(FxRate.rate_date == day)
    found = dict(db.execute(query).tuples().all())
    if not found:
        publish_rates(db, day)
        found = dict(db.execute(query).tuples().all())
    return found


def rate(db: Session, currency: str, day: date) -> Decimal:
    found = rates_on(db, day).get(currency)
    if found is None:
        raise BusinessRuleViolation(
            f"No exchange rate for {currency}.", {"rule": "no_rate", "currency": currency}
        )
    return found


def history(db: Session, currency: str, start: date, end: date) -> list[tuple[date, Decimal]]:
    """Published rates of one currency between two dates (missing days are published)."""
    if not rates.supported(currency):
        raise NotFoundError(f"No exchange rates for {currency}.")
    if (end - start).days > 366:
        raise BusinessRuleViolation("At most a year of history at a time.")
    day, out = start, []
    while day <= end:
        out.append((day, rate(db, currency, day)))
        day = date.fromordinal(day.toordinal() + 1)
    return out


# --- Quotes and conversions -------------------------------------------------------------------


def _major(amount: int, currency: str) -> Decimal:
    return Decimal(amount) / (Decimal(10) ** minor_unit_exponent(currency))


def _minor(major: Decimal, currency: str, rounding: str = ROUND_DOWN) -> int:
    scaled = major * (Decimal(10) ** minor_unit_exponent(currency))
    return int(scaled.quantize(Decimal(1), rounding=rounding))


def quote(
    db: Session,
    sell_currency: str,
    buy_currency: str,
    sell_amount: int,
    day: date,
    margin_bps: int = DEFAULT_MARGIN_BPS,
) -> dict[str, Any]:
    """What `sell_amount` (minor units) buys: the mid rate, the customer rate (mid less the
    margin) and the bought amount, rounded down to a minor unit."""
    if sell_currency == buy_currency:
        raise BusinessRuleViolation("A conversion needs two different currencies.")
    if sell_amount <= 0:
        raise BusinessRuleViolation("The amount to convert must be positive.")
    if not 0 <= margin_bps <= 1000:
        raise BusinessRuleViolation("The margin must be between 0 and 1,000 basis points.")
    sell_rate, buy_rate = rate(db, sell_currency, day), rate(db, buy_currency, day)
    mid = (buy_rate / sell_rate).quantize(RATE_PLACES, ROUND_HALF_EVEN)
    customer = (mid * (1 - Decimal(margin_bps) / 10_000)).quantize(RATE_PLACES, ROUND_DOWN)
    sold = _major(sell_amount, sell_currency)
    buy_amount = _minor(sold * customer, buy_currency)
    if buy_amount <= 0:
        raise BusinessRuleViolation(
            "The amount is too small to convert.", {"rule": "amount_too_small"}
        )
    return {
        "sell_currency": sell_currency,
        "sell_amount": sell_amount,
        "buy_currency": buy_currency,
        "buy_amount": buy_amount,
        "mid_rate": mid,
        "customer_rate": customer,
        "margin_bps": margin_bps,
        "rate_date": day,
        "base_amount": _minor(sold / sell_rate, rates.BASE, ROUND_HALF_EVEN),
    }


def position_account(db: Session, currency: str) -> LedgerAccount:
    """The bank's open position in a currency, created on first use."""
    return ledger.ensure_ledger_account(
        db,
        code=f"{POSITION_PREFIX}-{currency}",
        name=f"Foreign exchange position ({currency})",
        account_type=LedgerAccountType.EQUITY,
        currency=currency,
    )


def convert(
    db: Session,
    *,
    from_account: LedgerAccount,
    to_account: LedgerAccount,
    sell_amount: int,
    day: date,
    idempotency_key: str,
    purpose: str,
    reference: str,
    actor_id: uuid.UUID | None,
    margin_bps: int = DEFAULT_MARGIN_BPS,
) -> tuple[FxDeal, bool]:
    """Move `sell_amount` out of `from_account` and its value, converted, into `to_account`:
    two balanced entries, one per currency, through the position accounts. Returns
    (deal, replayed); the same key returns the original deal."""
    existing = db.execute(
        select(FxDeal).where(FxDeal.idempotency_key == idempotency_key)
    ).scalar_one_or_none()
    if existing is not None:
        return existing, True
    terms = quote(db, from_account.currency, to_account.currency, sell_amount, day, margin_bps)
    number = db.execute(FX_DEAL_NUMBER_SEQUENCE.next_value()).scalar_one()
    deal_number = f"FX-{number:08d}"
    memo = f"{deal_number} {reference}"[:200]
    sell_entry, _ = ledger.post_entry(
        db,
        idempotency_key=f"{idempotency_key}:sell",
        currency=terms["sell_currency"],
        description=f"FX {deal_number}: sell {terms['sell_currency']}",
        source="fx",
        lines=[
            ledger.LineSpec(from_account.id, Direction.DEBIT, sell_amount, memo),
            ledger.LineSpec(
                position_account(db, terms["sell_currency"]).id,
                Direction.CREDIT,
                sell_amount,
                memo,
            ),
        ],
        actor_id=actor_id,
        effective_date=day,
    )
    buy_entry, _ = ledger.post_entry(
        db,
        idempotency_key=f"{idempotency_key}:buy",
        currency=terms["buy_currency"],
        description=f"FX {deal_number}: buy {terms['buy_currency']}",
        source="fx",
        lines=[
            ledger.LineSpec(
                position_account(db, terms["buy_currency"]).id,
                Direction.DEBIT,
                terms["buy_amount"],
                memo,
            ),
            ledger.LineSpec(to_account.id, Direction.CREDIT, terms["buy_amount"], memo),
        ],
        actor_id=actor_id,
        effective_date=day,
    )
    deal = FxDeal(
        deal_number=deal_number,
        idempotency_key=idempotency_key,
        purpose=purpose,
        reference=reference[:140],
        rate_date=day,
        sell_currency=terms["sell_currency"],
        sell_amount=sell_amount,
        buy_currency=terms["buy_currency"],
        buy_amount=terms["buy_amount"],
        mid_rate=terms["mid_rate"],
        customer_rate=terms["customer_rate"],
        margin_bps=margin_bps,
        base_amount=terms["base_amount"],
        sell_entry_id=sell_entry.id,
        buy_entry_id=buy_entry.id,
        created_by=actor_id,
    )
    db.add(deal)
    db.flush()
    record_audit_event(
        db,
        actor_id=actor_id,
        action="fx.converted",
        entity_type="fx_deal",
        entity_id=deal.id,
        metadata={
            "deal_number": deal_number,
            "sell": f"{sell_amount} {deal.sell_currency}",
            "buy": f"{deal.buy_amount} {deal.buy_currency}",
            "purpose": purpose,
        },
    )
    return deal, False


def list_deals(
    db: Session, params: PageParams, currency: str | None = None
) -> tuple[list[FxDeal], int]:
    query = select(FxDeal).order_by(FxDeal.created_at.desc(), FxDeal.deal_number.desc())
    if currency:
        query = query.where((FxDeal.sell_currency == currency) | (FxDeal.buy_currency == currency))
    return paginate(db, query, params)


# --- Positions and revaluation ----------------------------------------------------------------


def _revaluation_accounts(db: Session) -> tuple[LedgerAccount, LedgerAccount]:
    adjustment = ledger.ensure_ledger_account(
        db,
        code=REVALUATION_ACCOUNT,
        name="FX revaluation of open positions (USD)",
        account_type=LedgerAccountType.ASSET,
        currency=rates.BASE,
    )
    income = ledger.ensure_ledger_account(
        db,
        code=REVALUATION_INCOME,
        name="Foreign exchange result (USD)",
        account_type=LedgerAccountType.INCOME,
        currency=rates.BASE,
    )
    return adjustment, income


def positions(db: Session, as_of: date) -> dict[str, Any]:
    """Each open currency position (credit balance: the bank is long), its value in US cents
    at the day's rate, the total, what revaluation has booked so far and the unbooked rest."""
    accounts = list(
        db.execute(
            select(LedgerAccount)
            .where(LedgerAccount.code.like(f"{POSITION_PREFIX}-%"))
            .order_by(LedgerAccount.currency)
        ).scalars()
    )
    balances = ledger.balances(db, accounts)
    day_rates = rates_on(db, as_of)
    rows, total = [], 0
    for account in accounts:
        amount = balances[account.id]
        units = day_rates.get(account.currency)
        if units is None:
            raise BusinessRuleViolation(f"No exchange rate for {account.currency}.")
        value = _minor(_major(amount, account.currency) / units, rates.BASE, ROUND_HALF_EVEN)
        rows.append(
            {
                "currency": account.currency,
                "position": amount,
                "units_per_usd": str(units),
                "value_usd": value,
            }
        )
        total += value
    adjustment, _ = _revaluation_accounts(db)
    booked = ledger.balance(db, adjustment)
    return {
        "as_of": as_of,
        "positions": rows,
        "total_value_usd": total,
        "booked_usd": booked,
        "unbooked_usd": total - booked,
    }


def revalue(db: Session, as_of: date, actor_id: uuid.UUID | None) -> FxRevaluation:
    """Book the change in the positions' US-dollar value since the last revaluation:
    debit (or credit) the revaluation account against FX income, in US dollars."""
    report = positions(db, as_of)
    delta = report["unbooked_usd"]
    run = FxRevaluation(
        as_of=as_of,
        positions=report["positions"],
        total_value=report["total_value_usd"],
        previously_booked=report["booked_usd"],
        posted=delta,
        run_by=actor_id,
    )
    db.add(run)
    db.flush()
    if delta:
        adjustment, income = _revaluation_accounts(db)
        gain = delta > 0
        entry, _ = ledger.post_entry(
            db,
            idempotency_key=f"fx-revaluation:{run.run_number}",
            currency=rates.BASE,
            description=f"FX revaluation #{run.run_number} as of {as_of.isoformat()}",
            source="fx_revaluation",
            lines=[
                ledger.LineSpec(
                    adjustment.id, Direction.DEBIT if gain else Direction.CREDIT, abs(delta), None
                ),
                ledger.LineSpec(
                    income.id, Direction.CREDIT if gain else Direction.DEBIT, abs(delta), None
                ),
            ],
            actor_id=actor_id,
            effective_date=as_of,
        )
        run.journal_entry_id = entry.id
        db.flush()
    record_audit_event(
        db,
        actor_id=actor_id,
        action="fx.revalued",
        entity_type="fx_revaluation",
        entity_id=run.id,
        metadata={"as_of": as_of.isoformat(), "posted_usd_cents": delta},
    )
    return run


def list_revaluations(db: Session, params: PageParams) -> tuple[list[FxRevaluation], int]:
    return paginate(db, select(FxRevaluation).order_by(FxRevaluation.run_number.desc()), params)
