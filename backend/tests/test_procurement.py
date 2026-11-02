"""Phase 57: procurement and vendor management — vendors, bank changes, orders, invoices."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, ConflictError
from app.core.permissions import RoleCode
from app.modules.ledger import service as ledger
from app.modules.procurement import service as procurement
from tests.factories import auth, make_org_tree, make_user

DAY = date(2041, 3, 4)


def _vendor(db: Session, clerk, approver, *, name: str = "Harbour Office Supplies",
            country: str = "US", category: str = "facilities"):  # fmt: skip
    vendor = procurement.register_vendor(db, name=name, country_code=country, category=category,
                                         bank_account="US000123456789",
                                         registered_by=clerk.id)  # fmt: skip
    return procurement.decide_vendor(db, vendor, approver.id, True)


def _order(db: Session, vendor, dept, clerk, approver, quantity: int = 10,
           unit_price: int = 10_000):  # fmt: skip
    order = procurement.raise_order(db, vendor, dept.id, "Printer paper",
                                    [{"description": "A4 paper", "quantity": quantity,
                                      "unit_price": unit_price}], clerk.id)  # fmt: skip
    return procurement.decide_order(db, order, approver.id, True)


def test_vendor_screening_tiers_and_approval(db: Session) -> None:
    clerk = make_user(db, RoleCode.BANKING_EMPLOYEE)
    manager = make_user(db, RoleCode.DEPARTMENT_MANAGER)
    with pytest.raises(BusinessRuleViolation, match="Category"):
        procurement.register_vendor(db, name="Odd Things", country_code="US", category="toys",
                                    bank_account="US000123456789",
                                    registered_by=clerk.id)  # fmt: skip
    vendor = procurement.register_vendor(db, name="Harbour Office Supplies", country_code="us",
                                         category="facilities", bank_account="us000123456789",
                                         registered_by=clerk.id)  # fmt: skip
    assert vendor.vendor_number.startswith("VEN-") and vendor.status == "pending"
    assert vendor.risk_tier == "low" and vendor.currency == "USD"
    assert vendor.bank_account == "US000123456789" and not vendor.screening["hit"]
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        procurement.decide_vendor(db, vendor, clerk.id, True)
    procurement.decide_vendor(db, vendor, manager.id, True)
    assert vendor.status == "approved" and vendor.approved_by == manager.id
    with pytest.raises(ConflictError):
        procurement.decide_vendor(db, vendor, manager.id, False)

    # One tier higher outside the bank's active countries; outsourcing is high already.
    planned = procurement.register_vendor(db, name="Gulf Print House", country_code="AE",
                                          category="it", bank_account="AE000123456789",
                                          registered_by=clerk.id)  # fmt: skip
    assert planned.risk_tier == "high" and planned.currency == "AED"
    with pytest.raises(BusinessRuleViolation, match="executive") as refused:
        procurement.decide_vendor(db, planned, manager.id, True)
    assert refused.value.details["rule"] == "needs_executive"
    procurement.decide_vendor(db, planned, manager.id, True, executive=True)
    assert planned.status == "approved"

    # A sanctions hit is never approved, not even by an executive; it can be rejected.
    hit = procurement.register_vendor(db, name="Cyrus Frontcorp", country_code="US",
                                      category="marketing", bank_account="US000999999999",
                                      registered_by=clerk.id)  # fmt: skip
    assert hit.screening["hit"] and hit.screening["list"] == "synthetic-us-v1"
    with pytest.raises(BusinessRuleViolation, match="sanctions") as refused:
        procurement.decide_vendor(db, hit, manager.id, True, executive=True)
    assert refused.value.details["rule"] == "sanctions_hit"
    procurement.decide_vendor(db, hit, manager.id, False)
    assert hit.status == "rejected" and hit.approved_by is None


def test_orders_need_approved_vendors_and_executives_above_threshold(db: Session) -> None:
    tree = make_org_tree(db)
    clerk = make_user(db, RoleCode.BANKING_EMPLOYEE)
    manager = make_user(db, RoleCode.DEPARTMENT_MANAGER)
    pending = procurement.register_vendor(db, name="Late Supplies", country_code="US",
                                          category="facilities", bank_account="US000111111111",
                                          registered_by=clerk.id)  # fmt: skip
    with pytest.raises(BusinessRuleViolation, match="approved vendors"):
        procurement.raise_order(db, pending, tree.us_onboarding.id, "Paper",
                                [{"description": "Paper", "quantity": 1, "unit_price": 100}],
                                clerk.id)  # fmt: skip
    vendor = _vendor(db, clerk, manager)
    with pytest.raises(BusinessRuleViolation, match="lines"):
        procurement.raise_order(db, vendor, tree.us_onboarding.id, "Paper",
                                [{"description": "Paper", "quantity": 0, "unit_price": 100}],
                                clerk.id)  # fmt: skip
    order = procurement.raise_order(
        db, vendor, tree.us_onboarding.id, "Desks and paper",
        [{"description": "Desk", "quantity": 2, "unit_price": 30_000},
         {"description": "Paper", "quantity": 10, "unit_price": 1_000}], clerk.id,
    )  # fmt: skip
    assert order.order_number.startswith("PO-") and order.total == 70_000
    assert order.status == "requested" and procurement.total_usd(db, order) == 700
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        procurement.decide_order(db, order, clerk.id, True)
    procurement.decide_order(db, order, manager.id, True)
    assert order.status == "approved"

    # Above US$50,000 only an executive approves; anyone else may still reject.
    large = procurement.raise_order(db, vendor, tree.us_onboarding.id, "Fit-out",
                                    [{"description": "Fit-out", "quantity": 1,
                                      "unit_price": 5_000_001}], clerk.id)  # fmt: skip
    with pytest.raises(BusinessRuleViolation, match="executive") as refused:
        procurement.decide_order(db, large, manager.id, True)
    assert refused.value.details["rule"] == "needs_executive"
    procurement.decide_order(db, large, manager.id, True, executive=True)
    assert large.status == "approved"
    exactly = procurement.raise_order(db, vendor, tree.us_onboarding.id, "Fit-out",
                                      [{"description": "Fit-out", "quantity": 1,
                                        "unit_price": 5_000_000}], clerk.id)  # fmt: skip
    procurement.decide_order(db, exactly, manager.id, True)  # US$50,000 exactly is not above

    # Receipts are only for approved orders and never above what was ordered.
    with pytest.raises(BusinessRuleViolation, match="More was received"):
        procurement.receive(db, order, 70_001, clerk.id)
    procurement.receive(db, order, 30_000, clerk.id, on=DAY)
    procurement.receive(db, order, 40_000, clerk.id, on=DAY)
    assert order.status == "received" and order.received_amount == 70_000
    with pytest.raises(BusinessRuleViolation, match="More was received"):
        procurement.receive(db, order, 1, clerk.id)
    rejected = procurement.raise_order(db, vendor, tree.us_onboarding.id, "Chairs",
                                       [{"description": "Chair", "quantity": 1,
                                         "unit_price": 100}], clerk.id)  # fmt: skip
    procurement.decide_order(db, rejected, manager.id, False)
    with pytest.raises(BusinessRuleViolation, match="rejected"):
        procurement.receive(db, rejected, 100, clerk.id)


def test_invoice_matching_holds_duplicates_and_payment(db: Session) -> None:
    tree = make_org_tree(db)
    clerk = make_user(db, RoleCode.BANKING_EMPLOYEE)
    manager = make_user(db, RoleCode.DEPARTMENT_MANAGER)
    vendor = _vendor(db, clerk, manager)
    order = _order(db, vendor, tree.us_onboarding, clerk, manager)  # 100,000 ordered
    with pytest.raises(BusinessRuleViolation, match="nothing received"):
        procurement.record_invoice(db, order, "HOS-1", 100_000, DAY, clerk.id)
    procurement.receive(db, order, 60_000, clerk.id)

    # Within 2 % of what was received: matched. Beyond it: held.
    first = procurement.record_invoice(db, order, "hos-1", 61_200, DAY, clerk.id)
    assert first.status == "recorded" and first.vendor_reference == "HOS-1"
    assert first.invoice_number.startswith("INV-") and first.hold_reason is None
    with pytest.raises(BusinessRuleViolation, match="already") as refused:
        procurement.record_invoice(db, order, "HOS-1", 10, DAY, clerk.id)
    assert refused.value.details["rule"] == "duplicate_invoice"
    held = procurement.record_invoice(db, order, "HOS-2", 1, DAY, clerk.id)
    assert held.status == "held" and "exceed" in held.hold_reason
    with pytest.raises(ConflictError):
        procurement.pay_invoice(db, held, manager.id)
    procurement.reject_invoice(db, held, manager.id)
    assert held.status == "rejected"

    # Paid by someone other than the recorder: purchases debited, cash credited.
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        procurement.pay_invoice(db, first, clerk.id)
    purchases = procurement.purchases_account(db, "USD")
    before = ledger.balance(db, purchases)
    procurement.pay_invoice(db, first, manager.id)
    assert first.status == "paid" and first.paid_to == "US000123456789"
    assert first.entry_number and ledger.balance(db, purchases) - before == 61_200
    assert order.status == "received"  # not everything has been received yet

    # The rest arrives and is invoiced and paid: the order closes.
    procurement.receive(db, order, 40_000, clerk.id)
    rest = procurement.record_invoice(db, order, "HOS-3", 38_800, DAY, clerk.id)
    procurement.pay_invoice(db, rest, manager.id)
    assert order.status == "closed"


def test_bank_change_needs_a_second_person_and_blocks_payment(db: Session) -> None:
    tree = make_org_tree(db)
    clerk = make_user(db, RoleCode.BANKING_EMPLOYEE)
    manager = make_user(db, RoleCode.DEPARTMENT_MANAGER)
    vendor = _vendor(db, clerk, manager)
    order = _order(db, vendor, tree.us_onboarding, clerk, manager)
    procurement.receive(db, order, order.total, clerk.id)
    invoice = procurement.record_invoice(db, order, "HOS-9", order.total, DAY, clerk.id)

    with pytest.raises(BusinessRuleViolation, match="different"):
        procurement.request_bank_change(db, vendor, "US000123456789", clerk.id)
    procurement.request_bank_change(db, vendor, "US000987654321", clerk.id)
    with pytest.raises(ConflictError):
        procurement.request_bank_change(db, vendor, "US000555555555", clerk.id)
    with pytest.raises(BusinessRuleViolation, match="bank details are changing") as refused:
        procurement.pay_invoice(db, invoice, manager.id)
    assert refused.value.details["rule"] == "bank_change_pending"
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        procurement.verify_bank_change(db, vendor, clerk.id, True)
    procurement.verify_bank_change(db, vendor, manager.id, True)
    assert vendor.bank_account == "US000987654321" and vendor.pending_bank_account is None
    procurement.pay_invoice(db, invoice, manager.id)
    assert invoice.paid_to == "US000987654321"

    # A refused change leaves the account as it was.
    procurement.request_bank_change(db, vendor, "US000444444444", clerk.id)
    procurement.verify_bank_change(db, vendor, manager.id, False)
    assert vendor.bank_account == "US000987654321" and vendor.pending_bank_account is None
    with pytest.raises(ConflictError):
        procurement.verify_bank_change(db, vendor, manager.id, True)


def test_procurement_api_and_permissions(client: TestClient, db: Session) -> None:
    tree = make_org_tree(db)
    clerk = make_user(db, RoleCode.BANKING_EMPLOYEE)
    manager = make_user(db, RoleCode.DEPARTMENT_MANAGER)
    executive = make_user(db, RoleCode.REGIONAL_EXECUTIVE)
    auditor = make_user(db, RoleCode.AUDITOR)
    body = {"name": "Meridian Outsourcing", "country": "US", "category": "outsourcing",
            "bank_account": "US000222222222"}  # fmt: skip
    assert client.post("/api/v1/procurement/vendors", json=body,
                       headers=auth(auditor)).status_code == 403  # fmt: skip
    created = client.post("/api/v1/procurement/vendors", json=body, headers=auth(clerk))
    assert created.status_code == 201, created.text
    vendor = created.json()
    assert vendor["risk_tier"] == "high" and vendor["status"] == "pending"
    url = f"/api/v1/procurement/vendors/{vendor['id']}"
    assert client.post(f"{url}/approve", headers=auth(clerk)).status_code == 403
    refused = client.post(f"{url}/approve", headers=auth(manager))
    assert refused.status_code == 422
    assert refused.json()["error"]["details"]["rule"] == "needs_executive"
    approved = client.post(f"{url}/approve", headers=auth(executive))
    assert approved.status_code == 200 and approved.json()["status"] == "approved"

    order = client.post(
        "/api/v1/procurement/orders",
        headers=auth(clerk),
        json={
            "vendor_number": vendor["vendor_number"],
            "department_id": str(tree.us_onboarding.id),
            "description": "Call centre overflow",
            "lines": [{"description": "Agent hours", "quantity": 100, "unit_price": 2_500}],
        },
    )
    assert order.status_code == 201, order.text
    order = order.json()
    assert order["total"] == 250_000 and order["department"] == tree.us_onboarding.name
    order_url = f"/api/v1/procurement/orders/{order['id']}"
    assert client.post(f"{order_url}/approve", headers=auth(manager)).json()["status"] == (
        "approved")  # fmt: skip
    received = client.post(f"{order_url}/receive", json={"amount": 250_000},
                           headers=auth(clerk))  # fmt: skip
    assert received.json()["status"] == "received"
    invoice = client.post(
        "/api/v1/procurement/invoices",
        headers=auth(clerk),
        json={
            "order_number": order["order_number"],
            "vendor_reference": "MO-77",
            "amount": 250_000,
            "invoice_date": "2041-03-04",
        },
    )
    assert invoice.status_code == 201, invoice.text
    invoice = invoice.json()
    assert invoice["status"] == "recorded" and invoice["vendor_name"] == "Meridian Outsourcing"
    pay_url = f"/api/v1/procurement/invoices/{invoice['id']}/pay"
    assert client.post(pay_url, headers=auth(clerk)).status_code == 403
    paid = client.post(pay_url, headers=auth(manager))
    assert paid.status_code == 200 and paid.json()["status"] == "paid"
    assert paid.json()["paid_to"] == "US000222222222"

    listed = client.get("/api/v1/procurement/invoices?status=paid", headers=auth(auditor))
    assert listed.status_code == 200 and listed.json()["total"] >= 1
    counts = client.get("/api/v1/procurement/summary/counts", headers=auth(auditor)).json()
    assert set(counts) >= {"vendors_to_approve", "orders_to_approve", "invoices_to_pay",
                           "invoices_held", "bank_changes_to_verify"}  # fmt: skip
    closed = client.get("/api/v1/procurement/orders?status=closed", headers=auth(auditor))
    assert order["order_number"] in [o["order_number"] for o in closed.json()["items"]]
    departments = client.get("/api/v1/procurement/departments", headers=auth(clerk)).json()
    assert tree.us_onboarding.name in [d["name"] for d in departments]
