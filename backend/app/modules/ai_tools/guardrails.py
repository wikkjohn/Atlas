"""Guardrails for AI tools (Phase 79, roadmap Milestone G step 4).

Three checks on what tools have been recorded doing, with nothing assumed about the tool:

- **Audit.** Every invocation is written with a SHA-256 of its whole record (input,
  output, error, usage, the exact prompt and response of a hosted model, identity and
  time). `verify_audit` recomputes them and lists any record that no longer matches.
- **Drift.** A reference window of a tool's invocations against a current one (two
  simulation runs, or before and after a time): the Population Stability Index (PSI) and
  a chi-square test of its recommendations, the shift in its confidence (Welch's t), its
  error rate (two-proportion z) and the PSI of what it was given (segment attributes).
  PSI below 0.1 is stable, below 0.25 a moderate shift, above it significant.
- **Bias across segments.** A tool's recommendations split by the segment attributes
  found in its inputs (country, nationality, age band, employment status, ...). Where the
  simulation's ground truth is known, the primary test is equal opportunity: among cases
  that should be approved, is the false rejection rate the same in every group? Otherwise,
  are the recommendations independent of the group? Chi-square tests, Holm-adjusted across
  attributes; the four-fifths rule on approval rates is reported alongside.

The data are synthetic and the groups are those the generators produce; a difference can
reflect the case mix rather than the tool, which is why the ground-truth test leads.
"""

import math
import uuid
from collections import Counter
from datetime import UTC, date, datetime
from statistics import fmean, variance
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation
from app.modules.ai_tools.models import AITool, AIToolInvocation, InvocationStatus
from app.modules.experiments.significance import holm, t_two_sided_p

MIN_GROUP = 20  # cases in a group before it is compared
PSI_MODERATE, PSI_SIGNIFICANT = 0.1, 0.25
FOUR_FIFTHS = 0.8
EO_GAP = 0.1  # a false-rejection gap this large between groups is material
ALPHA = 0.05

# Input fields read as segment attributes, wherever they appear in a tool's input.
SEGMENT_FIELDS = {
    "country_code": "country",
    "home_country": "country",
    "residence_country": "country",
    "nationality": "nationality",
    "employment_status": "employment status",
    "account_type": "account type",
    "segment": "segment",
    "customer_segment": "segment",
}
AGE_BANDS = ((25, "under 25"), (40, "25–39"), (55, "40–54"), (70, "55–69"))


# --- Distributions -----------------------------------------------------------------------------


def _gammainc_upper(a: float, x: float) -> float:
    """The regularized upper incomplete gamma function Q(a, x)."""
    if x <= 0:
        return 1.0
    if x < a + 1:  # series for P, then Q = 1 - P
        term = total = 1.0 / a
        n = a
        for _ in range(500):
            n += 1
            term *= x / n
            total += term
            if abs(term) < abs(total) * 1e-15:
                break
        return 1.0 - total * math.exp(-x + a * math.log(x) - math.lgamma(a))
    tiny = 1e-300  # continued fraction (modified Lentz)
    b = x + 1 - a
    c, d = 1 / tiny, 1 / b
    h = d
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = 1 / (d if abs(d) > tiny else tiny)
        c = b + an / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-15:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def chi2_sf(statistic: float, df: int) -> float:
    """P(X ≥ statistic) for a chi-square distribution with `df` degrees of freedom."""
    return _gammainc_upper(df / 2, statistic / 2)


def chi2_independence(table: list[list[int]]) -> tuple[float, int, float] | None:
    """Pearson's chi-square test on a contingency table (rows × columns of counts). None
    when it has fewer than two non-empty rows or columns."""
    rows = [r for r in table if sum(r) > 0]
    columns = [j for j in range(len(rows[0]) if rows else 0) if sum(r[j] for r in rows) > 0]
    if len(rows) < 2 or len(columns) < 2:
        return None
    total = sum(sum(r) for r in rows)
    statistic = 0.0
    for r in rows:
        for j in columns:
            expected = sum(r) * sum(x[j] for x in rows) / total
            statistic += (r[j] - expected) ** 2 / expected
    df = (len(rows) - 1) * (len(columns) - 1)
    return statistic, df, chi2_sf(statistic, df)


