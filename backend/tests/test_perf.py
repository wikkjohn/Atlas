"""Phase 16: the performance suite's targets and report (the benchmarks themselves run
against a scratch database with `python -m app.cli perf`, not inside the test transaction)."""

import pytest

from app import perf
from app.perf import Benchmark, Context, Target


def test_targets_judge_throughput_and_latency_per_profile() -> None:
    throughput = Target("cases/s", minimum={"quick": 1.5, "full": 3})
    assert throughput.met("full", 3.0) is True
    assert throughput.met("full", 2.9) is False
    assert throughput.met("quick", 2.0) is True
    assert throughput.describe("full") == ">= 3 cases/s"
    latency = Target("ms", maximum={"full": 150})
    assert latency.met("full", 151) is False and latency.describe("full") == "<= 150 ms"
    assert latency.met("quick", 10_000) is None  # no quick target: recorded only


def test_the_suite_records_values_misses_and_errors(monkeypatch) -> None:
    def broken(ctx: Context):
        raise RuntimeError("no admin")

    monkeypatch.setattr(
        perf,
        "BENCHMARKS",
        (
            Benchmark("fast", "meets", Target("x/s", minimum={"quick": 1}), lambda c: (5, {})),
            Benchmark("slow", "misses", Target("x/s", minimum={"quick": 10}), lambda c: (5, {})),
            Benchmark("broken", "fails", Target("ms", maximum={"quick": 1}), broken),
            Benchmark(
                "full-only", "skipped", Target("x", minimum={}), lambda c: (1, {}), ("full",)
            ),
        ),
    )
    report = perf.run(None, "quick")

    results = {r["name"]: r for r in report["results"]}
    assert set(results) == {"fast", "slow", "broken"}
    assert (results["fast"]["ok"], results["slow"]["ok"]) == (True, False)
    assert results["broken"]["value"] is None and "no admin" in results["broken"]["error"]
    assert report["passed"] is False
    text = perf.render(report)
    assert "MISS  slow" in text and "FAILED" in text and "no admin" in text

    only = perf.run(None, "quick", only=["fast"])
    assert [r["name"] for r in only["results"]] == ["fast"] and only["passed"] is True


def test_the_suite_refuses_to_run_in_production(monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "environment", "production")
    with pytest.raises(RuntimeError, match="not in production"):
        perf.run(None, "quick")
