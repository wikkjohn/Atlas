"""Idempotent create operations.

A client may send an `Idempotency-Key` header with a state-changing request. The first
request with a key runs normally and its response is stored; a retry with the same key and
the same body replays the stored response instead of creating a duplicate. Reusing a key
with a different body is rejected.

Concurrency: the key row is inserted in the request's own transaction before the work runs.
A concurrent duplicate blocks on the primary key until the first transaction finishes, then
either replays its stored response (committed) or proceeds (rolled back).
"""

import hashlib
import json
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any

from fastapi import Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import DateTime, ForeignKey, Integer, String, Uuid, func, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.database import Base
from app.core.errors import ConflictError

IDEMPOTENCY_HEADER = "Idempotency-Key"
REPLAY_HEADER = "Idempotent-Replayed"

IdempotencyKey = Annotated[
    str | None,
    Header(
        alias=IDEMPOTENCY_HEADER,
        min_length=1,
        max_length=255,
        description="Optional client-generated key that makes this request safe to retry.",
    ),
]


RequiredIdempotencyKey = Annotated[
    str,
    Header(
        alias=IDEMPOTENCY_HEADER,
        min_length=1,
        max_length=255,
        description="Required for money movements: retries with the same key never post twice.",
    ),
]


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_keys"

    actor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[Any] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


def _fingerprint(method: str, path: str, payload: BaseModel) -> str:
    canonical = json.dumps(
        {"method": method, "path": path, "body": payload.model_dump(mode="json")},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def run_idempotent(
    db: Session,
    *,
    key: str | None,
    actor_id: uuid.UUID,
    method: str,
    path: str,
    payload: BaseModel,
    status_code: int,
    operation: Callable[[], BaseModel],
) -> JSONResponse:
    if key is None:
        return JSONResponse(status_code=status_code, content=operation().model_dump(mode="json"))

    request_hash = _fingerprint(method, path, payload)
    claimed = db.execute(
        insert(IdempotencyRecord)
        .values(actor_id=actor_id, key=key, method=method, path=path, request_hash=request_hash)
        .on_conflict_do_nothing()
        .returning(IdempotencyRecord.key)
    ).scalar_one_or_none()

    if claimed is None:
        existing = db.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.actor_id == actor_id, IdempotencyRecord.key == key
            )
        ).scalar_one()
        if existing.request_hash != request_hash:
            raise ConflictError(
                "This Idempotency-Key was already used for a different request.",
                {"idempotency_key": key},
            )
        if existing.status_code is None:
            raise ConflictError("A request with this Idempotency-Key is still in progress.")
        return JSONResponse(
            status_code=existing.status_code,
            content=existing.response_body,
            headers={REPLAY_HEADER: "true"},
        )

    body = operation().model_dump(mode="json")
    record = db.get(IdempotencyRecord, (actor_id, key))
    assert record is not None
    record.status_code = status_code
    record.response_body = body
    db.flush()
    return JSONResponse(status_code=status_code, content=body)
