# The event pipeline

Phase 74 (roadmap Milestone F, step 6). Departments integrate through events, not imports.
One department's change can start another department's work without either importing the
other, and without the second department's failure undoing the first's change.

## How it works

`app/modules/events/outbox.py`, tables `domain_events` and `event_deliveries`
(migration 0049).

1. **Publish.** A department calls `outbox.publish(db, topic, key, payload, publisher=...)`
   in the same transaction as the change it reports. The event and one *delivery* per
   subscriber of the topic are written with that change: they exist exactly when it does.
2. **Deliver inline.** Right after publishing, each delivery runs in its own savepoint:
   - success marks it delivered;
   - a failure rolls back only that subscriber's work, records the error and schedules a
     retry.

   The publisher's change always stands.
3. **Dispatch.** The `events.dispatch` job runs every minute (schedule `events-dispatch`;
   also `python -m app.cli events dispatch`).
   - It claims due deliveries 100 at a time with `FOR UPDATE SKIP LOCKED`, so several
     workers share the backlog without taking the same row.
   - Each delivery runs in its own savepoint, and a batch commits together.
   - Retries back off exponentially: 30 s, 1 min, 2 min … After 8 attempts a delivery is
     **dead** until someone retries it (API or Settings).

A subscriber is a function `(db, event)` registered with
`@subscribe(topic, name, department=...)` in the subscribing department. Its changes commit
with its delivery's status, so a delivery takes effect once. Subscribers must still be
idempotent: a worker that dies mid-batch leaves the batch to be delivered again.

## The dependencies on it

| Topic | Published by | Subscriber | What it does |
| --- | --- | --- | --- |
| `lending.arrears_changed` | lending servicing: the daily run, arrears repayment, payoff | `collections.sync` (collections) | Opens, escalates or cures the WF-0004 collections case |
| `hr.employee_hired` | HR, on a hire | `information_security.request_access` | Requests the joiner's systems access (an access grant for their role) |
| `access.granted` | Information Security, on granting access | `hr.complete_it_access` | Closes the joiner's "Systems access granted" onboarding task |
| `hr.employee_left` | Employees, on termination | `information_security.revoke_access` | Revokes every live grant of the leaver |

Before Phase 74, lending called collections through an in-process listener list. A failing
collections step broke the servicing run, and nothing recorded what collections had been
told. Lending now publishes only loans in arrears, and each loan's return to current, so
loans that stay current produce no events.

**Information Security's access grants** (`app/modules/access`, table `access_grants`)
belong to this phase:
- A grant is `requested` when HR hires someone; the profile follows the employee's role.
- An administrator grants it (`users:manage`), which publishes `access.granted`.
- It is `revoked` when the employee leaves.
- A grant records the event that asked for it, so a redelivery cannot ask twice.

HR's hire and Information Security's grant never call each other.

## API, CLI and pages

| Where | What |
| --- | --- |
| `GET /api/v1/events?topic=&status=` | `jobs:read`: recent events with their deliveries |
| `GET /api/v1/events/summary` | `jobs:read`: deliveries by subscriber and status; waiting, dead; oldest waiting |
| `POST /api/v1/events/deliveries/{id}/retry` | `jobs:manage`: make a failed or dead delivery due now |
| `GET /api/v1/access/grants?status=` and `/grants/summary` | `employees:read` |
| `POST /api/v1/access/grants/{id}/grant` | `users:manage`: grant requested access |
| `python -m app.cli events dispatch|summary` | Deliver due events now; show the pipeline |
| Settings | *Event pipeline*: subscribers and their deliveries, undelivered events, Retry |
| Employees | *Systems access*: requested, granted and revoked grants; Grant access |

## Measured

On the development container (a scratch database): 20,000 events on one topic, published
without inline delivery, then delivered by the dispatcher. The subscriber wrote one row per
call, to count how many times each event was handled.

| Run | Result |
| --- | --- |
| Publishing (an event and its delivery, in batches of 2,000 a transaction) | about 600 events a second |
| Dispatching, 1 worker | 56.7 s, 353 deliveries a second |
| Dispatching, 4 workers at once (separate processes) | 12.1 s, 1,656 a second; exactly 5,000 each |
| Exactly once | 20,000 handler calls for 20,000 events, every one on its first attempt, all `delivered` |

The first dispatcher claimed and committed one delivery at a time: 152 deliveries a
second with 1 worker, 401 with 4. Claiming batches of 100 under `SKIP LOCKED`, with a
savepoint per delivery, made it 2.3 times faster with 1 worker and 4.1 times with 4.

## Known limitations

- **In one database:** the outbox is for this modular monolith; it does not publish to an
  external broker.
- **No ordering guarantee between deliveries:** a retried event can be delivered after a
  later one. The current subscribers either read the latest state (collections reloads the
  loan) or are order-free.
- **Simulations do not publish:** the simulated servicing path, `service_loan`, never
  notified listeners, and still does not.
- **Delivered events are kept:** there is no retention or archive for `domain_events` yet.
