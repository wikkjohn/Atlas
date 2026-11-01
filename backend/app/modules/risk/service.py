"""Risk services (Phase 47): internal credit ratings, obligor limits, credit exposure and
expected-credit-loss provisioning."""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text, tuple_
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.core.money import minor_unit_exponent
from app.modules.accounts.models import Account, AccountStatus
from app.modules.customers.models import Customer
from app.modules.fx import service as fx
from app.modules.ledger import service as ledger
from app.modules.ledger.models import Direction, LedgerAccount, LedgerAccountType, LedgerBalance
from app.modules.risk.models import (
    PROVISION_SEQUENCE,
    RATING_SEQUENCE,
    CreditRating,
    ObligorLimit,
    ProvisionLine,
    ProvisionRun,
    ProvisionStatus,
    RatingStatus,
)

# The internal scale: one-year probability of default (basis points) and the default credit
# limit (whole US dollars) by grade; grade 10 is in default.
GRADES = {
    1: (3, 25_000_000), 2: (6, 25_000_000), 3: (12, 10_000_000), 4: (25, 10_000_000),
    5: (50, 2_000_000), 6: (100, 2_000_000), 7: (200, 500_000), 8: (500, 100_000),
    9: (1_500, 0), 10: (10_000, 0),
}  # fmt: skip
KYC_GRADE = {"low": 4, "medium": 6, "high": 7, "unrated": 6}
RATING_VALID_DAYS = 365
# Loss given default (basis points) by exposure type.
LGD_BPS = {"mortgage": 1_500, "loan": 4_500, "facility": 4_000, "overdraft": 6_000}
UNDRAWN_CCF = Decimal("0.5")  # credit conversion factor on a revolving facility's headroom
MAX_LIFETIME_YEARS = 5


def _audit(db, actor_id, action: str, entity_type: str, entity_id, **metadata) -> None:
    record_audit_event(db, actor_id=actor_id, action=action, entity_type=entity_type,
                       entity_id=entity_id, metadata=metadata)  # fmt: skip


def _today(today: date | None) -> date:
    return today or datetime.now(UTC).date()


def _usd(db: Session, amount: int, currency: str, day: date) -> int:
    """Minor units of a currency in whole US dollars at the day's rate."""
    major = Decimal(amount) / Decimal(10) ** minor_unit_exponent(currency)
    return int(major / fx.rate(db, currency, day))


# --- Exposure ---------------------------------------------------------------------------------


@dataclass
class Exposure:
    customer_id: uuid.UUID
    exposure_type: str  # loan | mortgage | facility | overdraft
    reference: str
    currency: str
    ead: int  # exposure at default, minor units
    days_past_due: int
    remaining_years: Decimal
    frozen: bool = False  # a commercial facility frozen by a covenant breach


def exposures(db: Session, today: date, customer_ids: list[uuid.UUID] | None = None
              ) -> list[Exposure]:  # fmt: skip
    """Every credit exposure: active loans and mortgages (outstanding principal), commercial
    facilities (drawn, plus half the headroom of a revolving one in use) and overdrawn
    accounts."""
    from app.modules.commercial.models import CommercialFacility, FacilityStatus
    from app.modules.lending.models import Loan, LoanStatus
    from app.modules.lending.servicing import arrears

    out: list[Exposure] = []
    loans = select(Loan).where(Loan.status == LoanStatus.ACTIVE)
    if customer_ids is not None:
        loans = loans.where(Loan.customer_id.in_(customer_ids))
    loan_rows = list(db.execute(loans).scalars())
    ids = [loan.ledger_account_id for loan in loan_rows]
    accounts = list(db.execute(select(LedgerAccount).where(LedgerAccount.id.in_(ids))).scalars())
    outstanding = ledger.balances(db, accounts)
    for loan in loan_rows:
        principal = outstanding.get(loan.ledger_account_id, 0)
        if principal <= 0:
            continue
        months_left = max(loan.term_months - _months_since(loan.disbursed_at.date(), today), 1)
        out.append(Exposure(
            loan.customer_id, "mortgage" if loan.property_id else "loan", loan.loan_number,
            loan.currency, principal, arrears(db, loan, today).days_past_due,
            Decimal(months_left) / 12,
        ))  # fmt: skip
    facilities = select(CommercialFacility).where(CommercialFacility.status.in_(
        [FacilityStatus.ACTIVE, FacilityStatus.FROZEN, FacilityStatus.TERMINATED]))  # fmt: skip
    if customer_ids is not None:
        facilities = facilities.where(CommercialFacility.customer_id.in_(customer_ids))
    for f in db.execute(facilities).scalars():
        revolving = f.facility_type == "revolving" and f.status == FacilityStatus.ACTIVE
        headroom = max(f.credit_limit - f.drawn, 0) if revolving else 0
        ead = f.drawn + int(Decimal(headroom) * UNDRAWN_CCF)
        if ead > 0:
            frozen = f.status == FacilityStatus.FROZEN
            out.append(Exposure(f.customer_id, "facility", f.facility_number, f.currency, ead,
                                0, Decimal(3), frozen=frozen))  # fmt: skip
    overdrawn = (
        select(Account.customer_id, Account.account_number, Account.currency,
               func.sum(LedgerBalance.debit_total - LedgerBalance.credit_total))
        .join(LedgerBalance, LedgerBalance.ledger_account_id == Account.ledger_account_id)
        .where(Account.status != AccountStatus.CLOSED)
        .group_by(Account.customer_id, Account.account_number, Account.currency)
        .having(func.sum(LedgerBalance.debit_total - LedgerBalance.credit_total) > 0)
    )  # fmt: skip
    if customer_ids is not None:
        overdrawn = overdrawn.where(Account.customer_id.in_(customer_ids))
    for customer_id, number, currency, owed in db.execute(overdrawn):
        out.append(Exposure(customer_id, "overdraft", number, currency, int(owed), 0, Decimal(1)))
    return out


