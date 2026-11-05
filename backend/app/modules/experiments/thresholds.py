"""Scenario-specific success thresholds (Phase 80, roadmap Milestone G, step 5).

One set of thresholds for every scenario judges a fraud screen and a leave request alike:
a 5 % false-approval rate is a loss and a regulatory breach in one and a day off in the
other. Each scenario therefore has a **risk tier** with built-in defaults, and may have
stored, versioned thresholds that one person proposes and a risk approver (someone else)
approves. Experiments resolve their thresholds from the scenario unless a request gives
them explicitly, and record where they came from.

The tier values are illustrative for synthetic data, not any real bank's risk appetite.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.modules.experiments.assumptions import EvaluationConfig, SuccessThresholds
from app.modules.experiments.evaluation import evaluate
from app.modules.experiments.models import (
    Experiment,
    ExperimentMeasurement,
    ExperimentStatus,
    ScenarioThresholdVersion,
)
from app.modules.identity.models import User
from app.simulation.scenarios import SCENARIOS

RiskTier = Literal["critical", "high", "medium", "low"]

TIERS: dict[str, SuccessThresholds] = {
    # A wrong approval is a financial-crime, fraud or sanctions failure.
    "critical": SuccessThresholds(
        max_accuracy_drop=0.0,
        max_false_approval_rate=0.01,
        max_false_rejection_rate=0.10,
        max_error_rate=0.02,
    ),
    # A wrong approval is a credit, market, conduct or reporting loss.
    "high": SuccessThresholds(
        max_accuracy_drop=0.005,
        max_false_approval_rate=0.03,
        max_false_rejection_rate=0.08,
        max_error_rate=0.03,
    ),
    # Operational and customer decisions that are costly but correctable: the defaults.
    "medium": SuccessThresholds(),
    # Internal, reversible decisions.
    "low": SuccessThresholds(
        max_accuracy_drop=0.02,
        max_false_approval_rate=0.10,
        max_false_rejection_rate=0.10,
        max_error_rate=0.05,
    ),
}

TIER_DESCRIPTIONS = {
    "critical": "Financial crime, fraud or sanctions: a wrong approval is a loss and a breach.",
    "high": "Credit, market, conduct or financial-reporting risk.",
    "medium": "Operational or customer decisions that are costly but correctable.",
    "low": "Internal, reversible decisions.",
}

# The tier of each scenario with AI modes, and why.
SCENARIO_TIERS: dict[str, tuple[str, str]] = {
    "retail-onboarding": ("critical", "Know-your-customer: an approval opens an account to a "
                          "customer who may fail identity or sanctions checks."),
    "domestic-payments": ("critical", "Fraud screening: a wrong release sends money that "
                          "cannot be recalled."),
    "card-fraud-alerts": ("critical", "A wrong release lets card fraud continue."),
    "alert-triage": ("critical", "Anti-money-laundering: closing a true alert can mean an "
                     "unfiled suspicious activity report."),
    "personal-loans": ("high", "Credit risk: a wrong approval lends to a borrower who "
                       "cannot repay."),
    "mortgage-applications": ("high", "Credit risk on large, long-dated loans."),
    "covenant-breaches": ("high", "A wrong waiver leaves a deteriorating commercial borrower "
                          "unchallenged."),
    "rating-overrides": ("high", "A wrong override misstates credit risk and provisions."),
    "journal-review": ("high", "A wrong posting misstates the books and regulatory reports."),
    "order-review": ("high", "Suitability: an unsuitable order is a conduct breach."),
    "discrepant-presentations": ("high", "Paying a discrepant presentation can lose the "
                                 "bank's recourse under the letter of credit."),
    "retail-overdrafts": ("medium", "Small, monitored credit lines."),
    "payment-plans": ("medium", "Collections arrangements that can be revisited."),
    "complaint-redress": ("medium", "Redress is costly but correctable."),
    "deal-confirmations": ("medium", "Back-office confirmations are reconciled afterwards."),
    "recall-triage": ("medium", "Recalls are operational and traceable."),
    "invoice-payments": ("medium", "Supplier payments pass further controls before release."),
    "change-approvals": ("medium", "IT changes are tested and can be rolled back."),
    "leave-requests": ("low", "A day off granted in error is easily corrected."),
}  # fmt: skip

DEFAULT_TIER = "medium"


def _scenario_exists(scenario_id: str) -> bool:
    return any(sid == scenario_id for sid, _ in SCENARIOS)


def tier_of(scenario_id: str) -> tuple[str, str]:
    """The scenario's tier; a variant (e.g. `domestic-payments-outage`) has its base's."""
    if scenario_id in SCENARIO_TIERS:
        return SCENARIO_TIERS[scenario_id]
    bases = [b for b in SCENARIO_TIERS if scenario_id.startswith(f"{b}-")]
    if bases:
        tier, why = SCENARIO_TIERS[max(bases, key=len)]
        return tier, f"As {max(bases, key=len)}: {why}"
    return DEFAULT_TIER, "No tier assigned: the bank's default thresholds."


def active(db: Session, scenario_id: str, *, lock: bool = False) -> ScenarioThresholdVersion | None:
    query = select(ScenarioThresholdVersion).where(
        ScenarioThresholdVersion.scenario_id == scenario_id,
        ScenarioThresholdVersion.status == "active",
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return db.execute(query).scalar_one_or_none()


def resolve(db: Session, scenario_id: str) -> tuple[SuccessThresholds, dict[str, Any]]:
    """The thresholds a new experiment on the scenario is judged by, and their source."""
    stored = active(db, scenario_id)
    if stored is not None:
        return SuccessThresholds.model_validate(stored.thresholds), {
            "source": "scenario",
            "scenario_id": scenario_id,
            "risk_tier": stored.risk_tier,
            "version": stored.version,
            "record_id": str(stored.id),
        }
    tier, _ = tier_of(scenario_id)
    return TIERS[tier].model_copy(), {
        "source": "tier_default",
        "scenario_id": scenario_id,
        "risk_tier": tier,
        "version": 0,
        "record_id": None,
    }


def thresholds_for(
    db: Session, scenario_id: str, given: SuccessThresholds | None
) -> tuple[SuccessThresholds, dict[str, Any]]:
    """Given thresholds win (the request chose them); otherwise the scenario's."""
    if given is not None:
        return given, {"source": "request", "scenario_id": scenario_id}
    return resolve(db, scenario_id)


