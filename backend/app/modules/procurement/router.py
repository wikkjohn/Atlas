"""Procurement and vendor management API (Phase 57)."""

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.dependencies import DbSession
from app.core.pagination import Page, PageParamsDep, paginate
from app.core.permissions import Permission
from app.modules.countries.models import Country
from app.modules.identity.dependencies import Authorized
from app.modules.organizations.models import Organization
from app.modules.procurement import service
from app.modules.procurement.models import PurchaseOrder, Vendor, VendorInvoice

router = APIRouter(prefix="/procurement", tags=["procurement"])
READ, MANAGE = Permission.PROCUREMENT_READ, Permission.PROCUREMENT_MANAGE
APPROVE, LARGE = Permission.PROCUREMENT_APPROVE, Permission.PROCUREMENT_APPROVE_LARGE


class VendorIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    country: str = Field(pattern=r"^[A-Za-z]{2}$")
    category: str = Field(max_length=30)
    bank_account: str = Field(min_length=8, max_length=40)


class BankChangeIn(BaseModel):
    bank_account: str = Field(min_length=8, max_length=40)


class VendorOut(BaseModel):
    id: uuid.UUID
    vendor_number: str
    name: str
    country: str
    currency: str
    category: str
    bank_account: str
    pending_bank_account: str | None
    risk_tier: str
    sanctions_hit: bool
    status: str
    created_at: datetime


class LineIn(BaseModel):
    description: str = Field(min_length=1, max_length=150)
    quantity: int = Field(ge=1, le=100_000)
    unit_price: int = Field(gt=0, description="Minor units of the vendor's currency")


class OrderIn(BaseModel):
    vendor_number: str = Field(min_length=1, max_length=20)
    department_id: uuid.UUID
    description: str = Field(min_length=3, max_length=300)
    lines: list[LineIn] = Field(min_length=1, max_length=50)


class ReceiveIn(BaseModel):
    amount: int = Field(gt=0)


class OrderOut(BaseModel):
    id: uuid.UUID
    order_number: str
    vendor_number: str
    vendor_name: str
    department: str
    description: str
    lines: list
    total: int
    total_usd: int
    currency: str
    received_amount: int
    invoiced: int
    status: str
    created_at: datetime


class InvoiceIn(BaseModel):
    order_number: str = Field(min_length=1, max_length=20)
    vendor_reference: str = Field(min_length=1, max_length=40)
    amount: int = Field(gt=0)
    invoice_date: date


class InvoiceOut(BaseModel):
    id: uuid.UUID
    invoice_number: str
    vendor_reference: str
    order_number: str
    vendor_name: str
    amount: int
    currency: str
    invoice_date: date
    status: str
    hold_reason: str | None
    paid_to: str | None
    entry_number: str | None
    created_at: datetime


def _vendor_out(db, v: Vendor) -> VendorOut:
    return VendorOut(
        id=v.id, vendor_number=v.vendor_number, name=v.name,
        country=db.get(Country, v.country_id).iso_country_code, currency=v.currency,
        category=v.category, bank_account=v.bank_account,
        pending_bank_account=v.pending_bank_account, risk_tier=v.risk_tier,
        sanctions_hit=bool(v.screening.get("hit")), status=v.status, created_at=v.created_at,
    )  # fmt: skip


def _order_out(db, o: PurchaseOrder) -> OrderOut:
    vendor = db.get(Vendor, o.vendor_id)
    return OrderOut(
        id=o.id, order_number=o.order_number, vendor_number=vendor.vendor_number,
        vendor_name=vendor.name, department=db.get(Organization, o.department_id).name,
        description=o.description, lines=o.lines, total=o.total,
        total_usd=service.total_usd(db, o), currency=o.currency,
        received_amount=o.received_amount, invoiced=service.invoiced(db, o), status=o.status,
        created_at=o.created_at,
    )  # fmt: skip


