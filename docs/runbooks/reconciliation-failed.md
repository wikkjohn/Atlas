# Runbook: A ledger reconciliation reports a failed check

**Severity when it happens:** Critical

## Symptoms
- `GET /api/v1/ledger/reconciliations` lists a run with `ok: false`.
- A `ledger.reconcile` job fails. The schedules run a full reconciliation daily
  (`ledger-full-reconciliation`) and an incremental one every 15 minutes
  (`ledger-incremental-reconciliation`).

## Checks
1. Open the run, `GET /api/v1/ledger/reconciliations/{run_id}`, and read which checks
   failed: entry balance, line currencies, trial balance, stored balances, reversal links,
   account links. The failures are listed with their entry numbers.
2. If it was an incremental run, run a full one: `POST /api/v1/ledger/reconciliation`
   (mode `full`). It compares every account's stored totals with its lines.
3. Find what posted the entries named. Each entry carries its idempotency key, and the
   audit log has the request's correlation id.

## Actions
- **Do not edit ledger rows.** The database forbids it, and corrections are reversing
  entries ([ADR 0004](../adr/0004-the-ledger-is-the-only-writer-of-money.md)).
- **Stored balance differs from its lines:** a stored-balance defect. The lines are the
  truth. Report it as a bug with the account and the run; do not post to "fix" the number.
- **Entry unbalanced or mixing currencies:** this should be impossible, since the database
  refuses such entries. Treat it as a critical defect and stop the module that posted it.
- **If the books cannot be trusted:** restore from the last backup whose drill passed
  ([restore-from-backup.md](restore-from-backup.md)).

## Verify
A new full run reports `ok: true`.

## Escalation
If the actions do not restore service, or data may be lost or altered, open an incident.
Record the correlation ids, the run or archive numbers and the times, and stop changes to
the affected area until it is understood.
