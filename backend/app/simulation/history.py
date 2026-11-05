"""Simulation history: archive, restore and reset (Phase 15).

A simulation run leaves two kinds of data behind. Its results (summary, digest, one
measured row per case) are small and stay. Its workflow history (every execution, step
run and event, and every AI tool call) is large — roughly 16 step runs and 50 events per
case — and lives in the `simulation` partitions of the workflow tables (migration 0013).

- **Archive** writes a run's history to compressed PostgreSQL COPY files (one per table,
  with a manifest of row counts, columns and SHA-256 checksums), then deletes it from the
  database in the same transaction. The run is marked `archived`.
- **Restore** checks the files against the manifest and copies the rows back.
- **Reset** removes the history of every run at once by dropping and recreating the
  simulation partitions; with `archive=True` each run is archived first.

The live bank's history is never touched: it is in other partitions, and the guard on
workflow events refuses to delete live rows under any setting. Synthetic customers,
accounts and ledger postings that simulated cases created also stay, because the ledger is
append-only; only workflow history is archived.
"""

import gzip
import hashlib
import json
import logging
import os
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from psycopg import sql
from psycopg.errors import LockNotAvailable
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.core import locks
from app.core.audit import record_audit_event
from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.modules.accounts.models import Account
from app.modules.ai_tools.models import AIToolInvocation
from app.modules.experiments.models import Experiment, ExperimentStatus
from app.modules.workflows.models import (
    PARTITIONED_TABLES,
    Realm,
    WorkflowEvent,
    WorkflowExecution,
    partition_name,
)
from app.simulation.models import (
    HistoryState,
    SimulationArchive,
    SimulationArchiveSegment,
    SimulationRun,
    SimulationStatus,
)
from app.simulation.workloads import customer_keyed

logger = logging.getLogger("atlas.simulation.history")

FORMAT_VERSION = 1
# An archive made of segments, written while the run was going (Phase 75).
SEGMENTED_FORMAT = 2
# The disabled-by-default schedule that archives old runs (migration 0014).
RETENTION_SCHEDULE = "simulation-history-retention"
MANIFEST = "manifest.json"
# Set for the transaction that may delete simulation events (see migration 0013).
PURGE_SETTING = "atlas.simulation_history_purge"

_RUN_EXECUTIONS = (
    "SELECT id FROM workflow_executions WHERE realm = 'simulation' AND simulation_run_id = {run}"
)
# What belongs to one run, per table, in the order rows are restored (parents first).
_RUN_ROWS: dict[str, str] = {
    "workflow_executions": "realm = 'simulation' AND simulation_run_id = {run}",
    "workflow_step_runs": f"realm = 'simulation' AND execution_id IN ({_RUN_EXECUTIONS})",
    "workflow_events": f"realm = 'simulation' AND execution_id IN ({_RUN_EXECUTIONS})",
    "ai_tool_invocations": "simulation_run_id = {run}",
}


@dataclass
class ResetReport:
    archived: list[int] = field(default_factory=list)  # run numbers archived first
    purged: list[int] = field(default_factory=list)  # run numbers whose history was dropped
    rows: int = 0
    bytes_freed: int = 0


def archive_root() -> Path:
    return get_settings().simulation_archive_dir.resolve()


# The same tables, limited to some of the run's executions (a rolling-archive segment).
_SEGMENT_ROWS: dict[str, str] = {
    "workflow_executions": "realm = 'simulation' AND simulation_run_id = {run} AND id = ANY({ids})",
    "workflow_step_runs": "realm = 'simulation' AND execution_id = ANY({ids})",
    "workflow_events": "realm = 'simulation' AND execution_id = ANY({ids})",
    "ai_tool_invocations": "simulation_run_id = {run} AND execution_id = ANY({ids})",
}


def _where(table: str, run_id: uuid.UUID, ids: list[uuid.UUID] | None = None) -> sql.Composed:
    if ids is None:
        return sql.SQL(_RUN_ROWS[table]).format(run=sql.Literal(str(run_id)))
    return sql.SQL(_SEGMENT_ROWS[table]).format(
        run=sql.Literal(str(run_id)),
        ids=sql.SQL("{}::uuid[]").format(sql.Literal([str(i) for i in ids])),
    )


