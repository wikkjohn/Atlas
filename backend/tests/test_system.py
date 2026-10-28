from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient

from app import __version__
from app.core.database import get_engine
from app.core.system import alembic_config
from app.modules import MODULE_REGISTRY
from tests.conftest import migrate


def test_system_info_describes_platform_and_module_roadmap(client: TestClient) -> None:
    response = client.get("/api/system/info")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "ATLAS Global Bank"
    assert body["version"] == __version__
    assert body["environment"] == "test"
    assert body["api_versions"] == ["v1"]
    assert body["uptime_seconds"] >= 0
    assert "Synthetic" in body["data_policy"]

    # The endpoint publishes the registry exactly, in order.
    assert body["modules"] == [m.as_dict() for m in MODULE_REGISTRY]
    statuses = {m["key"]: m["status"] for m in body["modules"]}
    assert statuses["platform"] == "available"
    assert set(statuses.values()) <= {"available", "planned"}


def test_system_status_is_operational_after_migrations(client: TestClient) -> None:
    response = client.get("/api/system/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "operational"
    database = body["database"]
    assert database["connected"] is True
    assert database["database_name"] == "atlas_test"
    assert database["server_version"]
    assert database["table_count"] >= 2
    assert database["initialized_at"].endswith("Z")
    heads = sorted(ScriptDirectory.from_config(alembic_config()).get_heads())
    assert database["migrations"] == {
        "current_revisions": heads,
        "head_revisions": heads,
        "up_to_date": True,
    }


def test_system_status_reports_pending_migrations(client: TestClient) -> None:
    migrate("base")
    try:
        response = client.get("/api/system/status")
    finally:
        migrate("head")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "needs_migration"
    assert body["database"]["connected"] is True
    assert body["database"]["migrations"]["current_revisions"] == []
    assert body["database"]["migrations"]["up_to_date"] is False
    assert body["database"]["initialized_at"] is None


def test_system_status_reports_unavailable_database(
    app, client: TestClient, unreachable_engine
) -> None:
    app.dependency_overrides[get_engine] = lambda: unreachable_engine

    response = client.get("/api/system/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["database"]["connected"] is False
    assert body["database"]["error"]
    assert body["database"]["migrations"] is None


def test_openapi_document_lists_system_endpoints(client: TestClient) -> None:
    response = client.get("/api/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert {"/api/health", "/api/system/info", "/api/system/status"} <= set(paths)
