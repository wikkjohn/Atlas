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

from alembic import command  # noqa: E402
from app.core.database import build_engine  # noqa: E402
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
def app() -> FastAPI:
    return create_app()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def unreachable_engine():
    engine = build_engine(UNREACHABLE_DATABASE_URL)
    yield engine
    engine.dispose()
