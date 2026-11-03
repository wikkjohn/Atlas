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

## WF-1030 v2 and the rating review assistant (Phase 48)

WF-1030 v2 is a stored workflow. When a rating departs from the model's grade, it reads the
rating profile (`risk.rating_profile`) and asks the assistant through `ai.review` before a
regional executive (`risk:approve`) approves the grade or keeps the model's. An approver
always decides, so the scenario runs baseline and AI assisted only.

Each case's customer gets three months of dated deposits, and an overdraft drawn or a loan
where the case needs one, through the real accounts, retail and lending services.

What the assistant (`rule_based_rating_review`) weighs:
- **Keep the model's grade:**
  - grade 10 (in default) without 90 days past due;
  - a departure of three notches or more;
  - an upgrade with the overdraft 75 % drawn or more, or debt above 120 % of a year's money
    in.
- **Refer on:** an upgrade nothing supports; a downgrade with no overdraft or debt strain.
- **Approve:** a downgrade the overdraft or debt explains; an upgrade with debt at most 25 %
  of a year's money in and no overdraft drawn.

Its **blind spot** is the rating history. The profile counts the customer's other departures
from the model in the last year and how many were rejected, and the assistant never reads
them. So an upgrade a rater keeps asking for, and is refused, looks like a strong customer
due one notch, and it recommends approving.

What `rating-overrides` v1 measured (seed 2030, 300 ratings, 12 staff, default assumptions;
one run each):

| | Baseline | AI assisted |
| --- | ---: | ---: |
| Accuracy | 87.0 % | 94.7 % |
| Wrongly approved | 15 | 9 |
| Wrongly rejected | 24 | 7 |
| Refused upgrades asked for again, approved (of 44) | 4 | 8 |
| Approver hours | 152.6 | 98.9 |
| Median cycle time (hours) | 12.3 | 6.5 |
| Tool's recommendation accuracy | — | 83 % (35 referred on) |

**Where the assistant helps:**
- Justified grades wrongly rejected fall from 24 to 7.
- Upgrades under strain, departures of three notches or more and default grades without
  arrears are rejected 100 times of 101 (11 approved in the baseline).
- Approvers' time falls by about a third.

**Where it does not:**
- It recommends approving all 44 upgrades already refused this year. The simulated
  approvers, following it, approve 8 rather than 4.
- A one-notch precautionary downgrade is referred on, which leaves approvers where the
  baseline was: 30 of 35 approved either way.

These results rest on the scenario's stated reviewer and AI-assistance assumptions, not on
measured behaviour.

## WF-1036 v2 and the journal review assistant (Phase 50)

WF-1036 v2 is a stored workflow. A proposed manual journal is read for its profile
(`finance.journal_profile`) and the assistant is asked through `ai.review` before a regional
executive (`finance:approve`), never the preparer, posts it or rejects it. An approver always
decides, so the scenario runs baseline and AI assisted only.

Each case is a journal on its own simulation ledger accounts. Earlier journals the case needs
(a duplicate's original, a split entry's first pieces) are proposed and posted first through
the real finance service.

What the assistant (`rule_based_journal_review`) weighs:
- **Reject:**
  - a journal straight to equity;
  - a duplicate of a journal posted in the 30 days before;
  - one dated more than 31 days back, or into a closed month;
  - a round cash amount with a description under 20 characters;
  - a material journal (US$100,000 or more) with a description under 40 characters.
- **Refer on:** a material journal with a full description.
- **Post:** anything else, as routine.

Its **blind spot** is the preparer's week. The profile counts the preparer's other journals
on the same accounts in the last seven days, and their total, and the assistant never reads
them. So a large entry split into pieces, each just under materiality, looks like a run of
routine accruals, and it recommends posting.

What `journal-review` v1 measured (seed 2030, 300 journals, 12 staff, default assumptions;
one run each):

| | Baseline | AI assisted |
| --- | ---: | ---: |
| Accuracy | 87.0 % | 96.7 % |
| Wrongly posted | 20 | 7 |
| Wrongly rejected | 19 | 3 |
| Split entries posted (of 45) | 6 | 6 |
| Approver hours | 101.7 | 64.7 |
| Median cycle time (hours) | 5.8 | 2.1 |
| Tool's recommendation accuracy | — | 84 % (27 referred on) |

