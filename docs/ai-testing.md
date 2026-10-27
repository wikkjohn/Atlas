# AI testing laboratory

> **Status: design only.** The AI Innovation Lab is delivered in Phase 6 and benchmarking
> in Phase 7. Nothing in this document is implemented yet.

## Principles

- AI tools are registered once in a shared registry and called through one
  provider-independent adapter interface with typed requests and results, permission
  checks, timeouts, execution metadata and structured errors.
- **AI tools never make final decisions on their own authority.** The workflow policy
  engine and authorized human reviewers control account creation. An AI task can only
  return a recommendation, which policy decides how to use.
- Every tool invocation stores its input, output, version, timing and cost inputs.

## First candidate tool: AGB Intelligent KYC Assistant

A deterministic, rule-based proof-of-concept adapter that analyses a synthetic application
and its documents, flags missing or inconsistent fields, proposes a risk classification
with an explanation, and recommends approve, reject or escalate. A model-backed adapter can
replace it later without changing the workflow engine.

## Experiment configurations

| Config | Description |
| --- | --- |
| A — Baseline | Conventional validation rules + simulated human review |
| B — AI assisted | Tool prepares risk summaries and exceptions; humans still approve |
| C — AI automated tasks | Tool completes designated low-risk review tasks; policy and authorization controls remain |

All three run against the same seeded applications under equivalent conditions.

## Evaluation

Compared metrics: processing time, simulated labour time, manual reviews, cost per case,
completion rate, false approval and false rejection rates, escalation rate, policy
violations, errors, AI execution cost, total operating cost.

Costs come from transparent, configurable assumptions stored with each experiment. Raw
measurements and derived calculations are stored separately. Reports state their
assumptions and limitations, and never present simulated estimates as verified savings.
