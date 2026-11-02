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
Intranet (tier 3). Executives (`itops:approve_major`) register more. Milestone E will
generate the 2,500-application estate on this catalogue and wire workflows to it.

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

## Permissions

| Permission | Roles | What it allows |
| --- | --- | --- |
| `itops:read` | banking employees, department managers, regional and global executives, auditors | the page and the lists |
| `itops:manage` | banking employees, department managers | report, acknowledge and resolve incidents; raise changes and record them implemented or failed; the SLA sweep |
| `itops:approve` | department managers, regional and global executives | approve or reject changes, close incidents |
| `itops:approve_major` | regional and global executives | high-risk changes, changes to tier-1 applications, registering applications |

## Known limitations

- **Workflows do not call applications yet:** an outage does not delay the processes that
  depend on the application (Milestone E).
- **No on-call rota:** acknowledging an incident stands for paging the engineer.
- **Targets run on the clock,** not on business hours, and are not paused while waiting on
  a third party.
- **No problem records:** a P1's review is free text; recurring incidents are not linked.
- **A change's window is not enforced** when it is implemented.
- **Not simulated yet:** no workload drives these workflows.
