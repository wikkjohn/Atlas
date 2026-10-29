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
right failure state. Feature screens are loaded on first visit (`React.lazy` per route), so
the initial bundle stays small. Every navigation entry links to a working screen; synthetic
data and simulation estimates are labelled where they appear.

Screens: Enterprise Overview (analytics), Organization, Countries, Employees, Customers,
Accounts, Workflow Explorer, Simulation Center, AI Innovation Lab, Experiments,
Benchmarking, Audit Center and System Settings (platform health, build, database,
modules, users, roles and permissions).

## Banking core (Phase 3)

**Account opening is approval-gated.** `accounts.service.approve_request` is the only code
path that creates an `Account`; no endpoint creates one directly. Approval requires a
pending request, an approver holding `accounts:approve` who is not the requester (also a
database CHECK), a compliance reviewer for high-risk customers, and eligibility re-checked
at that moment. The request row is locked during approval and records the account it
opened, so one request yields exactly one account. Phase 4's WF-0001 workflow will drive
these same service calls rather than duplicating the rules.

**Account metadata and balances are separate.** `accounts` holds number, type, currency
and status; each account points at its own liability ledger account (`2100-<number>`).
Balances come from posted journal lines. Since Phase 12 their running totals are stored in
`ledger_balances`, maintained by a database trigger on every inserted line in the same
transaction, and checked against the lines by reconciliation.

**The ledger is the only writer of money.** `ledger.service.post_entry` validates that an
entry has two or more lines in one currency and that debits equal credits, then inserts
it. PostgreSQL re-checks the same rules with deferred constraint triggers (forced to run
immediately after each posting), forbids updating or deleting lines, forbids adding lines
to an entry from an earlier transaction, and only lets an entry change from `posted` to
`reversed`. Corrections are opposite reversing entries.

**Duplicates and races.** Every posting carries an idempotency key (unique column); a
replay returns the original entry and a different payload under the same key is a 409.
Concurrent duplicates are resolved by the unique index. Withdrawals lock the account row
(`SELECT … FOR UPDATE`) before checking the balance, so parallel withdrawals cannot
overdraw; a test races six withdrawals and fails if the lock is removed.

**Reconciliation** re-verifies the invariants over all posted data (per-entry balance,
currency consistency, trial balance per currency, reversal links, account/ledger currency,
and since Phase 12 stored balances against their lines) and records each run in the audit
log and in `ledger_reconciliations`.

## Workflow engine (Phase 4)

Business processes are versioned definitions interpreted by one shared engine
(`app/modules/workflows`); see [workflows.md](workflows.md). Modules contribute named step
handlers and keep their own rules: WF-0001 calls the Phase 3 customer and account services,
so four-eyes, high-risk and eligibility checks apply whether an account is opened through
the workflow or the API. Each step commits atomically with its handler's effects; the
execution row lock prevents concurrent double execution; `run_due` resumes work after a
restart. The engine takes `now` as a parameter so the Phase 5 simulation clock can drive it.

## Simulation engine (Phase 5)

`app/simulation` replays scenarios on simulated time through the real workflow engine — no
separate model of the process. A discrete-event loop (a heap ordered by simulated time and
insertion order) starts cases, queues approvals to simulated reviewer pools, delivers late
documents as signals and fires timeouts; every random draw comes from a per-case stream
derived from the seed. Simulated staff are real employees and service-account users (they
cannot sign in) in a per-run team, so every permission and four-eyes rule applies. See
[simulation.md](simulation.md).

## AI Innovation Lab (Phase 6)

`app/modules/ai_tools` is the single AI registry of the platform: tool versions with JSON
Schema contracts, an async provider-independent adapter interface, and one invocation
service that enforces allowed actions, validates requests and results, applies timeouts
and records every call. Workflows reach it only through `ai_task` steps (WF-0001 v2,
WF-0002); a separate policy step and the accounts or payments service keep final
decisions with authorized principals. Experiments are ordinary simulation runs in different modes on the same seed.
See [ai-testing.md](ai-testing.md).

