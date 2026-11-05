"""Scenario definitions and workload profiles.

A scenario describes *what* is simulated (which workflow, the mix of applications, how the
simulated staff behave); a profile describes *how much*. Both are versioned code, and each
run stores the fully resolved configuration, so a run can always be reproduced exactly.
"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.simulation.arrivals import ArrivalEvent, ArrivalPattern


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
    # On cases that should be rejected, when it differs (Phase 82: calibrated reviewers
    # can be better at one than the other). None: `accuracy` for both, as before.
    accuracy_should_reject: float | None = Field(default=None, ge=0, le=1)


class AIAssistanceModel(BaseModel):
    """ASSUMPTIONS (not measurements) about how an AI summary changes human review.

    They are part of the scenario configuration, stored with every run and shown with every
    result, so a reader can see — and change — what the simulated benefit rests on.
    """

    review_time_factor: float = Field(default=0.6, gt=0, le=10)  # share of the usual time
    accuracy_when_ai_correct: float = Field(default=0.99, ge=0, le=1)
    accuracy_when_ai_wrong: float = Field(default=0.80, ge=0, le=1)  # automation bias


def normalized(mix: dict[str, float]) -> dict[str, float]:
    total = sum(mix.values())
    if total <= 0 or any(weight < 0 for weight in mix.values()):
        raise ValueError("A case mix needs non-negative weights with a positive total.")
    return {kind: weight / total for kind, weight in mix.items()}


class StaffSchedule(BaseModel):
    """When simulated reviewers work (Phase 70): shifts in a country's time zone, its
    business days, and absences. See `app.simulation.staffing`."""

    country: str = Field(default="US", pattern=r"^[A-Z]{2}$")  # time zone and holidays
    # (start hour, hours) in local time, given out to reviewers in turn.
    shifts: list[tuple[int, int]] = Field(default_factory=lambda: [(8, 8), (12, 8)])
    absence_rate: float = Field(default=0.05, ge=0, lt=1)  # per reviewer and working day

    @model_validator(mode="after")
    def _shifts_valid(self) -> "StaffSchedule":
        if not self.shifts or any(not 0 <= h <= 23 or not 1 <= n <= 12 for h, n in self.shifts):
            raise ValueError("Each shift starts at hour 0 to 23 and lasts 1 to 12 hours.")
        return self


class ScenarioOutage(BaseModel):
    """An application outage on the scenario's own timeline (Phase 67): it applies only to
    the run's executions."""

    application: str = Field(min_length=1, max_length=150)  # by name, e.g. "Payments Gateway"
    kind: Literal["down", "degraded"] = "down"
    start_hours: float = Field(ge=0)  # after the scenario's simulated start
    minutes: int = Field(gt=0, le=7 * 24 * 60)


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
    # Application outages during the run (Phase 67). None keeps older scenarios' configs,
    # and so their hashes, unchanged.
    outages: list[ScenarioOutage] | None = None
    # Reviewers' working time (Phase 70). None: they work around the clock, as before.
    staff_schedule: StaffSchedule | None = None
    # When in the window cases arrive (Phase 73): daily and weekly peaks, seasonality and
    # events, in a country's local time. None: evenly over the window, as before.
    arrival_pattern: ArrivalPattern | None = None


class Scenario(BaseModel):
    scenario_id: str = Field(pattern=r"^[a-z0-9-]+$")
    version: int = Field(ge=1)
    name: str
    description: str
    # How cases are generated, staffed and checked (see `app.simulation.workloads`).
    workload: str = "retail_onboarding"
    workflow_id: str
    workflow_version: int = Field(ge=1)  # pinned: a scenario version never changes meaning
    # Phase 83: a template whose variant for the run's one country is the workflow run
    # (`workflow_id` is then the process it was templated from). None: `workflow_id` itself.
    workflow_template: str | None = Field(default=None, pattern=r"^TPL-[A-Z0-9-]+$")
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

