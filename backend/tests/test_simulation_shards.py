"""Phase 16: sharded simulation runs — parallel slices with their own staff, merged results."""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Connection, func, select, text
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.jobs import engine as jobs
from app.jobs.models import Job
from app.modules.accounts.service import deposit
from app.modules.ledger.models import LedgerBalance
from app.simulation import runner
from app.simulation.models import (
    SimulationCaseResult,
    SimulationRun,
    SimulationShard,
    SimulationStatus,
)
from app.simulation.router import get_simulation_sessionmaker
from app.simulation.runner import SimulationSetupError, create_run, execute_run
from app.simulation.scenarios import get_scenario
from tests.factories import (
    auth,
    make_customer,
    make_org_tree,
    make_staff,
    make_user,
    open_account,
)

SCENARIO = get_scenario("retail-onboarding")
assert SCENARIO is not None


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


def _create(db: Session, *, shards: int, seed: int = 21, applications: int = 30):
    creator = make_user(db, RoleCode.AI_RESEARCHER)
    run = create_run(
        db, SCENARIO, profile="custom", applications=applications, employees=18, seed=seed,
        created_by=creator.id, shards=shards,
    )  # fmt: skip
    db.commit()
    return run


def _shard_jobs(db: Session, run: SimulationRun) -> list[Job]:
    return list(
        db.execute(
            select(Job)
            .where(Job.kind == "simulation.shard", Job.payload["run_id"].astext == str(run.id))
            .order_by(Job.job_number)
        ).scalars()
    )


def test_a_sharded_run_matches_itself_in_any_order_and_the_single_run_in_outcomes(
    db: Session, factory
) -> None:
    make_org_tree(db)
    single = _create(db, shards=1)
    execute_run(factory, single.id)

    outcomes = []
    for order in (lambda j: j, lambda j: list(reversed(j))):
        run = _create(db, shards=3)
        queued = execute_run(factory, run.id)
        assert len(queued) == 3
        db.expire_all()
        assert db.get(SimulationRun, run.id).status == SimulationStatus.RUNNING
        for job in order(_shard_jobs(db, run)):
            assert jobs.run_now(factory, job.id) == "succeeded"
        db.expire_all()
        run = db.get(SimulationRun, run.id)
        assert run.status == SimulationStatus.COMPLETED, run.failure_reason
        outcomes.append(run)

    first, second = outcomes
    assert first.result_digest == second.result_digest  # shard order does not matter
    assert first.config_hash == second.config_hash != db.get(SimulationRun, single.id).config_hash
    single = db.get(SimulationRun, single.id)
    # Each case decides the same way (per-case random streams); only queueing differs.
    assert first.results["outcomes"] == single.results["outcomes"]
    assert first.results["ground_truth"] == single.results["ground_truth"]
    assert first.results["staff"] == single.results["staff"]  # the whole run's staff
    assert first.results["cases"] == first.results["completed"] == 30
    assert [s["cases"] for s in first.results["execution"]["shards"]] == [10, 10, 10]
    shards = db.execute(select(SimulationShard).where(SimulationShard.run_id == first.id)).scalars()
    assert {(s.status, s.cases_completed) for s in shards} == {("completed", 10)}
    # Staff were hired once for the whole run, not per shard.
    team_results = db.execute(
        select(func.count()).where(SimulationCaseResult.run_id == first.id)
    ).scalar_one()
    assert team_results == 30


def test_merging_happens_once_when_the_last_shard_finishes(db: Session, factory) -> None:
    make_org_tree(db)
    run = _create(db, shards=2)
    execute_run(factory, run.id)
    first, last = _shard_jobs(db, run)
    # Each shard has its share of every role, dealt round-robin; together, everyone.
    db.expire_all()
    run = db.get(SimulationRun, run.id)
    views = [runner._Simulation(db, run, SCENARIO, shard) for shard in (0, 1)]
    for view in views:
        view.load_staff()
    everyone = runner._role_counts(SCENARIO, 18)
    assert sum(len(v.tellers) for v in views) == everyone["teller"]
    assert all(abs(len(views[0].reviewers[s]) - len(views[1].reviewers[s])) <= 1
               for s in views[0].reviewers)  # fmt: skip
    ids = [p.principal.id for v in views for people in v.reviewers.values() for p in people]
    assert len(ids) == len(set(ids))  # nobody works in two shards
    jobs.run_now(factory, first.id)
    db.expire_all()
    assert db.get(SimulationRun, run.id).status == SimulationStatus.RUNNING  # one to go
    assert runner.merge_shards(factory, run.id) is False
    jobs.run_now(factory, last.id)
    db.expire_all()
    assert db.get(SimulationRun, run.id).status == SimulationStatus.COMPLETED
    assert runner.merge_shards(factory, run.id) is False  # already merged


