# Benchmarking and experiment evaluation

> **Everything here is a simulation estimate on synthetic data.** The evaluation engine
> compares recorded simulation runs under stated assumptions. It never presents its
> figures as verified enterprise savings, and every screen and report says so.

## Experiment model

An experiment (`experiments`) compares one **baseline** run with one **candidate** run of
the same workload: `experiment_id` (+ `experiment_number`), `name`, `scenario_id`,
`scenario_version`, `baseline_run_id`, `candidate_run_id`, `candidate_mode`, `tool_id`,
`tool_version`, `configuration` (the resolved cost assumptions and success thresholds,
with its hash), `status` (running, completed, failed), `failure_reason`, `created_at`,
`completed_at`.

Two ways to create one:

- **Run it:** `POST /api/v1/experiments` starts the baseline and the candidate as a suite
  (same scenario, seed, applications and staff; executed one after the other) and
  evaluates when both finish. A failed run fails the experiment with its reason.
- **From existing runs:** `POST /api/v1/experiments/from-runs` evaluates two completed
  runs, for example to re-price them under other assumptions. The runs must be a
  baseline and an AI-mode run of an **equivalent workload** (same scenario and workflow
  version, seed, sizes, dataset, scenario configuration and software version, and
  identical generated applications); otherwise the request is refused with the
  differences.

## Raw measurements vs. derived results

Stored separately, so the derivation can be audited and repeated:

| Stored in | What | Source |
| --- | --- | --- |
| `experiment_measurements` (raw, one row per run) | cases, completions, outcomes vs. ground truth, manual reviews, review and wait seconds, escalations (compliance reviews, fraud reviews or credit committee, by workload), automated approvals, overdue tasks, document timeouts, failed executions, AI invocations by status, cycle-time statistics, banking decisions checked and policy violations, workload fingerprint | the run's recorded case results, workflow executions and history, AI invocations, and the banking decisions its cases made: account requests (onboarding), released payments (four-eyes, high-value authority) or booked loans (underwriting authority, committee), re-checked by the scenario's workload |
| `experiment_evaluations` (derived) | costs, metric comparisons, criteria, verdict, conclusion, limitations, evaluation digest | a pure function of the two raw measurement sets and the configuration |

**Policy violations** are found by re-checking every account decision the run's cases
made against the authorization rules: four-eyes, decider without approval authority,
limited (policy-engine) approver beyond low risk, high-risk approval without compliance
authority. Blocked AI actions are reported alongside as evidence that the controls
worked. (Self-approval cannot even be stored: the database enforces four-eyes.)

## Cost model

Transparent, configurable assumptions stored with every experiment (defaults are
illustrative):

| Assumption | Default | Applied to |
| --- | ---: | --- |
| Reviewer cost per minute | 0.85 | recorded review minutes, and oversight minutes |
| AI cost per invocation | 0.04 | executed tool calls that did not measure their own cost (including failed ones; blocked calls never ran). A hosted model's calls (Phase 76) count at the cost they recorded |
| Infrastructure per workload / per case | 20.00 / 0.02 | each run / each case |
| Workflow exception handling | 12.00 | document timeouts, overdue tasks, failed executions, AI errors |
| Manual escalation | 6.00 | cases escalated to compliance review |
| Oversight of automation | 10 % × 6 min | automated decisions re-checked by a person |
| Risk cost of a false approval / rejection | 750 / 60 | reported as risk exposure, **not** in operating cost |

Operating cost = review labour + oversight + AI execution + infrastructure + exceptions +
escalations; cost per completed case = operating cost ÷ completed cases.

## Compared metrics

Workflow processing time (average and p95 cycle), simulated labour time (review +
oversight), manual reviews, cost per completed case, successful completion rate,
decision accuracy, false approval rate (of should-reject cases), false rejection rate
(of should-approve cases), escalation rate, policy violation rate, error count (failed
executions + AI errors), AI execution cost (informational), overall operating cost.
Each comparison records baseline, candidate, delta, relative change, whether it
improved and whether it **regressed** (worse by more than the regression tolerance;
any worsening from a zero baseline counts).

## Success criteria

