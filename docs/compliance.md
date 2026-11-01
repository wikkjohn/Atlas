# Compliance

Phase 45 (roadmap Milestone D, step 17). Compliance covers:
- anti-money-laundering (AML) transaction monitoring over customer accounts;
- alerts, and the cases that investigate them;
- suspicious activity reports (SARs), filed with a synthetic financial intelligence unit
  (FIU);
- periodic KYC reviews by risk rating.

Code: `backend/app/modules/compliance/`.

## Transaction monitoring

A monitoring run (`MON-`, `compliance:monitor`) reads the ledger activity of every open or
frozen customer account over a window (30 days by default, ending today). The activity it
reads:
- cash deposits (the ledger's `deposit` entries);
- money in (credits) and money out (debits) in total.

**The reporting threshold** is US$10,000, converted to each account's currency at the FX
anchor rate.

| Rule | Raised when | Score |
| --- | --- | ---: |
| `large_cash` | A cash deposit at or above the threshold | 40, plus 10 per deposit |
| `structuring` | Three or more cash deposits of 80–100 % of the threshold within ten days | 70, plus 5 per deposit beyond three |
| `rapid_movement` | Money in of twice the threshold or more, with at least 80 % of it out again | 60 |
| `high_risk_turnover` | A high-risk customer's money in of five times the threshold or more | 50 |

**Alerts** (`ALR-`) record what the rule saw: the deposits, totals and threshold. An account
with an open or investigated alert for a rule gets no second one for it, and a window that
already raised an alert (resolved or not) raises none again, so runs can be repeated.

## Alerts and cases

- **Dismiss:** an open alert can be dismissed as a false positive, with a note.
- **Investigate:** this opens a case (`CASE-`) for the customer, which takes in every open
  alert of theirs. If a case is being investigated for the customer, the alerts join it.
  While the customer's case has a drafted report, new alerts wait until it is filed (rule
  `report_pending`), so a filed report covers every alert it escalates. There is one case
  under way per customer, which is also a database constraint. Opening a case locks the
  customer first, so two officers investigating the same customer cannot deadlock.
- **Close with no action:** someone other than the investigator closes the case. This is
  also a database constraint, and the alerts are closed with it.
- **Escalate:** a suspicious activity report (`SAR-`) is drafted from the case's alerts,
  with the customer, the rules and the amounts, unless a narrative is given.

## Suspicious activity reports

A drafted report is filed by someone other than the officer who prepared it
(`compliance:file`). This is also a database constraint. Filing does three things:
- records the FIU reference (`FIU-<year>-<number>`);
- marks the case's alerts escalated;
- rates the customer high risk.

There is one report per case.

## Periodic KYC reviews

Verified, rated customers are reviewed periodically:

| Risk rating | Review every |
| --- | --- |
| High | 1 year |
| Medium | 2 years |
| Low | 3 years |

**Scheduling.** The interval runs from the last completed review, or from when the customer
joined. Scheduling (`compliance:monitor`) opens a review (`KYR-`) for every customer due
within a horizon (30 days by default) who has none open. There is one review due per
customer, which is also a database constraint. A review can also be opened on demand for any
verified, rated customer.

**Completing.** A review confirms, raises or lowers the customer's risk rating, and the next
one falls due by the new rating. Reviews past their due date are counted as overdue.

## The base processes (workflow factory)

| Workflow | Library handlers it adds | Effect |
| --- | --- | --- |
| WF-1027 AML Alert Investigation | `compliance.lookup_alert`, `compliance.open_case`, `compliance.close_case`, `compliance.draft_sar` | writes; closing requires an approval |
| WF-1028 Suspicious Activity Report Filing | `compliance.lookup_case`, `compliance.file_sar` | writes; filing requires an approval |
| WF-1029 Periodic KYC Review | `compliance.open_kyc_review`, `compliance.complete_kyc_review` | writes; completing requires an approval |

