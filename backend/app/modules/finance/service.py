"""Finance services (Phase 49): month-end close, regulatory reporting extracts and cost
allocation."""

import csv
import io
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.modules.customers.models import Customer
from app.modules.employees.models import Employee
from app.modules.finance.models import (
    ALLOCATION_SEQUENCE,
    CLOSE_SEQUENCE,
    JOURNAL_SEQUENCE,
    REPORT_SEQUENCE,
    AllocationStatus,
    CloseStatus,
    CostAllocation,
    JournalStatus,
    ManualJournal,
    PeriodClose,
    RegulatoryReport,
    ReportStatus,
    ReportType,
)
from app.modules.ledger import service as ledger
from app.modules.ledger.models import (
    DEBIT_NORMAL,
    Direction,
    JournalEntry,
    JournalLine,
    LedgerAccount,
    LedgerAccountType,
    LedgerReconciliation,
    ReconciliationMode,
)
from app.modules.organizations.models import Organization

RESULT_TYPES = (LedgerAccountType.INCOME, LedgerAccountType.EXPENSE)
BALANCE_TYPES = (LedgerAccountType.ASSET, LedgerAccountType.LIABILITY, LedgerAccountType.EQUITY)
LARGE_EXPOSURE_USD = 10_000  # obligors at or above this are reported
LARGE_EXPOSURE_ROWS = 50
MATERIALITY_USD = 100_000  # a manual journal at or above this is material
STALE_DAYS = 31  # a manual journal dated further back than this is stale


def _audit(db, actor_id, action: str, entity_type: str, entity_id, **metadata) -> None:
    record_audit_event(db, actor_id=actor_id, action=action, entity_type=entity_type,
                       entity_id=entity_id, metadata=metadata)  # fmt: skip


def _today(today: date | None) -> date:
    return today or datetime.now(UTC).date()


