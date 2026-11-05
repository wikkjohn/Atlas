# ADR 0011: Server-side sessions, a TOTP second factor and simulated SSO

- **Status:** Accepted
- **Decided in:** Phases 84, 85

## Context
Stateless tokens cannot be revoked on sign-out or deactivation. A bank's staff need a
second factor and, in practice, single sign-on. Everything must stay synthetic: no real
identity provider and no real authenticator.

## Decision
- **Sessions.** Every access token names a sign-in session (`auth_sessions`), checked on
  each request. A session ends on any of:
  - sign-out or revocation;
  - 30 minutes idle;
  - 12 hours.
- **Second factor.** TOTP (RFC 6238), implemented with the standard library and checked
  against the RFC's test vectors. It can be required per role, and has recovery codes.
- **Simulated SSO.** A corporate identity provider with OpenID Connect's shape (state,
  nonce, signed ID token) runs inside the API, under its own key.
- **Abuse protection (Phase 85).** Rate limits, and a lockout after five wrong passwords,
  applied to both sign-in paths (PR #76 review).

## Consequences
- **Benefits:**
  - Revocation is immediate.
  - The second-factor and SSO flows can be tested end to end.
- **Costs:**
  - Each request reads its session row.
  - The TOTP secret is stored unencrypted in the database.
  - A real deployment would use a real identity provider's published keys (JWKS).

## Evidence
- `backend/app/modules/identity/sessions.py`
- `backend/app/core/totp.py`
- `docs/security.md`
