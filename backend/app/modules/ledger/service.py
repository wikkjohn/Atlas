"""General ledger service: the only code that writes journal entries.

Invariants (each also enforced by the database, see migration 0003):
- an entry has at least two lines, all in the entry's currency;
- total debits equal total credits;
- lines are immutable; an entry may only move from `posted` to `reversed`, which happens by
  posting a separate, opposite entry;
- every posting has an idempotency key; a replay returns the original entry.

Balances are stored per account in `ledger_balances`, maintained by a database trigger on
every posted line (migration 0010) and checked against the lines by reconciliation.
"""

import hashlib
import json
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

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
    LedgerBalance,
    LedgerReconciliation,
    ReconciliationMode,
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


def _on_normal_side(
    accounts: list[LedgerAccount], debit_minus_credit: dict[uuid.UUID, int]
) -> dict[uuid.UUID, int]:
    result = {}
    for account in accounts:
        net = int(debit_minus_credit.get(account.id, 0))
        result[account.id] = (
            net if normal_balance(account.account_type) == Direction.DEBIT else -net
        )
    return result


def balances(db: Session, accounts: Iterable[LedgerAccount]) -> dict[uuid.UUID, int]:
    """Balance on each account's normal side, from the stored totals (kept by a trigger in
    the same transaction as every posting)."""
    accounts = list(accounts)
    if not accounts:
        return {}
    db.flush()  # lines added in this session must reach the trigger first
    debit_minus_credit = dict(
        db.execute(
            select(
                LedgerBalance.ledger_account_id,
                func.sum(LedgerBalance.debit_total - LedgerBalance.credit_total),
            )
            .where(LedgerBalance.ledger_account_id.in_([a.id for a in accounts]))
            .group_by(LedgerBalance.ledger_account_id)
        ).all()
    )
    return _on_normal_side(accounts, debit_minus_credit)


def line_balances(db: Session, accounts: Iterable[LedgerAccount]) -> dict[uuid.UUID, int]:
    """The same balances summed from the posted lines: the reference reconciliation and the
    benchmark compare the stored totals with."""
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
    return _on_normal_side(accounts, debit_minus_credit)


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


def _request_hash(
    currency: str,
    description: str,
    source: str,
    lines: list[LineSpec],
    effective_date: date | None = None,
) -> str:
    body: dict = {
        "currency": currency,
        "description": description,
        "source": source,
        "lines": [
            [str(line.ledger_account_id), line.direction.value, line.amount, line.memo]
            for line in lines
        ],
    }
    if effective_date is not None:
        # Only when supplied, so requests without a date keep their earlier fingerprint.
        body["effective_date"] = effective_date.isoformat()
    canonical = json.dumps(body, separators=(",", ":"))
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
    request_hash = _request_hash(currency, description, source, lines, effective_date)

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
        db.flush()
        query = query.with_for_update().execution_options(populate_existing=True)
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


# --- Reconciliation -----------------------------------------------------------------------

# Incremental runs re-check entries posted shortly before the previous run ended: a
# transaction that started earlier (posted_at is its start time) may have committed after
# that run looked. A full run remains the backstop for anything older.
INCREMENTAL_OVERLAP = timedelta(minutes=10)
# Incremental runs compare stored balances with their lines for at most this many of the
# accounts the window touched (a full run compares every account).
INCREMENTAL_BALANCE_SAMPLE = 500


def _debit_credit():
    debit = case((JournalLine.direction == "debit", JournalLine.amount), else_=0)
    credit = case((JournalLine.direction == "credit", JournalLine.amount), else_=0)
    return debit, credit


def _check_entries(db: Session, since: datetime | None) -> tuple[ReconciliationCheck, int, int]:
    debit, credit = _debit_credit()
    query = (
        select(
            JournalEntry.entry_number,
            func.count(JournalLine.id),
            func.coalesce(func.sum(debit), 0),
            func.coalesce(func.sum(credit), 0),
        )
        .outerjoin(JournalLine, JournalLine.journal_entry_id == JournalEntry.id)
        .group_by(JournalEntry.id)
    )
    if since is not None:
        query = query.where(JournalEntry.posted_at >= since)
    per_entry = db.execute(query).all()
    unbalanced = [
        {"entry_number": number, "lines": count, "debits": int(d), "credits": int(c)}
        for number, count, d, c in per_entry
        if count < 2 or d != c
    ]
    lines = sum(count for _, count, _, _ in per_entry)
    check = ReconciliationCheck(
        name="Every entry balances",
        passed=not unbalanced,
        detail=f"{len(per_entry)} entries checked; {len(unbalanced)} unbalanced.",
        failures=unbalanced[:50],
    )
    return check, len(per_entry), lines


