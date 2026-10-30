# Country sweep: the Milestone C exit

Phase 28 (roadmap Milestone C, step 6). The exit criterion was that onboarding and payment
variants pass in all 120 countries. Here that means two scenarios, run once in every
country, with nothing failing.

Code: `backend/app/simulation/sweep.py`, plus the rule-following generators in
`generators.py` and `workloads.py`.

## Why the generators had to change

Before Phase 28, simulated cases ignored the country they were created for:
- **Onboarding:** applicants were 19–80 years old (underage ones 14–17), held a passport or
  a national ID at random, and always handed in a proof of address. Sanctioned names came
  from the global list.
- **Payments:** amounts used fixed figures. A high-value payment was 10,000–40,000 units
  and an ordinary balance 2,000–10,000 units, whatever the currency.

Since Phase 25, the workflows apply each country's own rules. Once all 120 countries are
active, those rules turn many of these cases into wrong ground truth:
- A 19-year-old applying in Kuwait is underage there (the minimum is 21).
- A national ID is not accepted in a country that takes passports only.
- 40,000 Indonesian rupiah is far below Indonesia's high-value threshold.

## Cases that follow their country's rules

A scenario with `country_rules: true` makes its cases follow the rules of their customer's
country. The run looks up the rules in force on the simulated day and stores them in its
dataset as `config.dataset.rules`, so the run keeps the rules it was generated against.

### Onboarding cases

- **Ages:** applicants are older than the country's minimum age. Underage applicants are
  up to three years below it.
- **Identity documents:** each applicant holds an identity document the country accepts.
- **Missing documents:** a proof of address is required only where the country requires
  one. Elsewhere, for the "missing documents" and "abandoned documents" cases, the identity
  document is the one that arrives late or never.
- **Sanctions hits:** sanctioned names come from the lists that country screens against.

### Payment cases

- **Ordinary payments:** balances stay below the country's high-value threshold.
- **High-value payments:** amounts fall between the threshold and the lower of four times
  the threshold and the country's payment limit.
- **Watchlisted payees:** payee names come from the payer's country's lists.

### Existing scenarios

Existing scenarios are unchanged. The field is left out of their configuration, their
hashes are the same, and their generators draw the same cases.

## The scenarios and the sweep

| Scenario | Workflow | What it checks |
| --- | --- | --- |
| `global-onboarding` v1 | WF-0001 v1 | the eight application kinds, under the applicant's country's KYC and screening rules |
| `global-payments` v1 | WF-0002 v1 | seven payment kinds, on the payer's country's scale and lists |

In both scenarios, reviewers always decide correctly (accuracy 1.0). An outcome that
differs from the ground truth is therefore a fault in the workflow or in the rules, not a
simulated person's mistake. The "quiet scam" kind is left out because, by design, no rule
catches it; it is what the AI screener experiments are for.

### Running one country

A run can be limited to one or more active countries. In the API this is `country` when
starting a simulation, and in the UI it is the *Country* field of the Simulation Center's
start form. Internally, `create_run` takes `countries`.

When a run is limited this way:
- its customers come only from those countries;
- its staff are hired in the first country's own subsidiary, which Phase 27 generates for
  every country;
- "Run again" keeps the same countries.

### Running the sweep

`python -m app.cli country-sweep [--country XX ...] [--cases 20] [--seed 2028]
[--output report.json]` runs each scenario once in each active country.

**Seeds.** Each run uses its own seed. The search starts from the base seed plus a number
derived from the country code, and takes the first seed whose cases include every kind of
the scenario's mix. A case's kind is the first draw of its own random stream, so
`case_kinds` predicts the kinds without running anything. Without this, every country
drew the same kinds, and rare ones could be missed altogether.

**What a run must do to pass:**
- every case completes;
- every outcome matches its ground truth;
- every kind of the mix occurs;
- every case takes the steps its kind requires. A high-value payment must pass through
  the second person's approval; routine, new-payee and large-share payments must not. An
  outcome alone cannot show this: a high-value payment is approved either way.
- the workload's control check finds no violation: four-eyes, the decider's authority,
  compliance review of high-risk customers, and approval before money moves.

The command prints each run and exits with a non-zero status if any run fails. The JSON
report lists the failures and counts how often each case kind occurred, per scenario and
across countries.

### Does the sweep detect cases that ignore country rules?

A sweep that the old, country-blind cases would also pass would prove nothing. So the same
scenarios were run with `country_rules` switched off, 30 cases per run, on the fully
launched database:

| Country | Rule that matters | Country-blind cases |
| --- | --- | --- |
| Austria, Lebanon | passports only | onboarding fails: 7 of 30 outcomes wrong (applicants with national IDs never complete their documents) |
| Indonesia, Vietnam | high-value thresholds of millions of units | payments fail: 4 high-value payments each skip the second approval |
| Korea | high-value threshold of about 14 million won | payments fail: 1 high-value payment skips it |
| Kuwait | a threshold of about 3,000 dinars | payments fail: a large-share payment needs the second approval |
| Kuwait, Korea | minimum age 21 and 19 | onboarding passes at this size (few applicants fall between 18 and the minimum) |
| United Kingdom, Japan | the original operating countries | pass, as before |

With cases that follow the rules, every one of these passes.

Two problems were found and fixed before the result below:
- **The first full sweep's coverage.** It passed all 240 runs, but every country drew the
  same kinds, which left out sanctions hits and scams. Seeds now cover every kind.
- **The first control run.** The country-blind cases also passed, because only outcomes
  were checked. The sweep now checks paths too.

## Result

**240 of 240 runs passed in 120 countries** (7,200 cases): 30 cases per run, seed 2028,
on the database where every country is launched with its generated subsidiary (Phase 27).
Every case kind occurred in every country:

| Scenario | Kinds (cases across the 120 countries) |
| --- | --- |
| `global-onboarding` | clean 2,222 · politically exposed 228 · missing documents 221 · name mismatch 215 · sanctions hit 205 · forged document 181 · underage 166 · abandoned documents 162 |
| `global-payments` | routine 1,543 · new payee 524 · high value 502 · scam 304 · large share 267 · insufficient funds 230 · watchlisted payee 230 |

It took 31 min 43 s (1,900 s of runs, 6 to 9 s each) on one process in the development
container. The machine was not otherwise loaded during this sweep. The first, superseded
sweep took 27 min, partly while other test suites were running.

## Limitations

- The sweep runs one country at a time in one process.
- Reviewers never err in the sweep scenarios. How accurate people are is studied with the
  other scenarios, not here.
- Identity document numbers use the simulation's own format, not each country's mask.
  WF-0001 does not check numbers against the masks.
- The sweep covers the rules in force on the simulated day. A later rules version applies
  only to runs made after it.
