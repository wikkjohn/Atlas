# ATLAS Global Bank

A synthetic enterprise banking simulation platform with an integrated AI testing
laboratory. ATLAS models a hypothetical global bank (organizations, workforce, customers,
accounts, ledger and executable business workflows) so that AI tools can be introduced
into simulated banking operations and measured through repeatable proof-of-concept
experiments.

> **All data is synthetic.** ATLAS never connects to real payment networks, financial
> institutions, customer databases or credit decisioning systems.

**Current state: Phase 1 (platform foundation) is complete.** See
[docs/implementation-status.md](docs/implementation-status.md) for what exists today and
what is planned.

| Layer    | Technology                                                                |
| -------- | ------------------------------------------------------------------------- |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS 4, React Router, TanStack Query  |
| Backend  | Python 3.11+, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic                  |
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
Then confirm everything is wired together:

```bash
python3 scripts/validate_system.py
```

## Quick start (without Docker)

Requirements: Python 3.11+, Node.js 20.19+ (22 recommended), PostgreSQL 16, and
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
   ```

3. **Run** (two terminals):

   ```bash
   make backend    # http://localhost:8000
   make frontend   # http://localhost:5173
   ```

Run `make help` to see every command.

## Tests

| Command             | What it runs                                                       |
| ------------------- | ------------------------------------------------------------------ |
| `make test-backend` | pytest against the real `atlas_test` PostgreSQL database           |
| `make test-frontend`| TypeScript typecheck + Vitest unit/component tests                 |
| `make test-e2e`     | Playwright in Chromium against the real backend and frontend       |
| `make lint`         | Ruff lint and format check (backend)                               |
| `make validate`     | Live checks against a running stack (`scripts/validate_system.py`) |

The backend suite **drops and recreates the schema of the test database**. Point
`ATLAS_TEST_DATABASE_URL` only at a disposable database.

For Playwright, the first time on a new machine run `cd frontend && npx playwright install chromium`.

## API

| Method | Path                  | Purpose                                                    |
| ------ | --------------------- | ---------------------------------------------------------- |
| GET    | `/api/health`         | Application + database health. 200 healthy, 503 if the database is down |
| GET    | `/api/system/info`    | Version, environment, runtime and the module roadmap       |
| GET    | `/api/system/status`  | Database details, migration state, Redis status            |
| GET    | `/api/docs`           | Interactive OpenAPI documentation                          |

Every response carries an `X-Correlation-ID` header (a valid one you send is echoed back).
Errors use one envelope: `{"error": {"code", "message", "details", "correlation_id"}}`.
Business modules will be mounted under the versioned prefix `/api/v1/`.

## Repository layout

```
backend/            FastAPI application, Alembic migrations, pytest suite
  app/core/         Shared platform services (config, database, logging, errors, DI)
  app/modules/      Bounded banking modules (filled in phase by phase)
  app/api/          HTTP routers
  app/simulation/   Simulation engine (Phase 5)
frontend/           React application, Vitest and Playwright tests
docs/               Architecture, database, workflow and AI-testing documentation
scripts/            Operational scripts (validate_system.py)
docker-compose.yml  Local development stack
```

See [docs/architecture.md](docs/architecture.md) for the design.
