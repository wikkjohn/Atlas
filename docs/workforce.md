# The workforce

Phase 69 (roadmap Milestone F, step 1). Code: `backend/app/modules/employees/workforce.py`,
migration 0046. Page: **Employees** (`/employees`), the Workforce panel.

## The generator

`POST /api/v1/employees/workforce/generate` (`employees:manage`) and
`python -m app.cli workforce generate --count 150000 --seed 2030` staff the bank with
synthetic employees:
- **Deterministic:** the same seed gives the same people.
- **Idempotent:** a second run with the seed adds nothing.

**Where they work.** The count is split over every active department in every country,
by the department's kind:

| Department | Weight |
| --- | --- |
| Branch Network | 30 |
| Customer Onboarding, Customer Service | 10 |
| Retail Banking, Retail Banking Operations | 8 |
| Payments Operations, Cards, IT Operations, Financial Crime Compliance | 6 |
| Retail Lending, Collections | 5 |
| Mortgages, Commercial Lending | 4 |
| Wealth Management, Credit Risk, Finance | 3 |
| Treasury, Trade Finance, Human Resources, Procurement, others | 2 |
| AI Innovation Lab | 1 |

**The hierarchy in each department:**
- a **head** (grade 9, `department_manager`), with no manager;
- **team leads** (grades 6 and 7), one for each team of about ten, reporting to the head;
- **staff** (grades 1 to 5) reporting to their team lead, entry grades most often (weights
  30, 30, 20, 12, 8).

Staff take the department's role: `compliance_officer` in Financial Crime Compliance,
`auditor` in Internal Audit, `ai_researcher` in the AI Innovation Lab, otherwise
`banking_employee`.

**Grades and pay.** Each grade has a title and a US-dollar band midpoint. Pay is the
midpoint ±10 %, converted at the FX anchor rates into the country's currency (as the
subsidiary blueprint does) and rounded to the thousand.

| Grade | Title | US$ |
| --- | --- | --- |
| 1 | Associate | 38,000 |
| 2 | Analyst | 46,000 |
| 3 | Senior Analyst | 57,000 |
| 4 | Specialist | 70,000 |
| 5 | Senior Specialist | 86,000 |
| 6 | Team Lead | 102,000 |
| 7 | Senior Team Lead | 122,000 |
| 8 | Manager | 148,000 |
| 9 | Head of Department | 185,000 |
| 10 | Director | 240,000 |

**Other attributes:**
- **Skills:** one or two from the department's pool (e.g. `kyc` and `sanctions` in Customer
  Onboarding), one general skill (`excel`, `coaching`…), and one language of the country
  (`language:ja-JP`).
- **Status:** everyone starts active. Leave comes with leave records (Milestone F step 2);
  the leave sweep (WF-1045) keeps the status in line with them, so an on-leave status
  without a record would be undone by the next sweep.
- **Contact:** emails are on `staff.atlas-bank.example`.

Generated employees are tagged `workforce-v1:<seed>` and have no user accounts.

**Speed.**
- Rows are inserted 5,000 at a time, with employee numbers drawn from the sequence in one
  query.
- The table is analysed afterwards: straight after the bulk insert, the summary's queries
  were planned for the old, small table and took 16 s instead of 0.5 s.

## The summary

`GET /api/v1/employees/workforce/summary` (`employees:read`) and `workforce summary` give:
- the total, and how many were generated;
- employees by country, department, grade, role and status;
- the twelve commonest skills.

## Measured

On the development database, which has 5 countries with 21 departments:

| Measure | Result |
| --- | --- |
| 150,000 generated | 37.0 s (with the commit), 230 MB peak memory |
| Spread | US, GB, JP, SG about 29,800 each, DE 31,163; Branch Network 94,945, Customer Onboarding 31,695, Financial Crime Compliance 19,019 |
| Grades | 1: 40,907 · 2: 40,953 · 3: 27,260 · 4: 16,405 · 5: 10,809 · 6: 6,860 · 7: 6,785 · 9: 21 |
| Roles | 127,989 banking employees, 19,008 compliance officers, 3,160 AI researchers, 89 department managers |
| Generated workflow tests (115 workflows, 1,482 cases) on this database | 233.0 s, against 211.9 s before the workforce. Before the leave sweep was made set-based, they took 403.1 s, WF-1045 alone 151 s; it now takes 0.85 s |
| Summary | 0.5 to 1.0 s |
| Employee list, a page of 50 | 0.83 s; searching 0.74 s; at offset 100,000, 0.97 s |

## The leave sweep, at scale

HR's leave sweep (WF-1045, Phase 55) loaded every employee who was not terminated, one
object at a time, with its organisation, country, role and manager. With 150,000 employees,
its generated test took 151 s. It is now two set-based updates:
- employees on approved leave today go on leave;
- those whose leave has ended become active again.

The counts it returns are unchanged.

## Known limitations

- **The spread follows the departments that exist:** with five countries, each has about
  30,000 staff. Launching more subsidiaries (Phase 27) spreads them further.
- **No teams as organisations:** a team is the people reporting to a team lead, not an
  organisational unit.
- **No grade 8 or 10:** the generated hierarchy has heads, leads and staff only.
- **Generated staff have no user accounts and no shifts or leave records yet.** Shifts,
  holidays, absences and time zones are Milestone F step 2.
