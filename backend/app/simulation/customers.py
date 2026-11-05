"""The customer generator (Phase 72, roadmap Milestone F step 4).

Builds on the bulk population loader (Phase 13): the same COPY path, the same end state for
every account (an approved four-eyes request, a liability ledger account, postings through
the ledger's bulk path), but a bank's real mix of customers instead of one kind:

- **segments:** mass market, students, affluent, seniors, private clients and small
  businesses, each with its own ages (or years since incorporation), income or turnover,
  risk mix and products;
- **products:** the retail account types (current, savings, business current); a customer
  holds the ones their segment usually has;
- **transaction history:** for each month back, the money a customer of the segment moves:
  salary or pension in, rent and bills out, card spending, a monthly transfer to savings; for
  businesses, customer receipts, supplier payments and payroll. Every movement is a
  balanced journal entry dated in its month, with its category as the entry's source
  (`history.salary`, `history.card` ...). Balances never go below zero: a payment that would
  overdraw is cut to what is there.

Money is set in US dollars and converted to the country's currency at the FX anchor rates.
Everything is seeded per customer (`case_random(seed, index, ...)`), so a run repeats, and
it is idempotent per seed: a second run with the same seed continues where the first one
stopped and creates only the customers still missing. Everything is synthetic.
"""

import calendar as month_calendar
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.audit import record_audit_event
from app.core.money import to_minor_units
from app.modules.accounts.numbers import make_account_number
from app.modules.countries.models import Country, OperationalStatus
from app.modules.customers.models import Customer
from app.modules.fx import rates
from app.modules.identity.models import User
from app.modules.ledger import service as ledger
from app.modules.ledger.models import Direction, LedgerAccountType
from app.simulation.generators import FIRST_NAMES, LAST_NAMES, case_random
from app.simulation.population import MAX_CUSTOMER_NUMBER, PopulationError, _copy, _numbers

GENERATOR = "customers-v1"
MAX_COUNT = 5_000_000
MAX_HISTORY_MONTHS = 24
BATCH = 2_000
NOTE = "Generated customer (synthetic)"
SOURCE = "history"


@dataclass(frozen=True)
class Segment:
    weight: int
    customer_type: str  # individual / business
    ages: tuple[int, int]  # years: age, or years since incorporation
    income_usd: tuple[int, int]  # a year: pay, pension or turnover
    products: dict[str, float]  # account type -> share of the segment holding it
    risk: dict[str, int]  # rating -> weight
    card_spends: tuple[int, int]  # card payments a month
    saves: float = 0.0  # share of monthly income moved to savings


SEGMENTS: dict[str, Segment] = {
    "mass": Segment(
        55,
        "individual",
        (25, 64),
        (22_000, 60_000),
        {"current": 1.0, "savings": 0.3},
        {"low": 85, "medium": 13, "high": 2},
        (4, 9),
        0.05,
    ),
    "student": Segment(
        8,
        "individual",
        (18, 24),
        (3_000, 14_000),
        {"current": 1.0, "savings": 0.05},
        {"low": 90, "medium": 10},
        (5, 10),
        0.02,
    ),
    "affluent": Segment(
        15,
        "individual",
        (30, 64),
        (60_000, 200_000),
        {"current": 1.0, "savings": 0.8},
        {"low": 80, "medium": 18, "high": 2},
        (8, 14),
        0.12,
    ),
    "senior": Segment(
        12,
        "individual",
        (65, 92),
        (14_000, 45_000),
        {"current": 1.0, "savings": 0.6},
        {"low": 92, "medium": 8},
        (3, 6),
        0.04,
    ),
    "private": Segment(
        2,
        "individual",
        (35, 85),
        (250_000, 2_000_000),
        {"current": 1.0, "savings": 1.0},
        {"low": 50, "medium": 40, "high": 10},
        (10, 18),
        0.25,
    ),
    "sme": Segment(
        8,
        "business",
        (1, 40),
        (120_000, 5_000_000),
        {"business_current": 1.0},
        {"low": 60, "medium": 32, "high": 8},
        (0, 0),
    ),
}
SEGMENT_NAMES = list(SEGMENTS)
SEGMENT_WEIGHTS = [s.weight for s in SEGMENTS.values()]
MERCHANTS = (
    "grocer",
    "fuel",
    "restaurant",
    "pharmacy",
    "online retail",
    "transport",
    "clothing",
    "electronics",
    "cafe",
    "bookshop",
)
BUSINESS_SUFFIXES = (
    "Trading",
    "Services",
    "Holdings",
    "Logistics",
    "Studio",
    "Partners",
    "Engineering",
    "Foods",
    "Consulting",
    "Retail",
)


