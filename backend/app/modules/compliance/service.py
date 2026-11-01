"""Compliance services (Phase 45): transaction monitoring, alerts, cases, suspicious activity
reports and periodic KYC reviews."""

import uuid
from collections import defaultdict
from collections.abc import Collection
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, case, func, literal, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.core.money import minor_unit_exponent
from app.modules.accounts.models import Account, AccountStatus
from app.modules.compliance.models import (
    ALERT_SEQUENCE,
    CASE_SEQUENCE,
    REVIEW_SEQUENCE,
    RUN_SEQUENCE,
    SAR_SEQUENCE,
    AlertStatus,
    AmlAlert,
    CaseStatus,
    ComplianceCase,
    KycReview,
    MonitoringRun,
    ReviewStatus,
    SarStatus,
    SuspiciousActivityReport,
)
from app.modules.customers.models import Customer, KycStatus, RiskRating
from app.modules.fx import rates
from app.modules.ledger.models import Direction, JournalEntry, JournalLine

REPORTING_THRESHOLD_USD = 10_000  # the cash reporting threshold, converted per currency
NEAR_THRESHOLD = Decimal("0.8")  # structuring: deposits of 80-100 % of the threshold
STRUCTURING_COUNT = 3  # ... at least this many ...
STRUCTURING_DAYS = 10  # ... within this many days
PASS_THROUGH_SHARE = Decimal("0.8")  # rapid movement: this share of the money in goes out
RULE_SCORES = {"large_cash": 40, "structuring": 70, "rapid_movement": 60,
               "high_risk_turnover": 50}  # fmt: skip
# Periodic KYC review interval by risk rating (days).
REVIEW_INTERVAL_DAYS = {"high": 365, "medium": 730, "low": 1095}
OPEN_ALERTS = (AlertStatus.OPEN, AlertStatus.IN_CASE)


def _audit(db, actor_id, action: str, entity_type: str, entity_id, **metadata) -> None:
    record_audit_event(db, actor_id=actor_id, action=action, entity_type=entity_type,
                       entity_id=entity_id, metadata=metadata)  # fmt: skip


def _today(today: date | None) -> date:
    return today or datetime.now(UTC).date()


def threshold(currency: str) -> int:
    """The reporting threshold in minor units of `currency`, at the FX anchor rate."""
    units = Decimal(REPORTING_THRESHOLD_USD) * rates.units_per_usd(currency, rates.ANCHOR_DATE)
    return int(units * 10 ** minor_unit_exponent(currency))


# --- Transaction monitoring -------------------------------------------------------------------


def evaluate(activity: dict[str, Any], currency: str, risk_rating: str) -> list[dict[str, Any]]:
    """The rules one account breaks, from its activity in the window: `deposits` [(date,
    amount)] of cash, and `credits` and `debits` totals. Pure: no database."""
    limit = threshold(currency)
    deposits = sorted(activity["deposits"])
    credits, debits = activity["credits"], activity["debits"]
    hits = []
    large = [(d, a) for d, a in deposits if a >= limit]
    if large:
        hits.append({"rule": "large_cash", "score": min(RULE_SCORES["large_cash"] + 10 * len(large),
                                                        100),
                     "amount": sum(a for _, a in large),
                     "details": {"deposits": [[d.isoformat(), a] for d, a in large]}})  # fmt: skip
    near = [(d, a) for d, a in deposits if limit * NEAR_THRESHOLD <= a < limit]
    best: list[tuple[date, int]] = []
    for i, (start, _) in enumerate(near):
        span = [x for x in near[i:] if (x[0] - start).days < STRUCTURING_DAYS]
        best = span if len(span) > len(best) else best
    if len(best) >= STRUCTURING_COUNT:
        hits.append({"rule": "structuring",
                     "score": min(RULE_SCORES["structuring"] + 5 * (len(best) - STRUCTURING_COUNT),
                                  100),
                     "amount": sum(a for _, a in best),
                     "details": {"deposits": [[d.isoformat(), a] for d, a in best]}})  # fmt: skip
    if credits >= 2 * limit and debits >= credits * PASS_THROUGH_SHARE:
        hits.append({"rule": "rapid_movement", "score": RULE_SCORES["rapid_movement"],
                     "amount": debits, "details": {}})  # fmt: skip
    if risk_rating == RiskRating.HIGH and credits >= 5 * limit:
        hits.append({"rule": "high_risk_turnover", "score": RULE_SCORES["high_risk_turnover"],
                     "amount": credits, "details": {}})  # fmt: skip
    for hit in hits:
        hit["details"].update({"credits": credits, "debits": debits, "threshold": limit})
    return hits


