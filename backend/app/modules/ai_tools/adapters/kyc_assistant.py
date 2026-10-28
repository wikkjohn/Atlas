"""AGB Intelligent KYC Assistant — rule-based proof-of-concept adapter.

Analyses a synthetic retail application: structured identity information, the synthetic
documents and any screening results the workflow already has. It reports missing and
inconsistent fields, proposes a risk classification, explains it, and recommends approve,
reject or escalate. It never decides: the workflow's policy engine and authorized people
do. A model-backed adapter can replace this one by implementing the same contract.
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

ACTIONS = frozenset({"analyze_application", "recommend_decision", "complete_low_risk_review"})
DOCUMENT_PREFIX = {"passport": "P", "national_id": "N", "proof_of_address": "A"}
IDENTITY_DOCUMENTS = ("passport", "national_id")
# Input bounds (the same as WF-0001's): they keep the analysis small — name comparison is
# quadratic — so a call finishes well within its timeout, which cannot interrupt
# synchronous work.
MAX_NAME = 200
MAX_DOCUMENTS = 10
SEVERITY_POINTS = {"low": 1, "medium": 2, "high": 3, "critical": 5}


class KycDocument(BaseModel):
    document_type: Literal["passport", "national_id", "proof_of_address"]
    document_number: str = Field(max_length=20)
    name_on_document: str = Field(max_length=MAX_NAME)
    date_of_birth: date | None = None
    expiry_date: date | None = None


class KycApplication(BaseModel):
    applicant_name: str = Field(max_length=MAX_NAME)
    date_of_birth: date
    country_code: str = Field(max_length=2)
    account_type: Literal["current", "savings"] = "current"
    documents: list[KycDocument] = Field(default_factory=list, max_length=MAX_DOCUMENTS)
    politically_exposed: bool = False
    expected_monthly_deposits: int = Field(default=0, ge=0)


class KycScreening(BaseModel):
    """Results the workflow already produced; the assistant takes them into account."""

    sanctions_hit: bool = False


class KycAssistantInput(BaseModel):
    application: KycApplication
    screening: KycScreening = Field(default_factory=KycScreening)
    as_of: date


class Finding(BaseModel):
    code: str
    severity: Literal["low", "medium", "high", "critical"]
    field: str | None = None
    message: str


class KycAssistantOutput(BaseModel):
    findings: list[Finding]
    missing_fields: list[str]
    inconsistencies: list[str]
    risk_score: int = Field(ge=0)
    risk_classification: Literal["low", "medium", "high"]
    recommendation: Literal["approve", "reject", "escalate"]
    confidence: float = Field(ge=0, le=1)
    explanation: str


class KycAssistantConfig(BaseModel):
    name_variation_tolerance: int = Field(default=2, ge=0, le=5)  # edits treated as a typo
    large_deposit_threshold: int = Field(default=50_000, ge=0)  # whole currency units
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)


def _normalize(name: str) -> str:
    return " ".join(name.casefold().split())


def edit_distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def _number_valid(document: KycDocument) -> bool:
    number = document.document_number
    if len(number) != 9 or number[0] != DOCUMENT_PREFIX[document.document_type]:
        return False
    if not number[1:].isdigit():
        return False
    return sum(int(d) for d in number[1:8]) % 10 == int(number[8])


def analyze(data: KycAssistantInput, config: KycAssistantConfig) -> tuple[KycAssistantOutput, int]:
    """The rule set. Returns the result and the number of rules evaluated."""
    app = data.application
    findings: list[Finding] = []
    missing: list[str] = []
    inconsistent: list[str] = []
    rules = 0

    def find(code: str, severity: str, message: str, field_name: str | None = None) -> None:
        findings.append(Finding(code=code, severity=severity, field=field_name, message=message))

    identity = next((d for d in app.documents if d.document_type in IDENTITY_DOCUMENTS), None)
    address = next((d for d in app.documents if d.document_type == "proof_of_address"), None)
    rules += 2
    if identity is None:
        missing.append("identity_document")
        find("missing_identity_document", "high", "No passport or national ID was provided.")
    if address is None:
        missing.append("proof_of_address")
        find("missing_proof_of_address", "medium", "No proof of address was provided.")

    age = (data.as_of - app.date_of_birth).days // 365
    rules += 1
    if age < 18:
        find("underage", "critical", f"The applicant is {age}; the minimum age is 18.")

    applicant = _normalize(app.applicant_name)
    for document in app.documents:
        label = document.document_type
        rules += 2
        if not _number_valid(document):
            inconsistent.append(f"{label}.document_number")
            find(
                "document_number_invalid",
                "critical",
                f"The {label.replace('_', ' ')} number fails its check digit.",
                f"{label}.document_number",
            )
        distance = edit_distance(_normalize(document.name_on_document), applicant)
        if distance:
            inconsistent.append(f"{label}.name_on_document")
            if distance <= config.name_variation_tolerance:
                find(
                    "name_minor_variation",
                    "low",
                    f"The name on the {label.replace('_', ' ')} differs from the application "
                    f"by {distance} character(s), consistent with a typing error.",
                    f"{label}.name_on_document",
                )
            else:
                find(
                    "name_mismatch",
                    "high",
                    f"The name on the {label.replace('_', ' ')} does not match the applicant.",
                    f"{label}.name_on_document",
                )
    if identity is not None:
        rules += 2
        if identity.date_of_birth is None:
            missing.append("identity_document.date_of_birth")
        elif identity.date_of_birth != app.date_of_birth:
            inconsistent.append("identity_document.date_of_birth")
            find(
                "date_of_birth_mismatch",
                "critical",
                "The date of birth on the identity document differs from the application.",
                "identity_document.date_of_birth",
            )
        if identity.expiry_date is None:
            missing.append("identity_document.expiry_date")
        elif identity.expiry_date <= data.as_of:
            find("document_expired", "high", "The identity document has expired.")

    rules += 3
    if data.screening.sanctions_hit:
        find("sanctions_hit", "critical", "Sanctions screening matched the applicant's name.")
    if app.politically_exposed:
        find(
            "politically_exposed",
            "high",
            "The applicant is a politically exposed person; policy requires human review.",
        )
    if app.expected_monthly_deposits > config.large_deposit_threshold:
        find(
            "large_expected_deposits",
            "medium",
            f"Expected monthly deposits of {app.expected_monthly_deposits:,} exceed "
            f"{config.large_deposit_threshold:,}.",
        )

    score = sum(SEVERITY_POINTS[f.severity] for f in findings)
    classification = "low" if score <= 1 else "medium" if score <= 3 else "high"
    severities = {f.severity for f in findings}
    if "critical" in severities:
        recommendation, confidence = "reject", 0.95
    elif severities & {"high", "medium"}:
        recommendation, confidence = "escalate", 0.6
    else:
        recommendation = "approve"
        confidence = round(0.95 - 0.1 * len(findings), 2)

    if findings:
        reasons = "; ".join(f.message for f in findings)
        explanation = (
            f"Recommend {recommendation} ({classification} risk, score {score}): {reasons}"
        )
    else:
        explanation = (
            "Recommend approve (low risk, score 0): documents are complete, valid and "
            "consistent with the application, and screening found nothing."
        )
    return (
        KycAssistantOutput(
            findings=findings,
            missing_fields=missing,
            inconsistencies=inconsistent,
            risk_score=score,
            risk_classification=classification,
            recommendation=recommendation,
            confidence=max(confidence, 0.5),
            explanation=explanation,
        ),
        rules,
    )


class KycAssistantAdapter(AIToolAdapter):
    key = "rule_based_kyc"
    name = "Rule-based KYC analysis"
    provider = "ATLAS Global Bank (in-house, rule-based)"
    description = (
        "Deterministic rule-based analysis of synthetic retail applications: missing and "
        "inconsistent fields, risk classification, explanation and recommendation."
    )
    supported_actions = ACTIONS
    input_model = KycAssistantInput
    output_model = KycAssistantOutput
    config_model = KycAssistantConfig

    async def execute(self, request: ToolRequest, context: ToolContext) -> ToolResult:
        data = KycAssistantInput.model_validate(request.input)
        config = KycAssistantConfig.model_validate(context.configuration)
        result, rules = analyze(data, config)
        return ToolResult(
            output=result.model_dump(mode="json"),
            usage={"rules_evaluated": rules, "findings": len(result.findings)},
        )