def period_bounds(period: str) -> tuple[date, date]:
    """'YYYY-MM' -> (first day, last day)."""
    try:
        year, month = (int(p) for p in period.split("-"))
        start = date(year, month, 1)
    except (ValueError, TypeError):
        raise BusinessRuleViolation(
            "A period is a month: YYYY-MM.", {"rule": "period_format"}
        ) from None
    if len(period) != 7:
        raise BusinessRuleViolation("A period is a month: YYYY-MM.", {"rule": "period_format"})
    following = date(year + month // 12, month % 12 + 1, 1)
    return start, following - timedelta(days=1)


def balances_as_of(db: Session, types, end: date, start: date | None = None
                   ) -> list[dict[str, Any]]:  # fmt: skip
    """Each account of `types` with its balance (on its normal side) from the lines of entries
    effective up to `end` (and from `start`, if given). Accounts with no such lines are left
    out."""
    signed = case((JournalLine.direction == Direction.DEBIT, JournalLine.amount),
                  else_=-JournalLine.amount)  # fmt: skip
    query = (
        select(LedgerAccount.code, LedgerAccount.account_type, LedgerAccount.currency,
               LedgerAccount.id, func.sum(signed))
        .join(JournalLine, JournalLine.ledger_account_id == LedgerAccount.id)
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
        .where(LedgerAccount.account_type.in_([str(t) for t in types]),
               JournalEntry.effective_date <= end)
        .group_by(LedgerAccount.id)
    )  # fmt: skip
    if start is not None:
        query = query.where(JournalEntry.effective_date >= start)
    out = []
    for code, account_type, currency, account_id, debit_minus_credit in db.execute(query):
        amount = int(debit_minus_credit)
        if account_type not in DEBIT_NORMAL:
            amount = -amount
        out.append({"code": code, "type": account_type, "currency": currency,
                    "account_id": account_id, "balance": amount})  # fmt: skip
    out.sort(key=lambda a: (a["currency"], a["type"], a["code"]))
    return out


def _results(db: Session, end: date) -> dict[str, dict[str, Any]]:
    """Each currency's income and expense not yet closed, as of `end`."""
    out: dict[str, dict[str, Any]] = {}
    for a in balances_as_of(db, RESULT_TYPES, end):
        r = out.setdefault(a["currency"], {"income": 0, "expense": 0, "net_income": 0,
                                           "accounts": []})  # fmt: skip
        r[a["type"]] += a["balance"]
        r["net_income"] = r["income"] - r["expense"]
        if a["balance"]:
            r["accounts"].append({"code": a["code"], "type": a["type"], "balance": a["balance"]})
    return out


# --- The month-end close ----------------------------------------------------------------------


def _checks(db: Session, end: date, today: date, actor_id: uuid.UUID | None
            ) -> list[dict[str, Any]]:  # fmt: skip
    debits = func.sum(case((JournalLine.direction == Direction.DEBIT, JournalLine.amount),
                           else_=0))  # fmt: skip
    credits = func.sum(case((JournalLine.direction == Direction.CREDIT, JournalLine.amount),
                            else_=0))  # fmt: skip
    unbalanced = [
        currency for currency, d, c in db.execute(
            select(JournalEntry.currency, debits, credits)
            .join(JournalLine, JournalLine.journal_entry_id == JournalEntry.id)
            .where(JournalEntry.effective_date <= end).group_by(JournalEntry.currency))
        if d != c
    ]  # fmt: skip

    def latest_reconciliation():
        return db.execute(
            select(LedgerReconciliation.ok, LedgerReconciliation.run_number)
            .where(func.date(LedgerReconciliation.window_end) > end)
            .order_by(LedgerReconciliation.window_end.desc()).limit(1)
        ).first()  # fmt: skip

    reconciled = latest_reconciliation()
    if reconciled is None and end < today:
        # None since the month's end: the close runs one (incremental) itself.
        ledger.reconcile(db, actor_id, ReconciliationMode.INCREMENTAL)
        reconciled = latest_reconciliation()
    from app.modules.risk.models import ProvisionRun, ProvisionStatus

    start = end.replace(day=1)
    provisioned = db.execute(
        select(func.count()).select_from(ProvisionRun)
        .where(ProvisionRun.status == ProvisionStatus.POSTED,
               ProvisionRun.as_of.between(start, end))
    ).scalar_one()  # fmt: skip
    return [
        {"check": "period_ended", "passed": end < today, "blocking": True,
         "detail": f"The month ended on {end}." if end < today else "The month has not ended."},
        {"check": "trial_balance", "passed": not unbalanced, "blocking": True,
         "detail": "Debits equal credits in every currency." if not unbalanced
         else f"Unbalanced: {', '.join(unbalanced)}."},
        {"check": "reconciliation", "passed": bool(reconciled and reconciled.ok),
         "blocking": True,
         "detail": f"Reconciliation run {reconciled.run_number} after the month's end "
         + ("passed." if reconciled.ok else "failed.") if reconciled
         else "No ledger reconciliation has run since the month's end."},
        {"check": "provisions_posted", "passed": provisioned > 0, "blocking": False,
         "detail": "An ECL provision run was posted for the month." if provisioned
         else "No ECL provision run was posted for the month (advisory)."},
    ]  # fmt: skip


def prepare_close(db: Session, period: str, prepared_by: uuid.UUID,
                  today: date | None = None) -> PeriodClose:  # fmt: skip
    """Check the ledger as of the month's end and record its result; nothing is posted until
    a second person approves. Months close in order: once one is closed, the next one closed
    must follow it."""
    today = _today(today)
    start, end = period_bounds(period)
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('finance-period-close'))"))
    existing = db.execute(
        select(PeriodClose).where(PeriodClose.period == period,
                                  PeriodClose.status != CloseStatus.REJECTED)
    ).scalar_one_or_none()  # fmt: skip
    if existing is not None:
        raise ConflictError(f"{period} is already {existing.status} ({existing.close_number}).")
    latest = db.execute(
        select(func.max(PeriodClose.period)).where(PeriodClose.status == CloseStatus.CLOSED)
    ).scalar_one()  # fmt: skip
    if latest is not None and period != _next(latest):
        raise BusinessRuleViolation(
            f"Months close in order: the next month to close is {_next(latest)}.",
            {"rule": "out_of_order", "next": _next(latest)},
        )
    number = f"CLS-{db.execute(CLOSE_SEQUENCE.next_value()).scalar_one():07d}"
    close = PeriodClose(
        close_number=number, period=period, period_start=start, period_end=end,
        status=CloseStatus.PREPARED.value, checks=_checks(db, end, today, prepared_by),
        results=_results(db, end), prepared_by=prepared_by,
    )  # fmt: skip
    db.add(close)
    db.flush()
    _audit(db, prepared_by, "finance.close_prepared", "period_close", close.id,
           close_number=number, period=period)  # fmt: skip
    return close


def _next(period: str) -> str:
    _, end = period_bounds(period)
    following = end + timedelta(days=1)
    return f"{following.year:04d}-{following.month:02d}"


