"""Phase 34: the mortgage-applications workload and the mortgage underwriting AI tool."""

import json
from datetime import date

import pytest
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.ai_tools.adapters.mortgage_underwriting import (
    ApplicationProfile,
    MortgageUnderwritingConfig,
    MortgageUnderwritingInput,
    analyze,
)
from app.modules.ai_tools.schemas import ToolCreate
from app.modules.ai_tools.service import register_tool
from app.modules.lending import service as lending
from app.modules.mortgages import service as mortgages
from app.modules.workflows import authoring
from app.modules.workflows.examples import HERE
from app.seed import DEMO_AI_TOOLS
from app.simulation.models import SimulationCaseResult, SimulationRun, SimulationStatus
from app.simulation.runner import create_run, execute_run
from app.simulation.scenarios import get_scenario
from app.simulation.workloads import (
    MORTGAGE_MAX_ESTIMATE_USD,
    MORTGAGE_SHAPES,
    MORTGAGE_SHOULD_REJECT,
    WORKLOADS,
)
from tests.factories import funded_account, make_org_tree, make_staff, make_user, unique_surname

SCENARIO = get_scenario("mortgage-applications")


def _advice(**profile) -> tuple[str, list[str]]:
    values = {
        "currency": "USD", "loan_amount": 20_000_000, "term_years": 25, "ltv_bps": 6000,
        "monthly_payment": 110_000, "declared_monthly_income": 700_000,
        "income_estimate": 700_000, "payment_to_income_bps": 1571,
        "payment_to_estimate_bps": 1571, "declared_to_estimate_bps": 10_000,
        "credit_score": 760, "valuation_method": "surveyor", "model_to_price_bps": 10_000,
        "age_at_term_end": 60,
    }  # fmt: skip
    result, _ = analyze(
        MortgageUnderwritingInput(profile=ApplicationProfile(**{**values, **profile})),
        MortgageUnderwritingConfig(),
    )
    return result.recommendation, [f.code for f in result.findings]


def test_the_underwriting_rules_and_their_blind_spot() -> None:
    assert _advice() == ("approve", [])
    assert _advice(ltv_bps=8800) == ("approve", ["high_ltv"])
    # A large payment on a high loan-to-value.
    assert _advice(ltv_bps=8800, payment_to_income_bps=3300) == ("reject", ["stretched"])
    # Declared income well above the estimate, and the payment too much for the estimate.
    assert _advice(declared_to_estimate_bps=14_000, payment_to_estimate_bps=4000) == (
        "reject",
        ["unaffordable_on_estimate", "income_gap"],
    )
    # A thin credit file at a high loan-to-value: escalate.
    assert _advice(ltv_bps=8400, credit_score=640) == ("escalate", ["high_ltv", "thin_credit"])
    assert _advice(model_to_price_bps=8700) == ("approve", ["model_below_price"])
    # The blind spot: a term ending at 95 with prime figures is approved.
    assert _advice(age_at_term_end=95, term_years=35) == ("approve", [])


def test_every_kind_of_case_fits_its_product_at_the_extremes(db: Session) -> None:
    """The largest loan a case can draw stays within its product's maximum, with room for
    the two-significant-figure rounding of converted limits (Codex review on PR #25: an
    inflated-income case at a high income estimate exceeded home-75's US$1m)."""
    for kind, ((_, ltv), (_, share), (_, ratio)) in MORTGAGE_SHAPES.items():
        product = mortgages.get_product(db, "home-90" if ltv > 0.75 else "home-75")
        years = 35 if kind == "retirement_term" else 30
        r = product.annual_rate_bps / 10_000 / 12
        payment = MORTGAGE_MAX_ESTIMATE_USD * ratio * share
        loan = payment * (1 - (1 + r) ** -(years * 12)) / r
        assert loan <= product.max_loan_usd * 0.95, (kind, round(loan))
    assert set(MORTGAGE_SHAPES) == WORKLOADS["mortgage_applications"].kinds
    assert MORTGAGE_SHOULD_REJECT < set(MORTGAGE_SHAPES)


