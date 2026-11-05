"""Phase 87: backups, verification, restore and the recovery drill, on real PostgreSQL.

The backup is taken of the test database itself (what other tests committed is in it) and
restored into a scratch database. Two audit archives with real files are committed for the
duration of the module, so the archive chain is carried and checked too.
"""

import hashlib
import json
import os
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import locks
from app.core.permissions import RoleCode
from app.modules.backup import service as backup
from tests.conftest import TEST_DATABASE_URL
from tests.factories import auth, make_user

SOURCE = make_url(TEST_DATABASE_URL)
SCRATCH = f"atlas_backup_test_{os.getpid()}"


def _database_exists(name: str) -> bool:
    engine = create_engine(SOURCE.set(database="postgres"))
    try:
        with engine.connect() as conn:
            return bool(
                conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name})
                .scalar_one_or_none()
            )  # fmt: skip
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def archives(tmp_path_factory):
    """Two chained audit archives, files and rows, committed (and removed afterwards)."""
    root = tmp_path_factory.mktemp("live")
    audit_dir, sim_dir = root / "audit-archive", root / "simulation-archive"
    audit_dir.mkdir()
    (sim_dir / "run-1").mkdir(parents=True)
    (sim_dir / "run-1" / "workflow_events.copy.gz").write_bytes(b"simulated history")
    engine = create_engine(SOURCE)
    ids, previous = [], None
    with engine.begin() as conn:
        for n in range(2):
            name = f"backup-test-{uuid.uuid4().hex[:8]}.jsonl.gz"
            (audit_dir / name).write_bytes(f"archive {n}".encode())
            sha = hashlib.sha256(f"archive {n}".encode()).hexdigest()
            ids.append(
                conn.execute(
                    text(
                        "INSERT INTO audit_archives (id, before, events, location, bytes,"
                        " sha256, previous_sha256) VALUES (:id, now(), 1, :loc, 9, :sha, :prev)"
                        " RETURNING id"
                    ),
                    {"id": uuid.uuid4(), "loc": name, "sha": sha, "prev": previous},
                ).scalar_one()
            )
            previous = sha
    yield {"audit": audit_dir, "simulation": sim_dir}
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM audit_archives WHERE id = ANY(:ids)"), {"ids": ids})
    engine.dispose()


@pytest.fixture(scope="module")
def settings(archives):
    return get_settings().model_copy(
        update={
            "database_url": TEST_DATABASE_URL,
            "audit_archive_dir": archives["audit"],
            "simulation_archive_dir": archives["simulation"],
        }
    )


@pytest.fixture(scope="module")
def taken(settings, tmp_path_factory) -> Path:
    return backup.create(tmp_path_factory.mktemp("backups"), settings)


@pytest.fixture(scope="module")
def restored(taken, tmp_path_factory):
    backup._recreate_database(SOURCE, SCRATCH)
    files_root = tmp_path_factory.mktemp("restored-files")
    result = backup.restore(taken, SOURCE.set(database=SCRATCH), files_root=files_root)
    yield result, files_root
    backup.drop_database(SOURCE, SCRATCH)


def test_a_backup_records_what_it_must_restore_to(taken: Path) -> None:
    manifest = backup.read_manifest(taken)
    assert {p.name for p in taken.iterdir()} == {"manifest.json", "database.dump", "files.tar.gz"}
    assert manifest["alembic_revision"] == ["0058_backup_runs"]
    assert set(manifest["row_counts"]) == set(backup.KEY_TABLES)
    assert manifest["row_counts"]["audit_archives"] >= 2
    assert manifest["ledger"]["debits"] == manifest["ledger"]["credits"]
    assert manifest["audit_archive_head"] is not None
    assert manifest["archive_files"] == {"audit-archive": 2, "simulation-archive": 1}
    for name, entry in manifest["files"].items():
        assert entry["sha256"] == hashlib.sha256((taken / name).read_bytes()).hexdigest()
    assert backup.verify(taken)["ok"]


def test_a_restore_reproduces_the_database_and_the_files(restored) -> None:
    result, files_root = restored
    assert result["ok"], result["checks"]
    names = [c["name"] for c in result["checks"]]
    assert names == [
        "Schema revision", "Row counts", "Ledger balances", "Newest audit event",
        "Audit archive chain",
    ]  # fmt: skip
    assert result["files_restored"] == {"audit-archive": 2, "simulation-archive": 1}
    restored_history = files_root / "simulation-archive" / "run-1" / "workflow_events.copy.gz"
    assert restored_history.read_bytes() == b"simulated history"
    assert set(result["timings"]) == {"verify_s", "database_s", "files_s", "checks_s", "total_s"}


def test_a_restore_refuses_a_database_that_is_not_empty(taken, restored) -> None:
    with pytest.raises(backup.BackupError, match="has .* tables"):
        backup.restore(taken, SOURCE.set(database=SCRATCH))