def psi(reference: Counter, current: Counter) -> float | None:
    """Population Stability Index between two categorical distributions."""
    n_ref, n_cur = sum(reference.values()), sum(current.values())
    if not n_ref or not n_cur:
        return None
    eps = 1e-4
    total = 0.0
    for key in set(reference) | set(current):
        r = max(reference[key] / n_ref, eps)
        c = max(current[key] / n_cur, eps)
        total += (c - r) * math.log(c / r)
    return round(total, 6)


def psi_status(value: float | None, p_value: float | None = None) -> str:
    """Stable, moderate or significant by the PSI; a shift that a chi-square test cannot
    tell from sampling noise (small windows) counts as stable."""
    if value is None:
        return "no_data"
    if value < PSI_MODERATE or (p_value is not None and p_value >= ALPHA):
        return "stable"
    return "moderate" if value < PSI_SIGNIFICANT else "significant"


def _compare(reference: Counter, current: Counter) -> dict[str, Any]:
    keys = sorted(set(reference) | set(current))
    test = chi2_independence([[reference[k] for k in keys], [current[k] for k in keys]])
    value = psi(reference, current)
    p_value = _r(test[2], 8) if test else None
    return {"psi": value, "p_value": p_value, "status": psi_status(value, p_value)}


def welch(a: list[float], b: list[float]) -> float | None:
    """Two-sided p-value of Welch's t-test for a difference in means."""
    if len(a) < 2 or len(b) < 2:
        return None
    va, vb = variance(a) / len(a), variance(b) / len(b)
    if va + vb == 0:
        return 1.0 if fmean(a) == fmean(b) else 0.0
    t = (fmean(b) - fmean(a)) / math.sqrt(va + vb)
    df = (va + vb) ** 2 / (va**2 / (len(a) - 1) + vb**2 / (len(b) - 1))
    return t_two_sided_p(t, df)


def two_proportions(x1: int, n1: int, x2: int, n2: int) -> float | None:
    """Two-sided p-value of the z-test that two proportions are equal."""
    if not n1 or not n2:
        return None
    pooled = (x1 + x2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    return math.erfc(abs(x2 / n2 - x1 / n1) / se / math.sqrt(2))


def _r(v: float | None, digits: int = 6) -> float | None:
    return None if v is None or math.isinf(v) or math.isnan(v) else round(v, digits)


# --- Segments ----------------------------------------------------------------------------------


def _age_band(born: str, on: date) -> str | None:
    try:
        birth = date.fromisoformat(born[:10])
    except ValueError:
        return None
    age = on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))
    return next((label for limit, label in AGE_BANDS if age < limit), "70 and over")


def segments(payload: dict[str, Any], on: date) -> dict[str, str]:
    """The segment attributes in a tool's input: the first value of each known field,
    and an age band from a date of birth."""
    found: dict[str, str] = {}
    as_of = payload.get("as_of")
    if isinstance(as_of, str):
        try:
            on = date.fromisoformat(as_of[:10])
        except ValueError:
            pass

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in SEGMENT_FIELDS and isinstance(value, str) and value:
                    found.setdefault(SEGMENT_FIELDS[key], value)
                elif key == "date_of_birth" and isinstance(value, str):
                    band = _age_band(value, on)
                    if band:
                        found.setdefault("age band", band)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return found


# --- Selection ---------------------------------------------------------------------------------


def _tool(db: Session, tool_record_id: uuid.UUID) -> AITool:
    tool = db.get(AITool, tool_record_id)
    if tool is None:
        from app.core.errors import NotFoundError

        raise NotFoundError("AI tool not found.")
    return tool


