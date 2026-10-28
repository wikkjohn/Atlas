# AI Innovation Lab

> **Status:** implemented — the AI tool registry, adapters, invocation service, WF-0001
> v2 AI modes and A/B/C runs (Phase 6), and the evaluation engine with cost models,
> success criteria and reports (Phase 7, see [benchmarking.md](benchmarking.md)).

## Principles

- **One registry, one contract.** Every AI tool is registered once in the shared
  `ai_tools` table and called only through `app.modules.ai_tools.service.invoke`. Swapping
  a rule-based tool for a model-backed one means registering a new tool version with a
  different adapter; workflows do not change.
- **Tools advise; they never decide.** No tool can be granted an action that changes
  banking records. Account creation stays with authorized people and the workflow policy
  engine, and the accounts service re-checks authority whatever the workflow asks.
- **Every call is recorded** in `ai_tool_invocations`: the request, the result or error,
  status, duration, usage figures, the workflow execution and simulation run it belongs to.
- **Failures are safe.** A tool that errors, times out, returns malformed output or is
  refused never fails the workflow: the case is escalated to people.

## Registry

A tool version has `tool_id`, `tool_name`, `tool_version` (semantic), `provider`,
`description`, `adapter` (the implementation), `input_schema` and `output_schema` (JSON
Schema, defaulting to the adapter's), `allowed_actions`, `permissions` (platform
permissions a person needs to call it directly), `compatible_workflows`, `configuration`
(validated by the adapter), `status` (active or disabled) and `created_at`. Versions are
immutable; only the status changes. Registration is refused (422) for:

- actions that may never be delegated (`approve_account`, `open_account`,
  `reject_application`, `change_kyc_status`, `post_ledger_entry`, `modify_customer`),
  unknown actions, or actions the adapter does not implement;
- schemas that are not valid JSON Schema or do not describe an object;
- configuration the adapter rejects, unknown permissions or unknown workflows.

Grantable actions: `analyze_application`, `recommend_decision`,
`complete_low_risk_review` (the policy engine still decides whether a case proceeds).

## Adapter contract

```python
class AIToolAdapter(ABC):
    key, name, provider, description: ClassVar[str]
    supported_actions: ClassVar[frozenset[str]]
    input_model, output_model, config_model: ClassVar[type[BaseModel]]

    async def execute(self, request: ToolRequest, context: ToolContext) -> ToolResult: ...
```

`ToolRequest` = action + input; `ToolContext` = tool identity, configuration, business
time, actor, execution and correlation id; `ToolResult` = output + usage. Adapters raise
`ToolError(code, message, retryable)` for structured failures.

The invocation service, in order: refuses disabled tools and actions the tool was not
granted (`blocked`, audited); validates the request against `input_schema`
(`invalid_input`); runs the adapter under the configured `timeout_seconds` (`timeout`);
captures `ToolError` and any unexpected exception (`failed`); validates the result
against `output_schema` (`invalid_output`); otherwise `succeeded`.

### Registered implementations

| Adapter | What it does |
| --- | --- |
| `rule_based_kyc` | **AGB Intelligent KYC Assistant** (proof of concept). Checks for missing identity document / proof of address, document check digits, name consistency (≤ 2 edits is a typo), date-of-birth match, document expiry, age, sanctions screening result, politically exposed status and large expected deposits. Each finding has a severity; the score gives low/medium/high risk; any critical finding → **reject**, any high or medium → **escalate**, otherwise **approve**; plus a confidence and a written explanation. Deterministic. |
| `fault_injection` | Behaves like the KYC assistant but fails, times out or returns malformed output for a configurable share of requests, decided by a hash of the request (reproducible). Exists to test failure handling. |

The demo seed registers `agb-intelligent-kyc-assistant 1.0.0` (all three actions) and
`kyc-fault-injector 1.0.0` (10 % errors, 5 % timeouts, 5 % malformed output; not granted
`complete_low_risk_review`).

## WF-0001 version 2

Version 2 is version 1 plus two steps, controlled by the execution's settings
(`ai_mode`: off, assisted, automated; `ai_tool_id`):

1. **`ai_kyc_review`** (ai_task) after compliance evaluation. Off: does nothing, so v2 with
   AI off behaves exactly like v1. Assisted: calls `recommend_decision` and stores the
   recommendation, risk classification, findings and explanation in the case. Automated:
   calls `complete_low_risk_review` and *requests* automation when the tool recommends
   approval at low risk. Any unsuccessful call → recommendation `escalate`, no automation.
2. **`policy_approval`** — the workflow policy engine (`low-risk-automation-v1`). Reached
   only when automation was requested and the case needs no compliance review. It approves
   only if **every** check passes: automation enabled, tool result available, tool
   recommends approval, tool risk low, workflow risk rating low, no compliance flags,
   identity verified, sanctions clear, expected monthly deposits ≤ 25,000. Otherwise the
   case goes to a human approver as usual. Approval is recorded against the
   `atlas-policy-engine` system principal.

Controls that hold regardless of the workflow:

- The policy engine principal has role `automated_policy` with a single permission,
  `accounts:approve_low_risk`. The accounts service refuses it for any customer whose risk
  rating is not low, and refuses it rejections. It cannot sign in and the role cannot be
  given to people or employees.
- High-risk cases, sanctions hits, PEPs and flagged identities always go to compliance
  review; four-eyes still applies to every human decision.

## Experiment configurations

Scenario `retail-onboarding` **v2** (pinned to WF-0001 v2) runs in three modes:

| Config | Mode | WF-0001 v2 AI mode | What changes |
| --- | --- | --- | --- |
| A — Baseline | `baseline` | off | Conventional rules and simulated human review |
| B — AI assisted | `ai_assisted` | assisted | The tool prepares a recommendation for every case; people still decide |
| C — AI automated tasks | `ai_automated` | automated | The policy engine may approve low-risk cases the tool recommends; everything else stays with people |

`POST /api/v1/simulations/suites` runs the chosen modes one after another with the same
scenario, seed and workload, so they process **the same applications and staff** (the
generators depend only on the seed). Each run is an ordinary simulation run (stored
configuration incl. the tool's id, version, adapter, configuration and schema hashes;
digest; reproductions).

### Assumptions (simulated, not measured)

How an AI summary changes human reviewers is a modelling assumption, stored in the
scenario configuration (`ai_assistance`) and therefore in every run:

| Assumption | Value |
| --- | --- |
| Review time with an approve/reject recommendation | 60 % of the usual time |
| Reviewer accuracy when the recommendation is right | 99 % |
| Reviewer accuracy when the recommendation is wrong (automation bias) | 80 % |
| Escalation or unavailable tool | no change |

The rule-based assistant sees the same synthetic signals as the workflow's own checks, so
its recommendations are almost always right on this synthetic data. That is a property of
the proof of concept and the data, not evidence about any real model.

### What a run reports about the tool

Invocations by status, failed or blocked calls, recommendations, escalations, accuracy of
approve/reject recommendations against ground truth, and approvals made by the policy
engine; per case: the recommendation, the call status and whether it was automated.

Example (seed 42, 100 applications, 25 staff, local): baseline 92 manual reviews and
21.0 h of review labour, 98 % decision accuracy; assisted 92 reviews, 13.1 h, 100 %;
automated 12 reviews, 3.9 h, 100 %, 80 policy approvals. With the fault injector, failed,
timed-out and malformed calls were captured and escalated, and every automated-mode call
was blocked (the action is not granted), leaving results identical to the baseline.

## Evaluation

Experiments, the cost model, success criteria, regressions, reports and the
Benchmarking screen are described in [benchmarking.md](benchmarking.md).