def _columns(db: Session, table: str) -> list[str]:
    """Stored columns (generated ones are derived again on restore)."""
    return list(
        db.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = :table "
                "AND is_generated = 'NEVER' ORDER BY ordinal_position"
            ),
            {"table": table},
        ).scalars()
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def summarize(db: Session, run_id: uuid.UUID, ids: list[uuid.UUID] | None = None) -> dict[str, Any]:
    """What the analytics still need about a run once its history is gone (or about some of
    its executions, `ids`, for a rolling-archive segment)."""
    in_run = (WorkflowExecution.realm == Realm.SIMULATION) & (
        WorkflowExecution.simulation_run_id == run_id
    )
    ai_filter = AIToolInvocation.simulation_run_id == run_id
    if ids is not None:
        in_run = in_run & WorkflowExecution.id.in_(ids)
        ai_filter = ai_filter & AIToolInvocation.execution_id.in_(ids)
    statuses = dict(
        db.execute(
            select(WorkflowExecution.status, func.count())
            .where(in_run)
            .group_by(WorkflowExecution.status)
        ).all()
    )
    timeouts = db.execute(
        select(func.count()).where(
            WorkflowEvent.realm == Realm.SIMULATION,
            WorkflowEvent.execution_id.in_(select(WorkflowExecution.id).where(in_run)),
            WorkflowEvent.event_type == "step.timed_out",
        )
    ).scalar_one()
    calls = dict(
        db.execute(
            select(AIToolInvocation.status, func.count())
            .where(ai_filter)
            .group_by(AIToolInvocation.status)
        ).all()
    )
    # Accounts of the customers the run's cases created (the dashboard counts them).
    customers = customer_keyed(in_run)
    accounts = db.execute(
        select(func.count()).select_from(Account).where(Account.customer_id.in_(customers))
    ).scalar_one()
    return {
        "accounts": accounts,
        "executions": sum(statuses.values()),
        "failed_executions": statuses.get("failed", 0),
        "document_timeouts": timeouts,
        "ai_calls": calls,
    }


