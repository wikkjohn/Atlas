# Thin departments

Phase 61 (roadmap Milestone D, step 33). Seventeen of the bank's support departments run on
one data-driven framework rather than a module each (Branch Network joined in Phase 62):

| Department | Processes (the first carries an amount) |
| --- | --- |
| Legal | outside counsel instruction · contract review · legal hold |
| Internal Audit | audit engagement · finding closure · follow-up review |
| Marketing | campaign approval · financial promotion review · brand asset request |
| Facilities | capital works request · maintenance request · space change |
| Information Security | security tooling purchase · security exception · vulnerability remediation |
| Data Office | external data purchase · data access request · data quality issue |
| Business Continuity | recovery site booking · continuity plan review · recovery test report |
| Corporate Communications | sponsorship · press release · media enquiry |
| Investor Relations | investor roadshow · market disclosure · shareholder query |
| Strategy | strategy consultancy · strategic initiative · market study |
| Tax | external tax advice · tax filing sign-off · tax query |
| Company Secretariat | board event · board paper · statutory filing |
| Model Risk | external validation · model change · model registration |
| Operational Risk | insurance purchase · risk acceptance · loss event |
| Regulatory Affairs | licence fee payment · regulator response · rule change assessment |
| Sustainability | carbon offset purchase · green finance label · ESG data return |
| Branch Network | branch cash order · opening hours change · ATM fault report |

With the eighteen departments that have their own modules, the bank has 35 (see
**Milestone D coverage** below). Code:
`backend/app/modules/backoffice/` (the registry is `registry.py`). Page: **Departments**
(`/departments`, `departments:read`).

## Processes

Each process is defined in the registry:
- **approval:** whether someone other than the requester decides the request. A process
  without approval is ready to complete as soon as it is submitted.
- **target:** hours from submission to completion. A request completed later is marked as
  a breach; an unfinished one past its target counts as overdue.
- **amount** (the first process of every department): what it is (a fee estimate, a media
  budget…), in US dollars. It comes with:
  - a **budget**: above it the request is out of policy. Nothing forbids approving it;
    whether to is the approver's judgement, and the page flags it;
  - an **executive threshold**: above it only an executive (`departments:approve_major`)
    may approve (rule `needs_executive`).

## Requests

A request (`DR-`) has a department, a process, a title, optional details and, for the first
process, the amount (rule `amount_required`; other processes carry none, rule
`amount_not_expected`):
1. **submitted** (`departments:request`): it waits for a decision, or, without approval, is
   approved at once;
2. **approved or rejected** (`departments:approve`) by someone other than the requester
   (rule `four_eyes`, also a database constraint), with an optional note;
3. **completed** (`departments:request`) once approved, on time or as a breach.

## Workflows

Each process has a stored workflow, generated from the registry rather than written as a
file: WF-1100 to WF-1150, three per department in registry order (WF-1100 to WF-1102 for
Legal, and so on). `examples.documents()` includes them, so `seed-demo` imports them and the
factory's generated tests cover them like any other example. Each is classified in the
catalogue under its department, tagged `thin-department`.
- **With approval:** submit → approval (`departments:approve`) → approve and complete, or
  reject.
- **Without approval:** submit → complete.

Handlers: `backoffice.submit_request` (the department and process are constants in its
parameters), `backoffice.approve_request`, `backoffice.reject_request` and
`backoffice.complete_request`. They need `departments:request` to start and
`departments:read` to read executions.

## Simulation workload

One workload, `department_requests`, serves every department, with one scenario each:
`dept-legal`, `dept-internal-audit`, … `dept-branch-network`. Each runs the department's
first process, decided by simulated department managers.
- **Approved:** routine and urgent requests within the budget.
- **Rejected:** requests over the budget (below the executive threshold, so a manager may
  approve them), and the same request submitted again after it was approved and completed.

A control check covers four-eyes, `departments:approve`, and nothing approved without the
decision. The departments have no AI tool, so the scenarios run in baseline mode only.

## Milestone D coverage (Phase 62)

`GET /api/v1/backoffice/coverage` (`departments:read`), and a panel on the Departments page,
list every department of the bank with:
- its **base processes**: the stored and code workflows whose catalogue department is the
  department, or, without one, whose business owner is. Older owner names map onto one
  department each: Retail Banking Operations onto Retail Banking, Retail Banking — Customer
  Onboarding onto Customer Onboarding, Retail Lending — Collections onto Collections;
- its **workloads**: the simulation scenarios that run one of those workflows;
- its **dashboard**: its own page, or this page for a thin department.

A department is complete with three or more processes, a scenario and a dashboard. A test
checks that 35 or more are, and that every dashboard is a page the navigation links to. At
Phase 62 all 35 are:
- **with their own modules (18):** Customer Onboarding, Retail Banking, Retail Lending,
  Cards, Mortgages, Commercial Lending, Trade Finance, Treasury, Payments Operations,
  Wealth Management, Financial Crime Compliance, Credit Risk, Finance, Customer Service,
  Collections, Human Resources, Procurement, IT Operations;
- **thin (17):** the departments in the table above.

To get there, Phase 62 added:
- **WF-1052 Customer Risk Re-rating** (Customer Onboarding): a compliance officer approves
  a new risk rating before it is recorded, and the customer is written to;
- **WF-1053 Loan Early Payoff** and **WF-1054 Loan Arrears Repayment** (Retail Lending):
  the loan profile (`lending.loan_profile`: payoff amount, arrears, the account's funds),
  an approval by someone other than whoever started it (`loans:approve`), then
  `lending.pay_off` or `lending.repay_arrears`, which move money from the borrower's account
  through loan servicing;
- **Branch Network** as a seventeenth thin department. The catalogue already classified
  WF-1002 Paper Statement Request under it.

## Permissions

| Permission | Roles | What it allows |
| --- | --- | --- |
| `departments:read` | banking employees, department managers, regional and global executives, auditors | the page and the lists |
| `departments:request` | banking employees, department managers | submit and complete requests |
| `departments:approve` | department managers, regional and global executives | approve or reject requests |
| `departments:approve_major` | regional and global executives | requests above a process's executive threshold |

## Known limitations

- **Thin by design:** no domain records beyond the request; legal matters, audit findings
  or campaigns are not modelled in their own right, and nothing posts to the ledger.
- **One currency:** amounts are US dollars.
- **No AI tool** and no ground truth beyond the budget and duplicates.
- **The same simulated day:** every department's scenario has the same mix and reviewer
  model, so their baseline results match except for amounts.
