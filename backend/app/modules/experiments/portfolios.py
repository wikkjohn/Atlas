"""Experiment portfolios (Phase 78, roadmap Milestone G step 3).

A portfolio evaluates a tool **family** (a product line of tools, e.g. the AGB rule-based
review assistants) wherever it applies: every scenario with AI modes that one of the
family's active tools is compatible with, in each chosen country. Each such cell is a
repeated-seed series (Phase 77); when all have completed, the portfolio computes
statistics across the cells (`significance.portfolio_statistics`), with breakdowns by
department and country. Scenarios with application outages are left out: their effects
come from the outage, not the tool.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import BusinessRuleViolation, NotFoundError
from app.core.pagination import PageParams, paginate
from app.modules.ai_tools.models import AITool, ToolStatus
from app.modules.experiments import series as series_service
from app.modules.experiments import service
from app.modules.experiments.models import (
    ExperimentPortfolio,
    ExperimentSeries,
    ExperimentStatus,
)
from app.modules.experiments.schemas import (
    MAX_PORTFOLIO_EXPERIMENTS,
    PortfolioCreate,
    PortfolioDetail,
    PortfolioSummary,
    SeriesCreate,
)
from app.modules.experiments.significance import portfolio_statistics
from app.modules.identity.models import User
from app.simulation import runner
from app.simulation import service as simulations
from app.simulation.scenarios import SCENARIOS, Scenario
from app.simulation.workloads import workload_for

logger = logging.getLogger("atlas.experiments")


def _version_key(tool: AITool) -> tuple:
    return tuple(int(p) if p.isdigit() else p for p in tool.tool_version.split("."))


def family_tools(db: Session, family: str) -> dict[str, AITool]:
    """The family's active tools, the latest version of each."""
    latest: dict[str, AITool] = {}
    for tool in db.execute(
        select(AITool).where(AITool.family == family, AITool.status == ToolStatus.ACTIVE)
    ).scalars():
        if tool.tool_id not in latest or _version_key(tool) > _version_key(latest[tool.tool_id]):
            latest[tool.tool_id] = tool
    return latest


def plan(db: Session, family: str, mode: str) -> tuple[list[dict[str, Any]], list[dict]]:
    """The scenarios the family serves, each with the tool that serves it, and the AI
    scenarios it does not (with why)."""
    tools = family_tools(db, family)
    latest: dict[str, Scenario] = {}
    for (scenario_id, version), scenario in SCENARIOS.items():
        if scenario.config.ai_assistance is None:
            continue
        if scenario_id not in latest or version > latest[scenario_id].version:
            latest[scenario_id] = scenario
    cells, skipped = [], []
    for scenario_id, scenario in sorted(latest.items()):
        tool = next(
            (t for _, t in sorted(tools.items()) if scenario.workflow_id in t.compatible_workflows),
            None,
        )
        reason = None
        if scenario.config.outages:
            reason = "an outage scenario: its effects come from the outage"
        elif tool is None:
            reason = f"no tool of the family serves {scenario.workflow_id}"
        elif mode == "ai_automated" and workload_for(scenario).automated_path is None:
            reason = "no automated decision path"
        if reason:
            skipped.append({"scenario_id": scenario_id, "reason": reason})
            continue
        cells.append(
            {
                "scenario_id": scenario_id,
                "scenario_version": scenario.version,
                "workflow_id": scenario.workflow_id,
                "tool_id": tool.tool_id,
                "tool_version": tool.tool_version,
            }
        )
    return cells, skipped


def department(db: Session, workflow_id: str) -> str | None:
    from app.modules.workflows import registry
    from app.modules.workflows.models import WorkflowCatalogueEntry

    entry = db.execute(
        select(WorkflowCatalogueEntry.department).where(
            WorkflowCatalogueEntry.workflow_id == workflow_id
        )
    ).scalar_one_or_none()
    if entry:
        return entry
    catalogue = registry.catalogue_of(workflow_id)
    if catalogue and catalogue.department:
        return catalogue.department
    # A stored definition names its owning department as its business owner.
    from app.modules.workflows.models import WorkflowDefinitionRecord as Definition

    owner = db.execute(
        select(Definition.definition["business_owner"].astext)
        .where(Definition.workflow_id == workflow_id)
        .order_by(Definition.version.desc())
        .limit(1)
    ).scalar_one_or_none()
    return owner or None


