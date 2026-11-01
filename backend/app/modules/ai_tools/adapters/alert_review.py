"""AGB Alert Review Assistant — rule-based proof-of-concept adapter (Phase 46).

Reviews an AML alert under investigation before a second compliance officer decides whether
its case may be closed with no action, with the profile the workflow reads
(`compliance.alert_profile`): the rule and the amount against the reporting threshold, the
customer's type and risk rating, the window's money in against the account's own baseline,
and reports already filed on the customer. It explains the risk and recommends closing
(approve), escalating to a suspicious activity report (reject) or referring it on
(escalate). It never closes or files anything: the officer decides, then the workflow.

Its rules escalate structuring, money passed through at four times the account's usual
level, a high-risk customer's turnover at three times it, and any customer with a report
already filed; they close a business's cash in line with its usual takings, a one-off large
deposit and a pass-through pattern the account always has. Its blind spot is the alert
history: the profile counts the customer's earlier alerts in the last year (closed or
dismissed), and the assistant never reads it, so a customer whose cash keeps setting off
alerts looks like a business banking its usual takings — and it recommends closing.
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


class AlertProfile(BaseModel):
    rule: Literal["large_cash", "structuring", "rapid_movement", "high_risk_turnover"]
    score: int = Field(default=0, ge=0, le=100)
    currency: str = Field(default="", max_length=3)
    amount: int = Field(default=0, ge=0)
    amount_x_threshold_pct: int = Field(default=0, ge=0)
    deposits: int = Field(default=0, ge=0)
    customer_type: Literal["individual", "business"] = "individual"
    customer_risk: str = Field(default="low", max_length=20)
    credits: int = Field(default=0, ge=0)
    baseline_monthly_credits: int = Field(default=0, ge=0)
    activity_vs_baseline_pct: int = Field(default=0, ge=0)
    prior_alerts_365d: int = Field(default=0, ge=0)
    prior_reports_filed: int = Field(default=0, ge=0)


class AlertReviewInput(BaseModel):
    profile: AlertProfile


class Finding(BaseModel):
    code: str
    severity: Literal["low", "medium", "high", "critical"]
    message: str


class AlertReviewOutput(BaseModel):
    findings: list[Finding]
    risk_score: int = Field(ge=0)
    risk_classification: Literal["low", "medium", "high"]
    recommendation: Literal["approve", "reject", "escalate"]
    confidence: float = Field(ge=0, le=1)
    explanation: str


class AlertReviewConfig(BaseModel):
    funnel_pct: int = Field(default=400, ge=100, le=10_000)  # pass-through vs baseline
    usual_pct: int = Field(default=200, ge=100, le=10_000)
    high_risk_pct: int = Field(default=300, ge=100, le=10_000)
    business_usual_pct: int = Field(default=150, ge=100, le=10_000)
    business_spike_pct: int = Field(default=250, ge=100, le=10_000)
    large_amount_pct: int = Field(default=300, ge=100, le=10_000)  # of the threshold
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)


def analyze(data: AlertReviewInput, config: AlertReviewConfig) -> tuple[AlertReviewOutput, int]:
    """The rule set. Returns the result and the number of rules evaluated."""
    p = data.profile
    findings: list[Finding] = []
    activity = p.activity_vs_baseline_pct

    def find(code: str, severity: str, message: str) -> None:
        findings.append(Finding(code=code, severity=severity, message=message))

    if p.rule == "structuring":
        find("structuring_pattern", "high",
             f"{p.deposits} cash deposits just under the reporting threshold.")  # fmt: skip
    elif p.rule == "rapid_movement":
        if activity >= config.funnel_pct:
            find("funnel", "high", f"Money passed through at {activity} % of the account's "
                                   "usual level.")  # fmt: skip
        elif activity <= config.usual_pct:
            find("usual_pattern", "low", "The account moves money through like this every month.")
        else:
            find("pass_through", "medium", f"Money passed through at {activity} % of usual.")
    elif p.rule == "high_risk_turnover":
        if activity >= config.high_risk_pct:
            find("high_risk_spike", "high",
                 f"A high-risk customer's money in at {activity} % of usual.")  # fmt: skip
        else:
            find("high_risk_turnover", "medium", "A high-risk customer's usual turnover.")
    elif p.customer_type == "business":
        if activity <= config.business_usual_pct:
            find("consistent_takings", "low", "Cash in line with the business's usual takings.")
        elif activity >= config.business_spike_pct:
            find("business_spike", "medium", f"The business's money in at {activity} % of usual.")
            if p.amount_x_threshold_pct >= config.large_amount_pct:
                share = p.amount_x_threshold_pct
                find("large_amount", "medium", f"{share} % of the reporting threshold in cash.")
    elif p.deposits <= 1:
        find("one_off", "low", "A single large deposit.")
    else:
        find("repeated_cash", "medium", f"{p.deposits} large cash deposits.")
    if p.prior_reports_filed:
        find("previous_report", "high",
             f"{p.prior_reports_filed} report(s) already filed on the customer.")  # fmt: skip
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
    action = {"approve": "close with no action", "reject": "escalate to a report",
              "escalate": "refer it on"}[recommendation]  # fmt: skip
    explanation = (
        f"Recommend {action} ({classification} risk, score {score}): "
        + "; ".join(f.message for f in findings)
        if findings
        else "Recommend close with no action (low risk, score 0)."
    )
    return (
        AlertReviewOutput(
            findings=findings,
            risk_score=score,
            risk_classification=classification,
            recommendation=recommendation,
            confidence=max(confidence, 0.5),
            explanation=explanation,
        ),
        rules,
    )


class AlertReviewAdapter(AIToolAdapter):
    key = "rule_based_alert_review"
    name = "Rule-based AML alert review"
    provider = "ATLAS Global Bank (in-house, rule-based)"
    description = (
        "Deterministic rule-based review of AML alerts under investigation: the rule, the "
        "activity against the account's own baseline, the customer's type and risk, and reports "
        "already filed, with a risk classification, explanation and a close, escalate-to-report "
        "or refer recommendation."
    )
    supported_actions = ACTIONS
    input_model = AlertReviewInput
    output_model = AlertReviewOutput
    config_model = AlertReviewConfig

    async def execute(self, request: ToolRequest, context: ToolContext) -> ToolResult:
        data = AlertReviewInput.model_validate(request.input)
        config = AlertReviewConfig.model_validate(context.configuration)
        result, rules = analyze(data, config)
        return ToolResult(
            output=result.model_dump(mode="json"),
            usage={"rules_evaluated": rules, "findings": len(result.findings)},
        )
