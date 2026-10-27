"""Top-level API routing.

Platform endpoints live directly under `/api` (health checks must stay stable for
infrastructure probes). Business modules are mounted under the versioned `/api/v1` prefix
as they are implemented.
"""

from fastapi import APIRouter

from app.api import system

api_router = APIRouter(prefix="/api")
api_router.include_router(system.router)

v1_router = APIRouter(prefix="/api/v1")
# Phase 2+ module routers are included here, e.g. v1_router.include_router(organizations.router)
