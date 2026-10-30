"""Masks for document numbers and postal codes: `9` a digit, `A` an upper-case letter,
`X` either; any other character stands for itself. A format is a list of masks, any of
which may match ("A9 9AA" or "AA9 9AA" for a UK postcode).

Masks are deliberately simpler than the real rules (check digits, allowed letters): they
fix length and character classes, enough to validate input shape and to generate
plausible synthetic values deterministically from a seeded random generator.
"""

import random
import re
import string

_CLASSES = {"9": "[0-9]", "A": "[A-Z]", "X": "[0-9A-Z]"}
_ALPHABETS = {
    "9": string.digits,
    "A": string.ascii_uppercase,
    "X": string.digits + string.ascii_uppercase,
}


def pattern(mask: str) -> str:
    """The regular expression a mask stands for."""
    return "".join(_CLASSES.get(c, re.escape(c)) for c in mask)


def matches(masks: list[str], value: str) -> bool:
    return any(re.fullmatch(pattern(m), value) for m in masks)


def generate(mask: str, rng: random.Random) -> str:
    return "".join(rng.choice(_ALPHABETS[c]) if c in _ALPHABETS else c for c in mask)


def example(mask: str) -> str:
    """A fixed, readable example of a mask (digits count up, letters run A, B, C …)."""
    out, digit, letter = [], 1, 0
    for c in mask:
        if c in ("9", "X"):
            out.append(str(digit % 10))
            digit += 1
        elif c == "A":
            out.append(string.ascii_uppercase[letter % 26])
            letter += 1
        else:
            out.append(c)
    return "".join(out)
