"""Card services (Phase 31): issuing, authorisation with fraud rules, blocks, disputes."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.core.money import minor_unit_exponent
from app.modules.accounts import service as accounts
from app.modules.accounts.models import Account, AccountStatus
from app.modules.cards.models import (
    AUTHORIZATION_SEQUENCE,
    CARD_SEQUENCE,
    DISPUTE_SEQUENCE,
    AuthorizationStatus,
    Card,
    CardAuthorization,
    CardDispute,
    CardProduct,
    CardStatus,
    DisputeStatus,
)
from app.modules.countries.models import Country
from app.modules.customers.models import Customer
from app.modules.fx import rates
from app.modules.ledger import service as ledger
from app.modules.ledger.models import Direction, LedgerAccountType

SYNTHETIC_PREFIX = "9999"  # used by no real card scheme
# Merchant categories the fraud rules treat as high risk (gambling, crypto, money transfer).
HIGH_RISK_CATEGORIES = frozenset({"7995", "6051", "4829"})
# Fraud score from which an authorisation is declined and the card blocked.
BLOCK_SCORE = 70
VELOCITY_WINDOW = timedelta(hours=1)
VELOCITY_COUNT = 5
DISPUTE_WINDOW = timedelta(days=120)


def luhn_digit(digits: str) -> str:
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d)
        if i % 2 == 0:
            n *= 2
            n = n - 9 if n > 9 else n
        total += n
    return str((10 - total % 10) % 10)


def luhn_valid(number: str) -> bool:
    return number.isdigit() and luhn_digit(number[:-1]) == number[-1]


def masked(number: str) -> str:
    return f"{number[:4]} •••• •••• {number[-4:]}"


def get_product(db: Session, code: str) -> CardProduct:
    product = db.get(CardProduct, code)
    if product is None:
        raise NotFoundError(f"No card product {code}.")
    return product


def list_products(db: Session) -> list[CardProduct]:
    return list(db.execute(select(CardProduct).order_by(CardProduct.product_code)).scalars())


def daily_limit(product: CardProduct, currency: str) -> int:
    units = Decimal(product.daily_limit_usd) * rates.units_per_usd(currency, rates.ANCHOR_DATE)
    whole = int(units)
    if whole >= 100:  # two significant figures, like the other converted terms
        whole = round(whole, -(len(str(whole)) - 2))
    return max(whole, 1) * 10 ** minor_unit_exponent(currency)


def get_card(db: Session, card_id: uuid.UUID, *, for_update: bool = False) -> Card:
    query = select(Card).where(Card.id == card_id)
    if for_update:
        query = query.with_for_update()
    card = db.execute(query).scalar_one_or_none()
    if card is None:
        raise NotFoundError("Card not found.")
    return card


def find_card(db: Session, number: str) -> Card | None:
    return db.execute(select(Card).where(Card.card_number == number)).scalar_one_or_none()


# --- Issuing ------------------------------------------------------------------------------------


def issue_card(
    db: Session,
    account: Account,
    product_code: str,
    actor_id: uuid.UUID | None,
    *,
    now: datetime | None = None,
) -> Card:
    now = now or datetime.now(UTC)
    product = get_product(db, product_code)
    if account.status != AccountStatus.OPEN:
        raise BusinessRuleViolation(f"The account is {account.status}; no card can be issued.")
    if account.account_type not in ("current", "business_current"):
        raise BusinessRuleViolation("Debit cards are issued on current accounts only.")
    live = db.execute(
        select(func.count()).where(
            Card.account_id == account.id, Card.status != CardStatus.CANCELLED
        )
    ).scalar_one()
    if live >= 2:
        raise BusinessRuleViolation("An account has at most two live cards.")
    serial = db.execute(CARD_SEQUENCE.next_value()).scalar_one()
    body = f"{SYNTHETIC_PREFIX}{serial:011d}"
    card = Card(
        card_number=body + luhn_digit(body),
        product_code=product.product_code,
        account_id=account.id,
        customer_id=account.customer_id,
        currency=account.currency,
        daily_limit=daily_limit(product, account.currency),
        expires_on=now.replace(year=now.year + product.validity_years),
        status=CardStatus.ACTIVE.value,
        issued_by=actor_id,
        issued_at=now,
    )
    db.add(card)
    db.flush()
    record_audit_event(
        db,
        actor_id=actor_id,
        action="card.issued",
        entity_type="card",
        entity_id=card.id,
        metadata={"card": masked(card.card_number), "account_number": account.account_number,
                  "product": product.product_code},
    )  # fmt: skip
    return card


def block_card(
    db: Session, card: Card, reason: str, actor_id: uuid.UUID | None, *, now: datetime | None = None
) -> Card:
    if card.status != CardStatus.ACTIVE:
        raise ConflictError(f"The card is {card.status}.")
    card.status = CardStatus.BLOCKED.value
    card.blocked_reason = reason
    card.blocked_at = now or datetime.now(UTC)
    db.flush()
    record_audit_event(
        db,
        actor_id=actor_id,
        action="card.blocked",
        entity_type="card",
        entity_id=card.id,
        metadata={"card": masked(card.card_number), "reason": reason},
    )
    return card


def unblock_card(db: Session, card: Card, actor_id: uuid.UUID | None) -> Card:
    if card.status != CardStatus.BLOCKED:
        raise ConflictError(f"The card is {card.status}, not blocked.")
    reason = card.blocked_reason
    card.status = CardStatus.ACTIVE.value
    card.blocked_reason = None
    card.blocked_at = None
    db.flush()
    record_audit_event(
        db,
        actor_id=actor_id,
        action="card.unblocked",
        entity_type="card",
        entity_id=card.id,
        metadata={"card": masked(card.card_number), "was": reason},
    )
    return card


def cancel_card(db: Session, card: Card, actor_id: uuid.UUID) -> Card:
    if card.status == CardStatus.CANCELLED:
        raise ConflictError("The card is already cancelled.")
    card.status = CardStatus.CANCELLED.value
    card.blocked_reason = None
    card.blocked_at = None
    db.flush()
    record_audit_event(
        db, actor_id=actor_id, action="card.cancelled", entity_type="card", entity_id=card.id,
        metadata={"card": masked(card.card_number)},
    )  # fmt: skip
    return card


# --- Authorisation ------------------------------------------------------------------------------


def settlement_account(db: Session, currency: str):
    """What the bank owes the card network for approved purchases, per currency."""
    return ledger.ensure_ledger_account(
        db,
        code=f"CARD-SETTLEMENT-{currency}",
        name=f"Card settlement payable ({currency})",
        account_type=LedgerAccountType.LIABILITY,
        currency=currency,
    )


def home_country(db: Session, card: Card) -> str:
    return db.execute(
        select(Country.iso_country_code)
        .join(Customer, Customer.country_id == Country.id)
        .where(Customer.id == card.customer_id)
    ).scalar_one()


def fraud_signals(
    db: Session, card: Card, merchant_category: str, merchant_country: str, amount: int,
    now: datetime,
) -> tuple[int, list[str]]:  # fmt: skip
    """The fraud rules: points per signal; from BLOCK_SCORE the card is blocked."""
    signals: list[tuple[str, int]] = []
    if merchant_country != home_country(db, card):
        signals.append(("foreign_merchant", 30))
    if merchant_category in HIGH_RISK_CATEGORIES:
        signals.append(("high_risk_category", 40))
    if amount >= card.daily_limit // 2:
        signals.append(("large_amount", 20))
    recent = db.execute(
        select(func.count()).where(
            CardAuthorization.card_id == card.id,
            CardAuthorization.created_at >= now - VELOCITY_WINDOW,
            CardAuthorization.created_at <= now,  # bounded: simulations backdate purchases
        )
    ).scalar_one()
    if recent >= VELOCITY_COUNT:
        signals.append(("velocity", 30))
    return sum(points for _, points in signals), [name for name, _ in signals]


def authorize(
    db: Session,
    card: Card,
    *,
    merchant_name: str,
    merchant_category: str,
    merchant_country: str,
    amount: int,
    now: datetime | None = None,
) -> CardAuthorization:
    """Decide a purchase from the synthetic merchant terminal. The checks, in order: card
    status and expiry, the daily limit, funds (balance plus any arranged overdraft), then
    the fraud rules, whose score from 70 declines the purchase and blocks the card. An
    approved purchase is posted at once: card account debited, card settlement credited."""
    now = now or datetime.now(UTC)
    card = get_card(db, card.id, for_update=True)
    account = accounts.get_account(db, card.account_id, for_update=True)
    if amount <= 0:
        raise BusinessRuleViolation("The amount must be positive.")
    reason = None
    score, signals = 0, []
    if card.status != CardStatus.ACTIVE:
        reason = f"card_{card.status}"
    elif card.expires_on <= now:
        reason = "card_expired"
    elif account.status != AccountStatus.OPEN:
        reason = "account_not_open"
    else:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        spent = db.execute(
            select(func.coalesce(func.sum(CardAuthorization.amount), 0)).where(
                CardAuthorization.card_id == card.id,
                CardAuthorization.status == AuthorizationStatus.APPROVED,
                CardAuthorization.created_at >= start,
                CardAuthorization.created_at <= now,
            )
        ).scalar_one()
        if spent + amount > card.daily_limit:
            reason = "daily_limit"
        elif amount > accounts.available(db, account):
            reason = "insufficient_funds"
        else:
            score, signals = fraud_signals(
                db, card, merchant_category, merchant_country, amount, now
            )
            if score >= BLOCK_SCORE:
                reason = "fraud_suspected"
    number = db.execute(AUTHORIZATION_SEQUENCE.next_value()).scalar_one()
    auth = CardAuthorization(
        auth_code=f"AUTH-{number:08d}",
        card_id=card.id,
        merchant_name=merchant_name.strip()[:100],
        merchant_category=merchant_category,
        merchant_country=merchant_country,
        amount=amount,
        currency=card.currency,
        status=(AuthorizationStatus.DECLINED if reason else AuthorizationStatus.APPROVED).value,
        decline_reason=reason,
        fraud_score=score,
        fraud_signals=",".join(signals),
        created_at=now,
    )
    if reason is None:
        memo = f"{auth.auth_code} {auth.merchant_name}"[:200]
        entry, _ = ledger.post_entry(
            db,
            idempotency_key=f"card-auth:{auth.auth_code}",
            currency=card.currency,
            description=f"Card purchase {masked(card.card_number)} at {auth.merchant_name}",
            source="card",
            lines=[
                ledger.LineSpec(account.ledger_account_id, Direction.DEBIT, amount, memo),
                ledger.LineSpec(
                    settlement_account(db, card.currency).id, Direction.CREDIT, amount, memo
                ),
            ],
            actor_id=None,
            effective_date=now.date(),
        )
        auth.journal_entry_id = entry.id
    db.add(auth)
    db.flush()
    if reason == "fraud_suspected":
        block_card(db, card, "fraud_suspected", None, now=now)
    return auth


def find_authorization(db: Session, code: str) -> CardAuthorization | None:
    return db.execute(
        select(CardAuthorization).where(CardAuthorization.auth_code == code)
    ).scalar_one_or_none()


# --- Disputes -----------------------------------------------------------------------------------


def open_dispute(
    db: Session,
    auth: CardAuthorization,
    reason: str,
    amount: int | None,
    actor_id: uuid.UUID | None,
    *,
    now: datetime | None = None,
) -> CardDispute:
    now = now or datetime.now(UTC)
    if auth.status != AuthorizationStatus.APPROVED:
        raise BusinessRuleViolation("Only an approved purchase can be disputed.")
    if now - auth.created_at > DISPUTE_WINDOW:
        raise BusinessRuleViolation("Purchases can be disputed for 120 days.")
    amount = auth.amount if amount is None else amount
    if not 0 < amount <= auth.amount:
        raise BusinessRuleViolation("The disputed amount must be within the purchase amount.")
    live = db.execute(
        select(CardDispute.id).where(
            CardDispute.authorization_id == auth.id, CardDispute.status != DisputeStatus.REJECTED
        )
    ).first()
    if live:
        raise ConflictError("This purchase already has a dispute.")
    number = db.execute(DISPUTE_SEQUENCE.next_value()).scalar_one()
    dispute = CardDispute(
        dispute_number=f"DSP-{number:07d}",
        authorization_id=auth.id,
        reason=reason,
        amount=amount,
        status=DisputeStatus.OPEN.value,
        opened_by=actor_id,
        opened_at=now,
    )
    db.add(dispute)
    db.flush()
    record_audit_event(
        db, actor_id=actor_id, action="card_dispute.opened", entity_type="card_dispute",
        entity_id=dispute.id,
        metadata={"dispute_number": dispute.dispute_number, "auth_code": auth.auth_code,
                  "reason": reason, "amount": amount},
    )  # fmt: skip
    return dispute


def get_dispute(db: Session, dispute_id: uuid.UUID, *, for_update: bool = False) -> CardDispute:
    query = select(CardDispute).where(CardDispute.id == dispute_id)
    if for_update:
        query = query.with_for_update()
    dispute = db.execute(query).scalar_one_or_none()
    if dispute is None:
        raise NotFoundError("Dispute not found.")
    return dispute


def decide_dispute(
    db: Session,
    dispute: CardDispute,
    refund: bool,
    actor_id: uuid.UUID,
    *,
    now: datetime | None = None,
    idempotency_key: str | None = None,
) -> CardDispute:
    """Charge back (refund the disputed amount to the card's account, recovered from the
    network through card settlement) or reject. The person who opened the dispute cannot
    decide it."""
    dispute = get_dispute(db, dispute.id, for_update=True)
    if dispute.status != DisputeStatus.OPEN:
        raise ConflictError(f"The dispute is {dispute.status}.")
    if dispute.opened_by is not None and dispute.opened_by == actor_id:
        raise BusinessRuleViolation(
            "Four-eyes rule: the person who opened the dispute cannot decide it.",
            {"rule": "four_eyes"},
        )
    now = now or datetime.now(UTC)
    if refund:
        auth = db.get(CardAuthorization, dispute.authorization_id)
        card = get_card(db, auth.card_id)
        account = accounts.get_account(db, card.account_id)
        memo = f"{dispute.dispute_number} chargeback {auth.auth_code}"
        entry, _ = ledger.post_entry(
            db,
            idempotency_key=idempotency_key or f"card-chargeback:{dispute.id}",
            currency=card.currency,
            description=f"Chargeback {dispute.dispute_number} to {account.account_number}",
            source="chargeback",
            lines=[
                ledger.LineSpec(
                    settlement_account(db, card.currency).id, Direction.DEBIT, dispute.amount, memo
                ),
                ledger.LineSpec(account.ledger_account_id, Direction.CREDIT, dispute.amount, memo),
            ],
            actor_id=actor_id,
            effective_date=now.date(),
        )
        dispute.refund_entry_id = entry.id
    dispute.status = (DisputeStatus.REFUNDED if refund else DisputeStatus.REJECTED).value
    dispute.decided_by = actor_id
    dispute.decided_at = now
    db.flush()
    record_audit_event(
        db, actor_id=actor_id, action="card_dispute.decided", entity_type="card_dispute",
        entity_id=dispute.id,
        metadata={"dispute_number": dispute.dispute_number, "decision": dispute.status},
    )  # fmt: skip
    return dispute


PROFILE_WINDOW = timedelta(days=90)


def fraud_profile(db: Session, card: Card) -> dict[str, Any]:
    """What a fraud analyst looks at when a block is reviewed (Phase 32): the purchase the
    fraud rules declined most recently and the card's history before it — approved
    purchases over 90 days, their median, earlier high-risk purchases, when the card was
    first used in the declined purchase's country, and every attempt in the hour before.
    `blocked` is None when no purchase was declined for suspected fraud (a manual block)."""
    home = home_country(db, card)
    base = {"currency": card.currency, "home_country": home, "daily_limit": card.daily_limit}
    declined = db.execute(
        select(CardAuthorization)
        .where(
            CardAuthorization.card_id == card.id,
            CardAuthorization.decline_reason == "fraud_suspected",
        )
        .order_by(CardAuthorization.created_at.desc(), CardAuthorization.auth_code.desc())
        .limit(1)
    ).scalar_one_or_none()
    if declined is None:
        return {**base, "blocked": None, "purchases_90d": 0, "median_amount": 0,
                "high_risk_purchases_90d": 0, "country_first_seen_hours": None,
                "attempts_last_hour": []}  # fmt: skip
    at = declined.created_at
    earlier = db.execute(
        select(CardAuthorization)
        .where(
            CardAuthorization.card_id == card.id,
            CardAuthorization.created_at >= at - PROFILE_WINDOW,
            CardAuthorization.created_at < at,
        )
        .order_by(CardAuthorization.created_at)
    ).scalars().all()  # fmt: skip
    approved = [a for a in earlier if a.status == AuthorizationStatus.APPROVED]
    amounts = sorted(a.amount for a in approved)
    median = amounts[len(amounts) // 2] if amounts else 0
    first_seen = next(
        (a.created_at for a in approved if a.merchant_country == declined.merchant_country),
        None,
    )
    abroad = declined.merchant_country != home
    return {
        **base,
        "blocked": {
            "auth_code": declined.auth_code,
            "merchant_name": declined.merchant_name,
            "merchant_category": declined.merchant_category,
            "merchant_country": declined.merchant_country,
            "abroad": abroad,
            "amount": declined.amount,
            "fraud_score": declined.fraud_score,
            "fraud_signals": [s for s in declined.fraud_signals.split(",") if s],
        },
        "purchases_90d": len(approved),
        "median_amount": median,
        "high_risk_purchases_90d": sum(
            a.merchant_category in HIGH_RISK_CATEGORIES for a in approved
        ),
        # Hours since the card was first used (approved) in that country; None at home or
        # when never used there before.
        "country_first_seen_hours": (
            round((at - first_seen).total_seconds() / 3600, 1)
            if abroad and first_seen is not None
            else None
        ),
        "attempts_last_hour": [a.amount for a in earlier if a.created_at >= at - VELOCITY_WINDOW],
    }


def summary(db: Session) -> dict[str, Any]:
    def count(*where) -> int:
        return db.execute(select(func.count()).where(*where)).scalar_one()

    return {
        "active_cards": count(Card.status == CardStatus.ACTIVE),
        "blocked_cards": count(Card.status == CardStatus.BLOCKED),
        "authorizations": count(CardAuthorization.id.is_not(None)),
        "declined": count(CardAuthorization.status == AuthorizationStatus.DECLINED),
        "open_disputes": count(CardDispute.status == DisputeStatus.OPEN),
    }
