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
| Platform core | `app/core/` | Database engine and sessions, logging, correlation IDs, error envelope and domain errors, DI aliases, pagination, password hashing and tokens, the permission model, the audit log, idempotency, money units |
| Modules | `app/modules/<name>/` | Bounded business capabilities, each with models, schemas, a service layer and a router |
| API | `app/api/` | Routing; platform endpoints under `/api`, business endpoints under `/api/v1` |
| Simulation | `app/simulation/` | Clock, scenarios, generators, run engine (Phase 5) |

### Module conventions

Each module package contains:

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

Modules implemented so far: `identity` (users, roles, auth), `countries`, `organizations`,
`employees`, `audit` (read API over `app/core/audit.py`). `app/models.py` imports every
module's models so Alembic and tests see the complete schema.

## Cross-cutting behaviour

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
- **Domain errors:** services raise `NotFoundError`, `ConflictError`,
  `BusinessRuleViolation`, `AuthenticationError` or `PermissionDeniedError`; one handler
  renders them in the error envelope. Routers contain no business rules.
- **Authentication (Phase 2):** username/password → short-lived HS256 JWT (PyJWT).
  Passwords are hashed with salted scrypt. Each request re-loads the user, so deactivation
  and role changes apply to existing tokens immediately. Unknown usernames are verified
  against a dummy hash so timing does not reveal which accounts exist.
- **Authorization (Phase 2):** `app/core/permissions.py` maps each of the eight roles to a
  set of permissions; it is versioned with the code and the `roles` table holds role
  identity. Routers declare `Authorized(Permission.X)`; there is no unauthenticated path to
  business data (a test sweeps every `/api/v1` route). Field-level rules live in services
  (e.g. compensation is omitted without `employees:read_compensation`).
- **Audit (Phase 2):** `record_audit_event` writes in the same transaction as the change,
  with actor, correlation ID and redacted metadata (passwords and compensation values are
  never stored). Database triggers reject UPDATE, DELETE and TRUNCATE on `audit_events`.
  Failed logins are committed before the 401 is raised so the record survives the rollback.
- **Idempotency (Phase 2):** `run_idempotent` claims `(user, Idempotency-Key)` with an
  `INSERT … ON CONFLICT DO NOTHING` inside the request transaction; concurrent duplicates
  block on the key and then replay the stored response.
- **Country configuration (Phase 2):** a country's operational status gates creating
  subsidiaries, units and staff in it; its region constrains which headquarters it can sit
  under; its currency becomes the compensation currency of staff placed there.
- **Migrations:** schema changes are Alembic migrations only. `/api/system/status` compares
  the database's revision with the code's head revision and reports `needs_migration`.
  A test fails if models and migrations drift apart.

## Frontend

- `src/app/`: application root, routes, navigation definition
- `src/components/`: shared UI primitives (panels, status pills, app shell)
- `src/features/<area>/`: one folder per screen area (dashboard, workflows, ai-lab, …)
- `src/services/`: the API client and TanStack Query hooks; the only code that talks HTTP
- `src/types/`: TypeScript mirrors of backend response models

Authentication state lives in `src/app/auth.tsx`: the token is kept in memory and in
`sessionStorage` (cleared when the tab closes), re-validated with `/auth/me` on load, and
dropped on any 401 or at expiry; the query cache is cleared on sign-out so one user's data
never shows for the next. An API outage does not sign the user out. Navigation hides
screens the role cannot use; the backend remains the enforcement point.

The API client separates *backend unreachable* (network failure or proxy 502/503/504) from
*backend answered with an error* (`ApiError` carrying the envelope), so screens can show the
right failure state. Navigation entries for unbuilt screens are visibly disabled and
labelled with the phase that delivers them, never linked to placeholder pages.

## Planned design for later phases

- **Events (Phase 4):** an in-process event dispatcher in `app/core/events.py` for
  cross-module side effects, introduced with the workflow engine that first needs it.
- **Scoped access (later):** Phase 2 permissions are role-wide. Restricting a regional
  executive or department manager to *their* part of the hierarchy is a planned refinement.
- **Ledger (Phase 3):** integer minor units, balanced-per-currency journal entries, an
  idempotency key unique constraint, balances derived from posted lines.
- **Workflow engine (Phase 4):** see [workflows.md](workflows.md).
- **Simulation (Phase 5):** seeded generators (`random.Random(seed)`, never global random)
  with every run's scenario version, seed, configuration and software version stored. The
  first generator (synthetic names, `app/simulation/generators.py`) already drives the
  Phase 2 demo seed.
- **AI lab and benchmarking (Phases 6–7):** see [ai-testing.md](ai-testing.md).

## Explicit non-goals for now

No Kubernetes, microservices, service mesh or managed cloud infrastructure. The platform
must run on one machine with `docker compose up`.
