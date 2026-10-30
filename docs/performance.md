# Performance

How fast the platform's key paths are, how that is measured, and the targets that guard
against regressions. Every number here was measured; the environment is the development
container (4 vCPUs, 15 GB RAM, PostgreSQL 16 on the same host) unless a row says
otherwise.

## The performance suite

```bash
cd backend
.venv/bin/python -m app.cli perf            # full profile, a few minutes
.venv/bin/python -m app.cli perf --quick    # smaller sizes, looser targets (CI)
.venv/bin/python -m app.cli perf --only api.dashboard,jobs.throughput --output perf.json
```

The suite writes synthetic data (ledger accounts and entries coded `BENCH-…`, jobs,
simulation runs) into the configured database: run it against a scratch database, never
production (it refuses `ATLAS_ENVIRONMENT=production`). It needs the demo users
(`python -m app.cli seed-demo`). It exits non-zero when a target is missed, and `--output`
writes every value as JSON. CI runs the quick profile on every push (job *Performance
(quick suite)*) and keeps the JSON as a build artifact.

| Benchmark | What it measures | Target (quick / full) | Measured (full) |
| --- | --- | --- | ---: |
| `ledger.posting` | 5,000 single-entry postings through `post_entry`, 30 % on one hot account | ≥ 60 / ≥ 120 entries/s | 161.9 entries/s |
| `ledger.bulk_posting` | 5,000 postings through `post_entries` (COPY) | ≥ 500 / ≥ 1,500 entries/s | 2,895.8 entries/s |
| `api.customers` | `GET /api/v1/customers`, p95 of 60, in-process (no network) | ≤ 400 / ≤ 150 ms | 10.0 ms |
| `api.task_inbox` | `GET /api/v1/workflow-tasks`, p95 of 60 | ≤ 400 / ≤ 150 ms | 11.3 ms |
| `api.dashboard` | `GET /api/v1/analytics/overview`, p95 of 60 | ≤ 1,500 / ≤ 600 ms | 28.1 ms |
| `jobs.throughput` | 1,000 `system.ping` jobs drained by one worker | ≥ 30 / ≥ 60 jobs/s | 103.3 jobs/s |
| `simulation.single` | 400 retail onboarding cases in one process | ≥ 1.5 / ≥ 3 cases/s | 6.4 cases/s |
| `simulation.sharded` | 1,600 cases in 4 shards and 4 processes (full only) | ≥ 7 cases/s | 27.4 cases/s |

Measured on a freshly migrated and seeded database (Phase 16). In CI (GitHub's
`ubuntu-latest` runners) the quick profile measured, for example, 159 single postings/s,
1,266 bulk postings/s, 134 jobs/s and 6.1 cases/s.

The targets sit well below what was measured, so a miss means a real
regression, not noise. The API benchmarks call the ASGI application directly: they time
the platform's own work, not the network or an HTTP server.

## Simulation scaling (Phase 16)

Retail onboarding (WF-0001 v2), seed 2026, 2,000 applications, 100 staff, run with
`simulate --shards N` (one worker process per shard):

| Shards | Wall time | Cases/s | Speed-up | Decision accuracy | Manual reviews | Avg queue wait | Median cycle |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 333.6 s | 6.0 | 1.0× | 97.05 % | 1,819 | 0.021 h | 0.214 h |
| 2 | 159.7 s | 12.5 | 2.1× | 97.05 % | 1,819 | 0.063 h | 0.246 h |
| 4 | 80.3 s | 24.9 | 4.2× | 97.05 % | 1,819 | 0.130 h | 0.303 h |
| 8 | 81.9 s | 24.4 | 4.1× | 97.05 % | 1,819 | 0.233 h | 0.335 h |

- Four shards use the four vCPUs fully; eight add nothing on this machine (they would on a
  larger one, up to the limit of 8).
- One process is bound by round trips to PostgreSQL (about 190 statements per case), not
  by the CPU; that is why four processes gain slightly more than four times.
- Decisions, accuracy and review counts are identical at every shard count; queueing is
  not — each shard has its own, smaller team, so cases wait longer for a reviewer.

### The department profile, twice

`simulate --profile department --seed 2026 --shards 8` (10,000 applications, 500 staff):

| Run | Wall time | Cases/s | Accuracy | Manual reviews | Result digest |
| --- | ---: | ---: | ---: | ---: | --- |
| 1 | 399.4 s | 25.0 | 96.47 % | 9,092 | `d5c681393cd764b8…` |
| 2 | 413.9 s | 24.2 | 96.47 % | 9,092 | `d5c681393cd764b8…` |

Identical digests: the run is repeatable. The same profile took 35 min 16 s in one
process in Phase 5 (4.7 cases/s); its accuracy and review count then (96.5 %, 9,092) are
the same as now, because those depend only on each case's own decisions.

### One hundred thousand applications (the Milestone A exit measurement)

