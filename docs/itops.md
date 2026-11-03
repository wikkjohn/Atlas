# IT operations

Phase 59 (roadmap Milestone D, step 31). IT operations covers:
- the application catalogue: the bank's applications, each owned by a department and given
  a criticality tier;
- incidents against applications, prioritised from impact and urgency, with targets to
  respond and to resolve;
- change management: changes risk-rated, approved by a second person, kept out of the
  month-end freeze and out of each other's way.

Code: `backend/app/modules/itops/`. Page: **IT Operations** (`/it-operations`, `itops:read`).

## Applications

An application (`APP-`) has a name, a description, an owning department and a tier:

| Tier | Meaning |
| --- | --- |
| 1 | Customers or money stop when it stops |
| 2 | A department stops |
| 3 | An inconvenience |

The seed registers twelve applications, from the Core Banking Ledger (tier 1) to the Staff
Intranet (tier 3). Executives (`itops:approve_major`) register more.

## The application registry (Phase 63)

Phase 63 (roadmap Milestone E, step 1) turns the catalogue into a registry. Code:
`backend/app/modules/itops/estate.py`, migration 0043.

**Each application also has:**
- an **owner**: a named user, or none;
- a **technology**, such as Java or COBOL;
- **hosting**: on premise, private cloud, public cloud or SaaS (a database check);
- a **vendor**, for bought-in and SaaS applications;
- **generated from**: the generator's tag (`estate-v1:<seed>`) on a generated application.

An executive sets these (`PUT /itops/applications/{id}/profile`).

**Dependencies.** An application relies on another for data, an API, a batch feed or
authentication (`application_dependencies`). An executive adds or removes them. The rules:
- **`kind_invalid`**: the kind is one of the four above.
- **`not_self`**: an application does not rely on itself; this is also a database check.
- **`application_retired`**: nothing new relies on a retired application.
- **No cycles**: a dependency is refused if the other application already relies on this
  one, directly or through others.
- **No duplicates**: the same dependency twice is a conflict (409).

The twelve core applications come with their dependencies: the Payments Gateway, Card
Authorisation, Online Banking, Loan Origination, the Branch Teller, the Workflow Factory and
the Document Archive all rely on the Core Banking Ledger.

**Impact: what stops if it stops.** Starting from an application, the registry walks back
through everything that relies on it, directly or through others. It reports:
- how many applications are affected, how many directly, and the longest chain;
- the affected applications by tier;
- the departments that own them (a department in each country counts once per country);
- a sample of the affected applications.

The page shows this for the selected application, beside what it relies on and what relies
on it.

**The estate generator** (`POST /itops/estate/generate`, `itops:approve_major`; `python -m
app.cli estate generate --count 2500 --seed 2030`) adds synthetic applications:
- **Deterministic:** the same seed gives the same estate.
- **Idempotent:** a second run with the seed adds nothing.
- **Names** combine a domain and a function with a number, e.g. "Payments Gateway 0001".
- **Tiers:** 10 % tier 1, 35 % tier 2, 55 % tier 3.
- **Technology and hosting** are paired (a SaaS application has a vendor).
- **Owning departments** are spread across the existing departments.
- **Dependencies:** each application relies only on applications created before it, so the
  graph has no cycles. Critical applications are relied on more often: tier 1 six times and
  tier 2 three times as often as tier 3.

`GET /itops/estate/summary` (and `python -m app.cli estate summary`) counts the estate:
- applications, generated applications and dependencies;
- applications with no dependencies either way;
- applications by tier, technology and hosting.

Measured on a development database with seed 2030 (2,500 applications):

| Measure | Result |
| --- | --- |
| Generated | 2,500 applications and 6,015 dependencies in 2.2 s |
| Estate summary | 2,512 applications (2,500 generated and the twelve core), 6,025 dependencies; 243 tier 1, 913 tier 2, 1,356 tier 3 |
| Re-run with the same seed | 0 created, 0.7 s |
| Unconnected applications | 78 |
| Impact of the Core Banking Ledger | 2,255 applications affected, 39 directly, up to 7 steps away, in about 0.1 s |

The registry panel lists applications 25 at a time. It searches by name or number and
filters by tier.

## Simulated applications and outages (Phase 64)

Phase 64 (roadmap Milestone E, step 2) makes every application in the registry answer calls
through one generic contract. Code: `backend/app/modules/itops/simulated.py`, migration
0044.

