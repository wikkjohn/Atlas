"""Phase 25: the country rules engine — versioned rules per country, and how account opening
(WF-0001) and payments (WF-0002) apply them."""

import uuid
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditEvent
from app.core.errors import BusinessRuleViolation
from app.core.permissions import RoleCode
from app.modules.compliance.screening import SANCTIONS_LISTS, screen_name
from app.modules.countries.models import Country
from app.modules.payments.models import Payment
from app.modules.reference import data
from app.modules.rules import defaults, service
from app.modules.rules.schemas import CountryRules
from tests.factories import (
    application,
    auth,
    country,
    funded_account,
    make_staff,
    make_user,
    payment,
)

TODAY = datetime.now(UTC).date()


def bump(db: Session, code: str, change, effective_from: date = date(2026, 2, 1)) -> CountryRules:
    """Add a version of a country's rules changed by `change` (a function of a dict)."""
    target = country(db, code)
    rules = service.rules_on(db, target, effective_from).model_dump()
    change(rules)
    model = CountryRules.model_validate(rules)
    service.add_version(db, target, model, effective_from, "test", None)
    return model


# --- Rules and versions -----------------------------------------------------------------------


def test_every_country_starts_with_valid_default_rules(db: Session) -> None:
    for entry in data.COUNTRIES:
        CountryRules.model_validate(defaults.default_rules(entry))
    countries = db.execute(select(Country)).scalars().all()
    assert all(service.version_on(db, c, TODAY) is not None for c in countries)
    gb, kr, kw = (service.rules_on(db, country(db, c), TODAY) for c in ("GB", "KR", "KW"))
    assert (gb.kyc.min_age, gb.payments.cutoff, gb.payments.high_value_major) == (
        18,
        "17:30",
        10_000,
    )
    assert gb.screening.lists == ["synthetic-watchlist-v1", "synthetic-uk-v1"]
    assert kr.kyc.min_age == 19
    assert kw.payments.high_value_major == 3_100  # $10,000 in dinars, two figures
    assert service.rules_on(db, country(db, "DE"), TODAY).screening.lists[1] == "synthetic-eu-v1"


def test_versions_take_effect_on_their_date_and_are_audited(db: Session) -> None:
    gb = country(db, "GB")
    bump(db, "GB", lambda r: r["kyc"].update(min_age=21), effective_from=date(2030, 1, 1))
    assert service.rules_on(db, gb, date(2029, 12, 31)).kyc.min_age == 18
    assert service.rules_on(db, gb, date(2030, 1, 1)).kyc.min_age == 21
    event = db.execute(
        select(AuditEvent).where(AuditEvent.action == "country_rules.versioned")
    ).scalar_one()
    assert event.event_metadata["changes"] == {"kyc.min_age": {"from": 18, "to": 21}}
    with pytest.raises(BusinessRuleViolation):  # cannot slip in before the latest version
        bump(db, "GB", lambda r: None, effective_from=date(2029, 6, 1))


def test_rules_are_validated() -> None:
    base = defaults.default_rules(data.BY_CODE["GB"])
    for broken in (
        {**base, "kyc": {**base["kyc"], "min_age": 12}},
        {**base, "kyc": {**base["kyc"], "identity_documents": []}},
        {**base, "screening": {"lists": ["no-such-list"]}},
        {**base, "payments": {**base["payments"], "cutoff": "25:00"}},
        {**base, "payments": {**base["payments"], "max_payment_major": 5}},
    ):
        with pytest.raises(ValueError):
            CountryRules.model_validate(broken)


def test_screening_checks_every_list_a_country_uses() -> None:
    assert screen_name("Lena Nominee")["hit"] is False  # not on the global list
    hit = screen_name("lena  NOMINEE", ["synthetic-watchlist-v1", "synthetic-eu-v1"])
    assert (hit["hit"], hit["list"]) == (True, "synthetic-eu-v1")
    assert len(SANCTIONS_LISTS) == 5


def test_value_dates_follow_the_cutoff_and_the_calendar(db: Session) -> None:
    gb = country(db, "GB")
    rules = service.rules_on(db, gb, TODAY)  # cut-off 17:30 London
    tuesday = date(2026, 3, 3)
    before = datetime(2026, 3, 3, 12, 0, tzinfo=UTC)
    after = datetime(2026, 3, 3, 18, 0, tzinfo=UTC)
    friday_late = datetime(2026, 3, 6, 18, 0, tzinfo=UTC)
    assert service.value_date(gb, rules, before) == tuesday
    assert service.value_date(gb, rules, after) == date(2026, 3, 4)
    assert service.value_date(gb, rules, friday_late) == date(2026, 3, 9)  # over the weekend
    christmas_eve = datetime(2026, 12, 24, 18, 0, tzinfo=UTC)
    assert service.value_date(gb, rules, christmas_eve) == date(2026, 12, 29)  # holidays


