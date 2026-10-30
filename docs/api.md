# API contracts

The OpenAPI document generated from the code is the authoritative contract:
`GET /api/openapi.json`, browsable at `/api/docs`. This page explains the conventions
every endpoint follows and lists what exists.

## Conventions

| Concern | Rule |
| --- | --- |
| Versioning | Business endpoints live under `/api/v1/`. Platform health endpoints live under `/api/` so infrastructure probes stay stable. |
| Authentication | `Authorization: Bearer <access token>` from `POST /api/v1/auth/login`. Tokens are HS256 JWTs (default lifetime 60 minutes). The user is re-loaded on every request, so deactivation and role changes apply immediately. |
| Authorization | Each endpoint requires one permission (below). Checked on the server; 403 names the missing permission in `details.required_permission`. |
| Errors | `{"error": {"code", "message", "details", "correlation_id"}}`. Codes: `unauthorized` (401), `forbidden` (403), `not_found` (404), `conflict` (409), `validation_error` (422, malformed input, `details` lists fields), `business_rule_violation` (422, well-formed but breaks a rule), `internal_error` (500, no internal detail). |
| Correlation | Send `X-Correlation-ID` (≤128 chars of `A-Za-z0-9._:-`) or one is generated. It is echoed in the response, logged, and stored on audit events. |
| Idempotency | `POST` create endpoints accept `Idempotency-Key`. Retrying with the same key and body replays the original response (header `Idempotent-Replayed: true`) without side effects. The same key with a different body returns 409. Keys are scoped per user. A request that failed stores nothing, so it can be retried. |
| Pagination | List endpoints take `limit` (1–200, default 50) and `offset`, and return `{"items", "total", "limit", "offset"}`. |
| Filtering | Query parameters per endpoint (below). Free-text `q` is a case-insensitive contains-match. |
| Money | Integer minor units of an ISO 4217 currency (e.g. `8250000` USD = $82,500.00; JPY has no minor unit). Never floating point. |
| Partial updates | `PATCH` changes only the fields sent; send `null` explicitly to clear a nullable field (e.g. `manager_id`). |

## Endpoints

