"""Database engine, session management and health inspection.

All modules share this engine and the `Base` declarative class. Request handlers obtain a
session through `get_db`, which wraps the request in one explicit transaction.
"""

import time
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import Engine, MetaData, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

# Deterministic constraint names keep Alembic autogenerate diffs stable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def build_engine(database_url: str) -> Engine:
    settings = get_settings()
    return create_engine(
        database_url,
        pool_size=settings.database_pool_size,
        pool_pre_ping=True,
        connect_args={"connect_timeout": settings.database_connect_timeout_seconds},
    )


@lru_cache
def get_engine() -> Engine:
    return build_engine(get_settings().database_url)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session and one transaction per request."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@dataclass(frozen=True)
class DatabaseHealth:
    ok: bool
    latency_ms: float | None
    error: str | None = None


def check_database(engine: Engine) -> DatabaseHealth:
    started = time.perf_counter()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        # Report the driver's first line only; full detail goes to the log.
        message = str(exc.orig if getattr(exc, "orig", None) else exc).strip().splitlines()[0]
        return DatabaseHealth(ok=False, latency_ms=None, error=message)
    return DatabaseHealth(ok=True, latency_ms=round((time.perf_counter() - started) * 1000, 2))
