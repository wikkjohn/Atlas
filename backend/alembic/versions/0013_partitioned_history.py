"""Partitioned workflow history

Workflow executions, step runs and events become LIST-partitioned tables on a new `realm`
column: `live` (the bank's own cases) and `simulation` (cases driven by the simulation
engine). Each partition is a separate table underneath, so simulation history can be
archived and reset (Phase 15) without touching, locking or bloating the live bank's.

PostgreSQL requires the partition key in every primary key and unique constraint, so the
keys become (id, realm) and foreign keys between the three tables carry the realm. AI tool
invocations get a derived `execution_realm` for their foreign key; simulation case results
keep their execution id without a foreign key (the history can be archived while the
measured result stays).

Live history stays append-only without exception. Simulation events may be deleted only
by the archive and reset commands, which set `atlas.simulation_history_purge` for their
transaction.

Revision ID: 0013_partitioned_history
Revises: 0012_background_jobs
Create Date: 2026-10-29 18:05:00.000000+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013_partitioned_history"
down_revision: str | None = "0012_background_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXECUTION_COLUMNS = (
    "id, workflow_id, workflow_version, definition_id, status, outcome, current_steps, "
    "context, error, business_key, initiated_by, idempotency_key, correlation_id, "
    "started_at, completed_at, updated_at, step_counter, simulation_run_id"
)
STEP_RUN_COLUMNS = (
    "id, execution_id, sequence, step_id, step_type, status, branch, attempt, "
    "required_permissions, actor_id, output, error, created_at, started_at, completed_at, "
    "duration_ms, not_before, due_at, escalated_at"
)
EVENT_COLUMNS = "id, seq, execution_id, step_run_id, event_type, occurred_at, actor_id, data"
REALMS = ("live", "simulation")
TABLES = ("workflow_executions", "workflow_step_runs", "workflow_events")

GUARD = """
CREATE OR REPLACE FUNCTION workflow_events_append_only() RETURNS trigger AS $$
BEGIN
    -- Simulation history may be removed by the archive and reset commands only, which
    -- set this for their own transaction. Live history has no such exception.
    IF TG_OP = 'DELETE' AND OLD.realm = 'simulation'
       AND current_setting('atlas.simulation_history_purge', true) = 'on' THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'workflow_events is append-only: % is not permitted', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;
