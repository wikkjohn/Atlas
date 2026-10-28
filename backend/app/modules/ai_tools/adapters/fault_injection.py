"""Synthetic fault injector: a KYC adapter that fails on purpose.

It exists to prove the platform's failure handling — errors, timeouts and malformed
results are captured and workflows escalate safely — and to measure how experiments
degrade when a tool is unreliable. Which calls fail is decided by a hash of the request,
so the same input always gets the same behaviour (runs stay reproducible).
"""

import asyncio
import hashlib
import json

from pydantic import BaseModel, Field

from app.modules.ai_tools.adapters.base import (
    AIToolAdapter,
    ToolContext,
    ToolError,
    ToolRequest,
    ToolResult,
)
from app.modules.ai_tools.adapters.kyc_assistant import (
    ACTIONS,
    KycAssistantConfig,
    KycAssistantInput,
    KycAssistantOutput,
    analyze,
)


class FaultInjectionConfig(BaseModel):
    failure_rate: float = Field(default=0.1, ge=0, le=1)
    timeout_rate: float = Field(default=0.05, ge=0, le=1)
    invalid_output_rate: float = Field(default=0.05, ge=0, le=1)
    timeout_seconds: float = Field(default=0.2, gt=0, le=60)
    seed: int = 0


def _roll(request: ToolRequest, seed: int) -> float:
    canonical = json.dumps(request.input, sort_keys=True, default=str)
    digest = hashlib.sha256(f"{seed}:{request.action}:{canonical}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


class FaultInjectionAdapter(AIToolAdapter):
    key = "fault_injection"
    name = "Synthetic fault injector (KYC)"
    provider = "ATLAS Global Bank (test harness)"
    description = (
        "Behaves like the rule-based KYC assistant but fails, times out or returns "
        "malformed output for a configurable, reproducible share of requests."
    )
    supported_actions = ACTIONS
    input_model = KycAssistantInput
    output_model = KycAssistantOutput
    config_model = FaultInjectionConfig

    async def execute(self, request: ToolRequest, context: ToolContext) -> ToolResult:
        config = FaultInjectionConfig.model_validate(context.configuration)
        roll = _roll(request, config.seed)
        if roll < config.failure_rate:
            raise ToolError("injected_failure", "The tool reported an internal error (injected).")
        roll -= config.failure_rate
        if roll < config.timeout_rate:
            await asyncio.sleep(config.timeout_seconds * 4)  # longer than the timeout
        roll -= config.timeout_rate
        if roll < config.invalid_output_rate:
            return ToolResult(output={"recommendation": "maybe"}, usage={"rules_evaluated": 0})
        result, rules = analyze(
            KycAssistantInput.model_validate(request.input), KycAssistantConfig()
        )
        return ToolResult(output=result.model_dump(mode="json"), usage={"rules_evaluated": rules})
