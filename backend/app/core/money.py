"""Currency minor units (ISO 4217 exponents).

All amounts are stored as integers in the currency's minor unit (cents, pence, yen …).
"""

# Currencies whose minor unit differs from the common two decimal places.
_EXPONENT_OVERRIDES = {
    "JPY": 0,
    "KRW": 0,
    "CLP": 0,
    "ISK": 0,
    "VND": 0,
    "BHD": 3,
    "KWD": 3,
    "OMR": 3,
    "JOD": 3,
    "TND": 3,
}


def minor_unit_exponent(currency: str) -> int:
    return _EXPONENT_OVERRIDES.get(currency.upper(), 2)


def to_minor_units(major_amount: int, currency: str) -> int:
    """Convert a whole-number major amount (e.g. 85000 USD) to minor units."""
    return major_amount * 10 ** minor_unit_exponent(currency)
