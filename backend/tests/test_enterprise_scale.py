"""Phase 75: the Milestone F exit — what makes enterprise-sized runs possible."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import AuditEvent
from app.core.security import UNUSABLE_PASSWORD_HASH
from app.modules.employees.models import Employee
from app.modules.identity.models import User
from app.simulation import runner
from app.simulation.models import SimulationRun
from app.simulation.scenarios import get_scenario
from tests.factories import make_org_tree, make_user
from tests.test_simulation import session_factory  # noqa: F401  (the fixture)


def _run(db: Session, factory, employees: int, seed: int) -> SimulationRun:
    from app.core.permissions import RoleCode

    creator = make_user(db, RoleCode.AI_RESEARCHER)
    run = runner.create_run(
        db,
        get_scenario("retail-onboarding", 1),
        profile="custom",
        applications=30,
        employees=employees,
        seed=seed,
        created_by=creator.id,
    )
    db.commit()
    runner.execute_run(factory, run.id)
    db.expire_all()
    return db.get(SimulationRun, run.id)


def test_bulk_hiring_gives_the_same_staff_and_the_same_run(
    db: Session,
    session_factory,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_org_tree(db)
    db.commit()

    def audits() -> int:
        return db.execute(select(func.count()).select_from(AuditEvent)).scalar_one()

    start = audits()
    one_by_one = _run(db, session_factory, 12, seed=909)
    middle = audits()
    monkeypatch.setattr(runner, "BULK_HIRE_ABOVE", 5)
    bulk = _run(db, session_factory, 12, seed=909)
    assert one_by_one.status == bulk.status == "completed", bulk.failure_reason
    # The staff are the same people with the same roles; only the hiring path differs, so
    # every decision, and the digest, is the same.
    assert bulk.result_digest == one_by_one.result_digest
    staff = list(
        db.execute(select(User).where(User.username.like(f"sim{bulk.run_number}-%"))).scalars()
    )
    assert len(staff) == 12
    assert all(u.password_hash == UNUSABLE_PASSWORD_HASH and u.is_active for u in staff)
    employees = {
        e.id: e
        for e in db.execute(
            select(Employee).where(Employee.id.in_([u.employee_id for u in staff]))
        ).scalars()
    }
    assert len(employees) == 12
    assert {e.employee_number[:4] for e in employees.values()} == {"AGB-"}
    assert all(e.role_id == u.role_id for u in staff for e in [employees[u.employee_id]])
    # One audit record for the whole hire (and the run's own), not two per person.
    hired = (
        db.execute(select(AuditEvent).where(AuditEvent.action == "simulation.staff_hired"))
        .scalars()
        .all()
    )
    assert [a.event_metadata["staff"] for a in hired] == [12]
    # Hiring through the services audits each employee and each user; the bulk path, once.
    assert (middle - start) - (audits() - middle) >= 12


def test_the_engine_runs_a_case_in_fewer_statements(db: Session, session_factory) -> None:  # noqa: F811
    """Steps no longer flush and query one by one (Phase 75): far fewer statements per
    case than the ~195 before, with the same results."""
    from sqlalchemy import event

    make_org_tree(db)
    db.commit()
    count = {"n": 0}

    def tally(*_args) -> None:
        count["n"] += 1

    engine = db.get_bind().engine if hasattr(db.get_bind(), "engine") else db.get_bind()
    event.listen(engine, "before_cursor_execute", tally)
    try:
        run = _run(db, session_factory, 12, seed=911)
    finally:
        event.remove(engine, "before_cursor_execute", tally)
    assert run.status == "completed", run.failure_reason
    assert count["n"] / 30 < 160
