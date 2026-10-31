"""Commercial lending services (Phase 35): facilities, drawdowns, covenants, reviews."""

import calendar
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
from app.modules.commercial.models import (
    FACILITY_SEQUENCE,
    REVIEW_SEQUENCE,
    CommercialFacility,
    CovenantKind,
    CovenantTest,
    FacilityCovenant,
    FacilityReview,
    FacilityStatus,
    FacilityType,
    ReviewOutcome,
)
from app.modules.customers.models import Customer, CustomerType, KycStatus
from app.modules.fx import rates
from app.modules.ledger import service as ledger
from app.modules.ledger.models import Direction, LedgerAccountType

MIN_LIMIT_USD, MAX_LIMIT_USD = 50_000, 5_000_000
COMMITTEE_LIMIT_USD = 1_000_000  # above this the credit committee also approves
RATES_BPS = {FacilityType.TERM_LOAN: 650, FacilityType.REVOLVING: 750}  # fixed, a year
DEFAULT_COVENANTS = {CovenantKind.MIN_DSCR: 125, CovenantKind.MAX_LEVERAGE: 350}
REVIEW_EVERY_DAYS = 365
REVIEW_WINDOW_DAYS = 60  # a review can be opened this long before it is due
RECEIVABLE_PREFIX = "1350"


def _usd(amount: int, currency: str) -> int:
    """US dollars in minor units of `currency`, two significant figures."""
    units = Decimal(amount) * rates.units_per_usd(currency, rates.ANCHOR_DATE)
    whole = int(units)
    if whole >= 100:
        whole = round(whole, -(len(str(whole)) - 2))
    return to_minor_units(max(whole, 1), currency)


def limit_range(currency: str) -> tuple[int, int]:
    return _usd(MIN_LIMIT_USD, currency), _usd(MAX_LIMIT_USD, currency)


def needs_committee(facility: CommercialFacility) -> bool:
    return facility.credit_limit > _usd(COMMITTEE_LIMIT_USD, facility.currency)


def _add_months(day: date, months: int) -> date:
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def find_customer(db: Session, number: str) -> Customer | None:
    return db.execute(
        select(Customer).where(Customer.customer_number == number.strip().upper())
    ).scalar_one_or_none()


def get_facility(db: Session, facility_id: uuid.UUID, *, for_update: bool = False):
    query = select(CommercialFacility).where(CommercialFacility.id == facility_id)
    if for_update:
        query = query.with_for_update()
    facility = db.execute(query).scalar_one_or_none()
    if facility is None:
        raise NotFoundError("Facility not found.")
    return facility


def find_facility(db: Session, number: str) -> CommercialFacility | None:
    return db.execute(
        select(CommercialFacility).where(
            CommercialFacility.facility_number == number.strip().upper()
        )
    ).scalar_one_or_none()


def covenants(db: Session, facility: CommercialFacility) -> list[FacilityCovenant]:
    return list(
        db.execute(
            select(FacilityCovenant)
            .where(FacilityCovenant.facility_id == facility.id)
            .order_by(FacilityCovenant.kind)
        ).scalars()
    )


def _audit(db, actor_id, action: str, facility: CommercialFacility, **metadata) -> None:
    record_audit_event(
        db, actor_id=actor_id, action=action, entity_type="commercial_facility",
        entity_id=facility.id, metadata={"facility_number": facility.facility_number, **metadata},
    )  # fmt: skip


# --- Proposal and approval -------------------------------------------------------------------


