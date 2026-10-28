import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.core.permissions import RoleCode
from app.modules.employees.models import EmploymentStatus

NAME_PATTERN = r"^[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ' -]*$"
# Up to 1 trillion minor units.
MAX_COMPENSATION = 10**12


class EmployeeCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=100, pattern=NAME_PATTERN)
    last_name: str = Field(min_length=1, max_length=100, pattern=NAME_PATTERN)
    email: str | None = Field(
        default=None,
        max_length=254,
        pattern=r"^[a-z0-9._-]+@atlasbank\.example$",
        description="Synthetic address in atlasbank.example; generated when omitted.",
    )
    organization_id: uuid.UUID = Field(description="A department or team")
    manager_id: uuid.UUID | None = None
    job_title: str = Field(min_length=2, max_length=150)
    role: RoleCode = RoleCode.BANKING_EMPLOYEE
    country_id: uuid.UUID | None = Field(
        default=None, description="Defaults to the organization's country."
    )
    employment_status: EmploymentStatus = EmploymentStatus.ACTIVE
    annual_compensation: int = Field(
        ge=0, le=MAX_COMPENSATION, description="Minor units of the country's currency"
    )


class EmployeeUpdate(BaseModel):
    """Only the fields sent are changed. Send `manager_id: null` to clear the manager."""

    job_title: str | None = Field(default=None, min_length=2, max_length=150)
    organization_id: uuid.UUID | None = None
    manager_id: uuid.UUID | None = None
    role: RoleCode | None = None
    employment_status: EmploymentStatus | None = None
    annual_compensation: int | None = Field(default=None, ge=0, le=MAX_COMPENSATION)


class EmployeeRef(BaseModel):
    id: uuid.UUID
    employee_number: str
    full_name: str
    job_title: str


class EmployeeOut(BaseModel):
    id: uuid.UUID
    employee_number: str
    first_name: str
    last_name: str
    full_name: str
    email: str
    organization_id: uuid.UUID
    organization_name: str
    department_id: uuid.UUID
    department_name: str
    manager: EmployeeRef | None
    job_title: str
    role: str
    country_id: uuid.UUID
    country_code: str
    employment_status: str
    annual_compensation: int | None = Field(
        description="Minor units; null unless the caller may read compensation."
    )
    compensation_currency: str | None
    created_at: datetime
    updated_at: datetime
