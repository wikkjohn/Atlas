# Backup, restore and the recovery drill

Phase 87 (roadmap Milestone H, step 4). The bank is synthetic. The procedure is the one a real
deployment of this platform would follow; the numbers below were measured on this
repository's development databases.

## What a backup is

`python -m app.cli backup create --output DIR` writes a new directory
`DIR/atlas-backup-<UTC time>/` holding three files:

| File | What it holds |
| --- | --- |
| `database.dump` | `pg_dump --format=custom --no-owner --no-privileges` of the whole database |
| `files.tar.gz` | The audit-log archive (`ATLAS_AUDIT_ARCHIVE_DIR`) and the simulation-history archive (`ATLAS_SIMULATION_ARCHIVE_DIR`) |
| `manifest.json` | What a restore must reproduce, and each file's size and SHA-256 |

The manifest records:
- the schema revision (Alembic);
- the row counts of eleven key tables: users, customers, accounts, journal entries and
  lines, audit events and archives, simulation runs, workflow definitions, employees,
  payments;
- the ledger's totals: debits, credits, and how many entries do not balance (must be 0);
- the newest audit event;
- the head of the audit archives' digest chain.

**One consistent moment.** The manifest and the dump see the same data. The backup opens
a read-only repeatable-read transaction, exports its snapshot, reads the manifest's facts
in it, and runs `pg_dump --snapshot` on it. The bank keeps running meanwhile: nothing is
locked beyond what `pg_dump` itself takes (shared locks, which block only schema changes).

**Files after the database.** The archive files are packed after the dump. So every
archive the dump records has its file in the backup. A file whose archiving transaction
failed may be there too, unreferenced; that is harmless.

## Verifying a backup

`python -m app.cli backup verify DIR/atlas-backup-…` checks a backup without restoring it:
- every file is present, with the manifest's size and SHA-256;
- `pg_restore --list` reads the dump's table of contents, and the dump holds table data;
- the files archive opens and holds the number of files the manifest says.

A backup that fails verification is never restored.

## Restoring

```
python -m app.cli backup restore DIR/atlas-backup-… \
    --target postgresql+psycopg://atlas:…@host:5432/atlas_restored \
    --files-root /srv/atlas/var
```

1. The backup is verified.
2. The target must have no tables, or the restore stops. `--force` empties it first
   (`DROP SCHEMA public CASCADE`); use it only on a database you mean to replace.
3. `pg_restore --exit-on-error --no-owner --no-privileges`.
   - By default it runs in a single transaction: a failure leaves the target empty.
   - `--jobs N` restores in parallel instead (not in one transaction); on failure,
     empty the target and run again.
   - Comments on extensions are left out: only a superuser may set them, and they hold
     no data.
4. The archive directories are extracted under `--files-root` (it must be empty unless
   `--force`). The extraction refuses absolute paths, links that leave the directory, and
   devices.
5. The restored database is checked against the manifest. Each check passes or fails with
   its detail:

| Check | Passes when |
| --- | --- |
| Schema revision | The restored revision is the backup's |
| Row counts | All eleven tables have exactly the backup's counts |
| Ledger balances | Debits equal credits, no entry is unbalanced, and both totals are the backup's |
| Newest audit event | The newest audit event is the backup's |
| Audit archive chain | With `--files-root`: each archive's file is present with its recorded digest, and each archive names the previous one's digest |

The command exits 1 if any check fails.

After the restore, point the API and the workers at the restored database, and the archive
settings at the restored directories. If the code is newer than the backup, run
`alembic upgrade head`, as for any deployment.

## The recovery drill

`python -m app.cli backup drill` runs the whole procedure against a scratch database:

1. take a backup of the live database;
2. create the scratch database (`--scratch-database`, default `atlas_drill`);
   - the scratch database must not be the live one;
   - its name must be a plain identifier;
3. restore the backup into it, with the files into a scratch directory;
4. run the checks;
5. drop the scratch database and directory (`--keep` keeps them).

It measures three things:
- **RTO:** the time from the start of the restore to the last check;
- **RPO:** the age of the backup's snapshot when the checks finish. Everything committed
  after the snapshot would be lost;
