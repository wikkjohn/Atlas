"""Phase 26: dated lunar holidays, business-day schedules and simulation arrivals."""

import uuid
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Connection, select, update
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.jobs import engine
from app.jobs.models import Job, JobSchedule
from app.modules.reference import calendar, data, dated
from app.simulation.models import SimulationCaseResult, SimulationStatus
from app.simulation.router import get_simulation_sessionmaker
from app.simulation.runner import business_offset, create_run, execute_run
from app.simulation.scenarios import get_scenario
from tests.factories import auth, make_org_tree, make_user


def holidays_of(code: str, year: int) -> dict[str, tuple[date, date]]:
    profile = data.profile(data.BY_CODE[code])
    return {h["name"]: (h["date"], h["observed"]) for h in calendar.holidays(profile, year)}


@pytest.fixture
def factory(db_connection: Connection):
    def make() -> Session:
        return Session(
            bind=db_connection,
            join_transaction_mode="create_savepoint",
            autoflush=False,
            expire_on_commit=False,
        )

    return make


@pytest.fixture(autouse=True)
def quiet_schedules(db: Session) -> None:
    db.execute(update(JobSchedule).values(next_run_at=datetime.now(UTC) + timedelta(days=1)))
    db.flush()


# --- Dated holidays -------------------------------------------------------------------------------


def test_every_festival_has_one_date_a_year_in_the_table_range() -> None:
    for festival, days in dated.FESTIVALS.items():
        assert sorted(days) == list(range(dated.FIRST_YEAR, dated.LAST_YEAR + 1)), festival
    for code, rules in dated.DATED.items():
        assert code in data.BY_CODE
        names = [r["name"] for r in rules]
        assert len(names) == len(set(names)), code
        assert all(r["festival"] in dated.FESTIVALS for r in rules)


def test_dated_holidays_and_their_observance() -> None:
    sa = holidays_of("SA", 2026)
    assert sa["Eid al-Fitr"][0] == date(2026, 3, 20)
    assert sa["Eid al-Fitr (day 4)"][0] == date(2026, 3, 23)
    assert sa["Day of Arafah"][0] == date(2026, 5, 26)
    # Vesak on Sunday 31 May is observed on Monday in Singapore.
    assert holidays_of("SG", 2026)["Vesak Day"] == (date(2026, 5, 31), date(2026, 6, 1))
    kr = holidays_of("KR", 2026)
    assert kr["Chuseok"][0] == date(2026, 9, 25)
    il = holidays_of("IL", 2026)
    assert il["Yom Kippur"][0] == date(2026, 9, 21)
    assert il["Shavuot"][0] == date(2026, 5, 22)
    assert holidays_of("CN", 2027)["Spring Festival (day 3)"][0] == date(2027, 2, 8)
    # A Lunar New Year's Eve falling in the previous Gregorian year belongs to that year.
    assert holidays_of("VN", 2028)["Tết (eve)"][0] == date(2028, 1, 25)


def test_no_dated_holidays_outside_the_table() -> None:
    assert "Eid al-Fitr" not in holidays_of("SA", 2031)
    assert holidays_of("SA", 2031)  # the fixed holidays remain
    assert all(dated.on(f, 2031) is None for f in dated.FESTIVALS)
    assert data.BY_CODE["SA"].notes == (data._DATED_NOTE,)


# --- Schedules ------------------------------------------------------------------------------------


def _schedule(db: Session, at: datetime, country: str | None = "GB") -> JobSchedule:
    schedule = JobSchedule(
        name=f"test-{uuid.uuid4().hex[:8]}",
        description="test",
        kind="ledger.reconcile",
        payload={"mode": "incremental"},
        interval_seconds=24 * 3600,
        enabled=True,
        business_calendar=country,
        next_run_at=at,
    )
    db.add(schedule)
    db.commit()
    return schedule


def test_a_schedule_due_on_a_weekend_moves_to_the_next_business_day(db: Session, factory) -> None:
    saturday = datetime(2025, 1, 4, 10, 0, tzinfo=UTC)
    schedule = _schedule(db, saturday)

    assert engine.tick_schedules(factory) == []
    db.refresh(schedule)
    assert schedule.next_run_at == datetime(2025, 1, 6, 10, 0, tzinfo=UTC)
    assert not db.execute(select(Job).where(Job.schedule_name == schedule.name)).first()

    queued = engine.tick_schedules(factory)  # Monday is in the past: due now
    assert len(queued) == 1
    db.refresh(schedule)
    nxt = schedule.next_run_at.astimezone(ZoneInfo("Europe/London")).date()
    assert calendar.is_business_day(data.profile(data.BY_CODE["GB"]), nxt)


