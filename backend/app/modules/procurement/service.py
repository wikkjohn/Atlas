"""Procurement and vendor management (Phase 57): vendors, bank-detail changes, purchase
orders, receipts and invoices paid on a three-way match."""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.modules.compliance.screening import SANCTIONS_LISTS, screen_name
from app.modules.countries.models import Country, OperationalStatus
from app.modules.ledger import service as ledger
from app.modules.ledger.models import Direction, LedgerAccount, LedgerAccountType
from app.modules.organizations.models import Organization, OrganizationType
from app.modules.procurement.models import (
    INVOICE_SEQUENCE,
    ORDER_SEQUENCE,
    VENDOR_SEQUENCE,
    InvoiceStatus,
    OrderStatus,
    PurchaseOrder,
    Vendor,
    VendorInvoice,
    VendorStatus,
)

CATEGORIES = {"facilities": "low", "marketing": "low", "it": "medium",
              "professional_services": "medium", "outsourcing": "high"}  # fmt: skip
TIERS = ("low", "medium", "high")
LARGE_ORDER_USD = 50_000  # above this an executive approves the order
MATCH_TOLERANCE_PCT = 2  # invoiced may exceed what was received by this much


def _now() -> datetime:
    return datetime.now(UTC)


def _audit(db, actor_id, action: str, entity_type: str, entity_id, **metadata) -> None:
    record_audit_event(db, actor_id=actor_id, action=action, entity_type=entity_type,
                       entity_id=entity_id, metadata=metadata)  # fmt: skip


def _four_eyes(by: uuid.UUID | None, actor_id: uuid.UUID, who: str) -> None:
    if by == actor_id:
        raise BusinessRuleViolation(f"Four-eyes rule: the person who {who} it cannot decide it.",
                                    {"rule": "four_eyes"})  # fmt: skip


def _usd(db: Session, amount: int, currency: str) -> int:
    from app.modules.risk import service as risk

    return risk._usd(db, amount, currency, _now().date())


# --- Vendors -----------------------------------------------------------------------------------


def find_vendor(db: Session, number: str) -> Vendor:
    vendor = db.execute(
        select(Vendor).where(Vendor.vendor_number == number.strip().upper())
    ).scalar_one_or_none()  # fmt: skip
    if vendor is None:
        raise NotFoundError(f"No vendor {number}.")
    return vendor


def get_vendor(db: Session, vendor_id: uuid.UUID) -> Vendor:
    vendor = db.get(Vendor, vendor_id)
    if vendor is None:
        raise NotFoundError("No such vendor.")
    return vendor


def register_vendor(db: Session, *, name: str, country_code: str, category: str,
                    bank_account: str, registered_by: uuid.UUID) -> Vendor:  # fmt: skip
    """Register a vendor: screened against every sanctions list and tiered by risk (its
    category, one tier higher outside the bank's active countries). It waits for approval
    by someone other than the registrant."""
    if category not in CATEGORIES:
        raise BusinessRuleViolation(f"Category is one of {', '.join(sorted(CATEGORIES))}.",
                                    {"rule": "category_invalid"})  # fmt: skip
    if len(name.strip()) < 2 or len(bank_account.strip()) < 8:
        raise BusinessRuleViolation("A vendor needs a name and a bank account.",
                                    {"rule": "details_missing"})  # fmt: skip
    country = db.execute(
        select(Country).where(Country.iso_country_code == country_code.strip().upper())
    ).scalar_one_or_none()  # fmt: skip
    if country is None:
        raise NotFoundError(f"No country {country_code}.")
    tier = TIERS.index(CATEGORIES[category])
    if country.operational_status != OperationalStatus.ACTIVE:
        tier = min(tier + 1, 2)
    screening = screen_name(name, list(SANCTIONS_LISTS))
    number = db.execute(VENDOR_SEQUENCE.next_value()).scalar_one()
    vendor = Vendor(
        vendor_number=f"VEN-{number:06d}", name=name.strip(), country_id=country.id,
        currency=country.default_currency, category=category,
        bank_account=bank_account.strip().upper(), risk_tier=TIERS[tier],
        screening=screening, status=VendorStatus.PENDING.value, registered_by=registered_by,
    )  # fmt: skip
    db.add(vendor)
    db.flush()
    _audit(db, registered_by, "procurement.vendor_registered", "vendor", vendor.id,
           vendor_number=vendor.vendor_number, risk_tier=vendor.risk_tier,
           sanctions_hit=screening["hit"])  # fmt: skip
    return vendor


