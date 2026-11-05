# ADR 0004: The ledger is the only writer of money, and the database re-checks it

- **Status:** Accepted
- **Decided in:** Phases 3, 12, 13

## Context
Many modules move money: payments, loans, cards, treasury, fees and FX. If each wrote
balances directly, one bug could unbalance the books, and nothing would notice until a
reconciliation.

## Decision
- **One writer.** `ledger.service.post_entry` and its bulk form `post_entries` are the only
  code that writes journal entries.
- **Each entry is checked:**
  - at least two lines;
  - one currency;
  - debits equal to credits;
  - an idempotency key.
- **PostgreSQL repeats the rules** with deferred constraint triggers. It also forbids
  updating or deleting lines.
- **Corrections** are reversing entries.
- **Stored balances** (`ledger_balances`, Phase 12) are maintained by a trigger in the
  posting's transaction and checked by reconciliation (full or incremental).

## Consequences
- **Benefits:**
  - A bug in a module cannot post an unbalanced entry: the database refuses it, and a test
    shows this with the Python checks switched off.
  - Duplicate postings replay; they do not double.
  - Reconciliation, the backup checks and the drill all rely on the same invariant: debits
    equal credits.
- **Costs:**
  - Every money movement is a journal entry, even an internal one.
  - Bulk loading needs its own path (`post_entries` with COPY), which keeps every database
    rule.

## Evidence
- `backend/app/modules/ledger/service.py`
- `backend/tests/test_ledger.py`
- `backend/tests/test_ledger_concurrency.py`
