"""Helpers that create test data through the real services (so rules and audit apply)."""

import itertools
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.permissions import RoleCode
from app.core.security import create_access_token
from app.modules.countries.models import Country, Region
from app.modules.employees.models import Employee
from app.modules.employees.schemas import EmployeeCreate
from app.modules.employees.service import create_employee
from app.modules.identity.models import User
from app.modules.identity.schemas import UserCreate
from app.modules.identity.service import create_user
from app.modules.organizations.models import Organization, OrganizationType
from app.modules.organizations.schemas import OrganizationCreate
from app.modules.organizations.service import create_organization

PASSWORD = "correct-horse-battery-staple"
_counter = itertools.count(1)


def country(db: Session, code: str) -> Country:
    return db.execute(select(Country).where(Country.iso_country_code == code)).scalar_one()


def make_user(db: Session, role: RoleCode, username: str | None = None) -> User:
    username = username or f"{role.value.replace('_', '-')}-{next(_counter)}"
    return create_user(
        db,
        UserCreate(
            username=username,
            email=f"{username}@atlasbank.example",
            display_name=username.title(),
            password=PASSWORD,
            role=role,
        ),
        actor_id=None,
    )


def token_for(user: User, ttl: timedelta = timedelta(minutes=5)) -> str:
    secret = get_settings().jwt_secret.get_secret_value()
    return create_access_token(user.id, secret, ttl).token


def auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(user)}"}


def make_org(
    db: Session,
    name: str,
    org_type: OrganizationType,
    parent: Organization | None = None,
    *,
    country_code: str | None = None,
    region: Region | None = None,
) -> Organization:
    return create_organization(
        db,
        OrganizationCreate(
            name=name,
            organization_type=org_type,
            parent_organization_id=parent.id if parent else None,
            country_id=country(db, country_code).id if country_code else None,
            region=region,
        ),
        actor_id=None,
    )


@dataclass
class OrgTree:
    bank: Organization
    americas: Organization
    europe: Organization
    asia: Organization
    us: Organization
    us_retail: Organization
    us_onboarding: Organization  # department
    us_kyc_team: Organization  # team inside onboarding
    jp: Organization
    jp_retail: Organization
    jp_onboarding: Organization  # department


def make_org_tree(db: Session) -> OrgTree:
    t = OrganizationType
    bank = make_org(db, "ATLAS Global Bank", t.GLOBAL_BANK)
    americas = make_org(db, "Americas HQ", t.REGIONAL_HEADQUARTERS, bank, region=Region.AMERICAS)
    europe = make_org(db, "Europe HQ", t.REGIONAL_HEADQUARTERS, bank, region=Region.EUROPE)
    asia = make_org(
        db, "Asia-Pacific HQ", t.REGIONAL_HEADQUARTERS, bank, region=Region.ASIA_PACIFIC
    )
    us = make_org(db, "ATLAS US", t.COUNTRY_SUBSIDIARY, americas, country_code="US")
    us_retail = make_org(db, "Retail Banking", t.BUSINESS_DIVISION, us)
    us_onboarding = make_org(db, "Customer Onboarding", t.DEPARTMENT, us_retail)
    us_kyc_team = make_org(db, "KYC Review Team", t.TEAM, us_onboarding)
    jp = make_org(db, "ATLAS Japan", t.COUNTRY_SUBSIDIARY, asia, country_code="JP")
    jp_retail = make_org(db, "Retail Banking", t.BUSINESS_DIVISION, jp)
    jp_onboarding = make_org(db, "Customer Onboarding", t.DEPARTMENT, jp_retail)
    return OrgTree(
        bank,
        americas,
        europe,
        asia,
        us,
        us_retail,
        us_onboarding,
        us_kyc_team,
        jp,
        jp_retail,
        jp_onboarding,
    )


def make_employee(
    db: Session,
    organization: Organization,
    *,
    first_name: str = "Avery",
    last_name: str | None = None,
    manager: Employee | None = None,
    compensation: int = 9_500_000,
    job_title: str = "Analyst",
    role: RoleCode = RoleCode.BANKING_EMPLOYEE,
) -> Employee:
    return create_employee(
        db,
        EmployeeCreate(
            first_name=first_name,
            last_name=last_name or unique_surname(),
            organization_id=organization.id,
            manager_id=manager.id if manager else None,
            job_title=job_title,
            role=role,
            annual_compensation=compensation,
        ),
        actor_id=None,
    )


def new_id() -> str:
    return str(uuid.uuid4())


def unique_surname() -> str:
    """A letters-only surname that differs on every call (names may not contain digits)."""
    n = next(_counter)
    letters = ""
    while True:
        n, remainder = divmod(n, 26)
        letters = chr(ord("a") + remainder) + letters
        if n == 0:
            break
    return f"Sample{letters}"
