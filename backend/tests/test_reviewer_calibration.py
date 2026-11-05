"""Phase 82: reviewer behaviour calibrated from observed reviews instead of fixed."""

import random
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.simulation import calibration
from app.simulation.models import SimulationRun
from tests.factories import auth, make_user
from tests.test_experiments import _experiment, api, factory, lab  # noqa: F401, F811

TRUTH = {"mean_minutes": 18.0, "sigma": 0.6, "accuracy": 0.95, "accuracy_should_reject": 0.80,
         "review_time_factor": 0.7, "accuracy_when_ai_correct": 0.98,
         "accuracy_when_ai_wrong": 0.55}  # fmt: skip


def _pilot(n: int = 400, seed: int = 1, **changes) -> list[dict]:
    return calibration.pilot(n=n, seed=seed, **{**TRUTH, **changes})


def test_known_proportions_and_lognormal() -> None:
    # Wilson interval for 8 of 10 at 95 %: 0.490 to 0.943.
    w = calibration.wilson(8, 10)
    assert (w["estimate"], w["low"], w["high"]) == (0.8, pytest.approx(0.4902, abs=1e-4),
                                                    pytest.approx(0.9433, abs=1e-4))  # fmt: skip
    assert calibration.wilson(0, 0)["estimate"] is None
    # Identical log-spacing: a lognormal with known mean.
    fit = calibration.lognormal([10.0, 20.0, 40.0] * 20)
    assert (
        fit["mean_minutes"]["low"] < fit["mean_minutes"]["estimate"] < fit["mean_minutes"]["high"]
    )
    assert fit["sigma"]["estimate"] == pytest.approx(0.5704, abs=1e-3)


def test_the_fit_recovers_the_parameters_it_was_drawn_from() -> None:
    fitted = calibration.fit(_pilot(), ai_capable=True)
    r, a = fitted["reviewer"], fitted["ai_assistance"]
    values = {"mean_minutes": r["mean_minutes"], "sigma": r["sigma"], "accuracy": r["accuracy"],
              "accuracy_should_reject": r["accuracy_should_reject"],
              "review_time_factor": a["review_time_factor"],
              "accuracy_when_ai_correct": a["accuracy_when_ai_correct"],
              "accuracy_when_ai_wrong": a["accuracy_when_ai_wrong"]}  # fmt: skip
    for name, interval in values.items():
        assert interval["low"] <= TRUTH[name] <= interval["high"], name
    assert fitted["notes"] == [] and fitted["unassisted"] + fitted["assisted"] == 400
    # Over many pilots, the 95 % intervals cover the truth about 95 % of the time.
    covered = 0
    for seed in range(200):
        m = calibration.fit(_pilot(seed=1000 + seed), ai_capable=True)["reviewer"]["mean_minutes"]
        covered += m["low"] <= TRUTH["mean_minutes"] <= m["high"]
    assert 0.9 <= covered / 200 <= 0.99


def test_what_the_reviews_cannot_support_stays_an_assumption() -> None:
    with pytest.raises(ValueError, match="At least 30 reviews"):
        calibration.fit(_pilot(n=20, assisted_share=0.0), ai_capable=True)
    few_rejects = calibration.fit(_pilot(n=60, assisted_share=0.0, share_should_reject=0.05),
                                  ai_capable=True)  # fmt: skip
    assert few_rejects["reviewer"]["accuracy_should_reject"] is None
    assert "one accuracy for both" in few_rejects["notes"][0]
    assert few_rejects["ai_assistance"] is None and "assumption" in few_rejects["notes"][1]
    no_ai = calibration.fit(_pilot(), ai_capable=False)
    assert no_ai["ai_assistance"] is None and "no AI modes" in no_ai["notes"][0]


def test_draws_are_deterministic_and_vary_by_seed() -> None:
    fitted = calibration.fit(_pilot(), ai_capable=True)
    point = calibration.parameters(fitted, None)
    one = calibration.parameters(fitted, random.Random(7))
    assert one == calibration.parameters(fitted, random.Random(7))
    assert one != calibration.parameters(fitted, random.Random(8)) and one != point
    # Draws scatter around the estimate, within plausible bounds.
    draws = [calibration.parameters(fitted, random.Random(s))["reviewer"] for s in range(300)]
    mean = sum(d["mean_minutes"] for d in draws) / len(draws)
    assert mean == pytest.approx(point["reviewer"]["mean_minutes"], rel=0.03)
    assert all(0 <= d["accuracy_should_reject"] <= 1 for d in draws)


