"""Generated country subsidiaries (Phase 27).

A versioned blueprint says what a country subsidiary looks like: its business divisions,
departments and teams, and the synthetic staff of each. Launching a country makes it
active, adds its regional headquarters if the region has none yet, and builds the missing
parts of its subsidiary from the blueprint. Launching again adds only what is missing, and
staff are hired only for units created by that launch, so it never doubles anyone.
Organizations built this way record the blueprint in `generated_from`.
"""

import uuid
import zlib
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.errors import BusinessRuleViolation
from app.core.money import to_minor_units
from app.core.permissions import RoleCode
from app.modules.countries.models import Country, OperationalStatus, Region
from app.modules.employees.models import Employee
from app.modules.employees.schemas import EmployeeCreate
from app.modules.employees.service import create_employee
from app.modules.fx import rates
from app.modules.organizations.models import (
    Organization,
    OrganizationStatus,
    OrganizationType,
)
from app.modules.organizations.schemas import OrganizationCreate
from app.modules.organizations.service import create_organization
from app.simulation.generators import SyntheticNameGenerator

BLUEPRINT_VERSION = 1
GENERATED_FROM = f"subsidiary-blueprint/{BLUEPRINT_VERSION}"

REGIONAL_HEADQUARTERS = {
    Region.AMERICAS: "Americas Regional Headquarters",
    Region.EUROPE: "Europe Regional Headquarters",
    Region.MIDDLE_EAST_AFRICA: "Middle East & Africa Regional Headquarters",
    Region.ASIA_PACIFIC: "Asia-Pacific Regional Headquarters",
}

# division -> department -> teams; the demo seed builds the operating countries the same way.
STRUCTURE: dict[str, dict[str, list[str]]] = {
    "Retail Banking": {
        "Customer Onboarding": ["KYC Review", "Account Services"],
        "Branch Network": [],
    },
    "Compliance & Risk": {"Financial Crime Compliance": ["Sanctions Screening"]},
    "Technology & Operations": {"AI Innovation Lab": ["Model Evaluation"]},
}

TEAM_ANALYSTS = 3
# Annual pay in US dollars; converted at the FX anchor rates for each country's currency.
USD_SALARY_BAND = (62_000, 240_000)


def subsidiary_name(country: Country) -> str:
    return f"ATLAS Bank {country.country_name}"


def _two_figures(value: Decimal) -> int:
    whole = int(value)
    if whole < 100:
        return max(whole, 1)
    return round(whole, -(len(str(whole)) - 2))


def salary_band(currency: str) -> tuple[int, int]:
    """The blueprint's pay band in whole units of `currency`, to two significant figures."""
    rate = rates.units_per_usd(currency, rates.ANCHOR_DATE)
    low, high = USD_SALARY_BAND
    return _two_figures(Decimal(low) * rate), _two_figures(Decimal(high) * rate)


def staff_per_subsidiary() -> int:
    departments = sum(len(d) for d in STRUCTURE.values())
    teams = sum(len(t) for d in STRUCTURE.values() for t in d.values())
    return departments * 2 + teams * (1 + TEAM_ANALYSTS)


def units_per_subsidiary() -> int:
    return 1 + sum(1 + len(d) + sum(len(t) for t in d.values()) for d in STRUCTURE.values())


def describe() -> dict:
    return {
        "version": BLUEPRINT_VERSION,
        "generated_from": GENERATED_FROM,
        "regional_headquarters": {r.value: name for r, name in REGIONAL_HEADQUARTERS.items()},
        "structure": STRUCTURE,
        "units_per_subsidiary": units_per_subsidiary(),
        "staff_per_subsidiary": staff_per_subsidiary(),
        "usd_salary_band": list(USD_SALARY_BAND),
    }


@dataclass
class LaunchResult:
    country_code: str
    subsidiary_id: uuid.UUID
    activated: bool = False
    organizations_created: int = 0
    employees_hired: int = 0
    created: list[str] = field(default_factory=list)  # names of the new units


