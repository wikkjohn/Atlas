"""Synthetic identity-document numbers, postal codes and addresses that follow a country's
reference formats. Deterministic for a given random generator, so simulations repeat."""

import random
from typing import Any

from app.modules.reference import masks

STREETS = ["Synthetic Street", "Sample Road", "Example Avenue", "Model Lane", "Fixture Way"]
CITIES = ["Testville", "Sampleton", "Mockford", "Exampleburg", "Demoport"]
REGIONS = ["North Province", "East Region", "West State", "South County"]


def document_number(documents: list[dict[str, Any]], kind: str, rng: random.Random) -> str | None:
    found = next((d for d in documents if d["type"] == kind), None)
    return masks.generate(found["mask"], rng) if found else None


def postal_code(address_format: dict[str, Any] | None, rng: random.Random) -> str | None:
    found = (address_format or {}).get("postal_code_masks") or []
    return masks.generate(rng.choice(found), rng) if found else None


def format_address(address_format: dict[str, Any] | None, **parts: str | None) -> list[str]:
    """The address as its country writes it, one line per entry, blank parts left out."""
    lines = (address_format or {}).get("lines") or ["{street}", "{city}"]
    values = {k: v or "" for k, v in parts.items()}
    out = [" ".join(line.format_map(_Blank(values)).split()).strip(" ,") for line in lines]
    return [line for line in out if line]


def address(
    address_format: dict[str, Any] | None, rng: random.Random, postal: str | None = None
) -> list[str]:
    return format_address(
        address_format,
        street=f"{rng.randint(1, 250)} {rng.choice(STREETS)}",
        city=rng.choice(CITIES),
        region=rng.choice(REGIONS),
        postal_code=postal if postal is not None else postal_code(address_format, rng),
    )


class _Blank(dict):
    def __missing__(self, key: str) -> str:
        return ""
