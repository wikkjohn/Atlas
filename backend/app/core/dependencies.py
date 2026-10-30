"""Typed FastAPI dependencies shared by every router.

Routers depend on these aliases rather than constructing services themselves, so tests
(and later, extracted services) can substitute implementations via `dependency_overrides`.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.database import get_db, get_engine

SettingsDep = Annotated[Settings, Depends(get_settings)]
EngineDep = Annotated[Engine, Depends(get_engine)]
# scope="function": the request's transaction commits (or rolls back) before the response
# is sent. With FastAPI's default ("request") scope the commit ran after the client already
# had its response — a client refetching at once could read the state from before its own
# write, and a commit that failed was still reported as a success.
DbSession = Annotated[Session, Depends(get_db, scope="function")]
