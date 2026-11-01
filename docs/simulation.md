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
| Scenario | `scenarios.py` | Versioned definition of *what* is simulated: the workload, the workflow, the case mix, arrival window, document delays, reviewer behaviour and staff mix. |
| Workload | `workloads.py` | How a scenario's cases are made and checked (Phase 9): the case generator with its ground truth and any pre-existing customers and accounts the cases need, which staff role decides each approval step, where the AI step and the automated decision live in the context, and the authorization check of every decision. One per business workflow: `retail_onboarding`, `domestic_payments`, `personal_loans`. |
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
3. **Cases arrive** at seeded times across the arrival window and are started by a
   teller (round robin) with `engine.start(now=<simulated time>)`. Before that, workloads
   whose cases need existing customers create them (see *Workloads* below).
4. **Events are processed in simulated-time order** (a heap ordered by time, then insertion
   order). After each event the runner inspects the case and schedules what happens next:
   - an **approval** is queued to its reviewer pool, chosen by the workload
     (`account_approval` → managers, `compliance_review` → compliance analysts in
     onboarding; `fraud_review` → compliance, `payment_approval` → managers in payments;
     `underwriting_review` → managers, `credit_committee` → executives in lending). Each reviewer handles one case at a time
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

## Workloads (Phase 9)

| Scenario | Workload | Workflow | Modes |
| --- | --- | --- | --- |
| `domestic-payments` v1 | `domestic_payments` | WF-0002 v1 | baseline, ai_assisted, ai_automated (AGB Payment Fraud Screener) |
| `personal-loans` v1 | `personal_loans` | WF-0003 v1 | baseline |
| `personal-loans` v2 (Phase 11) | `personal_loans_income` | WF-0003 v2 | baseline, ai_assisted, ai_automated (AGB Credit Underwriting Assistant) |

**Population.** Payments and loans need customers who already bank with ATLAS. Before the
cases arrive the workload creates them through the normal services — a KYC-verified, low
risk customer and a current account requested by a simulated teller and approved by a
simulated manager, dated a week before the scenario starts, and for payers a synthetic
cash deposit. Payees come from a pool per country (12 people, plus the four synthetic
watchlist names when a case needs them). A payment to a *known* payee is preceded by a
small released payment last week, so screening sees an existing relationship.

### Case types (domestic-payments v1)

| Case type | Share | Ground truth | What happens in WF-0002 |
| --- | --- | --- | --- |
| `routine` | 50 % | release | known payee, 2–20 % of the balance: straight-through |
| `new_payee` | 15 % | release | first payment, ≤ 30 % of the balance: straight-through |
| `high_value` | 8 % | release | 10,000–40,000 to a known payee: manager approval |
| `large_share` | 7 % | release | 85–98 % of the balance to a new payee: held, fraud review |
| `scam` | 8 % | reject | scam phrase in the reference: held, fraud review |
| `quiet_scam` | 4 % | reject | looks exactly like `large_share`: held; only a person can tell |
| `watchlisted_payee` | 3 % | reject | payee on the synthetic watchlist: held, high risk |
| `insufficient_funds` | 5 % | reject | refused automatically |

Fraud review: 20 minutes, 90 % accuracy; high-value approval: 8 minutes, 97 %. Staff: 40 %
operations officers, 30 % managers, 30 % fraud analysts. The `quiet_scam` cases are the
point of the scenario: a rule-based screener rates them low risk, so automated release
lets them through where a person sometimes stops them.

### Case types (personal-loans v1)

| Case type | Share | Ground truth | What happens in WF-0003 |
| --- | --- | --- | --- |
| `prime` | 40 % | approve | score 720–850, 5,000–20,000: underwriter |
| `near_prime` | 15 % | approve | score 640–719 (flagged): underwriter |
| `self_employed` | 5 % | approve | self-employed income (flagged): underwriter |
| `large_loan` | 10 % | approve | 26,000–50,000: underwriter, then credit committee |
| `poor_credit` | 10 % | decline | score < 560: declined automatically |
| `overextended` | 10 % | decline | existing debts 45–60 % of income: declined automatically |
| `inflated_income` | 10 % | decline | passes every rule; only an underwriter can catch it |

Applicants are drawn until the synthetic bureau score fits the case type. Underwriting:
25 minutes, 93 % accuracy; credit committee: 30 minutes, 97 %. Staff: 40 % lending
officers, 45 % underwriters (department managers), 15 % committee members (regional
executives).

### personal-loans v2 (Phase 11)