def propose_facility(
    db: Session,
    *,
    customer: Customer,
    account: Account,
    facility_type: str,
    credit_limit: int,
    term_months: int,
    purpose: str,
    requested_by: uuid.UUID,
    covenant_thresholds: dict[str, int] | None = None,
) -> CommercialFacility:
    """A facility proposal for a verified business customer, drawn into its business
    current account; covenants default to DSCR at least 1.25× and leverage at most 3.5×."""
    if customer.customer_type != CustomerType.BUSINESS:
        raise BusinessRuleViolation("Commercial facilities are for business customers.")
    if customer.kyc_status != KycStatus.VERIFIED:
        raise BusinessRuleViolation("The customer's KYC is not verified.")
    if (
        account.customer_id != customer.id
        or account.account_type != "business_current"
        or account.status != AccountStatus.OPEN
    ):
        raise BusinessRuleViolation("Facilities are drawn into the customer's open business "
                                    "current account.")  # fmt: skip
    kind = FacilityType(facility_type)
    low, high = limit_range(account.currency)
    if not low <= credit_limit <= high:
        raise BusinessRuleViolation(
            f"The limit must be between {low} and {high} ({account.currency} minor units)."
        )
    if not 12 <= term_months <= (60 if kind == FacilityType.REVOLVING else 120):
        raise BusinessRuleViolation("Terms run 12 to 120 months (revolving credit at most 60).")
    thresholds = {**DEFAULT_COVENANTS, **{CovenantKind(k): v for k, v in
                                          (covenant_thresholds or {}).items()}}  # fmt: skip
    if not all(1 <= v <= 10_000 for v in thresholds.values()):
        raise BusinessRuleViolation("Covenant thresholds are ratios between 0.01 and 100.")
    number = f"FAC-{db.execute(FACILITY_SEQUENCE.next_value()).scalar_one():07d}"
    facility = CommercialFacility(
        facility_number=number,
        customer_id=customer.id,
        account_id=account.id,
        facility_type=kind.value,
        purpose=purpose.strip()[:100] or "Working capital",
        credit_limit=credit_limit,
        currency=account.currency,
        annual_rate_bps=RATES_BPS[kind],
        term_months=term_months,
        drawn=0,
        drawn_total=0,
        status=FacilityStatus.PROPOSED.value,
        requested_by=requested_by,
    )
    db.add(facility)
    db.flush()
    for kind_, threshold in thresholds.items():
        db.add(FacilityCovenant(facility_id=facility.id, kind=kind_.value,
                                threshold_centi=threshold))  # fmt: skip
    db.flush()
    _audit(db, requested_by, "facility.proposed", facility, credit_limit=credit_limit)
    return facility


def _require(facility: CommercialFacility, *statuses: FacilityStatus) -> None:
    if facility.status not in statuses:
        raise ConflictError(f"Facility {facility.facility_number} is {facility.status}.")


def approve_facility(
    db: Session, facility: CommercialFacility, actor_id: uuid.UUID, *, now: datetime | None = None
) -> CommercialFacility:
    """The credit approval, not by the requester. A facility above the committee limit
    also needs the committee (`committee_approve`) before it is active."""
    _require(facility, FacilityStatus.PROPOSED)
    if facility.approved_by is not None:
        raise ConflictError(f"Facility {facility.facility_number} is already approved.")
    if actor_id == facility.requested_by:
        raise BusinessRuleViolation(
            "Four-eyes rule: the person who proposed the facility cannot approve it.",
            {"rule": "four_eyes"},
        )
    facility.approved_by = actor_id
    db.flush()
    _audit(db, actor_id, "facility.approved", facility)
    return _activate_if_ready(db, facility, now or datetime.now(UTC))


def committee_approve(
    db: Session, facility: CommercialFacility, actor_id: uuid.UUID, *, now: datetime | None = None
) -> CommercialFacility:
    _require(facility, FacilityStatus.PROPOSED)
    if not needs_committee(facility):
        raise BusinessRuleViolation("This facility is within the credit approver's authority.")
    if facility.approved_by is None:
        raise BusinessRuleViolation("The credit approval comes before the committee's.")
    if actor_id in (facility.requested_by, facility.approved_by):
        raise BusinessRuleViolation(
            "Four-eyes rule: the committee approver must be a third person.",
            {"rule": "committee_four_eyes"},
        )
    facility.committee_approved_by = actor_id
    db.flush()
    _audit(db, actor_id, "facility.committee_approved", facility)
    return _activate_if_ready(db, facility, now or datetime.now(UTC))


