# Payments operations

Phase 41 (roadmap Milestone D, step 13). Payments operations cover payments to accounts at
other banks through a simulated external clearing system:
- outgoing payments, with an approval for high value;
- clearing cycles that pay out or return each payment;
- bulk payment files;
- recalls.

Code: `backend/app/modules/clearing/`. The existing payments module (WF-0002) moves money
between accounts inside the bank; this module is for money leaving it.

## Beneficiary banks and accounts

The clearing system reaches six synthetic banks. Their names are invented for the simulation.

| Code | Bank |
| --- | --- |
| NBKAGB22 | Northbank Retail |
| RIVRUS33 | Riverside Savings |
| ALPEDEFF | Alpenland Sparkasse |
| KITSJPJT | Kitsune Shinkin |
| HARBSGSG | Harbourfront Bank |
| LACBFRPP | Lac Bleu Banque |

**Account numbers.** A beneficiary account is 14 digits: 12, then two check digits that are
the first 12 read as a number, modulo 97. For example, `123456789012` gives
`12345678901218`.

**Closed accounts.** The simulated banks have closed every account whose 12-digit number
ends in `00`. Payments to these accounts pass validation, but come back at settlement.

## Outgoing payments

A payment is refused unless:
- the payer's account is open;
- the bank is one of the six above;
- the account's check digits are right;
- a beneficiary is named;
- the amount is within the payer's country payment limits (see
  [country-rules.md](country-rules.md)).

Numbers are `OPY-` followed by eight digits.

- **High value:** at or above the country's high-value threshold, the payment waits for
  approval (`payments:approve`) by someone other than the person who entered it. This is
  also a database constraint.
- **Otherwise:** the payment waits for the next clearing cycle.

Approval moves no money. Either an approver or another officer can reject the payment
before clearing.

## Clearing cycles

A cycle (`payments:operate`) runs for one currency in two steps.

**1. Submission.** Every payment waiting for clearing goes into a batch (`CLB-`, oldest
first). Simulations and generated tests limit a cycle to the payments they made. Its payer is debited into the clearing suspense account `CLEARING-OUT-<CCY>`, a
liability. If the payer can no longer pay (counting any arranged overdraft), that payment
is rejected with code AM04 instead.

**2. Settlement.**

| Result | Debit | Credit |
| --- | --- | --- |
| Paid out (one entry per payment) | `CLEARING-OUT-<CCY>` | the bank's cash account `1000-<CCY>` |
| Returned, code AC04 (account closed) | `CLEARING-OUT-<CCY>` | the payer's account |

Each batch records how many payments it held, settled and returned. Submission locks the
payers' accounts in a fixed order, so two cycles cannot deadlock on them. Settling one
entry per payment keeps every ledger line within its limit, however large the batch.

**Closing a payer's account.** An account cannot be closed while one of its outgoing
payments could still come back to it: one not yet settled, one settled within the last
10 days (the longest recall window), or one with an open recall.

## Bulk payment files

A bulk file (`BLK-`) holds 1 to 500 lines, all from one account. Each line has a name, bank,
account, amount and reference.
- **Validation:** every line is checked like a single payment, and the reason a line fails
  is kept with it.
- **Funds:** the file is refused if no line is valid, or if the valid lines add up to more
  than the account can pay.
- **Release:** someone other than the person who received the file (`payments:approve`)
  releases it. Funds are checked again, and each valid line becomes a payment waiting for
  clearing. The file's approval covers high-value lines.
- **Rejection:** the same approver can reject the file instead.

## Recalls

A recall (`RCL-`) asks for a payment back. The reason codes are:
- DUPL: duplicate payment;
- FRAD: fraud;
- TECH: technical error;
- CUST: customer request.

There can be one open recall per payment, and none while the payment is in a clearing batch.

Someone other than the requester approves the recall (`payments:approve`), which is also a
database constraint.
- **Not yet cleared:** the payment is cancelled at once. Nothing had left the bank.
- **Settled:** the recall is sent to the beneficiary's bank. Operations
  (`payments:operate`) record the answer.

