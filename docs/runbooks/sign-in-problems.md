# Runbook: Sign-in problems: lockouts, lost authenticators, compromised sessions

**Severity when it happens:** Medium

## Symptoms
- A user is told their account is locked after repeated failed sign-ins.
- A user lost the device with their authenticator and has no recovery codes.
- A session is suspected stolen, or a user left a session signed in somewhere.

## Checks
1. Confirm who is asking, outside the platform: the bank's identity procedures, not the
   caller's word.
2. Read the audit log for the user. Look for `auth.login_failed` (with the reason),
   `auth.locked` and `auth.mfa_failed`, and for sign-ins from unexpected addresses.
3. List the user's sessions: `GET /api/v1/users/{user_id}/sessions`.

## Actions
- **Locked out:** the lock lifts by itself after 15 minutes. An unscoped administrator
  may lift it at once: `POST /api/v1/users/{user_id}/unlock`. If the failed attempts were
  not the user's, also revoke their sessions and ask them to change the password.
- **Lost authenticator:** an unscoped administrator resets the factor with
  `POST /api/v1/users/{user_id}/mfa/reset`. This also ends every session. The user enrols
  a new factor at the next sign-in; a role that requires a factor is held to enrolment.
  Administrators cannot reset their own.
- **Compromised session:** `POST /api/v1/users/{user_id}/sessions/revoke` ends the user's
  sessions at once. Tokens stop working on their next request.

## Verify
The user signs in, with a newly enrolled factor where one was reset. The audit log shows
the administrator's action (`auth.session_revoked`, `auth.mfa_removed` or `auth.unlocked`).

## Escalation
If the actions do not restore service, or data may be lost or altered, open an incident.
Record the correlation ids, the run or archive numbers and the times, and stop changes to
the affected area until it is understood.
