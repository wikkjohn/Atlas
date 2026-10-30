# Implementation status

Last updated: Phase 26.

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
| 11 | AI underwriting for personal loans | **Complete** |
| 12 | Scale foundation, step 1: stored balances and incremental reconciliation ([roadmap](roadmap.md) Milestone A) | **Complete** |
| 13 | Scale foundation, step 2: bulk loading, one million customers, search indexes | **Complete** |
| 14 | Scale foundation, step 3: durable background jobs, workers and schedules | **Complete** |
| 15 | Scale foundation, step 4: partitioned workflow history, simulation history archive/reset, observability | **Complete** |
| 16 | Scale foundation, step 5: sharded simulation runs, performance suite, 100,000 applications — roadmap Milestone A complete | **Complete** |
| 17 | Workflow factory, step 1: stored, versioned workflow definitions with an import API and full validation | **Complete** |
| 18 | Workflow factory, step 2: domain step-handler library with declared effects; money moves only behind an approval | **Complete** |
| 19 | Workflow factory, step 3: parameterised templates and a deterministic, versioned variant generator | **Complete** |
| 20 | Workflow factory, step 4: generated path tests for every stored and generated workflow, in CI | **Complete** |
| 21 | Workflow factory, step 5: workflow diagram and an editor with live validation | **Complete** |
| 22 | Workflow factory, step 6: catalogue search, ownership, review lifecycle; the Milestone B exit run — roadmap Milestone B complete | **Complete** |
| 23 | Global footprint, step 1: reference data for 120 countries ([reference-data.md](reference-data.md)) | **Complete** |
| 24 | Global footprint, step 2: multi-currency — FX rates, conversions, cross-currency payments, revaluation ([fx.md](fx.md)) | **Complete** |
| 25 | Global footprint, step 3: country rules engine ([country-rules.md](country-rules.md)) | **Complete** |
| 26 | Global footprint, step 4: business calendars ([business-calendars.md](business-calendars.md)) | **Complete** |

## Phase 26: what exists

- **Dated lunar holidays** for 2025–2030 (`reference/dated.py`): 12 festivals, 257 rules in
  50 countries, with weekend observance; reference data 2026.2 loaded by migration 0023.
- **Schedules on business days:** `job_schedules.business_calendar`; a schedule due on a
  weekend or holiday of its country moves to the next business day without running. Set
  in System Settings → Background jobs or with `PATCH /job-schedules/{name}`.
- **Simulation arrivals on business days:** scenario configuration `business_calendar`;
  new scenario `payments-easter` (UK Easter weekend 2026).

## Phase 26: verified results

PENDING

## Phase 26: known limitations

- Dated holidays cover 2025–2030 only; Islamic dates can move by a day with the moon.
- Scheduler calendars move whole days; simulated staff still work every day.
- Working weekends (China, Vietnam, Korea), bridge days and regional holidays are not
  modelled.

## Phase 25: what exists

- **Versioned rules per country** (`country_rules`, migration 0022): KYC (minimum age,
  accepted identity documents, proof of address), screening (which synthetic sanctions
  lists apply) and payments (cut-off, high-value threshold, single-payment limit).
  Version 1 of all 120 countries comes from defaults derived from the reference data. New
  versions take effect on a date, are never edited, and are audited.
- **Applied by the workflows:**
  - WF-0001 checks the applicant's country's minimum age and documents, and screens
    against its lists;
  - WF-0002 takes the limit, the threshold and the lists from the payer's country.
  - Each payment records its threshold and a value date (cut-off plus the country's
    calendar), and posts with that effective date.
- **Five synthetic sanctions lists.** The library's `compliance.screen_name` takes `lists`.
- **API and UI:** country rules (current, versions, add a version) and sanctions lists. The
  country panel shows the rules and lets managers add a version; payments show value dates.

## Phase 25: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 537 passed (new: 9 — valid defaults for all 120 countries and their spot values; versions take effect on their date, are audited and cannot predate the latest; rules validation; screening across several lists; value dates over the cut-off, weekends and holidays; WF-0001 applying a country's minimum age and accepted documents; a waived proof of address and an EU-style list hit; WF-0002 limits, high-value threshold and value date from the payer's country; the rules API and permissions) |
| Frontend Vitest / typecheck / build | 93 passed (new: the rules in force, versions and a manager's new version) / clean / built |
| Playwright on a fresh database | First run: 27 passed, 1 failed — the new rules test's sign-in landed on the Overview instead of the Countries page (the deep link was lost); it passed twice alone and in the full rerun. Like the Phase 24 shell failure, it occurs only under full parallel load; root cause not yet found (see known limitations). Second run on a fresh database: 28 passed |
| Migration 0022 | Upgrade, downgrade and upgrade again; `alembic check` clean |

## Phase 25: known limitations

- Rules cover individuals' account opening and payments, per payment only (no daily or
  monthly cumulative limits, no business-customer or lending rules yet).
- The five operating countries keep their earlier payment limits (10,000 and 1,000,000
  units of their currency) so earlier simulations reproduce. In Japan that leaves a
  10,000-yen high-value threshold; change it with a new rules version.
- The defaults are compiled for the simulation, not regulatory advice.
- Under full parallel Playwright load, a sign-in has twice (Phases 24 and 25) ended on the
  Overview or the "API unavailable" state instead of the requested page; both passed on
  rerun. The login redirect keeps the requested page in navigation state, so something
  under load replaces it; not yet diagnosed.


## Phase 24: what exists

- **Rates:** deterministic synthetic daily rates (units per US dollar) for all 93
  currencies, with USD and EUR pegs; published to `fx_rates` daily or on first use.