- the time the backup took.

Every `create`, `verify` and `drill` is recorded in `backup_runs` (migration 0058) and the
audit log (`backup.backup`, `backup.verify`, `backup.drill`). A failed backup or drill is
recorded too, with its error. Restores are not recorded in the database being restored, which the
restore replaces.

The Audit page shows a **Backups and recovery drills** panel to holders of `audit:read`:
- the latest backup;
- the latest passing drill and its RTO;
- the age of the recovery point;
- the recent runs, failures included.

`GET /api/v1/backups` returns the same. The API only reports: backups are taken by the
operator, on a host with the PostgreSQL client tools.

## Measured

Drills run with `python -m app.cli backup drill` on this repository's development server.
It is PostgreSQL 16 on 4 vCPUs, shared with the API's test databases, and every run passed all
five checks.

| Database | Rows in the key tables | Dump | Backup | Restore jobs | Restore (database) | Checks | **RTO** | RPO at the end |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `atlas_ci` (the end-to-end suite's bank, 49 MB) | 9,637 | 3.1 MB | 6.5 s | 1 | 2.1 s | 0.05 s | **2.2 s** | 9 s |
| `atlas_exit` (the Milestone E exit run, 1.2 GB) | 1,320,873 | 166 MB | 20.2 s | 1 | 37.6 s | 1.0 s | **39.2 s** | 59 s |
| `atlas_exit` | 1,320,873 | 166 MB | 20.4 s | 4 | 16.8 s | 1.3 s | **18.8 s** | 41 s |

- `atlas_exit` holds:
  - 571,290 audit events;
  - 211,531 journal entries with 423,063 lines;
  - 36,818 customers and 36,780 accounts;
  - 21,204 employees and 18,334 users;
  - 1,464 simulation runs.
- **Parallel restores pay off on large databases:** with 4 jobs the restore took half the
  time of 1 job. Parallel jobs give up the single-transaction guarantee, so a failed
  restore must be emptied and run again.
- **The restore dominates.** `pg_restore` rebuilds every index; the checks take about a
  second.
- **An earlier run under heavier load took longer:** a 59 s backup and a 54 s single-job
  restore. Expect the times to vary with the server's load.
- **A bug the drill found:** cleanup used `DROP DATABASE … WITH (FORCE)`.
  - After a large restore, autovacuum works on the new database as the superuser, and a
    non-superuser may not terminate it. The drop failed, and its error hid the drill's
    result.
  - The drill now drops with a plain `DROP DATABASE`: PostgreSQL stops autovacuum itself.
    FORCE is kept only for sessions left open.
  - A cleanup failure is reported as `cleanup_problem` and no longer hides the result.

## Schedule and retention (recommended)

The platform does not schedule backups itself: they need the PostgreSQL client tools
and storage outside the database host. A real deployment would:
- take a backup nightly, from cron or the platform's scheduler (`backup create`);
- verify it right away (`backup verify`);
- copy it off the host;
- run the drill weekly, and after every migration that changes many tables;
- keep 14 nightly backups and 12 monthly ones;
- alert when the Backups panel's recovery point is older than 26 hours.

**Achievable objectives with this procedure:**
- **RPO:** up to 24 hours with nightly backups. Closer needs continuous WAL archiving
  (point-in-time recovery), which is not part of this phase.
- **RTO:** the measured restore time above, plus the time to repoint the services.

## Limitations

- **No point-in-time recovery.** The recovery point is the last backup. WAL archiving
  (for example with pgBackRest or WAL-G) would bring it to seconds.
- **Backups are not encrypted** and stay on the host that took them. A real deployment
  would encrypt them and copy them off site.
- **Logical, not physical.** `pg_dump` and `pg_restore` rebuild the indexes on restore, so
  the restore time grows with the data. For large databases a physical base backup restores
  faster.
- **Redis is not backed up.** It holds only caches and transient queues; the job queue's
  record of truth is in PostgreSQL.
- **The drill restores onto the same server.** It proves the backup and the procedure, not
  a second site.
