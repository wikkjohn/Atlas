# Simulation engine

The simulation engine (`backend/app/simulation`) runs seeded, reproducible workloads of
synthetic customers and staff through the **real** workflow engine on **simulated time**.
There is no separate model of the bank's processes: every simulated application is a
WF-0001 execution, every approval passes the same permission and four-eyes checks, and
every approved case opens a real (synthetic) account through the Phase 3 services.

## Concepts

| Concept | Where | What it is |
| --- | --- | --- |
| Simulation clock | `clock.py` | Timezone-aware simulated time that only moves forward. Each scenario starts at a fixed moment (`2026-01-05 09:00 UTC` for `retail-onboarding`), so simulated timestamps are reproducible. |
| Scenario | `scenarios.py` | Versioned definition of *what* is simulated: the workflow, the application mix, arrival window, document delays, reviewer behaviour and staff mix. |
| Profile | `scenarios.py` | *How much*: small (100 applications / 100 customers / 25 staff), department (10,000 / 10,000 / 500), enterprise (1,000,000 / 150,000 — a configuration target, see below), or a custom size (up to 10,000 / 500). |
| Generators | `generators.py` | Synthetic applications with known ground truth and synthetic staff. Every random draw uses its own `random.Random` derived from the seed and the case index — never the global random state. |
| Runner | `runner.py` | Discrete-event loop that drives the workflow engine (below). |
| Run registry | `simulation_runs`, `simulation_case_results` | Configuration, software version, progress, results and per-case measurements of every run. |

## What a run does

1. **Configuration is resolved and stored** before anything runs: scenario id and version,
   workflow id and version, profile and sizes, the full scenario configuration and the
   dataset it draws on (the active countries). Its SHA-256 is the `config_hash`. The
   software version (`app.__version__` plus `ATLAS_BUILD_SHA` when set) and the seed are
   stored next to it.
2. **Simulated staff are hired** into a new team, `Simulation run N`, under a
   `Simulated Operations` department of the first active country's Retail Banking division.
   Tellers are banking employees, managers department managers, compliance analysts
   compliance officers. Each has a service-account user that holds the role's permissions
   but can never sign in (its password hash is not a valid hash).
3. **Applications arrive** at seeded times across the arrival window and are started by a
   teller (round robin) with `engine.start(now=<simulated time>)`.
4. **Events are processed in simulated-time order** (a heap ordered by time, then insertion
   order). After each event the runner inspects the case and schedules what happens next:
   - an **approval** is queued to its reviewer pool (`account_approval` → managers,
     `compliance_review` → compliance analysts). Each reviewer handles one case at a time
     (the earliest-free reviewer takes the next case), review time is lognormal around the
     scenario's mean, and the decision matches the ground truth with the scenario's
     accuracy — so queues, waiting time and mistakes emerge from the model;
   - a **document wait** receives the late documents as a `documents_submitted` signal
     after the seeded delay — or never, for abandoned applications, whose 72-hour timeout
     then rejects them;
   - every **timeout** (`due_at`) fires at its due time through `process_timers`;
     approval timeouts flag the task as overdue, which the results count.
5. **Results are collected** per case (ground truth, outcome, risk rating, flags, reviews,
   reviewer time, queue wait, cycle time, path through the workflow) and summarized:
   outcomes per case type, decision accuracy with false approvals and false rejections,
   straight-through rate, review labour, overdue tasks, cycle-time and queue-wait
   percentiles, events processed, workflow steps completed, wall time and throughput.
6. Work is committed every 250 events together with progress and a heartbeat, so a run can
   be watched while it executes.

### Case types (retail-onboarding v1)

| Case type | Share | Ground truth | How WF-0001 handles it |
| --- | --- | --- | --- |
| `clean` | 70 % | approve | authorized approval |
| `missing_documents` | 6 % | approve | waits for proof of address (2–48 h), then approval |
| `abandoned_documents` | 2 % | reject | documents never arrive; rejected by the 72 h timeout |
| `politically_exposed` | 6 % | approve | high risk → compliance review |
| `name_mismatch` | 5 % | approve | identity issue flagged → compliance review |
| `sanctions_hit` | 4 % | reject | synthetic watchlist name → compliance review |
| `forged_document` | 4 % | reject | invalid check digit → rejected automatically |
| `underage` | 3 % | reject | under 18 → rejected at validation |

Reviewers: authorized approval 12 minutes on average with 97 % accuracy; compliance review
35 minutes with 93 % accuracy (lognormal spread σ = 0.5). Staff mix: 40 % tellers, 40 %
managers, 20 % compliance.

## Scenario versions and AI modes (Phase 6)

| Scenario | Workflow | Modes |
| --- | --- | --- |
| `retail-onboarding` v1 | WF-0001 v1 | baseline |
| `retail-onboarding` v2 | WF-0001 v2 | baseline, ai_assisted, ai_automated (needs an AI tool) |

