# Implementation status

Last updated: Phase 10.

| Phase | Name | Status |
| --- | --- | --- |
| 1 | Initialize the application | **Complete** |
| 2 | Shared enterprise foundation | **Complete** |
| 3 | First banking business modules | **Complete** |
| 4 | Workflow execution engine | **Complete** |
| 5 | Simulation engine | **Complete** |
| 6 | AI Innovation Lab | **Complete** |
| 7 | Benchmarking and experiment evaluation | **Complete** |
| 8 | Enterprise dashboard | **Complete** |
| — | End-to-end demonstration (Part 12) | **Complete** — [demo.md](demo.md), automated in Playwright |
| 9 | Additional business workflows: payments and lending | **Complete** |
| 10 | Loan servicing and collections | **Complete** |

## Phase 10: what exists

- **Repayment schedules** (`loan_instalments`): level monthly instalments from one month
  after disbursement (due days past the 28th move to the 28th), interest rounded half up,
  the last instalment takes the remaining principal. Created at origination; migration
  0009 backfills existing loans.
- **Servicing runs** (`loan_servicing_runs`, `POST /api/v1/loans/servicing-runs`, CLI
  `service-loans`): accrue interest on each due date (interest receivable → interest
  income), collect whole instalments oldest first from the borrower's account (deposit →
  interest receivable + loan receivable), leave the rest due. Idempotent per instalment;
  the business date never goes backwards; one run at a time (advisory lock); a summary
  per run (accrued, collected, missed, repaid, arrears per currency, buckets).
- **Arrears:** days past due from the oldest unpaid due date, buckets current / 1-29 /
  30-59 / 60-89 / 90+, and the overdue amount on every loan.
- **Repayment and payoff** (`loans:repay`, Idempotency-Key required): repay the oldest
  overdue instalments; pay the loan off early for outstanding principal plus accrued
  interest (checked against the receivable balance first). The final instalment or a
  payoff closes the loan as `repaid`.
- **Write-off:** at 90+ days past due, by `loans:approve_large`: remaining principal and
  accrued interest → loan losses; status `written_off`.
- **WF-0004 Loan Collections:** opened by servicing at 30 days past due, sends a simulated
  arrears letter, closes as cured when the arrears are paid, and at 90 days escalates to a
  four-eyes credit-committee write-off review.
- **Permissions:** `loans:repay` (front office), `loans:service` (department managers);
  `loans:approve_large` now also covers write-offs.
- **UI:** the Lending screen shows the business date, runs servicing, lists recent runs,
  shows status and arrears per loan, and opens a loan's schedule with repayment, payoff
  and its collections cases.
- **Engine fix:** `workflow_step_runs.duration_ms` is BIGINT (a wait of weeks overflowed
  a 32-bit millisecond count).

## Phase 10: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 287 passed (new: 12 servicing tests — schedule maths, due-date capping and buckets, schedules at origination, accrual and collection posted once per instalment, monotonic business date, arrears and DPD, oldest-whole-instalment collection, idempotent repayment and its funds and count checks, payoff of principal plus accrued interest, the last instalment closing the loan, write-off authority and 90-day rule, permissions and idempotent runs; 4 WF-0004 tests — case at 30 days, one case per loan, cure on repayment, 90-day escalation with four-eyes write-off, declined write-off reopened by the next run, a loan repaid during the review closing as cured) |
| Ruff lint + format check | clean |
| Alembic 0008 → 0009 → 0008 → 0009 on a seeded database, `alembic check` | clean; backfill verified on 17 existing loans (708 instalments match the schedule maths; ledger reconciles) |
| Frontend typecheck, production build | clean; succeeds |
| Vitest | 74 passed (new: servicing panel, run to a date with an Idempotency-Key, arrears in the loan list, schedule, repayment and payoff with distinct keys, actions hidden without the permissions) |
| Playwright (Chromium, real backend, fresh database) | 16 passed, including the new servicing journey (a manager moves the business date; a teller, who cannot run servicing, pays a loan off and the schedule closes) |
| Docker Compose stack | `validate_system.py` 10/10 (migration head `0009_loan_servicing`, v0.10.0); `service-loans` CLI in the container; Playwright 16 passed against the stack |
| Visual review | Lending with servicing and a loan in arrears with its collections case at 1440 px ([images](images/)) |

## Phase 9: what exists

- **Payments module** (`payments` table, `GET /api/v1/payments`): the payments service is
  the only code that moves money between customer accounts. It re-checks open accounts,
  currency, funds (under row locks taken in id order), four-eyes and the high-value
  approval rule for every caller, and posts one balanced ledger entry.
