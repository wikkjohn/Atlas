# Data retention, the audit-log archive and rate limits

Phase 85 (roadmap Milestone H, step 2). The bank is synthetic, but the platform keeps its
records as a bank would: each kind of record has a purpose, a period and an action after
it. Old audit events move to an archive that can be verified, and requests are rate
limited.

## The retention schedule

The schedule is code (`app/modules/retention/service.py`) and is versioned with the
platform. The `retention-apply` schedule applies it daily, or *Apply the retention
schedule* on System Settings applies it on demand (`retention:apply`).
`GET /api/v1/data-retention` reports, per class, how many rows exist and how many are past
their period.

| Records | Kept | Then | Applied by |
| --- | --- | --- | --- |
| Sign-in sessions (`auth_sessions`) | 90 days after the session ended | Delete | Retention run |
| Single sign-on requests (`sso_requests`) | 1 day | Delete | Retention run |
| Rate-limit counters (`rate_limit_counters`) | 1 day | Delete | Retention run |
| Idempotency keys (`idempotency_keys`) | 30 days | Delete | Retention run |
| Audit log (`audit_events`) | 1 year online | Archive (kept) | Retention run, through the audit-log archive |
| Simulation workflow history | 30 days | Archive (kept, restorable) | The `simulation.archive_old_history` job (Phase 15) |
| Background jobs (`jobs`) | 180 days after finishing | Review | A person: they hold results and errors |
| AI tool calls and stored prompts (`ai_tool_invocations`) | 1 year | Review | A person: they are the evidence behind experiments |
| Customers | At least 10 years after the relationship ends | Keep | Never removed by the platform |
| Accounts and the ledger | At least 10 years | Keep | Never removed by the platform |

Each run is recorded in `retention_runs` with what it removed. It is also audited as
`retention.applied`.

**Review of the schedule (Phase 85).**
- **Deleted classes.** Sessions, sign-on requests, rate-limit counters and idempotency keys
  are deleted: they exist to operate the platform, and once their period passes they serve
  no purpose.
- **The audit log is never deleted.** It leaves the database only into the archive.
- **Financial records are never removed.** The ten-year periods follow common banking and
  accounting practice; a real bank's periods come from its regulators and its legal
  counsel.
- **Jobs and AI calls are reported, not removed.** They are evidence, so a person decides.

## The audit-log archive

Audit events stay online for at least `ATLAS_AUDIT_MIN_ONLINE_DAYS` (90). The retention run
archives those older than a year. An administrator can archive sooner (`audit:archive`;
`POST /api/v1/audit-archives {older_than_days}`, or *Archive* on the Audit Center), but
never inside the minimum.

**Archiving:**
1. The events before the cut-off are written in timestamp order to a compressed
   JSON-lines file in `ATLAS_AUDIT_ARCHIVE_DIR` (`audit-NNNNNN-….jsonl.gz`), one event per
   line with every column.
2. The file is read back. Its lines must equal the events, and its SHA-256 digest is
   recorded.
3. The events are deleted, in the same transaction.
   - The append-only trigger allows DELETE only while `atlas.audit_archiving = 'on'`, which
     the archive sets with `SET LOCAL` for that one statement.
   - UPDATE and TRUNCATE remain impossible.
   - Any other DELETE is still refused.
4. `audit_archives` records the period, the event count, the size, the digest, and the
   previous archive's digest. The archives form a chain, so a missing, replaced or altered
   file shows when verified.

**Verifying** (`POST /api/v1/audit-archives/{id}/verify`, *Verify* on the Audit Center;
auditors may) re-reads the file and checks three things:
- the digest and event count against the record;
- that `previous_sha256` is the digest of the archive before it.

The result and its time are stored with the archive and audited.

**Reading archived events** uses the live log's filters: action (exact, or a prefix
`name.*`), entity type and entity id
(`GET /api/v1/audit-archives/{id}/events`, *Search* on the Audit Center).

## Rate limits and the sign-in lockout

Limits are counted in PostgreSQL (`rate_limit_counters`, fixed windows), so every API
process shares them. A refused request answers **429** with `Retry-After`.

| Rule | Per | Limit |
| --- | --- | --- |
| `login.user` | username | 10 password sign-ins a 15 minutes |
| `login.ip` | client address | 100 password sign-ins a 15 minutes |
| `mfa.ip` | client address | 30 second-factor attempts a 15 minutes |
| `sso.ip` | client address | 60 single sign-on steps a 15 minutes |
| `writes.user` | user | 600 changes (POST, PUT, PATCH, DELETE) a minute |

- `ATLAS_RATE_LIMITS_ENABLED=false` turns the limits off.
- `ATLAS_RATE_LIMIT_OVERRIDES` (JSON, rule → limit) replaces a limit. The end-to-end suite
  raises the two sign-in limits, because it signs the demo users in many times from one
  address.

**Lockout:**
- `ATLAS_LOGIN_LOCKOUT_ATTEMPTS` (5) wrong passwords in a row lock the account for
  `ATLAS_LOGIN_LOCKOUT_MINUTES` (15). While it is locked, even the right password is
  refused, and the message says so.
- A successful sign-in resets the count.
- An administrator can unlock sooner (`POST /api/v1/users/{id}/unlock`, *Unlock* on System
  Settings → Users).
- Locks, failed attempts (with their reason) and unlocks are audited.

## Limitations

- **The archive lives on local disk** (`backend/var/audit-archive`, ignored by git), like
  the simulation archive. A real deployment would write it to WORM object storage and keep
  the digests elsewhere too.
- **The audit trigger's opening is a setting, not a role.** A database user who can set
  `atlas.audit_archiving` can delete audit events. Production would give archiving its own
  database role.
- **Sign-in limits count by client address,** which is the proxy's address behind a reverse
  proxy that does not forward the client's.
- **The lockout can be used to lock someone out** by guessing wrong on purpose. The
  per-address limit slows that down but does not prevent it.
- **Retention never reaches beyond the database:** backups and archive files keep their
  own copies.
