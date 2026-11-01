"""Wealth and investments services (Phase 43): securities and their prices, suitability
profiles, portfolios in custody, orders and income distributions."""

import math
import uuid
import zlib
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.core.money import minor_unit_exponent
from app.modules.accounts import service as accounts
from app.modules.accounts.models import Account, AccountStatus
from app.modules.customers.models import Customer, KycStatus
from app.modules.fx import service as fx
from app.modules.ledger import service as ledger
from app.modules.ledger.models import Direction, LedgerAccount, LedgerAccountType
from app.modules.wealth.models import (
    DISTRIBUTION_SEQUENCE,
    ORDER_SEQUENCE,
    PORTFOLIO_SEQUENCE,
    Holding,
    IncomeDistribution,
    InvestmentOrder,
    InvestmentProfile,
    Knowledge,
    LossCapacity,
    Objective,
    OrderStatus,
    Portfolio,
    PortfolioStatus,
    Security,
)

# The synthetic securities (names invented): code, name, asset class, currency, risk level
# (1-7), complex, base price (major units), drift and swing (basis points a year), income
# (basis points a year).
# fmt: off
SECURITIES = [
    ("AGB-MMF-USD", "Atlas Liquidity Fund (USD)", "money_market", "USD", 1, False, "100.00",
     450, 5, 450),
    ("AGB-GOVT-2031", "Synthetic Treasury 3.50% 2031", "bond", "USD", 2, False, "100.00",
     0, 150, 350),
    ("AGB-CORP-2029", "Meridian Utilities 4.80% 2029", "bond", "EUR", 3, False, "100.00",
     0, 300, 480),
    ("AGB-BAL-FUND", "Atlas Balanced Fund", "fund", "GBP", 4, False, "250.00", 500, 600, 200),
    ("AGB-GLOBAL-EQ", "Atlas Global Equity Fund", "fund", "USD", 5, False, "180.00",
     800, 1200, 150),
    ("AGB-EM-EQ", "Atlas Emerging Markets Fund", "fund", "USD", 6, False, "95.00",
     1000, 2200, 200),
    ("EQ-NORTHWIND", "Northwind Logistics plc", "equity", "GBP", 6, False, "42.50",
     900, 2000, 300),
    ("EQ-HELIOS", "Helios Renewables AG", "equity", "EUR", 6, False, "78.20", 1200, 2500, 100),
    ("SN-AUTOCALL-28", "Atlas Autocall Note 2028", "structured", "USD", 6, True, "100.00",
     600, 1500, 700),
    ("SN-DIGITAL-TRK", "Synthetic Digital Asset Tracker", "structured", "USD", 7, True, "50.00",
     1500, 4000, 0),
]
# fmt: on
PRICE_ANCHOR = date(2026, 1, 1)
SWING_PERIOD_DAYS = 91
PROFILE_VALID_DAYS = 365
CONCENTRATION_LIMIT_PCT = 40  # one security's share of investable assets after a buy
FEE_BPS = 25  # dealing fee, at least one major unit of the portfolio's currency
OBJECTIVE_RISK = {"preservation": 2, "income": 3, "balanced": 4, "growth": 6}


def _audit(db, actor_id, action: str, entity_type: str, entity_id, **metadata) -> None:
    record_audit_event(db, actor_id=actor_id, action=action, entity_type=entity_type,
                       entity_id=entity_id, metadata=metadata)  # fmt: skip


def _today(today: date | None) -> date:
    return today or datetime.now(UTC).date()


# --- Securities and prices --------------------------------------------------------------------


def ensure_securities(db: Session) -> int:
    """Create the synthetic securities that are missing; returns how many were added."""
    existing = set(db.execute(select(Security.code)).scalars())
    added = 0
    for code, name, asset_class, ccy, risk, is_complex, price, drift, swing, income in SECURITIES:
        if code in existing:
            continue
        db.add(Security(
            code=code, name=name, asset_class=asset_class, currency=ccy, risk_level=risk,
            complex=is_complex,
            base_price=int(Decimal(price) * 10 ** minor_unit_exponent(ccy)),
            drift_bps=drift, volatility_bps=swing, income_bps=income,
        ))  # fmt: skip
        added += 1
    db.flush()
    return added


