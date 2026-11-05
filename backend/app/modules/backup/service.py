"""Backup, restore and a tested recovery procedure (Phase 87).

A backup is a directory holding three files:

- `database.dump`: `pg_dump` in its custom format, taken from an exported snapshot;
- `files.tar.gz`: the audit-log archive and the simulation-history archive directories;
- `manifest.json`: what the backup should restore to — the schema revision, the row counts
  of the key tables, the ledger's totals, the newest audit event, the audit archives' chain
  head — all read inside the same snapshot as the dump, plus each file's size and SHA-256.

`verify` re-reads a backup without restoring it: every digest, and the dump's table of
contents. `restore` loads a verified backup into an empty database (and, when given, the
archive files into empty directories), then checks the result against the manifest.
`drill` is the recovery procedure run end to end against a scratch database, timed.

The database is dumped first and the files after it, so every archive the dump records is
in the files (a file written by an archiving transaction that then failed may be there too,
unreferenced; that is harmless).
"""

import hashlib
import json
import os
import re
import shutil
import subprocess  # nosec B404 - runs the PostgreSQL client tools with fixed arguments
import tarfile
import tempfile
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, func, select, table, text
from sqlalchemy.engine import URL, Connection, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app import __version__
from app.config import Settings
from app.core import locks
from app.core.audit import record_audit_event
from app.core.errors import BusinessRuleViolation
from app.modules.backup.models import BackupKind, BackupRun

MANIFEST = "manifest.json"
DUMP = "database.dump"
FILES = "files.tar.gz"
FORMAT = 1
# The tables whose row counts a restore must reproduce exactly.
KEY_TABLES = (
    "users",
    "customers",
    "accounts",
    "journal_entries",
    "journal_lines",
    "audit_events",
    "audit_archives",
    "simulation_runs",
    "workflow_definitions",
    "employees",
    "payments",
)
_DATABASE_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


class BackupError(BusinessRuleViolation):
    code = "backup_failed"


# --- helpers ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _url(database_url: str | URL) -> URL:
    return make_url(database_url) if isinstance(database_url, str) else database_url


def _pg_env(url: URL) -> dict[str, str]:
    """The libpq environment for the client tools; the password never goes on a command
    line, where other users could read it."""
    env = dict(os.environ)
    for key, value in (
        ("PGHOST", url.host), ("PGPORT", url.port), ("PGUSER", url.username),
        ("PGPASSWORD", url.password), ("PGDATABASE", url.database),
    ):  # fmt: skip
        if value is not None:
            env[key] = str(value)
    return env


