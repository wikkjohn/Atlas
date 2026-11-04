"""Phase 79: AI guardrails — record audit, drift and bias across segments."""

import uuid
from collections import Counter
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.ai_tools import guardrails
from app.modules.ai_tools.models import AIToolInvocation
from app.modules.ai_tools.service import find_tool, invoke, record_hash
from tests.test_experiments import _experiment, api, factory, lab  # noqa: F401  (fixtures)

# --- Distributions, against published tables -------------------------------------------------


@pytest.mark.parametrize(
    ("statistic", "df", "p"),
    [(3.841, 1, 0.05), (5.991, 2, 0.05), (11.070, 5, 0.05), (6.635, 1, 0.01), (2.0, 3, 0.5724)],
)
def test_chi_square_tail(statistic: float, df: int, p: float) -> None:
    assert guardrails.chi2_sf(statistic, df) == pytest.approx(p, abs=2e-4)


def test_psi_welch_and_proportions() -> None:
    same = Counter(approve=80, reject=20)
    assert guardrails.psi(same, Counter(approve=40, reject=10)) == 0.0
    shifted = guardrails.psi(same, Counter(approve=50, reject=50))
    # (0.5-0.8)·ln(0.5/0.8) + (0.5-0.2)·ln(0.5/0.2) = 0.4159
    assert shifted == pytest.approx(0.4159, abs=1e-4) and guardrails.psi_status(shifted) == (
        "significant"
    )
    assert guardrails.psi_status(0.05) == "stable" and guardrails.psi_status(0.2) == "moderate"
    # A large PSI that a chi-square test cannot tell from noise is not drift.
    assert guardrails.psi_status(0.9, p_value=0.4) == "stable"
    assert guardrails.welch([1.0, 1.1, 0.9, 1.0], [1.0, 1.0, 1.1, 0.9]) == pytest.approx(1.0)
    assert guardrails.welch([1.0, 1.1, 0.9, 1.0], [2.0, 2.1, 1.9, 2.0]) < 0.001
    assert guardrails.two_proportions(5, 100, 5, 100) == 1.0
    # 10/100 against 30/100: z = 3.54, p = 0.0004
    assert guardrails.two_proportions(10, 100, 30, 100) == pytest.approx(0.0004, abs=1e-4)
    assert guardrails.chi2_independence([[10, 0], [5, 0]]) is None  # one column only


def test_segments_come_from_the_input() -> None:
    payload = {
        "as_of": "2026-01-07",
        "application": {
            "country_code": "JP",
            "date_of_birth": "1954-12-22",
            "account_type": "current",
            "documents": [{"date_of_birth": "1990-01-01"}],
        },
    }
    assert guardrails.segments(payload, date(2030, 1, 1)) == {
        "country": "JP", "age band": "70 and over", "account type": "current"
    }  # fmt: skip
    assert guardrails.segments({"profile": {"days": 3}}, date(2026, 1, 1)) == {}


# --- Bias, on calls built by hand ------------------------------------------------------------


def _calls(groups: dict[str, list[tuple[str, str | None]]]) -> tuple[list, dict]:
    """Calls per country: (recommendation, ground truth)."""
    calls, truth = [], {}
    for country, rows in groups.items():
        for recommendation, expected in rows:
            execution = uuid.uuid4()
            calls.append(SimpleNamespace(
                status="succeeded", output={"recommendation": recommendation, "confidence": 0.8},
                input={"application": {"country_code": country}}, execution_id=execution,
                occurred_at=datetime(2026, 1, 5, tzinfo=UTC)))  # fmt: skip
            if expected:
                truth[execution] = expected
    return calls, truth


@pytest.fixture
def tool_stub(monkeypatch):
    def use(calls, truth):
        monkeypatch.setattr(guardrails, "_tool", lambda db, i: SimpleNamespace(
            id=i, tool_id="t", tool_version="1.0.0"))  # fmt: skip
        monkeypatch.setattr(guardrails, "_invocations", lambda db, tool, **kw: calls)
        monkeypatch.setattr(guardrails, "_truth", lambda db, c: truth)

    return use


def test_unequal_false_rejections_are_a_disparity(tool_stub) -> None:
    # Both groups have 40 cases that should be approved; JP's are rejected 10 times as often.
    calls, truth = _calls({
        "GB": [("approve", "approved")] * 38 + [("reject", "approved")] * 2,
        "JP": [("approve", "approved")] * 20 + [("reject", "approved")] * 20,
    })  # fmt: skip
    tool_stub(calls, truth)
    report = guardrails.bias(None, uuid.uuid4())
    (country,) = report["attributes"]
    assert country["test"] == "equal_opportunity"
    assert {g["group"]: g["false_rejection_rate"] for g in country["groups"]} == {
        "GB": 0.05, "JP": 0.5
    }  # fmt: skip
    assert country["false_rejection_gap"] == pytest.approx(0.45)
    assert country["p_adjusted"] < 0.001 and country["finding"] == "disparity"
    assert country["four_fifths_rule"] is False  # 0.5 / 0.95
    assert report["status"] == "flagged" and report["flagged"] == ["country"]


