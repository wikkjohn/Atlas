# Procurement and vendor management

Phase 57 (roadmap Milestone D, step 29). Procurement covers:
- vendors, screened against the sanctions lists, tiered by risk and approved by a second
  person;
- changes to a vendor's bank details, verified by a second person before anything is paid;
- purchase orders charged to a department, approved within limits, and received;
- vendor invoices matched against the order and what was received, then paid through the
  ledger by someone other than whoever recorded them.

Code: `backend/app/modules/procurement/`. Page: **Procurement** (`/procurement`,
`procurement:read`).

## Vendors

A vendor (`VEN-`, `procurement:manage`) has:
- a name, a country (which sets its currency), a category and a bank account;
- a **risk tier** from its category, one tier higher when its country is not one of the
  bank's active countries:

  | Category | Tier |
  | --- | --- |
  | Facilities, marketing | low |
  | IT, professional services | medium |
  | Outsourcing | high |

- a **screening** of its name against every sanctions list (Phase 25), stored with it.

A new vendor waits for approval (`procurement:approve`) by someone other than the registrant
(rule `four_eyes`, also a database constraint):
- a vendor that matches a sanctions list is never approved, not even by an executive (rule
  `sanctions_hit`); it can be rejected;
- a high-risk vendor is approved only by an executive, `procurement:approve_large` (rule
  `needs_executive`).

Only approved vendors are ordered from (rule `vendor_not_approved`).

## Bank-detail changes

A change of bank account (`procurement:manage`) is the classic route for invoice fraud, so:
- it waits, as a pending account, until someone other than the requester verifies or
  refuses it (`procurement:approve`, rule `four_eyes`, also a database constraint);
- while it waits, nothing is paid to the vendor (rule `bank_change_pending`);
- only one change waits at a time; a refused change leaves the account as it was.

Each payment records the account it was paid to, as it was on the day.

## Purchase orders

A purchase order (`PO-`, `procurement:manage`):
- goes to an approved vendor, in the vendor's currency, and is charged to an active
  department;
- has lines, each a description, a quantity and a unit price (rule `lines_invalid`); its
  total is their sum;
- is approved or rejected by someone other than the requester (`procurement:approve`, rule
  `four_eyes`, also a database constraint). Above **US$50,000**, at the day's rate, only an
  executive may approve it (`procurement:approve_large`, rule `needs_executive`).

An approved order is **received** in one delivery or several (`procurement:manage`), never
above its total (rule `over_receipt`).

## Invoices

A vendor's invoice (`INV-`, `procurement:manage`) is recorded against a received order
(rule `not_received`). It carries the vendor's own reference:
- a reference already recorded for the same vendor, and not rejected, is refused (rule
  `duplicate_invoice`): the same invoice is never paid twice;
- it is **matched** when the total invoiced on the order, with it, stays within **2 %** of
  what was received. Otherwise it is **held**, with the reason.

A matched invoice is **paid** (`procurement:approve`) by someone other than whoever recorded
it (rule `four_eyes`, also a database constraint):
- only to an approved vendor with no bank change waiting;
- the ledger debits the purchases expense account for the currency
  (`PROC-PURCHASES-<CCY>`) and credits the bank's cash;
- the order closes when everything ordered has been received and paid.

Matched or held invoices can be rejected; nothing is paid.

## Workflows

| Workflow | Steps | Handlers |
| --- | --- | --- |
| WF-1046 Vendor Onboarding | register → approval (`procurement:approve`) → approve or reject | `procurement.register_vendor`, `procurement.approve_vendor`, `procurement.reject_vendor` |
| WF-1047 Purchase Order | raise → approval (`procurement:approve`) → approve or reject | `procurement.raise_order`, `procurement.approve_order`, `procurement.reject_order` |
| WF-1048 Invoice Payment | record → matched? → approval (`procurement:approve`) → pay or reject; held invoices end there | `procurement.record_invoice`, `procurement.pay_invoice`, `procurement.reject_invoice` |

`procurement.record_invoice` takes the date on the vendor's invoice (`invoice_date_path`,
optional since Phase 58); without it, the invoice is dated the day it is recorded.

The handlers need `procurement:manage` to start and `procurement:read` to read executions.
Approving a high-risk vendor or a large order in a workflow needs a decider holding
`procurement:approve_large`. Paying an invoice moves money, so it comes after an approval.

Their generated tests take, from fixtures:
- an approved US facilities vendor;
- an active US department;
- an approved order of US$1,000 from the vendor, received in full.

## Simulation workload and AI tool (Phase 58)

The `invoice_payments` workload drives WF-1048 v2 (scenario `invoice-payments`).
- **Cases:** each case has its own approved US vendor and a received purchase order. Any
  bank-detail change and earlier paid invoices the case needs are booked through the real
  procurement service. The workflow then records the invoice, with the date the vendor put
  on it, and a department manager (`procurement:approve`) pays or rejects it.
- **Ground truth:**
  - paid: routine invoices, partial deliveries, invoices within the 2 % tolerance, vendors
    whose bank details changed long ago, and small first invoices from new vendors;
  - rejected: an invoice to a bank account changed in the last fortnight with nothing paid
    to it yet, an invoice dated before its order, and the same bill sent again under a new
    reference.
- **`procurement.invoice_profile`** (also a library handler) reads:
  - the amount, in US dollars too;
  - the vendor's category, tier and age;
  - any bank-detail change, and how many payments have gone to the new account since;
  - whether the invoice is dated before its order, and how old it is;
  - whether the delivery was partial, and how far the invoiced total runs over what was
    received;
  - the vendor's other invoices in the 90 days before, and how many were for the same
    amount.
- **AGB Invoice Review Assistant** (`agb-invoice-assistant`): advisory. It is blind to the
  vendor's same-amount history; see [ai-testing.md](ai-testing.md) for its rules and the
  measurement.

## Permissions

| Permission | Roles | What it allows |
| --- | --- | --- |
| `procurement:read` | banking employees, department managers, regional and global executives, auditors | the page and the lists |
| `procurement:manage` | banking employees, department managers | register vendors, ask for bank changes, raise orders, receive, record invoices |
| `procurement:approve` | department managers, regional and global executives | approve or reject vendors and orders, verify bank changes, pay or reject invoices |
| `procurement:approve_large` | regional and global executives | high-risk vendors and orders above US$50,000 |

## Known limitations

- **One currency per order:** the vendor's. There is no multi-currency invoice or payment.
- **Payments post straight to the ledger:** there is no payment file, clearing or
  remittance advice to the vendor, and no payment terms or due dates.
- **No tax:** invoices carry no VAT or withholding.
- **No budgets:** orders are not checked against a department's budget.
- **Vendors are never re-screened** after registration, and none is suspended
  automatically.
- **Only invoice payments are simulated** (Phase 58); vendor onboarding and purchase orders
  are not.
