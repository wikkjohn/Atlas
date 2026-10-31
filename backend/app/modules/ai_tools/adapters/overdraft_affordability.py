"""AGB Overdraft Affordability Assistant — rule-based proof-of-concept adapter (Phase 30).

Reviews an arranged-overdraft request with the account's recent history, which the
workflow reads from the ledger (`retail.account_profile`): the average monthly money in,
in how many of the last three months any came in, how many of the last 90 days the account
was overdrawn, and the product's maximum. It explains the risk and recommends approve,
reject or escalate. It never sets a limit: a credit officer decides, then the workflow.

Its rules weigh the size of the limit against income and how regular that income is. Its
blind spot is a customer who already lives in an overdraft: regular income and a modest
request, but overdrawn most days — it counts that as a medium concern only, and still
recommends approval. Exactly the kind of thing an experiment should bring out.
"""

from datetime import date
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


class AccountProfile(BaseModel):
    currency: str = Field(min_length=3, max_length=3)
    balance: int
    overdraft_limit: int = Field(ge=0)
    max_overdraft: int = Field(ge=0, description="The product's largest arranged overdraft")
    monthly_credits: int = Field(ge=0, description="Average money in a month, last 90 days")
    months_with_credits: int = Field(ge=0, le=3)
    days_overdrawn: int = Field(ge=0, le=90, description="Of the last 90 days")


class OverdraftAffordabilityInput(BaseModel):
    limit: int = Field(ge=0, description="The overdraft asked for, minor units")
    profile: AccountProfile
    as_of: date | None = None


class Finding(BaseModel):
    code: str
    severity: Literal["low", "medium", "high", "critical"]
    message: str


class OverdraftAffordabilityOutput(BaseModel):
    findings: list[Finding]
    risk_score: int = Field(ge=0)
    risk_classification: Literal["low", "medium", "high"]
    recommendation: Literal["approve", "reject", "escalate"]
    confidence: float = Field(ge=0, le=1)
    explanation: str


class OverdraftAffordabilityConfig(BaseModel):
    stretched_ratio: float = Field(default=1.0, gt=0, le=10)  # limit / monthly money in
    moderate_ratio: float = Field(default=0.5, gt=0, le=10)
    often_overdrawn_days: int = Field(default=15, ge=1, le=90)
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)


def analyze(
    data: OverdraftAffordabilityInput, config: OverdraftAffordabilityConfig
) -> tuple[OverdraftAffordabilityOutput, int]:
    """The rule set. Returns the result and the number of rules evaluated."""
    limit, p = data.limit, data.profile
    findings: list[Finding] = []

    def find(code: str, severity: str, message: str) -> None:
        findings.append(Finding(code=code, severity=severity, message=message))

    if limit > p.max_overdraft:
        find("above_product_maximum", "critical",
             f"The limit is above the product's maximum of {p.max_overdraft}.")  # fmt: skip
    if p.monthly_credits == 0:
        find("no_income", "high", "No money came into the account in the last 90 days.")
    else:
        ratio = limit / p.monthly_credits
        if ratio > config.stretched_ratio:
            find("stretched", "high",
                 f"The limit is {ratio:.1f}× a month's money in.")  # fmt: skip
        elif ratio > config.moderate_ratio:
            find("moderate_size", "low", f"The limit is {ratio:.0%} of a month's money in.")
    if p.monthly_credits and p.months_with_credits < 3:
        find("irregular_income", "medium",
             f"Money came in during {p.months_with_credits} of the last 3 months.")  # fmt: skip
    if p.days_overdrawn >= config.often_overdrawn_days:
        find("often_overdrawn", "medium",
             f"The account was overdrawn on {p.days_overdrawn} of the last 90 days.")  # fmt: skip
    rules = 5

    score = sum(SEVERITY_POINTS[f.severity] for f in findings)
    severities = {f.severity for f in findings}
    if severities & {"critical", "high"}:
        classification, recommendation, confidence = "high", "reject", 0.85
    elif score >= 4:
        classification, recommendation, confidence = "medium", "escalate", 0.6
    elif "medium" in severities:
        classification, recommendation, confidence = "medium", "approve", 0.65
    else:
        classification, recommendation = "low", "approve"
        confidence = round(0.92 - 0.04 * len(findings), 2)
    explanation = (
        f"Recommend {recommendation} ({classification} risk, score {score}): "
        + "; ".join(f.message for f in findings)
        if findings
        else "Recommend approve (low risk, score 0): a small limit against regular income."
    )
    return (
        OverdraftAffordabilityOutput(
            findings=findings,
            risk_score=score,
            risk_classification=classification,
            recommendation=recommendation,
            confidence=max(confidence, 0.5),
            explanation=explanation,
        ),
        rules,
    )


class OverdraftAffordabilityAdapter(AIToolAdapter):
    key = "rule_based_overdraft_affordability"
    name = "Rule-based overdraft affordability review"
    provider = "ATLAS Global Bank (in-house, rule-based)"
    description = (
        "Deterministic rule-based review of arranged-overdraft requests against the "
        "account's recent income and overdraft use, with a risk classification, "
        "explanation and recommendation."
    )
    supported_actions = ACTIONS
    input_model = OverdraftAffordabilityInput
    output_model = OverdraftAffordabilityOutput
    config_model = OverdraftAffordabilityConfig

    async def execute(self, request: ToolRequest, context: ToolContext) -> ToolResult:
        data = OverdraftAffordabilityInput.model_validate(request.input)
        config = OverdraftAffordabilityConfig.model_validate(context.configuration)
        result, rules = analyze(data, config)
        return ToolResult(
            output=result.model_dump(mode="json"),
            usage={"rules_evaluated": rules, "findings": len(result.findings)},
        )
