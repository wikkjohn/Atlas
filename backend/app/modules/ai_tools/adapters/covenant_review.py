"""AGB Covenant Breach Assistant — rule-based proof-of-concept adapter (Phase 36).

Reviews a facility whose covenant test was breached, with the profile the workflow reads
(`commercial.breach_profile`): the period's DSCR and leverage against their thresholds,
how EBITDA moved over the last periods, how much of the facility is drawn, and the
facility's earlier breaches and waivers. It explains the risk and recommends waiving the
breach (approve), keeping the facility frozen (reject) or escalating. It never waives: the
credit committee decides, then the workflow.

Its rules look for a severe shortfall in debt service cover, leverage well above its
limit, EBITDA falling period after period, thin cover and a facility drawn to its limit,
and treat a breach close to its threshold as a mild one. Its blind spot is history: the
profile counts the facility's earlier breaches and waivers, and the assistant never reads
them, so a business breaching again a year after a waiver looks like a first, marginal
breach — and it recommends another waiver.
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


class BreachProfile(BaseModel):
    currency: str = Field(min_length=3, max_length=3)
    facility_type: str = Field(default="", max_length=20)
    dscr_centi: int = Field(ge=0)
    dscr_threshold_centi: int = Field(ge=0)
    leverage_centi: int = Field(ge=0)
    leverage_threshold_centi: int = Field(ge=0)
    ebitda_change_bps: int
    previous_ebitda_change_bps: int = 0
    consecutive_declines: int = Field(default=0, ge=0)
    utilisation_bps: int = Field(ge=0, le=10_000)
    periods_tested: int = Field(default=1, ge=1)
    previous_breaches: int = Field(default=0, ge=0)
    previous_waivers: int = Field(default=0, ge=0)


class CovenantReviewInput(BaseModel):
    profile: BreachProfile


class Finding(BaseModel):
    code: str
    severity: Literal["low", "medium", "high", "critical"]
    message: str


class CovenantReviewOutput(BaseModel):
    findings: list[Finding]
    risk_score: int = Field(ge=0)
    risk_classification: Literal["low", "medium", "high"]
    recommendation: Literal["approve", "reject", "escalate"]
    confidence: float = Field(ge=0, le=1)
    explanation: str


class CovenantReviewConfig(BaseModel):
    severe_dscr_centi: int = Field(default=100, ge=0, le=1000)
    thin_dscr_centi: int = Field(default=110, ge=0, le=1000)
    leverage_tolerance: float = Field(default=1.25, ge=1, le=3)  # × the threshold
    decline_bps: int = Field(default=-1500, le=0)  # a fall of 15 % or more
    full_utilisation_bps: int = Field(default=9000, ge=0, le=10_000)
    marginal_share: float = Field(default=0.9, gt=0, le=1)  # DSCR ≥ 90 % of its threshold
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)


def analyze(
    data: CovenantReviewInput, config: CovenantReviewConfig
) -> tuple[CovenantReviewOutput, int]:
    """The rule set. Returns the result and the number of rules evaluated."""
    p = data.profile
    findings: list[Finding] = []

    def find(code: str, severity: str, message: str) -> None:
        findings.append(Finding(code=code, severity=severity, message=message))

    dscr_breached = p.dscr_threshold_centi and p.dscr_centi < p.dscr_threshold_centi
    if p.dscr_centi < config.severe_dscr_centi:
        find("severe_shortfall", "high",
             f"EBITDA covers debt service {p.dscr_centi / 100:.2f}×: short of it.")  # fmt: skip
    elif p.dscr_centi < config.thin_dscr_centi:
        find("thin_cover", "medium", f"Debt service cover of {p.dscr_centi / 100:.2f}×.")
    elif dscr_breached and p.dscr_centi >= p.dscr_threshold_centi * config.marginal_share:
        find("marginal", "low",
             f"DSCR {p.dscr_centi / 100:.2f}× is close to its "
             f"{p.dscr_threshold_centi / 100:.2f}× threshold.")  # fmt: skip
    if p.leverage_threshold_centi and (
        p.leverage_centi > p.leverage_threshold_centi * config.leverage_tolerance
    ):
        find("leverage_far_over", "high",
             f"Leverage of {p.leverage_centi / 100:.2f}× against "
             f"{p.leverage_threshold_centi / 100:.2f}×.")  # fmt: skip
    if (
        p.consecutive_declines >= 2
        and p.ebitda_change_bps <= config.decline_bps
        and p.previous_ebitda_change_bps <= config.decline_bps
    ):
        find("structural_decline", "high",
             f"EBITDA fell {-p.ebitda_change_bps / 100:.0f} % after falling "
             f"{-p.previous_ebitda_change_bps / 100:.0f} % the period before.")  # fmt: skip
    if p.utilisation_bps >= config.full_utilisation_bps:
        find("fully_drawn", "medium",
             f"{p.utilisation_bps / 100:.0f} % of the facility is drawn.")  # fmt: skip
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
    action = {"approve": "waive the breach", "reject": "keep the facility frozen",
              "escalate": "escalate"}[recommendation]  # fmt: skip
    explanation = (
        f"Recommend {action} ({classification} risk, score {score}): "
        + "; ".join(f.message for f in findings)
        if findings
        else "Recommend waive the breach (low risk, score 0): a one-off dip."
    )
    return (
        CovenantReviewOutput(
            findings=findings,
            risk_score=score,
            risk_classification=classification,
            recommendation=recommendation,
            confidence=max(confidence, 0.5),
            explanation=explanation,
        ),
        rules,
    )


class CovenantReviewAdapter(AIToolAdapter):
    key = "rule_based_covenant_review"
    name = "Rule-based covenant breach review"
    provider = "ATLAS Global Bank (in-house, rule-based)"
    description = (
        "Deterministic rule-based review of covenant breaches on commercial facilities: "
        "debt service cover, leverage, the EBITDA trend and how much is drawn, with a risk "
        "classification, explanation and a waive, keep frozen or escalate recommendation."
    )
    supported_actions = ACTIONS
    input_model = CovenantReviewInput
    output_model = CovenantReviewOutput
    config_model = CovenantReviewConfig

    async def execute(self, request: ToolRequest, context: ToolContext) -> ToolResult:
        data = CovenantReviewInput.model_validate(request.input)
        config = CovenantReviewConfig.model_validate(context.configuration)
        result, rules = analyze(data, config)
        return ToolResult(
            output=result.model_dump(mode="json"),
            usage={"rules_evaluated": rules, "findings": len(result.findings)},
        )