register_scenario(
    Scenario(
        scenario_id="retail-overdrafts",
        version=1,
        name="Arranged overdraft requests (retail banking)",
        description="A working day of arranged-overdraft requests through WF-1003 v2 from "
        "existing customers with three months of account history: affordable requests from "
        "steady earners, limits large against income, irregular income, customers already "
        "living in an overdraft, and limits above the product's maximum. Credit officers "
        "decide; in AI-assisted runs the AGB Overdraft Affordability Assistant advises them "
        "(Phase 30).",
        workload="retail_overdrafts",
        workflow_id="WF-1003",
        workflow_version=2,
        simulated_start=datetime(2026, 4, 7, 9, 0, tzinfo=UTC),
        config=ScenarioConfig(
            arrival_window_hours=8.0,
            document_delay_hours=None,
            mix={
                "steady_small": 0.45,
                "steady_large": 0.20,
                "stretched": 0.12,
                "habitual_overdraft": 0.10,
                "irregular_income": 0.07,
                "over_maximum": 0.06,
            },
            reviewers={"credit_decision": ReviewerModel(mean_minutes=15, accuracy=0.92)},
            staff_mix={"teller": 0.5, "manager": 0.5},
            ai_assistance=AIAssistanceModel(),
        ),
    )
)

# The Milestone G exit (Phase 83): the same overdraft requests, each run through its
# country's own workflow — the variant of TPL-OVERDRAFT-REQUEST generated for that country —
# so one tool can be evaluated across one workflow per country.
register_scenario(
    Scenario(
        scenario_id="retail-overdrafts-country",
        version=1,
        name="Arranged overdraft requests, each country's workflow",
        description="The arranged-overdraft workload of retail-overdrafts, run in one country "
        "at a time through that country's variant of TPL-OVERDRAFT-REQUEST (its own "
        "workflow, owner and decision deadline), with customers and staff from that country. "
        "Choose one country per run (Phase 83).",
        workload="retail_overdrafts",
        workflow_id="WF-1003",
        workflow_version=2,
        workflow_template="TPL-OVERDRAFT-REQUEST",
        simulated_start=datetime(2026, 4, 7, 9, 0, tzinfo=UTC),
        config=get_scenario("retail-overdrafts", 1).config.model_copy(deep=True),
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
            min_shards=8,
            note="Not yet completed end to end. Measured at its settings (150,000 staff, 8 "
            "shards, rolling archive): 100,000 cases in 80 min (20.8 cases/s); a million "
            "would take about 13.4 hours here. See docs/performance.md.",
        ),
    )
}

MAX_CUSTOM_APPLICATIONS = 10_000
MAX_CUSTOM_EMPLOYEES = 500
# A run splits into at most this many parallel shards: each pins its own one of the 8
# balance rows every ledger account has (`ledger.models.BALANCE_SHARDS`), so shards never
# contend for a busy account's balance.
MAX_SHARDS = 8


register_scenario(
    Scenario(
        scenario_id="card-fraud-alerts",
        version=1,
        name="Card fraud alerts (cards)",
        description="A working day of cards blocked by the fraud rules, reviewed through WF-1008 "
        "v2. Each card's history is built through the real authorisation service, so the real "
        "fraud rules decline the last purchase: travellers at a casino (some for a large "
        "amount), a regular crypto buyer buying in a hurry, stolen cards used abroad, account "
        "takeovers spending fast in a new country, and card testing at home. Card fraud "
        "analysts decide; in AI-assisted runs the AGB Card Fraud Alert Assistant advises them "
        "(Phase 32).",
        workload="card_fraud_alerts",
        workflow_id="WF-1008",
        workflow_version=2,
        simulated_start=datetime(2026, 5, 12, 9, 0, tzinfo=UTC),
        config=ScenarioConfig(
            arrival_window_hours=8.0,
            document_delay_hours=None,
            mix={
                "traveller": 0.30,
                "big_spender_abroad": 0.08,
                "crypto_investor": 0.15,
                "stolen_abroad": 0.22,
                "account_takeover": 0.13,
                "card_testing": 0.12,
            },
            reviewers={"fraud_review": ReviewerModel(mean_minutes=12, accuracy=0.88)},
            staff_mix={"teller": 0.5, "manager": 0.5},
            ai_assistance=AIAssistanceModel(),
        ),
    )
)


