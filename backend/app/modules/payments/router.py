import uuid

from fastapi import APIRouter

from app.core.dependencies import DbSession
from app.core.pagination import Page, PageParamsDep
from app.core.permissions import Permission
from app.modules.identity.dependencies import Authorized
from app.modules.payments import service
from app.modules.payments.models import PaymentStatus
from app.modules.payments.schemas import PaymentOut

router = APIRouter(prefix="/payments", tags=["payments"])


@router.get("", response_model=Page[PaymentOut], summary="List payments")
def list_payments(
    db: DbSession,
    page: PageParamsDep,
    _: Authorized(Permission.PAYMENTS_READ),
    status: PaymentStatus | None = None,
    account_id: uuid.UUID | None = None,
    q: str | None = None,
) -> Page[PaymentOut]:
    items, total = service.list_payments(db, page, status=status, account_id=account_id, q=q)
    return Page(
        items=service.payments_out(db, items), total=total, limit=page.limit, offset=page.offset
    )


@router.get("/{payment_id}", response_model=PaymentOut, summary="Get a payment")
def get_payment(
    payment_id: uuid.UUID, db: DbSession, _: Authorized(Permission.PAYMENTS_READ)
) -> PaymentOut:
    return service.payments_out(db, [service.get_payment(db, payment_id)])[0]
