"""Mortgage services (Phase 33): properties, valuations, quotes, offers and completion."""

import hashlib
import math
import random
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.core.money import to_minor_units
from app.modules.accounts.models import Account, AccountStatus
from app.modules.countries.models import Country
from app.modules.customers.models import Customer, KycStatus
from app.modules.fx import rates
from app.modules.lending import service as lending
from app.modules.lending.models import Loan, LoanPurpose, LoanStatus
from app.modules.mortgages.models import (
    LIVE_OFFER_STATUSES,
    OFFER_SEQUENCE,
    PROPERTY_SEQUENCE,
    VALUATION_SEQUENCE,
    MortgageOffer,
    MortgageProduct,
    OfferStatus,
    Property,
    PropertyValuation,
    ValuationMethod,
)
from app.modules.reference import synthetic

VALUATION_VALID_DAYS = 180  # an offer needs a valuation at most this old
DESKTOP_MAX_LTV_BPS = 7500  # above this loan-to-value a surveyor must value the property
MAX_PAYMENT_TO_INCOME = 0.35  # the monthly payment against declared monthly income
INCOME_TOLERANCE = 1.5  # declared income may exceed the bureau's estimate by up to 50 %
MIN_SCORE = 620
OFFER_VALID_DAYS = 90


# --- Products --------------------------------------------------------------------------------


def get_product(db: Session, code: str) -> MortgageProduct:
    product = db.get(MortgageProduct, code)
    if product is None:
        raise NotFoundError(f"No mortgage product {code}.")
    return product


def list_products(db: Session) -> list[MortgageProduct]:
    return list(db.execute(select(MortgageProduct).order_by(MortgageProduct.max_ltv_bps)).scalars())


def _usd(amount: int | float, currency: str) -> int:
    """US dollars in minor units of `currency`, two significant figures, like the other
    converted product terms."""
    units = Decimal(str(amount)) * rates.units_per_usd(currency, rates.ANCHOR_DATE)
    whole = int(units)
    if whole >= 100:
        whole = round(whole, -(len(str(whole)) - 2))
    return to_minor_units(max(whole, 1), currency)


def loan_limits(product: MortgageProduct, currency: str) -> tuple[int, int]:
    return _usd(product.min_loan_usd, currency), _usd(product.max_loan_usd, currency)


def monthly_income_estimate(customer: Customer, currency: str) -> int:
    """The synthetic bureau's monthly income estimate (US dollars), in `currency`."""
    usd = lending.income_estimate(customer.name, customer.date_of_birth_or_incorporation)
    units = Decimal(usd) * rates.units_per_usd(currency, rates.ANCHOR_DATE)
    return to_minor_units(int(units), currency)


def find_customer(db: Session, number: str) -> Customer | None:
    return db.execute(
        select(Customer).where(Customer.customer_number == number.strip().upper())
    ).scalar_one_or_none()


# --- Properties and valuations ---------------------------------------------------------------


def register_property(
    db: Session,
    customer: Customer,
    property_type: str,
    purchase_price: int,
    actor_id: uuid.UUID | None,
) -> Property:
    if purchase_price <= 0:
        raise BusinessRuleViolation("The purchase price must be positive.")
    country = db.get(Country, customer.country_id)
    number = f"PRP-{db.execute(PROPERTY_SEQUENCE.next_value()).scalar_one():07d}"
    rng = random.Random(number)
    prop = Property(
        property_number=number,
        customer_id=customer.id,
        country_code=country.iso_country_code,
        property_type=property_type,
        address=", ".join(synthetic.address(country.address_format, rng))[:200],
        purchase_price=purchase_price,
        currency=country.default_currency,
        created_by=actor_id,
    )
    db.add(prop)
    db.flush()
    record_audit_event(
        db, actor_id=actor_id, action="property.registered", entity_type="property",
        entity_id=prop.id, metadata={"property_number": number, "purchase_price": purchase_price},
    )  # fmt: skip
    return prop


def get_property(db: Session, property_id: uuid.UUID) -> Property:
    prop = db.get(Property, property_id)
    if prop is None:
        raise NotFoundError("Property not found.")
    return prop


def find_property(db: Session, number: str) -> Property | None:
    return db.execute(
        select(Property).where(Property.property_number == number.strip().upper())
    ).scalar_one_or_none()


def desktop_value(prop: Property) -> int:
    """The synthetic automated valuation model: between 85 % and 114 % of the purchase
    price, the same every time for the same property, three significant figures."""
    digest = hashlib.sha256(f"avm|{prop.property_number}".encode()).digest()
    raw = prop.purchase_price * (85 + digest[0] % 30) // 100
    digits = len(str(raw))
    return max(round(raw, -(digits - 3)) if digits > 3 else raw, 1)


