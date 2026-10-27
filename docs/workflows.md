# Workflows

> **Status: design only.** The workflow engine is delivered in Phase 4. Nothing in this
> document is implemented yet; it records the agreed design so that earlier phases stay
> compatible with it.

## Engine design

A general-purpose, durable, database-backed workflow engine shared by every banking
module. Business processes are *definitions* (data), not hard-coded endpoint logic.

**Definition:** `workflow_id`, `name`, `version`, `description`, `business_owner`,
`trigger_type`, `input_schema` (JSON Schema), `steps`, `transition_rules`,
`approval_policies`, `failure_policies`, `timeout_policies`.

**Execution:** `execution_id`, `workflow_id`, `workflow_version`, `status`,
`current_steps`, `started_at`, `completed_at`, `initiated_by`, `correlation_id`, `context`.

**Step types:** automated service task, human task, approval, conditional decision,
parallel branch, wait state, AI task, completion, failure.

**Guarantees:** every state transition is persisted in the same transaction as its effects.
Step claims use row locks so a step cannot run twice. Executions resume after restart from
persisted state. Approvals are checked against role-based policies in the backend. Retries
follow per-step policies. Failures record the step, error and attempt count. Every
transition emits an audit event carrying the execution's correlation ID.

## WF-0001 Retail Account Opening (planned)

1. Customer submits application
2. Validate required information
3. Synthetic identity verification
4. Assign customer risk rating
5. Evaluate compliance rules
6. Route high-risk cases to human review
7. Authorized approver accepts or rejects
8. Create the account when approved (exactly once)
9. Finalize audit and workflow records
10. Send a simulated customer notification

Test scenarios: normal approval, rejection, high-risk human review.
