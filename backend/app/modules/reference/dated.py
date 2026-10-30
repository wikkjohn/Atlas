"""Dated holidays of lunar and lunisolar calendars (Phase 26), 2025–2030.

Their Gregorian dates cannot be computed from a simple rule: they follow moon sightings or
published calendars. These tables give the first day of each festival by year as published
or widely expected; Islamic dates in particular can move by a day when the moon is sighted.
A country's holiday rule `{"name", "festival": key, "offset": days}` takes the festival's
date in a year plus `offset`. Outside the years listed the holiday is not computed.
Compiled for the simulation; not authoritative.
"""

from datetime import date

FIRST_YEAR, LAST_YEAR = 2025, 2030


def _d(*days: str) -> dict[int, date]:
    found = [date.fromisoformat(d) for d in days]
    return {d.year: d for d in found}


FESTIVALS: dict[str, dict[int, date]] = {
    "lunar_new_year": _d(
        "2025-01-29", "2026-02-17", "2027-02-06", "2028-01-26", "2029-02-13", "2030-02-03"
    ),
    "qingming": _d(
        "2025-04-04", "2026-04-05", "2027-04-05", "2028-04-04", "2029-04-04", "2030-04-05"
    ),
    "dragon_boat": _d(
        "2025-05-31", "2026-06-19", "2027-06-09", "2028-05-28", "2029-06-16", "2030-06-05"
    ),
    "mid_autumn": _d(
        "2025-10-06", "2026-09-25", "2027-09-15", "2028-10-03", "2029-09-22", "2030-09-12"
    ),
    "eid_al_fitr": _d(
        "2025-03-30", "2026-03-20", "2027-03-10", "2028-02-27", "2029-02-15", "2030-02-05"
    ),
    "eid_al_adha": _d(
        "2025-06-06", "2026-05-27", "2027-05-16", "2028-05-05", "2029-04-24", "2030-04-13"
    ),
    "islamic_new_year": _d(
        "2025-06-26", "2026-06-16", "2027-06-06", "2028-05-25", "2029-05-14", "2030-05-03"
    ),
    "mawlid": _d(
        "2025-09-04", "2026-08-25", "2027-08-14", "2028-08-03", "2029-07-24", "2030-07-13"
    ),
    "diwali": _d(
        "2025-10-20", "2026-11-08", "2027-10-29", "2028-10-17", "2029-11-05", "2030-10-26"
    ),
    "vesak": _d("2025-05-12", "2026-05-31", "2027-05-20", "2028-05-09", "2029-05-27", "2030-05-16"),
    "rosh_hashanah": _d(
        "2025-09-23", "2026-09-12", "2027-10-02", "2028-09-21", "2029-09-10", "2030-09-28"
    ),
    "passover": _d(
        "2025-04-13", "2026-04-02", "2027-04-22", "2028-04-11", "2029-03-31", "2030-04-18"
    ),
}


def on(festival: str, year: int) -> date | None:
    return FESTIVALS[festival].get(year)


def _rules(name: str, festival: str, offsets: tuple[int, ...]) -> list[dict]:
    """One rule per day of a festival; the first is `name`, later ones "(day 2)" etc."""
    return [
        {"name": name if i == 0 else f"{name} (day {i + 1})", "festival": festival, "offset": o}
        for i, o in enumerate(offsets)
    ]


def _eve(name: str, festival: str, offset: int = -1) -> list[dict]:
    return [{"name": name, "festival": festival, "offset": offset}]


EID_FITR, EID_ADHA = "Eid al-Fitr", "Eid al-Adha"


def _islamic(fitr: int, adha: int, *, new_year: bool = False, mawlid: bool = False,
             arafat: bool = False) -> list[dict]:  # fmt: skip
    found = _rules(EID_FITR, "eid_al_fitr", tuple(range(fitr)))
    found += _rules(EID_ADHA, "eid_al_adha", tuple(range(adha)))
    if arafat:
        found += _eve("Day of Arafah", "eid_al_adha")
    if new_year:
        found += _rules("Islamic New Year", "islamic_new_year", (0,))
    if mawlid:
        found += _rules("Prophet's Birthday", "mawlid", (0,))
    return found