### Platform (public)

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/health` | 200 healthy/degraded, 503 when the database is down |
| GET | `/api/system/info` | Version, environment, module roadmap |
| GET | `/api/system/status` | Database, migration state, Redis |
| GET | `/api/metrics` | Prometheus text: this API process's requests by route and status, latency histograms, job queue, finished jobs per kind, workers, database size. Needs `Authorization: Bearer $ATLAS_METRICS_TOKEN`; 404 when no token is configured or it does not match (Phase 15) |

### Auth, users and roles

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| POST | `/api/v1/auth/login` | public | `{username, password}` → token, expiry, user with permissions. Failures are audited. |
| GET | `/api/v1/auth/me` | signed in | Current user and permissions |
| GET | `/api/v1/roles` | signed in | Roles and the permissions each grants |
| GET | `/api/v1/users?kind=people|service&q=` | `users:read` | Paginated; `is_service_account` marks system principals (simulated staff, the policy engine) that cannot sign in |
| POST | `/api/v1/users` | `users:manage` | Password ≥ 12 characters; idempotent |
| GET | `/api/v1/users/{id}` | `users:read` | |
| PATCH | `/api/v1/users/{id}` | `users:manage` | `display_name`, `role`, `is_active`; administrators cannot demote or deactivate themselves; service accounts keep their role (deactivating the policy engine switches automated approvals off); service roles cannot be given to people |

### Countries

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| GET | `/api/v1/countries` | `countries:read` | Filters: `region`, `operational_status`, `q` |
| POST | `/api/v1/countries` | `countries:manage` | ISO 3166 code, ISO 4217 currency, IANA time zone, language tags; idempotent |
| GET | `/api/v1/countries/{id}` | `countries:read` | |
| PATCH | `/api/v1/countries/{id}` | `countries:manage` | Name, time zone, languages, status. Code, region and currency are fixed once created. |

### Organizations

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| GET | `/api/v1/organizations` | `organizations:read` | Filters: `parent_id`, `root_only`, `organization_type`, `country_id`, `status`, `q` |
| POST | `/api/v1/organizations` | `organizations:manage` | Hierarchy and country rules below; idempotent |
| GET | `/api/v1/organizations/{id}` | `organizations:read` | Includes `child_count`, `employee_count`, inherited `currency` |
| GET | `/api/v1/organizations/{id}/ancestors` | `organizations:read` | Path from the global bank |
| PATCH | `/api/v1/organizations/{id}` | `organizations:manage` | `name`, `status` |

Hierarchy rules: global bank (exactly one, the only root) → regional headquarters (has a
region) → country subsidiary (one per country; the country must be **active** and in the
headquarters' region) → business division → department → team. Region and country are
inherited downward and cannot be overridden. Sibling names are unique. A unit with active
children or staff cannot be deactivated, and nothing can be created under an inactive unit.

### Employees

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| GET | `/api/v1/employees` | `employees:read` | Filters: `q`, `organization_id`, `department_id`, `country_id`, `manager_id`, `employment_status` |
| POST | `/api/v1/employees` | `employees:manage` | Idempotent; see rules |
| GET | `/api/v1/employees/{id}` | `employees:read` | |
| GET | `/api/v1/employees/{id}/direct-reports` | `employees:read` | |
| GET | `/api/v1/employees/{id}/reporting-chain` | `employees:read` | Direct manager upwards |
| PATCH | `/api/v1/employees/{id}` | `employees:manage` | Title, unit (transfer), manager, role, status, compensation |

Rules: staff join a department or a team (`department_id` is derived). Country defaults to
the unit's and must be active; compensation is recorded in that country's currency. Email
addresses are synthetic (`@atlasbank.example`), generated when omitted. A manager must be
an active employee and the reporting line may not form a cycle. An employee with active
direct reports cannot be terminated. `annual_compensation` and `compensation_currency`
are `null` unless the caller has `employees:read_compensation`.

### Customers

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| GET | `/api/v1/customers` | `customers:read` | Filters: `q`, `customer_type`, `country_id`, `risk_rating`, `kyc_status` |
| POST | `/api/v1/customers` | `customers:manage` | Individual or business; active country; date not in the future; idempotent |
| GET | `/api/v1/customers/{id}` | `customers:read` | Includes the country's currency |
| PATCH | `/api/v1/customers/{id}` | `customers:manage` | `name` |
| POST | `/api/v1/customers/{id}/review` | `customers:review` | `kyc_status` and/or `risk_rating`, optional `note`. KYC moves not_started → pending → verified/rejected (and back to pending for re-review); verifying requires a risk rating. |
| GET | `/api/v1/customers/{id}/eligibility?account_type=` | `accounts:read` | `{eligible, reasons[]}` |

### Account opening

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| GET | `/api/v1/account-requests` | `accounts:read` | Filters: `status`, `customer_id` |
| POST | `/api/v1/account-requests` | `accounts:request` | `{customer_id, account_type, currency?}`; eligibility checked; one pending request per customer/type/currency; idempotent |
| GET | `/api/v1/account-requests/{id}` | `accounts:read` | |
| POST | `/api/v1/account-requests/{id}/approve` | `accounts:approve` | Opens the account. Not by the requester (four-eyes, also a DB constraint); high-risk customers need `customers:review`; eligibility re-checked; a second approval returns 409. |
| POST | `/api/v1/account-requests/{id}/reject` | `accounts:approve` | `{reason}`; four-eyes applies |

Eligibility: KYC verified; a risk rating assigned; account type matches the customer type
(individuals: current, savings; businesses: business_current); individuals aged 18+; the
customer's country is active; domestic currency only; no live account of the same type
and currency.

### Accounts

There is no endpoint that creates an account directly.

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| GET | `/api/v1/accounts` | `accounts:read` | Filters: `q`, `customer_id`, `status`, `currency`. `balance` is derived from the ledger. |
| GET | `/api/v1/accounts/{id}` | `accounts:read` | |
| GET | `/api/v1/accounts/{id}/transactions` | `accounts:read` | Posted ledger lines, newest first |
| POST | `/api/v1/accounts/{id}/deposits` | `accounts:transact` | `{amount, memo?}` in minor units; **Idempotency-Key required**; account must be open |
| POST | `/api/v1/accounts/{id}/withdrawals` | `accounts:transact` | Same; no overdrafts (the account row is locked while the balance is checked) |
| POST | `/api/v1/accounts/{id}/freeze` · `/unfreeze` · `/close` | `accounts:manage` | `{reason}`; closing requires a zero balance |

Account numbers: two-letter country code, ten digits and two ISO 7064 MOD 97-10 check
digits (e.g. `US000000004257`). They are synthetic, not IBANs.

### Ledger

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| GET | `/api/v1/ledger/accounts` | `ledger:read` | Chart of accounts with balances (stored totals since Phase 12). Filters: `currency`, `account_type`, `q` (substring of code or name), `code_prefix` (codes starting with it, e.g. `1000-`; Phase 13) |
| POST | `/api/v1/ledger/accounts` | `ledger:post` | `{code, name, account_type, currency}` |
| GET | `/api/v1/ledger/accounts/{id}` · `/statement` | `ledger:read` | |
| GET | `/api/v1/ledger/journal-entries` | `ledger:read` | Filters: `currency`, `source`, `ledger_account_id` |
| POST | `/api/v1/ledger/journal-entries` | `ledger:post` | Manual balanced entry; **Idempotency-Key required**; same key + same body replays (200), different body 409 |
| GET | `/api/v1/ledger/journal-entries/{id}` | `ledger:read` | Lines, `reversal_of_id`, `reversed_by_id` |
| POST | `/api/v1/ledger/journal-entries/{id}/reverse` | `ledger:post` | `{reason}`; posts the opposite entry; **Idempotency-Key required** |
| POST | `/api/v1/ledger/reconciliation` | `ledger:read` | `?mode=full` (default) or `incremental` (entries posted since the previous run, with a 10-minute overlap). Runs the checks below; the run is recorded and audited (Phase 12: `id`, `run_number`, `mode`, `window_start`, `window_end`, `duration_ms`) |
| GET | `/api/v1/ledger/reconciliations` | `ledger:read` | Reconciliation history, latest first: mode, result, failed checks, entries and lines checked, duration, who ran it (Phase 12) |
| GET | `/api/v1/ledger/reconciliations/{id}` | `ledger:read` | One recorded report (Phase 12) |

Reconciliation checks: every entry has ≥ 2 lines and balances; every line uses a ledger
account in the entry's currency; debits equal credits per currency (trial balance); every
reversed entry has a reversing entry; every customer account matches its ledger currency;
stored balances match their lines (Phase 12). Incremental runs limit the entry, currency,
reversal and account checks to the window and compare the stored balances of up to 500
accounts it touched; the trial balance always covers the whole ledger, from the stored totals.

### Payments and loans (Phase 9)

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| GET | `/api/v1/payments` | `payments:read` | Filters: `status`, `account_id`, `q` (number or reference). Debtor and creditor, amount, high-value flag, initiator, approver, journal entry, rejection reason, workflow execution |
| GET | `/api/v1/payments/{id}` | `payments:read` | One payment |
| GET | `/api/v1/loans` | `loans:read` | Filters: `customer_id`, `status`, `q` (number or customer). Pricing, instalment, outstanding balance (from the ledger), underwriter and committee approver |
| GET | `/api/v1/loans/{id}` | `loans:read` | One loan, with its servicing state: instalments paid of total, next due date and amount, days past due, arrears amount and bucket, closed on, written off by |
| GET | `/api/v1/loans/{id}/schedule` | `loans:read` | Repayment schedule: number, due date, principal, interest, instalment, status, paid on (Phase 10) |
| GET | `/api/v1/loans/{id}/payoff-quote` | `loans:read` | Outstanding principal + interest already accrued, and the date it would be booked on (Phase 10) |
| POST | `/api/v1/loans/{id}/repayments` | `loans:repay` | **Idempotency-Key required.** Body `{"instalments": n}` (optional; default all): settles the oldest overdue instalments from the borrower's account. 409 if nothing is overdue, 422 on insufficient funds (Phase 10) |
| POST | `/api/v1/loans/{id}/payoff` | `loans:repay` | **Idempotency-Key required.** Settles the loan early (payoff quote) and closes it as repaid; remaining instalments become `prepaid` (Phase 10) |
| GET | `/api/v1/loans/servicing-runs` | `loans:read` | Servicing runs, latest first; the first one's `as_of` is the lending business date (Phase 10) |
| POST | `/api/v1/loans/servicing-runs` | `loans:service` | Body `{"as_of": "YYYY-MM-DD"}`; optional Idempotency-Key. Accrues interest and collects every instalment due up to `as_of`; 422 if `as_of` is before the business date (Phase 10) |

Write-offs have no endpoint: only the WF-0004 credit-committee approval writes a loan off.
Payments and loans are created only by their workflows (`POST /api/v1/workflows/WF-0002/executions`,
`…/WF-0003/executions`); there is no endpoint that moves money or books a loan directly.

### Background jobs (Phase 14)

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| GET | `/api/v1/jobs` | `jobs:read` | Latest first. Filters: `status`, `kind`. Payload, attempts, result (with `duration_ms` and the `worker` that ran it), last error, schedule, who queued it |
| GET | `/api/v1/jobs/kinds` | `jobs:read` | Registered kinds, their attempts and whether they can be queued by hand |
| GET | `/api/v1/jobs/{id}` | `jobs:read` | One job |
| POST | `/api/v1/jobs` | `jobs:manage` | `{kind, payload}` for kinds marked manual (`ledger.reconcile`, `workflows.run_due`, `lending.service_loans`, `system.ping`); runs as the caller; audited; 202 |
| POST | `/api/v1/jobs/{id}/cancel` | `jobs:manage` | Queued jobs only |
| GET | `/api/v1/job-schedules` | `jobs:read` | Schedules with interval, next run and last job |
| PATCH | `/api/v1/job-schedules/{name}` | `jobs:manage` | `{enabled?, interval_seconds?}` (60 s – 7 days); audited |
| POST | `/api/v1/job-schedules/{name}/run` | `jobs:manage` | Queue the schedule's job now (one active job per schedule); 202 |

### Observability (Phase 15)

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| GET | `/api/v1/observability/overview` | `observability:read` | `process` (version, uptime, job execution mode, slow-query threshold); `requests` per route template of this API process (count, errors, by status class, avg/p50/p95/max ms over the last 1,000); `queue` (due, scheduled later, running, age of the oldest due job); `throughput` per job kind over the last hour (finished, failed, per minute, avg/p95/max ms); `workers` (running, lost — no report for 60 s — or stopped, with counts and the job each holds); `database` (size, connections, cache hit %) |
| GET | `/api/v1/observability/slow-queries?limit=&grouped=` | `observability:read` | Statements over `ATLAS_SLOW_QUERY_MS` from the API and every worker, newest first; `grouped=true` groups by statement and route/job, worst total time first |

`observability:read` is held by administrators and auditors.

Simulation, suite, rerun and experiment starts now queue `simulation.execute` /
`experiment.execute` jobs in the same transaction as the runs; their responses are
unchanged.

### Workflows

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| GET | `/api/v1/workflows?q=` | `workflows:read` | Every workflow, code and stored (latest active version), with `source` and `status` |
| GET | `/api/v1/workflows/{id}?version=` | `workflows:read` | Definition, steps, input schema, presentation, transition/approval/failure/timeout policies |
| GET | `/api/v1/workflows/{id}/export?version=` | `workflows:read` | The definition as an importable JSON document (code or stored) |
| GET | `/api/v1/workflows/{id}/metrics` | `workflows:read` | Per-step runs, completions, failures, retries, avg/p50/p95/max duration; bottleneck step |
| POST | `/api/v1/workflows/{id}/executions` | `workflows:start` | `{input}`; validated against the input schema; optional `Idempotency-Key` (same key → same execution, 200) |
| GET | `/api/v1/workflow-executions` | `workflows:read` | Filters: `workflow_id`, `status`, `outcome`, `business_key`. Live executions only, unless `simulation_run_id` asks for one simulation run's executions |
| GET | `/api/v1/workflow-executions/{id}` | `workflows:read` | Status, outcome, context, error and every step run (attempts, actor, timings, errors) |
| GET | `/api/v1/workflow-executions/{id}/history` | `workflows:read` | Append-only events |
| POST | `/api/v1/workflow-executions/{id}/signals` | `workflows:start` | `{signal, payload}` for a waiting wait-state |
| POST | `/api/v1/workflow-executions/{id}/resume` | `workflows:manage` | Runs due steps now (never passes a waiting approval) |
| POST | `/api/v1/workflow-executions/{id}/cancel` | `workflows:manage` | `{reason}` |
| GET | `/api/v1/workflow-tasks?actionable=` | signed in | Open tasks/approvals with `can_act` and `blocked_reason` for the caller |
| POST | `/api/v1/workflow-tasks/{run_id}/complete` | the step's permissions | `{decision?, data?, note?}`; four-eyes enforced; a task completes once (409 after) |

#### Workflow definitions (Phase 17)

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| GET | `/api/v1/workflow-definitions` | `workflows:read` | Every stored version: status, content hash, importer, executions |
| GET | `/api/v1/workflow-definitions/handlers` | `workflows:read` | The handler library: name, step type, summary, output, `effect`, `requires_approval`, params as JSON Schema |
| POST | `/api/v1/workflow-definitions/validate` | `workflows:define` | `{definition}` → `{valid, workflow_id, version, content_hash, existing, errors[], warnings[], effects}`; stores nothing |
| POST | `/api/v1/workflow-definitions` | `workflows:define` | `{definition}` → 201 `{created, definition, warnings}`; 200 when this exact version is already stored; 422 `definition_invalid` with every error |
| POST | `/api/v1/workflow-definitions/{id}/versions/{v}/retire` | `workflows:define` | No new executions on that version; running ones finish on it |
| POST | `/api/v1/workflow-definitions/{id}/versions/{v}/reactivate` | `workflows:define` | Startable again |

Starting a stored workflow uses the same `POST /api/v1/workflows/{id}/executions`; its input
is checked against the definition's JSON Schema, errors in the same format. Starting a
retired version (or a workflow whose versions are all retired) returns 409.
`workflows:define` is held by platform administrators.

Simulated executions (driven by the Phase 5 simulation engine on simulated time) are kept
out of the task inbox, the metrics and the `run_due` timer sweep; each carries its
`simulation_run_id`.

### Simulations

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| GET | `/api/v1/simulations/scenarios` | `simulations:read` | Registered scenarios with their workload, workflow, modes and full configuration (`retail-onboarding` v1/v2, `domestic-payments` v1, `personal-loans` v1) |
| GET | `/api/v1/simulations/profiles` | `simulations:read` | Workload profiles; `runnable` is false for the enterprise configuration target; `min_shards` is the fewest parallel shards a profile runs with (4 for `large`) |
| POST | `/api/v1/simulations` | `simulations:run` | `{scenario_id, scenario_version?, profile, seed, applications?, employees?}` (sizes only with `profile: custom`, max 10,000 / 500). **202**: the run executes in the background. One run at a time (409 otherwise); the enterprise profile is refused (422); idempotent: a retry with the same key replays the started run and starts nothing |
| GET | `/api/v1/simulations?status=` | `simulations:read` | Run registry, newest first, with progress |
| GET | `/api/v1/simulations/{id}` | `simulations:read` | Configuration, software version, config hash, progress, results, result digest, failure reason and `reproductions` (other completed runs with the same scenario, seed, configuration and software, and whether their results match) |
| GET | `/api/v1/simulations/{id}/cases?kind=&mismatched=` | `simulations:read` | Per-case results next to their ground truth |
| POST | `/api/v1/simulations/{id}/rerun` | `simulations:run` | Same scenario version, profile, sizes, seed, mode and tool (202); idempotent |
| POST | `/api/v1/simulations/suites` | `simulations:run` | `{scenario_id, scenario_version?, profile (small/custom), seed, applications?, employees?, modes, tool_id, tool_version?}`: one run per mode on the same seed and workload, executed one after another (202, returns the runs with their shared `batch_id`); idempotent |

`POST /api/v1/simulations` takes `shards` (1–8, default 1; Phase 16): the run is split
into that many slices, each simulated by a worker process with its own share of every
role's staff (the run's staff must have at least `shards` members of each role, and the
`large` profile — 100,000 applications, 5,000 staff — needs at least 4). The run queues
one `simulation.shard` job per slice; the last to finish merges the results. Run
summaries carry `shards`; run detail adds `shard_progress` (status, cases, events,
worker, wall time and error per shard). The same seed and shard count reproduce the same
results; a different shard count is a different configuration (separate queues per
shard), so its config hash differs. Reruns keep the shard count. Suites and experiments
run single-process.

`POST /api/v1/simulations` also takes `mode` (`baseline`, `ai_assisted`, `ai_automated`)
and, for AI modes, `tool_id` (+ optional `tool_version`, default: highest active). AI
modes need a scenario version that supports them (`retail-onboarding` v2) and an active
tool declared compatible with the scenario's workflow (422 otherwise). The run list
filters by `batch_id` and `mode`.

Phase 15 — workflow history (`simulations:manage`: administrators and AI researchers):

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| GET | `/api/v1/simulations/history` | `simulations:manage` | Rows and bytes per workflow-history partition (live, simulation), runs by `history_state`, archive directory and its size, the last 10 archives, whether the retention schedule is on |
| POST | `/api/v1/simulations/{id}/archive` | `simulations:manage` | Queues `simulation.archive_history` (202, `{job_id, job_number, kind, status}`). Refused (422) unless the run has finished, its history is present and no running experiment uses it. One archive or restore per run at a time |
| POST | `/api/v1/simulations/{id}/restore` | `simulations:manage` | Queues `simulation.restore_history` (202); only for archived history; the files are checked against their SHA-256 first |

Run summaries carry `history_state` (`present`, `archived`, `purged`); run detail adds
`archive` (the archive in effect: kind, rows per table, bytes, who and when). Case results
stay after an archive; their `execution_id` then names an execution that is no longer
stored until the history is restored.

Runs that stop making progress for 5 minutes (the process running them stopped) are
reported as failed with an "Interrupted" reason. See [simulation.md](simulation.md).

### AI tools

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| GET | `/api/v1/ai-tools?status=&workflow_id=` | `ai_tools:read` | Registered tool versions with invocation counts |
| GET | `/api/v1/ai-tools/adapters` | `ai_tools:read` | Implementations with their default input, output and configuration schemas |
| GET | `/api/v1/ai-tools/actions` | `ai_tools:read` | Grantable and never-grantable actions |
| POST | `/api/v1/ai-tools` | `ai_tools:manage` | Register a version (see [ai-testing.md](ai-testing.md#registry) for validation); optional `Idempotency-Key`; 409 for an existing version |
| GET | `/api/v1/ai-tools/{id}` | `ai_tools:read` | |
| PATCH | `/api/v1/ai-tools/{id}` | `ai_tools:manage` | `{status: active | disabled}` — everything else is immutable |
| POST | `/api/v1/ai-tools/{id}/invoke` | `ai_tools:invoke` + the tool's `permissions` | `{action, input}` → the recorded invocation (its `status` says whether it succeeded, failed, timed out or broke a schema). A disabled tool or an action not granted → **403**, and the refused call is still recorded |
| GET | `/api/v1/ai-tools/invocations?tool=&status=&execution_id=&simulation_run_id=` | `ai_tools:read` | Recorded invocations, newest first |

### Experiments and benchmarks

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| GET | `/api/v1/experiments?status=&tool_id=` | `experiments:read` | Newest first, with the two runs' progress and headline changes |
| POST | `/api/v1/experiments` | `experiments:run` | `{name, tool_id, tool_version?, candidate_mode (ai_assisted/ai_automated), scenario_id?, scenario_version?, profile (small/department/custom), applications?, employees?, seed, costs?, thresholds?}` → **202**; runs baseline and candidate, then evaluates; idempotent: a retry replays the experiment and runs nothing again |
| POST | `/api/v1/experiments/from-runs` | `experiments:run` | `{name, baseline_run_id, candidate_run_id, costs?, thresholds?}` → 201, evaluated; 422 when the runs are not an equivalent baseline/candidate pair; idempotent |
| GET | `/api/v1/experiments/{id}` | `experiments:read` | Configuration, raw `measurements`, derived `evaluation` |
| POST | `/api/v1/experiments/{id}/re-evaluate` | `experiments:read` | Recomputes from the stored raw measurements: `{stored_digest, recomputed_digest, matches}` |
| GET | `/api/v1/experiments/{id}/report?format=markdown|json` | `experiments:read` | Downloadable proof-of-concept report; 409 until evaluated |
| GET | `/api/v1/benchmarks` | `experiments:read` | Completed experiments by tool version and configuration: counts, successes, median relative changes, latest verdict |

See [benchmarking.md](benchmarking.md) for metrics, costs and criteria.

### Audit

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| GET | `/api/v1/audit-events` | `audit:read` | Newest first. Filters: `action` (exact or `prefix*`), `entity_type`, `entity_id`, `actor_id`, `correlation_id`, `since`, `until` |

There are no write endpoints for audit events.

### Analytics

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| GET | `/api/v1/analytics/overview` | `analytics:read` (every role) | The dashboard: employees, configured countries, registered workflows, active simulation runs, completed and failed workflow executions, customer accounts, AI tools, completed experiments, average process duration and the estimated simulation operating cost — each with a `detail` saying what it includes, `synthetic` and `estimate` flags — plus live execution outcomes, open tasks, recent runs and experiments |

Every figure is queried from the records at request time. The cost figure applies the
default cost assumptions to every completed simulation run through the experiment
engine's cost function, and is flagged as an estimate.
