# Runbook: An audit archive fails verification

**Severity when it happens:** High

## Symptoms
- `POST /api/v1/audit-archives/{archive_id}/verify` reports `ok: false`. Possible problems:
  - the file is missing;
  - the file cannot be read;
  - its digest or event count differs from the record;
  - the chain is broken.
- A restore's *Audit archive chain* check fails.

## Checks
1. Note which archive and which problem, from the verification's `problems`.
2. Check that the archive directory is the one the API and workers share
   (`ATLAS_AUDIT_ARCHIVE_DIR`, the persistent `audit-archive` volume in Docker Compose).
3. Verify the archives on either side of it. A broken chain names the link that differs.

## Actions
- **File missing or unreadable:** recover it from the latest backup, whose
  `files.tar.gz` holds every archive file. Extract only that file into the directory, then
  verify again.
- **Digest differs:** the file was changed after it was written. Keep the changed file for
  investigation and restore the original from a backup. Treat it as a security incident:
  the audit log is evidence.
- **Never "repair" the record to match a file.** The record and the chain are what make
  tampering visible.

## Verify
Verification of that archive, and of the one after it, reports `ok: true`.

## Escalation
If the actions do not restore service, or data may be lost or altered, open an incident.
Record the correlation ids, the run or archive numbers and the times, and stop changes to
the affected area until it is understood.