def test_business_runs_skip_holidays_and_weekends(db: Session) -> None:
    schedule = _schedule(db, datetime.now(UTC) + timedelta(days=1))
    christmas = datetime(2026, 12, 25, 9, 0, tzinfo=UTC)  # Friday; Boxing Day observed Monday
    assert engine._business_run(db, schedule, christmas) == datetime(2026, 12, 29, 9, 0, tzinfo=UTC)
    plain = _schedule(db, datetime.now(UTC) + timedelta(days=1), country=None)
    assert engine._business_run(db, plain, christmas) == christmas
    # Late Thursday evening in UTC is already Friday, the weekend, in Saudi Arabia.
    gulf = _schedule(db, datetime.now(UTC) + timedelta(days=1), country="SA")
    thursday = datetime(2026, 10, 1, 21, 0, tzinfo=UTC)
    assert engine._business_run(db, gulf, thursday) == thursday + timedelta(days=2)


@pytest.fixture
def api(app: FastAPI, factory) -> TestClient:
    app.dependency_overrides[get_simulation_sessionmaker] = lambda: factory
    with TestClient(app) as client:
        yield client


def test_the_schedule_api_sets_and_clears_a_business_calendar(api: TestClient, db: Session) -> None:
    admin = auth(make_user(db, RoleCode.PLATFORM_ADMINISTRATOR))
    url = "/api/v1/job-schedules/loan-servicing"

    changed = api.patch(url, json={"business_calendar": "GB"}, headers=admin)
    assert changed.status_code == 200 and changed.json()["business_calendar"] == "GB"
    listed = {s["name"]: s for s in api.get("/api/v1/job-schedules", headers=admin).json()}
    assert listed["loan-servicing"]["business_calendar"] == "GB"

    assert api.patch(url, json={"business_calendar": "ZZ"}, headers=admin).status_code == 422
    assert api.patch(url, json={"business_calendar": "gb"}, headers=admin).status_code == 422
    # Leaving it out keeps it; an empty string clears it.
    kept = api.patch(url, json={"enabled": False}, headers=admin)
    assert kept.json()["business_calendar"] == "GB"
    cleared = api.patch(url, json={"business_calendar": ""}, headers=admin)
    assert cleared.status_code == 200 and cleared.json()["business_calendar"] is None


# --- Simulation -----------------------------------------------------------------------------------


def test_business_offset_moves_arrivals_past_weekends_and_holidays() -> None:
    start = datetime(2026, 4, 2, 8, 0, tzinfo=UTC)  # Thursday before Easter
    hour = 3600
    assert business_offset(start, 2 * hour, "GB") == 2 * hour
    assert business_offset(start, 2 * hour, None) == 2 * hour
    # Good Friday, Saturday, Sunday and Easter Monday: all move to Tuesday 7 April.
    for day in (1, 2, 3, 4):
        assert business_offset(start, day * 24 * hour + hour, "GB") == 5 * 24 * hour + hour
    # In the US, Good Friday is a working day.
    assert business_offset(start, 24 * hour, "US") == 24 * hour


def test_the_easter_payment_scenario_arrives_on_business_days_only(db: Session, factory) -> None:
    make_org_tree(db)
    scenario = get_scenario("payments-easter")
    assert scenario.config.business_calendar == "GB"
    creator = make_user(db, RoleCode.AI_RESEARCHER)
    run = create_run(
        db, scenario, profile="custom", applications=30, employees=8, seed=7, created_by=creator.id
    )
    db.commit()
    execute_run(factory, run.id)
    db.expire_all()
    db.refresh(run)
    assert run.status == SimulationStatus.COMPLETED

    cases = (
        db.execute(select(SimulationCaseResult).where(SimulationCaseResult.run_id == run.id))
        .scalars()
        .all()
    )
    assert len(cases) == 30
    london = ZoneInfo("Europe/London")
    days = Counter(c.arrived_at.astimezone(london).date() for c in cases)
    assert set(days) <= {date(2026, 4, 2), date(2026, 4, 7)}
    assert days[date(2026, 4, 7)] > 0  # the Easter weekend's arrivals queue up for Tuesday