## Benchmarking (Phase 7)

`app/modules/experiments` reads raw measurements from what simulation runs recorded,
stores them, and derives costs, comparisons, criteria and a verdict through a pure
evaluation function (deterministic, digest-checked). Reports are generated from the
stored records. See [benchmarking.md](benchmarking.md).

## Payments and lending (Phase 9)

Two banking modules and two workflows extend the bank beyond account opening, on the same
engine, simulation and evaluation layers:

- `app/modules/payments` and `app/modules/lending` follow the banking-core pattern: one
  service per module is the only writer (`payments.service.release`,
  `lending.service.originate`), re-checks every control under row locks for any caller,
  and posts through the ledger; the database repeats the four-eyes rules as CHECK
  constraints. Read APIs only: payments and loans are created by WF-0002 and WF-0003.
- Workflows register a **presenter** (what a case is about, its risk and flags) so the
  task inbox and execution lists stay workflow-neutral; advisory AI steps share
  `workflows/advisory.py`.
- The simulation runner no longer knows any workflow: a **workload**
  (`app/simulation/workloads.py`) produces a scenario's cases with ground truth, creates
  the pre-existing customers they need, maps approval steps to staff roles, and re-checks
  the decisions its cases made for the experiment measurements.

## Loan servicing (Phase 10)

- `app/modules/lending/servicing.py` is the only writer of instalments and servicing
  postings. A **servicing run** (`POST /api/v1/loans/servicing-runs`, or
  `python -m app.cli service-loans --as-of …`) accrues each instalment's interest on its
  due date and collects due instalments oldest first; every posting's idempotency key is
  derived from the instalment, so repeating a run for the same date posts nothing twice.
  Runs are serialised by a PostgreSQL advisory lock, and the business date (the latest
  run's `as_of`) never goes backwards.
- Repayments and payoffs are customer actions with a required Idempotency-Key; write-offs
  happen only through the WF-0004 credit-committee approval and re-check authority and
  the 90-day rule in the service.
- **Listener, not import:** servicing calls `on_arrears_change` listeners after each loan is
  serviced, repaid or paid off. WF-0004 registers one, so lending never depends on the
  workflow module, and collections cases open, cure and escalate as a side effect of
  servicing in the same transaction.

## Scale foundation (Phase 12, roadmap Milestone A)

The first step towards the long-term scale in [roadmap.md](roadmap.md):

- **Stored balances.** `journal_lines_maintain_balance` (an AFTER INSERT trigger) adds every
  line to `ledger_balances` in the posting's transaction, so a balance read is a lookup of
  at most eight rows instead of a sum over all of an account's lines. Each account's totals
  are spread over eight shards (by a hash of the line), so concurrent postings to one busy
  account, such as a currency's cash account, rarely wait on the same row. Lines are
  immutable, so the totals are exact; a guard trigger refuses every other write to the
  table. `ledger.line_balances` keeps the old computation as the reference.
- **Incremental reconciliation.** A run in `incremental` mode checks the entries posted
  since the previous run (minus a ten-minute overlap for transactions that committed late),
  the trial balance from the stored totals, and the stored balances of up to 500 accounts
  the window touched. A `full` run remains the backstop and compares every account's stored
  totals with its lines.
- **Measured.** `python -m app.cli bench-ledger` posts synthetic entries through the normal
  service (half of them on one hot account by default) and times both read paths and both
  reconciliation modes; results are in [implementation-status.md](implementation-status.md).

## Planned design for later phases

- **Events:** cross-module side effects are currently explicit service calls made from
  workflow steps; a separate in-process event dispatcher has not been needed yet and will be
  added when a second consumer of the same business event appears.
- **Scoped access (later):** Phase 2 permissions are role-wide. Restricting a regional
  executive or department manager to *their* part of the hierarchy is a planned refinement.
- **Workflow engine (Phase 4):** see [workflows.md](workflows.md).

## Explicit non-goals for now

No Kubernetes, microservices, service mesh or managed cloud infrastructure. The platform
must run on one machine with `docker compose up`.
