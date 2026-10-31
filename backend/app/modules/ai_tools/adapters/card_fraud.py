"""AGB Card Fraud Alert Assistant — rule-based proof-of-concept adapter (Phase 32).

Reviews a card the fraud rules blocked, with the card's history that the workflow reads
(`cards.fraud_profile`): the declined purchase, how many purchases the card made over 90
days and their median, earlier high-risk purchases, when the card was first used in the
declined purchase's country, and every attempt in the hour before. It explains the risk
and recommends releasing the block (approve), keeping it (reject) or escalating. It never
releases a card: a fraud analyst decides, then the workflow.

Its rules look for a card used somewhere it has never been, a first high-risk purchase,
an amount far above the usual and a burst of attempts. Its blind spot is card testing: to
ignore coffee-sized noise it leaves out attempts below a small share of the daily limit,
so a burst of tiny test purchases before a high-risk purchase at home looks like a single,
ordinary first high-risk purchase — and it recommends releasing the card.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.modules.ai_tools.adapters.base import (
    AIToolAdapter,
    ToolContext,
    ToolRequest,
    ToolResult,
)
from app.modules.cards.service import HIGH_RISK_CATEGORIES

ACTIONS = frozenset({"recommend_decision"})
SEVERITY_POINTS = {"low": 1, "medium": 2, "high": 3, "critical": 5}


class DeclinedPurchase(BaseModel):
    auth_code: str = Field(min_length=1, max_length=20)
    merchant_name: str = Field(default="", max_length=100)
    merchant_category: str = Field(pattern=r"^\d{4}$")
    merchant_country: str = Field(pattern=r"^[A-Z]{2}$")
    abroad: bool
    amount: int = Field(gt=0)
    fraud_score: int = Field(ge=0)
    fraud_signals: list[str] = Field(default_factory=list, max_length=10)


class CardFraudProfile(BaseModel):
    currency: str = Field(min_length=3, max_length=3)
    home_country: str = Field(pattern=r"^[A-Z]{2}$")
    daily_limit: int = Field(gt=0)
    blocked: DeclinedPurchase | None = None
    purchases_90d: int = Field(ge=0)
    median_amount: int = Field(ge=0)
    high_risk_purchases_90d: int = Field(ge=0)
    country_first_seen_hours: float | None = Field(default=None, ge=0)
    attempts_last_hour: list[int] = Field(default_factory=list, max_length=500)


class CardFraudInput(BaseModel):
    profile: CardFraudProfile


class Finding(BaseModel):
    code: str
    severity: Literal["low", "medium", "high", "critical"]
    message: str


class CardFraudOutput(BaseModel):
    findings: list[Finding]
    risk_score: int = Field(ge=0)
    risk_classification: Literal["low", "medium", "high"]
    recommendation: Literal["approve", "reject", "escalate"]
    confidence: float = Field(ge=0, le=1)
    explanation: str


class CardFraudConfig(BaseModel):
    familiar_after_hours: float = Field(default=24.0, gt=0, le=720)
    unusual_amount_ratio: float = Field(default=5.0, gt=1, le=100)  # × the median purchase
    burst_attempts: int = Field(default=5, ge=2, le=50)
    # Attempts below this share of the daily limit are left out as noise (the blind spot).
    noise_share: float = Field(default=0.02, ge=0, le=0.5)
    thin_history: int = Field(default=5, ge=0, le=100)
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)


def analyze(data: CardFraudInput, config: CardFraudConfig) -> tuple[CardFraudOutput, int]:
    """The rule set. Returns the result and the number of rules evaluated."""
    p = data.profile
    findings: list[Finding] = []

    def find(code: str, severity: str, message: str) -> None:
        findings.append(Finding(code=code, severity=severity, message=message))

    if p.blocked is None:
        find("no_fraud_decline", "medium",
             "No purchase was declined for suspected fraud: a manual block.")  # fmt: skip
        return _result(findings, escalate=True), 1
    b = p.blocked
    if b.abroad and (
        p.country_first_seen_hours is None
        or p.country_first_seen_hours < config.familiar_after_hours
    ):
        find("unfamiliar_country", "high",
             f"The card had not been used in {b.merchant_country} before the last "
             f"{config.familiar_after_hours:.0f} hours.")  # fmt: skip
    if b.merchant_category in HIGH_RISK_CATEGORIES and p.high_risk_purchases_90d == 0:
        find("first_high_risk", "medium",
             f"The first high-risk purchase ({b.merchant_category}) in 90 days.")  # fmt: skip
    if p.median_amount and b.amount > p.median_amount * config.unusual_amount_ratio:
        find("unusual_amount", "medium",
             f"The amount is {b.amount / p.median_amount:.1f}× the usual purchase.")  # fmt: skip
    noise = p.daily_limit * config.noise_share
    burst = [a for a in p.attempts_last_hour if a >= noise]
    if len(burst) >= config.burst_attempts:
        find("burst", "low", f"{len(burst)} attempts in the hour before.")
    if p.purchases_90d < config.thin_history:
        find("thin_history", "medium", f"Only {p.purchases_90d} purchases in 90 days.")
    return _result(findings), 5


def _result(findings: list[Finding], *, escalate: bool = False) -> CardFraudOutput:
    score = sum(SEVERITY_POINTS[f.severity] for f in findings)
    severities = {f.severity for f in findings}
    if severities & {"critical", "high"}:
        classification, recommendation, confidence = "high", "reject", 0.85
    elif escalate or score >= 4:
        classification, recommendation, confidence = "medium", "escalate", 0.6
    elif "medium" in severities:
        classification, recommendation, confidence = "medium", "approve", 0.65
    else:
        classification, recommendation = "low", "approve"
        confidence = round(0.92 - 0.04 * len(findings), 2)
    action = {"approve": "release the block", "reject": "keep the block",
              "escalate": "escalate"}[recommendation]  # fmt: skip
    explanation = (
        f"Recommend {action} ({classification} risk, score {score}): "
        + "; ".join(f.message for f in findings)
        if findings
        else "Recommend release the block (low risk, score 0): it fits the card's history."
    )
    return CardFraudOutput(
        findings=findings,
        risk_score=score,
        risk_classification=classification,
        recommendation=recommendation,
        confidence=max(confidence, 0.5),
        explanation=explanation,
    )


class CardFraudAdapter(AIToolAdapter):
    key = "rule_based_card_fraud_review"
    name = "Rule-based card fraud alert review"
    provider = "ATLAS Global Bank (in-house, rule-based)"
    description = (
        "Deterministic rule-based review of cards blocked by the fraud rules against the "
        "card's history: where it has been used, its usual amounts, earlier high-risk "
        "purchases and bursts of attempts, with a risk classification, explanation and "
        "recommendation."
    )
    supported_actions = ACTIONS
    input_model = CardFraudInput
    output_model = CardFraudOutput
    config_model = CardFraudConfig

    async def execute(self, request: ToolRequest, context: ToolContext) -> ToolResult:
        data = CardFraudInput.model_validate(request.input)
        config = CardFraudConfig.model_validate(context.configuration)
        result, rules = analyze(data, config)
        return ToolResult(
            output=result.model_dump(mode="json"),
            usage={"rules_evaluated": rules, "findings": len(result.findings)},
        )
