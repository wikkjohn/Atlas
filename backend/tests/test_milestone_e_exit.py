"""Phase 68: the Milestone E exit — 2,500 applications generated and wired, and an outage's
impact measured."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.itops import estate, links
from app.modules.itops import service as itops
from app.modules.itops.models import Application, ApplicationDependency
from app.simulation.scenarios import ScenarioOutage
from tests.factories import make_org_tree
from tests.test_app_workflow_links import _workflow
from tests.test_outage_scenarios import _run, _with
from tests.test_simulation import session_factory  # noqa: F401  (the fixture)


def test_the_warehouse_wires_the_whole_estate(db: Session) -> None:
    make_org_tree(db)
    itops.ensure_applications(db)
    _workflow(db, "WF-9951", "Finance", "finance.close_period", "core.check")
    _workflow(db, "WF-9952", "Retail Banking", "accounts.lookup")
    warehouse = db.execute(select(Application).where(
        Application.name == estate.WAREHOUSE)).scalar_one()  # fmt: skip

    result = estate.generate_estate(db, 2500, seed=2030)
    assert result["created"] == 2500 and result["warehouse_feeds_added"] > 0
    # The warehouse is fed, never relied on: the estate never depends on it.
    assert not db.execute(select(ApplicationDependency).where(
        ApplicationDependency.depends_on_id == warehouse.id)).first()  # fmt: skip
    feeds = db.execute(select(ApplicationDependency).where(
        ApplicationDependency.application_id == warehouse.id)).scalars().all()  # fmt: skip
    assert {f.kind for f in feeds} == {"batch"}
    # Wiring again adds nothing.
    assert estate.wire(db)["feeds_added"] == 0

    wiring = links.summary(db)
    assert wiring["applications"] >= 2500 + 26
    assert wiring["unwired"] == 0 and wiring["wired"] == wiring["applications"]
    # The finance step calls the warehouse; a batch feed fails no call, so an estate
    # application's outage does not stop the finance workflow through it.
    calls = links.workflow_applications(db, "WF-9951")
    assert estate.WAREHOUSE in [a["name"] for a in calls["applications"]]
    fed = db.get(Application, feeds[0].depends_on_id)
    stopped = {w["workflow_id"] for w in links.outage_impact(db, fed)["workflows"]}
    assert "WF-9951" not in stopped or fed.id in {
        x.application_id for x in links.links(db) if x.workflow_id == "WF-9951"
    }


def test_the_exit_check(db: Session, session_factory) -> None:  # noqa: F811
    make_org_tree(db)
    itops.ensure_applications(db)
    _workflow(db, "WF-9953", "Finance", "finance.close_period")
    db.commit()
    first = links.exit_check(db)
    assert first["passed"] is False
    assert first["checks"] == {"generated": False, "wired": True, "outage_measured": False}

    estate.generate_estate(db, 2500, seed=2030)
    db.commit()
    screening = ScenarioOutage(application="Sanctions Screening", start_hours=3, minutes=120)
    run = _run(db, session_factory, _with("exit", screening))
    check = links.exit_check(db)
    assert check["checks"] == {"generated": True, "wired": True, "outage_measured": True}
    assert check["passed"] is True
    assert check["outage"]["run_number"] == run.run_number
    assert check["outage"]["outages"] == ["Sanctions Screening"]
    assert check["outage"]["executions_failed"] > 0
