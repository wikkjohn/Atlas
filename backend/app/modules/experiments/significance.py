"""Statistics for repeated-seed experiments (Phase 77, roadmap Milestone G step 2).

One experiment compares a baseline and a candidate on one seeded workload: a single
draw. A series repeats it over several seeds, so every metric has one paired difference
(candidate minus baseline) per seed. From those this module gives, per metric:

- the mean difference and its confidence interval (Student's t, n - 1 degrees of freedom);
- a two-sided paired t-test p-value;
- the p-value adjusted for testing many metrics at once (Holm's step-down method), which
  decides whether a difference is called significant.

The seeds vary the generated cases, reviewers and their decisions; what a series measures
is how much a tool's effect varies with the workload, not uncertainty in the simulation's
assumptions (see the experiment's limitations). Only the standard library is used.
"""

import math
from dataclasses import dataclass
from statistics import fmean, stdev
from typing import Any

# The metrics that lead the conclusion, in order.
HEADLINE = ("labour_hours", "cost_per_completed_case", "processing_time_hours", "accuracy")
SHORT_NAMES = {
    "labour_hours": "labour time",
    "cost_per_completed_case": "cost per completed case",
    "processing_time_hours": "processing time",
    "accuracy": "accuracy",
    "error_count": "errors",
}


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction of the incomplete beta function (modified Lentz)."""
    tiny, eps = 1e-300, 3e-16
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 400):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """The regularized incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x)
        + b * math.log1p(-x)
    )  # fmt: skip
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def t_two_sided_p(t: float, df: int) -> float:
    """P(|T| >= |t|) for Student's t with `df` degrees of freedom."""
    if math.isinf(t):
        return 0.0
    return betainc(df / 2.0, 0.5, df / (df + t * t))


def t_critical(confidence: float, df: int) -> float:
    """The t such that P(|T| <= t) = confidence (by bisection on the exact p-value)."""
    alpha = 1.0 - confidence
    low, high = 0.0, 1.0
    while t_two_sided_p(high, df) > alpha:
        high *= 2.0
    for _ in range(200):
        mid = (low + high) / 2.0
        if t_two_sided_p(mid, df) > alpha:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


@dataclass(frozen=True)
class Paired:
    n: int
    mean: float | None
    sd: float | None
    ci_low: float | None
    ci_high: float | None
    t: float | None
    p_value: float | None


def paired(differences: list[float], confidence: float) -> Paired:
    """Mean of paired differences, its confidence interval and the t-test against zero."""
    n = len(differences)
    if n == 0:
        return Paired(0, None, None, None, None, None, None)
    mean = fmean(differences)
    if n < 2:
        return Paired(n, mean, None, None, None, None, None)
    sd = stdev(differences)
    if sd == 0.0:
        # The same difference on every seed: no spread to test against. A zero difference
        # is no evidence of an effect; any other is as consistent as data can be.
        p = 1.0 if mean == 0.0 else 0.0
        t = 0.0 if mean == 0.0 else math.copysign(math.inf, mean)
        return Paired(n, mean, 0.0, mean, mean, t, p)
    se = sd / math.sqrt(n)
    t = mean / se
    half = t_critical(confidence, n - 1) * se
    return Paired(n, mean, sd, mean - half, mean + half, t, t_two_sided_p(t, n - 1))


def holm(p_values: dict[str, float]) -> dict[str, float]:
    """Holm's step-down adjustment of several p-values (controls the family-wise error)."""
    ordered = sorted(p_values.items(), key=lambda kv: kv[1])
    m = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for i, (key, p) in enumerate(ordered):
        running = max(running, min(1.0, (m - i) * p))
        adjusted[key] = running
    return adjusted


def _r(value: float | None, digits: int = 6) -> float | None:
    """Rounded for storage; infinities (a t statistic when every seed differs by the same
    amount) and NaN become None, since JSON (and PostgreSQL's jsonb) cannot hold them."""
    if value is None or math.isinf(value) or math.isnan(value):
        return None
    return round(value, digits)


