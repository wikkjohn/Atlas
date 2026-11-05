# ADR 0005: An append-only audit log, archived in a digest chain

- **Status:** Accepted
- **Decided in:** Phases 2, 85

## Context
Regulators and auditors need to know who changed what, and that the record has not been
edited. Over time the log also grows without bound.

## Decision
- **Same transaction.** `record_audit_event` writes in the same transaction as the change,
  with actor, correlation id and redacted metadata.
- **Append-only, enforced by the database.** A trigger rejects UPDATE, DELETE and TRUNCATE
  on `audit_events`.
- **Archiving (Phase 85).** Events past the minimum online period are moved into
  gzip-compressed JSON-lines files:
  - the file is written and checked first;
  - DELETE is then allowed only inside that transaction, after
    `SET LOCAL atlas.audit_archiving = 'on'`;
  - each archive records the SHA-256 of the archive before it, so a removed, replaced or
    edited file shows when verified.

## Consequences
- **Benefits:**
  - The record cannot be edited by the application.
  - Archived events stay searchable and verifiable.
- **Costs:**
  - Archive files are durable state outside the database. They need a persistent volume
    shared by the API and the workers (PR #76 review), and they are carried in every
    backup.
  - A failed login must be committed before its error is raised, so the record survives
    the request's rollback.

## Evidence
- `backend/app/core/audit.py`
- `backend/app/modules/audit/archive.py`
- `docs/data-retention.md`