**The contract.** An application offers two operations, `read` and `write`.

| Part | Model |
| --- | --- |
| Latency | log-normal (spread 0.5) around a median read time set by the technology: COBOL mainframe 40 ms, Go 50, Node 70, Java 80, .NET 90, Python 110, Oracle PL/SQL 120, low-code 200, SAP 250, SaaS 300 (unknown 100) |
| Hosting | the median times 1.0 on premise, 1.1 private cloud, 1.3 public cloud, 1.5 SaaS |
| Calls it waits on | 20 ms more for each API or authentication dependency |
| Writes | 1.5 times a read |
| Errors | 0.1 % of calls for tier 1, 0.5 % for tier 2, 1 % for tier 3; twice that for low-code, 1.5 times for SaaS, half for a mainframe |
| Timeout | a call slower than 5 seconds fails as a timeout |

The 95th percentile is the median times about 2.28.

**Outages.** An outage (`OUT-`) takes an application **down** or **degrades** it from a start,
to an end or until it is ended:
- A **down** application fails every call. So does every application that waits on it through
  an API or authentication dependency, directly or through others. Data and batch
  dependencies do not fail a call: the data is late, not missing.
- A **degraded** application is four times slower and fails 10 % more calls. So is every
  application that waits on it the same way.
- A failed call names the cause: the nearest application that is down, and the chain of
  calls that reaches it.
- **An outage that has started opens an incident** against the application: high urgency,
  impact by tier (a tier-1 outage is a P1). A planned outage opens none.
- The rules:
  - `kind_invalid`: down or degraded;
  - `reason_required`;
  - `application_retired`;
  - `window_invalid`: the end comes after the start;
  - `outage_overlap`: one outage at a time per application;
  - `outage_not_active`: only an outage in force is ended.

Calls are deterministic for a seed, so a simulation repeats exactly. Nothing about a call is
stored.

**The page.** The selected application shows:
- whether it is up, degraded or down, and why;
- its contract;
- how many applications fail if it goes down;
- a **Test 100 calls** button (`itops:manage`).

The **Outages** panel declares outages (`itops:manage`), lists them and ends them.

Measured on the development estate (2,512 applications, 6,025 dependencies, seed 2030):

| Measure | Result |
| --- | --- |
| 10,048 calls, four to every application, no outage | 2.7 s, including loading each contract |
| Core Banking Ledger, 10,000 reads | p50 39.9 ms, p95 90.4 ms (model: 91 ms), 7 errors (0.07 %; model 0.05 %) |
| Core Banking Ledger down | 1,239 applications down (itself and the 1,238 that wait on it), found in 0.13 s; their 4,956 calls all failed as outages |
| Longest chain from a failing application to the ledger | 11 applications |
| The registry's impact of the same outage | 2,255 applications: data and batch feeds count there, but they do not fail calls |

## Applications and workflows (Phase 65)

Phase 65 (roadmap Milestone E, step 3) links the bank's workflows to the applications they
use. Code: `backend/app/modules/itops/links.py`. Nothing new is stored: the graph is read
from the latest active version of each workflow, so it is always current.

**Which applications a step calls.** A step runs a handler, and the handler's namespace
names the core systems it uses:

| Handlers | Core systems | Estate domain |
| --- | --- | --- |
| `accounts.*` | Core Banking Ledger | Ledger |
| `customers.*` | Core Banking Ledger, Document Archive | Customer |
| `compliance.*` | Sanctions Screening, AML Monitoring | Compliance |
| `lending.*` | Loan Origination, Core Banking Ledger | Lending |
| `cards.*` | Card Authorisation | Cards |
| `clearing.*` | Payments Gateway | Payments |
| `retail.*` | Retail Banking Platform, Core Banking Ledger | Channels |
| `mortgages.*`, `commercial.*` | Mortgage Platform, Commercial Lending Platform | Lending |
| `trade.*`, `treasury.*`, `wealth.*`, `risk.*` | Trade Finance System, Treasury Dealing System, Wealth Platform, Risk Engine | Trade, Treasury, Wealth, Risk |
| `finance.*` | Core Banking Ledger, Regulatory Reporting, Enterprise Data Warehouse (Phase 68) | Finance |
| `service.*`, `collections.*` | Service Desk CRM, Collections System | Customer, Collections |
| `hr.*`, `procurement.*`, `itops.*` | HR System, Procurement Suite, IT Service Management | HR, Procurement, Data |
| `backoffice.*`, `ai.*` | Workflow Factory, AI Innovation Lab Console | Reporting, Data |
| `wf0001.*` to `wf0004.*` (the code workflows) | the ledger, screening, the gateway, loan origination | Customer, Payments, Lending, Collections |