def _run(args: list[str], url: URL) -> subprocess.CompletedProcess[str]:
    tool = shutil.which(args[0])
    if tool is None:
        raise BackupError(f"{args[0]} is not installed; install the PostgreSQL client tools.")
    result = subprocess.run(  # nosec B603 - fixed arguments, no shell
        [tool, *args[1:]], env=_pg_env(url), capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise BackupError(f"{args[0]} failed: {result.stderr.strip()[-2000:]}")
    return result


def _sha256(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as raw:
        for chunk in iter(lambda: raw.read(1 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _engine(url: URL):
    return create_engine(url)


def _archive_dirs(settings: Settings) -> dict[str, Path]:
    return {
        "audit-archive": settings.audit_archive_dir,
        "simulation-archive": settings.simulation_archive_dir,
    }


# --- what a backup must restore to ---------------------------------------------------


def facts(conn: Connection) -> dict[str, Any]:
    """The state a restore must reproduce, read on `conn` (inside the dump's snapshot)."""
    revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    counts = {
        name: conn.execute(select(func.count()).select_from(table(name))).scalar_one()
        for name in KEY_TABLES
    }
    ledger = conn.execute(
        text(
            "SELECT count(*) FILTER (WHERE d <> c OR n < 2), coalesce(sum(d), 0),"
            " coalesce(sum(c), 0) FROM ("
            " SELECT e.id, count(l.id) AS n,"
            " coalesce(sum(l.amount) FILTER (WHERE l.direction = 'debit'), 0) AS d,"
            " coalesce(sum(l.amount) FILTER (WHERE l.direction = 'credit'), 0) AS c"
            " FROM journal_entries e LEFT JOIN journal_lines l ON l.journal_entry_id = e.id"
            " GROUP BY e.id) AS per_entry"
        )
    ).one()
    newest = conn.execute(
        text("SELECT id, timestamp FROM audit_events ORDER BY timestamp DESC, id DESC LIMIT 1")
    ).one_or_none()
    head = conn.execute(
        text("SELECT archive_number, sha256 FROM audit_archives ORDER BY archive_number DESC"
             " LIMIT 1")
    ).one_or_none()  # fmt: skip
    return {
        "alembic_revision": sorted(revision),
        "row_counts": counts,
        "ledger": {
            "unbalanced_entries": int(ledger[0]),
            "debits": int(ledger[1]),
            "credits": int(ledger[2]),
        },
        "newest_audit_event": (
            {"id": str(newest[0]), "timestamp": newest[1].isoformat()} if newest else None
        ),
        "audit_archive_head": (
            {"archive_number": int(head[0]), "sha256": head[1]} if head else None
        ),
    }


# --- create ----------------------------------------------------------------------------


@contextmanager
def _snapshot(url: URL) -> Iterator[tuple[Connection, str]]:
    """A repeatable-read transaction held open with its snapshot exported, so `pg_dump`
    and the manifest see exactly the same data while the bank keeps running."""
    engine = _engine(url)
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
            with conn.begin():
                conn.execute(text("SET TRANSACTION READ ONLY"))
                # No archive file the snapshot refers to may be deleted until the files are
                # packed (PR #78 review): a restored run's archive is removed only after
                # its rows commit, which this snapshot may not see.
                locks.hold_shared(conn, locks.ARCHIVE_FILES)
                snapshot = conn.execute(text("SELECT pg_export_snapshot()")).scalar_one()
                yield conn, snapshot
    finally:
        engine.dispose()


def _pack_files(path: Path, settings: Settings) -> dict[str, int]:
    counts: dict[str, int] = {}
    with tarfile.open(path, "w:gz") as archive:
        for name, directory in _archive_dirs(settings).items():
            directory = Path(directory)
            files = sorted(p for p in directory.rglob("*") if p.is_file())
            counts[name] = len(files)
            for file in files:
                archive.add(file, arcname=f"{name}/{file.relative_to(directory).as_posix()}")
    return counts


def create(destination: Path, settings: Settings, *, database_url: str | None = None) -> Path:
    """Take a backup into a new directory under `destination`; returns its path."""
    url = _url(database_url or settings.database_url)
    started = _now()
    target = Path(destination) / f"atlas-backup-{started.strftime('%Y%m%dT%H%M%S%fZ')}"
    target.mkdir(parents=True, exist_ok=False)
    timings: dict[str, float] = {}
    clock = time.perf_counter()
    with _snapshot(url) as (conn, snapshot):
        state = facts(conn)
        snapshot_at = conn.execute(text("SELECT now()")).scalar_one()
        server = conn.execute(text("SHOW server_version")).scalar_one()
        _run(
            ["pg_dump", "--format=custom", "--no-owner", "--no-privileges",
             f"--snapshot={snapshot}", f"--file={target / DUMP}"],
            url,
        )  # fmt: skip
        timings["database_s"] = round(time.perf_counter() - clock, 3)
        clock = time.perf_counter()
        # Still inside the snapshot's transaction, so its archive-files lock is held.
        file_counts = _pack_files(target / FILES, settings)
        timings["files_s"] = round(time.perf_counter() - clock, 3)
    manifest = {
        "format": FORMAT,
        "created_at": started.isoformat(),
        "snapshot_at": snapshot_at.isoformat(),
        "app_version": __version__,
        "server_version": server,
        "source_database": url.database,
        **state,
        "archive_files": file_counts,
        "timings": timings,
        "files": {
            name: {"bytes": (target / name).stat().st_size, "sha256": _sha256(target / name)}
            for name in (DUMP, FILES)
        },
    }
    (target / MANIFEST).write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    return target


def read_manifest(backup: Path) -> dict[str, Any]:
    path = Path(backup) / MANIFEST
    if not path.exists():
        raise BackupError(f"{path} is missing: this is not a backup directory.")
    return json.loads(path.read_text())


# --- verify ----------------------------------------------------------------------------


def verify(backup: Path, *, database_url: str | URL | None = None) -> dict[str, Any]:
    """Check a backup without restoring it: the files' digests, the dump's table of
    contents and the files archive's members."""
    backup = Path(backup)
    problems: list[str] = []
    try:
        manifest = read_manifest(backup)
    except (BackupError, ValueError) as exc:
        return {"ok": False, "problems": [str(exc)]}
    if manifest.get("format") != FORMAT:
        problems.append(f"unknown backup format {manifest.get('format')!r}")
    for name, expected in manifest.get("files", {}).items():
        path = backup / name
        if not path.exists():
            problems.append(f"{name} is missing")
            continue
        if path.stat().st_size != expected["bytes"]:
            problems.append(f"{name} is {path.stat().st_size} bytes, the manifest says "
                            f"{expected['bytes']}")  # fmt: skip
        if _sha256(path) != expected["sha256"]:
            problems.append(f"{name}'s digest does not match the manifest")
    toc_entries = None
    if not problems:
        try:
            url = _url(database_url or URL.create("postgresql"))
            toc = _run(["pg_restore", "--list", str(backup / DUMP)], url)
            toc_entries = sum(1 for line in toc.stdout.splitlines() if line and line[0] != ";")
            data = sum(1 for line in toc.stdout.splitlines() if " TABLE DATA " in line)
            if data < len(KEY_TABLES):
                problems.append(f"the dump holds data for only {data} tables")
        except BackupError as exc:
            problems.append(str(exc))
        try:
            with tarfile.open(backup / FILES, "r:gz") as archive:
                members = [m for m in archive.getmembers() if m.isfile()]
            expected_files = sum(manifest.get("archive_files", {}).values())
            if len(members) != expected_files:
                problems.append(f"the files archive holds {len(members)} files, the manifest "
                                f"says {expected_files}")  # fmt: skip
        except (tarfile.TarError, OSError) as exc:
            problems.append(f"the files archive cannot be read: {exc}")
    return {"ok": not problems, "problems": problems, "dump_entries": toc_entries,
            "created_at": manifest.get("created_at")}  # fmt: skip


# --- restore ---------------------------------------------------------------------------


def _public_tables(url: URL) -> int:
    engine = _engine(url)
    try:
        with engine.connect() as conn:
            return conn.execute(
                text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
            ).scalar_one()
    finally:
        engine.dispose()


def _restore_list(backup: Path, url: URL, workdir: Path) -> Path:
    """The dump's table of contents without the extensions' comments: only an extension's
    owner (a superuser, for pg_trgm) may comment on it, and the comment carries no data."""
    toc = _run(["pg_restore", "--list", str(backup / DUMP)], url).stdout
    kept = [line for line in toc.splitlines() if " COMMENT - EXTENSION " not in line]
    path = workdir / "restore.list"
    path.write_text("\n".join(kept) + "\n")
    return path


def _check_files_root(files_root: Path, *, force: bool) -> None:
    if files_root.exists() and not files_root.is_dir():
        raise BackupError(f"{files_root} is not a directory.")
    if files_root.exists() and any(files_root.iterdir()) and not force:
        raise BackupError(f"{files_root} is not empty; restore the files into an empty "
                          "directory, or pass force.")  # fmt: skip


def _extract(backup: Path, files_root: Path, *, force: bool) -> dict[str, int]:
    files_root = Path(files_root)
    _check_files_root(files_root, force=force)
    files_root.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    with tarfile.open(backup / FILES, "r:gz") as archive:
        # The "data" filter refuses absolute paths, links out of the tree and devices.
        archive.extractall(files_root, filter="data")
        for member in archive.getmembers():
            if member.isfile():
                top = member.name.split("/", 1)[0]
                counts[top] = counts.get(top, 0) + 1
    return counts


def checks(url: URL, manifest: dict[str, Any], files_root: Path | None) -> list[dict[str, Any]]:
    """Compare a restored database (and files) with the manifest it came from."""
    engine = _engine(url)
    try:
        with engine.connect() as conn:
            state = facts(conn)
            archives = conn.execute(
                text("SELECT archive_number, location, sha256, previous_sha256, events"
                     " FROM audit_archives ORDER BY archive_number")
            ).all()  # fmt: skip
    finally:
        engine.dispose()
    results: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str) -> None:
        results.append({"name": name, "passed": bool(passed), "detail": detail})

    check(
        "Schema revision", state["alembic_revision"] == manifest["alembic_revision"],
        f"{', '.join(state['alembic_revision'])} (backup: "
        f"{', '.join(manifest['alembic_revision'])})",
    )  # fmt: skip
    differing = {
        name: (manifest["row_counts"].get(name), count)
        for name, count in state["row_counts"].items()
        if manifest["row_counts"].get(name) != count
    }
    check(
        "Row counts", not differing,
        f"{len(state['row_counts'])} tables, {sum(state['row_counts'].values())} rows"
        if not differing else
        "; ".join(f"{k}: {a} expected, {b} restored" for k, (a, b) in differing.items()),
    )  # fmt: skip
    ledger = state["ledger"]
    check(
        "Ledger balances",
        ledger == manifest["ledger"] and ledger["unbalanced_entries"] == 0
        and ledger["debits"] == ledger["credits"],
        f"debits {ledger['debits']}, credits {ledger['credits']}, "
        f"{ledger['unbalanced_entries']} unbalanced entries",
    )  # fmt: skip
    check(
        "Newest audit event", state["newest_audit_event"] == manifest["newest_audit_event"],
        str((state["newest_audit_event"] or {}).get("timestamp", "none")),
    )  # fmt: skip
    if files_root is not None:
        problems: list[str] = []
        previous: str | None = None
        directory = Path(files_root) / "audit-archive"
        for number, location, sha, previous_sha, _events in archives:
            if previous_sha != previous:
                problems.append(f"archive {number}: the chain is broken")
            path = directory / location
            if not path.exists():
                problems.append(f"archive {number}: {location} is missing")
            elif _sha256(path) != sha:
                problems.append(f"archive {number}: the file's digest differs")
            previous = sha
        check(
            "Audit archive chain", not problems,
            "; ".join(problems) if problems else f"{len(archives)} archives, every file and "
            "link intact",
        )  # fmt: skip
    return results


def restore(
    backup: Path, target_url: str | URL, *, files_root: Path | None = None, force: bool = False,
    jobs: int = 1,
) -> dict[str, Any]:  # fmt: skip
    """Restore a backup into `target_url` (empty, or emptied when `force`), and its archive
    files under `files_root`; then check the result against the manifest."""
    backup = Path(backup)
    url = _url(target_url)
    started = time.perf_counter()
    verification = verify(backup, database_url=url)
    if not verification["ok"]:
        raise BackupError("The backup failed verification: " + "; ".join(verification["problems"]))
    manifest = read_manifest(backup)
    # Every destination is checked before anything is written, so a refused restore leaves
    # the target as it was (PR #78 review).
    if files_root is not None:
        _check_files_root(Path(files_root), force=force)
    existing = _public_tables(url)
    if existing and not force:
        raise BackupError(f"The target database {url.database} has {existing} tables; restore "
                          "into an empty database, or pass force to replace it.")  # fmt: skip
    if existing:
        engine = _engine(url)
        try:
            with engine.begin() as conn:
                conn.execute(text("DROP SCHEMA public CASCADE"))
                conn.execute(text("CREATE SCHEMA public"))
        finally:
            engine.dispose()
    timings = {"verify_s": round(time.perf_counter() - started, 3)}
    clock = time.perf_counter()
    with tempfile.TemporaryDirectory() as workdir:
        listing = _restore_list(backup, url, Path(workdir))
        args = ["pg_restore", "--exit-on-error", "--no-owner", "--no-privileges",
                f"--use-list={listing}", f"--dbname={url.database}"]  # fmt: skip
        args += [f"--jobs={jobs}"] if jobs > 1 else ["--single-transaction"]
        _run([*args, str(backup / DUMP)], url)
    timings["database_s"] = round(time.perf_counter() - clock, 3)
    clock = time.perf_counter()
    files = _extract(backup, files_root, force=force) if files_root is not None else None
    timings["files_s"] = round(time.perf_counter() - clock, 3)
    clock = time.perf_counter()
    results = checks(url, manifest, files_root)
    timings["checks_s"] = round(time.perf_counter() - clock, 3)
    timings["total_s"] = round(time.perf_counter() - started, 3)
    return {
        "ok": all(c["passed"] for c in results),
        "backup": str(backup),
        "backup_created_at": manifest["created_at"],
        "target_database": url.database,
        "files_restored": files,
        "checks": results,
        "timings": timings,
    }


# --- the drill -------------------------------------------------------------------------


def _admin_url(url: URL) -> URL:
    return url.set(database="postgres")


def _drop(conn: Connection, name: str) -> None:
    """Drop a scratch database. A plain DROP first: PostgreSQL itself stops autovacuum
    workers in the way (they run as the superuser, so a non-superuser's FORCE may not
    terminate them, as after a large restore). FORCE only for other sessions left open."""
    quoted = conn.dialect.identifier_preparer.quote(name)
    for attempt in range(5):
        try:
            conn.execute(text(f"DROP DATABASE IF EXISTS {quoted}"))
            return
        except DBAPIError as exc:
            if "is being accessed by other users" not in str(exc.orig):
                raise
            if attempt == 2:
                try:
                    conn.execute(text(f"DROP DATABASE IF EXISTS {quoted} WITH (FORCE)"))
                    return
                except DBAPIError:
                    pass  # autovacuum again, or a session we may not end: retry plain
            time.sleep(2)
    raise BackupError(f"The database {name} is still in use and cannot be dropped.")


def _admin(url: URL):
    return create_engine(_admin_url(url), isolation_level="AUTOCOMMIT")


def _recreate_database(url: URL, name: str) -> None:
    if not _DATABASE_NAME.match(name):
        raise BackupError(f"'{name}' is not a plain database name.")
    if name == url.database:
        raise BackupError("The drill database must not be the database being backed up.")
    engine = _admin(url)
    try:
        with engine.connect() as conn:
            _drop(conn, name)
            quoted = conn.dialect.identifier_preparer.quote(name)
            conn.execute(text(f"CREATE DATABASE {quoted}"))
    finally:
        engine.dispose()


def drop_database(url: URL, name: str) -> None:
    if not _DATABASE_NAME.match(name) or name == url.database:
        raise BackupError(f"Refusing to drop '{name}'.")
    engine = _admin(url)
    try:
        with engine.connect() as conn:
            _drop(conn, name)
    finally:
        engine.dispose()


def drill(
    destination: Path, settings: Settings, *, scratch_database: str = "atlas_drill",
    keep: bool = False, database_url: str | None = None, jobs: int = 1,
) -> dict[str, Any]:  # fmt: skip
    """The recovery procedure, end to end: back up the live database, restore the backup
    into a scratch database (and its files into a scratch directory), check the result.

    Recovery time (RTO) is measured from the start of the restore to the last check;
    the recovery point (RPO) is the backup's snapshot time: everything committed after it
    would be lost if the live database were lost now."""
    source = _url(database_url or settings.database_url)
    started = time.perf_counter()
    backup = create(Path(destination), settings, database_url=source.render_as_string(False))
    backup_s = round(time.perf_counter() - started, 3)
    manifest = read_manifest(backup)
    scratch = source.set(database=scratch_database)
    _recreate_database(source, scratch_database)
    files_root = backup.parent / f"{backup.name}-drill-files"
    cleanup: str | None = None
    try:
        result = restore(backup, scratch, files_root=files_root, jobs=jobs)
        restored_at = _now()
    finally:
        if not keep:
            shutil.rmtree(files_root, ignore_errors=True)
            try:
                drop_database(source, scratch_database)
            except (BackupError, DBAPIError) as exc:
                # The drill's result stands; the scratch database is left to drop by hand.
                cleanup = f"The scratch database {scratch_database} was not dropped: {exc}"
    snapshot_at = datetime.fromisoformat(manifest["snapshot_at"])
    return {
        **result,
        "backup": str(backup),
        "scratch_database": scratch_database,
        "kept": keep,
        "cleanup_problem": cleanup,
        "backup_bytes": sum(f["bytes"] for f in manifest["files"].values()),
        "row_counts": manifest["row_counts"],
        "measured": {
            "backup_s": backup_s,
            "rto_s": result["timings"]["total_s"],
            "rpo_s": round((restored_at - snapshot_at).total_seconds(), 3),
            "total_s": round(time.perf_counter() - started, 3),
        },
    }


# --- the record ------------------------------------------------------------------------


def record(
    db: Session, kind: str, *, ok: bool, location: str, details: dict[str, Any],
    started_at: datetime, actor_id: uuid.UUID | None = None,
) -> BackupRun:  # fmt: skip
    run = BackupRun(
        kind=kind, ok=ok, location=location[:500], details=details, started_at=started_at,
        finished_at=_now(), created_by=actor_id,
    )  # fmt: skip
    db.add(run)
    db.flush()
    record_audit_event(
        db, actor_id=actor_id, action=f"backup.{kind}", entity_type="backup_run",
        entity_id=run.id, metadata={"ok": ok, "location": location[:500]},
    )  # fmt: skip
    return run


def runs(db: Session, *, kind: str | None = None, limit: int = 50) -> list[BackupRun]:
    query = select(BackupRun).order_by(BackupRun.run_number.desc()).limit(limit)
    if kind:
        query = query.where(BackupRun.kind == kind)
    return list(db.execute(query).scalars())


def status(db: Session) -> dict[str, Any]:
    """The latest successful backup and drill, and how old the recovery point is."""

    def latest(kind: str) -> BackupRun | None:
        return db.execute(
            select(BackupRun).where(BackupRun.kind == kind, BackupRun.ok.is_(True))
            .order_by(BackupRun.run_number.desc()).limit(1)
        ).scalar_one_or_none()  # fmt: skip

    backup, drill_run = latest(BackupKind.BACKUP), latest(BackupKind.DRILL)
    newest = max((r for r in (backup, drill_run) if r), key=lambda r: r.finished_at, default=None)
    return {
        "latest_backup": serialize(backup) if backup else None,
        "latest_drill": serialize(drill_run) if drill_run else None,
        "recovery_point_age_s": (
            round((_now() - newest.started_at).total_seconds()) if newest else None
        ),
    }


def serialize(run: BackupRun) -> dict[str, Any]:
    return {
        "run_number": run.run_number,
        "kind": run.kind,
        "ok": run.ok,
        "location": run.location,
        "details": run.details,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat(),
    }
