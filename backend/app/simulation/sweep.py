"""The country sweep (Phase 28): the Milestone C exit check.

Runs each rule-following scenario (`global-onboarding`, `global-payments`) once per active
country, with that country's applicants, payers and staff only, and checks each run:
- every case completes;
- every outcome matches its ground truth (the scenarios' reviewers never err, so a
  mismatch is the workflow's or the country rules');
- the workload's control check finds no violation (four-eyes, authority, approvals before
  money moves).
"""

import time
import uuid
import zlib
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.modules.countries.models import Country, OperationalStatus
from app.simulation.generators import case_random
from app.simulation.models import SimulationCaseResult, SimulationRun, SimulationStatus
from app.simulation.runner import create_run, execute_run
from app.simulation.scenarios import Scenario, get_scenario, normalized
from app.simulation.workloads import workload_for

SCENARIOS = ("global-onboarding", "global-payments")
# The random stream each workload draws a case's kind from (its first draw).
KIND_STREAM = {"retail_onboarding": "application", "domestic_payments": "payment"}


@dataclass
class SweepResult:
    country: str
    scenario: str
    run_number: int
    seed: int
    status: str
    cases: int
    completed: int
    correct: int
    violations: int
    passed: bool
    seconds: float
    problems: list[str] = field(default_factory=list)
    kinds: dict[str, int] = field(default_factory=dict)  # cases of each kind


def case_kinds(scenario: Scenario, seed: int, cases: int) -> list[str]:
    """The kind of each case a run of `scenario` with this seed generates, without running it:
    a case's kind is the first draw of its own random stream."""
    mix = normalized(scenario.config.mix)
    kinds = sorted(mix)
    weights = [mix[k] for k in kinds]
    stream = KIND_STREAM[scenario.workload]
    return [
        case_random(seed, index, stream).choices(kinds, weights=weights)[0]
        for index in range(cases)
    ]


def covering_seed(scenario: Scenario, cases: int, start: int) -> int:
    """The first seed from `start` whose cases include every kind of the scenario's mix, so
    each run exercises all of them (rare kinds would otherwise be missed at small sizes)."""
    wanted = set(scenario.config.mix)
    if cases < len(wanted):
        raise ValueError(f"{cases} cases cannot cover {len(wanted)} kinds.")
    for seed in range(start, start + 100_000):
        if set(case_kinds(scenario, seed, cases)) == wanted:
            return seed
    raise ValueError("No seed covers every kind; use more cases.")


def active_countries(db: Session) -> list[str]:
    return sorted(
        db.execute(
            select(Country.iso_country_code).where(
                Country.operational_status == OperationalStatus.ACTIVE
            )
        ).scalars()
    )


def run_one(
    factory: sessionmaker[Session],
    scenario_id: str,
    country: str,
    *,
    cases: int,
    employees: int,
    seed: int,
    created_by: uuid.UUID,
) -> SweepResult:
    scenario = get_scenario(scenario_id)
    assert scenario is not None
    # Each country starts its search from its own seed, so countries see different cases.
    seed = covering_seed(scenario, cases, seed + zlib.crc32(country.encode()) % 1_000_000)
    started = time.perf_counter()
    with factory() as db, db.begin():
        run = create_run(
            db,
            scenario,
            profile="custom",
            applications=cases,
            employees=employees,
            seed=seed,
            created_by=created_by,
            countries=[country],
        )
        run_id, run_number = run.id, run.run_number
    execute_run(factory, run_id)
    with factory() as db:
        run = db.get(SimulationRun, run_id)
        assert run is not None
        results = run.results or {}
        truth = results.get("ground_truth", {})
        completed, correct = results.get("completed", 0), truth.get("correct", 0)
        violations = workload_for(scenario).check_controls(db, run_id).violations
        problems = []
        if run.status != SimulationStatus.COMPLETED:
            problems.append(f"run {run.status}: {run.failure_reason}")
        if completed != cases:
            problems.append(f"{cases - completed} of {cases} cases unfinished")
        if correct != completed:
            mismatched = db.execute(
                select(
                    SimulationCaseResult.case_index,
                    SimulationCaseResult.kind,
                    SimulationCaseResult.expected_outcome,
                    SimulationCaseResult.outcome,
                )
                .where(
                    SimulationCaseResult.run_id == run_id,
                    SimulationCaseResult.outcome.is_distinct_from(
                        SimulationCaseResult.expected_outcome
                    ),
                )
                .order_by(SimulationCaseResult.case_index)
            ).all()
            problems += [
                f"case {i} ({kind}): expected {expected}, got {outcome}"
                for i, kind, expected, outcome in mismatched
            ]
        problems += [f"control violation: {v['rule']}" for v in violations]
        kinds = {kind: entry["cases"] for kind, entry in results.get("by_kind", {}).items()}
        missing = sorted(set(scenario.config.mix) - set(kinds))
        if missing:
            problems.append(f"kinds not exercised: {', '.join(missing)}")
        return SweepResult(
            country=country,
            scenario=scenario_id,
            run_number=run_number,
            seed=seed,
            status=run.status,
            cases=cases,
            completed=completed,
            correct=correct,
            violations=len(violations),
            passed=not problems,
            seconds=round(time.perf_counter() - started, 2),
            problems=problems,
            kinds=kinds,
        )


def sweep(
    factory: sessionmaker[Session],
    *,
    created_by: uuid.UUID,
    countries: list[str] | None = None,
    scenarios: tuple[str, ...] = SCENARIOS,
    cases: int = 20,
    employees: int = 8,
    seed: int = 2028,
    progress: Callable[[SweepResult], None] | None = None,
) -> list[SweepResult]:
    """Every scenario in every country (default: all active ones), one run each."""
    if countries is None:
        with factory() as db:
            countries = active_countries(db)
    found = []
    for country in countries:
        for scenario_id in scenarios:
            result = run_one(
                factory,
                scenario_id,
                country,
                cases=cases,
                employees=employees,
                seed=seed,
                created_by=created_by,
            )
            found.append(result)
            if progress is not None:
                progress(result)
    return found


def report(results: list[SweepResult]) -> dict:
    failed = [r for r in results if not r.passed]
    return {
        "runs": len(results),
        "countries": len({r.country for r in results}),
        "cases": sum(r.cases for r in results),
        "passed": len(results) - len(failed),
        "failed": [asdict(r) for r in failed],
        "seconds": round(sum(r.seconds for r in results), 1),
        "kinds": _kinds(results),
        "results": [asdict(r) for r in results],
    }


def _kinds(results: list[SweepResult]) -> dict[str, dict[str, int]]:
    """Per scenario: cases of each kind, and in how many countries each kind occurred."""
    found: dict[str, dict[str, int]] = {}
    for r in results:
        for kind, n in r.kinds.items():
            entry = found.setdefault(f"{r.scenario}:{kind}", {"cases": 0, "countries": 0})
            entry["cases"] += n
            entry["countries"] += 1
    return dict(sorted(found.items()))
