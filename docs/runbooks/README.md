# Runbooks

What to do when something goes wrong in the platform. Each runbook has the same parts:
- the **symptoms** that send you to it;
- the **checks** to find the cause;
- the **actions** that fix it;
- how to **verify** the fix;
- when to **escalate**.

They name real commands (`python -m app.cli …`) and API routes.
`backend/tests/test_documentation.py` fails if a runbook names a CLI command or an
`/api/v1` route that does not exist.

| Runbook | Severity |
| --- | --- |
| [The API is unhealthy or unreachable](api-unhealthy.md) | High |
| [Restore the bank from a backup](restore-from-backup.md) | Critical |
| [Background jobs are stalled or failing](background-jobs-stalled.md) | Medium |
| [A ledger reconciliation reports a failed check](reconciliation-failed.md) | Critical |
| [Sign-in problems: lockouts, lost authenticators, compromised sessions](sign-in-problems.md) | Medium |
| [An audit archive fails verification](audit-archive-verification-failed.md) | High |
| [Event deliveries are dead or falling behind](event-deliveries-dead.md) | Medium |
| [Simulation history is filling the database](simulation-history-growth.md) | Low |
| [The Security CI job fails](security-check-failed.md) | Medium |

The bank is synthetic. These are the procedures a real deployment of this platform would
follow, and they are exercised in this repository: the recovery drill
([backup-recovery.md](../backup-recovery.md)), the tests behind each endpoint, and the CI
jobs.
