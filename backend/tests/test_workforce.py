"""Phase 69: the workforce generator — staff by department and country, with a hierarchy,
roles, grades, pay and skills."""

from collections import Counter, defaultdict

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation
from app.core.permissions import RoleCode
from app.modules.countries.models import Country
from app.modules.employees import workforce
from app.modules.employees.models import Employee
from app.modules.hr import service as hr
from app.modules.identity.models import Role
from tests.factories import auth, make_org_tree, make_user


def _generated(db: Session) -> list[Employee]:
    return list(db.execute(select(Employee).where(
        Employee.generated_from.is_not(None))).scalars())  # fmt: skip


def test_shares_sum_exactly_and_follow_the_weights() -> None:
    assert workforce._shares(10, [1, 1, 1]) == [4, 3, 3]
    shares = workforce._shares(150_000, [30, 10, 2, 2, 1])
    assert sum(shares) == 150_000 and shares[0] == 100_000


def test_the_workforce_has_a_hierarchy_roles_grades_pay_and_skills(db: Session) -> None:
    make_org_tree(db)
    result = workforce.generate_workforce(db, 2_000, seed=2030)
    assert result["created"] == 2_000 and result["departments"] >= 2
    # A second run with the seed adds nothing.
    again = workforce.generate_workforce(db, 2_000, seed=2030)
    assert (again["created"], again["existing"]) == (0, 2_000)

    staff = _generated(db)
    assert len(staff) == 2_000
    roles = {r.id: r.code for r in db.execute(select(Role)).scalars()}
    by_id = {e.id: e for e in staff}
    heads = [e for e in staff if e.manager_id is None]
    assert {e.grade for e in heads} == {9}
    assert {roles[e.role_id] for e in heads} == {RoleCode.DEPARTMENT_MANAGER.value}
    assert len({e.department_id for e in heads}) == len(heads)  # one head per department
    reports: dict = defaultdict(int)
    for e in staff:
        if e.manager_id is None:
            continue
        boss = by_id[e.manager_id]
        assert boss.department_id == e.department_id  # managers are in the same department
        if e.grade in (6, 7):
            assert boss.manager_id is None  # team leads report to the head
        else:
            assert 1 <= e.grade <= 5 and boss.grade in (6, 7)
            reports[boss.id] += 1
    assert max(reports.values()) <= workforce.TEAM_SIZE

    # Pay rises with the grade; it is in the country's currency.
    countries = {c.id: c for c in db.execute(select(Country)).scalars()}
    assert all(e.compensation_currency == countries[e.country_id].default_currency
               for e in staff)  # fmt: skip
    usd = [e for e in staff if e.compensation_currency == "USD"]
    mean = {g: sum(e.annual_compensation for e in usd if e.grade == g)
            / max(1, sum(1 for e in usd if e.grade == g)) for g in (1, 3, 5, 9)}  # fmt: skip
    assert mean[1] < mean[3] < mean[5] < mean[9]

    # Skills: from the department's pool, a general one, and a language of the country.
    for e in staff[:200]:
        languages = [s for s in e.skills if s.startswith("language:")]
        assert len(languages) == 1
        assert languages[0].split(":", 1)[1] in countries[e.country_id].supported_languages
        assert 3 <= len(e.skills) <= 4
    grades = Counter(e.grade for e in staff)
    assert grades[1] > grades[4] > grades[5]  # entry grades are the most common
    # Everyone starts active, so the leave sweep (WF-1045) has nothing to change for them.
    assert {e.employment_status for e in staff} == {"active"}
    swept = hr.leave_sweep(db)
    assert (swept["started"], swept["ended"]) == (0, 0)


def test_the_rules(db: Session) -> None:
    with pytest.raises(BusinessRuleViolation) as refused:
        workforce.generate_workforce(db, 0, seed=1)
    assert refused.value.details["rule"] == "count_invalid"
    with pytest.raises(BusinessRuleViolation) as refused:
        workforce.generate_workforce(db, 10, seed=1)
    assert refused.value.details["rule"] == "no_departments"


def test_the_api(client: TestClient, db: Session) -> None:
    make_org_tree(db)
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    auditor = make_user(db, RoleCode.AUDITOR)
    db.commit()
    assert client.post("/api/v1/employees/workforce/generate", headers=auth(auditor),
                       json={"count": 100, "seed": 7}).status_code == 403  # fmt: skip
    made = client.post("/api/v1/employees/workforce/generate", headers=auth(admin),
                       json={"count": 300, "seed": 7})  # fmt: skip
    assert made.status_code == 200, made.text
    assert made.json()["created"] == 300
    summary = client.get("/api/v1/employees/workforce/summary", headers=auth(auditor)).json()
    assert summary["generated"] == 300
    assert sum(summary["grades"].values()) == 300
    assert summary["roles"]["department_manager"] >= 2
    listed = client.get("/api/v1/employees?limit=5", headers=auth(admin)).json()["items"]
    assert all("grade" in e and "skills" in e for e in listed)
