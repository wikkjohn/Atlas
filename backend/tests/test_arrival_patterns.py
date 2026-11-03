"""Phase 73: realistic arrival patterns — daily and weekly peaks, seasonality and events."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.simulation.arrivals import ArrivalEvent, ArrivalPattern, ArrivalShape, profile
from app.simulation.scenarios import get_scenario, register_scenario
from tests.factories import make_org_tree
from tests.test_outage_scenarios import _run
from tests.test_simulation import session_factory  # noqa: F401  (the fixture)

# Monday 5 January 2026, 09:00 UTC: 04:00 in New York.
START = datetime(2026, 1, 5, 9, tzinfo=UTC)
WEEK = 7 * 24 * 3600
NEW_YORK = ZoneInfo("America/New_York")


def _placed(pattern: ArrivalPattern, n: int = 20_000, window: int = WEEK) -> list[int]:
    shape = ArrivalShape(pattern, START, window)
    return [shape.place(round(i * window / (n - 1))) for i in range(n)]


def _local(offset: int) -> datetime:
    return (START + timedelta(seconds=offset)).astimezone(NEW_YORK)


def test_a_flat_pattern_changes_nothing_and_placing_keeps_the_order() -> None:
    flat = ArrivalPattern(hourly=[1] * 24, weekdays=[1] * 7, months=[1] * 12)
    shape = ArrivalShape(flat, START, WEEK)
    for offset in (0, 1, 3_599, 3_600, 250_000, WEEK - 1, WEEK):
        assert abs(shape.place(offset) - offset) <= 1
    placed = _placed(ArrivalPattern())
    assert placed == sorted(placed)  # monotone: cases keep their order
    assert 0 <= placed[0] and placed[-1] <= WEEK


def test_the_retail_pattern_has_daily_and_weekly_peaks() -> None:
    placed = _placed(ArrivalPattern())
    hours = [_local(o).hour for o in placed]
    days = [_local(o).weekday() for o in placed]
    night = sum(1 for h in hours if 1 <= h <= 4)
    lunch = sum(1 for h in hours if 12 <= h <= 13)
    assert lunch > 8 * night  # 1.8 against 0.1 an hour, two hours against four
    monday, sunday = days.count(0), days.count(6)
    assert monday > 4 * sunday
    # Profile: by hour and weekday, peak against mean.
    shown = profile(ArrivalPattern(), START, placed)
    assert sum(shown["by_local_hour"]) == sum(shown["by_weekday"]) == len(placed)
    assert shown["peak_to_mean"] > 1.5


def test_an_event_multiplies_demand_and_months_set_the_season() -> None:
    event = ArrivalEvent(name="campaign", start_hours=56, hours=6, multiplier=3.0)
    flat = dict(hourly=[1] * 24, weekdays=[1] * 7, months=[1] * 12)
    placed = _placed(ArrivalPattern(**flat, events=[event]))
    inside = sum(1 for o in placed if 56 * 3600 <= o < 62 * 3600)
    before = sum(1 for o in placed if 50 * 3600 <= o < 56 * 3600)
    assert 2.7 < inside / before < 3.3
    assert profile(ArrivalPattern(**flat, events=[event]), START, placed)["events"] == {
        "campaign": inside
    }
    # A window over January and February: February has twice the weight.
    season = ArrivalPattern(**{**flat, "months": [1, 2] + [1] * 10})
    window = 59 * 24 * 3600
    placed = _placed(season, window=window)
    january = sum(1 for o in placed if _local(o).month == 1)
    assert 1.6 < (len(placed) - january) / january < 2.4  # 28 days at 2 against 31 at 1


def test_the_pattern_is_validated() -> None:
    with pytest.raises(ValidationError):
        ArrivalPattern(hourly=[1] * 23)
    with pytest.raises(ValidationError):
        ArrivalPattern(weekdays=[0] * 7)
    with pytest.raises(ValidationError):
        ArrivalPattern(months=[-1] + [1] * 11)
    with pytest.raises(ValidationError):
        ArrivalPattern(country="XX")
    # Demand only on Sundays, in a window of Monday to Friday: nothing can arrive.
    with pytest.raises(ValueError, match="no demand"):
        ArrivalShape(ArrivalPattern(weekdays=[0, 0, 0, 0, 0, 0, 1]), START, 4 * 24 * 3600)
    # Older scenarios keep their configuration, and so their hashes.
    base = get_scenario("retail-onboarding", 1)
    assert "arrival_pattern" not in base.config.model_dump(mode="json", exclude_none=True)


def test_a_week_of_real_demand_against_an_even_week(db: Session, session_factory) -> None:  # noqa: F811
    make_org_tree(db)
    db.commit()
    week = get_scenario("retail-onboarding-week")
    assert week.config.arrival_window_hours == 168.0
    even = week.model_copy(update={
        "scenario_id": "test-retail-onboarding-even-week",
        "config": week.config.model_copy(update={"arrival_pattern": None})})  # fmt: skip
    register_scenario(even)
    peaks = _run(db, session_factory, week, seed=606, applications=80)
    flat = _run(db, session_factory, even, seed=606, applications=80)
    assert peaks.status == flat.status == "completed", peaks.failure_reason
    assert "arrivals" not in flat.results
    arrivals = peaks.results["arrivals"]
    assert arrivals["country"] == "US" and sum(arrivals["by_weekday"]) == 80
    assert arrivals["by_weekday"][0] > arrivals["by_weekday"][6]
    assert arrivals["events"]["campaign"] > 0
    # The same cases, decided the same way: at this size nothing queues, so only when they
    # arrived changed (with queues, who reviews a case can change too; see arrivals.py).
    assert peaks.results["completed"] == flat.results["completed"]
    assert peaks.results["outcomes"] == flat.results["outcomes"]
    # The digest records decisions, not times: it is the same. When the cases arrived is
    # not, and so neither is when the run ended.
    assert peaks.result_digest == flat.result_digest
    assert peaks.results["simulated_hours"] != flat.results["simulated_hours"]
    again = _run(db, session_factory, week, seed=606, applications=80)
    assert again.result_digest == peaks.result_digest
    assert again.results["arrivals"] == arrivals
