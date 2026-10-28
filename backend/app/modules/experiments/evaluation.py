"""The evaluation engine: derived results from raw measurements and stated assumptions.

Pure functions — no database, no clock — so an evaluation is a deterministic function of
(baseline measurements, candidate measurements, configuration). Its digest therefore
proves that a re-evaluation reproduced the same result.
"""

from dataclasses import dataclass
from typing import Any, Literal

from app.modules.experiments.assumptions import CostAssumptions, EvaluationConfig
from app.modules.experiments.measurements import canonical_hash

EVALUATION_VERSION = "eval-1"

# Cost lines in reading order (stored JSONB does not keep key order).
COST_LINES = {
    "review_labour": "Review labour",
    "automation_oversight": "Oversight of automated decisions",
    "ai_execution": "AI execution",
    "infrastructure": "Infrastructure",
    "exception_handling": "Exception handling",
    "manual_escalation": "Manual escalation",
}

LIMITATIONS = [
    "All customers, staff, documents and outcomes are synthetic; nothing here is evidence "
    "about a real bank's operations.",
    "Costs are estimates computed from the stated assumptions, not measured spending. They "
    "are not verified savings.",
    "Reviewer time and accuracy are simulated; the effect of AI advice on reviewers is an "
    "assumption of the scenario, not an observation.",
    "Workflow steps take no simulated time, so processing time reflects waiting for people "
    "and documents only.",
    "The tested tool is evaluated on one scenario, one seed and one workload size; other "
    "mixes of cases may give different results.",
]


