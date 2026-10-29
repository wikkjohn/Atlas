"""Bulk population loader: many synthetic customers with open accounts, fast.

Creating a customer through the services takes about twenty round trips (customer, two
KYC reviews, the request, the four-eyes approval, the ledger account, the deposit, the
audit trail). That is right for one customer at a time and far too slow for millions.
This loader writes the same end state in batches with PostgreSQL COPY:

- a KYC-verified, low-risk individual customer in an active country;
- an approved account request (requested by one person, decided by another: the
  database's four-eyes CHECK still applies) and the open current account it created,
  with a valid check-digit account number in the country's currency;
- the account's own liability ledger account, and an opening deposit posted through the
  ledger's bulk path (balance triggers, stored balances and reconciliation all apply).

Each batch is one transaction and one audit event. Names, birth dates and balances come
from `case_random(seed, index, "population")`, so the same seed loads the same people.
Everything is synthetic.
"""

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.audit import record_audit_event
from app.core.money import to_minor_units
from app.modules.accounts.numbers import make_account_number
from app.modules.countries.models import Country, OperationalStatus
from app.modules.identity.models import User
from app.modules.ledger import service as ledger
from app.modules.ledger.models import Direction, LedgerAccountType
from app.simulation.generators import FIRST_NAMES, LAST_NAMES, case_random

MAX_CUSTOMER_NUMBER = 9_999_999  # CUS-0000001 .. CUS-9999999
DEFAULT_BATCH = 5_000
NOTE = "Bulk population load (synthetic)"


class PopulationError(Exception):
    pass


@dataclass
class PopulationReport:
    customers: int = 0
    batches: int = 0
    seconds: float = 0.0
    by_country: dict[str, int] = field(default_factory=dict)
    deposits: dict[str, int] = field(default_factory=dict)  # minor units per currency

    def as_dict(self) -> dict[str, Any]:
        return {
            "customers": self.customers,
            "batches": self.batches,
            "seconds": round(self.seconds, 1),
            "customers_per_second": round(self.customers / self.seconds, 1)
            if self.seconds
            else None,
            "by_country": self.by_country,
            "deposits": self.deposits,
        }


def _person(seed: int, index: int, today: date) -> tuple[str, date, int]:
    rng = case_random(seed, index, "population")
    name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
    born = today - timedelta(days=rng.randint(18 * 366, 85 * 365))
    balance = rng.randint(50, 25_000)  # major units
    return name, born, balance


def _numbers(db: Session, sequence: str, n: int) -> list[int]:
    return list(
        db.execute(
            text(f"SELECT nextval('{sequence}') FROM generate_series(1, :n)"), {"n": n}
        ).scalars()
    )


def _copy(cursor, table: str, columns: str, rows) -> None:
    with cursor.copy(f"COPY {table} ({columns}) FROM STDIN") as copy:
        for row in rows:
            copy.write_row(row)


