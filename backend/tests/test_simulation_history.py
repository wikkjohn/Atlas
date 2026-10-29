"""Phase 15: partitioned workflow history; archive, restore and reset of simulation history."""

import gzip
import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Connection, func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation
from app.core.permissions import RoleCode
from app.modules.analytics.service import simulation_costs
from app.modules.experiments.assumptions import CostAssumptions
from app.modules.identity.models import User
from app.modules.workflows import engine
from app.modules.workflows.models import Realm, WorkflowEvent, WorkflowExecution
from app.simulation import history
from app.simulation.models import (
    HistoryState,
    SimulationArchive,
    SimulationCaseResult,
    SimulationRun,
    SimulationStatus,
)
from app.simulation.router import get_simulation_sessionmaker
from app.simulation.runner import create_run, execute_run
from app.simulation.scenarios import get_scenario
from tests.factories import application, auth, make_org_tree, make_user, principal

SCENARIO = get_scenario("retail-onboarding")
assert SCENARIO is not None
TABLES = ("workflow_executions", "workflow_step_runs", "workflow_events", "ai_tool_invocations")


@pytest.fixture
def factory(db_connection: Connection):
    def make() -> Session:
        return Session(
            bind=db_connection,
            join_transaction_mode="create_savepoint",
            autoflush=False,
            expire_on_commit=False,
        )

    return make


@pytest.fixture(autouse=True)
def archive_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "archive_root", lambda: tmp_path)
    return tmp_path


def _run(db: Session, factory, seed: int = 11) -> SimulationRun:
    if seed == 11:  # the first run of a test sets the bank up
        make_org_tree(db)
    creator = make_user(db, RoleCode.AI_RESEARCHER)
    run = create_run(
        db, SCENARIO, profile="custom", applications=12, employees=6, seed=seed,
        created_by=creator.id,
    )  # fmt: skip
    db.commit()
    execute_run(factory, run.id)
    db.expire_all()
    run = db.get(SimulationRun, run.id)
    assert run.status == SimulationStatus.COMPLETED, run.failure_reason
    return run


def _history(db: Session, run: SimulationRun) -> dict[str, list[tuple]]:
    """Every stored row of the run's history, in a stable order."""
    rows = {}
    for table in TABLES:
        columns = ", ".join(history._columns(db, table))
        raw = db.connection().connection.driver_connection
        where = history._where(table, run.id).as_string(raw)
        rows[table] = [
            tuple(r)
            for r in db.execute(text(f"SELECT {columns} FROM {table} WHERE {where} ORDER BY id"))
        ]
    return rows


def _live_execution(db: Session) -> WorkflowExecution:
    teller = principal(make_user(db, RoleCode.BANKING_EMPLOYEE))
    execution, _ = engine.start(db, workflow_id="WF-0001", payload=application(), initiator=teller)
    db.commit()
    return execution


def test_history_is_stored_in_the_partition_of_its_realm(db: Session, factory) -> None:
    run = _run(db, factory)
    live = _live_execution(db)

    def partition(table: str, key: str, value) -> list[str]:
        return list(
            db.execute(
                text(f"SELECT DISTINCT tableoid::regclass::text FROM {table} WHERE {key} = :v"),
                {"v": value},
            ).scalars()
        )

    assert live.realm == Realm.LIVE
    assert partition("workflow_events", "execution_id", live.id) == ["workflow_events_live"]
    simulated = db.execute(
        select(WorkflowExecution.id).where(WorkflowExecution.simulation_run_id == run.id).limit(1)
    ).scalar_one()
    assert partition("workflow_step_runs", "execution_id", simulated) == [
        "workflow_step_runs_simulation"
    ]
    # The realm always follows the run: a simulated execution cannot claim to be live.
    with pytest.raises(DBAPIError, match="realm_matches_run"), db.begin_nested():
        db.execute(
            update(WorkflowExecution)
            .where(WorkflowExecution.id == simulated)
            .values(simulation_run_id=None)
        )