def _check_line_currencies(db: Session, since: datetime | None) -> ReconciliationCheck:
    query = (
        select(
            JournalEntry.entry_number,
            LedgerAccount.code,
            JournalEntry.currency,
            LedgerAccount.currency,
        )
        .join(JournalLine, JournalLine.journal_entry_id == JournalEntry.id)
        .join(LedgerAccount, LedgerAccount.id == JournalLine.ledger_account_id)
        .where(JournalEntry.currency != LedgerAccount.currency)
    )
    if since is not None:
        query = query.where(JournalEntry.posted_at >= since)
    mismatches = [
        {"entry_number": n, "account": code, "entry_currency": e, "account_currency": a}
        for n, code, e, a in db.execute(query).all()
    ]
    return ReconciliationCheck(
        name="Lines match their entry's currency",
        passed=not mismatches,
        detail=f"{len(mismatches)} mismatched lines.",
        failures=mismatches[:50],
    )


def _check_trial_balance(db: Session) -> ReconciliationCheck:
    """Debits equal credits per currency, from the stored totals (no line scan)."""
    rows = db.execute(
        select(
            LedgerAccount.currency,
            func.sum(LedgerBalance.debit_total),
            func.sum(LedgerBalance.credit_total),
        )
        .join(LedgerAccount, LedgerAccount.id == LedgerBalance.ledger_account_id)
        .group_by(LedgerAccount.currency)
        .order_by(LedgerAccount.currency)
    ).all()
    failures = [
        {"currency": cur, "debits": int(d), "credits": int(c)} for cur, d, c in rows if d != c
    ]
    return ReconciliationCheck(
        name="Trial balance per currency",
        passed=not failures,
        detail=(
            "Debits = credits in minor units: "
            + ", ".join(f"{cur}: {int(d):,} = {int(c):,}" for cur, d, c in rows)
        )
        if rows
        else "No postings yet.",
        failures=failures,
    )


def _check_stored_balances(db: Session, account_ids: list[uuid.UUID] | None) -> ReconciliationCheck:
    """Stored totals against the lines they summarize (`None`: every account)."""
    debit, credit = _debit_credit()
    lines = select(
        JournalLine.ledger_account_id.label("account_id"),
        func.sum(debit).label("debits"),
        func.sum(credit).label("credits"),
        func.count().label("lines"),
    ).group_by(JournalLine.ledger_account_id)
    stored = select(
        LedgerBalance.ledger_account_id.label("account_id"),
        func.sum(LedgerBalance.debit_total).label("debits"),
        func.sum(LedgerBalance.credit_total).label("credits"),
        func.sum(LedgerBalance.line_count).label("lines"),
    ).group_by(LedgerBalance.ledger_account_id)
    if account_ids is not None:
        lines = lines.where(JournalLine.ledger_account_id.in_(account_ids))
        stored = stored.where(LedgerBalance.ledger_account_id.in_(account_ids))
    from_lines = {r.account_id: (int(r.debits), int(r.credits), r.lines) for r in db.execute(lines)}
    from_store = {
        r.account_id: (int(r.debits), int(r.credits), int(r.lines)) for r in db.execute(stored)
    }
    accounts = set(from_lines) | set(from_store)
    differ = sorted(a for a in accounts if from_lines.get(a) != from_store.get(a))
    codes = dict(
        db.execute(select(LedgerAccount.id, LedgerAccount.code).where(LedgerAccount.id.in_(differ)))
        .tuples()
        .all()
    )
    failures = [
        {
            "account": codes.get(a, str(a)),
            "lines": list(from_lines.get(a, (0, 0, 0))),
            "stored": list(from_store.get(a, (0, 0, 0))),
        }
        for a in differ[:50]
    ]
    scope = "every account" if account_ids is None else "the accounts this window touched"
    return ReconciliationCheck(
        name="Stored balances match the lines",
        passed=not differ,
        detail=f"{len(accounts)} accounts compared ({scope}); {len(differ)} differ.",
        failures=failures,
    )


def _check_reversals(db: Session, since: datetime | None) -> ReconciliationCheck:
    if since is None:
        reversed_entries = db.execute(
            select(JournalEntry.id, JournalEntry.entry_number).where(
                JournalEntry.status == EntryStatus.REVERSED.value
            )
        ).all()
        targets = set(
            db.execute(
                select(JournalEntry.reversal_of_id).where(JournalEntry.reversal_of_id.is_not(None))
            ).scalars()
        )
        orphans = [
            {"entry_number": n} for entry_id, n in reversed_entries if entry_id not in targets
        ]
        detail = f"{len(reversed_entries)} reversed entries checked."
    else:
        # The window's reversing entries each mark their original reversed.
        original = JournalEntry.__table__.alias("original")
        rows = db.execute(
            select(JournalEntry.entry_number, original.c.entry_number, original.c.status)
            .join(original, original.c.id == JournalEntry.reversal_of_id)
            .where(JournalEntry.posted_at >= since)
        ).all()
        orphans = [
            {"entry_number": original_number, "reversed_by": number}
            for number, original_number, status in rows
            if status != EntryStatus.REVERSED.value
        ]
        detail = f"{len(rows)} reversing entries checked."
    return ReconciliationCheck(
        name="Reversed entries have a reversing entry",
        passed=not orphans,
        detail=detail,
        failures=orphans[:50],
    )


