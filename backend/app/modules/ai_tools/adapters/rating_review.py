"""AGB Rating Review Assistant — rule-based proof-of-concept adapter (Phase 48).

Reviews a credit rating that departs from the model's grade before a second person approves
or rejects it, with the profile the workflow reads (`risk.rating_profile`): the departure in
notches and its direction, days past due, the customer's exposure and overdraft use, their
money in against their debt, and the default limits at the model's and the proposed grade. It
explains the risk and recommends approving the grade, rejecting it (the model's stands) or
referring it on. It never rates or approves anything: the approver decides, then the workflow.

Its rules reject a default grade without 90 days past due, any departure of three notches or
more, and an upgrade for a customer whose overdraft is nearly used up or whose debt is above
a year's money in; they support a downgrade the overdraft or debt explains, and an upgrade
for a customer whose money in dwarfs their debt. Its blind spot is the rating history: the
profile counts the customer's other departures from the model in the last year and how many
were rejected, and the assistant never reads them, so a customer whose rater keeps asking for
an upgrade that keeps being refused looks like a strong customer due one notch — and it
recommends approving.
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


class RatingProfile(BaseModel):
    customer_type: Literal["individual", "business"] = "individual"
    kyc_risk: str = Field(default="low", max_length=20)
    suggested_grade: int = Field(ge=1, le=10)
    proposed_grade: int = Field(ge=1, le=10)
    notches: int = Field(default=0, ge=-9, le=9)
    direction: Literal["upgrade", "downgrade"] = "downgrade"
    worst_days_past_due: int = Field(default=0, ge=0)
    frozen_facility: bool = False
    exposure_usd: int = Field(default=0, ge=0)
    overdraft_usd: int = Field(default=0, ge=0)
    overdraft_use_pct: int = Field(default=0, ge=0)
    monthly_inflow_usd: int = Field(default=0, ge=0)
    exposure_to_annual_inflow_pct: int = Field(default=0, ge=0)
    limit_at_model_usd: int = Field(default=0, ge=0)
    limit_at_proposed_usd: int = Field(default=0, ge=0)
    rationale_chars: int = Field(default=0, ge=0)
    prior_overrides_365d: int = Field(default=0, ge=0)
    prior_overrides_rejected_365d: int = Field(default=0, ge=0)


class RatingReviewInput(BaseModel):
    profile: RatingProfile


class Finding(BaseModel):
    code: str
    severity: Literal["low", "medium", "high", "critical"]
    message: str


class RatingReviewOutput(BaseModel):
    findings: list[Finding]
    risk_score: int = Field(ge=0)
    risk_classification: Literal["low", "medium", "high"]
    recommendation: Literal["approve", "reject", "escalate"]
    confidence: float = Field(ge=0, le=1)
    explanation: str


class RatingReviewConfig(BaseModel):
    max_notches: int = Field(default=2, ge=1, le=9)  # beyond this, the departure is refused
    strained_overdraft_pct: int = Field(default=75, ge=1, le=1_000)
    heavy_debt_pct: int = Field(default=120, ge=1, le=100_000)  # debt against a year's money in
    strong_capacity_pct: int = Field(default=25, ge=0, le=100_000)
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)


def analyze(data: RatingReviewInput, config: RatingReviewConfig
            ) -> tuple[RatingReviewOutput, int]:  # fmt: skip
    """The rule set. Returns the result and the number of rules evaluated."""
    p = data.profile
    findings: list[Finding] = []
    debt = p.exposure_to_annual_inflow_pct
    overdraft = p.overdraft_use_pct

    def find(code: str, severity: str, message: str) -> None:
        findings.append(Finding(code=code, severity=severity, message=message))

    if p.proposed_grade == 10 and p.worst_days_past_due < 90:
        find("default_without_arrears", "high",
             f"Grade 10 (in default) with {p.worst_days_past_due} days past due.")  # fmt: skip
    if abs(p.notches) > config.max_notches:
        find("large_departure", "high",
             f"{abs(p.notches)} notches from the model's grade {p.suggested_grade}.")  # fmt: skip
    if p.direction == "upgrade":
        if overdraft >= config.strained_overdraft_pct:
            find("strained_upgrade", "high",
                 f"An upgrade with the overdraft {overdraft} % used.")  # fmt: skip
        if debt >= config.heavy_debt_pct:
            find("indebted_upgrade", "high",
                 f"An upgrade with debt at {debt} % of a year's money in.")  # fmt: skip
        if overdraft < config.strained_overdraft_pct and debt < config.heavy_debt_pct:
            if debt <= config.strong_capacity_pct and overdraft == 0:
                find("strong_capacity", "low",
                     f"Debt only {debt} % of a year's money in, no overdraft used.")  # fmt: skip
            else:
                find("thin_support", "medium", "Nothing in the profile supports the upgrade.")
    else:
        explained = False
        if overdraft >= config.strained_overdraft_pct:
            find("overdraft_stress", "low", f"The overdraft is {overdraft} % used.")
            explained = True
        if debt >= config.heavy_debt_pct:
            find("heavy_debt", "low", f"Debt at {debt} % of a year's money in.")
            explained = True
        if not explained and p.proposed_grade < 10:
            find("no_stress_seen", "medium",
                 "No overdraft or debt strain behind the downgrade.")  # fmt: skip
    rules = 6

    score = sum(SEVERITY_POINTS[f.severity] for f in findings)
    severities = {f.severity for f in findings}
    if severities & {"critical", "high"}:
        classification, recommendation, confidence = "high", "reject", 0.85
    elif "medium" in severities:
        classification, recommendation, confidence = "medium", "escalate", 0.6
    else:
        classification, recommendation = "low", "approve"
        confidence = round(0.9 - 0.04 * len(findings), 2)
    action = {"approve": "approve the grade", "reject": "keep the model's grade",
              "escalate": "refer it on"}[recommendation]  # fmt: skip
    explanation = (
        f"Recommend {action} ({classification} risk, score {score}): "
        + "; ".join(f.message for f in findings)
        if findings
        else "Recommend approve the grade (low risk, score 0)."
    )
    return (
        RatingReviewOutput(
            findings=findings,
            risk_score=score,
            risk_classification=classification,
            recommendation=recommendation,
            confidence=max(confidence, 0.5),
            explanation=explanation,
        ),
        rules,
    )


class RatingReviewAdapter(AIToolAdapter):
    key = "rule_based_rating_review"
    name = "Rule-based rating override review"
    provider = "ATLAS Global Bank (in-house, rule-based)"
    description = (
        "Deterministic rule-based review of credit ratings that depart from the model: the "
        "departure, days past due, overdraft use and debt against money in, with a risk "
        "classification, explanation and an approve, keep-the-model or refer recommendation."
    )
    supported_actions = ACTIONS
    input_model = RatingReviewInput
    output_model = RatingReviewOutput
    config_model = RatingReviewConfig

    async def execute(self, request: ToolRequest, context: ToolContext) -> ToolResult:
        data = RatingReviewInput.model_validate(request.input)
        config = RatingReviewConfig.model_validate(context.configuration)
        result, rules = analyze(data, config)
        return ToolResult(
            output=result.model_dump(mode="json"),
            usage={"rules_evaluated": rules, "findings": len(result.findings)},
        )
