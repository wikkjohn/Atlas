"""Phase 55: human resources — hiring, onboarding, leave, shifts and simulation staffing."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, ConflictError
from app.core.permissions import RoleCode
from app.modules.employees.models import EmploymentStatus
from app.modules.hr import service as hr
from app.simulation import service as simulations
from app.simulation.scenarios import get_scenario
from app.simulation.schemas import StartSimulation
from tests.factories import auth, make_employee, make_org_tree, make_user

MONDAY = date(2041, 3, 4)  # a full Monday-to-Friday week in the US, no holidays


def test_hiring_and_onboarding(db: Session) -> None:
    tree = make_org_tree(db)
    manager = make_user(db, RoleCode.DEPARTMENT_MANAGER)
    executive = make_user(db, RoleCode.REGIONAL_EXECUTIVE)
    dept = tree.us_onboarding
    with pytest.raises(BusinessRuleViolation, match="Explain"):
        hr.open_requisition(db, dept, job_title="Adviser", role="banking_employee", openings=1,
                            salary_min=4_000_000, salary_max=5_000_000, reason="short",
                            requested_by=manager.id)  # fmt: skip
    with pytest.raises(BusinessRuleViolation, match="not a role"):
        hr.open_requisition(db, dept, job_title="Bot", role="system_scheduler", openings=1,
                            salary_min=1, salary_max=2, reason="We need a robot here.",
                            requested_by=manager.id)  # fmt: skip
    row = hr.open_requisition(db, dept, job_title="Onboarding Adviser", role="banking_employee",
                              openings=1, salary_min=4_000_000, salary_max=5_000_000,
                              reason="Two advisers left this month.",
                              requested_by=manager.id)  # fmt: skip
    assert row.requisition_number.startswith("REQ-") and row.currency == "USD"
    candidate = None
    with pytest.raises(BusinessRuleViolation, match="approved requisition"):
        candidate = hr.add_candidate(db, row, "Rina", "Okafor")
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        hr.decide_requisition(db, row, manager.id, approve=True)
    hr.decide_requisition(db, row, executive.id, approve=True)
    assert row.status == "approved" and candidate is None
    candidate = hr.add_candidate(db, row, "Rina", "Okafor")
    with pytest.raises(BusinessRuleViolation, match="within the band"):
        hr.make_offer(db, candidate, 6_000_000, MONDAY, manager.id)
    with pytest.raises(BusinessRuleViolation, match="past"):
        hr.make_offer(db, candidate, 4_500_000, date(2020, 1, 1), manager.id)
    hr.make_offer(db, candidate, 4_500_000, MONDAY, manager.id)
    employee = hr.hire(db, candidate, manager.id)
    assert employee.department_id == dept.id and employee.annual_compensation == 4_500_000
    assert employee.job_title == "Onboarding Adviser" and employee.role.code == "banking_employee"
    assert candidate.status == "hired" and row.filled == 1 and row.status == "filled"
    tasks = hr.onboarding(db, employee.id)
    assert [t.code for t in tasks][:2] == ["contract", "it_access"] and len(tasks) == 5
    assert max(t.due for t in tasks) == MONDAY + timedelta(days=90)
    hr.complete_task(db, tasks[0].id, manager.id)
    assert len(hr.onboarding(db, employee.id, open_only=True)) == 4
    with pytest.raises(ConflictError):
        hr.complete_task(db, tasks[0].id, manager.id)


def test_leave(db: Session) -> None:
    tree = make_org_tree(db)
    manager, other = make_user(db, RoleCode.DEPARTMENT_MANAGER), make_user(
        db, RoleCode.DEPARTMENT_MANAGER)  # fmt: skip
    employee = make_employee(db, tree.us_onboarding)
    # A week Monday to Sunday: five business days in the US.
    leave = hr.request_leave(db, employee, "annual", MONDAY, MONDAY + timedelta(days=6),
                             manager.id)  # fmt: skip
    assert leave.days == 5 and leave.leave_number.startswith("LV-")
    with pytest.raises(BusinessRuleViolation, match="overlaps"):
        hr.request_leave(db, employee, "sick", MONDAY + timedelta(days=2), MONDAY
                         + timedelta(days=3), manager.id)  # fmt: skip
    with pytest.raises(BusinessRuleViolation, match="no working days"):
        hr.request_leave(db, employee, "annual", date(2041, 3, 16), date(2041, 3, 17),
                         manager.id)  # fmt: skip
    # 5 used of 25: 2 June to 2 July is 21 business days (Juneteenth off), too many.
    with pytest.raises(BusinessRuleViolation, match="20 of the year's 25 remain"):
        hr.request_leave(db, employee, "annual", date(2041, 6, 2), date(2041, 7, 2),
                         manager.id)  # fmt: skip
    hr.request_leave(db, employee, "unpaid", date(2041, 6, 2), date(2041, 6, 30), manager.id)
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        hr.decide_leave(db, leave, manager.id, approve=True)
    hr.decide_leave(db, leave, other.id, approve=True)
    assert leave.status == "approved"
    swept = hr.leave_sweep(db, MONDAY + timedelta(days=1))
    assert swept["started"] == 1 and employee.employment_status == EmploymentStatus.ON_LEAVE
    hr.leave_sweep(db, MONDAY + timedelta(days=8))
    assert employee.employment_status == EmploymentStatus.ACTIVE


def test_shifts_and_capacity(db: Session) -> None:
    tree = make_org_tree(db)
    manager, other = make_user(db, RoleCode.DEPARTMENT_MANAGER), make_user(
        db, RoleCode.DEPARTMENT_MANAGER)  # fmt: skip
    dept = tree.us_onboarding
    staff = [make_employee(db, dept) for _ in range(4)]
    boss = make_employee(db, dept, role=RoleCode.DEPARTMENT_MANAGER)
    stranger = make_employee(db, tree.jp_onboarding)
    away = hr.request_leave(db, staff[3], "sick", MONDAY, MONDAY, manager.id)
    hr.decide_leave(db, away, other.id, approve=True)
    # No shifts that day: everyone not on leave can work.
    cap = hr.capacity(db, dept.id, MONDAY)
    assert (cap["headcount"], cap["on_leave"], cap["available"]) == (5, 1, 4)
    assert cap["available_by_role"] == {"teller": 3, "manager": 1}
    early = hr.create_shift(db, dept, MONDAY, 8, 8, 3, manager.id)
    late = hr.create_shift(db, dept, MONDAY, 14, 8, 2, manager.id)
    for e in (staff[0], staff[1], boss):
        hr.assign(db, early, e, manager.id)
    with pytest.raises(BusinessRuleViolation, match="other department"):
        hr.assign(db, late, stranger, manager.id)
    with pytest.raises(BusinessRuleViolation, match="on leave"):
        hr.assign(db, late, staff[3], manager.id)
    with pytest.raises(BusinessRuleViolation, match="same time"):
        hr.assign(db, late, staff[0], manager.id)
    with pytest.raises(BusinessRuleViolation, match="fully staffed"):
        hr.assign(db, early, staff[2], manager.id)
    # Rest: after the early shift (08:00 to 16:00), a start at midnight leaves only 8 hours.
    night = hr.create_shift(db, dept, MONDAY + timedelta(days=1), 0, 6, 2, manager.id)
    with pytest.raises(BusinessRuleViolation, match="rest"):
        hr.assign(db, night, staff[0], manager.id)
    # 48 hours a week: six 8-hour shifts are the most.
    for day in range(1, 6):
        hr.assign(db, hr.create_shift(db, dept, MONDAY + timedelta(days=day), 8, 8, 1,
                                      manager.id), staff[1], manager.id)  # fmt: skip
    sunday = hr.create_shift(db, dept, MONDAY + timedelta(days=6), 8, 8, 1, manager.id)
    with pytest.raises(BusinessRuleViolation, match="48 hours"):
        hr.assign(db, sunday, staff[1], manager.id)
    # Shifts are rostered that day: only the rostered staff count.
    cap = hr.capacity(db, dept.id, MONDAY)
    assert (cap["shifts"], cap["rostered"], cap["available"]) == (2, 3, 3)
    assert cap["available_by_role"] == {"teller": 2, "manager": 1}


def test_a_simulation_staffed_from_hr(db: Session) -> None:
    tree = make_org_tree(db)
    researcher = make_user(db, RoleCode.AI_RESEARCHER)
    dept = tree.us_onboarding
    scenario = get_scenario("retail-onboarding")
    day = scenario.simulated_start.date()
    body = StartSimulation(scenario_id="retail-onboarding", profile="custom", applications=10,
                           staffing_department_id=dept.id)  # fmt: skip
    with pytest.raises(BusinessRuleViolation, match="0 staff available"):
        simulations.start_run(db, body, researcher.id)
    staff = [make_employee(db, dept) for _ in range(6)]
    make_employee(db, dept, role=RoleCode.DEPARTMENT_MANAGER)
    make_employee(db, dept, role=RoleCode.COMPLIANCE_OFFICER)
    away = hr.request_leave(db, staff[0], "sick", day, day, researcher.id)
    hr.decide_leave(db, away, make_user(db, RoleCode.DEPARTMENT_MANAGER).id, approve=True)
    run = simulations.start_run(db, body, researcher.id)
    assert run.config["employees"] == 7  # eight in the department, one on leave that day
    assert run.config["staffing"]["on_leave"] == 1 and run.config["staffing"]["on"] == str(day)
    with pytest.raises(BusinessRuleViolation, match="no employees"):
        simulations.start_run(db, body.model_copy(update={"employees": 5}), researcher.id)


def test_the_hr_api(client: TestClient, db: Session) -> None:
    tree = make_org_tree(db)
    manager, executive = make_user(db, RoleCode.DEPARTMENT_MANAGER), make_user(
        db, RoleCode.REGIONAL_EXECUTIVE)  # fmt: skip
    teller = make_user(db, RoleCode.BANKING_EMPLOYEE)
    employee = make_employee(db, tree.us_onboarding)
    db.commit()
    m, x, t = auth(manager), auth(executive), auth(teller)
    assert client.get("/api/v1/hr/departments", headers=t).status_code == 403
    names = [d["name"] for d in client.get("/api/v1/hr/departments", headers=m).json()]
    assert "Customer Onboarding" in names
    body = {"department_id": str(tree.us_onboarding.id), "job_title": "Adviser",
            "salary_min": 4_000_000, "salary_max": 5_000_000,
            "reason": "Queues are over target."}  # fmt: skip
    assert client.post("/api/v1/hr/requisitions", json=body, headers=x).status_code == 403
    req = client.post("/api/v1/hr/requisitions", json=body, headers=m).json()
    url = f"/api/v1/hr/requisitions/{req['id']}/approve"
    assert client.post(url, headers=m).status_code == 403  # hr:approve
    assert client.post(url, headers=x).json()["status"] == "approved"
    name = {"first_name": "Rina", "last_name": "Okafor"}
    cand = client.post(f"/api/v1/hr/requisitions/{req['id']}/candidates", json=name,
                       headers=m).json()  # fmt: skip
    bad = client.post(f"/api/v1/hr/candidates/{cand['id']}/offer",
                      json={"salary": 9_000_000, "start_date": str(MONDAY)}, headers=m)  # fmt: skip
    assert bad.status_code == 422 and bad.json()["error"]["details"]["rule"] == "offer_outside_band"
    client.post(f"/api/v1/hr/candidates/{cand['id']}/offer",
                json={"salary": 4_200_000, "start_date": str(MONDAY)}, headers=m)  # fmt: skip
    hired = client.post(f"/api/v1/hr/candidates/{cand['id']}/hire", headers=m).json()
    assert hired["status"] == "hired" and hired["employee_number"].startswith("AGB-")
    leave = client.post("/api/v1/hr/leave", headers=m, json={
        "employee_number": employee.employee_number, "kind": "annual",
        "start_date": str(MONDAY), "end_date": str(MONDAY + timedelta(days=1))}).json()  # fmt: skip
    assert leave["days"] == 2
    assert client.post(f"/api/v1/hr/leave/{leave['id']}/approve", headers=m).status_code == 422
    shift = client.post("/api/v1/hr/shifts", headers=m, json={
        "department_id": str(tree.us_onboarding.id), "on": str(MONDAY + timedelta(days=7)),
        "start_hour": 9, "hours": 8, "required": 2}).json()  # fmt: skip
    rostered = client.post(f"/api/v1/hr/shifts/{shift['id']}/assign", headers=m,
                           json={"employee_number": employee.employee_number}).json()  # fmt: skip
    assert rostered["rostered"] == [employee.employee_number]
    week = str(MONDAY + timedelta(days=7))
    cap = client.get("/api/v1/hr/capacity", headers=x, params={
        "department_id": str(tree.us_onboarding.id), "on": week}).json()  # fmt: skip
    assert cap["available"] == 1 and cap["rostered"] == 1
    counts = client.get("/api/v1/hr/summary/counts", headers=m).json()
    assert counts["leave_to_decide"] == 1 and counts["onboarding_overdue"] >= 0
