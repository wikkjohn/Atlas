"""Tool comparison across all benchmarks (Phase 81, roadmap Milestone G, step 6).

A **benchmark** is a scenario version and a candidate mode. Tools — including two versions
of one tool — are compared on it only where the comparison is fair: two experiments form
a **matched pair** when their workloads are identical (scenario version, seed, sizes,
dataset, country rules, software), their baselines processed the same cases, and they
assumed the same costs. Then the only difference between the two candidates is the tool,
so per metric the differences across matched workloads get a paired t-test, with Holm's
adjustment across metrics.

Everything is derived from stored experiments on request; nothing is stored. Verdicts are
re-judged under each scenario's thresholds in force now (Phase 80), so tools evaluated at
different times are held to the same standard.
"""

import uuid
from datetime import UTC, datetime
from itertools import combinations
from statistics import fmean
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import BusinessRuleViolation
from app.modules.experiments import series as series_service
from app.modules.experiments import thresholds
from app.modules.experiments.measurements import canonical_hash
from app.modules.experiments.models import (
    Experiment,
    ExperimentEvaluation,
    ExperimentMeasurement,
    ExperimentSeries,
    ExperimentStatus,
)
from app.modules.experiments.schemas import SeriesCreate
from app.modules.experiments.significance import HEADLINE, _r, holm, paired
from app.simulation import runner
from app.simulation import service as simulations

CONFIDENCE = 0.95
MIN_MATCHED = 2


def _tool(e: Experiment) -> str:
    return f"{e.tool_id}@{e.tool_version}"


def _records(db: Session, scenario_id: str | None) -> list[dict[str, Any]]:
    """Every completed experiment of a tool, with what it is matched on."""
    query = (
        select(Experiment, ExperimentEvaluation)
        .join(ExperimentEvaluation, ExperimentEvaluation.experiment_id == Experiment.id)
        .where(Experiment.status == ExperimentStatus.COMPLETED, Experiment.tool_id.is_not(None))
        .order_by(Experiment.experiment_number)
    )
    if scenario_id:
        query = query.where(Experiment.scenario_id == scenario_id)
    rows = db.execute(query).all()
    ids = [e.id for e, _ in rows]
    baselines = {
        m.experiment_id: m.metrics
        for m in db.execute(
            select(ExperimentMeasurement).where(
                ExperimentMeasurement.experiment_id.in_(ids),
                ExperimentMeasurement.role == "baseline",
            )
        ).scalars()
    } if ids else {}  # fmt: skip
    records = []
    for experiment, evaluation in rows:
        base = baselines.get(experiment.id)
        if base is None:
            continue
        match = canonical_hash(
            {
                "workload": base["workload"],
                "cases": base["case_fingerprint"],
                "costs": experiment.configuration.get("costs"),
            }
        )
        records.append({"experiment": experiment, "evaluation": evaluation, "match": match,
                        "seed": base["workload"]["seed"]})  # fmt: skip
    return records