register_scenario(
    Scenario(
        scenario_id="mortgage-applications",
        version=1,
        name="Mortgage applications (mortgages)",
        description="A working day of mortgage applications through WF-1009 v2 that pass every "
        "lending rule, so an underwriter decides each: prime borrowers, strong borrowers at a "
        "high loan-to-value, stretched borrowers, income declared well above the bureau's "
        "estimate, thin credit files and terms running far past retirement. Underwriters "
        "decide; in AI-assisted runs the AGB Mortgage Underwriting Assistant advises them "
        "(Phase 34).",
        workload="mortgage_applications",
        workflow_id="WF-1009",
        workflow_version=2,
        simulated_start=datetime(2026, 6, 2, 9, 0, tzinfo=UTC),
        config=ScenarioConfig(
            arrival_window_hours=8.0,
            document_delay_hours=None,
            mix={
                "prime": 0.35,
                "high_ltv_strong": 0.15,
                "stretched": 0.12,
                "inflated_income": 0.12,
                "thin_credit": 0.12,
                "retirement_term": 0.14,
            },
            reviewers={"underwriting": ReviewerModel(mean_minutes=25, accuracy=0.88)},
            staff_mix={"teller": 0.5, "manager": 0.5},
            ai_assistance=AIAssistanceModel(),
        ),
    )
)


register_scenario(
    Scenario(
        scenario_id="covenant-breaches",
        version=1,
        name="Covenant breaches (commercial lending)",
        description="A working day of covenant breaches through WF-1013 v2: businesses with a "
        "revolving facility and two years of covenant tests submit this year's figures, which "
        "breach. One-off dips and near misses are worth waiving; EBITDA falling year after "
        "year, leverage far over its limit, a second breach after a waiver and thin cover on a "
        "fully drawn facility are not. The credit committee decides; in AI-assisted runs the "
        "AGB Covenant Breach Assistant advises it (Phase 36).",
        workload="covenant_breaches",
        workflow_id="WF-1013",
        workflow_version=2,
        simulated_start=datetime(2026, 4, 14, 9, 0, tzinfo=UTC),
        config=ScenarioConfig(
            arrival_window_hours=8.0,
            document_delay_hours=None,
            mix={
                "one_off_dip": 0.25,
                "seasonal_borderline": 0.20,
                "structural_decline": 0.15,
                "over_leveraged": 0.13,
                "repeat_breach": 0.17,
                "stretched_facility": 0.10,
            },
            reviewers={"committee_review": ReviewerModel(mean_minutes=40, accuracy=0.85)},
            staff_mix={"teller": 0.4, "manager": 0.2, "executive": 0.4},
            ai_assistance=AIAssistanceModel(),
        ),
    )
)


register_scenario(
    Scenario(
        scenario_id="discrepant-presentations",
        version=1,
        name="Discrepant presentations (trade finance)",
        description="A working day of discrepant documents under letters of credit through "
        "WF-1016 v2: each presentation goes to a trade officer, who decides whether to pay on "
        "the applicant's waiver. A late presentation or a wording slip is worth paying; a "
        "missing document, a late shipment presented in the last days of the credit, the same "
        "faulty documents presented again after a rejection, and a late shipment the applicant "
        "can barely pay for are not. In AI-assisted runs the AGB Document Check Assistant "
        "advises the officer (Phase 38).",
        workload="discrepant_presentations",
        workflow_id="WF-1016",
        workflow_version=2,
        simulated_start=datetime(2026, 5, 12, 9, 0, tzinfo=UTC),
        config=ScenarioConfig(
            arrival_window_hours=8.0,
            document_delay_hours=None,
            mix={
                "late_presentation": 0.25,
                "wording_slip": 0.20,
                "missing_document": 0.15,
                "last_minute_shipment": 0.13,
                "repeat_discrepancy": 0.17,
                "stretched_applicant": 0.10,
            },
            reviewers={"applicant_waiver": ReviewerModel(mean_minutes=30, accuracy=0.85)},
            staff_mix={"teller": 0.5, "manager": 0.5},
            ai_assistance=AIAssistanceModel(),
        ),
    )
)