# --- Account opening (WF-0001) ----------------------------------------------------------------


def test_account_opening_applies_the_countrys_minimum_age_and_documents(
    client: TestClient, db: Session
) -> None:
    staff = make_staff(db)
    bump(db, "GB", lambda r: r["kyc"].update(min_age=21, identity_documents=["passport"]))
    start = lambda body: client.post(  # noqa: E731
        "/api/v1/workflows/WF-0001/executions", json={"input": body}, headers=auth(staff.employee)
    ).json()
    young = start(application(born="2006-01-15"))  # 20 years old in 2026
    assert young["outcome"] == "rejected"
    assert "require age 21 or over" in str(young["context"]["validate_application"]["reasons"])
    national = start(application(documents=["national_id", "proof_of_address"]))
    assert national["context"]["validate_application"]["status"] == "missing_documents"
    assert national["context"]["validate_application"]["missing"] == ["passport"]


def test_proof_of_address_can_be_waived_and_regional_lists_screen(
    client: TestClient, db: Session
) -> None:
    staff = make_staff(db)
    bump(db, "DE", lambda r: r["kyc"].update(proof_of_address=False))
    done = client.post(
        "/api/v1/workflows/WF-0001/executions",
        json={"input": application(name="Lena Nominee", country_code="DE", documents=["passport"])},
        headers=auth(staff.employee),
    ).json()
    assert done["context"]["validate_application"]["status"] == "valid"
    screened = done["context"]["sanctions_screening"]
    assert (screened["hit"], screened["list"]) == (True, "synthetic-eu-v1")


# --- Payments (WF-0002) -----------------------------------------------------------------------


def test_payments_take_limits_and_value_dates_from_the_payers_country(
    client: TestClient, db: Session
) -> None:
    staff = make_staff(db)
    bump(db, "US", lambda r: r["payments"].update(high_value_major=100, max_payment_major=5_000))
    debtor = funded_account(db, staff, balance=1_000_000)  # US customer, USD
    creditor = funded_account(db, staff)
    start = lambda amount: client.post(  # noqa: E731
        "/api/v1/workflows/WF-0002/executions",
        json={"input": payment(debtor, creditor, amount)},
        headers=auth(staff.employee),
    ).json()
    over = start(600_000)  # $6,000 > the $5,000 limit
    assert over["outcome"] == "rejected"
    assert "single-payment limit" in str(over["context"]["reject_payment"]["reasons"])
    held = start(15_000)  # $150 ≥ the $100 high-value threshold: needs an approver
    validated = held["context"]["validate_payment"]
    assert validated["high_value"] is True and held["status"] == "waiting"
    record = db.get(Payment, uuid.UUID(validated["payment_id"]))
    assert record.high_value_threshold == 10_000
    assert record.value_date is not None and record.value_date >= TODAY
    listed = client.get(
        "/api/v1/payments", params={"q": record.payment_number}, headers=auth(staff.employee)
    ).json()["items"][0]
    assert listed["high_value"] is True and listed["value_date"] == record.value_date.isoformat()


# --- API --------------------------------------------------------------------------------------


def test_the_rules_api(client: TestClient, db: Session) -> None:
    reader = auth(make_user(db, RoleCode.BANKING_EMPLOYEE))
    admin = auth(make_user(db, RoleCode.PLATFORM_ADMINISTRATOR))
    jp = country(db, "JP")
    shown = client.get(f"/api/v1/countries/{jp.id}/rules", headers=reader).json()
    assert shown["current"]["version"] == 1
    assert shown["effective"]["payments"]["cutoff"] == "15:00"
    lists = client.get("/api/v1/sanctions-lists", headers=reader).json()
    assert {item["list_id"] for item in lists} == set(SANCTIONS_LISTS)

    body = {
        "rules": {**shown["effective"], "kyc": {**shown["effective"]["kyc"], "min_age": 20}},
        "effective_from": "2031-04-01",
        "note": "Synthetic regulatory change",
    }
    assert (
        client.post(f"/api/v1/countries/{jp.id}/rules", json=body, headers=reader).status_code
        == 403
    )
    bad = {**body, "rules": {**body["rules"], "screening": {"lists": ["nope"]}}}
    assert (
        client.post(f"/api/v1/countries/{jp.id}/rules", json=bad, headers=admin).status_code == 422
    )
    created = client.post(f"/api/v1/countries/{jp.id}/rules", json=body, headers=admin)
    assert created.status_code == 201, created.text
    assert created.json()["version"] == 2
    later = client.get(
        f"/api/v1/countries/{jp.id}/rules", params={"on": "2031-04-01"}, headers=reader
    ).json()
    assert later["effective"]["kyc"]["min_age"] == 20
    assert [v["version"] for v in later["versions"]] == [2, 1]
