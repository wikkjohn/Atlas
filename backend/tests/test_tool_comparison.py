"""Phase 81: tools compared on matched workloads across all benchmarks."""

import copy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.ai_tools.schemas import ToolCreate
from app.modules.ai_tools.service import register_tool
from app.modules.experiments import comparison, thresholds
from app.modules.experiments import series as series_service
from app.seed import DEMO_AI_TOOLS
from tests.factories import auth, make_org_tree, make_user
from tests.test_experiments import api, factory  # noqa: F401  (fixtures)


def _row(metric: str, candidate: float, better: str = "lower") -> dict:
    return {"metric": metric, "label": metric.replace("_", " "), "unit": "hours",
            "better": better, "candidate": candidate}  # fmt: skip


def _side(values: dict[str, list[float]]) -> dict:
    """One tool's experiments on matched workloads w0, w1, ...: metric → value per workload."""
    n = len(next(iter(values.values())))
    return {
        f"w{i}": {
            "seed": i,
            "evaluation": SimpleNamespace(
                comparisons=[
                    _row(m, v[i], "higher" if m == "accuracy" else "lower")
                    for m, v in values.items()
                ]  # fmt: skip
            ),
        }
        for i in range(n)
    }


def test_a_tool_better_on_every_seed_is_preferred() -> None:
    a = _side({"labour_hours": [10, 11, 9, 10], "accuracy": [0.95, 0.96, 0.95, 0.94]})
    b = _side({"labour_hours": [14, 15, 13, 15], "accuracy": [0.95, 0.96, 0.95, 0.94]})
    pair = comparison._pair("a@1", "b@1", a, b)
    assert pair["matched_workloads"] == 4 and pair["seeds"] == [0, 1, 2, 3]
    labour = next(m for m in pair["metrics"] if m["metric"] == "labour_hours")
    assert labour["mean_difference"] == pytest.approx(-4.25)
    assert labour["relative_difference"] == pytest.approx(-4.25 / 14.25, abs=1e-6)
    assert labour["finding"] == "a_better" and labour["p_adjusted"] < 0.05
    accuracy = next(m for m in pair["metrics"] if m["metric"] == "accuracy")
    assert accuracy["finding"] == "no_significant_difference"  # identical
    assert pair["outcome"] == "a_preferred" and pair["a_better_on"] == ["labour_hours"]


def test_better_on_one_metric_and_worse_on_another_is_a_trade_off() -> None:
    a = _side({"labour_hours": [10, 11, 9, 10], "accuracy": [0.80, 0.82, 0.79, 0.81]})
    b = _side({"labour_hours": [14, 15, 13, 15], "accuracy": [0.95, 0.96, 0.95, 0.94]})
    pair = comparison._pair("a@1", "b@1", a, b)
    assert pair["outcome"] == "trade_off"
    assert (pair["a_better_on"], pair["b_better_on"]) == (["labour_hours"], ["accuracy"])


def test_noise_and_unmatched_workloads_decide_nothing() -> None:
    a = _side({"labour_hours": [10, 14, 9, 15]})
    b = _side({"labour_hours": [14, 10, 15, 9]})
    assert comparison._pair("a@1", "b@1", a, b)["outcome"] == "no_difference"
    one = {"w0": a["w0"]}
    lone = comparison._pair("a@1", "b@1", one, {"w0": b["w0"], "w9": b["w1"]})
    assert lone["matched_workloads"] == 1 and lone["outcome"] == "too_few_matched"
    assert lone["metrics"][0]["finding"] == "too_few_matched"