**Where the assistant helps:**
- Routine accruals and reclassifications wrongly rejected fall from 17 to 1.
- Equity adjustments, stale and duplicate journals and unexplained cash are posted once in
  121 (14 times in the baseline).
- Approvers' time falls by more than a third.

**Where it does not:**
- It recommends posting all 45 split entries. In this run the simulated approvers posted 6
  either way: following the advice made the blind spot no worse, but no better.
- A material, documented journal is referred on, which leaves approvers where the baseline
  was: 25 of 27 posted either way.

These results rest on the scenario's stated reviewer and AI-assistance assumptions, not on
measured behaviour.

## WF-1038 v2 and the complaint review assistant (Phase 52)

WF-1038 v2 is a stored workflow. After a complaint is opened and acknowledged and its
redress proposed, it reads the complaint profile (`service.complaint_profile`) and asks the
assistant through `ai.review`. A complaints manager (`service:approve`) then approves paying
the redress, which upholds the complaint, or refuses it. A manager always decides, so the
scenario runs baseline and AI assisted only.

Each case's customer has a US-dollar account. Its fees are charged through the real accounts
service, dated in the last 90 days, and any earlier complaints are opened, refunded and
upheld through the real customer service.

What the assistant (`rule_based_complaint_review`) weighs:
- **Fee complaints:**
  - reject when no fee was charged in 90 days;
  - reject when the redress is more than 150 % of the fees charged;
  - otherwise uphold, as a refund (a fee charged twice is called out).
- **Goodwill:**
  - uphold up to US$50;
  - refer on up to US$250;
  - reject above that.

Its **blind spot** is the customer's history. The profile counts the customer's complaints
in the last year, how many were upheld and the redress already paid, and the assistant never
reads them. So a customer who disputes every fee and is refunded every time looks like a fair
refund, and it recommends paying.

What `complaint-redress` v1 measured (seed 2030, 300 complaints, 12 staff, default
assumptions; one run each):

| | Baseline | AI assisted |
| --- | ---: | ---: |
| Accuracy | 87.0 % | 95.0 % |
| Wrongly upheld | 19 | 9 |
| Wrongly refused | 20 | 6 |
| Repeat complainants refunded (of 64) | 8 | 9 |
| Manager hours | 101.7 | 64.1 |
| Median cycle time (hours) | 6.3 | 2.5 |
| Tool's recommendation accuracy | — | 77 % (22 referred on) |

**Where the assistant helps:**
- Fair refunds and small goodwill wrongly refused fall from 16 to 2.
- Complaints with no fee charged, redress far above the loss and large goodwill are never
  upheld (11 of 89 in the baseline).
- Managers' time falls by more than a third.

**Where it does not:**
- It recommends refunding all 64 repeat complainants. The simulated managers, following it,
  refund 9 rather than 8.
- A moderate goodwill payment is referred on, which leaves managers where the baseline was:
  18 of 22 upheld either way.

These results rest on the scenario's stated reviewer and AI-assistance assumptions, not on
measured behaviour.

## WF-1040 v2 and the collections review assistant (Phase 54)

WF-1040 v2 is a stored workflow. After a payment plan is proposed for a loan in arrears, it
reads the plan profile (`collections.plan_profile`) and asks the assistant through
`ai.review`. A collections manager (`loans:approve`, someone other than the proposer) then
activates or rejects the plan. A manager always decides, so the scenario runs baseline and AI
assisted only.

Each case's borrower is built through the real services:
- a US-dollar loan, disbursed 65 to 110 days before and spent;
- salary paid in and spent at past dates, or nothing paid in for 90 days;
- the loan serviced on its own, so its instalments fall into arrears without touching any
  other loan or starting a WF-0004 case;
- for some borrowers, an earlier plan on the loan, proposed, approved and broken.

The plan itself is proposed by the workflow.

What the assistant (`rule_based_plan_review`) weighs, from the monthly commitment while the
plan runs (the regular instalment plus the catch-up payments) against the money paid in over
the 90 days before:
- **Reject:** nothing paid in for 90 days, or nothing for more than 60 days, or a commitment
  above 70 % of the monthly income.
- **Refer on:** a commitment of 45 % to 70 % of the income.
- **Activate:** anything else, as affordable.

Its **blind spot** is the borrower's history. The profile counts the borrower's earlier
payment plans and how many they broke, and the assistant never reads them. So a borrower who
broke a plan before looks like any other affordable plan, and it recommends activating.

