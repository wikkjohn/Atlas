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
| `rule_based_payment_screening` | **AGB Payment Fraud Screener** (Phase 9, proof of concept). Reviews payments that WF-0002's screening held: scam phrases in the reference (high), payee on the synthetic watchlist (critical), share of the balance and payment velocity (medium), first payment to the payee and high value (low). Any critical or high finding → **reject**; score ≥ 5 → **escalate**; otherwise **approve** at low risk — behavioural signals alone are common for legitimate first payments. Its blind spot is deliberate and documented: a scam with an ordinary reference looks like a legitimate large payment. Deterministic. |
| `rule_based_credit_underwriting` | **AGB Credit Underwriting Assistant** (Phase 11, proof of concept). Reviews loan applications WF-0003's credit policy refers to an underwriter: declared income against the synthetic bureau's income estimate (≥ 1.4× → high, ≥ 1.15× → medium), a recent default, a near-prime score (< 660) and a debt-to-income above 35 % (medium), self-employed income, five or more credit lines and a committee-size loan (low). Any high finding → **reject**; score ≥ 4 → **escalate**; a single medium finding → **approve** at medium risk; otherwise **approve** at low risk. Its blind spot is the same income rule: an honest self-employed applicant whose irregular income runs well above the estimate looks inflated. Deterministic. |
| `rule_based_overdraft_affordability` | **AGB Overdraft Affordability Assistant** (Phase 30, proof of concept). Reviews arranged-overdraft requests in WF-1003 v2 against the account's last 90 days (`retail.account_profile`). Findings: a limit above the product's maximum (critical); no money in, or a limit above a month's money in (high); money in during fewer than all three months, or overdrawn on 15 or more of 90 days (medium); a limit above half a month's money in (low). Any critical or high finding → **reject**; score ≥ 4 → **escalate**; a single medium finding → **approve** at medium risk; otherwise **approve** at low risk. Its blind spot is deliberate and documented: a customer with regular income who already lives in an overdraft raises one medium finding only, and is recommended for approval. Deterministic. |
| `fault_injection` | Behaves like the KYC assistant but fails, times out or returns malformed output for a configurable share of requests, decided by a hash of the request (reproducible). Exists to test failure handling. |

The demo seed registers `agb-intelligent-kyc-assistant 1.0.0` (all three actions),
`kyc-fault-injector 1.0.0` (10 % errors, 5 % timeouts, 5 % malformed output; not granted
`complete_low_risk_review`) and `agb-payment-fraud-screener 1.0.0` (`analyze_payment`,
`recommend_decision`, `complete_low_risk_review`; compatible with WF-0002). Phase 9 adds
`release_payment` and `approve_loan` to the actions no tool can ever be granted. Phase 11
registers `agb-credit-underwriting-assistant 1.0.0` (`analyze_credit_application`,
`recommend_decision`, `complete_low_risk_review`; compatible with WF-0003). Phase 30
registers `agb-overdraft-affordability-assistant 1.0.0` (`recommend_decision` only;
compatible with WF-1003, a stored workflow; the seed imports the examples without AI
steps first, then registers the tools, then imports WF-1003 v2, which calls the tool).

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

## WF-0002 and the payment fraud screener (Phase 9)

WF-0002 has the same three modes, applied to *held* payments only (straight-through
payments never reach a tool): `ai_fraud_review` (advisory) and `policy_release`
(`low-risk-payment-release-v1`), which releases a held payment without a person only when
automation is enabled, the tool answered, recommends approval at low risk, the payment is
below the high-value limit, the payee is not on the watchlist and the reference has no
scam phrase. The policy engine's `payments:release_low_risk` permission is refused by the
payments service for high-value payments.

What one experiment on `domestic-payments` v1 (seed 42, 100 payments, 25 staff, default
assumptions) measured:

| | Baseline | AI assisted | AI automated |
| --- | ---: | ---: | ---: |
| Manual reviews | 23 | 23 | 11 |
| Labour hours | 6.57 | 4.25 | 2.11 |
| Cost per completed case | 4.65 | 3.47 | 1.66 |
| Accuracy | 96 % | 98 % | 97 % |
| False approval rate (of should-reject payments) | 20 % | 13 % | 20 % |
| Policy violations | 0 | 0 | 0 |
| Verdict | — | not successful | not successful |

