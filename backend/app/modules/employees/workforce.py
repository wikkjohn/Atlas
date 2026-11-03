"""The workforce generator (Phase 69, roadmap Milestone F step 1).

`generate_workforce` staffs the bank: a seeded, deterministic number of synthetic employees,
spread over every active department in every country by the department's kind (a branch
network employs many more people than a tax department), each with:

- **a place in the hierarchy:** a head of department (grade 9), team leads (grades 6 and 7)
  for teams of about ten, and staff (grades 1 to 5) reporting to them;
- **a role:** the head manages the department (`department_manager`); staff take the
  department's role (`compliance_officer` in Financial Crime Compliance, `auditor` in
  Internal Audit, `ai_researcher` in the AI Innovation Lab, otherwise `banking_employee`);
- **a grade, a title and pay:** a US-dollar band per grade, converted at the FX anchor
  rates into the country's currency, as the subsidiary blueprint does;
- **skills:** from the department's pool, one general skill, and a language of the country.

Rows are inserted in bulk, a few thousand at a time. A second run with the same seed adds
nothing.
"""

import random
import time
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, insert, select, text
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.errors import BusinessRuleViolation
from app.core.money import to_minor_units
from app.core.permissions import RoleCode
from app.modules.countries.models import Country
from app.modules.employees.models import Employee, EmploymentStatus
from app.modules.fx import rates
from app.modules.identity.models import Role
from app.modules.organizations.models import Organization, OrganizationType
from app.simulation.generators import FIRST_NAMES, LAST_NAMES

GENERATOR = "workforce-v1"
MAX_COUNT = 250_000
BATCH = 5_000
TEAM_SIZE = 10
DOMAIN = "staff.atlas-bank.example"
# How many people a department employs, relative to one of weight 1.
DEPARTMENT_WEIGHTS = {
    "Branch Network": 30, "Customer Onboarding": 10, "Customer Service": 10,
    "Retail Banking": 8, "Retail Banking Operations": 8, "Payments Operations": 6,
    "Cards": 6, "Retail Lending": 5, "Collections": 5, "IT Operations": 6,
    "Financial Crime Compliance": 6, "Mortgages": 4, "Commercial Lending": 4,
    "Wealth Management": 3, "Treasury": 2, "Trade Finance": 2, "Credit Risk": 3,
    "Finance": 3, "Human Resources": 2, "Procurement": 2, "AI Innovation Lab": 1,
}  # fmt: skip
DEFAULT_WEIGHT = 2
STAFF_ROLES = {
    "Financial Crime Compliance": RoleCode.COMPLIANCE_OFFICER,
    "Internal Audit": RoleCode.AUDITOR,
    "AI Innovation Lab": RoleCode.AI_RESEARCHER,
}
# Grade -> (title, annual pay in US dollars at the band's midpoint).
GRADES = {
    1: ("Associate", 38_000), 2: ("Analyst", 46_000), 3: ("Senior Analyst", 57_000),
    4: ("Specialist", 70_000), 5: ("Senior Specialist", 86_000), 6: ("Team Lead", 102_000),
    7: ("Senior Team Lead", 122_000), 8: ("Manager", 148_000),
    9: ("Head of Department", 185_000), 10: ("Director", 240_000),
}  # fmt: skip
STAFF_GRADE_WEIGHTS = {1: 30, 2: 30, 3: 20, 4: 12, 5: 8}
SKILLS = {
    "Branch Network": ("cash-handling", "customer-service", "sales", "account-opening"),
    "Customer Onboarding": ("kyc", "document-checks", "account-opening", "sanctions"),
    "Customer Service": ("customer-service", "complaints", "telephony", "case-handling"),
    "Financial Crime Compliance": ("aml", "sanctions", "investigations", "kyc"),
    "Payments Operations": ("payments", "clearing", "reconciliation", "fraud"),
    "Cards": ("card-disputes", "fraud", "chargebacks", "payments"),
    "Retail Lending": ("credit", "underwriting", "affordability", "collections"),
    "Collections": ("collections", "negotiation", "affordability", "recoveries"),
    "Mortgages": ("underwriting", "valuations", "conveyancing", "credit"),
    "Commercial Lending": ("credit", "covenants", "financial-analysis", "relationship-management"),
    "Treasury": ("liquidity", "fx", "money-markets", "risk"),
    "Trade Finance": ("letters-of-credit", "guarantees", "documentary-checks", "sanctions"),
    "Wealth Management": ("suitability", "portfolios", "investments", "relationship-management"),
    "Credit Risk": ("risk-modelling", "ratings", "provisioning", "credit"),
    "Finance": ("accounting", "regulatory-reporting", "reconciliation", "period-close"),
    "Human Resources": ("recruitment", "payroll", "employee-relations", "rostering"),
    "Procurement": ("procurement", "vendor-management", "negotiation", "contracts"),
    "IT Operations": ("it-service-management", "incident-management", "python", "sql"),
    "AI Innovation Lab": ("python", "machine-learning", "evaluation", "sql"),
}  # fmt: skip
DEFAULT_SKILLS = ("case-handling", "policy", "reporting", "stakeholder-management")
GENERAL_SKILLS = ("excel", "presentation", "project-management", "data-analysis", "coaching",
                  "risk-awareness", "writing")  # fmt: skip
