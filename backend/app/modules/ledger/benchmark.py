"""Ledger benchmark: what stored balances and incremental reconciliation buy at volume.

Posts synthetic entries through the normal `post_entry` (so the balance trigger, the
balance constraint triggers and the audit trail all run), with a configurable share of
lines on one hot account (like a currency's cash account). Then it times balance reads
from the stored totals against summing the lines, and full against incremental
reconciliation. Every account and entry it creates is synthetic and coded `BENCH-…`.
"""

import random
import statistics
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.modules.ledger import service as ledger
from app.modules.ledger.models import (
    Direction,
    JournalLine,
    LedgerAccountType,
    ReconciliationMode,
)

CURRENCY = "USD"


def _timed(fn: Callable[[], Any], repeat: int) -> dict[str, float]:
    samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    return {
        "median_ms": round(statistics.median(samples), 3),
        "max_ms": round(max(samples), 3),
        "runs": repeat,
    }


def run(
    factory: sessionmaker[Session],
    *,
    accounts: int,
    entries: int,
    hot_share: float,
    batch: int = 500,
    seed: int = 7,
) -> dict[str, Any]:
    rng = random.Random(seed)
    tag = f"{int(time.time())}"
    with factory() as db, db.begin():
        hot = ledger.ensure_ledger_account(
            db,
            code=f"BENCH-{tag}-HOT",
            name="Benchmark hot account",
            account_type=LedgerAccountType.ASSET,
            currency=CURRENCY,
        )
        pool = [
            ledger.ensure_ledger_account(
                db,
                code=f"BENCH-{tag}-{i:06d}",
                name=f"Benchmark account {i}",
                account_type=LedgerAccountType.LIABILITY,
                currency=CURRENCY,
            )
            for i in range(accounts)
        ]
        hot_id, pool_ids = hot.id, [a.id for a in pool]

    posted = 0
    start = time.perf_counter()
    while posted < entries:
        with factory() as db, db.begin():
            for _ in range(min(batch, entries - posted)):
                amount = rng.randint(1, 100_000)
                debit = hot_id if rng.random() < hot_share else rng.choice(pool_ids)
                credit = rng.choice([a for a in rng.sample(pool_ids, 2) if a != debit])
                ledger.post_entry(
                    db,
                    idempotency_key=f"bench:{tag}:{posted}",
                    currency=CURRENCY,
                    description="Benchmark posting (synthetic)",
                    source="benchmark",
                    lines=[
                        ledger.LineSpec(debit, Direction.DEBIT, amount),
                        ledger.LineSpec(credit, Direction.CREDIT, amount),
                    ],
                    actor_id=None,
                )
                posted += 1
    posting_seconds = time.perf_counter() - start

    with factory() as db:
        hot = ledger.get_ledger_account(db, hot_id)
        sample = [
            ledger.get_ledger_account(db, a) for a in rng.sample(pool_ids, min(200, accounts))
        ]
        stored, lines = (
            ledger.balances(db, [hot, *sample]),
            ledger.line_balances(db, [hot, *sample]),
        )
        report: dict[str, Any] = {
            "accounts": accounts + 1,
            "entries": entries,
            "hot_share": hot_share,
            "hot_account_lines": None,
            "posting": {
                "seconds": round(posting_seconds, 2),
                "entries_per_second": round(entries / posting_seconds, 1),
            },
            "balances_agree": stored == lines,
            "hot_account_balance": {
                "stored": _timed(lambda: ledger.balances(db, [hot]), 20),
                "from_lines": _timed(lambda: ledger.line_balances(db, [hot]), 20),
            },
            "two_hundred_accounts": {
                "stored": _timed(lambda: ledger.balances(db, sample), 10),
                "from_lines": _timed(lambda: ledger.line_balances(db, sample), 10),
            },
        }
        report["hot_account_lines"] = db.execute(
            select(func.count()).where(JournalLine.ledger_account_id == hot_id)
        ).scalar_one()
    for mode in (ReconciliationMode.FULL, ReconciliationMode.INCREMENTAL):
        with factory() as db, db.begin():
            result = ledger.reconcile(db, None, mode)
            report[f"reconciliation_{mode.value}"] = {
                "ok": result.ok,
                "duration_ms": result.duration_ms,
                "entries_checked": result.entries_checked,
            }
    return report