def _invoice_out(db, i: VendorInvoice) -> InvoiceOut:
    order = db.get(PurchaseOrder, i.order_id)
    return InvoiceOut(
        id=i.id, invoice_number=i.invoice_number, vendor_reference=i.vendor_reference,
        order_number=order.order_number, vendor_name=db.get(Vendor, order.vendor_id).name,
        amount=i.amount, currency=i.currency, invoice_date=i.invoice_date, status=i.status,
        hold_reason=i.hold_reason, paid_to=i.paid_to, entry_number=i.entry_number,
        created_at=i.created_at,
    )  # fmt: skip


def _page(db, query, page, out):
    items, total = paginate(db, query, page)
    return Page(items=[out(db, r) for r in items], total=total, limit=page.limit,
                offset=page.offset)  # fmt: skip


# --- Vendors -----------------------------------------------------------------------------------


@router.get("/vendors", response_model=Page[VendorOut], summary="Vendors, newest first")
def list_vendors(db: DbSession, page: PageParamsDep, _: Authorized(READ),
                 status_: str | None = Query(default=None, alias="status")):  # fmt: skip
    query = select(Vendor).order_by(Vendor.created_at.desc(), Vendor.vendor_number.desc())
    if status_:
        query = query.where(Vendor.status == status_)
    return _page(db, query, page, _vendor_out)


@router.post("/vendors", response_model=VendorOut, status_code=status.HTTP_201_CREATED,
             summary="Register a vendor (screened, tiered, approved by someone else)")  # fmt: skip
def register_vendor(body: VendorIn, db: DbSession, user: Authorized(MANAGE)):
    vendor = service.register_vendor(db, name=body.name, country_code=body.country,
                                     category=body.category, bank_account=body.bank_account,
                                     registered_by=user.id)  # fmt: skip
    return _vendor_out(db, vendor)


@router.post("/vendors/{vendor_id}/approve", response_model=VendorOut)
def approve_vendor(vendor_id: uuid.UUID, db: DbSession, user: Authorized(APPROVE)):
    vendor = service.get_vendor(db, vendor_id)
    return _vendor_out(db, service.decide_vendor(db, vendor, user.id, True, user.can(LARGE)))


@router.post("/vendors/{vendor_id}/reject", response_model=VendorOut)
def reject_vendor(vendor_id: uuid.UUID, db: DbSession, user: Authorized(APPROVE)):
    vendor = service.get_vendor(db, vendor_id)
    return _vendor_out(db, service.decide_vendor(db, vendor, user.id, False))


@router.post("/vendors/{vendor_id}/bank-change", response_model=VendorOut,
             summary="Ask to change the vendor's bank account")  # fmt: skip
def request_bank_change(vendor_id: uuid.UUID, body: BankChangeIn, db: DbSession,
                        user: Authorized(MANAGE)):  # fmt: skip
    vendor = service.get_vendor(db, vendor_id)
    return _vendor_out(db, service.request_bank_change(db, vendor, body.bank_account, user.id))


@router.post("/vendors/{vendor_id}/bank-change/verify", response_model=VendorOut)
def verify_bank_change(vendor_id: uuid.UUID, db: DbSession, user: Authorized(APPROVE)):
    vendor = service.get_vendor(db, vendor_id)
    return _vendor_out(db, service.verify_bank_change(db, vendor, user.id, True))


@router.post("/vendors/{vendor_id}/bank-change/refuse", response_model=VendorOut)
def refuse_bank_change(vendor_id: uuid.UUID, db: DbSession, user: Authorized(APPROVE)):
    vendor = service.get_vendor(db, vendor_id)
    return _vendor_out(db, service.verify_bank_change(db, vendor, user.id, False))


# --- Purchase orders ---------------------------------------------------------------------------