def get_close(db: Session, close_id: uuid.UUID, *, for_update: bool = False) -> PeriodClose:
    query = select(PeriodClose).where(PeriodClose.id == close_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    close = db.execute(query).scalar_one_or_none()
    if close is None:
        raise NotFoundError("Period close not found.")
    return close


def find_close(db: Session, number: str) -> PeriodClose | None:
    return db.execute(
        select(PeriodClose).where(PeriodClose.close_number == number.strip().upper())
    ).scalar_one_or_none()


def _decide(row, actor_id: uuid.UUID, by: uuid.UUID, pending: str, who: str) -> None:
    if row.status != pending:
        raise ConflictError(f"It is {row.status}.")
    if actor_id == by:
        raise BusinessRuleViolation(f"Four-eyes rule: the person who {who} it cannot decide it.",
                                    {"rule": "four_eyes"})  # fmt: skip


def retained_earnings_account(db: Session, currency: str) -> LedgerAccount:
    return ledger.ensure_ledger_account(
        db, code=f"FIN-RETAINED-{currency}", name=f"Retained earnings ({currency})",
        account_type=LedgerAccountType.EQUITY, currency=currency,
    )  # fmt: skip


def approve_close(db: Session, close: PeriodClose, actor_id: uuid.UUID) -> PeriodClose:
    """Close the month: every income and expense account's balance as of its end (including
    entries backdated into an earlier closed month since) is brought to zero against each
    currency's retained earnings, dated the month's end. Not by the preparer, and not while a
    blocking check fails."""
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('finance-period-close'))"))
    close = get_close(db, close.id, for_update=True)
    _decide(close, actor_id, close.prepared_by, CloseStatus.PREPARED, "prepared")
    # The order holds at approval too: a later month closed first would leave this one's
    # result to be closed twice.
    latest = db.execute(
        select(func.max(PeriodClose.period)).where(PeriodClose.status == CloseStatus.CLOSED)
    ).scalar_one()  # fmt: skip
    if latest is not None and close.period != _next(latest):
        raise BusinessRuleViolation(
            f"Months close in order: the next month to close is {_next(latest)}.",
            {"rule": "out_of_order", "next": _next(latest)},
        )
    failed = [c["check"] for c in close.checks if c["blocking"] and not c["passed"]]
    if failed:
        raise BusinessRuleViolation(f"Checks failed: {', '.join(failed)}.",
                                    {"rule": "checks_failed", "checks": failed})  # fmt: skip
    results = _results(db, close.period_end)
    accounts = {a["code"]: a for a in balances_as_of(db, RESULT_TYPES, close.period_end)}
    for currency, r in sorted(results.items()):
        lines: list[ledger.LineSpec] = []
        memo = f"{close.close_number} close of {close.period}"
        for item in r["accounts"]:
            account = accounts[item["code"]]
            # Debit an income balance away, credit an expense balance away (signs flip a
            # balance on the wrong side).
            towards = Direction.DEBIT if item["type"] == LedgerAccountType.INCOME else \
                Direction.CREDIT  # fmt: skip
            if item["balance"] < 0:
                towards = Direction.CREDIT if towards == Direction.DEBIT else Direction.DEBIT
            lines.append(ledger.LineSpec(account["account_id"], towards, abs(item["balance"]),
                                         memo))  # fmt: skip
        if r["net_income"]:
            retained = retained_earnings_account(db, currency)
            side = Direction.CREDIT if r["net_income"] > 0 else Direction.DEBIT
            lines.append(ledger.LineSpec(retained.id, side, abs(r["net_income"]), memo))
        if lines:
            ledger.post_entry(
                db, idempotency_key=f"finance-close:{close.close_number}:{currency}",
                currency=currency, description=memo, source="period_close", lines=lines,
                actor_id=actor_id, effective_date=close.period_end,
            )  # fmt: skip
    close.results = results
    close.status, close.approved_by = CloseStatus.CLOSED.value, actor_id
    close.decided_at = datetime.now(UTC)
    db.flush()
    _audit(db, actor_id, "finance.period_closed", "period_close", close.id,
           close_number=close.close_number, period=close.period)  # fmt: skip
    return close


def reject_close(db: Session, close: PeriodClose, actor_id: uuid.UUID, note: str) -> PeriodClose:
    close = get_close(db, close.id, for_update=True)
    _decide(close, actor_id, close.prepared_by, CloseStatus.PREPARED, "prepared")
    close.status, close.approved_by = CloseStatus.REJECTED.value, actor_id
    close.note, close.decided_at = (note.strip() or None), datetime.now(UTC)
    db.flush()
    _audit(db, actor_id, "finance.close_rejected", "period_close", close.id,
           close_number=close.close_number)  # fmt: skip
    return close


def closed_period(db: Session, period: str) -> PeriodClose | None:
    return db.execute(
        select(PeriodClose).where(PeriodClose.period == period,
                                  PeriodClose.status == CloseStatus.CLOSED)
    ).scalar_one_or_none()  # fmt: skip


# --- Regulatory reporting ---------------------------------------------------------------------


