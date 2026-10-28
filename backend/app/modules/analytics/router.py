from fastapi import APIRouter

from app.core.dependencies import DbSession
from app.core.permissions import Permission
from app.modules.analytics import service
from app.modules.analytics.schemas import Overview
from app.modules.identity.dependencies import Authorized

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview", response_model=Overview, summary="Enterprise dashboard metrics")
def get_overview(db: DbSession, _: Authorized(Permission.ANALYTICS_READ)) -> Overview:
    return service.overview(db)