def create(db: Session, body: PortfolioCreate, actor_id: uuid.UUID) -> ExperimentPortfolio:
    cells, skipped = plan(db, body.family, body.candidate_mode)
    if not cells:
        raise BusinessRuleViolation(
            f"No active tool of the family '{body.family}' serves a scenario with AI modes.",
            {"skipped": skipped},
        )
    experiments = len(cells) * len(body.countries) * body.replicates
    if experiments > MAX_PORTFOLIO_EXPERIMENTS:
        raise BusinessRuleViolation(
            f"The portfolio would run {experiments} experiments; at most "
            f"{MAX_PORTFOLIO_EXPERIMENTS}. Use fewer countries or seeds.",
            {"cells": len(cells), "countries": len(body.countries)},
        )
    simulations.reap_stale(db)
    simulations._ensure_idle(db)  # once: the portfolio's runs then queue behind each other
    config, config_hash = service._config(body.costs, body.thresholds)
    seeds = [body.seed + i for i in range(body.replicates)]
    portfolio = ExperimentPortfolio(
        name=body.name.strip(),
        family=body.family,
        candidate_mode=body.candidate_mode,
        countries=body.countries,
        seeds=seeds,
        applications=body.applications,
        employees=body.employees,
        confidence=body.confidence,
        configuration={**config, "plan": {"cells": cells, "skipped": skipped}},
        configuration_hash=config_hash,
        status=ExperimentStatus.RUNNING.value,
        created_by=actor_id,
    )
    db.add(portfolio)
    db.flush()
    for cell in cells:
        for country in body.countries:
            series_service.create(
                db,
                SeriesCreate(
                    name=f"{portfolio.name} · {cell['scenario_id']} · {country}",
                    scenario_id=cell["scenario_id"],
                    scenario_version=cell["scenario_version"],
                    tool_id=cell["tool_id"],
                    tool_version=cell["tool_version"],
                    candidate_mode=body.candidate_mode,
                    profile="custom",
                    applications=body.applications,
                    employees=body.employees,
                    seeds=seeds,
                    confidence=body.confidence,
                    country=country,
                    costs=body.costs,
                    thresholds=body.thresholds,
                ),
                actor_id,
                portfolio_id=portfolio.id,
                check_idle=False,
            )
    db.flush()
    db.refresh(portfolio)
    return portfolio


def cells(db: Session, portfolio: ExperimentPortfolio) -> list[ExperimentSeries]:
    return list(
        db.execute(
            select(ExperimentSeries)
            .where(ExperimentSeries.portfolio_id == portfolio.id)
            .order_by(ExperimentSeries.series_number)
        ).scalars()
    )


def run_ids(db: Session, portfolio: ExperimentPortfolio) -> list[uuid.UUID]:
    return [r for s in cells(db, portfolio) for r in series_service.run_ids(db, s)]


def compute(db: Session, portfolio: ExperimentPortfolio, members: list[ExperimentSeries]):
    rows = []
    for s in members:
        scenario = SCENARIOS[(s.scenario_id, s.scenario_version)]
        rows.append(
            {
                "scenario_id": s.scenario_id,
                "workflow_id": scenario.workflow_id,
                "department": department(db, scenario.workflow_id),
                "country": s.country,
                "tool_id": s.tool_id,
                "series_number": s.series_number,
                "verdict": s.verdict,
                "metrics": (s.statistics or {}).get("metrics", []),
            }
        )
    return portfolio_statistics(rows, portfolio.confidence)