"""

ORIGINAL_GUARD = """
CREATE OR REPLACE FUNCTION workflow_events_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'workflow_events is append-only: % is not permitted', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;
"""


def _drop_cross_table_keys() -> None:
    for table, name in (
        ("ai_tool_invocations", "fk_ai_tool_invocations_execution_id_workflow_executions"),
        (
            "simulation_case_results",
            "fk_simulation_case_results_execution_id_workflow_executions",
        ),
        ("workflow_events", "fk_workflow_events_execution_id_workflow_executions"),
        ("workflow_events", "fk_workflow_events_step_run_id_workflow_step_runs"),
        ("workflow_step_runs", "fk_workflow_step_runs_execution_id_workflow_executions"),
    ):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {name}")


def _event_triggers(tables: Sequence[str]) -> None:
    for table in tables:
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION workflow_events_append_only()"
        )
    # A row trigger on the parent is cloned to every partition, present and future.
    op.execute(
        "CREATE TRIGGER workflow_events_no_update_delete BEFORE UPDATE OR DELETE "
        "ON workflow_events FOR EACH ROW EXECUTE FUNCTION workflow_events_append_only()"
    )


def upgrade() -> None:
    _drop_cross_table_keys()
    op.execute("DROP TRIGGER workflow_events_no_update_delete ON workflow_events")
    op.execute("DROP TRIGGER workflow_events_no_truncate ON workflow_events")

    # New partitioned tables beside the old ones, filled from them.
    for table in TABLES:
        identity = " INCLUDING IDENTITY" if table == "workflow_events" else ""
        op.execute(
            f"CREATE TABLE {table}_new (LIKE {table} INCLUDING DEFAULTS{identity}, "
            "realm varchar(10) NOT NULL) PARTITION BY LIST (realm)"
        )
        for realm in REALMS:
            op.execute(
                f"CREATE TABLE {table}_{realm} PARTITION OF {table}_new FOR VALUES IN ('{realm}')"
            )
    op.execute(
        f"INSERT INTO workflow_executions_new ({EXECUTION_COLUMNS}, realm) "
        f"SELECT {EXECUTION_COLUMNS}, "
        "CASE WHEN simulation_run_id IS NULL THEN 'live' ELSE 'simulation' END "
        "FROM workflow_executions"
    )
    prefixed = ", ".join(f"r.{c.strip()}" for c in STEP_RUN_COLUMNS.split(","))
    op.execute(
        f"INSERT INTO workflow_step_runs_new ({STEP_RUN_COLUMNS}, realm) "
        f"SELECT {prefixed}, e.realm FROM workflow_step_runs r "
        "JOIN workflow_executions_new e ON e.id = r.execution_id"
    )
    prefixed = ", ".join(f"v.{c.strip()}" for c in EVENT_COLUMNS.split(","))
    op.execute(
        f"INSERT INTO workflow_events_new ({EVENT_COLUMNS}, realm) OVERRIDING SYSTEM VALUE "
        f"SELECT {prefixed}, e.realm FROM workflow_events v "
        "JOIN workflow_executions_new e ON e.id = v.execution_id"
    )

    for table in reversed(TABLES):
        op.execute(f"DROP TABLE {table}")
    for table in TABLES:
        op.execute(f"ALTER TABLE {table}_new RENAME TO {table}")
    op.execute("ALTER SEQUENCE workflow_events_new_seq_seq RENAME TO workflow_events_seq_seq")
    op.execute(
        "SELECT setval('workflow_events_seq_seq', "
        "COALESCE((SELECT max(seq) FROM workflow_events), 0) + 1, false)"
    )

    # Keys, checks and indexes (declared on the parent, created on every partition).
    op.execute(
        """
        ALTER TABLE workflow_executions
            ADD CONSTRAINT pk_workflow_executions PRIMARY KEY (id, realm),
            ADD CONSTRAINT uq_workflow_executions_idempotency
                UNIQUE (initiated_by, idempotency_key, realm),
            ADD CONSTRAINT ck_workflow_executions_status_valid CHECK (status IN
                ('running', 'waiting', 'completed', 'failed', 'cancelled')),
            ADD CONSTRAINT ck_workflow_executions_realm_matches_run
                CHECK ((realm = 'simulation') = (simulation_run_id IS NOT NULL)),
            ADD CONSTRAINT fk_workflow_executions_definition_id_workflow_definitions
                FOREIGN KEY (definition_id) REFERENCES workflow_definitions (id)
                ON DELETE RESTRICT,
            ADD CONSTRAINT fk_workflow_executions_initiated_by_users
                FOREIGN KEY (initiated_by) REFERENCES users (id) ON DELETE RESTRICT,
            ADD CONSTRAINT fk_workflow_executions_simulation_run_id_simulation_runs
                FOREIGN KEY (simulation_run_id) REFERENCES simulation_runs (id)
                ON DELETE RESTRICT;
        CREATE INDEX ix_workflow_executions_business_key ON workflow_executions (business_key);
        CREATE INDEX ix_workflow_executions_initiated_by ON workflow_executions (initiated_by);
        CREATE INDEX ix_workflow_executions_simulation_run_id
            ON workflow_executions (simulation_run_id);
        CREATE INDEX ix_workflow_executions_status ON workflow_executions (status);
        CREATE INDEX ix_workflow_executions_workflow_status
            ON workflow_executions (workflow_id, status);

        ALTER TABLE workflow_step_runs
            ADD CONSTRAINT pk_workflow_step_runs PRIMARY KEY (id, realm),
            ADD CONSTRAINT uq_workflow_step_runs_sequence UNIQUE (execution_id, sequence, realm),
            ADD CONSTRAINT ck_workflow_step_runs_status_valid CHECK (status IN
                ('pending', 'waiting', 'completed', 'failed', 'cancelled')),
            ADD CONSTRAINT fk_workflow_step_runs_execution_id_workflow_executions
                FOREIGN KEY (execution_id, realm)
                REFERENCES workflow_executions (id, realm) ON DELETE RESTRICT,
            ADD CONSTRAINT fk_workflow_step_runs_actor_id_users
                FOREIGN KEY (actor_id) REFERENCES users (id) ON DELETE RESTRICT;
        CREATE INDEX ix_workflow_step_runs_execution_id ON workflow_step_runs (execution_id);
        CREATE INDEX ix_workflow_step_runs_due ON workflow_step_runs (status, not_before)
            WHERE status = 'pending';
        CREATE INDEX ix_workflow_step_runs_waiting_due ON workflow_step_runs (due_at)
            WHERE status = 'waiting';

        ALTER TABLE workflow_events
            ADD CONSTRAINT pk_workflow_events PRIMARY KEY (id, realm),
            ADD CONSTRAINT uq_workflow_events_seq UNIQUE (seq, realm),
            ADD CONSTRAINT fk_workflow_events_execution_id_workflow_executions
                FOREIGN KEY (execution_id, realm)
                REFERENCES workflow_executions (id, realm) ON DELETE RESTRICT,
            ADD CONSTRAINT fk_workflow_events_step_run_id_workflow_step_runs
                FOREIGN KEY (step_run_id, realm)
                REFERENCES workflow_step_runs (id, realm) ON DELETE RESTRICT,
            ADD CONSTRAINT fk_workflow_events_actor_id_users
                FOREIGN KEY (actor_id) REFERENCES users (id) ON DELETE RESTRICT;
        CREATE INDEX ix_workflow_events_execution_id ON workflow_events (execution_id);
        CREATE INDEX ix_workflow_events_step_run_id ON workflow_events (step_run_id);
        CREATE INDEX ix_workflow_events_timeouts ON workflow_events (execution_id)
            WHERE event_type = 'step.timed_out';

        ALTER TABLE ai_tool_invocations ADD COLUMN execution_realm varchar(10)
            GENERATED ALWAYS AS (CASE WHEN execution_id IS NULL THEN NULL
                WHEN simulation_run_id IS NULL THEN 'live' ELSE 'simulation' END) STORED;
        ALTER TABLE ai_tool_invocations
            ADD CONSTRAINT fk_ai_tool_invocations_execution_id_workflow_executions
                FOREIGN KEY (execution_id, execution_realm)
                REFERENCES workflow_executions (id, realm) ON DELETE RESTRICT;
        """
    )

    op.execute(GUARD)
    _event_triggers(["workflow_events", "workflow_events_live", "workflow_events_simulation"])


def downgrade() -> None:
    op.execute(
        "ALTER TABLE ai_tool_invocations "
        "DROP CONSTRAINT fk_ai_tool_invocations_execution_id_workflow_executions, "
        "DROP COLUMN execution_realm"
    )
    for table in TABLES:
        identity = " INCLUDING IDENTITY" if table == "workflow_events" else ""
        op.execute(f"CREATE TABLE {table}_old (LIKE {table} INCLUDING DEFAULTS{identity})")
        op.execute(f"ALTER TABLE {table}_old DROP COLUMN realm")
    op.execute(
        f"INSERT INTO workflow_executions_old ({EXECUTION_COLUMNS}) "
        f"SELECT {EXECUTION_COLUMNS} FROM workflow_executions"
    )
    op.execute(
        f"INSERT INTO workflow_step_runs_old ({STEP_RUN_COLUMNS}) "
        f"SELECT {STEP_RUN_COLUMNS} FROM workflow_step_runs"
    )
    op.execute(
        f"INSERT INTO workflow_events_old ({EVENT_COLUMNS}) OVERRIDING SYSTEM VALUE "
        f"SELECT {EVENT_COLUMNS} FROM workflow_events"
    )
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE {table}")  # its partitions go with it
    for table in TABLES:
        op.execute(f"ALTER TABLE {table}_old RENAME TO {table}")
    op.execute("ALTER SEQUENCE workflow_events_old_seq_seq RENAME TO workflow_events_seq_seq")
    op.execute(
        "SELECT setval('workflow_events_seq_seq', "
        "COALESCE((SELECT max(seq) FROM workflow_events), 0) + 1, false)"
    )
    op.execute(
        """
        ALTER TABLE workflow_executions
            ADD CONSTRAINT pk_workflow_executions PRIMARY KEY (id),
            ADD CONSTRAINT uq_workflow_executions_idempotency
                UNIQUE (initiated_by, idempotency_key),
            ADD CONSTRAINT ck_workflow_executions_status_valid CHECK (status IN
                ('running', 'waiting', 'completed', 'failed', 'cancelled')),
            ADD CONSTRAINT fk_workflow_executions_definition_id_workflow_definitions
                FOREIGN KEY (definition_id) REFERENCES workflow_definitions (id)
                ON DELETE RESTRICT,
            ADD CONSTRAINT fk_workflow_executions_initiated_by_users
                FOREIGN KEY (initiated_by) REFERENCES users (id) ON DELETE RESTRICT,
            ADD CONSTRAINT fk_workflow_executions_simulation_run_id_simulation_runs
                FOREIGN KEY (simulation_run_id) REFERENCES simulation_runs (id)
                ON DELETE RESTRICT;
        CREATE INDEX ix_workflow_executions_business_key ON workflow_executions (business_key);
        CREATE INDEX ix_workflow_executions_initiated_by ON workflow_executions (initiated_by);
        CREATE INDEX ix_workflow_executions_simulation_run_id
            ON workflow_executions (simulation_run_id);
        CREATE INDEX ix_workflow_executions_status ON workflow_executions (status);
        CREATE INDEX ix_workflow_executions_workflow_status
            ON workflow_executions (workflow_id, status);

        ALTER TABLE workflow_step_runs
            ADD CONSTRAINT pk_workflow_step_runs PRIMARY KEY (id),
            ADD CONSTRAINT uq_workflow_step_runs_sequence UNIQUE (execution_id, sequence),
            ADD CONSTRAINT ck_workflow_step_runs_status_valid CHECK (status IN
                ('pending', 'waiting', 'completed', 'failed', 'cancelled')),
            ADD CONSTRAINT fk_workflow_step_runs_execution_id_workflow_executions
                FOREIGN KEY (execution_id) REFERENCES workflow_executions (id)
                ON DELETE RESTRICT,
            ADD CONSTRAINT fk_workflow_step_runs_actor_id_users
                FOREIGN KEY (actor_id) REFERENCES users (id) ON DELETE RESTRICT;
        CREATE INDEX ix_workflow_step_runs_execution_id ON workflow_step_runs (execution_id);
        CREATE INDEX ix_workflow_step_runs_due ON workflow_step_runs (status, not_before)
            WHERE status = 'pending';
        CREATE INDEX ix_workflow_step_runs_waiting_due ON workflow_step_runs (due_at)
            WHERE status = 'waiting';

        ALTER TABLE workflow_events
            ADD CONSTRAINT pk_workflow_events PRIMARY KEY (id),
            ADD CONSTRAINT uq_workflow_events_seq UNIQUE (seq),
            ADD CONSTRAINT fk_workflow_events_execution_id_workflow_executions
                FOREIGN KEY (execution_id) REFERENCES workflow_executions (id)
                ON DELETE RESTRICT,
            ADD CONSTRAINT fk_workflow_events_step_run_id_workflow_step_runs
                FOREIGN KEY (step_run_id) REFERENCES workflow_step_runs (id)
                ON DELETE RESTRICT,
            ADD CONSTRAINT fk_workflow_events_actor_id_users
                FOREIGN KEY (actor_id) REFERENCES users (id) ON DELETE RESTRICT;
        CREATE INDEX ix_workflow_events_execution_id ON workflow_events (execution_id);

        ALTER TABLE ai_tool_invocations
            ADD CONSTRAINT fk_ai_tool_invocations_execution_id_workflow_executions
                FOREIGN KEY (execution_id) REFERENCES workflow_executions (id)
                ON DELETE RESTRICT;
        -- NOT VALID: results of runs whose history was archived or reset (Phase 15) keep
        -- the id of an execution that is no longer stored; new rows are still checked.
        ALTER TABLE simulation_case_results
            ADD CONSTRAINT fk_simulation_case_results_execution_id_workflow_executions
                FOREIGN KEY (execution_id) REFERENCES workflow_executions (id)
                ON DELETE RESTRICT NOT VALID;
        """
    )
    op.execute(ORIGINAL_GUARD)
    op.execute(
        "CREATE TRIGGER workflow_events_no_update_delete BEFORE UPDATE OR DELETE "
        "ON workflow_events FOR EACH ROW EXECUTE FUNCTION workflow_events_append_only()"
    )
    op.execute(
        "CREATE TRIGGER workflow_events_no_truncate BEFORE TRUNCATE ON workflow_events "
        "FOR EACH STATEMENT EXECUTE FUNCTION workflow_events_append_only()"
    )
