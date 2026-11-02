"""AGB Invoice Review Assistant — rule-based proof-of-concept adapter (Phase 58).

Reviews a matched vendor invoice before someone releases its payment, with the profile the
workflow reads (`procurement.invoice_profile`): the amount, the vendor's age, tier and any
change to its bank details (and whether anything has been paid to the new account since),
whether the invoice is dated before its order, and how far the invoiced total runs over what
was received. It explains the risk and recommends paying, rejecting or referring the invoice
on. It never pays anything: the approver decides, then the workflow.

Its rules reject an invoice to a bank account changed in the last 30 days with nothing paid
to it yet (the classic invoice-fraud route) and an invoice dated before its order; they
refer on invoices running over what was received, large first invoices from new vendors and
high-risk vendors, and recommend paying the rest. Its blind spot is the vendor's history:
the profile counts the vendor's other invoices in the last 90 days and how many were for the
same amount, and the assistant never reads them, so the same bill sent again under a new
reference looks like any routine invoice, and it recommends paying.
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


class InvoiceProfile(BaseModel):
    amount: int = Field(default=0, ge=0)
    currency: str = Field(default="USD", max_length=3)
    amount_usd: int = Field(default=0, ge=0)
    vendor_category: str = Field(default="facilities", max_length=30)
    vendor_risk_tier: Literal["low", "medium", "high"] = "low"
    vendor_age_days: int = Field(default=365)
    bank_changed_days_ago: int | None = None
    paid_since_bank_change: int | None = None
    invoice_before_order: bool = False
    invoice_age_days: int = Field(default=0)
    partial_delivery: bool = False
    over_received_bps: int = Field(default=0, ge=0)
    vendor_invoices_90d: int = Field(default=0, ge=0)
    same_amount_invoices_90d: int = Field(default=0, ge=0)


class InvoiceReviewInput(BaseModel):
    profile: InvoiceProfile


class Finding(BaseModel):
    code: str
    severity: Literal["low", "medium", "high", "critical"]
    message: str


class InvoiceReviewOutput(BaseModel):
    findings: list[Finding]
    risk_score: int = Field(ge=0)
    risk_classification: Literal["low", "medium", "high"]
    recommendation: Literal["approve", "reject", "escalate"]
    confidence: float = Field(ge=0, le=1)
    explanation: str


class InvoiceReviewConfig(BaseModel):
    recent_bank_change_days: int = Field(default=30, ge=0)
    new_vendor_days: int = Field(default=30, ge=0)
    new_vendor_large_usd: int = Field(default=10_000, ge=0)
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)


def analyze(
    data: InvoiceReviewInput, config: InvoiceReviewConfig
) -> tuple[InvoiceReviewOutput, int]:
    """The rule set. Returns the result and the number of rules evaluated."""
    p = data.profile
    findings: list[Finding] = []

    def find(code: str, severity: str, message: str) -> None:
        findings.append(Finding(code=code, severity=severity, message=message))

    if (p.bank_changed_days_ago is not None
            and p.bank_changed_days_ago < config.recent_bank_change_days
            and not p.paid_since_bank_change):  # fmt: skip
        find("recent_bank_change", "high",
             f"The vendor's bank account changed {p.bank_changed_days_ago} days ago and "
             "nothing has been paid to it yet: confirm it with the vendor first.")  # fmt: skip
    if p.invoice_before_order:
        find("dated_before_order", "high", "The invoice is dated before the order was raised.")
    if p.over_received_bps > 0:
        over = p.over_received_bps / 100
        find("over_received", "medium", f"Invoiced runs {over:.2f} % over what was received.")
    if p.vendor_age_days < config.new_vendor_days and p.amount_usd >= config.new_vendor_large_usd:
        find("new_vendor_large", "medium",
             f"US${p.amount_usd:,} from a vendor registered {p.vendor_age_days} days "
             "ago.")  # fmt: skip
    if p.vendor_risk_tier == "high":
        find("high_risk_vendor", "medium", f"A high-risk {p.vendor_category} vendor.")
    if not findings:
        find("routine", "low", f"US${p.amount_usd:,} matched to the order and receipt.")
    rules = 5

    score = sum(SEVERITY_POINTS[f.severity] for f in findings)
    severities = {f.severity for f in findings}
    if severities & {"critical", "high"}:
        classification, recommendation, confidence = "high", "reject", 0.84
    elif "medium" in severities:
        classification, recommendation, confidence = "medium", "escalate", 0.6
    else:
        classification, recommendation, confidence = "low", "approve", 0.86
    action = {"approve": "pay the invoice", "reject": "reject the invoice",
              "escalate": "refer it on"}[recommendation]  # fmt: skip
    explanation = (f"Recommend {action} ({classification} risk, score {score}): "
                   + "; ".join(f.message for f in findings))  # fmt: skip
    return (
        InvoiceReviewOutput(
            findings=findings,
            risk_score=score,
            risk_classification=classification,
            recommendation=recommendation,
            confidence=confidence,
            explanation=explanation,
        ),
        rules,
    )


class InvoiceReviewAdapter(AIToolAdapter):
    key = "rule_based_invoice_review"
    name = "Rule-based invoice review"
    provider = "ATLAS Global Bank (in-house, rule-based)"
    description = (
        "Deterministic rule-based review of a vendor invoice before payment: recent bank-"
        "detail changes, invoices dated before their order, invoicing over what was "
        "received, large first invoices and high-risk vendors, with a risk classification, "
        "explanation and a pay, reject or refer recommendation."
    )
    supported_actions = ACTIONS
    input_model = InvoiceReviewInput
    output_model = InvoiceReviewOutput
    config_model = InvoiceReviewConfig

    async def execute(self, request: ToolRequest, context: ToolContext) -> ToolResult:
        data = InvoiceReviewInput.model_validate(request.input)
        config = InvoiceReviewConfig.model_validate(context.configuration)
        result, rules = analyze(data, config)
        return ToolResult(
            output=result.model_dump(mode="json"),
            usage={"rules_evaluated": rules, "findings": len(result.findings)},
        )
