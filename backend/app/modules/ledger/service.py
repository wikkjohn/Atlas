"""General ledger service: the only code that writes journal entries.

Invariants (each also enforced by the database, see migration 0003):
- an entry has at least two lines, all in the entry's currency;
- total debits equal total credits;
- lines are immutable; an entry may only move from `posted` to `reversed`, which happens by
  posting a separate, opposite entry;
- every posting has an idempotency key; a replay returns the original entry.

Balances are never stored: they are derived from posted lines.
"""

import hashlib
import json
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import case, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.core.logging import correlation_id_var
from app.core.pagination import PageParams, paginate
from app.modules.ledger.models import (
    DEBIT_NORMAL,
    JOURNAL_ENTRY_NUMBER_SEQUENCE,
    MAX_LINE_AMOUNT,
    Direction,
    EntryStatus,
    JournalEntry,
    JournalLine,
    LedgerAccount,
    LedgerAccountType,
)
from app.modules.ledger.schemas import (
    JournalEntryOut,
    JournalLineOut,
    LedgerAccountOut,
    ReconciliationCheck,
    ReconciliationReport,
    StatementLineOut,
)

CASH_ACCOUNT_PREFIX = "1000"
CUSTOMER_DEPOSITS_PREFIX = "2100"
_DEFERRED_CONSTRAINTS = "journal_lines_balanced, journal_entries_balanced"


@dataclass(frozen=True)
class LineSpec:
    ledger_account_id: uuid.UUID
    direction: Direction
    amount: int
    memo: str | None = None


# --- Ledger accounts ---------------------------------------------------------------------


def normal_balance(account_type: str) -> Direction:
    return Direction.DEBIT if account_type in DEBIT_NORMAL else Direction.CREDIT


def get_ledger_account(db: Session, ledger_account_id: uuid.UUID) -> LedgerAccount:
    account = db.get(LedgerAccount, ledger_account_id)
    if account is None:
        raise NotFoundError("Ledger account not found.")
    return account


def ensure_ledger_account(
    db: Session, *, code: str, name: str, account_type: LedgerAccountType, currency: str
) -> LedgerAccount:
    """Get or create an account by code. Safe under concurrency (unique code)."""
    db.execute(
        insert(LedgerAccount)
        .values(
            id=uuid.uuid4(),
            code=code,
            name=name,
            account_type=account_type.value,
            currency=currency,
        )
        .on_conflict_do_nothing(index_elements=["code"])
    )
    account = db.execute(select(LedgerAccount).where(LedgerAccount.code == code)).scalar_one()
    if account.currency != currency or account.account_type != account_type.value:
        raise ConflictError(f"Ledger account {code} exists with a different type or currency.")
    return account


def cash_account(db: Session, currency: str) -> LedgerAccount:
    """The bank's (synthetic) cash account for a currency, created on first use."""
    return ensure_ledger_account(
        db,
        code=f"{CASH_ACCOUNT_PREFIX}-{currency}",
        name=f"Cash and equivalents ({currency})",
        account_type=LedgerAccountType.ASSET,
        currency=currency,
    )


def open_customer_deposit_account(db: Session, account_number: str, currency: str) -> LedgerAccount:
    """The liability account holding one customer account's balance."""
    return ensure_ledger_account(
        db,
        code=f"{CUSTOMER_DEPOSITS_PREFIX}-{account_number}",
        name=f"Customer deposits {account_number}",
        account_type=LedgerAccountType.LIABILITY,
        currency=currency,
    )


def balances(db: Session, accounts: Iterable[LedgerAccount]) -> dict[uuid.UUID, int]:
    """Balance on each account's normal side, derived from posted lines."""
    accounts = list(accounts)
    if not accounts:
        return {}
    signed = case(
        (JournalLine.direction == Direction.DEBIT.value, JournalLine.amount),
        else_=-JournalLine.amount,
    )
    debit_minus_credit = dict(
        db.execute(
            select(JournalLine.ledger_account_id, func.coalesce(func.sum(signed), 0))
            .where(JournalLine.ledger_account_id.in_([a.id for a in accounts]))
            .group_by(JournalLine.ledger_account_id)
        ).all()
    )
    result = {}
    for account in accounts:
        net = int(debit_minus_credit.get(account.id, 0))
        result[account.id] = (
            net if normal_balance(account.account_type) == Direction.DEBIT else -net
        )
    return result


