"""Currency minor units (ISO 4217 exponents).

All amounts are stored as integers in the currency's minor unit (cents, pence, yen …).
"""

from app.modules.reference.data import CURRENCIES


def minor_unit_exponent(currency: str) -> int:
    """Decimal places of a currency, from the reference data (Phase 23); a currency it does
    not know keeps the common two."""
    found = CURRENCIES.get(currency.upper())
    return found[1] if found else 2


def to_minor_units(major_amount: int, currency: str) -> int:
    """Convert a whole-number major amount (e.g. 85000 USD) to minor units."""
    return major_amount * 10 ** minor_unit_exponent(currency)
