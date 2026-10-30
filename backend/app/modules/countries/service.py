"""Country registry service."""

import random
import uuid
from datetime import date, timedelta

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import diff, record_audit_event
from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.core.pagination import PageParams, paginate
from app.modules.countries.models import Country, Currency, OperationalStatus
from app.modules.countries.schemas import CountryCreate, CountryUpdate
from app.modules.reference import calendar, masks, synthetic

_AUDITED = ("country_name", "default_timezone", "supported_languages", "operational_status")


def get_country(db: Session, country_id: uuid.UUID) -> Country:
    country = db.get(Country, country_id)
    if country is None:
        raise NotFoundError("Country not found.")
    return country


def require_active_country(db: Session, country_id: uuid.UUID, purpose: str) -> Country:
    """Fetch a country that the bank currently operates in, or raise a business-rule error."""
    country = db.get(Country, country_id)
    if country is None:
        raise BusinessRuleViolation("country_id does not reference a configured country.")
    if country.operational_status != OperationalStatus.ACTIVE:
        raise BusinessRuleViolation(
            f"{country.country_name} is '{country.operational_status}'; {purpose} requires an "
            "active country.",
            {"country": country.iso_country_code, "status": country.operational_status},
        )
    return country


def list_countries(
    db: Session,
    params: PageParams,
    *,
    region: str | None = None,
    status: str | None = None,
    q: str | None = None,
    currency: str | None = None,
) -> tuple[list[Country], int]:
    query = select(Country).order_by(Country.country_name)
    if currency:
        query = query.where(Country.default_currency == currency.upper())
    if region:
        query = query.where(Country.region == region)
    if status:
        query = query.where(Country.operational_status == status)
    if q:
        pattern = f"%{q.strip()}%"
        query = query.where(
            or_(Country.country_name.ilike(pattern), Country.iso_country_code.ilike(pattern))
        )
    return paginate(db, query, params)


def create_country(db: Session, data: CountryCreate, actor_id: uuid.UUID) -> Country:
    require_currency(db, data.default_currency)
    country = Country(**data.model_dump(mode="json"))
    db.add(country)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError as exc:
        raise ConflictError("A country with this ISO code or name already exists.") from exc
    db.refresh(country)
    record_audit_event(
        db,
        actor_id=actor_id,
        action="country.created",
        entity_type="country",
        entity_id=country.id,
        metadata=data.model_dump(mode="json"),
    )
    return country


def update_country(
    db: Session, country: Country, data: CountryUpdate, actor_id: uuid.UUID
) -> Country:
    before = {field: getattr(country, field) for field in _AUDITED}
    for field, value in data.model_dump(mode="json", exclude_unset=True).items():
        if value is not None:
            setattr(country, field, value)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError as exc:
        raise ConflictError("A country with this name already exists.") from exc
    db.refresh(country)
    changes = diff(before, {field: getattr(country, field) for field in _AUDITED})
    if changes:
        record_audit_event(
            db,
            actor_id=actor_id,
            action="country.updated",
            entity_type="country",
            entity_id=country.id,
            metadata={"changes": changes},
        )
    return country


# --- Reference data (Phase 23) ---------------------------------------------------------------


def list_currencies(db: Session) -> list[Currency]:
    return list(db.execute(select(Currency).order_by(Currency.code)).scalars())


def require_currency(db: Session, code: str) -> Currency:
    found = db.get(Currency, code)
    if found is None:
        raise BusinessRuleViolation(
            f"{code} is not a known currency; add it to the reference data first.",
            {"currency": code},
        )
    return found


def calendar_of(country: Country, year: int) -> dict:
    profile = country.calendar_profile()
    found = calendar.holidays(profile, year)
    days_off = {h["observed"] for h in found}
    day, business = date(year, 1, 1), 0
    while day.year == year:
        if day.isoweekday() not in profile["weekend"] and day not in days_off:
            business += 1
        day += timedelta(days=1)
    return {
        "iso_country_code": country.iso_country_code,
        "year": year,
        "weekend_days": profile["weekend"],
        "holidays": found,
        "business_days": business,
        "notes": country.reference_notes,
    }


def business_day(country: Country, on: date) -> dict:
    profile = country.calendar_profile()
    holiday = next(
        (h["name"] for h in calendar.holidays(profile, on.year) if h["observed"] == on), None
    )
    return {
        "date": on,
        "business_day": calendar.is_business_day(profile, on),
        "holiday": holiday,
        "next_business_day": calendar.next_business_day(profile, on),
    }


def check_value(country: Country, kind: str, value: str) -> dict:
    if kind == "postal_code":
        found = (country.address_format or {}).get("postal_code_masks") or []
    else:
        found = [d["mask"] for d in country.identity_documents if d["type"] == kind]
    cleaned = value.strip().upper()
    return {"kind": kind, "value": cleaned, "valid": masks.matches(found, cleaned), "masks": found}


def samples(country: Country, count: int, seed: int) -> list[dict]:
    rng = random.Random(f"{country.iso_country_code}:{seed}")
    found = []
    for _ in range(count):
        documents = country.identity_documents
        postal = synthetic.postal_code(country.address_format, rng)
        found.append(
            {
                "national_id": synthetic.document_number(documents, "national_id", rng),
                "passport": synthetic.document_number(documents, "passport", rng),
                "postal_code": postal,
                "address_lines": synthetic.address(country.address_format, rng, postal),
            }
        )
    return found