def _activate_if_ready(db: Session, facility: CommercialFacility, now: datetime):
    if facility.approved_by is None or (
        needs_committee(facility) and facility.committee_approved_by is None
    ):
        return facility
    receivable = ledger.ensure_ledger_account(
        db,
        code=f"{RECEIVABLE_PREFIX}-{facility.facility_number}",
        name=f"Facility receivable {facility.facility_number}",
        account_type=LedgerAccountType.ASSET,
        currency=facility.currency,
    )
    facility.ledger_account_id = receivable.id
    facility.status = FacilityStatus.ACTIVE.value
    facility.activated_at = now
    facility.review_due_on = now.date() + timedelta(days=REVIEW_EVERY_DAYS)
    facility.matures_on = _add_months(now.date(), facility.term_months)
    db.flush()
    _audit(db, None, "facility.activated", facility)
    return facility


def decline_facility(db: Session, facility: CommercialFacility, actor_id: uuid.UUID):
    _require(facility, FacilityStatus.PROPOSED)
    if actor_id == facility.requested_by:
        raise BusinessRuleViolation("Four-eyes rule: the proposer cannot decide.",
                                    {"rule": "four_eyes"})  # fmt: skip
    facility.status = FacilityStatus.DECLINED.value
    db.flush()
    _audit(db, actor_id, "facility.declined", facility)
    return facility


# --- Drawdowns and repayments ----------------------------------------------------------------


def available(facility: CommercialFacility) -> int:
    """What may still be drawn: revolving credit redraws repaid amounts; a term loan is
    drawn up to its limit once over its life."""
    used = facility.drawn if facility.facility_type == FacilityType.REVOLVING else (
        facility.drawn_total
    )  # fmt: skip
    return max(facility.credit_limit - used, 0)


def draw_block(facility: CommercialFacility, today: date) -> str | None:
    """Why the facility cannot be drawn today, or None."""
    if facility.status == FacilityStatus.FROZEN:
        return f"frozen: {facility.frozen_reason}"
    if facility.status != FacilityStatus.ACTIVE:
        return facility.status
    if facility.review_due_on and today > facility.review_due_on:
        return f"annual review overdue since {facility.review_due_on}"
    if facility.matures_on and today >= facility.matures_on:
        return f"matured on {facility.matures_on}"
    return None


def _post(db, facility, account, amount, *, draw: bool, actor_id, now, key: str) -> None:
    memo = f"{'Drawdown' if draw else 'Repayment'} {facility.facility_number}"
    ledger.post_entry(
        db,
        idempotency_key=key,
        currency=facility.currency,
        description=memo,
        source="commercial_facility",
        lines=[
            ledger.LineSpec(
                facility.ledger_account_id,
                Direction.DEBIT if draw else Direction.CREDIT,
                amount,
                memo,
            ),
            ledger.LineSpec(
                account.ledger_account_id,
                Direction.CREDIT if draw else Direction.DEBIT,
                amount,
                memo,
            ),
        ],  # fmt: skip
        actor_id=actor_id,
        effective_date=now.date(),
    )


def draw(
    db: Session, facility: CommercialFacility, amount: int, actor_id: uuid.UUID | None,
    *, now: datetime | None = None,
) -> CommercialFacility:  # fmt: skip
    now = now or datetime.now(UTC)
    if amount <= 0:
        raise BusinessRuleViolation("The amount must be positive.")
    blocked = draw_block(facility, now.date())
    if blocked:
        raise BusinessRuleViolation(f"Facility {facility.facility_number} cannot be drawn: "
                                    f"{blocked}.")  # fmt: skip
    if amount > available(facility):
        raise BusinessRuleViolation(f"Only {available(facility)} is available.")
    account = accounts.get_account(db, facility.account_id, for_update=True)
    if account.status != AccountStatus.OPEN:
        raise BusinessRuleViolation(f"The business account is {account.status}.")
    facility.drawn += amount
    facility.drawn_total += amount
    _post(db, facility, account, amount, draw=True, actor_id=actor_id, now=now,
          key=f"facility-draw:{facility.facility_number}:{facility.drawn_total}")  # fmt: skip
    db.flush()
    _audit(db, actor_id, "facility.drawn", facility, amount=amount)
    return facility