# --- Proposals and decisions -------------------------------------------------------------------


def get(db: Session, record_id: uuid.UUID, *, lock: bool = False) -> ScenarioThresholdVersion:
    """One version; `lock` takes a row lock and re-reads it, so two people deciding on the
    same proposal at once are serialised and the second sees the first's decision."""
    query = select(ScenarioThresholdVersion).where(ScenarioThresholdVersion.id == record_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    record = db.execute(query).scalar_one_or_none()
    if record is None:
        raise NotFoundError("Threshold version not found.")
    return record


def propose(
    db: Session,
    *,
    scenario_id: str,
    risk_tier: str,
    thresholds: SuccessThresholds | None,
    rationale: str,
    actor_id: uuid.UUID,
) -> ScenarioThresholdVersion:
    if not _scenario_exists(scenario_id):
        raise NotFoundError(f"Scenario '{scenario_id}' not found.")
    pending = db.execute(
        select(ScenarioThresholdVersion.version).where(
            ScenarioThresholdVersion.scenario_id == scenario_id,
            ScenarioThresholdVersion.status == "proposed",
        )
    ).scalar_one_or_none()
    if pending is not None:
        raise ConflictError(
            f"Version {pending} of {scenario_id}'s thresholds is already awaiting a decision."
        )
    latest = db.execute(
        select(func.max(ScenarioThresholdVersion.version)).where(
            ScenarioThresholdVersion.scenario_id == scenario_id
        )
    ).scalar_one()
    values = thresholds if thresholds is not None else TIERS[risk_tier]
    record = ScenarioThresholdVersion(
        scenario_id=scenario_id,
        version=(latest or 0) + 1,
        risk_tier=risk_tier,
        thresholds=values.model_dump(mode="json"),
        rationale=rationale.strip(),
        status="proposed",
        proposed_by=actor_id,
    )
    db.add(record)
    db.flush()
    record_audit_event(
        db,
        actor_id=actor_id,
        action="scenario_thresholds.proposed",
        entity_type="scenario_thresholds",
        entity_id=record.id,
        metadata={
            "scenario_id": scenario_id,
            "version": record.version,
            "risk_tier": risk_tier,
            "thresholds": record.thresholds,
        },  # fmt: skip
    )
    return record


def _decide(
    db: Session, record: ScenarioThresholdVersion, actor_id: uuid.UUID, status: str, note: str
) -> ScenarioThresholdVersion:
    if record.status != "proposed":
        raise ConflictError(
            f"Version {record.version} is {record.status}, not awaiting a decision."
        )
    if record.proposed_by == actor_id:
        raise BusinessRuleViolation(
            "Thresholds need a second person: the proposer cannot decide on them."
        )
    if status == "active":
        previous = active(db, record.scenario_id, lock=True)
        if previous is not None:
            previous.status = "superseded"
            db.flush()  # the partial unique index allows one active version
    record.status = status
    record.decided_by = actor_id
    record.decided_at = datetime.now(UTC)
    record.decision_note = note.strip() or None
    db.flush()
    record_audit_event(
        db,
        actor_id=actor_id,
        action="scenario_thresholds.approved" if status == "active" else
        "scenario_thresholds.rejected",
        entity_type="scenario_thresholds",
        entity_id=record.id,
        metadata={"scenario_id": record.scenario_id, "version": record.version,
                  "note": record.decision_note},
    )  # fmt: skip
    return record


def approve(db: Session, record_id: uuid.UUID, actor_id: uuid.UUID, note: str = ""):
    return _decide(db, get(db, record_id, lock=True), actor_id, "active", note)


def reject(db: Session, record_id: uuid.UUID, actor_id: uuid.UUID, note: str):
    if len(note.strip()) < 5:
        raise BusinessRuleViolation("Say why the thresholds are rejected.")
    return _decide(db, get(db, record_id, lock=True), actor_id, "rejected", note)


# --- Reading -----------------------------------------------------------------------------------


def _username(db: Session, user_id: uuid.UUID | None) -> str | None:
    user = db.get(User, user_id) if user_id else None
    return user.username if user else None


def version_out(db: Session, r: ScenarioThresholdVersion) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "scenario_id": r.scenario_id,
        "version": r.version,
        "risk_tier": r.risk_tier,
        "thresholds": r.thresholds,
        "rationale": r.rationale,
        "status": r.status,
        "proposed_by_username": _username(db, r.proposed_by),
        "proposed_at": r.proposed_at.isoformat(),
        "decided_by_username": _username(db, r.decided_by),
        "decided_at": r.decided_at.isoformat() if r.decided_at else None,
        "decision_note": r.decision_note,
    }


