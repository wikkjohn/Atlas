"""Scenario definitions and workload profiles.

A scenario describes *what* is simulated (which workflow, the mix of applications, how the
simulated staff behave); a profile describes *how much*. Both are versioned code, and each
run stores the fully resolved configuration, so a run can always be reproduced exactly.
"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ApplicationMix(BaseModel):
    """Retail onboarding: share of each kind of synthetic application (normalized)."""

    clean: float = 0.70  # legitimate, low risk
    missing_documents: float = 0.06  # legitimate; documents arrive later
    abandoned_documents: float = 0.02  # documents never arrive (times out)
    politically_exposed: float = 0.06  # legitimate but high risk
    name_mismatch: float = 0.05  # legitimate; typo on a document (flagged)
    sanctions_hit: float = 0.04  # must be rejected
    forged_document: float = 0.04  # must be rejected
    underage: float = 0.03  # must be rejected


class ReviewerModel(BaseModel):
    """How simulated reviewers perform one kind of review."""

    mean_minutes: float = Field(gt=0)
    sigma: float = Field(default=0.5, ge=0, le=2)  # lognormal spread
    accuracy: float = Field(default=0.95, ge=0, le=1)  # P(decision matches ground truth)


class AIAssistanceModel(BaseModel):
    """ASSUMPTIONS (not measurements) about how an AI summary changes human review.

    They are part of the scenario configuration, stored with every run and shown with every
    result, so a reader can see — and change — what the simulated benefit rests on.
    """

    review_time_factor: float = Field(default=0.6, gt=0, le=2)  # share of the usual time
    accuracy_when_ai_correct: float = Field(default=0.99, ge=0, le=1)
    accuracy_when_ai_wrong: float = Field(default=0.80, ge=0, le=1)  # automation bias


def normalized(mix: dict[str, float]) -> dict[str, float]:
    total = sum(mix.values())
    if total <= 0 or any(weight < 0 for weight in mix.values()):
        raise ValueError("A case mix needs non-negative weights with a positive total.")
    return {kind: weight / total for kind, weight in mix.items()}


class ScenarioConfig(BaseModel):
    arrival_window_hours: float = Field(default=8.0, gt=0)  # cases arrive across this
    # When late documents arrive (None: the workload has no document waits).
    document_delay_hours: tuple[float, float] | None = (2.0, 48.0)
    # Share of each kind of case; the kinds belong to the scenario's workload.
    mix: dict[str, float] = Field(default_factory=lambda: ApplicationMix().model_dump())
    reviewers: dict[str, ReviewerModel] = Field(
        default_factory=lambda: {
            "account_approval": ReviewerModel(mean_minutes=12, accuracy=0.97),
            "compliance_review": ReviewerModel(mean_minutes=35, accuracy=0.93),
        }
    )
    # Share of simulated staff by role: tellers start cases, managers and compliance review.
    staff_mix: dict[str, float] = Field(
        default_factory=lambda: {"teller": 0.4, "manager": 0.4, "compliance": 0.2}
    )
    # Present when the scenario supports AI experiment modes.
    ai_assistance: AIAssistanceModel | None = None
    # A country whose business days cases arrive on (Phase 26): an arrival on a weekend or
    # holiday there moves to the same time on the next business day. None: any day.
    business_calendar: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    # Cases follow the rules of their customer's country (Phase 28): ages, documents and
    # sanctions names for onboarding; amounts against the high-value threshold and the
    # payment limit for payments. None keeps the original, country-blind generators.
    country_rules: bool | None = None


class Scenario(BaseModel):
    scenario_id: str = Field(pattern=r"^[a-z0-9-]+$")
    version: int = Field(ge=1)
    name: str
    description: str
    # How cases are generated, staffed and checked (see `app.simulation.workloads`).
    workload: str = "retail_onboarding"
    workflow_id: str
    workflow_version: int = Field(ge=1)  # pinned: a scenario version never changes meaning
    simulated_start: datetime  # fixed, so simulated timestamps are reproducible
    config: ScenarioConfig


class Profile(BaseModel):
    profile_id: str
    name: str
    applications: int = Field(ge=1)
    employees: int = Field(ge=3)
    # "verified": exercised end to end in this repository. "target": a configuration goal
    # whose performance has NOT been measured; it must be confirmed explicitly to run.
    status: Literal["verified", "target"]
    note: str = ""
    # Parallel shards the profile needs at least (Phase 16): one process is too slow.
    min_shards: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _customers(self) -> "Profile":
        return self

    @property
    def customers(self) -> int:
        # Every application registers one new synthetic customer.
        return self.applications


SCENARIOS: dict[tuple[str, int], Scenario] = {}


def register_scenario(scenario: Scenario) -> None:
    SCENARIOS[(scenario.scenario_id, scenario.version)] = scenario


def get_scenario(scenario_id: str, version: int | None = None) -> Scenario | None:
    if version is not None:
        return SCENARIOS.get((scenario_id, version))
    versions = [v for (sid, v) in SCENARIOS if sid == scenario_id]
    return SCENARIOS[(scenario_id, max(versions))] if versions else None


register_scenario(
    Scenario(
        scenario_id="retail-onboarding",
        version=1,
        name="Retail account onboarding",
        description="A working day of synthetic retail applications through WF-0001, with a "
        "realistic mix of clean, high-risk, incomplete and fraudulent cases and simulated "
        "reviewers who take time and occasionally make mistakes.",
        workflow_id="WF-0001",
        workflow_version=1,
        simulated_start=datetime(2026, 1, 5, 9, 0, tzinfo=UTC),
        config=ScenarioConfig(),
    )
)

register_scenario(
    Scenario(
        scenario_id="retail-onboarding",
        version=2,
        name="Retail account onboarding (AI experiments)",
        description="The version 1 working day on WF-0001 v2, which can run without AI "
        "(baseline), with the KYC assistant preparing summaries for human reviewers "
        "(AI assisted), or with the policy engine approving low-risk cases the assistant "
        "recommends (AI automated tasks). Same applications and staff in every mode.",
        workflow_id="WF-0001",
        workflow_version=2,
        simulated_start=datetime(2026, 1, 5, 9, 0, tzinfo=UTC),
        config=ScenarioConfig(ai_assistance=AIAssistanceModel()),
    )
)

register_scenario(
    Scenario(
        scenario_id="domestic-payments",
        version=1,
        name="Domestic payments (fraud screening)",
        description="A working day of synthetic payments through WF-0002: routine payments "
        "to known payees, first payments, high-value transfers, authorised push-payment "
        "scams (some with tell-tale references, some without), payments to watchlisted "
        "payees and payments without funds. Fraud analysts review held payments and "
        "managers approve high-value ones; the AI fraud screener can assist them or let the "
        "policy engine release low-risk holds.",
        workload="domestic_payments",
        workflow_id="WF-0002",
        workflow_version=1,
        simulated_start=datetime(2026, 1, 6, 8, 0, tzinfo=UTC),
        config=ScenarioConfig(
            arrival_window_hours=10.0,
            document_delay_hours=None,
            mix={
                "routine": 0.50,
                "new_payee": 0.15,
                "high_value": 0.08,
                "large_share": 0.07,
                "scam": 0.08,
                "quiet_scam": 0.04,
                "watchlisted_payee": 0.03,
                "insufficient_funds": 0.05,
            },
            reviewers={
                "fraud_review": ReviewerModel(mean_minutes=20, accuracy=0.90),
                "payment_approval": ReviewerModel(mean_minutes=8, accuracy=0.97),
            },
            staff_mix={"teller": 0.4, "manager": 0.3, "compliance": 0.3},
            ai_assistance=AIAssistanceModel(),
        ),
    )
)

register_scenario(
    Scenario(
        scenario_id="payments-easter",
        version=1,
        name="Payments over the Easter weekend (business calendar)",
        description="The domestic-payments workload instructed across four days from Maundy "
        "Thursday 2026, on the UK business calendar: customers arrive on Thursday and the "
        "rest of their payments wait for Tuesday, because Good Friday, the weekend and Easter "
        "Monday are not business days (Phase 26).",
        workload="domestic_payments",
        workflow_id="WF-0002",
        workflow_version=1,
        simulated_start=datetime(2026, 4, 2, 8, 0, tzinfo=UTC),
        config=ScenarioConfig(
            arrival_window_hours=96.0,
            document_delay_hours=None,
            mix={
                "routine": 0.55,
                "new_payee": 0.15,
                "high_value": 0.08,
                "large_share": 0.07,
                "scam": 0.07,
                "watchlisted_payee": 0.03,
                "insufficient_funds": 0.05,
            },
            reviewers={
                "fraud_review": ReviewerModel(mean_minutes=20, accuracy=0.90),
                "payment_approval": ReviewerModel(mean_minutes=8, accuracy=0.97),
            },
            staff_mix={"teller": 0.4, "manager": 0.3, "compliance": 0.3},
            business_calendar="GB",
        ),
    )
)

# The Milestone C exit (Phase 28): the same workflows in any active country, with cases that
# follow each country's rules and reviewers who always decide correctly, so every outcome
# that differs from the ground truth is the workflow's or the rules', not a person's.
PERFECT = 1.0

register_scenario(
    Scenario(
        scenario_id="global-onboarding",
        version=1,
        name="Retail onboarding in every country (country rules)",
        description="WF-0001 applications that follow the applicant's country's rules: ages "
        "around its minimum age, its accepted identity documents, a proof of address only "
        "where required and names from the sanctions lists it screens against. Reviewers "
        "always decide correctly, so each outcome tests the workflow and the rules (Phase 28).",
        workflow_id="WF-0001",
        workflow_version=1,
        simulated_start=datetime(2026, 3, 2, 9, 0, tzinfo=UTC),
        config=ScenarioConfig(
            arrival_window_hours=4.0,
            document_delay_hours=(1.0, 8.0),
            reviewers={
                "account_approval": ReviewerModel(mean_minutes=12, accuracy=PERFECT),
                "compliance_review": ReviewerModel(mean_minutes=35, accuracy=PERFECT),
            },
            country_rules=True,
        ),
    )
)

register_scenario(
    Scenario(
        scenario_id="global-payments",
        version=1,
        name="Domestic payments in every country (country rules)",
        description="WF-0002 payments on each payer's country's scale: ordinary payments "
        "below its high-value threshold, high-value ones between the threshold and its "
        "payment limit, and watchlisted payees from the lists it screens against. Reviewers "
        "always decide correctly; the quiet scams no rule can catch are left out (Phase 28).",
        workload="domestic_payments",
        workflow_id="WF-0002",
        workflow_version=1,
        simulated_start=datetime(2026, 3, 3, 8, 0, tzinfo=UTC),
        config=ScenarioConfig(
            arrival_window_hours=4.0,
            document_delay_hours=None,
            mix={
                "routine": 0.45,
                "new_payee": 0.15,
                "high_value": 0.15,
                "large_share": 0.07,
                "scam": 0.08,
                "watchlisted_payee": 0.05,
                "insufficient_funds": 0.05,
            },
            reviewers={
                "fraud_review": ReviewerModel(mean_minutes=20, accuracy=PERFECT),
                "payment_approval": ReviewerModel(mean_minutes=8, accuracy=PERFECT),
            },
            staff_mix={"teller": 0.4, "manager": 0.3, "compliance": 0.3},
            country_rules=True,
        ),
    )
)

register_scenario(
    Scenario(
        scenario_id="personal-loans",
        version=1,
        name="Personal loan origination",
        description="A working day of synthetic loan applications through WF-0003 from "
        "existing customers: prime and near-prime borrowers, large loans for the credit "
        "committee, poor credit and over-indebted applicants the policy declines, and "
        "applications with inflated income that only an underwriter can catch.",
        workload="personal_loans",
        workflow_id="WF-0003",
        workflow_version=1,
        simulated_start=datetime(2026, 1, 7, 9, 0, tzinfo=UTC),
        config=ScenarioConfig(
            document_delay_hours=None,
            mix={
                "prime": 0.40,
                "near_prime": 0.15,
                "self_employed": 0.05,
                "large_loan": 0.10,
                "poor_credit": 0.10,
                "overextended": 0.10,
                "inflated_income": 0.10,
            },
            reviewers={
                "underwriting_review": ReviewerModel(mean_minutes=25, accuracy=0.93),
                "credit_committee": ReviewerModel(mean_minutes=30, accuracy=0.97),
            },
            staff_mix={"teller": 0.4, "manager": 0.45, "executive": 0.15},
        ),
    )
)

register_scenario(
    Scenario(
        scenario_id="personal-loans",
        version=2,
        name="Personal loan origination (AI experiments)",
        description="The version 1 working day on WF-0003 v2, where declared incomes can be "
        "checked against the bureau's income estimate. It can run without AI (baseline), "
        "with the AI underwriting assistant preparing a recommendation for underwriters "
        "(AI assisted), or with the policy engine underwriting small, clean loans the "
        "assistant rates low risk (AI automated tasks). Same applicants in every mode.",
        workload="personal_loans_income",
        workflow_id="WF-0003",
        workflow_version=2,
        simulated_start=datetime(2026, 1, 7, 9, 0, tzinfo=UTC),
        config=ScenarioConfig(
            document_delay_hours=None,
            mix={
                "prime": 0.40,
                "near_prime": 0.15,
                "self_employed": 0.05,
                "large_loan": 0.10,
                "poor_credit": 0.10,
                "overextended": 0.10,
                "inflated_income": 0.10,
            },
            reviewers={
                "underwriting_review": ReviewerModel(mean_minutes=25, accuracy=0.93),
                "credit_committee": ReviewerModel(mean_minutes=30, accuracy=0.97),
            },
            staff_mix={"teller": 0.4, "manager": 0.45, "executive": 0.15},
            ai_assistance=AIAssistanceModel(),
        ),
    )
)

# Experiment modes and the AI mode each one runs with.
MODES: dict[str, str] = {"baseline": "off", "ai_assisted": "assisted", "ai_automated": "automated"}

PROFILES: dict[str, Profile] = {
    p.profile_id: p
    for p in (
        Profile(
            profile_id="small",
            name="Small test",
            applications=100,
            employees=25,
            status="verified",
        ),
        Profile(
            profile_id="department",
            name="Department test",
            applications=10_000,
            employees=500,
            status="verified",
            note="Measured in this repository; see docs/simulation.md for timings.",
        ),
        Profile(
            profile_id="large",
            name="Large test (sharded)",
            applications=100_000,
            employees=5_000,
            status="verified",
            min_shards=4,
            note="Runs as parallel shards across worker processes (at least 4); see "
            "docs/performance.md for the measured time.",
        ),
        Profile(
            profile_id="enterprise",
            name="Future enterprise scale",
            applications=1_000_000,
            employees=150_000,
            status="target",
            note="A configuration target only. Its performance has not been measured; the "
            "current single-process runner is not expected to complete it in practical time.",
        ),
    )
}

MAX_CUSTOM_APPLICATIONS = 10_000
MAX_CUSTOM_EMPLOYEES = 500
# A run splits into at most this many parallel shards: each pins its own one of the 8
# balance rows every ledger account has (`ledger.models.BALANCE_SHARDS`), so shards never
# contend for a busy account's balance.
MAX_SHARDS = 8
