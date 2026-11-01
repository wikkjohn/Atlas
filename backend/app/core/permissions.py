"""Roles and the permissions each one grants.

Permissions are defined in code (and so versioned with the software). The `roles` table
stores each role's identity; this module is the single source of truth for what a role
may do. Every protected endpoint checks a permission on the server.
"""

from enum import StrEnum


class Permission(StrEnum):
    COUNTRIES_READ = "countries:read"
    COUNTRIES_MANAGE = "countries:manage"
    ORGANIZATIONS_READ = "organizations:read"
    ORGANIZATIONS_MANAGE = "organizations:manage"
    EMPLOYEES_READ = "employees:read"
    EMPLOYEES_MANAGE = "employees:manage"
    EMPLOYEES_READ_COMPENSATION = "employees:read_compensation"
    USERS_READ = "users:read"
    USERS_MANAGE = "users:manage"
    AUDIT_READ = "audit:read"
    CUSTOMERS_READ = "customers:read"
    CUSTOMERS_MANAGE = "customers:manage"  # create customers, edit their details
    CUSTOMERS_REVIEW = "customers:review"  # KYC status and risk rating decisions
    ACCOUNTS_READ = "accounts:read"
    ACCOUNTS_REQUEST = "accounts:request"  # submit an account-opening request
    ACCOUNTS_APPROVE = "accounts:approve"  # approve/reject requests (never one's own)
    # Approve requests of LOW-risk customers only (held by the automated policy engine).
    ACCOUNTS_APPROVE_LOW_RISK = "accounts:approve_low_risk"
    ACCOUNTS_TRANSACT = "accounts:transact"  # synthetic deposits and withdrawals
    ACCOUNTS_MANAGE = "accounts:manage"  # freeze, unfreeze, close
    LEDGER_READ = "ledger:read"
    LEDGER_POST = "ledger:post"  # manual journal entries and reversals
    FX_MANAGE = "fx:manage"  # revalue currency positions (Phase 24)
    # Retail products, overdraft limits and month-end interest, fees and statements (Phase 29)
    RETAIL_MANAGE = "retail:manage"
    # Card blocks and their release, dispute decisions (Phase 31)
    CARDS_MANAGE = "cards:manage"
    # Mortgage product terms and surveyor valuations (Phase 33)
    MORTGAGES_MANAGE = "mortgages:manage"
    # Trade finance: pay or reject documents and claims, close expired instruments (Phase 37)
    TRADE_MANAGE = "trade:manage"
    # Treasury (Phase 39): book money-market deals and FX desk trades; confirm and settle
    # them in back office (never one's own); set counterparty and position limits.
    TREASURY_DEAL = "treasury:deal"
    TREASURY_CONFIRM = "treasury:confirm"
    TREASURY_LIMITS = "treasury:limits"
    # Wealth (Phase 43): suitability assessments, portfolios and orders; approve unsuitable
    # orders (never one's own); pay income to holders in custody.
    WEALTH_ADVISE = "wealth:advise"
    WEALTH_APPROVE = "wealth:approve"
    WEALTH_CUSTODY = "wealth:custody"
    # Compliance (Phase 45): read alerts, cases and reports; run monitoring, investigate and
    # review KYC; file suspicious activity reports (never one's own).
    COMPLIANCE_READ = "compliance:read"
    COMPLIANCE_MONITOR = "compliance:monitor"
    COMPLIANCE_FILE = "compliance:file"
    # Risk (Phase 47): read ratings, limits and provisions; rate obligors and calculate
    # provisions; approve departing ratings, set limits and post provisions (never one's own).
    RISK_READ = "risk:read"
    RISK_RATE = "risk:rate"
    RISK_APPROVE = "risk:approve"
    WORKFLOWS_READ = "workflows:read"
    WORKFLOWS_START = "workflows:start"  # start executions, deliver signals (e.g. documents)
    WORKFLOWS_MANAGE = "workflows:manage"  # resume or cancel executions
    # Import, retire and reactivate stored workflow definitions.
    WORKFLOWS_DEFINE = "workflows:define"
    SIMULATIONS_READ = "simulations:read"
    SIMULATIONS_RUN = "simulations:run"  # start simulation runs (creates synthetic data)
    # Archive and restore simulation runs' workflow history.
    SIMULATIONS_MANAGE = "simulations:manage"
    AI_TOOLS_READ = "ai_tools:read"
    AI_TOOLS_MANAGE = "ai_tools:manage"  # register tools and versions, enable/disable
    AI_TOOLS_INVOKE = "ai_tools:invoke"  # call a tool directly (test console)
    EXPERIMENTS_READ = "experiments:read"  # experiments, evaluations, benchmarks, reports
    EXPERIMENTS_RUN = "experiments:run"  # start and evaluate experiments
    ANALYTICS_READ = "analytics:read"  # enterprise dashboard metrics
    PAYMENTS_READ = "payments:read"
    PAYMENTS_REVIEW = "payments:review"  # decide payments held by fraud screening
    PAYMENTS_APPROVE = "payments:approve"  # release high-value payments (never one's own)
    # Release flagged payments within the low-risk policy only (the automated policy engine).
    PAYMENTS_RELEASE_LOW_RISK = "payments:release_low_risk"
    # Payments operations (Phase 41): run external clearing cycles, record recall answers.
    PAYMENTS_OPERATE = "payments:operate"
    LOANS_READ = "loans:read"
    LOANS_APPROVE = "loans:approve"  # underwriting decisions (never one's own application)
    LOANS_APPROVE_LARGE = "loans:approve_large"  # credit committee: large loans, write-offs
    # Policy engine: underwrite small, clean loans the AI assistant rates low risk.
    LOANS_APPROVE_LOW_RISK = "loans:approve_low_risk"
    LOANS_REPAY = "loans:repay"  # record a borrower's arrears repayment or early payoff
    LOANS_SERVICE = "loans:service"  # run loan servicing (moves the lending business date)
    JOBS_READ = "jobs:read"  # background jobs and their schedules
    JOBS_MANAGE = "jobs:manage"  # queue jobs, change schedules
    # Request and job metrics, worker processes, the slow-query log, storage use.
    OBSERVABILITY_READ = "observability:read"