def test_runs_simulate_the_calibrated_reviewers(api: TestClient, db: Session, lab: dict) -> None:  # noqa: F811
    body = {"scenario_id": "retail-onboarding", "step_id": "account_approval",
            "source": "Synthetic pilot study for the test",
            "observations": _pilot(n=200)}  # fmt: skip
    created = api.post("/api/v1/reviewer-calibrations", json=body, headers=lab)
    assert created.status_code == 201, created.text
    record = created.json()
    assert record["status"] == "active" and record["observation_count"] == 200
    assert record["assumption"]["reviewer"]["mean_minutes"] == 12  # the scenario's assumption
    fitted = record["fitted"]["reviewer"]
    assert fitted["mean_minutes"]["low"] <= 18 <= fitted["mean_minutes"]["high"]

    # A new experiment simulates the calibrated reviewers, for baseline and candidate alike.
    e = _experiment(api, lab, candidate_mode="ai_assisted", applications=15, seed=5)
    assert e["status"] == "completed"
    runs = [db.get(SimulationRun, uuid.UUID(e[r]["id"])) for r in ("baseline", "candidate")]
    for run in runs:
        used = run.config["calibration"]
        assert used["ids"] == [record["id"]] and used["draw"] is False
        reviewers = run.config["scenario"]["reviewers"]
        assert reviewers["account_approval"]["mean_minutes"] == fitted["mean_minutes"]["estimate"]
        assert reviewers["compliance_review"]["mean_minutes"] == 35  # not calibrated: assumed
        assert (
            run.config["scenario"]["ai_assistance"]["accuracy_when_ai_wrong"]
            == (record["fitted"]["ai_assistance"]["accuracy_when_ai_wrong"]["estimate"])
        )
    # A rerun simulates exactly the same reviewers and reproduces the result.
    rerun = api.post(f"/api/v1/simulations/{runs[0].id}/rerun", headers=lab)
    assert rerun.status_code == 202, rerun.text
    again = db.get(SimulationRun, uuid.UUID(rerun.json()["id"]))
    db.refresh(again)
    assert again.config_hash == runs[0].config_hash
    assert again.result_digest == runs[0].result_digest

    # Uncalibrated, the assumptions apply; drawn, each seed has its own reviewers.
    plain = _experiment(api, lab, candidate_mode="ai_assisted", applications=15, seed=5,
                        calibrated=False)  # fmt: skip
    plain_run = db.get(SimulationRun, uuid.UUID(plain["baseline"]["id"]))
    assert "calibration" not in plain_run.config
    assert plain_run.config_hash != runs[0].config_hash
    drawn = [
        _experiment(
            api, lab, candidate_mode="ai_assisted", applications=15, seed=s, calibration_draws=True
        )  # fmt: skip
        for s in (6, 7)
    ]
    params = []
    for d in drawn:
        base, cand = (
            db.get(SimulationRun, uuid.UUID(d[r]["id"])) for r in ("baseline", "candidate")
        )
        assert base.config["calibration"]["reviewers"] == cand.config["calibration"]["reviewers"]
        params.append(base.config["calibration"]["reviewers"]["account_approval"])
    assert params[0] != params[1]

    # A second calibration supersedes the first; the list shows both.
    again_body = {**body, "observations": _pilot(n=200, seed=2)}
    second = api.post("/api/v1/reviewer-calibrations", json=again_body, headers=lab)
    assert second.status_code == 201
    listed = api.get("/api/v1/reviewer-calibrations?scenario_id=retail-onboarding", headers=lab)
    statuses = [(c["calibration_number"], c["status"]) for c in listed.json()][:2]
    assert statuses == [
        (second.json()["calibration_number"], "active"),
        (record["calibration_number"], "superseded"),
    ]
    assert api.get(f"/api/v1/reviewer-calibrations/{record['id']}", headers=lab).status_code == 200

    # Refusals: an unknown step, too few reviews, a reader.
    bad_step = api.post("/api/v1/reviewer-calibrations", json={**body, "step_id": "nope"},
                        headers=lab)  # fmt: skip
    assert bad_step.status_code == 422 and "no review step" in bad_step.text
    few_body = {**body, "observations": _pilot(n=10, assisted_share=0.0)}
    few = api.post("/api/v1/reviewer-calibrations", json=few_body, headers=lab)
    assert few.status_code == 422 and "At least 30" in few.text
    auditor = auth(make_user(db, RoleCode.AUDITOR))
    db.commit()
    assert api.post("/api/v1/reviewer-calibrations", json=body, headers=auditor).status_code == 403
    assert api.get("/api/v1/reviewer-calibrations", headers=auditor).status_code == 200
    assert db.execute(select(SimulationRun)).first() is not None
