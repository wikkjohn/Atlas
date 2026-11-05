# ADR 0001: A modular monolith on FastAPI and PostgreSQL

- **Status:** Accepted
- **Decided in:** Phase 1

## Context
The platform simulates a whole bank, with dozens of departments, a workflow engine, a
simulation engine and an AI lab. It has to be simple to run on one machine, in CI and with
Docker Compose. Banking changes have to be transactional: an account opening, its ledger
entry and its audit event commit together or not at all.

Microservices and Kubernetes were ruled out from the start. One service per department
would turn every cross-department step into a distributed transaction, and the project
has one maintainer.

## Decision
- **Process:** one backend process (FastAPI), one PostgreSQL database and one React
  single-page app. Background work runs in the same codebase as worker processes
  (`python -m app.cli worker`).
- **Modules:** each business capability lives in `backend/app/modules/<name>/`, with
  `models.py`, `schemas.py`, `service.py` and `router.py`.
- **Boundaries:** other modules call a module's service and never its tables.
- **Transactions:** a request has exactly one database transaction, opened and committed
  by `get_db` in `backend/app/core/database.py`.

## Consequences
- **Benefits:**
  - Atomic changes across modules, with no distributed transactions.
  - One test database and one CI pipeline.
  - `docker compose up` runs the whole bank.
- **Costs:**
  - Scaling means more API and worker processes against one database, not independent
    services.
  - The service boundary is a convention. Code review and the module layout enforce it;
    the compiler does not.
- **Room to grow:** cross-module side effects already go through the outbox
  ([ADR 0008](0008-outbox-for-departmental-events.md)), so a module could be extracted
  behind a message bus later without rewriting its callers.

## Evidence
- `docs/architecture.md` (system context, module conventions)
- `backend/app/core/database.py`
- `docker-compose.yml`