`core.*` handlers (values, checks, outcomes) call nothing.

The catalogue gains the thirteen core systems these name, one for each department whose
workflows had none. Each comes with its technology, hosting and dependencies: the
Treasury Dealing System, for example, relies on the Payments Gateway and the ledger.

**The estate.** Where the generated estate exists, each linked step also calls one critical
(tier 1 or 2) estate application from its domain. A hash of the workflow and step picks
it, so the same step always calls the same application. A domain with no critical
application adds none.

**What an outage stops.** A down application fails everything that waits on it
synchronously (Phase 64). Every workflow with a step that calls any of those stops. For
each application the page shows:
- the workflows that call it, with their steps;
- what its outage stops: workflows, steps and failing applications, by department, and for
  each workflow the applications it fails through.

**Wiring.** An application is wired when a workflow calls it, or when an application a
workflow calls relies on it, directly or not (any kind of dependency). `GET
/itops/estate/wiring` counts this, and so does `python -m app.cli estate wiring`. `python -m
app.cli estate impact "<application>"` gives one application's outage.

Measured on the development database: 119 active workflows, and 2,512 applications plus the
thirteen new core systems, so 2,525.

| Measure | Result |
| --- | --- |
| Workflows linked | 119 of 119: 544 steps, 1,270 links, 340 applications called directly |
| Wired | 1,105 of 2,525 applications (44 %); 1,420 not yet |
| Core Banking Ledger down | 1,248 applications fail; 117 of 119 workflows stop (479 steps); 0.22 s |
| Sanctions Screening down | 1,034 applications fail; 106 workflows stop (269 steps) |
| Card Authorisation down | 255 applications fail; 42 workflows stop (57 steps) |
| Staff Intranet down | 20 applications fail; 9 workflows stop (18 steps), mostly HR and IT |
| Whole-estate wiring count | 0.35 s |

**Why only 44 % is wired.** A generated application relies only on applications generated
before it (Phase 63), so the most recently generated ones are wired only when a step calls
them directly. Phase 68 wires the rest (below).

## The Milestone E exit (Phase 68)

**The Enterprise Data Warehouse.**
- A core system (Finance, tier 2), the 26th.
- It takes a nightly **batch feed** from every application nothing else relies on: the most
  recently generated applications, and core systems such as Online Banking.
- Every application is then either fed to the warehouse or relied on, directly or not, by
  one that is.
- Finance steps (`finance.*`) call the warehouse, so the bank's workflows depend on the whole
  estate.

`estate.wire` adds the feeds:
- the seeded catalogue (`ensure_applications`) and the estate generator call it, and so do
  `POST /itops/estate/wire` and `python -m app.cli estate wire`;
- it is idempotent: a second run adds nothing.

The warehouse is never relied on, so the feeds make no cycle: the generator leaves it out
of the applications it may depend on.

**Batch feeds fail no call** (Phase 64), so the warehouse changes nobody's outage impact.
The Core Banking Ledger down still fails 1,248 applications and stops 117 workflows.

**The exit check** (`GET /itops/estate/exit`, `python -m app.cli estate exit`, and the line
on the registry panel) passes when:
- **generated:** at least 2,500 applications are generated;
- **wired:** none is unwired;
- **outage measured:** a completed simulation run carries an outage's cost (Phase 67).

Measured on the development database:

| Measure | Result |
| --- | --- |
| Warehouse feeds added | 947, all batch, in 4.4 s (adding the warehouse and wiring together) |
| Applications | 2,526 (2,500 generated and 26 core systems) |
| Wired | 2,526 of 2,526; 341 called directly by 544 steps of 119 workflows |
| Outage measured | run #10, `domestic-payments-outage`: 19 of 300 executions failed |
| **Exit check** | **passed** |

## Workflows call their applications (Phase 66)

Phase 66 (roadmap Milestone E, step 4) makes the links real. Code:
`backend/app/modules/itops/gateway.py`, called by the workflow engine before each service or
AI step's handler.

**Calls.** A step calls the applications the dependency graph gives it (Phase 65): its
core systems, then its estate application. Each call goes through the generic simulated
application (Phase 64):
- it is made at the step's time, the simulation clock or the real one;
- it is a write when the handler's action is one (open, post, approve, release…),
  otherwise a read;
