"""AGB Complaint Review Assistant — rule-based proof-of-concept adapter (Phase 52).

Reviews the redress proposed for a complaint before a service manager approves paying it,
with the profile the workflow reads (`service.complaint_profile`): the redress against the
fees the account was actually charged in the last 90 days (and whether one was charged
twice), its size in US dollars, how long the account has been open and the description. It
explains the risk and recommends paying the redress and upholding the complaint (approve),
not upholding it (reject) or referring it on. It never pays anything: the manager decides,
then the workflow.

Its rules uphold a refund of a fee charged twice, a refund no larger than the fees charged
and a small goodwill payment; they reject a fee complaint with no fee charged, redress well
above the fees charged, and a large goodwill payment; they refer a moderate goodwill payment
on. Its blind spot is the customer's history: the profile counts the customer's complaints in
the last year, how many were upheld and the redress already paid, and the assistant never
reads them, so a customer who complains about every fee and is refunded every time looks like
a fair refund — and it recommends paying.
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


class ComplaintProfile(BaseModel):
    topic: str = Field(default="other", max_length=30)
    channel: str = Field(default="phone", max_length=20)
    currency: str = Field(default="USD", max_length=3)
    redress_amount: int = Field(default=0, ge=0)
    redress_usd: int = Field(default=0, ge=0)
    fees_90d: int = Field(default=0, ge=0)
    fees_90d_amount: int = Field(default=0, ge=0)
    duplicate_fee: bool = False
    redress_to_fees_pct: int = Field(default=0, ge=0)
    account_age_days: int = Field(default=0, ge=0)
    description_chars: int = Field(default=0, ge=0)
    prior_complaints_365d: int = Field(default=0, ge=0)
    prior_upheld_365d: int = Field(default=0, ge=0)
    prior_redress_paid_365d_usd: int = Field(default=0, ge=0)


class ComplaintReviewInput(BaseModel):
    profile: ComplaintProfile


class Finding(BaseModel):
    code: str
    severity: Literal["low", "medium", "high", "critical"]
    message: str


class ComplaintReviewOutput(BaseModel):
    findings: list[Finding]
    risk_score: int = Field(ge=0)
    risk_classification: Literal["low", "medium", "high"]
    recommendation: Literal["approve", "reject", "escalate"]
    confidence: float = Field(ge=0, le=1)
    explanation: str


class ComplaintReviewConfig(BaseModel):
    max_refund_pct: int = Field(default=150, ge=100, le=10_000)  # redress against fees charged
    small_goodwill_usd: int = Field(default=50, ge=0)
    large_goodwill_usd: int = Field(default=250, ge=0)
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)


def analyze(data: ComplaintReviewInput, config: ComplaintReviewConfig
            ) -> tuple[ComplaintReviewOutput, int]:  # fmt: skip
    """The rule set. Returns the result and the number of rules evaluated."""
    p = data.profile
    findings: list[Finding] = []

    def find(code: str, severity: str, message: str) -> None:
        findings.append(Finding(code=code, severity=severity, message=message))

    if p.topic == "fees":
        if p.fees_90d == 0:
            find("no_fee_found", "high", "No fee was charged to the account in 90 days.")
        elif p.redress_to_fees_pct > config.max_refund_pct:
            find("exceeds_loss", "high",
                 f"Redress is {p.redress_to_fees_pct} % of the fees charged.")  # fmt: skip
        elif p.duplicate_fee:
            find("duplicate_fee", "low", "A fee was charged twice; the redress refunds it.")
        else:
            find("refund", "low", "The redress refunds fees the account was charged.")
    elif p.redress_usd <= config.small_goodwill_usd:
        find("small_goodwill", "low", f"A goodwill payment of US${p.redress_usd}.")
    elif p.redress_usd <= config.large_goodwill_usd:
        find("moderate_goodwill", "medium", f"A goodwill payment of US${p.redress_usd}.")
    else:
        find("large_goodwill", "high",
             f"A goodwill payment of US${p.redress_usd} with no charge behind it.")  # fmt: skip
    rules = 4

    score = sum(SEVERITY_POINTS[f.severity] for f in findings)
    severities = {f.severity for f in findings}
    if severities & {"critical", "high"}:
        classification, recommendation, confidence = "high", "reject", 0.85
    elif "medium" in severities:
        classification, recommendation, confidence = "medium", "escalate", 0.6
    else:
        classification, recommendation, confidence = "low", "approve", 0.86
    action = {"approve": "pay the redress and uphold", "reject": "not uphold",
              "escalate": "refer it on"}[recommendation]  # fmt: skip
    explanation = (f"Recommend {action} ({classification} risk, score {score}): "
                   + "; ".join(f.message for f in findings))  # fmt: skip
    return (
        ComplaintReviewOutput(
            findings=findings,
            risk_score=score,
            risk_classification=classification,
            recommendation=recommendation,
            confidence=confidence,
            explanation=explanation,
        ),
        rules,
    )


class ComplaintReviewAdapter(AIToolAdapter):
    key = "rule_based_complaint_review"
    name = "Rule-based complaint redress review"
    provider = "ATLAS Global Bank (in-house, rule-based)"
    description = (
        "Deterministic rule-based review of complaint redress: the redress against the fees "
        "the account was charged, a duplicate fee, and the size of a goodwill payment, with a "
        "risk classification, explanation and an uphold, not-uphold or refer recommendation."
    )
    supported_actions = ACTIONS
    input_model = ComplaintReviewInput
    output_model = ComplaintReviewOutput
    config_model = ComplaintReviewConfig

    async def execute(self, request: ToolRequest, context: ToolContext) -> ToolResult:
        data = ComplaintReviewInput.model_validate(request.input)
        config = ComplaintReviewConfig.model_validate(context.configuration)
        result, rules = analyze(data, config)
        return ToolResult(
            output=result.model_dump(mode="json"),
            usage={"rules_evaluated": rules, "findings": len(result.findings)},
        )
