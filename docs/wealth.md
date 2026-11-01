# Wealth and investments

Phase 43 (roadmap Milestone D, step 15). Wealth and investments cover:
- synthetic securities, with a price for every day;
- suitability: a questionnaire that gives each customer a risk profile;
- portfolios held in custody for customers;
- buy and sell orders checked against the customer's profile;
- income (coupons, dividends, fund distributions) paid to holders.

Code: `backend/app/modules/wealth/`.

## Securities

Ten synthetic securities are seeded (`seed-demo`, idempotent). Their names are invented for
the simulation.

| Code | Security | Class | Currency | Risk | Income a year |
| --- | --- | --- | --- | ---: | ---: |
| AGB-MMF-USD | Atlas Liquidity Fund (USD) | money market | USD | 1 | 4.50 % |
| AGB-GOVT-2031 | Synthetic Treasury 3.50% 2031 | bond | USD | 2 | 3.50 % |
| AGB-CORP-2029 | Meridian Utilities 4.80% 2029 | bond | EUR | 3 | 4.80 % |
| AGB-BAL-FUND | Atlas Balanced Fund | fund | GBP | 4 | 2.00 % |
| AGB-GLOBAL-EQ | Atlas Global Equity Fund | fund | USD | 5 | 1.50 % |
| AGB-EM-EQ | Atlas Emerging Markets Fund | fund | USD | 6 | 2.00 % |
| EQ-NORTHWIND | Northwind Logistics plc | equity | GBP | 6 | 3.00 % |
| EQ-HELIOS | Helios Renewables AG | equity | EUR | 6 | 1.00 % |
| SN-AUTOCALL-28 | Atlas Autocall Note 2028 | structured, **complex** | USD | 6 | 7.00 % |
| SN-DIGITAL-TRK | Synthetic Digital Asset Tracker | structured, **complex** | USD | 7 | none |

Risk runs from 1 (lowest) to 7.

**Prices.** A security's price on a day is deterministic, so every run sees the same prices.
It starts from the base price on 1 January 2026 and has two parts:
- a straight-line drift (for example 8 % a year for the global equity fund);
- a seasonal swing over 91 days, whose size depends on the security (from 0.05 % for the
  money-market fund to 40 % for the tracker) and whose phase depends on its code.

**Currencies.** A portfolio is in its cash account's currency. Prices are converted to it at
the day's mid rates (see [fx.md](fx.md)), rounded down.

## Suitability

An adviser (`wealth:advise`) records the customer's answers. The customer's KYC must be
verified. The answers are:
- the objective (preservation, income, balanced or growth);
- the horizon in years;
- investment knowledge (none, basic, informed or expert);
- capacity for loss (low, medium or high).

**The risk profile** starts from the objective, then caps apply:

| Rule | Risk profile |
| --- | --- |
| Objective: preservation, income, balanced, growth | 2, 3, 4, 6 |
| Horizon under 3 years | at most 3 |
| Horizon 3–4 years | at most 5 |
| Capacity for loss low, medium | at most 3, 5 |
| No investment knowledge | at most 4 |
| Growth, 10 years or more, high capacity for loss, informed or expert | 7 |

The profile is valid for a year. The latest unexpired assessment is the customer's profile;
without one, nothing can be bought.

## Portfolios

An adviser opens a portfolio (`INV-` followed by eight digits) on one of the customer's open
accounts.
- **The cash account** pays for purchases and fees, and receives sales and income.
- **Custody.** Holdings are units of a security, kept at their average cost. They are off
  the bank's balance sheet: only the cash goes through the ledger.
- **Valuation:** each holding at the day's price in the portfolio's currency, with its gain
  on cost, and the cash account's balance.
- **Closing.** A portfolio can be closed once it holds nothing and no order is waiting.
  While it is open, its cash account cannot be closed.

## Orders

An order (`ORD-` followed by eight digits) buys or sells whole units at the day's price.
- **Amount:** units × price, converted to the portfolio's currency.
- **Fee:** 0.25 % of the amount, at least one major unit, to `WEALTH-FEES-<CCY>` (income).
- **Cash:** a buy must be covered by the account's balance. An arranged overdraft does not
  count, so customers do not borrow to invest.

**Suitability check.** A sell is always suitable, if the units are held. A buy is
unsuitable for each of these reasons:

| Reason | When |
| --- | --- |
| `risk_above_profile` | The security's risk level is above the customer's profile |
| `complex_product` | A complex product, and the customer's knowledge is none or basic |
| `concentration` | After the buy, the security would be more than 40 % of the customer's investable assets (the portfolio's value plus the cash account's balance) |

**What happens next:**
- **Suitable** (API): executed at once.
- **Unsuitable:** the order waits (`awaiting_approval`). Someone other than the adviser
  (`wealth:approve`) either approves it at the client's insistence, which executes it at the
  day's price with the note recorded, or rejects it. This is also a database constraint.
- **Placed:** in stored workflows, a suitable order is placed (`placed`) and released by
  someone on the dealing desk other than the adviser (`wealth:advise`). Stored workflows
  never move money before an approval. A manager approving a placed order also executes it.
- **Release is checked again.** A placed buy is checked against today's holdings, prices
  and profile when it is released; orders placed together can add up to an unsuitable
  position. If it is no longer suitable, release is refused (rule `now_unsuitable`) and the
  order stays placed for a manager to approve or reject. WF-1025 v2 then sends it to the
  manager.