def _pair(a: str, b: str, left: dict, right: dict) -> dict[str, Any]:
    """Tool a against tool b on their matched workloads (latest experiment of each)."""
    keys = sorted(set(left) & set(right))
    rows: dict[str, dict[str, Any]] = {}
    for key in keys:
        ca = {c["metric"]: c for c in left[key]["evaluation"].comparisons}
        cb = {c["metric"]: c for c in right[key]["evaluation"].comparisons}
        for metric, row in ca.items():
            other = cb.get(metric)
            if row["better"] == "none" or other is None:
                continue
            if row["candidate"] is None or other["candidate"] is None:
                continue
            entry = rows.setdefault(
                metric,
                {"metric": metric, "label": row["label"], "unit": row["unit"],
                 "better": row["better"], "a": [], "b": []},
            )  # fmt: skip
            entry["a"].append(row["candidate"])
            entry["b"].append(other["candidate"])
    metrics, tested = [], {}
    for metric, entry in rows.items():
        stats = paired([x - y for x, y in zip(entry["a"], entry["b"], strict=True)], CONFIDENCE)
        mean_b = fmean(entry["b"])
        out = {
            "metric": metric,
            "label": entry["label"],
            "unit": entry["unit"],
            "better": entry["better"],
            "n": stats.n,
            "a_mean": _r(fmean(entry["a"])),
            "b_mean": _r(mean_b),
            "mean_difference": _r(stats.mean),
            "relative_difference": _r(stats.mean / mean_b) if mean_b and stats.mean is not None
            else None,
            "ci_low": _r(stats.ci_low),
            "ci_high": _r(stats.ci_high),
            "p_value": _r(stats.p_value, 8),
            "identical": entry["a"] == entry["b"],
        }  # fmt: skip
        if stats.p_value is not None:
            tested[metric] = stats.p_value
        metrics.append(out)
    adjusted = holm(tested)
    better, worse = [], []
    for m in metrics:
        m["p_adjusted"] = _r(adjusted.get(m["metric"]), 8)
        if m["n"] < MIN_MATCHED or m["p_adjusted"] is None:
            m["finding"] = "too_few_matched"
        elif m["p_adjusted"] >= 1 - CONFIDENCE or not m["mean_difference"]:
            m["finding"] = "no_significant_difference"
        else:
            lower = m["mean_difference"] < 0
            a_wins = lower if m["better"] == "lower" else not lower
            m["finding"] = "a_better" if a_wins else "b_better"
            (better if a_wins else worse).append(m["metric"])
    if len(keys) < MIN_MATCHED:
        outcome = "too_few_matched"
    elif better and worse:
        outcome = "trade_off"
    elif better:
        outcome = "a_preferred"
    elif worse:
        outcome = "b_preferred"
    elif metrics and all(m["identical"] for m in metrics):
        # Not merely indistinguishable: the same values on every matched workload.
        outcome = "identical"
    else:
        outcome = "no_difference"
    order = {k: i for i, k in enumerate(HEADLINE)}
    metrics.sort(key=lambda m: (order.get(m["metric"], len(order)), m["metric"]))
    return {
        "a": a,
        "b": b,
        "matched_workloads": len(keys),
        "seeds": sorted({left[k]["seed"] for k in keys}),
        "outcome": outcome,
        "a_better_on": better,
        "b_better_on": worse,
        "metrics": metrics,
    }


def compare(db: Session, scenario_id: str | None = None, tool: str | None = None) -> dict:
    """Every benchmark with two or more tools, or with the given tool; pairs; a scoreboard."""
    benchmarks: dict[tuple, dict[str, dict[str, dict]]] = {}
    for record in _records(db, scenario_id):
        e = record["experiment"]
        key = (e.scenario_id, e.scenario_version, e.candidate_mode)
        # The latest experiment of a tool on a workload stands for it.
        benchmarks.setdefault(key, {}).setdefault(_tool(e), {})[record["match"]] = record
    out, board = [], {}
    for (sid, version, mode), tools in sorted(benchmarks.items()):
        if tool is not None and tool not in tools:
            continue
        if tool is None and len(tools) < 2 and scenario_id is None:
            continue
        tier, _ = thresholds.tier_of(sid)
        ranked = []
        for name, by_match in tools.items():
            records = list(by_match.values())
            now = [thresholds.reassess(db, r["experiment"]) for r in records]
            changes = {}
            for metric in HEADLINE:
                values = [
                    c["relative_change"]
                    for r in records
                    for c in r["evaluation"].comparisons
                    if c["metric"] == metric and c["relative_change"] is not None
                ]
                changes[metric] = _r(fmean(values)) if values else None
            ranked.append(
                {
                    "tool": name,
                    "tool_id": records[0]["experiment"].tool_id,
                    "tool_version": records[0]["experiment"].tool_version,
                    "experiments": len(records),
                    "successful": sum(n is not None and n["verdict"] == "successful" for n in now),
                    "successful_stored": sum(
                        r["evaluation"].verdict == "successful" for r in records
                    ),  # fmt: skip
                    "mean_relative_change": changes,
                }
            )
        pairs = [_pair(a, b, tools[a], tools[b]) for a, b in combinations(sorted(tools), 2)]
        preferred = {t["tool"]: 0 for t in ranked}
        for p in pairs:
            if p["outcome"] == "a_preferred":
                preferred[p["a"]] += 1
            elif p["outcome"] == "b_preferred":
                preferred[p["b"]] += 1
        beaten = {t["tool"]: 0 for t in ranked}
        for p in pairs:
            if p["outcome"] == "a_preferred":
                beaten[p["b"]] += 1
            elif p["outcome"] == "b_preferred":
                beaten[p["a"]] += 1
        for t in ranked:
            t["preferred_in"] = preferred[t["tool"]]
            t["not_preferred_in"] = beaten[t["tool"]]

        # Ranked only on evidence that compares like with like: the share of experiments
        # that succeed under the scenario's thresholds, then matched head-to-heads. Tools
        # nothing separates share a rank (averages over unmatched workloads never decide).
        def standing(t: dict) -> tuple:
            return (-round(t["successful"] / t["experiments"], 6), -t["preferred_in"],
                    t["not_preferred_in"])  # fmt: skip

        ranked.sort(key=lambda t: (standing(t), t["tool"]))
        for t in ranked:
            t["rank"] = 1 + sum(standing(o) < standing(t) for o in ranked)
        out.append({"scenario_id": sid, "scenario_version": version, "candidate_mode": mode,
                     "risk_tier": tier, "tools": ranked, "pairs": pairs})  # fmt: skip
        for t in ranked:
            row = board.setdefault(t["tool"], {
                "tool": t["tool"], "tool_id": t["tool_id"], "tool_version": t["tool_version"],
                "benchmarks": 0, "ranked_first": 0, "experiments": 0, "successful": 0,
                "preferred": 0, "not_preferred": 0, "trade_off": 0, "no_difference": 0,
                "too_few_matched": 0, "identical": 0,
            })  # fmt: skip
            row["benchmarks"] += 1
            row["ranked_first"] += t["rank"] == 1 and len(ranked) > 1
            row["experiments"] += t["experiments"]
            row["successful"] += t["successful"]
        for p in pairs:
            for side, other in (("a", "b"), ("b", "a")):
                row = board[p[side]]
                if p["outcome"] == f"{side}_preferred":
                    row["preferred"] += 1
                elif p["outcome"] == f"{other}_preferred":
                    row["not_preferred"] += 1
                else:
                    row[p["outcome"]] += 1
    scoreboard = sorted(
        board.values(), key=lambda r: (-r["preferred"], r["not_preferred"], r["tool"])
    )
    return {
        "benchmarks": out,
        "scoreboard": scoreboard,
        "confidence": CONFIDENCE,
        "method": "Two tools are compared on a benchmark (scenario version and mode) only on "
        "matched workloads: identical workload, baseline cases and cost assumptions, so the "
        "tool is the only difference. Per metric, the differences of the candidates' values "
        f"get a paired t-test; Holm's adjustment across metrics; significant below "
        f"{1 - CONFIDENCE:.2f}. A tool is preferred when it is significantly better on at "
        "least one metric and worse on none; a trade-off when both; identical when every value "
        "matched. Ranks: the share of experiments successful under the scenario's thresholds, "
        "then head-to-heads won and lost; tools nothing separates share a rank. Verdicts are "
        "re-judged under each scenario's thresholds in force now; the latest experiment of a "
        "tool on a workload stands for it. Nothing is stored.",
    }