A candidate is **successful** only if every criterion holds:

| Criterion | Rule (medium-tier threshold; see the scenario thresholds below) |
| --- | --- |
| Equivalent workloads | identical workload and applications; the baseline is a baseline-mode run |
| Measurable improvement | ≥ 5 % better on processing time, labour time or cost per case |
| Correctness acceptable | accuracy no more than 0.5 points below the baseline; completion rate not lower |
| Compliance thresholds | false approvals ≤ 5 %, false rejections ≤ 5 %, errors ≤ 5 % of cases |
| Authorization controls effective | no policy violations (in either run) |
| Costs complete | AI execution, oversight of automated decisions and human review all have a cost |

The conclusion names the changes, every regression and every failed criterion, and ends
with a recommendation (a controlled pilot with real-world validation, or do not
proceed) that restates that the figures are simulated estimates.

## Scenario-specific thresholds (Phase 80)

The defaults above were one standard for every scenario: a 5 % false-approval rate judged
a fraud screen and a leave request alike. Since Phase 80 (`app/modules/experiments/
thresholds.py`) each scenario is judged by thresholds that fit its risk.

**Risk tiers.** Every scenario with AI modes has a tier and a stated reason (an outage
variant has its base scenario's). The tiers' built-in thresholds (illustrative, not any
real bank's risk appetite):

| Tier | Scenarios | False approvals ≤ | False rejections ≤ | Accuracy drop ≤ | Errors ≤ |
| --- | --- | --- | --- | --- | --- |
| Critical: financial crime, fraud, sanctions | retail onboarding (KYC), domestic payments, card fraud alerts, AML alert triage | 1 % | 10 % | 0 | 2 % |
| High: credit, market, conduct, reporting | personal loans, mortgages, covenant breaches, rating overrides, journal review, order review, discrepant presentations | 3 % | 8 % | 0.5 pt | 3 % |
| Medium: costly but correctable (the former defaults) | overdrafts, payment plans, complaint redress, deal confirmations, recall triage, invoice payments, change approvals | 5 % | 5 % | 0.5 pt | 5 % |
| Low: internal, reversible | leave requests | 10 % | 10 % | 2 pt | 5 % |

The minimum improvement (5 %) and the other criteria are the same in every tier. A tier
tolerates more false rejections where it tolerates fewer false approvals: friction is the
price of a stricter control.

**Approved versions.** A scenario may have stored thresholds of its own
(`scenario_thresholds`): one person proposes a version (`experiments:run`) with a tier and
a rationale; a risk approver (`risk:approve`), who must be someone else, approves or
rejects it (a rejection needs a reason). Approving supersedes the previous version; at most
one is active per scenario; every step is in the audit log.

**Resolution.** An experiment, series or portfolio cell that does not give thresholds is
judged by its scenario's: the approved version, else the tier's defaults. Thresholds given
in a request still win. The resolved values are stored with the experiment, together with
`thresholds_source` (`scenario` with its version, `tier_default`, or `request`), so a
later change to the scenario's thresholds never changes a stored verdict; the report says
which applied.

**Re-judging stored results.** `GET /api/v1/experiments/{id}/under-scenario-thresholds`
and `GET /api/v1/experiment-portfolios/{id}/under-scenario-thresholds` re-evaluate from the
stored raw measurements under the thresholds in force now, recompute the series and
portfolio statistics, and store nothing.

**Measured: the Phase 78 portfolio re-judged** (19 workflows × GB, US, JP × 3 seeds, the
review assistants, AI-assisted; recomputed in 5.9 s):

| Tier | Cells | Successful (one standard) | Successful (scenario thresholds) |
| --- | --- | --- | --- |
| Critical | 12 | 6 | 3 |
| High | 21 | 3 | 3 |
| Medium | 21 | 0 | 0 |
| Low | 3 | 0 | 0 |
| **All** | **57** | **9** | **6** |

Card fraud alerts lost its three cells (false approvals 3.3 % on average, above the
critical 1 %); nothing else changed. Every failure, in every tier, is on the compliance
criterion. Two findings:

- **The baseline would fail too.** In 17 of the 19 workloads the simulated human
  reviewers approve 8–31 % of the cases that should be rejected (leave requests 20 %,
  invoice payments 31 %; KYC and personal loans 0 %); the assistants cut that to 0–16 %. An absolute limit asks the tool to meet a standard the
  people it supports do not; whether "better than today's reviewers" should be enough is
  a policy decision, not a statistical one, and the thresholds do not make it.
- **Small runs make the rates coarse.** With 40 cases a run, a workload has about nine
  cases that should be rejected, so one wrong approval moves the rate by 11 points. Leave
  requests averages 8.2 % false approvals, inside the low tier's 10 %, yet two of its three
  seeds land at 11.1 % and 13.6 %, and a cell needs every seed to pass.

## Tool comparison across all benchmarks (Phase 81)

The leaderboard (*All experiments by tool* on the Benchmarking page) summarises each
tool's experiments against their own baselines, whatever their workloads: it describes a
tool, it does not compare two. `app/modules/experiments/comparison.py` compares them.

- **Benchmarks.** A benchmark is a scenario version and a candidate mode. Every completed
  experiment of a tool belongs to one.
- **Matched workloads.** Two tools are compared only on workloads they share: experiments
  whose workload is identical (scenario version, seed, sizes, dataset, scenario
  configuration such as the country, software version), whose baselines processed the
  same cases (the case fingerprint) and that assumed the same costs. Then the tool is the
  only difference. The latest experiment of a tool on a workload stands for it. Two
  versions of one tool are two tools.
- **Head-to-head.** For each pair and each metric with a direction, the differences of
  the candidates' values across the matched workloads get a paired t-test (95 %
  interval), with Holm's adjustment across metrics. The pair's outcome: a tool is
  **preferred** when it is significantly better on at least one metric and worse on none;
  a **trade-off** when each is better on something; **identical** when every value on
  every workload matched; otherwise **no significant difference**, or **too few matched
  workloads** (under 2).
- **Ranking.** Per benchmark, by the share of experiments successful under the scenario's
  thresholds in force now (Phase 80; tools evaluated at different times meet the same
  standard), then by head-to-heads won and lost. Tools nothing separates share a rank:
  averages over unmatched workloads never decide.
- **Scoreboard.** Per tool across benchmarks: benchmarks, times ranked first, successful
  experiments, and its head-to-heads preferred, beaten, trade-off, no difference and
  identical.
- **Running one.** `POST /api/v1/tool-comparison/runs` (or *Compare tools* on the
  Benchmarking page) starts one repeated-seed series per tool (2 to 5 tools, two versions
  of one tool allowed) on the same scenario, seeds, sizes and costs, in one background
  job, so every pair is matched on every seed. Any series that happen to share workloads
  are compared too.

Everything is derived on request (`GET /api/v1/tool-comparison?scenario_id=&tool=`);
nothing is stored. Comparing every benchmark on the development database takes 0.3 s.

**Measured** on the development database: the KYC assistant 1.0.0; a tuned 1.1.0
(escalates expected deposits above 20,000 instead of 50,000 and treats one edit, not two,
as a typo in a name); and the KYC fault injector (a test double that fails, times out or
answers out of schema on 20 % of calls) — retail onboarding v2, AI-assisted, 40 cases and
20 staff, seeds 81–85: 30 runs in 321 s.

| Rank | Tool | Successful (critical thresholds) | Head-to-heads |
| --- | --- | --- | --- |
| 1 | KYC assistant 1.0.0 | 19 of 19 (its 14 earlier experiments included) | preferred over the fault injector; identical to 1.1.0 |
| 1 | KYC assistant 1.1.0 | 5 of 5 | preferred over the fault injector; identical to 1.0.0 |
| 3 | KYC fault injector | 0 of 5 | beaten by both |

- **The tuning changed nothing.** 1.0.0 and 1.1.0 gave the same value on every metric on
  all five seeds, and the same recommendations (169 approve, 8 escalate, 15 reject of 192
  calls each): no application's expected deposits fell between 20,000 and 50,000 (the
  highest was 120,000, above both limits), and the stricter name rule changed no
  recommendation. A
  version that the benchmarks cannot tell apart is not evidence of an improvement; it
  needs cases that reach the changed rule.
