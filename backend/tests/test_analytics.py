"""Phase 8: dashboard analytics and System Settings user management."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from app.core.permissions import SERVICE_ROLES, RoleCode
from app.modules.ai_tools.schemas import ToolCreate
from app.modules.ai_tools.service import register_tool
from app.modules.experiments.assumptions import CostAssumptions
from app.modules.experiments.evaluation import costs
from app.modules.experiments.measurements import measure
from app.modules.identity.models import User
from app.modules.workflows.wf0001 import POLICY_ENGINE_USERNAME
from app.seed import DEMO_AI_TOOLS
from app.simulation.models import SimulationRun
from app.simulation.router import get_simulation_sessionmaker
from tests.factories import auth, make_employee, make_org_tree, make_user

REQUIRED = {
    "employees",
    "countries",
    "workflows",
    "active_simulations",
    "completed_executions",
    "failed_executions",
    "accounts",
    "ai_tools",
    "experiments",
    "avg_process_duration",
    "simulation_cost",
}


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


def _metrics(client: TestClient, headers: dict) -> dict:
    response = client.get("/api/v1/analytics/overview", headers=headers)
    assert response.status_code == 200, response.text
    return {m["key"]: m for m in response.json()["metrics"]}


def test_overview_reports_every_required_metric(client: TestClient, db: Session) -> None:
    headers = auth(make_user(db, RoleCode.AUDITOR))
    metrics = _metrics(client, headers)
    assert set(metrics) == REQUIRED
    assert all(m["detail"] for m in metrics.values())
    # Only the cost is an estimate; it says so.
    assert [k for k, m in metrics.items() if m["estimate"]] == ["simulation_cost"]
    assert metrics["countries"]["value"] == 5  # the five seeded by migration
    assert metrics["workflows"]["value"] == 4  # WF-0001 and WF-0003 have two versions each
    assert "6 definition version" in metrics["workflows"]["detail"]


def test_overview_counts_follow_the_records(api: TestClient, db: Session) -> None:
    tree = make_org_tree(db)
    make_employee(db, tree.us_onboarding)
    register_tool(db, ToolCreate.model_validate(DEMO_AI_TOOLS[0]), actor_id=None)
    headers = auth(make_user(db, RoleCode.AI_RESEARCHER))
    before = _metrics(api, headers)
    assert before["employees"]["value"] == 1
    assert before["ai_tools"]["value"] == 1

    response = api.post(
        "/api/v1/experiments",
        json={
            "name": "Dashboard check",
            "tool_id": "agb-intelligent-kyc-assistant",
            "candidate_mode": "ai_automated",
            "profile": "custom",
            "applications": 12,
            "employees": 4,
            "seed": 3,
        },
        headers=headers,
    )
    assert response.status_code == 202
    after = _metrics(api, headers)
    assert after["employees"]["value"] == 1 + 2 * 4  # two runs hired 4 simulated staff each
    assert "8 simulated staff" in after["employees"]["detail"]
    assert after["experiments"]["value"] == 1
    assert after["active_simulations"]["value"] == 0
    assert after["avg_process_duration"]["value"] is not None
    assert after["accounts"]["value"] > before["accounts"]["value"]
    assert "plus 24 simulated" in after["completed_executions"]["detail"]

    # The dashboard estimate uses the experiment engine's cost function on the same records.
    runs = db.execute(select(SimulationRun)).scalars().all()
    expected = sum(costs(measure(db, run), CostAssumptions())["operating_total"] for run in runs)
    assert after["simulation_cost"]["value"] == pytest.approx(expected, abs=0.01)

    overview = api.get("/api/v1/analytics/overview", headers=headers).json()
    assert [r["mode"] for r in overview["recent_runs"]] == ["ai_automated", "baseline"]
    assert overview["recent_experiments"][0]["verdict"] in ("successful", "not_successful")


def test_every_role_can_read_the_dashboard(client: TestClient, db: Session) -> None:
    for role in RoleCode:
        if role in SERVICE_ROLES:  # system principals cannot sign in
            continue
        headers = auth(make_user(db, role))
        assert client.get("/api/v1/analytics/overview", headers=headers).status_code == 200


def test_users_can_be_filtered_into_people_and_service_accounts(
    client: TestClient, db: Session
) -> None:
    headers = auth(make_user(db, RoleCode.PLATFORM_ADMINISTRATOR, username="settings-admin"))
    service = client.get("/api/v1/users", params={"kind": "service"}, headers=headers).json()
    assert [u["username"] for u in service["items"]] == [POLICY_ENGINE_USERNAME, "atlas-scheduler"]
    assert service["items"][0]["is_service_account"] is True
    people = client.get("/api/v1/users", params={"kind": "people"}, headers=headers).json()
    assert POLICY_ENGINE_USERNAME not in {u["username"] for u in people["items"]}
    found = client.get("/api/v1/users", params={"q": "settings"}, headers=headers).json()
    assert [u["username"] for u in found["items"]] == ["settings-admin"]


def test_service_accounts_keep_their_role_but_can_be_switched_off(
    client: TestClient, db: Session
) -> None:
    headers = auth(make_user(db, RoleCode.PLATFORM_ADMINISTRATOR))
    engine = db.execute(select(User).where(User.username == POLICY_ENGINE_USERNAME)).scalar_one()
    response = client.patch(
        f"/api/v1/users/{engine.id}", json={"role": "department_manager"}, headers=headers
    )
    assert response.status_code == 422
    assert "Service accounts keep their role" in response.text
    off = client.patch(f"/api/v1/users/{engine.id}", json={"is_active": False}, headers=headers)
    assert off.status_code == 200 and off.json()["is_active"] is False