def _rule(message: str, rule: str):
    from app.core.errors import BusinessRuleViolation

    return BusinessRuleViolation(message, {"rule": rule})


def _months(today: date, count: int) -> list[date]:
    """The first day of each of the last `count` whole months, oldest first."""
    first = today.replace(day=1)
    out = []
    for _ in range(count):
        first = (first - timedelta(days=1)).replace(day=1)
        out.append(first)
    return out[::-1]


def _on(month: date, day: int) -> date:
    return month.replace(day=min(day, month_calendar.monthrange(month.year, month.month)[1]))


@dataclass
class Plan:
    """One generated customer, before numbers are given out."""

    index: int
    segment: str
    customer_type: str
    name: str
    born: date
    risk: str
    country_id: uuid.UUID
    country_code: str
    currency: str
    products: list[str]
    yearly_minor: int  # income or turnover in minor units
    opening: dict[str, int]  # account type -> opening balance, minor units
    opened_at: datetime
    customer_number: str = ""  # given out when the batch is loaded
    ledger_ids: dict[str, uuid.UUID] = field(default_factory=dict)


def plan(
    seed: int,
    index: int,
    countries: list[tuple[uuid.UUID, str, str]],
    per_usd: dict[str, Decimal],
    today: date,
    history_start: date,
) -> Plan:
    rng = case_random(seed, index, "customers")
    segment_name = rng.choices(SEGMENT_NAMES, SEGMENT_WEIGHTS)[0]
    seg = SEGMENTS[segment_name]
    country_id, code, currency = countries[rng.randrange(len(countries))]
    years = rng.randint(*seg.ages)
    born = today - timedelta(days=years * 365 + rng.randint(0, 364))
    if seg.customer_type == "business":
        name = f"{rng.choice(LAST_NAMES)} {rng.choice(BUSINESS_SUFFIXES)}"
    else:
        name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
    risk = rng.choices(list(seg.risk), list(seg.risk.values()))[0]
    products = [p for p, share in seg.products.items() if rng.random() < share]

    def money(usd: float) -> int:
        local = Decimal(str(round(usd, 2))) * per_usd[currency]
        return int(to_minor_units(local.quantize(Decimal("0.01")), currency))

    low, high = seg.income_usd
    yearly = rng.uniform(low, high) if high < 300_000 else low * (high / low) ** rng.random()
    opening = {
        p: money(
            yearly * rng.uniform(0.02, 0.15) if p != "savings" else yearly * rng.uniform(0.05, 0.6)
        )
        for p in products
    }
    days_open = rng.randint(30, max(31, min(years * 365, 20 * 365)))
    opened = min(today - timedelta(days=days_open), history_start)
    return Plan(
        index,
        segment_name,
        seg.customer_type,
        name,
        born,
        risk,
        country_id,
        code,
        currency,
        products,
        money(yearly),
        opening,
        datetime.combine(opened, datetime.min.time(), UTC),
    )


