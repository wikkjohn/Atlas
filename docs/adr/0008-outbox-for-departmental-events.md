# ADR 0008: Departments react to each other through a durable outbox

- **Status:** Accepted
- **Decided in:** Phases 10, 74

## Context
Departments depend on each other's events. A loan in arrears opens a collections case; a
hire changes reviewer capacity. Direct imports would couple every module to every other,
and in-process callbacks are lost if a process stops.

## Decision
- **Recorded with the change.** A department publishes an event in the same transaction
  as the change it reports (`backend/app/modules/events/outbox.py`). Each subscribing
  department gets its own delivery row in that transaction.
- **Delivered at least once:**
  - first inline, in a savepoint, right after publishing;
  - otherwise by the `events.dispatch` job every minute, which claims due deliveries with
    `FOR UPDATE SKIP LOCKED` and retries with exponential back-off.
- **Dead deliveries.** After the maximum number of attempts a delivery is *dead* and waits
  for an operator.
- **Listeners for side effects.** Earlier code used listeners, not imports (servicing's
  `on_arrears_change`, Phase 10). The outbox generalises this across departments.

## Consequences
- **Benefits:**
  - A department's reaction cannot be lost by a crash between the change and the reaction.
  - Modules do not import each other's internals.
- **Costs:**
  - Delivery is asynchronous and at least once, so subscribers must be idempotent.
  - A failed delivery waits in the outbox until retried. Operators retry it with
    `POST /api/v1/events/deliveries/{delivery_id}/retry`.
- **Superseded parts.** The early in-process event dispatcher that older documentation
  placed in the core package no longer exists; the outbox replaced it.

## Evidence
- `backend/app/modules/events/outbox.py`
- `backend/tests/test_event_outbox.py`
- `docs/events.md`