def series_statistics(replicates: list[dict[str, Any]], confidence: float) -> dict[str, Any]:
    """Statistics across a series' replicates. Each replicate: `seed`, `verdict` and the
    evaluation's `comparisons` (one row per metric, with baseline and candidate values)."""
    alpha = 1.0 - confidence
    by_metric: dict[str, dict[str, Any]] = {}
    for replicate in replicates:
        for row in replicate["comparisons"]:
            entry = by_metric.setdefault(
                row["metric"],
                {key: row[key] for key in ("metric", "label", "unit", "better")} | {"per_seed": []},
            )
            entry["per_seed"].append(
                {
                    "seed": replicate["seed"],
                    "baseline": row["baseline"],
                    "candidate": row["candidate"],
                    "delta": row["delta"],
                }
            )
    metrics = []
    tested: dict[str, float] = {}
    for key, entry in by_metric.items():
        seeds = [s for s in entry["per_seed"] if s["delta"] is not None]
        result = paired([s["delta"] for s in seeds], confidence)
        base_mean = fmean([s["baseline"] for s in seeds]) if seeds else None
        relative = result.mean / abs(base_mean) if result.mean is not None and base_mean else None

        def rel(v, base_mean=base_mean):
            return None if v is None or not base_mean else v / abs(base_mean)

        metrics.append(
            entry
            | {
                "n": result.n,
                "baseline_mean": _r(base_mean),
                "candidate_mean": _r(fmean([s["candidate"] for s in seeds]) if seeds else None),
                "mean_delta": _r(result.mean),
                "sd_delta": _r(result.sd),
                "ci_low": _r(result.ci_low),
                "ci_high": _r(result.ci_high),
                "relative_change": _r(relative),
                "relative_ci_low": _r(rel(result.ci_low)),
                "relative_ci_high": _r(rel(result.ci_high)),
                "t": _r(result.t, 4),
                "p_value": _r(result.p_value, 8),
            }
        )
        if entry["better"] != "none" and result.p_value is not None:
            tested[key] = result.p_value
    adjusted = holm(tested)
    for row in metrics:
        p_adj = adjusted.get(row["metric"])
        row["p_adjusted"] = _r(p_adj, 8)
        row["significant"] = p_adj is not None and p_adj < alpha
        if row["better"] == "none":
            row["finding"] = "informational"
        elif row["n"] < 2:
            row["finding"] = "too_few_seeds"
        elif not row["significant"]:
            row["finding"] = "no_significant_difference"
        else:
            direction = 1 if row["better"] == "higher" else -1
            row["finding"] = "improved" if row["mean_delta"] * direction > 0 else "worse"

    successful = sum(r["verdict"] == "successful" for r in replicates)
    worse = [r["metric"] for r in metrics if r["finding"] == "worse"]
    verdict = (
        "successful"
        if replicates and successful == len(replicates) and not worse
        else "not_successful"
    )
    stats = {
        "method": "paired t-test on per-seed differences (candidate minus baseline); "
        f"{confidence:.0%} confidence interval per metric (not adjusted); a difference is "
        f"significant when its Holm-adjusted p-value, across the {len(tested)} tested "
        f"metrics, is below {1 - confidence:.2f}. An interval that excludes zero can "
        "therefore still be not significant.",
        "confidence": confidence,
        "replicates": len(replicates),
        "seeds": [r["seed"] for r in replicates],
        "replicate_verdicts": {
            "successful": successful,
            "not_successful": len(replicates) - successful,
        },  # fmt: skip
        "metrics": metrics,
        "significantly_worse": worse,
        "verdict": verdict,
    }
    stats["conclusion"] = conclusion(stats)
    return stats