What `payment-plans` v1 measured (seed 2030, 300 plans, 12 staff, default assumptions; one
run each):

| | Baseline | AI assisted |
| --- | ---: | ---: |
| Accuracy | 82.0 % | 92.7 % |
| Wrongly activated | 32 | 17 |
| Wrongly rejected | 22 | 5 |
| Plans for borrowers who broke one before activated (of 61) | 14 | 17 |
| Manager hours | 98.2 | 64.6 |
| Median cycle time (hours) | 6.2 | 2.7 |
| Tool's recommendation accuracy | — | 76 % (45 referred on) |

**Where the assistant helps:**
- Affordable plans wrongly rejected fall from 17 to 0.
- Plans for borrowers with no income, or who cannot afford them, are never activated (18 of
  87 in the baseline).
- Managers' time falls by about a third.

**Where it does not:**
- It recommends activating all 61 plans for borrowers who broke one before. The simulated
  managers, following it, activate 17 rather than 14: here the blind spot makes outcomes
  worse.
- A stretched plan is referred on, which leaves managers where the baseline was: 40 of 45
  activated either way.

These results rest on the scenario's stated reviewer and AI-assistance assumptions, not on
measured behaviour.

## WF-1044 v2 and the leave review assistant (Phase 56)

WF-1044 v2 is a stored workflow. After leave is requested, it reads the leave profile
(`hr.leave_profile`) and asks the assistant through `ai.review`. A department manager
(`hr:manage`, someone other than the requester) then approves or rejects the leave. A
manager always decides, so the scenario runs baseline and AI assisted only.

Each case has its own five-person US department, created for it. The colleagues' leave
that sets the department's cover, and the employee's earlier short-notice days off, are
requested and approved through the real HR service.

What the assistant (`rule_based_leave_review`) weighs:
- **Reject:**
  - the department's cover on the leave's working days, with the others already away,
    below 60 %;
  - five days or more of annual leave asked for less than a week ahead.
- **Refer on:** cover of 60 % to 70 %, or more than five days off sick.
- **Approve:** anything else, as routine.

Its **blind spot** is the employee's history. The profile counts their other requests in
the 90 days before and how many came at short notice, and the assistant never reads them.
So someone who keeps asking for a day or two off at the last minute looks like any short
request, and it recommends approving.

What `leave-requests` v1 measured (seed 2030, 300 requests, 12 staff, default assumptions;
one run each):

| | Baseline | AI assisted |
| --- | ---: | ---: |
| Accuracy | 82.0 % | 94.7 % |
| Wrongly approved | 29 | 11 |
| Wrongly rejected | 25 | 5 |
| Serial short-notice requests approved (of 51) | 10 | 10 |
| Manager hours | 98.2 | 62.0 |
| Median cycle time (hours) | 5.7 | 2.2 |
| Tool's recommendation accuracy | — | 81 % (28 referred on) |

**Where the assistant helps:**
- Routine, planned, sick and short leave wrongly rejected falls from 20 to 0.
- Under-covered leave and long leave at short notice are approved once in 79 (19 times in
  the baseline).
- Managers' time falls by more than a third.

**Where it does not:**
- It recommends approving all 51 serial short-notice requests. In this run the simulated
  managers approved 10 either way: the blind spot made outcomes no worse, but no better.
- Tight cover is referred on, which leaves managers where the baseline was: 23 of 28
  approved either way.

These results rest on the scenario's stated reviewer and AI-assistance assumptions, not on
measured behaviour.

## WF-1048 v2 and the invoice review assistant (Phase 58)

WF-1048 v2 is a stored workflow. After a vendor's invoice is recorded and matched, it reads
the invoice profile (`procurement.invoice_profile`) and asks the assistant through
`ai.review`. A department manager (`procurement:approve`, someone other than whoever
recorded the invoice) then releases the payment or rejects the invoice. Held invoices end
before the review. A manager always decides, so the scenario runs baseline and AI assisted
only.

Each case has its own approved US vendor and a received purchase order. The history the
case needs is booked through the real procurement service:
- a bank-detail change, verified by a second person;
- earlier invoices paid to the vendor.

What the assistant (`rule_based_invoice_review`) weighs:
- **Reject:**
  - the vendor's bank account changed less than 30 days ago, and nothing has been paid to
    it since;
  - the invoice is dated before its order was raised.
