/** Risk (Phase 47). Amounts are minor units of the named currency unless named `_usd` (whole US dollars). */
/** Percent from basis points: 25 -> "0.25 %". */
export const bps = (value) => `${(value / 100).toFixed(2)} %`;