def history(seed: int, p: Plan, months: list[date]) -> list[tuple[date, str, str, str, int]]:
    """(day, category, from, to, amount) movements; "from"/"to" are an account type or
    "bank" (the settlement side). Balances are kept at or above zero."""
    rng = case_random(seed, p.index, "history")
    seg = SEGMENTS[p.segment]
    balance = dict(p.opening)
    monthly = p.yearly_minor // 12
    out: list[tuple[date, str, str, str, int]] = []
    main = "business_current" if p.customer_type == "business" else "current"

    def move(day: date, category: str, src: str, dst: str, amount: int) -> None:
        if src != "bank":
            amount = min(amount, balance[src])
        if amount <= 0:
            return
        if src != "bank":
            balance[src] -= amount
        if dst != "bank":
            balance[dst] += amount
        out.append((day, category, src, dst, amount))

    for month in months:
        events: list[tuple[date, str, str, str, int]] = []
        if p.customer_type == "business":
            for _ in range(rng.randint(4, 8)):
                events.append(
                    (
                        _on(month, rng.randint(1, 28)),
                        "receipt",
                        "bank",
                        main,
                        int(monthly / 6 * rng.uniform(0.6, 1.4)),
                    )
                )
            for _ in range(rng.randint(3, 6)):
                events.append(
                    (
                        _on(month, rng.randint(2, 28)),
                        "supplier",
                        main,
                        "bank",
                        int(monthly / 8 * rng.uniform(0.5, 1.5)),
                    )
                )
            events.append(
                (_on(month, 28), "payroll", main, "bank", int(monthly * rng.uniform(0.2, 0.35)))
            )
        else:
            income = "pension" if p.segment == "senior" else "salary"
            events.append(
                (_on(month, 25), income, "bank", main, int(monthly * rng.uniform(0.97, 1.03)))
            )
            events.append(
                (_on(month, 1), "housing", main, "bank", int(monthly * rng.uniform(0.18, 0.32)))
            )
            for day in (rng.randint(3, 12), rng.randint(13, 22)):
                events.append(
                    (_on(month, day), "bills", main, "bank", int(monthly * rng.uniform(0.02, 0.06)))
                )
            for _ in range(rng.randint(*seg.card_spends)):
                events.append(
                    (
                        _on(month, rng.randint(1, 28)),
                        "card",
                        main,
                        "bank",
                        int(monthly * rng.uniform(0.005, 0.05)),
                    )
                )
            if "savings" in p.products and seg.saves:
                events.append(
                    (
                        _on(month, 26),
                        "savings",
                        main,
                        "savings",
                        int(monthly * seg.saves * rng.uniform(0.5, 1.5)),
                    )
                )
        events.sort(key=lambda e: e[0])
        for event in events:
            move(*event)
    return out


def _countries(db: Session) -> list[tuple[uuid.UUID, str, str]]:
    return [
        (c.id, c.iso_country_code, c.default_currency)
        for c in db.execute(
            select(Country)
            .where(Country.operational_status == OperationalStatus.ACTIVE)
            .order_by(Country.iso_country_code)
        ).scalars()
    ]