# --- Running a comparison ----------------------------------------------------------------------

MAX_TOOLS = 5


def start(db: Session, body, actor_id: uuid.UUID) -> list[ExperimentSeries]:
    """One repeated-seed series per tool on the same scenario, seeds and sizes, so every
    pair of tools is matched on every seed."""
    tools = [(t.tool_id, t.tool_version) for t in body.tools]
    if len(set(tools)) != len(tools):
        raise BusinessRuleViolation("Each tool version may be compared only once.")
    simulations.reap_stale(db)
    simulations._ensure_idle(db)  # once: the series' runs then queue behind each other
    created = []
    for tool_id, tool_version in tools:
        created.append(
            series_service.create(
                db,
                SeriesCreate(
                    name=f"{body.name} · {tool_id} {tool_version or ''}".strip(),
                    scenario_id=body.scenario_id,
                    scenario_version=body.scenario_version,
                    tool_id=tool_id,
                    tool_version=tool_version,
                    candidate_mode=body.candidate_mode,
                    profile="custom",
                    applications=body.applications,
                    employees=body.employees,
                    seed=body.seed,
                    replicates=body.replicates,
                    country=body.country,
                    costs=body.costs,
                ),
                actor_id,
                check_idle=False,
            )
        )
    versions = {s.scenario_version for s in created}
    if len(versions) != 1:
        raise BusinessRuleViolation("The tools must run the same scenario version.")
    return created


def execute(session_factory: sessionmaker[Session], series_ids: list[uuid.UUID],
            run_ids: list[uuid.UUID]) -> None:  # fmt: skip
    """Background job: every series' runs, one after another, then each series' statistics."""
    runner.execute_batch(session_factory, run_ids)
    with session_factory() as db:
        for series_id in series_ids:
            series = db.get(ExperimentSeries, series_id)
            if series is None:
                continue
            try:
                series_service.refresh(db, series)
                db.commit()
            except Exception as exc:  # recorded on the series; nothing awaits this job
                db.rollback()
                series = db.get(ExperimentSeries, series_id)
                if series is not None:
                    series.status = ExperimentStatus.FAILED.value
                    series.failure_reason = f"Evaluation failed: {type(exc).__name__}: {exc}"
                    series.completed_at = datetime.now(UTC)
                    db.commit()
