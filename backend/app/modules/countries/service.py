"""Country registry service."""

import uuid

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import diff, record_audit_event
from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.core.pagination import PageParams, paginate
from app.modules.countries.models import Country, OperationalStatus
from app.modules.countries.schemas import CountryCreate, CountryUpdate

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
) -> tuple[list[Country], int]:
    query = select(Country).order_by(Country.country_name)
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