def value_property(
    db: Session,
    prop: Property,
    method: str,
    *,
    value: int | None = None,
    actor_id: uuid.UUID | None = None,
    notes: str | None = None,
    today: date | None = None,
) -> PropertyValuation:
    today = today or datetime.now(UTC).date()
    if method == ValuationMethod.DESKTOP:
        value, actor_id = desktop_value(prop), None
    else:
        if value is None or value <= 0:
            raise BusinessRuleViolation("A surveyor valuation needs a positive value.")
        if actor_id is None:
            raise BusinessRuleViolation("A surveyor valuation names the surveyor.")
    number = f"VAL-{db.execute(VALUATION_SEQUENCE.next_value()).scalar_one():07d}"
    valuation = PropertyValuation(
        valuation_number=number,
        property_id=prop.id,
        method=method,
        value=value,
        currency=prop.currency,
        valued_on=today,
        valued_by=actor_id,
        notes=notes,
    )
    db.add(valuation)
    db.flush()
    record_audit_event(
        db, actor_id=actor_id, action="property.valued", entity_type="property", entity_id=prop.id,
        metadata={"valuation_number": number, "method": method, "value": value},
    )  # fmt: skip
    return valuation


def latest_valuation(db: Session, prop: Property) -> PropertyValuation | None:
    return db.execute(
        select(PropertyValuation)
        .where(PropertyValuation.property_id == prop.id)
        .order_by(PropertyValuation.valued_on.desc(), PropertyValuation.valuation_number.desc())
        .limit(1)
    ).scalar_one_or_none()


def charged_loan(db: Session, prop: Property) -> Loan | None:
    """The live loan the property secures, if any."""
    return db.execute(
        select(Loan).where(Loan.property_id == prop.id, Loan.status == LoanStatus.ACTIVE)
    ).scalar_one_or_none()


# --- Quotes and offers -----------------------------------------------------------------------


def quote(
    db: Session,
    *,
    customer: Customer,
    prop: Property,
    product: MortgageProduct,
    account: Account,
    loan_amount: int,
    term_years: int,
    declared_monthly_income: int,
    today: date | None = None,
) -> dict[str, Any]:
    """A decision in principle: every lending rule, passed or failed, with the figures.
    Nothing is written."""
    today = today or datetime.now(UTC).date()
    checks: list[dict[str, Any]] = []

    def check(rule: str, passed: bool, detail: str) -> None:
        checks.append({"rule": rule, "passed": bool(passed), "detail": detail})

    check("kyc_verified", customer.kyc_status == KycStatus.VERIFIED,
          f"KYC status {customer.kyc_status}.")  # fmt: skip
    check("property_owner", prop.customer_id == customer.id,
          "The property is the applicant's purchase.")  # fmt: skip
    check("account", account.customer_id == customer.id and account.status == AccountStatus.OPEN
          and account.account_type in ("current", "business_current")
          and account.currency == prop.currency,
          "An open current account of the applicant in the property's currency.")  # fmt: skip
    low, high = loan_limits(product, prop.currency)
    check("loan_limits", low <= loan_amount <= high,
          f"Between {low} and {high} ({prop.currency} minor units).")  # fmt: skip
    check("term", 5 <= term_years <= product.max_term_years,
          f"5 to {product.max_term_years} years.")  # fmt: skip
    valuation = latest_valuation(db, prop)
    fresh = valuation is not None and (today - valuation.valued_on).days <= VALUATION_VALID_DAYS
    check("valuation", fresh,
          f"A valuation in the last {VALUATION_VALID_DAYS} days"
          + (f" ({valuation.valuation_number}, {valuation.valued_on})." if valuation else
             "; none yet."))  # fmt: skip
    basis = min(valuation.value, prop.purchase_price) if valuation else prop.purchase_price
    ltv_bps = math.ceil(loan_amount * 10_000 / basis) if basis else 10_000
    check("loan_to_value", ltv_bps <= product.max_ltv_bps,
          f"{ltv_bps / 100:.2f} % of the lower of valuation and price; the product allows "
          f"{product.max_ltv_bps / 100:.0f} %.")  # fmt: skip
    if valuation is not None and valuation.method == ValuationMethod.DESKTOP:
        check("valuation_method", ltv_bps <= DESKTOP_MAX_LTV_BPS,
              f"A desktop valuation supports up to {DESKTOP_MAX_LTV_BPS / 100:.0f} % "
              "loan-to-value; above that a surveyor values the property.")  # fmt: skip
    term_months = term_years * 12
    payment = lending.monthly_payment(loan_amount, product.annual_rate_bps, term_months)
    ratio = payment / declared_monthly_income if declared_monthly_income > 0 else math.inf
    check("affordability", ratio <= MAX_PAYMENT_TO_INCOME,
          f"The payment is {ratio:.0%} of declared monthly income; at most "
          f"{MAX_PAYMENT_TO_INCOME:.0%}.")  # fmt: skip
    estimate = monthly_income_estimate(customer, prop.currency)
    check("income_supported", declared_monthly_income <= estimate * INCOME_TOLERANCE,
          f"Declared income against the bureau's estimate of {estimate}.")  # fmt: skip
    bureau = lending.bureau_report(customer.name, customer.date_of_birth_or_incorporation)
    check("credit_history", bureau["score"] >= MIN_SCORE and bureau["recent_defaults"] == 0,
          f"Score {bureau['score']} (at least {MIN_SCORE}), {bureau['recent_defaults']} recent "
          "defaults.")  # fmt: skip
    live_offer = db.execute(
        select(MortgageOffer.offer_number).where(
            MortgageOffer.property_id == prop.id, MortgageOffer.status.in_(LIVE_OFFER_STATUSES)
        )
    ).scalar_one_or_none()
    check("unencumbered", live_offer is None and charged_loan(db, prop) is None,
          "No live offer or loan on the property"
          + (f" ({live_offer} is live)." if live_offer else "."))  # fmt: skip
    return {
        "eligible": all(c["passed"] for c in checks),
        "checks": checks,
        "currency": prop.currency,
        "loan_amount": loan_amount,
        "term_months": term_months,
        "annual_rate_bps": product.annual_rate_bps,
        "monthly_payment": payment,
        "ltv_bps": ltv_bps,
        "valuation_id": str(valuation.id) if valuation else None,
        "valuation_number": valuation.valuation_number if valuation else None,
        "valuation_method": valuation.method if valuation else None,
        "income_estimate": estimate,
        "credit_score": bureau["score"],
    }


