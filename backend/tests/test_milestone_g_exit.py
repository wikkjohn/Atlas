"""Phase 83: one tool across many workflows — each country's variant of one template."""

import json
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.ai_tools.models import AIToolInvocation
from app.modules.ai_tools.schemas import ToolCreate
from app.modules.ai_tools.service import find_tool, register_tool, serves
from app.modules.experiments import portfolios
from app.modules.experiments.models import ExperimentPortfolio
from app.modules.workflows import authoring, templates
from app.modules.workflows.examples import HERE
from app.seed import DEMO_AI_TOOLS, TEMPLATE_AI_TOOLS
from app.simulation.models import SimulationRun
from app.simulation.runner import SimulationSetupError, create_run
from app.simulation.scenarios import get_scenario
from tests.factories import auth, make_org_tree, make_user
from tests.test_experiments import api, factory  # noqa: F401  (fixtures)

FAMILY = "agb-review-assistants"
TEMPLATE = "TPL-OVERDRAFT-REQUEST"


def _setup(db: Session, countries: tuple[str, ...]) -> dict[str, str]:
    """WF-1003 v1/v2, the template and its variants, the assistant (1.0.0 and the
    template-wide 1.1.0). Returns country → variant workflow id."""
    make_org_tree(db)
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    authoring.import_definition(db, json.loads((HERE / "WF-1003.json").read_text()), admin.id)
    base = next(t for t in DEMO_AI_TOOLS if t["tool_id"] == "agb-overdraft-affordability-assistant")
    register_tool(db, ToolCreate.model_validate(base), actor_id=None)
    authoring.import_definition(db, json.loads((HERE / "WF-1003-v2.json").read_text()), admin.id)
    document = json.loads((HERE / f"{TEMPLATE}.json").read_text())
    templates.import_template(db, document, admin.id)
    report = templates.generate(
        db, TEMPLATE, [{"country_code": c, "decision_seconds": 86_400} for c in countries],
        admin.id,
    )  # fmt: skip
    assert report.valid and report.count("created") == len(countries), report.results
    for spec in TEMPLATE_AI_TOOLS:
        register_tool(db, ToolCreate.model_validate(spec), actor_id=None)
    return {r.params["country_code"]: r.workflow_id for r in report.results}


def test_a_tool_declared_for_a_template_serves_its_variants(db: Session) -> None:
    variants = _setup(db, ("US", "JP"))
    assert len(set(variants.values())) == 2 and all(w.startswith("WF-3") for w in variants.values())
    wide = find_tool(db, "agb-overdraft-affordability-assistant", "1.1.0")
    narrow = find_tool(db, "agb-overdraft-affordability-assistant", "1.0.0")
    assert all(serves(db, wide, w) for w in variants.values()) and serves(db, wide, "WF-1003")
    assert not any(serves(db, narrow, w) for w in variants.values())
    assert not serves(db, wide, "WF-0001")

    scenario = get_scenario("retail-overdrafts-country")
    creator = make_user(db, RoleCode.AI_RESEARCHER)
    run = create_run(
        db, scenario, profile="custom", applications=5, employees=4, seed=3,
        created_by=creator.id, mode="ai_assisted", tool=wide, countries=["JP"],
    )  # fmt: skip
    # The run executes Japan's own workflow, and says which template it came from.
    assert run.workflow_id == variants["JP"]
    assert run.config["workflow_variant"] == {
        "template_id": TEMPLATE, "template_version": 1, "country_code": "JP"
    }  # fmt: skip
    for countries, message in ((None, "exactly one country"), (["US", "JP"], "exactly one"),
                               (["DE"], "No TPL-OVERDRAFT-REQUEST variant")):  # fmt: skip
        try:
            create_run(db, scenario, profile="custom", applications=5, employees=4, seed=3,
                       created_by=creator.id, countries=countries)  # fmt: skip
        except SimulationSetupError as exc:
            assert message in str(exc)
        else:
            raise AssertionError(f"{countries} should be refused")


def test_one_tool_across_each_countrys_workflow(api: TestClient, db: Session) -> None:  # noqa: F811
    variants = _setup(db, ("US", "JP"))
    headers = auth(make_user(db, RoleCode.AI_RESEARCHER))
    db.commit()
    body = {
        "name": "Overdraft assistant, each country's workflow",
        "family": FAMILY,
        "candidate_mode": "ai_assisted",
        "scenario_ids": ["retail-overdrafts-country"],
        "countries": ["US", "JP"],
        "applications": 12,
        "employees": 6,
        "seed": 9,
        "replicates": 2,
    }
    response = api.post("/api/v1/experiment-portfolios", json=body, headers=headers)
    assert response.status_code == 202, response.text
    portfolio = api.get(
        f"/api/v1/experiment-portfolios/{response.json()['id']}", headers=headers
    ).json()
    assert portfolio["status"] == "completed", portfolio["failure_reason"]
    assert [c["tool_version"] for c in portfolio["configuration"]["plan"]["cells"]] == ["1.1.0"]
    stats = portfolio["statistics"]
    # Each country's variant is its own workflow: two workflows, not one scenario twice.
    assert (stats["cells"], stats["workflows"]) == (2, 2)
    record = db.get(ExperimentPortfolio, uuid.UUID(portfolio["id"]))
    runs = db.execute(
        select(SimulationRun).where(SimulationRun.scenario_id == "retail-overdrafts-country")
    ).scalars().all()  # fmt: skip
    assert {r.workflow_id for r in runs} == set(variants.values())
    calls = db.execute(
        select(AIToolInvocation).where(AIToolInvocation.simulation_run_id.in_([r.id for r in runs]))
    ).scalars().all()  # fmt: skip
    assert calls and {(c.tool_id, c.tool_version) for c in calls} == {
        ("agb-overdraft-affordability-assistant", "1.1.0")
    }  # fmt: skip
    assert record.statistics == stats

    # A country without its variant is refused before anything runs; unasked for, the
    # templated scenario is left out with the reason.
    refused = api.post("/api/v1/experiment-portfolios",
                       json={**body, "countries": ["US", "GB"]}, headers=headers)  # fmt: skip
    assert refused.status_code == 422 and "none is generated for GB" in refused.text
    cell = {"scenario_id": "retail-overdrafts-country", "scenario_version": 1}
    kept, left_out = portfolios._with_variants(db, [cell], ["US", "GB"])
    assert kept == [] and left_out == [
        {"scenario_id": "retail-overdrafts-country", "reason": "no variant generated for GB"}
    ]
    assert portfolios._with_variants(db, [cell], ["US", "JP"]) == ([cell], [])