def test_a_failing_shard_fails_the_run_and_stops_the_others(
    db: Session, factory, monkeypatch
) -> None:
    make_org_tree(db)
    run = _create(db, shards=2)
    execute_run(factory, run.id)
    first, second = _shard_jobs(db, run)
    original = runner._Simulation.load_staff

    def broken(self):
        if self.shard == 0:
            raise RuntimeError("simulated crash")
        original(self)

    monkeypatch.setattr(runner._Simulation, "load_staff", broken)
    jobs.run_now(factory, first.id)
    jobs.run_now(factory, second.id)

    db.expire_all()
    run = db.get(SimulationRun, run.id)
    assert run.status == SimulationStatus.FAILED
    assert "Shard 0 failed: RuntimeError: simulated crash" in run.failure_reason
    statuses = dict(
        db.execute(
            select(SimulationShard.shard, SimulationShard.status).where(
                SimulationShard.run_id == run.id
            )
        ).all()
    )
    assert statuses == {0: "failed", 1: "failed"}  # the second never simulated anything


def test_shards_need_staff_of_every_role() -> None:
    with pytest.raises(SimulationSetupError, match="need at least 4 staff of each role"):
        runner._check_shards(SCENARIO, None, applications=100, employees=8, shards=4)
    with pytest.raises(SimulationSetupError, match="more shards than cases"):
        runner._check_shards(SCENARIO, None, applications=2, employees=40, shards=3)


def test_a_pinned_balance_row_takes_the_transactions_lines(db: Session) -> None:
    staff = make_staff(db)
    account = open_account(db, staff, make_customer(db))
    db.execute(text("SET LOCAL atlas.balance_shard = '5'"))
    deposit(
        db, account.id, amount=1_000, memo="pinned", idempotency_key=uuid.uuid4().hex,
        actor_id=staff.employee.id,
    )  # fmt: skip
    rows = db.execute(
        select(LedgerBalance.shard).where(
            LedgerBalance.ledger_account_id == account.ledger_account_id
        )
    ).scalars()
    assert set(rows) == {5}


@pytest.fixture
def api(app: FastAPI, factory) -> TestClient:
    app.dependency_overrides[get_simulation_sessionmaker] = lambda: factory
    with TestClient(app) as client:
        yield client


def test_api_starts_sharded_runs_and_checks_profiles(api: TestClient, db: Session) -> None:
    make_org_tree(db)
    headers = auth(make_user(db, RoleCode.AI_RESEARCHER))
    body = {"profile": "custom", "applications": 20, "employees": 12, "seed": 4}

    too_many = api.post("/api/v1/simulations", json={**body, "shards": 9}, headers=headers)
    assert too_many.status_code == 422
    short_staff = api.post(
        "/api/v1/simulations", json={**body, "employees": 4, "shards": 3}, headers=headers
    )
    assert short_staff.status_code == 422 and "staff of each role" in short_staff.text
    large = api.post("/api/v1/simulations", json={"profile": "large", "shards": 2}, headers=headers)
    assert large.status_code == 422 and "at least 4 parallel shards" in large.text
    profiles = {p["profile_id"]: p for p in api.get(
        "/api/v1/simulations/profiles", headers=headers).json()}  # fmt: skip
    assert profiles["large"]["min_shards"] == 4 and profiles["large"]["runnable"]

    started = api.post("/api/v1/simulations", json={**body, "shards": 2}, headers=headers)
    assert started.status_code == 202, started.text
    # Inline execution (no worker processes): the API ran the shards itself.
    detail = api.get(f"/api/v1/simulations/{started.json()['id']}", headers=headers).json()
    assert detail["status"] == "completed" and detail["shards"] == 2
    assert [s["status"] for s in detail["shard_progress"]] == ["completed", "completed"]
    assert sum(s["cases_completed"] for s in detail["shard_progress"]) == 20
    rerun = api.post(f"/api/v1/simulations/{detail['id']}/rerun", headers=headers)
    rerun_detail = api.get(f"/api/v1/simulations/{rerun.json()['id']}", headers=headers).json()
    assert rerun_detail["shards"] == 2
    assert rerun_detail["result_digest"] == detail["result_digest"]