def _describe(row: dict[str, Any]) -> str:
    label = SHORT_NAMES.get(row["metric"]) or row["label"].split(" (")[0].lower()
    if row["relative_change"] is None:
        return f"{label}: no comparable data"
    change = row["relative_change"]
    text = f"{label} {'down' if change < 0 else 'up'} {abs(change):.1%}"
    if row["relative_ci_low"] is not None:
        text += f" ({row['relative_ci_low']:+.1%} to {row['relative_ci_high']:+.1%})"
    p = row["p_adjusted"]
    if p is not None:
        text += ", p < 0.001" if p < 0.001 else f", p = {p:.3f}"
    return text + ("" if row["significant"] else ", not significant")


def conclusion(stats: dict[str, Any]) -> str:
    rows = {r["metric"]: r for r in stats["metrics"]}
    parts = [_describe(rows[k]) for k in HEADLINE if k in rows]
    counts = stats["replicate_verdicts"]
    tested = sum(r["better"] != "none" and r["n"] >= 2 for r in stats["metrics"])
    text = (
        f"Over {stats['replicates']} seeds ({stats['confidence']:.0%} interval per metric; "
        f"significance after adjusting for {tested} metrics tested together): "
        + "; ".join(parts)
        + ". "
        f"{counts['successful']} of {stats['replicates']} replicates met every success "
        "criterion."
    )
    if stats["significantly_worse"]:
        worse = ", ".join(
            SHORT_NAMES.get(k) or rows[k]["label"].lower() for k in stats["significantly_worse"]
        )
        text += f" Significantly worse: {worse}."
    return text


# --- Portfolios (Phase 78) ---------------------------------------------------------------------


