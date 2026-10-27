# Architecture

ATLAS Global Bank is a **modular monolith**: one deployable backend, one database and one
web application, divided internally into modules with explicit boundaries. That keeps local
development and transactional correctness simple while leaving a clear path to extract a
module into its own service later.

## System context

```
 Browser ──▶ React SPA (Vite dev server / static build)
                │  same-origin /api/* (proxied in development)
                ▼
          FastAPI application ──────────▶ PostgreSQL 16  (system of record)
           ├─ platform core                 Redis 7      (optional cache / light queues)
           ├─ business modules
           ├─ workflow engine
           ├─ simulation engine
           └─ AI innovation lab ──▶ AI adapters (deterministic local adapter first;
                                    external model providers later, behind one interface)
```

No component connects to real banking infrastructure. All data is generated synthetically.

## Backend layers

| Layer | Location | Responsibility |
| --- | --- | --- |
| Configuration | `app/config.py` | Typed settings from `ATLAS_*` environment variables |
| Platform core | `app/core/` | Database engine and sessions, logging, correlation IDs, error envelope, dependency aliases; later security, permissions, events and audit |
| Modules | `app/modules/<name>/` | Bounded business capabilities, each with models, schemas, a service layer and a router |
| API | `app/api/` | Routing; platform endpoints under `/api`, business endpoints under `/api/v1` |
| Simulation | `app/simulation/` | Clock, scenarios, generators, run engine (Phase 5) |

### Module conventions (from Phase 2)

Each module package will contain:

- `models.py`: SQLAlchemy models registered on the shared `Base`
- `schemas.py`: Pydantic request and response contracts
- `service.py`: the module's public interface; other modules call this, never its tables
- `router.py`: HTTP endpoints that delegate to the service

Cross-module calls go through service interfaces. Cross-module side effects (for example
"account opened" → "post opening ledger entry") go through the shared event dispatcher in
`app/core/events.py`, so a module can later be extracted behind a message bus without
rewriting its callers.

### Shared foundation (one of each)

Every future banking module reuses the same identity and authentication, permissions,
organization structure, country configuration, employee registry, workflow engine, event
dispatcher, database session, audit log, synthetic data generators, AI tool registry,
experiment management and analytics. No module may introduce its own version of these.

## Cross-cutting behaviour implemented in Phase 1

- **Transactions:** `get_db` gives each request one session and one transaction, committed
  on success and rolled back on error. Services do not commit implicitly.
- **Correlation IDs:** `CorrelationIdMiddleware` accepts a safe caller-supplied
  `X-Correlation-ID` or generates a UUID, stores it in a context variable, attaches it to
  every log line and error body, and returns it in the response header. Audit events and
  workflow executions will record the same ID.
- **Structured logging:** JSON lines on stdout (`ATLAS_LOG_FORMAT=json`), including uvicorn's
  own logs; `text` is available for local reading.
- **Error envelope:** HTTP errors, validation errors and unhandled exceptions all return
  `{"error": {code, message, details, correlation_id}}`. Unhandled errors never leak
  internal detail to the client.
- **Dependency injection:** routers depend on typed aliases (`EngineDep`, `SettingsDep`,
  `DbSession`) so tests and future extracted services can override them.
- **Health semantics:** `/api/health` is 503 when a *critical* dependency (the database) is
  down. Redis is non-critical in Phase 1, so an outage reports `degraded` with HTTP 200.
- **Migrations:** schema changes are Alembic migrations only. `/api/system/status` compares
  the database's revision with the code's head revision and reports `needs_migration`.
  A test fails if models and migrations drift apart.

## Frontend

- `src/app/`: application root, routes, navigation definition
- `src/components/`: shared UI primitives (panels, status pills, app shell)
- `src/features/<area>/`: one folder per screen area (dashboard, workflows, ai-lab, …)
- `src/services/`: the API client and TanStack Query hooks; the only code that talks HTTP
- `src/types/`: TypeScript mirrors of backend response models

The API client separates *backend unreachable* (network failure or proxy 502/503/504) from
*backend answered with an error* (`ApiError` carrying the envelope), so screens can show the
right failure state. Navigation entries for unbuilt screens are visibly disabled and
labelled with the phase that delivers them, never linked to placeholder pages.

## Planned design for later phases

- **Identity (Phase 2):** username/password login issuing signed, expiring access tokens;
  roles map to permission sets checked by a FastAPI dependency on every protected route.
- **Audit (Phase 2):** append-only `audit_events` table. The application role gets INSERT
  and SELECT only, enforced by database privileges and a trigger that rejects UPDATE/DELETE.
- **Ledger (Phase 3):** integer minor units, balanced-per-currency journal entries, an
  idempotency key unique constraint, balances derived from posted lines.
- **Workflow engine (Phase 4):** see [workflows.md](workflows.md).
- **Simulation (Phase 5):** seeded generators (`random.Random(seed)`, never global random)
  with every run's scenario version, seed, configuration and software version stored.
- **AI lab and benchmarking (Phases 6–7):** see [ai-testing.md](ai-testing.md).

## Explicit non-goals for now

No Kubernetes, microservices, service mesh or managed cloud infrastructure. The platform
must run on one machine with `docker compose up`.