def price_on(security: Security, day: date) -> int:
    """The security's price on a day, in minor units of its currency: a straight-line drift
    from the anchor date times a seasonal swing whose phase depends on the code."""
    t = (day - PRICE_ANCHOR).days
    phase = (zlib.crc32(security.code.encode()) % 360) * math.pi / 180
    drift = 1 + security.drift_bps / 10_000 * t / 365
    swing = 1 + security.volatility_bps / 10_000 * math.sin(2 * math.pi * t / SWING_PERIOD_DAYS
                                                            + phase)  # fmt: skip
    return max(1, round(security.base_price * max(drift, 0.05) * swing))


def find_security(db: Session, code: str) -> Security | None:
    return db.execute(
        select(Security).where(Security.code == code.strip().upper())
    ).scalar_one_or_none()


def get_security(db: Session, security_id: uuid.UUID) -> Security:
    security = db.get(Security, security_id)
    if security is None:
        raise NotFoundError("Security not found.")
    return security


def convert(db: Session, amount: int, from_ccy: str, to_ccy: str, day: date) -> int:
    """`amount` minor units of one currency in the other at the day's mid rates, rounded
    down."""
    if from_ccy == to_ccy:
        return amount
    major = Decimal(amount) / Decimal(10) ** minor_unit_exponent(from_ccy)
    usd = major / fx.rate(db, from_ccy, day)
    target = usd * fx.rate(db, to_ccy, day) * Decimal(10) ** minor_unit_exponent(to_ccy)
    return int(target.to_integral_value(rounding=ROUND_DOWN))


# --- Suitability profiles ---------------------------------------------------------------------


def risk_profile(objective: str, horizon_years: int, knowledge: str, loss_capacity: str) -> int:
    """The risk profile (1-7) the answers allow: the objective's level, capped by a short
    horizon, a limited capacity for loss and no investment knowledge."""
    level = OBJECTIVE_RISK[objective]
    if horizon_years < 3:
        level = min(level, 3)
    elif horizon_years < 5:
        level = min(level, 5)
    if loss_capacity == LossCapacity.LOW:
        level = min(level, 3)
    elif loss_capacity == LossCapacity.MEDIUM:
        level = min(level, 5)
    if knowledge == Knowledge.NONE:
        level = min(level, 4)
    if (objective == Objective.GROWTH and horizon_years >= 10
            and loss_capacity == LossCapacity.HIGH
            and knowledge in (Knowledge.INFORMED, Knowledge.EXPERT)):  # fmt: skip
        level = 7
    return level


def record_profile(
    db: Session, customer: Customer, *, objective: str, horizon_years: int, knowledge: str,
    loss_capacity: str, assessed_by: uuid.UUID | None, today: date | None = None,
) -> InvestmentProfile:  # fmt: skip
    """Record a suitability assessment; it is the customer's profile for a year."""
    today = _today(today)
    if customer.kyc_status != KycStatus.VERIFIED:
        raise BusinessRuleViolation("The customer's KYC is not verified.",
                                    {"rule": "kyc_not_verified"})  # fmt: skip
    try:
        objective, knowledge = Objective(objective).value, Knowledge(knowledge).value
        loss_capacity = LossCapacity(loss_capacity).value
    except ValueError as exc:
        raise BusinessRuleViolation(str(exc), {"rule": "invalid_answer"}) from exc
    if not 0 <= horizon_years <= 50:
        raise BusinessRuleViolation("The horizon is 0 to 50 years.", {"rule": "invalid_answer"})
    profile = InvestmentProfile(
        customer_id=customer.id, objective=objective, horizon_years=horizon_years,
        knowledge=knowledge, loss_capacity=loss_capacity,
        risk_profile=risk_profile(objective, horizon_years, knowledge, loss_capacity),
        assessed_by=assessed_by, assessed_on=today,
        expires_on=today + timedelta(days=PROFILE_VALID_DAYS),
    )  # fmt: skip
    db.add(profile)
    db.flush()
    _audit(db, assessed_by, "wealth.profile_recorded", "investment_profile", profile.id,
           customer_id=str(customer.id), risk_profile=profile.risk_profile)  # fmt: skip
    return profile