def _rate(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def costs(m: dict[str, Any], a: CostAssumptions) -> dict[str, Any]:
    """Operating cost of one run, line by line, with the inputs each line used."""
    review_minutes = m["review_seconds"] / 60
    oversight_minutes = (
        m["automated_approvals"] * a.oversight_sample_rate * a.oversight_minutes_per_sample
    )
    lines = {
        "review_labour": review_minutes * a.reviewer_cost_per_minute,
        "automation_oversight": oversight_minutes * a.reviewer_cost_per_minute,
        "ai_execution": m["ai"]["executed_invocations"] * a.ai_cost_per_invocation,
        "infrastructure": a.infrastructure_cost_per_run
        + m["cases"] * a.infrastructure_cost_per_case,
        "exception_handling": m["exceptions"] * a.exception_handling_cost,
        "manual_escalation": m["escalations"] * a.manual_escalation_cost,
    }
    total = sum(lines.values())
    risk = {
        "false_approvals": m["false_approvals"] * a.false_approval_cost,
        "false_rejections": m["false_rejections"] * a.false_rejection_cost,
    }
    return {
        "inputs": {
            "review_minutes": round(review_minutes, 2),
            "oversight_minutes": round(oversight_minutes, 2),
            "executed_ai_invocations": m["ai"]["executed_invocations"],
            "cases": m["cases"],
            "exceptions": m["exceptions"],
            "escalations": m["escalations"],
            "false_approvals": m["false_approvals"],
            "false_rejections": m["false_rejections"],
        },
        "lines": {k: round(v, 2) for k, v in lines.items()},
        "operating_total": round(total, 2),
        "cost_per_completed_case": round(total / m["completed"], 4) if m["completed"] else None,
        "risk_exposure": {k: round(v, 2) for k, v in risk.items()},
        "risk_exposure_total": round(sum(risk.values()), 2),
    }


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str
    unit: str
    better: Literal["lower", "higher", "none"]  # "none": informational, never a regression


METRICS = [
    MetricSpec(
        "processing_time_hours", "Workflow processing time (average cycle)", "hours", "lower"
    ),
    MetricSpec("processing_time_p95_hours", "Workflow processing time (p95)", "hours", "lower"),
    MetricSpec("labour_hours", "Simulated labour time (review + oversight)", "hours", "lower"),
    MetricSpec("manual_reviews", "Manual reviews", "count", "lower"),
    MetricSpec("cost_per_completed_case", "Cost per completed case", "currency", "lower"),
    MetricSpec("completion_rate", "Successful completion rate", "ratio", "higher"),
    MetricSpec("accuracy", "Decisions matching ground truth", "ratio", "higher"),
    MetricSpec(
        "false_approval_rate", "False approval rate (of should-reject cases)", "ratio", "lower"
    ),
    MetricSpec(
        "false_rejection_rate", "False rejection rate (of should-approve cases)", "ratio", "lower"
    ),
    MetricSpec(
        "escalation_rate", "Escalation rate (compliance reviews per case)", "ratio", "lower"
    ),
    MetricSpec("policy_violation_rate", "Policy violation rate (per decision)", "ratio", "lower"),
    MetricSpec("error_count", "Errors (failed executions and AI errors)", "count", "lower"),
    MetricSpec("ai_execution_cost", "AI execution cost", "currency", "none"),
    MetricSpec("operating_cost", "Overall operating cost", "currency", "lower"),
]


def metric_values(m: dict[str, Any], c: dict[str, Any], a: CostAssumptions) -> dict[str, Any]:
    cycle = m["cycle_seconds"]
    labour_minutes = m["review_seconds"] / 60 + c["inputs"]["oversight_minutes"]
    return {
        "processing_time_hours": cycle["avg"] / 3600 if cycle["avg"] is not None else None,
        "processing_time_p95_hours": cycle["p95"] / 3600 if cycle["p95"] is not None else None,
        "labour_hours": labour_minutes / 60,
        "manual_reviews": m["manual_reviews"],
        "cost_per_completed_case": c["cost_per_completed_case"],
        "completion_rate": _rate(m["completed"], m["cases"]),
        "accuracy": _rate(m["correct"], m["cases"]),
        "false_approval_rate": _rate(m["false_approvals"], m["should_reject"]) or 0.0,
        "false_rejection_rate": _rate(m["false_rejections"], m["should_approve"]) or 0.0,
        "escalation_rate": _rate(m["escalations"], m["cases"]),
        "policy_violation_rate": _rate(m["policy_violations"], m["decisions_checked"]) or 0.0,
        "error_count": m["failed_executions"] + m["ai"]["errors"],
        "ai_execution_cost": c["lines"]["ai_execution"],
        "operating_cost": c["operating_total"],
    }


def compare(base: dict[str, Any], cand: dict[str, Any], tolerance: float) -> list[dict[str, Any]]:
    rows = []
    for spec in METRICS:
        b, c = base[spec.key], cand[spec.key]
        delta = None if b is None or c is None else c - b
        relative = None if delta is None or not b else delta / abs(b)
        worse = improved = False
        if delta is not None and spec.better != "none" and delta != 0:
            direction = 1 if spec.better == "higher" else -1
            improved = delta * direction > 0
            # Worse by more than the tolerance (any worsening from a zero baseline counts).
            worse = not improved and (relative is None or abs(relative) > tolerance)
        rows.append(
            {
                "metric": spec.key,
                "label": spec.label,
                "unit": spec.unit,
                "better": spec.better,
                "baseline": _round(b),
                "candidate": _round(c),
                "delta": _round(delta),
                "relative_change": _round(relative),
                "improved": improved,
                "regression": worse,
            }
        )
    return rows


def _round(value: float | int | None) -> float | int | None:
    if value is None or isinstance(value, int):
        return value
    return round(value, 6)


def criteria(
    bm: dict[str, Any],
    cm: dict[str, Any],
    base: dict[str, Any],
    cand: dict[str, Any],
    config: EvaluationConfig,
) -> list[dict[str, Any]]:
    t, a = config.thresholds, config.costs
    results = []

    def check(key: str, label: str, passed: bool, detail: str) -> None:
        results.append({"criterion": key, "label": label, "passed": passed, "detail": detail})

    differences = [k for k in bm["workload"] if bm["workload"][k] != cm["workload"].get(k)]
    same_cases = bm["case_fingerprint"] == cm["case_fingerprint"]
    check(
        "equivalent_workloads",
        "The comparison uses equivalent workloads",
        not differences and same_cases and bm["mode"] == "baseline",
        "Same scenario, workflow version, seed, sizes, dataset, assumptions and software; "
        "identical applications with identical ground truth."
        if not differences and same_cases
        else f"Differs in: {', '.join(differences) or 'the generated applications'}.",
    )

    gains = {
        key: -cand[key] / base[key] + 1
        for key in ("processing_time_hours", "labour_hours", "cost_per_completed_case")
        if base[key] and cand[key] is not None
    }
    best = max(gains.items(), key=lambda kv: kv[1]) if gains else None
    check(
        "measurable_improvement",
        f"Performance improves measurably (≥ {t.min_improvement:.0%} on time, labour or cost)",
        best is not None and best[1] >= t.min_improvement,
        f"Best improvement: {best[0].replace('_', ' ')} {best[1]:.1%}." if best else "No data.",
    )

    accuracy_ok = (
        cand["accuracy"] is not None
        and base["accuracy"] is not None
        and cand["accuracy"] >= base["accuracy"] - t.max_accuracy_drop
    )
    completion_ok = (cand["completion_rate"] or 0) >= (base["completion_rate"] or 0)
    check(
        "correctness_acceptable",
        "Correctness remains acceptable",
        accuracy_ok and completion_ok,
        f"Accuracy {_pct(base['accuracy'])} → {_pct(cand['accuracy'])} (allowed drop "
        f"{t.max_accuracy_drop:.1%}); completion {_pct(base['completion_rate'])} → "
        f"{_pct(cand['completion_rate'])}.",
    )

    error_rate = _rate(cand["error_count"], cm["cases"]) or 0.0
    compliance = (
        cand["false_approval_rate"] <= t.max_false_approval_rate
        and cand["false_rejection_rate"] <= t.max_false_rejection_rate
        and error_rate <= t.max_error_rate
    )
    check(
        "compliance_thresholds",
        "Compliance thresholds are satisfied",
        compliance,
        f"False approvals {_pct(cand['false_approval_rate'])} (max "
        f"{t.max_false_approval_rate:.1%}), false rejections "
        f"{_pct(cand['false_rejection_rate'])} (max {t.max_false_rejection_rate:.1%}), "
        f"errors {error_rate:.1%} of cases (max {t.max_error_rate:.1%}).",
    )

    violations = cm["policy_violations"]
    check(
        "authorization_controls",
        "Authorization controls remain effective",
        violations <= t.max_policy_violations and bm["policy_violations"] == 0,
        f"{cm['decisions_checked']} account decisions checked: {violations} violation(s) "
        f"(max {t.max_policy_violations}); {cm['ai']['blocked']} unauthorized tool action(s) "
        "were blocked.",
    )

    missing = []
    if cm["ai"]["executed_invocations"] and a.ai_cost_per_invocation <= 0:
        missing.append("AI execution is assumed to cost nothing")
    if cm["automated_approvals"] and (
        a.oversight_sample_rate <= 0 or a.oversight_minutes_per_sample <= 0
    ):
        missing.append("automated decisions are assumed to need no human oversight")
    if a.reviewer_cost_per_minute <= 0:
        missing.append("human review is assumed to cost nothing")
    check(
        "costs_complete",
        "Costs include AI operation and human oversight",
        not missing,
        "AI execution, oversight of automated decisions and human review are all costed."
        if not missing
        else (lambda t: t[0].upper() + t[1:])("; ".join(missing)) + ".",
    )
    return results


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def evaluate(
    baseline: dict[str, Any], candidate: dict[str, Any], config: EvaluationConfig
) -> dict[str, Any]:
    a = config.costs
    base_costs, cand_costs = costs(baseline, a), costs(candidate, a)
    base = metric_values(baseline, base_costs, a)
    cand = metric_values(candidate, cand_costs, a)
    comparisons = compare(base, cand, config.thresholds.regression_tolerance)
    checks = criteria(baseline, candidate, base, cand, config)
    successful = all(c["passed"] for c in checks)
    verdict = "successful" if successful else "not_successful"
    conclusion = _conclusion(comparisons, checks, successful, a)
    derived = {
        "evaluation_version": EVALUATION_VERSION,
        "costs": {"baseline": base_costs, "candidate": cand_costs},
        "comparisons": comparisons,
        "criteria": checks,
        "verdict": verdict,
        "conclusion": conclusion,
        "limitations": LIMITATIONS,
    }
    derived["evaluation_digest"] = canonical_hash(derived)
    return derived


def _conclusion(
    comparisons: list[dict[str, Any]],
    checks: list[dict[str, Any]],
    successful: bool,
    a: CostAssumptions,
) -> str:
    by_key = {r["metric"]: r for r in comparisons}

    def change(key: str) -> str:
        rel = by_key[key]["relative_change"]
        if rel is None or rel == 0:
            return "unchanged"
        return f"{'down' if rel < 0 else 'up'} {abs(rel):.1%}"

    regressions = [r["label"] for r in comparisons if r["regression"]]
    failed = [c["label"] for c in checks if not c["passed"]]
    text = (
        f"Compared with the baseline, simulated labour time is {change('labour_hours')}, "
        f"manual reviews are {change('manual_reviews')}, average processing time is "
        f"{change('processing_time_hours')} and estimated cost per completed case is "
        f"{change('cost_per_completed_case')} (cost assumptions in {a.currency_label}). "
    )
    text += f"Regressions: {', '.join(regressions)}. " if regressions else "No metric regressed. "
    if successful:
        text += (
            "Every success criterion is met. Recommendation: the candidate merits a "
            "controlled pilot with real-world validation; these figures are simulated "
            "estimates on synthetic data, not verified savings."
        )
    else:
        text += (
            f"Not successful — failed criteria: {'; '.join(failed)}. Recommendation: do not "
            "proceed on this evidence."
        )
    return text