# Country code -> dated holiday rules added to its reference data (version 2026.2).
DATED: dict[str, list[dict]] = {
    # Middle East and Africa
    "AE": _islamic(3, 3, arafat=True, new_year=True, mawlid=True),
    "SA": _islamic(4, 4, arafat=True),
    "QA": _islamic(3, 3),
    "KW": _islamic(3, 3, arafat=True, new_year=True, mawlid=True),
    "BH": _islamic(3, 3, arafat=True, new_year=True, mawlid=True),
    "OM": _islamic(3, 3, arafat=True, new_year=True, mawlid=True),
    "JO": _islamic(3, 4, arafat=True, new_year=True, mawlid=True),
    "LB": _islamic(1, 1, new_year=True, mawlid=True),
    "EG": _islamic(3, 4, arafat=True, new_year=True, mawlid=True),
    "MA": _islamic(2, 2, new_year=True, mawlid=True),
    "TN": _islamic(2, 2, new_year=True, mawlid=True),
    "DZ": _islamic(2, 2, new_year=True, mawlid=True),
    "NG": _islamic(2, 2, mawlid=True),
    "GH": _islamic(1, 1),
    "KE": _islamic(1, 0),
    "TZ": _islamic(2, 1, mawlid=True),
    "UG": _islamic(1, 1),
    "ET": _islamic(1, 1, mawlid=True),
    "MU": _islamic(1, 0) + _rules("Chinese Spring Festival", "lunar_new_year", (0,))
    + _rules("Diwali", "diwali", (0,)),
    "SN": _islamic(1, 1, new_year=True, mawlid=True),
    "CI": _islamic(1, 1, mawlid=True),
    "CM": _islamic(1, 1),
    "IL": _rules("Rosh Hashanah", "rosh_hashanah", (0, 1))
    + _rules("Yom Kippur", "rosh_hashanah", (9,))
    + _rules("Sukkot", "rosh_hashanah", (14,))
    + _rules("Simchat Torah", "rosh_hashanah", (21,))
    + _rules("Passover", "passover", (0,))
    + _rules("Last day of Passover", "passover", (6,))
    + _rules("Shavuot", "passover", (50,)),
    # Europe
    "TR": _islamic(3, 4, arafat=True),
    "BA": _islamic(1, 1),
    "AL": _islamic(1, 1),
    # Asia Pacific
    "CN": _rules("Spring Festival", "lunar_new_year", (0, 1, 2))
    + _rules("Qingming Festival", "qingming", (0,))
    + _rules("Dragon Boat Festival", "dragon_boat", (0,))
    + _rules("Mid-Autumn Festival", "mid_autumn", (0,)),
    "HK": _rules("Lunar New Year", "lunar_new_year", (0, 1, 2))
    + _rules("Ching Ming Festival", "qingming", (0,))
    + _rules("Buddha's Birthday", "vesak", (0,))
    + _rules("Tuen Ng Festival", "dragon_boat", (0,))
    + _rules("Day following the Mid-Autumn Festival", "mid_autumn", (1,)),
    "MO": _rules("Lunar New Year", "lunar_new_year", (0, 1, 2))
    + _rules("Ching Ming Festival", "qingming", (0,))
    + _rules("Dragon Boat Festival", "dragon_boat", (0,))
    + _rules("Day following the Mid-Autumn Festival", "mid_autumn", (1,)),
    "TW": _eve("Lunar New Year's Eve", "lunar_new_year")
    + _rules("Lunar New Year", "lunar_new_year", (0, 1, 2))
    + _rules("Tomb Sweeping Day", "qingming", (0,))
    + _rules("Dragon Boat Festival", "dragon_boat", (0,))
    + _rules("Mid-Autumn Festival", "mid_autumn", (0,)),
    "KR": _eve("Seollal (eve)", "lunar_new_year")
    + _rules("Seollal", "lunar_new_year", (0, 1))
    + _eve("Chuseok (eve)", "mid_autumn")
    + _rules("Chuseok", "mid_autumn", (0, 1)),
    "SG": _rules("Chinese New Year", "lunar_new_year", (0, 1))
    + _rules("Hari Raya Puasa", "eid_al_fitr", (0,))
    + _rules("Vesak Day", "vesak", (0,))
    + _rules("Hari Raya Haji", "eid_al_adha", (0,))
    + _rules("Deepavali", "diwali", (0,)),
    "MY": _rules("Chinese New Year", "lunar_new_year", (0, 1))
    + _islamic(2, 1, new_year=True, mawlid=True)
    + _rules("Wesak Day", "vesak", (0,))
    + _rules("Deepavali", "diwali", (0,)),
    "BN": _rules("Chinese New Year", "lunar_new_year", (0,))
    + _islamic(3, 1, new_year=True, mawlid=True),
    "ID": _rules("Chinese New Year", "lunar_new_year", (0,))
    + _islamic(2, 1, new_year=True, mawlid=True)
    + _rules("Vesak Day", "vesak", (0,)),
    "PH": _rules("Chinese New Year", "lunar_new_year", (0,)) + _islamic(1, 1),
    "VN": _eve("Tết (eve)", "lunar_new_year")
    + _rules("Tết", "lunar_new_year", (0, 1, 2, 3)),
    "TH": _rules("Visakha Bucha Day", "vesak", (0,)),
    "KH": _rules("Visak Bochea Day", "vesak", (0,)),
    "LA": _rules("Boun Visakha Bousa", "vesak", (0,)),
    "IN": _rules("Diwali", "diwali", (0,)) + _islamic(1, 1),
    "PK": _islamic(3, 3, mawlid=True),
    "BD": _islamic(3, 3, mawlid=True) + _rules("Buddha Purnima", "vesak", (0,)),
    "LK": _rules("Vesak Full Moon Poya Day", "vesak", (0, 1)) + _rules("Deepavali", "diwali", (0,))
    + _islamic(1, 1, mawlid=True),
    "NP": _rules("Tihar", "diwali", (0, 1)) + _rules("Buddha Jayanti", "vesak", (0,)),
    "MV": _islamic(3, 4, new_year=True, mawlid=True),
    "KZ": _islamic(0, 1),
    "UZ": _islamic(1, 1),
    "FJ": _rules("Diwali", "diwali", (0,)) + _islamic(0, 0, mawlid=True),
    "TT": _rules("Divali", "diwali", (0,)) + _islamic(1, 0),
}  # fmt: skip
