"""Raw measurements of a simulation run, read from what the run recorded.

Sources: the run's configuration, its per-case results, its workflow executions and
history, the AI tool invocations it made, and the account requests its cases decided.
Nothing here uses cost assumptions; wall-clock time is kept apart from everything that
must reproduce.
"""

import hashlib
import json
import math
import uuid
from typing import Any

from sqlalchemy import Text, cast, func, select
from sqlalchemy.orm import Session

from app.core.permissions import Permission, permissions_for
from app.modules.accounts.models import AccountRequest
from app.modules.ai_tools.models import AIToolInvocation
from app.modules.customers.models import Customer, RiskRating
from app.modules.identity.models import Role, User
from app.modules.workflows.models import WorkflowEvent, WorkflowExecution
from app.simulation.models import SimulationCaseResult, SimulationRun

AI_ERROR_STATUSES = ("failed", "timeout", "invalid_input", "invalid_output")


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def workload(run: SimulationRun) -> dict[str, Any]:
    """What must be identical for two runs to be compared."""
    config = run.config
    return {
        "scenario_id": run.scenario_id,
        "scenario_version": run.scenario_version,
        "workflow_id": run.workflow_id,
        "workflow_version": run.workflow_version,
        "seed": run.seed,
        "applications": config["applications"],
        "employees": config["employees"],
        "dataset": config["dataset"],
        "scenario_config": config["scenario"],
        "software_version": run.software_version,
    }


def _policy_violations(db: Session, run_id: uuid.UUID) -> tuple[int, list[dict[str, Any]]]:
    """Check every account decision the run's cases made against the authorization rules."""
    request_id = WorkflowExecution.context["open_account"]["account_request_id"].astext
    rows = db.execute(
        select(AccountRequest, Customer.risk_rating, User.role_id, User.username)
        .join(WorkflowExecution, request_id == cast(AccountRequest.id, Text))
        .join(Customer, Customer.id == AccountRequest.customer_id)
        .join(User, User.id == AccountRequest.decided_by)
        .where(WorkflowExecution.simulation_run_id == run_id)
    ).all()
    roles = dict(db.execute(select(Role.id, Role.code)).all())
    violations: list[dict[str, Any]] = []
    for request, risk, role_id, username in rows:
        permissions = permissions_for(roles.get(role_id, ""))
        found = []
        if request.decided_by == request.requested_by:
            found.append("four_eyes")
        full = Permission.ACCOUNTS_APPROVE in permissions
        if not full and Permission.ACCOUNTS_APPROVE_LOW_RISK not in permissions:
            found.append("decider_without_authority")
        if not full and risk != RiskRating.LOW:
            found.append("limited_approver_beyond_low_risk")
        if risk == RiskRating.HIGH and Permission.CUSTOMERS_REVIEW not in permissions:
            found.append("high_risk_without_compliance")
        for rule in found:
            violations.append(
                {"rule": rule, "account_request_id": str(request.id), "decided_by": username}
            )
    return len(rows), violations


def measure(db: Session, run: SimulationRun) -> dict[str, Any]:
    cases = list(
        db.execute(
            select(SimulationCaseResult)
            .where(SimulationCaseResult.run_id == run.id)
            .order_by(SimulationCaseResult.case_index)
        ).scalars()
    )
    should_reject = [c for c in cases if c.expected_outcome == "rejected"]
    should_approve = [c for c in cases if c.expected_outcome == "approved"]
    cycles = [c.cycle_seconds for c in cases if c.cycle_seconds is not None]
    completed = [c for c in cases if c.status == "completed"]

    execution_ids = select(WorkflowExecution.id).where(
        WorkflowExecution.simulation_run_id == run.id
    )
    failed_executions = db.execute(
        select(func.count()).where(
            WorkflowExecution.simulation_run_id == run.id, WorkflowExecution.status == "failed"
        )
    ).scalar_one()
    document_timeouts = db.execute(
        select(func.count()).where(
            WorkflowEvent.execution_id.in_(execution_ids),
            WorkflowEvent.event_type == "step.timed_out",
        )
    ).scalar_one()
    statuses = dict(
        db.execute(
            select(AIToolInvocation.status, func.count())
            .where(AIToolInvocation.simulation_run_id == run.id)
            .group_by(AIToolInvocation.status)
        ).all()
    )
    ai_errors = sum(statuses.get(s, 0) for s in AI_ERROR_STATUSES)
    recommendations: dict[str, int] = {}
    for c in cases:
        if c.ai_recommendation:
            recommendations[c.ai_recommendation] = recommendations.get(c.ai_recommendation, 0) + 1
    decisions, violations = _policy_violations(db, run.id)
    overdue = sum(c.overdue_tasks for c in cases)
    fingerprint = [(c.case_index, c.kind, c.expected_outcome) for c in cases]

    return {
        "run_id": str(run.id),
        "run_number": run.run_number,
        "mode": run.mode,
        "status": run.status,
        "result_digest": run.result_digest,
        "config_hash": run.config_hash,
        "workload": workload(run),
        "case_fingerprint": canonical_hash(fingerprint),
        "tool": run.config.get("ai_tool"),
        "cases": len(cases),
        "completed": len(completed),
        "should_approve": len(should_approve),
        "should_reject": len(should_reject),
        "approved": sum(c.outcome == "approved" for c in cases),
        "rejected": sum(c.outcome == "rejected" for c in cases),
        "correct": sum(c.outcome == c.expected_outcome for c in cases),
        "false_approvals": sum(c.outcome == "approved" for c in should_reject),
        "false_rejections": sum(c.outcome == "rejected" for c in should_approve),
        "manual_reviews": sum(c.manual_reviews for c in cases),
        "review_seconds": sum(c.review_seconds for c in cases),
        "queue_wait_seconds": sum(c.queue_wait_seconds for c in cases),
        "escalations": sum("compliance_review" in c.path for c in cases),
        "automated_approvals": sum(c.automated for c in cases),
        "overdue_tasks": overdue,
        "document_timeouts": document_timeouts,
        "failed_executions": failed_executions,
        "exceptions": overdue + document_timeouts + failed_executions + ai_errors,
        "cycle_seconds": {
            "sum": sum(cycles),
            "avg": sum(cycles) / len(cycles) if cycles else None,
            "p50": _percentile(cycles, 0.5),
            "p95": _percentile(cycles, 0.95),
            "max": max(cycles) if cycles else None,
        },
        "ai": {
            "invocations": sum(statuses.values()),
            "executed_invocations": sum(statuses.values()) - statuses.get("blocked", 0),
            "by_status": statuses,
            "errors": ai_errors,
            "blocked": statuses.get("blocked", 0),
            "recommendations": recommendations,
        },
        "decisions_checked": decisions,
        "policy_violations": len(violations),
        "policy_violation_details": violations[:20],
        "simulated_hours": run.results.get("simulated_hours") if run.results else None,
    }


def measurement_digest(metrics: dict[str, Any]) -> str:
    """Fingerprint of what must reproduce: excludes run identifiers."""
    stable = {k: v for k, v in metrics.items() if k not in ("run_id", "run_number")}
    stable["policy_violation_details"] = [
        {"rule": v["rule"]} for v in metrics.get("policy_violation_details", [])
    ]
    return canonical_hash(stable)
