"""AGB Leave Review Assistant — rule-based proof-of-concept adapter (Phase 56).

Reviews a leave request before a department manager decides it, with the profile the
workflow reads (`hr.leave_profile`): the leave's kind, length and notice, the department's
cover on its working days with the others already away, and the annual balance. It explains
the risk and recommends approving, rejecting or referring the request on. It never decides
anything: the manager does, then the workflow.

Its rules reject leave that would leave the department under-covered, and a week or more of
annual leave asked for less than a week ahead; they refer tight cover on and approve the
rest. Its blind spot is the employee's history: the profile counts their other requests in
the last 90 days and how many came at short notice, and the assistant never reads them, so
someone who keeps asking for a day or two off at the last minute looks like any short
request, and it recommends approving.
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


class LeaveProfile(BaseModel):
    kind: str = Field(default="annual", max_length=20)
    days: int = Field(default=1, ge=0)
    notice_days: int = Field(default=30)
    annual_balance_after: int | None = None
    department_headcount: int = Field(default=0, ge=0)
    others_away: int = Field(default=0, ge=0)
    coverage_pct: int = Field(default=100, ge=0)
    sick_days_365: int = Field(default=0, ge=0)
    prior_requests_90d: int = Field(default=0, ge=0)
    prior_short_notice_90d: int = Field(default=0, ge=0)


class LeaveReviewInput(BaseModel):
    profile: LeaveProfile


class Finding(BaseModel):
    code: str
    severity: Literal["low", "medium", "high", "critical"]
    message: str


class LeaveReviewOutput(BaseModel):
    findings: list[Finding]
    risk_score: int = Field(ge=0)
    risk_classification: Literal["low", "medium", "high"]
    recommendation: Literal["approve", "reject", "escalate"]
    confidence: float = Field(ge=0, le=1)
    explanation: str


class LeaveReviewConfig(BaseModel):
    min_coverage_pct: int = Field(default=60, ge=0, le=100)
    comfortable_coverage_pct: int = Field(default=70, ge=0, le=100)
    long_leave_days: int = Field(default=5, ge=1)
    min_notice_days: int = Field(default=7, ge=0)
    long_sick_days: int = Field(default=5, ge=1)
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)


def analyze(data: LeaveReviewInput, config: LeaveReviewConfig) -> tuple[LeaveReviewOutput, int]:
    """The rule set. Returns the result and the number of rules evaluated."""
    p = data.profile
    findings: list[Finding] = []

    def find(code: str, severity: str, message: str) -> None:
        findings.append(Finding(code=code, severity=severity, message=message))

    if p.coverage_pct < config.min_coverage_pct:
        find("understaffed", "high",
             f"Only {p.coverage_pct} % of the department would be working.")  # fmt: skip
    if (p.kind == "annual" and p.days >= config.long_leave_days
            and p.notice_days < config.min_notice_days):  # fmt: skip
        find("short_notice", "high",
             f"{p.days} days of annual leave asked {p.notice_days} days ahead.")  # fmt: skip
    if p.kind == "sick" and p.days > config.long_sick_days:
        find("long_sickness", "medium", f"{p.days} days off sick: a fit note is needed.")
    if config.min_coverage_pct <= p.coverage_pct < config.comfortable_coverage_pct:
        find("tight_cover", "medium",
             f"{p.coverage_pct} % of the department would be working.")  # fmt: skip
    if not findings:
        find("routine", "low", f"{p.days} days of {p.kind} leave with the department covered.")
    rules = 5

    score = sum(SEVERITY_POINTS[f.severity] for f in findings)
    severities = {f.severity for f in findings}
    if severities & {"critical", "high"}:
        classification, recommendation, confidence = "high", "reject", 0.83
    elif "medium" in severities:
        classification, recommendation, confidence = "medium", "escalate", 0.6
    else:
        classification, recommendation, confidence = "low", "approve", 0.86
    action = {"approve": "approve the leave", "reject": "reject the leave",
              "escalate": "refer it on"}[recommendation]  # fmt: skip
    explanation = (f"Recommend {action} ({classification} risk, score {score}): "
                   + "; ".join(f.message for f in findings))  # fmt: skip
    return (
        LeaveReviewOutput(
            findings=findings,
            risk_score=score,
            risk_classification=classification,
            recommendation=recommendation,
            confidence=confidence,
            explanation=explanation,
        ),
        rules,
    )


class LeaveReviewAdapter(AIToolAdapter):
    key = "rule_based_leave_review"
    name = "Rule-based leave review"
    provider = "ATLAS Global Bank (in-house, rule-based)"
    description = (
        "Deterministic rule-based review of a leave request: the department's cover with the "
        "others already away, notice for long annual leave and long sickness, with a risk "
        "classification, explanation and an approve, reject or refer recommendation."
    )
    supported_actions = ACTIONS
    input_model = LeaveReviewInput
    output_model = LeaveReviewOutput
    config_model = LeaveReviewConfig

    async def execute(self, request: ToolRequest, context: ToolContext) -> ToolResult:
        data = LeaveReviewInput.model_validate(request.input)
        config = LeaveReviewConfig.model_validate(context.configuration)
        result, rules = analyze(data, config)
        return ToolResult(
            output=result.model_dump(mode="json"),
            usage={"rules_evaluated": rules, "findings": len(result.findings)},
        )
