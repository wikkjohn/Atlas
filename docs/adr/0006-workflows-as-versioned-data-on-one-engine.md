# ADR 0006: Workflows are versioned definitions interpreted by one engine

- **Status:** Accepted
- **Decided in:** Phases 4, 17–22

## Context
The bank runs thousands of process variants: department, product and country versions of
onboarding, payments, lending and reviews. Hand-coding each variant does not scale, and the
simulation has to run exactly the processes the bank runs.

## Decision
- **One engine** (`backend/app/modules/workflows/engine.py`) interprets versioned
  definitions. Each step commits atomically with its handler's effects, under the
  execution's row lock.
- **Definitions are code or data.**
  - Since Phase 17, definitions can be stored as data, as validated JSON in
    `workflow_definitions`.
  - Since Phase 19, they can be generated from templates.
  - Since Phase 20, each comes with generated tests.
- **Step handlers** come from a shared library. Modules contribute handlers and keep their
  own rules in their services: four eyes, eligibility and authority.
- **Versions are immutable snapshots.** Only their lifecycle status changes.

## Consequences
- **Benefits:**
  - About 5,000 workflows exist and are tested by the generated suite (Milestone B exit).
  - A rule in a service applies whether a case arrives by workflow or by API.
- **Costs:**
  - The engine is the most central code in the platform, and every change to it is
    high-risk.
  - Debugging a case means reading its event history, not one function.

## Evidence
- `docs/workflows.md`
- `backend/app/modules/workflows/`
- `backend/tests/test_idempotent_starts.py`
