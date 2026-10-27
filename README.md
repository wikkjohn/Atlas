# ATLAS Global Bank

A synthetic enterprise banking simulation platform with an integrated AI testing
laboratory. ATLAS models a hypothetical global bank (organizations, workforce, customers,
accounts, ledger and executable business workflows) so that AI tools can be introduced
into simulated banking operations and measured through repeatable proof-of-concept
experiments.

> **All data is synthetic.** ATLAS never connects to real payment networks, financial
> institutions, customer databases or credit decisioning systems.

**Current state: Phases 1–2 are complete** — the platform foundation plus the shared
enterprise foundation (sign-in and role-based permissions, countries, the organization
hierarchy, the employee registry and an append-only audit log). See
[docs/implementation-status.md](docs/implementation-status.md) for what exists today and
what is planned.

| Layer    | Technology                                                                |
| -------- | ------------------------------------------------------------------------- |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS 4, React Router, TanStack Query  |
| Backend  | Python 3.12+, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic                  |
| Data     | PostgreSQL 16, Redis 7 (optional)                                         |
| Tests    | pytest, Vitest + Testing Library, Playwright                              |
| Local    | Docker Compose                                                            |

## Quick start (Docker)

Requirements: Docker with Compose v2.

```bash
cp .env.example .env
docker compose up --build
```

Open:

- Web UI: <http://localhost:5173>
- API docs (OpenAPI): <http://localhost:8000/api/docs>
- Health check: <http://localhost:8000/api/health>

The backend container applies database migrations automatically before it starts.
Create the demo bank and demo sign-ins, then confirm everything is wired together:

```bash
docker compose exec backend python -m app.cli seed-demo
python3 scripts/validate_system.py
```

## Quick start (without Docker)

Requirements: Python 3.12+, Node.js 20.19+ (22 recommended), PostgreSQL 16, and
optionally Redis.

1. **Create the databases** (once). As a PostgreSQL superuser:

   ```bash
   psql -U postgres -c "CREATE ROLE atlas LOGIN PASSWORD 'atlas' CREATEDB"
   createdb -U postgres -O atlas atlas        # application database
   createdb -U postgres -O atlas atlas_test   # used and reset by the backend tests
   ```

2. **Install dependencies and configure:**

   ```bash
   cp .env.example .env    # set ATLAS_REDIS_URL= (empty) if you are not running Redis
   make setup
   make migrate
   make seed               # demo bank: 64 organizations, 120 synthetic employees, 8 sign-ins
   ```

3. **Run** (two terminals):

   ```bash
   make backend    # http://localhost:8000
   make frontend   # http://localhost:5173
   ```

Run `make help` to see every command.

## Signing in

`make seed` (or the `seed-demo` command above) creates one demo account per role, all with
the password `atlas-demo-password` (override with `ATLAS_DEMO_PASSWORD`). These exist for
local development only; the seed refuses to run in staging or production.

| Username     | Role                   | Can                                                        |
| ------------ | ---------------------- | ---------------------------------------------------------- |
| `admin`      | Platform Administrator | Everything, including creating users, countries, units, staff |
| `executive`  | Global Executive       | Read everything incl. compensation; list users             |
| `regional`   | Regional Executive     | Read the directory incl. compensation                      |
| `manager`    | Department Manager     | Read the directory                                         |
| `employee`   | Banking Employee       | Read the directory (no compensation)                       |
| `compliance` | Compliance Officer     | Read the directory and the audit log                       |
| `researcher` | AI Researcher          | Read the directory                                         |
| `auditor`    | Auditor                | Read everything incl. compensation and the audit log       |

Permissions are enforced by the backend on every request; the UI only hides what a role
cannot use. To create a real administrator for a non-demo environment:
`cd backend && .venv/bin/python -m app.cli create-user --username ops.admin --role platform_administrator --email ops.admin@example.com --display-name "Ops Admin"`.

## Tests

| Command             | What it runs                                                       |
| ------------------- | ------------------------------------------------------------------ |
| `make test-backend` | pytest against the real `atlas_test` PostgreSQL database           |
| `make test-frontend`| TypeScript typecheck + Vitest unit/component tests                 |
| `make test-e2e`     | Playwright in Chromium against the real backend and frontend       |
| `make lint`         | Ruff lint and format check (backend)                               |
| `make validate`     | Live checks against a running stack (`scripts/validate_system.py`) |
| `make seed`         | Create the demo bank and demo sign-ins (idempotent)                |

The backend suite **drops and recreates the schema of the test database**. Point
`ATLAS_TEST_DATABASE_URL` only at a disposable database.

For Playwright, the first time on a new machine run `cd frontend && npx playwright install chromium`.
The end-to-end suite seeds the demo data itself (idempotently) and creates uniquely named
records, so it can run repeatedly against your development database.

## API

Interactive documentation: <http://localhost:8000/api/docs>. Conventions and every
endpoint are described in [docs/api.md](docs/api.md).

| Area | Endpoints |
| --- | --- |
| Platform (public) | `GET /api/health`, `/api/system/info`, `/api/system/status` |
| Auth | `POST /api/v1/auth/login`, `GET /api/v1/auth/me` |
| Users & roles | `/api/v1/users`, `/api/v1/roles` |
| Countries | `/api/v1/countries` |
| Organizations | `/api/v1/organizations` (+ `/{id}/ancestors`) |
| Employees | `/api/v1/employees` (+ `/{id}/direct-reports`, `/{id}/reporting-chain`) |
| Audit | `GET /api/v1/audit-events` (read-only) |

Every response carries an `X-Correlation-ID` header. Errors use one envelope:
`{"error": {"code", "message", "details", "correlation_id"}}`. Create requests accept an
`Idempotency-Key` header so retries never create duplicates.

## Repository layout

```
backend/            FastAPI application, Alembic migrations, pytest suite
  app/core/         Shared platform services (config, database, logging, errors, DI)
  app/modules/      Bounded banking modules (filled in phase by phase)
  app/api/          HTTP routers
  app/simulation/   Simulation engine (Phase 5)
frontend/           React application, Vitest and Playwright tests
docs/               Architecture, database, workflow and AI-testing documentation
scripts/            Operational scripts (seed.py, validate_system.py)
docker-compose.yml  Local development stack
```

See [docs/architecture.md](docs/architecture.md) for the design.
