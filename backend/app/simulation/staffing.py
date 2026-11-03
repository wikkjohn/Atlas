"""Reviewers' working time (Phase 70, roadmap Milestone F step 2).

Without a staff schedule, simulated reviewers work around the clock (the model before Phase
70). With one, each reviewer has:

- **a shift** in the staff country's time zone: the schedule's shifts are given out in
  turn, e.g. 08:00 to 16:00 and 12:00 to 20:00 local time;
- **working days:** the country's business days (Phase 26): no weekends, no public holidays;
- **absences:** on each working day a reviewer is away with the schedule's absence rate,
  decided by the run's seed, the reviewer and the day, so a run repeats exactly.

A review starts when a reviewer is both free and at work. One that does not finish by the end
of the shift carries on at the reviewer's next shift. The work itself takes as long as it
would have: only the waiting changes.
"""

import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.modules.reference import calendar, data

MAX_DAYS = 60  # how far ahead to look for a working day


@dataclass
class StaffCalendar:
    start: datetime  # the run's simulated start (seconds are counted from it)
    country: str
    shifts: list[tuple[int, int]]  # (start hour, hours) in local time
    absence_rate: float
    seed: int | str
    _windows: dict[tuple[int, date], tuple[int, int] | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        reference = data.BY_CODE[self.country]
        self.profile = data.profile(reference)
        self.zone = ZoneInfo(reference.timezone)

    def shift(self, staff: int) -> tuple[int, int]:
        return self.shifts[staff % len(self.shifts)]

    def absent(self, staff: int, day: date) -> bool:
        return random.Random(f"{self.seed}:absence:{staff}:{day.isoformat()}").random() \
            < self.absence_rate  # fmt: skip

    def working(self, day: date) -> bool:
        return calendar.is_business_day(self.profile, day)

    def window(self, staff: int, day: date) -> tuple[int, int] | None:
        """The reviewer's shift on a local day, in seconds from the start; None when not at
        work (not a business day, or absent)."""
        key = (staff, day)
        if key not in self._windows:
            if not self.working(day) or self.absent(staff, day):
                self._windows[key] = None
            else:
                hour, hours = self.shift(staff)
                begins = datetime.combine(day, time(hour), self.zone)
                offset = (begins - self.start).total_seconds()
                self._windows[key] = (int(offset), int(offset + hours * 3600))
        return self._windows[key]

    def _local_day(self, seconds: int) -> date:
        return (self.start + timedelta(seconds=seconds)).astimezone(self.zone).date()

    def next_window(self, staff: int, at: int) -> tuple[int, int]:
        """The first shift that has not ended by `at`: (start, end), the start no earlier
        than `at`."""
        day = self._local_day(at) - timedelta(days=1)  # a shift may run past midnight
        for _ in range(MAX_DAYS):
            shift = self.window(staff, day)
            if shift is not None and shift[1] > at:
                return max(shift[0], at), shift[1]
            day += timedelta(days=1)
        raise ValueError(f"Reviewer {staff} has no shift within {MAX_DAYS} days.")

    def work(self, staff: int, at: int, seconds: int) -> tuple[int, int]:
        """When the reviewer, free from `at`, starts a piece of work of `seconds`, and when
        it is done, across shifts."""
        begin, end = self.next_window(staff, at)
        start, remaining, now = begin, seconds, begin
        while True:
            chunk = min(remaining, end - now)
            remaining -= chunk
            now += chunk
            if remaining <= 0:
                return start, now
            now, end = self.next_window(staff, end)

    def staff_days_absent(self, staff_count: int, until: int) -> int:
        """Working days lost to absence, from the start to `until`."""
        first, last = self._local_day(0), self._local_day(until)
        days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
        return sum(1 for s in range(staff_count) for d in days
                   if self.working(d) and self.absent(s, d))  # fmt: skip
