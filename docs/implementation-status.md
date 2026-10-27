# Implementation status

Last updated: Phase 2.

| Phase | Name | Status |
| --- | --- | --- |
| 1 | Initialize the application | **Complete** |
| 2 | Shared enterprise foundation | **Complete** |
| 3 | First banking business modules | Not started |
| 4 | Workflow execution engine | Not started |
| 5 | Simulation engine | Not started |
| 6 | AI Innovation Lab | Not started |
| 7 | Benchmarking and experiment evaluation | Not started |
| 8 | Enterprise dashboard | Not started (shell, Overview, Organization, Countries, Employees and Audit Center screens exist) |

## Phase 2: what exists

- **Identity:** sign-in with salted-scrypt passwords and short-lived JWTs; 8 roles mapped
  to 10 permissions in code; every `/api/v1` route enforces a permission on the server;
  users API; `python -m app.cli create-user`
- **Countries:** registry validated against ISO 3166 / ISO 4217 / IANA formats; US, GB, DE,
  SG, JP seeded and active; holds the 120-country target without schema changes
- **Organizations:** six-level hierarchy with enforced parent types, a single global bank,
  one subsidiary per country, inherited region and country, unique sibling names, and
  activation rules
- **Employees:** placement in departments or teams (department derived), synthetic emails
  and numbers, compensation in integer minor units of the country's currency (hidden
  without permission), manager validation with cycle prevention, direct-report and
  reporting-chain queries, termination rule
- **Audit:** append-only `audit_events`, enforced by database triggers; actor, correlation
  ID and redacted change diffs on every important change and every sign-in attempt;
  read-only, filterable API
- **Shared plumbing:** domain errors, pagination, `Idempotency-Key` support on all create
  endpoints, currency minor units, seeded synthetic name generator
- **Demo data:** `make seed` builds 64 organizations, 120 synthetic employees and one sign-in
  per role, deterministically for a given seed
- **UI:** sign-in page, session handling (outage-tolerant), role-aware navigation,
  Organization (lazy tree + details + add/rename/deactivate), Countries (registry + add +
  status), Employees (search, filters, pagination, profile with reporting lines, hire and
  edit), Audit Center (filters, expandable metadata)

## Phase 2: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 84 passed |
| Ruff lint + format check | clean |
| Alembic 0001 → 0002 → base → head, `alembic check` | clean |
| Frontend typecheck | clean |
| Vitest | 29 passed |
| Production build | succeeds |
| Playwright (Chromium, real backend + DB) | 6 passed, against local processes and against the Docker Compose stack |
| Docker Compose: upgrade of an existing Phase 1 database, seed in container | succeeds |
| `validate_system.py` | 10/10 (local and Docker) |

## Phase 1: what exists

- FastAPI backend with typed configuration, a shared SQLAlchemy engine and per-request
  transactions, JSON structured logging, correlation IDs, a consistent error envelope, CORS
  and typed DI aliases
- Alembic configured, with baseline migration `0001_platform_baseline`
- `GET /api/health`, `GET /api/system/info`, `GET /api/system/status`, OpenAPI at `/api/docs`
- React + TypeScript + Vite + Tailwind app shell: global navigation (unbuilt screens
  disabled and labelled by phase), live Overview page, backend-unavailable state with retry,
  not-found page, responsive layout
- Docker Compose stack (PostgreSQL, Redis, backend, frontend); backend migrates on start
- `scripts/validate_system.py` for live end-to-end checks of a running stack
- GitHub Actions CI: backend lint and tests, frontend typecheck/tests/build, Playwright

## Phase 1: verified results (at the end of Phase 1)

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 22 passed |
| Ruff lint + format check | clean |
| Frontend typecheck | clean |
| Vitest | 10 passed |
| Production build (`vite build`) | succeeds |
| Playwright (Chromium, real backend + DB) | 3 passed, against both local processes and the Docker Compose stack |
| `validate_system.py` against Docker Compose stack | 9/9 checks passed |
| Alembic upgrade → downgrade → upgrade, `alembic check` | clean |

## Known limitations

- Permissions are role-wide: a regional executive or department manager is not yet limited
  to their own region or department.
- No login rate limiting or account lockout yet; failed attempts are audited.
- Access tokens cannot be revoked individually before expiry (deactivating the user or
  changing their role does take effect immediately). No refresh tokens.
- Organizations cannot be moved to a different parent. Employees cannot transfer between
  countries (rejected, because compensation is held in the country's currency and the
  platform has no currency conversion).
- Stored idempotency keys are never pruned.
- `app/core/events.py` (event dispatcher) is deferred to Phase 4, where workflows need it.
- The Overview page still shows platform health only; enterprise metrics arrive with the
  Phase 8 dashboard.
- Redis is connected and health-checked but not used by any feature yet.
- `scripts/reset_demo.py` and `test-data/` arrive with the phases that need them (3 and 5).
- No charting library is installed yet; one is added with the benchmarking screens (Phase 7).
- The frontend Docker image runs the Vite dev server; a production static image is not yet
  defined.
