# API contracts

The OpenAPI document generated from the code is the authoritative contract:
`GET /api/openapi.json`, browsable at `/api/docs`. This page explains the conventions
every endpoint follows and lists what exists.

## Conventions

| Concern | Rule |
| --- | --- |
| Versioning | Business endpoints live under `/api/v1/`. Platform health endpoints live under `/api/` so infrastructure probes stay stable. |
| Authentication | `Authorization: Bearer <access token>` from `POST /api/v1/auth/login`. Tokens are HS256 JWTs (default lifetime 60 minutes). The user is re-loaded on every request, so deactivation and role changes apply immediately. |
| Authorization | Each endpoint requires one permission (below). Checked on the server; 403 names the missing permission in `details.required_permission`. |
| Errors | `{"error": {"code", "message", "details", "correlation_id"}}`. Codes: `unauthorized` (401), `forbidden` (403), `not_found` (404), `conflict` (409), `validation_error` (422, malformed input, `details` lists fields), `business_rule_violation` (422, well-formed but breaks a rule), `internal_error` (500, no internal detail). |
| Correlation | Send `X-Correlation-ID` (≤128 chars of `A-Za-z0-9._:-`) or one is generated. It is echoed in the response, logged, and stored on audit events. |
| Idempotency | `POST` create endpoints accept `Idempotency-Key`. Retrying with the same key and body replays the original response (header `Idempotent-Replayed: true`) without side effects. The same key with a different body returns 409. Keys are scoped per user. A request that failed stores nothing, so it can be retried. |
| Pagination | List endpoints take `limit` (1–200, default 50) and `offset`, and return `{"items", "total", "limit", "offset"}`. |
| Filtering | Query parameters per endpoint (below). Free-text `q` is a case-insensitive contains-match. |
| Money | Integer minor units of an ISO 4217 currency (e.g. `8250000` USD = $82,500.00; JPY has no minor unit). Never floating point. |
| Partial updates | `PATCH` changes only the fields sent; send `null` explicitly to clear a nullable field (e.g. `manager_id`). |

## Endpoints

### Platform (public)

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/health` | 200 healthy/degraded, 503 when the database is down |
| GET | `/api/system/info` | Version, environment, module roadmap |
| GET | `/api/system/status` | Database, migration state, Redis |

### Auth, users and roles

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| POST | `/api/v1/auth/login` | public | `{username, password}` → token, expiry, user with permissions. Failures are audited. |
| GET | `/api/v1/auth/me` | signed in | Current user and permissions |
| GET | `/api/v1/roles` | signed in | Roles and the permissions each grants |
| GET | `/api/v1/users` | `users:read` | Paginated |
| POST | `/api/v1/users` | `users:manage` | Password ≥ 12 characters; idempotent |
| GET | `/api/v1/users/{id}` | `users:read` | |
| PATCH | `/api/v1/users/{id}` | `users:manage` | `display_name`, `role`, `is_active`; administrators cannot demote or deactivate themselves |

### Countries

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| GET | `/api/v1/countries` | `countries:read` | Filters: `region`, `operational_status`, `q` |
| POST | `/api/v1/countries` | `countries:manage` | ISO 3166 code, ISO 4217 currency, IANA time zone, language tags; idempotent |
| GET | `/api/v1/countries/{id}` | `countries:read` | |
| PATCH | `/api/v1/countries/{id}` | `countries:manage` | Name, time zone, languages, status. Code, region and currency are fixed once created. |

### Organizations

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| GET | `/api/v1/organizations` | `organizations:read` | Filters: `parent_id`, `root_only`, `organization_type`, `country_id`, `status`, `q` |
| POST | `/api/v1/organizations` | `organizations:manage` | Hierarchy and country rules below; idempotent |
| GET | `/api/v1/organizations/{id}` | `organizations:read` | Includes `child_count`, `employee_count`, inherited `currency` |
| GET | `/api/v1/organizations/{id}/ancestors` | `organizations:read` | Path from the global bank |
| PATCH | `/api/v1/organizations/{id}` | `organizations:manage` | `name`, `status` |

Hierarchy rules: global bank (exactly one, the only root) → regional headquarters (has a
region) → country subsidiary (one per country; the country must be **active** and in the
headquarters' region) → business division → department → team. Region and country are
inherited downward and cannot be overridden. Sibling names are unique. A unit with active
children or staff cannot be deactivated, and nothing can be created under an inactive unit.

### Employees

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| GET | `/api/v1/employees` | `employees:read` | Filters: `q`, `organization_id`, `department_id`, `country_id`, `manager_id`, `employment_status` |
| POST | `/api/v1/employees` | `employees:manage` | Idempotent; see rules |
| GET | `/api/v1/employees/{id}` | `employees:read` | |
| GET | `/api/v1/employees/{id}/direct-reports` | `employees:read` | |
| GET | `/api/v1/employees/{id}/reporting-chain` | `employees:read` | Direct manager upwards |
| PATCH | `/api/v1/employees/{id}` | `employees:manage` | Title, unit (transfer), manager, role, status, compensation |

Rules: staff join a department or a team (`department_id` is derived). Country defaults to
the unit's and must be active; compensation is recorded in that country's currency. Email
addresses are synthetic (`@atlasbank.example`), generated when omitted. A manager must be
an active employee and the reporting line may not form a cycle. An employee with active
direct reports cannot be terminated. `annual_compensation` and `compensation_currency`
are `null` unless the caller has `employees:read_compensation`.

### Audit

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| GET | `/api/v1/audit-events` | `audit:read` | Newest first. Filters: `action` (exact or `prefix*`), `entity_type`, `entity_id`, `actor_id`, `correlation_id`, `since`, `until` |

There are no write endpoints for audit events.

### Planned

`/api/v1/customers`, `/accounts`, `/ledger` (Phase 3); `/workflows`,
`/workflow-executions` (Phase 4); `/simulations` (Phase 5); `/ai-tools` (Phase 6);
`/experiments`, `/benchmarks` (Phase 7); `/analytics` (Phase 8).
