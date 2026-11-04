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

| Criterion | Rule (default threshold) |
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
  in each chosen country (1 to 10), is a cell; each cell is a repeated-seed series. The
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
