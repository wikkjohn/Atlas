"""Public holidays and business days computed from a country's holiday rules.

A rule is one of
- a fixed date: `{"name", "date": "MM-DD"}`;
- relative to Easter Sunday: `{"name", "easter": days}` (Western or Orthodox computus, as
  the country's `easter` says);
- the n-th weekday of a month: `{"name", "nth": [month, iso_weekday, n]}` (n = -1: last);
- the last weekday before, or the first after, a date: `{"name", "before": [month, day,
  iso_weekday]}` (Canada's Victoria Day), `{"name", "after": [...]}`;
- Japan's equinox days: `{"name", "equinox": "vernal" | "autumnal"}` (the published
  approximation, valid 1980–2099).

Fixed dates that fall on a weekend move to the next business day when the country's
`observance` is `next_weekday`, to the nearest weekday (Saturday → Friday, Sunday →
Monday) for `nearest_weekday`, and only from a Sunday for `sunday_to_next`. Holidays of
lunar calendars (Eid, Lunar New Year, Diwali …) are not computed: they need dated tables,
which arrive with the business calendars of a later step.
"""

from datetime import date, timedelta
from typing import Any

MAX_SHIFT_DAYS = 7


def western_easter(year: int) -> date:
    """Anonymous Gregorian computus."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return date(year, month, day + 1)


def orthodox_easter(year: int) -> date:
    """Meeus's Julian computus, converted to the Gregorian calendar (valid 1900–2099)."""
    a, b, c = year % 4, year % 7, year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month, day = divmod(d + e + 114, 31)
    return date(year, month, day + 1) + timedelta(days=13)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    if n > 0:
        first = date(year, month, 1)
        return first + timedelta(days=(weekday - first.isoweekday()) % 7 + 7 * (n - 1))
    following = date(year + month // 12, month % 12 + 1, 1)
    last = following - timedelta(days=1)
    return last - timedelta(days=(last.isoweekday() - weekday) % 7 + 7 * (-n - 1))


def _equinox(year: int, kind: str) -> date:
    base = 20.8431 if kind == "vernal" else 23.2488
    day = int(base + 0.242194 * (year - 1980) - (year - 1980) // 4)
    return date(year, 3 if kind == "vernal" else 9, day)


def _date(rule: dict[str, Any], year: int, easter: date) -> date:
    if "date" in rule:
        month, day = map(int, rule["date"].split("-"))
        return date(year, month, day)
    if "easter" in rule:
        return easter + timedelta(days=rule["easter"])
    if "nth" in rule:
        return _nth_weekday(year, *rule["nth"])
    if "before" in rule:
        month, day, weekday = rule["before"]
        on = date(year, month, day) - timedelta(days=1)
        return on - timedelta(days=(on.isoweekday() - weekday) % 7)
    if "after" in rule:
        month, day, weekday = rule["after"]
        on = date(year, month, day) + timedelta(days=1)
        return on + timedelta(days=(weekday - on.isoweekday()) % 7)
    if "equinox" in rule:
        return _equinox(year, rule["equinox"])
    raise ValueError(f"Unknown holiday rule {rule!r}.")


def holidays(profile: dict[str, Any], year: int) -> list[dict[str, Any]]:
    """The country's public holidays in a year: `{date, name, observed}` sorted by date,
    where `observed` is the day off when a weekend moved it (else the date itself)."""
    weekend = set(profile["weekend"])
    easter = (orthodox_easter if profile.get("easter") == "orthodox" else western_easter)(year)
    found: list[dict[str, Any]] = []
    for rule in profile["holidays"]:
        on = _date(rule, year, easter)
        movable = "date" in rule or "equinox" in rule
        found.append({"date": on, "name": rule["name"], "observed": on, "fixed": movable})
    found.sort(key=lambda h: (h["date"], h["name"]))

    observance = profile.get("observance", "none")
    taken = {h["date"] for h in found if h["date"].isoweekday() not in weekend}
    for h in found:
        if not h["fixed"] or observance == "none" or h["date"].isoweekday() not in weekend:
            continue
        if observance == "sunday_to_next" and h["date"].isoweekday() != 7:
            continue
        on = h["date"]
        if observance == "nearest_weekday":
            on += timedelta(days=-1 if on.isoweekday() == 6 else 1)
        while on.isoweekday() in weekend or on in taken:
            on += timedelta(days=1)
            if (on - h["date"]).days > MAX_SHIFT_DAYS:
                break
        h["observed"] = on
        taken.add(on)
    return [{k: h[k] for k in ("date", "name", "observed")} for h in found]


def days_off(profile: dict[str, Any], year: int) -> set[date]:
    return {h["observed"] for h in holidays(profile, year)}


def is_business_day(profile: dict[str, Any], day: date) -> bool:
    return day.isoweekday() not in profile["weekend"] and day not in days_off(profile, day.year)


def next_business_day(profile: dict[str, Any], day: date) -> date:
    """The first business day on or after `day`."""
    while not is_business_day(profile, day):
        day += timedelta(days=1)
    return day