ON_LEAVE = 0.02  # share of staff on leave on the day they are generated


def _rule(message: str, rule: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, {"rule": rule})


def _shares(total: int, weights: list[int]) -> list[int]:
    """`total` split in proportion to `weights` (largest remainders), summing exactly."""
    whole = sum(weights)
    raw = [total * w / whole for w in weights]
    shares = [int(r) for r in raw]
    order = sorted(range(len(raw)), key=lambda i: (shares[i] - raw[i], i))
    for i in order[: total - sum(shares)]:
        shares[i] += 1
    return shares


def _pay(rng: random.Random, grade: int, per_usd: Decimal, currency: str) -> int:
    """Annual pay in minor units of `currency`: the grade's band ±10 %, to the thousand."""
    usd = GRADES[grade][1] * rng.uniform(0.9, 1.1)
    local = int(Decimal(usd) * per_usd)
    local = local // 1000 * 1000 if local >= 10_000 else max(local, 1)
    return to_minor_units(local, currency)


def generate_workforce(db: Session, count: int, seed: int,
                       actor_id: uuid.UUID | None = None) -> dict[str, Any]:  # fmt: skip
    """Generate `count` employees over the active departments; idempotent per seed."""
    if not 1 <= count <= MAX_COUNT:
        raise _rule(f"Generate 1 to {MAX_COUNT:,} employees.", "count_invalid")
    started = time.perf_counter()
    tag = f"{GENERATOR}:{seed}"
    existing = db.execute(select(func.count()).select_from(Employee).where(
        Employee.generated_from == tag)).scalar_one()  # fmt: skip
    if existing:
        return {"generator": tag, "requested": count, "created": 0, "existing": existing,
                "seconds": round(time.perf_counter() - started, 2)}  # fmt: skip
    departments = list(db.execute(
        select(Organization, Country).join(Country, Country.id == Organization.country_id)
        .where(Organization.organization_type == OrganizationType.DEPARTMENT,
               Organization.status == "active")
        .order_by(Country.iso_country_code, Organization.name)).all())  # fmt: skip
    if not departments:
        raise _rule("There are no departments to staff.", "no_departments")
    roles = {r.code: r.id for r in db.execute(select(Role)).scalars()}
    rng = random.Random(f"{GENERATOR}:{seed}")
    shares = _shares(count, [DEPARTMENT_WEIGHTS.get(d.name, DEFAULT_WEIGHT)
                             for d, _ in departments])  # fmt: skip
    numbers = iter(db.execute(text(
        "SELECT nextval('employee_number_seq') FROM generate_series(1, :n)"),
        {"n": count}).scalars().all())  # fmt: skip
    grades, weights = list(STAFF_GRADE_WEIGHTS), list(STAFF_GRADE_WEIGHTS.values())
    rows: list[dict[str, Any]] = []
    created = 0

    def person(dept: Organization, country: Country, grade: int, role: RoleCode,
               manager: uuid.UUID | None, title: str) -> uuid.UUID:  # fmt: skip
        number = next(numbers)
        first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
        pool = SKILLS.get(dept.name, DEFAULT_SKILLS)
        language = rng.choice(country.supported_languages or ["en"])
        skills = sorted({*rng.sample(pool, rng.randint(1, 2)), rng.choice(GENERAL_SKILLS),
                         f"language:{language}"})  # fmt: skip
        employee_id = uuid.UUID(int=rng.getrandbits(128), version=4)
        rows.append({
            "id": employee_id, "employee_number": f"AGB-{number:07d}",
            "first_name": first, "last_name": last,
            "email": f"{first.lower()}.{last.lower()}.{number}@{DOMAIN}",
            "organization_id": dept.id, "department_id": dept.id, "manager_id": manager,
            "job_title": title, "role_id": roles[role.value], "country_id": country.id,
            "employment_status": (EmploymentStatus.ON_LEAVE if rng.random() < ON_LEAVE
                                  else EmploymentStatus.ACTIVE).value,
            "annual_compensation": _pay(rng, grade, per_usd, country.default_currency),
            "compensation_currency": country.default_currency, "grade": grade,
            "skills": skills, "generated_from": tag,
        })  # fmt: skip
        return employee_id

    for (dept, country), size in zip(departments, shares, strict=True):
        if size == 0:
            continue
        per_usd = rates.units_per_usd(country.default_currency, rates.ANCHOR_DATE)
        staff_role = STAFF_ROLES.get(dept.name, RoleCode.BANKING_EMPLOYEE)
        head = person(dept, country, 9, RoleCode.DEPARTMENT_MANAGER, None,
                      f"Head of {dept.name}")  # fmt: skip
        rest = size - 1
        leads_needed = -(-rest // (TEAM_SIZE + 1)) if rest else 0
        leads = [person(dept, country, rng.choice((6, 7)), staff_role, head,
                        f"{GRADES[6][0]}, {dept.name}") for _ in range(leads_needed)]  # fmt: skip
        for i in range(rest - leads_needed):
            grade = rng.choices(grades, weights)[0]
            person(dept, country, grade, staff_role, leads[i % len(leads)],
                   f"{GRADES[grade][0]}, {dept.name}")  # fmt: skip
        if len(rows) >= BATCH:
            db.execute(insert(Employee), rows)
            created += len(rows)
            rows = []
    if rows:
        db.execute(insert(Employee), rows)
        created += len(rows)
    db.flush()
    seconds = round(time.perf_counter() - started, 2)
    record_audit_event(db, actor_id=actor_id, action="employees.workforce_generated",
                       entity_type="employee", entity_id=None,
                       metadata={"seed": seed, "count": count, "created": created,
                                 "seconds": seconds})  # fmt: skip
    return {"generator": tag, "requested": count, "created": created, "existing": 0,
            "departments": sum(1 for s in shares if s), "seconds": seconds}  # fmt: skip


def summary(db: Session) -> dict[str, Any]:
    """The workforce in numbers: by country, department, grade, role and skill."""

    def by(column, *where, limit: int | None = None) -> dict[str, int]:
        query = (select(column, func.count()).select_from(Employee)
                 .join(Country, Country.id == Employee.country_id)
                 .join(Organization, Organization.id == Employee.department_id)
                 .join(Role, Role.id == Employee.role_id)
                 .where(*where).group_by(column).order_by(func.count().desc()))  # fmt: skip
        if limit:
            query = query.limit(limit)
        return {str(k): n for k, n in db.execute(query).all()}

    total = db.execute(select(func.count()).select_from(Employee)).scalar_one()
    generated = db.execute(select(func.count()).select_from(Employee).where(
        Employee.generated_from.is_not(None))).scalar_one()  # fmt: skip
    skills = db.execute(text(
        "SELECT s, count(*) FROM employees, jsonb_array_elements_text(skills) AS s "
        "GROUP BY s ORDER BY count(*) DESC LIMIT 12")).all()  # fmt: skip
    grades = by(Employee.grade, Employee.grade.is_not(None))
    return {
        "employees": total, "generated": generated,
        "countries": by(Country.iso_country_code),
        "departments": by(Organization.name, limit=12),
        "grades": dict(sorted(grades.items(), key=lambda kv: int(kv[0]))),
        "roles": by(Role.code), "statuses": by(Employee.employment_status),
        "top_skills": {s: n for s, n in skills},
    }  # fmt: skip
