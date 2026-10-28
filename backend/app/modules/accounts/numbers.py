"""Synthetic account numbers: country code, ten digits and two ISO 7064 MOD 97-10 check
digits (the scheme IBANs use), e.g. "US000000004257". They are not real IBANs."""

import re

_FORMAT = re.compile(r"^([A-Z]{2})(\d{10})(\d{2})$")


def _letters_to_digits(value: str) -> str:
    return "".join(str(ord(ch) - 55) if ch.isalpha() else ch for ch in value)


def check_digits(country_code: str, serial: str) -> str:
    remainder = int(_letters_to_digits(f"{serial}{country_code}") + "00") % 97
    return f"{98 - remainder:02d}"


def make_account_number(country_code: str, sequence_value: int) -> str:
    serial = f"{sequence_value:010d}"
    return f"{country_code}{serial}{check_digits(country_code, serial)}"


def is_valid_account_number(value: str) -> bool:
    match = _FORMAT.match(value)
    if not match:
        return False
    country, serial, check = match.groups()
    return int(_letters_to_digits(f"{serial}{country}") + check) % 97 == 1