- **Against the fault injector** (both versions alike): cost per completed case 29.3 %
  lower, labour 12.4 % lower (0.47 to 1.23 hours a run less), errors 0 against 9.2 a run;
  Holm-adjusted p 0.026 to 0.033. Accuracy, false approvals and false rejections were the
  same: in the assisted mode people still decide, so the injected failures cost time and
  money, not correctness.
- **The old leaderboard would have ranked them by unmatched averages:** 1.0.0's mean
  labour change (−35.1 %) mixes 19 experiments of different sizes and seeds with 1.1.0's
  five (−37.0 %), which is why ranks no longer use it.

## Reproducibility

The evaluation is deterministic: `evaluation_digest` is a hash of the derived results.
`POST /api/v1/experiments/{id}/re-evaluate` recomputes from the stored raw measurements
and reports whether the digest matches. Two experiments with the same scenario, seed,
workload, tool, configuration and software produce identical measurement and evaluation
digests (tested). `scripts/validate_system.py --login auditor` re-evaluates every
evaluated experiment of a running stack.

## Repeated seeds: confidence intervals and significance (Phase 77)

One experiment is one draw: one seed's cases, reviewers and decisions. A **series**
(`POST /api/v1/experiment-series`, or *New series* on the Experiments page) runs the same
experiment once per seed (`seed`, `seed + 1`, … for `replicates` seeds, or an explicit
`seeds` list; 2 to 30) and tests the effect across them.