Scenarios pin their workflow version, so a scenario version always means the same thing.
v2 adds the `ai_assistance` assumptions (review time and accuracy with AI advice) to its
configuration. Suites run several modes on the same seed one after another. See
[ai-testing.md](ai-testing.md#experiment-configurations).

## Reproducibility

The same scenario version, dataset, seed, configuration and software version produce the
same results. Each run stores a **result digest**: SHA-256 over every case's ground truth,
outcome, risk rating, flags, review count, review and wait seconds, overdue count, cycle
time and step path, in case order. Database identifiers and wall-clock times are excluded
because they legitimately differ between runs.

Why it holds:

- all randomness comes from per-case streams (`random.Random("{seed}:{case}:{purpose}")`,
  hashed with SHA-512 by Python, independent of `PYTHONHASHSEED` and processing order);
- the simulation clock starts at a fixed moment and the workflow engine is given simulated
  time for every step, so ages, expiry checks and timeouts are evaluated identically;
- events with equal times keep their insertion order, and reviewers with equal free times
  are chosen by index.

`GET /api/v1/simulations/{id}` lists every other completed run with the same scenario,
seed, configuration hash and software version, and whether its digest matches.
`POST /api/v1/simulations/{id}/rerun` repeats a run. The test suite asserts that equal
seeds give equal digests and different seeds different ones; `scripts/validate_system.py
--login auditor` checks every repeated configuration of a running stack.

## Synthetic data only

Applicant names pair common given names and surnames from fixed lists; sanctions cases use
four fictional watchlist names. Dates of birth, document numbers (prefix + 7 digits + check
digit) and countries are generated. There are no addresses, contact details, national
identifiers or other personal information. Simulated staff use `atlasbank.example`
addresses and are labelled "(simulated)".

## Failure reporting

A run that cannot proceed is marked `failed` with its reason, for example:

- no active Retail Banking division exists to employ the simulated staff (run
  `make seed` first);
- no active country is configured;
- the scenario's workflow version is no longer registered;
- cases are left open when no simulated event remains;
- any unexpected error (type and message are recorded).

A run whose process stops (restart, crash) stops sending heartbeats; after 5 minutes it is
reported as failed with an "Interrupted" reason the next time runs are read. Only one run
executes at a time.

## Measured performance

Measured in the development container (4 vCPUs, PostgreSQL 16 on the same host), single
process, against the development database (Phase 5 code, seed 42 for small and 2026 for
department; wall time includes hiring the simulated staff):

| Profile | Applications / staff | Wall time | Throughput | Notes |
| --- | --- | --- | --- | --- |
| small | 100 / 25 | 24.7 s | 4.0 cases/s | 293 events, 1,466 workflow steps |
| department | 10,000 / 500 | 35 min 16 s | 4.7 cases/s | 29,632 events, 146,246 workflow steps; all 10,000 cases completed |
| enterprise | 1,000,000 / 150,000 | not run | — | configuration target only |

The cost is dominated by the workflow engine's durability: each case is ~15 committed step
transitions with their history events, audit records, customer, account and ledger rows
(roughly 190 SQL statements per case).

The department run's outcomes, for scale: 8,396 approved and 1,604 rejected; decision
accuracy 96.5 % against ground truth (33 false approvals, 320 false rejections, all from
the simulated reviewers' configured error rates); 9,092 manual reviews and 2,370 hours of
simulated review labour; median cycle time 12 minutes, p95 28 hours (late documents);
80 simulated hours from the first arrival to the last decision.

**The enterprise profile is a configuration target, not a verified capability.** At the
measured throughput a million applications would take days in one process, and hiring
150,000 simulated staff is untested. The API refuses to start it. Reaching that scale needs
parallel runners (partitioning cases across processes while keeping per-case random
streams, which already makes results independent of processing order) and bulk paths in
the engine; neither exists yet.

## Running simulations

- **UI:** Simulation Center (`/simulations`) — choose a scenario, workload and seed, start
  a run, watch its progress, inspect outcomes, ground-truth accuracy, case types,
  reproducibility and per-case results, and rerun with the same seed. Every role can read
  runs; AI researchers and administrators can start them.
- **API:** see [api.md](api.md#simulations).
- **CLI:** `make simulate` or
  `cd backend && .venv/bin/python -m app.cli simulate --profile custom --applications 500 --employees 40 --seed 7`
  runs to completion in the foreground and prints the results.

## Limitations

- Runs write into the same synthetic bank as everything else: simulated customers,
  accounts, ledger postings and staff remain afterwards (staff are grouped in their run's
  team; executions carry `simulation_run_id`). There is no reset or cleanup command yet.
- Reviewers work around the clock; there are no shifts, holidays or absences.
- Arrivals are uniform across the window; no peaks or seasonality.
- Background runs execute inside the API process (FastAPI background tasks). A restart
  interrupts a run; it is then reported as interrupted and must be started again.
- One scenario exists (`retail-onboarding`, v1 and v2, WF-0001).
- Workflow steps take no simulated time; only waiting for people and documents does. An
  automated case therefore completes the moment it arrives.