Both candidates fail the *compliance thresholds* criterion: the default maximum false
approval rate (5 %) was set for account opening, and in this scenario the people miss
quiet scams too. The point is not the verdict but that the platform shows where the risk
sits: automation removes half of the manual reviews and lets the quiet scams through.

## WF-0003 v2 and the credit underwriting assistant (Phase 11)

WF-0003 v2 adds `verify_income` (declared income ÷ the synthetic bureau's income estimate,
`lending.income_estimate`), then — for applications the credit policy refers, never for
automatic declines — `ai_underwriting_review` (advisory) and `policy_underwrite`
(`low-risk-loan-underwriting-v1`). The policy engine underwrites a loan without a person
only when automation is enabled, the tool answered, recommends approval at low risk, the
credit policy raised no flag, the loan is within the automation limit (15,000, never a
committee loan), declared income is at most 1.15× the estimate and the applicant is
salaried or retired. The lending service accepts the policy engine's
`loans:approve_low_risk` permission only within the automation limit, whoever calls it.

What two experiments on `personal-loans` v2 (seed 42, 100 applications, 25 staff, default
assumptions) measured — the baseline is the same run in both:

| | Baseline | AI assisted | AI automated |
| --- | ---: | ---: | ---: |
| Manual reviews | 91 | 92 | 59 |
| Labour hours | 35.6 | 21.7 | 15.2 |
| Cost per completed case | 18.91 | 11.89 | 8.59 |
| Accuracy | 93 % | 98 % | 98 % |
| False approval rate | 0 % | 0 % | 0 % |
| False rejection rate | 9.2 % | 2.6 % | 2.6 % |
| Policy violations | 0 | 0 | 0 |
| Verdict | — | successful | successful |

Unlike the fraud screener, this tool's main rule matches the scenario's main risk
(inflated incomes), so the simulated underwriters follow mostly correct advice. That
rests on the scenario's stated assumptions about reviewers and on a synthetic income
estimate that is better than real ones; it shows the platform working, not that such a
tool would perform like this on real applications.

## WF-1003 v2 and the overdraft affordability assistant (Phase 30)

WF-1003 v2 is a **stored** workflow. Before the credit officer decides, it reads the
account's last 90 days from the ledger (`retail.account_profile`), then asks the assistant
through `ai.review`. The advice is shown to the officer; no policy engine decides alone,
so the scenario runs baseline and AI assisted only (an AI-automated run is refused).
`ai.review` now skips the tool in an experiment's baseline (`ai_mode: off`) and reports
`invocation_status`, so the simulation's AI metrics count it like the code workflows'
AI steps.

What `retail-overdrafts` v1 measured (seed 2030, 300 requests, 12 staff, default
assumptions; one run each):

| | Baseline | AI assisted |
| --- | ---: | ---: |
| Accuracy | 94.3 % | 96.3 % |
| False approvals | 3 | 7 |
| False rejections | 14 | 4 |
| Customers living in an overdraft approved (of 33) | 2 | 7 |
| Review labour hours | 70.6 | 42.4 |
| Median cycle time (hours) | 1.87 | 0.18 |
| Tool's recommendation accuracy | — | 89 % |

Overall the assistant helps — fewer wrong refusals and much less review time — but every
extra false approval is the blind spot: simulated officers follow its approval of
customers who are already overdrawn most days. That is the trade-off an experiment's
evaluation should surface before such a tool is relied on, and it rests on the scenario's
stated reviewer assumptions, not on measured behaviour.

## WF-1008 v2 and the card fraud alert assistant (Phase 32)

WF-1008 v2 is a stored workflow. Before the fraud analyst decides whether to release a
card the fraud rules blocked, it reads the declined purchase and the card's history
(`cards.fraud_profile`), then asks the assistant through `ai.review`. As with WF-1003 v2,
a person always decides, so the scenario runs baseline and AI assisted only.

The assistant (`rule_based_card_fraud_review`) recommends keeping the block when the card
had not been used in the purchase's country before the last 24 hours, and weighs a first
high-risk purchase, an amount far above the usual and a burst of attempts. Its **blind
spot** is card testing: it leaves out attempts below 2 % of the daily limit as noise, so
five tiny test purchases before a crypto purchase at home look like one ordinary first
high-risk purchase, and it recommends releasing the card.