- **Each replicate is an ordinary experiment**, measured and evaluated as before, with its
  own verdict; the series links them (`experiments.series_id`).
- **Per metric**, the series takes the paired difference (candidate minus baseline) on
  every seed and reports the mean difference, its **confidence interval** (Student's t,
  n − 1 degrees of freedom; 95 % by default, 90 % or 99 % on request), the change relative
  to the baseline mean, and a two-sided **paired t-test**.
- **Many metrics are tested at once**, so p-values are adjusted with **Holm's method**
  across the tested metrics; a difference is *better* or *worse* only when its adjusted
  p-value is below 1 − confidence. The intervals are per metric and not adjusted, so an
  interval that excludes zero can still be "no significant difference" — the table shows
  both.
- **The series verdict** is successful when every replicate met every success criterion
  and no metric is significantly worse.
- **Recomputable:** the statistics are derived from the replicates' stored evaluations.
  A failed replicate fails the series; no statistics are computed over the seeds that
  happened to succeed.
- The statistics use the standard library only (an incomplete-beta implementation of the
  t distribution, checked against published t tables in the tests).

Measured on the development database: the KYC assistant on retail onboarding, 200
applications and 20 staff per run, seeds 101–105, 95 % intervals:

| Metric | AI-assisted (5 seeds, 285 s) | AI-automated (5 seeds, 244 s) |
| --- | --- | --- |
| Labour time | −34.4 % (−35.7 % to −33.1 %), p < 0.001 | −70.4 % (−73.2 % to −67.6 %), p < 0.001 |
| Cost per completed case | −31.0 % (−32.2 % to −29.8 %), p < 0.001 | −63.7 % (−66.2 % to −61.1 %), p < 0.001 |
| Processing time | −2.3 % (−2.5 % to −2.2 %), p < 0.001 | −4.9 % (−5.1 % to −4.7 %), p < 0.001 |
| Accuracy | +2.6 % (+0.7 % to +4.6 %), adjusted p = 0.163: not significant | +3.8 % (+2.6 % to +4.9 %), adjusted p = 0.007 |
| Manual reviews | unchanged on every seed | −84.7 % (−87.5 % to −81.9 %), p < 0.001 |
| Series verdict | successful (5 of 5 replicates) | successful (5 of 5 replicates) |

The seeds vary the generated cases and the simulated reviewers. What the intervals measure
is how much the tool's effect varies with the workload; they say nothing about whether the
simulation's own assumptions (review times, reviewer accuracy, how people use AI advice)
are right.

## Portfolios: a tool family across workflows, departments and countries (Phase 78)