- calls run one after another.

**When a call fails.**
- An application that is down fails the step as `application_unavailable`. So does one
  that waits synchronously on an application that is down.
- The error names the application, the cause and the chain from one to the other.
- The step is retried under its own retry policy: by default three attempts, 30 s then
  60 s apart. A short outage therefore delays the workflow, and a longer one fails it or
  sends it down its `on_failure` route.
- The handler does not run, so nothing is written.

**When the calls succeed.**
- Their latencies are added to the step's recorded duration. A degraded application is
  four times slower.
- The `step.completed` event lists each call and the total time.
- `core.*` steps, decisions and human tasks call nothing.

**Determinism.** By default only outages fail calls: each application's own error rate
and timeout are not applied, so a workflow without outages repeats exactly.
`gateway.realistic()` applies them too. Each call's random draw comes from the execution,
the step and the attempt.

**Outages are on the simulation's timeline.** A simulation dated in the past sees the
outages of that time. An outage declared from 2000 and ended today covers every simulated
date before today.

Measured with `retail-onboarding` (WF-0001: every step calls the ledger and Sanctions
Screening), 300 applications, 12 employees, seed 2030, on the development database:

| Run | Completed | Failed (`application_unavailable`) | Wall time |
| --- | --- | --- | --- |
| No outage | 300 | 0 | 101.1 s (94.2 s before Phase 66; 97.6 s once Phase 67 kept the gateway's lookups per session); result digest identical |
| Sanctions Screening down all day | 0 | 300, at their first step, after three attempts | 61.8 s |
| Down 12:00 to 14:00, and 15:00 to 15:01 | 222 | 78 (arrivals in the two-hour window are about a quarter of the day's) | 91.3 s |

In the last run, 2 executions that met the one-minute outage completed on a retry, a
minute or two late.

## Incidents

An incident (`INC-`, `itops:manage`) names an application, what is wrong, its impact and its
urgency. Its priority follows from the two:

| | High urgency | Medium urgency | Low urgency |
| --- | --- | --- | --- |
| **High impact** | P1 | P2 | P3 |
| **Medium impact** | P2 | P3 | P4 |
| **Low impact** | P3 | P4 | P4 |

Each priority sets the targets, counted from when the incident is reported:

| Priority | Acknowledge within | Resolve within |
| --- | --- | --- |
| P1 | 15 minutes | 4 hours |
| P2 | 30 minutes | 8 hours |
| P3 | 4 hours | 72 hours |
| P4 | 24 hours | 120 hours |

An incident is:
1. **acknowledged** (`itops:manage`); late, it is marked as a response breach;
2. **resolved** (`itops:manage`), saying how (rule `resolution_required`) and optionally
   naming the change that caused it (rule `other_application` if that change was to
   another application); late, it is marked as a resolution breach;
3. **closed** (`itops:approve`). A P1 is closed only with a post-incident review (rule
   `review_required`), written by someone other than whoever resolved it (rule
   `four_eyes`).

**The SLA sweep** (`POST /itops/incidents/sweep`, WF-1051) marks incidents not acknowledged,
or not resolved, by their targets.

## Changes

A change (`CHG-`, `itops:manage`) names an application, what changes, its kind, a backout
plan and a window.

**Risk** comes from the kind, raised or lowered:

| Kind | Risk |
| --- | --- |
| Standard | low |
| Normal | medium |
| Emergency | high |

It goes one level higher on a tier-1 application or without a backout plan, and one level
lower on a tier-3 application.

The rules:
- **Standard changes** are pre-approved, but only when low risk (rule `not_standard`).
- **Other changes** are approved or rejected (`itops:approve`) by someone other than the
  requester (rule `four_eyes`, also a database constraint). A high-risk change, or any
  change to a tier-1 application, needs an executive, `itops:approve_major` (rule
  `needs_cab`).
- **No clashes:** a change is not approved into a window that another approved change to
  the same application holds (rule `window_conflict`).
- **The month-end freeze:** from the 28th to the 1st, only emergency changes go into tier-1
  applications (rule `change_freeze`). The page shows when the freeze is on.
- **Emergency changes** must answer an open P1 or P2 incident on the same application
  (rule `emergency_needs_incident`). Only an emergency change may be planned in the past
  (rule `window_invalid`).

An approved change is recorded as **implemented** or as **failed**. A failed change opens an
incident against its application, attributed to it, with high urgency and an impact set by
the tier: high for tier 1, medium for tier 2, low for tier 3.

## Workflows

| Workflow | Steps | Handlers |
| --- | --- | --- |
| WF-1049 Incident Report | open → P1 or P2? → page the on-call engineer (acknowledge) or queue | `itops.open_incident`, `itops.acknowledge_incident` |
| WF-1050 Change Request | raise → pre-approved? → approval (`itops:approve`) → approve or reject | `itops.raise_change`, `itops.approve_change`, `itops.reject_change` |
| WF-1051 Incident SLA Sweep | sweep | `itops.sla_sweep` |

WF-1050 plans its window some days ahead, starting at 22:00 UTC, for a number of hours. It
takes standard and normal changes; emergency changes, which need an incident, are raised on
the page.

The handlers need `itops:manage` to start and `itops:read` to read executions. Their
generated tests take a new tier-2 application from a fixture, so the freeze never applies.

## Simulation workload and AI tool (Phase 60)

The `change_approvals` workload drives WF-1050 v2 (scenario `change-approvals`).
- **Cases:** each case has its own tier-2 or tier-3 application. The history the case needs
  is booked through the real IT operations service, dated against the scenario's
  simulated day: earlier changes (failed ones with their incidents resolved and closed), or
  an incident still open. The workflow then raises a normal change, with the window's start
  hour, and a department manager (`itops:approve`) approves or rejects it.
- **Ground truth:**
  - approved: routine changes out of hours, daytime changes to tier-3 applications, and
    changes raised at short notice for the small hours;
  - rejected: a change with no backout plan, a change to an application with a P2 still
    open, a business-hours window on a tier-2 application, and another change to an
    application whose last changes kept failing.
- **`itops.change_profile`** (also a library handler) reads:
  - the kind, risk and the application's tier, and whether there is a backout plan;
  - the window's length, start hour and lead time, business hours and the freeze;
  - the application's open P1 and P2 incidents;
  - the changes to the application in the 90 days before and how many failed, and the
    requester's failed changes.
- **AGB Change Review Assistant** (`agb-change-assistant`): advisory. It is blind to failure
  history; see [ai-testing.md](ai-testing.md) for its rules and the measurement.

`itops.raise_change` takes an optional start hour (`start_hour_path`, 22:00 UTC when not
given). It also accepts an empty backout plan, which the service rates one level riskier;
before Phase 60 the handler refused one as a missing value.

## Permissions

| Permission | Roles | What it allows |
| --- | --- | --- |
| `itops:read` | banking employees, department managers, regional and global executives, auditors | the page and the lists |
| `itops:manage` | banking employees, department managers | report, acknowledge and resolve incidents; raise changes and record them implemented or failed; the SLA sweep; declare and end outages, test calls |
| `itops:approve` | department managers, regional and global executives | approve or reject changes, close incidents |
| `itops:approve_major` | regional and global executives | high-risk changes, changes to tier-1 applications, registering applications, their profiles and dependencies, generating the estate |

## Known limitations

- **Links come from handler namespaces,** not from what a step does with its parameters:
  every `accounts.*` step calls the ledger, whatever it reads.
- **Every step of a namespace calls all its core systems:** each WF-0001 step calls both
  the ledger and Sanctions Screening, so a screening outage stops the workflow at its first
  step, not at its screening step.
- **A retried step waits at least 30 s;** a step with `max_attempts: 1` (most stored
  workflows' lookups) goes straight to `on_failure`.
- **Retries and circuit breakers are not modelled:** a caller sees each failure.
- **Latency does not grow with load:** an application answers as fast at 10,000 calls a
  second as at one.
- **Workflows do not call applications yet:** an outage does not delay the processes that
  depend on the application (Milestone E). The impact analysis counts applications, not
  workflows.
- **Generated applications have no owner;** the twelve core ones do not either until one is
  set.
- **The cycle check loads every dependency:** fine at 6,000, not tuned for far more.
- **No on-call rota:** acknowledging an incident stands for paging the engineer.
- **Targets run on the clock,** not on business hours, and are not paused while waiting on
  a third party.
- **No problem records:** a P1's review is free text; recurring incidents are not linked.
- **A change's window is not enforced** when it is implemented.
- **Only change approvals are simulated** (Phase 60); incidents are not.
