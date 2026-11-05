"""Calibrated reviewer behaviour (Phase 82, roadmap Milestone G, step 7).

Until now the simulated reviewers' review times, accuracy and response to AI advice were
stated assumptions in each scenario. A calibration estimates them from observed reviews of
one review step — each observation: how long the review took, what the right decision was,
what the reviewer decided, and the AI recommendation shown, if any — with an interval for
every parameter:

- review time: a lognormal fitted by maximum likelihood (the mean with Cox's interval, the
  spread with a chi-square interval);
- accuracy on cases that should be approved and on those that should be rejected, each a
  proportion with a Wilson interval (pooled when one side has too few cases);
- from reviews with a recommendation shown: how much faster they were (the ratio of mean
  times, delta-method interval) and how often the reviewer was right when the AI was
  right and when it was wrong.

New runs use the scenario's active calibrations and store the parameters they used, so a
run stays reproducible. A series may also **draw** each seed's parameters from their
sampling distributions (deterministically from the seed, the same for a seed's baseline
and candidate), so its intervals carry the calibration's uncertainty and not only the
workload's.
"""

import hashlib
import json
import math
import random
from statistics import NormalDist, fmean, stdev
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.simulation.models import ReviewerCalibration
from app.simulation.scenarios import AIAssistanceModel, ReviewerModel, Scenario

MIN_REVIEWS = 30  # unassisted reviews needed to fit a step
MIN_PER_SIDE = 10  # should-approve / should-reject cases needed to fit each accuracy
MIN_ASSISTED = 30  # reviews with a recommendation needed to fit the AI's effect
MIN_AI_WRONG = 5  # of them, with a wrong recommendation, to fit automation bias
MAX_OBSERVATIONS = 20_000
MAX_SIGMA = 2.0  # ReviewerModel.sigma's bound
TIME_FACTOR_RANGE = (0.05, 10.0)  # within AIAssistanceModel.review_time_factor's bound
CONFIDENCE = 0.95
_Z = NormalDist().inv_cdf(0.5 + CONFIDENCE / 2)


