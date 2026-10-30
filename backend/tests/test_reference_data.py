"""Phase 23: country reference data for the 120-country footprint — the dataset, holiday
calendars, document and postal formats, the loader and the API."""

import json
import random
import re
import zoneinfo
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.money import minor_unit_exponent, to_minor_units
from app.core.permissions import RoleCode
from app.modules.countries.models import Country, Currency
from app.modules.countries.schemas import LANGUAGE_PATTERN
from app.modules.reference import calendar, data, loader, masks, synthetic
from tests.factories import auth, make_user

SNAPSHOT = Path(__file__).parents[1] / "alembic" / "versions" / "0020_reference_data.json"


def holidays_of(code: str, year: int) -> dict[str, tuple[date, date]]:
    found = calendar.holidays(data.profile(data.BY_CODE[code]), year)
    return {h["name"]: (h["date"], h["observed"]) for h in found}


# --- The dataset ------------------------------------------------------------------------------


def test_the_dataset_covers_120_countries_in_four_regions() -> None:
    codes = [c.code for c in data.COUNTRIES]
    assert len(codes) == len(set(codes)) == 120
    assert len({c.alpha3 for c in data.COUNTRIES}) == 120
    assert len({c.name for c in data.COUNTRIES}) == 120
    regions = {
        r: sum(c.region == r for c in data.COUNTRIES) for r in {c.region for c in data.COUNTRIES}
    }
    assert regions == {"americas": 22, "europe": 42, "middle_east_africa": 28, "asia_pacific": 28}
    # The bank's first five countries are among them.
    assert {"US", "GB", "DE", "SG", "JP"} <= set(codes)


@pytest.mark.parametrize("country", data.COUNTRIES, ids=lambda c: c.code)
def test_every_country_is_internally_consistent(country: data.CountryData) -> None:
    assert re.fullmatch(r"[A-Z]{2}", country.code) and re.fullmatch(r"[A-Z]{3}", country.alpha3)
    assert country.currency in data.CURRENCIES
    zoneinfo.ZoneInfo(country.timezone)
    assert country.languages and all(re.fullmatch(LANGUAGE_PATTERN, x) for x in country.languages)
    assert re.fullmatch(r"\+[0-9]{1,4}", country.calling_code)
    assert 1 <= len(country.weekend) <= 2 and set(country.weekend) <= set(range(1, 8))
    assert country.address in data.ADDRESS_STYLES
    assert country.regulator[0] and country.regulator[1]
    assert (country.address == "no_postal") == (not country.postal)
    assert country.easter in ("western", "orthodox")
    for mask in [*country.postal, country.passport, *(country.national_id or ("", ""))[1:]]:
        assert masks.matches([mask], masks.example(mask)), mask
        assert masks.matches([mask], masks.generate(mask, random.Random(1))), mask
    # Every rule computes for a decade, every holiday has a name, the year has business days.
    for year in range(2024, 2036):
        found = calendar.holidays(data.profile(country), year)
        assert all(h["date"].year == year and h["name"] for h in found)
        assert all((h["observed"] - h["date"]).days in range(-1, 8) for h in found)
    assert not country.holidays or len({h["name"] for h in country.holidays}) == len(
        country.holidays
    )


def test_currencies_follow_iso_4217_minor_units() -> None:
    assert data.CURRENCIES["JPY"][1] == data.CURRENCIES["KRW"][1] == data.CURRENCIES["XOF"][1] == 0
    assert data.CURRENCIES["KWD"][1] == data.CURRENCIES["BHD"][1] == data.CURRENCIES["TND"][1] == 3
    assert data.CURRENCIES["EUR"][1] == data.CURRENCIES["USD"][1] == 2
    # Money conversion reads the reference data; an unknown code keeps two decimals.
    assert (minor_unit_exponent("jpy"), minor_unit_exponent("OMR"), minor_unit_exponent("ZZZ")) == (
        0,
        3,
        2,
    )
    assert to_minor_units(5, "KWD") == 5000 and to_minor_units(5, "CLP") == 5


# --- Calendars --------------------------------------------------------------------------------


