"""Employee registry service."""

import re
import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import diff, record_audit_event
from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.core.pagination import PageParams, paginate
from app.core.permissions import SERVICE_ROLES
from app.modules.countries.service import require_active_country
from app.modules.employees.models import (
    EMPLOYEE_NUMBER_SEQUENCE,
    SYNTHETIC_EMAIL_DOMAIN,
    Employee,
    EmploymentStatus,
)
from app.modules.employees.schemas import EmployeeCreate, EmployeeOut, EmployeeRef, EmployeeUpdate
from app.modules.identity.service import get_role
from app.modules.organizations.models import Organization, OrganizationStatus, OrganizationType

# Longer chains than this indicate corrupt data rather than a real hierarchy.
MAX_REPORTING_DEPTH = 64
_AUDITED = (
    "job_title",
    "organization_id",
    "department_id",
    "manager_id",
    "role",
    "country_id",
    "employment_status",
    "annual_compensation",
)


def _ref(employee: Employee) -> EmployeeRef:
    return EmployeeRef(
        id=employee.id,
        employee_number=employee.employee_number,
        full_name=f"{employee.first_name} {employee.last_name}",
        job_title=employee.job_title,
    )


def to_out(employee: Employee, *, include_compensation: bool) -> EmployeeOut:
    return EmployeeOut(
        id=employee.id,
        employee_number=employee.employee_number,
        first_name=employee.first_name,
        last_name=employee.last_name,
        full_name=f"{employee.first_name} {employee.last_name}",
        email=employee.email,
        organization_id=employee.organization_id,
        organization_name=employee.organization.name,
        department_id=employee.department_id,
        department_name=employee.department.name,
        manager=_ref(employee.manager) if employee.manager else None,
        job_title=employee.job_title,
        role=employee.role.code,
        country_id=employee.country_id,
        country_code=employee.country.iso_country_code,
        employment_status=employee.employment_status,
        annual_compensation=employee.annual_compensation if include_compensation else None,
        compensation_currency=employee.compensation_currency if include_compensation else None,
        created_at=employee.created_at,
        updated_at=employee.updated_at,
    )


def get_employee(db: Session, employee_id: uuid.UUID) -> Employee:
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise NotFoundError("Employee not found.")
    return employee


def list_employees(
    db: Session,
    params: PageParams,
    *,
    q: str | None = None,
    organization_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    country_id: uuid.UUID | None = None,
    manager_id: uuid.UUID | None = None,
    employment_status: str | None = None,
) -> tuple[list[Employee], int]:
    query = select(Employee).order_by(Employee.last_name, Employee.first_name, Employee.id)
    if q:
        pattern = f"%{q.strip()}%"
        query = query.where(
            or_(
                (Employee.first_name + " " + Employee.last_name).ilike(pattern),
                Employee.email.ilike(pattern),
                Employee.employee_number.ilike(pattern),
                Employee.job_title.ilike(pattern),
            )
        )
    if organization_id:
        query = query.where(Employee.organization_id == organization_id)
    if department_id:
        query = query.where(Employee.department_id == department_id)
    if country_id:
        query = query.where(Employee.country_id == country_id)
    if manager_id:
        query = query.where(Employee.manager_id == manager_id)
    if employment_status:
        query = query.where(Employee.employment_status == employment_status)
    return paginate(db, query, params)


def direct_reports(db: Session, employee: Employee) -> list[Employee]:
    return list(
        db.execute(
            select(Employee)
            .where(Employee.manager_id == employee.id)
            .order_by(Employee.last_name, Employee.first_name)
        ).scalars()
    )


def reporting_chain(db: Session, employee: Employee) -> list[Employee]:
    """Managers from the direct manager upwards."""
    chain: list[Employee] = []
    current = employee.manager
    while current is not None and len(chain) < MAX_REPORTING_DEPTH:
        chain.append(current)
        current = current.manager
    return chain


def _placement(db: Session, organization_id: uuid.UUID) -> tuple[Organization, Organization]:
    """Resolve the employee's unit and its department."""
    unit = db.get(Organization, organization_id)
    if unit is None:
        raise BusinessRuleViolation("organization_id does not reference an organization.")
    if unit.status != OrganizationStatus.ACTIVE:
        raise BusinessRuleViolation(f"{unit.name} is inactive.")
    if unit.organization_type == OrganizationType.DEPARTMENT:
        return unit, unit
    if unit.organization_type == OrganizationType.TEAM:
        assert unit.parent_organization_id is not None
        department = db.get(Organization, unit.parent_organization_id)
        assert department is not None
        return unit, department
    raise BusinessRuleViolation(
        f"Employees are assigned to a department or team, not a {unit.organization_type}.",
        {"organization_type": unit.organization_type},
    )