def _load_batch(
    db: Session,
    plans: list[Plan],
    *,
    seed: int,
    tag: str,
    months: list[date],
    history_start: date,
    teller: User,
    manager: User,
    totals: dict[str, Any],
) -> None:
    accounts = sum(len(p.products) for p in plans)
    customer_numbers = _numbers(db, "customer_number_seq", len(plans))
    if customer_numbers[-1] > MAX_CUSTOMER_NUMBER:
        raise PopulationError("Customer numbers are exhausted (CUS-9999999).")
    account_numbers = iter(_numbers(db, "account_number_seq", accounts))
    customers, rows = [], []
    for p, customer_number in zip(plans, customer_numbers, strict=True):
        customer_id = uuid.uuid4()
        p.customer_number = f"CUS-{customer_number:07d}"
        customers.append(
            (
                customer_id,
                p.customer_number,
                p.customer_type,
                p.name,
                p.born,
                p.country_id,
                p.risk,
                "verified",
                p.segment,
                tag,
            )
        )
        for product in p.products:
            account_number = make_account_number(p.country_code, next(account_numbers))
            p.ledger_ids[product] = uuid.uuid4()
            rows.append(
                {
                    "customer_id": customer_id,
                    "account_id": uuid.uuid4(),
                    "ledger_id": p.ledger_ids[product],
                    "request_id": uuid.uuid4(),
                    "account_number": account_number,
                    "type": product,
                    "currency": p.currency,
                    "opened_at": p.opened_at,
                }
            )
    cash = {cur: ledger.cash_account(db, cur).id for cur in {p.currency for p in plans}}
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
            " country_id, risk_rating, kyc_status, segment, generated_from",
            customers,
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
                    r["type"],
                    r["currency"],
                    "open",
                    r["ledger_id"],
                    r["opened_at"],
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
                    r["type"],
                    r["currency"],
                    "approved",
                    teller.id,
                    manager.id,
                    r["opened_at"],
                    NOTE,
                    r["account_id"],
                )
                for r in rows
            ),
        )

    def side(p: Plan, name: str) -> uuid.UUID:
        return cash[p.currency] if name == "bank" else p.ledger_ids[name]

    postings: list[ledger.Posting] = []
    for p in plans:
        key = f"{tag}:{p.customer_number}"
        for product, amount in p.opening.items():
            if amount > 0:
                postings.append(
                    ledger.Posting(
                        idempotency_key=f"{key}:open:{product}",
                        currency=p.currency,
                        description=f"Balance brought forward ({product}, synthetic)",
                        source=f"{SOURCE}.opening",
                        effective_date=history_start,
                        lines=[
                            ledger.LineSpec(cash[p.currency], Direction.DEBIT, amount),
                            ledger.LineSpec(p.ledger_ids[product], Direction.CREDIT, amount),
                        ],
                    )
                )
        for n, (day, category, src, dst, amount) in enumerate(history(seed, p, months)):
            postings.append(
                ledger.Posting(
                    idempotency_key=f"{key}:{n}",
                    currency=p.currency,
                    description=f"{category.title()} (synthetic)",
                    source=f"{SOURCE}.{category}",
                    effective_date=day,
                    # Debit where the money comes from, credit where it goes: money in debits
                    # the bank's cash (an asset) and credits the customer's deposit (a
                    # liability); money out the other way round; a transfer debits one deposit
                    # and credits the other.
                    lines=[
                        ledger.LineSpec(side(p, src), Direction.DEBIT, amount),
                        ledger.LineSpec(side(p, dst), Direction.CREDIT, amount),
                    ],
                )
            )
            totals["by_category"][category] = totals["by_category"].get(category, 0) + 1
    for start in range(0, len(postings), ledger.BULK_BATCH_LIMIT):
        ledger.post_entries(
            db, postings[start : start + ledger.BULK_BATCH_LIMIT], actor_id=teller.id
        )
    totals["accounts"] += accounts
    totals["entries"] += len(postings)
    for p in plans:
        totals["by_segment"][p.segment] = totals["by_segment"].get(p.segment, 0) + 1