- **Lending module** (`loans` table, `GET /api/v1/loans`): a deterministic synthetic credit
  bureau, risk-based pricing by score band, level-instalment amortization,
  debt-to-income, and `originate`, which re-checks KYC, ownership, limits, underwriting
  authority, four-eyes and the credit committee rule, then posts loan receivable →
  customer account. Outstanding balances come from the ledger.
- **WF-0002 Domestic Payment:** validation, funds check, fraud and sanctions screening,
  straight-through release of clean payments, fraud review of held payments, four-eyes
  approval of high-value payments, an optional AI fraud screener (off / assisted /
  automated) with a policy engine that may release low-risk holds.
- **WF-0003 Personal Loan Origination:** validation, bureau check, pricing and
  affordability, automatic credit-policy declines, underwriting and a credit committee
  above 25,000, disbursement.
- **AGB Payment Fraud Screener** (`rule_based_payment_screening`), registered by the seed;
  `release_payment` and `approve_loan` join the actions no tool can be granted.
- **Permissions:** `payments:read`, `payments:review` (compliance), `payments:approve`
  (managers), `payments:release_low_risk` (policy engine), `loans:read`, `loans:approve`
  (managers), `loans:approve_large` (regional and global executives).
- **Workflow-neutral platform:** presenters name cases in the task inbox and execution
  lists (`subject` replaces `applicant`); the simulation runner and the experiment
  measurements work through **workloads**; new scenarios `domestic-payments` v1 (with AI
  modes) and `personal-loans` v1, each with a pre-existing customer population and known
  ground truth; experiments run on any scenario with AI modes.
- **UI:** Payments and Lending screens; start dialogs for payments and loan applications
  in the Workflow Explorer; scenario choice in Experiments; the AI Lab console offers a
  payment sample to the fraud screener.
- **Seed:** 10 payments and 6 loan applications between the seeded customers, leaving a
  scam in the fraud review queue and applications waiting for an underwriter.

## Phase 9: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 266 passed (new: 9 WF-0002, 8 WF-0003, 7 workload tests — straight-through, high-value four-eyes, scam stopped, hold cleared, watchlist, invalid and unfunded payments, funds re-checked under the lock, service controls for every caller, automated release that never releases scams, bureau and pricing, underwriting, committee, policy declines, payment and loan runs, reproducibility, tampered-release detection, the screener experiment) |
| Ruff lint + format check | clean |
| Alembic 0007 → 0008 → 0007 → 0008, `alembic check` | clean |
| Frontend typecheck | clean |
| Vitest | 69 passed |
| Production build | succeeds; no chunk-size warning |
| Playwright (Chromium, real backend, fresh database) | 15 passed, including the new WF-0002 journey (scam held, a manager cannot clear it, the analyst rejects it, no money moves) |
| Visual review | Payments, Lending, WF-0002 in the Workflow Explorer, the task inbox at 1440 px ([images](images/)) |

## Phase 8: what exists

