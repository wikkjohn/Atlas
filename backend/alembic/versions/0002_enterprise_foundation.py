"""Enterprise foundation: countries, organizations, roles, users, employees, audit, idempotency.

Revision ID: 0002_enterprise_foundation
Revises: 0001_platform_baseline
Create Date: 2026-10-27

Reference data (the eight platform roles and the five initial countries) is written out
here rather than imported from application code, so this migration stays reproducible
when the code changes later.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_enterprise_foundation"
down_revision: str | None = "0001_platform_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ROLES = [
    ("platform_administrator", "Platform Administrator", "Full administration of the platform."),
    ("global_executive", "Global Executive", "Bank-wide read access including compensation."),
    ("regional_executive", "Regional Executive", "Read access including compensation."),
    ("department_manager", "Department Manager", "Directory access for managing a department."),
    ("banking_employee", "Banking Employee", "Directory access for day-to-day work."),
    ("compliance_officer", "Compliance Officer", "Directory and audit log access."),
    ("ai_researcher", "AI Researcher", "Runs AI experiments; directory access."),
    ("auditor", "Auditor", "Read-only access to records, compensation and the audit log."),
]

# Initial operating countries. Further countries (up to the 120-country target) are added
# through the API without schema changes.
COUNTRIES = [
    ("US", "United States", "americas", "USD", "America/New_York", ["en-US", "es-US"]),
    ("GB", "United Kingdom", "europe", "GBP", "Europe/London", ["en-GB"]),
    ("DE", "Germany", "europe", "EUR", "Europe/Berlin", ["de-DE", "en"]),
    ("SG", "Singapore", "asia_pacific", "SGD", "Asia/Singapore", ["en-SG", "zh", "ms", "ta"]),
    ("JP", "Japan", "asia_pacific", "JPY", "Asia/Tokyo", ["ja-JP"]),
]

APPEND_ONLY_FUNCTION = """
CREATE FUNCTION audit_events_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only: % is not permitted', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.execute("CREATE SEQUENCE employee_number_seq START 1")
    op.create_table(
        "countries",
        sa.Column("iso_country_code", sa.String(length=2), nullable=False),
        sa.Column("country_name", sa.String(length=100), nullable=False),
        sa.Column("region", sa.String(length=30), nullable=False),
        sa.Column("default_currency", sa.String(length=3), nullable=False),
        sa.Column("default_timezone", sa.String(length=64), nullable=False),
        sa.Column("supported_languages", sa.ARRAY(sa.String(length=16)), nullable=False),
        sa.Column("operational_status", sa.String(length=20), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "default_currency ~ '^[A-Z]{3}$'", name=op.f("ck_countries_default_currency_format")
        ),
        sa.CheckConstraint(
            "iso_country_code ~ '^[A-Z]{2}$'", name=op.f("ck_countries_iso_country_code_format")
        ),
        sa.CheckConstraint(
            "operational_status IN ('active', 'planned', 'suspended')",
            name=op.f("ck_countries_operational_status_valid"),
        ),
        sa.CheckConstraint(
            "region IN ('americas', 'europe', 'middle_east_africa', 'asia_pacific')",
            name=op.f("ck_countries_region_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_countries")),
        sa.UniqueConstraint("country_name", name=op.f("uq_countries_country_name")),
        sa.UniqueConstraint("iso_country_code", name=op.f("uq_countries_iso_country_code")),
    )
    op.create_index(op.f("ix_countries_region"), "countries", ["region"], unique=False)
    op.create_table(
        "roles",
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
        sa.UniqueConstraint("code", name=op.f("uq_roles_code")),
    )
    op.create_table(
        "organizations",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("organization_type", sa.String(length=30), nullable=False),
        sa.Column("parent_organization_id", sa.Uuid(), nullable=True),
        sa.Column("country_id", sa.Uuid(), nullable=True),
        sa.Column("region", sa.String(length=30), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(organization_type = 'global_bank') = (parent_organization_id IS NULL)",
            name=op.f("ck_organizations_root_is_global_bank"),
        ),
        sa.CheckConstraint(
            "organization_type IN ('global_bank', 'regional_headquarters', 'country_subsidiary',"
            " 'business_division', 'department', 'team')",
            name=op.f("ck_organizations_organization_type_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')", name=op.f("ck_organizations_status_valid")
        ),
        sa.ForeignKeyConstraint(
            ["country_id"],
            ["countries.id"],
            name=op.f("fk_organizations_country_id_countries"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_organization_id"],
            ["organizations.id"],
            name=op.f("fk_organizations_parent_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
        sa.UniqueConstraint("parent_organization_id", "name", name="uq_organizations_sibling_name"),
    )
    op.create_index(
        op.f("ix_organizations_country_id"), "organizations", ["country_id"], unique=False
    )
    op.create_index(
        op.f("ix_organizations_organization_type"),
        "organizations",
        ["organization_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_organizations_parent_organization_id"),
        "organizations",
        ["parent_organization_id"],
        unique=False,
    )
    op.create_index(
        "uq_organizations_one_subsidiary_per_country",
        "organizations",
        ["country_id"],
        unique=True,
        postgresql_where=sa.text("organization_type = 'country_subsidiary'"),
    )
    op.create_index(
        "uq_organizations_single_global_bank",
        "organizations",
        ["organization_type"],
        unique=True,
        postgresql_where=sa.text("organization_type = 'global_bank'"),
    )
    op.create_table(
        "employees",
        sa.Column("employee_number", sa.String(length=20), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=False),
        sa.Column("manager_id", sa.Uuid(), nullable=True),
        sa.Column("job_title", sa.String(length=150), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("country_id", sa.Uuid(), nullable=False),
        sa.Column("employment_status", sa.String(length=20), nullable=False),
        sa.Column("annual_compensation", sa.BigInteger(), nullable=False),
        sa.Column("compensation_currency", sa.String(length=3), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "compensation_currency ~ '^[A-Z]{3}$'", name=op.f("ck_employees_currency_format")
        ),
        sa.CheckConstraint(
            "employment_status IN ('active', 'on_leave', 'terminated')",
            name=op.f("ck_employees_employment_status_valid"),
        ),
        sa.CheckConstraint(
            "annual_compensation >= 0", name=op.f("ck_employees_compensation_non_negative")
        ),
        sa.CheckConstraint(
            "manager_id IS NULL OR manager_id <> id", name=op.f("ck_employees_not_own_manager")
        ),
        sa.ForeignKeyConstraint(
            ["country_id"],
            ["countries.id"],
            name=op.f("fk_employees_country_id_countries"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["organizations.id"],
            name=op.f("fk_employees_department_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["manager_id"],
            ["employees.id"],
            name=op.f("fk_employees_manager_id_employees"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_employees_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], name=op.f("fk_employees_role_id_roles"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_employees")),
        sa.UniqueConstraint("email", name=op.f("uq_employees_email")),
        sa.UniqueConstraint("employee_number", name=op.f("uq_employees_employee_number")),
    )
    op.create_index(op.f("ix_employees_country_id"), "employees", ["country_id"], unique=False)
    op.create_index(
        op.f("ix_employees_department_id"), "employees", ["department_id"], unique=False
    )
    op.create_index(
        op.f("ix_employees_employment_status"), "employees", ["employment_status"], unique=False
    )
    op.create_index(op.f("ix_employees_manager_id"), "employees", ["manager_id"], unique=False)
    op.create_index(
        op.f("ix_employees_organization_id"), "employees", ["organization_id"], unique=False
    )
    op.create_table(
        "users",
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            name=op.f("fk_users_employee_id_employees"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], name=op.f("fk_users_role_id_roles"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.UniqueConstraint("employee_id", name=op.f("uq_users_employee_id")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=True),
        sa.Column(
            "timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_audit_events_actor_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index("ix_audit_events_action", "audit_events", ["action"], unique=False)
    op.create_index("ix_audit_events_actor_id", "audit_events", ["actor_id"], unique=False)
    op.create_index(
        "ix_audit_events_entity", "audit_events", ["entity_type", "entity_id"], unique=False
    )
    op.create_index("ix_audit_events_timestamp", "audit_events", ["timestamp"], unique=False)
    op.create_table(
        "idempotency_keys",
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("path", sa.String(length=500), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_idempotency_keys_actor_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("actor_id", "key", name=op.f("pk_idempotency_keys")),
    )

    # Audit records can only ever be inserted.
    op.execute(APPEND_ONLY_FUNCTION)
    op.execute(
        "CREATE TRIGGER audit_events_no_update_delete BEFORE UPDATE OR DELETE ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION audit_events_append_only()"
    )
    op.execute(
        "CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON audit_events "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_events_append_only()"
    )

    roles = sa.table(
        "roles",
        sa.column("id", sa.Uuid()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("description", sa.Text()),
    )
    op.bulk_insert(
        roles,
        [
            {"id": uuid.uuid4(), "code": code, "name": name, "description": description}
            for code, name, description in ROLES
        ],
    )
    countries = sa.table(
        "countries",
        sa.column("id", sa.Uuid()),
        sa.column("iso_country_code", sa.String()),
        sa.column("country_name", sa.String()),
        sa.column("region", sa.String()),
        sa.column("default_currency", sa.String()),
        sa.column("default_timezone", sa.String()),
        sa.column("supported_languages", sa.ARRAY(sa.String())),
        sa.column("operational_status", sa.String()),
    )
    op.bulk_insert(
        countries,
        [
            {
                "id": uuid.uuid4(),
                "iso_country_code": code,
                "country_name": name,
                "region": region,
                "default_currency": currency,
                "default_timezone": timezone,
                "supported_languages": languages,
                "operational_status": "active",
            }
            for code, name, region, currency, timezone, languages in COUNTRIES
        ],
    )


def downgrade() -> None:
    op.drop_table("idempotency_keys")
    op.execute("DROP TRIGGER audit_events_no_truncate ON audit_events")
    op.execute("DROP TRIGGER audit_events_no_update_delete ON audit_events")
    op.execute("DROP FUNCTION audit_events_append_only()")
    op.drop_index("ix_audit_events_timestamp", table_name="audit_events")
    op.drop_index("ix_audit_events_entity", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_id", table_name="audit_events")
    op.drop_index("ix_audit_events_action", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("users")
    op.drop_index(op.f("ix_employees_organization_id"), table_name="employees")
    op.drop_index(op.f("ix_employees_manager_id"), table_name="employees")
    op.drop_index(op.f("ix_employees_employment_status"), table_name="employees")
    op.drop_index(op.f("ix_employees_department_id"), table_name="employees")
    op.drop_index(op.f("ix_employees_country_id"), table_name="employees")
    op.drop_table("employees")
    op.drop_index(
        "uq_organizations_single_global_bank",
        table_name="organizations",
        postgresql_where=sa.text("organization_type = 'global_bank'"),
    )
    op.drop_index(
        "uq_organizations_one_subsidiary_per_country",
        table_name="organizations",
        postgresql_where=sa.text("organization_type = 'country_subsidiary'"),
    )
    op.drop_index(op.f("ix_organizations_parent_organization_id"), table_name="organizations")
    op.drop_index(op.f("ix_organizations_organization_type"), table_name="organizations")
    op.drop_index(op.f("ix_organizations_country_id"), table_name="organizations")
    op.drop_table("organizations")
    op.drop_table("roles")
    op.drop_index(op.f("ix_countries_region"), table_name="countries")
    op.drop_table("countries")
    op.execute("DROP SEQUENCE employee_number_seq")