def test_a_different_case_mix_is_not_a_disparity(tool_stub) -> None:
    # JP has more cases that should be rejected; among should-approve cases both groups are
    # treated alike, so the lower approval rate is the case mix, not the tool.
    calls, truth = _calls({
        "GB": [("approve", "approved")] * 36 + [("reject", "approved")] * 4
        + [("reject", "rejected")] * 10,
        "JP": [("approve", "approved")] * 27 + [("reject", "approved")] * 3
        + [("reject", "rejected")] * 30,
    })  # fmt: skip
    tool_stub(calls, truth)
    (country,) = guardrails.bias(None, uuid.uuid4())["attributes"]
    assert country["test"] == "equal_opportunity" and country["finding"] == "no_disparity"
    assert country["four_fifths_rule"] is False  # approvals 0.72 vs 0.45, explained by mix


def test_without_ground_truth_parity_and_the_four_fifths_rule_decide(tool_stub) -> None:
    calls, truth = _calls({
        "GB": [("approve", None)] * 36 + [("reject", None)] * 4,
        "JP": [("approve", None)] * 20 + [("reject", None)] * 20,
        "SG": [("approve", None)] * 5,  # under 20 cases: left out
    })  # fmt: skip
    tool_stub(calls, truth)
    (country,) = guardrails.bias(None, uuid.uuid4())["attributes"]
    assert country["test"] == "demographic_parity" and country["excluded_groups"] == ["SG"]
    assert country["approval_ratio"] == pytest.approx(0.5 / 0.9, abs=1e-5)
    assert country["finding"] == "disparity"


# --- Through real calls and runs -------------------------------------------------------------


def test_every_call_is_hashed_and_tampering_is_found(db: Session, lab: dict) -> None:  # noqa: F811
    tool = find_tool(db, "agb-intelligent-kyc-assistant")
    application = {"applicant_name": "Mei Lin", "country_code": "SG", "documents": [],
                   "date_of_birth": "1990-05-01", "account_type": "current"}  # fmt: skip
    payload = {"application": application}
    call = invoke(db, tool, "recommend_decision", payload, actor_id=None)
    assert call.record_hash and call.record_hash == record_hash(call)
    db.flush()
    db.expire_all()
    assert guardrails.verify_audit(db, tool_record_id=tool.id)["status"] == "intact"
    db.execute(
        text("UPDATE ai_tool_invocations SET input = jsonb_set(input, '{tampered}', 'true') "
             "WHERE id = :id"),
        {"id": call.id},
    )  # fmt: skip
    db.expire_all()
    report = guardrails.verify_audit(db, tool_record_id=tool.id)
    assert report["status"] == "altered" and report["mismatched_ids"] == [str(call.id)]


def test_bias_and_drift_over_simulation_runs(api: TestClient, db: Session, lab: dict) -> None:  # noqa: F811
    first = _experiment(api, lab, candidate_mode="ai_assisted", applications=40, seed=31)
    second = _experiment(api, lab, candidate_mode="ai_assisted", applications=40, seed=32)
    assert first["status"] == second["status"] == "completed"
    tool = find_tool(db, "agb-intelligent-kyc-assistant")
    runs = api.get(f"/api/v1/ai-tools/{tool.id}/runs", headers=lab).json()
    # Cases screened out earlier never reach the assistant: up to 40 calls a run.
    assert len(runs) == 2 and all(0 < r["calls"] <= 40 for r in runs)
    bias = api.get(f"/api/v1/ai-tools/{tool.id}/bias?run_id={runs[0]['id']}&min_group=5",
                   headers=lab).json()  # fmt: skip
    assert 0 < bias["recommendations"] <= runs[0]["calls"]
    assert bias["with_ground_truth"] == bias["recommendations"]
    assert {a["attribute"] for a in bias["attributes"]} >= {"country", "age band"}
    assert bias["status"] in {"clear", "flagged", "insufficient_data"}
    drift = api.get(
        f"/api/v1/ai-tools/{tool.id}/drift?reference_run_id={runs[1]['id']}"
        f"&current_run_id={runs[0]['id']}",
        headers=lab,
    ).json()
    assert (drift["reference"]["calls"], drift["current"]["calls"]) == (
        runs[1]["calls"], runs[0]["calls"]
    )  # fmt: skip
    assert drift["recommendations"]["status"] in {"stable", "moderate", "significant"}
    assert set(drift["recommendations"]["shares"]) >= {"approve"}
    # Two seeds of the same workload: the inputs' countries stay put.
    country = next(i for i in drift["inputs"] if i["attribute"] == "country")
    assert country["status"] == "stable"
    refused = api.get(f"/api/v1/ai-tools/{tool.id}/drift", headers=lab)
    assert refused.status_code == 422
    audit = api.get("/api/v1/ai-tools/audit/verify", headers=lab).json()
    assert audit["status"] == "intact" and audit["unhashed"] == 0
    assert audit["valid"] == audit["checked"] >= runs[0]["calls"] + runs[1]["calls"]
    stored = db.query(AIToolInvocation).filter_by(simulation_run_id=uuid.UUID(runs[0]["id"]))
    assert all(c.record_hash == record_hash(c) for c in stored)