- **Analytics API** (`GET /api/v1/analytics/overview`, `analytics:read` for every role):
  employees (enterprise vs. simulated staff), configured countries, registered
  workflows, active simulation runs, completed and failed workflow executions (live, with
  simulated counts alongside), customer accounts (with the share opened by simulations),
  AI tools, completed experiments, average process duration and the estimated
  simulation operating cost (default assumptions, flagged as an estimate; computed with
  the experiment engine's cost function and cross-checked against it in tests)
- **Enterprise Overview:** every metric as a tile linked to its screen, live execution
  outcomes and open tasks, recent simulation runs and experiments, platform health, and
  visible synthetic-data and estimate labels
- **System Settings:** platform health, build, database and module registry; users
  (people vs. service accounts, search, create with validation, change role,
  activate/deactivate — service accounts keep their role; service roles are never
  offered to people); the role and permission matrix
- **Navigation complete:** every entry links to a working screen; feature screens
  load on first visit (initial bundle 303 kB, from 507 kB)
- **End-to-end demonstration** (Part 12) automated as a Playwright test and documented
  with screenshots in [demo.md](demo.md)

## Phase 8: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 238 passed (5 analytics/settings tests, incl. a cross-check of the dashboard cost estimate against the experiment engine) |
| Ruff lint + format check | clean |
| `alembic check` (no schema change in Phase 8) | clean |
| Frontend typecheck | clean |
| Vitest | 63 passed |
| Production build | succeeds; no chunk-size warning (route-level code splitting) |
| Playwright (Chromium, real backend + DB) | 14 passed — fresh local database (twice) and Docker Compose; includes the Part 12 demonstration and the System Settings user journey |
| `validate_system.py --login auditor` (Docker) | 14/14 |
| Visual review | Overview, Settings, Experiments, Benchmarking at 1440 px and 390 px (no horizontal scroll) |

## Phase 7: what exists

- **Experiment model** (`experiments`) linking a baseline and a candidate run, tool and
  version, resolved configuration (cost assumptions + thresholds) and status; created by
  running both modes on one seeded workload, or from two existing equivalent runs
- **Raw measurements** (`experiment_measurements`) read from what runs recorded — case
  results, workflow history, AI invocations and the account decisions, which are
  re-checked against the authorization rules (policy violations) — stored apart from
- **derived evaluations** (`experiment_evaluations`): a pure, digest-checked function of
  the measurements and configuration: cost lines (review labour, oversight of automation,
  AI execution, infrastructure, exceptions, escalations; risk exposure separately), 14
  compared metrics with improvement and regression flags, six success criteria
  (equivalent workloads, measurable improvement, acceptable correctness, compliance
  thresholds, effective authorization controls, complete costs), verdict, conclusion
  and limitations
- **Reports:** downloadable Markdown proof-of-concept report and JSON; re-evaluation
  proves the result reproduces; `/benchmarks` aggregates experiments by tool version
- **UI:** Experiments (create with editable assumptions and thresholds, live status,
  evaluation, report download, re-evaluate) and Benchmarking (tool comparison,
  processing-time and cost charts with table views, quality and compliance, conclusions)
- `validate_system.py` re-evaluates every evaluated experiment of a running stack

## Phase 7: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 233 passed (20 benchmarking tests: hand-checked cost lines and metrics, regression detection, thresholds, complete costs, authorization violations, workload equivalence, determinism, API, reproducibility, re-pricing, policy-violation detection from tampered records, failed runs, reports, benchmarks, permissions) |
| Ruff lint + format check | clean |
| Alembic 0006 → 0007, base ↔ head, `alembic check` | clean |
| Frontend typecheck | clean |
| Vitest | 57 passed |
| Production build | succeeds |
| Playwright (Chromium, real backend + DB) | 12 passed — fresh local database (twice) and Docker Compose |
| Docker Compose: upgrade 0006 → 0007, seed in container | succeeds |
| `validate_system.py --login auditor` (Docker) | 14/14, incl. experiment re-evaluation |
| Example experiment, 100 applications, seed 42, automated mode (local) | successful: labour −77 %, cost per case −70 %, no regressions; the fault injector in assisted mode is not successful (15 % errors) |

## Phase 6: what exists

- **AI tool registry** (`ai_tools`): versioned tools with JSON Schema input/output
  contracts, allowed actions, caller permissions, compatible workflows, adapter-validated
  configuration and status; registration refuses never-delegable actions (approve or open
  accounts, KYC decisions, ledger postings…), invalid schemas and invalid configuration
- **Adapter contract:** async `AIToolAdapter.execute(request, context)` with typed
  request/result, structured `ToolError`; one invocation service enforces allowed actions
  and status, validates input and output against the registered schemas, applies the
  timeout and records every call (`ai_tool_invocations`) with status, duration and usage
- **AGB Intelligent KYC Assistant** (rule-based proof of concept): missing and
  inconsistent fields, risk classification, explanation, approve/reject/escalate; plus a
  reproducible **fault injector** for failure testing
- **WF-0001 v2:** advisory `ai_kyc_review` step (off / assisted / automated) with safe
  escalation on any tool failure; `policy_approval` step — the workflow policy engine —
  approves only low-risk, unflagged, verified cases the tool recommends; the
  `automated_policy` system principal can approve low-risk customers only (enforced by the
  accounts service), cannot sign in, and its role cannot be given to people
- **Experiments A/B/C:** scenario `retail-onboarding` v2 runs baseline, AI-assisted and
  AI-automated modes on the same seeded applications and staff; suites run them back to
  back; AI-assistance effects on reviewers are explicit, stored assumptions; results
  report invocations, failures, recommendations, recommendation accuracy and policy
  approvals per run and per case
- **API:** `/api/v1/ai-tools` (registry, adapters, actions, invocations, test-console
  invoke, enable/disable) and `/api/v1/simulations/suites`; permissions `ai_tools:read`
  (every role), `ai_tools:manage` and `ai_tools:invoke` (AI researcher, administrator)
- **UI:** AI Innovation Lab — tool registry, capabilities and schemas, registration form
  (never-grantable actions shown disabled), test console, recorded invocations, experiment
  configuration on compatible workflows, side-by-side run results linking to the
  Simulation Center (which now shows modes, tools and AI behaviour)
- **Demo data:** the KYC assistant and the fault injector are registered by `make seed`;
  `python -m app.cli simulate --mode ai_assisted --tool agb-intelligent-kyc-assistant`

## Phase 6: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 213 passed (39 AI Innovation Lab tests) |
| Ruff lint + format check | clean |
| Alembic 0005 → 0006, base ↔ head, `alembic check` | clean (also upgraded a database holding a 10,000-case run) |
| Frontend typecheck | clean |
| Vitest | 53 passed |
| Production build | succeeds |
| Playwright (Chromium, real backend + DB) | 11 passed — fresh local database (twice) and Docker Compose |
| Docker Compose: upgrade of the Phase 4 database volume to 0006, seed in container | succeeds |
| `validate_system.py --login auditor` (Docker) | 13/13, incl. simulation reproducibility across 5 runs |
| A/B/C suite, 100 applications, seed 42 (local) | completed; same applications in all modes; see ai-testing.md |
| Mutation check: low-risk guard removed from the accounts service | the policy-limit test fails |

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
| Department profile (10,000 / 500), local | 10,000 cases completed in 35 min 16 s (4.7 cases/s) |
| Playwright (Chromium, real backend + fresh DB) | 10 passed (twice) |

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

- Accounts are domestic-currency only; there is no FX, interest, fees, or statements
  beyond posted lines. Payments are between accounts at ATLAS in one currency; there is no
  external clearing, scheduling, standing orders or recall.
- Loan servicing is monthly and simplified: interest accrues in full on each due date (no
  daily accrual between due dates), a payoff settles outstanding principal plus interest
  already accrued (no interest for the running period), partial instalments are not
  collected, and there are no late fees, payment holidays, restructuring or recoveries
  after a write-off. Instalments are collected only from the disbursement account. The
  lending business date moves only when someone runs servicing (no scheduler); in the
  dev database it can be moved past today, which then books repayments on that future
  date. The credit bureau is a deterministic function of name and date of birth.
- Workflow definitions are authored in code (registered at import); there is no visual
  designer or upload API. Four business workflows exist (WF-0001 to WF-0004).
- WF-0003 has no AI step yet, so `personal-loans` runs baseline only. Live WF-0002 cases
  run with AI off; the UI offers AI modes only through simulations and experiments.
- The default success thresholds were tuned for account opening; in `domestic-payments`
  even the baseline exceeds the 5 % maximum false approval rate (quiet scams), so
  experiments there fail the compliance-threshold criterion unless the thresholds are
  changed for the scenario.
- Simulation runs write into the same synthetic bank (customers, accounts, ledger postings
  and staff remain); there is no reset command. Simulated reviewers work around the clock;
  arrivals are uniform. Background runs live in the API process, so a restart interrupts
  them (reported as interrupted). See [simulation.md](simulation.md) for measured
  throughput and why the enterprise profile is only a target.
- The workflow runner is a polling CLI process; there is no in-API background scheduler, so
  timeouts and retries fire only while `make workflows` (or the CLI) runs.
- The only AI tool implementation is rule-based; no external model provider is connected
  (an adapter for one implements the same contract). Adapter timeouts cancel async work;
  CPU-bound synchronous code inside an adapter cannot be interrupted.
- The effect of AI advice on reviewers is an assumption of the scenario, not a measurement.
- Costs are estimates from illustrative default assumptions; experiments compare one
  baseline with one candidate on one seed (no repeated-seed statistics or confidence
  intervals yet). The cost model has no time-of-day, overtime or capacity costs.
- Live (non-simulated) WF-0001 cases run v2 with AI off; the UI does not offer AI modes for
  live cases.
- Simulated payers are one fresh customer per case, so the payment velocity signal never
  fires in simulations; it is covered by tests only.
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
- Redis is connected and health-checked but not used by any feature yet.
- `scripts/reset_demo.py` does not exist yet; simulation data accumulates in the
  development database (`docker compose down -v` resets everything).
- Charts are built from plain HTML/CSS (no charting library); only paired-bar charts exist so far.
- The frontend Docker image runs the Vite dev server; a production static image is not yet
  defined.
