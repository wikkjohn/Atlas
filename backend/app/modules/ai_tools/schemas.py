import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

TOOL_ID_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
VERSION_PATTERN = r"^\d+\.\d+\.\d+$"


class ToolCreate(BaseModel):
    tool_id: str = Field(min_length=3, max_length=64, pattern=TOOL_ID_PATTERN)
    tool_name: str = Field(min_length=3, max_length=200)
    tool_version: str = Field(pattern=VERSION_PATTERN, description="Semantic version, e.g. 1.0.0")
    provider: str = Field(min_length=2, max_length=200)
    description: str = Field(default="", max_length=2000)
    adapter: str = Field(description="Implementation key; see GET /ai-tools/adapters")
    input_schema: dict[str, Any] | None = Field(
        default=None, description="JSON Schema; defaults to the adapter's"
    )
    output_schema: dict[str, Any] | None = Field(
        default=None, description="JSON Schema; defaults to the adapter's"
    )
    allowed_actions: list[str] = Field(min_length=1, max_length=10)
    permissions: list[str] = Field(default_factory=list, max_length=10)
    compatible_workflows: list[str] = Field(default_factory=list, max_length=20)
    configuration: dict[str, Any] = Field(default_factory=dict)


class ToolStatusUpdate(BaseModel):
    status: Literal["active", "disabled"]


class ToolOut(BaseModel):
    id: uuid.UUID
    tool_id: str
    tool_name: str
    tool_version: str
    provider: str
    description: str
    adapter: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    allowed_actions: list[str]
    permissions: list[str]
    compatible_workflows: list[str]
    configuration: dict[str, Any]
    status: str
    created_by_username: str | None
    created_at: datetime
    invocations: int
    failures: int


class AdapterOut(BaseModel):
    key: str
    name: str
    provider: str
    description: str
    supported_actions: list[str]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    configuration_schema: dict[str, Any]


class ActionOut(BaseModel):
    action: str
    grantable: bool
    description: str


class InvokeRequest(BaseModel):
    action: str = Field(min_length=1, max_length=64)
    input: dict[str, Any]


class InvocationOut(BaseModel):
    id: uuid.UUID
    tool_record_id: uuid.UUID
    tool_id: str
    tool_version: str
    action: str
    status: str
    input: dict[str, Any]
    output: dict[str, Any] | None
    error: dict[str, Any] | None
    duration_ms: int
    usage: dict[str, Any]
    invoked_by: uuid.UUID | None
    execution_id: uuid.UUID | None
    simulation_run_id: uuid.UUID | None
    occurred_at: datetime
    created_at: datetime