def generate(
    factory: sessionmaker[Session],
    *,
    count: int,
    seed: int = 2030,
    history_months: int = 3,
    batch: int = BATCH,
    requested_by: str = "employee",
    decided_by: str = "manager",
    progress=None,
) -> dict[str, Any]:
    """Generate `count` customers of the seed (resuming a run that stopped part way)."""
    if not 1 <= count <= MAX_COUNT:
        raise _rule(f"Generate 1 to {MAX_COUNT:,} customers.", "count_invalid")
    if not 0 <= history_months <= MAX_HISTORY_MONTHS:
        raise _rule(f"History covers 0 to {MAX_HISTORY_MONTHS} months.", "history_invalid")
    if requested_by == decided_by:
        raise _rule("Four-eyes: the requester and the approver must differ.", "four_eyes")
    tag = f"{GENERATOR}:{seed}"
    started = time.perf_counter()
    with factory() as db:
        users = {
            u.username: u
            for u in db.execute(
                select(User).where(User.username.in_([requested_by, decided_by]))
            ).scalars()
        }
        countries = _countries(db)
        existing = db.execute(
            select(func.count()).select_from(Customer).where(Customer.generated_from == tag)
        ).scalar_one()
    if requested_by not in users or decided_by not in users:
        raise _rule(f"Users '{requested_by}' and '{decided_by}' must exist.", "users_missing")
    if not countries:
        raise _rule("No active country is configured.", "no_countries")
    today = datetime.now(UTC).date()
    months = _months(today, history_months)
    history_start = months[0] if months else today
    per_usd = {cur: rates.units_per_usd(cur, rates.ANCHOR_DATE) for _, _, cur in countries}
    totals: dict[str, Any] = {"accounts": 0, "entries": 0, "by_segment": {}, "by_category": {}}
    created = 0
    for start in range(existing, count, batch):
        size = min(batch, count - start)
        plans = [
            plan(seed, i, countries, per_usd, today, history_start)
            for i in range(start, start + size)
        ]
        with factory() as db, db.begin():
            _load_batch(
                db,
                plans,
                seed=seed,
                tag=tag,
                months=months,
                history_start=history_start,
                teller=users[requested_by],
                manager=users[decided_by],
                totals=totals,
            )
        created += size
        if progress:
            progress(existing + created, time.perf_counter() - started)
    seconds = round(time.perf_counter() - started, 1)
    with factory() as db, db.begin():
        if created:
            for table in (
                "customers",
                "accounts",
                "ledger_accounts",
                "journal_entries",
                "journal_lines",
            ):
                db.execute(text(f"ANALYZE {table}"))
        record_audit_event(
            db,
            actor_id=users[decided_by].id,
            action="customers.generated",
            entity_type="customer",
            entity_id=None,
            metadata={
                "seed": seed,
                "count": count,
                "created": created,
                "existing": existing,
                "history_months": history_months,
                "seconds": seconds,
            },
        )
    return {
        "generator": tag,
        "requested": count,
        "created": created,
        "existing": min(existing, count),
        "history_months": history_months,
        "accounts": totals["accounts"],
        "entries": totals["entries"],
        "by_segment": totals["by_segment"],
        "by_category": totals["by_category"],
        "seconds": seconds,
        "customers_per_second": round(created / seconds, 1) if created and seconds else None,
    }


def summary(db: Session) -> dict[str, Any]:
    """The customer base in numbers: segments, countries, products and history."""

    def grouped(sql: str) -> dict[str, int]:
        return {str(k): int(n) for k, n in db.execute(text(sql)).all()}

    total = db.execute(select(func.count()).select_from(Customer)).scalar_one()
    generated = db.execute(
        select(func.count()).select_from(Customer).where(Customer.generated_from.is_not(None))
    ).scalar_one()
    # Over every account (no join to customers): 0.8 s at a million customers, against 4.8 s
    # restricted to generated ones.
    holdings = grouped(
        "SELECT n, count(*) FROM (SELECT count(*) AS n FROM accounts GROUP BY customer_id) t "
        "GROUP BY n ORDER BY n"
    )
    return {
        "customers": total,
        "generated": generated,
        "segments": grouped(
            "SELECT coalesce(segment, 'unsegmented'), count(*) FROM customers "
            "GROUP BY 1 ORDER BY 2 DESC"
        ),
        "countries": grouped(
            "SELECT k.iso_country_code, count(*) FROM customers c JOIN "
            "countries k ON k.id = c.country_id GROUP BY 1 ORDER BY 2 DESC"
        ),
        "risk": grouped("SELECT risk_rating, count(*) FROM customers GROUP BY 1 ORDER BY 2 DESC"),
        "products": grouped(
            "SELECT account_type, count(*) FROM accounts GROUP BY 1 ORDER BY 2 DESC"
        ),
        "accounts_per_customer": holdings,
        "history": grouped(
            f"SELECT substr(source, {len(SOURCE) + 2}), count(*) FROM "  # nosec B608
            f"journal_entries WHERE source LIKE '{SOURCE}.%' GROUP BY 1 "
            "ORDER BY 2 DESC"
        ),
    }
