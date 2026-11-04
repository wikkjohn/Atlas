"""Claude (hosted model) adapter — the first real model provider (Phase 76, Milestone G1).

The same contract as every rule-based assistant: a registered tool keeps its input and
output schemas and switches only its `adapter` to `claude_messages`. The adapter sends the
request's input to the Claude Messages API with the tool's instructions, and asks for the
answer in the tool's own output schema (structured outputs), so the invocation service
validates it exactly as it validates a rule set's answer. Every call records its tokens and
what they cost, refused and cut-off calls included.

Synthetic data only: ATLAS holds no real customer, employee or payment data, and calls to
the hosted model are switched off unless `ATLAS_AI_PROVIDER_ENABLED` is set. Credentials
come from the environment (`ANTHROPIC_API_KEY`, or an `ant auth login` profile); the bank
never stores them.
"""

import json
from collections.abc import Callable
from typing import Any, Literal

import anthropic
from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings
from app.modules.ai_tools.actions import GRANTABLE_ACTIONS
from app.modules.ai_tools.adapters.base import (
    AIToolAdapter,
    ToolContext,
    ToolError,
    ToolRequest,
    ToolResult,
)

DEFAULT_MODEL = "claude-opus-5-5"
# Server-side refusal fallbacks: on a policy decline the API re-runs the request on a
# fallback model it chooses by the decline's category, within the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = frozenset({"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5"})

