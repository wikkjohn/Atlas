"""Named PostgreSQL advisory locks shared by more than one module.

`ARCHIVE_FILES` guards the archive directories against a backup (Phase 87): a backup holds
it shared from before its snapshot until the files are packed; deleting archive files that
committed data no longer needs (a restored run's archive) takes it exclusively first. A
backup therefore always holds every file its snapshot still refers to.
"""

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

ARCHIVE_FILES = "atlas.archive_files"


def hold_shared(conn: Connection | Session, name: str) -> None:
    """Until the end of the current transaction (works in a read-only one)."""
    conn.execute(text("SELECT pg_advisory_xact_lock_shared(hashtext(:n))"), {"n": name})


def hold_exclusive(conn: Connection | Session, name: str) -> None:
    """Until the end of the current transaction; waits for every shared holder."""
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:n))"), {"n": name})
