"""Phase 67: outage scenarios — a run's own application outages on its timeline, and their
cost."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.identity.models import User
from app.modules.itops import service as itops
from app.modules.itops import simulated
from app.modules.itops.models import Application, ApplicationOutage
from app.modules.workflows.models import WorkflowExecution
from app.simulation.models import SimulationRun, SimulationStatus
from app.simulation.runner import create_run, execute_run
from app.simulation.scenarios import ScenarioOutage, get_scenario, register_scenario
from tests.factories import make_org_tree, make_user
from tests.test_simulation import session_factory  # noqa: F401  (the fixture)

BASE = get_scenario("retail-onboarding", 1)


def _run(db: Session, factory, scenario, *, seed: int = 404, applications: int = 40):
    creator = db.execute(select(User).limit(1)).scalar_one_or_none() or make_user(
        db, RoleCode.AI_RESEARCHER)  # fmt: skip
    run = create_run(db, scenario, profile="custom", applications=applications, employees=6,
                     seed=seed, created_by=creator.id)  # fmt: skip
    db.commit()
    execute_run(factory, run.id)
    db.expire_all()
    return db.get(SimulationRun, run.id)


def _with(name: str, *outages: ScenarioOutage):
    """The base scenario with these outages, registered under its own id."""
    scenario = BASE.model_copy(update={
        "scenario_id": f"test-outage-{name}",
        "config": BASE.config.model_copy(update={"outages": list(outages)})})  # fmt: skip
    register_scenario(scenario)
    return scenario


def test_the_registered_outage_scenarios() -> None:
    screening = get_scenario("retail-onboarding-outage")
    assert screening.workflow_id == "WF-0001" and screening.config.outages == [
        ScenarioOutage(application="Sanctions Screening", start_hours=3, minutes=120)]  # fmt: skip
    payments = get_scenario("domestic-payments-outage")
    assert [o.kind for o in payments.config.outages] == ["down", "degraded"]
    # Older scenarios keep their configuration, so their hashes do not change.
    assert "outages" not in BASE.config.model_dump(mode="json", exclude_none=True)


def test_an_outage_scenario_fails_and_delays_only_its_own_run(
    db: Session,
    session_factory,  # noqa: F811
) -> None:
    make_org_tree(db)
    itops.ensure_applications(db)
    db.commit()
    baseline = _run(db, session_factory, BASE)
    assert baseline.status == SimulationStatus.COMPLETED, baseline.failure_reason
    assert "applications" not in baseline.results

    # Screening down for the middle two hours of the eight-hour arrival window.
    outage = _run(db, session_factory, _with("screening",
        ScenarioOutage(application="Sanctions Screening", start_hours=3, minutes=120)))  # fmt: skip
    assert outage.status == SimulationStatus.COMPLETED, outage.failure_reason
    effects = outage.results["applications"]
    assert effects["outages"][0]["application"] == "Sanctions Screening"
    assert effects["outages"][0]["from"] == (
        outage.simulated_start + timedelta(hours=3)).isoformat()  # fmt: skip
    failed = db.execute(select(WorkflowExecution).where(
        WorkflowExecution.simulation_run_id == outage.id,
        WorkflowExecution.status == "failed")).scalars().all()  # fmt: skip
    assert effects["executions_failed"] == len(failed) > 0
    assert all(e.error["code"] == "application_unavailable" for e in failed)
    # Each failed execution met the outage: it started, or was waiting, during the window.
    window_end = outage.simulated_start + timedelta(hours=5)
    assert all(e.started_at < window_end for e in failed)
    assert effects["retries"] >= 2 * effects["executions_failed"]  # three attempts each
    assert outage.results["completed"] == 40  # every case finished, some by failing
    assert outage.result_digest != baseline.result_digest

    # The run's outage is its own: the bank's estate, and the outage list, never see it.
    screening = db.execute(select(Application).where(
        Application.name == "Sanctions Screening")).scalar_one()  # fmt: skip
    inside = outage.simulated_start + timedelta(hours=4)
    assert simulated.Estate(db, inside).state(screening).status == "up"
    assert simulated.Estate(db, inside, outage.id).state(screening).status == "down"
    stored = db.execute(select(ApplicationOutage).where(
        ApplicationOutage.simulation_run_id == outage.id)).scalars().all()  # fmt: skip
    assert len(stored) == 1 and stored[0].incident_id is None

    # The same scenario and seed again: the same cost, and an overlapping window is fine
    # because each run's outages are scoped to it.
    again = _run(db, session_factory, _with("screening",
        ScenarioOutage(application="Sanctions Screening", start_hours=3, minutes=120)))  # fmt: skip
    assert again.results["applications"]["executions_failed"] == effects["executions_failed"]
    assert again.result_digest == outage.result_digest


def test_a_short_outage_only_delays(db: Session, session_factory) -> None:  # noqa: F811
    make_org_tree(db)
    itops.ensure_applications(db)
    db.commit()
    # One minute down: a step that meets it is retried 30 s later, then 60 s later.
    run = _run(db, session_factory, _with("short",
        ScenarioOutage(application="Core Banking Ledger", start_hours=1, minutes=1)),
        applications=120)  # fmt: skip
    effects = run.results["applications"]
    assert effects["executions_failed"] == 0
    assert effects["executions_delayed"] == effects["retries"] >= 0


def test_an_unknown_application_fails_the_run_with_a_reason(
    db: Session,
    session_factory,  # noqa: F811
) -> None:
    make_org_tree(db)
    itops.ensure_applications(db)
    db.commit()
    run = _run(db, session_factory, _with("unknown",
        ScenarioOutage(application="Mainframe Of Theseus", start_hours=1, minutes=10)))  # fmt: skip
    assert run.status == SimulationStatus.FAILED
    assert "Mainframe Of Theseus" in run.failure_reason
