# Runbook: Background jobs are stalled or failing

**Severity when it happens:** Medium

## Symptoms
- Queue depth or lag keeps growing on the Observability page
  (`GET /api/v1/observability/overview`).
- Scheduled work stops: workflow timers do not fire, reconciliation runs stop appearing,
  the daily retention run is missing.
- Jobs reach `failed` after their retries.

## Checks
1. `GET /api/v1/observability/overview`: workers alive (they report every 5 seconds),
   queue depth, lag and throughput per kind.
2. `GET /api/v1/jobs?status=failed`: which kind fails, and the error recorded on the job.
3. `GET /api/v1/job-schedules`: is the schedule enabled, and when is it next due?
4. Check the setting: with `ATLAS_JOBS_EXECUTION=worker`, jobs run only if a worker runs
   (`python -m app.cli worker`, the `worker` service in Docker Compose).

## Actions
- **No worker alive:** start one. Jobs whose worker stopped heart-beating for five
  minutes are taken back automatically (`recover_stale`) and run again.
- **One kind failing:** fix the cause shown in its error, then queue it again with
  `POST /api/v1/job-schedules/{name}/run` (scheduled kinds) or `POST /api/v1/jobs`
  (manual kinds). A stuck job is stopped with `POST /api/v1/jobs/{job_id}/cancel`.
- **Lag but healthy workers:** add worker processes
  (`python -m app.cli worker --processes N`). Jobs are claimed with `SKIP LOCKED`, so
  workers share the queue safely.

## Verify
Queue depth falls back to its usual level, and the failed kind's next run succeeds.

## Escalation
If the actions do not restore service, or data may be lost or altered, open an incident.
Record the correlation ids, the run or archive numbers and the times, and stop changes to
the affected area until it is understood.