def _report_rows(db: Session, report_type: str, close: PeriodClose
                 ) -> tuple[list[dict[str, Any]], dict[str, Any]]:  # fmt: skip
    end = close.period_end
    if report_type == ReportType.BALANCE_SHEET:
        totals: dict[str, dict[str, int]] = defaultdict(lambda: {t: 0 for t in BALANCE_TYPES})
        for a in balances_as_of(db, BALANCE_TYPES, end):
            totals[a["currency"]][a["type"]] += a["balance"]
        unclosed = {c: r["net_income"] for c, r in _results(db, end).items()}
        rows, summary = [], {}
        for currency, t in sorted(totals.items()):
            for account_type in BALANCE_TYPES:
                rows.append({"currency": currency, "line": account_type,
                             "amount": t[account_type]})  # fmt: skip
            gap = t["asset"] - t["liability"] - t["equity"] - unclosed.get(currency, 0)
            summary[currency] = {"assets": t["asset"], "liabilities": t["liability"],
                                 "equity": t["equity"],
                                 "unclosed_result": unclosed.get(currency, 0),
                                 "balanced": gap == 0}  # fmt: skip
        return rows, summary
    if report_type == ReportType.INCOME_STATEMENT:
        rows, summary = [], {}
        for currency, r in sorted(close.results.items()):
            for item in r["accounts"]:
                rows.append({"currency": currency, "line": item["code"], "type": item["type"],
                             "amount": item["balance"]})  # fmt: skip
            summary[currency] = {"income": r["income"], "expense": r["expense"],
                                 "net_income": r["net_income"]}  # fmt: skip
        return rows, summary
    if report_type == ReportType.LARGE_EXPOSURES:
        from app.modules.risk import service as risk

        by_customer: dict[uuid.UUID, int] = defaultdict(int)
        for e in risk.exposures(db, end):
            by_customer[e.customer_id] += risk._usd(db, e.ead, e.currency, end)
        large = sorted(((usd, cid) for cid, usd in by_customer.items()
                        if usd >= LARGE_EXPOSURE_USD), reverse=True)  # fmt: skip
        rows = []
        for usd, customer_id in large[:LARGE_EXPOSURE_ROWS]:
            customer = db.get(Customer, customer_id)
            grade = risk.grade_of(db, customer, end)
            rows.append({"customer_number": customer.customer_number, "name": customer.name,
                         "grade": grade, "exposure_usd": usd})  # fmt: skip
        return rows, {"threshold_usd": LARGE_EXPOSURE_USD, "obligors": len(large),
                      "total_usd": sum(usd for usd, _ in large)}  # fmt: skip
    if report_type == ReportType.CREDIT_QUALITY:
        from app.modules.risk.models import ProvisionRun, ProvisionStatus

        run = db.execute(
            select(ProvisionRun).where(ProvisionRun.status == ProvisionStatus.POSTED,
                                       ProvisionRun.as_of <= end)
            .order_by(ProvisionRun.as_of.desc(), ProvisionRun.created_at.desc()).limit(1)
        ).scalar_one_or_none()  # fmt: skip
        if run is None:
            return [], {"run_number": None}
        rows = [{"currency": currency, "ead": t["ead"], "stage_1": t["stage_1"],
                 "stage_2": t["stage_2"], "stage_3": t["stage_3"], "ecl": t["ecl"]}
                for currency, t in sorted(run.totals.items())]  # fmt: skip
        return rows, {"run_number": run.run_number, "as_of": run.as_of.isoformat()}
    raise BusinessRuleViolation(f"Unknown report type {report_type}.")


def prepare_report(db: Session, report_type: str, period: str,
                   prepared_by: uuid.UUID) -> RegulatoryReport:  # fmt: skip
    """Extract a report for a closed month."""
    if report_type not in set(ReportType):
        raise BusinessRuleViolation(f"Unknown report type {report_type}.",
                                    {"rule": "report_type"})  # fmt: skip
    period_bounds(period)
    close = closed_period(db, period)
    if close is None:
        raise BusinessRuleViolation(f"{period} is not closed; reports are of closed months.",
                                    {"rule": "period_open"})  # fmt: skip
    rows, summary = _report_rows(db, report_type, close)
    number = f"REG-{db.execute(REPORT_SEQUENCE.next_value()).scalar_one():07d}"
    report = RegulatoryReport(report_number=number, report_type=report_type, period=period,
                              status=ReportStatus.PREPARED.value, rows=rows, summary=summary,
                              prepared_by=prepared_by)  # fmt: skip
    db.add(report)
    db.flush()
    _audit(db, prepared_by, "finance.report_prepared", "regulatory_report", report.id,
           report_number=number, report_type=report_type, period=period)  # fmt: skip
    return report


def get_report(db: Session, report_id: uuid.UUID, *, for_update: bool = False
               ) -> RegulatoryReport:  # fmt: skip
    query = select(RegulatoryReport).where(RegulatoryReport.id == report_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    report = db.execute(query).scalar_one_or_none()
    if report is None:
        raise NotFoundError("Report not found.")
    return report


def find_report(db: Session, number: str) -> RegulatoryReport | None:
    return db.execute(
        select(RegulatoryReport).where(RegulatoryReport.report_number == number.strip().upper())
    ).scalar_one_or_none()


def submit_report(db: Session, report: RegulatoryReport, actor_id: uuid.UUID
                  ) -> RegulatoryReport:  # fmt: skip
    """Submit it to the (synthetic) regulator: not by its preparer, once per type and month."""
    report = get_report(db, report.id, for_update=True)
    _decide(report, actor_id, report.prepared_by, ReportStatus.PREPARED, "prepared")
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
               {"k": f"finance-report:{report.report_type}:{report.period}"})  # fmt: skip
    already = db.execute(
        select(RegulatoryReport.report_number).where(
            RegulatoryReport.report_type == report.report_type,
            RegulatoryReport.period == report.period,
            RegulatoryReport.status == ReportStatus.SUBMITTED)
    ).scalar_one_or_none()  # fmt: skip
    if already:
        raise ConflictError(f"{already} was already submitted for {report.period}.")
    report.status, report.submitted_by = ReportStatus.SUBMITTED.value, actor_id
    report.reference = f"REGU-{report.period}-{report.report_number[4:]}"
    report.decided_at = datetime.now(UTC)
    db.flush()
    _audit(db, actor_id, "finance.report_submitted", "regulatory_report", report.id,
           report_number=report.report_number, reference=report.reference)  # fmt: skip
    return report