def current_profile(db: Session, customer_id: uuid.UUID, today: date) -> InvestmentProfile | None:
    """The latest assessment, if it has not expired."""
    profile = db.execute(
        select(InvestmentProfile).where(InvestmentProfile.customer_id == customer_id)
        .order_by(InvestmentProfile.assessed_on.desc(), InvestmentProfile.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()  # fmt: skip
    return profile if profile is not None and profile.expires_on > today else None


# --- Portfolios -------------------------------------------------------------------------------


def open_portfolio(db: Session, account: Account, opened_by: uuid.UUID | None) -> Portfolio:
    """A custody account for the account's holder; the account pays and receives."""
    if account.status != AccountStatus.OPEN:
        raise BusinessRuleViolation(f"The account is {account.status}.")
    customer = db.get(Customer, account.customer_id)
    if customer.kyc_status != KycStatus.VERIFIED:
        raise BusinessRuleViolation("The customer's KYC is not verified.",
                                    {"rule": "kyc_not_verified"})  # fmt: skip
    number = f"INV-{db.execute(PORTFOLIO_SEQUENCE.next_value()).scalar_one():08d}"
    portfolio = Portfolio(portfolio_number=number, customer_id=customer.id,
                          cash_account_id=account.id, currency=account.currency,
                          status=PortfolioStatus.OPEN.value, opened_by=opened_by)  # fmt: skip
    db.add(portfolio)
    db.flush()
    _audit(db, opened_by, "wealth.portfolio_opened", "investment_portfolio", portfolio.id,
           portfolio_number=number, account_number=account.account_number)  # fmt: skip
    return portfolio


def find_portfolio(db: Session, number: str) -> Portfolio | None:
    return db.execute(
        select(Portfolio).where(Portfolio.portfolio_number == number.strip().upper())
    ).scalar_one_or_none()


def get_portfolio(db: Session, portfolio_id: uuid.UUID, *, for_update: bool = False):
    query = select(Portfolio).where(Portfolio.id == portfolio_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    portfolio = db.execute(query).scalar_one_or_none()
    if portfolio is None:
        raise NotFoundError("Portfolio not found.")
    return portfolio


def holdings(db: Session, portfolio: Portfolio) -> list[tuple[Holding, Security]]:
    return list(db.execute(
        select(Holding, Security).join(Security, Security.id == Holding.security_id)
        .where(Holding.portfolio_id == portfolio.id, Holding.units > 0)
        .order_by(Security.code)
    ).tuples())  # fmt: skip


def _cash_balance(db: Session, account: Account) -> int:
    return ledger.balance(db, accounts._ledger_account(db, account))


def valuation(db: Session, portfolio: Portfolio, today: date | None = None) -> dict[str, Any]:
    """Each holding at the day's price in the portfolio's currency, with its gain on cost."""
    today = _today(today)
    lines, total, cost = [], 0, 0
    for holding, security in holdings(db, portfolio):
        price = price_on(security, today)
        value = convert(db, holding.units * price, security.currency, portfolio.currency, today)
        lines.append({"security_code": security.code, "name": security.name,
                      "asset_class": security.asset_class, "risk_level": security.risk_level,
                      "units": holding.units, "price": price,
                      "price_currency": security.currency, "value": value, "cost": holding.cost,
                      "gain": value - holding.cost})  # fmt: skip
        total, cost = total + value, cost + holding.cost
    account = accounts.get_account(db, portfolio.cash_account_id)
    return {"portfolio_number": portfolio.portfolio_number, "currency": portfolio.currency,
            "as_of": today.isoformat(), "holdings": lines, "value": total, "cost": cost,
            "gain": total - cost, "cash": _cash_balance(db, account)}  # fmt: skip


def close_portfolio(db: Session, portfolio: Portfolio, actor_id: uuid.UUID | None) -> Portfolio:
    portfolio = get_portfolio(db, portfolio.id, for_update=True)
    if portfolio.status != PortfolioStatus.OPEN:
        raise ConflictError(f"{portfolio.portfolio_number} is {portfolio.status}.")
    if holdings(db, portfolio):
        raise BusinessRuleViolation("Sell every holding before closing the portfolio.",
                                    {"rule": "holdings_remain"})  # fmt: skip
    pending = db.execute(
        select(func.count()).select_from(InvestmentOrder).where(
            InvestmentOrder.portfolio_id == portfolio.id,
            InvestmentOrder.status.in_([OrderStatus.AWAITING_APPROVAL, OrderStatus.PLACED]))
    ).scalar_one()  # fmt: skip
    if pending:
        raise BusinessRuleViolation("An order is still waiting to be decided or released.",
                                    {"rule": "order_pending"})  # fmt: skip
    portfolio.status, portfolio.closed_at = PortfolioStatus.CLOSED.value, datetime.now(UTC)
    db.flush()
    _audit(db, actor_id, "wealth.portfolio_closed", "investment_portfolio", portfolio.id,
           portfolio_number=portfolio.portfolio_number)  # fmt: skip
    return portfolio


def open_portfolio_for_account(db: Session, account_id: uuid.UUID) -> str | None:
    """An open portfolio the account pays for: it cannot be closed while one exists."""
    return db.execute(
        select(Portfolio.portfolio_number).where(Portfolio.cash_account_id == account_id,
                                                 Portfolio.status == PortfolioStatus.OPEN)
    ).scalars().first()  # fmt: skip


# --- Orders -----------------------------------------------------------------------------------


def fee_for(amount: int, currency: str) -> int:
    return max(amount * FEE_BPS // 10_000, 10 ** minor_unit_exponent(currency))


def suitability(db: Session, portfolio: Portfolio, security: Security, amount: int,
                today: date) -> list[dict[str, str]]:  # fmt: skip
    """Why buying `amount` (portfolio currency) of the security would be unsuitable; empty
    when it is suitable. Without a current profile nothing can be bought."""
    profile = current_profile(db, portfolio.customer_id, today)
    if profile is None:
        raise BusinessRuleViolation(
            "The customer has no current investment profile: assess suitability first.",
            {"rule": "no_profile"},
        )
    reasons = []
    if security.risk_level > profile.risk_profile:
        reasons.append({"code": "risk_above_profile",
                        "message": f"Risk level {security.risk_level} is above the customer's "
                                   f"profile of {profile.risk_profile}."})  # fmt: skip
    if security.complex and profile.knowledge not in (Knowledge.INFORMED, Knowledge.EXPERT):
        reasons.append({"code": "complex_product",
                        "message": "A complex product, and the customer's knowledge is "
                                   f"{profile.knowledge}."})  # fmt: skip
    value = valuation(db, portfolio, today)
    investable = value["value"] + max(value["cash"], 0)
    held = next((h["value"] for h in value["holdings"] if h["security_code"] == security.code), 0)
    if investable > 0 and (held + amount) * 100 > investable * CONCENTRATION_LIMIT_PCT:
        share = (held + amount) * 100 // investable
        limit = CONCENTRATION_LIMIT_PCT
        reasons.append({"code": "concentration",
                        "message": f"{security.code} would be {share} % of the customer's "
                                   f"investable assets (limit {limit} %)."})  # fmt: skip
    return reasons


def _holding(db: Session, portfolio: Portfolio, security: Security) -> Holding:
    holding = db.execute(
        select(Holding).where(Holding.portfolio_id == portfolio.id,
                              Holding.security_id == security.id)
        .with_for_update()
    ).scalar_one_or_none()  # fmt: skip
    if holding is None:
        holding = Holding(portfolio_id=portfolio.id, security_id=security.id, units=0, cost=0)
        db.add(holding)
        db.flush()
    return holding


def fees_account(db: Session, currency: str) -> LedgerAccount:
    return ledger.ensure_ledger_account(
        db, code=f"WEALTH-FEES-{currency}", name=f"Investment dealing fees ({currency})",
        account_type=LedgerAccountType.INCOME, currency=currency,
    )  # fmt: skip


def _price(db: Session, order: InvestmentOrder, portfolio: Portfolio, security: Security,
           today: date) -> None:  # fmt: skip
    order.price = price_on(security, today)
    order.amount = convert(db, order.units * order.price, security.currency, portfolio.currency,
                           today)  # fmt: skip
    order.fee = fee_for(order.amount, portfolio.currency)


def _execute(db: Session, order: InvestmentOrder, actor_id: uuid.UUID | None,
             today: date) -> None:  # fmt: skip
    """Settle the order at the day's price: cash through the ledger, units in custody."""
    portfolio = get_portfolio(db, order.portfolio_id, for_update=True)
    if portfolio.status != PortfolioStatus.OPEN:
        raise BusinessRuleViolation(f"{portfolio.portfolio_number} is {portfolio.status}.")
    security = get_security(db, order.security_id)
    account = accounts.get_account(db, portfolio.cash_account_id, for_update=True)
    if account.status != AccountStatus.OPEN:
        raise BusinessRuleViolation(f"The cash account is {account.status}.")
    holding = _holding(db, portfolio, security)
    _price(db, order, portfolio, security, today)
    cash, fees = ledger.cash_account(db, portfolio.currency), fees_account(db, portfolio.currency)
    memo = f"{order.order_number} {order.side} {order.units} {security.code}"
    if order.side == "buy":
        if order.amount + order.fee > _cash_balance(db, account):
            raise BusinessRuleViolation("Not enough cash in the account for the order and its fee.",
                                        {"rule": "insufficient_funds"})  # fmt: skip
        lines = [
            (account.ledger_account_id, Direction.DEBIT, order.amount + order.fee),
            (cash.id, Direction.CREDIT, order.amount),
            (fees.id, Direction.CREDIT, order.fee),
        ]
        holding.units += order.units
        holding.cost += order.amount
    else:
        if order.units > holding.units:
            raise BusinessRuleViolation(f"Only {holding.units} units of {security.code} are held.",
                                        {"rule": "units_not_held"})  # fmt: skip
        if order.fee > order.amount:
            raise BusinessRuleViolation("The sale would not cover its fee.",
                                        {"rule": "fee_above_proceeds"})  # fmt: skip
        lines = [
            (cash.id, Direction.DEBIT, order.amount),
            (account.ledger_account_id, Direction.CREDIT, order.amount - order.fee),
            (fees.id, Direction.CREDIT, order.fee),
        ]
        holding.cost -= holding.cost * order.units // holding.units
        holding.units -= order.units
    ledger.post_entry(
        db, idempotency_key=f"wealth-order:{order.order_number}", currency=portfolio.currency,
        description=memo, source="wealth",
        lines=[ledger.LineSpec(acc, direction, amount, memo[:200])
               for acc, direction, amount in lines if amount],
        actor_id=actor_id, effective_date=today,
    )  # fmt: skip
    order.status, order.executed_on = OrderStatus.EXECUTED.value, today
    db.flush()


def place_order(
    db: Session, *, portfolio: Portfolio, security: Security, side: str, units: int,
    placed_by: uuid.UUID, today: date | None = None, execute: bool = True,
) -> InvestmentOrder:  # fmt: skip
    """A buy or sell order. A sell, or a suitable buy, is executed at once at the day's price
    (or, with `execute=False`, placed for the dealing desk to release); an unsuitable buy
    waits for someone else's approval."""
    today = _today(today)
    if side not in ("buy", "sell"):
        raise BusinessRuleViolation("The side is buy or sell.")
    if units <= 0:
        raise BusinessRuleViolation("The units must be a positive whole number.")
    # Locked, so an order cannot be placed while the portfolio is being closed (PR #34
    # review).
    portfolio = get_portfolio(db, portfolio.id, for_update=True)
    if portfolio.status != PortfolioStatus.OPEN:
        raise BusinessRuleViolation(f"{portfolio.portfolio_number} is {portfolio.status}.")
    if not security.active:
        raise BusinessRuleViolation(f"{security.code} is not available.")
    number = f"ORD-{db.execute(ORDER_SEQUENCE.next_value()).scalar_one():08d}"
    order = InvestmentOrder(order_number=number, portfolio_id=portfolio.id,
                            security_id=security.id, side=side, units=units, price=0, amount=0,
                            fee=0, status=OrderStatus.AWAITING_APPROVAL.value, suitable=True,
                            reasons=[], placed_by=placed_by)  # fmt: skip
    _price(db, order, portfolio, security, today)
    if side == "buy":
        order.reasons = suitability(db, portfolio, security, order.amount, today)
        order.suitable = not order.reasons
        account = accounts.get_account(db, portfolio.cash_account_id)
        if order.amount + order.fee > _cash_balance(db, account):
            raise BusinessRuleViolation("Not enough cash in the account for the order and its fee.",
                                        {"rule": "insufficient_funds"})  # fmt: skip
    db.add(order)
    db.flush()
    if order.suitable and execute:
        _execute(db, order, placed_by, today)
    elif order.suitable:
        order.status = OrderStatus.PLACED.value
        db.flush()
    _audit(db, placed_by, "wealth.order_placed", "investment_order", order.id,
           order_number=number, side=side, units=units, security=security.code,
           suitable=order.suitable, status=order.status)  # fmt: skip
    return order


def get_order(db: Session, order_id: uuid.UUID, *, for_update: bool = False) -> InvestmentOrder:
    query = select(InvestmentOrder).where(InvestmentOrder.id == order_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    order = db.execute(query).scalar_one_or_none()
    if order is None:
        raise NotFoundError("Order not found.")
    return order


def find_order(db: Session, number: str) -> InvestmentOrder | None:
    return db.execute(
        select(InvestmentOrder).where(InvestmentOrder.order_number == number.strip().upper())
    ).scalar_one_or_none()


def _decide(db: Session, order: InvestmentOrder, actor_id: uuid.UUID,
            *statuses: OrderStatus) -> InvestmentOrder:  # fmt: skip
    order = get_order(db, order.id, for_update=True)
    if order.status not in statuses:
        raise ConflictError(f"{order.order_number} is {order.status}.")
    if actor_id == order.placed_by:
        raise BusinessRuleViolation("Four-eyes rule: the adviser who placed the order cannot "
                                    "decide or release it.", {"rule": "four_eyes"})  # fmt: skip
    return order


def approve_order(db: Session, order: InvestmentOrder, actor_id: uuid.UUID, note: str,
                  today: date | None = None,
                  now: datetime | None = None) -> InvestmentOrder:  # fmt: skip
    """Approve an unsuitable order at the client's insistence, or a placed one: executed at
    the day's price."""
    order = _decide(db, order, actor_id, OrderStatus.AWAITING_APPROVAL, OrderStatus.PLACED)
    order.approved_by, order.note = actor_id, (note.strip() or "Insistent client")[:200]
    order.decided_at = now or datetime.now(UTC)
    _execute(db, order, actor_id, _today(today))
    _audit(db, actor_id, "wealth.order_approved", "investment_order", order.id,
           order_number=order.order_number, note=order.note)  # fmt: skip
    return order


def release_order(db: Session, order: InvestmentOrder, actor_id: uuid.UUID,
                  today: date | None = None) -> InvestmentOrder:  # fmt: skip
    """The dealing desk executes a placed (suitable) order at the day's price; not the
    adviser who placed it."""
    order = _decide(db, order, actor_id, OrderStatus.PLACED)
    today = _today(today)
    if order.side == "buy":
        # Checked again against today's holdings, prices and profile: orders placed together
        # can add up to an unsuitable position (PR #34 review). The order stays placed, for
        # a manager (wealth:approve) to approve or reject.
        portfolio = get_portfolio(db, order.portfolio_id, for_update=True)
        security = get_security(db, order.security_id)
        _price(db, order, portfolio, security, today)
        reasons = suitability(db, portfolio, security, order.amount, today)
        if reasons:
            raise BusinessRuleViolation(
                f"{order.order_number} is no longer suitable: "
                + " ".join(r["message"] for r in reasons)
                + " A manager must approve or reject it.",
                {"rule": "now_unsuitable", "reasons": [r["code"] for r in reasons]},
            )
    order.approved_by, order.decided_at = actor_id, datetime.now(UTC)
    _execute(db, order, actor_id, today)
    _audit(db, actor_id, "wealth.order_released", "investment_order", order.id,
           order_number=order.order_number)  # fmt: skip
    return order


def reject_order(db: Session, order: InvestmentOrder, actor_id: uuid.UUID, note: str,
                 now: datetime | None = None) -> InvestmentOrder:  # fmt: skip
    """Reject an unsuitable order, or cancel a placed one."""
    order = _decide(db, order, actor_id, OrderStatus.AWAITING_APPROVAL, OrderStatus.PLACED)
    order.status, order.note = OrderStatus.REJECTED.value, (note.strip() or "Unsuitable")[:200]
    order.decided_at = now or datetime.now(UTC)
    db.flush()
    _audit(db, actor_id, "wealth.order_rejected", "investment_order", order.id,
           order_number=order.order_number, note=order.note)  # fmt: skip
    return order


# --- Income (custody) -------------------------------------------------------------------------


def income_per_unit(security: Security, day: date) -> int:
    """Half a year's income on one unit at the day's price, in minor units, rounded down."""
    return price_on(security, day) * security.income_bps // 20_000


def distribute_income(db: Session, security: Security, paid_by: uuid.UUID | None,
                      today: date | None = None) -> IncomeDistribution:  # fmt: skip
    """Pay half a year's income to every holder on the record date, into each portfolio's
    cash account, converted to its currency; once per security and date."""
    today = _today(today)
    if security.income_bps == 0:
        raise BusinessRuleViolation(f"{security.code} pays no income.", {"rule": "no_income"})
    exists = db.execute(
        select(IncomeDistribution.distribution_number).where(
            IncomeDistribution.security_id == security.id, IncomeDistribution.record_date == today)
    ).scalar_one_or_none()  # fmt: skip
    if exists:
        raise ConflictError(f"{security.code} income for {today} was paid ({exists}).")
    per_unit = income_per_unit(security, today)
    rows = db.execute(
        select(Holding, Portfolio).join(Portfolio, Portfolio.id == Holding.portfolio_id)
        .where(Holding.security_id == security.id, Holding.units > 0,
               Portfolio.status == PortfolioStatus.OPEN)
        .order_by(Portfolio.portfolio_number)
    ).tuples().all()  # fmt: skip
    payees = []
    for holding, portfolio in rows:
        account = accounts.get_account(db, portfolio.cash_account_id)
        if account.status != AccountStatus.OPEN:
            # Refused before anything is recorded, rather than skipped: the record date
            # could not be paid again later (PR #34 review).
            raise BusinessRuleViolation(
                f"{portfolio.portfolio_number}'s cash account is {account.status}: pay "
                f"{security.code}'s income once every holder's account is open.",
                {"rule": "holder_account_not_open", "portfolio_number": portfolio.portfolio_number},
            )
        payees.append((holding, portfolio, account))
    number = f"DIS-{db.execute(DISTRIBUTION_SEQUENCE.next_value()).scalar_one():07d}"
    distribution = IncomeDistribution(distribution_number=number, security_id=security.id,
                                      record_date=today, income_per_unit=per_unit, holders=0,
                                      paid_by=paid_by)  # fmt: skip
    db.add(distribution)
    db.flush()
    for holding, portfolio, account in payees:
        amount = convert(db, holding.units * per_unit, security.currency, portfolio.currency,
                         today)  # fmt: skip
        if amount <= 0:
            continue
        memo = f"{number} {security.code} income on {holding.units} units"
        ledger.post_entry(
            db, idempotency_key=f"wealth-income:{number}:{portfolio.portfolio_number}",
            currency=portfolio.currency, description=memo, source="wealth",
            lines=[ledger.LineSpec(ledger.cash_account(db, portfolio.currency).id,
                                   Direction.DEBIT, amount, memo),
                   ledger.LineSpec(account.ledger_account_id, Direction.CREDIT, amount, memo)],
            actor_id=paid_by, effective_date=today,
        )  # fmt: skip
        distribution.holders += 1
    db.flush()
    _audit(db, paid_by, "wealth.income_distributed", "income_distribution", distribution.id,
           distribution_number=number, security=security.code, holders=distribution.holders,
           income_per_unit=per_unit)  # fmt: skip
    return distribution


def order_profile(db: Session, order: InvestmentOrder, today: date) -> dict[str, Any]:
    """What a manager weighs before letting an unsuitable order go ahead at the client's
    insistence (Phase 44): why it is unsuitable, how far the security's risk is above the
    customer's profile, the customer's answers, the order's share of their investable assets
    and the cash it leaves, whether they have held securities this risky before, and how
    often orders of theirs went ahead against advice, or were refused, in the last 90 days."""
    portfolio = get_portfolio(db, order.portfolio_id)
    security = get_security(db, order.security_id)
    profile = current_profile(db, portfolio.customer_id, today)
    value = valuation(db, portfolio, today)
    investable = value["value"] + max(value["cash"], 0)
    held = next((h["value"] for h in value["holdings"] if h["security_code"] == security.code), 0)
    portfolios = select(Portfolio.id).where(Portfolio.customer_id == portfolio.customer_id)
    others = (InvestmentOrder.portfolio_id.in_(portfolios), InvestmentOrder.id != order.id)
    experienced = db.execute(
        select(func.count()).select_from(InvestmentOrder)
        .join(Security, Security.id == InvestmentOrder.security_id)
        .where(*others, InvestmentOrder.side == "buy",
               InvestmentOrder.status == OrderStatus.EXECUTED,
               Security.risk_level >= security.risk_level)
    ).scalar_one()  # fmt: skip
    since = datetime.combine(today - timedelta(days=90), datetime.min.time(), tzinfo=UTC)
    against_advice = db.execute(
        select(InvestmentOrder.status).where(*others, InvestmentOrder.suitable.is_(False),
                                             InvestmentOrder.decided_at >= since)
    ).scalars().all()  # fmt: skip
    risk_profile = profile.risk_profile if profile else 0
    pct = (lambda part: part * 100 // investable) if investable > 0 else (lambda part: 0)
    if profile is None:
        reasons = ["no_profile"]
    elif order.side == "buy":
        # Today's reasons: a placed order may have become unsuitable since (PR #34 review).
        reasons = [r["code"] for r in suitability(db, portfolio, security, order.amount, today)]
    else:
        reasons = []
    return {
        "reasons": reasons, "security_code": security.code,
        "asset_class": security.asset_class, "risk_level": security.risk_level,
        "complex": security.complex, "risk_profile": risk_profile,
        "risk_gap": max(security.risk_level - risk_profile, 0),
        "objective": profile.objective if profile else "", "knowledge":
        profile.knowledge if profile else "none",
        "horizon_years": profile.horizon_years if profile else 0,
        "loss_capacity": profile.loss_capacity if profile else "low",
        "amount": order.amount, "currency": portfolio.currency,
        "share_after_pct": pct(held + order.amount),
        "cash_after_pct": pct(max(value["cash"], 0) - order.amount - order.fee),
        "experienced": experienced > 0,
        "insisted_90d": sum(s == OrderStatus.EXECUTED for s in against_advice),
        "refused_90d": sum(s == OrderStatus.REJECTED for s in against_advice),
    }  # fmt: skip


def summary(db: Session) -> dict[str, Any]:
    def count(model, *where) -> int:
        return db.execute(select(func.count()).select_from(model).where(*where)).scalar_one()

    return {
        "portfolios": count(Portfolio, Portfolio.status == PortfolioStatus.OPEN),
        "awaiting_approval": count(InvestmentOrder,
                                   InvestmentOrder.status == OrderStatus.AWAITING_APPROVAL),
        "placed": count(InvestmentOrder, InvestmentOrder.status == OrderStatus.PLACED),
        "executed": count(InvestmentOrder, InvestmentOrder.status == OrderStatus.EXECUTED),
        "profiles": count(InvestmentProfile),
        "securities": count(Security, Security.active.is_(True)),
    }  # fmt: skip