def test_archive_moves_history_to_files_and_restore_brings_back_every_row(
    db: Session, factory, archive_dir
) -> None:
    run = _run(db, factory)
    before = _history(db, run)
    assert all(before[t] for t in TABLES[:3])
    costs_before = simulation_costs(db, CostAssumptions())
    cases_before = db.execute(
        select(func.count()).where(SimulationCaseResult.run_id == run.id)
    ).scalar_one()

    record = history.archive_run(factory, run.id, None)

    db.expire_all()
    assert db.get(SimulationRun, run.id).history_state == HistoryState.ARCHIVED
    assert all(rows == [] for rows in _history(db, run).values())
    # Results stay: case rows, the run's summary, and the dashboard's cost estimate.
    assert (
        db.execute(select(func.count()).where(SimulationCaseResult.run_id == run.id)).scalar_one()
        == cases_before
    )
    assert simulation_costs(db, CostAssumptions()) == costs_before
    # The files hold exactly the rows and match the manifest.
    directory = archive_dir / record.location
    manifest = json.loads((directory / "manifest.json").read_text())
    assert manifest == record.manifest
    for table in TABLES:
        entry = manifest["tables"][table]
        assert entry["rows"] == len(before[table])
        with gzip.open(directory / entry["file"], "rb") as f:
            assert f.read().count(b"\n") == entry["rows"]
    assert record.rows == sum(len(v) for v in before.values())
    assert record.summary["executions"] == 12

    history.restore_run(factory, run.id, None)

    db.expire_all()
    assert db.get(SimulationRun, run.id).history_state == HistoryState.PRESENT
    assert _history(db, run) == before
    assert not directory.exists()  # the rows are back; the files are no longer needed
    assert db.get(SimulationArchive, record.id).restored_at is not None
    # Archived again after a restore: a new archive is in effect.
    again = history.archive_run(factory, run.id, None)
    assert again.id != record.id


def test_archive_and_restore_are_refused_when_they_do_not_apply(db: Session, factory) -> None:
    run = _run(db, factory)
    with pytest.raises(BusinessRuleViolation, match="only archived history"):
        history.restore_run(factory, run.id, None)
    history.archive_run(factory, run.id, None)
    with pytest.raises(BusinessRuleViolation, match="already archived"):
        history.archive_run(factory, run.id, None)

    queued = create_run(
        db, SCENARIO, profile="custom", applications=5, employees=6, seed=3,
        created_by=run.created_by,
    )  # fmt: skip
    db.commit()
    with pytest.raises(BusinessRuleViolation, match="only finished runs"):
        history.archive_run(factory, queued.id, None)


def test_restore_refuses_files_that_do_not_match_their_checksum(
    db: Session, factory, archive_dir
) -> None:
    run = _run(db, factory)
    record = history.archive_run(factory, run.id, None)
    events = archive_dir / record.location / "workflow_events.copy.gz"
    events.write_bytes(events.read_bytes()[:-10])

    with pytest.raises(BusinessRuleViolation, match="checksum"):
        history.restore_run(factory, run.id, None)
    db.expire_all()
    assert db.get(SimulationRun, run.id).history_state == HistoryState.ARCHIVED


def test_live_history_can_never_be_deleted(db: Session, factory) -> None:
    run = _run(db, factory)
    live = _live_execution(db)
    simulated = select(WorkflowExecution.id).where(WorkflowExecution.simulation_run_id == run.id)

    # Without the archive's setting, simulated events are as append-only as live ones.
    with pytest.raises(DBAPIError, match="append-only"), db.begin_nested():
        db.execute(
            WorkflowEvent.__table__.delete().where(WorkflowEvent.execution_id.in_(simulated))
        )
    with db.begin_nested():
        db.execute(text(f"SET LOCAL {history.PURGE_SETTING} = 'on'"))
        with pytest.raises(DBAPIError, match="append-only"), db.begin_nested():
            db.execute(
                WorkflowEvent.__table__.delete().where(WorkflowEvent.execution_id == live.id)
            )
        with pytest.raises(DBAPIError, match="append-only"), db.begin_nested():
            db.execute(text("TRUNCATE workflow_events_simulation"))


def test_reset_drops_all_simulation_history_and_keeps_the_live_bank(db: Session, factory) -> None:
    run = _run(db, factory)
    live = _live_execution(db)
    live_events = db.execute(
        select(func.count()).where(WorkflowEvent.execution_id == live.id)
    ).scalar_one()
    expected = {t: len(rows) for t, rows in _history(db, run).items()}

    report = history.reset(factory, None, archive=False)

    db.expire_all()
    assert report.purged == [run.run_number] and report.archived == []
    for table in ("workflow_executions", "workflow_step_runs", "workflow_events"):
        assert db.execute(text(f"SELECT count(*) FROM {table}_simulation")).scalar_one() == 0
    assert (
        db.execute(select(func.count()).where(WorkflowEvent.execution_id == live.id)).scalar_one()
        == live_events
    )
    assert db.get(SimulationRun, run.id).history_state == HistoryState.PURGED
    purge = db.execute(
        select(SimulationArchive).where(SimulationArchive.run_id == run.id)
    ).scalar_one()
    assert purge.kind == "purge"
    assert {t: e["rows"] for t, e in purge.manifest["tables"].items()} == {
        t: n for t, n in expected.items() if n
    }
    with pytest.raises(BusinessRuleViolation, match="purged"):
        history.restore_run(factory, run.id, None)
    # The recreated partitions work: a new run writes into them under the same guards.
    second = _run(db, factory, seed=12)
    assert _history(db, second)["workflow_events"]
    with pytest.raises(DBAPIError, match="append-only"), db.begin_nested():
        db.execute(text("TRUNCATE workflow_events_simulation"))


