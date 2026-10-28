"""Phase 5: simulation clock, generators, runner, run registry and API."""

import re
from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Connection, func, select
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.employees.models import Employee
from app.modules.identity.models import User
from app.modules.workflows import engine
from app.modules.workflows.models import WorkflowExecution
from app.modules.workflows.wf0001 import (
    SYNTHETIC_WATCHLIST,
    RetailAccountApplication,
    document_number_valid,
)
from app.simulation.clock import ClockError, SimulationClock
from app.simulation.generators import (
    FIRST_NAMES,
    LAST_NAMES,
    SHOULD_REJECT,
    WATCHLIST_NAMES,
    ApplicationGenerator,
    StaffGenerator,
    digest,
)
from app.simulation.models import SimulationCaseResult, SimulationRun, SimulationStatus
from app.simulation.router import get_simulation_sessionmaker
from app.simulation.runner import create_run, execute_run
from app.simulation.scenarios import PROFILES, ApplicationMix, get_scenario
from tests.factories import auth, make_org_tree, make_user

SCENARIO = get_scenario("retail-onboarding")
assert SCENARIO is not None
START = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)


def _generator(seed: int) -> ApplicationGenerator:
    return ApplicationGenerator(
        seed=seed,
        mix=ApplicationMix().normalized(),
        countries=["DE", "GB", "JP", "SG", "US"],
        arrival_window_seconds=8 * 3600,
        document_delay_seconds=(7200, 172800),
        today=START.date(),
    )


# --- Clock ------------------------------------------------------------------------------------


def test_clock_only_moves_forward() -> None:
    clock = SimulationClock(START)
    clock.advance_to(START + timedelta(hours=2))
    assert clock.elapsed == timedelta(hours=2)
    clock.advance_to(clock.now)  # standing still is allowed
    with pytest.raises(ClockError):
        clock.advance_to(START)


def test_clock_requires_a_timezone() -> None:
    with pytest.raises(ClockError):
        SimulationClock(datetime(2026, 1, 5, 9, 0))


# --- Generators -------------------------------------------------------------------------------


def test_same_seed_generates_identical_applications() -> None:
    first = _generator(7).generate(300)
    assert first == _generator(7).generate(300)
    assert digest([a.payload for a in first]) != digest(
        [a.payload for a in _generator(8).generate(300)]
    )


def test_applications_are_synthetic_and_valid_workflow_input() -> None:
    apps = _generator(11).generate(500)
    synthetic_names = {f"{f} {last}" for f in FIRST_NAMES for last in LAST_NAMES}
    for app in apps:
        payload = {k: v for k, v in app.payload.items() if not k.startswith("_")}
        RetailAccountApplication.model_validate(payload)  # accepted by WF-0001
        # Only generated fields: no contact details, addresses or identifiers of people.
        assert set(payload) == {
            "applicant_name",
            "date_of_birth",
            "country_code",
            "account_type",
            "documents",
            "politically_exposed",
            "expected_monthly_deposits",
        }
        name = payload["applicant_name"]
        if app.kind == "sanctions_hit":
            assert name in WATCHLIST_NAMES and name.lower() in SYNTHETIC_WATCHLIST
        else:
            assert name in synthetic_names
        for document in payload["documents"]:
            assert re.fullmatch(r"[PNA]\d{8}", document["document_number"])
            valid = document_number_valid(document["document_type"], document["document_number"])
            assert valid == (
                app.kind != "forged_document" or document["document_type"] == "proof_of_address"
            )
        assert app.expected_outcome == ("rejected" if app.kind in SHOULD_REJECT else "approved")


def test_application_mix_follows_the_weights() -> None:
    kinds = Counter(a.kind for a in _generator(3).generate(5000))
    shares = ApplicationMix().normalized()
    for kind, share in shares.items():
        assert abs(kinds[kind] / 5000 - share) < 0.02, kind


