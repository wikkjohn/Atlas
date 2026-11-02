# Customer service

Phase 51 (roadmap Milestone D, step 23). Customer service covers:
- contact-centre cases from every channel: enquiries, requests and complaints;
- SLA timers, with escalation of overdue cases;
- complaints, with redress paid by a second person.

Code: `backend/app/modules/customer_service/`. Page: **Customer Service**
(`/customer-service`, `service:read`).

## Cases

A case (`SRV-`, `service:handle`) is opened for a customer, and optionally one of their
accounts. It records:
- the channel: phone, email, chat, branch or letter;
- the topic: account, card, payments, lending, fees, digital or other;
- the category and priority;
- a subject and description.

Every step goes on the case's timeline: opened, responses, pauses, breaches, redress and
resolution.

## SLA timers

| Priority | First response | Resolution |
| --- | ---: | ---: |
| Urgent | 1 hour | 8 hours |
| High | 4 hours | 24 hours |
| Normal | 8 hours | 72 hours |
| Low | 24 hours | 120 hours |
| Complaint (any priority) | 48 hours (acknowledgement) | 8 weeks (final response) |

- The first reply meets the first-response SLA. Resolving a case that was never answered
  counts as its response.
- **Waiting on the customer** pauses the clock. When the customer replies, the due times move
  later by the pause, except a complaint's final response, which runs regardless.
- **The sweep** marks overdue cases breached. It runs from the page (`service:handle`), as
  WF-1039, and as the background job `customer_service.sla_sweep`, which the scheduler can
  run.
  - A missed first response escalates the case one priority.
  - A missed resolution flags it escalated, for the manager's queue.

## Complaints and redress

- A complaint is resolved with an outcome: upheld, partly upheld or not upheld (rule
  `outcome_required`).
- **Redress** is proposed (`service:handle`) into one of the customer's open accounts. It is
  paid (`service:approve`) by someone other than whoever proposed it (rule `four_eyes`, also
  a database constraint). Payment debits complaint redress expense (`CS-REDRESS-<CCY>`) and
  credits the account.
- Redress can be withdrawn instead. A complaint cannot be resolved while redress awaits
  approval (rule `redress_pending`).

## Simulation workload and AI tool (Phase 52)

The `complaint_redress` workload drives WF-1038 v2 (scenario `complaint-redress`).
- **Cases:** each case is a customer with a US-dollar account. The fees it needs are charged
  through the real accounts service, dated in the last 90 days. The earlier complaints it
  needs are opened, refunded and upheld through the real customer service. The workflow then
  opens the complaint and proposes the redress, and a complaints manager (`service:approve`)
  decides every case.
- **Ground truth, uphold:**
  - a refund of a monthly fee charged twice;
  - a refund of a fee actually charged;
  - a small goodwill payment (US$10–50) for an app outage;
  - a moderate goodwill payment (US$80–200) for a card blocked abroad.
- **Ground truth, refuse:**
  - a fee complaint with no fee charged;
  - redress of 4–10 times the fee charged;
  - a large goodwill payment (US$400–1,500) for a slow app;
  - a refund for a customer already refunded three or four times this year.
- **Decisions:** in AI-assisted runs the AGB Complaint Review Assistant advises the manager,
  from the profile `service.complaint_profile` reads. The profile covers:
  - the redress against the fees charged in 90 days, and a fee charged twice;
  - the redress in US dollars;
  - the account's age and the description;
  - the customer's other complaints this year, how many were upheld and the redress already
    paid.
- **Control check:** four-eyes against the initiator (who proposed the redress),
  `service:approve` on each decision, and no redress paid without it.

What it measured, and the assistant's blind spot, is in [ai-testing.md](ai-testing.md).

## Workflows

| Workflow | What it does |
| --- | --- |
| WF-1037 Service Request | Opens a request on the customer's account and acknowledges it; a colleague fulfils or declines it |
| WF-1038 Complaint Handling | Opens and acknowledges a complaint and proposes redress; an approver pays it (upheld) or it is withdrawn (not upheld). v2 (Phase 52): the complaint profile and the AGB Complaint Review Assistant's advice first |
| WF-1039 Service SLA Sweep | Marks overdue cases breached and escalates them |

The customer service handlers need `service:handle` to start a workflow using them and
`service:read` to read its executions through the API.

## Permissions

- **`service:read`:** every role.
- **`service:handle`:** banking employees and department managers (the front office), and
  the scheduler, which runs the sweep.
- **`service:approve`:** department managers.

## Limitations

- **Wall-clock SLAs:** timers run in hours on the clock, not business hours by the country's
  calendar.
- **No queues or routing:** a case is assigned to whoever opens it; there is no skills-based
  routing or workload balancing.
- **No messages out:** a response is recorded on the timeline; nothing is sent to the
  customer.
- **Simulation scope:** only complaint redress is simulated; requests and the SLA sweep are
  not.
