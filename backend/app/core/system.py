"""Platform-level persistence and inspection: system properties and migration state."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import DateTime, Engine, String, Text, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.database import Base

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class SystemProperty(Base):
    """Key/value facts about this platform installation (e.g. when it was initialised)."""

    __tablename__ = "system_properties"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


def alembic_config(database_url: str | None = None) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    if database_url:
        # ConfigParser interpolation treats "%" specially.
        config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


@dataclass(frozen=True)
class MigrationState:
    current_revisions: list[str]
    head_revisions: list[str]

    @property
    def up_to_date(self) -> bool:
        return bool(self.head_revisions) and set(self.current_revisions) == set(self.head_revisions)


def migration_state(engine: Engine) -> MigrationState:
    heads = ScriptDirectory.from_config(alembic_config()).get_heads()
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_heads()
    return MigrationState(current_revisions=sorted(current), head_revisions=sorted(heads))


@dataclass(frozen=True)
class DatabaseDetails:
    server_version: str
    database_name: str
    table_count: int
    properties: dict[str, str]


def database_details(engine: Engine) -> DatabaseDetails:
    with Session(engine) as session:
        server_version = session.execute(text("SHOW server_version")).scalar_one()
        database_name = session.execute(text("SELECT current_database()")).scalar_one()
        table_count = session.execute(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
            )
        ).scalar_one()
        try:
            rows = session.execute(select(SystemProperty.key, SystemProperty.value)).all()
            properties = {key: value for key, value in rows}
        except SQLAlchemyError:
            # Table absent because migrations have not been applied yet.
            properties = {}
    return DatabaseDetails(
        server_version=server_version,
        database_name=database_name,
        table_count=int(table_count),
        properties=properties,
    )
