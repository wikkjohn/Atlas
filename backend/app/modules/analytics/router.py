from typing import Any

from fastapi import APIRouter, Query

from app.core.dependencies import DbSession
from app.core.permissions import Permission
from app.modules.analytics import drilldown, service
from app.modules.analytics.schemas import Overview
from app.modules.identity.dependencies import Authorized

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview", response_model=Overview, summary="Enterprise dashboard metrics")
def get_overview(db: DbSession, _: Authorized(Permission.ANALYTICS_READ)) -> Overview:
    return service.overview(db)


@router.get(
    "/drilldown",
    summary="Workflow executions by country, department and workflow (Phase 88)",
)
def get_drilldown(
    db: DbSession,
    actor: Authorized(Permission.ANALYTICS_READ),
    country: str | None = Query(default=None, pattern="^([A-Z]{2}|none)$"),
    department: str | None = Query(default=None, min_length=1, max_length=100),
    workflow_id: str | None = Query(default=None, min_length=1, max_length=20),
    realm: str = Query(default="all", pattern="^(all|live|simulation)$"),
    days: int | None = Query(default=None, ge=1, le=3650),
) -> dict[str, Any]:
    """One place in the hierarchy (`country`, then `department`, then `workflow_id`; `none`
    selects the unattributed group) and its breakdown one level down. A scoped user sees
    only executions inside the scope."""
    path = drilldown.Path(country=country, department=department, workflow_id=workflow_id)
    return drilldown.drilldown(db, path, realm=realm, days=days, scope=actor.scope)