def test_staff_allocation_covers_every_role() -> None:
    staff = StaffGenerator(5, {"teller": 0.4, "manager": 0.4, "compliance": 0.2}).generate(25)
    assert len(staff) == 25
    assert Counter(s.role for s in staff) == {"teller": 10, "manager": 10, "compliance": 5}
    small = StaffGenerator(5, {"teller": 0.4, "manager": 0.4, "compliance": 0.2}).generate(3)
    assert {s.role for s in small} == {"teller", "manager", "compliance"}
    assert staff == StaffGenerator(5, {"teller": 0.4, "manager": 0.4, "compliance": 0.2}).generate(
        25
    )


def test_profiles_label_the_enterprise_scale_as_an_unverified_target() -> None:
    assert (PROFILES["small"].applications, PROFILES["small"].employees) == (100, 25)
    assert (PROFILES["department"].applications, PROFILES["department"].employees) == (
        10_000,
        500,
    )
    assert PROFILES["enterprise"].employees == 150_000
    assert PROFILES["enterprise"].status == "target"


# --- Runner -----------------------------------------------------------------------------------


@pytest.fixture
def session_factory(db_connection: Connection):
    def factory() -> Session:
        return Session(
            bind=db_connection,
            join_transaction_mode="create_savepoint",
            autoflush=False,
            expire_on_commit=False,
        )

    return factory


def _run(db: Session, factory, *, seed: int, applications: int = 24, employees: int = 6):
    creator = db.execute(select(User).limit(1)).scalar_one_or_none() or make_user(
        db, RoleCode.AI_RESEARCHER
    )
    run = create_run(
        db,
        SCENARIO,
        profile="custom",
        applications=applications,
        employees=employees,
        seed=seed,
        created_by=creator.id,
    )
    db.commit()
    execute_run(factory, run.id)
    db.expire_all()
    return db.get(SimulationRun, run.id)


def test_run_executes_every_case_through_the_workflow_engine(db: Session, session_factory) -> None:
    make_org_tree(db)
    run = _run(db, session_factory, seed=101)

    assert run.status == SimulationStatus.COMPLETED, run.failure_reason
    results = run.results
    assert results["cases"] == results["completed"] == 24
    assert sum(results["outcomes"].values()) == 24
    truth = results["ground_truth"]
    assert truth["correct"] + truth["false_approvals"] + truth["false_rejections"] == 24
    assert results["execution"]["events_processed"] >= 24
    assert results["execution"]["workflow_steps_completed"] > 24 * 5
    assert run.wall_ms is not None and run.wall_ms > 0
    assert run.simulated_end > run.simulated_start
    assert run.progress["cases_completed"] == 24

    executions = db.execute(
        select(WorkflowExecution).where(WorkflowExecution.simulation_run_id == run.id)
    ).scalars()
    executions = list(executions)
    assert len(executions) == 24
    assert all(e.status == "completed" for e in executions)
    # Simulated time, not wall time: every case started inside the arrival window.
    assert all(START <= e.started_at <= START + timedelta(hours=8) for e in executions)

    cases = list(
        db.execute(
            select(SimulationCaseResult).where(SimulationCaseResult.run_id == run.id)
        ).scalars()
    )
    assert len(cases) == 24
    for case in cases:
        assert case.path[0] == "receive_application" and case.path[-1] == "complete"
        if case.kind in ("forged_document", "underage", "abandoned_documents"):
            assert case.outcome == "rejected" and case.manual_reviews == 0
        if case.kind == "abandoned_documents":
            assert case.cycle_seconds == 72 * 3600  # the documents wait timed out

    # Simulated staff are labelled, employed in a dedicated team, and cannot sign in.
    staff = list(
        db.execute(select(Employee).where(Employee.organization_id == run.staff_unit_id)).scalars()
    )
    assert len(staff) == 6
    assert all(e.email.startswith(f"sim{run.run_number}.") for e in staff)


def test_same_seed_reproduces_the_same_results(db: Session, session_factory) -> None:
    make_org_tree(db)
    first = _run(db, session_factory, seed=202)
    second = _run(db, session_factory, seed=202)
    other = _run(db, session_factory, seed=203)

    assert first.status == second.status == other.status == SimulationStatus.COMPLETED
    assert first.config_hash == second.config_hash
    assert first.software_version == second.software_version
    assert first.result_digest == second.result_digest
    assert first.results["ground_truth"] == second.results["ground_truth"]
    assert first.results["cycle_time_hours"] == second.results["cycle_time_hours"]
    assert other.result_digest != first.result_digest