def reject_report(db: Session, report: RegulatoryReport, actor_id: uuid.UUID,
                  note: str) -> RegulatoryReport:  # fmt: skip
    report = get_report(db, report.id, for_update=True)
    _decide(report, actor_id, report.prepared_by, ReportStatus.PREPARED, "prepared")
    report.status, report.submitted_by = ReportStatus.REJECTED.value, actor_id
    report.note, report.decided_at = (note.strip() or None), datetime.now(UTC)
    db.flush()
    _audit(db, actor_id, "finance.report_rejected", "regulatory_report", report.id,
           report_number=report.report_number)  # fmt: skip
    return report


def report_csv(report: RegulatoryReport) -> str:
    out = io.StringIO()
    columns: list[str] = []
    for row in report.rows:
        columns += [k for k in row if k not in columns]
    writer = csv.DictWriter(out, fieldnames=columns or ["note"], lineterminator="\n")
    writer.writeheader()
    for row in report.rows:
        writer.writerow(row)
    return out.getvalue()


# --- Shared costs and their allocation --------------------------------------------------------


def shared_costs_account(db: Session, currency: str) -> LedgerAccount:
    return ledger.ensure_ledger_account(
        db, code=f"FIN-SHARED-COSTS-{currency}", name=f"Shared operating costs ({currency})",
        account_type=LedgerAccountType.EXPENSE, currency=currency,
    )  # fmt: skip


def cost_centre_account(db: Session, department: Organization, currency: str) -> LedgerAccount:
    return ledger.ensure_ledger_account(
        db, code=f"FIN-COST-{department.id.hex[:8].upper()}-{currency}",
        name=f"Cost centre: {department.name[:150]} ({currency})",
        account_type=LedgerAccountType.EXPENSE, currency=currency,
    )  # fmt: skip


def record_expense(db: Session, *, currency: str, amount: int, description: str,
                   actor_id: uuid.UUID, idempotency_key: str,
                   effective_date: date | None = None) -> dict[str, Any]:  # fmt: skip
    """A shared operating cost paid from the bank's cash: rent, technology, utilities."""
    if amount <= 0:
        raise BusinessRuleViolation("An expense is a positive amount.")
    memo = description.strip()[:200] or "Shared operating cost"
    entry, replayed = ledger.post_entry(
        db, idempotency_key=f"finance-expense:{idempotency_key}", currency=currency,
        description=memo, source="operating_expense",
        lines=[ledger.LineSpec(shared_costs_account(db, currency).id, Direction.DEBIT, amount,
                               memo),
               ledger.LineSpec(ledger.cash_account(db, currency).id, Direction.CREDIT, amount,
                               memo)],
        actor_id=actor_id, effective_date=effective_date,
    )  # fmt: skip
    return {"entry_number": entry.entry_number, "currency": currency, "amount": amount,
            "effective_date": entry.effective_date.isoformat(), "replayed": replayed}  # fmt: skip


def _pool(db: Session, currency: str, end: date) -> int:
    account = shared_costs_account(db, currency)
    return next((a["balance"] for a in balances_as_of(db, [LedgerAccountType.EXPENSE], end)
                 if a["account_id"] == account.id), 0)  # fmt: skip


def headcount(db: Session) -> list[tuple[Organization, int]]:
    """Departments with their active employees, largest first."""
    rows = db.execute(
        select(Employee.department_id, func.count(Employee.id))
        .where(Employee.employment_status == "active")
        .group_by(Employee.department_id)
    ).all()  # fmt: skip
    departments = [(db.get(Organization, department_id), int(n)) for department_id, n in rows]
    return sorted(departments, key=lambda r: (-r[1], r[0].name))