def _validate_manager(db: Session, manager_id: uuid.UUID, employee_id: uuid.UUID | None) -> None:
    manager = db.get(Employee, manager_id)
    if manager is None:
        raise BusinessRuleViolation("manager_id does not reference an employee.")
    if manager.employment_status == EmploymentStatus.TERMINATED:
        raise BusinessRuleViolation("A terminated employee cannot be a manager.")
    if employee_id is None:
        return
    if manager.id == employee_id:
        raise BusinessRuleViolation("An employee cannot be their own manager.")
    # Walk up from the proposed manager; meeting the employee would close a loop.
    current: Employee | None = manager
    for _ in range(MAX_REPORTING_DEPTH):
        if current is None:
            return
        if current.id == employee_id:
            raise BusinessRuleViolation(
                "This manager reports (directly or indirectly) to the employee; the reporting "
                "line would form a cycle."
            )
        current = current.manager
    raise BusinessRuleViolation("The reporting chain is too deep.")


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "x"


def _generate_email(db: Session, first_name: str, last_name: str) -> str:
    base = f"{_slug(first_name)}.{_slug(last_name)}"
    candidate = f"{base}@{SYNTHETIC_EMAIL_DOMAIN}"
    suffix = 1
    while db.execute(select(Employee.id).where(Employee.email == candidate)).first():
        suffix += 1
        candidate = f"{base}{suffix}@{SYNTHETIC_EMAIL_DOMAIN}"
    return candidate


def _snapshot(employee: Employee) -> dict[str, Any]:
    values = {field: getattr(employee, field, None) for field in _AUDITED if field != "role"}
    values["role"] = employee.role.code
    return {k: str(v) if isinstance(v, uuid.UUID) else v for k, v in values.items()}


def create_employee(db: Session, data: EmployeeCreate, actor_id: uuid.UUID | None) -> Employee:
    if data.role in SERVICE_ROLES:
        raise BusinessRuleViolation(
            f"The {data.role.value} role belongs to system principals only."
        )
    unit, department = _placement(db, data.organization_id)
    country_id = data.country_id or unit.country_id
    if country_id is None:
        raise BusinessRuleViolation("The organization has no country; specify country_id.")
    country = require_active_country(db, country_id, "employing staff")
    if data.manager_id is not None:
        _validate_manager(db, data.manager_id, None)

    number = db.execute(EMPLOYEE_NUMBER_SEQUENCE.next_value()).scalar_one()
    employee = Employee(
        employee_number=f"AGB-{number:07d}",
        first_name=data.first_name.strip(),
        last_name=data.last_name.strip(),
        email=data.email or _generate_email(db, data.first_name, data.last_name),
        organization_id=unit.id,
        department_id=department.id,
        manager_id=data.manager_id,
        job_title=data.job_title.strip(),
        role_id=get_role(db, data.role).id,
        country_id=country.id,
        employment_status=data.employment_status.value,
        annual_compensation=data.annual_compensation,
        # Country configuration decides the currency compensation is recorded in.
        compensation_currency=country.default_currency,
    )
    db.add(employee)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError as exc:
        raise ConflictError("An employee with this email already exists.") from exc
    db.refresh(employee)
    record_audit_event(
        db,
        actor_id=actor_id,
        action="employee.created",
        entity_type="employee",
        entity_id=employee.id,
        metadata={"employee_number": employee.employee_number, **_snapshot(employee)},
    )
    return employee


def update_employee(
    db: Session, employee: Employee, data: EmployeeUpdate, actor_id: uuid.UUID
) -> Employee:
    before = _snapshot(employee)
    sent = data.model_fields_set

    if "organization_id" in sent and data.organization_id is not None:
        unit, department = _placement(db, data.organization_id)
        if unit.country_id != employee.country_id:
            # Compensation is held in the country's currency; moving countries would need a
            # currency conversion the platform does not model.
            raise BusinessRuleViolation(
                "Transfers between countries are not supported; the unit is in a different "
                "country from the employee.",
                {"employee_country_id": str(employee.country_id)},
            )
        employee.organization_id = unit.id
        employee.department_id = department.id
    if "manager_id" in sent:
        if data.manager_id is not None:
            _validate_manager(db, data.manager_id, employee.id)
        employee.manager_id = data.manager_id
    if data.job_title is not None:
        employee.job_title = data.job_title.strip()
    if data.role is not None:
        if data.role in SERVICE_ROLES:
            raise BusinessRuleViolation(
                f"The {data.role.value} role belongs to system principals only."
            )
        employee.role_id = get_role(db, data.role).id
    if data.annual_compensation is not None:
        employee.annual_compensation = data.annual_compensation
    if data.employment_status is not None:
        if data.employment_status == EmploymentStatus.TERMINATED:
            reports = db.execute(
                select(Employee.id).where(
                    Employee.manager_id == employee.id,
                    Employee.employment_status != EmploymentStatus.TERMINATED,
                )
            ).all()
            if reports:
                raise BusinessRuleViolation(
                    "Reassign this employee's direct reports before terminating them.",
                    {"direct_reports": len(reports)},
                )
        employee.employment_status = data.employment_status.value

    db.flush()
    db.expire(employee)
    changes = diff(before, _snapshot(employee))
    if changes:
        record_audit_event(
            db,
            actor_id=actor_id,
            action="employee.updated",
            entity_type="employee",
            entity_id=employee.id,
            metadata={"changes": changes},
        )
    return employee
