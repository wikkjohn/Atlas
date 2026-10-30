"""Synthetic exchange rates (Phase 24): units of each currency per US dollar.

Each floating currency follows its own deterministic random walk from an anchor level on
2026-01-01 (seeded by currency and day, so any date always gives the same rate, in any
process); pegged currencies follow their anchor currency at a fixed factor. The anchor
levels are rounded approximations chosen for the simulation, not market data.
"""

import hashlib
import math
import random
from datetime import date
from decimal import Decimal

ANCHOR_DATE = date(2026, 1, 1)
BASE = "USD"
RATE_PLACES = Decimal("0.0000000001")  # stored with 10 decimal places

# Floating currencies: units per USD at the anchor date, and daily volatility (a fraction).
FLOATING: dict[str, tuple[float, float]] = {
    "ALL": (92.0, 0.005), "ARS": (1450.0, 0.012), "AUD": (1.53, 0.006),
    "BDT": (122.0, 0.003), "BWP": (13.5, 0.005), "BOB": (6.91, 0.001), "BRL": (5.4, 0.009),
    "CAD": (1.38, 0.004),
    "CHF": (0.80, 0.005), "CLP": (940.0, 0.008), "CNY": (7.1, 0.002), "COP": (4000.0, 0.008),
    "CRC": (500.0, 0.004), "CZK": (21.0, 0.005), "DOP": (63.0, 0.003), "DZD": (131.0, 0.003),
    "EGP": (48.0, 0.006), "ETB": (140.0, 0.006), "EUR": (0.86, 0.005), "FJD": (2.25, 0.004),
    "GBP": (0.75, 0.005), "GEL": (2.7, 0.004), "GHS": (11.0, 0.008), "GTQ": (7.67, 0.001),
    "HNL": (26.2, 0.002), "HUF": (335.0, 0.007), "IDR": (16600.0, 0.004), "ILS": (3.3, 0.006),
    "INR": (89.0, 0.003), "ISK": (125.0, 0.006), "JMD": (160.0, 0.003), "JPY": (155.0, 0.006),
    "KES": (129.0, 0.003), "KHR": (4020.0, 0.001), "KRW": (1450.0, 0.005),
    "KWD": (0.307, 0.001), "KZT": (515.0, 0.006), "LAK": (21700.0, 0.004), "LBP": (89500.0, 0.0005),
    "LKR": (300.0, 0.004), "MAD": (9.2, 0.004), "MDL": (17.0, 0.004), "MNT": (3580.0, 0.003),
    "MUR": (46.0, 0.004), "MVR": (15.42, 0.0005), "MXN": (18.3, 0.008), "MYR": (4.15, 0.004),
    "NGN": (1450.0, 0.010), "NOK": (10.1, 0.006), "NZD": (1.74, 0.006), "PEN": (3.38, 0.004),
    "PGK": (4.2, 0.002), "PHP": (59.0, 0.004), "PKR": (281.0, 0.003), "PLN": (3.65, 0.006),
    "PYG": (7000.0, 0.004), "RON": (4.38, 0.004), "RSD": (101.0, 0.003), "RWF": (1450.0, 0.003),
    "SEK": (9.4, 0.006), "SGD": (1.29, 0.003), "THB": (31.5, 0.005), "TRY": (43.0, 0.007),
    "TND": (2.95, 0.004), "TTD": (6.78, 0.001), "TWD": (31.0, 0.004), "TZS": (2450.0, 0.004),
    "UAH": (42.0, 0.005),
    "UGX": (3600.0, 0.004), "UYU": (39.5, 0.006), "UZS": (12000.0, 0.004),
    "VES": (300.0, 0.015), "VND": (26300.0, 0.002), "ZAR": (17.2, 0.009), "ZMW": (23.0, 0.009),
}  # fmt: skip

# Pegged currencies: (anchor currency, units per unit of the anchor currency).
PEGS: dict[str, tuple[str, float]] = {
    "AED": ("USD", 3.6725), "SAR": ("USD", 3.75), "QAR": ("USD", 3.64), "BHD": ("USD", 0.376),
    "OMR": ("USD", 0.3845), "JOD": ("USD", 0.709), "BSD": ("USD", 1.0), "HKD": ("USD", 7.78),
    "MOP": ("HKD", 1.03), "BND": ("SGD", 1.0), "NAD": ("ZAR", 1.0), "BAM": ("EUR", 1.95583),
    "XOF": ("EUR", 655.957), "XAF": ("EUR", 655.957), "DKK": ("EUR", 7.4604),
    "MKD": ("EUR", 61.5), "NPR": ("INR", 1.6),
}  # fmt: skip

_PATHS: dict[str, dict[int, float]] = {}  # currency -> {day offset: log level}


def _shock(currency: str, offset: int) -> float:
    seed = hashlib.sha256(f"fx:{currency}:{offset}".encode()).digest()
    return random.Random(seed).gauss(0.0, 1.0)


def _log_level(currency: str, offset: int) -> float:
    anchor, vol = FLOATING[currency]
    path = _PATHS.setdefault(currency, {0: math.log(anchor)})
    if offset not in path:
        step = 1 if offset > 0 else -1
        known = max(k for k in path if k * step <= offset * step and k * step >= 0)
        level = path[known]
        for day in range(known + step, offset + step, step):
            # Moving forward adds the day's shock; moving back removes the next day's.
            level += vol * (_shock(currency, day) if step > 0 else -_shock(currency, day + 1))
            path[day] = level
    return path[offset]


def supported(currency: str) -> bool:
    return currency == BASE or currency in FLOATING or currency in PEGS


def units_per_usd(currency: str, day: date) -> Decimal:
    """Units of `currency` per US dollar on `day` (deterministic)."""
    if currency == BASE:
        return Decimal(1)
    if currency in PEGS:
        anchor, factor = PEGS[currency]
        return (units_per_usd(anchor, day) * Decimal(str(factor))).quantize(RATE_PLACES)
    if currency not in FLOATING:
        raise KeyError(currency)
    level = _log_level(currency, (day - ANCHOR_DATE).days)
    return Decimal(repr(math.exp(level))).quantize(RATE_PLACES)