def ai_scenarios() -> dict[str, Any]:
    latest: dict[str, Any] = {}
    for (scenario_id, version), scenario in SCENARIOS.items():
        if scenario.config.ai_assistance is None:
            continue
        if scenario_id not in latest or version > latest[scenario_id].version:
            latest[scenario_id] = scenario
    return dict(sorted(latest.items()))


def overview(db: Session) -> list[dict[str, Any]]:
    """Every scenario with AI modes: the thresholds in force, their source, a pending
    proposal if any."""
    pending = {
        r.scenario_id: r
        for r in db.execute(
            select(ScenarioThresholdVersion).where(ScenarioThresholdVersion.status == "proposed")
        ).scalars()
    }
    rows = []
    for scenario_id, scenario in ai_scenarios().items():
        values, source = resolve(db, scenario_id)
        tier, why = tier_of(scenario_id)
        stored = active(db, scenario_id)
        rows.append(
            {
                "scenario_id": scenario_id,
                "name": scenario.name,
                "workflow_id": scenario.workflow_id,
                "risk_tier": source["risk_tier"],
                "default_tier": tier,
                "default_rationale": why,
                "source": source["source"],
                "version": source["version"],
                "thresholds": values.model_dump(mode="json"),
                "rationale": stored.rationale if stored else why,
                "pending": version_out(db, pending[scenario_id])
                if scenario_id in pending
                else None,
            }
        )
    return rows


def history(db: Session, scenario_id: str) -> list[dict[str, Any]]:
    if not _scenario_exists(scenario_id):
        raise NotFoundError(f"Scenario '{scenario_id}' not found.")
    rows = db.execute(
        select(ScenarioThresholdVersion)
        .where(ScenarioThresholdVersion.scenario_id == scenario_id)
        .order_by(ScenarioThresholdVersion.version.desc())
    ).scalars()
    return [version_out(db, r) for r in rows]


# --- What the stored experiments say under the scenarios' thresholds ---------------------------