def _check_account_links(db: Session, since: datetime | None) -> ReconciliationCheck:
    from app.modules.accounts.models import Account  # accounts depend on the ledger

    query = (
        select(Account.account_number, Account.currency, LedgerAccount.currency)
        .join(LedgerAccount, LedgerAccount.id == Account.ledger_account_id)
        .where(Account.currency != LedgerAccount.currency)
    )
    if since is not None:
        query = query.where(LedgerAccount.created_at >= since)
    failures = [
        {"account_number": n, "account_currency": a, "ledger_currency": lc}
        for n, a, lc in db.execute(query).all()
    ]
    return ReconciliationCheck(
        name="Customer accounts match their ledger currency",
        passed=not failures,
        detail=f"{len(failures)} mismatches.",
        failures=failures[:50],
    )


def _touched_accounts(db: Session, since: datetime) -> tuple[list[uuid.UUID], int]:
    touched = (
        select(JournalLine.ledger_account_id)
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
        .where(JournalEntry.posted_at >= since)
        .distinct()
        .subquery()
    )
    total = db.execute(select(func.count()).select_from(touched)).scalar_one()
    sample = list(
        db.execute(
            select(touched.c.ledger_account_id)
            .order_by(touched.c.ledger_account_id)
            .limit(INCREMENTAL_BALANCE_SAMPLE)
        ).scalars()
    )
    return sample, total


def reconcile(
    db: Session,
    actor_id: uuid.UUID | None,
    mode: ReconciliationMode = ReconciliationMode.FULL,
) -> ReconciliationReport:
    """Verify the ledger's invariants and record the run.

    A full run checks every entry, line and account. An incremental run checks the entries
    posted since the previous run (with an overlap), the stored trial balance and the
    stored balances of the accounts it touched; the first incremental run checks everything.
    """
    started = time.perf_counter()
    window_end = db.execute(select(func.clock_timestamp())).scalar_one()
    since: datetime | None = None
    if mode == ReconciliationMode.INCREMENTAL:
        previous = db.execute(select(func.max(LedgerReconciliation.window_end))).scalar_one()
        since = previous - INCREMENTAL_OVERLAP if previous is not None else None

    entries_check, entries_checked, lines_checked = _check_entries(db, since)
    if since is None:
        stored_check = _check_stored_balances(db, None)
    else:
        sample, touched = _touched_accounts(db, since)
        stored_check = _check_stored_balances(db, sample)
        if touched > len(sample):
            stored_check.detail += f" Sampled {len(sample)} of {touched} touched accounts."
    checks = [
        entries_check,
        _check_line_currencies(db, since),
        _check_trial_balance(db),
        stored_check,
        _check_reversals(db, since),
        _check_account_links(db, since),
    ]
    duration_ms = round((time.perf_counter() - started) * 1000)
    report = ReconciliationReport(
        ok=all(check.passed for check in checks),
        checked_at=datetime.now(UTC),
        entries_checked=entries_checked,
        lines_checked=lines_checked,
        checks=checks,
        mode=mode.value,
        window_start=since,
        window_end=window_end,
        duration_ms=duration_ms,
    )
    run = LedgerReconciliation(
        mode=mode.value,
        ok=report.ok,
        window_start=since,
        window_end=window_end,
        entries_checked=entries_checked,
        lines_checked=lines_checked,
        duration_ms=duration_ms,
        report=report.model_dump(mode="json"),
        run_by=actor_id,
    )
    db.add(run)
    db.flush()
    report.run_number = run.run_number
    report.id = run.id
    record_audit_event(
        db,
        actor_id=actor_id,
        action="ledger.reconciliation_run",
        entity_type="ledger",
        entity_id=run.id,
        metadata={
            "ok": report.ok,
            "mode": mode.value,
            "failed": [c.name for c in checks if not c.passed],
        },
    )
    return report


def list_reconciliations(db: Session, params: PageParams) -> tuple[list[LedgerReconciliation], int]:
    return paginate(
        db, select(LedgerReconciliation).order_by(LedgerReconciliation.run_number.desc()), params
    )
