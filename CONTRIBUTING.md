# Contributing to ATLAS Global Bank

ATLAS Global Bank is a synthetic bank: a platform for building, simulating and testing
banking workflows and the AI tools that assist them. **Every customer, account, employee and
amount is generated.** Never add real personal data, real credentials, or a connection to
real banking infrastructure.

## Setting up

The [README](README.md) has the two ways to run the platform:
- with Docker (`make up`);
- without it (PostgreSQL 16, Python 3.13, Node 22, then `make setup migrate seed`).

`make help` lists every developer command.

The backend tests need a disposable PostgreSQL database, `atlas_test` by default or
`ATLAS_TEST_DATABASE_URL`. **The suite drops and recreates its schema.** Never point it at a
database you care about.

## How the code is organised

Read [docs/architecture.md](docs/architecture.md) first, then the decision records in
[docs/adr/](docs/adr/README.md). They explain why the platform is shaped as it is:
- a modular monolith;
- PostgreSQL as the only system of record;
- one ledger writer;
- workflows as data;
- the reviewed authorization matrix.

**Backend.** A business capability is a module in `backend/app/modules/<name>/`, with:
- `models.py`;
- `schemas.py`;
- `service.py`: the module's interface;
- `router.py`: HTTP only, and no business rules.

Other modules call the service and never another module's tables.

**Frontend.**
- Screens live in `frontend/src/features/<area>/`.
- Only `frontend/src/services/` talks HTTP.
- `frontend/src/types/` mirrors the backend's responses.

## Rules the platform relies on

These are enforced by tests or by the database. A change that breaks one fails CI.

| Rule | Where it is enforced |
| --- | --- |
| Schema changes are Alembic migrations only. Revision ids are at most 32 characters | `backend/tests/test_migrations.py` compares models and migrations |
| Money is an integer of the currency's minor unit; an entry is in one currency and balances | the ledger service and database triggers ([ADR 0003](docs/adr/0003-money-in-integer-minor-units.md), [ADR 0004](docs/adr/0004-the-ledger-is-the-only-writer-of-money.md)) |
| Only `ledger.service` writes journal entries | database triggers refuse unbalanced, edited or deleted lines |
| A change and its audit event commit together; the audit log is append-only | `record_audit_event` and a trigger ([ADR 0005](docs/adr/0005-append-only-audit-log-with-an-archive-chain.md)) |
| Every `/api/v1` route is public, signed-in, or guarded by one permission | `backend/tests/test_authorization_matrix.py` and the Security CI job ([ADR 0010](docs/adr/0010-one-permission-per-route-and-a-reviewed-matrix.md)) |
| A request is one transaction; services do not commit on their own | `get_db` in `backend/app/core/database.py` |
| Customer, account and employee records respect the caller's country and department scope (404 outside it) | the scope tests in `backend/tests/test_sessions_mfa_sso_scopes.py` |

**When you add a route:**
1. Guard it with `Authorized(Permission.X)` (or make it deliberately public or signed-in).
2. Run `python -m app.cli authz-matrix`, review the difference, then
   `python -m app.cli authz-matrix --write`.
3. Commit the regenerated `backend/tests/authorization_matrix.json` and
   `docs/authorization-matrix.md`.

## Before you push

Run the checks CI runs.

| Check | Command |
| --- | --- |
| Backend lint and format | `make lint` (ruff; line length 100) |
| Backend tests | `make test-backend` |
| Frontend typecheck and unit tests | `make test-frontend` |
| Frontend build | `cd frontend && npm run build` |
| End to end | `make test-e2e` (starts the backend and frontend if needed) |
| Security | `bandit -r backend/app -q -ll`; `python -m app.cli authz-matrix`; `npm audit --audit-level=high` |

**Report results honestly.**
- Never claim a test passed unless it ran.
- Never skip, disable or loosen a test to make CI green.
- If a check fails for a reason outside your change, say so, with the failing output.

## Pull requests

- One phase or one fix per pull request, on its own branch. Open it as a draft until CI
  is green.
- Describe what changed, what was measured, which tests ran, and the known limitations.
- **Review findings:**
  - Answer each review comment: fix it, or explain why not.
  - Findings that arrive after a merge are fixed in the next pull request, which names the
    finding it fixes.
- **Documentation changes with the code:**
  - the module's own document in `docs/`;
  - `docs/api.md` for new routes;
  - `docs/implementation-status.md` for what now exists and what was verified;
  - `docs/roadmap.md` when a roadmap item is done.

### The phase report

A phase ends with tests, a demonstration, a commit and a report in this form:

```
Phase [N] — [Name]
Status
Implemented functionality
Files created or modified
Database changes
API endpoints implemented
Tests executed
How to verify
Known limitations
Next phase
```

## Decisions and operations

- **A decision that shapes the platform** (a new store, a new boundary, a change to a rule
  above) gets an architecture decision record. Copy
  [docs/adr/template.md](docs/adr/template.md), and supersede an old record rather than
  rewriting it.
- **A new operational failure mode** (a job, an archive, a dependency) gets a runbook in
  [docs/runbooks/](docs/runbooks/README.md), with symptoms, checks, actions, verification
  and escalation.
- `backend/tests/test_documentation.py` checks both:
  - the required sections of each record and runbook;
  - that they are listed in their index;
  - that every repository path, CLI command and `/api/v1` route they name exists.
