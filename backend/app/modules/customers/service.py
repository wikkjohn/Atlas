"""Customer service."""

import uuid
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.audit import diff, record_audit_event
from app.core.errors import BusinessRuleViolation, NotFoundError
from app.core.pagination import PageParams, paginate
from app.modules.countries.service import require_active_country
from app.modules.customers.models import (
    CUSTOMER_NUMBER_SEQUENCE,
    KYC_TRANSITIONS,
    Customer,
    CustomerType,
    KycStatus,
    RiskRating,
)
from app.modules.customers.schemas import (
    CustomerCreate,
    CustomerOut,
    CustomerReview,
    CustomerUpdate,
)

OLDEST_BIRTH_DATE = date(1900, 1, 1)


def to_out(customer: Customer) -> CustomerOut:
    return CustomerOut(
        id=customer.id,
        customer_number=customer.customer_number,
        customer_type=customer.customer_type,
        name=customer.name,
        date_of_birth_or_incorporation=customer.date_of_birth_or_incorporation,
        country_id=customer.country_id,
        country_code=customer.country.iso_country_code,
        currency=customer.country.default_currency,
        risk_rating=customer.risk_rating,
        kyc_status=customer.kyc_status,
        created_at=customer.created_at,
        updated_at=customer.updated_at,
    )


def age_in_years(born: date, on: date) -> int:
    return on.year - born.year - ((on.month, on.day) < (born.month, born.day))


def get_customer(db: Session, customer_id: uuid.UUID, *, for_update: bool = False) -> Customer:
    query = select(Customer).where(Customer.id == customer_id)
    if for_update:
        query = query.with_for_update(of=Customer)
    customer = db.execute(query).unique().scalar_one_or_none()
    if customer is None:
        raise NotFoundError("Customer not found.")
    return customer


def list_customers(
    db: Session,
    params: PageParams,
    *,
    q: str | None = None,
    customer_type: str | None = None,
    country_id: uuid.UUID | None = None,
    risk_rating: str | None = None,
    kyc_status: str | None = None,
) -> tuple[list[Customer], int]:
    query = select(Customer).order_by(Customer.name, Customer.id)
    if q:
        pattern = f"%{q.strip()}%"
        query = query.where(
            or_(Customer.name.ilike(pattern), Customer.customer_number.ilike(pattern))
        )
    if customer_type:
        query = query.where(Customer.customer_type == customer_type)
    if country_id:
        query = query.where(Customer.country_id == country_id)
    if risk_rating:
        query = query.where(Customer.risk_rating == risk_rating)
    if kyc_status:
        query = query.where(Customer.kyc_status == kyc_status)
    return paginate(db, query, params)


def create_customer(
    db: Session, data: CustomerCreate, actor_id: uuid.UUID | None, *, today: date | None = None
) -> Customer:
    today = today or date.today()
    if data.date_of_birth_or_incorporation > today:
        raise BusinessRuleViolation("The date of birth or incorporation is in the future.")
    if data.date_of_birth_or_incorporation < OLDEST_BIRTH_DATE:
        raise BusinessRuleViolation("The date of birth or incorporation is implausibly early.")
    country = require_active_country(db, data.country_id, "onboarding customers")

    number = db.execute(CUSTOMER_NUMBER_SEQUENCE.next_value()).scalar_one()
    customer = Customer(
        customer_number=f"CUS-{number:07d}",
        customer_type=data.customer_type.value,
        name=data.name.strip(),
        date_of_birth_or_incorporation=data.date_of_birth_or_incorporation,
        country_id=country.id,
        risk_rating=RiskRating.UNRATED.value,
        kyc_status=KycStatus.NOT_STARTED.value,
    )
    db.add(customer)
    db.flush()
    db.refresh(customer)
    record_audit_event(
        db,
        actor_id=actor_id,
        action="customer.created",
        entity_type="customer",
        entity_id=customer.id,
        metadata={
            "customer_number": customer.customer_number,
            "customer_type": customer.customer_type,
            "country": country.iso_country_code,
        },
    )
    return customer


def update_customer(
    db: Session, customer: Customer, data: CustomerUpdate, actor_id: uuid.UUID
) -> Customer:
    before = {"name": customer.name}
    if data.name is not None:
        customer.name = data.name.strip()
    db.flush()
    changes = diff(before, {"name": customer.name})
    if changes:
        record_audit_event(
            db,
            actor_id=actor_id,
            action="customer.updated",
            entity_type="customer",
            entity_id=customer.id,
            metadata={"changes": changes},
        )
    return customer


def review_customer(
    db: Session, customer: Customer, data: CustomerReview, actor_id: uuid.UUID | None
) -> Customer:
    """Record a KYC decision and/or risk rating. Transitions are validated."""
    if data.kyc_status is None and data.risk_rating is None:
        raise BusinessRuleViolation("Provide a kyc_status and/or a risk_rating.")
    before = {"kyc_status": customer.kyc_status, "risk_rating": customer.risk_rating}

    if data.kyc_status is not None and data.kyc_status != customer.kyc_status:
        current = KycStatus(customer.kyc_status)
        if data.kyc_status not in KYC_TRANSITIONS[current]:
            allowed = sorted(s.value for s in KYC_TRANSITIONS[current])
            raise BusinessRuleViolation(
                f"KYC status cannot change from {current.value} to {data.kyc_status.value}.",
                {"from": current.value, "to": data.kyc_status.value, "allowed": allowed},
            )
        customer.kyc_status = data.kyc_status.value

    if data.risk_rating is not None:
        if data.risk_rating == RiskRating.UNRATED and customer.risk_rating != RiskRating.UNRATED:
            raise BusinessRuleViolation("A rated customer cannot be returned to 'unrated'.")
        customer.risk_rating = data.risk_rating.value

    if customer.kyc_status == KycStatus.VERIFIED and customer.risk_rating == RiskRating.UNRATED:
        raise BusinessRuleViolation("A risk rating must be assigned before KYC is verified.")

    db.flush()
    changes = diff(before, {"kyc_status": customer.kyc_status, "risk_rating": customer.risk_rating})
    if changes:
        record_audit_event(
            db,
            actor_id=actor_id,
            action="customer.reviewed",
            entity_type="customer",
            entity_id=customer.id,
            metadata={"changes": changes, "note": data.note},
        )
    return customer


def is_individual(customer: Customer) -> bool:
    return customer.customer_type == CustomerType.INDIVIDUAL
