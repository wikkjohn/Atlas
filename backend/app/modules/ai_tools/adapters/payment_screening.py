"""AGB Payment Fraud Screener — rule-based proof-of-concept adapter.

Reviews a domestic payment that the payment workflow's screening has held: the payment
itself and the screening signals the workflow computed. It explains the risk, classifies
it and recommends approve (release), reject or escalate. It never releases or rejects a
payment: fraud reviewers, approvers and the workflow's policy engine do. Like every rule
set it has blind spots — a scam with an ordinary-looking reference looks like a legitimate
first payment — which is exactly what experiments are meant to expose.
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

ACTIONS = frozenset({"analyze_payment", "recommend_decision", "complete_low_risk_review"})
SEVERITY_POINTS = {"low": 1, "medium": 2, "high": 3, "critical": 5}
# Synthetic scam phrases (fictional training list, not a real fraud typology database).
DEFAULT_SCAM_PHRASES = (
    "gift card",
    "crypto",
    "lottery",
    "investment opportunity",
    "release fee",
    "customs fee",
    "safe account",
)


class PaymentFacts(BaseModel):
    amount: int = Field(ge=1)
    currency: str = Field(min_length=3, max_length=3)
    reference: str = Field(max_length=140)
    channel: Literal["branch", "online", "mobile"] = "online"
    high_value: bool = False


class PaymentSignals(BaseModel):
    """Signals the workflow's screening already produced."""

    sanctions_hit: bool = False
    new_payee: bool = False
    recent_payments_24h: int = Field(default=0, ge=0)
    share_of_balance: float = Field(default=0, ge=0)  # amount / balance before the payment


class PaymentScreeningInput(BaseModel):
    payment: PaymentFacts
    signals: PaymentSignals = Field(default_factory=PaymentSignals)
    as_of: date


class Finding(BaseModel):
    code: str
    severity: Literal["low", "medium", "high", "critical"]
    message: str


class PaymentScreeningOutput(BaseModel):
    findings: list[Finding]
    risk_score: int = Field(ge=0)
    risk_classification: Literal["low", "medium", "high"]
    recommendation: Literal["approve", "reject", "escalate"]
    confidence: float = Field(ge=0, le=1)
    explanation: str


class PaymentScreeningConfig(BaseModel):
    scam_phrases: list[str] = Field(
        default_factory=lambda: list(DEFAULT_SCAM_PHRASES), max_length=100
    )
    drain_share: float = Field(default=0.8, gt=0, le=1)  # of the balance in one payment
    velocity_limit: int = Field(default=3, ge=1, le=100)  # payments in 24 hours
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)


def analyze(
    data: PaymentScreeningInput, config: PaymentScreeningConfig
) -> tuple[PaymentScreeningOutput, int]:
    """The rule set. Returns the result and the number of rules evaluated."""
    payment, signals = data.payment, data.signals
    findings: list[Finding] = []

    def find(code: str, severity: str, message: str) -> None:
        findings.append(Finding(code=code, severity=severity, message=message))

    reference = " ".join(payment.reference.casefold().split())
    phrase = next((p for p in config.scam_phrases if p.casefold() in reference), None)
    if signals.sanctions_hit:
        find("sanctions_hit", "critical", "The payee matched the synthetic sanctions watchlist.")
    if phrase:
        find(
            "scam_reference",
            "high",
            f"The reference mentions '{phrase}', typical of authorised push-payment scams.",
        )
    if signals.share_of_balance >= config.drain_share:
        find(
            "drains_account",
            "medium",
            f"The payment moves {signals.share_of_balance:.0%} of the account balance.",
        )
    if signals.recent_payments_24h >= config.velocity_limit:
        find(
            "velocity",
            "medium",
            f"{signals.recent_payments_24h} other payments in the last 24 hours.",
        )
    if signals.new_payee:
        find("new_payee", "low", "First payment from this account to this payee.")
    if payment.high_value:
        find("high_value", "low", "High-value payment; a second approval is required anyway.")
    rules = 6

    score = sum(SEVERITY_POINTS[f.severity] for f in findings)
    severities = {f.severity for f in findings}
    if severities & {"critical", "high"}:
        classification, recommendation, confidence = "high", "reject", 0.9
    elif score >= 5:
        classification, recommendation, confidence = "medium", "escalate", 0.6
    else:
        # Behavioural signals alone are common for legitimate first payments.
        classification, recommendation = "low", "approve"
        confidence = round(0.9 - 0.05 * len(findings), 2)
    explanation = (
        f"Recommend {recommendation} ({classification} risk, score {score}): "
        + "; ".join(f.message for f in findings)
        if findings
        else "Recommend approve (low risk, score 0): no screening signal applies."
    )
    return (
        PaymentScreeningOutput(
            findings=findings,
            risk_score=score,
            risk_classification=classification,
            recommendation=recommendation,
            confidence=max(confidence, 0.5),
            explanation=explanation,
        ),
        rules,
    )


class PaymentScreeningAdapter(AIToolAdapter):
    key = "rule_based_payment_screening"
    name = "Rule-based payment fraud screening"
    provider = "ATLAS Global Bank (in-house, rule-based)"
    description = (
        "Deterministic rule-based review of held synthetic payments: scam indicators, "
        "behavioural signals, risk classification, explanation and recommendation."
    )
    supported_actions = ACTIONS
    input_model = PaymentScreeningInput
    output_model = PaymentScreeningOutput
    config_model = PaymentScreeningConfig

    async def execute(self, request: ToolRequest, context: ToolContext) -> ToolResult:
        data = PaymentScreeningInput.model_validate(request.input)
        config = PaymentScreeningConfig.model_validate(context.configuration)
        result, rules = analyze(data, config)
        return ToolResult(
            output=result.model_dump(mode="json"),
            usage={"rules_evaluated": rules, "findings": len(result.findings)},
        )