def test_the_application_profile(db: Session) -> None:
    staff = make_staff(db)
    born = date(1966, 3, 1)
    for _ in range(50_000):
        name = f"Ines {unique_surname()}"
        report = lending.bureau_report(name, born)
        if report["score"] >= 700 and report["recent_defaults"] == 0:
            break
    account = funded_account(db, staff, name=name, born=born)
    customer = account.customer
    prop = mortgages.register_property(db, customer, "house", 40_000_000, None)
    mortgages.value_property(db, prop, "surveyor", value=40_000_000, actor_id=staff.manager.id)
    estimate = mortgages.monthly_income_estimate(customer, "USD")
    offer = mortgages.request_offer(
        db, customer=customer, prop=prop, product=mortgages.get_product(db, "home-75"),
        account=account, loan_amount=8_000_000, term_years=30,
        declared_monthly_income=estimate, requested_by=staff.employee.id,
    )  # fmt: skip
    profile = mortgages.application_profile(db, offer, date(2026, 6, 2))
    assert profile["ltv_bps"] == 2000 and profile["term_years"] == 30
    assert profile["age_at_term_end"] == 60 + 30  # 60 in June 2026, then 30 years
    # The caller's date decides, not when the offer row was written (Codex review, PR #25).
    assert mortgages.application_profile(db, offer, date(2031, 6, 2))["age_at_term_end"] == 95
    assert profile["declared_to_estimate_bps"] == 10_000
    assert profile["payment_to_income_bps"] == offer.monthly_payment * 10_000 // estimate
    assert profile["valuation_method"] == "surveyor"
    assert profile["model_to_price_bps"] == mortgages.desktop_value(prop) * 10_000 // 40_000_000


@pytest.fixture
def factory(db_connection: Connection):
    def make() -> Session:
        return Session(
            bind=db_connection,
            join_transaction_mode="create_savepoint",
            autoflush=False,
            expire_on_commit=False,
        )

    return make


def _setup(db: Session) -> None:
    """The org tree, WF-1009 v1, the tool (compatible with WF-1009), then WF-1009 v2."""
    make_org_tree(db)
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    authoring.import_definition(db, json.loads((HERE / "WF-1009.json").read_text()), admin.id)
    spec = next(t for t in DEMO_AI_TOOLS if t["tool_id"] == "agb-mortgage-underwriting-assistant")
    register_tool(db, ToolCreate.model_validate(spec), actor_id=None)
    authoring.import_definition(db, json.loads((HERE / "WF-1009-v2.json").read_text()), admin.id)


def _run(db: Session, factory, mode: str, seed: int = 11) -> SimulationRun:
    from app.modules.ai_tools.service import find_tool

    creator = make_user(db, RoleCode.AI_RESEARCHER)
    tool = find_tool(db, "agb-mortgage-underwriting-assistant") if mode != "baseline" else None
    run = create_run(
        db, SCENARIO, profile="custom", applications=40, employees=6, seed=seed,
        created_by=creator.id, mode=mode, tool=tool,
    )  # fmt: skip
    db.commit()
    execute_run(factory, run.id)
    db.expire_all()
    return db.get(SimulationRun, run.id)


def _cases(db: Session, run: SimulationRun, **where) -> list[SimulationCaseResult]:
    query = select(SimulationCaseResult).where(SimulationCaseResult.run_id == run.id)
    for column, value in where.items():
        query = query.where(getattr(SimulationCaseResult, column) == value)
    return db.execute(query).scalars().all()


def test_mortgage_runs_with_and_without_the_assistant(db: Session, factory) -> None:
    _setup(db)
    db.commit()
    baseline = _run(db, factory, "baseline")
    assisted = _run(db, factory, "ai_assisted")
    for run in (baseline, assisted):
        assert run.status == SimulationStatus.COMPLETED, run.failure_reason
        assert run.results["completed"] == 40
        controls = WORKLOADS["mortgage_applications"].check_controls(db, run.id)
        # Every case passes the lending rules, so an underwriter decides each one.
        assert controls.decisions == 40 and controls.violations == []
    assert baseline.results["ai"]["invocations"] == 0
    ai = assisted.results["ai"]
    assert ai["invocations"] == 40 and ai["failed_invocations"] == 0
    expected = {"prime": "approve", "high_ltv_strong": "approve", "stretched": "reject",
                "inflated_income": "reject", "thin_credit": "escalate",
                "retirement_term": "approve"}  # fmt: skip
    seen = set()
    for case in _cases(db, assisted):
        assert case.ai_recommendation == expected[case.kind], case.kind
        seen.add(case.kind)
    assert {"retirement_term", "stretched", "prime"} <= seen
    assert ai["recommendation_accuracy"] < 1
    offered = _cases(db, assisted, outcome="approved")
    assert offered and all("issue" in c.path for c in offered)
    declined = _cases(db, assisted, outcome="rejected")
    assert declined and all("issue" not in c.path for c in declined)