class RoleCode(StrEnum):
    PLATFORM_ADMINISTRATOR = "platform_administrator"
    GLOBAL_EXECUTIVE = "global_executive"
    REGIONAL_EXECUTIVE = "regional_executive"
    DEPARTMENT_MANAGER = "department_manager"
    BANKING_EMPLOYEE = "banking_employee"
    COMPLIANCE_OFFICER = "compliance_officer"
    AI_RESEARCHER = "ai_researcher"
    AUDITOR = "auditor"
    # A service role, never assigned to a person: the workflow policy engine that may
    # approve low-risk cases when policy allows (Phase 6, experiment C).
    AUTOMATED_POLICY = "automated_policy"
    # A service role for the job scheduler (Phase 14): runs scheduled reconciliation and
    # loan servicing. Never assigned to a person.
    SYSTEM_SCHEDULER = "system_scheduler"


ROLE_NAMES: dict[RoleCode, str] = {
    RoleCode.PLATFORM_ADMINISTRATOR: "Platform Administrator",
    RoleCode.GLOBAL_EXECUTIVE: "Global Executive",
    RoleCode.REGIONAL_EXECUTIVE: "Regional Executive",
    RoleCode.DEPARTMENT_MANAGER: "Department Manager",
    RoleCode.BANKING_EMPLOYEE: "Banking Employee",
    RoleCode.COMPLIANCE_OFFICER: "Compliance Officer",
    RoleCode.AI_RESEARCHER: "AI Researcher",
    RoleCode.AUDITOR: "Auditor",
    RoleCode.AUTOMATED_POLICY: "Automated Policy Engine",
    RoleCode.SYSTEM_SCHEDULER: "System Scheduler",
}

# Roles that belong to system principals only; people cannot be given them.
SERVICE_ROLES = frozenset({RoleCode.AUTOMATED_POLICY, RoleCode.SYSTEM_SCHEDULER})

# Read access every role has: the enterprise directory and the banking books.
_BASE = frozenset(
    {
        Permission.COUNTRIES_READ,
        Permission.ORGANIZATIONS_READ,
        Permission.EMPLOYEES_READ,
        Permission.CUSTOMERS_READ,
        Permission.ACCOUNTS_READ,
        Permission.WORKFLOWS_READ,
        Permission.SIMULATIONS_READ,
        Permission.AI_TOOLS_READ,
        Permission.EXPERIMENTS_READ,
        Permission.ANALYTICS_READ,
        Permission.PAYMENTS_READ,
        Permission.LOANS_READ,
    }
)
_FRONT_OFFICE = frozenset(
    {
        Permission.CUSTOMERS_MANAGE,
        Permission.ACCOUNTS_REQUEST,
        Permission.ACCOUNTS_TRANSACT,
        Permission.WORKFLOWS_START,
        Permission.LOANS_REPAY,
    }
)