register_scenario(
    Scenario(
        scenario_id="deal-confirmations",
        version=1,
        name="Deal confirmations (treasury back office)",
        description="A working day of interbank deals through WF-1018 v2: dealers book "
        "placements and borrowings, and back office decides whether to confirm each one. "
        "Deals on market terms are confirmed; an off-market rate against the bank, a long "
        "placement with a counterparty at the bottom of investment grade, a dealer's "
        "double-keyed duplicate and a long placement that uses almost all of a counterparty's "
        "limit are cancelled. In AI-assisted runs the AGB Back-Office Check Assistant advises "
        "back office (Phase 40).",
        workload="deal_confirmations",
        workflow_id="WF-1018",
        workflow_version=2,
        simulated_start=datetime(2026, 6, 9, 9, 0, tzinfo=UTC),
        config=ScenarioConfig(
            arrival_window_hours=8.0,
            document_delay_hours=None,
            mix={
                "standard_placement": 0.25,
                "standard_borrowing": 0.20,
                "off_market_rate": 0.15,
                "weak_counterparty": 0.13,
                "duplicate_booking": 0.17,
                "stretched_counterparty": 0.10,
            },
            reviewers={"back_office": ReviewerModel(mean_minutes=20, accuracy=0.85)},
            staff_mix={"teller": 0.5, "manager": 0.5},
            ai_assistance=AIAssistanceModel(),
        ),
    )
)


register_scenario(
    Scenario(
        scenario_id="recall-triage",
        version=1,
        name="Recall triage (payments operations)",
        description="A working day of recalls of settled payments to other banks through WF-1023 "
        "v2: back office decides whether to send each recall to the beneficiary's bank. A "
        "genuine duplicate and a fraud reported within a day are worth sending; a claimed "
        "duplicate with no matching payment, a fraud claim against a beneficiary paid many times "
        "before, a customer who recalls payment after payment and a late technical recall of a "
        "high-value payment are not. In AI-assisted runs the AGB Recall Assistant advises back "
        "office (Phase 42).",
        workload="recall_triage",
        workflow_id="WF-1023",
        workflow_version=2,
        simulated_start=datetime(2026, 9, 15, 9, 0, tzinfo=UTC),
        config=ScenarioConfig(
            arrival_window_hours=8.0,
            document_delay_hours=None,
            mix={
                "genuine_duplicate": 0.25,
                "fraud_reported_fast": 0.20,
                "claimed_duplicate_no_match": 0.15,
                "fraud_on_known_payee": 0.13,
                "serial_recaller": 0.17,
                "stretched_tech": 0.10,
            },
            reviewers={"approval": ReviewerModel(mean_minutes=15, accuracy=0.85)},
            staff_mix={"teller": 0.5, "manager": 0.5},
            ai_assistance=AIAssistanceModel(),
        ),
    )
)

register_scenario(
    Scenario(
        scenario_id="order-review",
        version=1,
        name="Order review (wealth)",
        description="A working day of unsuitable investment orders through WF-1025 v2: a "
        "manager decides whether each may go ahead at the client's insistence. A small step one "
        "level above an experienced customer's profile and a concentration in a low-risk bond "
        "may; a security far above the profile, a complex product for a novice, an order that "
        "spends almost all the customer's cash, a customer who insists order after order and a "
        "two-level step without experience may not. In AI-assisted runs the AGB Suitability "
        "Review Assistant advises the manager (Phase 44).",
        workload="order_review",
        workflow_id="WF-1025",
        workflow_version=2,
        simulated_start=datetime(2026, 10, 15, 9, 0, tzinfo=UTC),
        config=ScenarioConfig(
            arrival_window_hours=8.0,
            document_delay_hours=None,
            mix={
                "experienced_small_step": 0.22,
                "safe_concentration": 0.18,
                "large_gap": 0.12,
                "complex_novice": 0.12,
                "liquidity_drain": 0.10,
                "serial_insister": 0.16,
                "stretch_without_experience": 0.10,
            },
            reviewers={"approval": ReviewerModel(mean_minutes=20, accuracy=0.85)},
            staff_mix={"teller": 0.5, "manager": 0.5},
            ai_assistance=AIAssistanceModel(),
        ),
    )
)

