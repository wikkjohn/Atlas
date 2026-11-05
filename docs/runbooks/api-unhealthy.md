# Runbook: The API is unhealthy or unreachable

**Severity when it happens:** High

## Symptoms
- `GET /api/health` answers 503: a critical dependency (the database) is down.
- `GET /api/health` answers 200 with `redis` *unavailable*: the API is **degraded**, not down.
  Redis is a cache only ([ADR 0002](../adr/0002-postgresql-is-the-system-of-record.md)).
- The web app shows *Backend unavailable* (network failure, or a proxy answering 502/503/504).

## Checks
1. `GET /api/health`: see which component is unavailable, and its error.
2. `GET /api/system/status`: if `needs_migration` is true, the code is newer than the
   schema.
3. Check that PostgreSQL accepts connections: `pg_isready -h <host>`.
4. Read the API's JSON logs. Every error line carries a `correlation_id`; the same id is in
   the error body the client saw.

## Actions
- **Database down:** restart PostgreSQL. If the data is lost or corrupt, follow
  [restore-from-backup.md](restore-from-backup.md).
- **Needs migration:** run `make migrate` (`alembic upgrade head`) before starting the API.
  Never run new code against an old schema.
- **Redis down:** nothing is lost. Restart it when convenient; the API keeps serving.
- **API process down:** restart it. Requests are one transaction each, so an interrupted
  request leaves nothing half-written.

## Verify
`GET /api/health` answers 200 with every critical component `ok`, and
`GET /api/system/status` reports the migrations up to date.

## Escalation
If the actions do not restore service, or data may be lost or altered, open an incident.
Record the correlation ids, the run or archive numbers and the times, and stop changes to
the affected area until it is understood.
