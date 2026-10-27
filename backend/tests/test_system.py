from fastapi.testclient import TestClient

from app import __version__
from app.core.database import get_engine
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

    modules = {m["key"]: m for m in body["modules"]}
    assert len(modules) == len(MODULE_REGISTRY)
    assert modules["platform"]["status"] == "available"
    assert modules["ledger"] == {
        "key": "ledger",
        "name": "Ledger",
        "phase": 3,
        "status": "planned",
        "description": modules["ledger"]["description"],
    }


def test_system_status_is_operational_after_migrations(client: TestClient) -> None:
    response = client.get("/api/system/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "operational"
    database = body["database"]
    assert database["connected"] is True
    assert database["database_name"] == "atlas_test"
    assert database["server_version"]
    # alembic_version + system_properties
    assert database["table_count"] >= 2
    assert database["initialized_at"].endswith("Z")
    assert database["migrations"] == {
        "current_revisions": ["0001_platform_baseline"],
        "head_revisions": ["0001_platform_baseline"],
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
