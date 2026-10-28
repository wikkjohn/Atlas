"""Simulation clock: simulated time that only moves forward, independently of wall time."""

from datetime import datetime, timedelta


class ClockError(Exception):
    pass


class SimulationClock:
    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ClockError("The simulation clock needs a timezone-aware start time.")
        self._start = start
        self._now = start

    @property
    def start(self) -> datetime:
        return self._start

    @property
    def now(self) -> datetime:
        return self._now

    @property
    def elapsed(self) -> timedelta:
        return self._now - self._start

    def advance_to(self, moment: datetime) -> None:
        if moment < self._now:
            raise ClockError(f"Time cannot go backwards ({moment} < {self._now}).")
        self._now = moment