def test_the_checks_catch_a_restore_that_differs(taken, restored) -> None:
    result, files_root = restored
    manifest = backup.read_manifest(taken)
    wrong = json.loads(json.dumps(manifest))
    wrong["row_counts"]["customers"] += 1
    wrong["ledger"]["debits"] += 1
    # A file in the restored archive is replaced: its digest no longer matches the chain.
    first = sorted((files_root / "audit-archive").iterdir())[0]
    original = first.read_bytes()
    first.write_bytes(b"tampered")
    try:
        checks = {c["name"]: c for c in backup.checks(SOURCE.set(database=SCRATCH), wrong,
                                                         files_root)}  # fmt: skip
    finally:
        first.write_bytes(original)
    assert not checks["Row counts"]["passed"]
    assert "customers" in checks["Row counts"]["detail"]
    assert not checks["Ledger balances"]["passed"]
    assert not checks["Audit archive chain"]["passed"]
    assert "digest differs" in checks["Audit archive chain"]["detail"]
    assert checks["Schema revision"]["passed"]


def test_a_damaged_backup_fails_verification_and_is_not_restored(taken, tmp_path) -> None:
    damaged = tmp_path / "damaged"
    shutil.copytree(taken, damaged)
    with (damaged / "database.dump").open("r+b") as dump:
        dump.seek(200)
        byte = dump.read(1)
        dump.seek(200)
        dump.write(bytes([byte[0] ^ 0xFF]))
    result = backup.verify(damaged)
    assert not result["ok"]
    assert "database.dump's digest does not match the manifest" in result["problems"]
    with pytest.raises(backup.BackupError, match="failed verification"):
        backup.restore(damaged, SOURCE.set(database="atlas_never_created"))
    (damaged / "manifest.json").unlink()
    assert not backup.verify(damaged)["ok"]


def test_the_drill_restores_checks_times_and_cleans_up(settings, tmp_path) -> None:
    name = f"atlas_drill_test_{os.getpid()}"
    result = backup.drill(tmp_path, settings, scratch_database=name)
    assert result["ok"], result["checks"]
    assert set(result["measured"]) == {"backup_s", "rto_s", "rpo_s", "total_s"}
    assert 0 < result["measured"]["rto_s"] <= result["measured"]["total_s"]
    assert result["measured"]["rpo_s"] > 0
    assert not _database_exists(name)
    assert not list(tmp_path.glob("*-drill-files"))
    with pytest.raises(backup.BackupError, match="must not be the database"):
        backup.drill(tmp_path, settings, scratch_database=SOURCE.database)
    with pytest.raises(backup.BackupError, match="not a plain database name"):
        backup.drill(tmp_path, settings, scratch_database='x"; DROP DATABASE atlas; --')


def test_runs_are_recorded_and_listed(client: TestClient, db: Session) -> None:
    started = datetime.now(UTC)
    backup.record(db, "backup", ok=True, location="/backups/one", details={}, started_at=started)
    backup.record(
        db, "drill", ok=True, location="/backups/two", started_at=started,
        details={"measured": {"rto_s": 2.2, "rpo_s": 9.1}},
    )  # fmt: skip
    backup.record(db, "drill", ok=False, location="/backups/three", details={},
                  started_at=started)  # fmt: skip
    db.commit()
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    body = client.get("/api/v1/backups", headers=auth(admin)).json()
    assert body["latest_backup"]["location"] == "/backups/one"
    # The latest drill that passed, not the latest drill.
    assert body["latest_drill"]["details"]["measured"]["rto_s"] == 2.2
    assert body["recovery_point_age_s"] is not None
    assert [r["location"] for r in body["runs"][:3]] == [
        "/backups/three", "/backups/two", "/backups/one",
    ]  # fmt: skip
    only = client.get("/api/v1/backups?kind=drill", headers=auth(admin)).json()["runs"]
    assert {r["kind"] for r in only} == {"drill"}
    employee = make_user(db, RoleCode.BANKING_EMPLOYEE)
    refused = client.get("/api/v1/backups", headers=auth(employee))
    assert refused.status_code == 403


# --- Fixes from the PR #78 review (Phase 88) ---------------------------------------------


def _can_lock_exclusively() -> bool:
    engine = create_engine(SOURCE)
    try:
        with engine.begin() as conn:
            return bool(
                conn.execute(
                    text("SELECT pg_try_advisory_xact_lock(hashtext(:n))"),
                    {"n": locks.ARCHIVE_FILES},
                ).scalar_one()
            )
    finally:
        engine.dispose()


def test_a_backup_snapshot_keeps_archive_files_from_being_deleted() -> None:
    assert _can_lock_exclusively()
    with backup._snapshot(SOURCE):
        # restore_run takes this lock exclusively before deleting a restored archive.
        assert not _can_lock_exclusively()
    assert _can_lock_exclusively()


def test_a_bad_files_destination_is_refused_before_the_database_is_touched(taken, tmp_path) -> None:
    name = f"atlas_backup_pre_{os.getpid()}"
    backup._recreate_database(SOURCE, name)
    try:
        occupied = tmp_path / "occupied"
        occupied.mkdir()
        (occupied / "something").write_text("x")
        with pytest.raises(backup.BackupError, match="is not empty"):
            backup.restore(taken, SOURCE.set(database=name), files_root=occupied)
        # Nothing was restored, so a retry with a good destination works.
        assert backup._public_tables(SOURCE.set(database=name)) == 0
        result = backup.restore(taken, SOURCE.set(database=name), files_root=tmp_path / "ok")
        assert result["ok"]
    finally:
        backup.drop_database(SOURCE, name)