register_scenario(
    Scenario(
        scenario_id="alert-triage",
        version=1,
        name="Alert triage (compliance)",
        description="A working day of AML alerts through WF-1027 v2: a second compliance officer "
        "decides whether each case may be closed with no action. A business banking its usual "
        "cash takings, a one-off large deposit and an account that always passes its salary "
        "straight through may be closed; structuring, a funnel account, a high-risk customer's "
        "spike, a business's sudden spike and a customer whose cash keeps setting off alerts are "
        "escalated. In AI-assisted runs the AGB Alert Review Assistant advises the officer "
        "(Phase 46).",
        workload="alert_triage",
        workflow_id="WF-1027",
        workflow_version=2,
        simulated_start=datetime(2026, 10, 20, 9, 0, tzinfo=UTC),
        config=ScenarioConfig(
            arrival_window_hours=8.0,
            document_delay_hours=None,
            mix={
                "payroll_cash_business": 0.18,
                "one_off_windfall": 0.14,
                "salary_pass_through": 0.12,
                "classic_structuring": 0.14,
                "funnel_account": 0.12,
                "high_risk_spike": 0.08,
                "business_spike": 0.10,
                "repeat_offender": 0.12,
            },
            reviewers={"decision": ReviewerModel(mean_minutes=25, accuracy=0.85)},
            staff_mix={"teller": 0.3, "manager": 0.2, "compliance": 0.5},
            ai_assistance=AIAssistanceModel(),
        ),
    )
)

register_scenario(
    Scenario(
        scenario_id="rating-overrides",
        version=1,
        name="Rating overrides (risk)",
        description="A working day of credit ratings that depart from the model through WF-1030 "
        "v2: a regional executive approves or rejects each. A downgrade a drawn overdraft or "
        "heavy debt explains, a one-notch precautionary downgrade and a one-notch upgrade for a "
        "customer whose income dwarfs their debt are approved; an upgrade with the overdraft "
        "drawn, a departure of three notches or more, a default grade without arrears and an "
        "upgrade already refused two or three times this year are rejected. In AI-assisted runs "
        "the AGB Rating Review Assistant advises the approver (Phase 48).",
        workload="rating_overrides",
        workflow_id="WF-1030",
        workflow_version=2,
        simulated_start=datetime(2026, 10, 20, 9, 0, tzinfo=UTC),
        config=ScenarioConfig(
            arrival_window_hours=8.0,
            document_delay_hours=None,
            mix={
                "overdraft_stress_downgrade": 0.14,
                "heavy_debt_downgrade": 0.12,
                "cautious_downgrade": 0.10,
                "strong_inflow_upgrade": 0.14,
                "upgrade_under_strain": 0.10,
                "excessive_upgrade": 0.10,
                "unfounded_default": 0.06,
                "unsupported_downgrade": 0.10,
                "rating_shopping": 0.14,
            },
            reviewers={"decision": ReviewerModel(mean_minutes=30, accuracy=0.85)},
            staff_mix={"teller": 0.4, "manager": 0.2, "executive": 0.4},
            ai_assistance=AIAssistanceModel(),
        ),
    )
)

register_scenario(
    Scenario(
        scenario_id="journal-review",
        version=1,
        name="Journal review (finance)",
        description="A working day of manual journals through WF-1036 v2: a regional executive "
        "posts or rejects each. A routine accrual, a reclassification between expense accounts "
        "and a material accrual with a full description are posted; a journal straight to "
        "equity, one dated months back, a duplicate of a journal posted days before, a round "
        "cash payment with no description and a large entry split into pieces just under "
        "materiality are rejected. In AI-assisted runs the AGB Journal Review Assistant advises "
        "the approver (Phase 50).",
        workload="journal_review",
        workflow_id="WF-1036",
        workflow_version=2,
        simulated_start=datetime(2026, 10, 20, 9, 0, tzinfo=UTC),
        config=ScenarioConfig(
            arrival_window_hours=8.0,
            document_delay_hours=None,
            mix={
                "routine_accrual": 0.22,
                "reclassification": 0.14,
                "large_documented": 0.10,
                "equity_adjustment": 0.08,
                "stale_backdated": 0.10,
                "duplicate_entry": 0.10,
                "unexplained_cash": 0.10,
                "split_below_threshold": 0.16,
            },
            reviewers={"decision": ReviewerModel(mean_minutes=20, accuracy=0.85)},
            staff_mix={"teller": 0.4, "manager": 0.2, "executive": 0.4},
            ai_assistance=AIAssistanceModel(),
        ),
    )
)

