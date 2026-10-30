"""Synthetic sanctions screening shared by workflows and the handler library."""

# Fictional names used to exercise sanctions screening. Not real people or entities.
SYNTHETIC_WATCHLIST = frozenset(
    {"darius vantablack", "morgana ledgerworth", "silas offshore", "vera shellcompany"}
)
WATCHLIST_NAME = "synthetic-watchlist-v1"


def normalize(name: str) -> str:
    return " ".join(name.casefold().split())


def screen_name(name: str) -> dict[str, object]:
    """Exact match of the normalised name against the synthetic watchlist."""
    normalized = normalize(name)
    hit = normalized in SYNTHETIC_WATCHLIST
    return {"hit": hit, "matched": normalized if hit else None, "list": WATCHLIST_NAME}
