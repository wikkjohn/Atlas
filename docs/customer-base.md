# The customer base

Phase 72 (roadmap Milestone F, step 4). The customer generator fills the bank with a
realistic mix of synthetic customers, their products and the money they have moved. It
builds on the Phase 13 population loader: the same COPY path and the same end state for
every account. Everything is synthetic.

## The generator

`app/simulation/customers.py`: `generate(factory, count, seed, history_months, batch)`.

**Segments.** Each customer draws a segment by weight:

| Segment | Weight | Type | Ages (years) | Income or turnover a year (USD) | Products | Risk (low/medium/high) | Card payments a month |
| --- | --- | --- | --- | --- | --- | --- | --- |
| mass | 55 | individual | 25–64 | 22,000–60,000 | current; savings for 30 % | 85/13/2 | 4–9 |
| student | 8 | individual | 18–24 | 3,000–14,000 | current; savings for 5 % | 90/10/0 | 5–10 |
| affluent | 15 | individual | 30–64 | 60,000–200,000 | current; savings for 80 % | 80/18/2 | 8–14 |
| senior | 12 | individual | 65–92 | 14,000–45,000 (pension) | current; savings for 60 % | 92/8/0 | 3–6 |
| private | 2 | individual | 35–85 | 250,000–2,000,000 (log-uniform) | current and savings | 50/40/10 | 10–18 |
| sme | 8 | business | 1–40 since incorporation | 120,000–5,000,000 turnover (log-uniform) | business current | 60/32/8 | — |

Customers are spread evenly over the active countries. Amounts are set in US dollars and
converted to each country's currency at the FX anchor rates. Every customer is KYC-verified,
so they can hold accounts.

**Products.** These are the retail account types (Phase 29): current, savings and business
current. Each account has the same end state as one opened one at a time:
- an approved account request, requested by one person and decided by another (the
  database's four-eyes CHECK applies);
- its own liability ledger account;
- an account number with a valid check digit, in the country's currency.

**Transaction history.** It covers the last *n* whole months (0 to 24; 3 by default).
Opening balances are brought forward on the first day of the window, and each month adds:

| Customers | Movements a month |
| --- | --- |
| Individuals | salary (pension for seniors) on the 25th; housing on the 1st; two bills; card payments as above; a transfer to savings on the 26th for savers |
| Businesses | 4–8 customer receipts, 3–6 supplier payments, payroll on the 28th |

Each movement is a balanced journal entry through the ledger's bulk path (`post_entries`).
It is dated in its month (`effective_date`), and its category is the entry's source:
`history.salary`, `history.card` and so on. The balance and stored-balance triggers fire as
for any posting, and the books reconcile. A payment that would overdraw an account is cut
to the balance, so no account goes below zero.

**Repeatable and resumable.** Customer *i* of a seed is always the same person with the same
products and history (`case_random(seed, i, …)`). Customers carry the run that made them
(`customers.generated_from = customers-v1:<seed>`) and their segment (migration 0048). A
second run with the same seed creates only the customers still missing, so a large run
that stopped can be resumed, and a larger count continues where the last run ended.

## The summary

`summary(db)` reports:
- customers, and how many were generated;
- customers by segment, country and risk rating;
- accounts by product, and accounts per customer;
- history entries by category.

## API, CLI and page

| Where | What |
| --- | --- |
| `POST /api/v1/customers/population/generate` | `customers:manage`; `{count ≤ 50,000, seed, history_months ≤ 24}`. The caller requests the accounts and the seeded manager approves them (four-eyes). Refused in staging and production. |
| `GET /api/v1/customers/population/summary` | `customers:read`. |
| `python -m app.cli customers generate --count N --months M --seed S --batch B` | Any size (up to 5,000,000), with progress. Refused in staging and production. |
| `python -m app.cli customers summary` | The summary as JSON. |
| Customers page | The *Customer base* panel: the summary, and the generator for `customers:manage`. |

Customers list and detail show the segment.

## Measured

On the development container (PostgreSQL 16, one process), into a scratch database that was
seeded and then dropped:

| Run | Result |
| --- | --- |
| 1,000,000 customers, no history (seed 2032, batches of 5,000) | 1,519 s, 658 a second; 1,380,846 accounts (638,247 customers with one, 392,860 with two); 1,380,846 opening entries; database 3.9 GB. Segments: mass 549,469, affluent 149,657, senior 120,404, sme 80,170, student 80,074, private 20,226 |
| Reads at that size (median) | customer list page 85 ms; search by name 27 ms, by number 73 ms; the summary 1.6 s (5.9 s before its accounts-per-customer count stopped joining customers) |
| 20,000 customers, no history | 23.2 s, 862 a second |
| 100,000 customers with 3 months of history (seed 2033, batches of 500) | HISTORY100K_PLACEHOLDER |

**What history costs.** Each customer moves money about 35 times in three months, and every
movement is a journal entry with two lines. The ledger checks each row: entries must
balance (deferred constraint triggers), and stored balances are kept by a per-line trigger
that updates the account's balance row, including the bank's cash row, which every movement
touches. That holds history at about 2,000 entries a second. Building the base:

- without history runs at about 650–860 customers a second;
- with three months of history runs at about 55.

**Found on the way: bulk posting was quadratic.** The posting check computed
`account_ids - accounts.keys()`, which builds a set of every account in the batch for every
posting. A batch of 17,761 entries hashed 12.5 million UUIDs. It is now a membership test,
which halves the time of a history batch and speeds up every bulk posting.

## Known limitations

- **Deposit products only:** no generated cards, loans or mortgages yet. The lending, card
  and mortgage workloads create their own.
- **The bank's cash account** is the other side of every movement: there are no
  counterparty banks or customer-to-customer payments.
- **One currency per customer** (the country's), and no overdrafts.
- **History is costly:** the ledger's per-row integrity triggers cap it at about 2,000
  entries a second, so a million customers with three months of history (about 35 million
  entries) takes hours. Load the base without history and add history for a sample.