def _months_since(start: date, today: date) -> int:
    return max((today.year - start.year) * 12 + today.month - start.month, 0)


# --- Ratings ----------------------------------------------------------------------------------


def suggest_grade(db: Session, customer: Customer, today: date | None = None
                  ) -> tuple[int, dict[str, Any]]:  # fmt: skip
    """The model's grade and what it saw: the KYC risk rating sets the starting grade; 30
    days past due on any loan worsens it by two, 90 puts the customer in default, and a
    facility frozen by a covenant breach worsens it by one."""
    today = _today(today)
    held = exposures(db, today, [customer.id])
    worst = max((e.days_past_due for e in held), default=0)
    frozen = any(e.frozen for e in held)
    grade = KYC_GRADE.get(customer.risk_rating, 6)
    if worst >= 90:
        grade = 10
    else:
        grade = min(grade + (2 if worst >= 30 else 0) + (1 if frozen else 0), 9)
    return grade, {"kyc_risk": customer.risk_rating, "worst_days_past_due": worst,
                   "frozen_facility": frozen, "exposures": len(held)}  # fmt: skip


def rate(db: Session, customer: Customer, grade: int | None, rated_by: uuid.UUID | None,
         rationale: str = "", today: date | None = None) -> CreditRating:  # fmt: skip
    """Rate the customer: the model's grade unless another is given. A grade other than the
    model's waits for someone else's approval (risk:approve)."""
    today = _today(today)
    suggested, factors = suggest_grade(db, customer, today)
    grade = suggested if grade is None else grade
    if grade not in GRADES:
        raise BusinessRuleViolation("The grade is 1 to 10.", {"rule": "grade_range"})
    if grade != suggested and len(rationale.strip()) < 10:
        raise BusinessRuleViolation("Explain a grade that departs from the model's.",
                                    {"rule": "rationale_required"})  # fmt: skip
    status = RatingStatus.APPROVED if grade == suggested else RatingStatus.PENDING
    if status == RatingStatus.PENDING:
        db.execute(select(Customer.id).where(Customer.id == customer.id).with_for_update())
        waiting = db.execute(
            select(CreditRating.rating_number).where(CreditRating.customer_id == customer.id,
                                                     CreditRating.status == RatingStatus.PENDING)
        ).scalar_one_or_none()  # fmt: skip
        if waiting:
            raise ConflictError(f"{waiting} is already awaiting approval for this customer.")
    number = f"RAT-{db.execute(RATING_SEQUENCE.next_value()).scalar_one():07d}"
    rating = CreditRating(
        rating_number=number, customer_id=customer.id, grade=grade, suggested_grade=suggested,
        pd_bps=GRADES[grade][0], factors=factors,
        rationale=(rationale.strip() or "The model's grade")[:300], status=status.value,
        rated_by=rated_by, rated_on=today, expires_on=today + timedelta(days=RATING_VALID_DAYS),
    )  # fmt: skip
    db.add(rating)
    db.flush()
    _audit(db, rated_by, "risk.rated", "credit_rating", rating.id, rating_number=number,
           grade=grade, suggested=suggested, status=rating.status)  # fmt: skip
    return rating


