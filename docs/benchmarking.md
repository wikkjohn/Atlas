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
| `experiment_measurements` (raw, one row per run) | cases, completions, outcomes vs. ground truth, manual reviews, review and wait seconds, escalations (compliance reviews), automated approvals, overdue tasks, document timeouts, failed executions, AI invocations by status, cycle-time statistics, account decisions checked and policy violations, workload fingerprint | the run's recorded case results, workflow executions and history, AI invocations, and the account requests its cases decided |
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
| AI cost per invocation | 0.04 | executed tool calls (including failed ones; blocked calls never ran) |
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