The workload builds every card's history through the real authorisation service, so the
blocks come from the real fraud rules (a case whose last purchase is not declined for
suspected fraud stops the run).

What `card-fraud-alerts` v1 measured (seed 2030, 300 cases, 12 staff, default
assumptions; one run each):

| | Baseline | AI assisted |
| --- | ---: | ---: |
| Accuracy | 88.0 % | 96.3 % |
| Wrong releases (fraud released) | 19 | 6 |
| Wrong refusals (genuine kept blocked) | 17 | 5 |
| Card testing released (of 27) | 3 | 4 |
| Review labour hours | 60.8 | 38.0 |
| Median cycle time (hours) | 0.85 | 0.13 |
| Tool's recommendation accuracy | — | 91 % (21 escalated) |

The assistant helps on every kind of case but one. Stolen cards and account takeovers
released fall from 16 to 2, and genuine travellers kept blocked from 12 to 2. Card testing
is the exception: the assistant recommends releasing 26 of the 27 (it escalates one whose
amount is far above the usual), and the simulated analysts,
following it, release 4 rather than 3, so card testing is 4 of the 6 wrong releases.
That rests on the scenario's stated reviewer assumptions, not on measured behaviour.

## WF-1009 v2 and the mortgage underwriting assistant (Phase 34)

WF-1009 v2 is a stored workflow. It records an application only when every lending rule
passes. Before the underwriter decides, it reads the application profile
(`mortgages.application_profile`) and asks the assistant through `ai.review`. A person
always decides, so the scenario runs baseline and AI assisted only.

What the assistant (`rule_based_mortgage_underwriting`) weighs:
- **Keep declined:** a stretched borrower (a payment above 30 % of income at 85 %
  loan-to-value or more), or a payment above 35 % of the bureau's income estimate.
- **Concerns:** declared income above 125 % of that estimate, loan-to-value of 80 % or
  more, a credit score below 660, and an automated valuation below 90 % of the price.

Its **blind spot** is age. The profile includes the applicant's age when the term ends,
and the assistant never reads it, so a 30- to 35-year mortgage for a 56- to 64-year-old
with prime figures is recommended for approval.

What `mortgage-applications` v1 measured (seed 2030, 300 applications, 12 staff, default
assumptions; one run each):

| | Baseline | AI assisted |
| --- | ---: | ---: |
| Accuracy | 89.7 % | 94.7 % |
| Wrong approvals | 17 | 15 |
| Wrong declines | 14 | 1 |
| Terms past retirement approved (of 54) | 2 | 7 |
| Review labour hours | 127.0 | 81.5 |
| Median cycle time (hours) | 7.50 | 3.56 |
| Tool's recommendation accuracy | — | 79 % (37 escalated) |

**Where the assistant helps:**
- Good applications declined fall from 14 to 1.
- Stretched and inflated-income applications approved fall from 9 to 2.
- Review time falls by more than a third.

**Where it does not:**
- Wrong approvals barely change (17 to 15). The assistant recommends approval for every
  application whose term runs past retirement, and the simulated underwriters, following
  it, approve 7 of 54 rather than 2.
- Thin credit files are escalated, which leaves the underwriter where the baseline was
  (6 approved either way).

These results rest on the scenario's stated reviewer assumptions, not on measured
behaviour.

## WF-1013 v2 and the covenant breach assistant (Phase 36)

WF-1013 v2 is a stored workflow. When a year's figures breach the facility's covenants, it
reads the breach profile (`commercial.breach_profile`) and asks the assistant through
`ai.review` before the credit committee decides whether to waive the breach. The committee
always decides, so the scenario runs baseline and AI assisted only. Its reviewers are
simulated executives, the first workload decided by the credit committee alone.

What the assistant (`rule_based_covenant_review`) weighs:
- **Keep frozen:** debt service cover below 1.00×, leverage more than 1.25 times its
  limit, or EBITDA falling 15 % or more two periods running.
- **Concerns:** cover below 1.10×, and a facility 90 % drawn or more.
- **A mild breach:** cover within 10 % of its threshold.

Its **blind spot** is history. The profile counts the facility's earlier breaches and
waivers, and the assistant never reads them, so a business that breaches again a year
after a waiver looks like a first near miss and is recommended for another waiver.

