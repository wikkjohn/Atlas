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
- [ ] Partition the largest tables (journal lines, workflow step runs, events, audit log)
- [ ] Bulk loading with COPY for generated data; index and query-plan review
- [ ] Queue-backed job system on Redis with multiple worker processes (same codebase)
- [ ] Built-in scheduler: workflow timers, loan servicing, statements, reconciliation
- [ ] Reset / archive command for simulation data
- [ ] Performance test suite with recorded targets (started: `bench-ledger`, Phase 12)
- [ ] Observability: metrics, slow-query log, worker throughput
- [ ] **Exit:** `department` profile repeatable; 1M customers / 100k applications measured

## Milestone B — Workflow factory

- [ ] Database-stored, versioned workflow definitions alongside code-registered ones
- [ ] Definition import API with full validation (reachability, permissions, handlers)
- [ ] Reusable step-handler library (validate, screen, approve, post, notify, wait, AI
      call, application call) so most workflows need no new code
- [ ] Parameterized workflow templates (country, product, currency, limits, documents, AI)
- [ ] Deterministic, versioned variant generator
- [ ] Generated tests per workflow (happy, reject, approval, timeout) in CI
- [ ] Visual workflow viewer, then editor with validation
- [ ] Catalogue search by department / country / product; ownership; lifecycle states
- [ ] **Exit:** 50 → 500 → 5,000 registered workflows, generated tests green

## Milestone C — Global footprint (5 → 120 countries)

- [ ] Reference data for 120 countries: currency, minor units, time zone, holidays,
      language, regulator, identity documents, address formats
- [ ] Multi-currency: synthetic FX rates, cross-currency payments, revaluation, positions
- [ ] Country rules engine: KYC documents, age limits, sanctions lists, cut-offs, limits
- [ ] Business calendars used by the scheduler and the simulation's arrivals
- [ ] Generated country subsidiaries in the organization hierarchy
- [ ] **Exit:** onboarding and payment variants pass in all 120 countries

## Milestone D — 35+ departments and their products

Each department: a domain module (services, ledger postings, permissions), base processes
for the factory, a simulation workload and at least one AI tool candidate.

- [ ] Retail banking: deposits, statements, interest and fees, overdrafts, standing orders
- [ ] Cards: issuing, authorisation, disputes and chargebacks, fraud blocks
- [ ] Mortgages and secured lending: valuation, collateral, offers
- [ ] SME and commercial lending: facilities, covenants, annual reviews
- [ ] Trade finance: letters of credit, guarantees
- [ ] Treasury and markets: FX desk, liquidity, interbank placements
- [ ] Payments operations: bulk payments, external clearing simulation, recalls
- [ ] Wealth and investments: synthetic securities, custody, suitability
- [ ] Compliance: AML monitoring, case management, SAR filing, periodic KYC refresh
- [ ] Risk: credit ratings, limits, provisioning (ECL)
- [ ] Finance: GL close, regulatory reporting extracts, cost allocation
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
| Phase 13 (A2, proposed) | Bulk loading and a faster posting path; reset / archive of simulation data | next |
