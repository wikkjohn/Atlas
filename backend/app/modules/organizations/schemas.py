import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.countries.models import Region
from app.modules.organizations.models import OrganizationStatus, OrganizationType


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    organization_type: OrganizationType
    parent_organization_id: uuid.UUID | None = None
    country_id: uuid.UUID | None = Field(
        default=None,
        description="Required for a country subsidiary; inherited by divisions, departments "
        "and teams; optional headquarters location otherwise.",
    )
    region: Region | None = Field(
        default=None, description="Required for a regional headquarters; inherited below it."
    )


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    status: OrganizationStatus | None = None


class OrganizationOut(BaseModel):
    id: uuid.UUID
    name: str
    organization_type: str
    parent_organization_id: uuid.UUID | None
    country_id: uuid.UUID | None
    country_code: str | None
    country_name: str | None
    currency: str | None
    region: str | None
    status: str
    generated_from: str | None = None
    child_count: int
    employee_count: int
    created_at: datetime
    updated_at: datetime
