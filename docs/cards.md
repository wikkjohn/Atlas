# Cards

Phase 31 (roadmap Milestone D, step 3). The cards department covers:
- debit cards issued on current accounts;
- purchases from a synthetic merchant terminal, checked against limits, funds and fraud
  rules;
- fraud blocks and their release;
- disputes that end in a chargeback or a rejection.

Every amount moves through the ledger. Code: `backend/app/modules/cards/`.

## Products and cards

`card_products` holds each product's daily limit, in US dollars, and its validity.
Migration 0026 loads two:

| Product | Daily limit | Valid for |
| --- | --- | --- |
| ATLAS Debit (`debit-standard`) | US$1,500 | 4 years |
| ATLAS Debit Premium (`debit-premium`) | US$5,000 | 4 years |

The daily limit is converted to the account's currency at the synthetic FX anchor rates
and rounded to two significant figures, like the retail terms. The same products
therefore apply in all 120 countries.

**Card numbers are synthetic.** They are 16 digits: the prefix `9999`, which no real
scheme uses, an 11-digit serial and a Luhn check digit. The API and the page show them
masked (`9999 •••• •••• 1234`).

**Issuing.** A card is issued on an open current or business current account, at most two
live (not cancelled) cards per account. Tellers (`accounts:transact`) issue on the Cards
page, with `POST /cards`, or through WF-1006. Each issue is audited (`card.issued`).

## Authorisation

A purchase from the merchant terminal (`POST /cards/{id}/authorizations`) is checked in
this order. The first check that fails declines it, with that reason:

1. the card is active (`card_blocked`, `card_cancelled`) and not expired (`card_expired`);
2. the account is open (`account_not_open`);
3. today's approved purchases plus this one stay within the daily limit (`daily_limit`);
4. the account can pay: balance plus any arranged overdraft (`insufficient_funds`);
5. the fraud rules score below 70 (`fraud_suspected`).

An approved purchase is posted at once: the account is debited and the card settlement
account `CARD-SETTLEMENT-<ccy>` credited. A declined one records the attempt and moves no
money.

### Fraud rules

| Signal | Points | When |
| --- | --- | --- |
| `foreign_merchant` | 30 | the merchant's country is not the customer's |
| `high_risk_category` | 40 | gambling (7995), crypto and quasi-cash (6051), money transfer (4829) |
| `large_amount` | 20 | at least half the card's daily limit |
| `velocity` | 30 | five or more attempts on the card in the last hour |

A score of 70 or more declines the purchase **and blocks the card** (`fraud_suspected`).
So a purchase abroad at a gambling merchant is blocked, while a purchase abroad alone is
not. Every authorisation records its score and signals.

## Blocks

- **Blocking:** tellers block a card (`lost`, `stolen`, `customer_request`,
  `fraud_suspected`).
- **Releasing:** only a manager or compliance officer (`cards:manage`) releases a block,
  on the page, with `POST /cards/{id}/unblock`, or through WF-1008 after a fraud review.
- **Cancelling:** `cards:manage`; a cancelled card cannot be reactivated and no longer
  counts towards the two-card limit.

Blocks, releases and cancellations are audited.

## Disputes and chargebacks

A customer can dispute an approved purchase for 120 days, for the whole amount or part of
it. The reasons are `not_recognised`, `not_received`, `duplicate` and `wrong_amount`. A
purchase has at most one live dispute (open or refunded); a rejected dispute frees it for
another.

Someone other than the person who opened the dispute decides it (four-eyes, also enforced
by a database constraint), with `cards:manage`:
- **Charge back:** the amount is refunded: card settlement debited, the account credited.
- **Reject:** no money moves.

## The base processes (workflow factory)

| Workflow | Library handlers it adds | Effect |
| --- | --- | --- |
| WF-1006 Debit Card Issue | `cards.issue` | writes |
| WF-1007 Card Dispute and Chargeback | `cards.lookup_authorization`, `cards.open_dispute`, `cards.chargeback`, `cards.reject_dispute` | the chargeback moves money and requires an approval |
| WF-1008 Card Fraud Block Release | `cards.lookup`, `cards.unblock` | writes; the release requires an approval |

- WF-1006 picks the product with a decision on the request's `premium` flag.
- WF-1007 opens the dispute, then a reviewer with `cards:manage` other than the requester
  decides (`dispute_review`): upheld, it charges back; otherwise it rejects.
- WF-1008 finds the blocked card and releases it only after a fraud review.

`seed-demo` imports all three. Their generated path tests pass with 100 % step and route
coverage (WF-1006: 15 cases, WF-1007: 18, WF-1008: 17). The generated tests provide two
new fixture kinds on the fixture account: `blocked_card.card_number` (a card blocked for
suspected fraud) and `authorization.auth_code` (an approved purchase of 25.00 at a grocer).

## API and permissions

See [api.md](api.md) (*Cards*). Reading needs `accounts:read`. Issuing, blocking, the
terminal and opening disputes need `accounts:transact`. Releasing and cancelling cards and
deciding disputes need the new permission `cards:manage`, held by department managers and
compliance officers.

## Limitations

- Debit cards only: no credit cards, statements or repayments.
- Single-message authorisation: approval and settlement happen together, with no holds,
  clearing files or partial captures.
- Purchases are in the card's currency only.
- There is no cards workload in the simulation and no AI fraud tool yet (the next step,
  Phase 32).