def test_reset_can_archive_first_and_waits_for_running_simulations(db: Session, factory) -> None:
    run = _run(db, factory)
    other = create_run(
        db, SCENARIO, profile="custom", applications=5, employees=6, seed=4,
        created_by=run.created_by,
    )  # fmt: skip
    db.commit()
    with pytest.raises(BusinessRuleViolation, match="queued or running"):
        history.reset(factory, None, archive=True)
    db.execute(
        update(SimulationRun)
        .where(SimulationRun.id == other.id)
        .values(status=SimulationStatus.FAILED, failure_reason="test")
    )
    db.commit()

    report = history.reset(factory, None, archive=True)

    assert sorted(report.archived) == sorted([run.run_number, other.run_number])
    assert report.purged == []
    db.expire_all()
    assert db.get(SimulationRun, run.id).history_state == HistoryState.ARCHIVED
    history.restore_run(factory, run.id, None)  # archived by the reset, so restorable


def test_retention_archives_only_old_finished_runs(db: Session, factory) -> None:
    old = _run(db, factory)
    recent = _run(db, factory, seed=12)
    db.execute(
        update(SimulationRun)
        .where(SimulationRun.id == old.id)
        .values(created_at=datetime.now(UTC) - timedelta(days=40))
    )
    db.commit()

    assert history.archive_older_than(factory, 30, None) == [old.run_number]
    db.expire_all()
    assert db.get(SimulationRun, recent.id).history_state == HistoryState.PRESENT


@pytest.fixture
def api(app: FastAPI, factory) -> TestClient:
    app.dependency_overrides[get_simulation_sessionmaker] = lambda: factory
    with TestClient(app) as client:
        yield client


def test_history_api_archives_and_restores_through_jobs(
    api: TestClient, db: Session, factory
) -> None:
    run = _run(db, factory)
    researcher = auth(db.get(User, run.created_by))
    teller = auth(make_user(db, RoleCode.BANKING_EMPLOYEE))
    auditor = auth(make_user(db, RoleCode.AUDITOR))

    assert api.post(f"/api/v1/simulations/{run.id}/archive", headers=teller).status_code == 403
    queued = api.post(f"/api/v1/simulations/{run.id}/archive", headers=researcher)
    assert queued.status_code == 202 and queued.json()["kind"] == "simulation.archive_history"

    # No worker process in tests: the API ran the job after responding.
    detail = api.get(f"/api/v1/simulations/{run.id}", headers=auditor).json()
    assert detail["history_state"] == "archived"
    assert detail["archive"]["kind"] == "archive" and detail["archive"]["rows"] > 0
    assert detail["archive"]["tables"]["workflow_executions"] == 12
    cases = api.get(f"/api/v1/simulations/{run.id}/cases", headers=auditor).json()
    assert cases["total"] == 12  # per-case results stay
    again = api.post(f"/api/v1/simulations/{run.id}/archive", headers=researcher)
    assert again.status_code == 422 and "already archived" in again.text

    overview = api.get("/api/v1/simulations/history", headers=researcher)
    assert overview.status_code == 200
    body = overview.json()
    assert body["runs_by_history_state"]["archived"] >= 1
    assert {(p["table"], p["realm"]) for p in body["partitions"]} >= {
        ("workflow_events", "live"),
        ("workflow_events", "simulation"),
    }
    assert body["recent_archives"][0]["run_number"] == run.run_number
    assert api.get("/api/v1/simulations/history", headers=auditor).status_code == 403

    restored = api.post(f"/api/v1/simulations/{run.id}/restore", headers=researcher)
    assert restored.status_code == 202
    detail = api.get(f"/api/v1/simulations/{run.id}", headers=auditor).json()
    assert detail["history_state"] == "present" and detail["archive"] is None