What `covenant-breaches` v1 measured (seed 2030, 300 breaches, 12 staff, default
assumptions; one run each):

| | Baseline | AI assisted |
| --- | ---: | ---: |
| Accuracy | 84.3 % | 94.3 % |
| Wrong waivers | 20 | 15 |
| Wrongly kept frozen | 27 | 2 |
| Repeat breaches waived (of 54) | 8 | 11 |
| Review labour hours | 192.8 | 123.7 |
| Median cycle time (hours) | 15.6 | 8.9 |
| Tool's recommendation accuracy | — | 80 % (32 escalated) |

**Where the assistant helps:**
- Breaches worth waiving that were kept frozen fall from 27 to 2.
- Falling businesses and over-leveraged ones are never waived (8 in the baseline).
- Committee time falls by more than a third.

**Where it does not:**
- The assistant recommends waiving all 54 repeat breaches, and the simulated committee,
  following it, waives 11 rather than 8.
- Thin cover on fully drawn facilities is escalated, which leaves the committee where the
  baseline was (4 waived either way).

These results rest on the scenario's stated reviewer assumptions, not on measured
behaviour.

## WF-1016 v2 and the document check assistant (Phase 38)

WF-1016 v2 is a stored workflow. When documents presented under a letter of credit are
discrepant, it reads the presentation profile (`trade.presentation_profile`) and asks the
assistant through `ai.review` before a trade officer (`trade:manage`) decides whether to pay
on the applicant's waiver. The officer always decides, so the scenario runs baseline and AI
assisted only.

What the assistant (`rule_based_document_check`) weighs:
- **Reject:** a missing document; a late shipment presented in the last 7 days of the
  credit; inconsistent documents on a draw of 90 % of the credit or more.
- **Concerns:** a late shipment; inconsistent documents on a smaller draw; an applicant
  whose funds cover the payment less than 1.10 times.
- **Minor:** a late presentation or a description that does not match.

Its **blind spot** is the credit's history. The profile counts earlier presentations
rejected for the same discrepancy, and the assistant never reads them, so a beneficiary who
presents the same faulty documents again looks like a first, minor slip and is recommended
for payment.

What `discrepant-presentations` v1 measured (seed 2030, 300 presentations, 12 staff,
default assumptions; one run each):

| | Baseline | AI assisted |
| --- | ---: | ---: |
| Accuracy | 86.0 % | 94.3 % |
| Wrongly paid | 24 | 15 |
| Wrongly rejected | 18 | 2 |
| Repeat discrepancies paid (of 61) | 8 | 12 |
| Review labour hours | 155.9 | 101.0 |
| Median cycle time (hours) | 9.5 | 4.7 |
| Tool's recommendation accuracy | — | 77 % (33 escalated) |

**Where the assistant helps:**
- Minor discrepancies wrongly rejected fall from 18 to 2.
- Missing documents and last-minute late shipments are never paid (13 in the baseline).
- Officer time falls by about a third.

**Where it does not:**
- The assistant recommends paying all 61 repeat discrepancies, and the simulated officers,
  following it, pay 12 rather than 8.
- Late shipments the applicant can barely fund are escalated, which leaves the officers
  where the baseline was (3 paid either way).

The headline figures are close to the covenant scenario's (Phase 36). Both scenarios use the
same reviewer and AI-assistance assumptions and a similar mix of kinds. These results rest
on those stated assumptions, not on measured behaviour.

## WF-1018 v2 and the back-office check assistant (Phase 40)

WF-1018 v2 is a stored workflow. After a dealer books an interbank deal, it reads the deal
profile (`treasury.deal_profile`) and asks the assistant through `ai.review` before back
office (`treasury:confirm`) decides whether to confirm the deal or cancel it. Back office
always decides, so the scenario runs baseline and AI assisted only. Each case gets its own
synthetic counterparty, and each placement is funded by a deposit, so cases share neither
limits nor cash.

What the assistant (`rule_based_back_office_check`) weighs:
- **Cancel:**
  - a rate more than 1.50 points from the currency's reference rate, against the bank;
  - a placement of more than 180 days with a counterparty rated BBB or BBB-.
- **Concerns:**
  - a placement using 90 % or more of the counterparty's limit;
  - a tenor beyond 90 days;
  - liquidity coverage after a placement below 110 %.
