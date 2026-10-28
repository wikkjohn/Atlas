import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import UUIDPrimaryKey


class ToolStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class InvocationStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"  # the adapter raised an error
    TIMEOUT = "timeout"
    INVALID_INPUT = "invalid_input"  # the request did not match the tool's input schema
    INVALID_OUTPUT = "invalid_output"  # the result did not match the tool's output schema
    BLOCKED = "blocked"  # not permitted: action not allowed, tool disabled


class AITool(UUIDPrimaryKey, Base):
    """One registered version of an AI tool. Versions are immutable; only status changes."""

    __tablename__ = "ai_tools"
    __table_args__ = (
        UniqueConstraint("tool_id", "tool_version", name="uq_ai_tools_id_version"),
        CheckConstraint("status IN ('active', 'disabled')", name="status_valid"),
    )

    tool_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tool_name: Mapped[str] = mapped_column(String(200), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    adapter: Mapped[str] = mapped_column(String(64), nullable=False)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    allowed_actions: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    # Platform permissions a person needs to invoke the tool directly.
    permissions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    compatible_workflows: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AIToolInvocation(UUIDPrimaryKey, Base):
    """Every call to a tool: request, result or error, timing and usage."""

    __tablename__ = "ai_tool_invocations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('succeeded', 'failed', 'timeout', 'invalid_input', 'invalid_output',"
            " 'blocked')",
            name="status_valid",
        ),
    )

    tool_record_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ai_tools.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    tool_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(40), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    invoked_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("workflow_executions.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    simulation_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("simulation_runs.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    # Business time of the call (simulated time inside simulations).
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
