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
