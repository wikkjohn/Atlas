# Runbook: Simulation history is filling the database

**Severity when it happens:** Low

## Symptoms
- The database grows quickly after large simulation runs.
- Queries on the workflow tables slow down. `GET /api/v1/observability/slow-queries` lists
  them.

## Checks
1. `python -m app.cli simulation-history status`: storage used by workflow history, and
   recent archives.
2. Only simulation history is lifecycle-managed. The live bank's history, the ledger and
   customers are never removed this way.

## Actions
- **Archive old runs:** `python -m app.cli simulation-history archive --older-than-days 30`.
  Their history moves to checksummed files in `ATLAS_SIMULATION_ARCHIVE_DIR`; results and
  outcomes stay.
- **Archive one run:** `python -m app.cli simulation-history archive --run <number>`.
  Restore it with `python -m app.cli simulation-history restore --run <number>`.
- **Clear everything simulated:**
  `python -m app.cli simulation-history reset --archive --yes`. The partitions are
  dropped, after archiving every run.
- **Take a backup first** if the archives matter: the backup carries the archive
  directory.

## Verify
`simulation-history status` shows the storage reduced, and the slow queries stop.

## Escalation
If the actions do not restore service, or data may be lost or altered, open an incident.
Record the correlation ids, the run or archive numbers and the times, and stop changes to
the affected area until it is understood.
