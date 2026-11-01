"""AGB Recall Assistant — rule-based proof-of-concept adapter (Phase 42).

Reviews a recall of a settled payment before back office decides whether to send it to the
beneficiary's bank, with the profile the workflow reads (`clearing.recall_profile`): the
reason and how much of its window is left, the payment's size, whether a matching duplicate
exists, how often the payer has paid this beneficiary before, and the payer's other recalls.
It explains the risk and recommends sending the recall (approve), withdrawing it (reject) or
escalating. It never sends: back office decides, then the workflow.

Its rules withdraw a recall outside its window, a "duplicate" with no matching payment, and
a fraud claim against a beneficiary the payer has paid many times before; a recall close to
the end of its window and a high-value payment are concerns. Its blind spot is the payer:
the profile counts the payer's recalls in the last 90 days and how many were refused, and
the assistant never reads them, so a customer who recalls payment after payment looks like
a first, reasonable request — and it recommends sending the recall.
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


class RecallProfile(BaseModel):
    reason_code: Literal["DUPL", "FRAD", "TECH", "CUST"]
    currency: str = Field(default="", max_length=3)
    amount: int = Field(default=0, ge=0)
    high_value: bool = False
    days_since_settlement: int = Field(ge=0)
    window_days: int = Field(ge=0)
    days_left: int
    duplicate_matches: int = Field(default=0, ge=0)
    payee_history: int = Field(default=0, ge=0)
    payer_recalls_90d: int = Field(default=0, ge=0)
    payer_refused_90d: int = Field(default=0, ge=0)


class RecallReviewInput(BaseModel):
    profile: RecallProfile


class Finding(BaseModel):
    code: str
    severity: Literal["low", "medium", "high", "critical"]
    message: str


class RecallReviewOutput(BaseModel):
    findings: list[Finding]
    risk_score: int = Field(ge=0)
    risk_classification: Literal["low", "medium", "high"]
    recommendation: Literal["approve", "reject", "escalate"]
    confidence: float = Field(ge=0, le=1)
    explanation: str


class RecallReviewConfig(BaseModel):
    established_payee: int = Field(default=3, ge=1, le=100)  # earlier payments to the payee
    near_end_days: int = Field(default=2, ge=0, le=30)
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)


def analyze(data: RecallReviewInput, config: RecallReviewConfig) -> tuple[RecallReviewOutput, int]:
    """The rule set. Returns the result and the number of rules evaluated."""
    p = data.profile
    findings: list[Finding] = []

    def find(code: str, severity: str, message: str) -> None:
        findings.append(Finding(code=code, severity=severity, message=message))

    if p.days_left < 0:
        find("outside_window", "high",
             f"{p.days_since_settlement} days after settlement, beyond the "
             f"{p.window_days}-day window: the beneficiary's bank will refuse.")  # fmt: skip
    elif p.days_left <= config.near_end_days:
        find("near_window_end", "medium", f"Only {p.days_left} days of the window are left.")
    if p.reason_code == "DUPL" and p.duplicate_matches == 0:
        find("no_duplicate_found", "high",
             "No other payment to this account for the same amount: not a duplicate.")  # fmt: skip
    if p.reason_code == "FRAD" and p.payee_history >= config.established_payee:
        find("established_payee", "high",
             f"The payer has paid this beneficiary {p.payee_history} times before.")  # fmt: skip
    if p.high_value:
        find("high_value", "medium", "A high-value payment.")
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
    action = {"approve": "send the recall", "reject": "withdraw the recall",
              "escalate": "escalate"}[recommendation]  # fmt: skip
    explanation = (
        f"Recommend {action} ({classification} risk, score {score}): "
        + "; ".join(f.message for f in findings)
        if findings
        else "Recommend send the recall (low risk, score 0): within its window."
    )
    return (
        RecallReviewOutput(
            findings=findings,
            risk_score=score,
            risk_classification=classification,
            recommendation=recommendation,
            confidence=max(confidence, 0.5),
            explanation=explanation,
        ),
        rules,
    )


class RecallReviewAdapter(AIToolAdapter):
    key = "rule_based_recall_review"
    name = "Rule-based payment recall review"
    provider = "ATLAS Global Bank (in-house, rule-based)"
    description = (
        "Deterministic rule-based review of recalls of settled payments: the reason's window, "
        "matching duplicates, the payer's history with the beneficiary and the payment's size, "
        "with a risk classification, explanation and a send, withdraw or escalate "
        "recommendation."
    )
    supported_actions = ACTIONS
    input_model = RecallReviewInput
    output_model = RecallReviewOutput
    config_model = RecallReviewConfig

    async def execute(self, request: ToolRequest, context: ToolContext) -> ToolResult:
        data = RecallReviewInput.model_validate(request.input)
        config = RecallReviewConfig.model_validate(context.configuration)
        result, rules = analyze(data, config)
        return ToolResult(
            output=result.model_dump(mode="json"),
            usage={"rules_evaluated": rules, "findings": len(result.findings)},
        )