def refresh(db: Session, portfolio: ExperimentPortfolio) -> ExperimentPortfolio:
    if portfolio.status != ExperimentStatus.RUNNING:
        return portfolio
    db.flush()
    portfolio = db.execute(
        select(ExperimentPortfolio).where(ExperimentPortfolio.id == portfolio.id).with_for_update()
    ).scalar_one()
    db.refresh(portfolio)
    if portfolio.status != ExperimentStatus.RUNNING:
        return portfolio
    members = [series_service.refresh(db, s) for s in cells(db, portfolio)]
    failed = [s for s in members if s.status == ExperimentStatus.FAILED]
    if failed:
        portfolio.status = ExperimentStatus.FAILED.value
        portfolio.failure_reason = "; ".join(
            f"{s.scenario_id} ({s.country}): {s.failure_reason}" for s in failed
        )[:4000]
        portfolio.completed_at = datetime.now(UTC)
    elif members and all(s.status == ExperimentStatus.COMPLETED for s in members):
        portfolio.statistics = compute(db, portfolio, members)
        portfolio.verdict = portfolio.statistics["verdict"]
        portfolio.status = ExperimentStatus.COMPLETED.value
        portfolio.completed_at = datetime.now(UTC)
    db.flush()
    return portfolio


def execute(
    session_factory: sessionmaker[Session], portfolio_id: uuid.UUID, ids: list[uuid.UUID]
) -> None:
    """Background job: every cell's runs, one after another, then the statistics."""
    runner.execute_batch(session_factory, ids)
    with session_factory() as db:
        try:
            portfolio = db.get(ExperimentPortfolio, portfolio_id)
            if portfolio is not None:
                refresh(db, portfolio)
            db.commit()
        except Exception as exc:  # recorded on the portfolio; nothing awaits this job
            db.rollback()
            logger.exception("experiment portfolio evaluation failed")
            portfolio = db.get(ExperimentPortfolio, portfolio_id)
            if portfolio is not None:
                portfolio.status = ExperimentStatus.FAILED.value
                portfolio.failure_reason = f"Evaluation failed: {type(exc).__name__}: {exc}"
                portfolio.completed_at = datetime.now(UTC)
                db.commit()


def get(db: Session, portfolio_id: uuid.UUID) -> ExperimentPortfolio:
    portfolio = db.get(ExperimentPortfolio, portfolio_id)
    if portfolio is None:
        raise NotFoundError("Experiment portfolio not found.")
    return refresh(db, portfolio)


def summary(db: Session, portfolio: ExperimentPortfolio) -> PortfolioSummary:
    creator = db.get(User, portfolio.created_by)
    counts = db.execute(
        select(
            func.count(),
            func.count().filter(ExperimentSeries.status == ExperimentStatus.COMPLETED),
        ).where(ExperimentSeries.portfolio_id == portfolio.id)
    ).one()
    return PortfolioSummary(
        id=portfolio.id,
        portfolio_number=portfolio.portfolio_number,
        name=portfolio.name,
        family=portfolio.family,
        candidate_mode=portfolio.candidate_mode,
        countries=portfolio.countries,
        seeds=portfolio.seeds,
        applications=portfolio.applications,
        employees=portfolio.employees,
        confidence=portfolio.confidence,
        status=portfolio.status,
        failure_reason=portfolio.failure_reason,
        verdict=portfolio.verdict,
        cells=counts[0],
        cells_completed=counts[1],
        created_by_username=creator.username if creator else None,
        created_at=portfolio.created_at,
        completed_at=portfolio.completed_at,
    )


def detail(db: Session, portfolio: ExperimentPortfolio) -> PortfolioDetail:
    return PortfolioDetail(
        **summary(db, portfolio).model_dump(),
        configuration=portfolio.configuration,
        statistics=portfolio.statistics,
        series=[series_service.summary(db, s) for s in cells(db, portfolio)],
    )


def list_portfolios(db: Session, params: PageParams) -> tuple[list[PortfolioSummary], int]:
    query = select(ExperimentPortfolio).order_by(ExperimentPortfolio.portfolio_number.desc())
    items, total = paginate(db, query, params)
    return [summary(db, refresh(db, p)) for p in items], total
