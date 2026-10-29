# Workflows

The workflow engine (Phase 4) is a durable, database-backed interpreter for versioned
business-process definitions. It is shared by every module: business logic lives in named
step handlers; the engine owns state, routing, approvals, retries, timeouts and history.

Code: `backend/app/modules/workflows/` — `definition.py` (model and validation),
`registry.py` (definitions and handlers), `engine.py` (execution), `wf0001.py` (the first
workflow), `service.py` / `router.py` (API).

## Definitions

A definition has `workflow_id` (`WF-0000` format), `name`, `version`, `description`,
`business_owner`, `trigger_type`, `input_schema` (generated from a Pydantic model),
`start` and `steps`. Its `transition_rules`, `approval_policies`, `failure_policies` and
`timeout_policies` are derived views returned by `GET /api/v1/workflows/{id}`.

Definitions are validated when registered: every referenced step exists, every
non-terminal step has a way forward, handlers are registered, parallel steps name a join,
approvals have transitions, at least one completion step exists and every step is
reachable. A version is immutable: re-registering it with different content fails, and the
first execution stores a snapshot (`workflow_definitions`) with a content hash that later
starts must match.

### Step types

| Type | Behaviour |
| --- | --- |
| `service_task` | Runs a registered handler. Retried on transient errors (`retry.max_attempts`, exponential `backoff_seconds`); then `on_failure` or the execution fails. |
| `human_task` | Waits for a person holding the step's permissions to submit its `form`. |
| `approval` | Waits for an `approve`/`reject` decision by a person holding every listed permission and not in `distinct_from` (`initiator` or earlier step ids — four-eyes). |
| `decision` | Routes on the first matching transition condition. |
| `parallel` / `join` | Starts every branch; the join runs once, after all branches arrive. |
| `wait` | Waits for a named signal and/or a timer. |
| `ai_task` | Calls a registered AI adapter (Phase 6 connects the AI tool registry). |
| `completion` / `failure` | Ends the execution (outcome from the step or `context.outcome`). |

Conditions are structured, never `eval`: `{"path": "a.b", "op": "eq", "value": …}` with
`eq, ne, in, not_in, gt, gte, lt, lte, exists, truthy`, combined with `all` / `any` and
`negate`. Timeouts either `flag` a task as overdue (audited) or `transition` elsewhere.

## Execution guarantees

- **Persisted state.** Executions, step runs (one row per visit; retries reuse it with
  `attempt` + 1) and an append-only event history (`workflow_events`, protected by a
  trigger, ordered by a database sequence) are all in PostgreSQL.
- **Atomic steps.** A handler runs inside a savepoint with its state transition. If it
  raises, its writes are rolled back and only the failure is recorded; if the process
  dies, the whole transaction rolls back and the step is still `pending`.
- **No duplicate execution.** Advancing locks the execution row; concurrent workers wait
  (or skip, in the runner) instead of running the same step. Tested with four threads.
- **Resumption.** `run_due` (CLI: `python -m app.cli run-workflows [--watch]`) advances
  every execution with due steps or expired timers, one execution per transaction, with
  `SKIP LOCKED`. A test commits one step, discards the session and resumes in a new one.
- **Validated transitions and approvals.** Only the engine moves state; approvals check
  permissions and four-eyes on every completion; a task can be completed once.
- **Timing.** Every run records `started_at`, `completed_at`, `duration_ms`; real time is
  read before each step (an explicit `now`, e.g. the simulation clock, freezes time).
- **Auditing.** `workflow.started`, `workflow.task_completed`, `workflow.task_overdue`,
  `workflow.completed` / `failed` / `cancelled` go to the audit log with correlation IDs.

## WF-0001 Retail Account Opening

| # | Step | Type | Notes |
| --- | --- | --- | --- |
| 1 | Customer submits application | service_task | Records receipt |
| 2 | Validate required information | service_task | Active country, age ≥ 18 → else reject; missing identity document or proof of address → wait |
| — | Wait for missing documents | wait | Signal `documents_submitted`; 72 h timeout → reject |
| 3 | Register synthetic customer | service_task | Creates the customer; KYC → pending |
| 4 | Identity verification ‖ sanctions screening | parallel | Synthetic document check digits, name/DOB match, expiry; synthetic watchlist |
| 5 | Assign customer risk rating | service_task | Score from sanctions hit, identity issues, PEP, large deposits, age |
| 6 | Evaluate compliance rules | service_task | Flags; `requires_review` when high risk or flagged |
| 7 | Route the case | decision | Forged documents → reject; review needed → compliance review; else approval |
| 8 | Compliance review / Authorized approval | approval | Needs `customers:review + accounts:approve` / `accounts:approve`; never the initiator; 48 h / 24 h overdue flags |
| 9 | Create the customer account | service_task | KYC verified, then the Phase 3 request → approval services (which re-check four-eyes, high risk and eligibility); failures → technical failure |
| — | Reject the application | service_task | KYC rejected (if a customer exists), reasons recorded |
| 10 | Finalize audit and workflow records | service_task | Audit summary |
| 11 | Send simulated customer notification | service_task | Stored in `customer_notifications`; nothing is sent |