- **Minor:** a rate 0.50–1.50 points off the reference against the bank.

Its **blind spot** is duplicates. The profile counts deals booked the same day with the
same counterparty, kind, currency, principal, rate and maturity, and the assistant never reads that count. So a
dealer's double-keyed booking looks like an ordinary deal and is recommended for
confirmation.

What `deal-confirmations` v1 measured (seed 2030, 300 deals, 12 staff, default
assumptions; one run each):

| | Baseline | AI assisted |
| --- | ---: | ---: |
| Accuracy | 83.3 % | 91.3 % |
| Wrongly confirmed | 33 | 25 |
| Wrongly cancelled | 17 | 1 |
| Duplicates confirmed (of 56) | 14 | 18 |
| Review labour hours | 98.7 | 63.6 |
| Median cycle time (hours) | 4.6 | 1.5 |
| Tool's recommendation accuracy | — | 79 % (34 escalated) |

**Where the assistant helps:**
- Deals on market terms that were wrongly cancelled fall from 17 to 1.
- Off-market rates and long placements with weak names are never confirmed (12 in the
  baseline).
- Back-office time falls by about a third.

**Where it does not:**
- The assistant recommends confirming all 56 duplicates. The simulated back office,
  following it, confirms 18 rather than 14.
- Long placements that use almost all of a counterparty's limit are escalated, which leaves
  back office where the baseline was: 7 confirmed either way.

These results rest on the scenario's stated reviewer and AI-assistance assumptions, not on
measured behaviour.

## WF-1023 v2 and the recall assistant (Phase 42)

WF-1023 v2 is a stored workflow. After a recall of an outgoing payment is recorded, it reads
the recall profile (`clearing.recall_profile`) and asks the assistant through `ai.review`
before back office (`payments:approve`) decides whether to send the recall or withdraw it.
Back office always decides, so the scenario runs baseline and AI assisted only. Each case's
payment, the payer's earlier payments and earlier recalls run through the real clearing
service before the run.

What the assistant (`rule_based_recall_review`) weighs:
- **Withdraw:**
  - a recall outside its reason's window;
  - a "duplicate" with no matching payment (same payer, account and amount within three
    days);
  - a fraud claim against a beneficiary the payer has paid three or more times before.
- **Concerns:** two days or fewer of the window left; a high-value payment.

Its **blind spot** is the payer. The profile counts the payer's recalls in the last 90 days
and how many were refused, and the assistant never reads either count. So a customer who
recalls payment after payment looks like a first, reasonable request and is recommended for
sending.

What `recall-triage` v1 measured (seed 2030, 300 recalls, 12 staff, default assumptions;
one run each):

| | Baseline | AI assisted |
| --- | ---: | ---: |
| Accuracy | 82.0 % | 94.0 % |
| Wrongly sent | 31 | 16 |
| Wrongly withdrawn | 23 | 2 |
| Serial recallers' requests sent (of 52) | 9 | 10 |
| Review labour hours | 73.6 | 48.2 |
| Median cycle time (hours) | 2.8 | 0.5 |
| Tool's recommendation accuracy | — | 80 % (37 escalated) |

**Where the assistant helps:**
- Genuine duplicates and fast fraud reports wrongly withdrawn fall from 23 to 2.
- Claimed duplicates with no match and fraud claims against established payees are never
  sent (16 in the baseline).
- Back-office time falls by about a third.

**Where it does not:**
- The assistant recommends sending all 52 serial recallers' requests. The simulated back
  office, following it, sends 10 rather than 9.
- Late technical recalls of high-value payments are escalated, which leaves back office
  where the baseline was: 6 sent either way.

These results rest on the scenario's stated reviewer and AI-assistance assumptions, not on
measured behaviour.

## WF-1025 v2 and the suitability review assistant (Phase 44)

WF-1025 v2 is a stored workflow. When an investment order is unsuitable, it reads the order
profile (`wealth.order_profile`) and asks the assistant through `ai.review` before a manager
(`wealth:approve`) decides whether the order may go ahead at the client's insistence or is
refused. A manager always decides, so the scenario runs baseline and AI assisted only. Each
case's customer, profile, portfolio and earlier orders run through the real wealth service
before the run.

