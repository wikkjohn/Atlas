"""AGB Document Check Assistant — rule-based proof-of-concept adapter (Phase 38).

Reviews a discrepant presentation under a letter of credit before the applicant is asked to
waive the discrepancy, with the profile the workflow reads (`trade.presentation_profile`):
the discrepancy, how much of the credit is drawn, how many days are left before expiry,
whether the applicant can fund the payment, and the credit's earlier presentations. It
explains the risk and recommends paying on the waiver (approve), rejecting the documents
(reject) or escalating. It never pays: a trade officer decides, then the workflow.

Its rules treat a missing document as a risk to the applicant's title to the goods, a late
shipment presented in the last days of the credit as a sign of a beneficiary in trouble,
and an applicant with barely enough to pay as a concern; a late presentation or a wording
mismatch on its own is minor. Its blind spot is the credit's history: the profile counts
earlier presentations rejected for the same discrepancy, and the assistant never reads
them, so a beneficiary presenting the same faulty documents again looks like a first,
minor slip — and it recommends paying.
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
DISCREPANCIES = Literal["none", "late_shipment", "late_presentation", "inconsistent_documents",
                        "missing_document", "description_mismatch"]  # fmt: skip


class PresentationProfile(BaseModel):
    currency: str = Field(min_length=3, max_length=3)
    kind: str = Field(default="letter_of_credit", max_length=20)
    discrepancy: DISCREPANCIES
    discrepancy_count: int = Field(default=1, ge=0)
    draw_share_bps: int = Field(ge=0, le=10_000)
    days_to_expiry: int
    funding_cover_bps: int = Field(ge=0)
    earlier_presentations: int = Field(default=0, ge=0)
    earlier_rejected: int = Field(default=0, ge=0)
    earlier_same_discrepancy: int = Field(default=0, ge=0)


class DocumentCheckInput(BaseModel):
    profile: PresentationProfile


class Finding(BaseModel):
    code: str
    severity: Literal["low", "medium", "high", "critical"]
    message: str


class DocumentCheckOutput(BaseModel):
    findings: list[Finding]
    risk_score: int = Field(ge=0)
    risk_classification: Literal["low", "medium", "high"]
    recommendation: Literal["approve", "reject", "escalate"]
    confidence: float = Field(ge=0, le=1)
    explanation: str


class DocumentCheckConfig(BaseModel):
    last_minute_days: int = Field(default=7, ge=0, le=60)
    thin_cover_bps: int = Field(default=11_000, ge=10_000, le=50_000)  # funds ÷ the payment
    full_draw_bps: int = Field(default=9000, ge=0, le=10_000)
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)


def analyze(
    data: DocumentCheckInput, config: DocumentCheckConfig
) -> tuple[DocumentCheckOutput, int]:
    """The rule set. Returns the result and the number of rules evaluated."""
    p = data.profile
    findings: list[Finding] = []

    def find(code: str, severity: str, message: str) -> None:
        findings.append(Finding(code=code, severity=severity, message=message))

    if p.discrepancy == "missing_document":
        find("title_risk", "high", "A document is missing: without it the applicant may not "
             "be able to take the goods.")  # fmt: skip
    elif p.discrepancy == "late_shipment":
        if p.days_to_expiry <= config.last_minute_days:
            find("last_minute", "high",
                 f"Shipped late and presented {p.days_to_expiry} days before the credit "
                 "expires.")  # fmt: skip
        else:
            find("late_shipment", "medium", "The goods were shipped after the latest date.")
    elif p.discrepancy == "inconsistent_documents":
        severity = "high" if p.draw_share_bps >= config.full_draw_bps else "medium"
        find("inconsistent", severity,
             f"The documents contradict each other on a draw of "
             f"{p.draw_share_bps / 100:.0f} % of the credit.")  # fmt: skip
    elif p.discrepancy in ("late_presentation", "description_mismatch"):
        find("minor", "low", f"A minor discrepancy: {p.discrepancy.replace('_', ' ')}.")
    if p.funding_cover_bps < config.thin_cover_bps:
        cover = p.funding_cover_bps / 10_000
        find("thin_funds", "medium", f"The applicant's funds cover the payment {cover:.2f}×.")
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
    action = {"approve": "pay on the applicant's waiver", "reject": "reject the documents",
              "escalate": "escalate"}[recommendation]  # fmt: skip
    explanation = (
        f"Recommend {action} ({classification} risk, score {score}): "
        + "; ".join(f.message for f in findings)
        if findings
        else "Recommend pay on the applicant's waiver (low risk, score 0)."
    )
    return (
        DocumentCheckOutput(
            findings=findings,
            risk_score=score,
            risk_classification=classification,
            recommendation=recommendation,
            confidence=max(confidence, 0.5),
            explanation=explanation,
        ),
        rules,
    )


class DocumentCheckAdapter(AIToolAdapter):
    key = "rule_based_document_check"
    name = "Rule-based documentary presentation review"
    provider = "ATLAS Global Bank (in-house, rule-based)"
    description = (
        "Deterministic rule-based review of discrepant presentations under letters of credit: "
        "the discrepancy, days to expiry, how much is drawn and whether the applicant can pay, "
        "with a risk classification, explanation and a pay, reject or escalate recommendation."
    )
    supported_actions = ACTIONS
    input_model = DocumentCheckInput
    output_model = DocumentCheckOutput
    config_model = DocumentCheckConfig

    async def execute(self, request: ToolRequest, context: ToolContext) -> ToolResult:
        data = DocumentCheckInput.model_validate(request.input)
        config = DocumentCheckConfig.model_validate(context.configuration)
        result, rules = analyze(data, config)
        return ToolResult(
            output=result.model_dump(mode="json"),
            usage={"rules_evaluated": rules, "findings": len(result.findings)},
        )
