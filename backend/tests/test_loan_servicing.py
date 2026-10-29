"""Phase 10 loan servicing: schedules, accrual, collection, arrears, repayment, payoff and
write-off, all through the ledger."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, ConflictError, PermissionDeniedError
from app.core.permissions import RoleCode
from app.modules.accounts.models import Account
from app.modules.ledger import service as ledger
from app.modules.ledger.models import JournalEntry
from app.modules.lending import servicing
from app.modules.lending.models import InstalmentStatus, LoanStatus
from app.modules.lending.service import monthly_payment
from tests.factories import auth, make_loan, make_staff, make_user, principal, top_up

LOANS = "/api/v1/loans"
RUNS = f"{LOANS}/servicing-runs"


def _balance(db: Session, ledger_account_id) -> int:
    return ledger.balance(db, ledger.get_ledger_account(db, ledger_account_id))


def _deposits(db: Session, loan) -> int:
    """The borrower's deposit account balance."""
    return _balance(db, db.get(Account, loan.disbursement_account_id).ledger_account_id)


def _run(db: Session, user, on: date):
    return servicing.run(db, on, principal(user))


def _entries(db: Session, source: str) -> int:
    return len(db.execute(select(JournalEntry.id).where(JournalEntry.source == source)).all())


def _statuses(db: Session, loan) -> list[str]:
    db.expire_all()  # the API wrote through another session
    return [i.status for i in servicing.instalments_of(db, loan.id)]


# --- Schedule maths -------------------------------------------------------------------------


def test_schedules_amortise_the_principal_exactly() -> None:
    payment = monthly_payment(1_000_000, 1200, 12)
    rows = servicing.build_schedule(1_000_000, 1200, 12, payment, date(2040, 2, 10))
    assert [r[0] for r in rows] == list(range(1, 13))
    assert rows[0] == (1, date(2040, 2, 10), payment - 10_000, 10_000)  # 1 % of 10,000.00
    assert sum(r[2] for r in rows) == 1_000_000
    assert all(abs(r[2] + r[3] - payment) <= 1 for r in rows[:-1])
    assert rows[-1][1] == date(2041, 1, 10)
    # 0 %: equal principal parts, no interest.
    flat = servicing.build_schedule(600_000, 0, 6, 100_000, date(2040, 2, 10))
    assert {r[2] for r in flat} == {100_000} and {r[3] for r in flat} == {0}


def test_due_dates_past_the_28th_move_to_the_28th() -> None:
    assert servicing.add_months(date(2040, 1, 31), 1) == date(2040, 2, 28)
    assert servicing.add_months(date(2040, 11, 15), 3) == date(2041, 2, 15)
    assert [servicing.bucket_for(d) for d in (0, 1, 29, 30, 60, 89, 90, 400)] == [
        "current",
        "1-29",
        "1-29",
        "30-59",
        "60-89",
        "60-89",
        "90+",
        "90+",
    ]


def test_originating_a_loan_creates_its_schedule(db: Session) -> None:
    loan = make_loan(db, make_staff(db))
    schedule = servicing.instalments_of(db, loan.id)
    assert len(schedule) == 12 and set(_statuses(db, loan)) == {"scheduled"}
    assert schedule[0].due_date == date(2040, 2, 10)
    assert sum(i.principal for i in schedule) == loan.principal
    assert loan.interest_receivable_account_id is not None


# --- Accrual and collection ------------------------------------------------------------------


def test_a_run_accrues_and_collects_due_instalments_once(db: Session) -> None:
    staff = make_staff(db)
    loan = make_loan(db, staff, keep_funds=True)
    first = servicing.instalments_of(db, loan.id)[0]

    record = _run(db, staff.manager, date(2040, 3, 10))

    assert record.summary["accrued"] == 2 and record.summary["collected"] == 2
    assert record.summary["missed"] == 0 and record.summary["buckets"] == {"current": 1}
    assert _statuses(db, loan)[:3] == ["paid", "paid", "scheduled"]
    assert first.paid_on == date(2040, 2, 10)  # collected on its due date
    paid = servicing.instalments_of(db, loan.id)[:2]
    assert _balance(db, loan.ledger_account_id) == loan.principal - sum(i.principal for i in paid)
    assert _balance(db, loan.interest_receivable_account_id) == 0
    assert _deposits(db, loan) == loan.principal - sum(i.amount for i in paid)
    accruals, collections = _entries(db, "loan_interest_accrual"), _entries(db, "loan_collection")

    again = _run(db, staff.manager, date(2040, 3, 10))  # the same date: nothing twice

    assert again.summary["accrued"] == 0 and again.summary["collected"] == 0
    assert _entries(db, "loan_interest_accrual") == accruals
    assert _entries(db, "loan_collection") == collections
    assert servicing.business_date(db) == date(2040, 3, 10)
    assert ledger.reconcile(db, None).ok