def decide_vendor(db: Session, vendor: Vendor, actor_id: uuid.UUID, approve: bool,
                  executive: bool = False) -> Vendor:  # fmt: skip
    """Approve or reject a vendor. A sanctions hit is never approved; a high-risk vendor is
    approved by an executive (procurement:approve_large)."""
    if vendor.status != VendorStatus.PENDING:
        raise ConflictError(f"{vendor.vendor_number} is {vendor.status}.")
    _four_eyes(vendor.registered_by, actor_id, "registered")
    if approve and vendor.screening.get("hit"):
        raise BusinessRuleViolation(f"{vendor.name} matches the {vendor.screening['list']} "
                                    "sanctions list.", {"rule": "sanctions_hit"})  # fmt: skip
    if approve and vendor.risk_tier == "high" and not executive:
        raise BusinessRuleViolation("A high-risk vendor is approved by an executive.",
                                    {"rule": "needs_executive"})  # fmt: skip
    vendor.status = (VendorStatus.APPROVED if approve else VendorStatus.REJECTED).value
    vendor.approved_by = actor_id if approve else None
    db.flush()
    _audit(db, actor_id, f"procurement.vendor_{vendor.status}", "vendor", vendor.id,
           vendor_number=vendor.vendor_number)  # fmt: skip
    return vendor


def request_bank_change(db: Session, vendor: Vendor, account: str, actor_id: uuid.UUID
                        ) -> Vendor:  # fmt: skip
    """Ask to change where the vendor is paid; nothing is paid to it until a second person
    verifies the change (the classic invoice-fraud route)."""
    if vendor.pending_bank_account:
        raise ConflictError(f"{vendor.vendor_number} already has a change awaiting checks.")
    if len(account.strip()) < 8 or account.strip().upper() == vendor.bank_account:
        raise BusinessRuleViolation("Give a different bank account.",
                                    {"rule": "account_invalid"})  # fmt: skip
    vendor.pending_bank_account = account.strip().upper()
    vendor.bank_change_by, vendor.bank_change_verified_by = actor_id, None
    db.flush()
    _audit(db, actor_id, "procurement.bank_change_requested", "vendor", vendor.id,
           vendor_number=vendor.vendor_number)  # fmt: skip
    return vendor


def verify_bank_change(db: Session, vendor: Vendor, actor_id: uuid.UUID, accept: bool
                       ) -> Vendor:  # fmt: skip
    if not vendor.pending_bank_account:
        raise ConflictError(f"{vendor.vendor_number} has no change awaiting checks.")
    _four_eyes(vendor.bank_change_by, actor_id, "requested")
    if accept:
        vendor.bank_account = vendor.pending_bank_account
        vendor.bank_change_verified_by, vendor.bank_changed_at = actor_id, _now()
    vendor.pending_bank_account = None
    db.flush()
    _audit(db, actor_id, "procurement.bank_change_" + ("verified" if accept else "refused"),
           "vendor", vendor.id, vendor_number=vendor.vendor_number)  # fmt: skip
    return vendor


# --- Purchase orders ---------------------------------------------------------------------------


def find_order(db: Session, number: str) -> PurchaseOrder:
    order = db.execute(
        select(PurchaseOrder).where(PurchaseOrder.order_number == number.strip().upper())
    ).scalar_one_or_none()  # fmt: skip
    if order is None:
        raise NotFoundError(f"No purchase order {number}.")
    return order


def get_order(db: Session, order_id: uuid.UUID) -> PurchaseOrder:
    order = db.get(PurchaseOrder, order_id)
    if order is None:
        raise NotFoundError("No such purchase order.")
    return order