- **Conversions:** quotes at the mid rate less a 0.50 % margin, rounded down to minor
  units. Each conversion posts two balanced entries, one per currency, through
  `FX-POSITION-<CCY>` accounts. Deals (`fx_deals`) are idempotent by key.
- **Cross-currency payments:** WF-0002 accepts payees in any currency. The payee's amount
  is estimated when the payment is created and converted at release. Payments record the
  payee's currency and amount and the deal (a constraint requires it once released). The
  customer is notified of both amounts.
- **Positions and revaluation:** positions valued in US dollars. Revaluation books the
  change to FX income (`fx_revaluations`). The `fx-daily` schedule publishes rates and
  revalues; administrators can revalue by hand (`fx:manage`).
- **UI:**
  - a Foreign Exchange page: rates, quote, positions with *Revalue*, revaluations,
    conversions;
  - the payment form lists payees in every currency, with a live estimate;
  - the Payments list shows the converted amount and the deal.

## Phase 24: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 528 passed (new: 8 — deterministic rates and pegs; idempotent publication; quotes with margin and minor-unit rounding (yen, dinars) and refusals; a conversion posts one balanced entry per currency, replays by key and the ledger still reconciles; revaluation books the margin, nothing more the same day, then the next day's rate move; a WF-0002 payment from USD to a yen account converts at release with its deal, notification and listing; the payer account must match the payment currency; the FX API and its permissions) |
| Frontend Vitest / typecheck / build | 92 passed (new: the Foreign Exchange page — rates, quote, positions and revaluation; the payment form's conversion estimate) / clean / built |
| Playwright on a fresh database | First run: 25 passed, 2 failed. The new multi-currency test assumed a funded US-dollar account among the accounts listed and found none; it now takes any funded account and a payee in another currency. The existing "backend unreachable" shell test failed once under the full parallel run and passed in every rerun (twice alone, then in the full run); not changed. Second run on a fresh database: 27 passed |
| Migration 0021 | Upgrade, downgrade and upgrade again on the development database; `alembic check` clean |

## Phase 24: known limitations

- One margin for every pair and size; spot only (no forwards or swaps); daily rates.
- Positions valued in US dollars only; no reporting currency per subsidiary.
- Customers cannot convert between their own accounts outside a payment.


## Phase 23: what exists

- **Reference data** (`app/modules/reference/`, version 2026.1) for the 120 countries:
  - ISO codes, calling codes, currency and minor units (`currencies`, 93 currencies);
  - time zone, languages, weekend days and banking regulator;
  - identity documents and passports with number masks;
  - address layouts with postal-code masks;
  - 1,167 holiday rules, with the Western or Orthodox Easter and the observance of weekend holidays.
- **Loading:** migration 0020 loads a frozen snapshot. It adds the `currencies` table (with
  a foreign key from `countries`), fills the reference columns of the 5 operating
  countries and adds 115 planned ones. `reference load` re-applies the data idempotently
  without touching operator-managed fields.
- **Calendars:** holidays and observed days off for any year from 1980 to 2099; business days
  and the next business day.
- **Formats:** masks validate and generate document numbers and postal codes; addresses are
  formatted in each country's layout. Synthetic samples are deterministic per seed.
- **API:** `/currencies`, plus four endpoints per country: `calendar`, `business-day`,
  `check` and `samples`. A new country must use a known currency.
- **Elsewhere:** `app.core.money` reads minor units from the reference data; templates
  get the new `{{country.*}}` fields.
- **UI:** the Countries page filters by status and searches by name or code. Each country
  opens to its reference data, the holiday calendar by year, a format checker and
  synthetic samples.

## Phase 23: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 520 passed (new: 131 — the dataset (120 countries, 4 regions), each country's consistency (one test per country: codes, currency, time zone, languages, masks with examples, a decade of computable holidays), ISO 4217 minor units through `money`, both Easter computuses, holiday rules and weekend observance, weekends of Friday–Saturday and Friday–Sunday, masks and address layouts, the migration snapshot equals the dataset, the database contents, an idempotent reload that keeps operator fields, the reference API, a new country needing a known currency). Writing the per-country test found a duplicated holiday name in China's data, fixed before commit |
| Frontend Vitest / typecheck / build | 91 passed (new: a country's reference data, calendar, format check and samples) / clean / built |
| Playwright on a fresh database | 26 passed, first run (new: Saudi Arabia found by region, status and search; its weekend, regulator, 2026 calendar and a postal-code check) |
| Migration 0020 | Upgrade, downgrade and upgrade again on the development database; `alembic check` clean |

## Phase 23: known limitations

- Lunar-calendar holidays (Islamic, Chinese, Hindu, Buddhist, Jewish), state and provincial
  holidays, bridge days and make-up working weekends are not computed. Business calendars
  that take dated tables are a later Milestone C step.
- Masks give the shape of document numbers and postal codes, not check digits.
- Regulators and holidays are compiled for the simulation, not from an authoritative feed.
- The scheduler and the simulation do not yet use the calendars; that is the business
  calendars step.


## Phase 22: what exists

- **Catalogue** (`workflow_catalogue`, migration 0019): department, countries, products,
  tags and owner per workflow — from a definition's or template's `catalogue` block, by hand
  (`PUT /workflow-catalogue/{id}`, *Classify*), or registered in code for WF-0001–0004.
  `GET /workflow-catalogue` searches by text and facets with counts; the Explorer filters by
  department, country, product and status.
- **Review lifecycle:** API and editor imports are drafts; submit → approve (four-eyes, the
  version's latest generated tests must pass) or return with a note; retire/reactivate.
  Drafts can be tested but not started. Department managers hold `workflows:define`.
  *Versions and review* panel in the Explorer; `workflows import --publish` for operators.
- **Parallel generated tests:** `workflows test --processes N`.
- **TPL-PAPER-STATEMENT v2** classifies its variants by country and product; the seed
  classifies WF-1001/WF-1002.

## Phase 22: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 389 passed (new: 10 — review to active under four-eyes and passing tests; return with a note; a draft does not reclassify an active workflow; department managers define; catalogue validation; hashes without a catalogue; code workflows classified and searchable; facets counted over the other filters with paging; the catalogue and review API; the seed classification is valid) |
| Frontend Vitest / typecheck / build | 90 passed (new: facet filters; submit, refused self-approval, return with a note; classification with an owner) / clean / built |
| Playwright on a fresh database | 25 passed, first run (new: WF-1001 edited, saved as a draft, submitted, tested, refused to its author and approved by a manager; variants found by country, product and department) |
| Milestone B exit run (`workflows test --all --processes 4`, 5,052 stored workflows) | 111,168 cases, 0 failed, 100 % step and route coverage, 5,381.6 s; 50 → 54.7 s, 500 → 604.6 s (linear) |

## Phase 22: known limitations

- Catalogue search builds every summary per request (0.37 s at 5,056 workflows); at tens
  of thousands it will want facet counts in SQL.
- One department, a country list and a product list per workflow; no per-country owners.
- Approval is by any holder of `workflows:define` other than the author; there is no
  routing of reviews to the owning department yet.
- Generated tests remain the only automatic gate; the exit run took 1 h 30 min on four
  processes, so CI tests the seeded bank, not the 5,000.

## Phase 21: what exists

- **Diagram for every workflow** (`workflows/graph.py`, `GET /workflows/{id}/graph`): a
  layered layout computed on the server (back routes, longest-path layers, barycentre
  ordering), labelled routes (approved/rejected, conditions, otherwise, on failure,
  timeouts), live step metrics with the bottleneck, and the latest generated tests'
  coverage per route; drawn as SVG in the Workflow Explorer's *Diagram* view.
- **Editor for stored workflows** (*Edit as v{n+1}*): a step form (name, type, library
  handler, next, params) and the JSON kept in step; add/remove steps; a live preview
  (`POST /workflow-definitions/preview`) validates and draws the draft, with problems shown
  on the step they belong to; saving imports through the usual validation. Generated
  variants are edited through their template, not here.

## Phase 21: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 379 passed (new: 4 — layers follow the routes with unique places and labels; WF-0001's documents loop as the one back route; metrics and coverage overlays incl. an uncovered route; the preview validates, draws drafts with errors, and refuses unparseable ones) |
| Frontend Vitest / typecheck / build | 87 passed (new: the diagram with coverage; the editor's located problems, form edit, live re-validation and save) / clean / built |
| Playwright on a fresh database | 24 passed (new: WF-1002's diagram; WF-1001 edited through a diagram click and saved as its next version). One run failed first on the test itself (a truncated step name and the SVG tooltip both matched); the locator was fixed and the full suite re-run green |

## Phase 21: known limitations

- The layout is simple (no edge routing around nodes); large workflows (dozens of steps
  per layer) become wide. Long step names are shortened on the diagram (full in tooltips).
- The editor edits steps' common fields in the form; transitions, approval policies and
  timeouts are edited in the JSON. No drag-and-drop.
- Code workflows can be viewed but not edited (they change in code).

## Phase 20: what exists

- **Generated path tests** (`workflows/testing.py`): for each stored definition, a happy
  case, one case per route (transitions, fallbacks, `on_failure`, timeouts) planned along
  the shortest path with its conditions solved together, approval cases (initiator and
  outsider refused), and no-route probes at decisions without a fallback. Inputs come from
  the schema; looked-up records (customer, funded account) are created from the library
  handlers' declared fixtures; staff are created per run. Cases run in rolled-back
  savepoints; checks: a clean ending, the planned path visited, a declared outcome, no money
  moved without a granted approval, refusals.
- **Coverage and records:** step and route coverage, uncovered routes with reasons;
  `workflow_test_runs` (migration 0018); `last_test` on stored definitions.
- **Interfaces:** CLI `workflows test --all | --template | WF-ID … [--sample] [--output]`
  (non-zero exit on failure); CI job *Workflow factory (generated tests)*; API run/list;
  the Explorer's *Generated tests* panel.

## Phase 20: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 375 passed (new: 7 — route planning incl. solved conflicts, fallbacks, rejects and injected failures; input synthesis and fixture inference; WF-1002 fully covered with refusals and nothing left behind; a generated variant with a steered product check; **defects found**: an input matching no route (probe) and a step reading the wrong record; run records and the API) |
| Migration 0017 → 0018 → 0017 → 0018, `alembic check` | clean |
| Frontend Vitest / typecheck / build | 85 passed / clean / built |
| Playwright on a fresh database | 23 passed (new: running WF-1002's generated tests from the catalogue) |
| `workflows test --all` on a freshly seeded bank (what CI runs) | 12 workflows, 288 cases, 0 failed, 100 % steps and routes each, 37.6 s |
| Scale sample: 100 variants of TPL-SCALE-STATEMENT | 0 failed, 296 s (about 3 s per workflow, single process) |

## Phase 20: known limitations

- About 3 s per workflow in one process: all 5,040 scale variants would take about 4 hours,
  so CI tests the seeded set; a template's variants differ only in parameters, so sampling
  (`--sample`) or sharding across workers is the way to the full set (not built yet).
- Code-registered workflows (WF-0001–0004) are not covered: their inputs are Pydantic
  models with domain documents, and they keep their hand-written tests.
- Planning steers single-level paths; nested input conditions, negated compound
  conditions and conflicting requirements leave a route uncovered (reported).
- Route coverage counts a route covered when a passing case planned through it.

## Phase 19: what exists

- **Templates** (`workflow_templates`, migration 0017): a definition body with typed
  `{{param}}` placeholders, country reference data (`{{country.currency}}` …), minor-unit
  conversion (`{{fee|minor}}`) and optional steps (`$include`, routed around when off), a
  parameter JSON Schema, an example and an id range. Import validates the template and
  renders its example through the full definition validation. Versions are immutable.
- **Variant generator:** grid × explicit variants over fixed values; one stored definition
  per parameter set, with a stable workflow id per variant key (`workflow_variants`), new
  versions only for changed content, all-or-nothing, dry run. Generated definitions carry
  `origin`; only the generator sets it, and variants cannot be imported by hand.
- **Interfaces:** `/api/v1/workflow-templates` (list, detail, variants, validate, import,
  render, generate, retire/reactivate); `GET /workflows` filters `source`, `template_id`,
  `limit`; CLI `workflows templates | import-template | generate`; the Workflow Explorer's
  Templates tab (parameters, variants, generate with preview) and template badges.
- **TPL-PAPER-STATEMENT** (WF-1002 as a template), imported by `seed-demo` with ten
  variants WF-2000–2009 (five countries × current and savings).
- **Scale:** 5,040 variants of one template generated (4,500 new in 52.5 s); 5,056
  registered workflows; two slow paths found and fixed (definition detail 0.27 → 0.015 s,
  dashboard 2.6 → 0.05–0.13 s); the catalogue summarises stored definitions in SQL.

## Phase 19: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 368 passed (new: 10 — rendering types, text, country data, minor units, optional steps; located render errors; example template clean; template validation incl. the rendered example's approval rule; immutable versions; generation deterministic in any input order (found a real ordering bug, fixed), idempotent, versioned on template change, skipping held ids; all-or-nothing, dry run, range full, limit, retired; variants owned by their template and `origin` reserved; a GB variant charging 500 and a US variant refusing a GB account; the API) |
| Migration 0016 → 0017 → 0016 → 0017, `alembic check` | clean |
| Code definition hashes | unchanged (`origin` is optional and omitted when unset) |
| Frontend Vitest / typecheck / build | 84 passed / clean / built |
| Playwright on a fresh database | 22 passed (new: the Templates tab — 10 seeded variants, a preview finding all unchanged, the Japanese variant's 5 JPY fee step) |
| Scale (CLI, demo database) | 60 / 540 / 5,040 variants: 0.6 / 5.4 / 52.5 s; dry run of 5,040 in 33.4 s; see `docs/performance.md` |

## Phase 19: known limitations

- The full catalogue response is 2.5 MB at 5,000 workflows; the UI asks for the first 200
  and relies on search. Catalogue facets (department, country, product) are a later step.
- Variants are not yet tested automatically per path; that is Milestone B step 4.
- One template renders one definition shape; templates do not compose or inherit.
- Generation runs in the request (at most 1,000 sets per API call; the CLI is unlimited);
  it is not a background job yet.

## Phase 18: what exists

- **Domain handlers** for stored definitions: `customers.lookup`, `customers.notify` (real
  notification rows, `{path}` templates), `customers.set_risk_rating`,
  `compliance.screen_name` (the WF-0001/0002 watchlist, now in `compliance/screening.py`),
  `accounts.lookup` (ownership check, balance), `accounts.charge_fee` (debits the account,
  credits `FEE-INCOME-<ccy>`, no overdraft, idempotent per step run) and `ai.review` (an AI
  task through the invocation service; escalates when no usable answer comes back).
- **Declared effects** (reads, writes, moves money, advisory) in the handlers API, the
  validation report (`effects`) and the Workflow Explorer (badges per step, a summary when
  validating).
- **Approval before money:** validation refuses a definition in which a money-moving
  handler is reachable without passing an approval's approve route (skipping the approval,
  its reject route, or a condition unrelated to the decision all count as unapproved).
  Also new: handler-kind checks for service vs. AI steps, database checks (the AI tool
  exists and may perform the action).
- **Examples:** WF-1001 v2 (finds and screens the customer, writes to them) and WF-1002
  Paper Statement Request (fee after four-eyes approval), imported by `seed-demo`.

## Phase 17: what exists

- **Stored definitions.** Workflow definitions can be imported as JSON next to the ones in
  code (`workflow_definitions.source = 'stored'`, migration 0016). Any process loads them
  from the database on first use. Versions are immutable; a version is `active` or
  `retired` (no new cases; running ones finish on it). Code definitions are unchanged:
  their content hashes are pinned by a test.
- **Full validation** before anything is stored, every problem with a location: graph and
  termination, ownership (no code workflow ids), version rules, handler names and params,
  the context paths conditions and handlers read, approval permissions and four-eyes
  references, the input JSON Schema, waiting rules; plus warnings.
- **Handler library** (`core.set_values`, `copy_values`, `check`, `business_key`,
  `notify`, `set_outcome`) with params models published as JSON Schema.
- **Interfaces:** `/api/v1/workflow-definitions` (list, handlers, validate, import,
  retire, reactivate), `GET /api/v1/workflows/{id}/export`, permission `workflows:define`
  (administrators); CLI `workflows list|validate|import|export`; Workflow Explorer badges,
  import dialog with every problem listed, start form generated from the input schema,
  export, retire/reactivate.
- **WF-1001 Customer Address Change**, imported by `seed-demo`: routing by reason,
  colleague or compliance four-eyes approval, `on_failure` route, synthetic letters.

## Phase 18: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 358 passed (new: 10 — library effects; examples valid with effects; approval rule: skipped approval, reject route, unrelated condition refused, `decision == approve` accepted (mutation-checked); handler kinds, params and AI-tool checks; AI advice and safe escalation; fee charged once after approval with income credited, letter text, retry replays the posting (mutation-checked); e-mail, declined, another customer's account, unknown customer; insufficient funds; WF-1001 v2 with screening to compliance and unknown customer; risk rating and the handlers/validate API). Two Phase 17 assertions updated for the intended changes (AI steps allowed; `effects` in reports) |
| Code definition hashes | unchanged (WF-0001 and WF-0002 now import the shared watchlist; their definitions did not change) |
| Frontend Vitest / typecheck / build | 83 passed / clean / built |
| Playwright on a fresh database | 21 passed (new: WF-1002 fee after approval; WF-1001 test now on v2 with a real customer) |
| Live check | Re-seeding a Phase 17 database added WF-1001 v2 and WF-1002; a WF-1002 case over HTTP charged 5.00 only after the manager approved (balance −500), and a full ledger reconciliation passed |

## Phase 18: known limitations

- Customers have no address fields, so WF-1001 v2 still keeps the new address in the case.
- Domain handlers act as the system; the approver is recorded on the approval step, not on
  the posting itself.
- `ai.review` passes context values to the tool as they are; mapping into a tool's nested
  input needs that structure in the case input.
- No payment, loan or account-opening handlers yet; those workflows remain in code.

## Phase 17: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 348 passed (new: 10 — code hashes unchanged; example valid and clean; every problem reported at once with locations; ids, triggers, people and schemas; warnings do not block; immutable, increasing versions and audit; a stored workflow end to end with four-eyes, `on_failure`, JSON-Schema input errors and a cold cache (another process); retire/reactivate with a new version taking new cases; export round trip; the API) |
| Migration 0015 → 0016 → 0015 → 0016, `alembic check` | clean |
| Frontend Vitest / typecheck / build | 83 passed / clean / built |
| Playwright on a fresh database | 20 passed (new: WF-1001 from the generated form through colleague approval to `updated`, and an administrator validating its next version) |
| Live check | WF-1001 started over HTTP, its compliance task completed by a separate process with nothing in memory; dashboard counts 5 workflows, 7 definition versions |

## Phase 17: known limitations

- Stored definitions use library handlers only: they cannot change banking records, call
  AI tools, run on schedules or drive simulations yet (WF-1001 records the approved address
  in the case, not on the customer). Milestone B step 2 extends the library.
- Defining is administrators-only (`workflows:define`); there is no draft state or
  review/approval of a definition before it becomes active.
- The start form handles flat schemas (strings, numbers, booleans, enums); nested objects
  and arrays need the API.
- Validation checks that a path's first segment exists, not that an earlier step's output
  has that field or that the step runs before the read.

## Phase 16: what exists

- **Sharded simulation runs.** `shards` (1–8) splits a run's cases (`case_index % shards`)
  and, round-robin per role, its staff into slices; each slice is a `simulation.shard`
  job any worker process runs; the last to finish merges the results (migration 0015,
  `simulation_shards`). Same seed and shard count, same digest; outcomes match a
  single-process run, queueing does not (each shard has its own team). The `large`
  profile (100,000 applications, 5,000 staff) needs at least 4 shards. API `shards`,
  `shard_progress`; `simulate --shards N`; start form and per-shard progress in the UI.
- **No deadlocks between shards.** The stored-balance trigger now honours
  `SET LOCAL atlas.balance_shard`; each shard pins its own balance row of every account
  (hence at most 8 shards). Without it, parallel payment shards deadlocked on the cash
  account.
- **Performance suite** (`python -m app.cli perf [--quick]`, `make perf`): ledger postings,
  API p95 latency, job throughput, simulation throughput single and sharded, each against a
  recorded target; JSON results; a CI job runs the quick profile on every push.
- **Docker Compose:** the worker service runs 4 processes (`ATLAS_WORKER_PROCESSES`), is
  marked as a worker, and forwards SIGTERM so each process finishes its job on `docker
  stop`.
- **Fixed along the way:**
  - Request transactions committed *after* the response was sent (FastAPI's default
    scope for yield dependencies): a client refetching at once could read the state from
    before its own write — the cause of the end-to-end tests' intermittent "approved but
    still listed" failures since Phase 11 — and a failing commit was reported as success.
    The session dependency now uses `scope="function"`; a test checks the order.
  - The dashboard (and the Phase 15 archive summary) failed once a payments simulation
    existed: simulated business keys were all cast to customer ids, but WF-0002 keys
    payments by payment number.
  - `SimulationSetupError` is a 422 business-rule error like the other refusals to start.

## Phase 16: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 338 passed (new: 6 shard tests — shard order does not change the digest and outcomes match a single run, staff dealt round-robin with nobody in two shards (mutation-checked), merge happens once, a failing shard fails the run and stops the others, staff and shard-count validation, pinned balance row; API with profiles, reruns and inline shards; 3 performance-suite tests; the dashboard with a payments simulation (fails without the fix); the transaction committing before the response (fails without the fix)) |
| Migration 0014 → 0015 → 0014 → 0015, `alembic check` | clean |
| Single-process results unchanged | a 300-case run reproduced its pre-change digest exactly |
| Sharded workloads | retail, payments and loans each twice in 8 shards with identical digests; full reconciliation passed |
| Frontend typecheck, Vitest, build | clean; 81 passed (new: the large profile's minimum shards and per-shard progress); succeeds |
| Playwright, fresh database (inline jobs) | 19 passed (new: a run in 2 parallel shards) |
| Docker Compose | `validate_system.py` 10/10; a 4-shard run spread over the 4 worker processes with the same digest twice; graceful stop of all 4 processes; Playwright 19 passed |
| Performance suite | full and quick profiles pass locally; quick profile passes in CI |

Measured: see [performance.md](performance.md) — 2,000 cases in 334 s on one process and
80 s on 4 shards (4.2×); the department profile in 6 min 39 s twice with identical
digests; **100,000 applications in 73 min 18 s** on 8 shards (22.7 cases/s, 96.65 %
accuracy), archived in 3 min 37 s.

## Phase 15: what exists

- **Partitioned workflow history** (migration 0013): executions, step runs and events are
  LIST-partitioned into `live` and `simulation`; keys `(id, realm)`; queries that know
  their realm read one partition; live history can never be deleted.
- **Archive, restore, reset of simulation history** (`app/simulation/history.py`):
  per-run archive to compressed COPY files with a checksummed manifest (results and case
  outcomes stay; the dashboard keeps counting the run), restore, reset of all simulation
  history by dropping the partitions, archive of runs older than N days and a (disabled)
  retention schedule. As background jobs from the API (`simulations:manage`, new: held by
  administrators and AI researchers), and `python -m app.cli simulation-history
  status|archive|restore|reset`.
- **Observability** (`app/observability`): request counts and latency by route template,
  the slow-query log from the API and every worker (`slow_queries`, threshold
  `ATLAS_SLOW_QUERY_MS`), the worker registry (`job_workers`), queue depth and lag, job
  throughput per kind, database size; `GET /api/v1/observability/overview` and
  `/slow-queries` (`observability:read`, new: administrators and auditors); Prometheus text
  at `/api/metrics` behind `ATLAS_METRICS_TOKEN`.
- **UI:** System Settings gains Observability and Simulation history panels; the
  Simulation Center run view shows where the run's history is and archives or restores it.
- **Found with the new slow-query log:** the dashboard's per-run timeout count scanned
  every event (≈ 200 ms at 100,000 simulated cases); a partial index brought the whole
  overview from ~340 ms to ~140 ms.
- **Docker Compose:** a shared `simulation-archive` volume for the API and the worker;
  `ATLAS_SLOW_QUERY_MS` and `ATLAS_METRICS_TOKEN` pass through.

## Phase 15: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 327 passed (new: 9 history tests — realm routing and the realm/run check, archive then restore returns every row exactly (compared column by column), dashboard costs unchanged by an archive, refusals (unfinished, twice, not archived), corrupted file refused by checksum, live events undeletable even with the purge setting and simulation events undeletable without it, reset keeps the live bank and new runs work on the recreated partitions, reset with archive and its refusal while runs are active, retention by age, API with jobs and permissions; 5 observability tests — routes counted by template not raw path, slow statements logged without parameters, overview with worker and throughput and grouped slow queries, worker registry, Prometheus endpoint and its token) |
| Migrations | `alembic check` clean; 0012 → 0014 → 0012 → 0014 on an empty database; 0014 → 0012 → 0014 on 100,000 simulated cases (downgrade 25 s, upgrade 40 s, every row and the event sequence kept) |
| Frontend typecheck, Vitest, build | clean; 80 passed (new: Observability panel, Simulation history panel, archive from the run view); succeeds |
| Playwright, fresh database (inline jobs) | 18 passed (new: archive a run's history and restore it; administrators see observability and simulation history) |
| Docker Compose with the worker service | archive and restore ran in the worker container with the files in the shared volume; CLI reset in the worker container; `/api/metrics` 404 without a token and served with one; Playwright 18 passed |

Measured in the development container on 100,000 simulated cases (100,236 executions,
1.6M step runs, 5.1M events, 2.4 GB):

| Measurement | Before | After |
| --- | ---: | ---: |
| Live executions list / task inbox / WF-0001 metrics / timer sweep | 3.4 / 3.3 / 4.4 / 2.5 ms | 3.9 / 3.7 / 4.7 / 2.0 ms (unchanged: indexes were enough) |
| Remove one run's history | row-by-row DELETE: events 24 s, step runs > 10 min (stopped) | reset 5.0 s; archive 119 s (to 519 MB of files) |
| Restore an archived run | — | 562 s |
| Enterprise overview (dashboard API) | ~340 ms | ~140 ms (partial index on timeout events) |
| Migration 0013 | — | 41 s up, 25 s down |

## Phase 14: what exists

- **Durable job queue** (`jobs`, migration 0012) in PostgreSQL: queued in the caller's
  transaction, claimed with `FOR UPDATE SKIP LOCKED`, heartbeats, retries with
  exponential backoff, recovery of jobs whose worker stopped, dedupe keys.
- **Worker** (`python -m app.cli worker [--processes N] [--drain] [--no-schedules]`,
  `make worker`, a `worker` service in Docker Compose).
- **Schedules** (`job_schedules`): incremental reconciliation every 15 minutes, full
  reconciliation daily, workflow timers every minute, loan servicing daily (off by
  default), run as the new `atlas-scheduler` service account (`system_scheduler` role).
- **Simulations and experiments are jobs**: queued with their runs in one transaction; run
  by a worker, or by the API itself when `ATLAS_JOBS_EXECUTION=inline` (the default
  outside Docker Compose).
- **API and UI:** jobs, kinds, schedules (switch, change, run now), cancel; a Background
  jobs panel in System Settings. New permissions `jobs:read` (administrators, auditors)
  and `jobs:manage` (administrators).

## Phase 14: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 313 passed (new: 9 job tests — run once with a result, dedupe keys, retry with backoff then success, permanent failure, recovery of a lost worker whose late report is ignored (mutation-checked), at most one job per schedule, four parallel workers sharing 120 jobs with real commits and none run twice, reconciliation and servicing jobs including the scheduler principal and the skip rule, API permissions, schedule changes, run-now, manual kinds only, cancel) |
| Migration 0011 → 0012 → 0011 → 0012, `alembic check` | clean |
| Frontend typecheck, Vitest, build | clean; 77 passed (new: the Background jobs panel, interval wording); succeeds |
| Playwright, fresh database (inline jobs) | 16 passed; the simulations and experiments it starts ran as jobs |
| Docker Compose with the worker service | `validate_system.py` 10/10; the worker ran the schedules on start; Playwright 16 passed with every simulation and experiment run by the worker container |

Queue throughput in the development container (5,000 `system.ping` jobs, `worker --drain`,
including process start-up):

| Worker processes | Throughput | Jobs per process |
| ---: | ---: | --- |
| 1 | 117 jobs/s | 5,000 |
| 4 | 379 jobs/s | 1,256 / 1,252 / 1,249 / 1,243 |

The queue costs about 8 ms per job (claim, load, heartbeat thread, completion); real jobs
are dominated by their own work.

## Phase 13: what exists

- **Bulk posting** (`ledger.post_entries`): batches of entries through PostgreSQL COPY with
  the same rules as single postings (checked in Python, again by the database's triggers),
  idempotent replays, all or nothing, one audit event per batch. `bench-ledger --bulk`.
- **Bulk population** (`python -m app.cli load-population --customers N`): KYC-verified
  customers, approved four-eyes account requests, open accounts and opening deposits in
  COPY batches, deterministic by seed.
- **Search and sort indexes** (migration 0011, `pg_trgm`), account and loan searches
  rewritten so each table's index is used, and `code_prefix` on the chart of accounts
  (the General ledger's cash-account list uses it).
- **Measured at one million customers** (below), which is the first part of Milestone A's
  exit test.

## Phase 13: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 304 passed (new: 5 bulk-loading tests — bulk and single postings agree, replays, a conflicting key refuses the batch, rules applied to the whole batch, the database refusing an unbalanced COPY with the Python checks off, a complete four-eyes population with balances matching its deposits and seed-determined names, the loader's refusals; 2 search tests — account search by number or name, an escaped code prefix) |
| Migration 0010 → 0011 → 0010 → 0011, `alembic check` | clean; 13 s to build the indexes on one million customers |
| Frontend typecheck, Vitest, build | clean; 75 passed; succeeds |
| Playwright (Chromium, real backend, fresh database) | 16 passed |

Measured in the development container:

| Measurement | Result |
| --- | ---: |
| Posting 10,000 entries: single / bulk | 227 / 4,204 entries per second |
| Loading 1,000,000 customers (5 countries, batches of 10,000) | 1,193 s, 838 per second (about 920/s at the start, 800/s at the end); database 2.2 GB |
| Full reconciliation over 1,000,312 entries / 2,000,624 lines | 34.6 s, passed |
| Incremental reconciliation over 40,000 recent entries | 1.1 s, passed |

API at one million customers (median of five, including authentication and JSON):

| Request | Before 0011 | After |
| --- | ---: | ---: |
| Customers, first page / search by name / by number | 24 / 218 / 655 ms | 27 / 43 / 25 ms |
| Accounts, first page / exact number / customer name | 395 / ~440 / ~420 ms | 24 / 21 / 431 ms |
| Account requests, first page | 532 ms | 27 ms |
| Cash accounts (General ledger) | 257 ms (`q=1000`) | 6 ms (`code_prefix=1000-`) |
| Journal entries, first page; analytics overview | 38; 27 ms | 38; 29 ms |

Broad substring searches that match a large share of a table (a common surname, a
fragment every account number shares, `q=1000` on the chart of accounts) still take
0.4–0.8 s; trigram indexes help selective searches, not those.

## Phase 12: what exists

- **Roadmap** ([roadmap.md](roadmap.md)): the remaining work towards the long-term vision,
  in milestones A–H with exit tests. Phase 12 is the first step of Milestone A.
- **Stored balances** (`ledger_balances`, migration 0010): running debit and credit totals
  per account in eight shards, maintained by a trigger on every journal line in the same
  transaction, guarded against any other write, backfilled from existing lines. All
  balance reads (accounts, payments, loans, servicing, the chart of accounts) use them.
- **Incremental reconciliation** (`POST /api/v1/ledger/reconciliation?mode=incremental`):
  the entries posted since the previous run (10-minute overlap), the trial balance from
  the stored totals and the stored balances of up to 500 touched accounts. Full runs also
  compare every account's stored totals with its lines.
- **Reconciliation history** (`ledger_reconciliations`, `GET /api/v1/ledger/reconciliations`):
  every run, its mode, result, failed checks and duration; shown under the General ledger.
- **Benchmark** (`python -m app.cli bench-ledger`): posts synthetic entries through the
  normal ledger service and times balance reads and reconciliation.

## Phase 12: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 297 passed (new: 4 — stored balances follow 40 postings and a reversal and match the line sums across shards; direct insert / update / delete / truncate refused; full and incremental runs recorded, listed and readable, incremental window after the previous run; a drifted stored balance caught by both modes) |
| Migration 0009 → 0010 on a copy of the seeded dev database | backfill matches the lines for all 127 accounts; downgrade and upgrade clean; `alembic check` clean |
| Frontend typecheck, Vitest, build | clean; 75 passed; succeeds |
| Playwright (Chromium, real backend, fresh database) | 16 passed; the banking journey now runs a full and an incremental reconciliation |
| Docker Compose stack | `validate_system.py` 10/10 (migration head 0010, v0.12.0); `bench-ledger` in the container: balances agree, both modes pass |

Measured with `bench-ledger` in the development container (5,001 accounts, 100,000 entries,
half of all lines on one hot account; medians):

| Measurement | Before (sum of lines) | After (stored totals) |
| --- | ---: | ---: |
| Balance of the hot account (49,985 lines) | 7.66 ms | 0.56 ms |
| Balances of 200 ordinary accounts (~20 lines each) | 5.21 ms | 5.33 ms |
| Reconciliation after 1,000 new entries on a 103,312-entry ledger | 1,006 ms (full) | 88 ms (incremental) |
| Posting rate, trigger on / off (two runs each, 5,000 entries) | 203 / 210 entries/s off | 207 / 184 entries/s on |

Stored totals keep a busy account's balance read constant as its history grows; ordinary
accounts with few lines gain nothing. The trigger's cost is within run-to-run noise; the
posting rate (about 200 entries per second) is set by the per-entry ORM and audit work, the
next item of Milestone A.

## Phase 11: what exists

- **AGB Credit Underwriting Assistant** (`rule_based_credit_underwriting`, registered by
  the seed for WF-0003): declared income against the bureau's income estimate, bureau
  file and affordability → risk, explanation, approve / reject / escalate. New grantable
  action `analyze_credit_application`; `approve_loan` stays forbidden.
- **Synthetic income estimate** (`lending.income_estimate`): a deterministic monthly
  income per synthetic person, like the bureau score.
- **WF-0003 v2:** income verification, an advisory AI step for referred applications
  (off / assisted / automated) and the `low-risk-loan-underwriting-v1` policy. Live
  applications run v2 with AI off.
- **`loans:approve_low_risk`** (policy engine only): the lending service lets it
  underwrite loans up to 15,000 that need no committee, and nothing else; the simulation's
  control check applies the same rule.
- **`personal-loans` v2** with AI modes, so experiments run on loans; v1 is unchanged.
- **UI:** the AI Lab console offers the assistant a sample referred application.

## Phase 11: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 293 passed (new: 6 — the assistant's rules and blind spot, v2 income check with AI off, automated underwriting of small clean loans only (inflated income, above the automation limit and self-employed go to a person), the lending service limiting the policy engine to the automation limit, scenario v2 against its workload, an automated experiment that rejects every inflated income and is evaluated successful with no violations) |
| Ruff lint + format check; `alembic check` | clean (no schema change in Phase 11) |
| Frontend typecheck, production build | clean; succeeds |
| Vitest | 75 passed (new: the AI Lab console offers the assistant a referred loan application) |
| Playwright (Chromium, real backend, fresh database) | 16 passed |
| Docker Compose stack | `validate_system.py` 10/10 (v0.11.0); seed registers the assistant; an AI-automated `personal-loans` v2 run completes in the container |
| Experiments (seed 42, 100 / 25) | assisted and automated both successful — see [ai-testing.md](ai-testing.md) |

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
- Live WF-0002 and WF-0003 cases run with AI off; the UI offers AI modes only through
  simulations and experiments. The income estimate behind the loan assistant is synthetic
  and more reliable than real income estimators.
- The default success thresholds were tuned for account opening; in `domestic-payments`
  even the baseline exceeds the 5 % maximum false approval rate (quiet scams), so
  experiments there fail the compliance-threshold criterion unless the thresholds are
  changed for the scenario.
- Simulation runs write into the same synthetic bank (customers, accounts, ledger postings
  and staff remain). Since Phase 15 a run's workflow history can be archived, restored or
  reset, but the domain records it created stay (the ledger is append-only). Restoring a
  large archive is slow (about 9 minutes for 100,000 cases). Request metrics are per API
  process and reset when it restarts; job, worker and slow-query figures come from the
  database and cover every process. Journal lines and the audit log are not partitioned
  yet (deferred until period close and an audit retention policy exist). Sharded runs
  (Phase 16) use separate teams per shard, so their queueing differs from a
  single-process run; at most 8 shards; suites and experiments run single-process. One
  process still runs about 6 cases/s (≈190 SQL statements per case); the engine's writes
  are not batched. Simulated reviewers work around the clock;
  arrivals are uniform. Since Phase 14 runs are durable jobs; a run whose worker stops is
  still reported as interrupted and is not resumed (`simulation.execute` is not retried).
  See [simulation.md](simulation.md) for measured throughput and why the enterprise
  profile is only a target.
- Schedules fire only while a worker runs (`make worker`, or the Docker Compose worker);
  intervals are fixed periods from the last run, not calendar times (no cron expressions,
  no business calendars).
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
- Postings go one entry at a time through the ORM (about 200 entries per second in the
  development container); bulk loading for generated data is still to come (roadmap
  Milestone A). Since Phase 13 generated data loads in bulk (`load-population`) and other
  callers may use `ledger.post_entries`, but simulation runs still create their customers
  through the services. Reconciliation runs synchronously in the request: a full run over
  a million customers takes about 35 s, so it belongs in a background job (next step);
  incremental runs keep routine checks short.
- Broad substring searches (patterns most rows contain) take 0.4–0.8 s at a million
  customers; a dedicated search index is future work. Employee and user searches have no
  trigram indexes yet (those tables are small).

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
- `scripts/reset_demo.py` does not exist; `python -m app.cli simulation-history reset`
  clears simulation workflow history, and `docker compose down -v` resets everything.
- Charts are built from plain HTML/CSS (no charting library); only paired-bar charts exist so far.
- The frontend Docker image runs the Vite dev server; a production static image is not yet
  defined.
