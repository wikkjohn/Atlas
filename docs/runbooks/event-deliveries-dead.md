# Runbook: Event deliveries are dead or falling behind

**Severity when it happens:** Medium

## Symptoms
- `GET /api/v1/events/summary` shows dead deliveries, or a growing lag for a subscriber.
- A department did not react to another's event: a hire not reflected in capacity, an
  arrears case not opened.

## Checks
1. `GET /api/v1/events?status=dead`: which subscriber, which topic, and the error
   recorded on the delivery.
2. Check that the `events.dispatch` schedule is enabled (`GET /api/v1/job-schedules`) and
   that a worker runs ([background-jobs-stalled.md](background-jobs-stalled.md)).

## Actions
- **Fix the subscriber's cause first.** A delivery retries with back-off and is dead after
  its last attempt.
- **Then retry** each dead delivery: `POST /api/v1/events/deliveries/{delivery_id}/retry`.
  Subscribers are idempotent, so a delivery that partly ran before is safe to repeat
  ([ADR 0008](../adr/0008-outbox-for-departmental-events.md)).
- The publisher's change always stands; nothing needs re-publishing.

## Verify
The summary shows no dead deliveries for that subscriber, and the expected effect exists.

## Escalation
If the actions do not restore service, or data may be lost or altered, open an incident.
Record the correlation ids, the run or archive numbers and the times, and stop changes to
the affected area until it is understood.
