"""Exportable proof-of-concept report (Markdown) built from an evaluated experiment."""

from typing import Any

from app.modules.experiments.assumptions import CostAssumptions
from app.modules.experiments.evaluation import COST_LINES
from app.modules.experiments.schemas import ExperimentDetail

UNITS = {"hours": " h", "currency": "", "count": "", "ratio": ""}


def _fmt(value: Any, unit: str) -> str:
    if value is None:
        return "—"
    if unit == "ratio":
        return f"{value:.2%}"
    if unit == "currency":
        return f"{value:,.2f}"
    if unit == "hours":
        return f"{value:,.2f} h"
    return f"{value:,}"


def _change(row: dict[str, Any]) -> str:
    rel = row["relative_change"]
    if rel is None:
        return "—"
    flag = " ⚠ regression" if row["regression"] else (" ✓" if row["improved"] else "")
    return f"{rel:+.1%}{flag}"


def markdown(e: ExperimentDetail) -> str:
    if e.evaluation is None:
        raise ValueError("Only evaluated experiments have a report.")
    ev = e.evaluation
    base = next(m.metrics for m in e.measurements if m.role == "baseline")
    cand = next(m.metrics for m in e.measurements if m.role == "candidate")
    workload = cand["workload"]
    costs = e.configuration["costs"]
    thresholds = e.configuration["thresholds"]
    verdict = "SUCCESSFUL" if ev.verdict == "successful" else "NOT SUCCESSFUL"
    lines = [
        f"# Proof-of-concept report — Experiment #{e.experiment_number}: {e.name}",
        "",
        "> **Synthetic simulation.** All data is synthetic and every cost is an estimate "
        "from the assumptions below. Nothing in this report is a verified saving.",
        "",
        f"**Verdict: {verdict}**",
        "",
        "## Tested tool",
        "",
        f"- Tool: `{e.tool_id}` version `{e.tool_version}`",
        f"- Configuration tested: {e.candidate_mode.replace('_', ' ')} "
        f"(run #{e.candidate.run_number}) against the baseline (run #{e.baseline.run_number})",
        "",
        "## Test scenario and workload",
        "",
        f"- Scenario: `{workload['scenario_id']}` v{workload['scenario_version']}, workflow "
        f"`{workload['workflow_id']}` v{workload['workflow_version']}",
        f"- Workload: {workload['applications']:,} synthetic cases, "
        f"{workload['employees']:,} simulated staff, countries "
        f"{', '.join(workload['dataset']['countries'])}",
        f"- Data seed: `{workload['seed']}`",
        f"- Software version: `{workload['software_version']}`; evaluation "
        f"`{ev.evaluation_version}`; configuration hash `{e.configuration_hash[:16]}`",
        f"- Run result digests: baseline `{(base['result_digest'] or '')[:16]}`, candidate "
        f"`{(cand['result_digest'] or '')[:16]}`; evaluation digest "
        f"`{ev.evaluation_digest[:16]}`",
        "",
        "## Baseline and AI performance",
        "",
        "| Metric | Baseline | Candidate | Change |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in ev.comparisons:
        lines.append(
            f"| {row['label']} | {_fmt(row['baseline'], row['unit'])} | "
            f"{_fmt(row['candidate'], row['unit'])} | {_change(row)} |"
        )
    lines += [
        "",
        "## Operational differences",
        "",
        f"- Manual reviews: {base['manual_reviews']:,} → {cand['manual_reviews']:,}; "
        f"decisions made by the policy engine: {cand['automated_approvals']:,}",
        f"- Escalations to compliance review: {base['escalations']:,} → {cand['escalations']:,}",
        f"- AI tool calls: {cand['ai']['invocations']:,} "
        f"({', '.join(f'{k} {v}' for k, v in sorted(cand['ai']['by_status'].items())) or 'none'})",
        f"- Workflow exceptions (timeouts, overdue tasks, failures, AI errors): "
        f"{base['exceptions']:,} → {cand['exceptions']:,}",
        "",
        "## Financial assumptions",
        "",
        "| Assumption | Value |",
        "| --- | ---: |",
    ]
    for key in CostAssumptions.model_fields:
        if key != "notes":
            lines.append(f"| {key.replace('_', ' ')} | {costs[key]} |")
    lines += ["", "| Cost line | Baseline | Candidate |", "| --- | ---: | ---: |"]
    for key, label in COST_LINES.items():
        lines.append(
            f"| {label} | {ev.costs['baseline']['lines'][key]:,.2f} | "
            f"{ev.costs['candidate']['lines'][key]:,.2f} |"
        )
    lines += [
        f"| **Operating total** | **{ev.costs['baseline']['operating_total']:,.2f}** | "
        f"**{ev.costs['candidate']['operating_total']:,.2f}** |",
        f"| Risk exposure of wrong decisions (not in operating cost) | "
        f"{ev.costs['baseline']['risk_exposure_total']:,.2f} | "
        f"{ev.costs['candidate']['risk_exposure_total']:,.2f} |",
    ]
    if costs.get("notes"):
        lines += ["", f"Notes: {costs['notes']}"]
    lines += [
        "",
        "## Security and compliance results",
        "",
        f"- Banking decisions checked against authorization rules: "
        f"{cand['decisions_checked']:,}; policy violations: baseline "
        f"{base['policy_violations']}, candidate {cand['policy_violations']}",
        f"- Unauthorized tool actions blocked: {cand['ai']['blocked']:,}",
        f"- Thresholds: false approvals ≤ {thresholds['max_false_approval_rate']:.1%}, false "
        f"rejections ≤ {thresholds['max_false_rejection_rate']:.1%}, errors ≤ "
        f"{thresholds['max_error_rate']:.1%} of cases, policy violations ≤ "
        f"{thresholds['max_policy_violations']}",
        "",
        "## Success criteria",
        "",
    ]
    for c in ev.criteria:
        lines.append(f"- {'✅' if c['passed'] else '❌'} **{c['label']}** — {c['detail']}")
    lines += ["", "## Known limitations", ""]
    lines += [f"- {item}" for item in ev.limitations]
    lines += ["", "## Recommendation", "", ev.conclusion, ""]
    return "\n".join(lines)
