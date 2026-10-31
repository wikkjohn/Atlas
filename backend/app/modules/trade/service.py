"""Trade finance services (Phase 37): letters of credit, guarantees, demands."""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.core.money import to_minor_units
from app.modules.accounts import service as accounts
from app.modules.accounts.models import Account, AccountStatus
from app.modules.compliance.screening import SANCTIONS_LISTS, screen_name
from app.modules.customers.models import Customer, CustomerType, KycStatus
from app.modules.fx import rates
from app.modules.ledger import service as ledger
from app.modules.ledger.models import Direction, LedgerAccountType
from app.modules.trade.models import (
    DEMAND_SEQUENCE,
    DISCREPANCIES,
    INSTRUMENT_SEQUENCE,
    DemandStatus,
    InstrumentKind,
    InstrumentStatus,
    TradeDemand,
    TradeInstrument,
)

MIN_AMOUNT_USD, MAX_AMOUNT_USD = 10_000, 5_000_000
COMMITTEE_LIMIT_USD = 1_000_000  # above this the credit committee also approves
MARGIN_BPS = {InstrumentKind.LETTER_OF_CREDIT: 2000, InstrumentKind.GUARANTEE: 1000}
MIN_DAYS, MAX_DAYS = 30, 730  # how far ahead an instrument may expire
PREFIX = {InstrumentKind.LETTER_OF_CREDIT: "LC", InstrumentKind.GUARANTEE: "BG"}


def _usd(amount: int, currency: str) -> int:
    """US dollars in minor units of `currency`, two significant figures."""
    units = Decimal(amount) * rates.units_per_usd(currency, rates.ANCHOR_DATE)
    whole = int(units)
    if whole >= 100:
        whole = round(whole, -(len(str(whole)) - 2))
    return to_minor_units(max(whole, 1), currency)


def amount_range(currency: str) -> tuple[int, int]:
    return _usd(MIN_AMOUNT_USD, currency), _usd(MAX_AMOUNT_USD, currency)


def needs_committee(instrument: TradeInstrument) -> bool:
    return instrument.amount > _usd(COMMITTEE_LIMIT_USD, instrument.currency)


def _ledger(db: Session, kind: str, currency: str):
    names = {"MARGIN": "Trade cash margin held", "SETTLEMENT": "Trade settlement payable"}
    return ledger.ensure_ledger_account(
        db, code=f"TRADE-{kind}-{currency}", name=f"{names[kind]} ({currency})",
        account_type=LedgerAccountType.LIABILITY, currency=currency,
    )  # fmt: skip


def margin_account(db: Session, currency: str):
    return _ledger(db, "MARGIN", currency)


def settlement_account(db: Session, currency: str):
    return _ledger(db, "SETTLEMENT", currency)


def _post(db, *, key: str, currency: str, memo: str, debit: uuid.UUID, credit: uuid.UUID,
          amount: int, actor_id, today: date) -> None:  # fmt: skip
    ledger.post_entry(
        db, idempotency_key=key, currency=currency, description=memo, source="trade_finance",
        lines=[ledger.LineSpec(debit, Direction.DEBIT, amount, memo),
               ledger.LineSpec(credit, Direction.CREDIT, amount, memo)],
        actor_id=actor_id, effective_date=today,
    )  # fmt: skip


def _audit(db, actor_id, action: str, instrument: TradeInstrument, **metadata) -> None:
    record_audit_event(
        db, actor_id=actor_id, action=action, entity_type="trade_instrument",
        entity_id=instrument.id,
        metadata={"instrument_number": instrument.instrument_number, **metadata},
    )  # fmt: skip


def find_customer(db: Session, number: str) -> Customer | None:
    return db.execute(
        select(Customer).where(Customer.customer_number == number.strip().upper())
    ).scalar_one_or_none()


