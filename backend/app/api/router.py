"""Top-level API routing.

Platform endpoints live directly under `/api` (health checks must stay stable for
infrastructure probes). Business modules are mounted under the versioned `/api/v1` prefix
as they are implemented.
"""

from fastapi import APIRouter

from app.api import system
from app.modules.audit.router import router as audit_router
from app.modules.countries.router import router as countries_router
from app.modules.employees.router import router as employees_router
from app.modules.identity.router import auth_router, roles_router, users_router
from app.modules.organizations.router import router as organizations_router

api_router = APIRouter(prefix="/api")
api_router.include_router(system.router)

v1_router = APIRouter(prefix="/api/v1")
for module_router in (
    auth_router,
    users_router,
    roles_router,
    countries_router,
    organizations_router,
    employees_router,
    audit_router,
):
    v1_router.include_router(module_router)