def repay(
    db: Session, facility: CommercialFacility, amount: int, actor_id: uuid.UUID | None,
    *, now: datetime | None = None,
) -> CommercialFacility:  # fmt: skip
    now = now or datetime.now(UTC)
    if not 0 < amount <= facility.drawn:
        raise BusinessRuleViolation(f"Repay between 1 and the {facility.drawn} drawn.")
    account = accounts.get_account(db, facility.account_id, for_update=True)
    if account.status != AccountStatus.OPEN:
        raise BusinessRuleViolation(f"The business account is {account.status}.")
    if amount > accounts.available(db, account):
        raise BusinessRuleViolation("The business account cannot pay that.")
    repaid = facility.drawn_total - facility.drawn + amount
    facility.drawn -= amount
    _post(db, facility, account, amount, draw=False, actor_id=actor_id, now=now,
          key=f"facility-repay:{facility.facility_number}:{repaid}")  # fmt: skip
    db.flush()
    _audit(db, actor_id, "facility.repaid", facility, amount=amount)
    return facility


# --- Covenants -------------------------------------------------------------------------------


def run_covenant_test(
    db: Session,
    facility: CommercialFacility,
    *,
    period_end: date,
    ebitda: int,
    debt_service: int,
    total_debt: int,
    actor_id: uuid.UUID | None,
) -> CovenantTest:
    """Test the covenants on a period's figures (a year). A breach freezes the facility."""
    _require(facility, FacilityStatus.ACTIVE, FacilityStatus.FROZEN)
    if debt_service <= 0 or ebitda < 0 or total_debt < 0:
        raise BusinessRuleViolation("Debt service must be positive; EBITDA and debt not negative.")
    exists = db.execute(
        select(CovenantTest.id).where(
            CovenantTest.facility_id == facility.id, CovenantTest.period_end == period_end
        )
    ).scalar_one_or_none()
    if exists:
        raise ConflictError(f"The period ending {period_end} is already tested.")
    dscr = ebitda * 100 // debt_service
    leverage = total_debt * 100 // ebitda if ebitda else 999_999
    results = []
    for covenant in covenants(db, facility):
        actual = dscr if covenant.kind == CovenantKind.MIN_DSCR else leverage
        # Compliance by exact cross-multiplication; the truncated ratio is for display only
        # (3.505× must not pass a 3.50× maximum).
        passed = (
            ebitda * 100 >= covenant.threshold_centi * debt_service
            if covenant.kind == CovenantKind.MIN_DSCR
            else total_debt * 100 <= covenant.threshold_centi * ebitda
        )
        results.append({"kind": covenant.kind, "threshold_centi": covenant.threshold_centi,
                        "actual_centi": actual, "passed": passed})  # fmt: skip
    breached = not all(r["passed"] for r in results)
    test = CovenantTest(
        facility_id=facility.id, period_end=period_end, ebitda=ebitda,
        debt_service=debt_service, total_debt=total_debt, results=results,
        breached=breached, submitted_by=actor_id,
    )  # fmt: skip
    db.add(test)
    if breached:
        facility.status = FacilityStatus.FROZEN.value
        failed = ", ".join(r["kind"] for r in results if not r["passed"])
        facility.frozen_reason = f"covenant breach ({failed}) for the period to {period_end}"
    db.flush()
    _audit(db, actor_id, "facility.covenants_tested", facility,
           period_end=period_end.isoformat(), breached=breached)  # fmt: skip
    return test


def get_test(db: Session, test_id: uuid.UUID) -> CovenantTest:
    test = db.get(CovenantTest, test_id)
    if test is None:
        raise NotFoundError("Covenant test not found.")
    return test


