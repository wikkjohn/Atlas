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

## Manual journals (Phase 50)

A manual journal (`MJ-`, `finance:close`) is two to twenty lines on the bank's own ledger
accounts in one currency, with debits equal to credits. It is refused on a customer's
account (rule `customer_account`); those move only through their own services. Nothing is
posted until someone other than the preparer approves it (`finance:approve`; rule
`four_eyes`, also a database constraint). The entry is dated the journal's effective date.

**The journal profile** (`finance.journal_profile`) is what the approver weighs:
- the amount in US dollars against materiality (US$100,000);
- the kinds of account it touches: equity, cash, income;
- how many days back it is dated, and whether into a closed month;
- a round amount (whole thousands);
- the length of its description;
- an identical journal (same amount, accounts and sides) posted in the 30 days before;
- the preparer's other journals in the last seven days on the same accounts (other than
  cash), and their total.

## Simulation workload and AI tool (Phase 50)

The `journal_review` workload drives WF-1036 v2 (scenario `journal-review`).
- **Cases:** each case is a manual journal in US dollars on its own simulation ledger
  accounts. It is proposed by a manager, and any earlier journals it needs are proposed and
  posted first. A regional executive decides every case.
- **Ground truth, post:**
  - a routine accrual of US$2,000–40,000;
  - a reclassification between two expense accounts;
  - a material accrual (1.5–4 times materiality) with a full description.
- **Ground truth, reject:**
  - a journal from retained earnings to income;
  - an accrual dated 45–120 days back;
  - a duplicate of an accrual posted 3–20 days before;
  - a round cash payment described only as "Adjustment";
  - a large entry split into pieces, each 70–95 % of materiality, two or three of them posted
    in the days before.
- **Decisions:** in AI-assisted runs the AGB Journal Review Assistant advises the approver
  from the journal profile.
- **Control check:** four-eyes against both the initiator and the preparer, `finance:approve`
  on each decision, and no journal posted without it.

What it measured, and the assistant's blind spot, is in [ai-testing.md](ai-testing.md).

## Workflows

| Workflow | What it does |
| --- | --- |
| WF-1033 Month-End Close | Prepares the close; an approver closes the month or rejects it |
| WF-1034 Regulatory Report Submission | Extracts a report for a closed month; an approver submits or rejects it |
| WF-1035 Cost Allocation | Splits a month's shared costs; an approver posts or rejects the split |
| WF-1036 Manual Journal Approval | v1: an approver posts or rejects a proposed journal. v2 (Phase 50): the journal profile and the AGB Journal Review Assistant's advice first |

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
- **Simulation scope.** Only manual journal review is simulated; closes, reports and
  allocations are not.
