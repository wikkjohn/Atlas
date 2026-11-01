# Roadmap to the long-term vision

The original assignment (Phases 1–8, the end-to-end demonstration, API contracts and
mandatory tests) is complete; Phases 9–11 extended it with payments, lending, loan
servicing, collections and AI underwriting. This roadmap covers what remains between today
and the mission statement: a synthetic global bank with 150,000 employees, 120 countries,
35+ departments, 5,000+ executable workflows, 2,500 simulated enterprise applications,
millions of customers and an AI testing laboratory at that scale.

| Dimension | Vision | Today |
| --- | --- | --- |
| Business workflows | 5,000+ | 4 (WF-0001 to WF-0004, 6 versions) |
| Countries | 120 | 5 |
| Departments | 35+ | organization hierarchy only; banking processes in 3 areas |
| Simulated enterprise applications | 2,500 | none |
| Employees | 150,000 | 120 seeded; simulations create staff per run |
| Customers | millions | hundreds seeded; thousands per simulation |
| Enterprise simulation profile | runs | a configuration target only; not measured |

## Strategy

1. **Scale before breadth.** Balances computed on every read, a synchronous whole-ledger
   reconciliation, a single-process simulation runner and no scheduler or reset are what
   millions of customers break first.
2. **Workflows become data.** About 150–250 hand-written *base processes* plus a template
   and variant generator (by country, product, channel, department). Every variant is
   validated, versioned and tested automatically. 200 processes × 120 countries × their
   products is well past 5,000 executable workflows.
3. **Generate the bank, do not hand-build it.** Countries, departments, employees,
   customers and applications come from versioned, seeded generators and reference data.
4. **Departments integrate through events, not imports.** The servicing → WF-0004 listener
   becomes a durable outbox, so one department's process can trigger another's.
5. **Keep the original rules.** A modular monolith (no microservices, no Kubernetes),
   synthetic data only, migrations for every schema change. Scale means more worker
   processes of the same application, partitioned tables and batched writes.
6. **Measurable milestones.** Each milestone ends with a test that can be run and timed.

## Milestone A — Scale foundation

- [x] Stored account balances maintained in the same transaction as each posting (Phase 12)
- [x] Incremental reconciliation (only what changed since the last checkpoint) with history
      (Phase 12)
