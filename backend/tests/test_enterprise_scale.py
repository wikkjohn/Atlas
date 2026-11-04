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


# --- Rolling archive --------------------------------------------------------------------------

HISTORY_TABLES = ("workflow_executions", "workflow_step_runs", "workflow_events")


@pytest.fixture
def archive_dir(tmp_path, monkeypatch):
    from app.simulation import history

    monkeypatch.setattr(history, "archive_root", lambda: tmp_path)
    return tmp_path


def _create(db: Session, *, seed: int, shards: int = 1, rolling: int | None = None):
    from app.core.permissions import RoleCode

    creator = make_user(db, RoleCode.AI_RESEARCHER)
    run = runner.create_run(
        db,
        get_scenario("retail-onboarding", 1),
        profile="custom",
        applications=30,
        employees=18,
        seed=seed,
        created_by=creator.id,
        shards=shards,
        rolling_archive=rolling,
    )
    db.commit()
    return run


def _counts(db: Session, run_id) -> dict[str, int]:
    from sqlalchemy import text

    from app.simulation import history

    raw = db.connection().connection.driver_connection
    return {
        table: db.execute(
            text(
                f"SELECT count(*) FROM {table} WHERE {history._where(table, run_id).as_string(raw)}"
            )
        ).scalar_one()
        for table in HISTORY_TABLES
    }


def test_a_rolling_archive_keeps_the_run_and_restores_its_history(
    db: Session,
    session_factory,  # noqa: F811
    archive_dir,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.simulation import history
    from app.simulation.models import HistoryState, SimulationArchive, SimulationArchiveSegment

    make_org_tree(db)
    monkeypatch.setattr(runner, "BATCH_EVENTS", 20)  # checkpoints, and so segments, often
    plain = _create(db, seed=31)
    runner.execute_run(session_factory, plain.id)
    rolling = _create(db, seed=31, rolling=7)
    runner.execute_run(session_factory, rolling.id)
    db.expire_all()
    plain, rolling = db.get(SimulationRun, plain.id), db.get(SimulationRun, rolling.id)
    assert plain.status == rolling.status == "completed", rolling.failure_reason
    # Where the history goes changes nothing that is simulated, or the run's identity.
    assert rolling.result_digest == plain.result_digest
    assert rolling.config_hash == plain.config_hash
    assert rolling.config["history"] == {"rolling_archive": 7}
    assert rolling.results["outcomes"] == plain.results["outcomes"]

    # Archived as it ran: nothing is left in the database, and the run is archived.
    assert rolling.history_state == HistoryState.ARCHIVED
    assert _counts(db, rolling.id) == dict.fromkeys(HISTORY_TABLES, 0)
    segments = list(
        db.execute(
            select(SimulationArchiveSegment)
            .where(SimulationArchiveSegment.run_id == rolling.id)
            .order_by(SimulationArchiveSegment.shard, SimulationArchiveSegment.sequence)
        ).scalars()
    )
    during = [s for s in segments if s.shard == 0]
    assert len(during) >= 2 and segments[0].shard == -1  # the rest, at the end
    assert all(s.summary["executions"] >= 7 for s in during)
    record = db.execute(
        select(SimulationArchive).where(SimulationArchive.run_id == rolling.id)
    ).scalar_one()
    assert record.manifest["format"] == history.SEGMENTED_FORMAT
    assert len(record.manifest["segments"]) == len(segments)
    expected = _counts(db, plain.id)
    assert {t: record.manifest["tables"][t]["rows"] for t in HISTORY_TABLES} == expected
    # The analytics' summary is the whole run's, added up across the segments.
    assert record.summary == history.summarize(db, plain.id)

    # Restored: every row is back, the segments are superseded, and it archives again.
    history.restore_run(session_factory, rolling.id, None)
    db.expire_all()
    assert db.get(SimulationRun, rolling.id).history_state == HistoryState.PRESENT
    assert _counts(db, rolling.id) == expected
    assert not (archive_dir / history.rolling_location(rolling.run_number)).exists()
    assert (
        db.execute(
            select(func.count()).where(SimulationArchiveSegment.run_id == rolling.id)
        ).scalar_one()
        == 0
    )
    again = history.archive_run(session_factory, rolling.id, None)
    assert again.manifest["format"] == history.FORMAT_VERSION and again.rows == record.rows


def test_a_sharded_run_archives_each_shard_as_it_goes(
    db: Session,
    session_factory,  # noqa: F811
    archive_dir,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.jobs import engine as jobs
    from app.jobs.models import Job
    from app.simulation.models import HistoryState, SimulationArchiveSegment

    make_org_tree(db)
    monkeypatch.setattr(runner, "BATCH_EVENTS", 20)
    digests = []
    for rolling in (None, 4):
        run = _create(db, seed=33, shards=2, rolling=rolling)
        runner.execute_run(session_factory, run.id)
        for job in db.execute(
            select(Job).where(
                Job.kind == "simulation.shard", Job.payload["run_id"].astext == str(run.id)
            )
        ).scalars():
            assert jobs.run_now(session_factory, job.id) == "succeeded"
        db.expire_all()
        run = db.get(SimulationRun, run.id)
        assert run.status == "completed", run.failure_reason
        digests.append(run.result_digest)
    assert digests[0] == digests[1]
    assert run.history_state == HistoryState.ARCHIVED
    shards = set(
        db.execute(
            select(SimulationArchiveSegment.shard).where(SimulationArchiveSegment.run_id == run.id)
        ).scalars()
    )
    assert shards == {-1, 0, 1}
    assert _counts(db, run.id) == dict.fromkeys(HISTORY_TABLES, 0)


def test_the_enterprise_profile_archives_as_it_runs_and_outages_cannot(db: Session) -> None:
    from app.core.permissions import RoleCode

    make_org_tree(db)
    creator = make_user(db, RoleCode.AI_RESEARCHER)
    run = runner.create_run(
        db,
        get_scenario("retail-onboarding", 1),
        profile="enterprise",
        applications=1_000_000,
        employees=150_000,
        seed=1,
        created_by=creator.id,
        shards=8,
    )
    assert run.config["history"] == {"rolling_archive": runner.ENTERPRISE_ROLLING_ARCHIVE}
    with pytest.raises(runner.SimulationSetupError, match="without a rolling archive"):
        runner.create_run(
            db,
            get_scenario("retail-onboarding-outage"),
            profile="custom",
            applications=10,
            employees=6,
            seed=1,
            created_by=creator.id,
            rolling_archive=5,
        )
