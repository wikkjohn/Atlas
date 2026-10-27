from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.core.database import get_engine


def test_health_reports_ok_when_database_is_reachable(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["components"]["application"]["status"] == "ok"
    database = body["components"]["database"]
    assert database["status"] == "ok"
    assert database["critical"] is True
    assert database["latency_ms"] >= 0
    assert database["error"] is None
    assert body["components"]["redis"]["status"] == "disabled"


def test_health_returns_503_when_database_is_unreachable(
    app, client: TestClient, unreachable_engine
) -> None:
    app.dependency_overrides[get_engine] = lambda: unreachable_engine

    response = client.get("/api/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["components"]["database"]["status"] == "unavailable"
    assert body["components"]["database"]["error"]
    assert body["components"]["application"]["status"] == "ok"


def test_unreachable_redis_degrades_but_does_not_fail_health(app, client: TestClient) -> None:
    settings = Settings(redis_url="redis://127.0.0.1:1/0")
    app.dependency_overrides[get_settings] = lambda: settings

    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["components"]["redis"]["status"] == "unavailable"
    assert body["components"]["redis"]["critical"] is False
