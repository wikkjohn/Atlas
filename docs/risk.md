# Risk

Phase 47 (roadmap Milestone D, step 19). Risk covers:
- internal credit ratings, suggested by a model, with four-eyes approval for overrides;
- obligor credit limits, measured against each customer's credit exposure;
- IFRS 9 expected-credit-loss (ECL) provisioning, posted to the ledger by a second person.

Code: `backend/app/modules/risk/`. Page: **Risk** (`/risk`, `risk:read`).

## The rating scale

Ten grades. Each has a one-year probability of default (PD) and a default credit limit.

| Grade | PD | Default limit (US$) |
| ---: | ---: | ---: |
| 1 | 0.03 % | 25,000,000 |
| 2 | 0.06 % | 25,000,000 |
| 3 | 0.12 % | 10,000,000 |
| 4 | 0.25 % | 10,000,000 |
| 5 | 0.50 % | 2,000,000 |
| 6 | 1.00 % | 2,000,000 |
| 7 | 2.00 % | 500,000 |
| 8 | 5.00 % | 100,000 |
| 9 | 15.00 % | 0 |
| 10 (in default) | 100 % | 0 |

## Ratings

**The model** suggests a grade:
- it starts from the customer's KYC risk rating: low 4, medium 6, high 7, unrated 6;
- 90 or more days past due on any loan: grade 10;
- otherwise 30 or more days past due: two grades worse;
- a frozen commercial facility: one grade worse;
- capped at 9 unless in default.

It records what it saw (`factors`): the KYC rating, the worst days past due and the frozen
facilities.

**A rating** (`RAT-`, `risk:rate`) takes the model's grade, or another with a rationale of at
least ten characters (rule `rationale_required`).
- The model's grade is approved at once.
- Any other grade is `pending` until someone other than the rater approves or rejects it
  (`risk:approve`; rule `four_eyes`, also a database constraint). One pending rating per
  customer: another override while one waits is a conflict (409).
- A rating lasts a year. The customer's grade is their latest approved, unexpired rating;
  without one, the model's.

## Limits and exposure

**Exposure** is measured per customer, in US dollars at the FX anchor rate:
- active loans: the ledger balance; a loan with a property is a mortgage;
- commercial facilities (active, frozen or terminated): drawn, plus 50 % of an active
  revolving facility's undrawn headroom (the credit conversion factor);
- overdrawn accounts.

**The limit** is the grade's default unless one is set (`PUT /risk/limits`, `risk:approve`).
An obligor whose exposure is above their limit is a **breach**; the breaches list is
largest excess first.

## ECL provisioning

A provisioning run (`PRV-`, `risk:rate`) measures every exposure as of today:

ECL = exposure at default (EAD) × PD × loss given default (LGD)

| Stage | When | PD applied |
| ---: | --- | --- |
| 1 | Otherwise | The grade's one-year PD |
| 2 | 30+ days past due, grade 8 or worse, or a frozen facility (a significant increase in credit risk) | Lifetime: the one-year PD × the remaining years (1–5), at most 100 % |
| 3 | 90+ days past due or grade 10 (credit-impaired) | 100 % |

| Exposure | LGD |
| --- | ---: |
| Mortgage | 15 % |
| Facility | 40 % |
| Loan | 45 % |
| Overdraft | 60 % |

The run stores a line per exposure and totals per currency: stage 1–3, ECL, EAD, the
allowance before and the change.

**Posting** (`risk:approve`) is by someone other than the calculator (rule `four_eyes`,
also a database constraint). For each currency it brings the loss allowance
(`RISK-ALLOWANCE-<CCY>`, a liability) to the run's ECL. The change is charged to impairment
expense (`RISK-IMPAIRMENT-<CCY>`), or released from it when the ECL fell. A currency with
an allowance but no exposure left is measured at zero, so posting releases it. Postings
are serialised. A run calculated before one already posted (by date, then calculation) is
refused (rule `superseded`); it can be rejected instead.

## Workflows

| Workflow | What it does |
| --- | --- |
| WF-1030 Obligor Credit Rating | Rates a customer; a grade departing from the model's goes to a second person's approval |
| WF-1031 Obligor Limit Change | Reads the obligor's grade and exposure, then sets a limit after approval |
| WF-1032 ECL Provisioning Run | Calculates the ECL; an approver posts it to the ledger or rejects it |

The risk handlers need `risk:rate` to start a workflow using them and `risk:read` to read
its executions through the API.

## Simulation workload and AI tool (Phase 48)

The `rating_overrides` workload drives WF-1030 v2 (scenario `rating-overrides`).
- **Cases:** each case is a customer in one of the run's countries, rated low or medium KYC
  risk (model grade 4 or 6). Their current account gets three months of dated deposits, and
  some an arranged overdraft drawn to 85–100 % or a loan, through the real accounts, retail
  and lending services. The case proposes a grade other than the model's with a rationale,
  so a regional executive (`risk:approve`) decides every case.
- **Ground truth, approve:**
  - a downgrade of two notches with the overdraft drawn;
  - a downgrade with debt at 1.6–3 times a year's money in;
  - a one-notch precautionary downgrade;
  - a one-notch upgrade for a customer whose money in is 6–24 times their debt.
- **Ground truth, reject:**
  - an upgrade with the overdraft drawn;
  - a departure of three notches or more, either way;
  - grade 10 (in default) without arrears;
  - an upgrade the rater asked for, and was refused, two or three times this year.
- **Decisions:** in AI-assisted runs the AGB Rating Review Assistant advises the approver,
  from the profile `risk.rating_profile` reads. The profile covers:
  - the model's and the proposed grade, and the notches between them;
  - days past due and frozen facilities;
  - exposure, the overdraft drawn against the arranged one;
  - deposits in the last 90 days (a month's average) against debt;
  - the default limits at both grades;
  - the customer's other departures from the model in the last year, and how many were
    rejected.
- **Control check:** four-eyes and `risk:approve` on each decision, and no departing grade
  approved without it.

What it measured, and the assistant's blind spot, is in [ai-testing.md](ai-testing.md).

## Limitations

- **A simple model:** PDs and LGDs are fixed per grade and exposure type. There are no
  macroeconomic scenarios, collateral values or discounting.
- **On request only:** nothing calculates or posts provisions on a schedule, and a breach
  blocks no lending.
- **Simulation scope:** the workload covers rating overrides (`rating-overrides`); limits
  and provisioning are not simulated.
- **Exposure is read today:** a run's ECL uses each obligor's grade as of the run date.
