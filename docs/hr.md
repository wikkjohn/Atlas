# Human resources

Phase 55 (roadmap Milestone D, step 27). Human resources covers:
- hiring: requisitions approved by a second person, offers inside the salary band, hires;
- onboarding checklists for new hires;
- leave, counted in each employee's country's business days;
- shift rosters;
- a department's capacity on a day, which can staff a simulation run.

Code: `backend/app/modules/hr/`. Page: **Human Resources** (`/hr`, `hr:read`).

## Hiring

1. **A requisition** (`REQ-`, `hr:manage`) asks to hire into a department. It names:
   - a job title and a role (banking employee, department manager or compliance officer;
     never a service role);
   - 1 to 50 openings;
   - a yearly salary band in the department's currency;
   - the reason (rule `reason_required`).
2. **Approval** (`hr:approve`, regional and global executives): someone other than the
   requester approves it or cancels it (rule `four_eyes`, also a database constraint).
3. **Candidates** (`CAN-`) apply to an approved requisition (rule `not_recruiting`).
4. **An offer** must fall within the band (rule `offer_outside_band`) and start today or
   later (rule `start_in_past`).
5. **Hiring** an offered candidate creates the employee through the employees service:
   - in the requisition's department, with its job title and role;
   - at the offered salary;
   - reporting to a department manager there, if there is one.

   The requisition is filled when its last opening is. A candidate can also decline, or be
   turned down.

## Onboarding

Every hire gets a checklist, due from the start date:

| Task | Due |
| --- | --- |
| Signed contract on file | the start date |
| Systems access granted | the start date |
| Induction completed | 7 days after |
| Compliance training completed | 30 days after |
| Probation review held | 90 days after |

Tasks are completed from the page (`hr:manage`); overdue ones are counted.

## Leave

A leave request (`LV-`, `hr:manage`):
- is annual, sick or unpaid;
- is counted in the business days of the employee's country, by the reference calendars
  (Phase 26). A request with none is refused (rule `no_working_days`). A request crossing
  the year end must be split (rule `spans_years`).
- may not overlap another request awaiting a decision or approved (rule `overlap`);
- for annual leave, counts against 25 days a calendar year, awaiting or approved (rule
  `insufficient_balance`).

Someone other than the requester approves or rejects it (`hr:manage`, rule `four_eyes`,
also a database constraint). Approved leave can be cancelled.

**The leave sweep** (`POST /hr/leave/sweep`, WF-1045) marks employees on approved leave
today as on leave, and those whose leave has ended as active. Nobody who has left the bank
is touched.

## Shifts

A shift (`SHF-`, `hr:manage`) has a department, a day, a start hour, 1 to 12 hours and the
number of people it needs. Rostering an employee onto it is refused when they:
- work in another department (rule `other_department`);
- have left the bank (rule `terminated`);
- are on approved leave that day (rule `on_leave`);
- are on another shift at the same time (rule `double_booked`);
- would work more than 48 hours that week, Monday to Sunday (rule `weekly_hours`);
- would have less than 11 hours' rest after or before another shift (rule
  `rest_period`).

A full shift takes nobody more (rule `shift_full`).

## Capacity and simulation staffing

A department's capacity on a day (`GET /hr/capacity`):
- **headcount:** its staff who have not left;
- **on leave:** those on approved leave that day;
- **available:** the staff not on leave. When shifts are rostered that day, only the
  rostered staff count.

Available staff are also counted by simulated role:

| Employee role | Simulated role |
| --- | --- |
| Banking employee | teller |
| Department manager | manager |
| Compliance officer | compliance |
| Regional executive | executive |

A custom simulation run can name `staffing_department_id` instead of an employee count
(`POST /api/v1/simulations`). The run then hires as many simulated staff as the department
has available on the scenario's simulated day. That capacity is stored in the run's
configuration (`staffing`) and is part of its hash, so runs staffed differently never count
as reproductions of each other. A department with fewer than 3 available staff cannot
staff a run.

## Workflows

| Workflow | Steps | Handlers |
| --- | --- | --- |
| WF-1043 Job Requisition | open → approval (`hr:approve`) → approve or cancel | `hr.open_requisition`, `hr.approve_requisition`, `hr.cancel_requisition` |
| WF-1044 Leave Request | request → approval (`hr:manage`) → approve or reject | `hr.request_leave`, `hr.approve_leave`, `hr.reject_leave` |
| WF-1045 Leave Status Sweep | sweep | `hr.leave_sweep` |

The handlers need `hr:manage` to start and `hr:read` to read executions. Their generated
tests take an active department, and a new employee hired into it, from fixtures.

## Permissions

- `hr:read`: department managers, regional and global executives, auditors.
- `hr:manage` (department managers): requisitions, candidates, offers, hires, leave
  requests and decisions, the sweep, shifts and onboarding.
- `hr:approve` (regional and global executives): approve or cancel requisitions.

## Known limitations

- **No self-service:** employees do not request their own leave; a manager records it.
- **Whole days only:** no half days or hourly leave.
- **Sick leave is not capped,** and there is no carry-over of annual leave between years.
- **Salaries are recorded, not paid:** there is no payroll.
- **Capacity sizes a run, it does not shape it:** the run's role mix still comes from the
  scenario, not from the department's roles.