- [x] Partition workflow history — executions, step runs, events — into live and
      simulation partitions (Phase 15; measured: live queries were already fast, the gain
      is removal: 5 s to drop 100,000 cases' history instead of over ten minutes)
- [ ] Partition journal lines and the audit log by period: deferred until period close
      (Finance, Milestone D) and an audit retention policy exist — stored balances already
      removed the full scans, and an append-only ledger has nothing to drop
- [x] Bulk loading with COPY for generated data; index and query-plan review (Phase 13)
- [x] Durable job queue with multiple worker processes, same codebase (Phase 14: in
      PostgreSQL with SKIP LOCKED rather than Redis, so jobs commit with their work)
- [x] Built-in scheduler: workflow timers, loan servicing, reconciliation (Phase 14;
      statements come with the deposits work in Milestone D)
- [x] Archive / restore / reset of simulation workflow history, with a retention schedule
      (Phase 15; synthetic customers, accounts and postings stay — the ledger is append-only)
- [x] Performance test suite with recorded targets (`python -m app.cli perf`, in CI;
      Phase 16 — see [performance.md](performance.md))
- [x] Simulation runs split into parallel shards across worker processes (Phase 16)
- [x] Observability: request metrics, Prometheus endpoint, slow-query log from every
      process, worker registry and job throughput (Phase 15)
- [x] **Exit:** `department` profile repeatable (twice with identical digests, Phase 16);
      1M customers loaded and measured (Phase 13); 100,000 applications in 73 minutes on
      8 shards (Phase 16)

## Milestone B — Workflow factory

- [x] Database-stored, versioned workflow definitions alongside code-registered ones
      (Phase 17: import, export, active/retired lifecycle, loaded by any process)
- [x] Definition import API with full validation (reachability, permissions, handlers)
      (Phase 17: every problem located; also termination, context paths, versions)
- [x] Reusable step-handler library (validate, screen, approve, post, notify, wait, AI
      call, application call) so most workflows need no new code (Phases 17–18: `core.*`,
      customers, accounts and fees, screening, notifications, AI advice; approvals and waits
      are step types; application calls arrive with Milestone E's applications)
- [x] Parameterized workflow templates (country, product, currency, limits, documents, AI)
      (Phase 19: placeholders, country reference data, minor units, optional steps)
- [x] Deterministic, versioned variant generator (Phase 19: stable ids per parameter set,
      new versions only for changed content, all or nothing)
- [x] Generated tests per workflow (happy, reject, approval, timeout) in CI (Phase 20:
      every route, approval refusals, no-route probes; coverage; CI job)
- [x] Visual workflow viewer, then editor with validation (Phase 21: layered diagram with
      metrics and test coverage; step form and JSON editor with live, located validation)
- [x] Catalogue search by department / country / product; ownership; lifecycle states
      (Phase 22: classification from definitions, templates or by hand; facet counts;
      draft → review → active → retired with four-eyes approval behind passing tests)
- [x] **Exit:** 50 → 500 → 5,000 registered workflows, generated tests green (Phase 22:
      5,052 stored workflows, 111,168 generated cases, 0 failed, 100 % step and route
      coverage, 1 h 30 min on 4 processes; see `performance.md`) — **Milestone B complete**

## Milestone C — Global footprint (5 → 120 countries)

- [x] Reference data for 120 countries: currency, minor units, time zone, holidays,
      language, regulator, identity documents, address formats (Phase 23: 93 currencies,
      1,167 holiday rules with computed calendars, document and postal masks, address
      layouts; see `reference-data.md`; lunar-calendar holidays follow with the calendars)
- [x] Multi-currency: synthetic FX rates, cross-currency payments, revaluation, positions
      (Phase 24: deterministic daily rates for 93 currencies with pegs, conversions through
      position accounts, WF-0002 payees in any currency, daily revaluation; see `fx.md`)
- [x] Country rules engine: KYC documents, age limits, sanctions lists, cut-offs, limits
      (Phase 25: versioned rules per country read by WF-0001 and WF-0002; value dates
      from cut-off and calendar; five synthetic sanctions lists; see `country-rules.md`)
- [x] Business calendars used by the scheduler and the simulation's arrivals
      (Phase 26: lunar holidays dated 2025–2030 for 50 countries; schedules and scenario
      arrivals follow a country's business days; see `business-calendars.md`)
- [x] Generated country subsidiaries in the organization hierarchy
      (Phase 27: a versioned blueprint of divisions, departments, teams and staff;
      launching a country activates it and builds what is missing; all 115 planned
      countries generated in 31 s; see `subsidiaries.md`)
- [x] **Exit:** onboarding and payment variants pass in all 120 countries (Phase 28:
      cases that follow each country's rules; `global-onboarding` and `global-payments`
      run in every country with its own staff; see `country-sweep.md`) — **Milestone C
      complete**

## Milestone D — 35+ departments and their products

Each department: a domain module (services, ledger postings, permissions), base processes
for the factory, a simulation workload and at least one AI tool candidate.

- [x] Retail banking: deposits, statements, interest and fees, overdrafts, standing orders
      (Phase 29: products with dollar terms converted per currency, arranged overdrafts
      in every funds check, standing orders on business days, month end with daily
      interest, fees and statements; WF-1003–1005; see `retail-banking.md`. Phase 30:
      the `retail-overdrafts` workload and the overdraft affordability assistant)
- [x] Cards: issuing, authorisation, disputes and chargebacks, fraud blocks
      (Phase 31: synthetic Luhn-checked numbers, a merchant terminal with limits, funds
      and fraud rules that block the card, four-eyes chargebacks through card
      settlement; WF-1006–1008; see `cards.md`. Phase 32: the `card-fraud-alerts`
      workload on WF-1008 v2 and the card fraud alert assistant)
- [x] Mortgages and secured lending: valuation, collateral, offers
      (Phase 33: properties with desktop and surveyor valuations, a decision in principle
      over every lending rule, four-eyes offers valid 90 days, completion into a loan
      charged on the property; WF-1009–1011; see `mortgages.md`. Phase 34: the
      `mortgage-applications` workload and the mortgage underwriting assistant)
- [x] SME and commercial lending: facilities, covenants, annual reviews
      (Phase 35: term loans and revolving credit with four-eyes and committee approval,
      drawdowns through the ledger, covenant tests that freeze a facility until waived,
      annual reviews; WF-1012–1014; see `commercial-lending.md`. Phase 36: the
      `covenant-breaches` workload and the covenant breach assistant)
- [x] Trade finance: letters of credit, guarantees
      (Phase 37: beneficiaries screened against the sanctions lists, four-eyes and
      committee approval, a cash margin held while live, documents checked for
      discrepancies and paid with the applicant's waiver, guarantee claims, expiry;
      WF-1015–1017; see `trade-finance.md`. Phase 38: the `discrepant-presentations`
      workload and the document check assistant)
- [x] Treasury and markets: FX desk, liquidity, interbank placements
      (Phase 39: placements and borrowings with synthetic counterparty banks under credit
      limits, dealer and back-office four-eyes, settlement and maturity through the ledger,
      30-day liquidity coverage, FX position limits and square-off spot trades;
      WF-1018–1020; see `treasury.md`. Phase 40: the `deal-confirmations` workload and
      the back-office check assistant)
- [x] Payments operations: bulk payments, external clearing simulation, recalls
      (Phase 41: payments to synthetic banks with check-digit accounts and four-eyes for
      high value, clearing cycles that pay out or return, bulk files released with
      four-eyes, recalls answered by reason and time since settlement; WF-1021–1023; see
      `payments-operations.md`. Phase 42: the `recall-triage` workload and the recall
      assistant)
- [x] Wealth and investments: synthetic securities, custody, suitability
      (Phase 43: ten synthetic securities with deterministic daily prices, a suitability
      questionnaire giving a risk profile from 1 to 7, portfolios in custody, orders checked
      for risk, complexity and concentration with four-eyes for unsuitable ones, income paid
      to holders; WF-1024–1026; see `wealth.md`. Phase 44: the `order-review` workload and
      the suitability review assistant)
- [x] Compliance: AML monitoring, case management, SAR filing, periodic KYC refresh
      (Phase 45: four monitoring rules over customer accounts' ledger activity, alerts
      investigated in cases closed with four-eyes or escalated to suspicious activity
      reports filed by a second officer, periodic KYC reviews by risk rating; WF-1027–1029;
      see `compliance.md`. Phase 46: the `alert-triage` workload and the alert review
      assistant)
- [x] Risk: credit ratings, limits, provisioning (ECL)
      (Phase 47: a ten-grade internal scale with a model grade from KYC rating and
      arrears, overrides approved by a second person, obligor limits against exposure in
      US dollars, IFRS 9 staged ECL posted to the ledger by a second person; WF-1030–1032;
      see `risk.md`. Phase 48: the `rating-overrides` workload and the rating review
      assistant)
- [x] Finance: GL close, regulatory reporting extracts, cost allocation
      (Phase 49: month-end closes checked and approved by a second person, posting income
      and expense to retained earnings in month order; balance sheet, income statement,
      large exposures and credit quality extracts submitted to a synthetic regulator; shared
      costs split across departments by headcount; WF-1033–1035; see `finance.md`)
- [ ] Customer service: contact-centre cases, complaints, SLA timers
- [ ] Collections and recoveries: payment plans, recoveries (extends WF-0004)
- [ ] HR: hiring, onboarding, leave and shifts (feeds simulation staffing)
- [ ] Procurement and vendor management
- [ ] IT operations: incidents and change management (linked to applications)
- [ ] Legal, audit, marketing, facilities and the remaining departments (thin modules)
- [ ] **Exit:** 35+ departments, each with ≥ 3 base processes, a workload and dashboards

## Milestone E — 2,500 simulated enterprise applications

- [ ] Application registry: department, owner, criticality, technology, dependencies
- [ ] Generic simulated-application adapter: contract, latency model, failure and outages
- [ ] Application ↔ workflow dependency graph with impact analysis
- [ ] Workflows call applications through the step library, so outages cause real delays
- [ ] Outage scenarios in the simulation engine
- [ ] **Exit:** 2,500 applications generated and wired; one outage's impact measured

## Milestone F — Workforce and customers at full scale

- [ ] Employee generator: 150,000 staff by department and country, roles, grades, skills
- [ ] Shifts, holidays, absences and time zones in the reviewer model
- [ ] Named task assignment, delegation and escalation routing
- [ ] Customer generator: millions of customers, segments, products, transaction history
- [ ] Realistic arrival patterns: daily and weekly peaks, seasonality, events
- [ ] Durable event pipeline (outbox) for departmental dependencies
- [ ] **Exit:** the `enterprise` profile completes, with its timing measured

## Milestone G — AI laboratory at enterprise scale

- [ ] Real model-provider adapter (same contract, synthetic data only, cost per call)
- [ ] Repeated-seed experiments with confidence intervals and significance tests
- [ ] Experiment portfolios: one tool across many workflows, departments and countries
- [ ] Guardrails: drift detection, prompt/response audit, bias checks across segments
- [ ] Scenario-specific success thresholds
- [ ] Tool comparison across all benchmarks
- [ ] Calibrate reviewer-behaviour assumptions instead of fixing them
- [ ] **Exit:** one tool evaluated across 100+ workflows with statistical confidence

## Milestone H — Platform hardening (alongside the others)

- [ ] Simulated SSO, MFA, session management, scoped permissions (country / department)
- [ ] Rate limiting, audit-log archive, data-retention review
- [ ] Security scanning in CI (dependencies, SAST) and an authorization test matrix
- [ ] Backup / restore and a tested recovery procedure
- [ ] Dashboard drill-down: enterprise → country → department → workflow
- [ ] Architecture decision records, runbooks, contributor guide

## Order

1. Milestone A, together with the first half of Milestone B (stored definitions, templates).
2. Milestones C and F (generators and reference data).
3. Milestone D, a few departments at a time, feeding base processes into the factory.
4. Milestone E once workflows can call applications.
5. Milestone G once the bank is broad enough to make portfolios meaningful.

At the pace of Phases 1–11 this is roughly 25–40 further phases. Milestone B is the
multiplier: after it, the workflow count grows by generating variants, not by hand-coding.

## Progress

| Step | Scope | Status |
| --- | --- | --- |
| Phase 12 (A1) | Stored balances, incremental reconciliation, ledger benchmark | complete |
| Phase 13 (A2) | Bulk posting, 1M-customer population loader, search and sort indexes | complete |
| Phase 14 (A3) | Durable job queue, worker processes, schedules; simulations and experiments as jobs | complete |
| Phase 15 (A4) | Partitioned workflow history; archive, restore and reset of simulation history; observability (metrics, slow queries, workers) | complete |
| Phase 16 (A5) | Sharded simulation runs across worker processes; performance suite with recorded targets; 100,000 applications measured — Milestone A done (journal-line and audit-log partitioning deferred, see above) | complete |
| Phase 17 (B1) | Database-stored, versioned workflow definitions next to code-registered ones; import/export API and CLI with full validation; first handler library (`core.*`); WF-1001 imported as data | complete |
| Phase 18 (B2) | Domain handler library (customers, accounts and fees, screening, notifications, AI advice) with declared effects; money moves only behind an approval; WF-1001 v2 and WF-1002 as data | complete |
| Phase 19 (B3) | Parameterised workflow templates and a deterministic, versioned variant generator; 5,040 variants generated and listed | complete |
| Phase 20 (B4) | Generated path tests for every stored and generated workflow (route planning, input synthesis, fixtures, coverage), run in CI and from the UI | complete |
| Phase 21 (B5) | Workflow diagram for every workflow (layout, route labels, live metrics, test coverage) and an editor for stored workflows with live, located validation | complete |
| Phase 22 (B6) | Catalogue at scale: search and facets by department, country and product; ownership; lifecycle (draft, review, active, retired) with four-eyes approval behind passing tests; parallel test runner; Milestone B exit run (5,052 workflows, 111,168 cases, 0 failed) — Milestone B done | complete |
| Phase 23 (C1) | Global footprint, step 1: reference data for 120 countries (currency, minor units, time zone, weekend, holidays, language, regulator, identity documents, address formats), computed holiday calendars, synthetic document numbers and addresses | complete |
| Phase 24 (C2) | Multi-currency: synthetic FX rates, conversions through currency positions, cross-currency payments, daily revaluation, Foreign Exchange page | complete |
| Phase 25 (C3) | Country rules engine: versioned per-country KYC, screening and payment rules applied by account opening and payments; value dates; rules editing on the Countries page | complete |
| Phase 26 (C4) | Business calendars: lunar holidays as dated tables; schedules and simulation arrivals on a country's business days | complete |
| Phase 27 (C5) | Generated country subsidiaries: a versioned blueprint; launching a country activates it and builds its subsidiary and staff | complete |
| Phase 28 (C6) | Milestone C exit: cases that follow each country's rules; onboarding and payments swept through all 120 countries — Milestone C done | complete |
| Phase 29 (D1) | Retail banking: products, arranged overdrafts, standing orders, month-end interest, fees and statements; WF-1003–1005 | complete |
| Phase 30 (D2) | Retail banking, step 2: the `retail-overdrafts` workload on stored WF-1003 v2 and the AGB Overdraft Affordability Assistant; simulations run stored workflows | complete |
| Phase 31 (D3) | Cards: issuing, a merchant terminal with fraud rules and blocks, disputes and chargebacks; WF-1006–1008 | complete |
| Phase 32 (D4) | Cards, step 2: the `card-fraud-alerts` workload on stored WF-1008 v2, built through the real authorisation service, and the AGB Card Fraud Alert Assistant | complete |
| Phase 33 (D5) | Mortgages and secured lending: properties and valuations, a decision in principle, four-eyes offers, completion into a loan charged on the property; WF-1009–1011 | complete |
| Phase 34 (D6) | Mortgages, step 2: the `mortgage-applications` workload on stored WF-1009 v2 and the AGB Mortgage Underwriting Assistant | complete |
| Phase 35 (D7) | SME and commercial lending: facilities, drawdowns, covenant tests and waivers, annual reviews; WF-1012–1014 | complete |
| Phase 36 (D8) | Commercial lending, step 2: the `covenant-breaches` workload on stored WF-1013 v2, decided by the credit committee, and the AGB Covenant Breach Assistant | complete |
| Phase 37 (D9) | Trade finance: letters of credit and guarantees, sanctions screening, cash margin, documentary presentations and guarantee claims; WF-1015–1017 | complete |
| Phase 38 (D10) | Trade finance, step 2: the `discrepant-presentations` workload on stored WF-1016 v2, decided by trade officers, and the AGB Document Check Assistant | complete |
| Phase 39 (D11) | Treasury and markets: interbank placements and borrowings under counterparty limits, 30-day liquidity coverage, FX position limits and square-off trades; WF-1018–1020 | complete |
| Phase 40 (D12) | Treasury, step 2: the `deal-confirmations` workload on stored WF-1018 v2, decided by back office, and the AGB Back-Office Check Assistant | complete |
| Phase 41 (D13) | Payments operations: outgoing payments to synthetic banks, clearing cycles with returns, bulk payment files, recalls; WF-1021–1023 | complete |
| Phase 42 (D14) | Payments operations, step 2: the `recall-triage` workload on stored WF-1023 v2, decided by back office, and the AGB Recall Assistant | complete |
| Phase 43 (D15) | Wealth and investments: synthetic securities, suitability profiles, portfolios in custody, orders with suitability checks, income; WF-1024–1026 | complete |
| Phase 44 (D16) | Wealth, step 2: the `order-review` workload on stored WF-1025 v2, decided by wealth managers, and the AGB Suitability Review Assistant | complete |
| Phase 45 (D17) | Compliance: AML transaction monitoring, alerts and cases, suspicious activity reports, periodic KYC reviews; WF-1027–1029 | complete |
| Phase 46 (D18) | Compliance, step 2: the `alert-triage` workload on stored WF-1027 v2, decided by compliance officers, and the AGB Alert Review Assistant | complete |
| Phase 47 (D19) | Risk: internal credit ratings with four-eyes overrides, obligor limits against exposure, IFRS 9 ECL provisioning posted to the ledger; WF-1030–1032 | complete |
| Phase 48 (D20) | Risk, step 2: the `rating-overrides` workload on stored WF-1030 v2, decided by regional executives, and the AGB Rating Review Assistant | complete |
| Phase 49 (D21) | Finance: month-end close with four-eyes approval, regulatory reporting extracts, cost allocation by headcount; WF-1033–1035 | complete |
| Phase 50 (D22, proposed) | Finance, step 2: a `month-end-close` workload on stored WF-1033 v2, decided by finance approvers, and an AGB Close Review Assistant | next |
