"""Shared plumbing for advisory AI steps (`ai_task`).

A step reads the execution's settings (`ai_mode`: off, assisted or automated, and the
registered tool), calls the tool through the invocation service, and returns either the
tool's analysis or a safe "escalate" result when no usable answer came back. It never
decides anything: a later policy step or a person does.
"""

import uuid
from typing import Any

from app.modules.workflows.engine import StepContext, StepError

AI_MODES = ("off", "assisted", "automated")


def unavailable(mode: str, code: str, message: str, **extra: object) -> dict[str, Any]:
    # Safe escalation: without a usable result the case follows the human path.
    return {
        "mode": mode,
        "available": False,
        "recommendation": "escalate",
        "automation_requested": False,
        "error": {"code": code, "message": message},
        **extra,
    }


def review(ctx: StepContext, *, assisted_action: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Call the configured tool. `automation_requested` is set when the mode is automated
    and the tool recommends approval at low risk — a request the policy step checks."""
    # Imported here: the AI module depends on the workflow registry, not the reverse.
    from app.modules.ai_tools.models import AITool, InvocationStatus
    from app.modules.ai_tools.service import invoke

    settings = ctx.get("_settings") or {}
    mode = settings.get("ai_mode", "off")
    if mode not in AI_MODES:
        raise StepError("invalid_ai_mode", f"Unknown AI mode '{mode}'.")
    if mode == "off":
        return {"mode": "off"}
    tool_record_id = settings.get("ai_tool_id")
    tool = ctx.db.get(AITool, uuid.UUID(tool_record_id)) if tool_record_id else None
    if tool is None:
        return unavailable(mode, "tool_missing", "No AI tool is configured for this case.")
    action = "complete_low_risk_review" if mode == "automated" else assisted_action
    call = invoke(
        ctx.db,
        tool,
        action,
        payload,
        actor_id=None,
        execution_id=ctx.execution.id,
        simulation_run_id=ctx.execution.simulation_run_id,
        now=ctx.now,
    )
    identity = {
        "tool_id": tool.tool_id,
        "tool_version": tool.tool_version,
        "invocation_id": str(call.id),
        "action": action,
    }
    if call.status != InvocationStatus.SUCCEEDED:
        error = call.error or {}
        return unavailable(
            mode,
            error.get("code", call.status),
            error.get("message", call.status),
            invocation_status=call.status,
            **identity,
        )
    out = call.output or {}
    return {
        "mode": mode,
        "available": True,
        "invocation_status": call.status,
        **identity,
        "recommendation": out["recommendation"],
        "risk_classification": out["risk_classification"],
        "risk_score": out["risk_score"],
        "confidence": out["confidence"],
        "findings": [f["code"] for f in out["findings"]],
        "explanation": out["explanation"],
        "automation_requested": mode == "automated"
        and out["recommendation"] == "approve"
        and out["risk_classification"] == "low",
    }
