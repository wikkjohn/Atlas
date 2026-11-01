# Implementation status

Last updated: Phase 46.

| Phase | Name | Status |
| --- | --- | --- |
| 1 | Initialize the application | **Complete** |
| 2 | Shared enterprise foundation | **Complete** |
| 3 | First banking business modules | **Complete** |
| 4 | Workflow execution engine | **Complete** |
| 5 | Simulation engine | **Complete** |
| 6 | AI Innovation Lab | **Complete** |
| 7 | Benchmarking and experiment evaluation | **Complete** |
| 8 | Enterprise dashboard | **Complete** |
| — | End-to-end demonstration (Part 12) | **Complete** — [demo.md](demo.md), automated in Playwright |
| 9 | Additional business workflows: payments and lending | **Complete** |
| 10 | Loan servicing and collections | **Complete** |
| 11 | AI underwriting for personal loans | **Complete** |
| 12 | Scale foundation, step 1: stored balances and incremental reconciliation ([roadmap](roadmap.md) Milestone A) | **Complete** |
| 13 | Scale foundation, step 2: bulk loading, one million customers, search indexes | **Complete** |
| 14 | Scale foundation, step 3: durable background jobs, workers and schedules | **Complete** |
| 15 | Scale foundation, step 4: partitioned workflow history, simulation history archive/reset, observability | **Complete** |
| 16 | Scale foundation, step 5: sharded simulation runs, performance suite, 100,000 applications — roadmap Milestone A complete | **Complete** |
| 17 | Workflow factory, step 1: stored, versioned workflow definitions with an import API and full validation | **Complete** |
| 18 | Workflow factory, step 2: domain step-handler library with declared effects; money moves only behind an approval | **Complete** |
| 19 | Workflow factory, step 3: parameterised templates and a deterministic, versioned variant generator | **Complete** |
| 20 | Workflow factory, step 4: generated path tests for every stored and generated workflow, in CI | **Complete** |
| 21 | Workflow factory, step 5: workflow diagram and an editor with live validation | **Complete** |
| 22 | Workflow factory, step 6: catalogue search, ownership, review lifecycle; the Milestone B exit run — roadmap Milestone B complete | **Complete** |
| 23 | Global footprint, step 1: reference data for 120 countries ([reference-data.md](reference-data.md)) | **Complete** |
| 24 | Global footprint, step 2: multi-currency — FX rates, conversions, cross-currency payments, revaluation ([fx.md](fx.md)) | **Complete** |
| 25 | Global footprint, step 3: country rules engine ([country-rules.md](country-rules.md)) | **Complete** |
| 26 | Global footprint, step 4: business calendars ([business-calendars.md](business-calendars.md)) | **Complete** |
| 27 | Global footprint, step 5: generated country subsidiaries ([subsidiaries.md](subsidiaries.md)) | **Complete** |
| 28 | Global footprint, step 6: the 120-country sweep ([country-sweep.md](country-sweep.md)) — roadmap Milestone C complete | **Complete** |
| 29 | Departments, step 1: retail banking ([retail-banking.md](retail-banking.md)) | **Complete** |
| 30 | Departments, step 2: the retail workload and AI tool ([ai-testing.md](ai-testing.md)) | **Complete** |
| 31 | Departments, step 3: cards ([cards.md](cards.md)) | **Complete** |
| 32 | Departments, step 4: the cards workload and AI tool ([ai-testing.md](ai-testing.md)) | **Complete** |
| 33 | Departments, step 5: mortgages and secured lending ([mortgages.md](mortgages.md)) | **Complete** |
| 34 | Departments, step 6: the mortgages workload and AI tool ([ai-testing.md](ai-testing.md)) | **Complete** |
| 35 | Departments, step 7: SME and commercial lending ([commercial-lending.md](commercial-lending.md)) | **Complete** |
| 36 | Departments, step 8: the commercial lending workload and AI tool ([ai-testing.md](ai-testing.md)) | **Complete** |
| 37 | Departments, step 9: trade finance ([trade-finance.md](trade-finance.md)) | **Complete** |
| 38 | Departments, step 10: the trade finance workload and AI tool ([ai-testing.md](ai-testing.md)) | **Complete** |
| 39 | Departments, step 11: treasury and markets ([treasury.md](treasury.md)) | **Complete** |
| 40 | Departments, step 12: the treasury workload and AI tool ([ai-testing.md](ai-testing.md)) | **Complete** |
| 41 | Departments, step 13: payments operations ([payments-operations.md](payments-operations.md)) | **Complete** |
| 42 | Departments, step 14: the payments operations workload and AI tool ([ai-testing.md](ai-testing.md)) | **Complete** |
| 43 | Departments, step 15: wealth and investments ([wealth.md](wealth.md)) | **Complete** |
| 44 | Departments, step 16: the wealth workload and AI tool ([ai-testing.md](ai-testing.md)) | **Complete** |
| 45 | Departments, step 17: compliance ([compliance.md](compliance.md)) | **Complete** |
| 46 | Departments, step 18: the compliance workload and AI tool ([ai-testing.md](ai-testing.md)) | **Complete** |

## Phase 46: what exists

- **`compliance.alert_profile`:** what an officer weighs before closing an alert's case.
  - The rule and score, and the amount against the threshold.
  - The customer's type and risk rating.
  - The window's money in against the account's own baseline (the average month of the 90
    days before the window).
  - The customer's earlier alerts in the last year and reports filed.

  It is also a library handler.
- **AGB Alert Review Assistant** (`rule_based_alert_review`, `recommend_decision` only,
  compatible with WF-1027, needs `compliance:read`), with a deliberate blind spot: it never
  reads the customer's earlier alerts. The seed registers it, and the AI Lab console has a
  sample.
- **WF-1027 v2:** alert profile and AI review before the second officer decides; the outcome
  reads as the sign-off (closed: approved, escalated: rejected).
- **Workload `alert_triage` and scenario `alert-triage` v1:**
  - Accounts in the run's countries with four months of dated activity (deposits and
    withdrawals accept an effective date), and alerts raised by real monitoring runs.
  - Eight kinds with ground truth, decided by simulated compliance officers.
  - A control check covers four-eyes, `compliance:monitor` and no closure without the
    sign-off.
- **Fixes from the Codex review of PR #36 (Phase 45):**
  - A monitoring rerun no longer fails with a unique-constraint error after an alert of the
    same window was resolved; that window raises nothing again.
  - While a customer's case has a drafted report, their new alerts wait until it is filed,
    instead of being escalated by a report that does not cover them.
  - Compliance workflows need compliance permissions through the API: `compliance:monitor`
    to start, `compliance:read` to list, view or signal executions, declared by their
    library handlers. Compliance officers gained `workflows:start`.
  - Opening a case locks the customer first, so concurrent investigations of one customer's
    alerts cannot deadlock.
- **Measured** (300 alerts): AI assisted 95.7 % accurate against 87.0 %, officers' hours 79
  against 127. Repeat offenders' cases closed rose to 10 from 8, the one kind it made worse.