def get_instrument(db: Session, instrument_id: uuid.UUID, *, for_update: bool = False):
    query = select(TradeInstrument).where(TradeInstrument.id == instrument_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    instrument = db.execute(query).scalar_one_or_none()
    if instrument is None:
        raise NotFoundError("Trade instrument not found.")
    return instrument


def find_instrument(db: Session, number: str) -> TradeInstrument | None:
    return db.execute(
        select(TradeInstrument).where(TradeInstrument.instrument_number == number.strip().upper())
    ).scalar_one_or_none()


def screen_beneficiary(name: str) -> dict[str, Any]:
    """The beneficiary against every synthetic sanctions list."""
    return screen_name(name, list(SANCTIONS_LISTS))


# --- Request and issue -----------------------------------------------------------------------


def request_instrument(
    db: Session,
    *,
    customer: Customer,
    account: Account,
    kind: str,
    beneficiary_name: str,
    beneficiary_country: str,
    amount: int,
    expires_on: date,
    purpose: str,
    requested_by: uuid.UUID,
    today: date | None = None,
) -> TradeInstrument:
    """A letter of credit or guarantee requested by a verified business. A beneficiary on a
    sanctions list is refused outright."""
    today = today or datetime.now(UTC).date()
    instrument_kind = InstrumentKind(kind)
    if customer.customer_type != CustomerType.BUSINESS:
        raise BusinessRuleViolation("Trade instruments are for business customers.")
    if customer.kyc_status != KycStatus.VERIFIED:
        raise BusinessRuleViolation("The customer's KYC is not verified.")
    if (account.customer_id != customer.id or account.account_type != "business_current"
            or account.status != AccountStatus.OPEN):  # fmt: skip
        raise BusinessRuleViolation(
            "Instruments are issued against the customer's open business current account."
        )
    low, high = amount_range(account.currency)
    if not low <= amount <= high:
        raise BusinessRuleViolation(
            f"The amount must be between {low} and {high} ({account.currency} minor units)."
        )
    if not today + timedelta(days=MIN_DAYS) <= expires_on <= today + timedelta(days=MAX_DAYS):
        raise BusinessRuleViolation(f"Expiry must be {MIN_DAYS} to {MAX_DAYS} days ahead.")
    name = " ".join(beneficiary_name.split())
    if len(name) < 2:
        raise BusinessRuleViolation("Name the beneficiary.")
    screening = screen_beneficiary(name)
    if screening["hit"]:
        raise BusinessRuleViolation(
            f"The beneficiary matches the sanctions list {screening['list']}.",
            {"rule": "sanctions_hit", "list": screening["list"]},
        )
    margin_bps = MARGIN_BPS[instrument_kind]
    sequence = db.execute(INSTRUMENT_SEQUENCE.next_value()).scalar_one()
    instrument = TradeInstrument(
        instrument_number=f"{PREFIX[instrument_kind]}-{sequence:07d}",
        kind=instrument_kind.value,
        customer_id=customer.id,
        account_id=account.id,
        beneficiary_name=name[:140],
        beneficiary_country=beneficiary_country.strip().upper()[:2],
        purpose=(purpose.strip() or "Trade")[:140],
        amount=amount,
        currency=account.currency,
        margin_bps=margin_bps,
        margin=amount * margin_bps // 10_000,
        drawn=0,
        expires_on=expires_on,
        screening=screening,
        status=InstrumentStatus.REQUESTED.value,
        requested_by=requested_by,
    )
    db.add(instrument)
    db.flush()
    _audit(db, requested_by, "trade.requested", instrument, amount=amount)
    return instrument


def _require(instrument: TradeInstrument, *statuses: InstrumentStatus) -> None:
    if instrument.status not in statuses:
        raise ConflictError(f"{instrument.instrument_number} is {instrument.status}.")


def approve_instrument(
    db: Session, instrument: TradeInstrument, actor_id: uuid.UUID, *, now: datetime | None = None
) -> TradeInstrument:
    """The credit approval, not by the requester. Above US$1m the committee approves too
    before the instrument is issued and its margin taken."""
    _require(instrument, InstrumentStatus.REQUESTED)
    now = now or datetime.now(UTC)
    _require_unexpired(instrument, now)
    if instrument.approved_by is not None:
        raise ConflictError(f"{instrument.instrument_number} is already approved.")
    if actor_id == instrument.requested_by:
        raise BusinessRuleViolation(
            "Four-eyes rule: the person who took the request cannot approve it.",
            {"rule": "four_eyes"},
        )
    instrument.approved_by = actor_id
    db.flush()
    _audit(db, actor_id, "trade.approved", instrument)
    return _issue_if_ready(db, instrument, actor_id, now)


def committee_approve(
    db: Session, instrument: TradeInstrument, actor_id: uuid.UUID, *, now: datetime | None = None
) -> TradeInstrument:
    _require(instrument, InstrumentStatus.REQUESTED)
    now = now or datetime.now(UTC)
    _require_unexpired(instrument, now)
    if not needs_committee(instrument):
        raise BusinessRuleViolation("This instrument is within the credit approver's authority.")
    if instrument.approved_by is None:
        raise BusinessRuleViolation("The credit approval comes before the committee's.")
    if actor_id in (instrument.requested_by, instrument.approved_by):
        raise BusinessRuleViolation(
            "Four-eyes rule: the committee approver must be a third person.",
            {"rule": "committee_four_eyes"},
        )
    instrument.committee_approved_by = actor_id
    db.flush()
    _audit(db, actor_id, "trade.committee_approved", instrument)
    return _issue_if_ready(db, instrument, actor_id, now)


def _require_unexpired(instrument: TradeInstrument, now: datetime) -> None:
    """An approval that comes after the expiry date cannot issue the instrument (PR #28
    review): it would take a margin for an instrument that can no longer be used."""
    if now.date() > instrument.expires_on:
        raise BusinessRuleViolation(
            f"{instrument.instrument_number} expired on {instrument.expires_on} before it was "
            "approved; decline it and request a new one.",
            {"rule": "expired_before_issue"},
        )


def _issue_if_ready(db, instrument: TradeInstrument, actor_id, now: datetime) -> TradeInstrument:
    if instrument.approved_by is None or (
        needs_committee(instrument) and instrument.committee_approved_by is None
    ):
        return instrument
    account = accounts.get_account(db, instrument.account_id, for_update=True)
    if account.status != AccountStatus.OPEN:
        raise BusinessRuleViolation(f"The business account is {account.status}.")
    if instrument.margin > accounts.available(db, account):
        raise BusinessRuleViolation(
            f"The business account cannot provide the {instrument.margin} cash margin."
        )
    if instrument.margin:
        _post(db, key=f"trade-margin:{instrument.instrument_number}",
              currency=instrument.currency, memo=f"Cash margin {instrument.instrument_number}",
              debit=account.ledger_account_id, credit=margin_account(db, instrument.currency).id,
              amount=instrument.margin, actor_id=actor_id, today=now.date())  # fmt: skip
    instrument.status, instrument.issued_at = InstrumentStatus.ISSUED.value, now
    db.flush()
    _audit(db, actor_id, "trade.issued", instrument, margin=instrument.margin)
    return instrument


def decline_instrument(db: Session, instrument: TradeInstrument, actor_id: uuid.UUID):
    _require(instrument, InstrumentStatus.REQUESTED)
    if actor_id == instrument.requested_by:
        raise BusinessRuleViolation("Four-eyes rule: the requester cannot decide.",
                                    {"rule": "four_eyes"})  # fmt: skip
    instrument.status = InstrumentStatus.DECLINED.value
    db.flush()
    _audit(db, actor_id, "trade.declined", instrument)
    return instrument


# --- Presentations and claims ----------------------------------------------------------------


def get_demand(db: Session, demand_id: uuid.UUID, *, for_update: bool = False) -> TradeDemand:
    query = select(TradeDemand).where(TradeDemand.id == demand_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    demand = db.execute(query).scalar_one_or_none()
    if demand is None:
        raise NotFoundError("Demand not found.")
    return demand


def receive_demand(
    db: Session,
    instrument: TradeInstrument,
    *,
    amount: int,
    presented_on: date,
    discrepancies: list[str] | None = None,
    received_by: uuid.UUID | None,
) -> TradeDemand:
    """Documents presented under a letter of credit (with the discrepancies the checker
    found, if any) or a claim under a guarantee, before expiry and within what is left."""
    _require(instrument, InstrumentStatus.ISSUED)
    found = sorted(set(discrepancies or []))
    if instrument.kind == InstrumentKind.GUARANTEE and found:
        raise BusinessRuleViolation("A guarantee pays on demand: no documents are examined.")
    unknown = set(found) - DISCREPANCIES
    if unknown:
        raise BusinessRuleViolation(f"Unknown discrepancies: {', '.join(sorted(unknown))}.")
    if presented_on > instrument.expires_on:
        raise BusinessRuleViolation(
            f"{instrument.instrument_number} expired on {instrument.expires_on}."
        )
    remaining = instrument.amount - instrument.drawn
    if not 0 < amount <= remaining:
        raise BusinessRuleViolation(f"Between 1 and the {remaining} left can be demanded.")
    pending = db.execute(
        select(TradeDemand.demand_number).where(
            TradeDemand.instrument_id == instrument.id, TradeDemand.status == DemandStatus.PENDING
        )
    ).scalar_one_or_none()
    if pending:
        raise ConflictError(f"{pending} is still being checked.")
    number = f"DMD-{db.execute(DEMAND_SEQUENCE.next_value()).scalar_one():07d}"
    demand = TradeDemand(
        demand_number=number, instrument_id=instrument.id, amount=amount,
        presented_on=presented_on, discrepancies=found, status=DemandStatus.PENDING.value,
        received_by=received_by,
    )  # fmt: skip
    db.add(demand)
    db.flush()
    _audit(db, received_by, "trade.demand_received", instrument, demand_number=number,
           amount=amount, discrepancies=found)  # fmt: skip
    return demand


def pay_demand(
    db: Session, demand: TradeDemand, actor_id: uuid.UUID, *, now: datetime | None = None
) -> TradeDemand:
    """Pay the beneficiary, not by the person who received the demand. The margin is
    released in proportion and the applicant's account debited; a discrepant presentation
    is paid only because the applicant waived the discrepancies (the decision says so)."""
    now = now or datetime.now(UTC)
    demand = get_demand(db, demand.id, for_update=True)
    if demand.status != DemandStatus.PENDING:
        raise ConflictError(f"{demand.demand_number} is {demand.status}.")
    if actor_id == demand.received_by:
        raise BusinessRuleViolation("Four-eyes rule: the person who received the demand "
                                    "cannot pay it.", {"rule": "four_eyes"})  # fmt: skip
    instrument = get_instrument(db, demand.instrument_id, for_update=True)
    _require(instrument, InstrumentStatus.ISSUED)
    account = accounts.get_account(db, instrument.account_id, for_update=True)
    if account.status != AccountStatus.OPEN:
        raise BusinessRuleViolation(f"The business account is {account.status}.")
    remaining = instrument.amount - instrument.drawn
    release = (
        instrument.margin
        if demand.amount == remaining
        else instrument.margin * demand.amount // remaining
    )
    if demand.amount > accounts.available(db, account) + release:
        raise BusinessRuleViolation("The applicant's account cannot fund the payment.")
    today = now.date()
    if release:
        _post(db, key=f"trade-release:{demand.demand_number}", currency=instrument.currency,
              memo=f"Margin released {instrument.instrument_number}",
              debit=margin_account(db, instrument.currency).id,
              credit=account.ledger_account_id, amount=release, actor_id=actor_id,
              today=today)  # fmt: skip
    _post(db, key=f"trade-payment:{demand.demand_number}", currency=instrument.currency,
          memo=f"Payment {demand.demand_number} under {instrument.instrument_number}",
          debit=account.ledger_account_id,
          credit=settlement_account(db, instrument.currency).id, amount=demand.amount,
          actor_id=actor_id, today=today)  # fmt: skip
    instrument.margin -= release
    instrument.drawn += demand.amount
    if instrument.drawn == instrument.amount:
        instrument.status, instrument.closed_at = InstrumentStatus.PAID.value, now
    demand.status, demand.decided_by, demand.decided_at = DemandStatus.PAID.value, actor_id, now
    demand.decision_note = (
        "Discrepancies waived by the applicant" if demand.discrepancies else "Complying"
    )
    db.flush()
    _audit(db, actor_id, "trade.demand_paid", instrument, demand_number=demand.demand_number,
           amount=demand.amount, margin_released=release)  # fmt: skip
    return demand


def reject_demand(
    db: Session, demand: TradeDemand, actor_id: uuid.UUID, note: str,
    *, now: datetime | None = None,
) -> TradeDemand:  # fmt: skip
    demand = get_demand(db, demand.id, for_update=True)
    if demand.status != DemandStatus.PENDING:
        raise ConflictError(f"{demand.demand_number} is {demand.status}.")
    if actor_id == demand.received_by:
        raise BusinessRuleViolation("Four-eyes rule: the person who received the demand "
                                    "cannot decide it.", {"rule": "four_eyes"})  # fmt: skip
    demand.status, demand.decided_by = DemandStatus.REJECTED.value, actor_id
    demand.decided_at, demand.decision_note = now or datetime.now(UTC), note.strip()[:200]
    db.flush()
    instrument = get_instrument(db, demand.instrument_id)
    _audit(db, actor_id, "trade.demand_rejected", instrument,
           demand_number=demand.demand_number, note=demand.decision_note)  # fmt: skip
    return demand


def expire_instrument(
    db: Session, instrument: TradeInstrument, actor_id: uuid.UUID | None,
    *, today: date | None = None,
) -> TradeInstrument:  # fmt: skip
    """Close an instrument after its expiry and release what is left of the margin."""
    today = today or datetime.now(UTC).date()
    instrument = get_instrument(db, instrument.id, for_update=True)
    _require(instrument, InstrumentStatus.ISSUED)
    if today <= instrument.expires_on:
        raise BusinessRuleViolation(
            f"{instrument.instrument_number} is valid until {instrument.expires_on}."
        )
    if db.execute(
        select(TradeDemand.id).where(TradeDemand.instrument_id == instrument.id,
                                     TradeDemand.status == DemandStatus.PENDING)
    ).scalar_one_or_none():  # fmt: skip
        raise ConflictError("A demand is still being checked.")
    if instrument.margin:
        account = accounts.get_account(db, instrument.account_id, for_update=True)
        _post(db, key=f"trade-expiry:{instrument.instrument_number}",
              currency=instrument.currency, memo=f"Margin released {instrument.instrument_number}",
              debit=margin_account(db, instrument.currency).id,
              credit=account.ledger_account_id, amount=instrument.margin, actor_id=actor_id,
              today=today)  # fmt: skip
    released, instrument.margin = instrument.margin, 0
    instrument.status = InstrumentStatus.EXPIRED.value
    instrument.closed_at = datetime.now(UTC)
    db.flush()
    _audit(db, actor_id, "trade.expired", instrument, margin_released=released)
    return instrument


def presentation_profile(db: Session, demand: TradeDemand) -> dict[str, Any]:
    """What a trade officer weighs when the applicant is asked to waive a discrepancy
    (Phase 38): the discrepancy, how much of the credit is drawn and how close it is to
    expiry, whether the applicant can fund the payment, and the credit's earlier
    presentations."""
    instrument = get_instrument(db, demand.instrument_id)
    account = accounts.get_account(db, instrument.account_id)
    earlier = list(
        db.execute(
            select(TradeDemand).where(TradeDemand.instrument_id == instrument.id,
                                      TradeDemand.id != demand.id,
                                      TradeDemand.status != DemandStatus.PENDING)
        ).scalars()
    )  # fmt: skip
    remaining = instrument.amount - instrument.drawn
    release = (
        instrument.margin
        if demand.amount >= remaining
        else instrument.margin * demand.amount // max(remaining, 1)
    )
    funds = accounts.available(db, account) + release
    found = set(demand.discrepancies)
    return {
        "currency": instrument.currency,
        "kind": instrument.kind,
        "discrepancy": demand.discrepancies[0] if demand.discrepancies else "none",
        "discrepancy_count": len(demand.discrepancies),
        "draw_share_bps": demand.amount * 10_000 // instrument.amount,
        "days_to_expiry": (instrument.expires_on - demand.presented_on).days,
        "funding_cover_bps": min(funds * 10_000 // demand.amount, 99_999),
        "earlier_presentations": len(earlier),
        "earlier_rejected": sum(d.status == DemandStatus.REJECTED for d in earlier),
        "earlier_same_discrepancy": sum(bool(found & set(d.discrepancies)) for d in earlier),
    }


def summary(db: Session) -> dict[str, Any]:
    def count(*where) -> int:
        return db.execute(select(func.count()).where(*where)).scalar_one()

    return {
        "requested": count(TradeInstrument.status == InstrumentStatus.REQUESTED),
        "issued": count(TradeInstrument.status == InstrumentStatus.ISSUED),
        "pending_demands": count(TradeDemand.status == DemandStatus.PENDING),
        "paid": count(TradeInstrument.status == InstrumentStatus.PAID),
        "expired": count(TradeInstrument.status == InstrumentStatus.EXPIRED),
    }