class _Builder:
    def __init__(self, db: Session, country: Country, actor_id: uuid.UUID | None, staff: bool):
        self.db, self.country, self.actor_id, self.staff = db, country, actor_id, staff
        seed = zlib.crc32(f"{country.iso_country_code}:{GENERATED_FROM}".encode())
        self.names = SyntheticNameGenerator(seed)
        self.band = salary_band(country.default_currency)
        self.result: LaunchResult | None = None

    def child(
        self, parent: Organization | None, name: str, kind: OrganizationType, **kwargs
    ) -> tuple[Organization, bool]:
        """The active child of `parent` called `name`, created from the blueprint if missing."""
        query = select(Organization).where(
            Organization.organization_type == kind,
            Organization.name == name,
            Organization.parent_organization_id == (parent.id if parent else None),
        )
        if kind == OrganizationType.COUNTRY_SUBSIDIARY:
            query = select(Organization).where(
                Organization.organization_type == kind,
                Organization.country_id == self.country.id,
            )
        existing = self.db.execute(query).scalar_one_or_none()
        if existing is not None:
            if existing.status != OrganizationStatus.ACTIVE:
                raise BusinessRuleViolation(
                    f"{existing.name} is inactive; reactivate it before launching "
                    f"{self.country.country_name}.",
                    {"organization_id": str(existing.id)},
                )
            return existing, False
        created = create_organization(
            self.db,
            OrganizationCreate(
                name=name,
                organization_type=kind,
                parent_organization_id=parent.id if parent else None,
                **kwargs,
            ),
            self.actor_id,
        )
        created.generated_from = GENERATED_FROM
        if self.result is not None:
            self.result.organizations_created += 1
            self.result.created.append(name)
        return created, True

    def hire(
        self,
        unit: Organization,
        title: str,
        manager: Employee | None,
        role: RoleCode = RoleCode.BANKING_EMPLOYEE,
    ) -> Employee:
        first, last = self.names.name()
        low, high = self.band
        if title.startswith("Head"):
            low = (low + high) // 2
        pay = self.names.integer(low, high)
        pay = pay // 1000 * 1000 if pay >= 10_000 else pay
        employee = create_employee(
            self.db,
            EmployeeCreate(
                first_name=first,
                last_name=last,
                organization_id=unit.id,
                manager_id=manager.id if manager else None,
                job_title=title,
                role=role,
                annual_compensation=to_minor_units(pay, self.country.default_currency),
            ),
            self.actor_id,
        )
        assert self.result is not None
        self.result.employees_hired += 1
        return employee


def _global_bank(db: Session) -> Organization:
    bank = db.execute(
        select(Organization).where(Organization.organization_type == OrganizationType.GLOBAL_BANK)
    ).scalar_one_or_none()
    if bank is None:
        raise BusinessRuleViolation(
            "There is no global bank to attach subsidiaries to; create it first "
            "(e.g. `python -m app.cli seed-demo`)."
        )
    return bank


def _regional_headquarters(builder: _Builder, region: Region) -> Organization:
    db = builder.db
    existing = (
        db.execute(
            select(Organization)
            .where(
                Organization.organization_type == OrganizationType.REGIONAL_HEADQUARTERS,
                Organization.region == region.value,
                Organization.status == OrganizationStatus.ACTIVE,
            )
            .order_by(Organization.created_at)
        )
        .scalars()
        .first()
    )
    if existing is not None:
        return existing
    hq, _ = builder.child(
        _global_bank(db),
        REGIONAL_HEADQUARTERS[region],
        OrganizationType.REGIONAL_HEADQUARTERS,
        region=region,
    )
    return hq