register_scenario(
    Scenario(
        scenario_id="complaint-redress",
        version=1,
        name="Complaint redress (customer service)",
        description="A working day of complaints through WF-1038 v2: a complaints manager "
        "approves paying the proposed redress, upholding the complaint, or refuses it. A refund "
        "of a fee charged twice or of a fee actually charged, and a small or moderate goodwill "
        "payment for a service failure are paid; a fee complaint with no fee charged, redress "
        "far above the fees, a large goodwill payment and a refund for a customer already "
        "refunded three or four times this year are refused. In AI-assisted runs the AGB "
        "Complaint Review Assistant advises the manager (Phase 52).",
        workload="complaint_redress",
        workflow_id="WF-1038",
        workflow_version=2,
        simulated_start=datetime(2026, 10, 20, 9, 0, tzinfo=UTC),
        config=ScenarioConfig(
            arrival_window_hours=8.0,
            document_delay_hours=None,
            mix={
                "duplicate_fee": 0.14,
                "fee_refund": 0.16,
                "small_goodwill": 0.12,
                "moderate_goodwill": 0.10,
                "no_fee_found": 0.10,
                "redress_exceeds_loss": 0.10,
                "large_goodwill": 0.12,
                "serial_complainant": 0.16,
            },
            reviewers={"decision": ReviewerModel(mean_minutes=20, accuracy=0.85)},
            staff_mix={"teller": 0.6, "manager": 0.4},
            ai_assistance=AIAssistanceModel(),
        ),
    )
)

register_scenario(
    Scenario(
        scenario_id="payment-plans",
        version=1,
        name="Payment plans (collections)",
        description="A working day of payment plans through WF-1040 v2: a collections manager "
        "activates or rejects each plan proposed for a loan in arrears. A plan the borrower can "
        "afford, one with only two instalments overdue and one that is stretched but within "
        "means are activated; a plan for a borrower with nothing coming in, one that would take "
        "most of the income and one for a borrower who already broke a plan on the loan are "
        "rejected. In AI-assisted runs the AGB Collections Review Assistant advises the manager "
        "(Phase 54).",
        workload="payment_plans",
        workflow_id="WF-1040",
        workflow_version=2,
        simulated_start=datetime(2026, 10, 20, 9, 0, tzinfo=UTC),
        config=ScenarioConfig(
            arrival_window_hours=8.0,
            document_delay_hours=None,
            mix={
                "affordable": 0.22,
                "short_arrears": 0.14,
                "stretched": 0.14,
                "no_income": 0.14,
                "unaffordable": 0.16,
                "broken_before": 0.20,
            },
            reviewers={"approval": ReviewerModel(mean_minutes=20, accuracy=0.85)},
            staff_mix={"teller": 0.6, "manager": 0.4},
            ai_assistance=AIAssistanceModel(),
        ),
    )
)

register_scenario(
    Scenario(
        scenario_id="leave-requests",
        version=1,
        name="Leave requests (human resources)",
        description="A working day of leave requests through WF-1044 v2: a department manager "
        "approves or rejects each. Routine annual leave, two weeks planned well ahead, short "
        "sickness, a day or two at short notice and leave that leaves the department tightly "
        "but sufficiently covered are approved; leave that would leave the department under-"
        "covered, a week or more asked for at short notice and another day or two at short "
        "notice from someone who keeps asking at the last minute are rejected. In AI-assisted "
        "runs the AGB Leave Review Assistant advises the manager (Phase 56).",
        workload="leave_requests",
        workflow_id="WF-1044",
        workflow_version=2,
        simulated_start=datetime(2026, 10, 20, 9, 0, tzinfo=UTC),
        config=ScenarioConfig(
            arrival_window_hours=8.0,
            document_delay_hours=None,
            mix={
                "routine_annual": 0.18,
                "planned_long": 0.08,
                "short_sick": 0.12,
                "short_notice_short": 0.12,
                "tight_cover": 0.10,
                "understaffed": 0.12,
                "short_notice_long": 0.10,
                "serial_short_notice": 0.18,
            },
            reviewers={"approval": ReviewerModel(mean_minutes=20, accuracy=0.85)},
            staff_mix={"teller": 0.6, "manager": 0.4},
            ai_assistance=AIAssistanceModel(),
        ),
    )
)