def test_run_without_an_organization_structure_fails_with_a_reason(
    db: Session, session_factory
) -> None:
    run = _run(db, session_factory, seed=1, applications=3)
    assert run.status == SimulationStatus.FAILED
    assert "Retail Banking" in run.failure_reason
    assert run.completed_at is not None


def test_simulated_executions_stay_out_of_live_operations(
    db: Session, session_factory, client: TestClient
) -> None:
    make_org_tree(db)
    run = _run(db, session_factory, seed=303, applications=6)
    assert run.status == SimulationStatus.COMPLETED
    headers = auth(make_user(db, RoleCode.PLATFORM_ADMINISTRATOR))

    live = client.get("/api/v1/workflow-executions", headers=headers).json()
    assert all(item["simulation_run_id"] is None for item in live["items"])
    simulated = client.get(
        "/api/v1/workflow-executions",
        params={"simulation_run_id": str(run.id)},
        headers=headers,
    ).json()
    assert simulated["total"] == 6
    # The live timer sweep never touches simulated executions.
    assert engine.run_due(session_factory, now=START + timedelta(days=30)).executions == 0


def test_simulated_staff_cannot_sign_in(db: Session, session_factory, client: TestClient) -> None:
    make_org_tree(db)
    run = _run(db, session_factory, seed=404, applications=2, employees=3)
    username = f"sim{run.run_number}-00000"
    assert db.execute(select(User).where(User.username == username)).scalar_one()
    for password in ("x", "!unusable", "atlas-demo-password"):
        response = client.post(
            "/api/v1/auth/login", json={"username": username, "password": password}
        )
        assert response.status_code == 401


# --- API --------------------------------------------------------------------------------------


@pytest.fixture
def sim_client(app: FastAPI, session_factory) -> TestClient:
    app.dependency_overrides[get_simulation_sessionmaker] = lambda: session_factory
    with TestClient(app) as client:
        yield client


def test_api_starts_a_run_and_reports_results(db: Session, sim_client: TestClient) -> None:
    make_org_tree(db)
    researcher = auth(make_user(db, RoleCode.AI_RESEARCHER))
    response = sim_client.post(
        "/api/v1/simulations",
        json={"profile": "custom", "applications": 8, "employees": 4, "seed": 77},
        headers=researcher,
    )
    assert response.status_code == 202, response.text
    queued = response.json()
    assert queued["status"] == "queued"
    assert queued["config"]["dataset"]["countries"]
    assert queued["software_version"]

    # The test client runs background tasks before returning; the run is finished.
    detail = sim_client.get(f"/api/v1/simulations/{queued['id']}", headers=researcher).json()
    assert detail["status"] == "completed", detail["failure_reason"]
    assert detail["percent_complete"] == 100.0
    assert detail["results"]["completed"] == 8
    assert detail["reproductions"] == []

    cases = sim_client.get(f"/api/v1/simulations/{queued['id']}/cases", headers=researcher).json()
    assert cases["total"] == 8
    assert {"kind", "expected_outcome", "outcome", "matches_ground_truth", "path"} <= set(
        cases["items"][0]
    )

    rerun = sim_client.post(f"/api/v1/simulations/{queued['id']}/rerun", headers=researcher)
    assert rerun.status_code == 202
    again = sim_client.get(f"/api/v1/simulations/{rerun.json()['id']}", headers=researcher).json()
    assert again["seed"] == 77
    assert again["result_digest"] == detail["result_digest"]
    assert again["reproductions"] == [
        {
            "id": queued["id"],
            "run_number": queued["run_number"],
            "result_digest": detail["result_digest"],
            "matches": True,
        }
    ]

    listing = sim_client.get("/api/v1/simulations", headers=researcher).json()
    assert [r["run_number"] for r in listing["items"][:2]] == [
        again["run_number"],
        queued["run_number"],
    ]