def launch_country(
    db: Session, country: Country, actor_id: uuid.UUID | None, *, staff: bool = True
) -> LaunchResult:
    """Make `country` operating and complete its subsidiary from the blueprint."""
    if country.operational_status == OperationalStatus.SUSPENDED:
        raise BusinessRuleViolation(
            f"{country.country_name} is suspended; resume it before launching.",
            {"country": country.iso_country_code},
        )
    builder = _Builder(db, country, actor_id, staff)
    activated = country.operational_status != OperationalStatus.ACTIVE
    if activated:
        country.operational_status = OperationalStatus.ACTIVE.value
        db.flush()
        record_audit_event(
            db,
            actor_id=actor_id,
            action="country.launched",
            entity_type="country",
            entity_id=country.id,
            metadata={"iso_country_code": country.iso_country_code, "blueprint": GENERATED_FROM},
        )
    builder.result = LaunchResult(country.iso_country_code, uuid.uuid4(), activated=activated)
    hq = _regional_headquarters(builder, Region(country.region))
    subsidiary, _ = builder.child(
        hq,
        subsidiary_name(country),
        OrganizationType.COUNTRY_SUBSIDIARY,
        country_id=country.id,
    )
    builder.result.subsidiary_id = subsidiary.id
    for division_name, departments in STRUCTURE.items():
        division, _ = builder.child(subsidiary, division_name, OrganizationType.BUSINESS_DIVISION)
        for department_name, teams in departments.items():
            department, new = builder.child(division, department_name, OrganizationType.DEPARTMENT)
            head = None
            if new and staff:
                head = builder.hire(
                    department, f"Head of {department_name}", None, RoleCode.DEPARTMENT_MANAGER
                )
                builder.hire(department, "Senior Analyst", head, RoleCode.BANKING_EMPLOYEE)
            for team_name in teams:
                team, new_team = builder.child(department, team_name, OrganizationType.TEAM)
                if new_team and staff:
                    lead = builder.hire(team, f"{team_name} Lead", head)
                    for _ in range(TEAM_ANALYSTS):
                        builder.hire(team, f"{team_name} Analyst", lead)
    db.flush()
    result = builder.result
    if result.organizations_created or result.activated:
        record_audit_event(
            db,
            actor_id=actor_id,
            action="organization.subsidiary_generated",
            entity_type="organization",
            entity_id=subsidiary.id,
            metadata={
                "country": country.iso_country_code,
                "blueprint": GENERATED_FROM,
                "organizations_created": result.organizations_created,
                "employees_hired": result.employees_hired,
            },
        )
    return result


def targets(
    db: Session, codes: list[str] | None = None, region: Region | None = None
) -> list[Country]:
    """The countries a generation covers: the codes given, else every country of the region
    (or of all regions) that has no subsidiary yet. Suspended countries are left out."""
    query = select(Country).order_by(Country.iso_country_code)
    if codes:
        found = list(db.execute(query.where(Country.iso_country_code.in_(codes))).scalars())
        missing = sorted(set(codes) - {c.iso_country_code for c in found})
        if missing:
            raise BusinessRuleViolation(
                f"Unknown countries: {', '.join(missing)}.", {"unknown": missing}
            )
        suspended = [
            c.iso_country_code for c in found if c.operational_status == OperationalStatus.SUSPENDED
        ]
        if suspended:
            raise BusinessRuleViolation(
                f"Suspended countries cannot be launched: {', '.join(suspended)}.",
                {"suspended": suspended},
            )
        return found
    with_subsidiary = select(Organization.country_id).where(
        Organization.organization_type == OrganizationType.COUNTRY_SUBSIDIARY
    )
    query = query.where(
        Country.id.not_in(with_subsidiary),
        Country.operational_status != OperationalStatus.SUSPENDED,
    )
    if region is not None:
        query = query.where(Country.region == region.value)
    return list(db.execute(query).scalars())


def coverage(db: Session) -> list[dict]:
    """Per region: configured countries, those with a subsidiary, and generated ones."""
    countries = list(db.execute(select(Country)).scalars())
    subsidiaries = {
        country_id: generated
        for country_id, generated in db.execute(
            select(Organization.country_id, Organization.generated_from).where(
                Organization.organization_type == OrganizationType.COUNTRY_SUBSIDIARY
            )
        ).all()
    }
    found = []
    for region in Region:
        members = [c for c in countries if c.region == region.value]
        found.append(
            {
                "region": region.value,
                "countries": len(members),
                "subsidiaries": sum(1 for c in members if c.id in subsidiaries),
                "generated": sum(1 for c in members if subsidiaries.get(c.id)),
                "without_subsidiary": sorted(
                    c.iso_country_code for c in members if c.id not in subsidiaries
                ),
            }
        )
    return found