def _add_summaries(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    total: dict[str, Any] = {
        "accounts": 0,
        "executions": 0,
        "failed_executions": 0,
        "document_timeouts": 0,
        "ai_calls": {},
    }
    for summary in summaries:
        for key in ("accounts", "executions", "failed_executions", "document_timeouts"):
            total[key] += summary.get(key, 0)
        for status, n in summary.get("ai_calls", {}).items():
            total["ai_calls"][status] = total["ai_calls"].get(status, 0) + n
    return total


def _lock_run(db: Session, run_id: uuid.UUID) -> SimulationRun:
    try:
        run = db.execute(
            select(SimulationRun)
            .where(SimulationRun.id == run_id)
            .with_for_update(nowait=True)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
    except OperationalError as exc:
        if isinstance(exc.orig, LockNotAvailable):
            raise ConflictError(
                "The run is being archived, restored or updated by another operation."
            ) from exc
        raise
    if run is None:
        raise NotFoundError("Simulation run not found.")
    return run


def check_archivable(db: Session, run: SimulationRun) -> None:
    if run.history_state != HistoryState.PRESENT:
        raise BusinessRuleViolation(
            f"Run {run.run_number}'s history is already {run.history_state}."
        )
    if run.status not in (SimulationStatus.COMPLETED, SimulationStatus.FAILED):
        raise BusinessRuleViolation(
            f"Run {run.run_number} is {run.status}; only finished runs can be archived."
        )
    in_experiment = db.execute(
        select(Experiment.experiment_number).where(
            Experiment.status == ExperimentStatus.RUNNING,
            (Experiment.baseline_run_id == run.id) | (Experiment.candidate_run_id == run.id),
        )
    ).first()
    if in_experiment:
        raise BusinessRuleViolation(
            f"Run {run.run_number} belongs to experiment {in_experiment[0]}, which is still "
            "running; archive it once the experiment has finished."
        )


def check_restorable(run: SimulationRun) -> None:
    if run.history_state != HistoryState.ARCHIVED:
        raise BusinessRuleViolation(
            f"Run {run.run_number}'s history is {run.history_state}; only archived history "
            "can be restored."
        )


def _delete(db: Session, table: str, run_id: uuid.UUID, ids: list[uuid.UUID] | None = None) -> int:
    raw = db.connection().connection.driver_connection
    with raw.cursor() as cursor:
        cursor.execute(
            sql.SQL("DELETE FROM {} WHERE {}").format(
                sql.Identifier(table), _where(table, run_id, ids)
            )
        )
        return cursor.rowcount


def _copy_out(
    db: Session, directory: Path, run_id: uuid.UUID, ids: list[uuid.UUID] | None = None
) -> dict[str, dict[str, Any]]:
    """Write the rows to compressed COPY files in `directory`, one per table."""
    raw = db.connection().connection.driver_connection
    tables: dict[str, dict[str, Any]] = {}
    for table in _RUN_ROWS:
        columns = _columns(db, table)
        path = directory / f"{table}.copy.gz"
        rows = 0
        query = sql.SQL("COPY (SELECT {} FROM {} WHERE {} ORDER BY id) TO STDOUT").format(
            sql.SQL(", ").join(map(sql.Identifier, columns)),
            sql.Identifier(table),
            _where(table, run_id, ids),
        )
        with raw.cursor() as cursor, gzip.open(path, "wb", compresslevel=6) as out:
            with cursor.copy(query) as copy:
                for data in copy:
                    out.write(data)
                    rows += bytes(data).count(b"\n")
        _fsync(path)
        tables[table] = {
            "file": path.name,
            "rows": rows,
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "columns": columns,
        }
    _fsync(directory)
    return tables


def _delete_archived(
    db: Session,
    tables: dict[str, dict[str, Any]],
    run_id: uuid.UUID,
    ids: list[uuid.UUID] | None = None,
) -> None:
    """Delete what was just copied out, checking every count against the files."""
    db.execute(text(f"SET LOCAL {PURGE_SETTING} = 'on'"))
    for table in reversed(_RUN_ROWS):  # children first
        deleted = _delete(db, table, run_id, ids)
        if deleted != tables[table]["rows"]:
            raise ConflictError(
                f"{table}: {deleted} rows to delete but {tables[table]['rows']} archived; "
                "the run's history changed while it was being archived."
            )


def rolling_location(run_number: int) -> str:
    return f"run-{run_number:06d}-rolling"


def archive_segment(
    db: Session,
    run_id: uuid.UUID,
    run_number: int,
    shard: int,
    sequence: int,
    ids: list[uuid.UUID] | None,
) -> SimulationArchiveSegment:
    """Archive part of a run's history while the run goes on (Phase 75), in the caller's
    transaction: the executions `ids` (finished cases) or, with `ids=None` at the end, all
    the run's history still in the database. The files stay if the transaction fails; a
    later segment with the same number overwrites them."""
    name = f"segment-{'rest' if shard < 0 else f'{shard:02d}'}-{sequence:05d}"
    location = f"{rolling_location(run_number)}/{name}"
    directory = archive_root() / location
    directory.mkdir(parents=True, exist_ok=True)
    summary = summarize(db, run_id, ids)
    tables = _copy_out(db, directory, run_id, ids)
    _delete_archived(db, tables, run_id, ids)
    segment = SimulationArchiveSegment(
        run_id=run_id,
        shard=shard,
        sequence=sequence,
        location=location,
        manifest={"format": FORMAT_VERSION, "tables": tables},
        summary=summary,
        rows=sum(t["rows"] for t in tables.values()),
        bytes=sum(t["bytes"] for t in tables.values()),
    )
    db.add(segment)
    db.flush()
    return segment


def archive_run(
    factory: sessionmaker[Session], run_id: uuid.UUID, actor_id: uuid.UUID | None
) -> SimulationArchive:
    """Move one finished run's workflow history to archive files. A run with a rolling
    archive already moved most of it while it ran: the rest becomes a last segment, and
    the segments become the one archive."""
    root = archive_root()
    directory: Path | None = None
    try:
        with factory() as db, db.begin():
            run = _lock_run(db, run_id)
            check_archivable(db, run)
            segments = list(
                db.execute(
                    select(SimulationArchiveSegment)
                    .where(SimulationArchiveSegment.run_id == run.id)
                    .order_by(SimulationArchiveSegment.shard, SimulationArchiveSegment.sequence)
                ).scalars()
            )
            if segments:
                rest = archive_segment(db, run.id, run.run_number, -1, 0, None)
                segments.append(rest)
                location = rolling_location(run.run_number)
                tables = {
                    table: {"rows": sum(s.manifest["tables"][table]["rows"] for s in segments)}
                    for table in _RUN_ROWS
                }
                manifest = {
                    "format": SEGMENTED_FORMAT,
                    "run_id": str(run.id),
                    "run_number": run.run_number,
                    "archived_at": datetime.now(UTC).isoformat(),
                    "tables": tables,
                    "segments": [
                        {"location": s.location, "tables": s.manifest["tables"]} for s in segments
                    ],
                }
                summary = _add_summaries([s.summary for s in segments])
                total_rows = sum(s.rows for s in segments)
                total_bytes = sum(s.bytes for s in segments)
            else:
                summary = summarize(db, run.id)
                stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
                location = f"run-{run.run_number:06d}-{stamp}-{uuid.uuid4().hex[:6]}"
                directory = root / location
                directory.mkdir(parents=True)
                tables = _copy_out(db, directory, run.id)
                manifest = {
                    "format": FORMAT_VERSION,
                    "run_id": str(run.id),
                    "run_number": run.run_number,
                    "archived_at": datetime.now(UTC).isoformat(),
                    "tables": tables,
                }
                _delete_archived(db, tables, run.id)
                total_rows = sum(t["rows"] for t in tables.values())
                total_bytes = sum(t["bytes"] for t in tables.values())
            (root / location / MANIFEST).write_text(json.dumps(manifest, indent=2))
            _fsync(root / location / MANIFEST)
            _fsync(root / location)

            record = SimulationArchive(
                run_id=run.id,
                kind="archive",
                location=location,
                manifest=manifest,
                summary=summary,
                rows=total_rows,
                bytes=total_bytes,
                created_by=actor_id,
            )
            db.add(record)
            run.history_state = HistoryState.ARCHIVED
            record_audit_event(
                db,
                actor_id=actor_id,
                action="simulation_history.archived",
                entity_type="simulation_run",
                entity_id=run.id,
                metadata={
                    "run_number": run.run_number,
                    "location": location,
                    "rows": total_rows,
                    "bytes": total_bytes,
                    **({"segments": len(segments)} if segments else {}),
                },
            )
            db.flush()
    except BaseException:
        if directory is not None:
            shutil.rmtree(directory, ignore_errors=True)
        raise
    logger.info(
        "simulation history archived",
        extra={"run_number": run.run_number, "rows": total_rows, "bytes": total_bytes},
    )
    return record


def restore_run(
    factory: sessionmaker[Session], run_id: uuid.UUID, actor_id: uuid.UUID | None
) -> SimulationArchive:
    """Copy an archived run's history back into the database."""
    root = archive_root()
    with factory() as db, db.begin():
        run = _lock_run(db, run_id)
        check_restorable(run)
        record = db.execute(
            select(SimulationArchive).where(
                SimulationArchive.run_id == run.id, SimulationArchive.restored_at.is_(None)
            )
        ).scalar_one()
        assert record.location is not None
        directory = root / record.location
        # One set of files, or one per segment of a rolling archive (Phase 75).
        parts = (
            [(root / seg["location"], seg["tables"]) for seg in record.manifest["segments"]]
            if record.manifest.get("format") == SEGMENTED_FORMAT
            else [(directory, record.manifest["tables"])]
        )
        for folder, tables in parts:
            for entry in tables.values():
                path = folder / entry["file"]
                if not path.is_file():
                    raise BusinessRuleViolation(f"Archive file {path} is missing.")
                if _sha256(path) != entry["sha256"]:
                    raise BusinessRuleViolation(f"Archive file {path} does not match its checksum.")

        raw = db.connection().connection.driver_connection
        for table in _RUN_ROWS:  # parents first, across every segment
            for folder, tables in parts:
                entry = tables[table]
                query = sql.SQL("COPY {} ({}) FROM STDIN").format(
                    sql.Identifier(table),
                    sql.SQL(", ").join(map(sql.Identifier, entry["columns"])),
                )
                with raw.cursor() as cursor:
                    with cursor.copy(query) as copy, gzip.open(folder / entry["file"], "rb") as f:
                        for chunk in iter(lambda f=f: f.read(1 << 20), b""):
                            copy.write(chunk)
                    if cursor.rowcount != entry["rows"]:
                        raise ConflictError(
                            f"{table}: restored {cursor.rowcount} rows, the manifest lists "
                            f"{entry['rows']}."
                        )
        # The history is whole again: its segments are superseded (the archive record keeps
        # their manifest), so a later archive starts afresh.
        db.execute(
            SimulationArchiveSegment.__table__.delete().where(
                SimulationArchiveSegment.run_id == run.id
            )
        )
        record.restored_at = datetime.now(UTC)
        record.restored_by = actor_id
        run.history_state = HistoryState.PRESENT
        record_audit_event(
            db,
            actor_id=actor_id,
            action="simulation_history.restored",
            entity_type="simulation_run",
            entity_id=run.id,
            metadata={"run_number": run.run_number, "location": record.location},
        )
        db.flush()
    # The rows are back in the database; the files are no longer the only copy. A backup in
    # progress may have taken its snapshot before the rows committed, so wait for it to pack
    # the files first (PR #78 review).
    with factory() as db, db.begin():
        locks.hold_exclusive(db, locks.ARCHIVE_FILES)
        shutil.rmtree(directory, ignore_errors=True)
    return record


def archive_older_than(
    factory: sessionmaker[Session], days: int, actor_id: uuid.UUID | None
) -> list[int]:
    """Archive every finished run older than `days` whose history is still present."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    with factory() as db:
        candidates = db.execute(
            select(SimulationRun.id, SimulationRun.run_number)
            .where(
                SimulationRun.history_state == HistoryState.PRESENT,
                SimulationRun.status.in_([SimulationStatus.COMPLETED, SimulationStatus.FAILED]),
                SimulationRun.created_at < cutoff,
            )
            .order_by(SimulationRun.run_number)
        ).all()
    archived = []
    for run_id, run_number in candidates:
        try:
            archive_run(factory, run_id, actor_id)
        except BusinessRuleViolation as exc:  # e.g. still part of a running experiment
            logger.info("run not archived", extra={"run_number": run_number, "reason": str(exc)})
            continue
        archived.append(run_number)
    return archived


# --- Reset --------------------------------------------------------------------------------


def _create_simulation_partitions(db: Session) -> None:
    for table in PARTITIONED_TABLES:  # parents before children (foreign keys)
        db.execute(
            text(
                f"CREATE TABLE {partition_name(table, Realm.SIMULATION)} PARTITION OF {table} "
                f"FOR VALUES IN ('{Realm.SIMULATION.value}')"
            )
        )
    events = partition_name("workflow_events", Realm.SIMULATION)
    db.execute(
        text(
            f"CREATE TRIGGER {events}_no_truncate BEFORE TRUNCATE ON {events} "
            "FOR EACH STATEMENT EXECUTE FUNCTION workflow_events_append_only()"
        )
    )


def simulation_partition_bytes(db: Session) -> int:
    return sum(
        db.execute(
            text("SELECT pg_total_relation_size(CAST(:name AS regclass))"),
            {"name": partition_name(table, Realm.SIMULATION)},
        ).scalar_one()
        for table in PARTITIONED_TABLES
    )


def reset(
    factory: sessionmaker[Session], actor_id: uuid.UUID | None, *, archive: bool
) -> ResetReport:
    """Remove the workflow history of every simulation run (optionally archiving it first).

    Drops and recreates the simulation partitions, which is instant however large they
    are, instead of deleting row by row. Refused while a simulation is queued or running.
    """
    report = ResetReport()
    with factory() as db:
        _ensure_no_active_runs(db)
    if archive:
        with factory() as db:
            present = db.execute(
                select(SimulationRun.id)
                .where(SimulationRun.history_state == HistoryState.PRESENT)
                .order_by(SimulationRun.run_number)
            ).scalars()
            run_ids = list(present)
        for run_id in run_ids:
            record = archive_run(factory, run_id, actor_id)
            report.archived.append(record.manifest["run_number"])

    with factory() as db, db.begin():
        db.execute(text("SET LOCAL lock_timeout = '15s'"))
        db.execute(text(f"SET LOCAL {PURGE_SETTING} = 'on'"))
        # No run may start (or finish writing) while the partitions are replaced.
        db.execute(text("LOCK TABLE simulation_runs IN SHARE ROW EXCLUSIVE MODE"))
        _ensure_no_active_runs(db)
        runs = list(
            db.execute(
                select(SimulationRun)
                .where(SimulationRun.history_state == HistoryState.PRESENT)
                .order_by(SimulationRun.run_number)
            ).scalars()
        )
        summaries = {run.id: summarize(db, run.id) for run in runs}
        report.bytes_freed = simulation_partition_bytes(db)
        per_run = _rows_per_run(db)
        counts = {table: sum(n.get(table, 0) for n in per_run.values()) for table in _RUN_ROWS}
        db.execute(
            AIToolInvocation.__table__.delete().where(
                AIToolInvocation.simulation_run_id.is_not(None)
            )
        )
        for table in reversed(PARTITIONED_TABLES):  # children first
            partition = partition_name(table, Realm.SIMULATION)
            db.execute(text(f"ALTER TABLE {table} DETACH PARTITION {partition}"))
            db.execute(text(f"DROP TABLE {partition}"))
        _create_simulation_partitions(db)

        for run in runs:
            summary = summaries[run.id]
            db.add(
                SimulationArchive(
                    run_id=run.id,
                    kind="purge",
                    location=None,
                    manifest={
                        "format": FORMAT_VERSION,
                        "run_number": run.run_number,
                        "tables": {t: {"rows": n} for t, n in per_run.get(run.id, {}).items()},
                    },
                    summary=summary,
                    rows=sum(per_run.get(run.id, {}).values()),
                    bytes=0,
                    created_by=actor_id,
                )
            )
            report.purged.append(run.run_number)
        if runs:
            db.execute(
                update(SimulationRun)
                .where(SimulationRun.id.in_([r.id for r in runs]))
                .values(history_state=HistoryState.PURGED)
            )
        report.rows = sum(counts.values())
        record_audit_event(
            db,
            actor_id=actor_id,
            action="simulation_history.reset",
            entity_type="simulation_history",
            entity_id=None,
            metadata={
                "archived_runs": report.archived,
                "purged_runs": report.purged,
                "rows": counts,
                "bytes_freed": report.bytes_freed,
            },
        )
    return report


def _rows_per_run(db: Session) -> dict[uuid.UUID, dict[str, int]]:
    """Rows of simulation history per run and table (one grouped scan per table)."""
    executions = partition_name("workflow_executions", Realm.SIMULATION)
    queries = {
        "workflow_executions": f"SELECT simulation_run_id, count(*) FROM {executions} GROUP BY 1",  # nosec B608
        "ai_tool_invocations": "SELECT simulation_run_id, count(*) FROM ai_tool_invocations "
        "WHERE simulation_run_id IS NOT NULL GROUP BY 1",
    }
    for table in ("workflow_step_runs", "workflow_events"):
        partition = partition_name(table, Realm.SIMULATION)
        queries[table] = (
            f"SELECT e.simulation_run_id, count(*) FROM {partition} t "  # nosec B608
            f"JOIN {executions} e ON e.id = t.execution_id GROUP BY 1"
        )
    per_run: dict[uuid.UUID, dict[str, int]] = {}
    for table, query in queries.items():
        for run_id, n in db.execute(text(query)).all():
            per_run.setdefault(run_id, {})[table] = n
    return per_run


def _ensure_no_active_runs(db: Session) -> None:
    active = db.execute(
        select(func.count()).where(
            SimulationRun.status.in_([SimulationStatus.QUEUED, SimulationStatus.RUNNING])
        )
    ).scalar_one()
    if active:
        raise BusinessRuleViolation(
            f"{active} simulation run(s) are queued or running; reset once they have finished."
        )