def test_api_lists_scenarios_and_profiles(db: Session, client: TestClient) -> None:
    headers = auth(make_user(db, RoleCode.AUDITOR))
    scenarios = client.get("/api/v1/simulations/scenarios", headers=headers).json()
    assert scenarios[0]["scenario_id"] == "retail-onboarding"
    assert scenarios[0]["workflow_id"] == "WF-0001"
    profiles = {
        p["profile_id"]: p
        for p in client.get("/api/v1/simulations/profiles", headers=headers).json()
    }
    assert profiles["small"]["runnable"] is True
    assert profiles["enterprise"]["runnable"] is False


@pytest.mark.parametrize(
    ("body", "status_code", "message"),
    [
        ({"profile": "enterprise"}, 422, "configuration target"),
        ({"profile": "custom", "applications": 5}, 422, "both applications and employees"),
        ({"profile": "small", "applications": 5}, 422, "custom profile"),
        ({"profile": "custom", "applications": 20_000, "employees": 5}, 422, ""),
        ({"scenario_id": "unknown"}, 404, "not registered"),
    ],
)
def test_api_rejects_invalid_runs(
    db: Session, client: TestClient, body: dict, status_code: int, message: str
) -> None:
    headers = auth(make_user(db, RoleCode.AI_RESEARCHER))
    response = client.post("/api/v1/simulations", json=body, headers=headers)
    assert response.status_code == status_code
    assert message in response.text


def test_only_permitted_roles_can_start_runs(db: Session, client: TestClient) -> None:
    for role in (RoleCode.BANKING_EMPLOYEE, RoleCode.AUDITOR, RoleCode.DEPARTMENT_MANAGER):
        headers = auth(make_user(db, role))
        assert client.get("/api/v1/simulations", headers=headers).status_code == 200
        response = client.post("/api/v1/simulations", json={}, headers=headers)
        assert response.status_code == 403
        assert "simulations:run" in response.text


def _queued_run(db: Session, **values) -> SimulationRun:
    user = make_user(db, RoleCode.AI_RESEARCHER)
    run = create_run(
        db, SCENARIO, profile="small", applications=100, employees=25, seed=1, created_by=user.id
    )
    for key, value in values.items():
        setattr(run, key, value)
    db.flush()
    return run


def test_one_run_at_a_time(db: Session, client: TestClient) -> None:
    run = _queued_run(db)
    headers = auth(make_user(db, RoleCode.AI_RESEARCHER))
    response = client.post("/api/v1/simulations", json={"profile": "small"}, headers=headers)
    assert response.status_code == 409
    assert f"#{run.run_number}" in response.json()["error"]["message"]


def test_interrupted_runs_are_reported_as_failed(db: Session, client: TestClient) -> None:
    long_ago = datetime.now(UTC) - timedelta(minutes=30)
    run = _queued_run(db, status="running", started_at=long_ago, heartbeat_at=long_ago)
    headers = auth(make_user(db, RoleCode.AUDITOR))
    detail = client.get(f"/api/v1/simulations/{run.id}", headers=headers).json()
    assert detail["status"] == "failed"
    assert detail["failure_reason"].startswith("Interrupted")


def test_case_counts_match_the_ground_truth_mix(db: Session, session_factory) -> None:
    make_org_tree(db)
    run = _run(db, session_factory, seed=505, applications=30)
    by_kind = run.results["by_kind"]
    stored = dict(
        db.execute(
            select(SimulationCaseResult.kind, func.count())
            .where(SimulationCaseResult.run_id == run.id)
            .group_by(SimulationCaseResult.kind)
        ).all()
    )
    assert {k: v["cases"] for k, v in by_kind.items()} == stored


def test_cli_registers_every_table_on_its_own() -> None:
    # The API imports all models; the CLI runs in its own process and must too, or the
    # workflow → simulation foreign key cannot be resolved when the seed writes executions.
    import subprocess
    import sys

    code = "import app.cli; from app.core.database import Base; Base.metadata.sorted_tables"
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
