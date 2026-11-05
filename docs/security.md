# Sign-in, sessions, second factor and scoped access

Phase 84 (roadmap Milestone H, step 1). Everything here is synthetic: the identity provider
is simulated and so is the authenticator app; no real credentials are involved.

## Sessions

Every sign-in opens a session (`auth_sessions`), and every access token names it (`sid`). A
request is accepted only while its session is:

- not signed out or revoked;
- not idle: unused for less than `ATLAS_SESSION_IDLE_MINUTES` (30);
- not expired: younger than `ATLAS_SESSION_ABSOLUTE_HOURS` (12).

A token issued for the session (60 minutes by default, `POST /auth/refresh` for another)
never outlives it. A session that ends on idleness or age is marked so, with the reason.

**What ends sessions:**
- signing out;
- signing out everywhere else;
- an administrator signing the user out;
- deactivating the user;
- enrolling a second factor (the other sessions);
- an administrator resetting the factor;
- five wrong codes at sign-in.

Each session records its method (password or SSO), its provider, its second-factor state,
the client's address and user agent, and when it was last used. That last use is written at
at most once a minute, or every quarter of the idle limit when that is
shorter.

Tokens without a session are refused, including tokens issued before this phase. Tests and
the performance suite create a session for the tokens they mint.

## Second factor (TOTP)

The second factor is a time-based one-time password (RFC 6238: HMAC-SHA1, 30-second steps,
six digits). It is implemented with the standard library (`app/core/totp.py`) and checked
against the RFC's test vectors.

**Enrolment** (`POST /auth/mfa/enrol`, then `/auth/mfa/confirm`):
- The bank issues a secret and an `otpauth://` URI.
- The secret becomes the user's factor only when a code from it is confirmed.
- Confirming returns eight one-time recovery codes, shown once and stored as SHA-256 hashes.

**Sign-in** with a factor enrolled:
- The password answers `mfa_required` with a 5-minute challenge token, not an access token.
  The challenge is a token of its own type, so it is never accepted as an access token.
- `POST /auth/mfa/verify` takes the challenge and a code (or a recovery code).
- Codes are accepted for the current step and one step either side. A step at or before
  the last one used is refused, so no code works twice.
- Five wrong codes end the sign-in.

**Required factors:** `ATLAS_MFA_REQUIRED_ROLES` (comma-separated role codes; empty by
default) names roles that must have a factor. A user of such a role without one signs in to
a session marked `enrolment_required`. That session may reach only `/auth/me`,
`/auth/logout` and the enrolment endpoints; everything else answers 403 until a factor is
confirmed. Such a user cannot remove their factor.

