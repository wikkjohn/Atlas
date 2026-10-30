"""Organization hierarchy service."""

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import diff, record_audit_event
from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.core.pagination import PageParams, paginate
from app.modules.countries.service import require_active_country
from app.modules.organizations.models import (
    ALLOWED_PARENT,
    COUNTRY_SCOPED,
    Organization,
    OrganizationStatus,
    OrganizationType,
)
from app.modules.organizations.schemas import (
    OrganizationCreate,
    OrganizationOut,
    OrganizationUpdate,
)

MAX_DEPTH = len(ALLOWED_PARENT)


def get_organization(db: Session, organization_id: uuid.UUID) -> Organization:
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise NotFoundError("Organization not found.")
    return organization


def _counts(db: Session, ids: list[uuid.UUID]) -> tuple[dict[uuid.UUID, int], dict[uuid.UUID, int]]:
    from app.modules.employees.models import Employee

    if not ids:
        return {}, {}
    children = dict(
        db.execute(
            select(Organization.parent_organization_id, func.count())
            .where(Organization.parent_organization_id.in_(ids))
            .group_by(Organization.parent_organization_id)
        ).all()
    )
    employees = dict(
        db.execute(
            select(Employee.organization_id, func.count())
            .where(Employee.organization_id.in_(ids), Employee.employment_status != "terminated")
            .group_by(Employee.organization_id)
        ).all()
    )
    return children, employees


def to_out(db: Session, organizations: list[Organization]) -> list[OrganizationOut]:
    children, employees = _counts(db, [o.id for o in organizations])
    return [
        OrganizationOut(
            id=o.id,
            name=o.name,
            organization_type=o.organization_type,
            parent_organization_id=o.parent_organization_id,
            country_id=o.country_id,
            country_code=o.country.iso_country_code if o.country else None,
            country_name=o.country.country_name if o.country else None,
            currency=o.country.default_currency if o.country else None,
            region=o.region,
            status=o.status,
            generated_from=o.generated_from,
            child_count=children.get(o.id, 0),
            employee_count=employees.get(o.id, 0),
            created_at=o.created_at,
            updated_at=o.updated_at,
        )
        for o in organizations
    ]


def list_organizations(
    db: Session,
    params: PageParams,
    *,
    parent_id: uuid.UUID | None = None,
    root_only: bool = False,
    organization_type: str | None = None,
    country_id: uuid.UUID | None = None,
    status: str | None = None,
    q: str | None = None,
) -> tuple[list[Organization], int]:
    query = select(Organization).order_by(Organization.name)
    if root_only:
        query = query.where(Organization.parent_organization_id.is_(None))
    elif parent_id is not None:
        query = query.where(Organization.parent_organization_id == parent_id)
    if organization_type:
        query = query.where(Organization.organization_type == organization_type)
    if country_id:
        query = query.where(Organization.country_id == country_id)
    if status:
        query = query.where(Organization.status == status)
    if q:
        query = query.where(or_(Organization.name.ilike(f"%{q.strip()}%")))
    return paginate(db, query, params)


def ancestors(db: Session, organization: Organization) -> list[Organization]:
    """The chain from the global bank down to (excluding) `organization`."""
    chain: list[Organization] = []
    current = organization
    while current.parent_organization_id is not None and len(chain) < MAX_DEPTH:
        current = get_organization(db, current.parent_organization_id)
        chain.append(current)
    return list(reversed(chain))


