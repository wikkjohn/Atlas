"""Treasury services (Phase 39): counterparties, money-market deals, liquidity and the FX
desk."""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.core.money import minor_unit_exponent
from app.modules.fx import rates
from app.modules.fx import service as fx
from app.modules.ledger import service as ledger
from app.modules.ledger.models import Direction, LedgerAccount, LedgerAccountType, LedgerBalance
from app.modules.treasury.models import (
    DEAL_SEQUENCE,
    FX_TRADE_SEQUENCE,
    DealKind,
    DealStatus,
    FxTradeStatus,
    TreasuryCounterparty,
    TreasuryDeal,
    TreasuryFxLimit,
    TreasuryFxTrade,
)

MIN_PRINCIPAL_USD, MAX_PRINCIPAL_USD = 100_000, 100_000_000
MIN_TENOR_DAYS, MAX_TENOR_DAYS = 1, 365
# Money-market convention: these currencies count interest on ACT/365, the rest ACT/360.
ACT_365 = frozenset({"GBP", "AUD", "NZD", "SGD", "HKD", "ZAR", "INR", "JPY", "CAD", "MYR"})
# Ratings from strongest to weakest; placements only with investment grade (BBB- or better).
RATINGS = ("AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-",
           "BB+", "BB", "BB-", "B+", "B", "B-")  # fmt: skip
INVESTMENT_GRADE = frozenset(RATINGS[: RATINGS.index("BBB-") + 1])
HORIZON_DAYS = 30  # the liquidity window
RUN_OFF_BPS = 1000  # stressed outflow: 10 % of customer deposits within the window
MIN_COVERAGE_BPS = 10_000  # a placement may not take a currency below 100 % coverage
DEFAULT_FX_LIMIT_USD = 1_000_000  # net open position limit where none is set

# Synthetic reference rates (bps a year) the back office compares deals against (Phase 40).
REFERENCE_RATES_BPS = {"USD": 525, "EUR": 375, "GBP": 500, "JPY": 25, "CHF": 150, "CAD": 450,
                       "AUD": 435, "SGD": 350, "HKD": 450}  # fmt: skip
DEFAULT_REFERENCE_BPS = 400

# Synthetic counterparty banks (names invented for the simulation).
COUNTERPARTIES = (
    ("CP-NORTHGATE", "Northgate Commercial Bank (synthetic)", "GB", "AA-", 250_000_000),
    ("CP-RIDGELINE", "Ridgeline National Bank (synthetic)", "US", "AA", 300_000_000),
    ("CP-RHEINTAL", "Rheintal Landesbank (synthetic)", "DE", "A+", 200_000_000),
    ("CP-SAKURAGAWA", "Sakuragawa Trust Bank (synthetic)", "JP", "A", 150_000_000),
    ("CP-MERLION", "Merlion Pacific Bank (synthetic)", "SG", "AA-", 150_000_000),
    ("CP-GULFSTAR", "Gulfstar Investment Bank (synthetic)", "AE", "A-", 100_000_000),
    ("CP-ANDINO", "Banco Andino del Sur (synthetic)", "CL", "BBB", 50_000_000),
    ("CP-SAVANNA", "Savanna Continental Bank (synthetic)", "KE", "BB+", 25_000_000),
)


# --- Counterparties and limits -----------------------------------------------------------


def ensure_counterparties(db: Session) -> int:
    """Create the synthetic counterparties that are missing; returns how many were added."""
    existing = set(db.execute(select(TreasuryCounterparty.code)).scalars())
    added = 0
    for code, name, country, rating, limit in COUNTERPARTIES:
        if code not in existing:
            db.add(TreasuryCounterparty(code=code, name=name, country_code=country,
                                        rating=rating, limit_usd=limit))  # fmt: skip
            added += 1
    db.flush()
    return added


def find_counterparty(db: Session, code: str) -> TreasuryCounterparty | None:
    return db.execute(
        select(TreasuryCounterparty).where(TreasuryCounterparty.code == code.strip().upper())
    ).scalar_one_or_none()