register_scenario(
    Scenario(
        scenario_id="invoice-payments",
        version=1,
        name="Invoice payments (procurement)",
        description="A working day of matched vendor invoices through WF-1048 v2: a department "
        "manager releases or rejects each payment. Routine invoices, partial deliveries, "
        "invoices within the 2 % tolerance, vendors whose bank details changed long ago and "
        "small first invoices from new vendors are paid; an invoice to a bank account changed "
        "in the last fortnight with nothing paid to it yet, an invoice dated before its order "
        "and the same bill sent again under a new reference are rejected. In AI-assisted runs "
        "the AGB Invoice Review Assistant advises the manager (Phase 58).",
        workload="invoice_payments",
        workflow_id="WF-1048",
        workflow_version=2,
        simulated_start=datetime(2026, 10, 20, 9, 0, tzinfo=UTC),
        config=ScenarioConfig(
            arrival_window_hours=8.0,
            document_delay_hours=None,
            mix={
                "routine": 0.24,
                "partial_delivery": 0.08,
                "within_tolerance": 0.10,
                "old_bank_change": 0.08,
                "new_vendor_small": 0.08,
                "recent_bank_change": 0.12,
                "backdated": 0.12,
                "near_duplicate": 0.18,
            },
            reviewers={"approval": ReviewerModel(mean_minutes=15, accuracy=0.85)},
            staff_mix={"teller": 0.6, "manager": 0.4},
            ai_assistance=AIAssistanceModel(),
        ),
    )
)

register_scenario(
    Scenario(
        scenario_id="change-approvals",
        version=1,
        name="Change approvals (IT operations)",
        description="A working day of normal change requests through WF-1050 v2: a department "
        "manager approves or rejects each. Routine changes out of hours, daytime changes to "
        "tier-3 applications and changes raised at short notice for the small hours are "
        "approved; a change with no backout plan, a change to an application with a P2 still "
        "open, a business-hours window on a tier-2 application and another change to an "
        "application whose last changes kept failing are rejected. In AI-assisted runs the "
        "AGB Change Review Assistant advises the manager (Phase 60).",
        workload="change_approvals",
        workflow_id="WF-1050",
        workflow_version=2,
        simulated_start=datetime(2026, 10, 20, 9, 0, tzinfo=UTC),
        config=ScenarioConfig(
            arrival_window_hours=8.0,
            document_delay_hours=None,
            mix={
                "routine": 0.24,
                "tier3_daytime": 0.10,
                "short_notice": 0.10,
                "no_backout": 0.12,
                "during_incident": 0.12,
                "business_hours": 0.14,
                "serial_failures": 0.18,
            },
            reviewers={"approval": ReviewerModel(mean_minutes=20, accuracy=0.85)},
            staff_mix={"teller": 0.6, "manager": 0.4},
            ai_assistance=AIAssistanceModel(),
        ),
    )
)


def _thin_department_scenarios() -> None:
    """One scenario per thin department (Phase 61), on its first process: a working day of
    requests decided by its managers. Baseline only: these departments have no AI tool."""
    from app.modules.backoffice.registry import DEPARTMENTS, workflow_id

    for department in DEPARTMENTS:
        process = department.processes[0]
        register_scenario(
            Scenario(
                scenario_id=f"dept-{department.code.replace('_', '-')}",
                version=1,
                name=f"{process.name} ({department.name})",
                description=f"A working day of {process.name.lower()} requests to "
                f"{department.name}: a department manager approves or rejects each. Routine "
                f"and urgent requests within the US${process.budget_usd:,} budget are "
                "approved; requests over the budget and the same request submitted again "
                "after it was completed are rejected (Phase 61).",
                workload="department_requests",
                workflow_id=workflow_id(department, process),
                workflow_version=1,
                simulated_start=datetime(2026, 10, 20, 9, 0, tzinfo=UTC),
                config=ScenarioConfig(
                    arrival_window_hours=8.0,
                    document_delay_hours=None,
                    mix={
                        "routine": 0.5,
                        "urgent": 0.2,
                        "over_budget": 0.15,
                        "duplicate": 0.15,
                    },  # fmt: skip
                    reviewers={"approval": ReviewerModel(mean_minutes=15, accuracy=0.85)},
                    staff_mix={"teller": 0.6, "manager": 0.4},
                ),
            )
        )


