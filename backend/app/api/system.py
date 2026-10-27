"""Platform health, information and status endpoints."""

import platform
import time
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from app import __version__
from app.core.cache import check_redis
from app.core.database import check_database
from app.core.dependencies import EngineDep, SettingsDep
from app.core.system import database_details, migration_state
from app.modules import MODULE_REGISTRY

router = APIRouter(tags=["system"])

STARTED_AT = datetime.now(UTC)
_STARTED_MONOTONIC = time.monotonic()


def _uptime_seconds() -> float:
    return round(time.monotonic() - _STARTED_MONOTONIC, 1)


class ComponentHealth(BaseModel):
    status: Literal["ok", "unavailable", "disabled"]
    critical: bool
    latency_ms: float | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "unavailable"]
    timestamp: datetime
    components: dict[str, ComponentHealth]


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness and dependency health",
    responses={503: {"model": HealthResponse, "description": "A critical dependency is down."}},
)
def health(
    response: Response,
    engine: EngineDep,
    settings: SettingsDep,
) -> HealthResponse:
    """Returns 200 when the application and database are healthy, 503 otherwise.

    Redis is optional in Phase 1: when configured but unreachable the platform is
    reported as `degraded` (HTTP 200) because no feature depends on it yet.
    """
    db = check_database(engine)
    redis = check_redis(settings.redis_url)
    components = {
        "application": ComponentHealth(status="ok", critical=True),
        "database": ComponentHealth(
            status="ok" if db.ok else "unavailable",
            critical=True,
            latency_ms=db.latency_ms,
            error=db.error,
        ),
        "redis": ComponentHealth(status=redis.status, critical=False, error=redis.error),
    }
    if any(c.critical and c.status != "ok" for c in components.values()):
        overall = "unavailable"
        response.status_code = 503
    elif any(c.status == "unavailable" for c in components.values()):
        overall = "degraded"
    else:
        overall = "ok"
    return HealthResponse(status=overall, timestamp=datetime.now(UTC), components=components)


class ModuleOut(BaseModel):
    key: str
    name: str
    phase: int
    status: Literal["available", "planned"]
    description: str


class SystemInfoResponse(BaseModel):
    name: str
    version: str
    environment: str
    build_sha: str | None
    api_versions: list[str]
    python_version: str
    started_at: datetime
    uptime_seconds: float
    data_policy: str
    modules: list[ModuleOut]


@router.get("/system/info", response_model=SystemInfoResponse, summary="Platform information")
def system_info(settings: SettingsDep) -> SystemInfoResponse:
    return SystemInfoResponse(
        name=settings.app_name,
        version=__version__,
        environment=settings.environment,
        build_sha=settings.build_sha,
        api_versions=["v1"],
        python_version=platform.python_version(),
        started_at=STARTED_AT,
        uptime_seconds=_uptime_seconds(),
        data_policy=(
            "Synthetic simulation only. No real customers, accounts, payment networks or "
            "financial institutions are connected."
        ),
        modules=[ModuleOut(**m.as_dict()) for m in MODULE_REGISTRY],
    )


class MigrationStatus(BaseModel):
    current_revisions: list[str]
    head_revisions: list[str]
    up_to_date: bool


class DatabaseStatus(BaseModel):
    connected: bool
    latency_ms: float | None = None
    error: str | None = None
    server_version: str | None = None
    database_name: str | None = None
    table_count: int | None = None
    migrations: MigrationStatus | None = None
    initialized_at: str | None = None


class SystemStatusResponse(BaseModel):
    status: Literal["operational", "needs_migration", "unavailable"]
    timestamp: datetime
    uptime_seconds: float
    database: DatabaseStatus
    redis: ComponentHealth


@router.get(
    "/system/status", response_model=SystemStatusResponse, summary="Detailed operational status"
)
def system_status(
    engine: EngineDep,
    settings: SettingsDep,
) -> SystemStatusResponse:
    """Detailed status for operators. Always HTTP 200; inspect `status` for the verdict."""
    db = check_database(engine)
    database = DatabaseStatus(connected=db.ok, latency_ms=db.latency_ms, error=db.error)
    if db.ok:
        try:
            details = database_details(engine)
            migrations = migration_state(engine)
        except SQLAlchemyError as exc:
            database.connected = False
            database.error = str(exc).splitlines()[0]
        else:
            database.server_version = details.server_version
            database.database_name = details.database_name
            database.table_count = details.table_count
            database.initialized_at = details.properties.get("platform.initialized_at")
            database.migrations = MigrationStatus(
                current_revisions=migrations.current_revisions,
                head_revisions=migrations.head_revisions,
                up_to_date=migrations.up_to_date,
            )

    if not database.connected:
        overall = "unavailable"
    elif database.migrations and not database.migrations.up_to_date:
        overall = "needs_migration"
    else:
        overall = "operational"

    redis = check_redis(settings.redis_url)
    return SystemStatusResponse(
        status=overall,
        timestamp=datetime.now(UTC),
        uptime_seconds=_uptime_seconds(),
        database=database,
        redis=ComponentHealth(status=redis.status, critical=False, error=redis.error),
    )
