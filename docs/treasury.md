# Treasury and markets

Phase 39 (roadmap Milestone D, step 11). The treasury covers:
- interbank placements and borrowings with synthetic counterparty banks;
- counterparty credit limits;
- the bank's liquidity over the next 30 days, by currency;
- the FX desk: open currency positions against limits, and interbank spot trades to square
  them.

Code: `backend/app/modules/treasury/`.

## Counterparties

Eight synthetic counterparty banks are seeded (`seed-demo`, idempotent). Their names are
invented for the simulation.

| Code | Country | Rating | Placement limit |
| --- | --- | --- | ---: |
| CP-RIDGELINE | US | AA | US$300m |
| CP-NORTHGATE | GB | AA- | US$250m |
| CP-RHEINTAL | DE | A+ | US$200m |
| CP-SAKURAGAWA | JP | A | US$150m |
| CP-MERLION | SG | AA- | US$150m |
| CP-GULFSTAR | AE | A- | US$100m |
| CP-ANDINO | CL | BBB | US$50m |
| CP-SAVANNA | KE | BB+ | US$25m |

**Exposure** to a counterparty is its booked and settled placements, converted at the day's
rates. Executives (`treasury:limits`) can change a limit; changes are audited.

## Money-market deals

A dealer (`treasury:deal`) books a placement (the bank lends) or a borrowing (the bank
takes cash in), value today. The booking is refused unless it meets these rules:

| Rule | Value |
| --- | --- |
| Principal | US$100,000 to 100m, converted to the deal's currency at the anchor rate |
| Tenor | 1 to 365 days |
| Rate | 0 to 50 % a year, fixed |
| Placements | only with an investment-grade counterparty (BBB- or better), within its limit |

**Interest** is simple interest for the tenor, rounded down to a minor unit. It is counted
ACT/365 in GBP, AUD, NZD, SGD, HKD, ZAR, INR, JPY, CAD and MYR, and ACT/360 in the other
currencies.

**Confirmation and settlement.** Back office (`treasury:confirm`), someone other than the
dealer, confirms a booked deal before it matures. This is also a database constraint.
Confirmation settles the deal against the bank's cash account `1000-<CCY>`:

| Deal | Debit | Credit |
| --- | --- | --- |
| Placement | `TREASURY-PLACEMENTS-<CCY>` (asset) | `1000-<CCY>` |
| Borrowing | `1000-<CCY>` | `TREASURY-BORROWINGS-<CCY>` (liability) |

At confirmation, a placement is checked again:
- the counterparty's limit, with the counterparty row locked;
- the cash to pay it;
- that it leaves the currency's liquidity coverage at 100 % or more.

**Maturity.** On or after the maturity date, back office (not the dealer) settles principal
and interest:

| Deal | Debit | Credit |
| --- | --- | --- |
| Placement | `1000-<CCY>` (principal and interest) | `TREASURY-PLACEMENTS-<CCY>`, `TREASURY-INTEREST-INCOME-<CCY>` |
| Borrowing | `TREASURY-BORROWINGS-<CCY>`, `TREASURY-INTEREST-EXPENSE-<CCY>` | `1000-<CCY>` |

A borrowing is repaid only if the cash is there. A booked deal can be cancelled. Bookings,
confirmations, maturities and cancellations are audited.

## Liquidity

For each currency over the next 30 days:
- **liquid:** cash, plus placements (principal and interest) maturing in the window;
- **stressed outflow:** borrowings maturing in the window, plus a 10 % run-off of customer
  deposits (the `2100-` accounts);
- **coverage:** liquid ÷ stressed outflow. Below 100 % is flagged.

A currency with no stressed outflow has no coverage figure.

## FX desk

The desk reads the open positions Phase 24 keeps in `FX-POSITION-<CCY>` (see
[fx.md](fx.md)), valued in US dollars, against a **net open position limit** per currency.
The default limit is US$1m; executives (`treasury:limits`) can set another. A position
whose absolute value is above its limit is flagged with the excess.

**Squaring a position.** A dealer books an interbank spot trade with a counterparty at the
day's mid rate (no margin), selling a currency the desk is long in. A trade may only reduce
a long position, never open or reverse one. Back office (not the dealer) confirms it, which
settles one balanced entry per currency:

| Leg | Debit | Credit |
| --- | --- | --- |
| Sold | `FX-POSITION-<sold>` | `1000-<sold>` |
| Bought | `1000-<bought>` | `FX-POSITION-<bought>` |

## The base processes (workflow factory)

| Workflow | Library handlers it adds | Effect |
| --- | --- | --- |
| WF-1018 Interbank Money-Market Deal | `treasury.book_deal`, `treasury.confirm_deal`, `treasury.cancel_deal` | moves money; settlement requires an approval |
| WF-1019 Money-Market Deal Maturity | `treasury.lookup_deal`, `treasury.mature_deal` | moves money; maturity requires an approval |
| WF-1020 FX Position Square-off | `treasury.fx_position`, `treasury.book_fx_trade`, `treasury.confirm_fx_trade`, `treasury.cancel_fx_trade` | moves money; settlement requires an approval |

- **WF-1018** books the deal and has back office confirm and settle it. If back office does
  not confirm, or settlement is refused, the deal is cancelled.
- **WF-1019** finds the deal. If it is due, back office settles principal and interest.
- **WF-1020** reads the position. Over the limit, it books a spot trade that back office
  confirms or cancels.

`seed-demo` imports all three. Their generated path tests pass with 100 % step and route
coverage (WF-1018: 13 cases, WF-1019: 11, WF-1020: 16). The generated tests provide three
new fixture kinds:
- `counterparty.code`: CP-NORTHGATE, with GBP cash for a placement;
- `treasury_deal.deal_number`: a settled GBP placement maturing today;
- `fx_long.currency`: EUR, with a long position of EUR 3m (above the US$1m default limit).

## Simulation workload and AI tool (Phase 40)

The `deal_confirmations` workload drives WF-1018 v2 (scenario `deal-confirmations`).
- **Cases:** each case books a placement or borrowing in USD, EUR or GBP of US$1–20m.
  - Each case has its own synthetic counterparty, with the rating and limit the case needs.
  - Each placement is funded by a business deposit in its currency.
  - Back office (simulated department managers with `treasury:confirm`) decides every
    deal.
- **Ground truth, confirm:**
  - a placement or borrowing within 0.40 points of the reference rate, 7–90 days, with a
    counterparty rated A or better; a placement uses 20–60 % of the limit.
- **Ground truth, cancel:**
  - lending 1.60–3.00 points below the reference rate;
  - a placement of 181–365 days with a counterparty rated BBB or BBB-;
  - a duplicate of a deal confirmed earlier the same day;
  - a placement of 91–150 days that takes a counterparty to 90–97 % of its limit.
- **Decisions:** in AI-assisted runs the AGB Back-Office Check Assistant advises back
  office, from the profile `treasury.deal_profile` reads. The synthetic reference rates are
  USD 5.25 %, EUR 3.75 %, GBP 5.00 % and so on; the default is 4.00 %.
- **Control check:** four-eyes and authority on each decision, and no settlement without a
  confirmation.

What it measured, and the assistant's blind spot, is in [ai-testing.md](ai-testing.md).

## API and permissions

See [api.md](api.md) (*Treasury*). Reading needs `payments:read`.
- **`treasury:deal`** (tellers and department managers): book and cancel deals and spot
  trades.
- **`treasury:confirm`** (department managers): confirm and settle others' deals and trades,
  and settle maturities.
- **`treasury:limits`** (regional and global executives): counterparty and position limits.

## Limitations

- **Settlement:** deals settle against the bank's cash account. There are no nostro
  accounts, settlement messages or correspondent banks, and counterparties never fail to
  pay.
- **Deals:** value today only. No forward-starting deals, rollovers, early termination,
  floating rates or repos.
- **Liquidity:** the measure is simplified. A single 10 % run-off rate replaces regulatory
  outflow categories, and there is no buffer of securities.
- **FX desk:** spot only, at the mid rate; no forwards, swaps or settlement risk on
  counterparty limits. Positions are valued in US dollars, so the US-dollar position itself
  has no limit.
- **Automation:** nothing matures deals automatically.
- **Simulation:** the workload covers deal confirmations (`deal-confirmations`); maturities
  and the FX desk are not simulated.