The same case types, staff and reviewers as v1 on WF-0003 v2, with incomes declared
relative to the synthetic bureau's income estimate: honest applicants 0.8–1.12× the
estimate, self-employed 0.9–1.6× (some legitimately above it), inflated incomes 1.5–2.3×;
large loans go to applicants with an estimate of at least 7,000. The ratio comes from its
own random stream, so v1 runs are unchanged and still reproduce.

### Measured (Phase 9, development container)

| Run | Cases / staff | Wall time | Outcome |
| --- | --- | --- | --- |
| `domestic-payments` baseline, seed 7 | 100 / 25 | 35.8 s (incl. population) | 99 % correct; 63 % straight-through; 37 manual reviews |
| `domestic-payments` AI automated, seed 7 | 100 / 25 | — | 95 % correct: all 5 quiet scams released by the policy engine; 21 manual reviews |
| `personal-loans` baseline, seed 42 | 100 / 25 | 17.2 s | 93 % correct (7 false declines, 0 false approvals); 91 manual reviews |
| `personal-loans` v2, seed 11, baseline / assisted / automated (Phase 11) | 300 / 40 | 32–35 s each | 94.3 % / 99.3 % / 99.7 % correct; 264 / 266 / 168 manual reviews; 98 loans underwritten by the policy engine |

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

## Bulk population (Phase 13)

`python -m app.cli load-population --customers N [--seed S] [--batch B]` adds N synthetic,
KYC-verified, low-risk individual customers spread evenly over the active countries, each
with an approved current-account request (requested by `employee`, decided by `manager`:
four-eyes), the open account in the country's currency and an opening deposit of 50–25,000
posted through the ledger's bulk path. Names, birth dates and deposits come from
`case_random(seed, index, "population")`. It needs the demo users (`seed-demo`) and refuses
to run in staging or production. Simulation runs still create their own customers through
the services.

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
| department, 8 shards (Phase 16) | 10,000 / 500 | 6 min 39 s | 25.0 cases/s | identical digest on a second run |
| large, 8 shards (Phase 16) | 100,000 / 5,000 | 73 min 18 s | 22.7 cases/s | 96.65 % accuracy, 91,086 manual reviews |
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
150,000 simulated staff is untested. The API refuses to start it. Phase 16 added parallel
shards (below), which carried a 100,000-application run in 73 minutes on 4 vCPUs (the
`large` profile); a million would still need more machines than one development container
and bulk paths in the workflow engine.

## Running simulations

- **UI:** Simulation Center (`/simulations`) — choose a scenario, workload and seed, start
  a run, watch its progress, inspect outcomes, ground-truth accuracy, case types,
  reproducibility and per-case results, and rerun with the same seed. Every role can read
  runs; AI researchers and administrators can start them.
