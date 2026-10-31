"""Phase 31: cards — issuing, authorisation with fraud rules, blocks, disputes."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, ConflictError
from app.modules.accounts.models import AccountType
from app.modules.cards import service as cards
from app.modules.cards.models import CardStatus
from app.modules.ledger import service as ledger
from app.modules.retail import service as retail
from tests.factories import auth, funded_account, make_customer, make_staff, open_account

NOW = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)


def _balance(db: Session, account) -> int:
    return ledger.balance(db, ledger.get_ledger_account(db, account.ledger_account_id))


def _buy(db, card, amount, *, category="5411", country="US", at=NOW, name="Corner Grocer"):
    return cards.authorize(
        db, card, merchant_name=name, merchant_category=category, merchant_country=country,
        amount=amount, now=at,
    )  # fmt: skip


def test_card_numbers_are_synthetic_and_check_digited(db: Session) -> None:
    staff = make_staff(db)
    account = funded_account(db, staff)
    card = cards.issue_card(db, account, "debit-standard", staff.employee.id, now=NOW)
    assert card.card_number.startswith("9999") and len(card.card_number) == 16
    assert cards.luhn_valid(card.card_number)
    assert cards.masked(card.card_number).endswith(card.card_number[-4:])
    assert card.daily_limit == 150_000 and card.expires_on.year == 2030  # US$1,500, 4 years
    savings = open_account(db, staff, make_customer(db), AccountType.SAVINGS)
    with pytest.raises(BusinessRuleViolation, match="current accounts"):
        cards.issue_card(db, savings, "debit-standard", None)
    cards.issue_card(db, account, "debit-premium", None)
    with pytest.raises(BusinessRuleViolation, match="at most two"):
        cards.issue_card(db, account, "debit-standard", None)


def test_authorisation_checks_funds_limit_and_posts_to_the_ledger(db: Session) -> None:
    staff = make_staff(db)
    account = funded_account(db, staff, balance=100_000)
    card = cards.issue_card(db, account, "debit-standard", None, now=NOW)
    approved = _buy(db, card, 30_000)
    assert approved.status == "approved" and approved.journal_entry_id is not None
    assert _balance(db, account) == 70_000
    settlement = cards.settlement_account(db, "USD")
    assert ledger.balance(db, settlement) == 30_000
    # More than the balance: declined, nothing posted.
    assert _buy(db, card, 80_000).decline_reason == "insufficient_funds"
    # An arranged overdraft counts.
    retail.set_overdraft(db, account, 50_000, staff.manager.id)
    assert _buy(db, card, 69_000, name="Electronics").status == "approved"
    assert _balance(db, account) == 1_000
    # The daily limit (US$1,500): 990.00 spent today; another 600.00 is too much.
    retail.set_overdraft(db, account, 200_000, staff.manager.id)
    assert _buy(db, card, 60_000).decline_reason == "daily_limit"
    assert _buy(db, card, 60_000, at=NOW + timedelta(days=1)).status == "approved"


def test_fraud_rules_decline_and_block_the_card(db: Session) -> None:
    staff = make_staff(db)
    account = funded_account(db, staff, balance=500_000)
    card = cards.issue_card(db, account, "debit-standard", None, now=NOW)
    # Abroad (30) at a gambling merchant (40): 70, declined and blocked.
    risky = _buy(db, card, 5_000, category="7995", country="MT", name="Lucky Spins")
    assert risky.status == "declined" and risky.decline_reason == "fraud_suspected"
    assert risky.fraud_score == 70 and risky.fraud_signals == "foreign_merchant,high_risk_category"
    assert card.status == CardStatus.BLOCKED and card.blocked_reason == "fraud_suspected"
    assert _buy(db, card, 1_000).decline_reason == "card_blocked"
    cards.unblock_card(db, card, staff.compliance.id)
    assert _buy(db, card, 1_000).status == "approved"
    # Abroad alone (30) is not enough; with velocity (30) and a large amount (20) it is.
    for minute in range(5):
        _buy(db, card, 1_000, at=NOW + timedelta(minutes=minute))
    fast = _buy(db, card, 80_000, country="FR", at=NOW + timedelta(minutes=6))
    assert fast.decline_reason == "fraud_suspected" and fast.fraud_score == 80
    with pytest.raises(ConflictError):
        cards.unblock_card(db, cards.issue_card(db, account, "debit-premium", None), None)


def test_disputes_end_in_a_chargeback_or_a_rejection_with_four_eyes(db: Session) -> None:
    staff = make_staff(db)
    account = funded_account(db, staff, balance=100_000)
    card = cards.issue_card(db, account, "debit-standard", None, now=NOW)
    purchase = _buy(db, card, 40_000)
    dispute = cards.open_dispute(db, purchase, "not_received", None, staff.employee.id, now=NOW)
    assert dispute.dispute_number.startswith("DSP-") and dispute.amount == 40_000
    with pytest.raises(ConflictError, match="already has a dispute"):
        cards.open_dispute(db, purchase, "duplicate", None, staff.employee.id, now=NOW)
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        cards.decide_dispute(db, dispute, True, staff.employee.id)
    cards.decide_dispute(db, dispute, True, staff.compliance.id, now=NOW)
    assert dispute.status == "refunded" and _balance(db, account) == 100_000
    assert ledger.balance(db, cards.settlement_account(db, "USD")) == 0
    # A rejected dispute moves no money and frees the purchase for another dispute.
    other = _buy(db, card, 10_000)
    rejected = cards.open_dispute(db, other, "wrong_amount", 4_000, staff.employee.id, now=NOW)
    cards.decide_dispute(db, rejected, False, staff.manager.id, now=NOW)
    assert rejected.status == "rejected" and _balance(db, account) == 90_000
    declined = _buy(db, card, 10_000_000)
    with pytest.raises(BusinessRuleViolation, match="approved purchase"):
        cards.open_dispute(db, declined, "not_recognised", None, staff.employee.id, now=NOW)
    with pytest.raises(BusinessRuleViolation, match="120 days"):
        cards.open_dispute(db, other, "duplicate", None, None, now=NOW + timedelta(days=121))


def test_the_cards_api(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    teller, compliance = auth(staff.employee), auth(staff.compliance)
    account = funded_account(db, staff, balance=200_000)
    db.commit()

    products = client.get("/api/v1/cards/products", headers=teller).json()
    assert {p["product_code"] for p in products} == {"debit-standard", "debit-premium"}
    issued = client.post(
        "/api/v1/cards", json={"account_number": account.account_number}, headers=teller
    )
    assert issued.status_code == 201, issued.text
    card = issued.json()
    assert "••••" in card["card_number"] and card["status"] == "active"

    body = {"merchant_name": "Book Shop", "merchant_category": "5942", "merchant_country": "US",
            "amount": 2_500}  # fmt: skip
    bought = client.post(f"/api/v1/cards/{card['id']}/authorizations", json=body, headers=teller)
    assert bought.status_code == 201 and bought.json()["status"] == "approved"
    code = bought.json()["auth_code"]
    risky = client.post(
        f"/api/v1/cards/{card['id']}/authorizations",
        json={**body, "merchant_category": "6051", "merchant_country": "KY"},
        headers=teller,
    ).json()
    assert risky["decline_reason"] == "fraud_suspected"
    assert risky["fraud_signals"] == ["foreign_merchant", "high_risk_category"]
    assert client.post(f"/api/v1/cards/{card['id']}/unblock", headers=teller).status_code == 403
    released = client.post(f"/api/v1/cards/{card['id']}/unblock", headers=compliance)
    assert released.json()["status"] == "active"

    opened = client.post(
        "/api/v1/cards/disputes", json={"auth_code": code, "reason": "duplicate"}, headers=teller
    )
    assert opened.status_code == 201
    decided = client.post(
        f"/api/v1/cards/disputes/{opened.json()['id']}/decide",
        json={"refund": True},
        headers=compliance,
    )
    assert decided.json()["status"] == "refunded"
    listed = client.get("/api/v1/cards/authorizations/list", headers=teller).json()
    assert listed["total"] == 2
    counts = client.get("/api/v1/cards/summary/counts", headers=teller).json()
    assert counts["active_cards"] >= 1 and counts["declined"] >= 1