def test_a_comparison_runs_every_tool_on_the_same_seeds(api: TestClient, db: Session) -> None:  # noqa: F811
    make_org_tree(db)
    kyc = next(t for t in DEMO_AI_TOOLS if t["tool_id"] == "agb-intelligent-kyc-assistant")
    for spec in DEMO_AI_TOOLS:
        if spec["tool_id"] in ("agb-intelligent-kyc-assistant", "kyc-fault-injector"):
            register_tool(db, ToolCreate.model_validate(spec), actor_id=None)
    tuned = copy.deepcopy(kyc)
    tuned["tool_version"] = "1.1.0"
    tuned["configuration"] = {**tuned.get("configuration", {}), "large_deposit_threshold": 20_000}
    register_tool(db, ToolCreate.model_validate(tuned), actor_id=None)
    headers = auth(make_user(db, RoleCode.AI_RESEARCHER))
    db.commit()
    body = {
        "name": "KYC versions",
        "scenario_id": "retail-onboarding",
        "tools": [
            {"tool_id": "agb-intelligent-kyc-assistant", "tool_version": "1.0.0"},
            {"tool_id": "agb-intelligent-kyc-assistant", "tool_version": "1.1.0"},
            {"tool_id": "kyc-fault-injector"},
        ],
        "applications": 12,
        "employees": 6,
        "seed": 3,
        "replicates": 2,
    }
    started = api.post("/api/v1/tool-comparison/runs", json=body, headers=headers)
    assert started.status_code == 202, started.text
    series = started.json()["series"]
    assert [(s["tool_id"], s["tool_version"]) for s in series] == [
        ("agb-intelligent-kyc-assistant", "1.0.0"),
        ("agb-intelligent-kyc-assistant", "1.1.0"),
        ("kyc-fault-injector", "1.0.0"),
    ]
    assert all(s["seeds"] == [3, 4] for s in series)
    for s in series:
        detail = api.get(f"/api/v1/experiment-series/{s['id']}", headers=headers).json()
        assert detail["status"] == "completed", detail["failure_reason"]

    result = api.get("/api/v1/tool-comparison", headers=headers).json()
    (bench,) = [b for b in result["benchmarks"] if b["scenario_id"] == "retail-onboarding"]
    assert bench["risk_tier"] == "critical" and bench["candidate_mode"] == "ai_assisted"
    assert sorted(t["tool"] for t in bench["tools"]) == [
        "agb-intelligent-kyc-assistant@1.0.0", "agb-intelligent-kyc-assistant@1.1.0",
        "kyc-fault-injector@1.0.0",
    ]  # fmt: skip
    ranks = {t["tool"]: t["rank"] for t in bench["tools"]}
    pairs = {(p["a"], p["b"]): p for p in bench["pairs"]}
    versions = pairs[("agb-intelligent-kyc-assistant@1.0.0", "agb-intelligent-kyc-assistant@1.1.0")]
    # The tuned version changes nothing these cases exercise: identical, so they share rank
    # 1; the fault injector's errors fail its experiments under the critical tier.
    assert versions["outcome"] == "identical"
    assert all(m["mean_difference"] == 0 for m in versions["metrics"])
    assert ranks == {
        "agb-intelligent-kyc-assistant@1.0.0": 1, "agb-intelligent-kyc-assistant@1.1.0": 1,
        "kyc-fault-injector@1.0.0": 3,
    }  # fmt: skip
    assert all(t["experiments"] == 2 for t in bench["tools"])
    assert len(bench["pairs"]) == 3 and all(p["matched_workloads"] == 2 for p in bench["pairs"])
    assert all(p["seeds"] == [3, 4] for p in bench["pairs"])
    assert {r["tool"] for r in result["scoreboard"]} == {t["tool"] for t in bench["tools"]}
    assert sum(r["ranked_first"] for r in result["scoreboard"]) == 2
    board = {r["tool"]: r for r in result["scoreboard"]}
    assert board["agb-intelligent-kyc-assistant@1.0.0"]["identical"] == 1
    only = api.get("/api/v1/tool-comparison?tool=kyc-fault-injector@1.0.0", headers=headers).json()
    assert [b["scenario_id"] for b in only["benchmarks"]] == ["retail-onboarding"]
    none = api.get("/api/v1/tool-comparison?tool=nobody@1", headers=headers).json()
    assert none["benchmarks"] == [] and none["scoreboard"] == []

    # Refusals: one tool, the same tool twice, no permission to run.
    one = api.post("/api/v1/tool-comparison/runs", json={**body, "tools": body["tools"][:1]},
                   headers=headers)  # fmt: skip
    assert one.status_code == 422
    twice = api.post(
        "/api/v1/tool-comparison/runs",
        json={**body, "tools": [body["tools"][0], body["tools"][0]]},
        headers=headers,
    )
    assert twice.status_code == 422 and "only once" in twice.text
    auditor = auth(make_user(db, RoleCode.AUDITOR))
    db.commit()
    assert api.get("/api/v1/tool-comparison", headers=auditor).status_code == 200
    assert api.post("/api/v1/tool-comparison/runs", json=body, headers=auditor).status_code == 403

    # Re-evaluating the same runs under other costs is a separate benchmark, never extra
    # evidence: the original pair still has its 2 matched workloads.
    replicates = [
        r
        for s in series[:2]
        for r in api.get(f"/api/v1/experiment-series/{s['id']}", headers=headers).json()[
            "experiments"
        ]
    ]
    for i, replicate in enumerate(replicates):
        variant = {
            "name": f"KYC under other costs {i}",
            "baseline_run_id": replicate["baseline"]["id"],
            "candidate_run_id": replicate["candidate"]["id"],
            "costs": {"notes": "a variant"},
        }
        assert (
            api.post("/api/v1/experiments/from-runs", json=variant, headers=headers).status_code
            == 201
        )
    again = api.get("/api/v1/tool-comparison?scenario_id=retail-onboarding", headers=headers).json()
    assert len(again["benchmarks"]) == 2
    original = next(
        b for b in again["benchmarks"] if b["cost_assumptions"] == bench["cost_assumptions"]
    )
    assert all(p["matched_workloads"] == 2 for p in original["pairs"])
    variant_bench = next(b for b in again["benchmarks"] if b is not original)
    assert sorted(t["tool"] for t in variant_bench["tools"]) == [
        "agb-intelligent-kyc-assistant@1.0.0", "agb-intelligent-kyc-assistant@1.1.0"
    ]  # fmt: skip
    assert [p["matched_workloads"] for p in variant_bench["pairs"]] == [2]

    # The tier shown is the tier of the thresholds applied, approved versions included.
    record = thresholds.propose(
        db, scenario_id="retail-onboarding", risk_tier="medium", thresholds=None,
        rationale="Onboarding is monitored after opening: medium risk.",
        actor_id=make_user(db, RoleCode.AI_RESEARCHER).id,
    )  # fmt: skip
    thresholds.approve(db, record.id, make_user(db, RoleCode.GLOBAL_EXECUTIVE).id)
    db.commit()
    tiers = api.get("/api/v1/tool-comparison?scenario_id=retail-onboarding", headers=headers)
    assert {b["risk_tier"] for b in tiers.json()["benchmarks"]} == {"medium"}

    # The same tool twice, once by its highest active version and once without one.
    same = api.post(
        "/api/v1/tool-comparison/runs",
        json={**body, "tools": [{"tool_id": "agb-intelligent-kyc-assistant"},
                                {"tool_id": "agb-intelligent-kyc-assistant",
                                 "tool_version": "1.1.0"}]},
        headers=headers,
    )  # fmt: skip
    assert same.status_code == 422 and "only once" in same.text


def test_generated_names_stay_within_the_limit() -> None:
    long = "x" * 200
    for suffix in (" · seed 2147483647", " · agb-intelligent-kyc-assistant 1.1.0", ""):
        name = series_service.bounded(long, suffix)
        assert len(name) <= 200 and name.endswith(suffix)
    assert series_service.bounded("short", " · seed 1") == "short · seed 1"