- **API:** see [api.md](api.md#simulations).
- **CLI:** `make simulate` or
  `cd backend && .venv/bin/python -m app.cli simulate --profile custom --applications 500 --employees 40 --seed 7`
  runs to completion in the foreground and prints the results.

## Parallel shards (Phase 16)

A run can be split into up to 8 **shards** (`shards` in the API, *Parallel shards* in the
Simulation Center, `simulate --shards N` on the command line). Shard *k* simulates the
cases whose index is `k` modulo the shard count, with every role's staff dealt
round-robin to the shards, so each shard is a complete, smaller bank team with its own
queues. Each shard is a `simulation.shard` background job: worker processes run them in
parallel (Docker Compose starts 4 worker processes; `python -m app.cli worker
--processes N` locally; `simulate --shards N` starts its own processes). Without worker
processes the API runs the shards itself, one after another.

- **Same decisions, different queues.** A case's applicant, documents, reviewer decisions
  and review times come from the case's own random stream, so outcomes and ground-truth
  accuracy are identical to a single-process run with the same seed. Queue waiting and
  cycle times are longer, because N small teams do not share their slack: in a
  2,000-case run with 100 staff the average queue wait went from 0.02 h (1 shard) to
  0.13 h (4) and 0.23 h (8); see [performance.md](performance.md).
- **Reproducible.** The same scenario, seed and shard count give the same digest whichever
  worker runs which shard and in whatever order. The shard count is part of the
  configuration hash, so a sharded run never counts as a reproduction of a single-process
  one.
- **Staff.** Every shard needs at least one member of every role, so the run's staff must
  have at least `shards` of each (the API says which role is short).
- **The `large` profile** — 100,000 applications, 5,000 staff — runs with at least 4
  shards. Measured results: [performance.md](performance.md).
- **Failure.** If one shard fails, the run fails with that shard's reason; the others stop
  at their next checkpoint.

## Workflow history: archive, restore, reset (Phase 15)

A run leaves results (summary, digest, one measured row per case) and workflow history:
every case's executions, step runs and events and its AI tool calls — roughly 16 step runs
and 50 events per case. The history lives in the `simulation` partitions of the workflow
tables, apart from the live bank's.

- **Archive** (Simulation Center → a run → *Archive history*, or
  `python -m app.cli simulation-history archive --run 7`) runs as a background job. It
  writes the history to gzip-compressed PostgreSQL COPY files under
  `ATLAS_SIMULATION_ARCHIVE_DIR` (one directory per run: one file per table and a
  `manifest.json` with row counts, columns and SHA-256 checksums) and deletes it from the
  database in the same transaction. Results, case outcomes and the dashboard's figures for
  the run stay. Refused for unfinished runs and for runs of a running experiment.
- **Restore** (*Restore history*, or `simulation-history restore --run 7`) verifies the
  checksums, copies the rows back, and removes the files.
- **Retention**: `simulation-history archive --older-than-days 30`, or switch on the
  `simulation-history-retention` schedule (System Settings → Background jobs).
- **Reset** (`python -m app.cli simulation-history reset --yes [--archive]`) drops and
  recreates the simulation partitions: every run's history goes at once, without
  archives unless `--archive` archives each run first. Refused while a run is queued or
  running. Runs reset this way are marked `purged`; their results stay.
- `simulation-history status` (or System Settings → Simulation history) shows the size of
  each partition, runs by state, the archive files and the latest archives.

Measured in the development container on one run of 100,000 cases (100,236 executions,
1,577,148 step runs, 5,129,739 events; 2.4 GB in the database):

| Operation | Time | Result |
| --- | ---: | --- |
| Archive | 119 s | 6,807,087 rows in 519 MB of compressed files; the space is reused after vacuum |
| Restore | 562 s | every row back (foreign-key checks and index updates dominate) |
| Reset | 5.0 s | 4.1 GB freed immediately (partitions dropped and recreated) |
| Row-by-row DELETE before partitioning (for comparison) | events 24 s; step runs > 10 min (stopped) | a missing index on `workflow_events.step_run_id`, now added |

What a reset or archive does **not** remove: customers, accounts, ledger postings, loans,
payments and simulated staff created by simulated cases. The ledger is append-only, and
removing postings would rewrite the books; only workflow history is lifecycle-managed.
`docker compose down -v` still resets everything.

## Limitations

- Runs write into the same synthetic bank as everything else: simulated customers,
  accounts, ledger postings and staff remain afterwards (staff are grouped in their run's
  team; executions carry `simulation_run_id`). Since Phase 15 a run's workflow history can
  be archived, restored or reset (above); the domain records stay.
- Reviewers work around the clock; there are no shifts, holidays or absences.
- Arrivals are uniform across the window; no peaks or seasonality.
- Runs execute as durable background jobs (`simulation.execute`, Phase 14): in the API
  process when no worker is configured, otherwise in `python -m app.cli worker`
  processes. A run whose process stops is reported as interrupted and must be started
  again; the job is not retried.
- Fourteen scenarios exist (`retail-onboarding` v1/v2, `domestic-payments` v1,
  `payments-easter` v1, `global-onboarding` v1, `global-payments` v1, `personal-loans`
  v1/v2, `retail-overdrafts` v1 — Phase 30, the first on a stored workflow, WF-1003 v2 —
  `card-fraud-alerts` v1 — Phase 32, on stored WF-1008 v2 — and `mortgage-applications`
  v1 — Phase 34, on stored WF-1009 v2 — and `covenant-breaches` v1 — Phase 36, on stored
  WF-1013 v2, decided by simulated executives — and `discrepant-presentations` v1 — Phase
  38, on stored WF-1016 v2, decided by simulated trade officers — and `deal-confirmations` v1 —
  Phase 40, on stored WF-1018 v2, decided by simulated back office — and `recall-triage` v1 —
  Phase 42, on stored WF-1023 v2; see
  [ai-testing.md](ai-testing.md)). `payments-easter` (Phase 26) sets a business calendar, so arrivals skip UK
  weekends and holidays; see [business-calendars.md](business-calendars.md). The two
  `global-*` scenarios (Phase 28) generate cases that follow each country's rules and run
  in one country at a time in the country sweep; see [country-sweep.md](country-sweep.md). Payment payers are one customer per case, so the velocity signal
  never fires in simulations (it is covered by tests).
- Workflow steps take no simulated time; only waiting for people and documents does. An
  automated case therefore completes the moment it arrives.
