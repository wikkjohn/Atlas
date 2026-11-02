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

## Workflows

| Workflow | What it does |
| --- | --- |
| WF-1037 Service Request | Opens a request on the customer's account and acknowledges it; a colleague fulfils or declines it |
| WF-1038 Complaint Handling | Opens and acknowledges a complaint and proposes redress; an approver pays it (upheld) or it is withdrawn (not upheld) |
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
- **No simulation yet:** there is no customer service workload or AI tool yet (Phase 52).
