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


class RoleCode(StrEnum):
    PLATFORM_ADMINISTRATOR = "platform_administrator"
    GLOBAL_EXECUTIVE = "global_executive"
    REGIONAL_EXECUTIVE = "regional_executive"
    DEPARTMENT_MANAGER = "department_manager"
    BANKING_EMPLOYEE = "banking_employee"
    COMPLIANCE_OFFICER = "compliance_officer"
    AI_RESEARCHER = "ai_researcher"
    AUDITOR = "auditor"


ROLE_NAMES: dict[RoleCode, str] = {
    RoleCode.PLATFORM_ADMINISTRATOR: "Platform Administrator",
    RoleCode.GLOBAL_EXECUTIVE: "Global Executive",
    RoleCode.REGIONAL_EXECUTIVE: "Regional Executive",
    RoleCode.DEPARTMENT_MANAGER: "Department Manager",
    RoleCode.BANKING_EMPLOYEE: "Banking Employee",
    RoleCode.COMPLIANCE_OFFICER: "Compliance Officer",
    RoleCode.AI_RESEARCHER: "AI Researcher",
    RoleCode.AUDITOR: "Auditor",
}

_DIRECTORY = frozenset(
    {Permission.COUNTRIES_READ, Permission.ORGANIZATIONS_READ, Permission.EMPLOYEES_READ}
)

ROLE_PERMISSIONS: dict[RoleCode, frozenset[Permission]] = {
    RoleCode.PLATFORM_ADMINISTRATOR: frozenset(Permission),
    RoleCode.GLOBAL_EXECUTIVE: _DIRECTORY
    | {Permission.EMPLOYEES_READ_COMPENSATION, Permission.USERS_READ},
    RoleCode.REGIONAL_EXECUTIVE: _DIRECTORY | {Permission.EMPLOYEES_READ_COMPENSATION},
    RoleCode.DEPARTMENT_MANAGER: _DIRECTORY,
    RoleCode.BANKING_EMPLOYEE: _DIRECTORY,
    RoleCode.COMPLIANCE_OFFICER: _DIRECTORY | {Permission.AUDIT_READ},
    RoleCode.AI_RESEARCHER: _DIRECTORY,
    RoleCode.AUDITOR: _DIRECTORY
    | {Permission.EMPLOYEES_READ_COMPENSATION, Permission.USERS_READ, Permission.AUDIT_READ},
}


def permissions_for(role_code: str) -> frozenset[Permission]:
    try:
        return ROLE_PERMISSIONS[RoleCode(role_code)]
    except ValueError:
        return frozenset()
