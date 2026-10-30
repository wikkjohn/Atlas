# Country rules

Phase 25 (roadmap Milestone C, step 3). The rules a country imposes on the bank's
processes are data, not code. Each country has versioned rules, and the account-opening
(WF-0001) and payment (WF-0002) workflows read the version in force in the customer's
country on the day.

Code: `backend/app/modules/rules/`.

## What a country's rules say

| Group | Rule | Used by |
| --- | --- | --- |
| `kyc` | `min_age` (14–25), the accepted `identity_documents` (passport, national ID), whether `proof_of_address` is required | WF-0001 validation; identity verification checks a proof of address only when one is given |
| `screening` | `lists`: which synthetic sanctions lists apply | WF-0001 sanctions screening of the applicant; WF-0002 screening of the payee (in the payer's country) |
| `payments` | `cutoff` (local time), `high_value_major` (from this amount a second person approves), `max_payment_major` (single-payment limit), in whole units of the currency | WF-0002 validation; the payments service records the threshold and value date on each payment and re-checks them at release |

Rules are validated as a whole (`CountryRules`). The payment limit may not be below the
high-value threshold, lists must exist, and documents must not repeat.

## Versions

`country_rules` holds versions per country, and versions are never edited. The version in
force on a day is the latest one whose `effective_from` is on or before that day. A new
version cannot take effect before the latest existing one. Each version records a note
and who added it, and an audit event `country_rules.versioned` lists the changed rules.
Payments created under a version keep the threshold and value date it gave them.

Version 1 of every country comes from `app/modules/rules/defaults.py`, loaded by migration
0022 from a frozen snapshot. How the defaults are set:
- **Minimum age:** 18, or the age of majority as best known (KR 19; AE, BH, KW, EG, CM, CI 21).
- **Identity documents:** the ones the reference data lists.
- **Proof of address:** always required.
- **Sanctions lists:** the global synthetic list plus one regional list. EU members use the
  EU-style list, the UK the UK-style list, the US the US-style list, everyone else the
  UN-style list.
- **Cut-off:** 16:00 local (JP 15:00, SG 15:30, AU 16:30, US 17:00, GB 17:30).
- **Payment amounts:** $10,000 (high value) and $1,000,000 (limit) converted at the FX
  anchor rates and rounded to two figures. The five operating countries keep 10,000 and
  1,000,000 units of their currency, as before Phase 25, so earlier simulations reproduce;
  in Japan that makes the high-value threshold 10,000 yen.

A country added by an operator gets generic rules: age 18, passport only, the global and UN-style lists, and the dollar-equivalent amounts.

## Value dates

A payment's value date is the business day it settles on. If it is instructed before the
cut-off on a business day, that is the same day in the country. Otherwise it is the next
business day under the country's calendar (Phase 23), skipping weekends and holidays. For
example, a UK payment at 18:00 UTC on Christmas Eve 2026 settles on 29 December. The
ledger entry carries the value date as its effective date.

## Sanctions lists

Five synthetic lists of fictional names (`app/modules/compliance/screening.py`): the
original global watchlist, and lists in the style of the EU, UK, US and UN lists. The
`compliance.screen_name` library handler takes an optional `lists` parameter.

## API and UI

See [api.md](api.md) (*Country rules*).
- `GET /countries/{id}/rules?on=` returns the rules in force and every version.
- `POST /countries/{id}/rules` adds a version (`countries:manage`).
- `GET /sanctions-lists` lists the sanctions lists.

On the Countries page, each country's panel shows the rules in force and their versions.
Managers can add a version: age, documents, proof of address, lists, cut-off, amounts,
effective date and a reason. Payments show their value date.

## Limitations

- Rules cover individuals' account opening and payments only. There are no rules yet for
  business customers, lending, or per-product limits.
- There is no daily or monthly cumulative limit, only per payment.
- Screening is an exact match on normalised names, against synthetic lists.
- The defaults are compiled for the simulation, not legal or regulatory advice.