def test_easter_follows_both_computuses() -> None:
    assert [calendar.western_easter(y) for y in (2024, 2025, 2026, 2027)] == [
        date(2024, 3, 31), date(2025, 4, 20), date(2026, 4, 5), date(2027, 3, 28),
    ]  # fmt: skip
    assert [calendar.orthodox_easter(y) for y in (2024, 2025, 2026, 2027)] == [
        date(2024, 5, 5), date(2025, 4, 20), date(2026, 4, 12), date(2027, 5, 2),
    ]  # fmt: skip
    assert holidays_of("GR", 2026)["Clean Monday"][0] == date(2026, 2, 23)


def test_holiday_rules_and_weekend_observance() -> None:
    us = holidays_of("US", 2026)
    assert us["Independence Day"] == (date(2026, 7, 4), date(2026, 7, 3))  # Saturday → Friday
    assert us["Thanksgiving Day"][0] == date(2026, 11, 26)
    assert us["Memorial Day"][0] == date(2026, 5, 25)
    gb = holidays_of("GB", 2027)  # Christmas on a Saturday, Boxing Day on a Sunday
    assert gb["Christmas Day"][1] == date(2027, 12, 27)
    assert gb["Boxing Day"][1] == date(2027, 12, 28)
    assert holidays_of("CA", 2026)["Victoria Day"][0] == date(2026, 5, 18)
    assert holidays_of("SE", 2026)["Midsummer Eve"][0] == date(2026, 6, 19)
    assert holidays_of("IS", 2026)["First Day of Summer"][0] == date(2026, 4, 23)
    jp = holidays_of("JP", 2026)
    assert jp["Vernal Equinox Day"][0] == date(2026, 3, 20)
    assert jp["Constitution Memorial Day"][1] == date(2026, 5, 6)  # Sunday, after two holidays
    # A Saturday holiday stays on Saturday in Japan.
    assert holidays_of("JP", 2027)["Constitution Memorial Day"] == (date(2027, 5, 3),) * 2


def test_business_days_honour_each_country_weekend() -> None:
    friday, saturday, sunday = date(2026, 3, 6), date(2026, 3, 7), date(2026, 3, 8)
    sa, gb, bn = (data.profile(data.BY_CODE[c]) for c in ("SA", "GB", "BN"))
    assert not calendar.is_business_day(sa, friday) and calendar.is_business_day(sa, sunday)
    assert calendar.is_business_day(gb, friday) and not calendar.is_business_day(gb, sunday)
    assert not calendar.is_business_day(bn, friday) and calendar.is_business_day(bn, saturday)
    assert calendar.next_business_day(gb, date(2026, 12, 25)) == date(2026, 12, 29)


# --- Masks and synthetic values ---------------------------------------------------------------


def test_masks_validate_shapes_and_generate_deterministically() -> None:
    uk = list(data.BY_CODE["GB"].postal)
    assert masks.matches(uk, "SW1A 1AA") and masks.matches(uk, "M1 1AE")
    assert not masks.matches(uk, "12345") and not masks.matches(["99999"], "1234")
    assert masks.example("999-99-9999") == "123-45-6789"
    first = [masks.generate("AA9 9AA", random.Random(7)) for _ in range(2)]
    assert first[0] == first[1]
    lines = synthetic.format_address(
        {"lines": data.ADDRESS_STYLES["city_region_postal"]},
        street="1 Synthetic Street", city="Testville", region="NY", postal_code=None,
    )  # fmt: skip
    assert lines == ["1 Synthetic Street", "Testville, NY"]


# --- Database and loader ----------------------------------------------------------------------


def test_the_migration_snapshot_matches_the_dataset() -> None:
    snapshot = json.loads(SNAPSHOT.read_text())
    assert snapshot["version"] == data.VERSION
    assert snapshot["currencies"] == loader.currency_rows()
    assert snapshot["countries"] == json.loads(
        json.dumps([loader.country_row(c) for c in data.COUNTRIES])
    ), "Regenerate 0020_reference_data.json, or add a migration for the new version."


