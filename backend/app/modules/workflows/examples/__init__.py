"""Example stored workflow definitions, imported by `seed-demo` (and a template for new
ones). Each JSON file is a definition document as the import API takes it."""

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent


def documents() -> list[dict[str, Any]]:
    """Every example, in import order (by workflow id, then version)."""
    found = [json.loads(p.read_text()) for p in HERE.glob("WF-*.json")]
    return sorted(found, key=lambda d: (d["workflow_id"], d["version"]))
