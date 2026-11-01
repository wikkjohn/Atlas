"""Top-level API routing.

Platform endpoints live directly under `/api` (health checks must stay stable for
infrastructure probes). Business modules are mounted under the versioned `/api/v1` prefix
as they are implemented.
"""

from fastapi import APIRouter

from app.api import system
from app.jobs import handlers  # noqa: F401  (registers the job kinds)
from app.jobs.router import jobs_router, schedules_router
from app.modules.accounts.router import accounts_router, requests_router
from app.modules.ai_tools.router import router as ai_tools_router
from app.modules.analytics.router import router as analytics_router
from app.modules.audit.router import router as audit_router
from app.modules.cards.router import router as cards_router
from app.modules.clearing.router import router as clearing_router
from app.modules.commercial.router import router as commercial_router
from app.modules.countries.router import currencies_router
from app.modules.countries.router import router as countries_router
from app.modules.customers.router import router as customers_router
from app.modules.employees.router import router as employees_router
from app.modules.experiments.router import benchmarks_router, experiments_router
from app.modules.fx.router import router as fx_router
from app.modules.identity.router import auth_router, roles_router, users_router
from app.modules.ledger.router import router as ledger_router
from app.modules.lending.router import router as loans_router
from app.modules.mortgages.router import router as mortgages_router
from app.modules.organizations.router import router as organizations_router
from app.modules.payments.router import router as payments_router
from app.modules.retail.router import router as retail_router
from app.modules.rules.router import router as rules_router
from app.modules.trade.router import router as trade_router
from app.modules.treasury.router import router as treasury_router
from app.modules.wealth.router import router as wealth_router
from app.modules.workflows import catalog  # noqa: F401  (registers every workflow)
from app.modules.workflows.router import (
    authoring_router,
    catalogue_router,
    definitions_router,
    executions_router,
    tasks_router,
    templates_router,
)
from app.observability.router import metrics_router
from app.observability.router import router as observability_router
from app.simulation.router import router as simulations_router

api_router = APIRouter(prefix="/api")
api_router.include_router(system.router)
api_router.include_router(metrics_router)

v1_router = APIRouter(prefix="/api/v1")
for module_router in (
    auth_router,
    users_router,
    roles_router,
    countries_router,
    currencies_router,
    rules_router,
    organizations_router,
    employees_router,
    customers_router,
    requests_router,
    accounts_router,
    ledger_router,
    fx_router,
    payments_router,
    retail_router,
    cards_router,
    mortgages_router,
    commercial_router,
    trade_router,
    clearing_router,
    treasury_router,
    wealth_router,
    loans_router,
    definitions_router,
    authoring_router,
    templates_router,
    catalogue_router,
    executions_router,
    tasks_router,
    simulations_router,
    ai_tools_router,
    experiments_router,
    benchmarks_router,
    analytics_router,
    audit_router,
    jobs_router,
    schedules_router,
    observability_router,
):
    v1_router.include_router(module_router)
