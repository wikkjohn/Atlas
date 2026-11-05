# ADR 0010: One permission per route, read from the code and reviewed as a matrix

- **Status:** Accepted
- **Decided in:** Phases 2, 84–86

## Context
The bank has eight person roles and two service principals, across about 480 routes. A
missing or wrong permission is a security defect that ordinary feature tests do not
notice.

## Decision
- **Permissions in code.** `backend/app/core/permissions.py` maps each role to its
  permissions.
- **Every route is exactly one of three kinds:**
  - public (sign-in only);
  - open to any signed-in user;
  - guarded by one permission via `Authorized(...)`, whose check records the permission
    it enforces.
- **The matrix is read from the routes** (`backend/app/security/matrix.py`) and compared
  with the reviewed copy, `backend/tests/authorization_matrix.json`. A difference fails CI
  until it is regenerated with `python -m app.cli authz-matrix --write` and reviewed.
- **Every refusal is tested.** Each role tries every guarded route it lacks, and must get
  403 naming the permission.
- **Scopes are separate from permissions (Phase 84).** Country and department scopes
  decide *where* a user may act; permissions decide *what*.

## Consequences
- **Benefits:**
  - Adding or changing a route's requirement cannot pass unnoticed.
  - `docs/authorization-matrix.md` is generated from what the server enforces.
- **Costs:**
  - Business rules are not in the matrix: four eyes, scopes and "not your own". Their
    modules' tests cover them.
  - Only GET routes are tried on the allowed side, since other methods would act.

## Evidence
- `backend/app/security/matrix.py`
- `backend/tests/test_authorization_matrix.py`
- `docs/security.md`
