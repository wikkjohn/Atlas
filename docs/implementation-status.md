# Implementation status

Last updated: Phase 5.

| Phase | Name | Status |
| --- | --- | --- |
| 1 | Initialize the application | **Complete** |
| 2 | Shared enterprise foundation | **Complete** |
| 3 | First banking business modules | **Complete** |
| 4 | Workflow execution engine | **Complete** |
| 5 | Simulation engine | **Complete** |
| 6 | AI Innovation Lab | Not started |
| 7 | Benchmarking and experiment evaluation | Not started |
| 8 | Enterprise dashboard | Not started (shell plus Overview, Organization, Countries, Employees, Customers, Accounts, Workflow Explorer, Simulation Center and Audit Center screens exist) |

## Phase 5: what exists

- **Simulation clock** (forward-only, timezone-aware, fixed scenario start), **scenarios**
  (versioned: workflow, application mix with ground truth, arrival window, document
  delays, reviewer time and accuracy, staff mix) and **workload profiles** (small 100/25,
  department 10,000/500, custom up to 10,000/500; enterprise 1,000,000 customers / 150,000
  staff as an unverified configuration target that the API refuses to run)
- **Generators:** synthetic applications (eight case types, from clean to forged and
  sanctions hits) and synthetic staff, each draw from a per-case stream derived from the
  seed; no personal information
- **Runner:** discrete-event loop driving the real WF-0001 engine on simulated time —
  tellers start cases, approvals queue to reviewer pools with lognormal review times and
  seeded accuracy, late documents arrive as signals, timeouts fire at their due time;
  progress and heartbeat committed every 250 events
- **Run registry:** every run stores scenario and workflow versions, profile, seed, the
  fully resolved configuration and its hash, the software version, timing, progress,
  results, a result digest and per-case results against ground truth; failed runs record
  their reason; interrupted runs are detected; one run at a time; rerun and
  reproduction comparison
- **Simulated staff** are real employees in a per-run team with service-account users
  that cannot sign in, so permissions and four-eyes rules apply to them
- **Isolation:** simulated executions carry `simulation_run_id` and are excluded from the
  live task inbox, workflow metrics, the timer sweep and default execution listings
- **API:** scenarios, profiles, start (background), list, detail, cases, rerun;
  `simulations:read` (every role) and `simulations:run` (AI researcher, administrator)
- **CLI:** `python -m app.cli simulate` / `make simulate`
- **UI:** Simulation Center — scenario, workload and seed selection, start, live progress,
  outcomes, decision accuracy, case types, execution statistics, reproducibility,
  per-case results with a ground-truth mismatch filter, rerun
- `validate_system.py --login …` also checks that every repeated configuration of a
  running stack produced identical results

## Phase 5: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 174 passed (24 simulation tests) |
| Ruff lint + format check | clean |
| Alembic 0004 → 0005, base ↔ head, `alembic check` | clean |
| Frontend typecheck | clean |
| Vitest | 48 passed |
| Production build | succeeds |
| Department profile (10,000 / 500) | measurement in progress — see simulation.md |

## Phase 4: what exists

- **Engine:** versioned, validated, immutable definitions with nine step types (service
  task, human task, approval, decision, parallel/join, wait, AI task, completion, failure)
  and a safe structured condition language; durable execution in PostgreSQL with atomic
  steps (handler effects and state change in one savepoint), execution-row locking against
  duplicate execution, retries with exponential backoff, failure routing, timeouts (flag or
  transition), signals, cancellation, step-level timing, append-only history and audit
- **Resumption:** `run_due` / `python -m app.cli run-workflows [--watch]` (`make workflows`)
  resumes due steps and applies timers after a restart, one execution per transaction,
  skipping executions other workers hold
- **WF-0001 Retail Account Opening:** validation, document wait (72 h timeout), customer
  registration, parallel identity verification and sanctions screening, risk rating,
  compliance rules, routing, compliance review or authorized approval (both four-eyes, with
  overdue flags), account opening through the Phase 3 services, rejection, finalized audit
  record and a simulated customer notification
- **API:** definitions, metrics (bottleneck analysis), start (idempotent), executions,
  history, signals, resume, cancel, task inbox and task completion
- **UI:** Workflow Explorer — catalogue with steps, routes, policies and per-step metrics
  (bottleneck highlighted); start-application form with valid synthetic documents; executions
  with step timeline, errors, context and history; task inbox with four-eyes explanations;
  document submission for waiting cases
