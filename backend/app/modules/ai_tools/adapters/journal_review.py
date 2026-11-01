"""AGB Journal Review Assistant — rule-based proof-of-concept adapter (Phase 50).

Reviews a manual journal before a second person posts it, with the profile the workflow
reads (`finance.journal_profile`): its size against materiality, the kinds of account it
touches, how far back it is dated, a round amount, its description and an identical journal
posted recently. It explains the risk and recommends posting (approve), rejecting or
referring it on. It never posts anything: the approver decides, then the workflow.

Its rules reject a journal straight to equity, a duplicate of a recent journal, one dated
more than a month back or into a closed month, a round cash journal with no real description,
and a material journal without a full description; they refer a well-described material
journal on, and pass routine accruals and reclassifications. Its blind spot is the preparer's
week: the profile counts the preparer's other journals on the same accounts in the last seven
days and their total, and the assistant never reads them, so a large entry split into pieces
each just under materiality looks like a run of routine accruals — and it recommends posting.
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


class JournalProfile(BaseModel):
    currency: str = Field(default="", max_length=3)
    amount: int = Field(default=0, ge=0)
    amount_usd: int = Field(default=0, ge=0)
    materiality_pct: int = Field(default=0, ge=0)
    lines: int = Field(default=2, ge=0)
    account_types: list[str] = Field(default_factory=list)
    touches_equity: bool = False
    touches_income: bool = False
    touches_cash: bool = False
    effective_date: str = Field(default="", max_length=10)
    days_backdated: int = Field(default=0, ge=0)
    in_closed_period: bool = False
    round_amount: bool = False
    description_chars: int = Field(default=0, ge=0)
    duplicate_of: str | None = Field(default=None, max_length=20)
    same_accounts_7d: int = Field(default=0, ge=0)
    same_accounts_7d_usd: int = Field(default=0, ge=0)


class JournalReviewInput(BaseModel):
    profile: JournalProfile


class Finding(BaseModel):
    code: str
    severity: Literal["low", "medium", "high", "critical"]
    message: str


class JournalReviewOutput(BaseModel):
    findings: list[Finding]
    risk_score: int = Field(ge=0)
    risk_classification: Literal["low", "medium", "high"]
    recommendation: Literal["approve", "reject", "escalate"]
    confidence: float = Field(ge=0, le=1)
    explanation: str


class JournalReviewConfig(BaseModel):
    stale_days: int = Field(default=31, ge=1, le=3650)
    documented_chars: int = Field(default=40, ge=1, le=300)
    vague_chars: int = Field(default=20, ge=1, le=300)
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)


def analyze(data: JournalReviewInput, config: JournalReviewConfig
            ) -> tuple[JournalReviewOutput, int]:  # fmt: skip
    """The rule set. Returns the result and the number of rules evaluated."""
    p = data.profile
    findings: list[Finding] = []

    def find(code: str, severity: str, message: str) -> None:
        findings.append(Finding(code=code, severity=severity, message=message))

    if p.touches_equity:
        find("equity_adjustment", "high", "Posts straight to equity.")
    if p.duplicate_of:
        find("duplicate", "high", f"Identical to {p.duplicate_of}, posted recently.")
    if p.in_closed_period:
        find("closed_period", "high", f"Dated {p.effective_date}, in a closed month.")
    elif p.days_backdated > config.stale_days:
        find("stale", "high", f"Dated {p.days_backdated} days back.")
    if p.touches_cash and p.round_amount and p.description_chars < config.vague_chars:
        find("unexplained_cash", "high", "A round cash amount with no real description.")
    if p.materiality_pct >= 100:
        if p.description_chars >= config.documented_chars:
            find("material", "medium", f"Material ({p.materiality_pct} % of the threshold).")
        else:
            find("material_undocumented", "high",
                 f"Material ({p.materiality_pct} % of the threshold) with a "
                 f"{p.description_chars}-character description.")  # fmt: skip
    if not findings:
        find("routine", "low", "A routine journal on the bank's own accounts.")
    rules = 6

    score = sum(SEVERITY_POINTS[f.severity] for f in findings)
    severities = {f.severity for f in findings}
    if severities & {"critical", "high"}:
        classification, recommendation, confidence = "high", "reject", 0.85
    elif "medium" in severities:
        classification, recommendation, confidence = "medium", "escalate", 0.6
    else:
        classification, recommendation, confidence = "low", "approve", 0.86
    action = {"approve": "post it", "reject": "reject it",
              "escalate": "refer it on"}[recommendation]  # fmt: skip
    explanation = (f"Recommend {action} ({classification} risk, score {score}): "
                   + "; ".join(f.message for f in findings))  # fmt: skip
    return (
        JournalReviewOutput(
            findings=findings,
            risk_score=score,
            risk_classification=classification,
            recommendation=recommendation,
            confidence=confidence,
            explanation=explanation,
        ),
        rules,
    )


class JournalReviewAdapter(AIToolAdapter):
    key = "rule_based_journal_review"
    name = "Rule-based manual journal review"
    provider = "ATLAS Global Bank (in-house, rule-based)"
    description = (
        "Deterministic rule-based review of manual journals: size against materiality, "
        "equity, cash and income accounts, backdating, round amounts, the description and "
        "recent duplicates, with a risk classification, explanation and a post, reject or "
        "refer recommendation."
    )
    supported_actions = ACTIONS
    input_model = JournalReviewInput
    output_model = JournalReviewOutput
    config_model = JournalReviewConfig

    async def execute(self, request: ToolRequest, context: ToolContext) -> ToolResult:
        data = JournalReviewInput.model_validate(request.input)
        config = JournalReviewConfig.model_validate(context.configuration)
        result, rules = analyze(data, config)
        return ToolResult(
            output=result.model_dump(mode="json"),
            usage={"rules_evaluated": rules, "findings": len(result.findings)},
        )