def get_rating(db: Session, rating_id: uuid.UUID, *, for_update: bool = False) -> CreditRating:
    query = select(CreditRating).where(CreditRating.id == rating_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    rating = db.execute(query).scalar_one_or_none()
    if rating is None:
        raise NotFoundError("Rating not found.")
    return rating


def decide_rating(db: Session, rating: CreditRating, actor_id: uuid.UUID,
                  approve: bool) -> CreditRating:  # fmt: skip
    """Approve or reject a rating that departs from the model: not by the person who rated."""
    rating = get_rating(db, rating.id, for_update=True)
    if rating.status != RatingStatus.PENDING:
        raise ConflictError(f"{rating.rating_number} is {rating.status}.")
    if actor_id == rating.rated_by:
        raise BusinessRuleViolation("Four-eyes rule: the person who rated cannot decide.",
                                    {"rule": "four_eyes"})  # fmt: skip
    rating.status = (RatingStatus.APPROVED if approve else RatingStatus.REJECTED).value
    rating.approved_by, rating.decided_at = actor_id, datetime.now(UTC)
    db.flush()
    _audit(db, actor_id, "risk.rating_decided", "credit_rating", rating.id,
           rating_number=rating.rating_number, status=rating.status)  # fmt: skip
    return rating


def current_rating(db: Session, customer_id: uuid.UUID, today: date) -> CreditRating | None:
    rating = db.execute(
        select(CreditRating)
        .where(CreditRating.customer_id == customer_id,
               CreditRating.status == RatingStatus.APPROVED)
        .order_by(func.coalesce(CreditRating.decided_at, CreditRating.created_at).desc(),
                  CreditRating.rating_number.desc()).limit(1)
    ).scalar_one_or_none()  # fmt: skip
    return rating if rating is not None and rating.expires_on > today else None


def grade_of(db: Session, customer: Customer, today: date) -> int:
    """The customer's approved grade, else the model's."""
    rating = current_rating(db, customer.id, today)
    return rating.grade if rating else suggest_grade(db, customer, today)[0]


# --- Limits -----------------------------------------------------------------------------------


def set_limit(db: Session, customer: Customer, limit_usd: int, set_by: uuid.UUID | None,
              note: str = "") -> ObligorLimit:  # fmt: skip
    if limit_usd < 0:
        raise BusinessRuleViolation("A limit cannot be negative.")
    row = db.execute(
        select(ObligorLimit).where(ObligorLimit.customer_id == customer.id).with_for_update()
    ).scalar_one_or_none()  # fmt: skip
    if row is None:
        row = ObligorLimit(customer_id=customer.id, limit_usd=limit_usd)
        db.add(row)
    row.limit_usd, row.set_by = limit_usd, set_by
    row.note, row.updated_at = (note.strip() or None), datetime.now(UTC)
    db.flush()
    _audit(db, set_by, "risk.limit_set", "obligor_limit", row.id,
           customer_id=str(customer.id), limit_usd=limit_usd)  # fmt: skip
    return row


def obligor(db: Session, customer: Customer, today: date | None = None) -> dict[str, Any]:
    """The customer's grade, limit and exposure in US dollars, and any excess."""
    today = _today(today)
    grade = grade_of(db, customer, today)
    custom = db.execute(
        select(ObligorLimit).where(ObligorLimit.customer_id == customer.id)
    ).scalar_one_or_none()  # fmt: skip
    limit = custom.limit_usd if custom else GRADES[grade][1]
    held = exposures(db, today, [customer.id])
    exposure = sum(_usd(db, e.ead, e.currency, today) for e in held)
    return {"customer_number": customer.customer_number, "name": customer.name,
            "grade": grade, "pd_bps": GRADES[grade][0], "limit_usd": limit,
            "limit_source": "set" if custom else "grade", "exposure_usd": exposure,
            "excess_usd": max(exposure - limit, 0),
            "exposures": [{"type": e.exposure_type, "reference": e.reference,
                           "currency": e.currency, "ead": e.ead,
                           "days_past_due": e.days_past_due} for e in held]}  # fmt: skip


def breaches(db: Session, today: date | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """Obligors whose exposure is above their limit, largest excess first."""
    today = _today(today)
    by_customer: dict[uuid.UUID, int] = defaultdict(int)
    for e in exposures(db, today):
        by_customer[e.customer_id] += _usd(db, e.ead, e.currency, today)
    out = []
    for customer_id in by_customer:
        view = obligor(db, db.get(Customer, customer_id), today)
        if view["excess_usd"] > 0:
            out.append({k: v for k, v in view.items() if k != "exposures"})
    out.sort(key=lambda o: -o["excess_usd"])
    return out[:limit]


# --- ECL provisioning -------------------------------------------------------------------------


def stage_of(exposure: Exposure, grade: int) -> int:
    """IFRS 9 stage: 3 when in default (90+ days past due, or grade 10); 2 after a
    significant increase in credit risk (30+ days past due, grade 8 or worse, or a frozen
    facility); otherwise 1."""
    if exposure.days_past_due >= 90 or grade >= 10:
        return 3
    if exposure.days_past_due >= 30 or grade >= 8 or exposure.frozen:
        return 2
    return 1


def ecl_of(exposure: Exposure, grade: int) -> tuple[int, int, int, int]:
    """(stage, PD applied in bps, LGD in bps, ECL in minor units): a year's PD in stage 1,
    lifetime (the year's PD times the remaining years, at most five, capped at 100 %) in
    stage 2, certain default in stage 3."""
    stage = stage_of(exposure, grade)
    pd = GRADES[grade][0]
    if stage == 3:
        pd = 10_000
    elif stage == 2:
        years = min(max(exposure.remaining_years, Decimal(1)), Decimal(MAX_LIFETIME_YEARS))
        pd = min(int(pd * years), 10_000)
    lgd = LGD_BPS[exposure.exposure_type]
    ecl = int(Decimal(exposure.ead) * pd * lgd / 100_000_000)
    return stage, pd, lgd, ecl


def allowance_account(db: Session, currency: str) -> LedgerAccount:
    """The loss allowance (credit balance against the loan book)."""
    return ledger.ensure_ledger_account(
        db, code=f"RISK-ALLOWANCE-{currency}", name=f"Loan loss allowance ({currency})",
        account_type=LedgerAccountType.LIABILITY, currency=currency,
    )  # fmt: skip


def impairment_account(db: Session, currency: str) -> LedgerAccount:
    return ledger.ensure_ledger_account(
        db, code=f"RISK-IMPAIRMENT-{currency}", name=f"Impairment charge ({currency})",
        account_type=LedgerAccountType.EXPENSE, currency=currency,
    )  # fmt: skip


def calculate(db: Session, calculated_by: uuid.UUID, today: date | None = None) -> ProvisionRun:
    """Measure the loan book's ECL as of today: one line per exposure, totals by currency
    with the change against the allowance already booked. Nothing is posted yet."""
    today = _today(today)
    number = f"PRV-{db.execute(PROVISION_SEQUENCE.next_value()).scalar_one():07d}"
    run = ProvisionRun(run_number=number, as_of=today, status=ProvisionStatus.CALCULATED.value,
                       exposures=0, totals={}, calculated_by=calculated_by)  # fmt: skip
    db.add(run)
    db.flush()
    grades: dict[uuid.UUID, int] = {}
    totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {"stage_1": 0, "stage_2": 0, "stage_3": 0, "ecl": 0, "ead": 0}
    )
    for e in exposures(db, today):
        if e.customer_id not in grades:
            grades[e.customer_id] = grade_of(db, db.get(Customer, e.customer_id), today)
        grade = grades[e.customer_id]
        stage, pd, lgd, ecl = ecl_of(e, grade)
        db.add(ProvisionLine(run_id=run.id, customer_id=e.customer_id,
                             exposure_type=e.exposure_type, reference=e.reference,
                             currency=e.currency, ead=e.ead, days_past_due=e.days_past_due,
                             grade=grade, stage=stage, pd_bps=pd, lgd_bps=lgd,
                             ecl=ecl))  # fmt: skip
        t = totals[e.currency]
        t[f"stage_{stage}"] += ecl
        t["ecl"] += ecl
        t["ead"] += e.ead
        run.exposures += 1
    # A currency with an allowance but no exposure left is measured at zero, so posting
    # releases it.
    for currency in _allowance_currencies(db):
        totals[currency]  # noqa: B018 - the defaultdict creates the zero totals
    for currency, t in totals.items():
        t["previous"] = ledger.balance(db, allowance_account(db, currency))
        t["change"] = t["ecl"] - t["previous"]
    run.totals = dict(totals)
    db.flush()
    _audit(db, calculated_by, "risk.provision_calculated", "provision_run", run.id,
           run_number=number, exposures=run.exposures)  # fmt: skip
    return run


def _allowance_currencies(db: Session) -> list[str]:
    return list(db.execute(
        select(LedgerAccount.currency).where(LedgerAccount.code.like("RISK-ALLOWANCE-%"))
    ).scalars())  # fmt: skip


def get_run(db: Session, run_id: uuid.UUID, *, for_update: bool = False) -> ProvisionRun:
    query = select(ProvisionRun).where(ProvisionRun.id == run_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    run = db.execute(query).scalar_one_or_none()
    if run is None:
        raise NotFoundError("Provision run not found.")
    return run


def find_run(db: Session, number: str) -> ProvisionRun | None:
    return db.execute(
        select(ProvisionRun).where(ProvisionRun.run_number == number.strip().upper())
    ).scalar_one_or_none()


def _decide_run(db: Session, run: ProvisionRun, actor_id: uuid.UUID) -> ProvisionRun:
    run = get_run(db, run.id, for_update=True)
    if run.status != ProvisionStatus.CALCULATED:
        raise ConflictError(f"{run.run_number} is {run.status}.")
    if actor_id == run.calculated_by:
        raise BusinessRuleViolation("Four-eyes rule: the person who calculated the run cannot "
                                    "decide it.", {"rule": "four_eyes"})  # fmt: skip
    return run


def post_run(db: Session, run: ProvisionRun, actor_id: uuid.UUID) -> ProvisionRun:
    """Bring each currency's loss allowance to the run's ECL: the change is charged to (or
    released from) impairment. Not by the person who calculated it, and only the latest run:
    one calculated after it (by date, then creation) already posted is refused."""
    # One posting at a time: each reads the allowance it moves.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('risk-provision-post'))"))
    run = _decide_run(db, run, actor_id)
    order = tuple_(ProvisionRun.as_of, ProvisionRun.created_at, ProvisionRun.run_number)
    newer = db.execute(
        select(func.count()).select_from(ProvisionRun)
        .where(ProvisionRun.status == ProvisionStatus.POSTED,
               order > tuple_(run.as_of, run.created_at, run.run_number))
    ).scalar_one()  # fmt: skip
    if newer:
        raise BusinessRuleViolation("A later provision run is already posted.",
                                    {"rule": "superseded"})  # fmt: skip
    totals = dict(run.totals)
    for currency, t in sorted(totals.items()):
        allowance = allowance_account(db, currency)
        previous = ledger.balance(db, allowance)
        change = t["ecl"] - previous
        t = {**t, "previous": previous, "change": change}
        totals[currency] = t
        if change == 0:
            continue
        expense = impairment_account(db, currency)
        debit, credit = (expense, allowance) if change > 0 else (allowance, expense)
        memo = f"{run.run_number} ECL as of {run.as_of}"
        ledger.post_entry(
            db, idempotency_key=f"risk-provision:{run.run_number}:{currency}", currency=currency,
            description=memo, source="risk",
            lines=[ledger.LineSpec(debit.id, Direction.DEBIT, abs(change), memo),
                   ledger.LineSpec(credit.id, Direction.CREDIT, abs(change), memo)],
            actor_id=actor_id, effective_date=run.as_of,
        )  # fmt: skip
    run.totals = totals
    run.status, run.approved_by = ProvisionStatus.POSTED.value, actor_id
    run.decided_at = datetime.now(UTC)
    db.flush()
    _audit(db, actor_id, "risk.provision_posted", "provision_run", run.id,
           run_number=run.run_number)  # fmt: skip
    return run


def reject_run(db: Session, run: ProvisionRun, actor_id: uuid.UUID, note: str) -> ProvisionRun:
    run = _decide_run(db, run, actor_id)
    run.status, run.approved_by = ProvisionStatus.REJECTED.value, actor_id
    run.note, run.decided_at = (note.strip() or "Not approved")[:200], datetime.now(UTC)
    db.flush()
    _audit(db, actor_id, "risk.provision_rejected", "provision_run", run.id,
           run_number=run.run_number, note=run.note)  # fmt: skip
    return run


def summary(db: Session) -> dict[str, Any]:
    def count(model, *where) -> int:
        return db.execute(select(func.count()).select_from(model).where(*where)).scalar_one()

    latest = db.execute(
        select(ProvisionRun).where(ProvisionRun.status == ProvisionStatus.POSTED)
        .order_by(ProvisionRun.as_of.desc(), ProvisionRun.created_at.desc()).limit(1)
    ).scalar_one_or_none()  # fmt: skip
    return {
        "ratings_pending": count(CreditRating, CreditRating.status == RatingStatus.PENDING),
        "ratings": count(CreditRating, CreditRating.status == RatingStatus.APPROVED),
        "runs_to_approve": count(ProvisionRun,
                                 ProvisionRun.status == ProvisionStatus.CALCULATED),
        "last_posted_run": latest.run_number if latest else None,
        "last_posted_as_of": latest.as_of.isoformat() if latest else None,
    }  # fmt: skip
