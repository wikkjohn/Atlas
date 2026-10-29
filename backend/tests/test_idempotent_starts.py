"""Starting simulations and experiments is safe to retry with an Idempotency-Key."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Connection, func, select
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.ai_tools.schemas import ToolCreate
from app.modules.ai_tools.service import register_tool
from app.modules.experiments.models import Experiment
from app.seed import DEMO_AI_TOOLS
from app.simulation.models import SimulationRun
from app.simulation.router import get_simulation_sessionmaker
from tests.factories import auth, make_org_tree, make_user

RUN = {"profile": "custom", "applications": 4, "employees": 3, "seed": 5}


@pytest.fixture
def api(app: FastAPI, db_connection: Connection) -> TestClient:
    def factory() -> Session:
        return Session(
            bind=db_connection,
            join_transaction_mode="create_savepoint",
            autoflush=False,
            expire_on_commit=False,
        )

    app.dependency_overrides[get_simulation_sessionmaker] = lambda: factory
    with TestClient(app) as client:
        yield client


def _count(db: Session, model) -> int:
    return db.execute(select(func.count()).select_from(model)).scalar_one()


def test_retried_simulation_start_replays_instead_of_running_again(
    api: TestClient, db: Session
) -> None:
    make_org_tree(db)
    headers = {**auth(make_user(db, RoleCode.AI_RESEARCHER)), "Idempotency-Key": "run-1"}

    first = api.post("/api/v1/simulations", json=RUN, headers=headers)
    # The first run has finished, so without the key a second start would be accepted.
    again = api.post("/api/v1/simulations", json=RUN, headers=headers)

    assert first.status_code == again.status_code == 202
    assert again.json()["id"] == first.json()["id"]
    assert again.headers["Idempotent-Replayed"] == "true"
    assert _count(db, SimulationRun) == 1
    other = api.post("/api/v1/simulations", json={**RUN, "seed": 6}, headers=headers)
    assert other.status_code == 409  # the key belongs to a different request


def test_retried_suite_and_rerun_start_nothing_new(api: TestClient, db: Session) -> None:
    make_org_tree(db)
    register_tool(db, ToolCreate.model_validate(DEMO_AI_TOOLS[0]), actor_id=None)
    user = auth(make_user(db, RoleCode.AI_RESEARCHER))
    suite = {
        **RUN,
        "tool_id": "agb-intelligent-kyc-assistant",
        "modes": ["baseline", "ai_assisted"],
    }

    first = api.post(
        "/api/v1/simulations/suites", json=suite, headers={**user, "Idempotency-Key": "s"}
    )
    again = api.post(
        "/api/v1/simulations/suites", json=suite, headers={**user, "Idempotency-Key": "s"}
    )
    assert [r["id"] for r in again.json()] == [r["id"] for r in first.json()]
    assert _count(db, SimulationRun) == 2

    path = f"/api/v1/simulations/{first.json()[0]['id']}/rerun"
    rerun = api.post(path, headers={**user, "Idempotency-Key": "r"})
    assert (
        api.post(path, headers={**user, "Idempotency-Key": "r"}).json()["id"] == rerun.json()["id"]
    )
    assert _count(db, SimulationRun) == 3


def test_retried_experiment_start_creates_one_experiment(api: TestClient, db: Session) -> None:
    make_org_tree(db)
    register_tool(db, ToolCreate.model_validate(DEMO_AI_TOOLS[0]), actor_id=None)
    headers = {**auth(make_user(db, RoleCode.AI_RESEARCHER)), "Idempotency-Key": "exp-1"}
    body = {
        "name": "Retry safety",
        "tool_id": "agb-intelligent-kyc-assistant",
        "candidate_mode": "ai_assisted",
        **RUN,
    }

    first = api.post("/api/v1/experiments", json=body, headers=headers)
    again = api.post("/api/v1/experiments", json=body, headers=headers)

    assert first.status_code == again.status_code == 202
    assert again.json()["id"] == first.json()["id"]
    assert _count(db, Experiment) == 1
    assert _count(db, SimulationRun) == 2