`simulate --profile large --seed 2026 --shards 8`: 100,000 applications through WF-0001 v2
with 5,000 simulated staff, in 8 shards on 8 worker processes (4 vCPUs):

| Measure | Value |
| --- | ---: |
| Wall time (staff hiring included) | 4,398 s (73 min 18 s) |
| Throughput | 22.7 cases/s |
| Cases completed | 100,000 of 100,000 |
| Decision accuracy against ground truth | 96.65 % |
| Manual reviews | 91,086 |
| Average review queue wait | 0.054 h |
| Median cycle time | 0.204 h |
| Database afterwards | 4.0 GB |
| Archiving the run's workflow history | 3 min 37 s: 6,740,271 rows into 556 MB of files |
| Full ledger reconciliation afterwards | passed (account opening posts no ledger entries) |

The same run in one process would take about 4.6 hours at the single-process rate.
Throughput was 22.7 cases/s against 25 for the 10,000-case runs: the wall time includes
hiring 5,000 staff, and the tables are ten times larger. It was steady across the run
(38,303 cases after 30 minutes, 77,898 after 60).

## Where the time goes, and what is not optimised

A simulated case costs about 190 SQL statements, most of them single-row inserts and
updates by the workflow engine (every step, event and audit record is written as it
happens). A one-process profile of 300 cases: 4.3 cases/s, 188 statements per case,
roughly half the time waiting on PostgreSQL and half in the ORM. Parallel shards hide
this latency rather than remove it; batching the engine's writes (for example, events
inserted after each step rather than flushed one by one) is the next lever, and it needs
care because some flushes order foreign-key inserts.

## Workflow variants at scale (Phase 19)

`TPL-SCALE-STATEMENT` (the paper-statement template with ids 3000–9999), generated with the
CLI on the Phase 17 demo database: 5 countries × 3 products × 2 approving permissions ×
screening on/off × N fees.

| Step | Variants | Result | Time |
| --- | ---: | --- | ---: |
| First grid (1 fee) | 60 | 60 created | 0.6 s |
| Second grid (9 fees) | 540 | 480 created, 60 unchanged | 5.4 s |
| Full grid (84 fees) | 5,040 | 4,500 created, 540 unchanged | 52.5 s |
| Same grid, dry run | 5,040 | 5,040 unchanged | 33.4 s |

Each variant is rendered, fully validated (graph, handlers, paths, permissions, approvals,
versions) and imported: about 86 per second. Afterwards: 5,056 registered workflows (4 in
code), 17 MB of definitions.

| Request with 5,056 workflows | Before | After |
| --- | ---: | ---: |
| `GET /workflows` (all, 2.5 MB) | — | 0.31–0.42 s |
| `GET /workflows?limit=200` (what the catalogue asks for) | — | 0.27 s |
| `GET /workflows/WF-5000` | 0.27 s | 0.012–0.017 s |
| `GET /analytics/overview` | 2.6 s | 0.05–0.13 s |

The catalogue summarises stored definitions in SQL from their JSON rather than loading and
parsing each; the two "before" figures were found by this measurement and fixed (a
definition's detail built the whole catalogue; the dashboard loaded every stored definition
to count them).

## Generated workflow tests (Phase 20)

`python -m app.cli workflows test`, one process, development container:

| Set | Workflows | Cases | Failed | Time |
| --- | ---: | ---: | ---: | ---: |
| Freshly seeded bank (`--all`, as in CI) | 12 | 288 | 0 | 37.6 s |
| `TPL-SCALE-STATEMENT --sample 100` | 100 | ≈ 2,200 | 0 | 296 s |

Each case is a full engine execution with synthetic records, rolled back: roughly 100–150 ms
per case, 2–4 s per workflow.

## The Milestone B exit run (Phase 22)

Generated tests for every active stored workflow in the scale database of Phase 19 (5,056
registered: 4 in code, 5,052 stored — the examples and the variants of the paper-statement
and scale templates), `python -m app.cli workflows test --all [--sample N] --processes 4`,
development container, one PostgreSQL:

| Workflows | Cases | Failed | Time | Per workflow |
| ---: | ---: | ---: | ---: | ---: |
| 50 | 1,124 | 0 | 54.7 s | 1.09 s |
| 500 | 11,024 | 0 | 604.6 s | 1.21 s |
| 5,052 (all) | 111,168 | 0 | 5,381.6 s (1 h 30 min) | 1.07 s |

Every workflow reached 100 % step and route coverage with no skipped case. A single
workflow's tests took 3.4 s at the median, 7.0 s at p95 and 15.5 s at most (in one worker);
four workers bring the wall time per workflow to about 1.1 s, against 2–4 s in one process
(Phase 20). Time grows linearly with the number of workflows: nothing in the runner or the
database slows as tested versions accumulate (each run is kept in `workflow_test_runs`).

**Catalogue search** over the same 5,056 workflows (`GET /workflow-catalogue`, with all
seven facets counted) takes 0.32–0.37 s whatever the filters: the summaries are built from
one SQL query and filtered and counted in memory.