**The beneficiary bank's answer.** The money comes back while the recall is within the
reason's window after settlement:

| Reason | Window after settlement |
| --- | --- |
| DUPL, TECH | 10 days |
| CUST | 5 days |
| FRAD | 3 days |

Otherwise the recall is refused. A returned payment debits the bank's cash and credits the
payer. Payments, approvals, batches, files and recalls are audited.

## The base processes (workflow factory)

| Workflow | Library handlers it adds | Effect |
| --- | --- | --- |
| WF-1021 Outgoing External Payment | `clearing.create_outgoing`, `clearing.approve_outgoing`, `clearing.reject_outgoing` | writes; approval requires an approval step |
| WF-1022 Bulk Payment File | `clearing.receive_bulk`, `clearing.release_bulk`, `clearing.reject_bulk` | writes; release requires an approval step |
| WF-1023 Payment Recall | `clearing.lookup_outgoing`, `clearing.request_recall`, `clearing.approve_recall`, `clearing.withdraw_recall`, `clearing.resolve_recall` | moves money (the answer); approval requires an approval step |

- **WF-1021** enters the payment. A high-value payment goes to a second person, who approves
  or rejects it.
- **WF-1022** receives and validates the file, then a second person releases or rejects it.
- **WF-1023** finds the payment and records the recall. A second person approves it, which
  cancels the payment, or sends the recall and records the answer.

`seed-demo` imports all three. Their generated path tests pass with 100 % step and route
coverage (WF-1021: 13 cases, WF-1022: 11, WF-1023: 19). The generated tests add one fixture
kind, `outgoing_payment.payment_number`: a payment from the fixture account, settled
through a clearing cycle that day.

## Simulation workload and AI tool (Phase 42)

The `recall_triage` workload drives WF-1023 v2 (scenario `recall-triage`).
- **Cases:** each case is a business, in one of the run's countries, that has paid other
  banks. A beneficiary is a bank and an account, as in the recall profile. Its payments, earlier
  payments and earlier recalls run through the real clearing service, and a recall of one
  settled payment arrives on the day. Back office (simulated department managers with
  `payments:approve`) decides every recall.
- **Ground truth, send:**
  - a duplicate keyed twice the same day, recalled 1–6 days later;
  - fraud reported 0–1 days after settlement.
- **Ground truth, withdraw:**
  - a "duplicate" with no matching payment;
  - a fraud claim against a beneficiary paid 3–6 times before;
  - a customer request from a payer with 3–5 earlier recalls, all but one refused;
  - a technical recall 8–9 days after a high-value payment.
- **Decisions:** in AI-assisted runs the AGB Recall Assistant advises back office, from the
  profile `clearing.recall_profile` reads.
- **Control check:** four-eyes and authority on each decision, and no recall sent or
  answered without an approval.

What it measured, and the assistant's blind spot, is in [ai-testing.md](ai-testing.md).

## API and permissions

See [api.md](api.md) (*Payments operations*). Reading needs `payments:read`.
- **`accounts:transact`:** entering payments and bulk files, and requesting recalls.
- **`payments:approve`:** approving or rejecting high-value payments, files and recalls.
- **`payments:operate`** (department managers): running clearing cycles and recording
  recall answers.

## Limitations

- **One simulated clearing system.** There are no message formats (such as ISO 20022), cut-off
  times or settlement windows, and no nostro or correspondent accounts.
- **The beneficiary banks' behaviour is rule-based.** Closed accounts and recall windows are
  rules, and the banks never fail or delay.
- **No incoming payments.** Payments arriving from other banks, and their returns, are not
  modelled.
- **No automation.** Nothing runs clearing cycles automatically, and nothing answers sent
  recalls.
- **No screening.** Outgoing payments are not screened against the sanctions lists. The
  fraud screening of WF-0002 does not apply to them.
- **Simulation scope.** The workload covers recall triage (`recall-triage`); outgoing
  payments, clearing and bulk files are not simulated.
