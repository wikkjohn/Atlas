"""AGB Collections Review Assistant — rule-based proof-of-concept adapter (Phase 54).

Reviews a proposed payment plan before a collections manager activates it, with the profile
the workflow reads (`collections.plan_profile`): what the borrower would pay a month while
the plan runs (the regular instalment plus the catch-up payments) against the money paid into
their account in the 90 days before, how long since the last of it, and how far in arrears
the loan is. It explains the risk and recommends activating the plan (approve), rejecting it
or referring it on. It never activates anything: the manager decides, then the workflow.

Its rules reject a plan for a borrower with no money coming in, or one whose monthly
commitment is well above what comes in; they refer a stretched plan on and approve an
affordable one. Its blind spot is the borrower's history: the profile counts the borrower's
earlier payment plans and how many they broke, and the assistant never reads them, so a
borrower who has broken a plan before looks like any other affordable plan — and it
recommends activating it.
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


class PlanProfile(BaseModel):
    currency: str = Field(default="USD", max_length=3)
    arrears_amount: int = Field(default=0, ge=0)
    arrears_usd: int = Field(default=0, ge=0)
    days_past_due: int = Field(default=0, ge=0)
    overdue_instalments: int = Field(default=0, ge=0)
    interval_days: int = Field(default=14, ge=0)
    monthly_payment: int = Field(default=0, ge=0)
    monthly_commitment: int = Field(default=0, ge=0)
    inflow_90d: int = Field(default=0, ge=0)
    credits_90d: int = Field(default=0, ge=0)
    commitment_to_income_pct: int = Field(default=999, ge=0)
    days_since_last_credit: int = Field(default=999, ge=0)
    loan_age_days: int = Field(default=0, ge=0)
    prior_plans: int = Field(default=0, ge=0)
    prior_plans_broken: int = Field(default=0, ge=0)


class PlanReviewInput(BaseModel):
    profile: PlanProfile


class Finding(BaseModel):
    code: str
    severity: Literal["low", "medium", "high", "critical"]
    message: str


class PlanReviewOutput(BaseModel):
    findings: list[Finding]
    risk_score: int = Field(ge=0)
    risk_classification: Literal["low", "medium", "high"]
    recommendation: Literal["approve", "reject", "escalate"]
    confidence: float = Field(ge=0, le=1)
    explanation: str


class PlanReviewConfig(BaseModel):
    affordable_pct: int = Field(default=45, ge=1, le=1_000)  # commitment against income
    unaffordable_pct: int = Field(default=70, ge=1, le=1_000)
    stale_income_days: int = Field(default=60, ge=1)
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)


def analyze(data: PlanReviewInput, config: PlanReviewConfig) -> tuple[PlanReviewOutput, int]:
    """The rule set. Returns the result and the number of rules evaluated."""
    p = data.profile
    findings: list[Finding] = []

    def find(code: str, severity: str, message: str) -> None:
        findings.append(Finding(code=code, severity=severity, message=message))

    if p.credits_90d == 0:
        find("no_income", "high", "Nothing was paid into the account in 90 days.")
    elif p.days_since_last_credit > config.stale_income_days:
        find("no_recent_income", "high",
             f"The last money in arrived {p.days_since_last_credit} days ago.")  # fmt: skip
    elif p.commitment_to_income_pct > config.unaffordable_pct:
        find("unaffordable", "high",
             f"The plan takes {p.commitment_to_income_pct} % of the monthly income.")  # fmt: skip
    elif p.commitment_to_income_pct > config.affordable_pct:
        find("stretched", "medium",
             f"The plan takes {p.commitment_to_income_pct} % of the monthly income.")  # fmt: skip
    else:
        find("affordable", "low",
             f"The plan takes {p.commitment_to_income_pct} % of the monthly income.")  # fmt: skip
    rules = 5

    score = sum(SEVERITY_POINTS[f.severity] for f in findings)
    severities = {f.severity for f in findings}
    if severities & {"critical", "high"}:
        classification, recommendation, confidence = "high", "reject", 0.84
    elif "medium" in severities:
        classification, recommendation, confidence = "medium", "escalate", 0.6
    else:
        classification, recommendation, confidence = "low", "approve", 0.85
    action = {"approve": "activate the plan", "reject": "reject the plan",
              "escalate": "refer it on"}[recommendation]  # fmt: skip
    explanation = (f"Recommend {action} ({classification} risk, score {score}): "
                   + "; ".join(f.message for f in findings))  # fmt: skip
    return (
        PlanReviewOutput(
            findings=findings,
            risk_score=score,
            risk_classification=classification,
            recommendation=recommendation,
            confidence=confidence,
            explanation=explanation,
        ),
        rules,
    )


class PlanReviewAdapter(AIToolAdapter):
    key = "rule_based_plan_review"
    name = "Rule-based payment plan review"
    provider = "ATLAS Global Bank (in-house, rule-based)"
    description = (
        "Deterministic rule-based review of a proposed payment plan: the monthly commitment "
        "against the money paid into the borrower's account, and whether any came in "
        "recently, with a risk classification, explanation and an activate, reject or refer "
        "recommendation."
    )
    supported_actions = ACTIONS
    input_model = PlanReviewInput
    output_model = PlanReviewOutput
    config_model = PlanReviewConfig

    async def execute(self, request: ToolRequest, context: ToolContext) -> ToolResult:
        data = PlanReviewInput.model_validate(request.input)
        config = PlanReviewConfig.model_validate(context.configuration)
        result, rules = analyze(data, config)
        return ToolResult(
            output=result.model_dump(mode="json"),
            usage={"rules_evaluated": rules, "findings": len(result.findings)},
        )