@router.get("/orders", response_model=Page[OrderOut], summary="Purchase orders, newest first")
def list_orders(db: DbSession, page: PageParamsDep, _: Authorized(READ),
                status_: str | None = Query(default=None, alias="status")):  # fmt: skip
    query = select(PurchaseOrder).order_by(PurchaseOrder.created_at.desc(),
                                           PurchaseOrder.order_number.desc())  # fmt: skip
    if status_:
        query = query.where(PurchaseOrder.status == status_)
    return _page(db, query, page, _order_out)


@router.post("/orders", response_model=OrderOut, status_code=status.HTTP_201_CREATED,
             summary="Raise a purchase order (approved by someone else)")  # fmt: skip
def raise_order(body: OrderIn, db: DbSession, user: Authorized(MANAGE)):
    vendor = service.find_vendor(db, body.vendor_number)
    order = service.raise_order(db, vendor, body.department_id, body.description,
                                [line.model_dump() for line in body.lines], user.id)  # fmt: skip
    return _order_out(db, order)


@router.post("/orders/{order_id}/approve", response_model=OrderOut)
def approve_order(order_id: uuid.UUID, db: DbSession, user: Authorized(APPROVE)):
    order = service.get_order(db, order_id)
    return _order_out(db, service.decide_order(db, order, user.id, True, user.can(LARGE)))


@router.post("/orders/{order_id}/reject", response_model=OrderOut)
def reject_order(order_id: uuid.UUID, db: DbSession, user: Authorized(APPROVE)):
    order = service.get_order(db, order_id)
    return _order_out(db, service.decide_order(db, order, user.id, False))


@router.post("/orders/{order_id}/receive", response_model=OrderOut,
             summary="Record what was delivered")  # fmt: skip
def receive(order_id: uuid.UUID, body: ReceiveIn, db: DbSession, user: Authorized(MANAGE)):
    order = service.get_order(db, order_id)
    return _order_out(db, service.receive(db, order, body.amount, user.id))


# --- Invoices ----------------------------------------------------------------------------------


@router.get("/invoices", response_model=Page[InvoiceOut], summary="Invoices, newest first")
def list_invoices(db: DbSession, page: PageParamsDep, _: Authorized(READ),
                  status_: str | None = Query(default=None, alias="status")):  # fmt: skip
    query = select(VendorInvoice).order_by(VendorInvoice.created_at.desc(),
                                           VendorInvoice.invoice_number.desc())  # fmt: skip
    if status_:
        query = query.where(VendorInvoice.status == status_)
    return _page(db, query, page, _invoice_out)


@router.post("/invoices", response_model=InvoiceOut, status_code=status.HTTP_201_CREATED,
             summary="Record a vendor invoice (matched to the order and receipt)")  # fmt: skip
def record_invoice(body: InvoiceIn, db: DbSession, user: Authorized(MANAGE)):
    order = service.find_order(db, body.order_number)
    invoice = service.record_invoice(db, order, body.vendor_reference, body.amount,
                                     body.invoice_date, user.id)  # fmt: skip
    return _invoice_out(db, invoice)


@router.post("/invoices/{invoice_id}/pay", response_model=InvoiceOut)
def pay_invoice(invoice_id: uuid.UUID, db: DbSession, user: Authorized(APPROVE)):
    return _invoice_out(db, service.pay_invoice(db, service.get_invoice(db, invoice_id),
                                                user.id))  # fmt: skip


@router.post("/invoices/{invoice_id}/reject", response_model=InvoiceOut)
def reject_invoice(invoice_id: uuid.UUID, db: DbSession, user: Authorized(APPROVE)):
    return _invoice_out(db, service.reject_invoice(db, service.get_invoice(db, invoice_id),
                                                   user.id))  # fmt: skip


@router.get("/departments", summary="Active departments an order can be charged to")
def departments(db: DbSession, _: Authorized(READ)) -> list[dict]:
    from app.modules.hr import service as hr

    return hr.departments(db)


@router.get("/summary/counts", summary="Counts for the procurement page")
def summary(db: DbSession, _: Authorized(READ)) -> dict:
    return service.summary(db)
