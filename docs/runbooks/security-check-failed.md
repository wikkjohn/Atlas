# Runbook: The Security CI job fails

**Severity when it happens:** Medium

## Symptoms
The **Security** job fails on a pull request. Its checks are:
- dependency audits: `pip-audit` and `npm audit`;
- Bandit;
- the authorization-matrix check.

## Checks
1. Open the failing step's log. Each check fails for one reason, named in its output.

## Actions
- **pip-audit or npm audit:** a dependency has a known vulnerability.
  - Upgrade it to a fixed version and run the tests.
  - If no fix exists, record the advisory and the reason it does not apply, in the PR and
    in `docs/security.md`, before any exception.
- **Bandit (medium or above):** fix the code.
  - Use a `# nosec` only for a verified false positive, with the reason beside it, as for
    the four B608 annotations.
- **Authorization matrix:** a route's requirement differs from the reviewed matrix.
  - If the change is intended, run `python -m app.cli authz-matrix --write` and review the
    difference in the PR: which route, which permission, which roles.
  - If it is not intended, fix the route.
  - Never regenerate the matrix to make CI green without reading the difference.

## Verify
The Security job passes on the next push.

## Escalation
If the actions do not restore service, or data may be lost or altered, open an incident.
Record the correlation ids, the run or archive numbers and the times, and stop changes to
the affected area until it is understood.
