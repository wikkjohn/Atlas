# Country reference data

Phase 23 (roadmap Milestone C, step 1). The bank's footprint is 120 countries. Five operate
today (US, GB, DE, SG, JP); the other 115 are `planned`. Every one of them carries the
reference data that the later Milestone C steps need. Those steps are multi-currency, the
country rules engine, business calendars and generated subsidiaries.

| Region | Countries |
| --- | --- |
| Americas (22) | US CA MX BR AR CL CO PE UY PY BO EC VE CR PA GT HN SV DO JM TT BS |
| Europe (42) | GB IE DE FR IT ES PT NL BE LU AT CH LI DK SE NO FI IS PL CZ SK HU RO BG GR CY MT SI HR RS BA ME MK AL EE LV LT UA MD MC TR GE |
| Middle East and Africa (28) | AE SA QA KW BH OM JO LB IL EG MA TN DZ NG GH KE TZ UG RW ET ZA NA BW MU SN CI ZM CM |
| Asia Pacific (28) | JP CN HK TW KR SG MY TH ID PH VN IN PK BD LK NP KZ UZ MN KH LA AU NZ FJ PG BN MO MV |

## What each country has

| Field | Content |
| --- | --- |
| Codes | ISO 3166-1 alpha-2 and alpha-3; international calling code |
| Money | Currency (ISO 4217), with its minor units in `currencies`. There are 93 currencies with 0, 2 or 3 decimals (JPY 0, KWD 3, …) |
| Time | IANA time zone; weekend days. Most countries have Saturday–Sunday. 11 have Friday–Saturday (e.g. SA, QA, EG, IL, BD), Brunei has Friday and Sunday, and Nepal has Saturday only |
| Languages | Language tags, the first being the default |
| Regulator | Name and abbreviation of the banking supervisor (e.g. PRA, BaFin, SAMA, MAS) |
| Identity documents | A national identity document (110 countries) and the passport, each with a number mask and an example |
| Address | A line layout (6 styles), postal-code masks (104 countries; 16 use none) with an example, and whether a state or province is part of the address |
| Holidays | 1,167 rules in all: fixed dates, days from Easter (Western, or Orthodox for 12 countries), the n-th weekday of a month, the last weekday before or first after a date, Japan's equinoxes. Also how a holiday on a weekend is observed |
| Notes | What the data leaves out for that country (e.g. lunar holidays, state holidays) |

The data lives in `backend/app/modules/reference/data.py` as Python data with a `VERSION`
(2026.1).

## Masks

Document numbers and postal codes are described by masks: `9` is a digit, `A` an upper-case
letter, `X` either, and any other character stands for itself. `999-99-9999` is a US Social
Security number; `A9 9AA`, `AA9 9AA` and four other masks are UK postcodes. Masks give the
length and character classes, not check digits or allowed letter ranges. That is enough to
reject malformed input and to generate plausible synthetic values deterministically
(`reference/synthetic.py`).

## Calendars

`reference/calendar.py` computes a country's holidays for any year from 1980 to 2099,
together with the observed day off when a weekend moves it:

- `next_weekday`: the next business day, e.g. UK Boxing Day 2026 on a Saturday → Monday 28 December;
- `nearest_weekday`: Saturday → Friday and Sunday → Monday, e.g. US Independence Day 2026 → Friday 3 July;
- `sunday_to_next`: only Sundays move, e.g. Japan.

It also answers whether a date is a business day and which business day comes next. The
2026 calendars give 253 business days in the UK and 259 in Saudi Arabia.

**Not computed:** holidays of lunar calendars (Eid, Lunar New Year, Diwali, Vesak,
Jewish holidays …). Their dates are not rules but published tables, which arrive with the
business calendars of a later Milestone C step. Also not modelled:
- state and provincial holidays (the data lists national ones, or one named state's);
- bridge days and working weekends that make up for holidays.

Each affected country says so in its notes.

## Loading

- **Migration 0020** creates `currencies` and the reference columns. It loads a frozen
  snapshot of the data (`alembic/versions/0020_reference_data.json`), updating the five
  existing countries and adding the 115 others as `planned`.
- **`python -m app.cli reference load`** applies the current data to any database,
  idempotently:
  - adds missing currencies and countries;
  - refreshes the reference fields of existing countries;
  - never touches what operators manage (name, time zone, languages, operational status)
    or an existing country's currency.

  Each change is audited (`reference_data.applied`).
- **`python -m app.cli reference show SA [--year 2026]`** prints a country's reference
  data, holidays and two synthetic samples.

To change the data, bump `VERSION` and add a migration with a new snapshot. A test fails
while the newest snapshot differs from the data.

## Use elsewhere

- `app.core.money` reads minor units from the reference currencies.
- Templates can use `{{country.alpha3}}`, `.timezone`, `.language`, `.calling_code` and
  `.regulator`.
- The Countries page searches by name or code and filters by region and status. Each
  country opens to its reference data, a holiday calendar by year, a checker for document
  numbers and postal codes, and synthetic samples.
- API: see [api.md](api.md) (*Countries*).

## How far to trust it

The data is compiled for the simulation and is not authoritative. Codes, currencies, minor
units, time zones, calling codes and weekends follow the public standards. Regulators and
holidays are recorded as best known, and masks only approximate real formats. Check against
official sources before any real-world use.