def balance(db: Session, account: LedgerAccount) -> int:
    return balances(db, [account])[account.id]


def account_out(account: LedgerAccount, account_balance: int) -> LedgerAccountOut:
    return LedgerAccountOut(
        id=account.id,
        code=account.code,
        name=account.name,
        account_type=account.account_type,
        currency=account.currency,
        normal_balance=normal_balance(account.account_type),
        balance=account_balance,
        created_at=account.created_at,
    )


def list_ledger_accounts(
    db: Session,
    params: PageParams,
    *,
    currency: str | None = None,
    account_type: str | None = None,
    q: str | None = None,
) -> tuple[list[LedgerAccount], int]:
    query = select(LedgerAccount).order_by(LedgerAccount.code)
    if currency:
        query = query.where(LedgerAccount.currency == currency)
    if account_type:
        query = query.where(LedgerAccount.account_type == account_type)
    if q:
        pattern = f"%{q.strip()}%"
        query = query.where(LedgerAccount.code.ilike(pattern) | LedgerAccount.name.ilike(pattern))
    return paginate(db, query, params)


# --- Posting -----------------------------------------------------------------------------


def _request_hash(currency: str, description: str, source: str, lines: list[LineSpec]) -> str:
    canonical = json.dumps(
        {
            "currency": currency,
            "description": description,
            "source": source,
            "lines": [
                [str(line.ledger_account_id), line.direction.value, line.amount, line.memo]
                for line in lines
            ],
        },
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _validate(db: Session, currency: str, lines: list[LineSpec]) -> None:
    if len(lines) < 2:
        raise BusinessRuleViolation("A journal entry needs at least two lines.")
    debits = credits = 0
    for line in lines:
        if not isinstance(line.amount, int) or line.amount <= 0 or line.amount > MAX_LINE_AMOUNT:
            raise BusinessRuleViolation("Line amounts must be positive integers (minor units).")
        if line.direction == Direction.DEBIT:
            debits += line.amount
        else:
            credits += line.amount
    if debits != credits:
        raise BusinessRuleViolation(
            "Unbalanced journal entry: debits must equal credits.",
            {"debits": debits, "credits": credits, "difference": debits - credits},
        )
    account_ids = {line.ledger_account_id for line in lines}
    accounts = {
        a.id: a
        for a in db.execute(
            select(LedgerAccount).where(LedgerAccount.id.in_(account_ids))
        ).scalars()
    }
    missing = account_ids - accounts.keys()
    if missing:
        raise BusinessRuleViolation(
            "Unknown ledger account.", {"ledger_account_ids": sorted(map(str, missing))}
        )
    wrong_currency = sorted(a.code for a in accounts.values() if a.currency != currency)
    if wrong_currency:
        raise BusinessRuleViolation(
            f"Every line must use a {currency} ledger account.", {"accounts": wrong_currency}
        )


def find_entry_by_key(db: Session, key: str) -> JournalEntry | None:
    """The entry already posted with this idempotency key, if any."""
    return db.execute(
        select(JournalEntry).where(JournalEntry.idempotency_key == key)
    ).scalar_one_or_none()


def _replay(existing: JournalEntry, request_hash: str) -> tuple[JournalEntry, bool]:
    if existing.request_hash != request_hash:
        raise ConflictError(
            "This idempotency key was already used for a different journal entry.",
            {"entry_number": existing.entry_number},
        )
    return existing, True


def post_entry(
    db: Session,
    *,
    idempotency_key: str,
    currency: str,
    description: str,
    source: str,
    lines: list[LineSpec],
    actor_id: uuid.UUID | None,
    effective_date: date | None = None,
    reversal_of_id: uuid.UUID | None = None,
) -> tuple[JournalEntry, bool]:
    """Post a balanced entry. Returns (entry, replayed)."""
    if not idempotency_key or len(idempotency_key) > 300:
        raise BusinessRuleViolation("An idempotency key (1-300 characters) is required.")
    request_hash = _request_hash(currency, description, source, lines)

    existing = find_entry_by_key(db, idempotency_key)
    if existing is not None:
        return _replay(existing, request_hash)

    _validate(db, currency, lines)
    number = db.execute(JOURNAL_ENTRY_NUMBER_SEQUENCE.next_value()).scalar_one()
    entry = JournalEntry(
        entry_number=f"JE-{number:08d}",
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        currency=currency,
        description=description,
        source=source,
        status=EntryStatus.POSTED.value,
        effective_date=effective_date or datetime.now(UTC).date(),
        posted_by=actor_id,
        correlation_id=correlation_id_var.get(),
        reversal_of_id=reversal_of_id,
    )
    entry.lines = [
        JournalLine(
            line_number=index,
            ledger_account_id=line.ledger_account_id,
            direction=line.direction.value,
            amount=line.amount,
            memo=line.memo,
        )
        for index, line in enumerate(lines, start=1)
    ]
    try:
        with db.begin_nested():
            db.add(entry)
            db.flush()
            # The balance constraint triggers are deferred to commit; run them now so a
            # violation surfaces here, then defer them again for later entries.
            db.execute(text(f"SET CONSTRAINTS {_DEFERRED_CONSTRAINTS} IMMEDIATE"))
            db.execute(text(f"SET CONSTRAINTS {_DEFERRED_CONSTRAINTS} DEFERRED"))
    except IntegrityError as exc:
        # A concurrent request with the same key won the race.
        existing = find_entry_by_key(db, idempotency_key)
        if existing is not None:
            return _replay(existing, request_hash)
        raise BusinessRuleViolation(f"The ledger rejected the entry: {exc.orig}") from exc
    except DBAPIError as exc:
        raise BusinessRuleViolation(f"The ledger rejected the entry: {exc.orig}") from exc

    record_audit_event(
        db,
        actor_id=actor_id,
        action="ledger.entry_posted",
        entity_type="journal_entry",
        entity_id=entry.id,
        metadata={
            "entry_number": entry.entry_number,
            "source": source,
            "currency": currency,
            "total": sum(line.amount for line in lines if line.direction == Direction.DEBIT),
        },
    )
    return entry, False


def get_entry(db: Session, entry_id: uuid.UUID, *, for_update: bool = False) -> JournalEntry:
    query = select(JournalEntry).where(JournalEntry.id == entry_id)
    if for_update:
        query = query.with_for_update()
    entry = db.execute(query).scalar_one_or_none()
    if entry is None:
        raise NotFoundError("Journal entry not found.")
    return entry


def reverse_entry(
    db: Session,
    entry_id: uuid.UUID,
    *,
    reason: str,
    idempotency_key: str,
    actor_id: uuid.UUID | None,
) -> tuple[JournalEntry, bool]:
    """Offset an entry with an opposite one and mark the original reversed."""
    original = get_entry(db, entry_id, for_update=True)
    reversal_lines = [
        LineSpec(
            ledger_account_id=line.ledger_account_id,
            direction=Direction.CREDIT if line.direction == Direction.DEBIT else Direction.DEBIT,
            amount=line.amount,
            memo=line.memo,
        )
        for line in original.lines
    ]
    description = f"Reversal of {original.entry_number}: {reason}"
    existing = find_entry_by_key(db, idempotency_key)
    if existing is not None:
        return _replay(
            existing, _request_hash(original.currency, description, "reversal", reversal_lines)
        )
    if original.reversal_of_id is not None:
        raise BusinessRuleViolation("A reversing entry cannot itself be reversed.")
    if original.status == EntryStatus.REVERSED:
        raise ConflictError(f"{original.entry_number} has already been reversed.")

    reversal, _ = post_entry(
        db,
        idempotency_key=idempotency_key,
        currency=original.currency,
        description=description,
        source="reversal",
        lines=reversal_lines,
        actor_id=actor_id,
        reversal_of_id=original.id,
    )
    original.status = EntryStatus.REVERSED.value
    db.flush()
    record_audit_event(
        db,
        actor_id=actor_id,
        action="ledger.entry_reversed",
        entity_type="journal_entry",
        entity_id=original.id,
        metadata={"reversed_by": reversal.entry_number, "reason": reason},
    )
    return reversal, False


# --- Reading -----------------------------------------------------------------------------


def entry_out(db: Session, entry: JournalEntry) -> JournalEntryOut:
    reversed_by = db.execute(
        select(JournalEntry.id).where(JournalEntry.reversal_of_id == entry.id)
    ).scalar_one_or_none()
    return JournalEntryOut(
        id=entry.id,
        entry_number=entry.entry_number,
        currency=entry.currency,
        description=entry.description,
        source=entry.source,
        status=entry.status,
        effective_date=entry.effective_date,
        posted_at=entry.posted_at,
        posted_by=entry.posted_by,
        correlation_id=entry.correlation_id,
        reversal_of_id=entry.reversal_of_id,
        reversed_by_id=reversed_by,
        total=sum(line.amount for line in entry.lines if line.direction == Direction.DEBIT),
        lines=[
            JournalLineOut(
                line_number=line.line_number,
                ledger_account_id=line.ledger_account_id,
                ledger_account_code=line.ledger_account.code,
                ledger_account_name=line.ledger_account.name,
                direction=line.direction,
                amount=line.amount,
                memo=line.memo,
            )
            for line in entry.lines
        ],
    )


def list_entries(
    db: Session,
    params: PageParams,
    *,
    currency: str | None = None,
    source: str | None = None,
    ledger_account_id: uuid.UUID | None = None,
) -> tuple[list[JournalEntry], int]:
    query = select(JournalEntry).order_by(
        JournalEntry.posted_at.desc(), JournalEntry.entry_number.desc()
    )
    if currency:
        query = query.where(JournalEntry.currency == currency)
    if source:
        query = query.where(JournalEntry.source == source)
    if ledger_account_id:
        query = query.where(
            JournalEntry.id.in_(
                select(JournalLine.journal_entry_id).where(
                    JournalLine.ledger_account_id == ledger_account_id
                )
            )
        )
    return paginate(db, query, params)


def statement(
    db: Session, ledger_account: LedgerAccount, params: PageParams
) -> tuple[list[StatementLineOut], int]:
    """Lines posted to one account, newest first."""
    query = (
        select(JournalLine, JournalEntry)
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
        .where(JournalLine.ledger_account_id == ledger_account.id)
        .order_by(JournalEntry.posted_at.desc(), JournalEntry.entry_number.desc())
    )
    total = db.execute(
        select(func.count()).where(JournalLine.ledger_account_id == ledger_account.id)
    ).scalar_one()
    rows = db.execute(query.limit(params.limit).offset(params.offset)).all()
    return [
        StatementLineOut(
            entry_id=entry.id,
            entry_number=entry.entry_number,
            posted_at=entry.posted_at,
            description=entry.description,
            source=entry.source,
            direction=line.direction,
            amount=line.amount,
            memo=line.memo,
        )
        for line, entry in rows
    ], int(total)


# --- Reconciliation ----------------------------------------------------------------------


def reconcile(db: Session, actor_id: uuid.UUID | None) -> ReconciliationReport:
    """Verify ledger invariants across every posted line."""
    debit = case((JournalLine.direction == "debit", JournalLine.amount), else_=0)
    credit = case((JournalLine.direction == "credit", JournalLine.amount), else_=0)

    per_entry = db.execute(
        select(
            JournalEntry.entry_number,
            func.count(JournalLine.id),
            func.coalesce(func.sum(debit), 0),
            func.coalesce(func.sum(credit), 0),
        )
        .outerjoin(JournalLine, JournalLine.journal_entry_id == JournalEntry.id)
        .group_by(JournalEntry.id)
    ).all()
    unbalanced = [
        {"entry_number": number, "lines": count, "debits": int(d), "credits": int(c)}
        for number, count, d, c in per_entry
        if count < 2 or d != c
    ]

    currency_mismatches = [
        {
            "entry_number": number,
            "account": code,
            "entry_currency": e_cur,
            "account_currency": a_cur,
        }
        for number, code, e_cur, a_cur in db.execute(
            select(
                JournalEntry.entry_number,
                LedgerAccount.code,
                JournalEntry.currency,
                LedgerAccount.currency,
            )
            .join(JournalLine, JournalLine.journal_entry_id == JournalEntry.id)
            .join(LedgerAccount, LedgerAccount.id == JournalLine.ledger_account_id)
            .where(JournalEntry.currency != LedgerAccount.currency)
        ).all()
    ]

    trial_balance = db.execute(
        select(JournalEntry.currency, func.sum(debit), func.sum(credit))
        .join(JournalLine, JournalLine.journal_entry_id == JournalEntry.id)
        .group_by(JournalEntry.currency)
        .order_by(JournalEntry.currency)
    ).all()
    trial_failures = [
        {"currency": cur, "debits": int(d), "credits": int(c)}
        for cur, d, c in trial_balance
        if d != c
    ]

    reversed_entries = db.execute(
        select(JournalEntry.id, JournalEntry.entry_number).where(
            JournalEntry.status == EntryStatus.REVERSED.value
        )
    ).all()
    reversal_targets = set(
        db.execute(
            select(JournalEntry.reversal_of_id).where(JournalEntry.reversal_of_id.is_not(None))
        ).scalars()
    )
    orphan_reversals = [
        {"entry_number": number}
        for entry_id, number in reversed_entries
        if entry_id not in reversal_targets
    ]

    from app.modules.accounts.models import Account  # accounts depend on the ledger

    account_link_failures = [
        {"account_number": number, "account_currency": a_cur, "ledger_currency": l_cur}
        for number, a_cur, l_cur in db.execute(
            select(Account.account_number, Account.currency, LedgerAccount.currency)
            .join(LedgerAccount, LedgerAccount.id == Account.ledger_account_id)
            .where(Account.currency != LedgerAccount.currency)
        ).all()
    ]

    lines_checked = db.execute(select(func.count()).select_from(JournalLine)).scalar_one()
    checks = [
        ReconciliationCheck(
            name="Every entry balances",
            passed=not unbalanced,
            detail=f"{len(per_entry)} entries checked; {len(unbalanced)} unbalanced.",
            failures=unbalanced[:50],
        ),
        ReconciliationCheck(
            name="Lines match their entry's currency",
            passed=not currency_mismatches,
            detail=f"{len(currency_mismatches)} mismatched lines.",
            failures=currency_mismatches[:50],
        ),
        ReconciliationCheck(
            name="Trial balance per currency",
            passed=not trial_failures,
            detail=(
                "Debits = credits in minor units: "
                + ", ".join(f"{cur}: {int(d):,} = {int(c):,}" for cur, d, c in trial_balance)
            )
            if trial_balance
            else "No postings yet.",
            failures=trial_failures,
        ),
        ReconciliationCheck(
            name="Reversed entries have a reversing entry",
            passed=not orphan_reversals,
            detail=f"{len(reversed_entries)} reversed entries checked.",
            failures=orphan_reversals[:50],
        ),
        ReconciliationCheck(
            name="Customer accounts match their ledger currency",
            passed=not account_link_failures,
            detail=f"{len(account_link_failures)} mismatches.",
            failures=account_link_failures[:50],
        ),
    ]
    report = ReconciliationReport(
        ok=all(check.passed for check in checks),
        checked_at=datetime.now(UTC),
        entries_checked=len(per_entry),
        lines_checked=int(lines_checked),
        checks=checks,
    )
    record_audit_event(
        db,
        actor_id=actor_id,
        action="ledger.reconciliation_run",
        entity_type="ledger",
        entity_id=None,
        metadata={"ok": report.ok, "failed": [c.name for c in checks if not c.passed]},
    )
    return report