def _pooled(values: list[float], confidence: float) -> dict[str, Any]:
    result = paired(values, confidence)
    return {
        "cells": result.n,
        "mean_relative_change": _r(result.mean),
        "ci_low": _r(result.ci_low),
        "ci_high": _r(result.ci_high),
        "median_relative_change": _r(sorted(values)[len(values) // 2] if values else None),
        "p_value": _r(result.p_value, 8),
    }


def portfolio_statistics(cells: list[dict[str, Any]], confidence: float) -> dict[str, Any]:
    """Statistics across a portfolio's cells. Each cell: `scenario_id`, `workflow_id`,
    `department`, `country`, `tool_id`, `verdict` and its series' `metrics`.

    The unit is the workflow: the cells of one workflow (its countries) share the tool,
    the rules and the seeds, so they are not independent evidence; each workflow
    contributes the mean relative change of its cells, so a workflow counts once whatever
    its size or number of countries. Across workflows the pooled mean has a t-interval and
    a one-sample t-test against zero (Holm-adjusted across metrics). Per cell, the series'
    own finding (better, worse, no significant difference) is counted; breakdowns give the
    mean change by department and by country, and how many workflows' effect the country
    changed at all."""
    alpha = 1.0 - confidence
    specs: dict[str, dict[str, Any]] = {}
    for cell in cells:
        for m in cell["metrics"]:
            if m["better"] != "none":
                specs.setdefault(m["metric"], {k: m[k] for k in ("metric", "label", "better")})
    metrics, tested = [], {}
    for key, spec in specs.items():
        rows = [
            (cell, m)
            for cell in cells
            for m in cell["metrics"]
            if m["metric"] == key and m["relative_change"] is not None
        ]
        per_workflow: dict[str, list[float]] = {}
        for cell, m in rows:
            per_workflow.setdefault(cell["workflow_id"], []).append(m["relative_change"])
        values = [fmean(v) for v in per_workflow.values()]
        country_dependent = sum(
            1 for v in per_workflow.values() if len(v) > 1 and max(v) - min(v) > 1e-9
        )
        findings = {"improved": 0, "worse": 0, "no_significant_difference": 0}
        for _, m in rows:
            if m["finding"] in findings:
                findings[m["finding"]] += 1

        def group(field: str, rows=rows) -> list[dict[str, Any]]:
            groups: dict[str, list[float]] = {}
            for cell, m in rows:
                groups.setdefault(cell[field] or "—", []).append(m["relative_change"])
            return [
                {field: name, "cells": len(v), "mean_relative_change": _r(fmean(v))}
                for name, v in sorted(groups.items())
            ]

        pooled = _pooled(values, confidence)
        pooled["workflows"] = pooled.pop("cells")
        row = (
            spec
            | pooled
            | {
                "cells": len(rows),
                "country_dependent_workflows": country_dependent,
                "cell_findings": findings,
                "by_department": group("department"),
                "by_country": group("country"),
            }
        )
        metrics.append(row)
        if row["p_value"] is not None:
            tested[key] = row["p_value"]
    adjusted = holm(tested)
    for row in metrics:
        p_adj = adjusted.get(row["metric"])
        row["p_adjusted"] = _r(p_adj, 8)
        row["significant"] = p_adj is not None and p_adj < alpha
        if row["workflows"] < 2:
            row["finding"] = "too_few_cells"
        elif not row["significant"]:
            row["finding"] = "no_significant_difference"
        else:
            direction = 1 if row["better"] == "higher" else -1
            row["finding"] = "improved" if row["mean_relative_change"] * direction > 0 else "worse"
    successful = sum(c["verdict"] == "successful" for c in cells)
    worse_cells = sorted(
        {
            f"{c['scenario_id']} ({c['country'] or 'all countries'})"
            for c in cells
            for m in c["metrics"]
            if m["finding"] == "worse"
        }
    )
    stats = {
        "method": "the workflow is the unit: each workflow's mean relative change over its "
        "cells (one per country), each cell the mean of its repeated-seed series; across "
        f"workflows a t-interval and a one-sample t-test against zero, {confidence:.0%} "
        f"confidence, Holm-adjusted across the {len(tested)} tested metrics",
        "confidence": confidence,
        "cells": len(cells),
        "workflows": len({c["workflow_id"] for c in cells}),
        "departments": sorted({c["department"] or "—" for c in cells}),
        "countries": sorted({c["country"] or "—" for c in cells}),
        "tools": sorted({c["tool_id"] for c in cells}),
        "cell_verdicts": {"successful": successful, "not_successful": len(cells) - successful},
        "cells_with_a_worse_metric": worse_cells,
        "metrics": metrics,
        "cell_summaries": [
            {
                k: c[k]
                for k in (
                    "scenario_id",
                    "workflow_id",
                    "department",
                    "country",
                    "tool_id",
                    "series_number",
                    "verdict",
                )
            }  # fmt: skip
            | {
                "headline": {
                    m["metric"]: m["relative_change"]
                    for m in c["metrics"]
                    if m["metric"] in HEADLINE
                }
            }
            for c in cells
        ],
        "verdict": "successful" if cells and successful == len(cells) else "not_successful",
    }
    rows = {r["metric"]: r for r in metrics}
    parts = []
    for key in HEADLINE:
        if key in rows and rows[key]["mean_relative_change"] is not None:
            r = rows[key]
            text = f"{SHORT_NAMES[key]} {r['mean_relative_change']:+.1%}"
            if r["ci_low"] is not None:
                text += f" ({r['ci_low']:+.1%} to {r['ci_high']:+.1%})"
            f = r["cell_findings"]
            text += f", better in {f['improved']} of {r['cells']} cells, worse in {f['worse']}"
            parts.append(text)
    labour = rows.get("labour_hours")
    country_note = (
        f"The country changed the labour effect in {labour['country_dependent_workflows']} "
        f"of {labour['workflows']} workflows. "
        if labour and len(stats["countries"]) > 1
        else ""
    )
    stats["conclusion"] = (
        f"Across {stats['workflows']} workflows ({len(cells)} cells; "
        f"{len(stats['departments'])} departments, {len(stats['countries'])} countries), "
        "mean change per workflow: "
        + "; ".join(parts)
        + ". "
        + country_note
        + f"{successful} of {len(cells)} cells met every success criterion on every seed."
        + (f" A metric was worse in: {', '.join(worse_cells)}." if worse_cells else "")
    )
    return stats