A **tool family** is a product line of tools evaluated together (`ai_tools.family`); the
19 AGB rule-based review assistants form `agb-review-assistants` (migration 0052
backfills it, the seed sets it). A **portfolio** (`POST /api/v1/experiment-portfolios`, or
*New portfolio* on the Experiments page) evaluates the family wherever it applies:

- **Cells.** Every scenario with AI modes that one of the family's active tools serves,
  in each chosen country (1 to 150), is a cell; each cell is a repeated-seed series. The
  plan (`GET /api/v1/experiment-portfolios/plan?family=`) lists the cells and the
  scenarios left out, with why: no tool of the family serves the workflow, no automated
  decision path (for the automated mode), or an outage scenario. At most 600 experiments
  (cells × seeds).
- **Countries.** Each cell's runs draw their customers from the one country, with staff
  from its subsidiary and its country rules (Phase 28); `country` is now on suites,
  experiments and series too.
- **The workflow is the unit.** A workflow's cells (one per country) share the tool, the
  rules and the seeds, so they are not independent evidence: each workflow contributes
  the mean relative change of its cells, and the statistics run across workflows — the
  mean change per workflow with a t-interval, a one-sample t-test against zero
  (Holm-adjusted across metrics) and the median. Per cell, how many were significantly
  better, worse or neither by their own series is counted, and how many workflows'
  effect the country changed at all. (The first design pooled cells; the measurement
  below showed identical cells across countries, which would have counted one workflow
  three times.)
