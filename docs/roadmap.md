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
| Phase 13 (A2) | Bulk posting, 1M-customer population loader, search and sort indexes | complete |
| Phase 14 (A3) | Durable job queue, worker processes, schedules; simulations and experiments as jobs | complete |
| Phase 15 (A4) | Partitioned workflow history; archive, restore and reset of simulation history; observability (metrics, slow queries, workers) | complete |
| Phase 16 (A5) | Sharded simulation runs across worker processes; performance suite with recorded targets; 100,000 applications measured — Milestone A done (journal-line and audit-log partitioning deferred, see above) | complete |
| Phase 17 (B1) | Database-stored, versioned workflow definitions next to code-registered ones; import/export API and CLI with full validation; first handler library (`core.*`); WF-1001 imported as data | complete |
| Phase 18 (B2) | Domain handler library (customers, accounts and fees, screening, notifications, AI advice) with declared effects; money moves only behind an approval; WF-1001 v2 and WF-1002 as data | complete |
| Phase 19 (B3, proposed) | Parameterised workflow templates (country, product, currency, limits, documents, AI) and a deterministic variant generator | next |
