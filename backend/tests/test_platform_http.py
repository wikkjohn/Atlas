"""Cross-cutting HTTP behaviour: correlation IDs, CORS and the error envelope."""

import uuid

from fastapi.testclient import TestClient


def test_correlation_id_is_generated_when_absent(client: TestClient) -> None:
    response = client.get("/api/system/info")

    uuid.UUID(response.headers["X-Correlation-ID"])


def test_valid_correlation_id_is_propagated(client: TestClient) -> None:
    response = client.get("/api/system/info", headers={"X-Correlation-ID": "demo-run:42"})

    assert response.headers["X-Correlation-ID"] == "demo-run:42"


def test_unsafe_correlation_id_is_replaced(client: TestClient) -> None:
    response = client.get("/api/system/info", headers={"X-Correlation-ID": "bad id\nwith newline"})

    uuid.UUID(response.headers["X-Correlation-ID"])


def test_cors_allows_the_local_frontend(client: TestClient) -> None:
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_rejects_unknown_origins(client: TestClient) -> None:
    response = client.options(
        "/api/health",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )

    assert "access-control-allow-origin" not in response.headers


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/api/does-not-exist", headers={"X-Correlation-ID": "trace-404"})

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "Not Found",
            "details": None,
            "correlation_id": "trace-404",
        }
    }


def test_validation_errors_use_error_envelope(app, client: TestClient) -> None:
    @app.get("/api/_test/validated")
    def validated(limit: int) -> dict[str, int]:
        return {"limit": limit}

    response = client.get("/api/_test/validated", params={"limit": "many"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["location"] == ["query", "limit"]
    assert error["correlation_id"]


def test_unhandled_errors_return_500_without_leaking_details(app) -> None:
    @app.get("/api/_test/boom")
    def boom() -> None:
        raise RuntimeError("secret internal detail")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/_test/boom", headers={"X-Correlation-ID": "trace-500"})

    assert response.status_code == 500
    assert response.headers["X-Correlation-ID"] == "trace-500"
    assert response.json()["error"] == {
        "code": "internal_error",
        "message": "An unexpected error occurred.",
        "details": None,
        "correlation_id": "trace-500",
    }
