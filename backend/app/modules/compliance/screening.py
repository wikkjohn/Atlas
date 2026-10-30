"""Synthetic sanctions screening shared by workflows and the handler library.

Since Phase 25 there are several synthetic lists, and each country's rules say which apply
(see `app.modules.rules`). Every name on them is fictional: no real people or entities.
"""

# The original list, still the default and part of every country's rules.
WATCHLIST_NAME = "synthetic-watchlist-v1"
SYNTHETIC_WATCHLIST = frozenset(
    {"darius vantablack", "morgana ledgerworth", "silas offshore", "vera shellcompany"}
)

# id -> (description, names). Fictional names only.
SANCTIONS_LISTS: dict[str, tuple[str, frozenset[str]]] = {
    WATCHLIST_NAME: ("Global synthetic watchlist", SYNTHETIC_WATCHLIST),
    "synthetic-eu-v1": (
        "Synthetic list in the style of an EU consolidated list",
        frozenset({"bruno ghostfund", "lena nominee", "otto shellberg"}),
    ),
    "synthetic-uk-v1": (
        "Synthetic list in the style of a UK consolidated list",
        frozenset({"harriet holdco", "percival proxy"}),
    ),
    "synthetic-us-v1": (
        "Synthetic list in the style of a US specially designated list",
        frozenset({"cyrus frontcorp", "dolores dummyco", "wade walletmix"}),
    ),
    "synthetic-un-v1": (
        "Synthetic list in the style of a UN security council list",
        frozenset({"ivan ironvault", "tariq tumbler"}),
    ),
}


def normalize(name: str) -> str:
    return " ".join(name.casefold().split())


def screen_name(name: str, lists: list[str] | None = None) -> dict[str, object]:
    """Exact match of the normalised name against the given lists (default: the global
    synthetic watchlist). `list` names the list that matched, else the first checked."""
    checked = lists or [WATCHLIST_NAME]
    normalized = normalize(name)
    matched_list = next(
        (list_id for list_id in checked if normalized in SANCTIONS_LISTS[list_id][1]), None
    )
    return {
        "hit": matched_list is not None,
        "matched": normalized if matched_list else None,
        "list": matched_list or checked[0],
        "lists": checked,
    }


def on_any_list(name: str, lists: list[str] | None = None) -> bool:
    return bool(screen_name(name, lists)["hit"])