def _load_batch(
    db: Session,
    *,
    seed: int,
    start: int,
    size: int,
    countries: list[tuple[uuid.UUID, str, str]],
    teller: User,
    manager: User,
    report: PopulationReport,
) -> None:
    now = datetime.now(UTC)
    today = now.date()
    customer_numbers = _numbers(db, "customer_number_seq", size)
    if customer_numbers[-1] > MAX_CUSTOMER_NUMBER:
        raise PopulationError("Customer numbers are exhausted (CUS-9999999).")
    account_numbers = _numbers(db, "account_number_seq", size)
    rows = []
    for offset in range(size):
        index = start + offset
        country_id, country_code, currency = countries[index % len(countries)]
        name, born, balance = _person(seed, index, today)
        rows.append(
            {
                "customer_id": uuid.uuid4(),
                "account_id": uuid.uuid4(),
                "ledger_id": uuid.uuid4(),
                "request_id": uuid.uuid4(),
                "customer_number": f"CUS-{customer_numbers[offset]:07d}",
                "account_number": make_account_number(country_code, account_numbers[offset]),
                "name": name,
                "born": born,
                "country_id": country_id,
                "country_code": country_code,
                "currency": currency,
                "balance": to_minor_units(balance, currency),
            }
        )
    cash = {cur: ledger.cash_account(db, cur).id for cur in {r["currency"] for r in rows}}
    db.flush()
    raw = db.connection().connection.driver_connection
    with raw.cursor() as cursor:
        _copy(
            cursor,
            "ledger_accounts",
            "id, code, name, account_type, currency",
            (
                (
                    r["ledger_id"],
                    f"{ledger.CUSTOMER_DEPOSITS_PREFIX}-{r['account_number']}",
                    f"Customer deposits {r['account_number']}",
                    LedgerAccountType.LIABILITY.value,
                    r["currency"],
                )
                for r in rows
            ),
        )
        _copy(
            cursor,
            "customers",
            "id, customer_number, customer_type, name, date_of_birth_or_incorporation,"
            " country_id, risk_rating, kyc_status",
            (
                (
                    r["customer_id"],
                    r["customer_number"],
                    "individual",
                    r["name"],
                    r["born"],
                    r["country_id"],
                    "low",
                    "verified",
                )
                for r in rows
            ),
        )
        _copy(
            cursor,
            "accounts",
            "id, account_number, customer_id, account_type, currency, status,"
            " ledger_account_id, opened_at",
            (
                (
                    r["account_id"],
                    r["account_number"],
                    r["customer_id"],
                    "current",
                    r["currency"],
                    "open",
                    r["ledger_id"],
                    now,
                )
                for r in rows
            ),
        )
        _copy(
            cursor,
            "account_requests",
            "id, customer_id, account_type, currency, status, requested_by, decided_by,"
            " decided_at, decision_note, account_id",
            (
                (
                    r["request_id"],
                    r["customer_id"],
                    "current",
                    r["currency"],
                    "approved",
                    teller.id,
                    manager.id,
                    now,
                    NOTE,
                    r["account_id"],
                )
                for r in rows
            ),
        )
    ledger.post_entries(
        db,
        [
            ledger.Posting(
                idempotency_key=f"population:{r['account_number']}",
                currency=r["currency"],
                description=f"Opening deposit to {r['account_number']} (synthetic)",
                source="population_load",
                lines=[
                    ledger.LineSpec(cash[r["currency"]], Direction.DEBIT, r["balance"]),
                    ledger.LineSpec(r["ledger_id"], Direction.CREDIT, r["balance"]),
                ],
            )
            for r in rows
        ],
        actor_id=teller.id,
    )
    record_audit_event(
        db,
        actor_id=manager.id,
        action="population.loaded",
        entity_type="customer",
        entity_id=None,
        metadata={
            "customers": size,
            "first_customer_number": rows[0]["customer_number"],
            "last_customer_number": rows[-1]["customer_number"],
            "seed": seed,
            "requested_by": str(teller.id),
        },
    )
    for r in rows:
        report.by_country[r["country_code"]] = report.by_country.get(r["country_code"], 0) + 1
        report.deposits[r["currency"]] = report.deposits.get(r["currency"], 0) + r["balance"]


def load(
    factory: sessionmaker[Session],
    *,
    customers: int,
    seed: int = 2026,
    batch: int = DEFAULT_BATCH,
    requested_by: str = "employee",
    decided_by: str = "manager",
    progress=None,
) -> PopulationReport:
    """Load `customers` synthetic customers with open, funded accounts."""
    if customers < 1:
        raise PopulationError("Load at least one customer.")
    if requested_by == decided_by:
        raise PopulationError("Four-eyes: the requester and the approver must differ.")
    with factory() as db:
        users = {
            u.username: u
            for u in db.execute(
                select(User).where(User.username.in_([requested_by, decided_by]))
            ).scalars()
        }
        countries = [
            (c.id, c.iso_country_code, c.default_currency)
            for c in db.execute(
                select(Country)
                .where(Country.operational_status == OperationalStatus.ACTIVE)
                .order_by(Country.iso_country_code)
            ).scalars()
        ]
    if requested_by not in users or decided_by not in users:
        raise PopulationError(
            f"Users '{requested_by}' and '{decided_by}' must exist (run seed-demo first)."
        )
    if not countries:
        raise PopulationError("No active country is configured.")
    report = PopulationReport()
    started = time.perf_counter()
    for start in range(0, customers, batch):
        size = min(batch, customers - start)
        with factory() as db, db.begin():
            _load_batch(
                db,
                seed=seed,
                start=start,
                size=size,
                countries=countries,
                teller=users[requested_by],
                manager=users[decided_by],
                report=report,
            )
        report.customers += size
        report.batches += 1
        if progress:
            progress(report.customers, time.perf_counter() - started)
    report.seconds = time.perf_counter() - started
    return report