def run_monitoring(db: Session, *, window_end: date | None = None, days: int = 30,
                   actor_id: uuid.UUID | None = None,
                   account_ids: Collection[uuid.UUID] | None = None) -> MonitoringRun:  # fmt: skip
    """Read every open or frozen customer account's ledger activity in the `days` up to
    `window_end` (or only `account_ids`) and raise an alert for each rule broken. An account
    with an open or investigated alert for a rule gets no second one for it."""
    window_end = _today(window_end)
    window_start = window_end - timedelta(days=days - 1)
    query = (
        select(Account.id, Account.customer_id, Account.currency, JournalEntry.source,
               JournalEntry.effective_date, JournalLine.direction, JournalLine.amount)
        .join(JournalLine, JournalLine.ledger_account_id == Account.ledger_account_id)
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
        .where(JournalEntry.effective_date.between(window_start, window_end),
               Account.status != AccountStatus.CLOSED)
    )  # fmt: skip
    if account_ids is not None:
        query = query.where(Account.id.in_(list(account_ids)))
    activity: dict[uuid.UUID, dict[str, Any]] = defaultdict(
        lambda: {"deposits": [], "credits": 0, "debits": 0}
    )
    owners: dict[uuid.UUID, tuple[uuid.UUID, str]] = {}
    for account_id, customer_id, currency, source, on, direction, amount in db.execute(query):
        owners[account_id] = (customer_id, currency)
        a = activity[account_id]
        if direction == Direction.CREDIT:
            a["credits"] += amount
            if source == "deposit":
                a["deposits"].append((on, amount))
        else:
            a["debits"] += amount
    number = f"MON-{db.execute(RUN_SEQUENCE.next_value()).scalar_one():07d}"
    run = MonitoringRun(run_number=number, window_start=window_start, window_end=window_end,
                        accounts_scanned=len(activity), alerts_raised=0,
                        run_by=actor_id)  # fmt: skip
    db.add(run)
    db.flush()
    risk = dict(db.execute(
        select(Customer.id, Customer.risk_rating)
        .where(Customer.id.in_({c for c, _ in owners.values()}))
    ).tuples().all()) if owners else {}  # fmt: skip
    # Skipped: an open or investigated alert for the rule, or any alert for the same window
    # (a resolved one is not raised again on a rerun: PR #36 review).
    open_rules = set(db.execute(
        select(AmlAlert.account_id, AmlAlert.rule)
        .where(AmlAlert.account_id.in_(list(owners)),
               AmlAlert.status.in_(OPEN_ALERTS) | (AmlAlert.window_end == window_end))
    ).tuples().all()) if owners else set()  # fmt: skip
    for account_id in sorted(activity, key=str):
        customer_id, currency = owners[account_id]
        for hit in evaluate(activity[account_id], currency, risk.get(customer_id, "low")):
            if (account_id, hit["rule"]) in open_rules:
                continue
            alert_no = f"ALR-{db.execute(ALERT_SEQUENCE.next_value()).scalar_one():07d}"
            db.add(AmlAlert(alert_number=alert_no, run_id=run.id, customer_id=customer_id,
                            account_id=account_id, rule=hit["rule"], score=hit["score"],
                            currency=currency, amount=hit["amount"], details=hit["details"],
                            window_start=window_start, window_end=window_end,
                            status=AlertStatus.OPEN.value))  # fmt: skip
            run.alerts_raised += 1
    db.flush()
    _audit(db, actor_id, "compliance.monitoring_run", "monitoring_run", run.id,
           run_number=number, accounts=run.accounts_scanned, alerts=run.alerts_raised)  # fmt: skip
    return run


