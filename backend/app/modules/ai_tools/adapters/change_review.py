"""AGB Change Review Assistant — rule-based proof-of-concept adapter (Phase 60).

Reviews a change request before someone approves it, with the profile the workflow reads
(`itops.change_profile`): its kind, risk and the application's tier, the backout plan, the
window's length, start hour and lead time, and the application's open P1 and P2 incidents.
It explains the risk and recommends approving, rejecting or referring the change on. It
never approves anything: the approver decides, then the workflow.

Its rules reject a change with no backout plan, a change to an application with a P1 or P2
still open, and a window in business hours on a tier-1 or tier-2 application; they refer on
changes raised less than a day ahead and long windows, and recommend approving the rest.
Its blind spot is history: the profile counts the failed changes to the application, and by
the requester, in the last 90 days, and the assistant never reads them, so a change from a
team whose last changes kept failing looks like any routine change, and it recommends
approving.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.modules.ai_tools.adapters.base import (
    AIToolAdapter,
    ToolContext,
    ToolRequest,
    ToolResult,
)

ACTIONS = frozenset({"recommend_decision"})
SEVERITY_POINTS = {"low": 1, "medium": 2, "high": 3, "critical": 5}


class ChangeProfile(BaseModel):
    kind: str = Field(default="normal", max_length=20)
    risk: Literal["low", "medium", "high"] = "medium"
    tier: int = Field(default=2, ge=1, le=3)
    has_backout_plan: bool = True
    window_hours: float = Field(default=2, ge=0)
    start_hour_utc: int = Field(default=22, ge=0, le=23)
    business_hours: bool = False
    lead_hours: float = Field(default=72)
    in_freeze: bool = False
    open_major_incidents: int = Field(default=0, ge=0)
    app_failed_changes_90d: int = Field(default=0, ge=0)
    app_changes_90d: int = Field(default=0, ge=0)
    requester_failed_changes_90d: int = Field(default=0, ge=0)


class ChangeReviewInput(BaseModel):
    profile: ChangeProfile


class Finding(BaseModel):
    code: str
    severity: Literal["low", "medium", "high", "critical"]
    message: str


class ChangeReviewOutput(BaseModel):
    findings: list[Finding]
    risk_score: int = Field(ge=0)
    risk_classification: Literal["low", "medium", "high"]
    recommendation: Literal["approve", "reject", "escalate"]
    confidence: float = Field(ge=0, le=1)
    explanation: str


class ChangeReviewConfig(BaseModel):
    min_lead_hours: float = Field(default=24, ge=0)
    long_window_hours: float = Field(default=8, gt=0)
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)


def analyze(data: ChangeReviewInput, config: ChangeReviewConfig) -> tuple[ChangeReviewOutput, int]:
    """The rule set. Returns the result and the number of rules evaluated."""
    p = data.profile
    findings: list[Finding] = []

    def find(code: str, severity: str, message: str) -> None:
        findings.append(Finding(code=code, severity=severity, message=message))

    if not p.has_backout_plan:
        find("no_backout_plan", "high", "There is no backout plan if the change goes wrong.")
    if p.open_major_incidents:
        find("open_major_incident", "high",
             f"The application has {p.open_major_incidents} P1 or P2 incident(s) open: "
             "change it once they are resolved.")  # fmt: skip
    if p.business_hours and p.tier <= 2:
        find("business_hours", "high",
             f"A tier-{p.tier} application changed at {p.start_hour_utc:02d}:00 UTC, in "
             "business hours.")  # fmt: skip
    if p.lead_hours < config.min_lead_hours:
        find("short_notice", "medium", f"Raised {p.lead_hours:.0f} hours ahead.")
    if p.window_hours > config.long_window_hours:
        find("long_window", "medium", f"A {p.window_hours:g}-hour window.")
    if not findings:
        find("routine", "low", f"A {p.risk}-risk {p.kind} change out of hours, with a backout "
                               "plan.")  # fmt: skip
    rules = 5

    score = sum(SEVERITY_POINTS[f.severity] for f in findings)
    severities = {f.severity for f in findings}
    if severities & {"critical", "high"}:
        classification, recommendation, confidence = "high", "reject", 0.84
    elif "medium" in severities:
        classification, recommendation, confidence = "medium", "escalate", 0.6
    else:
        classification, recommendation, confidence = "low", "approve", 0.86
    action = {"approve": "approve the change", "reject": "reject the change",
              "escalate": "refer it on"}[recommendation]  # fmt: skip
    explanation = (f"Recommend {action} ({classification} risk, score {score}): "
                   + "; ".join(f.message for f in findings))  # fmt: skip
    return (
        ChangeReviewOutput(
            findings=findings,
            risk_score=score,
            risk_classification=classification,
            recommendation=recommendation,
            confidence=confidence,
            explanation=explanation,
        ),
        rules,
    )


class ChangeReviewAdapter(AIToolAdapter):
    key = "rule_based_change_review"
    name = "Rule-based change review"
    provider = "ATLAS Global Bank (in-house, rule-based)"
    description = (
        "Deterministic rule-based review of a change request: the backout plan, open P1 and "
        "P2 incidents on the application, business-hours windows on critical systems, short "
        "notice and long windows, with a risk classification, explanation and an approve, "
        "reject or refer recommendation."
    )
    supported_actions = ACTIONS
    input_model = ChangeReviewInput
    output_model = ChangeReviewOutput
    config_model = ChangeReviewConfig

    async def execute(self, request: ToolRequest, context: ToolContext) -> ToolResult:
        data = ChangeReviewInput.model_validate(request.input)
        config = ChangeReviewConfig.model_validate(context.configuration)
        result, rules = analyze(data, config)
        return ToolResult(
            output=result.model_dump(mode="json"),
            usage={"rules_evaluated": rules, "findings": len(result.findings)},
        )