def split(pool: int, weights: list[int]) -> list[int]:
    """`pool` split in proportion to `weights` by largest remainder; the parts sum to it."""
    total = sum(weights)
    shares = [pool * w // total for w in weights]
    remainders = sorted(range(len(weights)), key=lambda i: (-(pool * weights[i] % total), i))
    for i in remainders[: pool - sum(shares)]:
        shares[i] += 1
    return shares


def _open_period(db: Session, period: str) -> tuple[date, date]:
    start, end = period_bounds(period)
    if closed_period(db, period) is not None:
        raise BusinessRuleViolation(f"{period} is closed.", {"rule": "period_closed"})
    return start, end


def calculate_allocation(db: Session, period: str, currency: str, calculated_by: uuid.UUID
                         ) -> CostAllocation:  # fmt: skip
    """Split the month's unallocated shared costs in a currency across departments by their
    active headcount. Nothing is posted until a second person approves."""
    _, end = _open_period(db, period)
    pool = _pool(db, currency, end)
    if pool <= 0:
        raise BusinessRuleViolation(f"No shared {currency} costs to allocate for {period}.",
                                    {"rule": "nothing_to_allocate"})  # fmt: skip
    departments = headcount(db)
    if not departments:
        raise BusinessRuleViolation("No department has active employees.",
                                    {"rule": "no_driver"})  # fmt: skip
    shares = split(pool, [n for _, n in departments])
    lines = [{"department_id": str(org.id), "department": org.name, "headcount": n,
              "amount": share,
              "account_code": f"FIN-COST-{org.id.hex[:8].upper()}-{currency}"}
             for (org, n), share in zip(departments, shares, strict=True) if share]  # fmt: skip
    number = f"ALC-{db.execute(ALLOCATION_SEQUENCE.next_value()).scalar_one():07d}"
    allocation = CostAllocation(
        allocation_number=number, period=period, currency=currency, pool=pool,
        driver="headcount", lines=lines, status=AllocationStatus.CALCULATED.value,
        calculated_by=calculated_by,
    )  # fmt: skip
    db.add(allocation)
    db.flush()
    _audit(db, calculated_by, "finance.allocation_calculated", "cost_allocation",
           allocation.id, allocation_number=number, pool=pool)  # fmt: skip
    return allocation


def get_allocation(db: Session, allocation_id: uuid.UUID, *, for_update: bool = False
                   ) -> CostAllocation:  # fmt: skip
    query = select(CostAllocation).where(CostAllocation.id == allocation_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    allocation = db.execute(query).scalar_one_or_none()
    if allocation is None:
        raise NotFoundError("Allocation not found.")
    return allocation


def find_allocation(db: Session, number: str) -> CostAllocation | None:
    return db.execute(
        select(CostAllocation)
        .where(CostAllocation.allocation_number == number.strip().upper())
    ).scalar_one_or_none()  # fmt: skip


def post_allocation(db: Session, allocation: CostAllocation, actor_id: uuid.UUID
                    ) -> CostAllocation:  # fmt: skip
    """Move the pool to the departments' cost centres, dated the month's end: not by the
    calculator, while the month is open, and only if the pool is still what was split."""
    allocation = get_allocation(db, allocation.id, for_update=True)
    _decide(allocation, actor_id, allocation.calculated_by, AllocationStatus.CALCULATED,
            "calculated")  # fmt: skip
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
               {"k": f"finance-allocation:{allocation.currency}"})  # fmt: skip
    _, end = _open_period(db, allocation.period)
    if _pool(db, allocation.currency, end) != allocation.pool:
        raise BusinessRuleViolation("The shared costs changed since the split; calculate again.",
                                    {"rule": "pool_changed"})  # fmt: skip
    memo = f"{allocation.allocation_number} cost allocation {allocation.period}"
    lines = [ledger.LineSpec(shared_costs_account(db, allocation.currency).id, Direction.CREDIT,
                             allocation.pool, memo)]  # fmt: skip
    for line in allocation.lines:
        department = db.get(Organization, uuid.UUID(line["department_id"]))
        lines.append(ledger.LineSpec(cost_centre_account(db, department, allocation.currency).id,
                                     Direction.DEBIT, line["amount"], memo))  # fmt: skip
    ledger.post_entry(
        db, idempotency_key=f"finance-allocation:{allocation.allocation_number}",
        currency=allocation.currency, description=memo, source="cost_allocation", lines=lines,
        actor_id=actor_id, effective_date=end,
    )  # fmt: skip
    allocation.status, allocation.approved_by = AllocationStatus.POSTED.value, actor_id
    allocation.decided_at = datetime.now(UTC)
    db.flush()
    _audit(db, actor_id, "finance.allocation_posted", "cost_allocation", allocation.id,
           allocation_number=allocation.allocation_number)  # fmt: skip
    return allocation


def reject_allocation(db: Session, allocation: CostAllocation, actor_id: uuid.UUID,
                      note: str) -> CostAllocation:  # fmt: skip
    allocation = get_allocation(db, allocation.id, for_update=True)
    _decide(allocation, actor_id, allocation.calculated_by, AllocationStatus.CALCULATED,
            "calculated")  # fmt: skip
    allocation.status, allocation.approved_by = AllocationStatus.REJECTED.value, actor_id
    allocation.note, allocation.decided_at = (note.strip() or None), datetime.now(UTC)
    db.flush()
    _audit(db, actor_id, "finance.allocation_rejected", "cost_allocation", allocation.id,
           allocation_number=allocation.allocation_number)  # fmt: skip
    return allocation


# --- Manual journals (Phase 50) ---------------------------------------------------------------


STANDARD_ACCOUNTS = {"FIN-SHARED-COSTS": "shared_costs_account", "FIN-ACCRUALS": "accruals_account",
                     "FIN-RETAINED": "retained_earnings_account"}  # fmt: skip


def _ledger_account(db: Session, code: str) -> LedgerAccount:
    """The account with this code. Finance's standard accounts (shared costs, accruals and
    retained earnings) are created on first use, in a currency the bank already books in."""
    code = code.strip().upper()
    account = db.execute(
        select(LedgerAccount).where(LedgerAccount.code == code)
    ).scalar_one_or_none()  # fmt: skip
    if account is None:
        prefix, _, currency = code.rpartition("-")
        booked = db.execute(
            select(LedgerAccount.id).where(LedgerAccount.currency == currency).limit(1)
        ).first()  # fmt: skip
        if prefix in STANDARD_ACCOUNTS and booked:
            return globals()[STANDARD_ACCOUNTS[prefix]](db, currency)
        raise BusinessRuleViolation(f"No ledger account {code}.", {"rule": "unknown_account"})
    return account


def propose_journal(db: Session, *, currency: str, effective_date: date, description: str,
                    lines: list[dict[str, Any]],
                    proposed_by: uuid.UUID) -> ManualJournal:  # fmt: skip
    """Propose a manual journal: two to twenty lines on the bank's own ledger accounts in one
    currency, debits equal to credits. Nothing is posted until someone else approves it.
    Customers' accounts are moved only through their own services."""
    from app.modules.accounts.models import Account

    if not 2 <= len(lines) <= 20:
        raise BusinessRuleViolation("A journal has 2 to 20 lines.", {"rule": "line_count"})
    clean, debits, credits = [], 0, 0
    for line in lines:
        account = _ledger_account(db, str(line["account_code"]))
        amount, direction = int(line["amount"]), str(line["direction"])
        if account.currency != currency:
            raise BusinessRuleViolation(f"{account.code} is in {account.currency}.",
                                        {"rule": "currency_mismatch"})  # fmt: skip
        if db.execute(select(Account.id).where(Account.ledger_account_id == account.id)).first():
            raise BusinessRuleViolation(f"{account.code} is a customer's account.",
                                        {"rule": "customer_account"})  # fmt: skip
        if amount <= 0 or direction not in (Direction.DEBIT, Direction.CREDIT):
            raise BusinessRuleViolation("Each line is a positive debit or credit.",
                                        {"rule": "line_invalid"})  # fmt: skip
        debits += amount if direction == Direction.DEBIT else 0
        credits += amount if direction == Direction.CREDIT else 0
        clean.append({"account_code": account.code, "direction": direction, "amount": amount})
    if debits != credits:
        raise BusinessRuleViolation("Debits must equal credits.", {"rule": "unbalanced"})
    number = f"MJ-{db.execute(JOURNAL_SEQUENCE.next_value()).scalar_one():07d}"
    journal = ManualJournal(
        journal_number=number, currency=currency, effective_date=effective_date,
        description=description.strip()[:300] or "Manual journal", lines=clean, amount=debits,
        status=JournalStatus.PROPOSED.value, proposed_by=proposed_by,
    )  # fmt: skip
    db.add(journal)
    db.flush()
    _audit(db, proposed_by, "finance.journal_proposed", "manual_journal", journal.id,
           journal_number=number, amount=debits, currency=currency)  # fmt: skip
    return journal


def get_journal(db: Session, journal_id: uuid.UUID, *, for_update: bool = False
                ) -> ManualJournal:  # fmt: skip
    query = select(ManualJournal).where(ManualJournal.id == journal_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    journal = db.execute(query).scalar_one_or_none()
    if journal is None:
        raise NotFoundError("Journal not found.")
    return journal


def find_journal(db: Session, number: str) -> ManualJournal | None:
    return db.execute(
        select(ManualJournal).where(ManualJournal.journal_number == number.strip().upper())
    ).scalar_one_or_none()


def _signature(journal: ManualJournal) -> frozenset:
    return frozenset((line["account_code"], line["direction"]) for line in journal.lines)


def journal_profile(db: Session, journal: ManualJournal, today: date | None = None
                    ) -> dict[str, Any]:  # fmt: skip
    """What an approver weighs before posting a manual journal (Phase 50): its size against
    materiality, the kinds of account it touches (equity, cash, income), how far back it is
    dated and whether into a closed month, a round amount, its description, an identical
    journal posted in the 30 days before, and the preparer's other journals in the last seven
    days on the same accounts (other than cash)."""
    from app.modules.risk import service as risk

    today = _today(today)
    accounts = {line["account_code"]: _ledger_account(db, line["account_code"])
                for line in journal.lines}  # fmt: skip
    types = sorted({a.account_type for a in accounts.values()})
    cash = ledger.cash_account(db, journal.currency).code
    amount_usd = risk._usd(db, journal.amount, journal.currency, today)
    month = f"{journal.effective_date:%Y-%m}"
    signature = _signature(journal)
    window_start = journal.effective_date - timedelta(days=30)
    duplicate = next((other.journal_number for other in db.execute(
        select(ManualJournal).where(
            ManualJournal.id != journal.id, ManualJournal.status == JournalStatus.POSTED,
            ManualJournal.currency == journal.currency, ManualJournal.amount == journal.amount,
            ManualJournal.effective_date.between(window_start, journal.effective_date))
    ).scalars() if _signature(other) == signature), None)  # fmt: skip
    own = set(accounts) - {cash}
    recent = [other for other in db.execute(
        select(ManualJournal).where(
            ManualJournal.id != journal.id, ManualJournal.proposed_by == journal.proposed_by,
            ManualJournal.status != JournalStatus.REJECTED,
            func.date(ManualJournal.created_at) > today - timedelta(days=7))
    ).scalars() if own & {line["account_code"] for line in other.lines}]  # fmt: skip
    major = journal.amount // 10 ** _exponent(journal.currency)
    return {
        "currency": journal.currency, "amount": journal.amount, "amount_usd": amount_usd,
        "materiality_pct": amount_usd * 100 // MATERIALITY_USD, "lines": len(journal.lines),
        "account_types": types,
        "touches_equity": LedgerAccountType.EQUITY in types,
        "touches_income": LedgerAccountType.INCOME in types,
        "touches_cash": cash in accounts,
        "effective_date": journal.effective_date.isoformat(),
        "days_backdated": max((today - journal.effective_date).days, 0),
        "in_closed_period": closed_period(db, month) is not None,
        "round_amount": major > 0 and major % 1_000 == 0
        and journal.amount % 10 ** _exponent(journal.currency) == 0,
        "description_chars": len(journal.description),
        "duplicate_of": duplicate,
        "same_accounts_7d": len(recent),
        "same_accounts_7d_usd": sum(risk._usd(db, o.amount, o.currency, today) for o in recent),
    }  # fmt: skip


def _exponent(currency: str) -> int:
    from app.core.money import minor_unit_exponent

    return minor_unit_exponent(currency)


def approve_journal(db: Session, journal: ManualJournal, actor_id: uuid.UUID) -> ManualJournal:
    """Post the journal to the ledger, dated its effective date: not by its preparer."""
    journal = get_journal(db, journal.id, for_update=True)
    _decide(journal, actor_id, journal.proposed_by, JournalStatus.PROPOSED, "proposed")
    memo = f"{journal.journal_number} {journal.description}"[:200]
    entry, _ = ledger.post_entry(
        db, idempotency_key=f"finance-journal:{journal.journal_number}",
        currency=journal.currency, description=memo, source="manual_journal",
        lines=[ledger.LineSpec(_ledger_account(db, line["account_code"]).id,
                               Direction(line["direction"]), line["amount"], memo[:200])
               for line in journal.lines],
        actor_id=actor_id, effective_date=journal.effective_date,
    )  # fmt: skip
    journal.status, journal.approved_by = JournalStatus.POSTED.value, actor_id
    journal.entry_number, journal.decided_at = entry.entry_number, datetime.now(UTC)
    db.flush()
    _audit(db, actor_id, "finance.journal_posted", "manual_journal", journal.id,
           journal_number=journal.journal_number, entry_number=entry.entry_number)  # fmt: skip
    return journal


def reject_journal(db: Session, journal: ManualJournal, actor_id: uuid.UUID,
                   note: str) -> ManualJournal:  # fmt: skip
    journal = get_journal(db, journal.id, for_update=True)
    _decide(journal, actor_id, journal.proposed_by, JournalStatus.PROPOSED, "proposed")
    journal.status, journal.approved_by = JournalStatus.REJECTED.value, actor_id
    journal.note, journal.decided_at = (note.strip() or None), datetime.now(UTC)
    db.flush()
    _audit(db, actor_id, "finance.journal_rejected", "manual_journal", journal.id,
           journal_number=journal.journal_number)  # fmt: skip
    return journal


def accruals_account(db: Session, currency: str) -> LedgerAccount:
    return ledger.ensure_ledger_account(
        db, code=f"FIN-ACCRUALS-{currency}", name=f"Accrued expenses ({currency})",
        account_type=LedgerAccountType.LIABILITY, currency=currency,
    )  # fmt: skip


def summary(db: Session) -> dict[str, Any]:
    def count(model, *where) -> int:
        return db.execute(select(func.count()).select_from(model).where(*where)).scalar_one()

    latest = db.execute(
        select(func.max(PeriodClose.period)).where(PeriodClose.status == CloseStatus.CLOSED)
    ).scalar_one()  # fmt: skip
    return {
        "last_closed_period": latest,
        "next_period": _next(latest) if latest else None,
        "closes_to_approve": count(PeriodClose, PeriodClose.status == CloseStatus.PREPARED),
        "reports_to_submit": count(RegulatoryReport,
                                   RegulatoryReport.status == ReportStatus.PREPARED),
        "reports_submitted": count(RegulatoryReport,
                                   RegulatoryReport.status == ReportStatus.SUBMITTED),
        "allocations_to_post": count(CostAllocation,
                                     CostAllocation.status == AllocationStatus.CALCULATED),
        "journals_to_approve": count(ManualJournal,
                                     ManualJournal.status == JournalStatus.PROPOSED),
    }  # fmt: skip