## Phase 46: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 644 passed (new: 4 — the alert rules and their blind spot; the alert profile against the baseline with an earlier alert; baseline and AI-assisted alert runs with every case decided by a second officer, no control violations, every kind's advice as designed; a rerun after a resolved alert, a new alert waiting for a drafted report, and compliance workflow access through the API (PR #36 review)) |
| Generated workflow tests | 39 workflows, 736 cases, 0 failed (WF-1027 v2: 17 cases, 100 % steps and routes) |
| Frontend Vitest / typecheck / build | 130 passed / clean / built |
| Playwright on a fresh database | 49 passed (new: the alert assistant in the AI Lab console, recommending closing a repeat offender's case), after the fix below |
| Measurement | `alert-triage`, seed 2030, 300 alerts each: baseline 87.0 % accurate (22 wrongly closed, 17 wrongly escalated, 127.1 officer hours, median cycle 6.9 h); AI assisted 95.7 % (11, 2, 79.2 h, 2.9 h); repeat offenders closed 8 against 10 of 43; the assistant's own advice 85 % accurate, 20 referred on |

Found while building it:
- **First workload run:** it failed with "Object of type Decimal is not JSON serializable":
  the profile's baseline was a database sum (a Decimal), which the workflow context cannot
  store. It is now converted to an integer. The profile test had passed because a Decimal
  compares equal to an integer.
- **Playwright, first run:** the new AI Lab test failed with "Your role cannot use this
  tool": the assistant needs `compliance:read`, which AI researchers do not have. The test
  now signs in as the administrator; the second run passed (49 of 49).
- **Review-fix test, first version:** it opened a second current account for one customer,
  which the accounts rules refuse; it now uses a savings account. Compliance officers could
  not start workflows at all (no `workflows:start`), which the test also exposed.
- **Review-fix test:** it fails on the code before the fixes (a unique-constraint error on
  the rerun) and passes after. There is no concurrency test for the customer lock.

## Phase 46: known limitations

- **The assistant is rule-based** and blind to the customer's earlier alerts, by design.
- **Simulation scope:** only alert triage is simulated.
- **Access is declared per handler:** a stored workflow is restricted only if it uses a
  restricted handler; the approval inbox is governed by the approval's permissions.

## Phase 45: what exists

- **Compliance module** (`app/modules/compliance/`, migration 0033).
- **Transaction monitoring** over customer accounts' ledger activity in a window, with four
  rules against a US$10,000 reporting threshold converted per currency: a large cash
  deposit, structuring (three or more deposits of 80–100 % of it within ten days), rapid
  movement of funds, and high turnover by a high-risk customer. An account gets no second
  open alert for a rule.
- **Alerts and cases:** alerts are dismissed or investigated in a case taking in all the
  customer's open alerts (one case under way per customer). A case is closed with no action
  by someone other than the investigator (also a database constraint), or escalated.
- **Suspicious activity reports:** drafted from the case's alerts and filed with a
  synthetic FIU by a second officer (also a database constraint). Filing records the
  reference, marks the alerts escalated and rates the customer high risk.
- **Periodic KYC reviews:** due every 1, 2 or 3 years for high, medium and low risk, from the
  last review or joining; scheduled within a horizon or opened on demand (one due per
  customer); completing one confirms, raises or lowers the rating.
- **Permissions** `compliance:read` (compliance officers and auditors), `compliance:monitor`
  and `compliance:file` (compliance officers).
- **Workflow factory:** eight `compliance.*` handlers and three workflows:
  - WF-1027 AML Alert Investigation
  - WF-1028 Suspicious Activity Report Filing
  - WF-1029 Periodic KYC Review

  Fixture kinds `aml_alert.alert_number` and `compliance_case.case_number`.
- **Compliance page:** monitoring runs, alerts with an account filter and paging, cases and
  reports, and KYC reviews.
- **Fixes from the Codex review of PR #35 (Phase 44):**
  - The order profile prices the order on the day it is read, not at placement.
  - Approving or rejecting a buy checks its suitability again; an order that has become
    unsuitable is recorded as decided against advice, so it counts in the customer's 90-day
    record.
  - The `order-review` measurement was re-run after the fixes and is unchanged.

## Phase 45: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 640 passed (new: 6 — the four monitoring rules; a run raising structuring and rapid-movement alerts once, and none for an ordinary account; a case taking in a customer's alerts, four-eyes on closing and filing, a filed report rating the customer high risk, an alert dismissed and a case closed with no action; KYC reviews falling due by rating and completed with a lowered rating; the API with its permissions and account filter; the order profile priced on the day and a newly unsuitable decision counted (PR #35 review)) |
| Migration 0033 | upgrade, `alembic check` clean, downgrade and upgrade again |
| Generated workflow tests | 39 workflows, 734 cases, 0 failed (WF-1027: 15 cases, WF-1028: 11, WF-1029: 11; each 100 % steps and routes) |
| Frontend Vitest / typecheck / build | 130 passed (new: 5 — runs, alerts, cases, reports and reviews; running monitoring, investigating, escalating, filing and completing a review; paging back through alerts; filtering alerts by account; read-only without the permissions) / clean / built |
| Playwright on a fresh database | 48 passed (new: structuring deposits detected by a monitoring run, investigated, escalated, refused filing by the preparer and filed by a second officer), after the fix below |

Found while building it:
- **Workflow validation:** the first WF-1027 sent the second officer's approval to
  escalation and the refusal to closing; validation refused it, because closing a case
  (approval required) must be reached only through an approval's approve route. The
  approval now signs off closing with no action, and refusing it escalates.
- **Playwright, first run:** the new compliance test failed: a monitoring run on the seeded
  data raised 103 alerts (the population's opening balances are cash deposits), and the
  test's alert was beyond the first page. The alerts list gained an account filter (API and
  page), which the test now uses; the second run passed (48 of 48).
- **New backend tests and the compliance unit tests** passed on their first run.
- **Review-fix test:** the new test fails on the code before the fixes (the decided order
  stayed suitable) and passes after.

## Phase 45: known limitations

- **Simple rules,** one account at a time: no network analysis, peer groups or tuning.
- **On request only:** nothing runs monitoring or schedules reviews automatically, and a
  filed report restricts nothing.
- **A synthetic FIU:** filing records a reference; nothing is sent.
- **No simulation yet:** there is no compliance workload or AI tool yet (Phase 46).

## Phase 44: what exists

- **`wealth.order_profile`:** what a manager weighs before an unsuitable order goes ahead.
  - Why it is unsuitable, and the gap between the security's risk and the customer's
    profile.
  - The customer's answers, the order's share of their investable assets and the cash it
    leaves.
  - Whether they have held a security this risky before.
  - Their orders that went ahead against advice, and that were refused, in the last 90 days.

  It is also a library handler.
- **AGB Suitability Review Assistant** (`rule_based_suitability_review`,
  `recommend_decision` only, compatible with WF-1025), with a deliberate blind spot: it never
  reads the customer's record of insisting. The seed registers it, and the AI Lab console has
  a sample.
- **WF-1025 v2:** order profile and AI review before the manager decides an unsuitable order.
- **Workload `order_review` and scenario `order-review` v1:**
  - Customers in the run's countries, each with a profile, a portfolio and earlier orders
    built through the real wealth service.
  - Seven kinds with ground truth, decided by simulated wealth managers (`wealth:approve`).
  - A control check covers four-eyes, `wealth:approve`, no order executed without an
    approval and no unsuitable order released by the dealing desk.
- **Decision dates:** approving or rejecting an order records the workflow's (simulated)
  time, so the profile's 90-day counts follow simulated dates.
- **Fixes from the Codex review of PR #34 (Phase 43):**
  - Releasing a placed buy checks suitability again against today's holdings, prices and
    profile: two placed orders can no longer add up to an unsuitable position without a
    manager. A refused release leaves the order placed for a manager; WF-1025 v2 sends it to
    the manager, and the Wealth page offers managers Approve and Reject on placed orders.
  - Paying income is refused, before anything is recorded, while a holder's cash account is
    not open, instead of skipping that holder for good.
  - Placing an order locks the portfolio, so an order cannot be placed while it is being
    closed.
  - The order profile's reasons are worked out on the day it is read.
- **Measured** (300 orders): AI assisted 95.3 % accurate against 82.0 %, managers' hours 64
  against 98. Serial insisters let through rose to 7 from 6, the one kind it made worse.

## Phase 44: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 634 passed (new: 4 — the suitability rules and their blind spot; the order profile with experience, an order against advice and a refusal in the last 90 days; baseline and AI-assisted order runs with every order decided by a manager, no control violations, every kind's advice as designed; a placed buy checked again at release and income refused while a holder's account is frozen (PR #34 review)) |
| Generated workflow tests | 36 workflows, 697 cases, 0 failed (WF-1025 v2: 24 cases, 100 % steps and routes) |
| Frontend Vitest / typecheck / build | 125 passed (the wealth page test now also checks a manager's Approve on a placed order (PR #34 review)) / clean / built |
| Playwright on a fresh database | 47 passed on the first run (new: the suitability assistant in the AI Lab console, recommending a serial insister's order go ahead) |
| Measurement | `order-review`, seed 2030, 300 orders each: baseline 82.0 % accurate (25 wrongly let go ahead, 29 wrongly refused, 98.2 manager hours, median cycle 4.3 h); AI assisted 95.3 % (13, 1, 63.8, 1.5 h); serial insisters let through 6 against 7 of 42; the assistant's own advice 84 % accurate, 30 escalated |

Found while building it:
- **New tests:** the three new workload tests passed on their first run, and WF-1025 v2's
  generated tests passed on their first run.
- **Measurement** re-run after the review fixes: unchanged.
- **Income refusal, first version:** the regression test found that a refused payment left
  its distribution row in the session, because the check ran after the row was added. The
  service now checks every holder before recording anything.
- **Review-fix test:** the new test fails on the code before the fixes (release did not
  raise) and passes after. There is no concurrency test for the portfolio lock.

## Phase 44: known limitations

- **The assistant is rule-based** and blind to the customer's record of insisting, by design.
- **Simulation scope.** Only unsuitable orders are simulated; assessments, suitable orders
  and income are not.
- **Earlier orders' dates.** An order's `created_at` is the real time it was entered; only
  its decision date follows the simulation.

## Phase 43: what exists

- **Wealth module** (`app/modules/wealth/`, migration 0032).
  - Ten synthetic securities (money market, bonds, funds, equities, two complex structured
    products), risk levels 1–7, with deterministic daily prices.
  - Prices converted to a portfolio's currency at the day's mid rates.
- **Suitability:** a questionnaire (objective, horizon, knowledge, capacity for loss) gives
  a risk profile from 1 to 7, valid for a year; the customer's KYC must be verified.
- **Portfolios in custody** on one of the customer's accounts: holdings at average cost, off
  the balance sheet; valuation with gain on cost; closed only when empty. The cash account
  cannot be closed while its portfolio is open.
- **Orders:** whole units at the day's price, a 0.25 % fee (at least one major unit), cash
  covered without the overdraft.
  - A buy is unsuitable above the customer's risk profile, for a complex product without
    the knowledge, or above 40 % of investable assets.
  - Suitable orders execute at once (API); unsuitable ones wait for someone other than the
    adviser (`wealth:approve`, also a database constraint), who approves at the client's
    insistence or rejects.
  - In stored workflows a suitable order is placed and released by the dealing desk, so no
    workflow moves money before an approval.
- **Income:** half a year's income at the day's price to every holder, converted to each
  portfolio's currency; once per security and record date.
- **Permissions** `wealth:advise` (tellers and managers), `wealth:approve` and
  `wealth:custody` (managers).
- **Fixes from the Codex review of PR #33 (Phase 42):**
  - The recall profile identifies a beneficiary by bank and account, so the same number at
    another bank is neither a duplicate nor payee history; the workload now keeps one bank
    per beneficiary, so its genuine duplicates go to the same bank.
  - An unsettled duplicate candidate is dated by when it was entered, not by the recalled
    payment's settlement.
  - A clearing cycle can be limited to some payments; the recall workload and the generated
    tests' fixture clear only the payments they made, never other pending payments.
  - The recall workload builds its payers in the run's countries.
  - The `recall-triage` measurement was re-run after the fixes and is unchanged (seed 2030,
    300 recalls: 82.0 % against 94.0 %).
- **Workflow factory:** eight `wealth.*` handlers and three workflows:
  - WF-1024 Investment Suitability Assessment
  - WF-1025 Investment Order
  - WF-1026 Custody Income Distribution

  Fixture kinds `portfolio.portfolio_number` and `security.code`.
- **Wealth page:** securities, the suitability form, portfolios with valuation and paging,
  orders with approval and release and paging, and income payments.

## Phase 43: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 630 passed (new: 7 — the recall profile's beneficiary by bank and account, an unsettled candidate dated by entry, and a cycle limited to some payments (PR #33 review); recall cases built in the run's countries (PR #33 review); risk profiles, deterministic prices and the fee floor; suitable orders executed with the cash, fees, average cost and valuation checked, selling more than held and buying beyond the cash refused; unsuitable orders (risk, complex product, concentration) waiting for a second person, rejected or approved at the client's insistence, a placed order released with four-eyes, no buying without a current profile; income paid to a EUR bond's holder in USD once a day, account and portfolio closure refused while they hold anything; the API with its permissions) |
| Migration 0032 | upgrade, `alembic check` clean, downgrade and upgrade again |
| Generated workflow tests | 36 workflows, 695 cases, 0 failed (WF-1024: 10 cases, WF-1025: 22, WF-1026: 11; each 100 % steps and routes, after the fix below) |
| Frontend Vitest / typecheck / build | 125 passed (new: 4 — securities, portfolios with their valuation, orders with reasons and income; recording a profile, opening a portfolio, placing, approving and releasing orders and paying income; paging back through orders; read-only without the wealth permissions) / clean / built |
| Playwright on a fresh database | 46 passed on the first run (new: a teller assesses a customer (risk 3), opens a portfolio and buys a money-market fund, executed at once; a risk-7 complex tracker waits and the teller cannot approve it; a manager approves it at the client's insistence) |

Found while building it:
- **Generated tests, first run:** WF-1025 failed 13 of 15 cases with "'order' moved money
  without a granted approval". Placing an order executed a suitable one in the same step,
  and stored workflows must never move money before an approval. Fixed by placing the
  order in the workflow (`placed`) and adding a dealing-desk release step. One route then
  failed because the planner forces the "unsuitable" branch on a really suitable order; a
  manager's approval now also executes a placed order. All three workflows then passed at
  100 %.
- **Lint:** the formatter expanded the securities table, which is now kept compact with
  `# fmt: off`.
- **Review-fix tests:** the two new tests fail on the code before the fixes (the clearing
  test with a `TypeError`, since the `only` parameter did not exist; the countries test on
  the payments' currencies) and pass after.
- **Frontend unit test:** two assertions in the first version were wrong (a lookup before
  the rows arrived, and the capitalised asset class); the page was not changed.

## Phase 43: known limitations

- **Synthetic market.** Deterministic prices, no order book, spread or settlement cycle;
  orders settle the same day against the bank's cash, with no broker, custodian or FX
  position for the conversion.
- **Whole units only;** no limit orders, switches or savings plans.
- **Simplified suitability:** one questionnaire and three checks; no periodic review.
- **Income on request;** nothing pays it on a schedule, and there is no tax withholding.
- **No simulation yet.** There is no wealth workload or AI tool yet (Phase 44).

## Phase 42: what exists

- **`clearing.recall_profile`:** what back office weighs before sending a recall.
  - The reason, days since settlement, and the days of its window left.
  - The payment's size and whether it is high value.
  - Matching duplicates (same payer, beneficiary bank and account, and amount within three
    days).
  - How often the payer has paid the beneficiary before.
  - The payer's recalls in the last 90 days, and how many were refused.

  It is also a library handler.
- **AGB Recall Assistant** (`rule_based_recall_review`, `recommend_decision` only,
  compatible with WF-1023), with a deliberate blind spot: it never reads the payer's
  earlier recalls. The seed registers it, and the AI Lab console has a sample.
- **WF-1023 v2:** recall profile and AI review before back office approves.
- **Workload `recall_triage` and scenario `recall-triage` v1:**
  - Each case is a business whose payments, earlier payments and earlier recalls run
    through the real clearing service; a recall of one settled payment arrives on the day.
  - Six kinds with ground truth, decided by simulated back office (`payments:approve`).
  - A control check covers four-eyes, `payments:approve`, and no recall sent or answered
    without an approval.
- **Fixes from the Codex review of PR #32 (Phase 41):**
  - Settlement posts one entry per settled payment, so a batch whose total is above the
    ledger's 10^15 line limit still settles.
  - Submission locks the payers' accounts in id order, so two cycles cannot deadlock.
  - An account cannot be closed while one of its outgoing payments could still come back:
    not yet settled, settled within the last 10 days, or with an open recall.
  - The Payments Operations page pages through bulk files and recalls beyond the newest 25.
- **Measured** (300 recalls): AI assisted 94.0 % accurate against 82.0 %, review hours 48
  against 74. Serial recallers sent rose to 10 from 9, the one kind it made worse.

## Phase 42: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 623 passed (new: 4 — the recall rules and their payer blind spot; the recall profile with a keyed-twice duplicate, payee history and a refused earlier recall; baseline and AI-assisted recall runs with every case decided by back office, no control violations, every kind's advice as designed, recalls sent and answered only after approval; a batch above the ledger line limit settling, and closure refused while a payment could come back (PR #32 review)) |
| Generated workflow tests | 33 workflows, 652 cases, 0 failed (WF-1023 v2: 21 cases, 100 % steps and routes) |
| Frontend Vitest / typecheck / build | 121 passed (new: paging back through bulk files and recalls (PR #32 review)) / clean / built |
| Playwright on a fresh database | 45 passed on the first run (new: the recall assistant in the AI Lab console, recommending sending a recall) |
| Measurement | `recall-triage`, seed 2030, 300 recalls each: baseline 82.0 % accurate (31 wrongly sent, 23 wrongly withdrawn, 73.6 review hours, median cycle 2.8 h); AI assisted 94.0 % (16, 2, 48.2, 0.5 h); serial recallers sent 9 against 10 of 52; the assistant's own advice 80 % accurate, 37 escalated |

Found while building it:
- **Lint:** ruff flagged closures defined inside the case loop (B023); case set-up moved into
  a method.
- **Review-fix tests:** the first version of the closure test settled its payments on a
  fixed test date, more than 10 days before the real date the closure check uses, so it did
  not raise; it now settles on the real date. Both review-fix tests (backend and frontend)
  fail on the code before the fixes and pass after. There is no concurrency test for the
  lock order.

## Phase 42: known limitations

- **The assistant is rule-based** and blind to the payer's recall history, by design.
- **Simulation scope.** Only recall triage is simulated; outgoing payments, clearing cycles
  and bulk files are not.
- **Closure check uses the real date.** The refundable-payment check reads today's date, not
  a simulated business date.
- **No automation.** Nothing runs clearing cycles or answers recalls automatically.

## Phase 41: what exists

- **Payments operations module** (`app/modules/clearing/`, migration 0031).
  - Outgoing payments to six synthetic banks.
  - 14-digit beneficiary accounts with mod-97 check digits.
  - The payer's country payment limits.
  - High-value payments approved by someone else (also a database constraint).
- **Clearing cycles** by currency:
  - Pending payments go into a batch, and each payer is debited into clearing suspense.
  - A payer who can no longer pay is rejected (AM04).
  - Settlement pays out of the bank's cash, or returns payments to closed accounts to the
    payer (AC04).
- **Bulk payment files:** 1–500 lines from one account, each validated with its error
  kept. The valid lines must be within the funds, and the file is released with four-eyes;
  each valid line becomes a payment.
- **Recalls:** four reasons, one open recall per payment, approved with four-eyes.
  - A payment not yet cleared is cancelled.
  - A settled payment is sent to the beneficiary's bank, which returns the money within the
    reason's window (10, 5 or 3 days) or refuses.
- **Fixes from the Codex review of PR #31 (Phase 40):**
  - Treasury settlement locks are FOR NO KEY UPDATE, compatible with the key-share locks
    ledger postings take, so parallel simulation shards cannot deadlock on them.
  - The deal profile counts as duplicates only same-day deals with the same rate and
    maturity as well.
- **Permission** `payments:operate` (department managers) for clearing cycles and recall
  answers.
- **Workflow factory:** eleven `clearing.*` handlers and three workflows:
  - WF-1021 Outgoing External Payment
  - WF-1022 Bulk Payment File
  - WF-1023 Payment Recall

  Fixture kind `outgoing_payment.payment_number`.
- **Payments Operations page:** outgoing payments with approvals and paging, clearing cycles
  and batches, bulk files with their line errors, and recalls with approval and answers.

## Phase 41: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 619 passed (new: 6 — outgoing payments validated with four-eyes for high value; a clearing cycle settling, returning (AC04) and rejecting (AM04) with the ledger checked; a bulk file with an invalid line, refused when over the funds, released with four-eyes; recalls cancelled before clearing, returned in the window, refused after it; the API with its permissions; the treasury lock mode and duplicate terms (PR #31 review)) |
| Migration 0031 | upgrade, `alembic check` clean, downgrade and upgrade again |
| Generated workflow tests | 33 workflows, 650 cases, 0 failed (WF-1021: 13 cases, WF-1022: 11, WF-1023: 19; each 100 % steps and routes, on their first run) |
| Frontend Vitest / typecheck / build | 120 passed (new: 3 — payments, returns, batches, bulk errors and recalls; sending a JPY payment in yen, approving, running a cycle, a bulk file in major units, recalls approved and answered; read-only without the permissions) / clean / built |
| Playwright on a fresh database | 44 passed on the first run (new: a teller pays another bank and cannot run clearing; a manager runs the cycle and it settles; the teller asks for it back and cannot approve; the manager approves and records the answer, and the payment is recalled) |

Found while building it:
- **New backend tests:** four tests failed on the first run because their payments of
  1,000,000 minor units were at the default high-value threshold (10,000 major units), so
  they waited for approval. The test amounts were scaled down; the service was not changed.
- **Lint:** the formatter wrapped the autogenerated migration, and a handful of lines were
  shortened by hand.
- **Review-fix test:** the new test (lock mode, duplicate terms) fails on the code before
  the fixes and passes after. There is still no concurrency test.

## Phase 41: known limitations

- **One simulated clearing system.** No message formats, cut-off times, nostro accounts or
  incoming payments.
- **Rule-based beneficiary banks.** Closed accounts and recall windows are rules, and the
  banks never fail or delay.
- **No automation.** Nothing runs clearing cycles or answers recalls automatically.
- **No screening.** Outgoing payments are not screened against the sanctions lists.
- **No simulation yet.** There is no payments operations workload or AI tool yet (Phase 42).

## Phase 40: what exists

- **`treasury.deal_profile`:** what back office checks before confirming a booked deal.
  - The rate against the currency's synthetic reference rate, with the deviation counted
    against the bank.
  - The tenor, and the counterparty's rating and limit use.
  - Liquidity coverage after a placement.
  - Same-day deals with the same terms.

  It is also a library handler.
- **AGB Back-Office Check Assistant** (`rule_based_back_office_check`,
  `recommend_decision` only, compatible with WF-1018), with a deliberate blind spot for
  same-day duplicates. The seed registers it, and the AI Lab console has a sample.
- **WF-1018 v2:** deal profile and AI review before back office decides; counterparty codes
  may contain digits.
- **Workload `deal_confirmations` and scenario `deal-confirmations` v1:**
  - Placements and borrowings booked through the real service, each case with its own
    synthetic counterparty, and each placement funded by a deposit.
  - Six kinds with ground truth, decided by simulated back office (`treasury:confirm`).
  - A control check covers four-eyes, `treasury:confirm`, and no settlement without
    confirmation.
- **Fixes from the Codex review of PR #30 (Phase 39):**
  - Treasury settlements lock the cash and FX position accounts they check, in id order,
    so concurrent confirmations cannot both pass against the same balance.
  - An FX desk trade's bought side may only close a short (US dollars excepted), so a
    square-off cannot open or grow a position in another currency.
  - The Treasury page pages through deals and FX trades beyond the newest 25.
  - Maturity posts principal and interest on separate cash lines, so a US$100m LBP deal at
    50 % no longer exceeds the ledger's 10^15 line limit.
- **Measured** (300 deals): AI assisted 91.3 % accurate against 83.3 %, back-office hours
  64 against 99. Duplicates confirmed rose to 18 from 14, the one kind it made worse.

## Phase 40: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 613 passed (new: 4 — the back-office rules and their duplicate blind spot; the deal profile with an off-market same-day duplicate; baseline and AI-assisted deal runs with every case decided by back office, no control violations, every kind's advice as designed, settlement only after confirmation; the bought side squaring only and a US$100m LBP deal maturing within the ledger line limit (PR #30 review)) |
| Generated workflow tests | 30 workflows, 607 cases, 0 failed (WF-1018 v2: 15 cases, 100 % steps and routes) |
| Frontend Vitest / typecheck / build | 117 passed (new: paging back through deals and FX trades (PR #30 review)) / clean / built |
| Playwright on a fresh database | 43 passed on the first run (new: the back-office check assistant in the AI Lab console, recommending confirmation of a same-day duplicate) |
| Measurement | `deal-confirmations`, seed 2030, 300 deals each: baseline 83.3 % accurate (33 wrongly confirmed, 17 wrongly cancelled, 98.7 back-office hours); AI assisted 91.3 % (25, 1, 63.6); duplicates confirmed 14 against 18 |

Found while building it:
- **New tests:** they passed on their first run.
- **Review-fix test:** the new test (bought side, maturity line split) fails on the code
  before the fixes and passes after. There is no concurrency test for the locks.
- **Measurements:** both runs were repeated after the review fixes and were identical.
- **Lint:** the formatter wrapped over-long lines in the new tests and the adapter. The
  format check now runs in the foreground before the suite, after PR #30's CI failure.

## Phase 40: known limitations

- **Workload scope:** it covers deal confirmations only. Maturities and the FX desk are not
  simulated.
- **AI modes:** WF-1018 v2 has no automated decision, so AI assisted is the only AI mode.
- **Unexercised rule:** the assistant's thin-coverage rule never fires, because the
  workload funds each placement.
- **Reference rates:** synthetic constants, not a curve.
- **Assumptions:** back office's response to the assistant rests on stated assumptions.

## Phase 39: what exists

- **Treasury module** (`app/modules/treasury/`, migration 0030).
  - Eight synthetic counterparty banks with ratings and placement limits, seeded by
    `seed-demo`.
  - Interbank placements and borrowings, value today, 1–365 days, US$100,000 to 100m
    converted per currency, fixed rates with ACT/360 or ACT/365 interest.
- **Rules:** placements only with investment-grade counterparties, within their limits
  (checked at booking and again at confirmation, with the counterparty locked).
- **Four-eyes:** a dealer books; back office, someone else, confirms (also database
  constraints).
- **Ledger:** confirmation settles against the bank's cash account; maturity settles
  principal and interest income or expense.
- **Liquidity:** 30-day coverage by currency: cash and placements coming back, against
  borrowings due and a 10 % run-off of customer deposits. A placement may not take a
  currency below 100 %.
- **FX desk:**
  - Net open position limits by currency (default US$1m).
  - Interbank spot trades at the mid rate that may only reduce a long position.
  - Settlement through the cash and FX position accounts, with four-eyes.
- **Permissions:**
  - `treasury:deal`: tellers and department managers.
  - `treasury:confirm`: department managers.
  - `treasury:limits`: regional and global executives.
- **Workflow factory:** nine `treasury.*` handlers and three workflows:
  - WF-1018 Interbank Money-Market Deal
  - WF-1019 Money-Market Deal Maturity
  - WF-1020 FX Position Square-off

  Fixture kinds `counterparty.code`, `treasury_deal.deal_number` and `fx_long.currency`.
- **Treasury page:** deals with booking, confirmation, cancellation and maturity;
  liquidity; FX desk positions and square-off trades; counterparties and limits.

## Phase 39: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 609 passed (new: 6 — booking rules (principal, tenor, rating, counterparty limit, cancelled deals freeing it); a placement settling and maturing with ACT/365 or ACT/360 interest and four-eyes on both; a placement refused for taking liquidity coverage to 50 % while the same amount for 30 days is allowed; a borrowing repaid with interest expense, refused while the cash is short; the FX desk squaring a EUR position over its limit with four-eyes; the API with its permissions) |
| Migration 0030 | upgrade, `alembic check` clean, downgrade and upgrade again |
| Generated workflow tests | 30 workflows, 605 cases, 0 failed (WF-1018: 13 cases, WF-1019: 11, WF-1020: 16; each 100 % steps and routes, on their first run) |
| Frontend Vitest / typecheck / build | 116 passed (new: 3 — deals, liquidity, positions and counterparties; booking a JPY borrowing in yen, confirming, settling a maturity, squaring a EUR position; read-only without the treasury permissions) / clean / built |
| Playwright on a fresh database | 42 passed on the first run (new: a dealer's placement with a BB+ bank is refused; the dealer books one with CP-NORTHGATE and cannot confirm it; back office confirms and it settles) |

Found while building it:
- **New backend tests:** one expectation in `test_treasury.py` assumed the test account
  was in GBP, so the limit check failed on the first run. The test now sets the limit
  from the measured exposure; the service was not changed.
- **Lint:** ruff flagged over-long lines in the autogenerated migration and the service.
- **CI format check:** the first CI run of PR #30 failed `ruff format --check` on one
  hand-wrapped call in `treasury/service.py`. The local run had printed the same failure,
  but the command carried on into pytest and it was missed. The fix is the formatter's
  output, with no code change.
- **Postgres** stopped once and was restarted.

## Phase 39: known limitations

- **Settlement:** deals settle against the bank's cash account. There are no nostros or
  settlement messages, and counterparties always pay.
- **Deals:** value today only. No forward-starting deals, rollovers, early termination,
  floating rates or repos.
- **Liquidity:** a simplified measure with a single run-off rate.
- **FX desk:** spot only; trades use no counterparty limit; the US-dollar position has no
  limit.
- **Automation:** nothing matures deals automatically.
- **Simulation:** no treasury workload or AI tool yet (Phase 40).

## Phase 38: what exists

- **`trade.presentation_profile`:** what a trade officer weighs before the applicant's
  waiver. It covers the discrepancy, the share of the credit drawn, days to expiry, how
  many times the applicant's funds (with the margin released) cover the payment, and the
  credit's earlier presentations, rejections and repeats of the same discrepancy. It is
  also a library handler.
- **AGB Document Check Assistant** (`rule_based_document_check`, `recommend_decision`
  only, compatible with WF-1016), with a deliberate blind spot for earlier rejections. The
  seed registers it, and the AI Lab console has a sample.
- **WF-1016 v2:** presentation profile and AI review before the applicant's waiver.
- **Workload `discrepant_presentations` and scenario `discrepant-presentations` v1:**
  - Businesses whose letters of credit are requested and issued through the real service;
    each presentation has one discrepancy.
  - Six kinds with ground truth, decided by simulated trade officers (`trade:manage`).
  - A control check covers four-eyes, `trade:manage`, and no payment without approval.
- **Fixes from the Codex review of PR #28 (Phase 37):**
  - An approval after the expiry date is refused, so no margin is taken for an instrument
    that can no longer be used.
  - A business account cannot be closed while it backs a requested or issued instrument,
    so a released margin cannot land in a closed account.
  - The Trade Finance page pages through instruments beyond the newest 25.
  - WF-1015 v2 and WF-1017 v2 (and WF-1016 v2) accept amounts up to 10^14 minor units,
    enough for US$5m in every supported currency. The committee's task in WF-1015 v2
    cannot be taken by the credit approver.
- **Refactor:** the verified-business helper the covenant workload used is now shared by
  both workloads.
- **Measured** (300 presentations): AI assisted 94.3 % accurate against 86.0 %, officer
  hours 101 against 156. Repeat discrepancies paid rose to 12 from 8, the one kind it made
  worse.

## Phase 38: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 603 passed (new: 4 — the document check rules and their history blind spot; the presentation profile with an earlier rejection of the same discrepancy; baseline and AI-assisted presentation runs with every case decided by a trade officer, no control violations, every kind's advice as designed, payments only after approval; an approval after expiry, closing an account behind a live instrument, and the workflows' amount ceilings and committee rule (PR #28 review)) |
| Generated workflow tests | 27 workflows, 565 cases, 0 failed, on a rebuilt database (WF-1015 v2: 23 cases, WF-1016 v2: 27, WF-1017 v2: 16; each 100 % steps and routes) |
| Frontend Vitest / typecheck / build | 113 passed (new: paging back to instruments beyond the newest 25 (PR #28 review)) / clean / built |
| Playwright on a fresh database | 41 passed on the first run (new: the document check assistant in the AI Lab console, recommending payment of a discrepancy the bank rejected before) |
| Measurement | `discrepant-presentations`, seed 2030, 300 presentations each: baseline 86.0 % accurate (24 wrongly paid, 18 wrongly rejected, 155.9 officer hours); AI assisted 94.3 % (15, 2, 101.0); repeat discrepancies paid 8 against 12 |

Found while building it:
- The new workload tests passed on their first run. Ruff flagged over-long lines.
- **The paging test failed on its first run.** The paging bar unmounted while the next page
  loaded, so the test held a stale element. The page now keeps the previous page visible
  while loading.
- **Review-fix test:** the new expiry and account-closure test fails on the code before the
  fixes and passes after.
- The measurements were repeated on the rebuilt database after WF-1016 v2's schema change;
  both runs were identical.
- The measured accuracy (94.3 %) and wrong decisions (15 and 2) are the same as the
  covenant scenario's. Both use the same reviewer and AI-assistance assumptions and a
  similar mix. The per-kind figures differ.

## Phase 38: known limitations

- The workload covers discrepant presentations only. Requests, complying documents and
  guarantee claims are not simulated.
- WF-1016 v2 has no automated decision: AI assisted is the only AI mode.
- The assistant's rule for inconsistent documents is not exercised by the workload.
- The officers' response to the assistant rests on stated assumptions.
- WF-1012 (commercial lending) has the same committee pattern as WF-1015 v1. It was not
  flagged and is not changed here.

## Phase 37: what exists

- **Trade finance module** (`app/modules/trade/`, migration 0029).
  - Letters of credit and bank guarantees for verified businesses, in the currency of
    their business current account.
  - Amounts of US$10,000 to 5m converted per currency; expiry 30 to 730 days ahead.
  - Beneficiaries screened against every synthetic sanctions list; a match refuses the
    request, and the result is kept on the instrument.
- **Approval:** four-eyes credit approval and, above US$1m, a third person on the credit
  committee (also database constraints). Issuing takes a cash margin, 20 % for a letter of
  credit and 10 % for a guarantee, into a margin liability account.
- **Demands:** documents under a letter of credit, with any of five discrepancies
  recorded, or a claim under a guarantee (no documents). One pending at a time, before
  expiry and within what is left.
- **Payment and rejection** by `trade:manage`, not by the receiver. A discrepant
  presentation is paid only as waived by the applicant. Payment releases the margin in
  proportion, debits the applicant and credits trade settlement. Expiry releases what is
  left of the margin.
- **Permission** `trade:manage` for department managers and compliance officers.
- **Fix from the Codex review of PR #27:** the property form's currency lookup compared
  customer numbers case-sensitively, so a lowercase number the server accepts was refused.
  The customer and account currency lookups now compare in upper case.
- **Workflow factory:** eight `trade.*` handlers and three workflows:
  - WF-1015 Trade Instrument Issuance
  - WF-1016 Documentary Presentation
  - WF-1017 Guarantee Claim

  Fixture kinds `letter_of_credit.instrument_number` and `guarantee.instrument_number`.
  The test business's account now holds 100,000,000, enough for a US$2m instrument's
  margin.
- **Trade Finance page:** requests, approvals, committee approvals, an instrument's
  margin and screening, presentations and claims, payment (*Pay (waived)* when
  discrepant), rejection and closing after expiry.

## Phase 37: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 599 passed (new: 5 — request rules and sanctions screening; issue with the margin, four-eyes and the committee, and a margin the account cannot provide; documents with a discrepancy paid as waived, proportional margin release and full drawing; a guarantee claim rejected, a late claim refused and expiry releasing the margin; the API with its permissions and a sanctioned beneficiary refused) |
| Migration 0029 | upgrade, `alembic check` clean, downgrade and upgrade again |
| Generated workflow tests | 27 workflows, 563 cases, 0 failed (WF-1015: 23 cases, WF-1016: 25, WF-1017: 16; each 100 % steps and routes) |
| Frontend Vitest / typecheck / build | 112 passed (new: 4 — a lowercase customer number still finds the customer's currency (PR #27 review); the instruments list and summary; a JPY request in yen, approval, committee approval, a discrepant presentation and *Pay (waived)*; read-only without the permissions) / clean / built |
| Playwright on a fresh database | 40 passed on the first run (new: a sanctioned beneficiary is refused; a teller requests a letter of credit and cannot approve it, a manager approves, the teller presents documents with a late shipment and cannot pay, the manager pays it as waived) |

Found while building it:
- **New backend tests:** two expectations in `test_trade.py` were wrong on the first run
  and were corrected; the service was not changed.
  - The account balance after a 40 % draw was miscalculated (6,400,000 instead of
    7,400,000).
  - The committee case expected the margin to be refused, but the test had funded the
    account well enough to cover it. The test now expects the issue and checks the
    refusal on a second US$2m request the remaining balance cannot cover.
- **Lint:** two over-long lines in the new test.

## Phase 37: known limitations

- Payments stop at a settlement account; nothing goes to the beneficiary's bank.
- Discrepancies are recorded by the checker, not found from documents; no amendments,
  transfers, confirmations or deferred-payment credits.
- No commissions or customer trade limits; nothing closes expired instruments
  automatically.
- No trade finance workload or AI tool yet (Phase 38).

## Phase 36: what exists

- **`commercial.breach_profile`:** what the credit committee reviews about a breached
  covenant test: ratios against thresholds, the EBITDA change over the last two periods,
  consecutive declines, utilisation, and earlier breaches and waivers. It is also a
  library handler.
- **AGB Covenant Breach Assistant** (`rule_based_covenant_review`, `recommend_decision`
  only, compatible with WF-1013), with a deliberate blind spot for earlier breaches. The
  seed registers it, and the AI Lab console has a sample.
- **WF-1013 v2:** breach profile and AI review before the committee.
- **Workload `covenant_breaches` and scenario `covenant-breaches` v1:**
  - Businesses whose two years of covenant history run through the real service; this
    year breaches.
  - Six kinds with ground truth, decided by simulated executives.
  - A control check covers four-eyes, `loans:approve_large`, and no waiver without
    approval.
- **Fixes from the Codex review of PR #25 (Phase 34):**
  - `mortgage_applications` caps applicants' income estimates at US$9,000 a month, so a
    generated loan can no longer exceed its product's maximum and stop the run.
  - `mortgages.application_profile` computes age from the workflow's date, not the offer
    row's creation time.
- **Fixes from the Codex review of PR #26 (Phase 35):**
  - A review can no longer raise a limit above US$1m without the committee.
  - Covenant compliance is decided exactly, not on truncated ratios.
  - A frozen business account cannot repay.
  - Reviews and covenant tests are locked before a decision.
  - The proposal form and the mortgage property form convert amounts in the account's or
    customer's own currency (JPY, KWD and others), not by a fixed ×100.
  - A terminated facility shows *Repay* on the page.
- **Measured** (300 breaches): AI assisted 94.3 % accurate against 84.3 %, committee hours
  124 against 193. Repeat breaches waived rose to 11 from 8, the one kind it made worse.

## Phase 36: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 594 passed (new: 5 — the assistant's rules and its history blind spot; the breach profile over three years with a waived breach; baseline and AI-assisted covenant runs with every case decided by the committee, no control violations, every kind's advice as designed, waivers only after approval; every mortgage kind within its product at its extreme draws (PR #25 review); leverage just over its limit, a frozen account's repayment and a review past the committee threshold (PR #26 review)) |
| Generated workflow tests | 24 workflows, 499 cases, 0 failed (WF-1013 v2: 19 cases, 100 % steps and routes) |
| Frontend Vitest / typecheck / build | 108 passed (new: a terminated facility offers Repay, not Draw; the proposal converts a JPY limit in yen) / clean / built |
| Playwright on a fresh database | 39 passed, both before and after the PR #26 fixes (new: the covenant breach assistant in the AI Lab console, recommending another waiver after a waived breach) |
| Measurement | `covenant-breaches`, seed 2030, 300 breaches each: baseline 84.3 % accurate (20 wrong waivers, 27 wrongly kept frozen, 192.8 committee hours); AI assisted 94.3 % (15, 2, 123.7); repeat breaches waived 8 against 11 |

Found while building it:
- **Breach-profile test:** two expectations in the new test were wrong on the first run.
  - An EBITDA change of −4.35 % came out as −435 basis points; the profile now rounds
    changes toward zero, so it reads −434.
  - The expected count of earlier breaches had left out the breach the test itself waived.
- **Codex review of PR #25** (Phase 34, merged before the review finished): its two
  findings were confirmed and fixed here. The mortgage extremes test fails with the old
  income ceiling and passes with the new one.
- **Ordering:** this phase ran the backend suite before Playwright, not alongside it.

## Phase 36: known limitations

- The commercial workload covers covenant breaches only; proposals and reviews are not
  simulated.
- WF-1013 v2 has no automated decision: AI assisted is the only AI mode.
- The assistant's advice and the committee's response to it rest on stated assumptions.
- The Phase 34 mortgage measurement was not rerun after the income cap; the cap changes
  which applicants are drawn, so its figures would differ somewhat.

## Phase 35: what exists

- **Commercial lending module** (`app/modules/commercial/`, migration 0028).
  - Term loans and revolving credit for verified businesses, drawn into their business
    current accounts.
  - Limits of US$50,000 to 5m converted per currency; fixed rates; default covenants.
- **Approval:** four-eyes credit approval and, above US$1m, a third person on the credit
  committee (also database constraints). Activation opens a ledger receivable and sets
  the review and maturity dates.
- **Drawdowns and repayments** through the ledger. Revolving credit redraws repaid
  amounts; a term loan does not. No drawdowns when frozen, terminated, overdue for
  review or matured.
- **Covenant tests:** DSCR and leverage on a year's figures, once per period. A breach
  freezes the facility until the committee (not the submitter) waives it.
- **Annual reviews:** opened from 60 days before the due date, one at a time, decided
  four-eyes. Renewal can change the limit; termination means repayments only.
- **Workflow factory:** ten `commercial.*` handlers and three workflows:
  - WF-1012 Commercial Facility Application
  - WF-1013 Covenant Compliance Test
  - WF-1014 Annual Facility Review

  Fixture kinds `business.customer_number`, `business.account_number` and
  `facility.facility_number`.
- **Commercial Lending page:** proposals, approvals, committee approvals, a facility's
  drawdowns, covenant figures and tests with waivers, and annual reviews.

## Phase 35: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 589 passed (new: 6 — proposal rules and four-eyes approval; committee approval above US$1m by a third person; drawdowns and repayments through the ledger, a term loan not redrawing, an overdue review blocking; a covenant breach freezing until the committee waives; reviews renewing with a new limit and terminating; the API with its permissions) |
| Migration 0028 | upgrade, `alembic check` clean, downgrade and upgrade again |
| Generated workflow tests | 24 workflows, 497 cases, 0 failed (WF-1012: 23 cases, WF-1013: 17, WF-1014: 16; each 100 % steps and routes) |
| Frontend Vitest / typecheck / build | 107 passed / clean / built |
| Playwright on a fresh database | 38 passed (new: a teller proposes, cannot approve their own proposal, a manager approves, the teller draws, breaching figures freeze the facility, the teller cannot waive, an executive waives) |

Found while building it:
- **New backend tests:** two assertions in `test_commercial.py` were wrong on the first run
  (a repayment the account could in fact pay, and the expected ratios listed backwards)
  and were corrected.
- **First Playwright run:** 1 failed and 6 did not run. In "a run in parallel shards", the
  *Start run* click sent no request: the trace shows the click and no POST, and no error
  on the page. That run overlapped the 12-minute backend suite on the same machine; no
  root cause was found in the form's code.
- **Rerun:** the simulations spec alone passed (9 tests), and the full suite on a newly
  rebuilt database, with nothing else running, passed 38 of 38.

## Phase 35: known limitations

- No interest, fees or term-loan repayment schedules on facilities.
- Two financial covenants on figures the bank is given; facilities are unsecured.
- Nothing opens a review automatically; an overdue review only blocks drawdowns.
- No commercial lending workload or AI tool yet (Phase 36).

## Phase 34: what exists

- **`mortgages.application_profile`:** what an underwriter reviews about a recorded
  application. It covers loan-to-value, the payment against declared income and against
  the bureau's estimate, how far declared income exceeds the estimate, the credit score,
  the valuation against the automated model, and age at the end of the term. It is also a
  library handler.
- **AGB Mortgage Underwriting Assistant** (`rule_based_mortgage_underwriting`,
  `recommend_decision` only, compatible with WF-1009), with a deliberate blind spot for
  age. The seed registers it, and the AI Lab console has a sample.
- **WF-1009 v2:** application profile and AI review before the underwriter.
- **Workload `mortgage_applications` and scenario `mortgage-applications` v1:** creditworthy
  applicants whose applications pass every lending rule (checked per case), in six kinds
  with ground truth. A control check covers four-eyes, `loans:approve`, and no offer
  issued without approval.
- **Measured** (300 applications): AI assisted 94.7 % accurate against 89.7 %, review
  hours 81 against 127. Terms past retirement approved rose to 7 from 2, the one kind it
  made worse.

## Phase 34: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 583 passed (new: 3 — the assistant's rules and its age blind spot; the application profile, including age at the end of the term; baseline and AI-assisted mortgage runs with every case decided by an underwriter, no control violations, every kind's advice as designed, offers issued only after approval) |
| Generated workflow tests | 21 workflows, 441 cases, 0 failed (WF-1009 v2: 23 cases, 100 % steps and routes) |
| Frontend Vitest / typecheck / build | 104 passed / clean / built |
| Playwright on a fresh database | 37 passed on the first run (new: the mortgage underwriting assistant in the AI Lab console, approving a term that ends at 94) |
| Measurement | `mortgage-applications`, seed 2030, 300 applications each: baseline 89.7 % accurate (17 wrong approvals, 14 wrong declines, 127.0 review hours); AI assisted 94.7 % (15, 1, 81.5); terms past retirement approved 2 against 7 |

Nothing failed while building this phase: every check above passed on its first run.

## Phase 34: known limitations

- The mortgages workload covers applications only; completions and valuations are not
  simulated.
- WF-1009 v2 has no automated decision: AI assisted is the only AI mode.
- The assistant's advice and the underwriters' response to it rest on stated assumptions.

## Phase 33: what exists

- **Mortgages module** (`app/modules/mortgages/`, migration 0027): two products with
  loan sizes in USD converted per currency; properties with synthetic addresses; desktop
  (synthetic model) and surveyor valuations.
- **Decision in principle:** twelve rules, each returned passed or failed with its
  figures: loan-to-value against the lower of valuation and price, valuation age and
  method (desktop up to 75 %), affordability, income against the bureau's estimate,
  credit history, and no other offer or loan on the property, among others.
- **Offers:** applications refused unless every rule passes; four-eyes decisions (also a
  database constraint); 90-day validity; acceptance; withdrawal; one live offer per
  property.
- **Completion:** `lending.book_loan`, now shared with personal-loan origination, books a
  `mortgage` loan of up to 35 years charged on the property (`loans.property_id`, one
  live loan per property), with its schedule and servicing.
- **Workflow factory:** ten `mortgages.*` handlers (issuing an offer and a surveyor's
  valuation require an approval; completion moves money behind one), WF-1009 Mortgage
  Application, WF-1010 Mortgage Completion, WF-1011 Property Valuation Request; fixture
  kinds `property.property_number` and `mortgage_offer.offer_number` with a creditworthy
  fixture customer.
- **Mortgages page:** products, properties and valuations, the application form with
  every rule shown, offers with approve, decline, accept and complete. New permission
  `mortgages:manage` (department managers).

## Phase 33: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 580 passed (new: 6 — properties and desktop and surveyor valuations; every lending rule passing and failing; the desktop valuation's 75 % limit; an offer from application to completion with four-eyes, a 300-instalment schedule and the property charged; declined, expired and withdrawn offers; the API with its permissions, and the mortgage listed as an ordinary loan) |
| Migration 0027 | upgrade, `alembic check` clean, downgrade and upgrade again |
| Generated workflow tests | 21 workflows, 439 cases, 0 failed (WF-1009: 21 cases, WF-1010: 19, WF-1011: 16; each 100 % steps and routes) |
| Frontend Vitest / typecheck / build | 104 passed / clean / built |
| Playwright on a fresh database | 36 passed on the first run (new: a teller checks eligibility and applies, cannot approve their own application, an underwriter approves, the customer accepts, a manager completes and the loan number appears) |

Found while building it: the first full backend run failed one test (1 failed, 579
passed). Adding `mortgage` to `LoanPurpose` had also added it to the personal-loan
workflow WF-0003, whose input schema lists that enum, so the code definition's content
hash changed and a personal loan could have been applied for as a mortgage.
`LoanPurpose` is unchanged now, and mortgages use their own purpose constant. One Vitest
assertion in the new test matched three rows and was narrowed to one.

## Phase 33: known limitations

- Fixed rates only; no rate switches, overpayments, further advances or second charges.
- Valuations are synthetic, and WF-1011's surveyor can only confirm the price.
- Completion pays into the customer's account; there is no conveyancing and there are
  no fees.
- No mortgages workload or AI tool yet (Phase 34).

## Phase 32: what exists

- **`cards.fraud_profile`:** the purchase the fraud rules declined most recently and the
  card's history before it (approved purchases over 90 days and their median, earlier
  high-risk purchases, when the card was first used in that country, attempts in the
  hour before); a library handler of the same name.
- **AGB Card Fraud Alert Assistant** (`rule_based_card_fraud_review`,
  `recommend_decision` only, compatible with WF-1008), with a deliberate blind spot for
  card testing; registered by the seed, with a sample in the AI Lab console.
- **WF-1008 v2:** fraud profile and AI review before the fraud analyst; completions
  `approved` (released) and `rejected`.
- **Workload `card_fraud_alerts` and scenario `card-fraud-alerts` v1:** card histories
  built through the real authorisation service, so the real fraud rules make every
  block; six kinds with ground truth; control check (four-eyes, `cards:manage`, no
  release without approval).
- **Authorisation windows bounded:** the daily-limit and velocity checks count only
  attempts up to the purchase's time, so backdated purchases are judged as they were.
- **Measured** (300 cases): AI assisted 96.3 % accurate against 88.0 %, review hours 38
  against 61; card testing released 4 against 3, the one kind it made worse.

## Phase 32: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 574 passed (new: 3 — the assistant's rules and its card-testing blind spot; the fraud profile from a card's history; baseline and AI-assisted fraud-alert runs with no control violations, every kind's advice as designed, releases only after approval) |
| Generated workflow tests | 18 workflows, 383 cases, 0 failed (WF-1008 v2: 19 cases, 100 % steps and routes) |
| Frontend Vitest / typecheck / build | 101 passed / clean / built |
| Playwright on a fresh database | 35 passed on the first run (new: the card fraud assistant in the AI Lab console, recommending release of a card-testing block) |
| Measurement | `card-fraud-alerts`, seed 2030, 300 cases each: baseline 88.0 % accurate (19 wrong releases, 17 wrong refusals, 60.8 review hours); AI assisted 96.3 % (6, 5, 38.0); card testing released 3 against 4 |

Found while building it: the first simulation run stopped because a regular crypto
buyer's card was blocked too early. The workload backdates purchases out of order, and the
velocity and daily-limit checks counted every attempt after the window's start, including
later ones. Both checks now stop at the purchase's own time. This never happened outside
the simulation, where purchases are always made at the current time.

## Phase 32: known limitations

- The cards workload covers fraud blocks only; disputes and chargebacks are not simulated.
- WF-1008 v2 has no automated decision: AI assisted is the only AI mode.
- The assistant's advice and the analysts' response to it rest on stated assumptions.
- Building each card's history through the authorisation service costs about 20
  authorisations a case (300 cases took about 3 minutes per run).

## Phase 31: what exists

- **Cards module** (`app/modules/cards/`, migration 0026): two debit products with daily
  limits in USD converted per currency; synthetic card numbers (prefix 9999, Luhn check
  digit), shown masked; at most two live cards per current account.
- **Merchant terminal:** authorisation checks card status and expiry, account status,
  the daily limit, funds (with any arranged overdraft) and four fraud rules. A score of
  70 or more declines the purchase and blocks the card. Approved purchases post at once
  to `CARD-SETTLEMENT-<ccy>`.
- **Blocks:** tellers block; only `cards:manage` (new permission: department managers,
  compliance officers) releases or cancels.
- **Disputes:** 120 days, one live dispute per purchase, decided four-eyes (also a
  database constraint); a chargeback refunds through card settlement.
- **Workflow factory:** seven `cards.*` handlers (the chargeback moves money and the
  release requires an approval), WF-1006 Debit Card Issue, WF-1007 Card Dispute and
  Chargeback, WF-1008 Card Fraud Block Release; fixture kinds `blocked_card.card_number`
  and `authorization.auth_code`.
- **Cards page:** summary, cards with block and release, the terminal, recent purchases
  with fraud scores, disputes with chargeback and rejection.

## Phase 31: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 571 passed (new: 5 — synthetic Luhn-checked numbers and the issuing rules; authorisation against funds, overdraft and the daily limit with ledger postings; fraud rules declining and blocking, release by a manager; disputes with four-eyes, chargeback and rejection; the API with its permissions) |
| Generated workflow tests | 18 workflows, 381 cases, 0 failed (WF-1006: 15 cases, WF-1007: 18, WF-1008: 17; each 100 % steps and routes) |
| Frontend Vitest / typecheck / build | 101 passed / clean / built |
| Playwright on a fresh database | 34 passed (new: a teller issues a card and pays, a purchase abroad at a gambling merchant is declined and blocks the card, the teller cannot release it, a manager does). The first run failed 1 test: the test's own `Merchant` label locator also matched `Merchant country`; the locator was made exact and the full suite passed on a newly rebuilt database |

Found while building it: the partial unique index for live disputes needed a `text()`
predicate in the migration, and a stray unfinished query in the fraud rules was removed
before the first test run.

## Phase 31: known limitations

- Debit cards only.
- Single-message authorisation: approval and settlement happen together.
- Purchases in the card's currency only.
- No cards workload in the simulation and no AI fraud tool yet (Phase 32).

## Phase 30: what exists

- **Simulations run stored workflows:** the runner resolves code or stored definitions,
  and an AI-automated run is refused for a workload without an automated decision path.
- **`retail.account_profile`:** an account's last 90 days from the ledger (money in,
  months with money in, days overdrawn, limits).
- **AGB Overdraft Affordability Assistant** (`rule_based_overdraft_affordability`,
  `recommend_decision` only, compatible with WF-1003), with a deliberate blind spot for
  customers already living in an overdraft; registered by the seed.
- **WF-1003 v2:** account profile and AI review before the credit officer; completions
  `approved` and `rejected`. `ai.review` skips the tool in an experiment's baseline and
  reports `invocation_status`.
- **Workload `retail_overdrafts` and scenario `retail-overdrafts` v1:** customers with
  three months of ledger history; ground truth; control check (four-eyes, authority, no
  limit without approval).
- **Seed order:** examples without AI steps, then the tools, then WF-1003 v2.
- **Measured** (300 requests): AI assisted 96.3 % accurate against 94.3 %, review hours
  42 against 71, but 7 false approvals against 3, all from the blind spot.

## Phase 30: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 566 passed (new: 4 — the assistant's rules and blind spot; the account profile over 90 days of ledger history; baseline and AI-assisted overdraft runs with no control violations, tool calls only when assisted, the blind spot's approvals and limits set only after approval; the automated mode refused) |
| Generated workflow tests | All stored workflows: 15 workflows, 331 cases, 0 failed (WF-1003 v2: 16 cases, 100 % steps and routes) |
| Frontend Vitest / typecheck / build | 98 passed / clean / built |
| Playwright on a fresh database | 33 passed on the first run (new: the overdraft assistant in the AI Lab console, recommending approval for a customer overdrawn most days) |
| Measurement | `retail-overdrafts`, seed 2030, 300 requests each: baseline 94.3 % accurate (3 false approvals, 14 false rejections, 70.6 review hours); AI assisted 96.3 % (7, 4, 42.4) |

Found while building it: the first seeding failed (a tool may only name existing workflows
as compatible, and WF-1003 is imported after the tools), and the first assisted runs
counted every tool call as failed (the simulation read `invocation_status`, which
`ai.review` did not report). Both fixed as described above.

## Phase 30: known limitations

- Retail banking has one workload (overdraft requests); standing orders and month end
  are not simulated as workloads.
- WF-1003 v2 has no automated decision: AI assisted is the only AI mode.
- The assistant's advice and the reviewers' response to it rest on stated assumptions.

## Phase 29: what exists

- **Products** (`retail_products`, migration 0025): credit and overdraft interest, a
  monthly fee and an overdraft maximum per account type. Dollar terms are converted to
  each currency at the FX anchor rates. Managers change them (`retail:manage`, audited).
- **Arranged overdrafts:** `accounts.overdraft_limit`. Every funds check (withdrawals,
  fees, WF-0002, payment release) uses the balance plus the limit.
- **Standing orders:** weekly or monthly, same currency, below the high-value threshold.
  The daily job pays them through the payments service on the payer's country's business
  days; three misses in a row stop an order.
- **Month end:** daily interest on credit and overdrawn balances, the monthly fee and each
  account's statement, posted on the last day of the month, once per month. The job runs
  from the page, the API or the `retail-month-end` schedule.
- **Base processes:** WF-1003 (overdraft, approval first), WF-1004 (standing order, payee
  screened) and WF-1005 (statement copy), on three new library handlers; all generated
  tests pass at 100 % coverage.
- **UI:** the Retail Banking page (products, standing orders, month end, statements);
  account detail shows the overdraft and what is available.

## Phase 29: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 562 passed (new: 6 — product terms converted per currency; overdrafts extending withdrawals and payments, refused above the maximum or below what is owed; standing orders waiting for a business day, keeping the 31st, and stopping after three misses; month end with exact daily interest, overdraft interest, fee, statement and lines, refused for an open month and run once only; the retail API and its permissions; the scheduler's and managers' permission) |
| Generated workflow tests | WF-1003 14, WF-1004 17, WF-1005 10 cases passed, 100 % steps and routes. The first WF-1005 run failed two cases: its handler required the optional `period` input. Fixed so a missing period means the last complete month |
| Frontend Vitest / typecheck / build | 98 passed (new: 3 — the page, a manager's changes, read-only access) / clean / built |
| Playwright on a fresh database | 32 passed on the first run (new: a manager sees the products and runs month end; a teller cannot) |
| Migration 0025 | Upgrade, downgrade and upgrade again; `alembic check` clean |

## Phase 29: known limitations

- No retail simulation workload or AI tool candidate yet (the next step).
- Simple daily interest on a 365-day year; no tiers, compounding or unarranged-overdraft
  fees.
- Standing orders are same-currency only and below the high-value threshold.

## Phase 28: what exists

- **Cases that follow each country's rules** (scenario field `country_rules`). Onboarding
  cases take their ages, accepted identity documents, proof of address and sanctions
  names from the applicant's country. Payment cases take their balances and high-value
  amounts from the payer's country's threshold and limit, and watchlisted payees from its
  lists. The rules in force on the simulated day are stored in the run's dataset. Existing
  scenarios are unchanged, configuration hashes included.
- **`global-onboarding` and `global-payments`:** scenarios on WF-0001 v1 and WF-0002 v1
  whose reviewers never err, so any outcome that differs from the ground truth points to
  the workflow or the rules.
- **Runs in one country:** `create_run(countries=…)`, the API's `country` and the Start
  form's *Country* field. Customers come from that country, staff from its subsidiary,
  and "Run again" keeps the country.
- **The country sweep:** `python -m app.cli country-sweep` runs both scenarios in every
  active country and checks completion, ground truth and the control checks.

## Phase 28: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 556 passed before the last two sweep changes (new: 5 — applications that follow a country's ages, documents and lists; unchanged configuration of existing scenarios; runs limited to countries with their rules snapshot; a sweep of Japan, Kenya and Saudi Arabia with staff in each subsidiary, every kind covered as predicted, and high-value payments approved by a second person; the API starting and re-running a one-country run). The sweep tests were re-run after the coverage and path checks: 5 passed |
| Frontend Vitest / typecheck / build | 95 passed (updated: the start form sends the chosen country) / clean / built |
| Playwright on a fresh database | 30 passed on the first run (new: a `global-payments` run in Japan, every outcome right) |
| Country sweep (Milestone C exit) | **240 of 240 runs passed in 120 countries, 7,200 cases**, every kind in every country, 31 min 43 s. Before it, two problems were found and fixed: the first full sweep (also 240 of 240) drew the same kinds everywhere and missed sanctions hits and scams; and a control with country-blind cases passed until paths were checked. With path checks, the control fails in Austria and Lebanon (onboarding) and in Indonesia, Vietnam, Korea and Kuwait (payments), and passes in the UK and Japan |

## Phase 28: known limitations

- The sweep runs one country at a time in one process.
- Sweep reviewers never err; how accurate people are is studied with the other scenarios.
- Document numbers use the simulation's own format, not each country's mask.

## Phase 27: what exists

- **Subsidiary blueprint** (version 1): 3 divisions, 4 departments and 4 teams with 24
  synthetic staff, paid in the country's currency on a dollar band converted at the FX
  anchor rates; names from a seed fixed per country.
- **Launching a country:** activates a planned country, adds its regional headquarters
  when the region has none, and builds whatever the subsidiary is missing; staff only for
  new units; generated units record `generated_from` (migration 0024); audited.
- **API, job, UI and CLI:** `GET /organizations/blueprint` (with coverage by region),
  `POST /organizations/generate` (an `organizations.generate` job, one transaction per
  country), the *Country subsidiaries* panel on the Organization page, and
  `python -m app.cli subsidiaries coverage|generate`.
- **Measured:** all 115 planned countries launched in 31 s (1,381 organizations, 2,760
  staff); a second run created nothing.
- **Employee pay limit** raised to 10¹⁵ minor units (the Lebanese pound band needs more
  than the previous 10¹²).

## Phase 27: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 551 passed (new: 6 — the blueprint, with every currency's pay band within the employee limit; launching Kenya: activation, the new Middle East & Africa headquarters, 12 generated units, 24 staff paid in KES, audit events; completing a partly built subsidiary and launching again without duplicates; refusals (no global bank, suspended country, unknown codes) and generation targets; reproducible staff names; the generation API and job with permissions) |
| Frontend Vitest / typecheck / build | 95 passed (new: coverage and a generation job with a failed country) / clean / built |
| Playwright on a fresh database | 29 passed locally (new: an administrator launches Kenya and opens its generated subsidiary). In CI the first push failed: the new test ran in parallel with the simulation test, launched Kenya between a run and its reproduction, and the reproduction (rightly) reported different results because its dataset had gained a country. The test now runs last in the serial simulations file; 29 passed again on a fresh database |
| Migration 0024 | Upgrade, downgrade and upgrade again; `alembic check` clean |
| Full generation (CLI, demo database) | 115 of 115 planned countries launched in 31.0 s: 1,381 organizations, 2,760 staff; a second run did nothing. The first attempt stopped at Lebanon on the employee pay limit (fixed by raising the limit, see above) |

## Phase 27: known limitations

- One blueprint for every country, whatever its size; names are not country-specific.
- Launching does not start customers, products or simulation workloads in a country; that
  is the Milestone C exit (Phase 28).
- Simulations hire staff in the first active country by code, so on a fully launched
  database that is the United Arab Emirates instead of Germany.

## Phase 26: what exists

- **Dated lunar holidays** for 2025–2030 (`reference/dated.py`): 12 festivals, 257 rules in
  50 countries, with weekend observance; reference data 2026.2 loaded by migration 0023.
- **Schedules on business days:** `job_schedules.business_calendar`; a schedule due on a
  weekend or holiday of its country moves to the next business day without running. Set
  in System Settings → Background jobs or with `PATCH /job-schedules/{name}`.
- **Simulation arrivals on business days:** scenario configuration `business_calendar`;
  new scenario `payments-easter` (UK Easter weekend 2026).

## Phase 26: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 545 passed (new: 8 — one date a year for every festival and valid country rules; dated holidays and their observance (Saudi Eid, Singapore Vesak, Korean Chuseok, Israeli holidays, Vietnam's Tết eve); none outside 2025–2030; a schedule due on a Saturday moved to Monday without a job; business runs over Christmas, without a calendar and over a Friday–Saturday weekend; the schedule API setting, rejecting and clearing a calendar; simulation arrivals moved past the UK Easter weekend; the `payments-easter` run) |
| Frontend Vitest / typecheck / build | 94 passed (new: an administrator setting and clearing a schedule's business calendar) / clean / built |
| Playwright on a fresh database | 28 passed on the first run (updated: Saudi Arabia's 2026 calendar shows Eid al-Fitr and 254 business days; System Settings sets and clears a schedule's business calendar) |
| Migration 0023 | Upgrade, downgrade and upgrade again; `alembic check` clean |

## Phase 26: known limitations

- Dated holidays cover 2025–2030 only; Islamic dates can move by a day with the moon.
- Scheduler calendars move whole days; simulated staff still work every day.
- Working weekends (China, Vietnam, Korea), bridge days and regional holidays are not
  modelled.

## Phase 25: what exists

- **Versioned rules per country** (`country_rules`, migration 0022): KYC (minimum age,
  accepted identity documents, proof of address), screening (which synthetic sanctions
  lists apply) and payments (cut-off, high-value threshold, single-payment limit).
  Version 1 of all 120 countries comes from defaults derived from the reference data. New
  versions take effect on a date, are never edited, and are audited.
- **Applied by the workflows:**
  - WF-0001 checks the applicant's country's minimum age and documents, and screens
    against its lists;
  - WF-0002 takes the limit, the threshold and the lists from the payer's country.
  - Each payment records its threshold and a value date (cut-off plus the country's
    calendar), and posts with that effective date.
- **Five synthetic sanctions lists.** The library's `compliance.screen_name` takes `lists`.
- **API and UI:** country rules (current, versions, add a version) and sanctions lists. The
  country panel shows the rules and lets managers add a version; payments show value dates.

## Phase 25: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 537 passed (new: 9 — valid defaults for all 120 countries and their spot values; versions take effect on their date, are audited and cannot predate the latest; rules validation; screening across several lists; value dates over the cut-off, weekends and holidays; WF-0001 applying a country's minimum age and accepted documents; a waived proof of address and an EU-style list hit; WF-0002 limits, high-value threshold and value date from the payer's country; the rules API and permissions) |
| Frontend Vitest / typecheck / build | 93 passed (new: the rules in force, versions and a manager's new version) / clean / built |
| Playwright on a fresh database | First run: 27 passed, 1 failed — the new rules test's sign-in landed on the Overview instead of the Countries page (the deep link was lost); it passed twice alone and in the full rerun. Like the Phase 24 shell failure, it occurs only under full parallel load; root cause not yet found (see known limitations). Second run on a fresh database: 28 passed |
| Migration 0022 | Upgrade, downgrade and upgrade again; `alembic check` clean |

## Phase 25: known limitations

- Rules cover individuals' account opening and payments, per payment only (no daily or
  monthly cumulative limits, no business-customer or lending rules yet).
- The five operating countries keep their earlier payment limits (10,000 and 1,000,000
  units of their currency) so earlier simulations reproduce. In Japan that leaves a
  10,000-yen high-value threshold; change it with a new rules version.
- The defaults are compiled for the simulation, not regulatory advice.
- Under full parallel Playwright load, a sign-in has twice (Phases 24 and 25) ended on the
  Overview or the "API unavailable" state instead of the requested page; both passed on
  rerun. The login redirect keeps the requested page in navigation state, so something
  under load replaces it; not yet diagnosed.


## Phase 24: what exists

- **Rates:** deterministic synthetic daily rates (units per US dollar) for all 93
  currencies, with USD and EUR pegs; published to `fx_rates` daily or on first use.
- **Conversions:** quotes at the mid rate less a 0.50 % margin, rounded down to minor
  units. Each conversion posts two balanced entries, one per currency, through
  `FX-POSITION-<CCY>` accounts. Deals (`fx_deals`) are idempotent by key.
- **Cross-currency payments:** WF-0002 accepts payees in any currency. The payee's amount
  is estimated when the payment is created and converted at release. Payments record the
  payee's currency and amount and the deal (a constraint requires it once released). The
  customer is notified of both amounts.
- **Positions and revaluation:** positions valued in US dollars. Revaluation books the
  change to FX income (`fx_revaluations`). The `fx-daily` schedule publishes rates and
  revalues; administrators can revalue by hand (`fx:manage`).
- **UI:**
  - a Foreign Exchange page: rates, quote, positions with *Revalue*, revaluations,
    conversions;
  - the payment form lists payees in every currency, with a live estimate;
  - the Payments list shows the converted amount and the deal.

## Phase 24: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 528 passed (new: 8 — deterministic rates and pegs; idempotent publication; quotes with margin and minor-unit rounding (yen, dinars) and refusals; a conversion posts one balanced entry per currency, replays by key and the ledger still reconciles; revaluation books the margin, nothing more the same day, then the next day's rate move; a WF-0002 payment from USD to a yen account converts at release with its deal, notification and listing; the payer account must match the payment currency; the FX API and its permissions) |
| Frontend Vitest / typecheck / build | 92 passed (new: the Foreign Exchange page — rates, quote, positions and revaluation; the payment form's conversion estimate) / clean / built |
| Playwright on a fresh database | First run: 25 passed, 2 failed. The new multi-currency test assumed a funded US-dollar account among the accounts listed and found none; it now takes any funded account and a payee in another currency. The existing "backend unreachable" shell test failed once under the full parallel run and passed in every rerun (twice alone, then in the full run); not changed. Second run on a fresh database: 27 passed |
| Migration 0021 | Upgrade, downgrade and upgrade again on the development database; `alembic check` clean |

## Phase 24: known limitations

- One margin for every pair and size; spot only (no forwards or swaps); daily rates.
- Positions valued in US dollars only; no reporting currency per subsidiary.
- Customers cannot convert between their own accounts outside a payment.


## Phase 23: what exists

- **Reference data** (`app/modules/reference/`, version 2026.1) for the 120 countries:
  - ISO codes, calling codes, currency and minor units (`currencies`, 93 currencies);
  - time zone, languages, weekend days and banking regulator;
  - identity documents and passports with number masks;
  - address layouts with postal-code masks;
  - 1,167 holiday rules, with the Western or Orthodox Easter and the observance of weekend holidays.
- **Loading:** migration 0020 loads a frozen snapshot. It adds the `currencies` table (with
  a foreign key from `countries`), fills the reference columns of the 5 operating
  countries and adds 115 planned ones. `reference load` re-applies the data idempotently
  without touching operator-managed fields.
- **Calendars:** holidays and observed days off for any year from 1980 to 2099; business days
  and the next business day.
- **Formats:** masks validate and generate document numbers and postal codes; addresses are
  formatted in each country's layout. Synthetic samples are deterministic per seed.
- **API:** `/currencies`, plus four endpoints per country: `calendar`, `business-day`,
  `check` and `samples`. A new country must use a known currency.
- **Elsewhere:** `app.core.money` reads minor units from the reference data; templates
  get the new `{{country.*}}` fields.
- **UI:** the Countries page filters by status and searches by name or code. Each country
  opens to its reference data, the holiday calendar by year, a format checker and
  synthetic samples.

## Phase 23: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 520 passed (new: 131 — the dataset (120 countries, 4 regions), each country's consistency (one test per country: codes, currency, time zone, languages, masks with examples, a decade of computable holidays), ISO 4217 minor units through `money`, both Easter computuses, holiday rules and weekend observance, weekends of Friday–Saturday and Friday–Sunday, masks and address layouts, the migration snapshot equals the dataset, the database contents, an idempotent reload that keeps operator fields, the reference API, a new country needing a known currency). Writing the per-country test found a duplicated holiday name in China's data, fixed before commit |
| Frontend Vitest / typecheck / build | 91 passed (new: a country's reference data, calendar, format check and samples) / clean / built |
| Playwright on a fresh database | 26 passed, first run (new: Saudi Arabia found by region, status and search; its weekend, regulator, 2026 calendar and a postal-code check) |
| Migration 0020 | Upgrade, downgrade and upgrade again on the development database; `alembic check` clean |

## Phase 23: known limitations

- Lunar-calendar holidays (Islamic, Chinese, Hindu, Buddhist, Jewish), state and provincial
  holidays, bridge days and make-up working weekends are not computed. Business calendars
  that take dated tables are a later Milestone C step.
- Masks give the shape of document numbers and postal codes, not check digits.
- Regulators and holidays are compiled for the simulation, not from an authoritative feed.
- The scheduler and the simulation do not yet use the calendars; that is the business
  calendars step.


## Phase 22: what exists

- **Catalogue** (`workflow_catalogue`, migration 0019): department, countries, products,
  tags and owner per workflow — from a definition's or template's `catalogue` block, by hand
  (`PUT /workflow-catalogue/{id}`, *Classify*), or registered in code for WF-0001–0004.
  `GET /workflow-catalogue` searches by text and facets with counts; the Explorer filters by
  department, country, product and status.
- **Review lifecycle:** API and editor imports are drafts; submit → approve (four-eyes, the
  version's latest generated tests must pass) or return with a note; retire/reactivate.
  Drafts can be tested but not started. Department managers hold `workflows:define`.
  *Versions and review* panel in the Explorer; `workflows import --publish` for operators.
- **Parallel generated tests:** `workflows test --processes N`.
- **TPL-PAPER-STATEMENT v2** classifies its variants by country and product; the seed
  classifies WF-1001/WF-1002.

## Phase 22: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 389 passed (new: 10 — review to active under four-eyes and passing tests; return with a note; a draft does not reclassify an active workflow; department managers define; catalogue validation; hashes without a catalogue; code workflows classified and searchable; facets counted over the other filters with paging; the catalogue and review API; the seed classification is valid) |
| Frontend Vitest / typecheck / build | 90 passed (new: facet filters; submit, refused self-approval, return with a note; classification with an owner) / clean / built |
| Playwright on a fresh database | 25 passed, first run (new: WF-1001 edited, saved as a draft, submitted, tested, refused to its author and approved by a manager; variants found by country, product and department) |
| Milestone B exit run (`workflows test --all --processes 4`, 5,052 stored workflows) | 111,168 cases, 0 failed, 100 % step and route coverage, 5,381.6 s; 50 → 54.7 s, 500 → 604.6 s (linear) |

## Phase 22: known limitations

- Catalogue search builds every summary per request (0.37 s at 5,056 workflows); at tens
  of thousands it will want facet counts in SQL.
- One department, a country list and a product list per workflow; no per-country owners.
- Approval is by any holder of `workflows:define` other than the author; there is no
  routing of reviews to the owning department yet.
- Generated tests remain the only automatic gate; the exit run took 1 h 30 min on four
  processes, so CI tests the seeded bank, not the 5,000.

## Phase 21: what exists

- **Diagram for every workflow** (`workflows/graph.py`, `GET /workflows/{id}/graph`): a
  layered layout computed on the server (back routes, longest-path layers, barycentre
  ordering), labelled routes (approved/rejected, conditions, otherwise, on failure,
  timeouts), live step metrics with the bottleneck, and the latest generated tests'
  coverage per route; drawn as SVG in the Workflow Explorer's *Diagram* view.
- **Editor for stored workflows** (*Edit as v{n+1}*): a step form (name, type, library
  handler, next, params) and the JSON kept in step; add/remove steps; a live preview
  (`POST /workflow-definitions/preview`) validates and draws the draft, with problems shown
  on the step they belong to; saving imports through the usual validation. Generated
  variants are edited through their template, not here.

## Phase 21: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 379 passed (new: 4 — layers follow the routes with unique places and labels; WF-0001's documents loop as the one back route; metrics and coverage overlays incl. an uncovered route; the preview validates, draws drafts with errors, and refuses unparseable ones) |
| Frontend Vitest / typecheck / build | 87 passed (new: the diagram with coverage; the editor's located problems, form edit, live re-validation and save) / clean / built |
| Playwright on a fresh database | 24 passed (new: WF-1002's diagram; WF-1001 edited through a diagram click and saved as its next version). One run failed first on the test itself (a truncated step name and the SVG tooltip both matched); the locator was fixed and the full suite re-run green |

## Phase 21: known limitations

- The layout is simple (no edge routing around nodes); large workflows (dozens of steps
  per layer) become wide. Long step names are shortened on the diagram (full in tooltips).
- The editor edits steps' common fields in the form; transitions, approval policies and
  timeouts are edited in the JSON. No drag-and-drop.
- Code workflows can be viewed but not edited (they change in code).

## Phase 20: what exists

- **Generated path tests** (`workflows/testing.py`): for each stored definition, a happy
  case, one case per route (transitions, fallbacks, `on_failure`, timeouts) planned along
  the shortest path with its conditions solved together, approval cases (initiator and
  outsider refused), and no-route probes at decisions without a fallback. Inputs come from
  the schema; looked-up records (customer, funded account) are created from the library
  handlers' declared fixtures; staff are created per run. Cases run in rolled-back
  savepoints; checks: a clean ending, the planned path visited, a declared outcome, no money
  moved without a granted approval, refusals.
- **Coverage and records:** step and route coverage, uncovered routes with reasons;
  `workflow_test_runs` (migration 0018); `last_test` on stored definitions.
- **Interfaces:** CLI `workflows test --all | --template | WF-ID … [--sample] [--output]`
  (non-zero exit on failure); CI job *Workflow factory (generated tests)*; API run/list;
  the Explorer's *Generated tests* panel.

## Phase 20: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 375 passed (new: 7 — route planning incl. solved conflicts, fallbacks, rejects and injected failures; input synthesis and fixture inference; WF-1002 fully covered with refusals and nothing left behind; a generated variant with a steered product check; **defects found**: an input matching no route (probe) and a step reading the wrong record; run records and the API) |
| Migration 0017 → 0018 → 0017 → 0018, `alembic check` | clean |
| Frontend Vitest / typecheck / build | 85 passed / clean / built |
| Playwright on a fresh database | 23 passed (new: running WF-1002's generated tests from the catalogue) |
| `workflows test --all` on a freshly seeded bank (what CI runs) | 12 workflows, 288 cases, 0 failed, 100 % steps and routes each, 37.6 s |
| Scale sample: 100 variants of TPL-SCALE-STATEMENT | 0 failed, 296 s (about 3 s per workflow, single process) |

## Phase 20: known limitations

- About 3 s per workflow in one process: all 5,040 scale variants would take about 4 hours,
  so CI tests the seeded set; a template's variants differ only in parameters, so sampling
  (`--sample`) or sharding across workers is the way to the full set (not built yet).
- Code-registered workflows (WF-0001–0004) are not covered: their inputs are Pydantic
  models with domain documents, and they keep their hand-written tests.
- Planning steers single-level paths; nested input conditions, negated compound
  conditions and conflicting requirements leave a route uncovered (reported).
- Route coverage counts a route covered when a passing case planned through it.

## Phase 19: what exists

- **Templates** (`workflow_templates`, migration 0017): a definition body with typed
  `{{param}}` placeholders, country reference data (`{{country.currency}}` …), minor-unit
  conversion (`{{fee|minor}}`) and optional steps (`$include`, routed around when off), a
  parameter JSON Schema, an example and an id range. Import validates the template and
  renders its example through the full definition validation. Versions are immutable.
- **Variant generator:** grid × explicit variants over fixed values; one stored definition
  per parameter set, with a stable workflow id per variant key (`workflow_variants`), new
  versions only for changed content, all-or-nothing, dry run. Generated definitions carry
  `origin`; only the generator sets it, and variants cannot be imported by hand.
- **Interfaces:** `/api/v1/workflow-templates` (list, detail, variants, validate, import,
  render, generate, retire/reactivate); `GET /workflows` filters `source`, `template_id`,
  `limit`; CLI `workflows templates | import-template | generate`; the Workflow Explorer's
  Templates tab (parameters, variants, generate with preview) and template badges.
- **TPL-PAPER-STATEMENT** (WF-1002 as a template), imported by `seed-demo` with ten
  variants WF-2000–2009 (five countries × current and savings).
- **Scale:** 5,040 variants of one template generated (4,500 new in 52.5 s); 5,056
  registered workflows; two slow paths found and fixed (definition detail 0.27 → 0.015 s,
  dashboard 2.6 → 0.05–0.13 s); the catalogue summarises stored definitions in SQL.

## Phase 19: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 368 passed (new: 10 — rendering types, text, country data, minor units, optional steps; located render errors; example template clean; template validation incl. the rendered example's approval rule; immutable versions; generation deterministic in any input order (found a real ordering bug, fixed), idempotent, versioned on template change, skipping held ids; all-or-nothing, dry run, range full, limit, retired; variants owned by their template and `origin` reserved; a GB variant charging 500 and a US variant refusing a GB account; the API) |
| Migration 0016 → 0017 → 0016 → 0017, `alembic check` | clean |
| Code definition hashes | unchanged (`origin` is optional and omitted when unset) |
| Frontend Vitest / typecheck / build | 84 passed / clean / built |
| Playwright on a fresh database | 22 passed (new: the Templates tab — 10 seeded variants, a preview finding all unchanged, the Japanese variant's 5 JPY fee step) |
| Scale (CLI, demo database) | 60 / 540 / 5,040 variants: 0.6 / 5.4 / 52.5 s; dry run of 5,040 in 33.4 s; see `docs/performance.md` |

## Phase 19: known limitations

- The full catalogue response is 2.5 MB at 5,000 workflows; the UI asks for the first 200
  and relies on search. Catalogue facets (department, country, product) are a later step.
- Variants are not yet tested automatically per path; that is Milestone B step 4.
- One template renders one definition shape; templates do not compose or inherit.
- Generation runs in the request (at most 1,000 sets per API call; the CLI is unlimited);
  it is not a background job yet.

## Phase 18: what exists

- **Domain handlers** for stored definitions: `customers.lookup`, `customers.notify` (real
  notification rows, `{path}` templates), `customers.set_risk_rating`,
  `compliance.screen_name` (the WF-0001/0002 watchlist, now in `compliance/screening.py`),
  `accounts.lookup` (ownership check, balance), `accounts.charge_fee` (debits the account,
  credits `FEE-INCOME-<ccy>`, no overdraft, idempotent per step run) and `ai.review` (an AI
  task through the invocation service; escalates when no usable answer comes back).
- **Declared effects** (reads, writes, moves money, advisory) in the handlers API, the
  validation report (`effects`) and the Workflow Explorer (badges per step, a summary when
  validating).
- **Approval before money:** validation refuses a definition in which a money-moving
  handler is reachable without passing an approval's approve route (skipping the approval,
  its reject route, or a condition unrelated to the decision all count as unapproved).
  Also new: handler-kind checks for service vs. AI steps, database checks (the AI tool
  exists and may perform the action).
- **Examples:** WF-1001 v2 (finds and screens the customer, writes to them) and WF-1002
  Paper Statement Request (fee after four-eyes approval), imported by `seed-demo`.

## Phase 17: what exists

- **Stored definitions.** Workflow definitions can be imported as JSON next to the ones in
  code (`workflow_definitions.source = 'stored'`, migration 0016). Any process loads them
  from the database on first use. Versions are immutable; a version is `active` or
  `retired` (no new cases; running ones finish on it). Code definitions are unchanged:
  their content hashes are pinned by a test.
- **Full validation** before anything is stored, every problem with a location: graph and
  termination, ownership (no code workflow ids), version rules, handler names and params,
  the context paths conditions and handlers read, approval permissions and four-eyes
  references, the input JSON Schema, waiting rules; plus warnings.
- **Handler library** (`core.set_values`, `copy_values`, `check`, `business_key`,
  `notify`, `set_outcome`) with params models published as JSON Schema.
- **Interfaces:** `/api/v1/workflow-definitions` (list, handlers, validate, import,
  retire, reactivate), `GET /api/v1/workflows/{id}/export`, permission `workflows:define`
  (administrators); CLI `workflows list|validate|import|export`; Workflow Explorer badges,
  import dialog with every problem listed, start form generated from the input schema,
  export, retire/reactivate.
- **WF-1001 Customer Address Change**, imported by `seed-demo`: routing by reason,
  colleague or compliance four-eyes approval, `on_failure` route, synthetic letters.

## Phase 18: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 358 passed (new: 10 — library effects; examples valid with effects; approval rule: skipped approval, reject route, unrelated condition refused, `decision == approve` accepted (mutation-checked); handler kinds, params and AI-tool checks; AI advice and safe escalation; fee charged once after approval with income credited, letter text, retry replays the posting (mutation-checked); e-mail, declined, another customer's account, unknown customer; insufficient funds; WF-1001 v2 with screening to compliance and unknown customer; risk rating and the handlers/validate API). Two Phase 17 assertions updated for the intended changes (AI steps allowed; `effects` in reports) |
| Code definition hashes | unchanged (WF-0001 and WF-0002 now import the shared watchlist; their definitions did not change) |
| Frontend Vitest / typecheck / build | 83 passed / clean / built |
| Playwright on a fresh database | 21 passed (new: WF-1002 fee after approval; WF-1001 test now on v2 with a real customer) |
| Live check | Re-seeding a Phase 17 database added WF-1001 v2 and WF-1002; a WF-1002 case over HTTP charged 5.00 only after the manager approved (balance −500), and a full ledger reconciliation passed |

## Phase 18: known limitations

- Customers have no address fields, so WF-1001 v2 still keeps the new address in the case.
- Domain handlers act as the system; the approver is recorded on the approval step, not on
  the posting itself.
- `ai.review` passes context values to the tool as they are; mapping into a tool's nested
  input needs that structure in the case input.
- No payment, loan or account-opening handlers yet; those workflows remain in code.

## Phase 17: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 348 passed (new: 10 — code hashes unchanged; example valid and clean; every problem reported at once with locations; ids, triggers, people and schemas; warnings do not block; immutable, increasing versions and audit; a stored workflow end to end with four-eyes, `on_failure`, JSON-Schema input errors and a cold cache (another process); retire/reactivate with a new version taking new cases; export round trip; the API) |
| Migration 0015 → 0016 → 0015 → 0016, `alembic check` | clean |
| Frontend Vitest / typecheck / build | 83 passed / clean / built |
| Playwright on a fresh database | 20 passed (new: WF-1001 from the generated form through colleague approval to `updated`, and an administrator validating its next version) |
| Live check | WF-1001 started over HTTP, its compliance task completed by a separate process with nothing in memory; dashboard counts 5 workflows, 7 definition versions |

## Phase 17: known limitations

- Stored definitions use library handlers only: they cannot change banking records, call
  AI tools, run on schedules or drive simulations yet (WF-1001 records the approved address
  in the case, not on the customer). Milestone B step 2 extends the library.
- Defining is administrators-only (`workflows:define`); there is no draft state or
  review/approval of a definition before it becomes active.
- The start form handles flat schemas (strings, numbers, booleans, enums); nested objects
  and arrays need the API.
- Validation checks that a path's first segment exists, not that an earlier step's output
  has that field or that the step runs before the read.

## Phase 16: what exists

- **Sharded simulation runs.** `shards` (1–8) splits a run's cases (`case_index % shards`)
  and, round-robin per role, its staff into slices; each slice is a `simulation.shard`
  job any worker process runs; the last to finish merges the results (migration 0015,
  `simulation_shards`). Same seed and shard count, same digest; outcomes match a
  single-process run, queueing does not (each shard has its own team). The `large`
  profile (100,000 applications, 5,000 staff) needs at least 4 shards. API `shards`,
  `shard_progress`; `simulate --shards N`; start form and per-shard progress in the UI.
- **No deadlocks between shards.** The stored-balance trigger now honours
  `SET LOCAL atlas.balance_shard`; each shard pins its own balance row of every account
  (hence at most 8 shards). Without it, parallel payment shards deadlocked on the cash
  account.
- **Performance suite** (`python -m app.cli perf [--quick]`, `make perf`): ledger postings,
  API p95 latency, job throughput, simulation throughput single and sharded, each against a
  recorded target; JSON results; a CI job runs the quick profile on every push.
- **Docker Compose:** the worker service runs 4 processes (`ATLAS_WORKER_PROCESSES`), is
  marked as a worker, and forwards SIGTERM so each process finishes its job on `docker
  stop`.
- **Fixed along the way:**
  - Request transactions committed *after* the response was sent (FastAPI's default
    scope for yield dependencies): a client refetching at once could read the state from
    before its own write — the cause of the end-to-end tests' intermittent "approved but
    still listed" failures since Phase 11 — and a failing commit was reported as success.
    The session dependency now uses `scope="function"`; a test checks the order.
  - The dashboard (and the Phase 15 archive summary) failed once a payments simulation
    existed: simulated business keys were all cast to customer ids, but WF-0002 keys
    payments by payment number.
  - `SimulationSetupError` is a 422 business-rule error like the other refusals to start.

## Phase 16: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 338 passed (new: 6 shard tests — shard order does not change the digest and outcomes match a single run, staff dealt round-robin with nobody in two shards (mutation-checked), merge happens once, a failing shard fails the run and stops the others, staff and shard-count validation, pinned balance row; API with profiles, reruns and inline shards; 3 performance-suite tests; the dashboard with a payments simulation (fails without the fix); the transaction committing before the response (fails without the fix)) |
| Migration 0014 → 0015 → 0014 → 0015, `alembic check` | clean |
| Single-process results unchanged | a 300-case run reproduced its pre-change digest exactly |
| Sharded workloads | retail, payments and loans each twice in 8 shards with identical digests; full reconciliation passed |
| Frontend typecheck, Vitest, build | clean; 81 passed (new: the large profile's minimum shards and per-shard progress); succeeds |
| Playwright, fresh database (inline jobs) | 19 passed (new: a run in 2 parallel shards) |
| Docker Compose | `validate_system.py` 10/10; a 4-shard run spread over the 4 worker processes with the same digest twice; graceful stop of all 4 processes; Playwright 19 passed |
| Performance suite | full and quick profiles pass locally; quick profile passes in CI |

Measured: see [performance.md](performance.md) — 2,000 cases in 334 s on one process and
80 s on 4 shards (4.2×); the department profile in 6 min 39 s twice with identical
digests; **100,000 applications in 73 min 18 s** on 8 shards (22.7 cases/s, 96.65 %
accuracy), archived in 3 min 37 s.

## Phase 15: what exists

- **Partitioned workflow history** (migration 0013): executions, step runs and events are
  LIST-partitioned into `live` and `simulation`; keys `(id, realm)`; queries that know
  their realm read one partition; live history can never be deleted.
- **Archive, restore, reset of simulation history** (`app/simulation/history.py`):
  per-run archive to compressed COPY files with a checksummed manifest (results and case
  outcomes stay; the dashboard keeps counting the run), restore, reset of all simulation
  history by dropping the partitions, archive of runs older than N days and a (disabled)
  retention schedule. As background jobs from the API (`simulations:manage`, new: held by
  administrators and AI researchers), and `python -m app.cli simulation-history
  status|archive|restore|reset`.
- **Observability** (`app/observability`): request counts and latency by route template,
  the slow-query log from the API and every worker (`slow_queries`, threshold
  `ATLAS_SLOW_QUERY_MS`), the worker registry (`job_workers`), queue depth and lag, job
  throughput per kind, database size; `GET /api/v1/observability/overview` and
  `/slow-queries` (`observability:read`, new: administrators and auditors); Prometheus text
  at `/api/metrics` behind `ATLAS_METRICS_TOKEN`.
- **UI:** System Settings gains Observability and Simulation history panels; the
  Simulation Center run view shows where the run's history is and archives or restores it.
- **Found with the new slow-query log:** the dashboard's per-run timeout count scanned
  every event (≈ 200 ms at 100,000 simulated cases); a partial index brought the whole
  overview from ~340 ms to ~140 ms.
- **Docker Compose:** a shared `simulation-archive` volume for the API and the worker;
  `ATLAS_SLOW_QUERY_MS` and `ATLAS_METRICS_TOKEN` pass through.

## Phase 15: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 327 passed (new: 9 history tests — realm routing and the realm/run check, archive then restore returns every row exactly (compared column by column), dashboard costs unchanged by an archive, refusals (unfinished, twice, not archived), corrupted file refused by checksum, live events undeletable even with the purge setting and simulation events undeletable without it, reset keeps the live bank and new runs work on the recreated partitions, reset with archive and its refusal while runs are active, retention by age, API with jobs and permissions; 5 observability tests — routes counted by template not raw path, slow statements logged without parameters, overview with worker and throughput and grouped slow queries, worker registry, Prometheus endpoint and its token) |
| Migrations | `alembic check` clean; 0012 → 0014 → 0012 → 0014 on an empty database; 0014 → 0012 → 0014 on 100,000 simulated cases (downgrade 25 s, upgrade 40 s, every row and the event sequence kept) |
| Frontend typecheck, Vitest, build | clean; 80 passed (new: Observability panel, Simulation history panel, archive from the run view); succeeds |
| Playwright, fresh database (inline jobs) | 18 passed (new: archive a run's history and restore it; administrators see observability and simulation history) |
| Docker Compose with the worker service | archive and restore ran in the worker container with the files in the shared volume; CLI reset in the worker container; `/api/metrics` 404 without a token and served with one; Playwright 18 passed |

Measured in the development container on 100,000 simulated cases (100,236 executions,
1.6M step runs, 5.1M events, 2.4 GB):

| Measurement | Before | After |
| --- | ---: | ---: |
| Live executions list / task inbox / WF-0001 metrics / timer sweep | 3.4 / 3.3 / 4.4 / 2.5 ms | 3.9 / 3.7 / 4.7 / 2.0 ms (unchanged: indexes were enough) |
| Remove one run's history | row-by-row DELETE: events 24 s, step runs > 10 min (stopped) | reset 5.0 s; archive 119 s (to 519 MB of files) |
| Restore an archived run | — | 562 s |
| Enterprise overview (dashboard API) | ~340 ms | ~140 ms (partial index on timeout events) |
| Migration 0013 | — | 41 s up, 25 s down |

## Phase 14: what exists

- **Durable job queue** (`jobs`, migration 0012) in PostgreSQL: queued in the caller's
  transaction, claimed with `FOR UPDATE SKIP LOCKED`, heartbeats, retries with
  exponential backoff, recovery of jobs whose worker stopped, dedupe keys.
- **Worker** (`python -m app.cli worker [--processes N] [--drain] [--no-schedules]`,
  `make worker`, a `worker` service in Docker Compose).
- **Schedules** (`job_schedules`): incremental reconciliation every 15 minutes, full
  reconciliation daily, workflow timers every minute, loan servicing daily (off by
  default), run as the new `atlas-scheduler` service account (`system_scheduler` role).
- **Simulations and experiments are jobs**: queued with their runs in one transaction; run
  by a worker, or by the API itself when `ATLAS_JOBS_EXECUTION=inline` (the default
  outside Docker Compose).
- **API and UI:** jobs, kinds, schedules (switch, change, run now), cancel; a Background
  jobs panel in System Settings. New permissions `jobs:read` (administrators, auditors)
  and `jobs:manage` (administrators).

## Phase 14: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 313 passed (new: 9 job tests — run once with a result, dedupe keys, retry with backoff then success, permanent failure, recovery of a lost worker whose late report is ignored (mutation-checked), at most one job per schedule, four parallel workers sharing 120 jobs with real commits and none run twice, reconciliation and servicing jobs including the scheduler principal and the skip rule, API permissions, schedule changes, run-now, manual kinds only, cancel) |
| Migration 0011 → 0012 → 0011 → 0012, `alembic check` | clean |
| Frontend typecheck, Vitest, build | clean; 77 passed (new: the Background jobs panel, interval wording); succeeds |
| Playwright, fresh database (inline jobs) | 16 passed; the simulations and experiments it starts ran as jobs |
| Docker Compose with the worker service | `validate_system.py` 10/10; the worker ran the schedules on start; Playwright 16 passed with every simulation and experiment run by the worker container |

Queue throughput in the development container (5,000 `system.ping` jobs, `worker --drain`,
including process start-up):

| Worker processes | Throughput | Jobs per process |
| ---: | ---: | --- |
| 1 | 117 jobs/s | 5,000 |
| 4 | 379 jobs/s | 1,256 / 1,252 / 1,249 / 1,243 |

The queue costs about 8 ms per job (claim, load, heartbeat thread, completion); real jobs
are dominated by their own work.

## Phase 13: what exists

- **Bulk posting** (`ledger.post_entries`): batches of entries through PostgreSQL COPY with
  the same rules as single postings (checked in Python, again by the database's triggers),
  idempotent replays, all or nothing, one audit event per batch. `bench-ledger --bulk`.
- **Bulk population** (`python -m app.cli load-population --customers N`): KYC-verified
  customers, approved four-eyes account requests, open accounts and opening deposits in
  COPY batches, deterministic by seed.
- **Search and sort indexes** (migration 0011, `pg_trgm`), account and loan searches
  rewritten so each table's index is used, and `code_prefix` on the chart of accounts
  (the General ledger's cash-account list uses it).
- **Measured at one million customers** (below), which is the first part of Milestone A's
  exit test.

## Phase 13: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 304 passed (new: 5 bulk-loading tests — bulk and single postings agree, replays, a conflicting key refuses the batch, rules applied to the whole batch, the database refusing an unbalanced COPY with the Python checks off, a complete four-eyes population with balances matching its deposits and seed-determined names, the loader's refusals; 2 search tests — account search by number or name, an escaped code prefix) |
| Migration 0010 → 0011 → 0010 → 0011, `alembic check` | clean; 13 s to build the indexes on one million customers |
| Frontend typecheck, Vitest, build | clean; 75 passed; succeeds |
| Playwright (Chromium, real backend, fresh database) | 16 passed |

Measured in the development container:

| Measurement | Result |
| --- | ---: |
| Posting 10,000 entries: single / bulk | 227 / 4,204 entries per second |
| Loading 1,000,000 customers (5 countries, batches of 10,000) | 1,193 s, 838 per second (about 920/s at the start, 800/s at the end); database 2.2 GB |
| Full reconciliation over 1,000,312 entries / 2,000,624 lines | 34.6 s, passed |
| Incremental reconciliation over 40,000 recent entries | 1.1 s, passed |

API at one million customers (median of five, including authentication and JSON):

| Request | Before 0011 | After |
| --- | ---: | ---: |
| Customers, first page / search by name / by number | 24 / 218 / 655 ms | 27 / 43 / 25 ms |
| Accounts, first page / exact number / customer name | 395 / ~440 / ~420 ms | 24 / 21 / 431 ms |
| Account requests, first page | 532 ms | 27 ms |
| Cash accounts (General ledger) | 257 ms (`q=1000`) | 6 ms (`code_prefix=1000-`) |
| Journal entries, first page; analytics overview | 38; 27 ms | 38; 29 ms |

Broad substring searches that match a large share of a table (a common surname, a
fragment every account number shares, `q=1000` on the chart of accounts) still take
0.4–0.8 s; trigram indexes help selective searches, not those.

## Phase 12: what exists

- **Roadmap** ([roadmap.md](roadmap.md)): the remaining work towards the long-term vision,
  in milestones A–H with exit tests. Phase 12 is the first step of Milestone A.
- **Stored balances** (`ledger_balances`, migration 0010): running debit and credit totals
  per account in eight shards, maintained by a trigger on every journal line in the same
  transaction, guarded against any other write, backfilled from existing lines. All
  balance reads (accounts, payments, loans, servicing, the chart of accounts) use them.
- **Incremental reconciliation** (`POST /api/v1/ledger/reconciliation?mode=incremental`):
  the entries posted since the previous run (10-minute overlap), the trial balance from
  the stored totals and the stored balances of up to 500 touched accounts. Full runs also
  compare every account's stored totals with its lines.
- **Reconciliation history** (`ledger_reconciliations`, `GET /api/v1/ledger/reconciliations`):
  every run, its mode, result, failed checks and duration; shown under the General ledger.
- **Benchmark** (`python -m app.cli bench-ledger`): posts synthetic entries through the
  normal ledger service and times balance reads and reconciliation.

## Phase 12: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 297 passed (new: 4 — stored balances follow 40 postings and a reversal and match the line sums across shards; direct insert / update / delete / truncate refused; full and incremental runs recorded, listed and readable, incremental window after the previous run; a drifted stored balance caught by both modes) |
| Migration 0009 → 0010 on a copy of the seeded dev database | backfill matches the lines for all 127 accounts; downgrade and upgrade clean; `alembic check` clean |
| Frontend typecheck, Vitest, build | clean; 75 passed; succeeds |
| Playwright (Chromium, real backend, fresh database) | 16 passed; the banking journey now runs a full and an incremental reconciliation |
| Docker Compose stack | `validate_system.py` 10/10 (migration head 0010, v0.12.0); `bench-ledger` in the container: balances agree, both modes pass |

Measured with `bench-ledger` in the development container (5,001 accounts, 100,000 entries,
half of all lines on one hot account; medians):

| Measurement | Before (sum of lines) | After (stored totals) |
| --- | ---: | ---: |
| Balance of the hot account (49,985 lines) | 7.66 ms | 0.56 ms |
| Balances of 200 ordinary accounts (~20 lines each) | 5.21 ms | 5.33 ms |
| Reconciliation after 1,000 new entries on a 103,312-entry ledger | 1,006 ms (full) | 88 ms (incremental) |
| Posting rate, trigger on / off (two runs each, 5,000 entries) | 203 / 210 entries/s off | 207 / 184 entries/s on |

Stored totals keep a busy account's balance read constant as its history grows; ordinary
accounts with few lines gain nothing. The trigger's cost is within run-to-run noise; the
posting rate (about 200 entries per second) is set by the per-entry ORM and audit work, the
next item of Milestone A.

## Phase 11: what exists

- **AGB Credit Underwriting Assistant** (`rule_based_credit_underwriting`, registered by
  the seed for WF-0003): declared income against the bureau's income estimate, bureau
  file and affordability → risk, explanation, approve / reject / escalate. New grantable
  action `analyze_credit_application`; `approve_loan` stays forbidden.
- **Synthetic income estimate** (`lending.income_estimate`): a deterministic monthly
  income per synthetic person, like the bureau score.
- **WF-0003 v2:** income verification, an advisory AI step for referred applications
  (off / assisted / automated) and the `low-risk-loan-underwriting-v1` policy. Live
  applications run v2 with AI off.
- **`loans:approve_low_risk`** (policy engine only): the lending service lets it
  underwrite loans up to 15,000 that need no committee, and nothing else; the simulation's
  control check applies the same rule.
- **`personal-loans` v2** with AI modes, so experiments run on loans; v1 is unchanged.
- **UI:** the AI Lab console offers the assistant a sample referred application.

## Phase 11: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 293 passed (new: 6 — the assistant's rules and blind spot, v2 income check with AI off, automated underwriting of small clean loans only (inflated income, above the automation limit and self-employed go to a person), the lending service limiting the policy engine to the automation limit, scenario v2 against its workload, an automated experiment that rejects every inflated income and is evaluated successful with no violations) |
| Ruff lint + format check; `alembic check` | clean (no schema change in Phase 11) |
| Frontend typecheck, production build | clean; succeeds |
| Vitest | 75 passed (new: the AI Lab console offers the assistant a referred loan application) |
| Playwright (Chromium, real backend, fresh database) | 16 passed |
| Docker Compose stack | `validate_system.py` 10/10 (v0.11.0); seed registers the assistant; an AI-automated `personal-loans` v2 run completes in the container |
| Experiments (seed 42, 100 / 25) | assisted and automated both successful — see [ai-testing.md](ai-testing.md) |

## Phase 10: what exists

- **Repayment schedules** (`loan_instalments`): level monthly instalments from one month
  after disbursement (due days past the 28th move to the 28th), interest rounded half up,
  the last instalment takes the remaining principal. Created at origination; migration
  0009 backfills existing loans.
- **Servicing runs** (`loan_servicing_runs`, `POST /api/v1/loans/servicing-runs`, CLI
  `service-loans`): accrue interest on each due date (interest receivable → interest
  income), collect whole instalments oldest first from the borrower's account (deposit →
  interest receivable + loan receivable), leave the rest due. Idempotent per instalment;
  the business date never goes backwards; one run at a time (advisory lock); a summary
  per run (accrued, collected, missed, repaid, arrears per currency, buckets).
- **Arrears:** days past due from the oldest unpaid due date, buckets current / 1-29 /
  30-59 / 60-89 / 90+, and the overdue amount on every loan.
- **Repayment and payoff** (`loans:repay`, Idempotency-Key required): repay the oldest
  overdue instalments; pay the loan off early for outstanding principal plus accrued
  interest (checked against the receivable balance first). The final instalment or a
  payoff closes the loan as `repaid`.
- **Write-off:** at 90+ days past due, by `loans:approve_large`: remaining principal and
  accrued interest → loan losses; status `written_off`.
- **WF-0004 Loan Collections:** opened by servicing at 30 days past due, sends a simulated
  arrears letter, closes as cured when the arrears are paid, and at 90 days escalates to a
  four-eyes credit-committee write-off review.
- **Permissions:** `loans:repay` (front office), `loans:service` (department managers);
  `loans:approve_large` now also covers write-offs.
- **UI:** the Lending screen shows the business date, runs servicing, lists recent runs,
  shows status and arrears per loan, and opens a loan's schedule with repayment, payoff
  and its collections cases.
- **Engine fix:** `workflow_step_runs.duration_ms` is BIGINT (a wait of weeks overflowed
  a 32-bit millisecond count).

## Phase 10: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 287 passed (new: 12 servicing tests — schedule maths, due-date capping and buckets, schedules at origination, accrual and collection posted once per instalment, monotonic business date, arrears and DPD, oldest-whole-instalment collection, idempotent repayment and its funds and count checks, payoff of principal plus accrued interest, the last instalment closing the loan, write-off authority and 90-day rule, permissions and idempotent runs; 4 WF-0004 tests — case at 30 days, one case per loan, cure on repayment, 90-day escalation with four-eyes write-off, declined write-off reopened by the next run, a loan repaid during the review closing as cured) |
| Ruff lint + format check | clean |
| Alembic 0008 → 0009 → 0008 → 0009 on a seeded database, `alembic check` | clean; backfill verified on 17 existing loans (708 instalments match the schedule maths; ledger reconciles) |
| Frontend typecheck, production build | clean; succeeds |
| Vitest | 74 passed (new: servicing panel, run to a date with an Idempotency-Key, arrears in the loan list, schedule, repayment and payoff with distinct keys, actions hidden without the permissions) |
| Playwright (Chromium, real backend, fresh database) | 16 passed, including the new servicing journey (a manager moves the business date; a teller, who cannot run servicing, pays a loan off and the schedule closes) |
| Docker Compose stack | `validate_system.py` 10/10 (migration head `0009_loan_servicing`, v0.10.0); `service-loans` CLI in the container; Playwright 16 passed against the stack |
| Visual review | Lending with servicing and a loan in arrears with its collections case at 1440 px ([images](images/)) |

## Phase 9: what exists

- **Payments module** (`payments` table, `GET /api/v1/payments`): the payments service is
  the only code that moves money between customer accounts. It re-checks open accounts,
  currency, funds (under row locks taken in id order), four-eyes and the high-value
  approval rule for every caller, and posts one balanced ledger entry.
- **Lending module** (`loans` table, `GET /api/v1/loans`): a deterministic synthetic credit
  bureau, risk-based pricing by score band, level-instalment amortization,
  debt-to-income, and `originate`, which re-checks KYC, ownership, limits, underwriting
  authority, four-eyes and the credit committee rule, then posts loan receivable →
  customer account. Outstanding balances come from the ledger.
- **WF-0002 Domestic Payment:** validation, funds check, fraud and sanctions screening,
  straight-through release of clean payments, fraud review of held payments, four-eyes
  approval of high-value payments, an optional AI fraud screener (off / assisted /
  automated) with a policy engine that may release low-risk holds.
- **WF-0003 Personal Loan Origination:** validation, bureau check, pricing and
  affordability, automatic credit-policy declines, underwriting and a credit committee
  above 25,000, disbursement.
- **AGB Payment Fraud Screener** (`rule_based_payment_screening`), registered by the seed;
  `release_payment` and `approve_loan` join the actions no tool can be granted.
- **Permissions:** `payments:read`, `payments:review` (compliance), `payments:approve`
  (managers), `payments:release_low_risk` (policy engine), `loans:read`, `loans:approve`
  (managers), `loans:approve_large` (regional and global executives).
- **Workflow-neutral platform:** presenters name cases in the task inbox and execution
  lists (`subject` replaces `applicant`); the simulation runner and the experiment
  measurements work through **workloads**; new scenarios `domestic-payments` v1 (with AI
  modes) and `personal-loans` v1, each with a pre-existing customer population and known
  ground truth; experiments run on any scenario with AI modes.
- **UI:** Payments and Lending screens; start dialogs for payments and loan applications
  in the Workflow Explorer; scenario choice in Experiments; the AI Lab console offers a
  payment sample to the fraud screener.
- **Seed:** 10 payments and 6 loan applications between the seeded customers, leaving a
  scam in the fraud review queue and applications waiting for an underwriter.

## Phase 9: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 266 passed (new: 9 WF-0002, 8 WF-0003, 7 workload tests — straight-through, high-value four-eyes, scam stopped, hold cleared, watchlist, invalid and unfunded payments, funds re-checked under the lock, service controls for every caller, automated release that never releases scams, bureau and pricing, underwriting, committee, policy declines, payment and loan runs, reproducibility, tampered-release detection, the screener experiment) |
| Ruff lint + format check | clean |
| Alembic 0007 → 0008 → 0007 → 0008, `alembic check` | clean |
| Frontend typecheck | clean |
| Vitest | 69 passed |
| Production build | succeeds; no chunk-size warning |
| Playwright (Chromium, real backend, fresh database) | 15 passed, including the new WF-0002 journey (scam held, a manager cannot clear it, the analyst rejects it, no money moves) |
| Visual review | Payments, Lending, WF-0002 in the Workflow Explorer, the task inbox at 1440 px ([images](images/)) |

## Phase 8: what exists

- **Analytics API** (`GET /api/v1/analytics/overview`, `analytics:read` for every role):
  employees (enterprise vs. simulated staff), configured countries, registered
  workflows, active simulation runs, completed and failed workflow executions (live, with
  simulated counts alongside), customer accounts (with the share opened by simulations),
  AI tools, completed experiments, average process duration and the estimated
  simulation operating cost (default assumptions, flagged as an estimate; computed with
  the experiment engine's cost function and cross-checked against it in tests)
- **Enterprise Overview:** every metric as a tile linked to its screen, live execution
  outcomes and open tasks, recent simulation runs and experiments, platform health, and
  visible synthetic-data and estimate labels
- **System Settings:** platform health, build, database and module registry; users
  (people vs. service accounts, search, create with validation, change role,
  activate/deactivate — service accounts keep their role; service roles are never
  offered to people); the role and permission matrix
- **Navigation complete:** every entry links to a working screen; feature screens
  load on first visit (initial bundle 303 kB, from 507 kB)
- **End-to-end demonstration** (Part 12) automated as a Playwright test and documented
  with screenshots in [demo.md](demo.md)

## Phase 8: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 238 passed (5 analytics/settings tests, incl. a cross-check of the dashboard cost estimate against the experiment engine) |
| Ruff lint + format check | clean |
| `alembic check` (no schema change in Phase 8) | clean |
| Frontend typecheck | clean |
| Vitest | 63 passed |
| Production build | succeeds; no chunk-size warning (route-level code splitting) |
| Playwright (Chromium, real backend + DB) | 14 passed — fresh local database (twice) and Docker Compose; includes the Part 12 demonstration and the System Settings user journey |
| `validate_system.py --login auditor` (Docker) | 14/14 |
| Visual review | Overview, Settings, Experiments, Benchmarking at 1440 px and 390 px (no horizontal scroll) |

## Phase 7: what exists

- **Experiment model** (`experiments`) linking a baseline and a candidate run, tool and
  version, resolved configuration (cost assumptions + thresholds) and status; created by
  running both modes on one seeded workload, or from two existing equivalent runs
- **Raw measurements** (`experiment_measurements`) read from what runs recorded — case
  results, workflow history, AI invocations and the account decisions, which are
  re-checked against the authorization rules (policy violations) — stored apart from
- **derived evaluations** (`experiment_evaluations`): a pure, digest-checked function of
  the measurements and configuration: cost lines (review labour, oversight of automation,
  AI execution, infrastructure, exceptions, escalations; risk exposure separately), 14
  compared metrics with improvement and regression flags, six success criteria
  (equivalent workloads, measurable improvement, acceptable correctness, compliance
  thresholds, effective authorization controls, complete costs), verdict, conclusion
  and limitations
- **Reports:** downloadable Markdown proof-of-concept report and JSON; re-evaluation
  proves the result reproduces; `/benchmarks` aggregates experiments by tool version
- **UI:** Experiments (create with editable assumptions and thresholds, live status,
  evaluation, report download, re-evaluate) and Benchmarking (tool comparison,
  processing-time and cost charts with table views, quality and compliance, conclusions)
- `validate_system.py` re-evaluates every evaluated experiment of a running stack

## Phase 7: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 233 passed (20 benchmarking tests: hand-checked cost lines and metrics, regression detection, thresholds, complete costs, authorization violations, workload equivalence, determinism, API, reproducibility, re-pricing, policy-violation detection from tampered records, failed runs, reports, benchmarks, permissions) |
| Ruff lint + format check | clean |
| Alembic 0006 → 0007, base ↔ head, `alembic check` | clean |
| Frontend typecheck | clean |
| Vitest | 57 passed |
| Production build | succeeds |
| Playwright (Chromium, real backend + DB) | 12 passed — fresh local database (twice) and Docker Compose |
| Docker Compose: upgrade 0006 → 0007, seed in container | succeeds |
| `validate_system.py --login auditor` (Docker) | 14/14, incl. experiment re-evaluation |
| Example experiment, 100 applications, seed 42, automated mode (local) | successful: labour −77 %, cost per case −70 %, no regressions; the fault injector in assisted mode is not successful (15 % errors) |

## Phase 6: what exists

- **AI tool registry** (`ai_tools`): versioned tools with JSON Schema input/output
  contracts, allowed actions, caller permissions, compatible workflows, adapter-validated
  configuration and status; registration refuses never-delegable actions (approve or open
  accounts, KYC decisions, ledger postings…), invalid schemas and invalid configuration
- **Adapter contract:** async `AIToolAdapter.execute(request, context)` with typed
  request/result, structured `ToolError`; one invocation service enforces allowed actions
  and status, validates input and output against the registered schemas, applies the
  timeout and records every call (`ai_tool_invocations`) with status, duration and usage
- **AGB Intelligent KYC Assistant** (rule-based proof of concept): missing and
  inconsistent fields, risk classification, explanation, approve/reject/escalate; plus a
  reproducible **fault injector** for failure testing
- **WF-0001 v2:** advisory `ai_kyc_review` step (off / assisted / automated) with safe
  escalation on any tool failure; `policy_approval` step — the workflow policy engine —
  approves only low-risk, unflagged, verified cases the tool recommends; the
  `automated_policy` system principal can approve low-risk customers only (enforced by the
  accounts service), cannot sign in, and its role cannot be given to people
- **Experiments A/B/C:** scenario `retail-onboarding` v2 runs baseline, AI-assisted and
  AI-automated modes on the same seeded applications and staff; suites run them back to
  back; AI-assistance effects on reviewers are explicit, stored assumptions; results
  report invocations, failures, recommendations, recommendation accuracy and policy
  approvals per run and per case
- **API:** `/api/v1/ai-tools` (registry, adapters, actions, invocations, test-console
  invoke, enable/disable) and `/api/v1/simulations/suites`; permissions `ai_tools:read`
  (every role), `ai_tools:manage` and `ai_tools:invoke` (AI researcher, administrator)
- **UI:** AI Innovation Lab — tool registry, capabilities and schemas, registration form
  (never-grantable actions shown disabled), test console, recorded invocations, experiment
  configuration on compatible workflows, side-by-side run results linking to the
  Simulation Center (which now shows modes, tools and AI behaviour)
- **Demo data:** the KYC assistant and the fault injector are registered by `make seed`;
  `python -m app.cli simulate --mode ai_assisted --tool agb-intelligent-kyc-assistant`

## Phase 6: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 213 passed (39 AI Innovation Lab tests) |
| Ruff lint + format check | clean |
| Alembic 0005 → 0006, base ↔ head, `alembic check` | clean (also upgraded a database holding a 10,000-case run) |
| Frontend typecheck | clean |
| Vitest | 53 passed |
| Production build | succeeds |
| Playwright (Chromium, real backend + DB) | 11 passed — fresh local database (twice) and Docker Compose |
| Docker Compose: upgrade of the Phase 4 database volume to 0006, seed in container | succeeds |
| `validate_system.py --login auditor` (Docker) | 13/13, incl. simulation reproducibility across 5 runs |
| A/B/C suite, 100 applications, seed 42 (local) | completed; same applications in all modes; see ai-testing.md |
| Mutation check: low-risk guard removed from the accounts service | the policy-limit test fails |

## Phase 5: what exists

- **Simulation clock** (forward-only, timezone-aware, fixed scenario start), **scenarios**
  (versioned: workflow, application mix with ground truth, arrival window, document
  delays, reviewer time and accuracy, staff mix) and **workload profiles** (small 100/25,
  department 10,000/500, custom up to 10,000/500; enterprise 1,000,000 customers / 150,000
  staff as an unverified configuration target that the API refuses to run)
- **Generators:** synthetic applications (eight case types, from clean to forged and
  sanctions hits) and synthetic staff, each draw from a per-case stream derived from the
  seed; no personal information
- **Runner:** discrete-event loop driving the real WF-0001 engine on simulated time —
  tellers start cases, approvals queue to reviewer pools with lognormal review times and
  seeded accuracy, late documents arrive as signals, timeouts fire at their due time;
  progress and heartbeat committed every 250 events
- **Run registry:** every run stores scenario and workflow versions, profile, seed, the
  fully resolved configuration and its hash, the software version, timing, progress,
  results, a result digest and per-case results against ground truth; failed runs record
  their reason; interrupted runs are detected; one run at a time; rerun and
  reproduction comparison
- **Simulated staff** are real employees in a per-run team with service-account users
  that cannot sign in, so permissions and four-eyes rules apply to them
- **Isolation:** simulated executions carry `simulation_run_id` and are excluded from the
  live task inbox, workflow metrics, the timer sweep and default execution listings
- **API:** scenarios, profiles, start (background), list, detail, cases, rerun;
  `simulations:read` (every role) and `simulations:run` (AI researcher, administrator)
- **CLI:** `python -m app.cli simulate` / `make simulate`
- **UI:** Simulation Center — scenario, workload and seed selection, start, live progress,
  outcomes, decision accuracy, case types, execution statistics, reproducibility,
  per-case results with a ground-truth mismatch filter, rerun
- `validate_system.py --login …` also checks that every repeated configuration of a
  running stack produced identical results

## Phase 5: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 174 passed (24 simulation tests) |
| Ruff lint + format check | clean |
| Alembic 0004 → 0005, base ↔ head, `alembic check` | clean |
| Frontend typecheck | clean |
| Vitest | 48 passed |
| Production build | succeeds |
| Department profile (10,000 / 500), local | 10,000 cases completed in 35 min 16 s (4.7 cases/s) |
| Playwright (Chromium, real backend + fresh DB) | 10 passed (twice) |

## Phase 4: what exists

- **Engine:** versioned, validated, immutable definitions with nine step types (service
  task, human task, approval, decision, parallel/join, wait, AI task, completion, failure)
  and a safe structured condition language; durable execution in PostgreSQL with atomic
  steps (handler effects and state change in one savepoint), execution-row locking against
  duplicate execution, retries with exponential backoff, failure routing, timeouts (flag or
  transition), signals, cancellation, step-level timing, append-only history and audit
- **Resumption:** `run_due` / `python -m app.cli run-workflows [--watch]` (`make workflows`)
  resumes due steps and applies timers after a restart, one execution per transaction,
  skipping executions other workers hold
- **WF-0001 Retail Account Opening:** validation, document wait (72 h timeout), customer
  registration, parallel identity verification and sanctions screening, risk rating,
  compliance rules, routing, compliance review or authorized approval (both four-eyes, with
  overdue flags), account opening through the Phase 3 services, rejection, finalized audit
  record and a simulated customer notification
- **API:** definitions, metrics (bottleneck analysis), start (idempotent), executions,
  history, signals, resume, cancel, task inbox and task completion
- **UI:** Workflow Explorer — catalogue with steps, routes, policies and per-step metrics
  (bottleneck highlighted); start-application form with valid synthetic documents; executions
  with step timeline, errors, context and history; task inbox with four-eyes explanations;
  document submission for waiting cases
- **Demo data:** 20 WF-0001 cases run through the engine (approved, rejected, waiting for
  documents, waiting for approval or compliance review)

## Phase 4: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 150 passed (35 workflow tests) |
| Ruff lint + format check | clean |
| Alembic 0003 → 0004, base ↔ head, `alembic check` | clean |
| Frontend typecheck | clean |
| Vitest | 43 passed |
| Production build | succeeds |
| Playwright (Chromium, real backend + DB) | 8 passed, local (twice) and against Docker Compose |
| Docker Compose: upgrade of the Phase 3 database, seed and runner in container | succeeds |
| `validate_system.py --login auditor` | 12/12 (local and Docker) |
| Restart/resume and four-thread duplicate-execution tests (committed sessions) | pass (3 repeated runs) |

## Phase 3: what exists

- **Customers:** synthetic individuals and businesses; onboarding only in active
  countries; KYC transitions (not_started → pending → verified/rejected, re-review back to
  pending) and risk ratings decided only by `customers:review` holders; verification
  requires a rating
- **Account opening:** request → approve/reject. Approval is the only way an account is
  created; four-eyes (service + DB CHECK); high-risk customers need a compliance approver;
  eligibility (KYC verified, rated, type matches customer type, 18+, active country,
  domestic currency, no duplicate) checked at request and again at approval; one request
  opens exactly one account
- **Accounts:** check-digit account numbers; balances derived from the ledger; deposits and
  withdrawals (Idempotency-Key required, no overdrafts, row lock against races);
  freeze/unfreeze/close (zero balance)
- **Ledger:** double-entry with integer minor units; balanced, single-currency entries
  enforced by the service and by deferred database triggers; immutable lines; reversals by
  opposite entry; idempotent postings (replay or 409); statements; reconciliation report
- **Permissions:** 10 new permissions; tellers request and transact, managers approve and
  control accounts, compliance reviews KYC and approves high-risk, auditors read the ledger
- **Demo data:** 150 customers across 5 countries with mixed KYC outcomes, 120 accounts
  opened through real approvals, 14 pending requests and 304 ledger postings — identical
  for the same seed (verified locally and in Docker)
- **UI:** Customers (search, filters, onboarding, KYC review, eligibility, account request)
  and Accounts (accounts with ledger balance and history, deposit/withdraw with
  retry-safe idempotency keys, controls; opening-request queue with four-eyes; general
  ledger with reconciliation, cash accounts and journal)
- `validate_system.py --login auditor` also reconciles the ledger of a running stack

## Phase 3: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 115 passed |
| Ruff lint + format check | clean |
| Alembic 0002 → 0003, base ↔ head, `alembic check` | clean |
| Frontend typecheck | clean |
| Vitest | 38 passed |
| Production build | succeeds |
| Playwright (Chromium, real backend + DB) | 7 passed, local (twice) and against Docker Compose |
| Docker Compose: upgrade of the Phase 2 database, seed in container | succeeds |
| `validate_system.py --login auditor` | 12/12 (local and Docker) |
| Concurrency: race test fails with the withdrawal row lock removed | 5/5 runs fail without the lock, 5/5 pass with it |

## Phase 2: what exists

- **Identity:** sign-in with salted-scrypt passwords and short-lived JWTs; 8 roles mapped
  to 10 permissions in code; every `/api/v1` route enforces a permission on the server;
  users API; `python -m app.cli create-user`
- **Countries:** registry validated against ISO 3166 / ISO 4217 / IANA formats; US, GB, DE,
  SG, JP seeded and active; holds the 120-country target without schema changes
- **Organizations:** six-level hierarchy with enforced parent types, a single global bank,
  one subsidiary per country, inherited region and country, unique sibling names, and
  activation rules
- **Employees:** placement in departments or teams (department derived), synthetic emails
  and numbers, compensation in integer minor units of the country's currency (hidden
  without permission), manager validation with cycle prevention, direct-report and
  reporting-chain queries, termination rule
- **Audit:** append-only `audit_events`, enforced by database triggers; actor, correlation
  ID and redacted change diffs on every important change and every sign-in attempt;
  read-only, filterable API
- **Shared plumbing:** domain errors, pagination, `Idempotency-Key` support on all create
  endpoints, currency minor units, seeded synthetic name generator
- **Demo data:** `make seed` builds 64 organizations, 120 synthetic employees and one sign-in
  per role, deterministically for a given seed
- **UI:** sign-in page, session handling (outage-tolerant), role-aware navigation,
  Organization (lazy tree + details + add/rename/deactivate), Countries (registry + add +
  status), Employees (search, filters, pagination, profile with reporting lines, hire and
  edit), Audit Center (filters, expandable metadata)

## Phase 2: verified results

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 84 passed |
| Ruff lint + format check | clean |
| Alembic 0001 → 0002 → base → head, `alembic check` | clean |
| Frontend typecheck | clean |
| Vitest | 29 passed |
| Production build | succeeds |
| Playwright (Chromium, real backend + DB) | 6 passed, against local processes and against the Docker Compose stack |
| Docker Compose: upgrade of an existing Phase 1 database, seed in container | succeeds |
| `validate_system.py` | 10/10 (local and Docker) |

## Phase 1: what exists

- FastAPI backend with typed configuration, a shared SQLAlchemy engine and per-request
  transactions, JSON structured logging, correlation IDs, a consistent error envelope, CORS
  and typed DI aliases
- Alembic configured, with baseline migration `0001_platform_baseline`
- `GET /api/health`, `GET /api/system/info`, `GET /api/system/status`, OpenAPI at `/api/docs`
- React + TypeScript + Vite + Tailwind app shell: global navigation (unbuilt screens
  disabled and labelled by phase), live Overview page, backend-unavailable state with retry,
  not-found page, responsive layout
- Docker Compose stack (PostgreSQL, Redis, backend, frontend); backend migrates on start
- `scripts/validate_system.py` for live end-to-end checks of a running stack
- GitHub Actions CI: backend lint and tests, frontend typecheck/tests/build, Playwright

## Phase 1: verified results (at the end of Phase 1)

| Check | Result |
| --- | --- |
| Backend pytest (real PostgreSQL) | 22 passed |
| Ruff lint + format check | clean |
| Frontend typecheck | clean |
| Vitest | 10 passed |
| Production build (`vite build`) | succeeds |
| Playwright (Chromium, real backend + DB) | 3 passed, against both local processes and the Docker Compose stack |
| `validate_system.py` against Docker Compose stack | 9/9 checks passed |
| Alembic upgrade → downgrade → upgrade, `alembic check` | clean |

## Known limitations

- Accounts are domestic-currency only; there is no FX, interest, fees, or statements
  beyond posted lines. Payments are between accounts at ATLAS in one currency; there is no
  external clearing, scheduling, standing orders or recall.
- Loan servicing is monthly and simplified: interest accrues in full on each due date (no
  daily accrual between due dates), a payoff settles outstanding principal plus interest
  already accrued (no interest for the running period), partial instalments are not
  collected, and there are no late fees, payment holidays, restructuring or recoveries
  after a write-off. Instalments are collected only from the disbursement account. The
  lending business date moves only when someone runs servicing (no scheduler); in the
  dev database it can be moved past today, which then books repayments on that future
  date. The credit bureau is a deterministic function of name and date of birth.
- Workflow definitions are authored in code (registered at import); there is no visual
  designer or upload API. Four business workflows exist (WF-0001 to WF-0004).
- Live WF-0002 and WF-0003 cases run with AI off; the UI offers AI modes only through
  simulations and experiments. The income estimate behind the loan assistant is synthetic
  and more reliable than real income estimators.
- The default success thresholds were tuned for account opening; in `domestic-payments`
  even the baseline exceeds the 5 % maximum false approval rate (quiet scams), so
  experiments there fail the compliance-threshold criterion unless the thresholds are
  changed for the scenario.
- Simulation runs write into the same synthetic bank (customers, accounts, ledger postings
  and staff remain). Since Phase 15 a run's workflow history can be archived, restored or
  reset, but the domain records it created stay (the ledger is append-only). Restoring a
  large archive is slow (about 9 minutes for 100,000 cases). Request metrics are per API
  process and reset when it restarts; job, worker and slow-query figures come from the
  database and cover every process. Journal lines and the audit log are not partitioned
  yet (deferred until period close and an audit retention policy exist). Sharded runs
  (Phase 16) use separate teams per shard, so their queueing differs from a
  single-process run; at most 8 shards; suites and experiments run single-process. One
  process still runs about 6 cases/s (≈190 SQL statements per case); the engine's writes
  are not batched. Simulated reviewers work around the clock;
  arrivals are uniform. Since Phase 14 runs are durable jobs; a run whose worker stops is
  still reported as interrupted and is not resumed (`simulation.execute` is not retried).
  See [simulation.md](simulation.md) for measured throughput and why the enterprise
  profile is only a target.
- Schedules fire only while a worker runs (`make worker`, or the Docker Compose worker);
  intervals are fixed periods from the last run, not calendar times (no cron expressions,
  no business calendars).
- The only AI tool implementation is rule-based; no external model provider is connected
  (an adapter for one implements the same contract). Adapter timeouts cancel async work;
  CPU-bound synchronous code inside an adapter cannot be interrupted.
- The effect of AI advice on reviewers is an assumption of the scenario, not a measurement.
- Costs are estimates from illustrative default assumptions; experiments compare one
  baseline with one candidate on one seed (no repeated-seed statistics or confidence
  intervals yet). The cost model has no time-of-day, overtime or capacity costs.
- Live (non-simulated) WF-0001 cases run v2 with AI off; the UI does not offer AI modes for
  live cases.
- Simulated payers are one fresh customer per case, so the payment velocity signal never
  fires in simulations; it is covered by tests only.
- Human tasks are offered to everyone holding the permissions; there is no assignment to a
  named person, delegation or escalation routing beyond the overdue flag.
- Postings go one entry at a time through the ORM (about 200 entries per second in the
  development container); bulk loading for generated data is still to come (roadmap
  Milestone A). Since Phase 13 generated data loads in bulk (`load-population`) and other
  callers may use `ledger.post_entries`, but simulation runs still create their customers
  through the services. Reconciliation runs synchronously in the request: a full run over
  a million customers takes about 35 s, so it belongs in a background job (next step);
  incremental runs keep routine checks short.
- Broad substring searches (patterns most rows contain) take 0.4–0.8 s at a million
  customers; a dedicated search index is future work. Employee and user searches have no
  trigram indexes yet (those tables are small).

- Permissions are role-wide: a regional executive or department manager is not yet limited
  to their own region or department.
- No login rate limiting or account lockout yet; failed attempts are audited.
- Access tokens cannot be revoked individually before expiry (deactivating the user or
  changing their role does take effect immediately). No refresh tokens.
- Organizations cannot be moved to a different parent. Employees cannot transfer between
  countries (rejected, because compensation is held in the country's currency and the
  platform has no currency conversion).
- Stored idempotency keys are never pruned.
- `app/core/events.py` (event dispatcher) is deferred to Phase 4, where workflows need it.
- Redis is connected and health-checked but not used by any feature yet.
- `scripts/reset_demo.py` does not exist; `python -m app.cli simulation-history reset`
  clears simulation workflow history, and `docker compose down -v` resets everything.
- Charts are built from plain HTML/CSS (no charting library); only paired-bar charts exist so far.
- The frontend Docker image runs the Vite dev server; a production static image is not yet
  defined.
