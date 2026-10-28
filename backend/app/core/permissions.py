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
    WORKFLOWS_READ = "workflows:read"
    WORKFLOWS_START = "workflows:start"  # start executions, deliver signals (e.g. documents)
    WORKFLOWS_MANAGE = "workflows:manage"  # resume or cancel executions
    SIMULATIONS_READ = "simulations:read"
    SIMULATIONS_RUN = "simulations:run"  # start simulation runs (creates synthetic data)
    AI_TOOLS_READ = "ai_tools:read"
    AI_TOOLS_MANAGE = "ai_tools:manage"  # register tools and versions, enable/disable
    AI_TOOLS_INVOKE = "ai_tools:invoke"  # call a tool directly (test console)
    EXPERIMENTS_READ = "experiments:read"  # experiments, evaluations, benchmarks, reports
    EXPERIMENTS_RUN = "experiments:run"  # start and evaluate experiments
    ANALYTICS_READ = "analytics:read"  # enterprise dashboard metrics


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
}

# Roles that belong to system principals only; people cannot be given them.
SERVICE_ROLES = frozenset({RoleCode.AUTOMATED_POLICY})

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
    }
)
_FRONT_OFFICE = frozenset(
    {
        Permission.CUSTOMERS_MANAGE,
        Permission.ACCOUNTS_REQUEST,
        Permission.ACCOUNTS_TRANSACT,
        Permission.WORKFLOWS_START,
    }
)

ROLE_PERMISSIONS: dict[RoleCode, frozenset[Permission]] = {
    RoleCode.PLATFORM_ADMINISTRATOR: frozenset(Permission),
    RoleCode.GLOBAL_EXECUTIVE: _BASE
    | {Permission.EMPLOYEES_READ_COMPENSATION, Permission.USERS_READ, Permission.LEDGER_READ},
    RoleCode.REGIONAL_EXECUTIVE: _BASE | {Permission.EMPLOYEES_READ_COMPENSATION},
    RoleCode.DEPARTMENT_MANAGER: _BASE
    | _FRONT_OFFICE
    | {Permission.ACCOUNTS_APPROVE, Permission.ACCOUNTS_MANAGE},
    RoleCode.BANKING_EMPLOYEE: _BASE | _FRONT_OFFICE,
    RoleCode.COMPLIANCE_OFFICER: _BASE
    | {
        Permission.AUDIT_READ,
        Permission.CUSTOMERS_REVIEW,
        Permission.ACCOUNTS_APPROVE,
        Permission.ACCOUNTS_MANAGE,
        Permission.LEDGER_READ,
    },
    RoleCode.AI_RESEARCHER: _BASE
    | {
        Permission.SIMULATIONS_RUN,
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
    },
    RoleCode.AUTOMATED_POLICY: frozenset(
        {Permission.CUSTOMERS_READ, Permission.ACCOUNTS_READ, Permission.ACCOUNTS_APPROVE_LOW_RISK}
    ),
}


def permissions_for(role_code: str) -> frozenset[Permission]:
    try:
        return ROLE_PERMISSIONS[RoleCode(role_code)]
    except ValueError:
        return frozenset()