def waive_breach(
    db: Session, test: CovenantTest, actor_id: uuid.UUID, *, now: datetime | None = None
) -> CommercialFacility:
    """The credit committee waives a breach; with no other unwaived breach the facility
    can be drawn again. Not by the person who submitted the figures."""
    test = db.execute(
        select(CovenantTest)
        .where(CovenantTest.id == test.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()
    if not test.breached or test.waived_by is not None:
        raise ConflictError("This test has no breach to waive.")
    if actor_id == test.submitted_by:
        raise BusinessRuleViolation("Four-eyes rule: the person who submitted the figures "
                                    "cannot waive the breach.", {"rule": "four_eyes"})  # fmt: skip
    test.waived_by, test.waived_at = actor_id, now or datetime.now(UTC)
    facility = get_facility(db, test.facility_id, for_update=True)
    db.flush()
    open_breaches = db.execute(
        select(func.count()).where(
            CovenantTest.facility_id == facility.id,
            CovenantTest.breached.is_(True),
            CovenantTest.waived_by.is_(None),
        )
    ).scalar_one()
    if open_breaches == 0 and facility.status == FacilityStatus.FROZEN:
        facility.status, facility.frozen_reason = FacilityStatus.ACTIVE.value, None
    db.flush()
    _audit(db, actor_id, "facility.breach_waived", facility, period_end=str(test.period_end))
    return facility


# --- Annual reviews --------------------------------------------------------------------------


def open_review(
    db: Session, facility: CommercialFacility, actor_id: uuid.UUID, *, today: date | None = None
) -> FacilityReview:
    today = today or datetime.now(UTC).date()
    _require(facility, FacilityStatus.ACTIVE, FacilityStatus.FROZEN)
    if facility.review_due_on and today < facility.review_due_on - timedelta(
        days=REVIEW_WINDOW_DAYS
    ):
        raise BusinessRuleViolation(
            f"The review is due on {facility.review_due_on}; it opens {REVIEW_WINDOW_DAYS} "
            "days before."
        )
    if db.execute(
        select(FacilityReview.id).where(
            FacilityReview.facility_id == facility.id, FacilityReview.outcome.is_(None)
        )
    ).scalar_one_or_none():
        raise ConflictError(f"Facility {facility.facility_number} has an open review.")
    number = f"REV-{db.execute(REVIEW_SEQUENCE.next_value()).scalar_one():07d}"
    review = FacilityReview(review_number=number, facility_id=facility.id,
                            due_on=facility.review_due_on, opened_by=actor_id)  # fmt: skip
    db.add(review)
    db.flush()
    _audit(db, actor_id, "facility.review_opened", facility, review_number=number)
    return review


def get_review(db: Session, review_id: uuid.UUID) -> FacilityReview:
    review = db.get(FacilityReview, review_id)
    if review is None:
        raise NotFoundError("Review not found.")
    return review


def decide_review(
    db: Session,
    review: FacilityReview,
    renew: bool,
    actor_id: uuid.UUID,
    *,
    new_limit: int | None = None,
    now: datetime | None = None,
) -> FacilityReview:
    """Renew for another year (optionally with a new limit, not below what is drawn) or
    terminate (no further drawdowns). Not by the person who opened the review."""
    now = now or datetime.now(UTC)
    # Re-read the review under a row lock, so two deciders cannot both see it open.
    review = db.execute(
        select(FacilityReview)
        .where(FacilityReview.id == review.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()
    if review.outcome is not None:
        raise ConflictError(f"Review {review.review_number} is decided.")
    if actor_id == review.opened_by:
        raise BusinessRuleViolation("Four-eyes rule: the person who opened the review cannot "
                                    "decide it.", {"rule": "four_eyes"})  # fmt: skip
    facility = get_facility(db, review.facility_id, for_update=True)
    if renew:
        if new_limit is not None:
            low, high = limit_range(facility.currency)
            if not (max(low, facility.drawn) <= new_limit <= high):
                raise BusinessRuleViolation("The new limit must cover what is drawn and stay "
                                            "within the limits.")  # fmt: skip
            if new_limit > facility.credit_limit and new_limit > _usd(
                COMMITTEE_LIMIT_USD, facility.currency
            ):
                raise BusinessRuleViolation(
                    "Raising a limit above US$1m needs the credit committee: propose a new "
                    "facility for the larger amount.",
                    {"rule": "committee_required"},
                )
            facility.credit_limit = new_limit
        facility.review_due_on = review.due_on + timedelta(days=REVIEW_EVERY_DAYS)
        review.outcome = ReviewOutcome.RENEWED.value
    else:
        facility.status = FacilityStatus.TERMINATED.value
        review.outcome = ReviewOutcome.TERMINATED.value
    review.new_limit, review.decided_by, review.decided_at = new_limit, actor_id, now
    db.flush()
    _audit(db, actor_id, "facility.reviewed", facility, review_number=review.review_number,
           outcome=review.outcome)  # fmt: skip
    return review


def breach_profile(db: Session, test: CovenantTest) -> dict[str, Any]:
    """What the credit committee looks at when a breach is reviewed (Phase 36): the
    period's ratios against the thresholds, how EBITDA moved over the last periods, how
    much of the facility is drawn, and the facility's earlier breaches and waivers."""
    facility = get_facility(db, test.facility_id)
    history = list(
        db.execute(
            select(CovenantTest)
            .where(CovenantTest.facility_id == facility.id,
                   CovenantTest.period_end <= test.period_end)
            .order_by(CovenantTest.period_end)
        ).scalars()
    )  # fmt: skip
    earlier = [t for t in history if t.period_end < test.period_end]
    ebitdas = [t.ebitda for t in history]

    def change(new: int, old: int) -> int:
        return int((new - old) * 10_000 / old) if old > 0 else 0  # toward zero

    changes = [change(b, a) for a, b in zip(ebitdas, ebitdas[1:], strict=False)]
    declines = 0
    for c in reversed(changes):
        if c >= 0:
            break
        declines += 1
    by_kind = {r["kind"]: r for r in test.results}
    dscr = by_kind.get(CovenantKind.MIN_DSCR, {})
    leverage = by_kind.get(CovenantKind.MAX_LEVERAGE, {})
    return {
        "currency": facility.currency,
        "facility_type": facility.facility_type,
        "dscr_centi": dscr.get("actual_centi", 0),
        "dscr_threshold_centi": dscr.get("threshold_centi", 0),
        "leverage_centi": leverage.get("actual_centi", 0),
        "leverage_threshold_centi": leverage.get("threshold_centi", 0),
        "ebitda_change_bps": changes[-1] if changes else 0,
        "previous_ebitda_change_bps": changes[-2] if len(changes) > 1 else 0,
        "consecutive_declines": declines,
        "utilisation_bps": facility.drawn * 10_000 // facility.credit_limit,
        "periods_tested": len(history),
        "previous_breaches": sum(t.breached for t in earlier),
        "previous_waivers": sum(t.waived_by is not None for t in earlier),
    }


def summary(db: Session) -> dict[str, Any]:
    def count(*where) -> int:
        return db.execute(select(func.count()).where(*where)).scalar_one()

    today = datetime.now(UTC).date()
    return {
        "proposed": count(CommercialFacility.status == FacilityStatus.PROPOSED),
        "active": count(CommercialFacility.status == FacilityStatus.ACTIVE),
        "frozen": count(CommercialFacility.status == FacilityStatus.FROZEN),
        "reviews_due": count(
            CommercialFacility.status.in_([FacilityStatus.ACTIVE, FacilityStatus.FROZEN]),
            CommercialFacility.review_due_on <= today + timedelta(days=REVIEW_WINDOW_DAYS),
        ),
        "open_reviews": count(FacilityReview.outcome.is_(None)),
    }
