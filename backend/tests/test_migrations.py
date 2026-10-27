from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect

from app.core.database import Base, build_engine
from tests.conftest import TEST_DATABASE_URL, migrate


def test_migrations_downgrade_and_upgrade_cleanly() -> None:
    engine = build_engine(TEST_DATABASE_URL)
    try:
        migrate("base")
        assert "system_properties" not in inspect(engine).get_table_names()

        migrate("head")
        assert "system_properties" in inspect(engine).get_table_names()
    finally:
        migrate("head")
        engine.dispose()


def test_models_match_migrations() -> None:
    engine = build_engine(TEST_DATABASE_URL)
    try:
        with engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    finally:
        engine.dispose()

    assert diff == [], f"Models and migrations differ; create a migration: {diff}"
