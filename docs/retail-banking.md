# Retail banking

Phase 29 (roadmap Milestone D, step 1). The first department of Milestone D covers:
- deposit products and their terms;
- arranged overdrafts;
- standing orders;
- the month end that pays interest, charges fees and issues statements.

Every amount moves through the ledger.

Code: `backend/app/modules/retail/`.

## Products

`retail_products` holds the terms of each account type:
- interest a year on credit balances (basis points);
- interest a year on overdrawn balances;
- a monthly fee;
- the largest arranged overdraft.

The fee and the overdraft maximum are set in US dollars and converted to each account's
currency at the synthetic FX anchor rates:
- the fee is converted exactly to minor units;
- the overdraft maximum is rounded to two significant figures.

The same terms therefore apply in all 120 countries. Migration 0025 loads version 1:

| Product | Credit interest | Overdraft interest | Monthly fee | Overdraft up to |
| --- | --- | --- | --- | --- |
| Everyday Current Account (`current`) | 0 % | 19.90 % | US$5.00 | US$2,500 |
| Instant Access Savings (`savings`) | 2.50 % | — | none | none |
| Business Current Account (`business_current`) | 0 % | 14.90 % | US$15.00 | US$25,000 |

Managers (`retail:manage`) change the terms on the Retail Banking page or with
`PATCH /retail/products/{type}`. Each change is audited.

## Arranged overdrafts

Every account has an `overdraft_limit`, in minor units, which is 0 unless one is arranged.
What an account can pay out is its balance plus that limit. This applies to every funds
check:
- withdrawals;
- fees;
- the WF-0002 funds check;
- the payments service at release.

A limit:
- cannot exceed the product's maximum;
- cannot be set on a product without overdrafts (savings);
- cannot go below what the account already owes.

There are two ways to arrange one:
- **WF-1003 Arranged Overdraft Request:** a credit officer other than the person who took
  the request approves before `retail.set_overdraft` sets the limit. The handler requires
  an approval, and validation refuses any definition that could reach it without one.
- **`PUT /retail/accounts/{id}/overdraft`:** for managers with `retail:manage`.

Both are audited (`account.overdraft_changed`). The account view shows the arranged
overdraft and what is available.

## Standing orders

A standing order pays a fixed amount from one account to another in the same currency,
weekly or monthly. Monthly orders keep their day: an order set up for the 31st pays on
28 February, then on 31 March.

**Setting one up:** use the Retail Banking page, `POST /retail/standing-orders` (tellers,
`accounts:transact`), or WF-1004.
- WF-1004 Standing Order Setup screens the payee against the sanctions lists first, and
  holds a match for compliance.
- The amount must be below the payer's country's high-value threshold, because payments
  at or above it need a second person's approval every time.

**The daily job** `retail.standing_orders` (schedule `retail-standing-orders`, off by
default) pays every order that is due.
- **Business days:** it pays on business days of the payer's country. An order due on a
  weekend or holiday waits for the next business day.
- **How it pays:** through the payments service: a payment is created and released, with
  the usual limits, value date and ledger posting.
- **Missed payments:** a payment that cannot be made (not enough funds, even with the
  overdraft) is not retried; the order moves to its next date. After three misses in a
  row it stops with status `failed`.

## Month end

The job `retail.month_end` (schedule `retail-month-end`, off by default, or *Run month
end* on the page) runs once for each calendar month that has ended. It covers every open
or frozen account of a retail product opened by the month's end.

**Interest.** The annual rate is applied to each day's closing balance (by effective
date), divided by 365, summed over the month and rounded once:
- credit balances earn the product's credit interest, paid from `INTEREST-EXPENSE-<ccy>`;
- overdrawn days are charged the overdraft interest, credited to `INTEREST-INCOME-<ccy>`.

**Fees.** Accounts open for the whole month pay the monthly fee, credited to
`FEE-INCOME-<ccy>`.

**Postings.** All postings take effect on the last day of the month. They are idempotent
per account and month, so running again posts nothing twice.

**Statements.** Each account then gets that month's statement:
- what it records: opening and closing balance, credits, debits, the number of entries
  and the overdraft limit;
- where the entries come from: the ledger, by effective date.

**The run.** It records its totals per currency (interest paid, interest charged, fees).
A month that has not ended is refused.

**Statement copies.** WF-1005 Statement Copy Request, through `retail.issue_statement`,
returns a statement on request. If month end has not issued one yet, it issues it.

## The base processes (workflow factory)

| Workflow | Library handlers it adds | Effect |
| --- | --- | --- |
| WF-1003 Arranged Overdraft Request | `retail.set_overdraft` | writes; approval required |
| WF-1004 Standing Order Setup | `retail.create_standing_order` | writes |
| WF-1005 Statement Copy Request | `retail.issue_statement` | writes |

`seed-demo` imports all three. Their generated path tests pass with 100 % step and route
coverage (WF-1003: 14 cases, WF-1004: 17, WF-1005: 10). To give a standing order two
different accounts, the generated tests now provide a second customer's account, the
fixture kind `payee.account_number`.

## Simulation workload and AI tool (Phase 30)

The `retail_overdrafts` workload drives WF-1003 v2 (scenario `retail-overdrafts`).
- **Customers:** each case is an existing customer whose current account has three months
  of history in the ledger: salaries and spending, effective on past dates.
- **Ground truth:** affordable requests from steady earners are approved. Declined:
  limits above a month's income, income in only one of three months, customers already
  overdrawn most days, and limits above the product's maximum.
- **Decisions:** credit officers decide. In AI-assisted runs the AGB Overdraft
  Affordability Assistant advises them.
- **Control check:** four-eyes and approval authority on each decision, and no limit set
  without an approval.

What it measured, and the assistant's blind spot, is in [ai-testing.md](ai-testing.md).

## API and permissions

See [api.md](api.md) (*Retail banking*). Reading needs `accounts:read`. Standing orders
need `accounts:transact`. Product terms, direct overdraft limits and month end need the
new permission `retail:manage`, held by department managers and the scheduler.

## Limitations

- Interest is simple and daily on the closing balance, with 365 days every year. There is
  no compounding within the month, no tiered rates and no unarranged-overdraft fees.
- Standing orders are same-currency only and never at or above the high-value threshold.
- Statements are records with their entries. There is no PDF or postal rendering.
