"""Phase 78: experiment portfolios — a tool family across workflows, departments, countries."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.ai_tools.schemas import ToolCreate
from app.modules.ai_tools.service import register_tool
from app.modules.experiments import portfolios
from app.modules.experiments.models import ExperimentPortfolio
from app.modules.experiments.significance import portfolio_statistics
from app.seed import DEMO_AI_TOOLS, REVIEW_FAMILY
from tests.factories import auth, make_org_tree, make_user
from tests.test_experiments import api, factory  # noqa: F401  (fixtures)

# --- Statistics across cells ---------------------------------------------------------------


def _metric(metric, label, better, rel, finding):
    return {"metric": metric, "label": label, "better": better, "relative_change": rel,
            "finding": finding}  # fmt: skip


def _cell(scenario, workflow, department, country, labour, accuracy, verdict="successful",
          accuracy_finding="no_significant_difference"):  # fmt: skip
    return {
        "scenario_id": scenario, "workflow_id": workflow, "department": department,
        "country": country, "tool_id": f"tool-{workflow}", "series_number": 1,
        "verdict": verdict,
        "metrics": [
            _metric("labour_hours", "Simulated labour time", "lower", labour, "improved"),
            _metric("accuracy", "Decisions matching ground truth", "higher", accuracy,
                    accuracy_finding),
            _metric("ai_execution_cost", "AI execution cost", "none", 1.0, "informational"),
        ],
    }  # fmt: skip


def test_the_workflow_is_the_unit_across_departments_and_countries() -> None:
    cells = [
        _cell("a", "WF-1", "Lending", "US", -0.30, 0.01),
        _cell("a", "WF-1", "Lending", "JP", -0.34, -0.01),
        _cell("b", "WF-2", "Cards", "US", -0.40, 0.00),
        _cell("b", "WF-2", "Cards", "JP", -0.36, 0.005),
        # The country makes no difference here: two identical cells, one workflow.
        _cell("c", "WF-3", "Human Resources", "US", -0.35, 0.0),
        _cell("c", "WF-3", "Human Resources", "JP", -0.35, 0.0),
    ]
    stats = portfolio_statistics(cells, 0.95)
    assert (stats["cells"], stats["workflows"]) == (6, 3)
    assert stats["countries"] == ["JP", "US"]
    rows = {m["metric"]: m for m in stats["metrics"]}
    assert "ai_execution_cost" not in rows  # informational metrics are not pooled
    labour = rows["labour_hours"]
    # Workflow means -0.32, -0.38 and -0.35: three units, not six.
    assert (labour["workflows"], labour["cells"]) == (3, 6)
    assert labour["mean_relative_change"] == pytest.approx(-0.35)
    assert labour["ci_high"] < 0 and labour["finding"] == "improved"
    assert labour["country_dependent_workflows"] == 2
    assert labour["cell_findings"] == {"improved": 6, "worse": 0, "no_significant_difference": 0}
    assert {d["department"]: d["mean_relative_change"] for d in labour["by_department"]} == {
        "Cards": pytest.approx(-0.38), "Human Resources": pytest.approx(-0.35),
        "Lending": pytest.approx(-0.32),
    }  # fmt: skip
    assert [c["cells"] for c in labour["by_country"]] == [3, 3]
    assert rows["accuracy"]["finding"] == "no_significant_difference"
    assert stats["verdict"] == "successful" and stats["cell_verdicts"]["successful"] == 6
    assert "Across 3 workflows (6 cells; 3 departments, 2 countries)" in stats["conclusion"]
    assert "better in 6 of 6 cells" in stats["conclusion"]
    assert "The country changed the labour effect in 2 of 3 workflows" in stats["conclusion"]


def test_identical_country_cells_add_no_evidence() -> None:
    # One workflow in five countries with the same result is still one unit: no test.
    cells = [_cell("a", "WF-1", "Lending", c, -0.3, 0.0) for c in ("DE", "GB", "JP", "SG", "US")]
    labour = next(
        m for m in portfolio_statistics(cells, 0.95)["metrics"] if m["metric"] == "labour_hours"
    )
    assert (labour["workflows"], labour["cells"]) == (1, 5)
    assert labour["p_value"] is None and labour["finding"] == "too_few_cells"


def test_a_cell_that_got_worse_is_named_and_fails_the_portfolio() -> None:
    cells = [
        _cell("a", "WF-1", "Lending", "US", -0.3, 0.0),
        _cell(
            "b",
            "WF-2",
            "Cards",
            "JP",
            -0.3,
            -0.05,
            verdict="not_successful",
            accuracy_finding="worse",
        ),  # fmt: skip
    ]
    stats = portfolio_statistics(cells, 0.95)
    assert stats["cells_with_a_worse_metric"] == ["b (JP)"]
    assert stats["verdict"] == "not_successful" and "worse in: b (JP)" in stats["conclusion"]


# --- Planning and running -------------------------------------------------------------------


def _family(db: Session, tool_ids: tuple[str, ...]) -> None:
    for spec in DEMO_AI_TOOLS:
        if spec["tool_id"] in tool_ids:
            assert spec["family"] == REVIEW_FAMILY
            register_tool(db, ToolCreate.model_validate(spec), actor_id=None)


def test_the_plan_covers_every_scenario_the_family_serves(db: Session) -> None:
    _family(db, ("agb-intelligent-kyc-assistant", "agb-payment-fraud-screener"))
    cells, skipped = portfolios.plan(db, REVIEW_FAMILY, "ai_assisted")
    assert [(c["scenario_id"], c["tool_id"]) for c in cells] == [
        ("domestic-payments", "agb-payment-fraud-screener"),
        ("retail-onboarding", "agb-intelligent-kyc-assistant"),
    ]
    reasons = {s["scenario_id"]: s["reason"] for s in skipped}
    assert "outage" in reasons["domestic-payments-outage"]
    assert reasons["leave-requests"] == "no tool of the family serves WF-1044"
    assert portfolios.department(db, "WF-0001") == "Customer Onboarding"
    assert portfolios.plan(db, "no-such-family", "ai_assisted")[0] == []


def test_a_portfolio_runs_every_cell_and_pools_them(api: TestClient, db: Session) -> None:  # noqa: F811
    make_org_tree(db)
    _family(db, ("agb-intelligent-kyc-assistant", "agb-payment-fraud-screener"))
    headers = auth(make_user(db, RoleCode.AI_RESEARCHER))
    db.commit()
    preview = api.get(
        f"/api/v1/experiment-portfolios/plan?family={REVIEW_FAMILY}", headers=headers
    ).json()
    assert len(preview["cells"]) == 2
    body = {
        "name": "Review assistants, assisted",
        "family": REVIEW_FAMILY,
        "candidate_mode": "ai_assisted",
        "countries": ["US", "JP"],
        "applications": 12,
        "employees": 12,
        "seed": 5,
        "replicates": 2,
    }
    response = api.post("/api/v1/experiment-portfolios", json=body, headers=headers)
    assert response.status_code == 202, response.text
    portfolio = api.get(
        f"/api/v1/experiment-portfolios/{response.json()['id']}", headers=headers
    ).json()
    assert portfolio["status"] == "completed", portfolio["failure_reason"]
    assert (portfolio["cells"], portfolio["cells_completed"]) == (4, 4)
    assert sorted((s["scenario_id"], s["country"]) for s in portfolio["series"]) == [
        ("domestic-payments", "JP"), ("domestic-payments", "US"),
        ("retail-onboarding", "JP"), ("retail-onboarding", "US"),
    ]  # fmt: skip
    assert all(s["seeds"] == [5, 6] for s in portfolio["series"])
    stats = portfolio["statistics"]
    assert (stats["cells"], stats["workflows"], stats["countries"]) == (4, 2, ["JP", "US"])
    assert stats["departments"] == ["Customer Onboarding", "Payments Operations"]
    assert stats["tools"] == ["agb-intelligent-kyc-assistant", "agb-payment-fraud-screener"]
    labour = next(m for m in stats["metrics"] if m["metric"] == "labour_hours")
    assert labour["cells"] == 4 and len(labour["by_country"]) == 2
    assert portfolio["verdict"] == stats["verdict"]
    assert len(portfolio["configuration"]["plan"]["cells"]) == 2
    # Derived: recomputable from the cells' stored series statistics.
    record = db.get(ExperimentPortfolio, uuid.UUID(portfolio["id"]))
    assert portfolios.compute(db, record, portfolios.cells(db, record)) == stats
    listed = api.get("/api/v1/experiment-portfolios", headers=headers).json()
    assert [p["portfolio_number"] for p in listed["items"]] == [portfolio["portfolio_number"]]


def test_refusals(api: TestClient, db: Session, monkeypatch) -> None:  # noqa: F811
    monkeypatch.setattr(portfolios, "MAX_PORTFOLIO_EXPERIMENTS", 3)
    make_org_tree(db)
    _family(db, ("agb-intelligent-kyc-assistant",))
    headers = auth(make_user(db, RoleCode.AI_RESEARCHER))
    db.commit()
    base = {"name": "x portfolio", "family": REVIEW_FAMILY, "countries": ["US"]}
    none = api.post(
        "/api/v1/experiment-portfolios", json={**base, "family": "nobody"}, headers=headers
    )
    assert none.status_code == 422 and "No active tool of the family" in none.text
    too_many = api.post(
        "/api/v1/experiment-portfolios",
        json={**base, "countries": ["US", "JP"], "replicates": 2},  # 1 cell × 2 × 2 = 4
        headers=headers,
    )
    assert too_many.status_code == 422 and "would run 4 experiments; at most 3" in too_many.text
    duplicate = api.post(
        "/api/v1/experiment-portfolios", json={**base, "countries": ["US", "US"]}, headers=headers
    )
    assert duplicate.status_code == 422 and "different" in duplicate.text
    auditor = auth(make_user(db, RoleCode.AUDITOR))
    db.commit()
    assert api.get("/api/v1/experiment-portfolios", headers=auditor).status_code == 200
    assert api.post("/api/v1/experiment-portfolios", json=base, headers=auditor).status_code == 403