def raise_order(db: Session, vendor: Vendor, department_id: uuid.UUID, description: str,
                lines: list[dict[str, Any]], requested_by: uuid.UUID) -> PurchaseOrder:  # fmt: skip
    """Order from an approved vendor for a department: the lines' total, in the vendor's
    currency. It waits for approval by someone other than the requester."""
    if vendor.status != VendorStatus.APPROVED:
        raise BusinessRuleViolation(
            f"{vendor.vendor_number} is {vendor.status}; orders go to approved vendors.",
            {"rule": "vendor_not_approved"})  # fmt: skip
    dept = db.get(Organization, department_id)
    if dept is None or dept.organization_type != OrganizationType.DEPARTMENT:
        raise NotFoundError("No such department.")
    if not lines or any(int(line["quantity"]) <= 0 or int(line["unit_price"]) <= 0
                        for line in lines):  # fmt: skip
        raise BusinessRuleViolation("An order needs lines with a quantity and a price.",
                                    {"rule": "lines_invalid"})  # fmt: skip
    clean = [{"description": str(line["description"])[:150], "quantity": int(line["quantity"]),
              "unit_price": int(line["unit_price"])} for line in lines]  # fmt: skip
    number = db.execute(ORDER_SEQUENCE.next_value()).scalar_one()
    order = PurchaseOrder(
        order_number=f"PO-{number:07d}", vendor_id=vendor.id, department_id=dept.id,
        description=description.strip(), lines=clean,
        total=sum(line["quantity"] * line["unit_price"] for line in clean),
        currency=vendor.currency, received_amount=0, status=OrderStatus.REQUESTED.value,
        requested_by=requested_by,
    )  # fmt: skip
    db.add(order)
    db.flush()
    _audit(db, requested_by, "procurement.order_raised", "purchase_order", order.id,
           order_number=order.order_number, total=order.total)  # fmt: skip
    return order


def total_usd(db: Session, order: PurchaseOrder) -> int:
    """The order's total in whole US dollars, for display."""
    return _usd(db, order.total, order.currency)


def _over_large_threshold(db: Session, order: PurchaseOrder) -> bool:
    from app.modules.risk import service as risk

    return risk._usd_cents(db, order.total, order.currency, _now().date()) > LARGE_ORDER_USD * 100


def decide_order(db: Session, order: PurchaseOrder, actor_id: uuid.UUID, approve: bool,
                 executive: bool = False) -> PurchaseOrder:  # fmt: skip
    """Approve or reject an order; above US$50,000 only an executive approves it."""
    if order.status != OrderStatus.REQUESTED:
        raise ConflictError(f"{order.order_number} is {order.status}.")
    _four_eyes(order.requested_by, actor_id, "requested")
    if approve and _over_large_threshold(db, order) and not executive:
        raise BusinessRuleViolation(
            f"Orders above US${LARGE_ORDER_USD:,} are approved by an executive.",
            {"rule": "needs_executive"})  # fmt: skip
    order.status = (OrderStatus.APPROVED if approve else OrderStatus.REJECTED).value
    order.approved_by = actor_id if approve else None
    db.flush()
    _audit(db, actor_id, f"procurement.order_{order.status}", "purchase_order", order.id,
           order_number=order.order_number)  # fmt: skip
    return order


def receive(db: Session, order: PurchaseOrder, amount: int, actor_id: uuid.UUID,
            on: date | None = None) -> PurchaseOrder:  # fmt: skip
    """Record what was delivered, up to the order's total."""
    if order.status not in (OrderStatus.APPROVED, OrderStatus.RECEIVED):
        raise BusinessRuleViolation(f"{order.order_number} is {order.status}.",
                                    {"rule": "not_approved"})  # fmt: skip
    if amount <= 0 or order.received_amount + amount > order.total:
        raise BusinessRuleViolation("More was received than was ordered.",
                                    {"rule": "over_receipt"})  # fmt: skip
    order.received_amount += amount
    order.status, order.received_on = OrderStatus.RECEIVED.value, on or _now().date()
    db.flush()
    _audit(db, actor_id, "procurement.received", "purchase_order", order.id,
           order_number=order.order_number, amount=amount)  # fmt: skip
    return order


# --- Invoices ----------------------------------------------------------------------------------


def invoiced(db: Session, order: PurchaseOrder, exclude: uuid.UUID | None = None) -> int:
    query = select(func.coalesce(func.sum(VendorInvoice.amount), 0)).where(
        VendorInvoice.order_id == order.id,
        VendorInvoice.status.in_([InvoiceStatus.RECORDED, InvoiceStatus.PAID]))  # fmt: skip
    if exclude is not None:
        query = query.where(VendorInvoice.id != exclude)
    return int(db.execute(query).scalar_one())


