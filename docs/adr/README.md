# Architecture decision records

Each record states one decision that shapes the platform: the context that forced a choice,
the decision, what it costs, and where the code and tests show it. They are written after the
fact, from the code, the phase history and the measurements in
[implementation-status.md](../implementation-status.md), and kept current as decisions
change.

| ADR | Decision | Decided in | Status |
| --- | --- | --- | --- |
| [0001](0001-modular-monolith.md) | A modular monolith on FastAPI and PostgreSQL | Phase 1 | Accepted |
| [0002](0002-postgresql-is-the-system-of-record.md) | PostgreSQL is the only system of record; Redis is optional | Phases 1, 14 | Accepted |
| [0003](0003-money-in-integer-minor-units.md) | Money in integer minor units, one currency per entry | Phases 3, 23, 24 | Accepted |
| [0004](0004-the-ledger-is-the-only-writer-of-money.md) | The ledger is the only writer of money, and the database re-checks it | Phases 3, 12, 13 | Accepted |
| [0005](0005-append-only-audit-log-with-an-archive-chain.md) | An append-only audit log, archived in a digest chain | Phases 2, 85 | Accepted |
| [0006](0006-workflows-as-versioned-data-on-one-engine.md) | Workflows are versioned definitions interpreted by one engine | Phases 4, 17–22 | Accepted |
| [0007](0007-simulation-through-the-real-engine-on-simulated-time.md) | Simulation runs the real engine on simulated time, with seeded randomness | Phases 5, 15, 16 | Accepted |
| [0008](0008-outbox-for-departmental-events.md) | Departments react to each other through a durable outbox | Phases 10, 74 | Accepted |
| [0009](0009-ai-tools-behind-one-contract-advisory-by-default.md) | AI tools sit behind one contract and advise; services decide | Phases 6, 76, 79 | Accepted |
| [0010](0010-one-permission-per-route-and-a-reviewed-matrix.md) | One permission per route, read from the code and reviewed as a matrix | Phases 2, 84–86 | Accepted |
| [0011](0011-sessions-totp-and-simulated-sso.md) | Server-side sessions, a TOTP second factor and simulated SSO | Phases 84, 85 | Accepted |
| [0012](0012-logical-backups-checked-against-a-manifest.md) | Logical backups from one snapshot, checked against a manifest | Phases 87, 88 | Accepted |

## Writing a new record

1. Copy [template.md](template.md) to the next number: `NNNN-short-title.md`.
2. Fill in **Context**, **Decision**, **Consequences** and **Evidence**. The evidence must
   name files or tests that exist.
3. Add the record to the table above.
4. To replace a decision, set the old record's status to `Superseded by ADR NNNN`, and add
   a new record. Do not rewrite the old one.

`backend/tests/test_documentation.py` checks that every record has these sections and is
listed here, and that every repository path it names exists.
