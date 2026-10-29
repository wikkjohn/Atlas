import hmac
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app.config import get_settings
from app.core.dependencies import DbSession
from app.core.errors import NotFoundError
from app.core.permissions import Permission
from app.modules.identity.dependencies import Authorized
from app.observability import service

router = APIRouter(prefix="/observability", tags=["observability"])
metrics_router = APIRouter(tags=["observability"])


class RouteMetrics(BaseModel):
    method: str
    route: str
    count: int
    errors: int
    by_status: dict[str, int]
    avg_ms: float
    p50_ms: float | None
    p95_ms: float | None
    max_ms: float


class KindThroughput(BaseModel):
    kind: str
    finished: int
    succeeded: int
    failed: int
    per_minute: float
    avg_ms: float | None
    p95_ms: float | None
    max_ms: float | None


class WorkerOut(BaseModel):
    name: str
    hostname: str
    pid: int
    state: str  # running, lost (stopped reporting) or stopped
    started_at: datetime
    last_seen_at: datetime
    stopped_at: datetime | None
    succeeded: int
    failed: int
    retried: int
    current_job_kind: str | None


class Overview(BaseModel):
    process: dict[str, Any]
    requests: list[RouteMetrics]
    queue: dict[str, Any]
    throughput: list[KindThroughput]
    workers: list[WorkerOut]
    database: dict[str, Any]


class SlowQueryOut(BaseModel):
    statement: str
    context: str | None
    # One slow execution...
    occurred_at: datetime | None = None
    duration_ms: int | None = None
    source: str | None = None
    correlation_id: str | None = None
    # ...or a group of them (grouped=true).
    count: int | None = None
    avg_ms: float | None = None
    max_ms: int | None = None
    total_ms: int | None = None
    last_seen: datetime | None = None


@router.get(
    "/overview",
    response_model=Overview,
    summary="Requests (this API process), job queue and throughput, workers, database",
)
def overview(db: DbSession, _: Authorized(Permission.OBSERVABILITY_READ)) -> Overview:
    return Overview.model_validate(service.overview(db))


@router.get(
    "/slow-queries",
    response_model=list[SlowQueryOut],
    summary="Statements slower than the threshold, newest first (or grouped by total time)",
)
def slow_queries(
    db: DbSession,
    _: Authorized(Permission.OBSERVABILITY_READ),
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    grouped: bool = False,
) -> list[SlowQueryOut]:
    return [
        SlowQueryOut.model_validate(r)
        for r in service.slow_queries(db, limit=limit, grouped=grouped)
    ]


@metrics_router.get(
    "/metrics",
    response_class=PlainTextResponse,
    summary="Prometheus metrics (needs ATLAS_METRICS_TOKEN as a bearer token)",
)
def prometheus(
    db: DbSession, authorization: Annotated[str | None, Header()] = None
) -> PlainTextResponse:
    token = get_settings().metrics_token
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    # Without a configured token the endpoint does not exist; a wrong token looks the same.
    # Bytes, not str: compare_digest refuses non-ASCII text (a header may carry any).
    if token is None or not hmac.compare_digest(
        supplied.encode(), token.get_secret_value().encode()
    ):
        raise NotFoundError("Not found.")
    return PlainTextResponse(service.prometheus(db), media_type="text/plain; version=0.0.4")