ROLE_PERMISSIONS: dict[RoleCode, frozenset[Permission]] = {
    RoleCode.PLATFORM_ADMINISTRATOR: frozenset(Permission),
    RoleCode.GLOBAL_EXECUTIVE: _BASE
    | {
        Permission.RISK_READ,
        Permission.RISK_APPROVE,
        Permission.EMPLOYEES_READ_COMPENSATION,
        Permission.USERS_READ,
        Permission.LEDGER_READ,
        Permission.LOANS_APPROVE_LARGE,
        Permission.TREASURY_LIMITS,
    },
    RoleCode.REGIONAL_EXECUTIVE: _BASE
    | {
        Permission.RISK_READ,
        Permission.RISK_APPROVE,
        Permission.EMPLOYEES_READ_COMPENSATION,
        Permission.LOANS_APPROVE_LARGE,
        Permission.TREASURY_LIMITS,
    },
    RoleCode.DEPARTMENT_MANAGER: _BASE
    | _FRONT_OFFICE
    | {
        Permission.ACCOUNTS_APPROVE,
        Permission.ACCOUNTS_MANAGE,
        Permission.PAYMENTS_APPROVE,
        Permission.LOANS_APPROVE,
        Permission.LOANS_SERVICE,
        Permission.RETAIL_MANAGE,
        Permission.CARDS_MANAGE,
        Permission.MORTGAGES_MANAGE,
        Permission.TRADE_MANAGE,
        Permission.TREASURY_DEAL,
        Permission.TREASURY_CONFIRM,  # back office: confirm and settle others' deals
        Permission.PAYMENTS_OPERATE,
        Permission.WEALTH_ADVISE,
        Permission.WEALTH_APPROVE,  # an unsuitable order at the client's insistence
        Permission.WEALTH_CUSTODY,
        Permission.RISK_READ,
        Permission.RISK_RATE,
        Permission.WORKFLOWS_DEFINE,  # author and review their department's workflows
    },
    RoleCode.BANKING_EMPLOYEE: _BASE
    | _FRONT_OFFICE
    | {Permission.TREASURY_DEAL, Permission.WEALTH_ADVISE},
    RoleCode.COMPLIANCE_OFFICER: _BASE
    | {
        Permission.AUDIT_READ,
        Permission.CUSTOMERS_REVIEW,
        Permission.ACCOUNTS_APPROVE,
        Permission.ACCOUNTS_MANAGE,
        Permission.LEDGER_READ,
        Permission.PAYMENTS_REVIEW,
        Permission.CARDS_MANAGE,
        Permission.TRADE_MANAGE,
        Permission.COMPLIANCE_READ,
        Permission.COMPLIANCE_MONITOR,
        Permission.COMPLIANCE_FILE,
        Permission.WORKFLOWS_START,  # start the compliance workflows (Phase 46)
    },
    RoleCode.AI_RESEARCHER: _BASE
    | {
        Permission.SIMULATIONS_RUN,
        Permission.SIMULATIONS_MANAGE,
        Permission.AI_TOOLS_MANAGE,
        Permission.AI_TOOLS_INVOKE,
        Permission.EXPERIMENTS_RUN,
    },
    RoleCode.AUDITOR: _BASE
    | {
        Permission.EMPLOYEES_READ_COMPENSATION,
        Permission.USERS_READ,
        Permission.AUDIT_READ,
        Permission.LEDGER_READ,
        Permission.JOBS_READ,
        Permission.OBSERVABILITY_READ,
        Permission.COMPLIANCE_READ,
        Permission.RISK_READ,
    },
    RoleCode.AUTOMATED_POLICY: frozenset(
        {
            Permission.CUSTOMERS_READ,
            Permission.ACCOUNTS_READ,
            Permission.ACCOUNTS_APPROVE_LOW_RISK,
            Permission.PAYMENTS_READ,
            Permission.PAYMENTS_RELEASE_LOW_RISK,
            Permission.LOANS_READ,
            Permission.LOANS_APPROVE_LOW_RISK,
        }
    ),
    RoleCode.SYSTEM_SCHEDULER: frozenset(
        {
            Permission.LEDGER_READ,
            Permission.FX_MANAGE,
            Permission.LOANS_READ,
            Permission.LOANS_SERVICE,
            Permission.RETAIL_MANAGE,
            Permission.WORKFLOWS_READ,
            Permission.SIMULATIONS_READ,
            Permission.SIMULATIONS_MANAGE,
        }
    ),
}


def permissions_for(role_code: str) -> frozenset[Permission]:
    try:
        return ROLE_PERMISSIONS[RoleCode(role_code)]
    except ValueError:
        return frozenset()
