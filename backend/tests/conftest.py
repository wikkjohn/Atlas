"""Shared pytest fixtures.

Tests run against a real PostgreSQL database (never SQLite) so that behaviour matches
production. Point ATLAS_TEST_DATABASE_URL at a dedicated, disposable database; the
suite drops and recreates its schema.
"""

import os

TEST_DATABASE_URL = os.environ.get(
    "ATLAS_TEST_DATABASE_URL", "postgresql+psycopg://atlas:atlas@localhost:5432/atlas_test"
)
# Must be set before the application is imported (settings are cached on first use).
os.environ["ATLAS_DATABASE_URL"] = TEST_DATABASE_URL
os.environ["ATLAS_ENVIRONMENT"] = "test"
os.environ["ATLAS_LOG_FORMAT"] = "text"
os.environ["ATLAS_CORS_ORIGINS"] = "http://localhost:5173"
os.environ.setdefault("ATLAS_REDIS_URL", "")

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Connection  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from alembic import command  # noqa: E402
from app.core.database import build_engine, get_db, get_engine  # noqa: E402
from app.core.system import alembic_config  # noqa: E402
from app.main import create_app  # noqa: E402

UNREACHABLE_DATABASE_URL = "postgresql+psycopg://atlas:atlas@127.0.0.1:1/atlas"


def migrate(target: str) -> None:
    config = alembic_config(TEST_DATABASE_URL)
    config.attributes["configure_logging"] = False
    if target == "base":
        command.downgrade(config, "base")
    else:
        command.upgrade(config, target)


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    migrate("base")
    migrate("head")
    yield


@pytest.fixture
def db_connection() -> Iterator[Connection]:
    """A connection holding an outer transaction that is rolled back after each test."""
    connection = get_engine().connect()
    transaction = connection.begin()
    yield connection
    transaction.rollback()
    connection.close()


def _session(connection: Connection) -> Session:
    # Commits inside the code under test release savepoints instead of committing.
    return Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        autoflush=False,
        expire_on_commit=False,
    )


@pytest.fixture
def db(db_connection: Connection) -> Iterator[Session]:
    """Session for arranging and asserting test data; sees everything the API writes."""
    session = _session(db_connection)
    yield session
    session.close()


@pytest.fixture
def app(db_connection: Connection) -> FastAPI:
    application = create_app()

    def _get_db() -> Iterator[Session]:
        session = _session(db_connection)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    application.dependency_overrides[get_db] = _get_db
    return application


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def unreachable_engine():
    engine = build_engine(UNREACHABLE_DATABASE_URL)
    yield engine
    engine.dispose()
