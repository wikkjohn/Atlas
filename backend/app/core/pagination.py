"""Offset pagination shared by every list endpoint."""

from typing import Annotated

from fastapi import Depends, Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

MAX_PAGE_SIZE = 200


class PageParams(BaseModel):
    limit: int
    offset: int


def page_params(
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE, description="Page size")] = 50,
    offset: Annotated[int, Query(ge=0, description="Items to skip")] = 0,
) -> PageParams:
    return PageParams(limit=limit, offset=offset)


PageParamsDep = Annotated[PageParams, Depends(page_params)]


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


def paginate[M](db: Session, query: Select[tuple[M]], params: PageParams) -> tuple[list[M], int]:
    """Run `query` for one page and count the full result set."""
    total = db.execute(
        select(func.count()).select_from(query.order_by(None).subquery())
    ).scalar_one()
    rows = db.execute(query.limit(params.limit).offset(params.offset)).scalars().all()
    return list(rows), int(total)