_thin_department_scenarios()


def _outage_scenario(base_id: str, base_version: int, scenario_id: str, name: str,
                     description: str, outages: list[ScenarioOutage]) -> None:  # fmt: skip
    """A scenario's working day with application outages on its timeline (Phase 67)."""
    base = get_scenario(base_id, base_version)
    assert base is not None
    register_scenario(base.model_copy(update={
        "scenario_id": scenario_id, "version": 1, "name": name, "description": description,
        "config": base.config.model_copy(update={"outages": outages})}))  # fmt: skip


_outage_scenario(
    "retail-onboarding", 1, "retail-onboarding-outage",
    "Retail account onboarding (screening outage)",
    "The retail onboarding working day with Sanctions Screening down from 12:00 to 14:00. "
    "WF-0001 calls the ledger and screening at every step: applications that reach a step "
    "in the outage are retried, then fail.",
    [ScenarioOutage(application="Sanctions Screening", start_hours=3, minutes=120)],
)  # fmt: skip
_outage_scenario(
    "domestic-payments", 1, "domestic-payments-outage",
    "Domestic payments (ledger outage)",
    "The domestic payments working day with the Core Banking Ledger down from 10:00 to "
    "10:30 and the Payments Gateway degraded until 11:00. A short outage delays payments "
    "through retries; the gateway's slowness adds to every call.",
    [ScenarioOutage(application="Core Banking Ledger", start_hours=2, minutes=30),
     ScenarioOutage(application="Payments Gateway", kind="degraded", start_hours=2,
                    minutes=180)],
)  # fmt: skip


def _schedule_scenario(base_id: str, base_version: int, scenario_id: str, name: str,
                       description: str, schedule: StaffSchedule) -> None:  # fmt: skip
    """A scenario's working day with its reviewers on shifts (Phase 70)."""
    base = get_scenario(base_id, base_version)
    assert base is not None
    register_scenario(base.model_copy(update={
        "scenario_id": scenario_id, "version": 1, "name": name, "description": description,
        "config": base.config.model_copy(update={"staff_schedule": schedule})}))  # fmt: skip


_schedule_scenario(
    "retail-onboarding", 1, "retail-onboarding-shifts",
    "Retail account onboarding (reviewers on New York shifts)",
    "The retail onboarding working day with its reviewers in New York: half on 08:00 to "
    "16:00 and half on 12:00 to 20:00 local time, on US business days, 5 % absent each "
    "day. Applications arrive from 09:00 UTC, 04:00 in New York, so the first reviews wait "
    "for the morning shift.",
    StaffSchedule(country="US", shifts=[(8, 8), (12, 8)], absence_rate=0.05),
)  # fmt: skip


def _arrival_scenario(base_id: str, base_version: int, scenario_id: str, name: str,
                      description: str, window_hours: float,
                      pattern: ArrivalPattern) -> None:  # fmt: skip
    """A scenario's cases arriving over a longer window in a real pattern (Phase 73)."""
    base = get_scenario(base_id, base_version)
    assert base is not None
    register_scenario(base.model_copy(update={
        "scenario_id": scenario_id, "version": 1, "name": name, "description": description,
        "config": base.config.model_copy(update={"arrival_window_hours": window_hours,
                                                 "arrival_pattern": pattern})}))  # fmt: skip


_arrival_scenario(
    "retail-onboarding", 1, "retail-onboarding-week",
    "Retail account onboarding (a week of real demand)",
    "A week of retail applications from Monday 04:00 in New York, arriving as demand "
    "really does there: few at night, a morning rise, lunchtime and after-work peaks, busy "
    "Mondays and quiet weekends, and a marketing campaign on Wednesday afternoon (12:00 "
    "to 18:00 local) that triples demand. Reviewers work around the clock, so the queues "
    "come from the peaks alone.",
    168.0,
    ArrivalPattern(country="US", events=[
        ArrivalEvent(name="campaign", start_hours=2 * 24 + 8, hours=6, multiplier=3.0)]),
)  # fmt: skip