# List prices in USD per million tokens: (input, output, cache read), Anthropic first-party
# API, as published in October 2026. A cache write costs 1.25 times the input price.
# Override per tool with `input_price_per_mtok` / `output_price_per_mtok`.
PRICES: dict[str, tuple[float, float, float]] = {
    "claude-fable-5-1": (10.0, 50.0, 0.25),
    "claude-fable-5": (10.0, 50.0, 1.0),
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-opus-4-8": (5.0, 25.0, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20),
    "claude-sonnet-5": (2.0, 10.0, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-haiku-4-5": (1.0, 5.0, 0.10),
}
CACHE_WRITE_FACTOR = 1.25

PREAMBLE = (
    "You are an AI review assistant inside ATLAS Global Bank, a simulated bank. Every "
    "customer, employee, account and amount you see is synthetic. You advise; people and "
    "the workflow's policy decide. Read the request, apply the instructions below, and "
    "answer with the JSON object the response format requires: no other text. Explain your "
    "recommendation in plain words a reviewer can check against the input."
)

# Keywords structured outputs do not accept. They are removed from the schema sent to the
# model; the invocation service still checks the answer against the full registered schema.
_UNSUPPORTED = frozenset({
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minLength", "maxLength", "pattern", "minItems", "maxItems", "uniqueItems",
    "minProperties", "maxProperties", "default", "examples", "title",
})  # fmt: skip


class ClaudeInput(BaseModel):
    """Any object: a tool using this adapter registers its own input schema."""

    model_config = ConfigDict(extra="allow")


class ClaudeOutput(BaseModel):
    """The shape of the advisory review assistants; tools register their own."""

    recommendation: Literal["approve", "reject", "escalate"]
    confidence: float = Field(ge=0, le=1)
    explanation: str


class ClaudeConfig(BaseModel):
    model: str = Field(default=DEFAULT_MODEL, min_length=3, max_length=60)
    # What the tool is for and how it should judge: the tool's own instructions.
    instructions: str = Field(min_length=20, max_length=20_000)
    # Claude Opus 5.5 defaults to medium; it is set explicitly so a run records it.
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    max_tokens: int = Field(default=16_000, ge=256, le=64_000)
    # The whole call, retries included (the invocation service waits this long).
    timeout_seconds: float = Field(default=120.0, gt=0, le=600)
    max_retries: int = Field(default=2, ge=0, le=5)
    refusal_fallbacks: bool = True
    input_price_per_mtok: float | None = Field(default=None, ge=0)
    output_price_per_mtok: float | None = Field(default=None, ge=0)


def _strip(schema: Any) -> Any:
    """The schema as structured outputs accept it: no numeric, length or count limits, and
    every object closed to properties it does not declare."""
    if isinstance(schema, list):
        return [_strip(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    out = {k: _strip(v) for k, v in schema.items() if k not in _UNSUPPORTED}
    if out.get("type") == "object" or "properties" in out:
        out["additionalProperties"] = False
    return out


def response_schema(output_schema: dict[str, Any]) -> dict[str, Any]:
    return _strip(output_schema)


def cost_usd(model: str, usage: dict[str, int], config: ClaudeConfig) -> float | None:
    """What the call cost at list prices (None for a model without a known price)."""
    listed = PRICES.get(model)
    if listed is None and config.input_price_per_mtok is None:
        return None
    base_in, base_out, base_cache = listed or (0.0, 0.0, 0.0)
    price_in = config.input_price_per_mtok if config.input_price_per_mtok is not None else base_in
    price_out = (
        config.output_price_per_mtok if config.output_price_per_mtok is not None else base_out
    )
    price_cache = base_cache if listed else price_in * 0.1
    total = (
        usage.get("input_tokens", 0) * price_in
        + usage.get("output_tokens", 0) * price_out
        + usage.get("cache_read_input_tokens", 0) * price_cache
        + usage.get("cache_creation_input_tokens", 0) * price_in * CACHE_WRITE_FACTOR
    ) / 1_000_000
    return round(total, 6)


def _usage(response: Any, config: ClaudeConfig) -> dict[str, Any]:
    raw = getattr(response, "usage", None)
    tokens = {
        key: int(getattr(raw, key, 0) or 0)
        for key in (
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        )
    }
    served = getattr(response, "model", None) or config.model
    cost = cost_usd(served, tokens, config)
    return {
        "provider": "anthropic",
        "model": served,
        "requested_model": config.model,
        "effort": config.effort,
        **tokens,
        "cost_usd": cost,
        "priced": cost is not None,
        "stop_reason": getattr(response, "stop_reason", None),
        "request_id": getattr(response, "_request_id", None),
    }


def make_client(config: ClaudeConfig) -> Any:
    """The SDK client; credentials come from the environment. Tests replace this."""
    per_attempt = config.timeout_seconds / (config.max_retries + 1)
    return anthropic.AsyncAnthropic(timeout=per_attempt, max_retries=config.max_retries)


client_factory: Callable[[ClaudeConfig], Any] = make_client


def _provider_error(exc: Exception) -> ToolError:
    """The SDK's failures as the contract's structured errors, most specific first."""
    if isinstance(exc, anthropic.APITimeoutError):
        return ToolError("provider_timeout", "The model provider did not answer in time.",
                         retryable=True)  # fmt: skip
    if isinstance(exc, anthropic.APIConnectionError):
        return ToolError("provider_unreachable", "The model provider could not be reached.",
                         retryable=True)  # fmt: skip
    if isinstance(exc, anthropic.RateLimitError):
        return ToolError("rate_limited", "The model provider's rate limit was reached.",
                         retryable=True)  # fmt: skip
    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return ToolError("provider_auth", "The model provider refused the credentials.")
    if isinstance(exc, anthropic.BadRequestError):
        return ToolError("provider_rejected", f"The model provider rejected the request: "
                         f"{getattr(exc, 'message', exc)}")  # fmt: skip
    if isinstance(exc, anthropic.APIStatusError):
        retryable = exc.status_code >= 500
        return ToolError("provider_error", f"The model provider failed ({exc.status_code}).",
                         retryable=retryable)  # fmt: skip
    raise exc


class ClaudeAdapter(AIToolAdapter):
    key = "claude_messages"
    name = "Claude (hosted model)"
    provider = "Anthropic Claude"
    description = (
        "A hosted Claude model behind the standard tool contract: the tool's instructions "
        "and the request's input go to the Messages API, and the answer comes back in the "
        "tool's own output schema. Tokens and cost are recorded on every call. Synthetic "
        "data only; switched off unless ATLAS_AI_PROVIDER_ENABLED is set."
    )
    supported_actions = frozenset(GRANTABLE_ACTIONS)
    input_model = ClaudeInput
    output_model = ClaudeOutput
    config_model = ClaudeConfig

    async def execute(self, request: ToolRequest, context: ToolContext) -> ToolResult:
        if not get_settings().ai_provider_enabled:
            raise ToolError(
                "provider_disabled",
                "Calls to hosted models are switched off (set ATLAS_AI_PROVIDER_ENABLED).",
            )
        config = ClaudeConfig.model_validate(context.configuration)
        output_schema = context.extra.get("output_schema") or ClaudeOutput.model_json_schema()
        params: dict[str, Any] = {
            "model": config.model,
            "max_tokens": config.max_tokens,
            "system": f"{PREAMBLE}\n\n{config.instructions}",
            "messages": [
                {
                    "role": "user",
                    "content": f"Action: {request.action}\n\nInput (JSON):\n"
                    + json.dumps(request.input, sort_keys=True, indent=2, default=str),
                }
            ],
            "output_config": {
                "effort": config.effort,
                "format": {"type": "json_schema", "schema": response_schema(output_schema)},
            },
            "metadata": {"user_id": f"atlas-tool:{context.tool_id}"},
        }
        if config.refusal_fallbacks and config.model in FALLBACK_MODELS:
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"
        client = client_factory(config)
        try:
            response = await client.beta.messages.create(**params)
        except anthropic.AnthropicError as exc:
            raise _provider_error(exc) from exc

        usage = _usage(response, config)
        stop = getattr(response, "stop_reason", None)
        if stop == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None)
            raise ToolError(
                "refused",
                f"The model declined the request (category: {category or 'unspecified'}).",
                usage=usage,
            )
        if stop == "max_tokens":
            raise ToolError("truncated", "The answer was cut off at max_tokens.", usage=usage)
        text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), "")
        try:
            output = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ToolError("unparseable_output", "The answer was not JSON.", usage=usage) from exc
        if not isinstance(output, dict):
            raise ToolError("unparseable_output", "The answer was not a JSON object.", usage=usage)
        return ToolResult(output=output, usage=usage)
