# Trade finance

Phase 37 (roadmap Milestone D, step 9). The trade finance department covers:
- letters of credit and bank guarantees for business customers;
- beneficiaries screened against every synthetic sanctions list;
- documents presented under a letter of credit, checked for discrepancies;
- claims under a guarantee, paid on demand;
- a cash margin held while an instrument is live.

Code: `backend/app/modules/trade/`.

## Instruments

An instrument is requested for a verified business customer, in the currency of its open
business current account. The request is refused unless it meets these rules:

| Rule | Value |
| --- | --- |
| Amount | US$10,000 to 5,000,000, converted to the account's currency (two significant figures) |
| Expiry | 30 to 730 days ahead |
| Beneficiary | screened against every synthetic sanctions list; a match refuses the request (rule `sanctions_hit`) |
| Cash margin | letter of credit 20 %, guarantee 10 % of the amount |

The screening result is kept on the instrument. Numbers are `LC-` (letter of credit) or
`BG-` (guarantee) followed by seven digits.

**Approval** (also database constraints):
- A credit approver (`loans:approve`) other than the requester approves or declines.
- Above US$1,000,000 the credit committee (`loans:approve_large`) must approve as well,
  and that must be a third person.

**Issue.** Once approved, the instrument is issued and its margin is moved from the
business account to `TRADE-MARGIN-<currency>`, a liability. If the account cannot provide
the margin, counting any arranged overdraft, the approval is refused.

## Demands

A demand is documents presented under a letter of credit, or a claim under a guarantee.
- It must be presented on or before the expiry date.
- It must be for no more than is left undrawn.
- Only one demand per instrument can be pending at a time.

**Documents (letters of credit).** The checker records any discrepancies:
- late shipment;
- late presentation;
- inconsistent documents;
- a missing document;
- a description that does not match the credit.

A complying presentation is paid. A discrepant one is paid only if the applicant waives the
discrepancies, and the decision note says so. Otherwise it is rejected.

**Claims (guarantees).** A guarantee pays on demand: no documents are examined, and a
claim recorded with discrepancies is refused.

**Decision.** Someone with `trade:manage` other than the person who received the demand
pays or rejects it. Payment locks the demand, the instrument and the account, then:
1. releases the margin in proportion to the amount paid (all of it on the last payment);
2. debits the applicant's account and credits `TRADE-SETTLEMENT-<currency>`.

When the full amount is drawn the instrument is `paid`. A rejection leaves it issued.

**Expiry.** After its expiry date, `trade:manage` can close an issued instrument with no
pending demand. What is left of the margin returns to the business account. Requests,
decisions, demands, payments, rejections and expiries are audited.

## The base processes (workflow factory)

| Workflow | Library handlers it adds | Effect |
| --- | --- | --- |
| WF-1015 Trade Instrument Issuance | `trade.request_instrument`, `trade.approve_instrument`, `trade.committee_approve`, `trade.decline_instrument` | writes; both approvals require an approval step |
| WF-1016 Documentary Presentation | `trade.lookup_instrument`, `trade.receive_demand`, `trade.pay_demand`, `trade.reject_demand` | moves money; payment requires an approval |
| WF-1017 Guarantee Claim | the same four | moves money; payment requires an approval |

- **WF-1015** screens and records the request, has a credit approver decide and, above
  US$1m, the credit committee.
- **WF-1016** finds the letter of credit and records the presentation. A complying one goes
  to the document checker. A discrepant one goes to the applicant's waiver. Either approval
  pays; otherwise the presentation is rejected.
- **WF-1017** finds the guarantee, records the claim, and has `trade:manage` pay or reject
  it.

`seed-demo` imports all three. Their generated path tests pass with 100 % step and route
coverage (WF-1015: 23 cases, WF-1016: 25, WF-1017: 16). The generated tests provide two new
fixture kinds:
- `letter_of_credit.instrument_number`;
- `guarantee.instrument_number`.

Both are issued instruments of 5,000,000 minor units valid for 120 days, for a test
business whose account now holds 100,000,000.

## API and permissions

See [api.md](api.md) (*Trade finance*). Reading needs `loans:read`.
- Requests and demands need `accounts:transact`.
- Approval and declining need `loans:approve`; the committee needs `loans:approve_large`.
- Paying or rejecting a demand and closing an expired instrument need `trade:manage`
  (department managers and compliance officers).

## Limitations

- **Settlement:** payments stop at the settlement account. Nothing is sent to the
  beneficiary's bank, and there is no correspondent or nostro.
- **Documents:** discrepancies are recorded by the checker, not found by examining
  documents. There are no amendments, transfers, confirmations, or usance (deferred
  payment) credits.
- **Fees and limits:** no commissions are charged, and there are no customer trade limits
  beyond the margin.
- **Expiry:** nothing closes expired instruments automatically.
- **Simulation:** no trade finance workload or AI tool yet (Phase 38).
