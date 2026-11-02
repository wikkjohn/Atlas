# Collections and recoveries

Phase 53 (roadmap Milestone D, step 25). Collections and recoveries cover:
- payment plans for loans in arrears, activated by a second person;
- taking the plan's payments as they fall due, and breaking plans that are not kept;
- recoveries on written-off loans: borrower payments, collection-agency remittances and debt
  sales.

It extends WF-0004 Loan Collections: a loan on an active plan cannot be written off, and its
WF-0004 case waits on the plan.

Code: `backend/app/modules/collections/`. Page: **Collections** (`/collections`,
`loans:read`).

## The arrears book

Every active loan with an overdue instalment, most days past due first, with:
- its days past due, arrears amount, overdue instalments and bucket (as loan servicing
  reports them);
- the loan's open payment plan, if any.

## Payment plans

A plan (`PLN-`) spreads a loan's arrears into catch-up payments:
- **Proposed** (`loans:service`): one payment per overdue instalment, every 7 to 31 days,
  the first one interval after today. Rules: `not_in_arrears`, `interval_range`. A loan has
  at most one open plan (also a partial unique index).
- **Activated or rejected** (`loans:approve`) by someone other than the proposer (rule
  `four_eyes`, also a database constraint).
- **Payments are taken** by the collection run (`POST /collections/plans/collect`, WF-1042).
  Each payment due by the run's date settles the oldest overdue instalment from the
  borrower's account, through loan servicing's own repayment, so the ledger postings and
  WF-0004 see it exactly as a repayment:
  - **paid** when the account covers it;
  - **missed** when it does not;
  - **settled** when the borrower already cleared that instalment some other way.
- **Completed** when every payment is paid or settled. **Broken** at the second missed
  payment, or when the schedule ends with any payment missed.

While a plan is active:
- the loan cannot be written off (rule `plan_active` in `servicing.write_off`);
- its WF-0004 case does not escalate to a write-off review, even past 90 days. A write-off
  approved before the plan began is not booked (`on_plan`). Once the plan is broken, the
  next servicing run escalates the case as before.

## Recoveries

Money recovered on a written-off loan (`REC-`, `loans:service`):

| Kind | What it is | Posting |
| --- | --- | --- |
| `payment` | The borrower pays after the write-off | At once |
| `agency` | A collection agency remits what it collected | At once |
| `debt_sale` | The debt is sold to a debt buyer | When someone other than the recorder approves (`loans:approve_large`, rule `four_eyes`) |

- A recovery debits the bank's cash account and credits **loan loss recoveries**
  (`LOAN-RECOVERIES-<CCY>`, income).
- Rules: `not_written_off`, `recovery_invalid` (amount ≤ 0 or unknown kind) and
  `exceeds_written_off`: recoveries posted and awaiting approval never exceed the amount
  written off.
- A debt sale can be rejected; nothing is posted.

## Workflows

| Workflow | Steps | Handlers |
| --- | --- | --- |
| WF-1040 Payment Plan | propose → approval (`loans:approve`) → activate or reject | `collections.propose_plan`, `collections.approve_plan`, `collections.reject_plan` |
| WF-1041 Debt Sale | record → approval (`loans:approve_large`) → post or reject | `collections.record_debt_sale`, `collections.approve_recovery`, `collections.reject_recovery` |
| WF-1042 Plan Collection Run | collect | `collections.collect` |

The handlers need `loans:service` to start and `loans:read` to read executions. Their
generated tests take a loan in arrears and a written-off loan from fixtures.

## Demo data

The demo seed adds two synthetic borrowers whose loans were disbursed 70 and 150 days ago
and spent: the first is two instalments in arrears, the second was written off by the
regional executive. The book is serviced to today.

## Permissions

- `loans:read`: the arrears book, plans, written-off loans, recoveries and the summary.
- `loans:service` (department managers and the scheduler): propose plans, take payments,
  record recoveries.
- `loans:approve` (department managers): activate or reject plans.
- `loans:approve_large` (regional and global executives): approve or reject debt sales.

## Known limitations

- **No partial payments:** a plan payment is one whole overdue instalment; it is paid or
  missed.
- **Instalments falling due during the plan** are collected by loan servicing as usual, not
  by the plan.
- **No agency placement:** an agency remittance is recorded, but there is no record of
  placing the debt with the agency or its commission.
- **No collections workload or AI tool yet** (proposed Phase 54).