**Promotions:** the requirement follows the user's current role on every request, not the
role at sign-in. A user promoted into a role that requires a factor is held to enrolment at
once. (This was a review finding on PR #75, fixed in Phase 85.)

**One code, one sign-in:** a code is checked and consumed under a lock on the user's row.
Two overlapping requests therefore cannot both accept the same code (Phase 85).

**Lost devices:** an administrator resets the factor (`POST /users/{id}/mfa/reset`), which
also signs the user out everywhere. Administrators cannot reset their own.

**The authenticator is simulated:** the Security page computes the current code from the
secret in the browser (Web Crypto). Any real authenticator app given the URI shows the same
codes.

## Single sign-on (simulated)

The bank trusts one simulated identity provider, the **ATLAS Corporate Directory**
(`atlas-directory`). The flow has OpenID Connect's shape:

1. `POST /auth/sso/atlas-directory/start`: a random `state` and `nonce`, stored, valid for
   10 minutes.
2. `POST /simulated-directory/atlas-directory/sign-in` (the directory): it checks the
   employee's credentials, and the TOTP code when one is given. It returns an ID token:
   issuer, audience (the bank), subject, email, the nonce, and `amr` (`pwd`, plus `otp` when
   a code was checked).
3. `POST /auth/sso/atlas-directory/callback` (the bank) accepts the token only when all of
   these hold:
   - the state is stored, unused and unexpired (it is used even when the token is then
     refused);
   - the directory's signature is valid;
   - the issuer, audience and expiry are right;
   - the nonce matches;
   - the subject is an active user with that email.

   A directory that checked the second factor satisfies the bank's. Otherwise a user with a
   factor is asked for it.

**Simulated, and how:** the directory runs inside the API and signs with a key derived from
the bank's secret. A real provider is a separate system with published keys (JWKS), and the
bank would fetch them. There is no just-in-time provisioning: the directory account must
already be a bank user.

## Scoped access

`user_scopes` limits a user to countries (ISO codes) and departments (department names, as
in the organisation tree and the catalogue). A dimension without entries does not limit.
Permissions still decide *what* a user may do; the scope decides *where*. The rules:

| Records | Limited by | Lists | By id, and actions on them | Creating |
| --- | --- | --- | --- | --- |
| Customers | the customer's country | filtered | 404 | 403 outside the scope |
| Accounts, account requests | their customer's country | filtered | 404 (deposits, withdrawals, freezes, approvals…) | 404 for a customer outside |
| Employees | the employee's country and department | filtered | 404 (reports and reporting chains are filtered too) | 403 when hiring or moving outside |

- Outside the scope a record answers 404, not 403, so its existence is not revealed.
- Scopes are set by an unscoped administrator (`PUT /users/{id}/scopes`) and audited
  (`user.scopes_changed`, with before and after).
- All user administration is for unscoped administrators (Phase 85: creating and editing
  users, scopes, sessions, factor resets, unlocking). Otherwise a scoped administrator
  could create an unscoped account.
- They take effect on the user's next request.

## Screens

- **Sign-in page:** the password; the code step when a factor is enrolled; *Continue with
  ATLAS Corporate Directory (simulated SSO)*.
- **Security** (shield icon in the header):
  - the second factor: set it up with the simulated authenticator, recovery codes, remove;
  - sessions: end one, sign out everywhere else;
  - the user's scope.
  - A user who still owes enrolment is held on this page.
- **System Settings → Users → Access…:**
  - set a user's countries and departments;
  - see and end their sessions;
  - reset their authenticator.

## Limitations

- The TOTP secret is stored as is, in a column readable by the database. Production would
  encrypt it with a key outside the database.
- Rate limits and a sign-in lockout were added in Phase 85: see `data-retention.md`.
- Scopes cover customers, accounts, account requests and employees. Payments, loans, cards,
  workflows, dashboards and the other departments' pages are not scoped yet.
- A scoped user's dashboards still show bank-wide totals.
- Scopes and the second factor apply to people; service principals (simulated staff, the
  policy engine) are unrestricted.
- Session tokens are kept in the browser's session storage, as before. There is no
  refresh-token rotation; the client signs in again when the access token expires.

## Security scanning and the authorization matrix (Phase 86)

Every pull request runs the **Security** CI job:

| Check | Tool | Fails on |
| --- | --- | --- |
| Python dependencies | `pip-audit --strict` over `pip freeze --exclude-editable` (PyPI advisories; the project itself is not on PyPI) | any known vulnerability, or a package it cannot audit |
| Backend source | `bandit -r app -q -ll` (static analysis) | any finding of medium severity or above |
| Route permissions | `python -m app.cli authz-matrix` | any route whose requirement differs from the reviewed matrix |
| npm dependencies | `npm audit --audit-level=high` | a high or critical advisory |

**Bandit results:**
- At the start of Phase 86 there were no high findings, 4 medium and 71 low.
- The four medium findings were B608 (SQL built from strings). They are false positives:
  the strings are module constants and partition names, never request input. Each now
  carries a `# nosec B608` with the reason beside it.
- The low findings are not gated. They are `assert`s, `random` (the simulation is meant to
  be pseudo-random and seeded), and names that look like passwords.

**The authorization matrix** is read from the code. Every route under `/api/v1` is one of
three kinds:
- public: signing in, before there is a session;
- open to any signed-in user;
- guarded by exactly one permission through `Authorized(...)`.

Each permission check records the permission it enforces, so the matrix is what the server
does. `backend/tests/authorization_matrix.json` is the reviewed copy; adding a route, or
changing what one requires, fails CI until it is regenerated (`--write`) and the
difference reviewed. `authorization-matrix.md` is generated from it, with the roles that may
call each route.

`tests/test_authorization_matrix.py` enforces the matrix for every person role:
- **Refused:** each role tries every guarded route whose permission it lacks, with every
  method. It must get 403 naming that permission, before any handler runs.
- **Allowed:** each role tries every GET route whose permission it holds. The permission
  check must pass. Other methods are not tried, since they would act.

At Phase 86: 478 routes; 6 public, 19 for any signed-in user, 453 behind a permission.