def reassess(db: Session, experiment: Experiment) -> dict[str, Any] | None:
    """The experiment's evaluation recomputed from its raw measurements under its scenario's
    thresholds in force now; nothing is stored. None until it has been evaluated."""
    if experiment.status != ExperimentStatus.COMPLETED:
        return None
    query = select(ExperimentMeasurement).where(
        ExperimentMeasurement.experiment_id == experiment.id
    )
    rows = {m.role: m.metrics for m in db.execute(query).scalars()}
    values, source = resolve(db, experiment.scenario_id)
    stored = EvaluationConfig.model_validate(experiment.configuration)
    stored_eval = evaluate(rows["baseline"], rows["candidate"], stored)
    now = evaluate(
        rows["baseline"],
        rows["candidate"],
        EvaluationConfig(costs=stored.costs, thresholds=values),
    )
    return {
        "experiment_id": str(experiment.id),
        "scenario_id": experiment.scenario_id,
        "thresholds_source": source,
        "thresholds": values.model_dump(mode="json"),
        "stored_thresholds": stored.thresholds.model_dump(mode="json"),
        "stored_verdict": stored_eval["verdict"],
        "verdict": now["verdict"],
        "changed": stored_eval["verdict"] != now["verdict"],
        "criteria": now["criteria"],
        "comparisons": now["comparisons"],
        "failed_criteria": [c["criterion"] for c in now["criteria"] if not c["passed"]],
    }


def reassess_portfolio(db: Session, portfolio) -> dict[str, Any] | None:
    """A completed portfolio's cells re-judged under each scenario's thresholds in force
    now: every replicate re-evaluated from its raw measurements, then the series and
    portfolio statistics recomputed. Nothing is stored."""
    from app.modules.experiments import portfolios as portfolio_service
    from app.modules.experiments import series as series_service
    from app.modules.experiments.significance import portfolio_statistics, series_statistics

    if portfolio.status != ExperimentStatus.COMPLETED:
        return None
    cells, rows, thresholds = [], [], {}
    for member in portfolio_service.cells(db, portfolio):
        replicates, failed = [], set()
        for experiment in series_service.replicates(db, member):
            result = reassess(db, experiment)
            assert result is not None
            failed.update(result["failed_criteria"])
            thresholds[member.scenario_id] = {
                "risk_tier": result["thresholds_source"]["risk_tier"],
                "source": result["thresholds_source"]["source"],
                "version": result["thresholds_source"]["version"],
                **result["thresholds"],
            }
            replicates.append(
                {
                    "seed": series_service._seed(db, experiment),
                    "experiment_number": experiment.experiment_number,
                    "verdict": result["verdict"],
                    "comparisons": result["comparisons"],
                }
            )
        stats = series_statistics(replicates, member.confidence)
        scenario = SCENARIOS[(member.scenario_id, member.scenario_version)]
        cells.append(
            {
                "scenario_id": member.scenario_id,
                "country": member.country,
                "risk_tier": thresholds[member.scenario_id]["risk_tier"],
                "stored_verdict": member.verdict,
                "verdict": stats["verdict"],
                "replicates_successful": stats["replicate_verdicts"]["successful"],
                "replicates": stats["replicates"],
                "failed_criteria": sorted(failed),
            }
        )
        rows.append(
            {
                "scenario_id": member.scenario_id,
                "workflow_id": scenario.workflow_id,
                "department": portfolio_service.department(db, scenario.workflow_id),
                "country": member.country,
                "tool_id": member.tool_id,
                "series_number": member.series_number,
                "verdict": stats["verdict"],
                "metrics": stats["metrics"],
            }
        )
    stats = portfolio_statistics(rows, portfolio.confidence)
    by_tier: dict[str, dict[str, int]] = {}
    for cell in cells:
        tier = by_tier.setdefault(cell["risk_tier"], {"cells": 0, "successful": 0, "before": 0})
        tier["cells"] += 1
        tier["successful"] += cell["verdict"] == "successful"
        tier["before"] += cell["stored_verdict"] == "successful"
    return {
        "portfolio_id": str(portfolio.id),
        "stored_cell_verdicts": (portfolio.statistics or {}).get("cell_verdicts"),
        "stored_verdict": portfolio.verdict,
        "cell_verdicts": stats["cell_verdicts"],
        "verdict": stats["verdict"],
        "by_tier": dict(sorted(by_tier.items(), key=lambda kv: list(TIERS).index(kv[0]))),
        "thresholds": thresholds,
        "cells": cells,
        "method": "Each replicate re-evaluated from its stored raw measurements under its "
        "scenario's thresholds in force now (approved version or risk-tier default); series "
        "and portfolio statistics recomputed. Nothing is stored.",
    }