def get_alert(db: Session, alert_id: uuid.UUID, *, for_update: bool = False) -> AmlAlert:
    query = select(AmlAlert).where(AmlAlert.id == alert_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    alert = db.execute(query).scalar_one_or_none()
    if alert is None:
        raise NotFoundError("Alert not found.")
    return alert


def find_alert(db: Session, number: str) -> AmlAlert | None:
    return db.execute(
        select(AmlAlert).where(AmlAlert.alert_number == number.strip().upper())
    ).scalar_one_or_none()


def find_open_alert(db: Session, account_id: uuid.UUID, rule: str) -> AmlAlert | None:
    return db.execute(
        select(AmlAlert).where(AmlAlert.account_id == account_id, AmlAlert.rule == rule,
                               AmlAlert.status == AlertStatus.OPEN)
    ).scalar_one_or_none()  # fmt: skip


def dismiss_alert(db: Session, alert: AmlAlert, actor_id: uuid.UUID, note: str) -> AmlAlert:
    """Close an open alert as a false positive, without a case."""
    alert = get_alert(db, alert.id, for_update=True)
    if alert.status != AlertStatus.OPEN:
        raise ConflictError(f"{alert.alert_number} is {alert.status}.")
    alert.status, alert.note = AlertStatus.DISMISSED.value, (note.strip() or "False positive")[:200]
    db.flush()
    _audit(db, actor_id, "compliance.alert_dismissed", "aml_alert", alert.id,
           alert_number=alert.alert_number, note=alert.note)  # fmt: skip
    return alert


def alert_profile(db: Session, alert: AmlAlert, today: date | None = None) -> dict[str, Any]:
    """What an investigating officer weighs before closing an alert's case with no action
    (Phase 46): the rule and its score, the amount against the threshold, the customer's type
    and risk rating, the window's money in against the account's own baseline (the average
    month of the 90 days before the window), and the customer's earlier alerts and filed
    reports in the last 365 days."""
    today = _today(today)
    customer = db.get(Customer, alert.customer_id)
    account = db.get(Account, alert.account_id)
    limit = threshold(alert.currency)
    base_end = alert.window_start - timedelta(days=1)
    base_start = base_end - timedelta(days=89)
    baseline = db.execute(
        select(func.coalesce(func.sum(JournalLine.amount), 0))
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
        .where(JournalLine.ledger_account_id == account.ledger_account_id,
               JournalLine.direction == Direction.CREDIT,
               JournalEntry.effective_date.between(base_start, base_end))
    ).scalar_one()  # fmt: skip
    monthly = int(baseline) * 30 // 90
    credits = int(alert.details.get("credits", 0))
    since = today - timedelta(days=365)
    earlier = db.execute(
        select(func.count()).select_from(AmlAlert)
        .where(AmlAlert.customer_id == alert.customer_id, AmlAlert.id != alert.id,
               AmlAlert.window_end >= since, AmlAlert.window_end < alert.window_end)
    ).scalar_one()  # fmt: skip
    filed = db.execute(
        select(func.count()).select_from(SuspiciousActivityReport)
        .where(SuspiciousActivityReport.customer_id == alert.customer_id,
               SuspiciousActivityReport.status == SarStatus.FILED)
    ).scalar_one()  # fmt: skip
    return {
        "rule": alert.rule, "score": alert.score, "currency": alert.currency,
        "amount": alert.amount, "amount_x_threshold_pct": alert.amount * 100 // max(limit, 1),
        "deposits": len(alert.details.get("deposits", [])),
        "customer_type": customer.customer_type, "customer_risk": customer.risk_rating,
        "credits": credits, "baseline_monthly_credits": monthly,
        "activity_vs_baseline_pct": min(credits * 100 // max(monthly, 1), 99_999),
        "prior_alerts_365d": earlier, "prior_reports_filed": filed,
    }  # fmt: skip


# --- Cases ------------------------------------------------------------------------------------


def get_case(db: Session, case_id: uuid.UUID, *, for_update: bool = False) -> ComplianceCase:
    query = select(ComplianceCase).where(ComplianceCase.id == case_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    found = db.execute(query).scalar_one_or_none()
    if found is None:
        raise NotFoundError("Case not found.")
    return found


def find_case(db: Session, number: str) -> ComplianceCase | None:
    return db.execute(
        select(ComplianceCase).where(ComplianceCase.case_number == number.strip().upper())
    ).scalar_one_or_none()


def case_alerts(db: Session, case_row: ComplianceCase) -> list[AmlAlert]:
    return list(db.execute(
        select(AmlAlert).where(AmlAlert.case_id == case_row.id).order_by(AmlAlert.alert_number)
    ).scalars())  # fmt: skip


def open_case(db: Session, alert: AmlAlert, opened_by: uuid.UUID) -> ComplianceCase:
    """Investigate an alert: a case for its customer, taking in every open alert of theirs.
    If a case is being investigated for the customer, the alerts join it; while one has a
    drafted report, new alerts wait until it is filed."""
    # The customer is locked first, so two officers investigating the same customer's alerts
    # take their locks in one order and cannot deadlock (PR #36 review).
    db.execute(select(Customer.id).where(Customer.id == alert.customer_id).with_for_update())
    alert = get_alert(db, alert.id, for_update=True)
    if alert.status != AlertStatus.OPEN:
        raise ConflictError(f"{alert.alert_number} is {alert.status}.")
    existing = db.execute(
        select(ComplianceCase).where(
            ComplianceCase.customer_id == alert.customer_id,
            ComplianceCase.status.in_([CaseStatus.INVESTIGATING, CaseStatus.SAR_DRAFTED]))
        .with_for_update()
    ).scalar_one_or_none()  # fmt: skip
    if existing is not None and existing.status == CaseStatus.SAR_DRAFTED:
        # Its report is drafted and would not cover the new alert (PR #36 review).
        raise BusinessRuleViolation(
            f"{existing.case_number}'s report is drafted; investigate this alert once it is filed.",
            {"rule": "report_pending", "case_number": existing.case_number},
        )
    if existing is None:
        number = f"CASE-{db.execute(CASE_SEQUENCE.next_value()).scalar_one():07d}"
        existing = ComplianceCase(case_number=number, customer_id=alert.customer_id,
                                  status=CaseStatus.INVESTIGATING.value,
                                  opened_by=opened_by)  # fmt: skip
        db.add(existing)
        db.flush()
        _audit(db, opened_by, "compliance.case_opened", "compliance_case", existing.id,
               case_number=number)  # fmt: skip
    for row in db.execute(
        select(AmlAlert).where(AmlAlert.customer_id == alert.customer_id,
                               AmlAlert.status == AlertStatus.OPEN).with_for_update()
    ).scalars():  # fmt: skip
        row.status, row.case_id = AlertStatus.IN_CASE.value, existing.id
    db.flush()
    return existing


def close_case(db: Session, case_row: ComplianceCase, closed_by: uuid.UUID,
               note: str) -> ComplianceCase:  # fmt: skip
    """Close a case with no action: not by the investigator who opened it."""
    case_row = get_case(db, case_row.id, for_update=True)
    if case_row.status != CaseStatus.INVESTIGATING:
        raise ConflictError(f"{case_row.case_number} is {case_row.status}.")
    if closed_by == case_row.opened_by:
        raise BusinessRuleViolation("Four-eyes rule: the investigator cannot close their own "
                                    "case.", {"rule": "four_eyes"})  # fmt: skip
    case_row.status, case_row.closed_by = CaseStatus.CLOSED.value, closed_by
    case_row.note, case_row.closed_at = (note.strip() or "No action")[:200], datetime.now(UTC)
    for alert in case_alerts(db, case_row):
        alert.status = AlertStatus.CLOSED.value
    db.flush()
    _audit(db, closed_by, "compliance.case_closed", "compliance_case", case_row.id,
           case_number=case_row.case_number, note=case_row.note)  # fmt: skip
    return case_row


# --- Suspicious activity reports --------------------------------------------------------------


def case_sar(db: Session, case_row: ComplianceCase) -> SuspiciousActivityReport | None:
    return db.execute(
        select(SuspiciousActivityReport).where(SuspiciousActivityReport.case_id == case_row.id)
    ).scalar_one_or_none()


def draft_sar(db: Session, case_row: ComplianceCase, prepared_by: uuid.UUID,
              narrative: str = "") -> SuspiciousActivityReport:  # fmt: skip
    """Escalate a case: a report drafted from its alerts (or the narrative given)."""
    case_row = get_case(db, case_row.id, for_update=True)
    if case_row.status != CaseStatus.INVESTIGATING:
        raise ConflictError(f"{case_row.case_number} is {case_row.status}.")
    alerts = case_alerts(db, case_row)
    customer = db.get(Customer, case_row.customer_id)
    summary = "; ".join(f"{a.alert_number} {a.rule.replace('_', ' ')} "
                        f"({a.amount} {a.currency} minor units)" for a in alerts)  # fmt: skip
    text_ = narrative.strip() or (
        f"{customer.name} ({customer.customer_number}): activity flagged by transaction "
        f"monitoring and investigated in {case_row.case_number}: {summary}."
    )
    currencies = {a.currency for a in alerts}
    number = f"SAR-{db.execute(SAR_SEQUENCE.next_value()).scalar_one():07d}"
    sar = SuspiciousActivityReport(
        sar_number=number, case_id=case_row.id, customer_id=case_row.customer_id,
        narrative=text_, currency=currencies.pop() if len(currencies) == 1 else "XXX",
        amount=sum(a.amount for a in alerts) if len({a.currency for a in alerts}) == 1 else 0,
        status=SarStatus.DRAFT.value, prepared_by=prepared_by,
    )  # fmt: skip
    db.add(sar)
    case_row.status = CaseStatus.SAR_DRAFTED.value
    db.flush()
    _audit(db, prepared_by, "compliance.sar_drafted", "suspicious_activity_report", sar.id,
           sar_number=number, case_number=case_row.case_number)  # fmt: skip
    return sar


def get_sar(db: Session, sar_id: uuid.UUID, *, for_update: bool = False):
    query = select(SuspiciousActivityReport).where(SuspiciousActivityReport.id == sar_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    sar = db.execute(query).scalar_one_or_none()
    if sar is None:
        raise NotFoundError("Report not found.")
    return sar


def file_sar(db: Session, sar: SuspiciousActivityReport, filed_by: uuid.UUID,
             today: date | None = None) -> SuspiciousActivityReport:  # fmt: skip
    """File the report with the (synthetic) financial intelligence unit: not by the officer
    who prepared it. The customer is rated high risk from then on."""
    from app.modules.customers.schemas import CustomerReview
    from app.modules.customers.service import review_customer

    sar = get_sar(db, sar.id, for_update=True)
    if sar.status != SarStatus.DRAFT:
        raise ConflictError(f"{sar.sar_number} is {sar.status}.")
    if filed_by == sar.prepared_by:
        raise BusinessRuleViolation("Four-eyes rule: the officer who prepared the report "
                                    "cannot file it.", {"rule": "four_eyes"})  # fmt: skip
    today = _today(today)
    sar.status, sar.filed_by, sar.filed_at = SarStatus.FILED.value, filed_by, datetime.now(UTC)
    sar.filing_reference = f"FIU-{today.year}-{sar.sar_number[4:]}"
    case_row = get_case(db, sar.case_id, for_update=True)
    case_row.status, case_row.closed_at = CaseStatus.SAR_FILED.value, datetime.now(UTC)
    for alert in case_alerts(db, case_row):
        alert.status = AlertStatus.ESCALATED.value
    customer = db.get(Customer, sar.customer_id)
    if customer.risk_rating != RiskRating.HIGH:
        review_customer(db, customer, CustomerReview(risk_rating=RiskRating.HIGH), filed_by)
    db.flush()
    _audit(db, filed_by, "compliance.sar_filed", "suspicious_activity_report", sar.id,
           sar_number=sar.sar_number, filing_reference=sar.filing_reference)  # fmt: skip
    return sar


# --- Periodic KYC reviews ---------------------------------------------------------------------


def _last_reviewed():
    """Per customer: the date of their last completed review, else when they joined."""
    completed = (
        select(KycReview.customer_id, func.max(KycReview.completed_on).label("on"))
        .where(KycReview.status == ReviewStatus.COMPLETED)
        .group_by(KycReview.customer_id)
        .subquery()
    )
    interval = case(*((Customer.risk_rating == rating, literal(days))
                      for rating, days in REVIEW_INTERVAL_DAYS.items()), else_=None)  # fmt: skip
    last = func.coalesce(completed.c.on, func.date(Customer.created_at))
    return completed, interval, last


def schedule_reviews(db: Session, today: date | None = None, *, horizon_days: int = 30,
                     actor_id: uuid.UUID | None = None, limit: int = 1000) -> int:  # fmt: skip
    """Open a review for each verified, rated customer whose next review falls due within
    `horizon_days` and who has none open; returns how many were opened (at most `limit`)."""
    today = _today(today)
    completed, interval, last = _last_reviewed()
    due_on = last + interval
    open_review = select(KycReview.id).where(KycReview.customer_id == Customer.id,
                                             KycReview.status == ReviewStatus.DUE)  # fmt: skip
    rows = db.execute(
        select(Customer.id, Customer.risk_rating, due_on.label("due_on"))
        .outerjoin(completed, completed.c.customer_id == Customer.id)
        .where(Customer.kyc_status == KycStatus.VERIFIED, interval.is_not(None),
               due_on <= today + timedelta(days=horizon_days), ~open_review.exists())
        .order_by(due_on, Customer.id)
        .limit(limit)
    ).all()  # fmt: skip
    for customer_id, rating, due in rows:
        number = f"KYR-{db.execute(REVIEW_SEQUENCE.next_value()).scalar_one():07d}"
        db.add(KycReview(review_number=number, customer_id=customer_id, due_on=due,
                         status=ReviewStatus.DUE.value, risk_before=rating))  # fmt: skip
    db.flush()
    if rows:
        _audit(db, actor_id, "compliance.kyc_reviews_scheduled", "kyc_review", None,
               count=len(rows), horizon_days=horizon_days)  # fmt: skip
    return len(rows)


def open_review(db: Session, customer: Customer, today: date | None = None) -> KycReview:
    """The customer's open review, or a new one due today."""
    today = _today(today)
    found = db.execute(
        select(KycReview).where(KycReview.customer_id == customer.id,
                                KycReview.status == ReviewStatus.DUE)
    ).scalar_one_or_none()  # fmt: skip
    if found is not None:
        return found
    if customer.kyc_status != KycStatus.VERIFIED or customer.risk_rating == RiskRating.UNRATED:
        raise BusinessRuleViolation("Only verified, rated customers have periodic reviews.",
                                    {"rule": "not_reviewable"})  # fmt: skip
    number = f"KYR-{db.execute(REVIEW_SEQUENCE.next_value()).scalar_one():07d}"
    review = KycReview(review_number=number, customer_id=customer.id, due_on=today,
                       status=ReviewStatus.DUE.value, risk_before=customer.risk_rating)  # fmt: skip
    db.add(review)
    db.flush()
    return review


def get_review(db: Session, review_id: uuid.UUID, *, for_update: bool = False) -> KycReview:
    query = select(KycReview).where(KycReview.id == review_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    review = db.execute(query).scalar_one_or_none()
    if review is None:
        raise NotFoundError("Review not found.")
    return review


RISK_ORDER = {"low": 1, "medium": 2, "high": 3}


def complete_review(db: Session, review: KycReview, completed_by: uuid.UUID, risk_rating: str,
                    note: str = "", today: date | None = None) -> KycReview:  # fmt: skip
    """Record the review's outcome: the customer's risk rating confirmed, raised or
    lowered. The next review falls due by the new rating."""
    from app.modules.customers.schemas import CustomerReview
    from app.modules.customers.service import review_customer

    review = get_review(db, review.id, for_update=True)
    if review.status != ReviewStatus.DUE:
        raise ConflictError(f"{review.review_number} is {review.status}.")
    if risk_rating not in RISK_ORDER:
        raise BusinessRuleViolation("The risk rating is low, medium or high.")
    customer = db.get(Customer, review.customer_id)
    before = customer.risk_rating
    if risk_rating != before:
        review_customer(db, customer, CustomerReview(risk_rating=RiskRating(risk_rating)),
                        completed_by)  # fmt: skip
    change = RISK_ORDER[risk_rating] - RISK_ORDER.get(before, 0)
    review.outcome = "confirmed" if change == 0 else ("raised" if change > 0 else "lowered")
    review.status, review.risk_after = ReviewStatus.COMPLETED.value, risk_rating
    review.completed_by, review.completed_on = completed_by, _today(today)
    review.note = (note.strip() or None) and note.strip()[:200]
    db.flush()
    _audit(db, completed_by, "compliance.kyc_review_completed", "kyc_review", review.id,
           review_number=review.review_number, outcome=review.outcome)  # fmt: skip
    return review


def summary(db: Session, today: date | None = None) -> dict[str, Any]:
    today = _today(today)

    def count(model, *where) -> int:
        return db.execute(select(func.count()).select_from(model).where(*where)).scalar_one()

    return {
        "open_alerts": count(AmlAlert, AmlAlert.status == AlertStatus.OPEN),
        "open_cases": count(ComplianceCase, ComplianceCase.status.in_(
            [CaseStatus.INVESTIGATING, CaseStatus.SAR_DRAFTED])),
        "draft_sars": count(SuspiciousActivityReport,
                            SuspiciousActivityReport.status == SarStatus.DRAFT),
        "filed_sars": count(SuspiciousActivityReport,
                            SuspiciousActivityReport.status == SarStatus.FILED),
        "reviews_due": count(KycReview, KycReview.status == ReviewStatus.DUE),
        "reviews_overdue": count(KycReview, and_(KycReview.status == ReviewStatus.DUE,
                                                 KycReview.due_on < today)),
    }  # fmt: skip