- **WF-1027** finds the alert and opens the case. Closing it with no action needs a second
  compliance officer's sign-off; without it, the case is escalated and a report drafted.
- **WF-1028** finds the case. If it has a drafted report, a second officer, not the
  preparer, approves filing it.
- **WF-1029** finds the customer and opens their review (the one due, or a new one). A
  second officer approves the outcome.

`seed-demo` imports all three. Their generated path tests pass with 100 % step and route
coverage (WF-1027: 15 cases, WF-1028: 11, WF-1029: 11). The generated tests add two fixture
kinds:
- `aml_alert.alert_number`: an open structuring alert on the fixture account, from three
  cash deposits of 90 % of the threshold;
- `compliance_case.case_number`: a case on another account with a drafted report.

## Simulation workload and AI tool (Phase 46)

The `alert_triage` workload drives WF-1027 v2 (scenario `alert-triage`).
- **Cases:** each case is a customer in one of the run's countries. Their account gets four
  months of dated deposits and withdrawals (`deposit` and `withdraw` accept an effective
  date). A real monitoring run then raises the alert. A second compliance officer decides
  every case.
- **Ground truth, close:**
  - a business banking its usual cash takings, four to eight times the threshold a month;
  - a one-off large deposit by an individual;
  - an individual whose salary is passed straight through every month.
- **Ground truth, escalate:**
  - structuring;
  - a funnel account: money passed through at many times its usual level;
  - a high-risk customer's turnover at four or more times usual;
  - a business's sudden spike of large cash deposits;
  - a business whose usual takings set off two or three earlier alerts in the year, closed
    as explained.
- **Decisions:** in AI-assisted runs the AGB Alert Review Assistant advises the officer,
  from the profile `compliance.alert_profile` reads. The profile covers:
  - the rule and the amount against the threshold;
  - the customer's type and risk rating;
  - the window's money in against the average month of the 90 days before it;
  - earlier alerts and filed reports.
- **Control check:** four-eyes and `compliance:monitor` on each decision, and no case closed
  without the sign-off.

What it measured, and the assistant's blind spot, is in [ai-testing.md](ai-testing.md).

## Workflow access

Compliance workflows disclose alerts and cases, so their handlers declare who may use them
through the workflow API:
- starting WF-1027, WF-1028 or WF-1029 needs `compliance:monitor`;
- listing, viewing or signalling their executions needs `compliance:read`.

Executions a caller may not read are left out of the execution list and reported as not
found. Compliance officers can start workflows (`workflows:start`). The engine itself (the
simulation and the generated tests) is not restricted.

## API and permissions

See [api.md](api.md) (*Compliance*).
- **`compliance:read`** (compliance officers and auditors): alerts, cases, reports and
  reviews. Other staff cannot see them.
- **`compliance:monitor`** (compliance officers): run monitoring, dismiss and investigate
  alerts, close cases, draft reports, and schedule and complete reviews.
- **`compliance:file`** (compliance officers): file others' reports.

## Limitations

- **Simple rules.** Four fixed rules over one account's activity at a time. There is no
  network analysis across customers, no peer-group profiling and no tuning by segment.
- **No sanctions rescreening.** Monitoring does not re-screen counterparties; payments are
  screened at the time they are made (see [country-rules.md](country-rules.md)).
- **Monitoring runs on request.** Nothing runs it on a schedule, and nothing restricts an
  account after a report is filed.
- **A synthetic FIU.** Filing records a reference; nothing is sent anywhere.
- **The seeded data is noisy.** The demo population's opening balances are cash deposits,
  so a first run on it raises many `large_cash` alerts.
- **Simulation scope.** The workload covers alert triage (`alert-triage`); monitoring runs,
  report filing and KYC reviews are not simulated.
- **Workflow tasks.** The approval inbox shows tasks to anyone holding the approval's
  permissions; for compliance workflows those are compliance permissions anyway.