What the assistant (`rule_based_suitability_review`) weighs:
- **Refuse:**
  - a security three or more risk levels above the customer's profile;
  - a complex product for a customer whose knowledge is none or basic;
  - an order that leaves less than a tenth of the customer's assets in cash.
- **Concerns:** two levels above the profile; a step above it without experience at that
  level; concentration in a security above risk 2.
- **No concern:** one level above the profile for an experienced customer, and concentration
  in a low-risk security.

Its **blind spot** is the customer's record. The profile counts orders of theirs that went
ahead against advice in the last 90 days, and orders refused, and the assistant never reads
either count. So a customer who insists order after order looks like a first, small step and
is recommended to go ahead.

What `order-review` v1 measured (seed 2030, 300 orders, 12 staff, default assumptions; one
run each):

| | Baseline | AI assisted |
| --- | ---: | ---: |
| Accuracy | 82.0 % | 95.3 % |
| Wrongly let go ahead | 25 | 13 |
| Wrongly refused | 29 | 1 |
| Serial insisters' orders let go ahead (of 42) | 6 | 7 |
| Review labour hours | 98.2 | 63.8 |
| Median cycle time (hours) | 4.3 | 1.5 |
| Tool's recommendation accuracy | — | 84 % (30 escalated) |

**Where the assistant helps:**
- Experienced customers' small steps and low-risk concentrations wrongly refused fall from
  29 to 1.
- Large risk gaps and complex products for novices are never let through (9 in the
  baseline), and only one order that drains the customer's cash goes ahead (5).
- Managers' time falls by about a third.

**Where it does not:**
- The assistant recommends letting all 42 serial insisters' orders go ahead. The simulated
  managers, following it, let 7 through rather than 6.
- Two-level steps without experience are escalated, which leaves managers where the baseline
  was: 5 let through either way.

These results rest on the scenario's stated reviewer and AI-assistance assumptions, not on
measured behaviour.

## WF-1027 v2 and the alert review assistant (Phase 46)

WF-1027 v2 is a stored workflow. When an AML alert is investigated, it reads the alert
profile (`compliance.alert_profile`) and asks the assistant through `ai.review` before a
second compliance officer (`compliance:monitor`) decides whether the case may be closed with
no action, or is escalated to a suspicious activity report. An officer always decides, so
the scenario runs baseline and AI assisted only. The workflow's outcome reads as the
sign-off: `approved` when the case is closed, `rejected` when it is escalated.

Each case's account gets four months of dated activity, posted through the real accounts
service, and its alert is raised by a real monitoring run before the run.

What the assistant (`rule_based_alert_review`) weighs:
- **Escalate:**
  - structuring;
  - money passed through at four times the account's usual level;
  - a high-risk customer's turnover at three times it;
  - a customer with a report already filed.
- **Concerns:** a business's cash at 2.5 times its usual level, especially in large
  amounts; repeated large cash deposits by an individual.
- **No concern:**
  - a business's cash in line with its usual takings;
  - a one-off large deposit;
  - a pass-through pattern the account always has.

Its **blind spot** is the alert history. The profile counts the customer's earlier alerts in
the last year, closed or dismissed, and the assistant never reads the count. So a customer
whose cash keeps setting off alerts looks like a business banking its usual takings and is
recommended for closing.

What `alert-triage` v1 measured (seed 2030, 300 alerts, 12 staff, default assumptions; one
run each):

| | Baseline | AI assisted |
| --- | ---: | ---: |
| Accuracy | 87.0 % | 95.7 % |
| Wrongly closed | 22 | 11 |
| Wrongly escalated | 17 | 2 |
| Repeat offenders' cases closed (of 43) | 8 | 10 |
| Officer hours | 127.1 | 79.2 |
| Median cycle time (hours) | 6.9 | 2.9 |
| Tool's recommendation accuracy | — | 85 % (20 referred on) |

**Where the assistant helps:**
- Explained alerts wrongly escalated fall from 17 to 2.
- Structuring, funnel accounts and high-risk spikes are never closed (13 in the baseline).
- Officers' time falls by more than a third.

**Where it does not:**
- The assistant recommends closing all 43 repeat offenders' cases. The simulated officers,
  following it, close 10 rather than 8.
- A business's sudden spike is referred on, which leaves officers where the baseline was:
  1 closed either way.

These results rest on the scenario's stated reviewer and AI-assistance assumptions, not on
measured behaviour.

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
