"""Account opening (request → approval), eligibility, and money movements."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import AuditEvent
from app.core.permissions import RoleCode
from app.modules.accounts.models import Account, AccountRequest, AccountType
from app.modules.accounts.numbers import is_valid_account_number, make_account_number
from app.modules.customers.models import CustomerType, KycStatus, RiskRating
from app.modules.customers.schemas import CustomerReview
from app.modules.customers.service import review_customer
from app.modules.ledger.models import LedgerAccount
from tests.factories import auth, make_customer, make_staff, make_user, open_account

REQUESTS = "/api/v1/account-requests"
ACCOUNTS = "/api/v1/accounts"


def _request(client: TestClient, user, customer, account_type: str = "current", **extra):
    return client.post(
        REQUESTS,
        json={"customer_id": str(customer.id), "account_type": account_type, **extra},
        headers=auth(user),
    )


def _approve(client: TestClient, user, request_id: str):
    return client.post(f"{REQUESTS}/{request_id}/approve", json={"note": "ok"}, headers=auth(user))


def _accounts_for(db: Session, customer) -> int:
    return db.execute(select(func.count()).where(Account.customer_id == customer.id)).scalar_one()


def test_account_numbers_carry_check_digits() -> None:
    number = make_account_number("US", 4242)

    assert len(number) == 14 and number.startswith("US0000004242")
    assert is_valid_account_number(number)
    assert not is_valid_account_number(number[:-1] + str((int(number[-1]) + 1) % 10))
    assert not is_valid_account_number("US12")


def test_approved_request_opens_exactly_one_account(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    customer = make_customer(db, country_code="GB")

    submitted = _request(client, staff.employee, customer)
    approved = _approve(client, staff.manager, submitted.json()["id"])
    again = _approve(client, staff.compliance, submitted.json()["id"])

    assert submitted.status_code == 201
    assert submitted.json()["status"] == "pending"
    assert submitted.json()["currency"] == "GBP"
    assert approved.status_code == 200
    account = approved.json()["account"]
    assert approved.json()["request"]["status"] == "approved"
    assert approved.json()["request"]["account_id"] == account["id"]
    assert approved.json()["request"]["decided_by_username"] == staff.manager.username
    assert is_valid_account_number(account["account_number"])
    assert account["account_number"].startswith("GB")
    assert account["status"] == "open"
    assert account["balance"] == 0
    assert account["ledger_account_code"] == f"2100-{account['account_number']}"
    ledger_account = db.get(LedgerAccount, account["ledger_account_id"])
    assert (ledger_account.account_type, ledger_account.currency) == ("liability", "GBP")
    # A second approval cannot open a second account.
    assert again.status_code == 409
    assert _accounts_for(db, customer) == 1
    opened = db.execute(
        select(AuditEvent).where(AuditEvent.action == "account.opened")
    ).scalar_one()
    assert opened.actor_id == staff.manager.id
    assert opened.event_metadata["requested_by"] == str(staff.employee.id)


def test_there_is_no_direct_account_creation(client: TestClient, db: Session) -> None:
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    customer = make_customer(db)

    response = client.post(
        ACCOUNTS,
        json={"customer_id": str(customer.id), "account_type": "current", "currency": "USD"},
        headers=auth(admin),
    )

    assert response.status_code == 405
    assert _accounts_for(db, customer) == 0


def test_unauthorized_approvals_are_rejected(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    customer = make_customer(db)
    request_id = _request(client, staff.employee, customer).json()["id"]
    own_request_id = _request(client, staff.manager, make_customer(db)).json()["id"]

    by_teller = _approve(client, staff.employee, request_id)
    by_researcher = _approve(client, make_user(db, RoleCode.AI_RESEARCHER), request_id)
    own = _approve(client, staff.manager, own_request_id)

    assert by_teller.status_code == 403
    assert by_researcher.status_code == 403
    assert own.status_code == 403
    assert own.json()["error"]["details"] == {"rule": "four_eyes"}
    assert _accounts_for(db, customer) == 0


def test_database_enforces_four_eyes(db: Session) -> None:
    staff = make_staff(db)
    from app.modules.accounts.service import submit_request

    request = submit_request(
        db,
        customer_id=make_customer(db).id,
        account_type=AccountType.CURRENT,
        currency=None,
        requested_by=staff.employee.id,
    )

    with pytest.raises(IntegrityError, match="four_eyes"), db.begin_nested():
        db.execute(
            update(AccountRequest)
            .where(AccountRequest.id == request.id)
            .values(decided_by=staff.employee.id)
        )


def test_high_risk_customers_need_a_compliance_approver(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    customer = make_customer(db, risk=RiskRating.HIGH)
    request_id = _request(client, staff.employee, customer).json()["id"]

    by_manager = _approve(client, staff.manager, request_id)
    by_compliance = _approve(client, staff.compliance, request_id)

    assert by_manager.status_code == 403
    assert by_manager.json()["error"]["details"] == {"rule": "high_risk_requires_compliance"}
    assert by_compliance.status_code == 200
    assert _accounts_for(db, customer) == 1


def test_eligibility_rules(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    cases = [
        (make_customer(db, kyc=KycStatus.PENDING), "current", {}, "KYC is 'pending'"),
        (make_customer(db, kyc=KycStatus.REJECTED), "current", {}, "KYC is 'rejected'"),
        (make_customer(db, born=date(date.today().year - 16, 1, 1)), "savings", {}, "minimum age"),
        (
            make_customer(db, customer_type=CustomerType.BUSINESS, born=date(2010, 1, 1)),
            "savings",
            {},
            "cannot hold a savings account",
        ),
        (make_customer(db, country_code="JP"), "current", {"currency": "USD"}, "domestic currency"),
    ]
    for customer, account_type, extra, reason in cases:
        response = _request(client, staff.employee, customer, account_type, **extra)
        assert response.status_code == 422, reason
        assert any(reason in r for r in response.json()["error"]["details"]["reasons"]), (
            response.json()
        )

    preview = client.get(
        f"/api/v1/customers/{cases[0][0].id}/eligibility?account_type=current",
        headers=auth(staff.employee),
    ).json()
    assert preview["eligible"] is False
    assert any("KYC" in r for r in preview["reasons"])


def test_eligibility_is_rechecked_at_approval(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    customer = make_customer(db)
    request_id = _request(client, staff.employee, customer).json()["id"]

    # KYC re-opened after the request was submitted.
    review_customer(db, customer, CustomerReview(kyc_status=KycStatus.PENDING), None)
    response = _approve(client, staff.manager, request_id)

    assert response.status_code == 422
    assert "no longer eligible" in response.json()["error"]["message"]
    assert _accounts_for(db, customer) == 0


def test_rejected_requests_never_open_accounts(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    customer = make_customer(db)
    request_id = _request(client, staff.employee, customer).json()["id"]

    rejected = client.post(
        f"{REQUESTS}/{request_id}/reject",
        json={"reason": "Customer withdrew the application"},
        headers=auth(staff.manager),
    )
    approve_after = _approve(client, staff.compliance, request_id)

    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["account_id"] is None
    assert approve_after.status_code == 409
    assert _accounts_for(db, customer) == 0


def test_duplicate_accounts_and_requests_are_refused(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    customer = make_customer(db)
    first = _request(client, staff.employee, customer)
    duplicate_pending = _request(client, staff.employee, customer)
    _approve(client, staff.manager, first.json()["id"])
    duplicate_account = _request(client, staff.employee, customer)
    savings = _request(client, staff.employee, customer, "savings")

    assert duplicate_pending.status_code == 409
    assert duplicate_account.status_code == 422
    assert (
        "already has a current account"
        in duplicate_account.json()["error"]["details"]["reasons"][0]
    )
    assert savings.status_code == 201  # a different account type is fine


def test_deposits_withdrawals_and_balances(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    account = open_account(db, staff, make_customer(db))
    headers = auth(staff.employee)
    url = f"{ACCOUNTS}/{account.id}"

    deposit = client.post(
        f"{url}/deposits", json={"amount": 10_000}, headers={**headers, "Idempotency-Key": "d1"}
    )
    withdrawal = client.post(
        f"{url}/withdrawals", json={"amount": 2_500}, headers={**headers, "Idempotency-Key": "w1"}
    )
    overdraft = client.post(
        f"{url}/withdrawals", json={"amount": 7_501}, headers={**headers, "Idempotency-Key": "w2"}
    )
    missing_key = client.post(f"{url}/deposits", json={"amount": 1}, headers=headers)
    history = client.get(f"{url}/transactions", headers=headers).json()

    assert deposit.status_code == 201
    assert deposit.json()["account"]["balance"] == 10_000
    assert withdrawal.json()["account"]["balance"] == 7_500
    assert overdraft.status_code == 422
    assert overdraft.json()["error"]["details"] == {"available": 7_500, "requested": 7_501}
    assert missing_key.status_code == 422
    assert [(t["source"], t["direction"], t["amount"]) for t in history["items"]] == [
        ("withdrawal", "debit", 2_500),
        ("deposit", "credit", 10_000),
    ]
    assert client.get(url, headers=headers).json()["balance"] == 7_500


def test_retried_deposits_are_not_posted_twice(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    account = open_account(db, staff, make_customer(db))
    headers = {**auth(staff.employee), "Idempotency-Key": "branch-42-txn-7"}
    url = f"{ACCOUNTS}/{account.id}/deposits"

    first = client.post(url, json={"amount": 5_000}, headers=headers)
    retry = client.post(url, json={"amount": 5_000}, headers=headers)
    different = client.post(url, json={"amount": 6_000}, headers=headers)

    assert first.status_code == 201
    assert retry.status_code == 200
    assert retry.headers["Idempotent-Replayed"] == "true"
    assert retry.json()["entry_number"] == first.json()["entry_number"]
    assert retry.json()["account"]["balance"] == 5_000
    assert different.status_code == 409


def test_freeze_unfreeze_and_close(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    account = open_account(db, staff, make_customer(db))
    teller = auth(staff.employee)
    manager = auth(staff.manager)
    url = f"{ACCOUNTS}/{account.id}"

    client.post(f"{url}/deposits", json={"amount": 900}, headers={**teller, "Idempotency-Key": "a"})
    frozen = client.post(f"{url}/freeze", json={"reason": "Fraud check"}, headers=manager)
    blocked = client.post(
        f"{url}/withdrawals", json={"amount": 100}, headers={**teller, "Idempotency-Key": "b"}
    )
    teller_freeze = client.post(f"{url}/unfreeze", json={"reason": "x" * 5}, headers=teller)
    client.post(f"{url}/unfreeze", json={"reason": "Check cleared"}, headers=manager)
    close_with_balance = client.post(
        f"{url}/close", json={"reason": "Customer left"}, headers=manager
    )
    client.post(
        f"{url}/withdrawals", json={"amount": 900}, headers={**teller, "Idempotency-Key": "c"}
    )
    closed = client.post(f"{url}/close", json={"reason": "Customer left"}, headers=manager)
    after_close = client.post(
        f"{url}/deposits", json={"amount": 1}, headers={**teller, "Idempotency-Key": "d"}
    )

    assert frozen.json()["status"] == "frozen"
    assert blocked.status_code == 422
    assert teller_freeze.status_code == 403
    assert close_with_balance.status_code == 422
    assert close_with_balance.json()["error"]["details"] == {"balance": 900}
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"
    assert closed.json()["closed_at"] is not None
    assert after_close.status_code == 422
    actions = (
        db.execute(select(AuditEvent.action).where(AuditEvent.entity_id == str(account.id)))
        .scalars()
        .all()
    )
    assert {"account.opened", "account.frozen", "account.unfrozen", "account.closed"} <= set(
        actions
    )


def test_roles_without_transact_permission_cannot_move_money(
    client: TestClient, db: Session
) -> None:
    staff = make_staff(db)
    account = open_account(db, staff, make_customer(db))

    response = client.post(
        f"{ACCOUNTS}/{account.id}/deposits",
        json={"amount": 100},
        headers={**auth(make_user(db, RoleCode.AUDITOR)), "Idempotency-Key": "k"},
    )

    assert response.status_code == 403
    assert account.account_type == AccountType.CURRENT