- **Refer on:**
  - the invoiced total runs over what was received, within the 2 % tolerance;
  - US$10,000 or more from a vendor registered less than 30 days ago;
  - a high-risk vendor.
- **Approve:** anything else, as routine.

Its **blind spot** is the vendor's history. The profile counts the vendor's other invoices
in the 90 days before and how many were for the same amount, and the assistant never reads
them. So the same bill sent again under a new reference looks like any routine invoice, and
it recommends paying.

What `invoice-payments` v1 measured (seed 2030, 300 invoices, 12 staff, default
assumptions; one run each):

| | Baseline | AI assisted |
| --- | ---: | ---: |
| Accuracy | 82.0 % | 95.0 % |
| Wrongly paid | 23 | 11 |
| Wrongly rejected | 31 | 4 |
| Near-duplicate invoices paid (of 48) | 10 | 11 |
| Manager hours | 73.6 | 47.6 |
| Median cycle time (hours) | 3.8 | 1.1 |
| Tool's recommendation accuracy | — | 82 % (32 referred on) |

**Where the assistant helps:**
- Routine invoices, partial deliveries, old bank changes and small first invoices wrongly
  rejected fall from 28 to 1.
- Invoices to a newly changed bank account, and invoices dated before their order, are
  paid 0 times in 72 (13 times in the baseline).
- Managers' time falls by more than a third.

**Where it does not:**
- It recommends paying all 48 near-duplicates. The simulated managers paid 10 of them in
  the baseline and 11 with the assistant: the blind spot made outcomes no better, and one
  more duplicate was paid.
- Invoices within the tolerance are referred on, which leaves managers where the baseline
  was: 29 of 32 paid either way.

These results rest on the scenario's stated reviewer and AI-assistance assumptions, not on
measured behaviour.

## WF-1050 v2 and the change review assistant (Phase 60)

WF-1050 v2 is a stored workflow. After a normal change is raised, it reads the change
profile (`itops.change_profile`) and asks the assistant through `ai.review`. A department
manager (`itops:approve`, someone other than the requester) then approves or rejects the
change. Standard changes are pre-approved and skip the review. A manager always decides,
so the scenario runs baseline and AI assisted only.

Each case has its own tier-2 or tier-3 application. The history the case needs is booked
through the real IT operations service, dated against the scenario's simulated day:
- earlier changes, some of which failed, with the incidents they opened resolved and
  closed;
- an incident still open.

What the assistant (`rule_based_change_review`) weighs:
- **Reject:**
  - no backout plan;
  - a P1 or P2 still open on the application;
  - a window in business hours (08:00 to 18:00 UTC on a weekday) on a tier-1 or tier-2
    application.
- **Refer on:** a change raised less than a day ahead, or a window over 8 hours.
- **Approve:** anything else, as routine.

Its **blind spot** is history. The profile counts the failed changes to the application, and
by the requester, in the 90 days before, and the assistant never reads them. So another
change to an application whose last changes kept failing looks like any routine change, and
it recommends approving.

What `change-approvals` v1 measured (seed 2030, 300 changes, 12 staff, default assumptions;
one run each):

| | Baseline | AI assisted |
| --- | ---: | ---: |
| Accuracy | 82.0 % | 93.3 % |
| Wrongly approved | 24 | 9 |
| Wrongly rejected | 30 | 11 |
| Changes after repeated failures approved (of 56) | 9 | 9 |
| Manager hours | 98.2 | 62.7 |
| Median cycle time (hours) | 5.7 | 2.0 |
| Tool's recommendation accuracy | — | 80 % (26 referred on) |

**Where the assistant helps:**
- Routine out-of-hours changes and daytime changes to tier-3 applications wrongly rejected
  fall from 21 to 2.
- Changes with no backout plan, during an open P2 or in business hours on a tier-2
  application are approved 0 times in 113 (15 times in the baseline).
- Managers' time falls by more than a third.

**Where it does not:**
- It recommends approving all 56 changes after repeated failures. The simulated managers
  approved 9 either way: the blind spot made outcomes no worse, but no better.
- Short-notice changes are referred on, which leaves managers where the baseline was: 17 of
  26 approved either way.

These results rest on the scenario's stated reviewer and AI-assistance assumptions, not on
measured behaviour.

