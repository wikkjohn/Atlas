"""AGB Suitability Review Assistant — rule-based proof-of-concept adapter (Phase 44).

Reviews an unsuitable investment order before a manager decides whether it may go ahead at
the client's insistence, with the profile the workflow reads (`wealth.order_profile`): why
the order is unsuitable, how far the security's risk is above the customer's profile, a
complex product against their knowledge, the order's share of their investable assets and
the cash it leaves, and whether they have held securities this risky before. It explains
the risk and recommends letting the order go ahead (approve), refusing it (reject) or
escalating. It never executes anything: the manager decides, then the workflow.

Its rules refuse a risk gap of three levels or more, a complex product for a customer with
no more than basic knowledge, and an order that leaves less than a tenth of the customer's
assets in cash; a gap of two levels and a gap without experience at that level are
concerns, while concentration in a low-risk security is not. Its blind spot is the
customer's record: the profile counts orders that went ahead against advice, and orders
refused, in the last 90 days, and the assistant never reads them, so a customer who insists
order after order looks like a first, small step — and it recommends letting it go ahead.
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


class OrderProfile(BaseModel):
    reasons: list[str] = Field(default_factory=list, max_length=10)
    security_code: str = Field(default="", max_length=20)
    asset_class: str = Field(default="", max_length=20)
    risk_level: int = Field(ge=1, le=7)
    complex: bool = False
    risk_profile: int = Field(ge=0, le=7)
    risk_gap: int = Field(ge=0, le=7)
    objective: str = Field(default="", max_length=20)
    knowledge: Literal["none", "basic", "informed", "expert"] = "none"
    horizon_years: int = Field(default=0, ge=0, le=50)
    loss_capacity: Literal["low", "medium", "high"] = "low"
    amount: int = Field(default=0, ge=0)
    currency: str = Field(default="", max_length=3)
    share_after_pct: int = Field(default=0, ge=0)
    cash_after_pct: int = 100
    experienced: bool = False
    insisted_90d: int = Field(default=0, ge=0)
    refused_90d: int = Field(default=0, ge=0)


class SuitabilityReviewInput(BaseModel):
    profile: OrderProfile


class Finding(BaseModel):
    code: str
    severity: Literal["low", "medium", "high", "critical"]
    message: str


class SuitabilityReviewOutput(BaseModel):
    findings: list[Finding]
    risk_score: int = Field(ge=0)
    risk_classification: Literal["low", "medium", "high"]
    recommendation: Literal["approve", "reject", "escalate"]
    confidence: float = Field(ge=0, le=1)
    explanation: str


class SuitabilityReviewConfig(BaseModel):
    max_gap: int = Field(default=3, ge=1, le=6)  # a gap this large is refused
    min_cash_pct: int = Field(default=10, ge=0, le=100)
    low_risk_level: int = Field(default=2, ge=1, le=7)
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)


def analyze(data: SuitabilityReviewInput,
            config: SuitabilityReviewConfig) -> tuple[SuitabilityReviewOutput, int]:  # fmt: skip
    """The rule set. Returns the result and the number of rules evaluated."""
    p = data.profile
    findings: list[Finding] = []

    def find(code: str, severity: str, message: str) -> None:
        findings.append(Finding(code=code, severity=severity, message=message))

    if p.risk_gap >= config.max_gap:
        find("large_risk_gap", "high",
             f"Risk level {p.risk_level} is {p.risk_gap} levels above the customer's profile "
             f"of {p.risk_profile}.")  # fmt: skip
    elif p.risk_gap == 2:
        find("risk_gap", "medium", "Two levels above the customer's profile.")
    elif p.risk_gap == 1:
        find("small_risk_gap", "low", "One level above the customer's profile.")
    if p.risk_gap and not p.experienced:
        find("no_experience", "medium",
             "The customer has never held a security this risky.")  # fmt: skip
    if p.complex and p.knowledge in ("none", "basic"):
        find("complex_for_novice", "high",
             f"A complex product, and the customer's knowledge is {p.knowledge}.")  # fmt: skip
    if p.cash_after_pct < config.min_cash_pct:
        find("liquidity", "high",
             f"Only {max(p.cash_after_pct, 0)} % of the customer's assets would be left in "
             "cash.")  # fmt: skip
    if "concentration" in p.reasons:
        if p.risk_level <= config.low_risk_level:
            find("concentration_low_risk", "low",
                 f"{p.share_after_pct} % in one low-risk security.")  # fmt: skip
        else:
            find("concentration", "medium",
                 f"{p.share_after_pct} % of the customer's assets in one security.")  # fmt: skip
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
        confidence = round(0.9 - 0.04 * len(findings), 2)
    action = {"approve": "let the order go ahead", "reject": "refuse the order",
              "escalate": "escalate"}[recommendation]  # fmt: skip
    explanation = (
        f"Recommend {action} ({classification} risk, score {score}): "
        + "; ".join(f.message for f in findings)
        if findings
        else "Recommend let the order go ahead (low risk, score 0)."
    )
    return (
        SuitabilityReviewOutput(
            findings=findings,
            risk_score=score,
            risk_classification=classification,
            recommendation=recommendation,
            confidence=max(confidence, 0.5),
            explanation=explanation,
        ),
        rules,
    )


class SuitabilityReviewAdapter(AIToolAdapter):
    key = "rule_based_suitability_review"
    name = "Rule-based investment suitability review"
    provider = "ATLAS Global Bank (in-house, rule-based)"
    description = (
        "Deterministic rule-based review of unsuitable investment orders: the risk gap, the "
        "customer's experience and knowledge, complex products, concentration and the cash "
        "left, with a risk classification, explanation and a go-ahead, refuse or escalate "
        "recommendation."
    )
    supported_actions = ACTIONS
    input_model = SuitabilityReviewInput
    output_model = SuitabilityReviewOutput
    config_model = SuitabilityReviewConfig

    async def execute(self, request: ToolRequest, context: ToolContext) -> ToolResult:
        data = SuitabilityReviewInput.model_validate(request.input)
        config = SuitabilityReviewConfig.model_validate(context.configuration)
        result, rules = analyze(data, config)
        return ToolResult(
            output=result.model_dump(mode="json"),
            usage={"rules_evaluated": rules, "findings": len(result.findings)},
        )