def _invocations(
    db: Session,
    tool: AITool,
    *,
    run_id: uuid.UUID | None = None,
    after: datetime | None = None,
    before: datetime | None = None,
) -> list[AIToolInvocation]:
    query = select(AIToolInvocation).where(
        AIToolInvocation.tool_record_id == tool.id,
        AIToolInvocation.status != InvocationStatus.BLOCKED,
    )
    if run_id is not None:
        query = query.where(AIToolInvocation.simulation_run_id == run_id)
    if after is not None:
        query = query.where(AIToolInvocation.occurred_at >= after)
    if before is not None:
        query = query.where(AIToolInvocation.occurred_at < before)
    return list(db.execute(query.order_by(AIToolInvocation.occurred_at)).scalars())


def _truth(db: Session, calls: list[AIToolInvocation]) -> dict[uuid.UUID, str]:
    """The ground truth of each simulated call's case: approved or rejected."""
    from app.simulation.models import SimulationCaseResult

    executions = {c.execution_id for c in calls if c.execution_id and c.simulation_run_id}
    truth: dict[uuid.UUID, str] = {}
    for chunk in [list(executions)[i : i + 5000] for i in range(0, len(executions), 5000)]:
        for execution_id, expected in db.execute(
            select(SimulationCaseResult.execution_id, SimulationCaseResult.expected_outcome).where(
                SimulationCaseResult.execution_id.in_(chunk)
            )
        ).all():
            truth[execution_id] = expected
    return truth


def _recommendation(call: AIToolInvocation) -> str | None:
    if call.status != InvocationStatus.SUCCEEDED or not call.output:
        return None
    value = call.output.get("recommendation")
    return value if isinstance(value, str) else None


# --- Bias --------------------------------------------------------------------------------------


