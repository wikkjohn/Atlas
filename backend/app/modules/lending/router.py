import uuid

from fastapi import APIRouter

from app.core.dependencies import DbSession
from app.core.pagination import Page, PageParamsDep
from app.core.permissions import Permission
from app.modules.identity.dependencies import Authorized
from app.modules.lending import service
from app.modules.lending.models import LoanStatus
from app.modules.lending.schemas import LoanOut

router = APIRouter(prefix="/loans", tags=["lending"])


@router.get("", response_model=Page[LoanOut], summary="List loans")
def list_loans(
    db: DbSession,
    page: PageParamsDep,
    _: Authorized(Permission.LOANS_READ),
    customer_id: uuid.UUID | None = None,
    status: LoanStatus | None = None,
    q: str | None = None,
) -> Page[LoanOut]:
    items, total = service.list_loans(db, page, customer_id=customer_id, status=status, q=q)
    return Page(
        items=service.loans_out(db, items), total=total, limit=page.limit, offset=page.offset
    )


@router.get("/{loan_id}", response_model=LoanOut, summary="Get a loan")
def get_loan(loan_id: uuid.UUID, db: DbSession, _: Authorized(Permission.LOANS_READ)) -> LoanOut:
    return service.loans_out(db, [service.get_loan(db, loan_id)])[0]
