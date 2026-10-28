"""The provider-independent adapter contract.

Every AI tool — the rule-based proof of concept today, a hosted model later — implements
`AIToolAdapter.execute`. The workflow engine and the experiments only ever talk to the
invocation service (`app.modules.ai_tools.service.invoke`), which validates requests and
results against the tool's registered JSON Schemas, enforces the tool's allowed actions,
applies the timeout and records every call. Replacing an adapter therefore never changes
a workflow.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel, Field


class ToolRequest(BaseModel):
    """What a caller asks a tool to do."""

    action: str = Field(min_length=1, max_length=64)
    input: dict[str, Any]


class ToolResult(BaseModel):
    """What an adapter returns: the output (checked against the output schema) and usage
    figures that feed cost estimates (e.g. rules evaluated, tokens)."""

    output: dict[str, Any]
    usage: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class ToolContext:
    """Facts about the call that are not part of the request itself."""

    tool_id: str
    tool_version: str
    configuration: dict[str, Any]
    now: datetime
    actor_id: str | None = None
    execution_id: str | None = None
    correlation_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class ToolError(Exception):
    """A structured failure reported by an adapter."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class AIToolAdapter(ABC):
    """Base class of every tool implementation."""

    key: ClassVar[str]  # referenced by registered tools
    name: ClassVar[str]
    provider: ClassVar[str]
    description: ClassVar[str]
    supported_actions: ClassVar[frozenset[str]]
    input_model: ClassVar[type[BaseModel]]  # default input schema
    output_model: ClassVar[type[BaseModel]]  # default output schema
    config_model: ClassVar[type[BaseModel]]  # validates the registered configuration

    @abstractmethod
    async def execute(self, request: ToolRequest, context: ToolContext) -> ToolResult:
        raise NotImplementedError
