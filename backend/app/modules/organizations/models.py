import uuid
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.models import Timestamps, UUIDPrimaryKey
from app.modules.countries.models import Country


class OrganizationType(StrEnum):
    GLOBAL_BANK = "global_bank"
    REGIONAL_HEADQUARTERS = "regional_headquarters"
    COUNTRY_SUBSIDIARY = "country_subsidiary"
    BUSINESS_DIVISION = "business_division"
    DEPARTMENT = "department"
    TEAM = "team"


# The only parent type each organization type may have.
ALLOWED_PARENT: dict[OrganizationType, OrganizationType | None] = {
    OrganizationType.GLOBAL_BANK: None,
    OrganizationType.REGIONAL_HEADQUARTERS: OrganizationType.GLOBAL_BANK,
    OrganizationType.COUNTRY_SUBSIDIARY: OrganizationType.REGIONAL_HEADQUARTERS,
    OrganizationType.BUSINESS_DIVISION: OrganizationType.COUNTRY_SUBSIDIARY,
    OrganizationType.DEPARTMENT: OrganizationType.BUSINESS_DIVISION,
    OrganizationType.TEAM: OrganizationType.DEPARTMENT,
}

# Types that sit inside one country and inherit it from their parent.
COUNTRY_SCOPED = {
    OrganizationType.COUNTRY_SUBSIDIARY,
    OrganizationType.BUSINESS_DIVISION,
    OrganizationType.DEPARTMENT,
    OrganizationType.TEAM,
}


class OrganizationStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class Organization(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "organizations"
    __table_args__ = (
        UniqueConstraint("parent_organization_id", "name", name="uq_organizations_sibling_name"),
        CheckConstraint(
            "organization_type IN ('global_bank', 'regional_headquarters', 'country_subsidiary',"
            " 'business_division', 'department', 'team')",
            name="organization_type_valid",
        ),
        CheckConstraint("status IN ('active', 'inactive')", name="status_valid"),
        # Exactly the global bank has no parent.
        CheckConstraint(
            "(organization_type = 'global_bank') = (parent_organization_id IS NULL)",
            name="root_is_global_bank",
        ),
        Index(
            "uq_organizations_single_global_bank",
            "organization_type",
            unique=True,
            postgresql_where=text("organization_type = 'global_bank'"),
        ),
        Index(
            "uq_organizations_one_subsidiary_per_country",
            "country_id",
            unique=True,
            postgresql_where=text("organization_type = 'country_subsidiary'"),
        ),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    organization_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    parent_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    country_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("countries.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    # Set for every type below the global bank; inherited from the regional headquarters.
    region: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    # The blueprint an organization was generated from (Phase 27); null when built by hand.
    generated_from: Mapped[str | None] = mapped_column(String(40), nullable=True)

    country: Mapped[Country | None] = relationship(lazy="joined")
