# ADR 0003: Money in integer minor units, one currency per entry

- **Status:** Accepted
- **Decided in:** Phases 3, 23, 24

## Context
Floating-point amounts accumulate rounding errors, and a bank's books must balance
exactly. The bank works in about 120 countries' currencies. Their minor units differ: zero
decimals for JPY, two for USD, three for KWD.

## Decision
- **Amounts:** every amount is an integer of the currency's minor unit (`BIGINT`). Each
  currency's digits come from the `currencies` table (Phase 23), and conversion helpers are
  in `backend/app/core/money.py`.
- **Journal entries:** an entry is in one currency, and its debits must equal its credits.
- **Cross-currency movements (Phase 24):** they post one balanced entry per currency,
  through FX position accounts.

## Consequences
- **Benefits:**
  - Totals are exact.
  - A trial balance is a plain sum per currency.
- **Costs:**
  - Every interface converts at its edge: the API accepts minor units, and the UI formats
    them with the currency's digits.
  - Rates and percentages that need fractions are stored separately (for example basis
    points), never as money.

## Evidence
- `backend/app/core/money.py`
- `backend/app/modules/fx/`
- `docs/fx.md`
