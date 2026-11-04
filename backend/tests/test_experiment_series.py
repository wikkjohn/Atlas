"""Phase 77: repeated-seed experiment series — confidence intervals and significance tests."""

import math
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.ai_tools.schemas import ToolCreate
from app.modules.ai_tools.service import register_tool
from app.modules.experiments import series as series_service
from app.modules.experiments.models import Experiment, ExperimentSeries
from app.modules.experiments.significance import (
    holm,
    paired,
    series_statistics,
    t_critical,
    t_two_sided_p,
)
from app.seed import DEMO_AI_TOOLS
from tests.factories import auth, make_user
from tests.test_experiments import api, factory, lab  # noqa: F401  (fixtures)

# --- The statistics, against values from published t tables ----------------------------------


@pytest.mark.parametrize(
    ("confidence", "df", "expected"),
    [
        (0.95, 1, 12.7062),
        (0.95, 4, 2.7764),
        (0.95, 29, 2.0452),
        (0.99, 9, 3.2498),
        (0.90, 2, 2.9200),
    ],  # fmt: skip
)
def test_t_critical_values(confidence: float, df: int, expected: float) -> None:
    assert t_critical(confidence, df) == pytest.approx(expected, abs=5e-4)
    assert t_two_sided_p(expected, df) == pytest.approx(1 - confidence, abs=5e-5)


def test_paired_differences() -> None:
    result = paired([1.0, 2.0, 3.0, 4.0, 5.0], 0.95)
    assert result.mean == 3.0 and result.sd == pytest.approx(math.sqrt(2.5))
    # 3 ± 2.776 × 1.581 / √5
    assert (result.ci_low, result.ci_high) == (pytest.approx(1.0368, abs=1e-4),
                                               pytest.approx(4.9632, abs=1e-4))  # fmt: skip
    assert result.p_value == pytest.approx(0.01324, abs=1e-5)
    # The same difference on every seed: as consistent as data can be, but no spread.
    assert paired([2.0, 2.0, 2.0], 0.95).p_value == 0.0
    assert paired([0.0, 0.0, 0.0], 0.95).p_value == 1.0
    assert paired([4.0], 0.95).p_value is None  # one seed: nothing to test


def test_holm_adjustment() -> None:
    assert holm({"a": 0.01, "b": 0.04, "c": 0.03}) == {
        "a": pytest.approx(0.03), "c": pytest.approx(0.06), "b": pytest.approx(0.06)
    }  # fmt: skip


def _replicate(seed: int, labour: float, accuracy: float, errors: int, verdict="successful"):
    def row(metric, label, better, base, cand):
        return {"metric": metric, "label": label, "unit": "x", "better": better,
                "baseline": base, "candidate": cand, "delta": cand - base}  # fmt: skip

    return {
        "seed": seed,
        "verdict": verdict,
        "comparisons": [
            row(
                "labour_hours",
                "Simulated labour time (review + oversight)",
                "lower",
                20.0,
                20.0 + labour,
            ),  # fmt: skip
            row("accuracy", "Decisions matching ground truth", "higher", 0.95, 0.95 + accuracy),
            row("error_count", "Errors", "lower", 0, errors),
            row("ai_execution_cost", "AI execution cost", "none", 0.0, 2.0),
        ],
    }


def test_a_consistent_effect_is_significant_and_noise_is_not() -> None:
    reps = [
        _replicate(1, -10.0, 0.01, 0),
        _replicate(2, -12.0, -0.01, 0),
        _replicate(3, -9.0, 0.0, 0),
        _replicate(4, -11.0, 0.005, 0),
    ]
    stats = series_statistics(reps, 0.95)
    rows = {r["metric"]: r for r in stats["metrics"]}
    labour = rows["labour_hours"]
    assert labour["mean_delta"] == -10.5 and labour["relative_change"] == pytest.approx(-0.525)
    assert labour["ci_high"] < 0 and labour["significant"] and labour["finding"] == "improved"
    assert [s["seed"] for s in labour["per_seed"]] == [1, 2, 3, 4]
    assert rows["accuracy"]["finding"] == "no_significant_difference"
    assert rows["accuracy"]["ci_low"] < 0 < rows["accuracy"]["ci_high"]
    assert rows["error_count"]["finding"] == "no_significant_difference"  # zero on every seed
    assert rows["ai_execution_cost"]["finding"] == "informational"  # never tested
    assert stats["verdict"] == "successful" and stats["replicate_verdicts"]["successful"] == 4
    assert (
        "Over 4 seeds (95% interval per metric" in stats["conclusion"]
        and "labour time down 52.5%" in stats["conclusion"]
    )
    assert "accuracy" in stats["conclusion"] and "not significant" in stats["conclusion"]


