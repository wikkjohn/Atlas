"""Example stored workflow definitions and templates, imported by `seed-demo` (and
starting points for new ones). `WF-*.json` are definition documents and `TPL-*.json`
templates, each as the import API takes it."""

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent


def documents() -> list[dict[str, Any]]:
    """Every example definition, in import order (by workflow id, then version)."""
    found = [json.loads(p.read_text()) for p in HERE.glob("WF-*.json")]
    return sorted(found, key=lambda d: (d["workflow_id"], d["version"]))


def templates() -> list[dict[str, Any]]:
    """Every example template (Phase 19), in import order."""
    found = [json.loads(p.read_text()) for p in HERE.glob("TPL-*.json")]
    return sorted(found, key=lambda d: (d["template_id"], d["version"]))


# The variants `seed-demo` generates: one paper-statement workflow per country of the demo
# bank and per retail product.
DEMO_GENERATION = {
    "template_id": "TPL-PAPER-STATEMENT",
    "grid": {
        "country_code": ["DE", "GB", "JP", "SG", "US"],
        "account_type": ["current", "savings"],
    },
    "fixed": {"fee": 5, "approval_permission": "accounts:manage", "screen_customers": True},
}