- **Demo data:** 20 WF-0001 cases run through the engine (approved, rejected, waiting for
  documents, waiting for approval or compliance review)

## Phase 4: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 150 passed (35 workflow tests) |
| Ruff lint + format check | clean |
| Alembic 0003 → 0004, base ↔ head, `alembic check` | clean |
| Frontend typecheck | clean |
| Vitest | 43 passed |
| Production build | succeeds |
| Playwright (Chromium, real backend + DB) | 8 passed, local (twice) and against Docker Compose |
| Docker Compose: upgrade of the Phase 3 database, seed and runner in container | succeeds |
| `validate_system.py --login auditor` | 12/12 (local and Docker) |
| Restart/resume and four-thread duplicate-execution tests (committed sessions) | pass (3 repeated runs) |

## Phase 3: what exists

- **Customers:** synthetic individuals and businesses; onboarding only in active
  countries; KYC transitions (not_started → pending → verified/rejected, re-review back to
  pending) and risk ratings decided only by `customers:review` holders; verification
  requires a rating
- **Account opening:** request → approve/reject. Approval is the only way an account is
  created; four-eyes (service + DB CHECK); high-risk customers need a compliance approver;
  eligibility (KYC verified, rated, type matches customer type, 18+, active country,
  domestic currency, no duplicate) checked at request and again at approval; one request
  opens exactly one account
- **Accounts:** check-digit account numbers; balances derived from the ledger; deposits and
  withdrawals (Idempotency-Key required, no overdrafts, row lock against races);
  freeze/unfreeze/close (zero balance)
- **Ledger:** double-entry with integer minor units; balanced, single-currency entries
  enforced by the service and by deferred database triggers; immutable lines; reversals by
  opposite entry; idempotent postings (replay or 409); statements; reconciliation report
- **Permissions:** 10 new permissions; tellers request and transact, managers approve and
  control accounts, compliance reviews KYC and approves high-risk, auditors read the ledger
- **Demo data:** 150 customers across 5 countries with mixed KYC outcomes, 120 accounts
  opened through real approvals, 14 pending requests and 304 ledger postings — identical
  for the same seed (verified locally and in Docker)
- **UI:** Customers (search, filters, onboarding, KYC review, eligibility, account request)
  and Accounts (accounts with ledger balance and history, deposit/withdraw with
  retry-safe idempotency keys, controls; opening-request queue with four-eyes; general
  ledger with reconciliation, cash accounts and journal)
- `validate_system.py --login auditor` also reconciles the ledger of a running stack

## Phase 3: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 115 passed |
| Ruff lint + format check | clean |
| Alembic 0002 → 0003, base ↔ head, `alembic check` | clean |
| Frontend typecheck | clean |
| Vitest | 38 passed |
| Production build | succeeds |
| Playwright (Chromium, real backend + DB) | 7 passed, local (twice) and against Docker Compose |
| Docker Compose: upgrade of the Phase 2 database, seed in container | succeeds |
| `validate_system.py --login auditor` | 12/12 (local and Docker) |
| Concurrency: race test fails with the withdrawal row lock removed | 5/5 runs fail without the lock, 5/5 pass with it |

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

- Accounts are domestic-currency only; there is no FX, interest, fees, transfers between
  accounts, or statements beyond posted lines.
- Workflow definitions are authored in code (registered at import); there is no visual
  designer or upload API, and only WF-0001 exists so far.
- Simulation runs write into the same synthetic bank (customers, accounts, ledger postings
  and staff remain); there is no reset command. Simulated reviewers work around the clock;
  arrivals are uniform. Background runs live in the API process, so a restart interrupts
  them (reported as interrupted). See [simulation.md](simulation.md) for measured
  throughput and why the enterprise profile is only a target.
- The workflow runner is a polling CLI process; there is no in-API background scheduler, so
  timeouts and retries fire only while `make workflows` (or the CLI) runs.
- `ai_task` steps work with registered adapters, but no AI tools exist until Phase 6.
- Human tasks are offered to everyone holding the permissions; there is no assignment to a
  named person, delegation or escalation routing beyond the overdue flag.
- Balances are computed from lines on every read; fine at demo scale, but large volumes
  will need snapshots or materialized balances.
- Reconciliation scans the whole ledger synchronously.

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
- `scripts/reset_demo.py` does not exist yet; simulation data accumulates in the
  development database (`docker compose down -v` resets everything).
- No charting library is installed yet; one is added with the benchmarking screens (Phase 7).
- The frontend Docker image runs the Vite dev server; a production static image is not yet
  defined.
