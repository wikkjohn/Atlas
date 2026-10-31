"""AGB Back-Office Check Assistant — rule-based proof-of-concept adapter (Phase 40).

Reviews a booked interbank money-market deal before back office confirms it, with the
profile the workflow reads (`treasury.deal_profile`): the rate against the currency's
reference rate, the tenor, the counterparty's rating and how much of its limit the deal
uses, liquidity coverage after a placement, and other deals with the same terms booked the
same day. It explains the risk and recommends confirming (approve), cancelling (reject) or
escalating. It never confirms: back office decides, then the workflow.

Its rules treat a rate far from the market against the bank as an off-market deal, a long
placement with a counterparty at the bottom of investment grade as too much risk, and a
placement that uses most of a counterparty's limit, a tenor beyond 90 days and thin
liquidity cover as concerns. Its blind spot is duplicates: the profile counts deals with
the same counterparty, terms and value date booked the same day, and the assistant never
reads it, so a dealer's double-keyed booking looks like an ordinary deal — and it
recommends confirming it.
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
WEAK_RATINGS = frozenset({"BBB", "BBB-"})  # the bottom of investment grade


class DealProfile(BaseModel):
    kind: Literal["placement", "borrowing"]
    currency: str = Field(min_length=3, max_length=3)
    rate_bps: int = Field(ge=0)
    reference_rate_bps: int = Field(ge=0)
    rate_against_bank_bps: int
    tenor_days: int = Field(ge=1)
    rating: str = Field(max_length=4)
    limit_utilisation_bps: int = Field(default=0, ge=0)
    coverage_after_bps: int | None = None
    same_day_duplicates: int = Field(default=0, ge=0)


class BackOfficeCheckInput(BaseModel):
    profile: DealProfile


class Finding(BaseModel):
    code: str
    severity: Literal["low", "medium", "high", "critical"]
    message: str


class BackOfficeCheckOutput(BaseModel):
    findings: list[Finding]
    risk_score: int = Field(ge=0)
    risk_classification: Literal["low", "medium", "high"]
    recommendation: Literal["approve", "reject", "escalate"]
    confidence: float = Field(ge=0, le=1)
    explanation: str


class BackOfficeCheckConfig(BaseModel):
    off_market_bps: int = Field(default=150, ge=0, le=2000)
    slightly_off_bps: int = Field(default=50, ge=0, le=2000)
    long_tenor_days: int = Field(default=90, ge=1, le=365)
    weak_tenor_days: int = Field(default=180, ge=1, le=365)
    near_limit_bps: int = Field(default=9000, ge=0, le=10_000)
    thin_coverage_bps: int = Field(default=11_000, ge=10_000, le=50_000)
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)


def analyze(
    data: BackOfficeCheckInput, config: BackOfficeCheckConfig
) -> tuple[BackOfficeCheckOutput, int]:
    """The rule set. Returns the result and the number of rules evaluated."""
    p = data.profile
    findings: list[Finding] = []

    def find(code: str, severity: str, message: str) -> None:
        findings.append(Finding(code=code, severity=severity, message=message))

    gap = p.rate_against_bank_bps / 100
    if p.rate_against_bank_bps > config.off_market_bps:
        find("off_market", "high",
             f"{p.rate_bps / 100:.2f} % is {gap:.2f} points from the "
             f"{p.reference_rate_bps / 100:.2f} % reference, against the bank.")  # fmt: skip
    elif p.rate_against_bank_bps > config.slightly_off_bps:
        find("slightly_off", "low", f"The rate is {gap:.2f} points off the reference.")
    placement = p.kind == "placement"
    if placement and p.rating in WEAK_RATINGS and p.tenor_days > config.weak_tenor_days:
        find("weak_name_long_tenor", "high",
             f"{p.tenor_days} days with a counterparty rated {p.rating}.")  # fmt: skip
    if placement and p.limit_utilisation_bps >= config.near_limit_bps:
        find("near_limit", "medium",
             f"The deal takes the counterparty to {p.limit_utilisation_bps / 100:.0f} % of "
             "its limit.")  # fmt: skip
    if p.tenor_days > config.long_tenor_days:
        find("long_tenor", "medium", f"A tenor of {p.tenor_days} days.")
    if (
        placement
        and p.coverage_after_bps is not None
        and (p.coverage_after_bps < config.thin_coverage_bps)
    ):
        cover = p.coverage_after_bps / 100
        find("thin_coverage", "medium", f"Liquidity coverage after the placement: {cover:.0f} %.")
    rules = 6

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
    action = {"approve": "confirm the deal", "reject": "cancel the deal",
              "escalate": "escalate"}[recommendation]  # fmt: skip
    explanation = (
        f"Recommend {action} ({classification} risk, score {score}): "
        + "; ".join(f.message for f in findings)
        if findings
        else "Recommend confirm the deal (low risk, score 0): on market terms."
    )
    return (
        BackOfficeCheckOutput(
            findings=findings,
            risk_score=score,
            risk_classification=classification,
            recommendation=recommendation,
            confidence=max(confidence, 0.5),
            explanation=explanation,
        ),
        rules,
    )


class BackOfficeCheckAdapter(AIToolAdapter):
    key = "rule_based_back_office_check"
    name = "Rule-based back-office deal check"
    provider = "ATLAS Global Bank (in-house, rule-based)"
    description = (
        "Deterministic rule-based check of booked interbank deals before confirmation: the "
        "rate against the market, the tenor, the counterparty's rating and limit use and "
        "liquidity cover, with a risk classification, explanation and a confirm, cancel or "
        "escalate recommendation."
    )
    supported_actions = ACTIONS
    input_model = BackOfficeCheckInput
    output_model = BackOfficeCheckOutput
    config_model = BackOfficeCheckConfig

    async def execute(self, request: ToolRequest, context: ToolContext) -> ToolResult:
        data = BackOfficeCheckInput.model_validate(request.input)
        config = BackOfficeCheckConfig.model_validate(context.configuration)
        result, rules = analyze(data, config)
        return ToolResult(
            output=result.model_dump(mode="json"),
            usage={"rules_evaluated": rules, "findings": len(result.findings)},
        )