def request_offer(
    db: Session,
    *,
    customer: Customer,
    prop: Property,
    product: MortgageProduct,
    account: Account,
    loan_amount: int,
    term_years: int,
    declared_monthly_income: int,
    requested_by: uuid.UUID,
    today: date | None = None,
) -> MortgageOffer:
    """A mortgage application: refused unless every rule passes; then pending, for an
    underwriter other than the requester to decide."""
    result = quote(
        db, customer=customer, prop=prop, product=product, account=account,
        loan_amount=loan_amount, term_years=term_years,
        declared_monthly_income=declared_monthly_income, today=today,
    )  # fmt: skip
    failed = [c for c in result["checks"] if not c["passed"]]
    if failed:
        raise BusinessRuleViolation(
            "The application fails: " + "; ".join(f"{c['rule']} ({c['detail']})" for c in failed),
            {"rules": [c["rule"] for c in failed]},
        )
    number = f"MOF-{db.execute(OFFER_SEQUENCE.next_value()).scalar_one():07d}"
    offer = MortgageOffer(
        offer_number=number,
        customer_id=customer.id,
        property_id=prop.id,
        valuation_id=uuid.UUID(result["valuation_id"]),
        product_code=product.product_code,
        account_id=account.id,
        loan_amount=loan_amount,
        currency=prop.currency,
        term_months=result["term_months"],
        annual_rate_bps=product.annual_rate_bps,
        monthly_payment=result["monthly_payment"],
        ltv_bps=result["ltv_bps"],
        declared_monthly_income=declared_monthly_income,
        status=OfferStatus.PENDING.value,
        requested_by=requested_by,
    )
    db.add(offer)
    db.flush()
    record_audit_event(
        db, actor_id=requested_by, action="mortgage_offer.requested", entity_type="mortgage_offer",
        entity_id=offer.id, metadata={"offer_number": number, "loan_amount": loan_amount,
                                      "ltv_bps": result["ltv_bps"]},
    )  # fmt: skip
    return offer


def get_offer(db: Session, offer_id: uuid.UUID, *, for_update: bool = False) -> MortgageOffer:
    query = select(MortgageOffer).where(MortgageOffer.id == offer_id)
    if for_update:
        query = query.with_for_update()
    offer = db.execute(query).scalar_one_or_none()
    if offer is None:
        raise NotFoundError("Mortgage offer not found.")
    return offer


def find_offer(db: Session, number: str) -> MortgageOffer | None:
    return db.execute(
        select(MortgageOffer).where(MortgageOffer.offer_number == number.strip().upper())
    ).scalar_one_or_none()


def _require(offer: MortgageOffer, *statuses: OfferStatus) -> None:
    if offer.status not in statuses:
        raise ConflictError(f"Offer {offer.offer_number} is {offer.status}.")


def expired(offer: MortgageOffer, today: date) -> bool:
    return (
        offer.status == OfferStatus.OFFERED
        and offer.expires_on is not None
        and (today > offer.expires_on)
    )


