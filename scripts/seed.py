#!/usr/bin/env python3
"""Seed the demo bank. Equivalent to `cd backend && .venv/bin/python -m app.cli seed-demo`.

Run with the backend's Python environment, e.g.:

    backend/.venv/bin/python scripts/seed.py [--seed 2026]
"""

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)  # so backend/.env and alembic paths resolve as in normal runs

from app.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(["seed-demo", *sys.argv[1:]]))