- **Breakdowns** give the mean change per cell by department (the workflow's catalogue
  department or its definition's business owner) and by country.
- **The verdict** is successful when every cell succeeded on every seed; cells with a
  significantly worse metric are named in the conclusion.

Measured on the development database: the 19 AGB rule-based review assistants
(`agb-review-assistants`), AI-assisted, on every scenario they serve in GB, US and JP,
3 seeds per cell, 40 cases and 20 staff per run — 57 cells, 171 experiments, 342 runs, in
2,293 s (38 min):

| Across 19 workflows (18 departments) | Mean change per workflow (95 % interval) | Adjusted p | Cells better / worse / neither |
| --- | --- | --- | --- |
| Labour time | −36.1 % (−36.9 % to −35.3 %) | < 0.001 | 30 / 0 / 27 |
| Cost per completed case | −34.0 % (−35.4 % to −32.6 %) | < 0.001 | 30 / 0 / 27 |
| Processing time | −34.4 % (−38.3 % to −30.5 %) | < 0.001 | 30 / 0 / 27 |
| Accuracy | +12.0 % (+9.0 % to +15.1 %) | < 0.001 | 3 / 0 / 54 |
| False approval rate (17 workflows with should-reject cases) | −45.2 % (−58.9 % to −31.6 %) | < 0.001 | 3 / 0 / 48 |
| Manual reviews | +0.1 % (−0.1 % to +0.3 %) | 0.99 | 0 / 0 / 57 |

- **Every department gained:** labour fell between 33.6 % (Trade Finance) and 40.0 %
  (Retail Banking).
- **The country made no difference:** in all 19 workflows the three countries gave the
  same decisions for the same seed (the workloads' cases and decisions do not depend on
  the customer's country), so each workflow's three cells are identical.
- **Verdict not successful:** 9 of 57 cells met every criterion on every seed. Every
  failure was the same criterion — the candidate's false approval rate above the absolute
  5 % threshold (114 of 171 replicate evaluations), the documented blind spot of each
  assistant, and coarse with 40 cases (a handful of should-reject cases per run). On
  average the assistants still cut false approvals by 45 % against the baseline.
- With 40 cases a run, 27 of 57 cells were not significant on their own over 3 seeds; the
  family's effect is clear only across workflows.

## Milestone G exit: one tool across 120 country workflows (Phase 83)

**One tool, many workflows.** A tool can be declared compatible with a workflow template as
well as with workflows (`compatible_workflows` may name `TPL-…` ids). It then serves every
variant generated from that template.

**Each country runs its own workflow.** A scenario can name a `workflow_template`. Each of
its runs then executes the variant generated for the run's single country, and records the
variant in `config.workflow_variant`. A run for a country without a variant is refused.

**The exit setup:**
- `TPL-OVERDRAFT-REQUEST` is WF-1003 v2 as a template, with parameters `country_code` and
  the credit decision's deadline. `python -m app.cli country-variants` generates one variant
  per active country.
- The overdraft affordability assistant 1.1.0 is declared for the template.
- The scenario `retail-overdrafts-country` runs the variants.
- A portfolio takes up to 150 countries and an optional `scenario_ids` filter. In it, each
  cell of a templated scenario counts as its variant's own workflow.

**Measured** on a dedicated database (`atlas_exit`: demo seed, all 120 countries launched,
120 variants WF-3000 to WF-3119):
- The assistant was run AI-assisted in every country's workflow.
- 3 seeds (83–85), 40 cases and 20 staff per run: 120 cells, 360 experiments, 720 runs, in
  6,385 s (106 min).

| Across 120 workflows (120 countries, 1 department) | Baseline → assisted | Mean change per workflow (95 % interval) | Adjusted p | Cells better / worse / neither |
| --- | --- | --- | --- | --- |
| Labour time | 10.83 h → 6.50 h a run | −40.0 % (−40.0 % to −40.0 %) | < 0.001 | 120 / 0 / 0 |
| Cost per completed case | | −38.3 % (−38.3 % to −38.3 %) | < 0.001 | 120 / 0 / 0 |
| Processing time | | −40.0 % (−40.0 % to −40.0 %) | < 0.001 | 120 / 0 / 0 |
| Accuracy | 91.7 % → 94.2 % | +2.7 % (+2.7 % to +2.7 %) | < 0.001 | 0 / 0 / 120 |
| False rejection rate | 9.4 % → 1.5 % | −84.0 % | < 0.001 | 0 / 0 / 120 |
| False approval rate | 6.1 % → 12.2 % | +100 % | < 0.001 | 0 / 0 / 120 |

- **The tool works in every country's workflow.** Every call went to the assistant at
  1.1.0, and every cell was significantly faster and cheaper by its own series.
- **It doubles false approvals.** This is its documented blind spot: it approves customers
  who are overdrawn most days. It does remove most false rejections.
- **Verdict not successful: 0 of 120 cells met every criterion on every seed.**
  - The compliance thresholds failed in 240 of 360 replicate evaluations.
  - Correctness failed in 120 of 360.
- **Read the interval with care.** For each seed, all 120 workflows gave exactly the same
  results, so the 95 % interval has zero width.
  - The variants differ only in name, owner, catalogue and decision deadline. The
    workload's cases do not depend on the country, and no case reaches the deadline.
  - So the 120 workflows are not 120 independent pieces of evidence: the evidence is 3
    seeds of one process.
  - The exit shows that the platform evaluates one tool across 120 workflows, each run as
    its own workflow, with intervals and adjusted significance. It does not show that the
    effect generalises across countries.
- **Input limits.** The first full run failed for Colombia. The template's `limit` cap,
  copied from WF-1003 (10^9 minor units), was below twice the largest overdraft in 17
  currencies (LBP, LAK, IDR, UZS, KHR, COP and others). The template now allows 10^13, and
  the run was repeated on template version 2.

## Reports

`GET /api/v1/experiments/{id}/report` downloads a Markdown proof-of-concept report
(`?format=json` for the full data): tested tool, scenario, workload, seed, software and
tool versions, baseline and AI performance, operational differences, financial
assumptions and cost lines, security and compliance results, success criteria, known
limitations and the recommendation.

## Screens

- **Experiments:** registry, new-experiment form (tool, configuration B or C, workload,
  seed, every cost assumption and threshold editable and validated), live run status,
  conclusion, criteria, metric comparison with regressions highlighted, cost breakdown,
  assumptions, raw measurements, limitations, report download, re-evaluation.
- **Benchmarking:** tool comparison across experiments (median relative change per
  tool version and configuration), processing-time and cost charts (baseline vs. AI,
  one shared scale, legend, hover/focus tooltips, table view), quality and compliance
  indicators, criteria, run details and conclusion.
