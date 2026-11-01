# Finance

Phase 49 (roadmap Milestone D, step 21). Finance covers:
- the general ledger's month-end close;
- regulatory reporting extracts, submitted to a synthetic regulator;
- shared operating costs, allocated to departments.

Code: `backend/app/modules/finance/`. Page: **Finance** (`/finance`, `finance:read`).

## The month-end close

**Preparing** a close (`CLS-`, `finance:close`) for a month (`YYYY-MM`) runs its checks and
measures each currency's result: the income and expense not yet closed as of the month's end.

| Check | Passes when | Blocking |
| --- | --- | --- |
| `period_ended` | The month is over | Yes |
| `trial_balance` | Debits equal credits in every currency, over entries effective by the month's end | Yes |
| `reconciliation` | A ledger reconciliation run since the month's end passed. If none has run, the close runs an incremental one itself | Yes |
| `provisions_posted` | An ECL provision run was posted for the month | No (advisory) |

**Closing** (`finance:approve`) is by someone other than the preparer (rule `four_eyes`,
also a database constraint), and not while a blocking check fails (rule `checks_failed`).
For each currency it posts one closing entry dated the month's end:
- every income and expense account's balance as of that date is brought to zero;
- the net result goes to retained earnings (`FIN-RETAINED-<CCY>`, equity).

**Order.** A month is prepared or closed once. Months close in order: after the first close,
the next one closed must be the month after the last closed (rule `out_of_order`), both when
preparing and when closing. A later month closed first would leave an earlier month's result
to be closed twice.

**Late entries.** Nothing stops an entry being dated into a closed month. Its income or
expense is still open as of the next month's end, so the next close takes it up, as a
prior-period adjustment.

## Regulatory reports

A report (`REG-`, `finance:close`) is extracted for a closed month (rule `period_open`
otherwise).

| Type | Rows |
| --- | --- |
| `balance_sheet` | Assets, liabilities and equity per currency as of the month's end; the summary checks that assets equal liabilities, equity and any result not yet closed |
| `income_statement` | Each income and expense account the close brought to zero, per currency, with income, expense and net result |
| `large_exposures` | Obligors with exposure of US$10,000 or more, largest first (at most 50), with their grade |
| `credit_quality` | The latest ECL provision run posted by the month's end: EAD, stage 1–3 and ECL per currency |

**Submitting** (`finance:approve`) is by someone other than the preparer (rule
`four_eyes`). It records a synthetic reference, `REGU-<month>-<number>`. Only one report of
each type is submitted per month; a second is a conflict (409). Every report downloads as
CSV.

## Shared costs and allocation

**Recording a shared operating cost** (`POST /finance/expenses`, `finance:close`, with an
Idempotency-Key) posts it straight away. It debits the currency's shared cost pool
(`FIN-SHARED-COSTS-<CCY>`, expense) and credits cash.

**An allocation** (`ALC-`, `finance:close`) splits a month's pool in a currency across
departments:
- the pool is its balance as of the month's end;
- the driver is each department's active employees, counting those in its teams;
- shares are split by largest remainder, so they add up to the pool.

**Posting** (`finance:approve`) is by someone other than the calculator. It moves the pool to
each department's cost centre (`FIN-COST-<department>-<CCY>`, expense), dated the month's
end. It needs the month to be open (rule `period_closed`) and the pool to be unchanged since
the split (rule `pool_changed`).

## Workflows

| Workflow | What it does |
| --- | --- |
| WF-1033 Month-End Close | Prepares the close; an approver closes the month or rejects it |
| WF-1034 Regulatory Report Submission | Extracts a report for a closed month; an approver submits or rejects it |
| WF-1035 Cost Allocation | Splits a month's shared costs; an approver posts or rejects the split |

The finance handlers need `finance:close` to start a workflow using them and `finance:read`
to read its executions through the API.

## Permissions

- **`finance:read`:** executives, department managers and auditors.
- **`finance:close`:** department managers.
- **`finance:approve`:** global and regional executives.

## Limitations

- **No hard lock.** A closed month accepts backdated entries; the next close takes them up
  rather than refusing them.
- **Reports from today's exposures.** Large exposures are read from today's balances, not
  as of the month's end.
- **One driver.** Costs are allocated by headcount only, and shared costs are recorded by
  hand.
- **A synthetic regulator.** Submitting records a reference; nothing is sent.
