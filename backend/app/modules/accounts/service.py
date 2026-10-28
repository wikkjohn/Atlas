"""Account service.

Accounts are created in exactly one place: `approve_request`, which requires a pending
request, an authorized approver who is not the requester, and a customer who is eligible
at the moment of approval. There is no API for creating an account directly.
"""

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.errors import (
    BusinessRuleViolation,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.pagination import PageParams, paginate
from app.core.permissions import Permission
from app.modules.accounts.models import (
    ACCOUNT_NUMBER_SEQUENCE,
    Account,
    AccountRequest,
    AccountStatus,
    AccountType,
    RequestStatus,
)
from app.modules.accounts.numbers import make_account_number
from app.modules.accounts.schemas import AccountOut, AccountRequestOut, Eligibility
from app.modules.countries.models import OperationalStatus
from app.modules.customers.models import Customer, CustomerType, KycStatus, RiskRating
from app.modules.customers.service import age_in_years, get_customer
from app.modules.identity.models import User
from app.modules.identity.service import AuthenticatedUser
from app.modules.ledger import service as ledger
from app.modules.ledger.models import Direction, LedgerAccount

MINIMUM_AGE = 18
STATUS_ACTIONS = {
    AccountStatus.OPEN: "account.unfrozen",
    AccountStatus.FROZEN: "account.frozen",
    AccountStatus.CLOSED: "account.closed",
}
TYPES_BY_CUSTOMER = {
    CustomerType.INDIVIDUAL: {AccountType.CURRENT, AccountType.SAVINGS},
    CustomerType.BUSINESS: {AccountType.BUSINESS_CURRENT},
}


# --- Eligibility ---------------------------------------------------------------------------


def eligibility(
    db: Session,
    customer: Customer,
    account_type: AccountType,
    currency: str,
    *,
    today: date | None = None,
) -> Eligibility:
    """Every reason the customer cannot receive this account (empty when eligible)."""
    today = today or date.today()
    reasons: list[str] = []
    if customer.kyc_status != KycStatus.VERIFIED:
        reasons.append(f"KYC is '{customer.kyc_status}'; it must be verified.")
    if customer.risk_rating == RiskRating.UNRATED:
        reasons.append("The customer has no risk rating.")
    if account_type not in TYPES_BY_CUSTOMER[CustomerType(customer.customer_type)]:
        reasons.append(
            f"A {customer.customer_type} customer cannot hold a {account_type.value} account."
        )
    if customer.customer_type == CustomerType.INDIVIDUAL:
        age = age_in_years(customer.date_of_birth_or_incorporation, today)
        if age < MINIMUM_AGE:
            reasons.append(f"The customer is {age}; the minimum age is {MINIMUM_AGE}.")
    if customer.country.operational_status != OperationalStatus.ACTIVE:
        reasons.append(f"{customer.country.country_name} is not an active country.")
    if currency != customer.country.default_currency:
        reasons.append(
            f"Accounts are opened in the customer's domestic currency "
            f"({customer.country.default_currency})."
        )
    duplicate = db.execute(
        select(Account.account_number).where(
            Account.customer_id == customer.id,
            Account.account_type == account_type.value,
            Account.currency == currency,
            Account.status != AccountStatus.CLOSED,
        )
    ).scalar_one_or_none()
    if duplicate:
        reasons.append(f"The customer already has a {account_type.value} account ({duplicate}).")
    return Eligibility(eligible=not reasons, reasons=reasons)


# --- Requests ------------------------------------------------------------------------------


def _usernames(db: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    return dict(db.execute(select(User.id, User.username).where(User.id.in_(ids))).all())


def requests_out(db: Session, requests: list[AccountRequest]) -> list[AccountRequestOut]:
    names = _usernames(
        db, {r.requested_by for r in requests} | {r.decided_by for r in requests if r.decided_by}
    )
    return [
        AccountRequestOut(
            id=r.id,
            customer_id=r.customer_id,
            customer_number=r.customer.customer_number,
            customer_name=r.customer.name,
            customer_risk_rating=r.customer.risk_rating,
            account_type=r.account_type,
            currency=r.currency,
            status=r.status,
            requested_by=r.requested_by,
            requested_by_username=names.get(r.requested_by),
            decided_by=r.decided_by,
            decided_by_username=names.get(r.decided_by) if r.decided_by else None,
            decided_at=r.decided_at,
            decision_note=r.decision_note,
            account_id=r.account_id,
            created_at=r.created_at,
        )
        for r in requests
    ]


def get_request(db: Session, request_id: uuid.UUID, *, for_update: bool = False) -> AccountRequest:
    query = select(AccountRequest).where(AccountRequest.id == request_id)
    if for_update:
        # Refresh an already-loaded request from the locked row (see get_customer).
        db.flush()
        query = query.with_for_update(of=AccountRequest).execution_options(populate_existing=True)
    request = db.execute(query).unique().scalar_one_or_none()
    if request is None:
        raise NotFoundError("Account request not found.")
    return request


def list_requests(
    db: Session,
    params: PageParams,
    *,
    status: str | None = None,
    customer_id: uuid.UUID | None = None,
) -> tuple[list[AccountRequest], int]:
    query = select(AccountRequest).order_by(AccountRequest.created_at.desc(), AccountRequest.id)
    if status:
        query = query.where(AccountRequest.status == status)
    if customer_id:
        query = query.where(AccountRequest.customer_id == customer_id)
    return paginate(db, query, params)


def submit_request(
    db: Session,
    *,
    customer_id: uuid.UUID,
    account_type: AccountType,
    currency: str | None,
    requested_by: uuid.UUID,
) -> AccountRequest:
    customer = get_customer(db, customer_id)
    currency = currency or customer.country.default_currency
    check = eligibility(db, customer, account_type, currency)
    if not check.eligible:
        raise BusinessRuleViolation(
            "The customer is not eligible for this account.", {"reasons": check.reasons}
        )
    request = AccountRequest(
        customer_id=customer.id,
        account_type=account_type.value,
        currency=currency,
        status=RequestStatus.PENDING.value,
        requested_by=requested_by,
    )
    db.add(request)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError as exc:
        raise ConflictError(
            "An account request for this customer, type and currency is already pending."
        ) from exc
    db.refresh(request)
    record_audit_event(
        db,
        actor_id=requested_by,
        action="account_request.submitted",
        entity_type="account_request",
        entity_id=request.id,
        metadata={
            "customer_number": customer.customer_number,
            "account_type": account_type.value,
            "currency": currency,
        },
    )
    return request


def _check_decider(request: AccountRequest, approver: AuthenticatedUser) -> None:
    if not (
        approver.can(Permission.ACCOUNTS_APPROVE)
        or approver.can(Permission.ACCOUNTS_APPROVE_LOW_RISK)
    ):
        raise PermissionDeniedError("Your role cannot decide account requests.")
    if request.requested_by == approver.id:
        raise PermissionDeniedError(
            "Four-eyes rule: you cannot decide a request you submitted.",
            {"rule": "four_eyes"},
        )
    if request.status != RequestStatus.PENDING:
        raise ConflictError(f"This request is already {request.status}.")


def approve_request(
    db: Session,
    request_id: uuid.UUID,
    approver: AuthenticatedUser,
    note: str | None = None,
    *,
    now: datetime | None = None,
) -> Account:
    """Approve a pending request and open its account (the only way to open one)."""
    request = get_request(db, request_id, for_update=True)
    _check_decider(request, approver)
    customer = get_customer(db, request.customer_id, for_update=True)
    if not approver.can(Permission.ACCOUNTS_APPROVE) and customer.risk_rating != RiskRating.LOW:
        # The automated policy engine's permission covers low-risk customers only, whatever
        # the workflow asked: this check holds even if a policy misfires.
        raise PermissionDeniedError(
            "Only low-risk customers can be approved without the accounts:approve permission.",
            {"rule": "low_risk_only", "risk_rating": customer.risk_rating},
        )
    if customer.risk_rating == RiskRating.HIGH and not approver.can(Permission.CUSTOMERS_REVIEW):
        raise PermissionDeniedError(
            "High-risk customers can only be approved by a compliance reviewer.",
            {"rule": "high_risk_requires_compliance"},
        )
    # Re-check: the customer may have changed since the request was submitted.
    check = eligibility(db, customer, AccountType(request.account_type), request.currency)
    if not check.eligible:
        raise BusinessRuleViolation(
            "The customer is no longer eligible; reject the request instead.",
            {"reasons": check.reasons},
        )

    now = now or datetime.now(UTC)
    sequence_value = db.execute(ACCOUNT_NUMBER_SEQUENCE.next_value()).scalar_one()
    number = make_account_number(customer.country.iso_country_code, sequence_value)
    ledger_account = ledger.open_customer_deposit_account(db, number, request.currency)
    account = Account(
        account_number=number,
        customer_id=customer.id,
        account_type=request.account_type,
        currency=request.currency,
        status=AccountStatus.OPEN.value,
        ledger_account_id=ledger_account.id,
        opened_at=now,
    )
    db.add(account)
    db.flush()
    request.status = RequestStatus.APPROVED.value
    request.decided_by = approver.id
    request.decided_at = now
    request.decision_note = note
    request.account_id = account.id
    db.flush()
    record_audit_event(
        db,
        actor_id=approver.id,
        action="account.opened",
        entity_type="account",
        entity_id=account.id,
        metadata={
            "account_number": number,
            "customer_number": customer.customer_number,
            "request_id": str(request.id),
            "requested_by": str(request.requested_by),
        },
    )
    return account


def reject_request(
    db: Session, request_id: uuid.UUID, approver: AuthenticatedUser, reason: str
) -> AccountRequest:
    request = get_request(db, request_id, for_update=True)
    _check_decider(request, approver)
    if not approver.can(Permission.ACCOUNTS_APPROVE):
        raise PermissionDeniedError("Rejecting a request needs the accounts:approve permission.")
    request.status = RequestStatus.REJECTED.value
    request.decided_by = approver.id
    request.decided_at = datetime.now(UTC)
    request.decision_note = reason
    db.flush()
    record_audit_event(
        db,
        actor_id=approver.id,
        action="account_request.rejected",
        entity_type="account_request",
        entity_id=request.id,
        metadata={"reason": reason},
    )
    return request


# --- Accounts ------------------------------------------------------------------------------


def accounts_out(db: Session, accounts: list[Account]) -> list[AccountOut]:
    ledger_accounts = {
        la.id: la
        for la in db.execute(
            select(LedgerAccount).where(
                LedgerAccount.id.in_([a.ledger_account_id for a in accounts])
            )
        ).scalars()
    }
    amounts = ledger.balances(db, ledger_accounts.values())
    return [
        AccountOut(
            id=a.id,
            account_number=a.account_number,
            customer_id=a.customer_id,
            customer_number=a.customer.customer_number,
            customer_name=a.customer.name,
            account_type=a.account_type,
            currency=a.currency,
            status=a.status,
            ledger_account_id=a.ledger_account_id,
            ledger_account_code=ledger_accounts[a.ledger_account_id].code,
            balance=amounts[a.ledger_account_id],
            opened_at=a.opened_at,
            closed_at=a.closed_at,
        )
        for a in accounts
    ]


def get_account(db: Session, account_id: uuid.UUID, *, for_update: bool = False) -> Account:
    query = select(Account).where(Account.id == account_id)
    if for_update:
        # Serializes balance-changing operations on one account; refreshes a loaded copy.
        db.flush()
        query = query.with_for_update(of=Account).execution_options(populate_existing=True)
    account = db.execute(query).unique().scalar_one_or_none()
    if account is None:
        raise NotFoundError("Account not found.")
    return account


def find_account(db: Session, account_number: str) -> Account | None:
    return db.execute(
        select(Account).where(Account.account_number == account_number)
    ).scalar_one_or_none()


def list_accounts(
    db: Session,
    params: PageParams,
    *,
    q: str | None = None,
    customer_id: uuid.UUID | None = None,
    status: str | None = None,
    currency: str | None = None,
) -> tuple[list[Account], int]:
    query = (
        select(Account)
        .join(Customer, Customer.id == Account.customer_id)
        .order_by(Account.opened_at.desc(), Account.account_number)
    )
    if q:
        pattern = f"%{q.strip()}%"
        query = query.where(
            or_(Account.account_number.ilike(pattern), Customer.name.ilike(pattern))
        )
    if customer_id:
        query = query.where(Account.customer_id == customer_id)
    if status:
        query = query.where(Account.status == status)
    if currency:
        query = query.where(Account.currency == currency)
    return paginate(db, query, params)


def _ledger_account(db: Session, account: Account) -> LedgerAccount:
    return ledger.get_ledger_account(db, account.ledger_account_id)


def deposit(
    db: Session,
    account_id: uuid.UUID,
    *,
    amount: int,
    memo: str | None,
    idempotency_key: str,
    actor_id: uuid.UUID,
) -> tuple[Account, str, uuid.UUID, bool]:
    """Synthetic cash deposit: debit the bank's cash, credit the customer's deposit account."""
    account = get_account(db, account_id, for_update=True)
    key = f"deposit:{actor_id}:{idempotency_key}"
    lines = [
        ledger.LineSpec(
            ledger.cash_account(db, account.currency).id, Direction.DEBIT, amount, memo
        ),
        ledger.LineSpec(account.ledger_account_id, Direction.CREDIT, amount, memo),
    ]
    if account.status != AccountStatus.OPEN and not ledger.find_entry_by_key(db, key):
        raise BusinessRuleViolation(f"The account is {account.status}; deposits are not allowed.")
    entry, replayed = ledger.post_entry(
        db,
        idempotency_key=key,
        currency=account.currency,
        description=f"Cash deposit to {account.account_number}",
        source="deposit",
        lines=lines,
        actor_id=actor_id,
    )
    return account, entry.entry_number, entry.id, replayed


def withdraw(
    db: Session,
    account_id: uuid.UUID,
    *,
    amount: int,
    memo: str | None,
    idempotency_key: str,
    actor_id: uuid.UUID,
) -> tuple[Account, str, uuid.UUID, bool]:
    """Synthetic cash withdrawal. Overdrafts are not allowed."""
    account = get_account(db, account_id, for_update=True)
    key = f"withdrawal:{actor_id}:{idempotency_key}"
    lines = [
        ledger.LineSpec(account.ledger_account_id, Direction.DEBIT, amount, memo),
        ledger.LineSpec(
            ledger.cash_account(db, account.currency).id, Direction.CREDIT, amount, memo
        ),
    ]
    if not ledger.find_entry_by_key(db, key):
        if account.status != AccountStatus.OPEN:
            raise BusinessRuleViolation(
                f"The account is {account.status}; withdrawals are not allowed."
            )
        available = ledger.balance(db, _ledger_account(db, account))
        if amount > available:
            raise BusinessRuleViolation(
                "Insufficient funds.", {"available": available, "requested": amount}
            )
    entry, replayed = ledger.post_entry(
        db,
        idempotency_key=key,
        currency=account.currency,
        description=f"Cash withdrawal from {account.account_number}",
        source="withdrawal",
        lines=lines,
        actor_id=actor_id,
    )
    return account, entry.entry_number, entry.id, replayed


def change_status(
    db: Session, account_id: uuid.UUID, target: AccountStatus, actor_id: uuid.UUID, reason: str
) -> Account:
    account = get_account(db, account_id, for_update=True)
    current = AccountStatus(account.status)
    if current == AccountStatus.CLOSED:
        raise ConflictError("The account is closed.")
    if current == target:
        raise ConflictError(f"The account is already {target.value}.")
    if target == AccountStatus.CLOSED:
        remaining = ledger.balance(db, _ledger_account(db, account))
        if remaining != 0:
            raise BusinessRuleViolation(
                "Only accounts with a zero balance can be closed.", {"balance": remaining}
            )
        account.closed_at = datetime.now(UTC)
    account.status = target.value
    db.flush()
    record_audit_event(
        db,
        actor_id=actor_id,
        action=STATUS_ACTIONS[target],
        entity_type="account",
        entity_id=account.id,
        metadata={"from": current.value, "to": target.value, "reason": reason},
    )
    return account
