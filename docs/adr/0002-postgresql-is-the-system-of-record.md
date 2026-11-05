# ADR 0002: PostgreSQL is the only system of record; Redis is optional

- **Status:** Accepted
- **Decided in:** Phases 1, 14

## Context
The bank needs durable state for:
- customers, accounts and the ledger;
- workflow history;
- background jobs;
- rate-limit counters;
- audit archives' records.

Each extra stateful store adds another backup, another failure mode, and transactions that
cannot span both stores.

## Decision
- **PostgreSQL 16 holds every durable state:**
  - The background-job queue (`jobs`), claimed with `SELECT … FOR UPDATE SKIP LOCKED`.
  - The job schedules.
  - The event outbox.
  - Rate-limit counters (`rate_limit_counters`, Phase 85).
  - Sign-in sessions.
- **Redis is optional.** It is a cache only. Its outage makes `/api/health` report
  `degraded`, never unavailable.
- **Work and its job commit together.** A job is queued in the same transaction as the
  work that needs it: a simulation run and its job commit together, or neither does.

## Consequences
- **Benefits:**
  - Recovery covers all durable state: one backup and restore procedure
    ([ADR 0012](0012-logical-backups-checked-against-a-manifest.md)) takes in everything
    but the file archives, and those are packed in the same backup.
  - A job can never refer to work that was rolled back.
- **Costs:**
  - Queue throughput is bounded by the database. Measured in Phases 14 and 16, it is
    adequate for this platform.
  - Polling workers add a small, steady load.

## Evidence
- `backend/app/jobs/engine.py`
- `backend/app/core/ratelimit.py`
- `backend/tests/test_jobs.py`
