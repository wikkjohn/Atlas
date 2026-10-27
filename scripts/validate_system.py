#!/usr/bin/env python3
"""Validate a running ATLAS Global Bank stack.

Calls the live API (and optionally the frontend) and checks that every Phase 1 platform
guarantee holds. Uses only the Python standard library so it runs anywhere.

    python3 scripts/validate_system.py
    python3 scripts/validate_system.py --api http://localhost:8000 --frontend http://localhost:5173

Exits with status 0 when every check passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


def fetch(url: str, timeout: float) -> tuple[int, dict[str, str], Any]:
    request = urllib.request.Request(url, headers={"X-Correlation-ID": "validate-system"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, headers, raw = response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        status, headers, raw = exc.code, dict(exc.headers), exc.read()
    try:
        body: Any = json.loads(raw)
    except ValueError:
        body = raw.decode("utf-8", errors="replace")
    return status, headers, body


def run_checks(api: str, frontend: str | None, timeout: float) -> list[Check]:
    checks: list[Check] = []

    try:
        status, headers, health = fetch(f"{api}/api/health", timeout)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return [Check("API reachable", False, f"{api} did not respond: {exc}")]
    checks.append(Check("API reachable", True, f"{api}/api/health answered HTTP {status}"))

    db = health.get("components", {}).get("database", {}) if isinstance(health, dict) else {}
    checks.append(
        Check(
            "Health endpoint reports healthy",
            status == 200 and health.get("status") in {"ok", "degraded"},
            f"HTTP {status}, status={health.get('status') if isinstance(health, dict) else '?'}",
        )
    )
    checks.append(
        Check(
            "Database connected",
            db.get("status") == "ok",
            f"latency {db.get('latency_ms')} ms" if db.get("status") == "ok" else str(db),
        )
    )
    checks.append(
        Check(
            "Correlation ID propagated",
            headers.get("x-correlation-id", headers.get("X-Correlation-ID")) == "validate-system",
            "X-Correlation-ID echoed back",
        )
    )

    status, _, system_status = fetch(f"{api}/api/system/status", timeout)
    migrations = (system_status.get("database") or {}).get("migrations") or {}
    checks.append(
        Check(
            "Migrations applied",
            status == 200 and migrations.get("up_to_date") is True,
            f"current={migrations.get('current_revisions')} head={migrations.get('head_revisions')}",
        )
    )

    status, _, info = fetch(f"{api}/api/system/info", timeout)
    modules = info.get("modules", []) if isinstance(info, dict) else []
    checks.append(
        Check(
            "System info available",
            status == 200 and any(m.get("key") == "platform" for m in modules),
            f"{info.get('name')} v{info.get('version')}, {len(modules)} modules registered"
            if isinstance(info, dict)
            else f"HTTP {status}",
        )
    )

    status, _, openapi = fetch(f"{api}/api/openapi.json", timeout)
    paths = set(openapi.get("paths", {})) if isinstance(openapi, dict) else set()
    required = {"/api/health", "/api/system/info", "/api/system/status"}
    checks.append(
        Check(
            "OpenAPI documents endpoints",
            required <= paths,
            f"{len(paths)} paths documented; missing {sorted(required - paths) or 'none'}",
        )
    )

    if frontend:
        try:
            status, _, page = fetch(frontend, timeout)
            ok = status == 200 and isinstance(page, str) and 'id="root"' in page
            checks.append(Check("Frontend serving", ok, f"{frontend} answered HTTP {status}"))
            status, _, proxied = fetch(f"{frontend}/api/health", timeout)
            checks.append(
                Check(
                    "Frontend reaches API",
                    status == 200 and isinstance(proxied, dict),
                    f"{frontend}/api/health answered HTTP {status}",
                )
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            checks.append(Check("Frontend serving", False, f"{frontend} did not respond: {exc}"))

    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--frontend", default="http://localhost:5173")
    parser.add_argument("--skip-frontend", action="store_true")
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()

    checks = run_checks(
        args.api.rstrip("/"),
        None if args.skip_frontend else args.frontend.rstrip("/"),
        args.timeout,
    )
    width = max(len(c.name) for c in checks)
    for check in checks:
        mark = "PASS" if check.passed else "FAIL"
        print(f"[{mark}] {check.name:<{width}}  {check.detail}")
    failed = [c for c in checks if not c.passed]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
