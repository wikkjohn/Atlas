# ADR 0012: Logical backups from one snapshot, checked against a manifest

- **Status:** Accepted
- **Decided in:** Phases 87, 88

## Context
The platform needs a recovery procedure that is tested, not assumed. State lives in
PostgreSQL and in two archive directories: audit-log archives and simulation-history
archives.

## Decision
- **A backup has three parts:**
  - `pg_dump` in custom format, taken from an exported repeatable-read snapshot;
  - the archive files;
  - a manifest, read in the same snapshot. It records the schema revision, the row counts
    of key tables, the ledger totals, the newest audit event, the archive chain head, and
    each file's digest.
- **Five checks on restore.** Every restore is compared with the manifest: revision, row
  counts, ledger balance, newest audit event and the archive chain.
- **A timed drill.** `python -m app.cli backup drill` runs the whole procedure against a
  scratch database and records its RTO and RPO.
- **Archive files cannot vanish mid-backup.** An advisory lock (`app/core/locks.py`) keeps
  any archive file the snapshot still refers to from being deleted until the files are
  packed (PR #78 review).

## Consequences
- **Benefits:**
  - A backup is proved by restoring it.
  - A 1.2 GB database was restored and checked in 19–39 s, depending on the parallel jobs.
- **Costs:**
  - No point-in-time recovery: the recovery point is the last backup.
  - Backups are not encrypted, and nothing schedules them; the runbook gives the schedule.
  - A logical restore rebuilds every index.

## Evidence
- `docs/backup-recovery.md`
- `backend/app/modules/backup/service.py`
- `backend/tests/test_backup_recovery.py`
