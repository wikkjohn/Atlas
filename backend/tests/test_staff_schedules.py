"""Phase 70: reviewers' shifts, business days, absences and time zones in the simulation."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.simulation.scenarios import StaffSchedule, get_scenario
from app.simulation.staffing import StaffCalendar
from tests.factories import make_org_tree
from tests.test_outage_scenarios import _run
from tests.test_simulation import session_factory  # noqa: F401  (the fixture)

# Monday 5 January 2026, 09:00 UTC: 04:00 in New York.
START = datetime(2026, 1, 5, 9, tzinfo=UTC)
HOUR = 3600


def _calendar(**kw) -> StaffCalendar:
    return StaffCalendar(START, kw.get("country", "US"), kw.get("shifts", [(8, 8)]),
                         kw.get("absence_rate", 0.0), seed=1)  # fmt: skip


def test_shifts_follow_the_country_s_time_zone_and_business_days() -> None:
    cal = _calendar()
    # 08:00 in New York is 13:00 UTC, four hours after the start; the shift ends at 21:00.
    assert cal.next_window(0, 0) == (4 * HOUR, 12 * HOUR)
    # Free mid-shift, the reviewer starts at once.
    assert cal.next_window(0, 6 * HOUR) == (6 * HOUR, 12 * HOUR)
    # A review of 2 hours begun at 15:00 local (1 h before the end) finishes at 09:00 the
    # next morning: one hour today, one hour tomorrow.
    begin, done = cal.work(0, 11 * HOUR, 2 * HOUR)
    assert begin == 11 * HOUR and done == 24 * HOUR + 5 * HOUR
    # Friday 9 January, 15:30 local: a one-hour review carries over the weekend to Monday.
    friday = 4 * 24 * HOUR + 11 * HOUR + 30 * 60
    begin, done = cal.work(0, friday, HOUR)
    monday = 7 * 24 * HOUR + 4 * HOUR
    assert begin == friday and done == monday + 30 * 60
    # Monday 19 January is a US holiday (Martin Luther King Jr. Day): no shift that day.
    mlk = 14 * 24 * HOUR
    assert cal.window(0, (START + timedelta(seconds=mlk)).date()) is None
    assert cal.next_window(0, mlk)[0] == 15 * 24 * HOUR + 4 * HOUR
    # Shifts are given out in turn.
    two = _calendar(shifts=[(8, 8), (12, 8)])
    assert two.next_window(0, 0)[0] == 4 * HOUR and two.next_window(1, 0)[0] == 8 * HOUR
    # Tokyo is 14 hours ahead of New York: the start is 18:00 there, so 08:00 is tomorrow.
    assert _calendar(country="JP").next_window(0, 0)[0] == 14 * HOUR


def test_absences_are_seeded_and_take_whole_days() -> None:
    cal = _calendar(absence_rate=0.2)
    days = [(START + timedelta(days=i)).date() for i in range(200)]
    workdays = [d for d in days if cal.working(d)]
    away = [d for d in workdays if cal.absent(0, d)]
    assert 0.1 < len(away) / len(workdays) < 0.3
    assert [cal.absent(0, d) for d in days] == [_calendar(absence_rate=0.2).absent(0, d)
                                               for d in days]  # fmt: skip
    for d in away[:5]:
        assert cal.window(0, d) is None
    assert cal.staff_days_absent(1, 200 * 24 * HOUR) == len(away)


def test_the_schedule_is_validated() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        StaffSchedule(shifts=[(25, 8)])
    with pytest.raises(ValidationError):
        StaffSchedule(shifts=[])
    # Older scenarios keep their configuration, and so their hashes.
    base = get_scenario("retail-onboarding", 1)
    assert "staff_schedule" not in base.config.model_dump(mode="json", exclude_none=True)


def test_reviewers_on_shifts_make_cases_wait(db: Session, session_factory) -> None:  # noqa: F811
    make_org_tree(db)
    db.commit()
    around = _run(db, session_factory, get_scenario("retail-onboarding", 1), seed=505)
    shifts = _run(db, session_factory, get_scenario("retail-onboarding-shifts"), seed=505)
    assert around.status == shifts.status == "completed", shifts.failure_reason
    assert "staffing" not in around.results
    staffing = shifts.results["staffing"]
    assert staffing["schedule"]["country"] == "US" and staffing["reviewers"] > 0
    # Cases arrive from 04:00 in New York: they wait for the 08:00 shift.
    assert staffing["off_shift_wait_hours"] > 0
    assert shifts.results["review_queue_wait_hours"]["avg"] > \
        around.results["review_queue_wait_hours"]["avg"]  # fmt: skip
    assert shifts.results["cycle_time_hours"]["avg"] > around.results["cycle_time_hours"]["avg"]
    # The same decisions are taken either way: only the timing changes.
    assert shifts.results["completed"] == around.results["completed"]
    again = _run(db, session_factory, get_scenario("retail-onboarding-shifts"), seed=505)
    assert again.result_digest == shifts.result_digest
    assert again.results["staffing"] == staffing