def get_counterparty(db: Session, counterparty_id: uuid.UUID, *, for_update: bool = False):
    query = select(TreasuryCounterparty).where(TreasuryCounterparty.id == counterparty_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    counterparty = db.execute(query).scalar_one_or_none()
    if counterparty is None:
        raise NotFoundError("Counterparty not found.")
    return counterparty


def _usd(amount: int, currency: str, day: date, db: Session) -> int:
    """`amount` minor units of `currency` in whole US dollars at the day's rate."""
    major = Decimal(amount) / (Decimal(10) ** minor_unit_exponent(currency))
    return int(major / fx.rate(db, currency, day))


def _from_usd(usd: int, currency: str) -> int:
    """Whole US dollars in minor units of `currency`, at the anchor rate."""
    units = Decimal(usd) * rates.units_per_usd(currency, rates.ANCHOR_DATE)
    return int(units * 10 ** minor_unit_exponent(currency))


def exposure_usd(db: Session, counterparty: TreasuryCounterparty, day: date) -> int:
    """Outstanding placements with the counterparty (booked or settled), in whole US dollars
    at the day's rates."""
    rows = db.execute(
        select(TreasuryDeal.currency, func.sum(TreasuryDeal.principal))
        .where(TreasuryDeal.counterparty_id == counterparty.id,
               TreasuryDeal.kind == DealKind.PLACEMENT,
               TreasuryDeal.status.in_([DealStatus.BOOKED, DealStatus.SETTLED]))
        .group_by(TreasuryDeal.currency)
    ).all()  # fmt: skip
    return sum(_usd(int(total), currency, day, db) for currency, total in rows)


def set_counterparty_limit(
    db: Session, counterparty: TreasuryCounterparty, limit_usd: int, actor_id: uuid.UUID | None
) -> TreasuryCounterparty:
    if not 0 <= limit_usd <= 1_000_000_000:
        raise BusinessRuleViolation("A counterparty limit is between 0 and US$1bn.")
    before, counterparty.limit_usd = counterparty.limit_usd, limit_usd
    counterparty.limit_changed_by = actor_id
    db.flush()
    metadata = {"code": counterparty.code, "from": before, "to": limit_usd}
    record_audit_event(db, actor_id=actor_id, action="treasury.counterparty_limit_set",
                       entity_type="treasury_counterparty", entity_id=counterparty.id,
                       metadata=metadata)  # fmt: skip
    return counterparty


# --- Ledger --------------------------------------------------------------------------------

_LEDGER = {
    "PLACEMENTS": ("Interbank placements", LedgerAccountType.ASSET),
    "BORROWINGS": ("Interbank borrowings", LedgerAccountType.LIABILITY),
    "INTEREST-INCOME": ("Interbank interest income", LedgerAccountType.INCOME),
    "INTEREST-EXPENSE": ("Interbank interest expense", LedgerAccountType.EXPENSE),
}


def treasury_account(db: Session, kind: str, currency: str) -> LedgerAccount:
    name, account_type = _LEDGER[kind]
    return ledger.ensure_ledger_account(
        db, code=f"TREASURY-{kind}-{currency}", name=f"{name} ({currency})",
        account_type=account_type, currency=currency,
    )  # fmt: skip


def _post(db: Session, *, key: str, currency: str, memo: str, lines: list[tuple], actor_id,
          today: date) -> None:  # fmt: skip
    ledger.post_entry(
        db, idempotency_key=key, currency=currency, description=memo, source="treasury",
        lines=[ledger.LineSpec(account.id, direction, amount, memo)
               for account, direction, amount in lines if amount],
        actor_id=actor_id, effective_date=today,
    )  # fmt: skip


def lock_query(ids):
    """FOR NO KEY UPDATE: it conflicts with itself, so treasury settlements serialise, but
    not with the KEY SHARE locks that inserting journal lines takes on their ledger
    accounts, so it cannot deadlock with postings in other transactions (PR #31 review)."""
    return (
        select(LedgerAccount.id)
        .where(LedgerAccount.id.in_(sorted(ids)))
        .order_by(LedgerAccount.id)
        .with_for_update(key_share=True)
    )


def _lock(db: Session, *accounts: LedgerAccount) -> None:
    """Lock the ledger account rows a check reads before posting to them, in id order, so
    two treasury settlements cannot both pass against the same balance (PR #30 review)."""
    db.execute(lock_query({a.id for a in accounts})).all()


def _cash(db: Session, currency: str) -> int:
    return ledger.balance(db, ledger.cash_account(db, currency))


def _audit(db, actor_id, action: str, entity_type: str, entity_id, **metadata) -> None:
    record_audit_event(db, actor_id=actor_id, action=action, entity_type=entity_type,
                       entity_id=entity_id, metadata=metadata)  # fmt: skip


# --- Liquidity -------------------------------------------------------------------------------


def _deposits(db: Session) -> dict[str, int]:
    """Customer deposits by currency (the credit balances of the 2100- accounts)."""
    rows = db.execute(
        select(LedgerAccount.currency,
               func.sum(LedgerBalance.credit_total - LedgerBalance.debit_total))
        .join(LedgerBalance, LedgerBalance.ledger_account_id == LedgerAccount.id)
        .where(LedgerAccount.code.like(f"{ledger.CUSTOMER_DEPOSITS_PREFIX}-%"))
        .group_by(LedgerAccount.currency)
    ).all()  # fmt: skip
    return {currency: int(total or 0) for currency, total in rows}


def _maturing(db: Session, kind: str, until: date) -> dict[str, int]:
    """Principal and interest of settled deals of `kind` maturing by `until`, by currency."""
    rows = db.execute(
        select(TreasuryDeal.currency, func.sum(TreasuryDeal.principal + TreasuryDeal.interest))
        .where(TreasuryDeal.kind == kind, TreasuryDeal.status == DealStatus.SETTLED,
               TreasuryDeal.maturity_date <= until)
        .group_by(TreasuryDeal.currency)
    ).all()  # fmt: skip
    return {currency: int(total) for currency, total in rows}


def _coverage(liquid: int, outflow: int) -> int | None:
    return liquid * 10_000 // outflow if outflow > 0 else None


def liquidity(db: Session, as_of: date, currency: str | None = None) -> dict[str, Any]:
    """Each currency's liquidity over the next 30 days: cash and placements maturing in the
    window against borrowings maturing in it plus a 10 % run-off of customer deposits."""
    until = as_of + timedelta(days=HORIZON_DAYS)
    deposits = _deposits(db)
    inflows = _maturing(db, DealKind.PLACEMENT, until)
    outflows = _maturing(db, DealKind.BORROWING, until)
    cash_accounts = list(db.execute(
        select(LedgerAccount).where(LedgerAccount.code.like(f"{ledger.CASH_ACCOUNT_PREFIX}-%"))
    ).scalars())  # fmt: skip
    balances = ledger.balances(db, cash_accounts)
    cash = {a.currency: balances[a.id] for a in cash_accounts}
    rows = []
    currencies = sorted(set(cash) | set(deposits) | set(inflows) | set(outflows))
    for ccy in currencies if currency is None else [currency]:
        liquid = cash.get(ccy, 0) + inflows.get(ccy, 0)
        outflow = outflows.get(ccy, 0) + deposits.get(ccy, 0) * RUN_OFF_BPS // 10_000
        coverage = _coverage(liquid, outflow)
        rows.append({
            "currency": ccy, "cash": cash.get(ccy, 0), "inflows": inflows.get(ccy, 0),
            "deposits": deposits.get(ccy, 0), "outflows": outflows.get(ccy, 0),
            "liquid": liquid, "stressed_outflow": outflow, "coverage_bps": coverage,
            "below_minimum": coverage is not None and coverage < MIN_COVERAGE_BPS,
        })  # fmt: skip
    return {"as_of": as_of, "horizon_days": HORIZON_DAYS, "run_off_bps": RUN_OFF_BPS,
            "minimum_bps": MIN_COVERAGE_BPS, "currencies": rows}  # fmt: skip


# --- Money-market deals ----------------------------------------------------------------------


def interest_for(principal: int, rate_bps: int, days: int, basis: int) -> int:
    """Simple interest, rounded down to a minor unit."""
    return principal * rate_bps * days // (10_000 * basis)


def book_deal(
    db: Session, *, counterparty: TreasuryCounterparty, kind: str, currency: str,
    principal: int, rate_bps: int, tenor_days: int, booked_by: uuid.UUID,
    today: date | None = None,
) -> TreasuryDeal:  # fmt: skip
    """A dealer books a placement or a borrowing, value today. A placement must be with an
    investment-grade counterparty and within its limit."""
    today = today or datetime.now(UTC).date()
    kind = DealKind(kind)
    currency = currency.strip().upper()
    if not rates.supported(currency):
        raise BusinessRuleViolation(f"{currency} is not a supported currency.")
    low, high = _from_usd(MIN_PRINCIPAL_USD, currency), _from_usd(MAX_PRINCIPAL_USD, currency)
    if not low <= principal <= high:
        raise BusinessRuleViolation(
            f"A deal's principal must be between {low} and {high} (US$100,000 to 100m).",
            {"rule": "principal_range"},
        )
    if not 0 <= rate_bps <= 5000:
        raise BusinessRuleViolation("The rate must be between 0 and 50 %.")
    if not MIN_TENOR_DAYS <= tenor_days <= MAX_TENOR_DAYS:
        raise BusinessRuleViolation("The tenor must be between 1 and 365 days.")
    if kind == DealKind.PLACEMENT:
        _check_placement(db, counterparty, currency, principal, today)
    basis = 365 if currency in ACT_365 else 360
    number = f"MM-{db.execute(DEAL_SEQUENCE.next_value()).scalar_one():07d}"
    deal = TreasuryDeal(
        deal_number=number, kind=kind.value, counterparty_id=counterparty.id, currency=currency,
        principal=principal, rate_bps=rate_bps, day_basis=basis, value_date=today,
        maturity_date=today + timedelta(days=tenor_days),
        interest=interest_for(principal, rate_bps, tenor_days, basis),
        status=DealStatus.BOOKED.value, booked_by=booked_by,
    )  # fmt: skip
    db.add(deal)
    db.flush()
    _audit(db, booked_by, "treasury.deal_booked", "treasury_deal", deal.id, deal_number=number,
           kind=kind.value, counterparty=counterparty.code, principal=principal)  # fmt: skip
    return deal


def _check_placement(db, counterparty, currency: str, principal: int, today: date,
                     *, counted: int = 0) -> None:  # fmt: skip
    """Investment grade and within the counterparty's limit. `counted` is the part of the
    current exposure that is this deal itself (when re-checking at confirmation)."""
    if counterparty.rating not in INVESTMENT_GRADE:
        raise BusinessRuleViolation(
            f"{counterparty.code} is rated {counterparty.rating}: placements need BBB- or "
            "better.", {"rule": "rating"},
        )  # fmt: skip
    after = exposure_usd(db, counterparty, today) - counted + _usd(principal, currency, today, db)
    if after > counterparty.limit_usd:
        raise BusinessRuleViolation(
            f"The placement would take {counterparty.code} to US${after:,}, above its "
            f"US${counterparty.limit_usd:,} limit.",
            {"rule": "counterparty_limit", "exposure_usd": after,
             "limit_usd": counterparty.limit_usd},
        )  # fmt: skip


def get_deal(db: Session, deal_id: uuid.UUID, *, for_update: bool = False) -> TreasuryDeal:
    query = select(TreasuryDeal).where(TreasuryDeal.id == deal_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    deal = db.execute(query).scalar_one_or_none()
    if deal is None:
        raise NotFoundError("Deal not found.")
    return deal


def find_deal(db: Session, number: str) -> TreasuryDeal | None:
    return db.execute(
        select(TreasuryDeal).where(TreasuryDeal.deal_number == number.strip().upper())
    ).scalar_one_or_none()


def _require(deal: TreasuryDeal, status: DealStatus) -> None:
    if deal.status != status:
        raise ConflictError(f"{deal.deal_number} is {deal.status}, not {status.value}.")


def confirm_deal(
    db: Session, deal: TreasuryDeal, actor_id: uuid.UUID, *, now: datetime | None = None
) -> TreasuryDeal:
    """Back office confirms a booked deal (not the dealer), which settles it: a placement
    pays the cash to the counterparty, a borrowing receives it."""
    now = now or datetime.now(UTC)
    today = now.date()
    deal = get_deal(db, deal.id, for_update=True)
    _require(deal, DealStatus.BOOKED)
    if actor_id == deal.booked_by:
        raise BusinessRuleViolation("Four-eyes rule: the dealer cannot confirm their own deal.",
                                    {"rule": "four_eyes"})  # fmt: skip
    if today >= deal.maturity_date:
        raise BusinessRuleViolation(f"{deal.deal_number} reached maturity unconfirmed; cancel "
                                    "it.", {"rule": "past_maturity"})  # fmt: skip
    counterparty = get_counterparty(db, deal.counterparty_id, for_update=True)
    cash = ledger.cash_account(db, deal.currency)
    _lock(db, cash)
    if deal.kind == DealKind.PLACEMENT:
        _check_placement(db, counterparty, deal.currency, deal.principal, today,
                         counted=_usd(deal.principal, deal.currency, today, db))  # fmt: skip
        _check_liquidity_after(db, deal, today)
        lines = [(treasury_account(db, "PLACEMENTS", deal.currency), Direction.DEBIT,
                  deal.principal), (cash, Direction.CREDIT, deal.principal)]  # fmt: skip
    else:
        lines = [(cash, Direction.DEBIT, deal.principal),
                 (treasury_account(db, "BORROWINGS", deal.currency), Direction.CREDIT,
                  deal.principal)]  # fmt: skip
    _post(db, key=f"treasury-settle:{deal.deal_number}", currency=deal.currency,
          memo=f"{deal.kind.title()} {deal.deal_number} with {counterparty.code}",
          lines=lines, actor_id=actor_id, today=today)  # fmt: skip
    deal.status, deal.confirmed_by, deal.settled_at = DealStatus.SETTLED.value, actor_id, now
    db.flush()
    _audit(db, actor_id, "treasury.deal_settled", "treasury_deal", deal.id,
           deal_number=deal.deal_number)  # fmt: skip
    return deal


def _check_liquidity_after(db: Session, deal: TreasuryDeal, today: date) -> None:
    """A placement must leave the cash to pay it and the currency at 100 % coverage."""
    if deal.principal > _cash(db, deal.currency):
        raise BusinessRuleViolation(f"Not enough {deal.currency} cash for the placement.",
                                    {"rule": "cash"})  # fmt: skip
    row = liquidity(db, today, deal.currency)["currencies"][0]
    liquid = row["liquid"] - deal.principal
    if deal.maturity_date <= today + timedelta(days=HORIZON_DAYS):
        liquid += deal.principal + deal.interest
    after = _coverage(liquid, row["stressed_outflow"])
    if after is not None and after < MIN_COVERAGE_BPS:
        raise BusinessRuleViolation(
            f"The placement would take {deal.currency} liquidity coverage to "
            f"{after / 100:.0f} %, below 100 %.",
            {"rule": "liquidity_coverage", "coverage_bps": after},
        )  # fmt: skip


def cancel_deal(db: Session, deal: TreasuryDeal, actor_id: uuid.UUID | None) -> TreasuryDeal:
    deal = get_deal(db, deal.id, for_update=True)
    _require(deal, DealStatus.BOOKED)
    deal.status, deal.closed_at = DealStatus.CANCELLED.value, datetime.now(UTC)
    db.flush()
    _audit(db, actor_id, "treasury.deal_cancelled", "treasury_deal", deal.id,
           deal_number=deal.deal_number)  # fmt: skip
    return deal


def mature_deal(
    db: Session, deal: TreasuryDeal, actor_id: uuid.UUID, *, now: datetime | None = None
) -> TreasuryDeal:
    """Back office settles a deal on or after its maturity date (not the dealer): a placement
    returns principal and interest, a borrowing repays them."""
    now = now or datetime.now(UTC)
    today = now.date()
    deal = get_deal(db, deal.id, for_update=True)
    _require(deal, DealStatus.SETTLED)
    if actor_id == deal.booked_by:
        raise BusinessRuleViolation("Four-eyes rule: the dealer cannot settle their own deal.",
                                    {"rule": "four_eyes"})  # fmt: skip
    if today < deal.maturity_date:
        raise BusinessRuleViolation(f"{deal.deal_number} matures on {deal.maturity_date}.")
    cash = ledger.cash_account(db, deal.currency)
    _lock(db, cash)
    total = deal.principal + deal.interest
    # Principal and interest on separate cash lines: each stays within the ledger's line
    # limit for every supported currency (PR #30 review).
    if deal.kind == DealKind.PLACEMENT:
        lines = [(cash, Direction.DEBIT, deal.principal),
                 (cash, Direction.DEBIT, deal.interest),
                 (treasury_account(db, "PLACEMENTS", deal.currency), Direction.CREDIT,
                  deal.principal),
                 (treasury_account(db, "INTEREST-INCOME", deal.currency), Direction.CREDIT,
                  deal.interest)]  # fmt: skip
    else:
        if total > _cash(db, deal.currency):
            raise BusinessRuleViolation(f"Not enough {deal.currency} cash to repay.",
                                        {"rule": "cash"})  # fmt: skip
        lines = [(treasury_account(db, "BORROWINGS", deal.currency), Direction.DEBIT,
                  deal.principal),
                 (treasury_account(db, "INTEREST-EXPENSE", deal.currency), Direction.DEBIT,
                  deal.interest),
                 (cash, Direction.CREDIT, deal.principal),
                 (cash, Direction.CREDIT, deal.interest)]  # fmt: skip
    _post(
        db,
        key=f"treasury-mature:{deal.deal_number}",
        currency=deal.currency,
        memo=f"Maturity {deal.deal_number}",
        lines=lines,
        actor_id=actor_id,
        today=today,
    )
    deal.status, deal.matured_by, deal.closed_at = DealStatus.MATURED.value, actor_id, now
    db.flush()
    _audit(db, actor_id, "treasury.deal_matured", "treasury_deal", deal.id,
           deal_number=deal.deal_number, interest=deal.interest)  # fmt: skip
    return deal


# --- FX desk ---------------------------------------------------------------------------------


def fx_limit(db: Session, currency: str) -> int:
    row = db.get(TreasuryFxLimit, currency)
    return row.limit_usd if row else DEFAULT_FX_LIMIT_USD


def set_fx_limit(db: Session, currency: str, limit_usd: int, actor_id: uuid.UUID | None):
    currency = currency.strip().upper()
    if not rates.supported(currency):
        raise BusinessRuleViolation(f"{currency} is not a supported currency.")
    if not 0 <= limit_usd <= 1_000_000_000:
        raise BusinessRuleViolation("A position limit is between 0 and US$1bn.")
    row = db.get(TreasuryFxLimit, currency)
    before = row.limit_usd if row else DEFAULT_FX_LIMIT_USD
    if row is None:
        row = TreasuryFxLimit(currency=currency, limit_usd=limit_usd, changed_by=actor_id)
        db.add(row)
    else:
        row.limit_usd, row.changed_by, row.updated_at = limit_usd, actor_id, func.now()
    db.flush()
    metadata = {"currency": currency, "from": before, "to": limit_usd}
    record_audit_event(
        db,
        actor_id=actor_id,
        action="treasury.fx_limit_set",
        entity_type="treasury_fx_limit",
        entity_id=None,
        metadata=metadata,
    )
    return row


def fx_desk(db: Session, as_of: date) -> dict[str, Any]:
    """The open currency positions against their limits (US dollars, by absolute value)."""
    book = fx.positions(db, as_of)
    rows = []
    for p in book["positions"]:
        if p["currency"] == rates.BASE:
            continue  # positions are valued in US dollars; the dollar is the base
        limit = fx_limit(db, p["currency"])
        value = abs(p["value_usd"]) // 100  # whole dollars
        rows.append({**p, "limit_usd": limit,
                     "utilisation_bps": value * 10_000 // limit if limit else None,
                     "over_limit": value > limit, "excess_usd": max(value - limit, 0)})  # fmt: skip
    return {"as_of": as_of, "positions": rows, "total_value_usd": book["total_value_usd"]}


def position(db: Session, currency: str, as_of: date) -> dict[str, Any]:
    currency = currency.strip().upper()
    row = next((p for p in fx_desk(db, as_of)["positions"] if p["currency"] == currency), None)
    if row is None:
        return {"currency": currency, "position": 0, "value_usd": 0,
                "limit_usd": fx_limit(db, currency), "utilisation_bps": 0, "over_limit": False,
                "excess_usd": 0}  # fmt: skip
    return row


def book_fx_trade(
    db: Session, *, counterparty: TreasuryCounterparty, sell_currency: str, buy_currency: str,
    sell_amount: int, booked_by: uuid.UUID, today: date | None = None,
) -> TreasuryFxTrade:  # fmt: skip
    """The FX desk sells a currency it is long in to a counterparty at the day's mid rate.
    A trade may only reduce a long position: it cannot open or reverse one."""
    today = today or datetime.now(UTC).date()
    sell_currency, buy_currency = sell_currency.strip().upper(), buy_currency.strip().upper()
    long = ledger.balance(db, fx.position_account(db, sell_currency))
    if sell_amount > long:
        raise BusinessRuleViolation(
            f"The desk is long {long} {sell_currency}: a trade can only reduce the position.",
            {"rule": "squares_only", "position": long},
        )  # fmt: skip
    quote = fx.quote(db, sell_currency, buy_currency, sell_amount, today, margin_bps=0)
    _check_bought(db, buy_currency, quote["buy_amount"])
    number = f"FXT-{db.execute(FX_TRADE_SEQUENCE.next_value()).scalar_one():07d}"
    trade = TreasuryFxTrade(
        trade_number=number, counterparty_id=counterparty.id, sell_currency=sell_currency,
        sell_amount=sell_amount, buy_currency=buy_currency, buy_amount=quote["buy_amount"],
        mid_rate=str(quote["mid_rate"]), trade_date=today, status=FxTradeStatus.BOOKED.value,
        booked_by=booked_by,
    )  # fmt: skip
    db.add(trade)
    db.flush()
    _audit(db, booked_by, "treasury.fx_trade_booked", "treasury_fx_trade", trade.id,
           trade_number=number, sell=f"{sell_amount} {sell_currency}",
           buy=f"{trade.buy_amount} {buy_currency}")  # fmt: skip
    return trade


def _check_bought(db: Session, currency: str, amount: int) -> None:
    """The bought side may only close a short, never open or grow a position, except in US
    dollars, the base the positions are valued in (PR #30 review)."""
    if currency == rates.BASE:
        return
    short = -ledger.balance(db, fx.position_account(db, currency))
    if amount > short:
        raise BusinessRuleViolation(
            f"The desk is short {max(short, 0)} {currency}: buying {amount} would open or "
            "grow a position. Buy US dollars, or no more than the short.",
            {"rule": "squares_only", "position": -short},
        )  # fmt: skip


def get_fx_trade(db: Session, trade_id: uuid.UUID, *, for_update: bool = False):
    query = select(TreasuryFxTrade).where(TreasuryFxTrade.id == trade_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    trade = db.execute(query).scalar_one_or_none()
    if trade is None:
        raise NotFoundError("FX trade not found.")
    return trade


def confirm_fx_trade(
    db: Session, trade: TreasuryFxTrade, actor_id: uuid.UUID, *, now: datetime | None = None
) -> TreasuryFxTrade:
    """Back office confirms (not the dealer) and settles both legs through the cash and
    position accounts, one balanced entry per currency."""
    now = now or datetime.now(UTC)
    trade = get_fx_trade(db, trade.id, for_update=True)
    if trade.status != FxTradeStatus.BOOKED:
        raise ConflictError(f"{trade.trade_number} is {trade.status}.")
    if actor_id == trade.booked_by:
        raise BusinessRuleViolation("Four-eyes rule: the dealer cannot confirm their own trade.",
                                    {"rule": "four_eyes"})  # fmt: skip
    _lock(db, fx.position_account(db, trade.sell_currency),
          fx.position_account(db, trade.buy_currency),
          ledger.cash_account(db, trade.sell_currency),
          ledger.cash_account(db, trade.buy_currency))  # fmt: skip
    long = ledger.balance(db, fx.position_account(db, trade.sell_currency))
    if trade.sell_amount > long:
        raise BusinessRuleViolation(
            f"The desk is now long only {long} {trade.sell_currency}; cancel the trade.",
            {"rule": "squares_only", "position": long},
        )  # fmt: skip
    _check_bought(db, trade.buy_currency, trade.buy_amount)
    if trade.sell_amount > _cash(db, trade.sell_currency):
        raise BusinessRuleViolation(f"Not enough {trade.sell_currency} cash to deliver.",
                                    {"rule": "cash"})  # fmt: skip
    today = now.date()
    _post(db, key=f"treasury-fx-sell:{trade.trade_number}", currency=trade.sell_currency,
          memo=f"FX desk {trade.trade_number}: sold",
          lines=[(fx.position_account(db, trade.sell_currency), Direction.DEBIT,
                  trade.sell_amount),
                 (ledger.cash_account(db, trade.sell_currency), Direction.CREDIT,
                  trade.sell_amount)], actor_id=actor_id, today=today)  # fmt: skip
    _post(db, key=f"treasury-fx-buy:{trade.trade_number}", currency=trade.buy_currency,
          memo=f"FX desk {trade.trade_number}: bought",
          lines=[(ledger.cash_account(db, trade.buy_currency), Direction.DEBIT,
                  trade.buy_amount),
                 (fx.position_account(db, trade.buy_currency), Direction.CREDIT,
                  trade.buy_amount)], actor_id=actor_id, today=today)  # fmt: skip
    trade.status, trade.confirmed_by, trade.settled_at = FxTradeStatus.SETTLED.value, actor_id, now
    db.flush()
    _audit(db, actor_id, "treasury.fx_trade_settled", "treasury_fx_trade", trade.id,
           trade_number=trade.trade_number)  # fmt: skip
    return trade


def cancel_fx_trade(db: Session, trade: TreasuryFxTrade, actor_id: uuid.UUID | None):
    trade = get_fx_trade(db, trade.id, for_update=True)
    if trade.status != FxTradeStatus.BOOKED:
        raise ConflictError(f"{trade.trade_number} is {trade.status}.")
    trade.status = FxTradeStatus.CANCELLED.value
    db.flush()
    _audit(db, actor_id, "treasury.fx_trade_cancelled", "treasury_fx_trade", trade.id,
           trade_number=trade.trade_number)  # fmt: skip
    return trade


def reference_rate(currency: str) -> int:
    return REFERENCE_RATES_BPS.get(currency, DEFAULT_REFERENCE_BPS)


def deal_profile(db: Session, deal: TreasuryDeal, today: date) -> dict[str, Any]:
    """What back office checks before confirming a booked deal (Phase 40): the rate against
    the currency's reference rate (the deviation counted against the bank), the tenor, the
    counterparty's rating and how much of its limit the deal uses, liquidity coverage after a
    placement, and other deals with the same terms booked the same day."""
    counterparty = get_counterparty(db, deal.counterparty_id)
    placement = deal.kind == DealKind.PLACEMENT
    reference = reference_rate(deal.currency)
    # Lending below the market or borrowing above it costs the bank.
    against = reference - deal.rate_bps if placement else deal.rate_bps - reference
    utilisation = 0
    coverage_after = None
    if placement:
        exposure = exposure_usd(db, counterparty, today)  # includes this booked deal
        utilisation = exposure * 10_000 // counterparty.limit_usd if counterparty.limit_usd else 0
        row = liquidity(db, today, deal.currency)["currencies"][0]
        liquid = row["liquid"] - deal.principal
        if deal.maturity_date <= today + timedelta(days=HORIZON_DAYS):
            liquid += deal.principal + deal.interest
        coverage_after = _coverage(liquid, row["stressed_outflow"])
    duplicates = db.execute(
        select(func.count()).select_from(TreasuryDeal).where(
            TreasuryDeal.id != deal.id, TreasuryDeal.counterparty_id == deal.counterparty_id,
            TreasuryDeal.kind == deal.kind, TreasuryDeal.currency == deal.currency,
            TreasuryDeal.principal == deal.principal, TreasuryDeal.value_date == deal.value_date,
            # The same terms: rate and maturity too (PR #31 review).
            TreasuryDeal.rate_bps == deal.rate_bps,
            TreasuryDeal.maturity_date == deal.maturity_date,
            TreasuryDeal.status.in_([DealStatus.BOOKED, DealStatus.SETTLED]),
        )
    ).scalar_one()  # fmt: skip
    return {
        "kind": deal.kind, "currency": deal.currency, "rate_bps": deal.rate_bps,
        "reference_rate_bps": reference, "rate_against_bank_bps": against,
        "tenor_days": (deal.maturity_date - deal.value_date).days,
        "rating": counterparty.rating, "limit_utilisation_bps": utilisation,
        "coverage_after_bps": coverage_after, "same_day_duplicates": duplicates,
    }  # fmt: skip


def summary(db: Session) -> dict[str, Any]:
    def count(model, *where) -> int:
        return db.execute(select(func.count()).select_from(model).where(*where)).scalar_one()

    return {
        "booked": count(TreasuryDeal, TreasuryDeal.status == DealStatus.BOOKED),
        "placements": count(TreasuryDeal, TreasuryDeal.status == DealStatus.SETTLED,
                            TreasuryDeal.kind == DealKind.PLACEMENT),
        "borrowings": count(TreasuryDeal, TreasuryDeal.status == DealStatus.SETTLED,
                            TreasuryDeal.kind == DealKind.BORROWING),
        "fx_trades_booked": count(TreasuryFxTrade, TreasuryFxTrade.status == FxTradeStatus.BOOKED),
    }  # fmt: skip
