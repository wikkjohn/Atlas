# Runbook: Restore the bank from a backup

**Severity when it happens:** Critical

## Symptoms
- The database is lost or corrupt, or data was destroyed and must be recovered to the last
  backup.
- A recovery drill is due: weekly, and after a migration that changes many tables.

## Checks
1. Find the latest good backup: `GET /api/v1/backups` (`latest_backup`, and
   `recovery_point_age_s`), or the newest `atlas-backup-*` directory.
2. Verify it without restoring: `python -m app.cli backup verify <dir>`. It must report
   `ok: true`.
3. Decide the target: a new, empty database. Keep the damaged one for investigation; do
   not restore over it unless it is unusable.

## Actions
1. Stop the API and the workers, so nothing writes during the restore.
2. Restore:
   `python -m app.cli backup restore <dir> --target <database URL> --files-root <var dir>`.
   - Add `--jobs 4` on a large database. It is faster, but not in one transaction.
   - The restore refuses a non-empty target or files directory. Use `--force` only to
     replace one deliberately.
3. All five checks must pass: schema revision, row counts, ledger balances, newest audit
   event, audit archive chain. If one fails, do not go live; see the escalation below.
4. If the code is newer than the backup, run `make migrate` against the restored database.
5. Point the API and workers at it (`ATLAS_DATABASE_URL`), and the archive settings at the
   restored directories (`ATLAS_AUDIT_ARCHIVE_DIR`, `ATLAS_SIMULATION_ARCHIVE_DIR`).
   Then start them.
6. Run a full reconciliation: `POST /api/v1/ledger/reconciliation`.

The details, and the times measured, are in [backup-recovery.md](../backup-recovery.md).

## Verify
`GET /api/health` is ok, and the reconciliation reports every check passed. The data
committed after the backup's `snapshot_at` is lost; record that in the incident.

## Escalation
If the actions do not restore service, or data may be lost or altered, open an incident.
Record the correlation ids, the run or archive numbers and the times, and stop changes to
the affected area until it is understood.