def decide_offer(
    db: Session, offer: MortgageOffer, approve: bool, actor_id: uuid.UUID,
    *, now: datetime | None = None,
) -> MortgageOffer:  # fmt: skip
    """An underwriter other than the requester approves (the offer is valid for 90 days)
    or declines."""
    now = now or datetime.now(UTC)
    _require(offer, OfferStatus.PENDING)
    if actor_id == offer.requested_by:
        raise BusinessRuleViolation(
            "Four-eyes rule: the person who took the application cannot decide it.",
            {"rule": "four_eyes"},
        )
    offer.status = (OfferStatus.OFFERED if approve else OfferStatus.DECLINED).value
    offer.decided_by, offer.decided_at = actor_id, now
    offer.expires_on = now.date() + timedelta(days=OFFER_VALID_DAYS) if approve else None
    db.flush()
    record_audit_event(
        db, actor_id=actor_id, action="mortgage_offer.decided", entity_type="mortgage_offer",
        entity_id=offer.id, metadata={"offer_number": offer.offer_number, "decision": offer.status},
    )  # fmt: skip
    return offer


def accept_offer(
    db: Session, offer: MortgageOffer, actor_id: uuid.UUID | None,
    *, now: datetime | None = None,
) -> MortgageOffer:  # fmt: skip
    now = now or datetime.now(UTC)
    _require(offer, OfferStatus.OFFERED)
    if expired(offer, now.date()):
        raise BusinessRuleViolation(f"Offer {offer.offer_number} expired on {offer.expires_on}.")
    offer.status, offer.accepted_at = OfferStatus.ACCEPTED.value, now
    db.flush()
    record_audit_event(
        db, actor_id=actor_id, action="mortgage_offer.accepted", entity_type="mortgage_offer",
        entity_id=offer.id, metadata={"offer_number": offer.offer_number},
    )  # fmt: skip
    return offer


def complete_offer(
    db: Session, offer: MortgageOffer, actor_id: uuid.UUID,
    *, workflow_execution_id: uuid.UUID | None = None, now: datetime | None = None,
) -> Loan:  # fmt: skip
    """Completion: the loan is drawn down into the applicant's account and charged on the
    property. Not by the person who took the application."""
    now = now or datetime.now(UTC)
    _require(offer, OfferStatus.ACCEPTED)
    if actor_id == offer.requested_by:
        raise BusinessRuleViolation(
            "Four-eyes rule: the person who took the application cannot complete it.",
            {"rule": "four_eyes"},
        )
    prop = get_property(db, offer.property_id)
    account = db.get(Account, offer.account_id)
    if account.status != AccountStatus.OPEN:
        raise BusinessRuleViolation(f"The drawdown account is {account.status}.")
    if charged_loan(db, prop) is not None:
        raise ConflictError(f"Property {prop.property_number} already secures a loan.")
    loan = lending.book_loan(
        db,
        customer_id=offer.customer_id,
        account_id=offer.account_id,
        principal=offer.loan_amount,
        annual_rate_bps=offer.annual_rate_bps,
        term_months=offer.term_months,
        purpose=LoanPurpose.MORTGAGE.value,
        requested_by=offer.requested_by,
        underwritten_by=offer.decided_by,
        actor_id=actor_id,
        property_id=prop.id,
        workflow_execution_id=workflow_execution_id,
        now=now,
    )
    offer.status, offer.completed_by, offer.loan_id = OfferStatus.COMPLETED.value, actor_id, loan.id
    db.flush()
    record_audit_event(
        db, actor_id=actor_id, action="mortgage_offer.completed", entity_type="mortgage_offer",
        entity_id=offer.id, metadata={"offer_number": offer.offer_number,
                                      "loan_number": loan.loan_number},
    )  # fmt: skip
    return loan


def withdraw_offer(db: Session, offer: MortgageOffer, actor_id: uuid.UUID | None) -> MortgageOffer:
    _require(offer, OfferStatus.PENDING, OfferStatus.OFFERED, OfferStatus.ACCEPTED)
    offer.status = OfferStatus.WITHDRAWN.value
    db.flush()
    record_audit_event(
        db, actor_id=actor_id, action="mortgage_offer.withdrawn", entity_type="mortgage_offer",
        entity_id=offer.id, metadata={"offer_number": offer.offer_number},
    )  # fmt: skip
    return offer


def summary(db: Session) -> dict[str, Any]:
    def count(*where) -> int:
        return db.execute(select(func.count()).where(*where)).scalar_one()

    return {
        "properties": count(Property.id.is_not(None)),
        "pending": count(MortgageOffer.status == OfferStatus.PENDING),
        "offered": count(MortgageOffer.status == OfferStatus.OFFERED),
        "accepted": count(MortgageOffer.status == OfferStatus.ACCEPTED),
        "active_mortgages": count(
            Loan.purpose == LoanPurpose.MORTGAGE, Loan.status == LoanStatus.ACTIVE
        ),
    }
