"""Country and department scopes of users (Phase 84)."""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.errors import BusinessRuleViolation, NotFoundError, PermissionDeniedError
from app.core.scope import UNRESTRICTED, Scope
from app.modules.countries.models import Country
from app.modules.identity.models import User, UserScope
from app.modules.organizations.models import Organization

COUNTRY = "country"
DEPARTMENT = "department"


def scope_for(db: Session, user_id: uuid.UUID) -> Scope:
    rows = db.execute(
        select(UserScope.kind, UserScope.value).where(UserScope.user_id == user_id)
    ).all()
    if not rows:
        return UNRESTRICTED
    countries = frozenset(v for k, v in rows if k == COUNTRY)
    departments = frozenset(v for k, v in rows if k == DEPARTMENT)
    return Scope(countries=countries or None, departments=departments or None)


def set_scopes(
    db: Session, user: User, countries: list[str], departments: list[str], actor_id: uuid.UUID
) -> Scope:
    """Replace the user's scopes. Empty lists remove the limit in that dimension."""
    countries = sorted({c.strip().upper() for c in countries if c.strip()})
    departments = sorted({d.strip() for d in departments if d.strip()})
    known_countries = set(
        db.execute(
            select(Country.iso_country_code).where(Country.iso_country_code.in_(countries))
        ).scalars()
    ) if countries else set()  # fmt: skip
    unknown = [c for c in countries if c not in known_countries]
    if unknown:
        raise BusinessRuleViolation(f"Unknown countries: {', '.join(unknown)}.")
    known_departments = set(
        db.execute(
            select(Organization.name).where(
                Organization.organization_type == "department", Organization.name.in_(departments)
            )
        ).scalars()
    ) if departments else set()  # fmt: skip
    unknown = [d for d in departments if d not in known_departments]
    if unknown:
        raise BusinessRuleViolation(f"Unknown departments: {', '.join(unknown)}.")
    before = scope_for(db, user.id).describe()
    db.execute(delete(UserScope).where(UserScope.user_id == user.id))
    for kind, values in ((COUNTRY, countries), (DEPARTMENT, departments)):
        for value in values:
            db.add(UserScope(user_id=user.id, kind=kind, value=value, created_by=actor_id))
    db.flush()
    db.expire(user, ["scopes"])
    after = scope_for(db, user.id)
    record_audit_event(
        db, actor_id=actor_id, action="user.scopes_changed", entity_type="user",
        entity_id=user.id, metadata={"before": before, "after": after.describe()},
    )  # fmt: skip
    return after


# --- Enforcement helpers --------------------------------------------------------------------


def visible(scope: Scope, *, country: str | None = None, department: str | None = None) -> bool:
    return scope.allows_country(country) and scope.allows_department(department)


def require_visible(
    scope: Scope, what: str, *, country: str | None = None, department: str | None = None
) -> None:
    """For a record the user asked for by id: outside the scope it does not exist for them
    (404), so its existence is not revealed."""
    if not visible(scope, country=country, department=department):
        raise NotFoundError(f"{what} not found.")


def require_in_scope(
    scope: Scope, *, country: str | None = None, department: str | None = None
) -> None:
    """For a record the user is creating or naming: outside the scope is refused (403)."""
    if not scope.allows_country(country):
        raise PermissionDeniedError(
            f"Your access is limited to {', '.join(sorted(scope.countries or []))}; "
            f"{country} is outside it.",
            {"scope": scope.describe()},
        )
    if not scope.allows_department(department):
        raise PermissionDeniedError(
            f"Your access is limited to {', '.join(sorted(scope.departments or []))}; "
            f"{department} is outside it.",
            {"scope": scope.describe()},
        )
