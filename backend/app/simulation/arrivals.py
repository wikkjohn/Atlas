"""Realistic arrival patterns (Phase 73, roadmap Milestone F step 5).

Without a pattern, each workload spreads its cases evenly over the scenario's arrival
window (the model before Phase 73). With one, the same cases arrive in the shape real
demand has, in a country's local time:

- **the hour of the day:** quiet at night, a morning rise, a lunchtime and an after-work
  peak;
- **the day of the week:** busy Mondays, quieter Saturdays, almost nothing on Sundays;
- **the month of the year:** seasonality, e.g. a January peak;
- **events:** a stretch of the window when demand is a multiple of usual, such as a
  marketing campaign, a salary day or a news story.

The workloads still draw each case's offset evenly over the window; the pattern then moves
it along the window by the inverse of the pattern's cumulative intensity. That keeps the
cases' order and every other draw (who the customer is, what they ask for), and a run
repeats exactly. While nothing queues, a run with a pattern differs from its baseline only
in when cases arrive; once peaks build queues, reviewers take cases in a different order,
so who reviews a case, and with it a reviewer's occasional mistake, can change too.
"""

import bisect
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, model_validator

from app.modules.reference import data

HOUR = 3600

# A retail bank's day, local time: 00:00 .. 23:00.
RETAIL_HOURS = [0.15, 0.1, 0.1, 0.1, 0.1, 0.2, 0.4, 0.7, 1.0, 1.3, 1.4, 1.4,
                1.8, 1.8, 1.3, 1.2, 1.2, 1.6, 1.7, 1.5, 1.1, 0.8, 0.5, 0.3]  # fmt: skip
RETAIL_WEEKDAYS = [1.3, 1.1, 1.0, 1.0, 1.15, 0.55, 0.2]  # Monday .. Sunday
FLAT_MONTHS = [1.0] * 12


class ArrivalEvent(BaseModel):
    """A stretch of the window with `multiplier` times the usual demand."""

    name: str = Field(min_length=1, max_length=60)
    start_hours: float = Field(ge=0)  # after the scenario's simulated start
    hours: float = Field(gt=0, le=24 * 31)
    multiplier: float = Field(gt=0, le=50)


class ArrivalPattern(BaseModel):
    country: str = Field(default="US", pattern=r"^[A-Z]{2}$")  # whose local time
    hourly: list[float] = Field(default_factory=lambda: list(RETAIL_HOURS))
    weekdays: list[float] = Field(default_factory=lambda: list(RETAIL_WEEKDAYS))
    months: list[float] = Field(default_factory=lambda: list(FLAT_MONTHS))
    events: list[ArrivalEvent] = Field(default_factory=list)

    @model_validator(mode="after")
    def _shape_valid(self) -> "ArrivalPattern":
        for name, values, size in (("hourly", self.hourly, 24), ("weekdays", self.weekdays, 7),
                                   ("months", self.months, 12)):  # fmt: skip
            if len(values) != size or any(v < 0 or not math.isfinite(v) for v in values):
                raise ValueError(f"'{name}' needs {size} weights of zero or more.")
            if not any(values):
                raise ValueError(f"'{name}' needs at least one weight above zero.")
        if self.country not in data.BY_CODE:
            raise ValueError(f"Unknown country '{self.country}'.")
        return self


class ArrivalShape:
    """The pattern over one window: where an evenly drawn offset lands."""

    def __init__(self, pattern: ArrivalPattern, start: datetime, window_seconds: int) -> None:
        self.pattern = pattern
        self.start = start
        self.window = max(1, window_seconds)
        self.zone = ZoneInfo(data.BY_CODE[pattern.country].timezone)
        # One bucket per started hour of the window (the last one may be shorter).
        self.bounds: list[int] = list(range(0, self.window, HOUR)) + [self.window]
        weights = [self.intensity(a) * (b - a) for a, b in zip(self.bounds, self.bounds[1:],
                                                                strict=False)]  # fmt: skip
        self.cumulative = [0.0]
        for w in weights:
            self.cumulative.append(self.cumulative[-1] + w)
        if self.cumulative[-1] <= 0:
            raise ValueError("The arrival pattern leaves no demand in the arrival window.")

    def intensity(self, offset: int) -> float:
        """Relative demand during the hour that starts `offset` seconds into the window."""
        local = (self.start + timedelta(seconds=offset)).astimezone(self.zone)
        p = self.pattern
        value = p.hourly[local.hour] * p.weekdays[local.weekday()] * p.months[local.month - 1]
        hours = offset / HOUR
        for event in p.events:
            if event.start_hours <= hours < event.start_hours + event.hours:
                value *= event.multiplier
        return value

    def place(self, offset: int) -> int:
        """The offset (0 .. window) moved to where the pattern's demand puts it."""
        target = min(max(offset, 0), self.window) / self.window * self.cumulative[-1]
        i = min(bisect.bisect_right(self.cumulative, target) - 1, len(self.bounds) - 2)
        # Skip empty buckets (zero demand), then interpolate within the bucket.
        while i < len(self.bounds) - 2 and self.cumulative[i + 1] == self.cumulative[i]:
            i += 1
        span = self.cumulative[i + 1] - self.cumulative[i]
        share = (target - self.cumulative[i]) / span if span else 0.0
        return int(self.bounds[i] + share * (self.bounds[i + 1] - self.bounds[i]))


def profile(pattern: ArrivalPattern, start: datetime, offsets: list[int]) -> dict:
    """How the cases arrived: by local hour and weekday, the busiest hour against the
    average hour, and the cases in each event."""
    zone = ZoneInfo(data.BY_CODE[pattern.country].timezone)
    by_hour = [0] * 24
    by_day = [0] * 7
    per_clock_hour: dict[int, int] = {}
    for offset in offsets:
        local = (start + timedelta(seconds=offset)).astimezone(zone)
        by_hour[local.hour] += 1
        by_day[local.weekday()] += 1
        per_clock_hour[offset // HOUR] = per_clock_hour.get(offset // HOUR, 0) + 1
    span_hours = (max(offsets) // HOUR + 1) if offsets else 1
    peak = max(per_clock_hour.values(), default=0)
    mean = len(offsets) / span_hours if span_hours else 0
    events = {e.name: sum(1 for o in offsets
                          if e.start_hours * HOUR <= o < (e.start_hours + e.hours) * HOUR)
              for e in pattern.events}  # fmt: skip
    return {
        "country": pattern.country,
        "by_local_hour": by_hour,
        "by_weekday": by_day,
        "peak_hour_cases": peak,
        "mean_hour_cases": round(mean, 2),
        "peak_to_mean": round(peak / mean, 2) if mean else None,
        "events": events,
    }