def test_the_database_holds_the_reference_data(db: Session) -> None:
    countries = {c.iso_country_code: c for c in db.execute(select(Country)).scalars()}
    assert len(countries) == 120
    assert sum(c.operational_status == "active" for c in countries.values()) == 5
    assert db.execute(select(Currency)).scalars().all().__len__() == len(data.CURRENCIES)
    sa = countries["SA"]
    assert (sa.iso_alpha3, sa.calling_code, sa.weekend_days) == ("SAU", "+966", [5, 6])
    assert sa.regulator == {"name": "Saudi Central Bank", "abbreviation": "SAMA"}
    gb = countries["GB"]
    assert gb.address_format["requires_region"] is False
    assert gb.identity_documents[0] == {
        "type": "national_id", "name": "National Insurance number", "mask": "AA999999A",
        "example": "AB123456C",
    }  # fmt: skip


def test_loading_again_changes_nothing_and_keeps_operator_fields(db: Session) -> None:
    assert loader.apply(db) == {"currencies_added": 0, "countries_added": 0, "countries_updated": 0}
    de = db.execute(select(Country).where(Country.iso_country_code == "DE")).scalar_one()
    de.country_name, de.weekend_days = "Germany (renamed by an operator)", [7]
    db.flush()
    assert loader.apply(db)["countries_updated"] == 1
    assert de.weekend_days == [6, 7]  # reference data restored
    assert de.country_name == "Germany (renamed by an operator)"  # operator's choice kept
    assert de.operational_status == "active"


# --- API --------------------------------------------------------------------------------------


@pytest.fixture
def reader(db: Session) -> dict[str, str]:
    return auth(make_user(db, RoleCode.BANKING_EMPLOYEE))


def country_id(client: TestClient, headers: dict, code: str) -> str:
    page = client.get(f"/api/v1/countries?q={code}", headers=headers).json()
    return next(c["id"] for c in page["items"] if c["iso_country_code"] == code)


def test_the_reference_api(client: TestClient, reader: dict) -> None:
    currencies = {c["code"]: c for c in client.get("/api/v1/currencies", headers=reader).json()}
    assert currencies["JPY"] == {"code": "JPY", "name": "Japanese yen", "minor_units": 0}

    gb = country_id(client, reader, "GB")
    detail = client.get(f"/api/v1/countries/{gb}", headers=reader).json()
    assert (detail["iso_alpha3"], detail["calling_code"], detail["reference_version"]) == (
        "GBR", "+44", data.VERSION,
    )  # fmt: skip
    year = client.get(f"/api/v1/countries/{gb}/calendar?year=2026", headers=reader).json()
    assert year["business_days"] == 253  # 261 weekdays, 8 bank holidays
    boxing = next(h for h in year["holidays"] if h["name"] == "Boxing Day")
    assert (boxing["date"], boxing["observed"]) == ("2026-12-26", "2026-12-28")
    assert (
        client.get(f"/api/v1/countries/{gb}/calendar?year=1900", headers=reader).status_code == 422
    )

    day = client.get(f"/api/v1/countries/{gb}/business-day?on=2026-12-28", headers=reader).json()
    assert day == {
        "date": "2026-12-28", "business_day": False, "holiday": "Boxing Day",
        "next_business_day": "2026-12-29",
    }  # fmt: skip

    check = lambda kind, value: client.post(  # noqa: E731
        f"/api/v1/countries/{gb}/check", json={"kind": kind, "value": value}, headers=reader
    ).json()
    assert check("postal_code", "sw1a 1aa")["valid"] is True
    assert check("postal_code", "12345")["valid"] is False
    assert check("national_id", "AB123456C")["valid"] is True

    samples = client.get(f"/api/v1/countries/{gb}/samples?count=3&seed=4", headers=reader).json()
    assert (
        samples
        == client.get(f"/api/v1/countries/{gb}/samples?count=3&seed=4", headers=reader).json()
    )  # deterministic
    for s in samples:
        assert masks.matches(list(data.BY_CODE["GB"].postal), s["postal_code"])
        assert s["address_lines"][-1] == s["postal_code"]
        assert check("national_id", s["national_id"])["valid"] is True
