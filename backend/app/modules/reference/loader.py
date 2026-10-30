"""Write the reference data into the database, idempotently.

Missing currencies and countries are added (new countries as `planned`); existing countries
get their reference fields refreshed, while what operators manage — name, time zone,
languages, operational status — is left as it is. The currency of an existing country is
never changed (balances depend on it).
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.modules.reference import data, masks

REFERENCE_FIELDS = (
    "iso_alpha3",
    "calling_code",
    "weekend_days",
    "easter",
    "holiday_observance",
    "holiday_rules",
    "regulator",
    "identity_documents",
    "address_format",
    "reference_notes",
    "reference_version",
)


def currency_rows() -> list[dict[str, Any]]:
    return [
        {"code": code, "name": name, "minor_units": units}
        for code, (name, units) in sorted(data.CURRENCIES.items())
    ]


def _documents(c: data.CountryData) -> list[dict[str, Any]]:
    found = []
    if c.national_id is not None:
        name, mask = c.national_id
        found.append({"type": "national_id", "name": name, "mask": mask})
    found.append({"type": "passport", "name": "Passport", "mask": c.passport})
    return [{**d, "example": masks.example(d["mask"])} for d in found]


def _address(c: data.CountryData) -> dict[str, Any]:
    lines = data.ADDRESS_STYLES[c.address]
    return {
        "style": c.address,
        "lines": lines,
        "postal_code_masks": list(c.postal),
        "postal_code_example": masks.example(c.postal[0]) if c.postal else None,
        "requires_region": any("{region}" in line for line in lines),
    }


def reference_fields(c: data.CountryData) -> dict[str, Any]:
    return {
        "iso_alpha3": c.alpha3,
        "calling_code": c.calling_code,
        "weekend_days": list(c.weekend),
        "easter": c.easter,
        "holiday_observance": c.observance,
        "holiday_rules": [dict(h) for h in c.holidays],
        "regulator": {"name": c.regulator[0], "abbreviation": c.regulator[1]},
        "identity_documents": _documents(c),
        "address_format": _address(c),
        "reference_notes": list(c.notes),
        "reference_version": data.VERSION,
    }


def country_row(c: data.CountryData) -> dict[str, Any]:
    """A whole new `countries` row (planned)."""
    return {
        "iso_country_code": c.code,
        "country_name": c.name,
        "region": c.region,
        "default_currency": c.currency,
        "default_timezone": c.timezone,
        "supported_languages": list(c.languages),
        "operational_status": "planned",
        **reference_fields(c),
    }


def apply(db: Session, actor_id: uuid.UUID | None = None) -> dict[str, int]:
    """Load the reference data; returns what changed."""
    from app.modules.countries.models import Country, Currency

    counts = {"currencies_added": 0, "countries_added": 0, "countries_updated": 0}
    known = set(db.execute(select(Currency.code)).scalars())
    for row in currency_rows():
        if row["code"] not in known:
            db.add(Currency(**row))
            counts["currencies_added"] += 1
    db.flush()
    existing = {c.iso_country_code: c for c in db.execute(select(Country)).scalars()}
    for entry in data.COUNTRIES:
        country = existing.get(entry.code)
        if country is None:
            db.add(Country(**country_row(entry)))
            counts["countries_added"] += 1
            continue
        fields = reference_fields(entry)
        if any(getattr(country, k) != v for k, v in fields.items()):
            for k, v in fields.items():
                setattr(country, k, v)
            counts["countries_updated"] += 1
    db.flush()
    if any(counts.values()):
        record_audit_event(
            db,
            actor_id=actor_id,
            action="reference_data.applied",
            entity_type="reference_data",
            entity_id=None,
            metadata={"version": data.VERSION, **counts},
        )
    return counts