### Version 2 (Phase 6)

Version 2 inserts **AI KYC assistant review** (ai_task, after step 6) and **Policy engine:
low-risk automation check** (service_task, between routing and approval). With the AI mode
off — the default for cases started from the API or UI — it behaves exactly like version 1.
Version 1 remains registered; executions keep the version they started on. See
[ai-testing.md](ai-testing.md#wf-0001-version-2).

Tested scenarios: normal approval, approver rejection, high-risk compliance review,
sanctions hit, underage (invalid), forged documents, missing documents (resume and
timeout), approvals cannot be skipped, initiator cannot approve, duplicate start, failing
account-opening step, history and metrics.

## WF-0002 Domestic Payment (Phase 9)

A customer pays another account at the bank in the same currency. Business owner:
Payments Operations. Input: debtor and creditor account numbers, amount (minor units),
currency, reference (≤ 140 characters) and channel.

| # | Step | Type | Notes |
| --- | --- | --- | --- |
| 1 | Customer instructs payment | service_task | Records receipt and the case summary ("1,250.50 USD to …") |
| 2 | Validate accounts and amount | service_task | Both accounts exist, are open and in the currency, are different, amount ≤ 1,000,000; creates the `pending` payment record → else reject (no record) |
| 3 | Check available funds | service_task | Balance from the ledger; not enough → reject |
| 4 | Fraud and sanctions screening | service_task | Signals: payee on the synthetic watchlist (5), scam phrase in the reference (3), ≥ 80 % of the balance (2), ≥ 3 other payments in 24 h (2), first payment to this payee (1). Held at score ≥ 3 or any watchlist hit |
| 5 | Route the payment | decision | Held → AI review; high value (≥ 10,000) → approval; else release (straight-through) |
| — | AI fraud screener review (advisory) | ai_task | Off / assisted / automated, like WF-0001 v2; never decides |
| — | Policy engine: low-risk release check | service_task | Automated mode only: tool says approve at low risk, not high value, no watchlist hit, no scam phrase → release by the policy engine; otherwise a person decides |
| 6 | Fraud review of a held payment | approval | `payments:review` (compliance), never the initiator; 4 h overdue flag. Approve → release (or high-value approval), reject → reject |
| 7 | High-value approval (four-eyes) | approval | `payments:approve` (managers), never the initiator or the fraud reviewer; 2 h overdue flag |
| 8 | Post the payment to the ledger | service_task | The payments service re-checks everything under row locks (see below); a refusal → reject |
| — | Reject the payment | service_task | Payment `rejected` with the reasons |
| 9 | Send simulated customer notification | service_task | To the paying customer |

The **payments service** is the only code that moves money between customer accounts and
re-applies its controls for any caller: both accounts open and in the payment's currency
(locked in id order, so two payments cannot deadlock), enough funds, and for a high-value
payment an approver other than the initiator holding `payments:approve`. Below the limit a
fraud reviewer (`payments:review`) or the policy engine (`payments:release_low_risk`) may
clear a held payment. The database refuses a payment approved by its initiator, and a
released payment without its journal entry.

![WF-0002 in the Workflow Explorer](images/10-wf0002.png)
![Payments](images/08-payments.png)

## WF-0003 Personal Loan Origination (Phase 9)

An existing, KYC-verified customer applies for an unsecured personal loan. Business owner:
Retail Lending. Input: customer number, disbursement account, amount, term (6–84 months),
purpose, declared monthly income and existing monthly repayments, employment status.

| # | Step | Type | Notes |
| --- | --- | --- | --- |
| 1 | Customer submits loan application | service_task | Records receipt |
| 2 | Validate customer, account and product limits | service_task | Customer exists, KYC verified, age ≥ 18; account is theirs and open; 1,000–50,000 → else decline |
| 3 | Synthetic credit bureau check | service_task | Deterministic score 300–850 from the name and date of birth, recent defaults, open credit lines (retried on transient failure) |
| 4 | Price the loan and assess affordability | service_task | Rate by score band (6.90 % ≥ 760, 8.90 % ≥ 700, 11.90 % ≥ 640, 15.90 % ≥ 580); level monthly instalment; debt-to-income including the new loan; committee needed above 25,000 |
| 5 | Apply the credit policy | service_task | Automatic decline: score < 580, ≥ 2 recent defaults, unemployed, debt-to-income > 45 %. Everything else is referred, with flags (near-prime score, debt-to-income > 35 %, self-employed income, committee) |
| 6 | Underwriting review | approval | `loans:approve` (managers), never the initiator; 24 h overdue flag |
| 7 | Credit committee approval | approval | Loans above 25,000: `loans:approve_large` (regional and global executives), never the initiator or the underwriter; 48 h overdue flag |
| 8 | Book the loan and disburse the funds | service_task | The lending service re-checks KYC, ownership, limits and the four-eyes and committee rules, then posts loan receivable → customer account in one entry; failures → technical failure |
| — | Decline the application | service_task | Reasons recorded and audited |
| 9 | Send simulated customer notification | service_task | Loan number, amount and instalment, or the decline reasons |

### Version 2 (Phase 11)

Live applications start on v2. After affordability, **Verify income against the bureau
estimate** (`verify_income`) records the declared income ÷ the synthetic bureau's income
estimate. A referred application then goes through **AI underwriting assistant review**
(`ai_task`, off / assisted / automated; with AI off it records `{"mode": "off"}`) and
**Route the referred application**: in automated mode, a low-risk approval request goes to
**Policy engine: low-risk underwriting check** (`low-risk-loan-underwriting-v1`), which
either underwrites the loan as the policy engine (then disbursement) or sends it to the
underwriter. Everything else is unchanged; see [ai-testing.md](ai-testing.md).

![Lending](images/09-lending.png)

## WF-0004 Loan Collections (Phase 10)

Works a personal loan in arrears. Business owner: Retail Lending — Collections. Trigger:
**event** — loan servicing starts and steers it; nobody needs to start it by hand. Input:
the loan id and the lending business date the case opened on. The case's business key is
the loan id, and every step runs at the business date that servicing reported.

| # | Step | Type | Notes |
| --- | --- | --- | --- |
| 1 | Open collections case | service_task | Records days past due, overdue amount, instalments and bucket; fails if nothing is overdue |
| 2 | Send simulated arrears reminder | service_task | A simulated letter to the borrower (`customer_notifications`) |
| 3 | Wait for repayment or escalation | wait | Signal `loan_status`: `cured` or `escalate` (sent by the servicing listener) |
| 4 | Route the case | decision | `cured` → close as cured; otherwise → write-off review |
| 5 | Write-off review (credit committee) | approval | `loans:approve_large` (regional and global executives), never the person who opened the case; 7-day overdue flag. Risk shown: the escalation bucket |
| 6 | Write the loan off | service_task | The lending service re-checks the authority and the 90-day rule on the business date. A loan paid while the review was open is not written off → closed as cured |
| — | Close: arrears cleared / write-off declined / written off | service_task | Outcome `cured`, `write_off_declined` or `written_off` |

How servicing drives it (`servicing.on_arrears_change` → `wf0004.sync_collections`, called
after every servicing run, arrears repayment and payoff):

- 30 or more days past due and no open case → a case starts;
- arrears cleared or the loan closed while the case waits → signal `cured`;
- 90 or more days past due while the case waits → signal `escalate`;
- a declined write-off closes the case; the next servicing run opens a new one.

The lending module never imports the workflow module: the workflow registers itself as a
listener, so lending stays independent of workflows.

![Lending with servicing](images/12-loan-servicing.png)
![A loan in arrears: schedule, repayment, payoff and its collections case](images/13-loan-detail.png)

## Shared workflow plumbing (Phase 9)

- **Presenters** (`registry.register_presenter`) say how a workflow's cases are named in
  lists and inboxes: a `subject` (applicant, payment summary, borrower), a risk and flags,
  each a path into the execution context. Execution and task lists return `subject`.

  ![One task inbox for every workflow](images/11-task-inbox.png)

- **Advisory AI steps** (`workflows/advisory.py`) share one implementation of the
  off/assisted/automated modes and the safe escalation when a tool gives no usable answer.
- **`workflows/catalog.py`** imports every business workflow (WF-0001 to WF-0004) so its definitions and
  handlers are registered wherever the application or the CLI starts.
