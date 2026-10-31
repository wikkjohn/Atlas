"""AGB Mortgage Underwriting Assistant — rule-based proof-of-concept adapter (Phase 34).

Reviews a mortgage application that has passed every lending rule, with the profile the
workflow reads (`mortgages.application_profile`): loan-to-value, the payment against
declared income and against the bureau's income estimate, how far declared income exceeds
the estimate, the credit score, and the valuation against the automated model. It explains
the risk and recommends approving, declining or escalating. It never issues an offer: an
underwriter decides, then the workflow.

Its rules look for a stretched borrower (a large payment on a high loan-to-value), a
payment the bureau's income estimate cannot carry, declared income well above that
estimate, a high loan-to-value and a thin credit file. Its blind spot is age: the profile
says how old the applicant will be when the term ends, and the assistant never looks — a
30-year mortgage for a 60-year-old with prime figures gets an approval.
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


class ApplicationProfile(BaseModel):
    currency: str = Field(min_length=3, max_length=3)
    product_code: str = Field(default="", max_length=40)
    loan_amount: int = Field(gt=0)
    term_years: int = Field(ge=1, le=40)
    ltv_bps: int = Field(ge=0, le=20_000)
    monthly_payment: int = Field(gt=0)
    declared_monthly_income: int = Field(ge=0)
    income_estimate: int = Field(ge=0)
    payment_to_income_bps: int = Field(ge=0)
    payment_to_estimate_bps: int = Field(ge=0)
    declared_to_estimate_bps: int = Field(ge=0)
    credit_score: int = Field(ge=0, le=1000)
    recent_defaults: int = Field(default=0, ge=0)
    valuation_method: Literal["desktop", "surveyor"]
    model_to_price_bps: int = Field(ge=0)
    age_at_term_end: int = Field(ge=0, le=150)


class MortgageUnderwritingInput(BaseModel):
    profile: ApplicationProfile


class Finding(BaseModel):
    code: str
    severity: Literal["low", "medium", "high", "critical"]
    message: str


class MortgageUnderwritingOutput(BaseModel):
    findings: list[Finding]
    risk_score: int = Field(ge=0)
    risk_classification: Literal["low", "medium", "high"]
    recommendation: Literal["approve", "reject", "escalate"]
    confidence: float = Field(ge=0, le=1)
    explanation: str


class MortgageUnderwritingConfig(BaseModel):
    stretched_payment_bps: int = Field(default=3000, ge=0, le=10_000)
    stretched_ltv_bps: int = Field(default=8500, ge=0, le=10_000)
    estimate_payment_bps: int = Field(default=3500, ge=0, le=10_000)
    income_gap_bps: int = Field(default=12_500, ge=10_000, le=30_000)
    high_ltv_bps: int = Field(default=8000, ge=0, le=10_000)
    thin_score: int = Field(default=660, ge=0, le=1000)
    model_gap_bps: int = Field(default=9000, ge=0, le=10_000)
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)


def analyze(
    data: MortgageUnderwritingInput, config: MortgageUnderwritingConfig
) -> tuple[MortgageUnderwritingOutput, int]:
    """The rule set. Returns the result and the number of rules evaluated."""
    p = data.profile
    findings: list[Finding] = []

    def find(code: str, severity: str, message: str) -> None:
        findings.append(Finding(code=code, severity=severity, message=message))

    stretched = (
        p.payment_to_income_bps > config.stretched_payment_bps
        and p.ltv_bps >= config.stretched_ltv_bps
    )
    if stretched:
        find("stretched", "high",
             f"A payment of {p.payment_to_income_bps / 100:.0f} % of income on "
             f"{p.ltv_bps / 100:.0f} % loan-to-value.")  # fmt: skip
    elif p.ltv_bps >= config.high_ltv_bps:
        find("high_ltv", "medium", f"Loan-to-value {p.ltv_bps / 100:.0f} %.")
    if p.payment_to_estimate_bps > config.estimate_payment_bps:
        find("unaffordable_on_estimate", "high",
             f"The payment is {p.payment_to_estimate_bps / 100:.0f} % of the bureau's income "
             "estimate.")  # fmt: skip
    if p.declared_to_estimate_bps > config.income_gap_bps:
        find("income_gap", "medium",
             f"Declared income is {p.declared_to_estimate_bps / 100:.0f} % of the "
             "estimate.")  # fmt: skip
    if p.credit_score < config.thin_score:
        find("thin_credit", "medium", f"Credit score {p.credit_score}.")
    if p.model_to_price_bps < config.model_gap_bps:
        find("model_below_price", "low",
             f"The automated model values it at {p.model_to_price_bps / 100:.0f} % of the "
             "price.")  # fmt: skip
    rules = 6

    score = sum(SEVERITY_POINTS[f.severity] for f in findings)
    severities = {f.severity for f in findings}
    if severities & {"critical", "high"}:
        classification, recommendation, confidence = "high", "reject", 0.85
    elif score >= 4:
        classification, recommendation, confidence = "medium", "escalate", 0.6
    elif "medium" in severities:
        classification, recommendation, confidence = "medium", "approve", 0.7
    else:
        classification, recommendation = "low", "approve"
        confidence = round(0.92 - 0.04 * len(findings), 2)
    explanation = (
        f"Recommend {recommendation} ({classification} risk, score {score}): "
        + "; ".join(f.message for f in findings)
        if findings
        else "Recommend approve (low risk, score 0): affordable on declared and estimated income."
    )
    return (
        MortgageUnderwritingOutput(
            findings=findings,
            risk_score=score,
            risk_classification=classification,
            recommendation=recommendation,
            confidence=max(confidence, 0.5),
            explanation=explanation,
        ),
        rules,
    )


class MortgageUnderwritingAdapter(AIToolAdapter):
    key = "rule_based_mortgage_underwriting"
    name = "Rule-based mortgage underwriting review"
    provider = "ATLAS Global Bank (in-house, rule-based)"
    description = (
        "Deterministic rule-based review of mortgage applications that passed the lending "
        "rules: stretched payments, affordability on the bureau's income estimate, income "
        "gaps, loan-to-value and credit, with a risk classification, explanation and "
        "recommendation."
    )
    supported_actions = ACTIONS
    input_model = MortgageUnderwritingInput
    output_model = MortgageUnderwritingOutput
    config_model = MortgageUnderwritingConfig

    async def execute(self, request: ToolRequest, context: ToolContext) -> ToolResult:
        data = MortgageUnderwritingInput.model_validate(request.input)
        config = MortgageUnderwritingConfig.model_validate(context.configuration)
        result, rules = analyze(data, config)
        return ToolResult(
            output=result.model_dump(mode="json"),
            usage={"rules_evaluated": rules, "findings": len(result.findings)},
        )
