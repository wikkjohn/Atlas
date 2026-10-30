"""Country rules: the version in force on a day, new versions, and what callers need from
them (KYC requirements, sanctions lists, payment limits and value dates)."""

import uuid
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import diff, record_audit_event
from app.core.errors import BusinessRuleViolation
from app.core.money import to_minor_units
from app.modules.countries.models import Country
from app.modules.identity.models import User
from app.modules.reference import calendar, data
from app.modules.rules import defaults
from app.modules.rules.models import CountryRuleSet
from app.modules.rules.schemas import CountryRules, RuleVersionOut


def default_for(country: Country) -> CountryRules:
    found = data.BY_CODE.get(country.iso_country_code)
    raw = (
        defaults.default_rules(found)
        if found is not None
        else defaults.generic_rules(country.default_currency)
    )
    return CountryRules.model_validate(raw)


def versions(db: Session, country: Country) -> list[CountryRuleSet]:
    return list(
        db.execute(
            select(CountryRuleSet)
            .where(CountryRuleSet.country_id == country.id)
            .order_by(CountryRuleSet.version.desc())
        ).scalars()
    )


def version_on(db: Session, country: Country, on: date) -> CountryRuleSet | None:
    return db.execute(
        select(CountryRuleSet)
        .where(CountryRuleSet.country_id == country.id, CountryRuleSet.effective_from <= on)
        .order_by(CountryRuleSet.effective_from.desc(), CountryRuleSet.version.desc())
        .limit(1)
    ).scalar_one_or_none()


def rules_on(db: Session, country: Country, on: date) -> CountryRules:
    """The rules in force in a country on a day (its defaults before any version exists)."""
    found = version_on(db, country, on)
    return CountryRules.model_validate(found.rules) if found else default_for(country)


def add_version(
    db: Session,
    country: Country,
    rules: CountryRules,
    effective_from: date,
    note: str,
    actor_id: uuid.UUID | None,
) -> CountryRuleSet:
    """A new version; it may not take effect before the latest existing one."""
    latest = db.execute(
        select(CountryRuleSet)
        .where(CountryRuleSet.country_id == country.id)
        .order_by(CountryRuleSet.version.desc())
        .limit(1)
        .with_for_update()
    ).scalar_one_or_none()
    if latest is not None and effective_from < latest.effective_from:
        raise BusinessRuleViolation(
            f"Version {latest.version} takes effect on {latest.effective_from}; a new version "
            "cannot take effect earlier.",
            {"rule": "effective_from_order"},
        )
    previous = (
        CountryRules.model_validate(latest.rules) if latest else default_for(country)
    ).model_dump()
    record = CountryRuleSet(
        country_id=country.id,
        version=(latest.version + 1) if latest else 1,
        effective_from=effective_from,
        rules=rules.model_dump(),
        note=note,
        created_by=actor_id,
    )
    db.add(record)
    db.flush()
    record_audit_event(
        db,
        actor_id=actor_id,
        action="country_rules.versioned",
        entity_type="country",
        entity_id=country.id,
        metadata={
            "country": country.iso_country_code,
            "version": record.version,
            "effective_from": effective_from.isoformat(),
            "changes": diff(_flat(previous), _flat(rules.model_dump())),
            "note": note,
        },
    )
    return record


def _flat(rules: dict[str, Any]) -> dict[str, Any]:
    return {
        f"{group}.{key}": value for group, values in rules.items() for key, value in values.items()
    }


def version_out(db: Session, records: list[CountryRuleSet]) -> list[RuleVersionOut]:
    ids = {r.created_by for r in records if r.created_by}
    names = (
        dict(db.execute(select(User.id, User.username).where(User.id.in_(ids))).tuples().all())
        if ids
        else {}
    )
    return [
        RuleVersionOut(
            id=r.id,
            version=r.version,
            effective_from=r.effective_from,
            rules=CountryRules.model_validate(r.rules),
            note=r.note,
            created_by_username=names.get(r.created_by) if r.created_by else None,
            created_at=r.created_at,
        )
        for r in records
    ]


def apply_defaults(db: Session) -> int:
    """Give every country without rules its default version 1; returns how many."""
    has_rules = select(CountryRuleSet.country_id).distinct()
    missing = db.execute(select(Country).where(Country.id.not_in(has_rules))).scalars().all()
    for country in missing:
        db.add(
            CountryRuleSet(
                country_id=country.id,
                version=1,
                effective_from=defaults.EFFECTIVE_FROM,
                rules=default_for(country).model_dump(),
                note="Default rules from the reference data",
            )
        )
    db.flush()
    return len(missing)


def count(db: Session) -> int:
    return db.execute(select(func.count()).select_from(CountryRuleSet)).scalar_one()


# --- What callers need -----------------------------------------------------------------------


def payment_limits(rules: CountryRules, currency: str) -> tuple[int, int]:
    """(high-value threshold, single-payment limit) in minor units of the currency."""
    return (
        to_minor_units(rules.payments.high_value_major, currency),
        to_minor_units(rules.payments.max_payment_major, currency),
    )


def value_date(country: Country, rules: CountryRules, now: datetime) -> date:
    """The business day a payment instructed at `now` settles on: today in the country if
    it is a business day and the cut-off has not passed, else the next business day."""
    local = now.astimezone(ZoneInfo(country.default_timezone))
    cutoff = time.fromisoformat(rules.payments.cutoff)
    profile = country.calendar_profile()
    day = local.date()
    if local.time() >= cutoff:
        day += timedelta(days=1)
    return calendar.next_business_day(profile, day)