def record_invoice(db: Session, order: PurchaseOrder, vendor_reference: str, amount: int,
                   invoice_date: date, recorded_by: uuid.UUID) -> VendorInvoice:  # fmt: skip
    """Record the vendor's invoice against a received order. The vendor's reference is
    unique; an invoice taking the total invoiced above what was received (by more than
    2 %) is held, otherwise it is matched and waits for payment approval."""
    if order.status not in (OrderStatus.RECEIVED, OrderStatus.CLOSED):
        raise BusinessRuleViolation(f"{order.order_number} has nothing received to invoice.",
                                    {"rule": "not_received"})  # fmt: skip
    if amount <= 0:
        raise BusinessRuleViolation("An invoice is for a positive amount.",
                                    {"rule": "amount_invalid"})  # fmt: skip
    reference = vendor_reference.strip().upper()
    duplicate = db.execute(
        select(VendorInvoice.invoice_number).join(PurchaseOrder,
                                                  PurchaseOrder.id == VendorInvoice.order_id)
        .where(PurchaseOrder.vendor_id == order.vendor_id,
               VendorInvoice.vendor_reference == reference,
               VendorInvoice.status != InvoiceStatus.REJECTED).limit(1)
    ).scalar_one_or_none()  # fmt: skip
    if duplicate:
        raise BusinessRuleViolation(f"The vendor's invoice {reference} is already {duplicate}.",
                                    {"rule": "duplicate_invoice"})  # fmt: skip
    allowed = order.received_amount * (100 + MATCH_TOLERANCE_PCT) // 100
    over = invoiced(db, order) + amount > allowed
    number = db.execute(INVOICE_SEQUENCE.next_value()).scalar_one()
    invoice = VendorInvoice(
        invoice_number=f"INV-{number:07d}", vendor_reference=reference, order_id=order.id,
        amount=amount, currency=order.currency, invoice_date=invoice_date,
        status=(InvoiceStatus.HELD if over else InvoiceStatus.RECORDED).value,
        hold_reason=(f"Invoiced would exceed the {order.received_amount} received by more "
                     f"than {MATCH_TOLERANCE_PCT} %.") if over else None,
        recorded_by=recorded_by,
    )  # fmt: skip
    db.add(invoice)
    db.flush()
    _audit(db, recorded_by, "procurement.invoice_recorded", "vendor_invoice", invoice.id,
           invoice_number=invoice.invoice_number, status=invoice.status)  # fmt: skip
    return invoice


def get_invoice(db: Session, invoice_id: uuid.UUID) -> VendorInvoice:
    invoice = db.get(VendorInvoice, invoice_id)
    if invoice is None:
        raise NotFoundError("No such invoice.")
    return invoice


def purchases_account(db: Session, currency: str) -> LedgerAccount:
    return ledger.ensure_ledger_account(
        db, code=f"PROC-PURCHASES-{currency}", name=f"Purchases ({currency})",
        account_type=LedgerAccountType.EXPENSE, currency=currency,
    )  # fmt: skip


def pay_invoice(db: Session, invoice: VendorInvoice, actor_id: uuid.UUID) -> VendorInvoice:
    """Pay a matched invoice: someone other than whoever recorded it, to an approved vendor
    with no bank change awaiting checks. Debits purchases, credits the bank's cash."""
    if invoice.status != InvoiceStatus.RECORDED:
        raise ConflictError(f"{invoice.invoice_number} is {invoice.status}.")
    _four_eyes(invoice.recorded_by, actor_id, "recorded")
    order = get_order(db, invoice.order_id)
    vendor = get_vendor(db, order.vendor_id)
    if vendor.status != VendorStatus.APPROVED:
        raise BusinessRuleViolation(f"{vendor.vendor_number} is {vendor.status}.",
                                    {"rule": "vendor_not_approved"})  # fmt: skip
    if vendor.pending_bank_account:
        raise BusinessRuleViolation(
            f"{vendor.vendor_number}'s bank details are changing; pay once the change is "
            "verified.", {"rule": "bank_change_pending"})  # fmt: skip
    memo = f"{invoice.invoice_number} {vendor.name} ({order.order_number})"
    entry, _ = ledger.post_entry(
        db, idempotency_key=f"vendor-invoice:{invoice.invoice_number}",
        currency=invoice.currency, description=memo, source="vendor_payment",
        lines=[ledger.LineSpec(purchases_account(db, invoice.currency).id, Direction.DEBIT,
                               invoice.amount, memo),
               ledger.LineSpec(ledger.cash_account(db, invoice.currency).id, Direction.CREDIT,
                               invoice.amount, memo)],
        actor_id=actor_id,
    )  # fmt: skip
    invoice.status, invoice.paid_by = InvoiceStatus.PAID.value, actor_id
    invoice.paid_to, invoice.entry_number = vendor.bank_account, entry.entry_number
    invoice.decided_at = _now()
    db.flush()
    paid = db.execute(
        select(func.coalesce(func.sum(VendorInvoice.amount), 0)).where(
            VendorInvoice.order_id == order.id, VendorInvoice.status == InvoiceStatus.PAID)
    ).scalar_one()  # fmt: skip
    if paid >= order.received_amount == order.total:
        order.status = OrderStatus.CLOSED.value
    db.flush()
    _audit(db, actor_id, "procurement.invoice_paid", "vendor_invoice", invoice.id,
           invoice_number=invoice.invoice_number, entry_number=entry.entry_number)  # fmt: skip
    return invoice