def _validate_placement(
    db: Session, data: OrganizationCreate
) -> tuple[uuid.UUID | None, str | None]:
    """Apply hierarchy and country rules; return the (country_id, region) to store."""
    org_type = data.organization_type
    expected_parent = ALLOWED_PARENT[org_type]

    if expected_parent is None:
        if data.parent_organization_id is not None:
            raise BusinessRuleViolation("The global bank is the root and cannot have a parent.")
        if db.execute(
            select(Organization.id).where(Organization.organization_type == org_type)
        ).first():
            raise ConflictError("The global bank already exists; there can be only one.")
        if data.region is not None:
            raise BusinessRuleViolation("The global bank spans all regions; omit region.")
        if data.country_id is not None:
            require_active_country(db, data.country_id, "a headquarters location")
        return data.country_id, None

    if data.parent_organization_id is None:
        raise BusinessRuleViolation(
            f"A {org_type.value} must have a parent of type {expected_parent.value}."
        )
    parent = db.get(Organization, data.parent_organization_id)
    if parent is None:
        raise BusinessRuleViolation("parent_organization_id does not reference an organization.")
    if parent.organization_type != expected_parent:
        raise BusinessRuleViolation(
            f"A {org_type.value} must sit under a {expected_parent.value}, not under a "
            f"{parent.organization_type}.",
            {"parent_type": parent.organization_type, "required_parent_type": expected_parent},
        )
    if parent.status != OrganizationStatus.ACTIVE:
        raise BusinessRuleViolation("The parent organization is inactive.")

    if org_type == OrganizationType.REGIONAL_HEADQUARTERS:
        if data.region is None:
            raise BusinessRuleViolation("A regional headquarters must specify its region.")
        if data.country_id is not None:
            country = require_active_country(db, data.country_id, "a headquarters location")
            if country.region != data.region:
                raise BusinessRuleViolation(
                    f"{country.country_name} is in {country.region}, not {data.region.value}."
                )
        return data.country_id, data.region.value

    if data.region is not None and data.region != parent.region:
        raise BusinessRuleViolation("region is inherited from the parent organization.")

    if org_type == OrganizationType.COUNTRY_SUBSIDIARY:
        if data.country_id is None:
            raise BusinessRuleViolation("A country subsidiary must specify its country.")
        country = require_active_country(db, data.country_id, "creating a subsidiary")
        if country.region != parent.region:
            raise BusinessRuleViolation(
                f"{country.country_name} is in {country.region}; it cannot belong to the "
                f"{parent.region} regional headquarters.",
                {"country_region": country.region, "parent_region": parent.region},
            )
        return country.id, parent.region

    # Divisions, departments and teams inherit the subsidiary's country.
    assert org_type in COUNTRY_SCOPED
    if data.country_id is not None and data.country_id != parent.country_id:
        raise BusinessRuleViolation(
            "country_id is inherited from the parent organization and cannot differ."
        )
    if parent.country_id is not None:
        require_active_country(db, parent.country_id, f"creating a {org_type.value}")
    return parent.country_id, parent.region


def create_organization(
    db: Session, data: OrganizationCreate, actor_id: uuid.UUID | None
) -> Organization:
    country_id, region = _validate_placement(db, data)
    organization = Organization(
        name=data.name.strip(),
        organization_type=data.organization_type.value,
        parent_organization_id=data.parent_organization_id,
        country_id=country_id,
        region=region,
        status=OrganizationStatus.ACTIVE.value,
    )
    db.add(organization)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError as exc:
        raise ConflictError(
            "An organization with this name already exists under the same parent, or this "
            "country already has a subsidiary."
        ) from exc
    db.refresh(organization)
    record_audit_event(
        db,
        actor_id=actor_id,
        action="organization.created",
        entity_type="organization",
        entity_id=organization.id,
        metadata={
            "name": organization.name,
            "organization_type": organization.organization_type,
            "parent_organization_id": str(organization.parent_organization_id)
            if organization.parent_organization_id
            else None,
            "country_id": str(country_id) if country_id else None,
        },
    )
    return organization


def update_organization(
    db: Session, organization: Organization, data: OrganizationUpdate, actor_id: uuid.UUID
) -> Organization:
    from app.modules.employees.models import Employee

    before = {"name": organization.name, "status": organization.status}
    if data.name is not None:
        organization.name = data.name.strip()
    if data.status is not None and data.status != organization.status:
        if data.status == OrganizationStatus.INACTIVE:
            active_children = db.execute(
                select(func.count()).where(
                    Organization.parent_organization_id == organization.id,
                    Organization.status == OrganizationStatus.ACTIVE,
                )
            ).scalar_one()
            active_staff = db.execute(
                select(func.count()).where(
                    Employee.organization_id == organization.id,
                    Employee.employment_status != "terminated",
                )
            ).scalar_one()
            if active_children or active_staff:
                raise BusinessRuleViolation(
                    "Deactivate or move child organizations and staff first.",
                    {"active_children": active_children, "active_employees": active_staff},
                )
        elif organization.parent_organization_id is not None:
            parent = get_organization(db, organization.parent_organization_id)
            if parent.status != OrganizationStatus.ACTIVE:
                raise BusinessRuleViolation("Reactivate the parent organization first.")
        organization.status = data.status.value
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError as exc:
        raise ConflictError("An organization with this name already exists here.") from exc
    db.refresh(organization)
    changes = diff(before, {"name": organization.name, "status": organization.status})
    if changes:
        record_audit_event(
            db,
            actor_id=actor_id,
            action="organization.updated",
            entity_type="organization",
            entity_id=organization.id,
            metadata={"changes": changes},
        )
    return organization
