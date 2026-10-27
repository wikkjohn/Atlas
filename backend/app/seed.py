"""Demo data: a small synthetic bank across the five initial countries.

Run with `python -m app.cli seed-demo`. The seed is deterministic for a given `seed`
value and safe to run repeatedly: existing data is left untouched and only missing demo
users are added. Refuses to run in staging or production.
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.money import to_minor_units
from app.core.permissions import RoleCode
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
from app.simulation.generators import SyntheticNameGenerator

DEFAULT_SEED = 2026

REGIONS = {
    Region.AMERICAS: ("Americas Regional Headquarters", ["US"]),
    Region.EUROPE: ("Europe Regional Headquarters", ["GB", "DE"]),
    Region.ASIA_PACIFIC: ("Asia-Pacific Regional Headquarters", ["SG", "JP"]),
}

SUBSIDIARY_NAMES = {
    "US": "ATLAS Bank USA",
    "GB": "ATLAS Bank UK",
    "DE": "ATLAS Bank Deutschland",
    "SG": "ATLAS Bank Singapore",
    "JP": "ATLAS Bank Japan",
}

# division -> department -> teams
STRUCTURE = {
    "Retail Banking": {
        "Customer Onboarding": ["KYC Review", "Account Services"],
        "Branch Network": [],
    },
    "Compliance & Risk": {"Financial Crime Compliance": ["Sanctions Screening"]},
    "Technology & Operations": {"AI Innovation Lab": ["Model Evaluation"]},
}

# Annual salary bands in whole units of each country's currency (synthetic).
SALARY_BANDS = {
    "US": (62_000, 240_000),
    "GB": (42_000, 190_000),
    "DE": (48_000, 200_000),
    "SG": (60_000, 250_000),
    "JP": (5_000_000, 24_000_000),
}

DEMO_USERS = [
    ("admin", RoleCode.PLATFORM_ADMINISTRATOR, "Platform Administrator"),
    ("executive", RoleCode.GLOBAL_EXECUTIVE, "Global Executive"),
    ("regional", RoleCode.REGIONAL_EXECUTIVE, "Regional Executive"),
    ("manager", RoleCode.DEPARTMENT_MANAGER, "Department Manager"),
    ("employee", RoleCode.BANKING_EMPLOYEE, "Banking Employee"),
    ("compliance", RoleCode.COMPLIANCE_OFFICER, "Compliance Officer"),
    ("researcher", RoleCode.AI_RESEARCHER, "AI Researcher"),
    ("auditor", RoleCode.AUDITOR, "Auditor"),
]


@dataclass
class SeedReport:
    organizations: int = 0
    employees: int = 0
    users: list[str] = field(default_factory=list)
    skipped_structure: bool = False


def _org(
    db: Session,
    name: str,
    org_type: OrganizationType,
    parent: Organization | None,
    report: SeedReport,
    **kwargs: object,
) -> Organization:
    organization = create_organization(
        db,
        OrganizationCreate(
            name=name,
            organization_type=org_type,
            parent_organization_id=parent.id if parent else None,
            **kwargs,
        ),
        actor_id=None,
    )
    report.organizations += 1
    return organization


def _hire(
    db: Session,
    names: SyntheticNameGenerator,
    unit: Organization,
    country: Country,
    title: str,
    manager: Employee | None,
    report: SeedReport,
    role: RoleCode = RoleCode.BANKING_EMPLOYEE,
) -> Employee:
    first, last = names.name()
    low, high = SALARY_BANDS[country.iso_country_code]
    # Senior titles sit in the upper half of the band.
    if title.startswith(("Head", "Chief", "Director")):
        low = (low + high) // 2
    salary = names.integer(low, high) // 1000 * 1000
    employee = create_employee(
        db,
        EmployeeCreate(
            first_name=first,
            last_name=last,
            organization_id=unit.id,
            manager_id=manager.id if manager else None,
            job_title=title,
            role=role,
            annual_compensation=to_minor_units(salary, country.default_currency),
        ),
        actor_id=None,
    )
    report.employees += 1
    return employee


def _build_structure(db: Session, names: SyntheticNameGenerator, report: SeedReport) -> None:
    countries = {c.iso_country_code: c for c in db.execute(select(Country)).scalars()}
    bank = _org(db, "ATLAS Global Bank", OrganizationType.GLOBAL_BANK, None, report)
    for region, (hq_name, codes) in REGIONS.items():
        hq = _org(db, hq_name, OrganizationType.REGIONAL_HEADQUARTERS, bank, report, region=region)
        for code in codes:
            country = countries[code]
            subsidiary = _org(
                db,
                SUBSIDIARY_NAMES[code],
                OrganizationType.COUNTRY_SUBSIDIARY,
                hq,
                report,
                country_id=country.id,
            )
            for division_name, departments in STRUCTURE.items():
                division = _org(
                    db, division_name, OrganizationType.BUSINESS_DIVISION, subsidiary, report
                )
                for department_name, teams in departments.items():
                    department = _org(
                        db, department_name, OrganizationType.DEPARTMENT, division, report
                    )
                    head = _hire(
                        db,
                        names,
                        department,
                        country,
                        f"Head of {department_name}",
                        None,
                        report,
                        RoleCode.DEPARTMENT_MANAGER,
                    )
                    _hire(db, names, department, country, "Senior Analyst", head, report)
                    for team_name in teams:
                        team = _org(db, team_name, OrganizationType.TEAM, department, report)
                        lead = _hire(db, names, team, country, f"{team_name} Lead", head, report)
                        for _ in range(3):
                            _hire(db, names, team, country, f"{team_name} Analyst", lead, report)


def seed_demo(db: Session, password: str, seed: int = DEFAULT_SEED) -> SeedReport:
    report = SeedReport()
    names = SyntheticNameGenerator(seed)

    has_bank = db.execute(
        select(Organization.id).where(
            Organization.organization_type == OrganizationType.GLOBAL_BANK
        )
    ).first()
    if has_bank:
        report.skipped_structure = True
    else:
        _build_structure(db, names, report)

    # Link the department-manager demo account to a real department head.
    manager_employee = (
        db.execute(
            select(Employee)
            .where(Employee.job_title == "Head of Customer Onboarding")
            .order_by(Employee.employee_number)
        )
        .scalars()
        .first()
    )
    for username, role, display_name in DEMO_USERS:
        if db.execute(select(User.id).where(User.username == username)).first():
            continue
        employee_id = None
        if role == RoleCode.DEPARTMENT_MANAGER and manager_employee is not None:
            linked = db.execute(
                select(User.id).where(User.employee_id == manager_employee.id)
            ).first()
            employee_id = None if linked else manager_employee.id
        create_user(
            db,
            UserCreate(
                username=username,
                email=f"{username}@atlasbank.example",
                display_name=f"Demo {display_name}",
                password=password,
                role=role,
                employee_id=employee_id,
            ),
            actor_id=None,
        )
        report.users.append(username)
    return report