def bias(
    db: Session, tool_record_id: uuid.UUID, *, run_id: uuid.UUID | None = None,
    min_group: int = MIN_GROUP,
) -> dict[str, Any]:  # fmt: skip
    """A tool's recommendations across the segment attributes of its inputs."""
    tool = _tool(db, tool_record_id)
    calls = [c for c in _invocations(db, tool, run_id=run_id) if _recommendation(c)]
    truth = _truth(db, calls)
    by_attribute: dict[str, dict[str, list[AIToolInvocation]]] = {}
    for call in calls:
        for attribute, value in segments(call.input, call.occurred_at.date()).items():
            by_attribute.setdefault(attribute, {}).setdefault(value, []).append(call)
    attributes, primary = [], {}
    for attribute, groups in sorted(by_attribute.items()):
        kept = {v: g for v, g in groups.items() if len(g) >= min_group}
        rows = []
        for value, group in sorted(kept.items()):
            recs = Counter(_recommendation(c) for c in group)
            should_approve = [c for c in group if truth.get(c.execution_id) == "approved"]
            should_reject = [c for c in group if truth.get(c.execution_id) == "rejected"]
            false_rej = sum(_recommendation(c) == "reject" for c in should_approve)
            false_app = sum(_recommendation(c) == "approve" for c in should_reject)
            rows.append(
                {
                    "group": value,
                    "n": len(group),
                    "approve_rate": _r(recs["approve"] / len(group)),
                    "reject_rate": _r(recs["reject"] / len(group)),
                    "escalate_rate": _r(recs["escalate"] / len(group)),
                    "should_approve": len(should_approve),
                    "false_rejections": false_rej,
                    "false_rejection_rate": _r(false_rej / len(should_approve))
                    if should_approve
                    else None,
                    "should_reject": len(should_reject),
                    "false_approval_rate": _r(false_app / len(should_reject))
                    if should_reject
                    else None,
                    "_recs": recs,
                }
            )
        parity = chi2_independence(
            [[r["_recs"][k] for k in ("approve", "reject", "escalate")] for r in rows]
        )
        with_truth = [r for r in rows if r["should_approve"] >= min_group // 2]
        opportunity = chi2_independence(
            [[r["false_rejections"], r["should_approve"] - r["false_rejections"]]
             for r in with_truth]
        ) if len(with_truth) >= 2 else None  # fmt: skip
        approve = [r["approve_rate"] for r in rows if r["approve_rate"] is not None]
        fr = [r["false_rejection_rate"] for r in with_truth]
        entry = {
            "attribute": attribute,
            "groups": [{k: v for k, v in r.items() if k != "_recs"} for r in rows],
            "excluded_groups": sorted(v for v in groups if v not in kept),
            "approval_ratio": _r(min(approve) / max(approve)) if approve and max(approve) else None,
            "false_rejection_gap": _r(max(fr) - min(fr)) if len(fr) >= 2 else None,
            "test": "equal_opportunity" if opportunity else "demographic_parity",
            "p_value": _r((opportunity or parity)[2], 8) if (opportunity or parity) else None,
        }
        attributes.append(entry)
        if entry["p_value"] is not None:
            primary[attribute] = entry["p_value"]
    adjusted = holm(primary)
    flagged = []
    for entry in attributes:
        p_adj = adjusted.get(entry["attribute"])
        entry["p_adjusted"] = _r(p_adj, 8)
        material = (entry["false_rejection_gap"] or 0) > EO_GAP or (
            entry["test"] == "demographic_parity"
            and entry["approval_ratio"] is not None
            and entry["approval_ratio"] < FOUR_FIFTHS
        )
        if p_adj is None:
            entry["finding"] = "insufficient_data"
        elif p_adj < ALPHA and material:
            entry["finding"] = "disparity"
            flagged.append(entry["attribute"])
        else:
            entry["finding"] = "no_disparity"
        entry["four_fifths_rule"] = (
            None if entry["approval_ratio"] is None else entry["approval_ratio"] >= FOUR_FIFTHS
        )
    return {
        "tool_id": tool.tool_id,
        "tool_version": tool.tool_version,
        "run_id": str(run_id) if run_id else None,
        "recommendations": len(calls),
        "with_ground_truth": sum(1 for c in calls if c.execution_id in truth),
        "min_group": min_group,
        "attributes": attributes,
        "flagged": flagged,
        "status": "flagged" if flagged else ("clear" if primary else "insufficient_data"),
        "method": "segment attributes from the inputs; per group the recommendation rates "
        "and, with ground truth, false rejection and approval rates; chi-square tests "
        "(equal opportunity among should-approve cases where ground truth allows, else "
        f"independence of recommendation and group), Holm-adjusted; a disparity needs "
        f"p < {ALPHA} and a false-rejection gap over {EO_GAP:.0%} (or, without ground truth, "
        f"approval rates below the four-fifths rule); groups under {min_group} cases are "
        "left out",
    }


# --- Drift -------------------------------------------------------------------------------------


def _window(calls: list[AIToolInvocation]) -> dict[str, Any]:
    recs = Counter(_recommendation(c) or "none" for c in calls if c.status == "succeeded")
    confidences = [
        float(c.output["confidence"])
        for c in calls
        if c.status == "succeeded" and isinstance((c.output or {}).get("confidence"), int | float)
    ]
    attributes: dict[str, Counter] = {}
    for c in calls:
        for attribute, value in segments(c.input, c.occurred_at.date()).items():
            attributes.setdefault(attribute, Counter())[value] += 1
    return {
        "calls": len(calls),
        "errors": sum(c.status != "succeeded" for c in calls),
        "recommendations": recs,
        "confidences": confidences,
        "attributes": attributes,
    }


def drift(
    db: Session,
    tool_record_id: uuid.UUID,
    *,
    reference_run_id: uuid.UUID | None = None,
    current_run_id: uuid.UUID | None = None,
    split_at: datetime | None = None,
) -> dict[str, Any]:
    """A tool's behaviour in a current window against a reference: two runs, or the
    invocations before and after `split_at`."""
    tool = _tool(db, tool_record_id)
    if reference_run_id and current_run_id:
        ref_calls = _invocations(db, tool, run_id=reference_run_id)
        cur_calls = _invocations(db, tool, run_id=current_run_id)
        windows = {"reference_run_id": str(reference_run_id),
                   "current_run_id": str(current_run_id)}  # fmt: skip
    elif split_at is not None:
        split_at = split_at if split_at.tzinfo else split_at.replace(tzinfo=UTC)
        ref_calls = _invocations(db, tool, before=split_at)
        cur_calls = _invocations(db, tool, after=split_at)
        windows = {"split_at": split_at.isoformat()}
    else:
        raise BusinessRuleViolation("Give two runs, or a time to split the calls at.")
    ref, cur = _window(ref_calls), _window(cur_calls)
    keys = sorted(set(ref["recommendations"]) | set(cur["recommendations"]))
    recommendations = _compare(ref["recommendations"], cur["recommendations"])

    def share(w: dict, k: str) -> float | None:
        n = sum(w["recommendations"].values())
        return _r(w["recommendations"][k] / n) if n else None

    inputs = []
    for attribute in sorted(set(ref["attributes"]) | set(cur["attributes"])):
        reference = ref["attributes"].get(attribute, Counter())
        current = cur["attributes"].get(attribute, Counter())
        inputs.append({"attribute": attribute} | _compare(reference, current))
    conf_p = welch(ref["confidences"], cur["confidences"])
    err_p = two_proportions(ref["errors"], ref["calls"], cur["errors"], cur["calls"])
    statuses = [recommendations["status"]] + [i["status"] for i in inputs]
    order = ["significant", "moderate", "stable", "no_data"]
    overall = next((s for s in order if s in statuses), "no_data")
    if overall == "stable" and ((conf_p is not None and conf_p < ALPHA)
                                or (err_p is not None and err_p < ALPHA)):  # fmt: skip
        overall = "moderate"
    return {
        "tool_id": tool.tool_id,
        "tool_version": tool.tool_version,
        "windows": windows,
        "reference": {"calls": ref["calls"], "errors": ref["errors"]},
        "current": {"calls": cur["calls"], "errors": cur["errors"]},
        "recommendations": {
            "shares": {k: {"reference": share(ref, k), "current": share(cur, k)} for k in keys},
            **recommendations,
        },
        "confidence": {
            "reference_mean": _r(fmean(ref["confidences"])) if ref["confidences"] else None,
            "current_mean": _r(fmean(cur["confidences"])) if cur["confidences"] else None,
            "p_value": _r(conf_p, 8),
        },
        "error_rate": {
            "reference": _r(ref["errors"] / ref["calls"]) if ref["calls"] else None,
            "current": _r(cur["errors"] / cur["calls"]) if cur["calls"] else None,
            "p_value": _r(err_p, 8),
        },
        "inputs": inputs,
        "status": overall,
        "method": f"Population Stability Index (stable < {PSI_MODERATE}, moderate < "
        f"{PSI_SIGNIFICANT}, significant above) of the recommendations and of the inputs' "
        "segment attributes, each with a chi-square test: a shift it cannot tell from "
        f"sampling noise (p ≥ {ALPHA}) counts as stable; Welch's t-test of the confidence; "
        "two-proportion z-test of the error rate",
    }


# --- Audit -------------------------------------------------------------------------------------


def verify_audit(
    db: Session, *, tool_record_id: uuid.UUID | None = None, limit: int = 100_000
) -> dict[str, Any]:
    """Recompute each invocation's record hash; list those that no longer match."""
    from app.modules.ai_tools.service import record_hash

    query = select(AIToolInvocation).order_by(AIToolInvocation.created_at)
    if tool_record_id is not None:
        query = query.where(AIToolInvocation.tool_record_id == tool_record_id)
    checked = valid = unhashed = 0
    mismatched: list[str] = []
    for call in db.execute(query.limit(limit)).scalars():
        checked += 1
        if call.record_hash is None:
            unhashed += 1
        elif call.record_hash == record_hash(call):
            valid += 1
        else:
            mismatched.append(str(call.id))
    return {
        "checked": checked,
        "valid": valid,
        "unhashed": unhashed,
        "mismatched": len(mismatched),
        "mismatched_ids": mismatched[:100],
        "status": "intact" if not mismatched else "altered",
    }
