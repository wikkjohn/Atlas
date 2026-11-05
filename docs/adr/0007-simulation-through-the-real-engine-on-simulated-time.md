# ADR 0007: Simulation runs the real engine on simulated time, with seeded randomness

- **Status:** Accepted
- **Decided in:** Phases 5, 15, 16

## Context
Experiments compare AI tools and process changes, so their results must reflect what the
bank would actually do, and they must be reproducible.

## Decision
- **No separate model of the process.** The simulation (`backend/app/simulation/`) drives
  the real workflow engine and services on a simulated clock.
- **Real staff, real rules.** Simulated reviewers are real employees and service accounts
  in a per-run team, so every permission and four-eyes rule applies.
- **Seeded randomness.** Every random draw comes from a per-case stream derived from the
  run's seed.
- **Partitioned history.** Simulation history is kept apart from the live bank: the
  workflow tables are LIST-partitioned on `realm` (Phase 15). It can be archived, restored
  or reset.
- **Shards.** Large runs are split across worker processes, with cases dealt by
  `case_index % N` (Phase 16).

## Consequences
- **Benefits:**
  - A run is reproducible from its seed and configuration.
  - An experiment measures the platform's real behaviour.
- **Costs:**
  - A simulated case costs as much as a real one: about 128–197 SQL statements.
  - At 20.8 cases a second, the Milestone F exit target of one million cases in a few hours
    was not met (Phase 75).
  - Simulated durations are in simulated time, which the dashboards label.

## Evidence
- `docs/simulation.md`
- `backend/app/simulation/history.py`
- `backend/tests/test_simulation_shards.py`