def test_business_dates_never_go_backwards(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    _run(db, staff.manager, date(2040, 3, 10))
    with pytest.raises(BusinessRuleViolation):
        _run(db, staff.manager, date(2040, 3, 9))

    response = client.post(RUNS, json={"as_of": "2040-03-01"}, headers=auth(staff.manager))

    assert response.status_code == 422
    assert response.json()["error"]["details"]["business_date"] == "2040-03-10"


def test_missed_instalments_put_the_loan_in_arrears(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    loan = make_loan(db, staff)

    record = _run(db, staff.manager, date(2040, 3, 25))

    assert record.summary["missed"] == 2 and record.summary["in_arrears"] == 1
    assert record.summary["buckets"] == {"30-59": 1}
    state = servicing.arrears(db, loan, date(2040, 3, 25))
    assert (state.days_past_due, state.instalments, state.bucket) == (44, 2, "30-59")
    # Interest is accrued even though nothing was collected.
    due = servicing.instalments_of(db, loan.id)[:2]
    assert _balance(db, loan.interest_receivable_account_id) == sum(i.interest for i in due)
    body = client.get(f"{LOANS}/{loan.id}", headers=auth(staff.employee)).json()
    assert body["days_past_due"] == 44 and body["arrears_bucket"] == "30-59"
    assert body["arrears_amount"] == state.amount and body["instalments_paid"] == 0
    assert body["next_due_date"] == "2040-04-10"
    schedule = client.get(f"{LOANS}/{loan.id}/schedule", headers=auth(staff.employee)).json()
    assert [s["status"] for s in schedule[:3]] == ["due", "due", "scheduled"]


def test_a_partial_balance_collects_the_oldest_whole_instalments(db: Session) -> None:
    staff = make_staff(db)
    loan = make_loan(db, staff)
    first, second = servicing.instalments_of(db, loan.id)[:2]
    top_up(db, staff, loan, first.amount + second.amount - 1)

    record = _run(db, staff.manager, date(2040, 3, 10))

    assert record.summary["collected"] == 1 and record.summary["missed"] == 1
    assert _statuses(db, loan)[:2] == ["paid", "due"]
    assert _deposits(db, loan) == second.amount - 1  # no partials


# --- Repayment and payoff --------------------------------------------------------------------


def test_repaying_arrears_is_idempotent_and_needs_funds(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    loan = make_loan(db, staff)
    _run(db, staff.manager, date(2040, 3, 25))
    url = f"{LOANS}/{loan.id}/repayments"
    headers = {**auth(staff.employee), "Idempotency-Key": "repay-1"}

    assert client.post(url, json={}, headers=auth(staff.employee)).status_code == 422  # no key
    broke = client.post(url, json={}, headers=headers)
    assert broke.status_code == 422
    assert broke.json()["error"]["details"]["rule"] == "insufficient_funds"

    top_up(db, staff, loan, 200_000)
    headers["Idempotency-Key"] = "repay-2"
    first = client.post(url, json={"instalments": 1}, headers=headers)
    replay = client.post(url, json={"instalments": 1}, headers=headers)

    assert first.status_code == 200, first.text
    assert replay.json() == first.json()
    assert first.json()["instalments_paid"] == 1 and first.json()["days_past_due"] == 15
    assert _entries(db, "loan_repayment") == 1
    assert _statuses(db, loan)[:2] == ["paid", "due"]
    assert servicing.instalments_of(db, loan.id)[0].paid_on == date(2040, 3, 25)

    too_many = client.post(
        url, json={"instalments": 5}, headers={**headers, "Idempotency-Key": "repay-3"}
    )
    assert too_many.status_code == 422
    rest = client.post(url, json={}, headers={**headers, "Idempotency-Key": "repay-4"})
    assert rest.json()["days_past_due"] == 0 and rest.json()["arrears_bucket"] == "current"
    none_left = client.post(url, json={}, headers={**headers, "Idempotency-Key": "repay-5"})
    assert none_left.status_code == 409
    assert ledger.reconcile(db, None).ok


def test_payoff_settles_principal_and_accrued_interest(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    loan = make_loan(db, staff)
    _run(db, staff.manager, date(2040, 3, 25))  # two instalments overdue
    schedule = servicing.instalments_of(db, loan.id)
    expected = loan.principal + schedule[0].interest + schedule[1].interest

    quote = client.get(f"{LOANS}/{loan.id}/payoff-quote", headers=auth(staff.employee)).json()

    assert quote == {
        "principal": loan.principal,
        "accrued_interest": schedule[0].interest + schedule[1].interest,
        "total": expected,
        "as_of": "2040-03-25",
    }
    top_up(db, staff, loan, expected)
    headers = {**auth(staff.employee), "Idempotency-Key": "payoff-1"}
    done = client.post(f"{LOANS}/{loan.id}/payoff", headers=headers)
    replay = client.post(f"{LOANS}/{loan.id}/payoff", headers=headers)

    assert done.status_code == 200, done.text
    assert replay.json() == done.json() and _entries(db, "loan_payoff") == 1
    assert done.json()["status"] == "repaid" and done.json()["closed_on"] == "2040-03-25"
    assert _statuses(db, loan) == ["paid", "paid"] + ["prepaid"] * 10
    assert _balance(db, loan.ledger_account_id) == 0
    assert _balance(db, loan.interest_receivable_account_id) == 0
    assert _deposits(db, loan) == 0
    again = client.post(
        f"{LOANS}/{loan.id}/payoff", headers={**headers, "Idempotency-Key": "payoff-2"}
    )
    assert again.status_code == 409
    # A repaid loan is not serviced again.
    assert _run(db, staff.manager, date(2040, 6, 1)).summary["loans"] == 0
    assert ledger.reconcile(db, None).ok


def test_the_last_instalment_closes_the_loan(db: Session) -> None:
    staff = make_staff(db)
    loan = make_loan(db, staff, rate_bps=0, term=6, keep_funds=True)

    record = _run(db, staff.manager, date(2040, 7, 10))

    assert record.summary["collected"] == 6 and record.summary["repaid"] == 1
    assert loan.status == LoanStatus.REPAID and loan.closed_on == date(2040, 7, 10)
    assert _entries(db, "loan_interest_accrual") == 0  # a 0 % loan accrues nothing
    assert _balance(db, loan.ledger_account_id) == 0
    assert ledger.reconcile(db, None).ok


# --- Write-off and permissions ---------------------------------------------------------------


def test_write_offs_need_authority_and_ninety_days(db: Session) -> None:
    staff = make_staff(db)
    executive = principal(make_user(db, RoleCode.REGIONAL_EXECUTIVE))
    loan = make_loan(db, staff)
    _run(db, staff.manager, date(2040, 4, 1))  # 51 days past due

    with pytest.raises(PermissionDeniedError):
        servicing.write_off(db, loan.id, principal(staff.manager), date(2040, 4, 1))
    with pytest.raises(BusinessRuleViolation):
        servicing.write_off(db, loan.id, executive, date(2040, 4, 1))

    _run(db, staff.manager, date(2040, 5, 15))  # 95 days past due, four instalments
    accrued = _balance(db, loan.interest_receivable_account_id)
    servicing.write_off(db, loan.id, executive, date(2040, 5, 15))

    assert loan.status == LoanStatus.WRITTEN_OFF and loan.written_off_by == executive.id
    assert set(_statuses(db, loan)) == {InstalmentStatus.WRITTEN_OFF.value}
    assert _balance(db, loan.ledger_account_id) == 0
    assert _balance(db, loan.interest_receivable_account_id) == 0
    entry = db.get(JournalEntry, loan.write_off_entry_id)
    assert sum(line.amount for line in entry.lines if line.direction == "debit") == (
        loan.principal + accrued
    )
    with pytest.raises(ConflictError):
        servicing.write_off(db, loan.id, executive, date(2040, 5, 15))
    assert ledger.reconcile(db, None).ok


def test_servicing_and_repayment_permissions(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    loan = make_loan(db, staff)
    auditor = make_user(db, RoleCode.AUDITOR)

    assert (
        client.post(RUNS, json={"as_of": "2040-03-01"}, headers=auth(staff.employee)).status_code
        == 403
    )
    assert client.get(RUNS, headers=auth(auditor)).status_code == 200
    assert (
        client.post(
            f"{LOANS}/{loan.id}/repayments",
            json={},
            headers={**auth(auditor), "Idempotency-Key": "x"},
        ).status_code
        == 403
    )
    with pytest.raises(PermissionDeniedError):
        servicing.run(db, date(2040, 3, 1), principal(staff.employee))

    created = client.post(
        RUNS,
        json={"as_of": "2040-03-01"},
        headers={**auth(staff.manager), "Idempotency-Key": "run-1"},
    )
    replay = client.post(
        RUNS,
        json={"as_of": "2040-03-01"},
        headers={**auth(staff.manager), "Idempotency-Key": "run-1"},
    )

    assert created.status_code == 201, created.text
    assert replay.json() == created.json()
    runs = client.get(RUNS, headers=auth(staff.employee)).json()
    assert runs["total"] == 1 and runs["items"][0]["started_by_username"] == staff.manager.username
    assert runs["items"][0]["summary"]["missed"] == 1
