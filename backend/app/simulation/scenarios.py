"""Scenario definitions and workload profiles.

A scenario describes *what* is simulated (which workflow, the mix of applications, how the
simulated staff behave); a profile describes *how much*. Both are versioned code, and each
run stores the fully resolved configuration, so a run can always be reproduced exactly.
"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ApplicationMix(BaseModel):
    """Share of each kind of synthetic application (normalized to sum to 1)."""

    clean: float = 0.70  # legitimate, low risk
    missing_documents: float = 0.06  # legitimate; documents arrive later
    abandoned_documents: float = 0.02  # documents never arrive (times out)
    politically_exposed: float = 0.06  # legitimate but high risk
    name_mismatch: float = 0.05  # legitimate; typo on a document (flagged)
    sanctions_hit: float = 0.04  # must be rejected
    forged_document: float = 0.04  # must be rejected
    underage: float = 0.03  # must be rejected

    def normalized(self) -> dict[str, float]:
        weights = self.model_dump()
        total = sum(weights.values())
        if total <= 0:
            raise ValueError("The application mix must have a positive total.")
        return {kind: weight / total for kind, weight in weights.items()}


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


class ScenarioConfig(BaseModel):
    arrival_window_hours: float = Field(default=8.0, gt=0)  # applications arrive across this
    document_delay_hours: tuple[float, float] = (2.0, 48.0)  # when late documents arrive
    mix: ApplicationMix = Field(default_factory=ApplicationMix)
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


class Scenario(BaseModel):
    scenario_id: str = Field(pattern=r"^[a-z0-9-]+$")
    version: int = Field(ge=1)
    name: str
    description: str
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

# Experiment modes and the WF-0001 v2 AI mode each one runs with.
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
