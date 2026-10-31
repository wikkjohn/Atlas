# SME and commercial lending

Phase 35 (roadmap Milestone D, step 7). The commercial lending department covers:
- credit facilities for business customers: term loans and revolving credit;
- drawdowns and repayments through the ledger;
- financial covenants, tested on each year's figures;
- annual reviews that renew or terminate a facility.

Code: `backend/app/modules/commercial/`.

## Facilities

A facility is proposed for a verified business customer and drawn into its open business
current account, in that account's currency. The proposal is refused unless it meets
these rules:

| Rule | Value |
| --- | --- |
| Limit | US$50,000 to 5,000,000, converted to the account's currency (two significant figures) |
| Term | 12 to 120 months; revolving credit at most 60 |
| Rate (fixed, a year) | term loan 6.50 %, revolving credit 7.50 % |
| Covenants (defaults, changeable at proposal) | DSCR (EBITDA ÷ debt service) at least 1.25×; leverage (total debt ÷ EBITDA) at most 3.5× |

**Approval** (also database constraints):
- A credit approver (`loans:approve`) other than the proposer approves or declines.
- Above US$1,000,000 the credit committee (`loans:approve_large`) must approve as well,
  and that must be a third person.

**Activation.** Once approved, the facility is active: a receivable account
`1350-<facility number>` is opened in the ledger, the annual review is due in a year, and
the facility matures at the end of its term.

## Drawdowns and repayments

- **Drawdown:** the facility's receivable is debited and the business account credited.
- **Repayment:** the reverse. The business account must be able to pay, counting any
  arranged overdraft.

**What can be drawn:**
- **Revolving credit:** up to the limit less what is drawn; repaid amounts can be drawn
  again.
- **Term loan:** up to its limit once over its life; repaid amounts cannot be drawn again.

**No drawdowns** while the facility is frozen or terminated, after its annual review is
overdue, or after it matures. The facilities table shows why a facility cannot be drawn.

## Covenants

Each year's figures (EBITDA, debt service and total debt, in minor units) are tested
against the facility's covenants: once per period, recording the actual ratio and whether
each covenant was met.

**A breach freezes the facility.** The credit committee (`loans:approve_large`), but not
the person who submitted the figures, may waive it. When no unwaived breach is left, the
facility can be drawn again. Tests, breaches and waivers are audited.

## Annual reviews

A review can be opened from 60 days before the facility's review is due, one at a time.
A credit approver other than the person who opened it decides:
- **Renew:** the next review is due a year after this one; the limit may change, but not
  below what is drawn.
- **Terminate:** no further drawdowns; repayments only.

A review left undecided past its due date stops drawdowns.

## The base processes (workflow factory)

| Workflow | Library handlers it adds | Effect |
| --- | --- | --- |
| WF-1012 Commercial Facility Application | `commercial.propose_facility`, `commercial.approve_facility`, `commercial.committee_approve`, `commercial.decline_facility` | writes; both approvals require an approval step |
| WF-1013 Covenant Compliance Test | `commercial.lookup_facility`, `commercial.test_covenants`, `commercial.waive_breach` | writes; a waiver requires an approval |
| WF-1014 Annual Facility Review | `commercial.open_review`, `commercial.renew_facility`, `commercial.terminate_facility` | writes; renewal requires an approval |

- **WF-1012** records the proposal, has a credit approver decide and, when the facility
  is above US$1m, the credit committee.
- **WF-1013** tests the year's figures. On a breach, the committee decides whether to
  waive it.
- **WF-1014** opens the review and has a credit approver renew or terminate.

`seed-demo` imports all three. Their generated path tests pass with 100 % step and route
coverage (WF-1012: 23 cases, WF-1013: 17, WF-1014: 16). The generated tests provide three
new fixture kinds:
- `business.customer_number`: a verified business;
- `business.account_number`: its funded business current account;
- `facility.facility_number`: an active revolving facility whose review is due in 30 days.

## API and permissions

See [api.md](api.md) (*Commercial lending*). Reading needs `loans:read`.
- Proposals, drawdowns, repayments, covenant figures and opening a review need
  `accounts:transact`.
- Approval, declining and review decisions need `loans:approve`.
- The committee's approval and waivers need `loans:approve_large` (executives).

## Limitations

- **No interest:** interest is not accrued or charged on drawn balances, and there are no
  fees or repayment schedules for term loans.
- **Covenants:** two financial covenants only, tested on figures the bank is given; no
  financial statements are analysed.
- **No security:** facilities are unsecured; there is no collateral or guarantee.
- **Reviews:** a review that is never opened only blocks drawdowns; no job raises it.
- **No simulation yet:** there is no commercial lending workload or AI tool (the next
  step, Phase 36).
