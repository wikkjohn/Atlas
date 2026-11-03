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
| `itops:manage` | banking employees, department managers | report, acknowledge and resolve incidents; raise changes and record them implemented or failed; the SLA sweep |
| `itops:approve` | department managers, regional and global executives | approve or reject changes, close incidents |
| `itops:approve_major` | regional and global executives | high-risk changes, changes to tier-1 applications, registering applications, their profiles and dependencies, generating the estate |

## Known limitations

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