def test_a_significant_regression_or_a_failed_replicate_fails_the_series() -> None:
    worse = [_replicate(s, -10.0 - s, 0.0, 3 + s % 2) for s in range(5)]
    stats = series_statistics(worse, 0.95)
    assert stats["significantly_worse"] == ["error_count"]
    assert (
        stats["verdict"] == "not_successful"
        and "Significantly worse: errors" in (stats["conclusion"])
    )
    mixed = [_replicate(1, -10, 0, 0), _replicate(2, -11, 0, 0, verdict="not_successful")]
    assert series_statistics(mixed, 0.95)["verdict"] == "not_successful"


# --- Series through the API ------------------------------------------------------------------


def _series(client: TestClient, headers: dict, **changes) -> dict:
    body = {
        "name": "KYC assistant, automated, 3 seeds",
        "tool_id": "agb-intelligent-kyc-assistant",
        "candidate_mode": "ai_automated",
        "profile": "custom",
        "applications": 20,
        "employees": 6,
        "seed": 17,
        "replicates": 3,
        **changes,
    }
    response = client.post("/api/v1/experiment-series", json=body, headers=headers)
    assert response.status_code == 202, response.text
    return client.get(f"/api/v1/experiment-series/{response.json()['id']}", headers=headers).json()


def test_a_series_runs_every_seed_and_tests_the_effect(
    api: TestClient,  # noqa: F811
    db: Session,
    lab: dict,  # noqa: F811
) -> None:
    series = _series(api, lab)
    assert series["status"] == "completed", series["failure_reason"]
    assert series["seeds"] == [17, 18, 19] and series["replicates_completed"] == 3
    assert series["tool_version"] == "1.0.0" and series["scenario_version"] >= 1
    experiments = series["experiments"]
    assert [e["status"] for e in experiments] == ["completed"] * 3
    assert [e["name"].split("seed ")[1] for e in experiments] == ["17", "18", "19"]
    stats = series["statistics"]
    assert stats["replicates"] == 3 and stats["confidence"] == 0.95
    labour = next(m for m in stats["metrics"] if m["metric"] == "labour_hours")
    assert labour["n"] == 3 and len(labour["per_seed"]) == 3
    # Automation removes most manual reviews on every seed: a large, consistent effect.
    assert (
        labour["mean_delta"] < 0 and labour["ci_low"] <= labour["mean_delta"] <= labour["ci_high"]
    )
    assert series["verdict"] == stats["verdict"]
    # Derived: recomputable from the replicates' stored evaluations.
    record = db.get(ExperimentSeries, uuid.UUID(series["id"]))
    assert series_service.compute(db, record, series_service.replicates(db, record)) == stats
    # The replicates are ordinary experiments, one per seed, tied to the series.
    tied = db.execute(select(Experiment).where(Experiment.series_id == record.id)).scalars()
    assert len(list(tied)) == 3
    listed = api.get("/api/v1/experiment-series", headers=lab).json()
    assert [s["series_number"] for s in listed["items"]] == [series["series_number"]]


def test_explicit_seeds_and_validation(api: TestClient, lab: dict) -> None:  # noqa: F811
    series = _series(api, lab, seeds=[5, 900], replicates=2)
    assert series["seeds"] == [5, 900] and series["status"] == "completed"
    duplicate = api.post(
        "/api/v1/experiment-series",
        json={"name": "dup", "tool_id": "agb-intelligent-kyc-assistant", "seeds": [3, 3]},
        headers=lab,
    )
    assert duplicate.status_code == 422 and "different" in duplicate.text
    one = api.post(
        "/api/v1/experiment-series",
        json={"name": "one", "tool_id": "agb-intelligent-kyc-assistant", "replicates": 1},
        headers=lab,
    )
    assert one.status_code == 422


def test_a_failed_replicate_fails_the_series(api: TestClient, db: Session) -> None:  # noqa: F811
    # No organization structure: the simulation cannot hire staff.
    register_tool(db, ToolCreate.model_validate(DEMO_AI_TOOLS[0]), actor_id=None)
    headers = auth(make_user(db, RoleCode.AI_RESEARCHER))
    series = _series(api, headers, applications=5, replicates=2)
    assert series["status"] == "failed" and series["statistics"] is None
    assert "seed 17" in series["failure_reason"] and "Retail Banking" in series["failure_reason"]


def test_only_permitted_roles_run_series(client: TestClient, db: Session) -> None:
    headers = auth(make_user(db, RoleCode.AUDITOR))
    assert client.get("/api/v1/experiment-series", headers=headers).status_code == 200
    response = client.post("/api/v1/experiment-series", json={}, headers=headers)
    assert response.status_code == 403 and "experiments:run" in response.text