**Settlement:**

| Order | Debit | Credit |
| --- | --- | --- |
| Buy | the customer's account (amount and fee) | the bank's cash account `1000-<CCY>` (amount), `WEALTH-FEES-<CCY>` (fee) |
| Sell | `1000-<CCY>` (amount) | the customer's account (amount less fee), `WEALTH-FEES-<CCY>` (fee) |

Placing an order locks the portfolio, so an order cannot arrive while it is being closed.
Execution locks the portfolio, the cash account and the holding before checking them.
Profiles, portfolios, orders and decisions are audited.

## Income

Custody operations (`wealth:custody`) pay a security's income to every holder.
- **Amount:** half a year's income on one unit at the day's price (rounded down to a minor
  unit), times the units held.
- **Paid into** each open portfolio's cash account, converted to its currency, from the
  bank's cash account.
- **Once per security and record date** (`DIS-` followed by seven digits). This is also a
  database constraint.
- **No income:** a security that pays none (the tracker) is refused.
- **Every holder must be payable.** If a holder's cash account is frozen, the payment is
  refused before anything is recorded (rule `holder_account_not_open`), so it can be paid
  once the account is open again.

## The base processes (workflow factory)

| Workflow | Library handlers it adds | Effect |
| --- | --- | --- |
| WF-1024 Investment Suitability Assessment | `wealth.record_profile`, `wealth.open_portfolio` | writes |
| WF-1025 Investment Order | `wealth.lookup_portfolio`, `wealth.place_order`, `wealth.release_order`, `wealth.approve_order`, `wealth.reject_order` | moves money; execution requires an approval |
| WF-1026 Custody Income Distribution | `wealth.lookup_security`, `wealth.distribute_income` | moves money; payment requires an approval |

- **WF-1024** finds the customer, records the assessment and, if asked, opens a portfolio on
  one of the customer's own accounts.
- **WF-1025** finds the portfolio and places the order. A suitable order goes to the dealing
  desk, which releases or cancels it; an unsuitable one goes to a manager, who approves it at
  the client's insistence or rejects it.
- **WF-1026** finds the security. If it pays income, a second person approves the payment.

`seed-demo` imports all three. Their generated path tests pass with 100 % step and route
coverage (WF-1024: 10 cases, WF-1025: 22, WF-1026: 11). The generated tests add two fixture
kinds:
- `portfolio.portfolio_number`: a portfolio on the fixture account, with a balanced profile
  (risk 4), 20,000.00 more cash and 20 units of the balanced fund;
- `security.code`: AGB-BAL-FUND.

## Simulation workload and AI tool (Phase 44)

The `order_review` workload drives WF-1025 v2 (scenario `order-review`).
- **Cases:** each case is a customer in one of the run's countries with savings, a profile
  assessed 200 days before, a portfolio and, for some kinds, earlier orders. All of it runs
  through the real wealth service. On the day, an unsuitable buy order arrives. Managers
  (simulated department managers with `wealth:approve`) decide every order.
- **Ground truth, go ahead:**
  - one level above an experienced customer's profile, 3–8 % of their cash;
  - 50–75 % of the customer's cash in a risk-2 government bond (concentration only).
- **Ground truth, refuse:**
  - a risk-6 security for a customer with a risk-2 profile;
  - a complex structured note for a customer with basic knowledge;
  - an order spending 92–96 % of the customer's cash;
  - a small step from a customer with 3–5 orders that went ahead against advice in the last
    90 days (and sometimes one refused);
  - a risk-6 security, two levels above the profile, with no experience at that level.
- **Decisions:** in AI-assisted runs the AGB Suitability Review Assistant advises the
  manager, from the profile `wealth.order_profile` reads (the reasons, the risk gap, the
  customer's answers, the order's share of their assets and the cash it leaves, their
  experience, and their orders against advice and refused in the last 90 days).
- **Control check:** four-eyes and authority on each decision, no order executed without
  an approval, and no unsuitable order released by the dealing desk.

What it measured, and the assistant's blind spot, is in [ai-testing.md](ai-testing.md).

## API and permissions

See [api.md](api.md) (*Wealth and investments*). Reading needs `accounts:read`.
- **`wealth:advise`** (tellers and department managers): record profiles, open and close
  portfolios, place orders, and release others' placed orders.
- **`wealth:approve`** (department managers): approve or reject others' unsuitable orders.
- **`wealth:custody`** (department managers): pay income to holders.

## Limitations

- **Securities are synthetic.** Prices follow a deterministic formula; there is no market
  data, no order book, no bid-offer spread and no settlement cycle (orders settle the same
  day).
- **The bank's own market side is not modelled.** Orders settle against the bank's cash
  account in the customer's currency; there is no broker, exchange or custodian, and no FX
  position for the conversion.
- **Whole units only.** No fractional units, limit orders, switches or regular savings plans.
- **Suitability is simplified.** One questionnaire and three checks; no knowledge test per
  product, no cooling-off period and no periodic review.
- **Income is paid on request.** Nothing pays coupons or dividends on a schedule, and there
  is no tax withholding.
- **Simulation scope.** The workload covers unsuitable orders (`order-review`); suitability
  assessments, suitable orders and income are not simulated.
