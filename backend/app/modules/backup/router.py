"""The backup and recovery-drill record (Phase 87): read only.

Backups, restores and drills are taken by the operator with `python -m app.cli backup`,
on a host with the PostgreSQL client tools; the API only reports them.
"""

from typing import Any

from fastapi import APIRouter, Query

from app.core.dependencies import DbSession
from app.core.permissions import Permission
from app.modules.backup import service
from app.modules.identity.dependencies import Authorized

router = APIRouter(prefix="/backups", tags=["audit"])


@router.get("", summary="The latest backup and drill, and every recorded run")
def list_runs(
    db: DbSession,
    _: Authorized(Permission.AUDIT_READ),
    kind: str | None = Query(default=None, pattern="^(backup|verify|restore|drill)$"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    return {
        **service.status(db),
        "runs": [service.serialize(run) for run in service.runs(db, kind=kind, limit=limit)],
    }