def reject_invoice(db: Session, invoice: VendorInvoice, actor_id: uuid.UUID) -> VendorInvoice:
    if invoice.status not in (InvoiceStatus.RECORDED, InvoiceStatus.HELD):
        raise ConflictError(f"{invoice.invoice_number} is {invoice.status}.")
    _four_eyes(invoice.recorded_by, actor_id, "recorded")
    invoice.status, invoice.decided_at = InvoiceStatus.REJECTED.value, _now()
    db.flush()
    _audit(db, actor_id, "procurement.invoice_rejected", "vendor_invoice", invoice.id,
           invoice_number=invoice.invoice_number)  # fmt: skip
    return invoice


def invoice_profile(db: Session, invoice: VendorInvoice) -> dict[str, Any]:
    """What an approver weighs before paying an invoice (Phase 58), as of the day it was
    recorded: its amount; the vendor's age, tier and any bank-detail change, and whether
    anything has been paid to the new account since; whether the invoice is dated before
    the order was raised; how far the invoiced total runs over what was received; and the
    vendor's other invoices in the 90 days before, and how many were for the same amount."""
    order = get_order(db, invoice.order_id)
    vendor = get_vendor(db, order.vendor_id)
    asked = invoice.created_at
    others = list(db.execute(
        select(VendorInvoice).join(PurchaseOrder, PurchaseOrder.id == VendorInvoice.order_id)
        .where(PurchaseOrder.vendor_id == vendor.id, VendorInvoice.id != invoice.id,
               VendorInvoice.status != InvoiceStatus.REJECTED,
               VendorInvoice.created_at < asked,
               VendorInvoice.created_at >= asked - timedelta(days=90))
    ).scalars())  # fmt: skip
    changed = vendor.bank_changed_at
    paid_since = None
    if changed is not None:
        paid_since = db.execute(
            select(func.count()).select_from(VendorInvoice)
            .join(PurchaseOrder, PurchaseOrder.id == VendorInvoice.order_id)
            .where(PurchaseOrder.vendor_id == vendor.id, VendorInvoice.id != invoice.id,
                   VendorInvoice.status == InvoiceStatus.PAID,
                   VendorInvoice.decided_at >= changed)
        ).scalar_one()  # fmt: skip
    invoiced_total = invoiced(db, order, exclude=invoice.id) + invoice.amount
    over = invoiced_total - order.received_amount
    return {
        "amount": invoice.amount, "currency": invoice.currency,
        "amount_usd": _usd(db, invoice.amount, invoice.currency),
        "vendor_category": vendor.category, "vendor_risk_tier": vendor.risk_tier,
        "vendor_age_days": (asked.date() - vendor.created_at.date()).days,
        "bank_changed_days_ago": (asked.date() - changed.date()).days if changed else None,
        "paid_since_bank_change": paid_since,
        "invoice_before_order": invoice.invoice_date < order.created_at.date(),
        "invoice_age_days": (asked.date() - invoice.invoice_date).days,
        "partial_delivery": order.received_amount < order.total,
        "over_received_bps": max(over, 0) * 10_000 // order.received_amount
        if order.received_amount else 0,
        "vendor_invoices_90d": len(others),
        "same_amount_invoices_90d": sum(1 for o in others if o.amount == invoice.amount),
    }  # fmt: skip


def summary(db: Session) -> dict[str, Any]:
    def count(model, *where) -> int:
        return db.execute(select(func.count()).select_from(model).where(*where)).scalar_one()

    return {
        "vendors_to_approve": count(Vendor, Vendor.status == VendorStatus.PENDING),
        "vendors_approved": count(Vendor, Vendor.status == VendorStatus.APPROVED),
        "bank_changes_to_verify": count(Vendor, Vendor.pending_bank_account.is_not(None)),
        "orders_to_approve": count(PurchaseOrder, PurchaseOrder.status == OrderStatus.REQUESTED),
        "orders_open": count(PurchaseOrder, PurchaseOrder.status.in_(
            [OrderStatus.APPROVED, OrderStatus.RECEIVED])),
        "invoices_to_pay": count(VendorInvoice, VendorInvoice.status == InvoiceStatus.RECORDED),
        "invoices_held": count(VendorInvoice, VendorInvoice.status == InvoiceStatus.HELD),
    }  # fmt: skip
