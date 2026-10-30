"""Default rules for each country of the reference data (version 1 of its rules).

Compiled for the simulation, not legal advice: the minimum age is the age of majority as
best known, identity documents are those the reference data lists, every country screens
against the global synthetic list plus one regional synthetic list, and payment thresholds
are the US-dollar-equivalent of $10,000 (high value) and $1,000,000 (single-payment limit)
at the synthetic FX anchor rates, rounded to two significant figures. The five operating
countries keep the limits they had before Phase 25 (10,000 and 1,000,000 units of their
currency), so earlier simulation runs reproduce exactly.
"""

from datetime import date
from decimal import Decimal
from typing import Any

from app.modules.compliance.screening import WATCHLIST_NAME
from app.modules.fx import rates
from app.modules.reference.data import CountryData

EFFECTIVE_FROM = date(2026, 1, 1)
DEFAULT_CUTOFF = "16:00"
OPERATING = {"US", "GB", "DE", "SG", "JP"}  # limits kept as configured before Phase 25

MIN_AGE = {"KR": 19, "AE": 21, "BH": 21, "KW": 21, "EG": 21, "CM": 21, "CI": 21}
CUTOFF = {"JP": "15:00", "GB": "17:30", "US": "17:00", "SG": "15:30", "AU": "16:30"}
EU = frozenset(
    "AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split()
)


def _list_for(code: str) -> str:
    if code in EU:
        return "synthetic-eu-v1"
    return {"GB": "synthetic-uk-v1", "US": "synthetic-us-v1"}.get(code, "synthetic-un-v1")


def _two_figures(value: Decimal) -> int:
    whole = int(value)
    if whole < 100:
        return max(whole, 1)
    digits = len(str(whole)) - 2
    return round(whole, -digits)


def _usd_equivalent(usd: int, currency: str) -> int:
    return _two_figures(Decimal(usd) * rates.units_per_usd(currency, rates.ANCHOR_DATE))


def default_rules(country: CountryData) -> dict[str, Any]:
    if country.code in OPERATING:
        high, limit = 10_000, 1_000_000
    else:
        high = _usd_equivalent(10_000, country.currency)
        limit = _usd_equivalent(1_000_000, country.currency)
    return {
        "kyc": {
            "min_age": MIN_AGE.get(country.code, 18),
            "identity_documents": (
                ["passport", "national_id"] if country.national_id else ["passport"]
            ),
            "proof_of_address": True,
        },
        "screening": {"lists": [WATCHLIST_NAME, _list_for(country.code)]},
        "payments": {
            "cutoff": CUTOFF.get(country.code, DEFAULT_CUTOFF),
            "high_value_major": high,
            "max_payment_major": limit,
        },
    }


def generic_rules(currency: str) -> dict[str, Any]:
    """For a country outside the reference data (added by an operator)."""
    supported = rates.supported(currency)
    return {
        "kyc": {"min_age": 18, "identity_documents": ["passport"], "proof_of_address": True},
        "screening": {"lists": [WATCHLIST_NAME, "synthetic-un-v1"]},
        "payments": {
            "cutoff": DEFAULT_CUTOFF,
            "high_value_major": _usd_equivalent(10_000, currency) if supported else 10_000,
            "max_payment_major": _usd_equivalent(1_000_000, currency) if supported else 1_000_000,
        },
    }
