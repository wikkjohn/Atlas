"""AGB Credit Underwriting Assistant — rule-based proof-of-concept adapter.

Reviews a personal loan application that the credit policy has referred to an underwriter:
the application, the synthetic bureau file, the affordability figures and the income
verification the workflow computed. It explains the credit risk, classifies it and
recommends approve, reject or escalate. It never approves or declines a loan: underwriters,
the credit committee and the workflow's policy engine do.

Its strongest rule compares the declared income with the bureau's income estimate, which
catches inflated incomes. Its blind spot is the same rule: honest self-employed applicants
whose irregular income runs above the estimate look like inflated ones — exactly what an
experiment is meant to expose.
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

ACTIONS = frozenset(
    {"analyze_credit_application", "recommend_decision", "complete_low_risk_review"}
)
SEVERITY_POINTS = {"low": 1, "medium": 2, "high": 3, "critical": 5}


class LoanFacts(BaseModel):
    amount: int = Field(ge=1)
    currency: str = Field(min_length=3, max_length=3)
    term_months: int = Field(ge=1, le=600)
    purpose: str = Field(max_length=40)
    employment_status: Literal["employed", "self_employed", "unemployed", "retired"]
    monthly_income: int = Field(ge=0, description="Declared, minor units")
    monthly_debt_payments: int = Field(ge=0, description="Declared, minor units")


class BureauFile(BaseModel):
    score: int = Field(ge=300, le=850)
    recent_defaults: int = Field(default=0, ge=0)
    open_credit_lines: int = Field(default=0, ge=0)


class Affordability(BaseModel):
    annual_rate_bps: int | None = Field(default=None, ge=0)
    monthly_payment: int | None = Field(default=None, ge=0)
    debt_to_income: float | None = Field(default=None, ge=0)
    committee_required: bool = False


class IncomeCheck(BaseModel):
    estimated_monthly_income: int | None = Field(default=None, ge=0)
    # Declared income / the bureau estimate; None when no estimate exists.
    declared_to_estimate: float | None = Field(default=None, ge=0)


class CreditUnderwritingInput(BaseModel):
    application: LoanFacts
    bureau: BureauFile
    affordability: Affordability = Field(default_factory=Affordability)
    income: IncomeCheck = Field(default_factory=IncomeCheck)
    as_of: date


class Finding(BaseModel):
    code: str
    severity: Literal["low", "medium", "high", "critical"]
    message: str


class CreditUnderwritingOutput(BaseModel):
    findings: list[Finding]
    risk_score: int = Field(ge=0)
    risk_classification: Literal["low", "medium", "high"]
    recommendation: Literal["approve", "reject", "escalate"]
    confidence: float = Field(ge=0, le=1)
    explanation: str


class CreditUnderwritingConfig(BaseModel):
    income_overstated_ratio: float = Field(default=1.4, gt=1, le=5)  # declared / estimate
    income_unverified_ratio: float = Field(default=1.15, gt=1, le=5)
    thin_margin_score: int = Field(default=660, ge=300, le=850)
    stretched_debt_to_income: float = Field(default=0.35, gt=0, le=1)
    many_credit_lines: int = Field(default=5, ge=1, le=50)
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)


def analyze(
    data: CreditUnderwritingInput, config: CreditUnderwritingConfig
) -> tuple[CreditUnderwritingOutput, int]:
    """The rule set. Returns the result and the number of rules evaluated."""
    app, bureau, afford, income = data.application, data.bureau, data.affordability, data.income
    findings: list[Finding] = []

    def find(code: str, severity: str, message: str) -> None:
        findings.append(Finding(code=code, severity=severity, message=message))

    ratio = income.declared_to_estimate
    if ratio is None:
        find("income_unverifiable", "medium", "No income estimate is available to compare.")
    elif ratio >= config.income_overstated_ratio:
        find(
            "income_overstated",
            "high",
            f"Declared income is {ratio:.1f}× the bureau's estimate; it looks inflated.",
        )
    elif ratio >= config.income_unverified_ratio:
        find(
            "income_above_estimate",
            "medium",
            f"Declared income is {ratio:.2f}× the bureau's estimate.",
        )
    if bureau.recent_defaults >= 1:
        find("recent_default", "medium", f"{bureau.recent_defaults} recent default on file.")
    if bureau.score < config.thin_margin_score:
        find("near_prime_score", "medium", f"Bureau score {bureau.score} is near-prime.")
    if (
        afford.debt_to_income is not None
        and afford.debt_to_income > config.stretched_debt_to_income
    ):
        find(
            "stretched_affordability",
            "medium",
            f"Debt-to-income after the loan is {afford.debt_to_income:.0%}.",
        )
    if app.employment_status == "self_employed":
        find("self_employed", "low", "Self-employed income varies from month to month.")
    if bureau.open_credit_lines >= config.many_credit_lines:
        find("many_credit_lines", "low", f"{bureau.open_credit_lines} open credit lines.")
    if afford.committee_required:
        find("committee_loan", "low", "Above the committee limit; a committee must also approve.")
    rules = 7

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
        else "Recommend approve (low risk, score 0): income matches the estimate and the "
        "bureau file is clean."
    )
    return (
        CreditUnderwritingOutput(
            findings=findings,
            risk_score=score,
            risk_classification=classification,
            recommendation=recommendation,
            confidence=max(confidence, 0.5),
            explanation=explanation,
        ),
        rules,
    )


class CreditUnderwritingAdapter(AIToolAdapter):
    key = "rule_based_credit_underwriting"
    name = "Rule-based credit underwriting review"
    provider = "ATLAS Global Bank (in-house, rule-based)"
    description = (
        "Deterministic rule-based review of referred synthetic loan applications: income "
        "against the bureau estimate, bureau file, affordability, risk classification, "
        "explanation and recommendation."
    )
    supported_actions = ACTIONS
    input_model = CreditUnderwritingInput
    output_model = CreditUnderwritingOutput
    config_model = CreditUnderwritingConfig

    async def execute(self, request: ToolRequest, context: ToolContext) -> ToolResult:
        data = CreditUnderwritingInput.model_validate(request.input)
        config = CreditUnderwritingConfig.model_validate(context.configuration)
        result, rules = analyze(data, config)
        return ToolResult(
            output=result.model_dump(mode="json"),
            usage={"rules_evaluated": rules, "findings": len(result.findings)},
        )
