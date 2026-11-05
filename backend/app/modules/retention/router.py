"""Data-retention review and application (Phase 85)."""

from typing import Any

from fastapi import APIRouter

from app.core.dependencies import DbSession
from app.core.permissions import Permission
from app.modules.identity.dependencies import Authorized
from app.modules.retention import service

router = APIRouter(prefix="/data-retention", tags=["audit"])


@router.get("", summary="The retention schedule and what is past its period")
def review(db: DbSession, _: Authorized(Permission.AUDIT_READ)) -> dict[str, Any]:
    return service.review(db)


@router.post("/apply", summary="Delete and archive what is past its period")
def apply(db: DbSession, actor: Authorized(Permission.RETENTION_APPLY)) -> dict[str, Any]:
    run = service.apply(db, actor.id)
    return {"run_number": run.run_number, "applied_at": run.applied_at.isoformat(),
            "results": run.results}  # fmt: skip
