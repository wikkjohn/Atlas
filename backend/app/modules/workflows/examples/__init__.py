"""Example stored workflow definitions, imported by `seed-demo` (and a template for new
ones). Each JSON file is a definition document as the import API takes it."""

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent


def documents() -> list[dict[str, Any]]:
    return [json.loads(p.read_text()) for p in sorted(HERE.glob("WF-*.json"))]