def digest(observations: list[dict[str, Any]]) -> str:
    canonical = json.dumps(observations, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _r(value: float | None, digits: int = 6) -> float | None:
    return None if value is None or not math.isfinite(value) else round(value, digits)


def wilson(successes: int, n: int) -> dict[str, Any]:
    """A proportion with its Wilson score interval."""
    if n == 0:
        return {"estimate": None, "low": None, "high": None, "n": 0, "successes": 0}
    p = successes / n
    centre = (p + _Z**2 / (2 * n)) / (1 + _Z**2 / n)
    half = _Z * math.sqrt(p * (1 - p) / n + _Z**2 / (4 * n * n)) / (1 + _Z**2 / n)
    return {"estimate": _r(p), "low": _r(max(0.0, centre - half)),
            "high": _r(min(1.0, centre + half)), "n": n, "successes": successes}  # fmt: skip


def _chi2_quantile(p: float, k: int) -> float:
    """Wilson–Hilferty approximation of the chi-square quantile (good for k ≥ 10)."""
    z = NormalDist().inv_cdf(p)
    return k * (1 - 2 / (9 * k) + z * math.sqrt(2 / (9 * k))) ** 3


def lognormal(minutes: list[float]) -> dict[str, Any]:
    """Maximum-likelihood lognormal: the mean (Cox's interval) and the spread sigma."""
    logs = [math.log(m) for m in minutes]
    n = len(logs)
    m, s = fmean(logs), stdev(logs)
    log_mean = m + s * s / 2
    se = math.sqrt(s * s / n + s**4 / (2 * (n - 1)))
    sigma_low = s * math.sqrt((n - 1) / _chi2_quantile(0.5 + CONFIDENCE / 2, n - 1))
    sigma_high = s * math.sqrt((n - 1) / _chi2_quantile(0.5 - CONFIDENCE / 2, n - 1))
    return {
        "n": n,
        "mean_minutes": {"estimate": _r(math.exp(log_mean)),
                         "low": _r(math.exp(log_mean - _Z * se)),
                         "high": _r(math.exp(log_mean + _Z * se))},
        "sigma": {"estimate": _r(s), "low": _r(sigma_low), "high": _r(sigma_high)},
        "_log_mean": log_mean, "_log_mean_se": se, "_s": s,
    }  # fmt: skip


def _correct(o: dict[str, Any]) -> bool:
    return o["decision"] == o["truth"]


def fit(observations: list[dict[str, Any]], *, ai_capable: bool) -> dict[str, Any]:
    """Every parameter the observations support, with intervals, and what they cannot."""
    plain = [o for o in observations if o.get("ai_recommendation") is None]
    assisted = [o for o in observations if o.get("ai_recommendation") is not None]
    if len(plain) < MIN_REVIEWS:
        raise ValueError(
            f"At least {MIN_REVIEWS} reviews without an AI recommendation are needed to fit "
            f"the reviewers; {len(plain)} given."
        )
    notes: list[str] = []
    times = lognormal([o["minutes"] for o in plain])
    if times["_s"] > MAX_SIGMA:
        # Never silently simulate something other than what was fitted.
        raise ValueError(
            f"The review times spread more widely (sigma {times['_s']:.2f}) than the "
            f"simulation supports ({MAX_SIGMA}): check the minutes, or split the step."
        )
    approve = [o for o in plain if o["truth"] == "approve"]
    reject = [o for o in plain if o["truth"] == "reject"]
    if len(approve) >= MIN_PER_SIDE and len(reject) >= MIN_PER_SIDE:
        acc = wilson(sum(map(_correct, approve)), len(approve))
        acc_reject = wilson(sum(map(_correct, reject)), len(reject))
    else:
        acc = wilson(sum(map(_correct, plain)), len(plain))
        acc_reject = None
        notes.append(
            f"Fewer than {MIN_PER_SIDE} reviews of cases that should be "
            f"{'approved' if len(approve) < MIN_PER_SIDE else 'rejected'}: one accuracy for both."
        )
    reviewer = {
        "mean_minutes": times["mean_minutes"],
        "sigma": times["sigma"],
        "accuracy": acc,
        "accuracy_should_reject": acc_reject,
    }
    out: dict[str, Any] = {
        "confidence": CONFIDENCE,
        "observations": len(observations),
        "unassisted": len(plain),
        "assisted": len(assisted),
        "reviewer": reviewer,
        "ai_assistance": None,
        "notes": notes,
        "_draw": {
            "log_mean": times["_log_mean"],
            "log_mean_se": times["_log_mean_se"],
            "s": times["_s"],
            "n": times["n"],
        },  # fmt: skip
    }
    if not ai_capable:
        if assisted:
            notes.append(
                "The scenario has no AI modes: the reviews with a recommendation are unused."
            )
        return out
    if len(assisted) < MIN_ASSISTED:
        notes.append(
            f"{len(assisted)} reviews with an AI recommendation (at least {MIN_ASSISTED} "
            "needed): the AI's effect stays the scenario's assumption."
        )
        return out
    with_ai = lognormal([o["minutes"] for o in assisted])
    log_ratio = with_ai["_log_mean"] - times["_log_mean"]
    se = math.hypot(with_ai["_log_mean_se"], times["_log_mean_se"])
    right = [o for o in assisted if o["ai_recommendation"] == o["truth"]]
    wrong = [o for o in assisted if o["ai_recommendation"] != o["truth"]]
    low_bound, high_bound = TIME_FACTOR_RANGE
    if not low_bound <= math.exp(log_ratio) <= high_bound:
        raise ValueError(
            f"Reviews with AI advice took {math.exp(log_ratio):.2f} times as long as those "
            f"without, outside what the simulation supports ({low_bound}–{high_bound})."
        )
    ai = {
        "review_time_factor": {"estimate": _r(math.exp(log_ratio)),
                               "low": _r(math.exp(log_ratio - _Z * se)),
                               "high": _r(math.exp(log_ratio + _Z * se))},
        "accuracy_when_ai_correct": wilson(sum(map(_correct, right)), len(right))
        if len(right) >= MIN_AI_WRONG else None,
        "accuracy_when_ai_wrong": wilson(sum(map(_correct, wrong)), len(wrong))
        if len(wrong) >= MIN_AI_WRONG else None,
    }  # fmt: skip
    if ai["accuracy_when_ai_correct"] is None:
        notes.append(
            f"{len(right)} reviews with a right recommendation (at least {MIN_AI_WRONG} "
            "needed): accuracy with right advice stays the scenario's assumption."
        )
    if ai["accuracy_when_ai_wrong"] is None:
        notes.append(
            f"{len(wrong)} reviews with a wrong recommendation (at least {MIN_AI_WRONG} needed): "
            "automation bias stays the scenario's assumption."
        )
    out["ai_assistance"] = ai
    out["_draw"]["log_ratio"] = log_ratio
    out["_draw"]["log_ratio_se"] = se
    # The assisted mean on its own, so a draw derives the ratio from the drawn unassisted
    # mean instead of counting its uncertainty twice.
    out["_draw"]["log_mean_ai"] = with_ai["_log_mean"]
    out["_draw"]["log_mean_ai_se"] = with_ai["_log_mean_se"]
    return out


def public(fitted: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in fitted.items() if not k.startswith("_")}


# --- Applying a calibration to a run ------------------------------------------------------------


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def _beta(rng: random.Random, p: dict[str, Any]) -> float:
    """A draw from the proportion's Jeffreys posterior, Beta(k + ½, n − k + ½)."""
    k, n = p["successes"], p["n"]
    return rng.betavariate(k + 0.5, n - k + 0.5)


def parameters(fitted: dict[str, Any], rng: random.Random | None) -> dict[str, Any]:
    """The point estimates, or with `rng` one draw from their sampling distributions."""
    r, d = fitted["reviewer"], fitted["_draw"]
    if rng is None:
        reviewer = {
            "mean_minutes": r["mean_minutes"]["estimate"],
            "sigma": r["sigma"]["estimate"],
            "accuracy": r["accuracy"]["estimate"],
            "accuracy_should_reject": r["accuracy_should_reject"]["estimate"]
            if r["accuracy_should_reject"] else None,
        }  # fmt: skip
    else:
        # sigma² ~ s²(n−1)/χ²(n−1), then the log-mean given sigma: the lognormal's
        # sampling distribution, drawn so that the two stay consistent.
        chi2 = 2 * rng.gammavariate((d["n"] - 1) / 2, 1)
        sigma = d["s"] * math.sqrt((d["n"] - 1) / chi2)
        log_mean = rng.gauss(d["log_mean"], d["log_mean_se"])
        reviewer = {
            "mean_minutes": math.exp(log_mean),
            "sigma": sigma,
            "accuracy": _beta(rng, r["accuracy"]),
            "accuracy_should_reject": _beta(rng, r["accuracy_should_reject"])
            if r["accuracy_should_reject"] else None,
        }  # fmt: skip
    reviewer["sigma"] = _clamp(reviewer["sigma"], 0.0, 2.0)
    reviewer = {k: _r(v) for k, v in reviewer.items()}
    out: dict[str, Any] = {"reviewer": reviewer, "ai_assistance": None}
    ai = fitted.get("ai_assistance")
    if ai:
        # Unfitted proportions stay None (the scenario's assumption), drawn or not.
        right_fit, wrong_fit = ai["accuracy_when_ai_correct"], ai["accuracy_when_ai_wrong"]
        if rng is None:
            factor = ai["review_time_factor"]["estimate"]
            right = right_fit["estimate"] if right_fit else None
            wrong = wrong_fit["estimate"] if wrong_fit else None
        else:
            if "log_mean_ai" in d:
                # The assisted mean drawn on its own, over the unassisted mean drawn above.
                factor = math.exp(rng.gauss(d["log_mean_ai"], d["log_mean_ai_se"]) - log_mean)
            else:  # calibrations recorded before the joint draw
                factor = math.exp(rng.gauss(d["log_ratio"], d["log_ratio_se"]))
            right = _beta(rng, right_fit) if right_fit else None
            wrong = _beta(rng, wrong_fit) if wrong_fit else None
        out["ai_assistance"] = {"review_time_factor": _r(_clamp(factor, *TIME_FACTOR_RANGE)),
                                "accuracy_when_ai_correct": _r(right),
                                "accuracy_when_ai_wrong": _r(wrong)}  # fmt: skip
    return out


def active(db: Session, scenario_id: str) -> list[ReviewerCalibration]:
    return list(
        db.execute(
            select(ReviewerCalibration)
            .where(ReviewerCalibration.scenario_id == scenario_id,
                   ReviewerCalibration.status == "active")
            .order_by(ReviewerCalibration.step_id)
        ).scalars()
    )  # fmt: skip


def for_run(
    db: Session,
    scenario: Scenario,
    *,
    seed: int,
    calibrated: bool = True,
    draw: bool = False,
    ids: list[str] | None = None,
) -> dict[str, Any] | None:
    """What a run of the scenario simulates: its active calibrations (or exactly `ids`,
    for a reproduction), as point estimates or one draw per seed. None: the scenario's
    stated assumptions apply."""
    if ids:
        records = [db.get(ReviewerCalibration, i) for i in ids]
        if any(r is None for r in records):
            raise ValueError("A calibration the run used no longer exists.")
        foreign = [r.calibration_number for r in records if r.scenario_id != scenario.scenario_id]
        if foreign:
            raise ValueError(
                f"Calibration(s) {', '.join(map(str, foreign))} belong to another scenario, "
                f"not {scenario.scenario_id}."
            )
    elif calibrated:
        records = active(db, scenario.scenario_id)
    else:
        return None
    records = [r for r in records if r is not None and r.step_id in scenario.config.reviewers]
    if not records:
        return None
    config = scenario.config.model_copy(deep=True)
    used: dict[str, Any] = {}
    ai_from = None
    for record in sorted(records, key=lambda r: r.calibration_number):
        rng = None
        if draw:
            key = f"{record.data_digest}:{seed}".encode()
            rng = random.Random(int.from_bytes(hashlib.sha256(key).digest()[:8], "big"))
        p = parameters(record.fitted, rng)
        config.reviewers[record.step_id] = ReviewerModel(**{
            k: v for k, v in p["reviewer"].items() if v is not None})  # fmt: skip
        used[record.step_id] = p["reviewer"]
        if p["ai_assistance"] and config.ai_assistance is not None:
            current = config.ai_assistance.model_dump()
            current.update({k: v for k, v in p["ai_assistance"].items() if v is not None})
            config.ai_assistance = AIAssistanceModel(**current)
            ai_from = record.step_id
    return {
        "ids": [str(r.id) for r in sorted(records, key=lambda r: r.calibration_number)],
        "numbers": sorted(r.calibration_number for r in records),
        "draw": draw,
        "reviewers": used,
        "ai_assistance": config.ai_assistance.model_dump() if ai_from else None,
        "ai_assistance_from": ai_from,
        "scenario": config.model_dump(mode="json", exclude_none=True),
    }


# --- A synthetic pilot study (for demonstrations and tests) -----------------------------------


def pilot(
    *,
    n: int,
    seed: int,
    mean_minutes: float,
    sigma: float,
    accuracy: float,
    accuracy_should_reject: float,
    share_should_reject: float = 0.3,
    assisted_share: float = 0.5,
    ai_accuracy: float = 0.9,
    review_time_factor: float = 0.6,
    accuracy_when_ai_correct: float = 0.98,
    accuracy_when_ai_wrong: float = 0.6,
) -> list[dict[str, Any]]:
    """Observed reviews drawn from known parameters: SYNTHETIC, labelled as such wherever
    they are used. Fitting them shows whether the calibration recovers the truth."""
    rng = random.Random(seed)
    mu = math.log(mean_minutes) - sigma * sigma / 2
    observations = []
    for _ in range(n):
        truth = "reject" if rng.random() < share_should_reject else "approve"
        wrong = "approve" if truth == "reject" else "reject"
        recommendation, factor = None, 1.0
        p_right = accuracy_should_reject if truth == "reject" else accuracy
        if rng.random() < assisted_share:
            recommendation = truth if rng.random() < ai_accuracy else wrong
            factor = review_time_factor
            p_right = (
                accuracy_when_ai_correct if recommendation == truth else accuracy_when_ai_wrong
            )
        minutes = rng.lognormvariate(mu, sigma) * factor
        observations.append({
            "minutes": round(minutes, 3), "truth": truth,
            "decision": truth if rng.random() < p_right else wrong,
            "ai_recommendation": recommendation,
        })  # fmt: skip
    return observations


# --- Recording a calibration ------------------------------------------------------------------


def calibrate(
    db: Session,
    *,
    scenario: Scenario,
    step_id: str,
    source: str,
    observations: list[dict[str, Any]],
    actor_id,
) -> ReviewerCalibration:
    """Fit the step's reviewers from the observations; the result becomes the step's active
    calibration (the previous one is superseded, kept with its observations)."""
    from app.core.audit import record_audit_event

    if step_id not in scenario.config.reviewers:
        raise ValueError(
            f"{scenario.scenario_id} has no review step '{step_id}'; its steps are "
            f"{', '.join(sorted(scenario.config.reviewers))}."
        )
    fitted = fit(observations, ai_capable=scenario.config.ai_assistance is not None)
    previous = db.execute(
        select(ReviewerCalibration)
        .where(ReviewerCalibration.scenario_id == scenario.scenario_id,
               ReviewerCalibration.step_id == step_id,
               ReviewerCalibration.status == "active")
        .with_for_update()
    ).scalar_one_or_none()  # fmt: skip
    if previous is not None:
        previous.status = "superseded"
        db.flush()  # the partial unique index allows one active calibration a step
    record = ReviewerCalibration(
        scenario_id=scenario.scenario_id,
        step_id=step_id,
        source=source.strip(),
        observations=observations,
        observation_count=len(observations),
        data_digest=digest(observations),
        fitted=fitted,
        status="active",
        created_by=actor_id,
    )
    db.add(record)
    db.flush()
    db.refresh(record)
    record_audit_event(
        db,
        actor_id=actor_id,
        action="reviewer_calibration.created",
        entity_type="reviewer_calibration",
        entity_id=record.id,
        metadata={"scenario_id": scenario.scenario_id, "step_id": step_id,
                  "observations": len(observations), "data_digest": record.data_digest,
                  "superseded": str(previous.id) if previous else None},
    )  # fmt: skip
    return record


def assumption(scenario: Scenario, step_id: str) -> dict[str, Any]:
    """What the scenario states, for comparison with the fitted values."""
    model = scenario.config.reviewers[step_id]
    ai = scenario.config.ai_assistance
    return {
        "reviewer": model.model_dump(),
        "ai_assistance": ai.model_dump() if ai is not None else None,
    }
