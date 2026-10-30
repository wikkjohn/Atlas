# Foreign exchange

Phase 24 (roadmap Milestone C, step 2). The bank holds accounts in the currencies of the
countries it operates in. Since this phase, money can move between them:
- a payment to an account in another currency is converted when it is released;
- the bank's open currency positions are valued in US dollars and revalued daily.

Code: `backend/app/modules/fx/`.

## Rates

Every currency of the reference data (93) has a synthetic daily rate in units per US
dollar.
- **Floating currencies** follow their own random walk. It starts from an anchor level on
  1 January 2026 with a daily volatility per currency, from 0.05 % to 1.5 %. The walk is
  seeded by currency and day, so a date always gives the same rate in any process.
- **Pegged currencies** follow their anchor currency at a fixed factor. AED, SAR, QAR,
  BHD, OMR, JOD, BSD and HKD are pegged to the US dollar; XOF, XAF, BAM, DKK and MKD to the
  euro. MOP follows HKD, BND follows SGD, NAD follows ZAR and NPR follows INR.

The anchor levels are rounded approximations chosen for the simulation, not market data.

Rates are published into `fx_rates`, one row per currency and day, either by the daily
job or on first use. Deals and revaluations use the published rate of their day.

## Conversions

`quote(sell, buy, amount, day)` works out a conversion:
- **mid rate:** buy units per sold unit;
- **customer rate:** the mid rate less a 0.50 % margin;
- **bought amount:** rounded down to the bought currency's minor unit (yen have no
  decimals, dinars three);
- **base amount:** the sold amount in US cents.

A conversion never mixes currencies in one journal entry. It posts two balanced entries
through the bank's position accounts `FX-POSITION-<CCY>` (equity, credit-normal):

| Entry | Debit | Credit |
| --- | --- | --- |
| In the sold currency | the customer's account (sold amount) | `FX-POSITION-<sold>` |
| In the bought currency | `FX-POSITION-<bought>` | the customer's account (bought amount) |

The deal (`fx_deals`) records the amounts, both rates, the margin and both entries. It is
idempotent by key: a retried release returns the original deal. Every entry balances in
its own currency, so ledger reconciliation is unchanged.

## Payments

WF-0002 accepts a payee account in any currency. The payment amount stays in the payer's
currency, and the payer's account must be held in it.
- The high-value limit and the other controls apply as before, in the payer's currency.
- When the payment is created, the payee's amount is estimated at that day's rate.
- At release the payments service converts at the release day's rate, and records the
  deal and the amount the payee received. A database constraint makes every released
  cross-currency payment carry its deal.
- The customer's notification gives both amounts.

In the UI:
- the payment form lists payees in every currency and shows a live estimate when the
  currencies differ;
- the Payments list shows what the payee received and the deal number.

## Positions and revaluation

A position account's balance is the bank's open position in that currency, with a credit
balance meaning the bank is long. Valued at the day's rates in US dollars, the positions
add up to the bank's FX result: the margins earned plus any rate moves since.

Revaluation (`fx_revaluations`) compares that value with what earlier runs booked and
posts the difference in US dollars:

| Result | Debit | Credit |
| --- | --- | --- |
| Gain | `FX-REVALUATION-USD` (asset) | `FX-REVALUATION-INCOME-USD` (income) |
| Loss | `FX-REVALUATION-INCOME-USD` | `FX-REVALUATION-USD` |

So after each run the booked value equals the positions' value. Example: a $50,000
payment to a pound account leaves about $250 of margin unbooked; revaluation books it, and
the next day's rate moves are booked by the next run.

The **`fx-daily` schedule** (job `fx.daily`, every 24 hours, as the scheduler's service
account with `fx:manage`) publishes the day's rates and revalues the positions.
Administrators can also revalue from the Foreign Exchange page.

## API

See [api.md](api.md) (*Foreign exchange*). The Foreign Exchange page has four sections:
- the day's rates, with the major currencies first;
- a conversion quote;
- the open positions, with their USD value and the unbooked result, and a *Revalue* button;
- the latest revaluations and conversions.

## Limitations

- One margin (0.50 %) for every pair and amount; there are no bid/ask spreads by size
  and no customer tiers.
- No FX between a customer's own accounts outside payments, and no forwards or swaps.
  Only spot conversions at the day's rate.
- Rates are daily; a payment released late in a day uses that day's rate.
- Positions are valued in US dollars only; there are no per-subsidiary reporting
  currencies yet.
