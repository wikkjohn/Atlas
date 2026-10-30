# Generated country subsidiaries

Phase 27 (roadmap Milestone C, step 5). Each country the bank enters gets a subsidiary
built from a blueprint, rather than a structure an operator assembles by hand.

The code is in `backend/app/modules/organizations/blueprint.py`.

## The blueprint

Blueprint version 1 (`subsidiary-blueprint/1`) describes a subsidiary with the same shape
the demo seed gives the five operating countries:

| Business division | Department | Teams |
| --- | --- | --- |
| Retail Banking | Customer Onboarding | KYC Review, Account Services |
| Retail Banking | Branch Network | — |
| Compliance & Risk | Financial Crime Compliance | Sanctions Screening |
| Technology & Operations | AI Innovation Lab | Model Evaluation |

That is 12 units: the subsidiary, 3 divisions, 4 departments and 4 teams.

### Staff

Each subsidiary has 24 synthetic staff:
- **Departments:** each has a head (Department Manager role) and a senior analyst.
- **Teams:** each has a lead and three analysts.

Pay works like this:
- **Band:** pay follows a band of US$62,000–240,000, converted at the FX anchor rates and
  rounded to two significant figures. For example, the band is KES 8.0–31 million in Kenya
  and LBP 5.5–21 billion in Lebanon.
- **Heads:** department heads are paid from the upper half of the band.
- **Currency:** pay is recorded in the country's currency.

### Names and headquarters

- **Names:** each country draws its staff names from its own fixed seed (taken from the
  country code and the blueprint version), so they come out the same every time.
- **Subsidiary names** follow the pattern "ATLAS Bank \<country name\>".
- **Regional headquarters:** a regional headquarters is added only for a region that has
  none yet. The demo seed has none for the Middle East & Africa, so launching the first
  country there creates "Middle East & Africa Regional Headquarters".

## Launching a country

Launching a country does three things:
1. It makes a *planned* country *active* and records the audit event `country.launched`.
2. It finds or creates the region's headquarters and the country's subsidiary.
3. It creates, from the blueprint, every division, department and team the subsidiary is
   missing. Staff are hired only for the units this launch creates.

### Rules

- **Repeating a launch** adds nothing new: no extra units, and no extra staff.
- **A partly built subsidiary** is completed. Its existing units are kept, along with
  their names.
- **Marking:** every unit the blueprint creates records `generated_from`. Units built by
  hand or by the demo seed keep a null value.
- **What is refused:**
  - a suspended country;
  - a database with no global bank;
  - a subsidiary or unit that exists but is inactive (reactivate it first).
- **Audit:** the subsidiary gets an `organization.subsidiary_generated` event recording
  how many units and staff were created.

## Running it

### API

`POST /api/v1/organizations/generate` takes `organizations:manage`.
- **Body:** `{country_codes?, region?, staff}`.
- **Default scope:** without `country_codes`, it covers every country that has no
  subsidiary yet, optionally limited to one region.
- **Response:** 202 with the queued job, of kind `organizations.generate`.
- **Transactions:** the job launches each country in its own transaction, so a failure
  stops only that country. Its result lists the countries launched and the ones that failed.

`GET /api/v1/organizations/blueprint` returns the blueprint, plus coverage by region:
countries, subsidiaries, generated subsidiaries, and countries without one.

### UI

On the Organization page, the *Country subsidiaries* panel shows the coverage. Managers
can generate subsidiaries by country code or region, with or without staff, and follow
the job's progress.

### CLI

`python -m app.cli subsidiaries coverage` shows the coverage.
`python -m app.cli subsidiaries generate [--country KE ...] [--region R] [--no-staff]`
launches countries.

### Measured result

Measured on the demo database, the CLI launched all 115 planned countries:
- 1,381 organizations: 115 subsidiaries of 12 units each, plus the new Middle East & Africa headquarters;
- 2,760 staff;
- 31 seconds on one process.

After that run all 120 countries are active with a subsidiary. Running it again found
nothing to do.

### Employee pay limit

The limit on an employee's annual pay was raised from 10¹² to 10¹⁵ minor units. The
Lebanese pound band needs about 2.1 × 10¹² minor units, and the old limit stopped the
first full run partway through.

## Limitations

- There is one blueprint. Every country gets the same structure, whatever its size or
  market.
- Staff names come from the same name list as the rest of the simulation; they are not
  specific to each country.
- Launching makes a country active, but it does not start customers, products or
  simulation workloads there. Making onboarding and payments pass in all 120 countries is
  the Milestone C exit (Phase 28).
- The simulation hires its staff in the first active country by code. After a full
  launch that is the United Arab Emirates (AE) rather than Germany (DE), so simulations run on a fully
  launched database have different staff placements from those on the demo database.
