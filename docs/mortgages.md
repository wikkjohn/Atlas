# Mortgages and secured lending

Phase 33 (roadmap Milestone D, step 5). The mortgages department covers:
- the properties customers buy, and their valuations;
- a decision in principle that checks every lending rule;
- mortgage offers decided by a second person;
- completion: the mortgage becomes an ordinary loan charged on the property.

Code: `backend/app/modules/mortgages/`. Addresses, prices and values are synthetic.

## Products

`mortgage_products` holds each product's largest loan-to-value, fixed rate, longest term
and loan sizes. Loan sizes are set in US dollars and converted to the property's currency
at the synthetic FX anchor rates (two significant figures), so the same products apply in
all 120 countries. Migration 0027 loads two:

| Product | Loan-to-value up to | Rate (fixed) | Term up to | Loan size |
| --- | --- | --- | --- | --- |
| ATLAS Home 75 (`home-75`) | 75 % | 4.49 % | 35 years | US$25,000–1,000,000 |
| ATLAS Home 90 (`home-90`) | 90 % | 5.79 % | 35 years | US$25,000–750,000 |

## Properties and valuations

A property is registered for the customer buying it, with its type (house or flat) and
purchase price. Its country and currency are the customer's, and it gets a synthetic
address in that country's format.

There are two kinds of valuation:
- **Desktop:** the synthetic automated valuation model values the property between 85 %
  and 114 % of its price, the same every time for the same property. Tellers
  (`accounts:transact`) request it.
- **Surveyor:** a person records the value they found. This needs the new permission
  `mortgages:manage` (department managers), and the valuation names the surveyor.

Every valuation is audited.

## The lending rules

A decision in principle (`POST /mortgages/quote`, or `mortgages.quote` in a workflow)
checks every rule and returns them all, passed or failed, with the figures. Nothing is
written.

| Rule | Passes when |
| --- | --- |
| `kyc_verified` | the customer's KYC is verified |
| `property_owner` | the property is the applicant's |
| `account` | the drawdown account is an open current account of the applicant in the property's currency |
| `loan_limits` | the loan is within the product's converted sizes |
| `term` | 5 years up to the product's longest term |
| `valuation` | the property has a valuation from the last 180 days |
| `loan_to_value` | the loan against the lower of valuation and price is within the product's maximum |
| `valuation_method` | a desktop valuation supports up to 75 % loan-to-value; above that a surveyor must value the property |
| `affordability` | the monthly payment is at most 35 % of declared monthly income |
| `income_supported` | declared income is at most 1.5 times the synthetic bureau's estimate (US dollars, converted) |
| `credit_history` | bureau score at least 620 and no recent defaults |
| `unencumbered` | no live offer or loan on the property |

## Offers

1. **Application.** A teller applies with the same details. The application is refused,
   with the failed rules, unless every rule passes. Otherwise it is recorded as `pending`,
   with the payment, rate and loan-to-value fixed.
2. **Decision.** An underwriter (`loans:approve`) other than the person who took the
   application approves or declines. This four-eyes rule is also a database constraint.
   An approved offer is `offered` and valid for 90 days.
3. **Acceptance.** The customer accepts before the offer expires (`accepted`).
4. **Completion.** A colleague with `loans:approve`, again not the person who took the
   application, completes the mortgage. The loan is drawn down into the customer's
   account and the offer is `completed`.

A live offer (pending, offered or accepted) can be withdrawn. A property has at most one
live offer.

## Completion: an ordinary loan, charged on the property

Completion books a loan through the lending module (`lending.book_loan`, shared with
personal loans):
- **Ledger:** a loan receivable is debited and the customer's account credited.
- **The loan:** purpose `mortgage`, the offer's rate and term, and `loans.property_id`.
- **Servicing:** its repayment schedule exists from day one, and servicing, arrears,
  payoff and collections (WF-0004) apply unchanged.

Mortgage loans may run from 5 to 35 years; personal loans keep 6 to 84 months. A
property secures at most one live loan (a partial unique index). The Properties table
shows the loan a property is charged with.

## The base processes (workflow factory)

| Workflow | Library handlers it adds | Effect |
| --- | --- | --- |
| WF-1009 Mortgage Application | `mortgages.quote`, `mortgages.request_offer`, `mortgages.issue_offer`, `mortgages.decline_offer` | writes; issuing an offer requires an approval |
| WF-1010 Mortgage Completion | `mortgages.lookup_offer`, `mortgages.accept_offer`, `mortgages.complete` | completion moves money and requires an approval |
| WF-1011 Property Valuation Request | `mortgages.register_property`, `mortgages.desktop_valuation`, `mortgages.confirm_value` | writes; a surveyor's valuation requires an approval |

- **WF-1009** runs the decision in principle. An ineligible application ends with a
  letter listing the failed rules. An eligible one is recorded, and an underwriter other
  than the requester decides.
- **WF-1010** checks that the offer is the customer's and still open, records the
  acceptance, and completes after a second person's review.
- **WF-1011** registers the property and values it with the model. When the model comes
  in below 90 % of the price, a surveyor reviews; confirmed, the surveyor's valuation at
  the price is recorded.

`seed-demo` imports all three. Their generated path tests pass with 100 % step and route
coverage (WF-1009: 21 cases, WF-1010: 19, WF-1011: 16). The generated tests provide two
new fixture kinds:
- `property.property_number`: a surveyor-valued house;
- `mortgage_offer.offer_number`: an issued offer.

Both belong to a fixture customer chosen so that the synthetic bureau scores them well.

## Simulation workload and AI tool (Phase 34)

The `mortgage_applications` workload drives WF-1009 v2 (scenario `mortgage-applications`).
- **Cases:** each case is a creditworthy customer buying a house a surveyor valued at its
  price. The application passes every lending rule, so an underwriter decides each one; a
  case that would fail a rule stops the run.
- **Ground truth:** approved: prime borrowers, and strong borrowers at 86–89 %
  loan-to-value. Declined: stretched borrowers (a payment of 31–34 % of income at 86–89 %
  loan-to-value), income declared 35–45 % above the bureau's estimate, thin credit files
  (score 620–659) at a high loan-to-value, and terms that end when the applicant is 86 or
  older.
- **Decisions:** underwriters decide (`loans:approve`). In AI-assisted runs the AGB
  Mortgage Underwriting Assistant advises them, from the profile that
  `mortgages.application_profile` reads.
- **Control check:** four-eyes and authority on each decision, and no offer issued
  without an approval.

What it measured, and the assistant's blind spot, is in [ai-testing.md](ai-testing.md).

## API and permissions

See [api.md](api.md) (*Mortgages*). Reading needs `loans:read`.
- Registering properties, desktop valuations, quotes, applications, acceptance and
  withdrawal need `accounts:transact`.
- Decisions and completion need `loans:approve`.
- Surveyor valuations need `mortgages:manage`.

## Limitations

- Fixed rates only. There are no rate switches, overpayments, porting, further advances
  or second charges.
- Valuations are synthetic: the desktop model is a hash of the property number, and a
  surveyor in WF-1011 can only confirm the price.
- Completion pays the loan into the customer's account; there is no conveyancing.
- No fees.
- The simulation covers applications (`mortgage-applications`); completions and valuations
  are not simulated as workloads.
