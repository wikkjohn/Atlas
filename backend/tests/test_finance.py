"""Phase 49: finance — month-end close, regulatory reporting extracts and cost allocation."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, ConflictError
from app.core.permissions import RoleCode
from app.modules.finance import service as finance
from app.modules.ledger import service as ledger
from app.modules.ledger.models import Direction, LedgerAccountType, ReconciliationMode
from tests.factories import auth, make_employee, make_loan, make_org_tree, make_staff, make_user

SEP, OCT = "2026-09", "2026-10"
TODAY = date(2026, 11, 1)


def _income(db: Session, amount: int, on: date, key: str) -> None:
    """Fee income received in cash."""
    income = ledger.ensure_ledger_account(
        db,
        code="TEST-FEES-USD",
        name="Fees (USD)",
        account_type=LedgerAccountType.INCOME,
        currency="USD",
    )
    ledger.post_entry(
        db, idempotency_key=key, currency="USD", description="Fees", source="test",
        lines=[ledger.LineSpec(ledger.cash_account(db, "USD").id, Direction.DEBIT, amount),
               ledger.LineSpec(income.id, Direction.CREDIT, amount)],
        actor_id=None, effective_date=on,
    )  # fmt: skip


def _expense(db: Session, staff, amount: int, on: date, key: str) -> None:
    finance.record_expense(db, currency="USD", amount=amount, description="Rent",
                           actor_id=staff.manager.id, idempotency_key=key,
                           effective_date=on)  # fmt: skip


def test_periods() -> None:
    assert finance.period_bounds("2024-02") == (date(2024, 2, 1), date(2024, 2, 29))
    assert finance.period_bounds("2026-12") == (date(2026, 12, 1), date(2026, 12, 31))
    for bad in ("2026-13", "26-01", "2026-1", "soon"):
        with pytest.raises(BusinessRuleViolation, match="YYYY-MM"):
            finance.period_bounds(bad)
    assert finance.split(1_000, [3, 1]) == [750, 250]
    assert finance.split(100, [1, 1, 1]) == [34, 33, 33] and sum(finance.split(7, [2, 3])) == 7


def test_the_month_end_close(db: Session) -> None:
    staff = make_staff(db)
    executive = make_user(db, RoleCode.REGIONAL_EXECUTIVE)
    _income(db, 250_000, date(2026, 9, 15), "fin-income-1")
    _expense(db, staff, 100_000, date(2026, 9, 10), "fin-rent-1")
    _income(db, 70_000, date(2026, 10, 5), "fin-income-oct")  # not September's
    # A month not yet over: a blocking check fails.
    early = finance.prepare_close(db, "2026-11", staff.manager.id, today=TODAY)
    assert {c["check"]: c["passed"] for c in early.checks} == {
        "period_ended": False, "trial_balance": True, "reconciliation": False,
        "provisions_posted": False,
    }  # fmt: skip
    with pytest.raises(BusinessRuleViolation, match="period_ended"):
        finance.approve_close(db, early, executive.id)
    finance.reject_close(db, early, executive.id, "Too early")
    # September's close runs a reconciliation itself, none having run since.
    close = finance.prepare_close(db, SEP, staff.manager.id, today=TODAY)
    assert all(c["passed"] for c in close.checks if c["blocking"])
    usd = close.results["USD"]
    assert (usd["income"], usd["expense"], usd["net_income"]) == (250_000, 100_000, 150_000)
    with pytest.raises(ConflictError):
        finance.prepare_close(db, SEP, staff.manager.id, today=TODAY)
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        finance.approve_close(db, close, staff.manager.id)
    finance.approve_close(db, close, executive.id)
    assert close.status == "closed"
    retained = finance.retained_earnings_account(db, "USD")
    assert ledger.balance(db, retained) == 150_000
    # September's income and expense are zero as of its end; October's income remains.
    assert not [a for a in finance.balances_as_of(db, finance.RESULT_TYPES, date(2026, 9, 30))
                if a["balance"]]  # fmt: skip
    with pytest.raises(BusinessRuleViolation, match="in order"):
        finance.prepare_close(db, "2026-11", staff.manager.id, today=date(2026, 12, 5))
    # Income backdated into the closed September is taken up by October's close.
    _income(db, 10_000, date(2026, 9, 20), "fin-income-late")
    october = finance.prepare_close(db, OCT, staff.manager.id, today=TODAY)
    assert october.results["USD"]["income"] == 80_000
    finance.approve_close(db, october, executive.id)
    assert ledger.balance(db, retained) == 230_000
    assert finance.summary(db)["last_closed_period"] == OCT


def test_regulatory_reports(db: Session) -> None:
    staff = make_staff(db)
    executive = make_user(db, RoleCode.REGIONAL_EXECUTIVE)
    loan = make_loan(db, staff, principal=2_000_000)
    _income(db, 40_000, date(2026, 9, 3), "fin-rep-income")
    with pytest.raises(BusinessRuleViolation, match="not closed"):
        finance.prepare_report(db, "balance_sheet", SEP, staff.manager.id)
    finance.approve_close(db, finance.prepare_close(db, SEP, staff.manager.id, today=TODAY),
                          executive.id)  # fmt: skip
    sheet = finance.prepare_report(db, "balance_sheet", SEP, staff.manager.id)
    assert sheet.summary["USD"]["balanced"] and sheet.summary["USD"]["unclosed_result"] == 0
    assert sheet.summary["USD"]["equity"] == 40_000  # September's result, retained
    income = finance.prepare_report(db, "income_statement", SEP, staff.manager.id)
    assert income.summary["USD"]["net_income"] == 40_000
    large = finance.prepare_report(db, "large_exposures", SEP, staff.manager.id)
    numbers = [r["customer_number"] for r in large.rows]
    assert large.summary["threshold_usd"] == 10_000 and len(numbers) >= 1
    assert loan.customer_id and large.rows[0]["exposure_usd"] >= 10_000
    quality = finance.prepare_report(db, "credit_quality", SEP, staff.manager.id)
    assert quality.rows == [] and quality.summary == {"run_number": None}
    assert finance.report_csv(sheet).splitlines()[0] == "currency,line,amount"
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        finance.submit_report(db, sheet, staff.manager.id)
    finance.submit_report(db, sheet, executive.id)
    assert sheet.status == "submitted" and sheet.reference.startswith("REGU-2026-09-")
    again = finance.prepare_report(db, "balance_sheet", SEP, staff.manager.id)
    with pytest.raises(ConflictError, match="already submitted"):
        finance.submit_report(db, again, executive.id)
    finance.reject_report(db, again, executive.id, "Duplicate")


def test_cost_allocation(db: Session) -> None:
    tree = make_org_tree(db)
    staff = make_staff(db)
    executive = make_user(db, RoleCode.REGIONAL_EXECUTIVE)
    for _ in range(2):
        make_employee(db, tree.us_onboarding)
    make_employee(db, tree.us_kyc_team)  # a team inside US onboarding
    make_employee(db, tree.jp_onboarding)
    with pytest.raises(BusinessRuleViolation, match="No shared"):
        finance.calculate_allocation(db, OCT, "USD", staff.manager.id)
    _expense(db, staff, 100_000, date(2026, 10, 2), "fin-alloc-rent")
    allocation = finance.calculate_allocation(db, OCT, "USD", staff.manager.id)
    shares = {line["department_id"]: line["amount"] for line in allocation.lines}
    assert allocation.pool == 100_000 and sum(shares.values()) == 100_000
    us, jp = shares[str(tree.us_onboarding.id)], shares[str(tree.jp_onboarding.id)]
    assert us == 3 * jp  # three to one by headcount
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        finance.post_allocation(db, allocation, staff.manager.id)
    # A cost recorded after the split makes it stale.
    _expense(db, staff, 500, date(2026, 10, 3), "fin-alloc-more")
    with pytest.raises(BusinessRuleViolation, match="changed"):
        finance.post_allocation(db, allocation, executive.id)
    finance.reject_allocation(db, allocation, executive.id, "Stale")
    fresh = finance.calculate_allocation(db, OCT, "USD", staff.manager.id)
    finance.post_allocation(db, fresh, executive.id)
    assert ledger.balance(db, finance.shared_costs_account(db, "USD")) == 0
    centre = finance.cost_centre_account(db, tree.jp_onboarding, "USD")
    assert ledger.balance(db, centre) == next(
        line["amount"]
        for line in fresh.lines
        if line["department_id"] == str(tree.jp_onboarding.id)
    )


def test_the_finance_api(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    executive = make_user(db, RoleCode.REGIONAL_EXECUTIVE)
    _income(db, 30_000, date(2026, 9, 9), "fin-api-income")
    ledger.reconcile(db, None, ReconciliationMode.FULL)
    db.commit()
    teller, manager, boss = auth(staff.employee), auth(staff.manager), auth(executive)
    assert client.get("/api/v1/finance/closes", headers=teller).status_code == 403
    assert client.post("/api/v1/finance/closes", json={"period": "2026-9"},
                       headers=manager).status_code == 422  # fmt: skip
    prepared = client.post("/api/v1/finance/closes", json={"period": SEP}, headers=manager)
    assert prepared.status_code == 201, prepared.text
    url = f"/api/v1/finance/closes/{prepared.json()['id']}/approve"
    assert client.post(url, headers=manager).status_code == 403
    assert client.post(url, headers=boss).json()["status"] == "closed"
    report = client.post("/api/v1/finance/reports",
                         json={"report_type": "income_statement", "period": SEP},
                         headers=manager)  # fmt: skip
    assert report.status_code == 201
    csv = client.get(f"/api/v1/finance/reports/{report.json()['id']}/csv", headers=boss)
    assert csv.headers["content-type"].startswith("text/csv") and "TEST-FEES-USD" in csv.text
    submitted = client.post(f"/api/v1/finance/reports/{report.json()['id']}/submit", headers=boss)
    assert submitted.json()["reference"].startswith("REGU-")
    expense = {"currency": "USD", "amount": 5_000, "description": "Cleaning"}
    assert client.post("/api/v1/finance/expenses", json=expense,
                       headers=manager).status_code == 422  # fmt: skip
    made = client.post("/api/v1/finance/expenses", json=expense,
                       headers={**manager, "Idempotency-Key": "fin-api-exp"})  # fmt: skip
    assert made.status_code == 201
    counts = client.get("/api/v1/finance/summary/counts", headers=boss).json()
    assert counts["last_closed_period"] == SEP and counts["reports_submitted"] == 1


def test_months_are_approved_in_order(db: Session) -> None:
    staff = make_staff(db)
    executive = make_user(db, RoleCode.REGIONAL_EXECUTIVE)
    _income(db, 50_000, date(2026, 9, 4), "fin-order-sep")
    _income(db, 20_000, date(2026, 10, 4), "fin-order-oct")
    september = finance.prepare_close(db, SEP, staff.manager.id, today=TODAY)
    october = finance.prepare_close(db, OCT, staff.manager.id, today=TODAY)
    finance.approve_close(db, october, executive.id)
    # September's result is in October's close; closing September now would count it twice.
    with pytest.raises(BusinessRuleViolation, match="in order"):
        finance.approve_close(db, september, executive.id)
    assert ledger.balance(db, finance.retained_earnings_account(db, "USD")) == 70_000
