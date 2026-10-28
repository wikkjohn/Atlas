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
import os
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


def fetch(
    url: str,
    timeout: float,
    *,
    body: dict[str, Any] | None = None,
    token: str | None = None,
) -> tuple[int, dict[str, str], Any]:
    headers = {"X-Correlation-ID": "validate-system"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, headers, raw = (
                response.status,
                dict(response.headers),
                response.read(),
            )
    except urllib.error.HTTPError as exc:
        status, headers, raw = exc.code, dict(exc.headers), exc.read()
    try:
        body: Any = json.loads(raw)
    except ValueError:
        body = raw.decode("utf-8", errors="replace")
    return status, headers, body


def ledger_checks(
    api: str, username: str, password: str, timeout: float
) -> list[Check]:
    """Sign in and run the ledger reconciliation (needs a role with ledger:read)."""
    status, _, login = fetch(
        f"{api}/api/v1/auth/login",
        timeout,
        body={"username": username, "password": password},
    )
    if status != 200:
        return [Check("Sign-in", False, f"login as {username} answered HTTP {status}")]
    checks = [
        Check("Sign-in", True, f"signed in as {username} ({login['user']['role']})")
    ]
    status, _, report = fetch(
        f"{api}/api/v1/ledger/reconciliation",
        timeout,
        body={},
        token=login["access_token"],
    )
    if status != 200:
        checks.append(Check("Ledger reconciliation", False, f"HTTP {status}: {report}"))
        return checks
    failed = [c["name"] for c in report["checks"] if not c["passed"]]
    checks.append(
        Check(
            "Ledger reconciliation",
            report["ok"],
            f"{report['entries_checked']} entries, {report['lines_checked']} lines; "
            + (f"failed: {', '.join(failed)}" if failed else "all checks passed"),
        )
    )
    checks.append(simulation_check(api, login["access_token"], timeout))
    checks.append(experiment_check(api, login["access_token"], timeout))
    return checks


def experiment_check(api: str, token: str, timeout: float) -> Check:
    """Every evaluated experiment re-evaluates to the same digest from its raw measurements."""
    status, _, page = fetch(
        f"{api}/api/v1/experiments?status=completed&limit=20", timeout, token=token
    )
    if status != 200:
        return Check("Experiment reproducibility", False, f"HTTP {status}: {page}")
    mismatched = []
    for item in page["items"]:
        status, _, result = fetch(
            f"{api}/api/v1/experiments/{item['id']}/re-evaluate",
            timeout,
            body={},
            token=token,
        )
        if status != 200 or not result.get("matches"):
            mismatched.append(f"#{item['experiment_number']}")
    return Check(
        "Experiment reproducibility",
        not mismatched,
        f"{len(page['items'])} evaluated experiment(s) re-evaluated; "
        + (f"differing: {', '.join(mismatched)}" if mismatched else "all identical"),
    )


def simulation_check(api: str, token: str, timeout: float) -> Check:
    """Completed runs with the same scenario, seed, configuration and software must match."""
    status, _, runs = fetch(f"{api}/api/v1/simulations?limit=200", timeout, token=token)
    if status != 200:
        return Check("Simulation reproducibility", False, f"HTTP {status}: {runs}")
    groups: dict[tuple, set[str]] = {}
    for run in runs["items"]:
        if run["status"] == "completed":
            key = (
                run["scenario_id"],
                run["scenario_version"],
                run["seed"],
                run["config_hash"],
                run["software_version"],
            )
            groups.setdefault(key, set()).add(run["result_digest"])
    repeated = [digests for digests in groups.values() if digests]
    differing = sum(1 for digests in repeated if len(digests) > 1)
    completed = sum(1 for run in runs["items"] if run["status"] == "completed")
    return Check(
        "Simulation reproducibility",
        differing == 0,
        f"{runs['total']} runs, {completed} completed; "
        + (
            f"{differing} configuration(s) produced different results"
            if differing
            else "every repeated configuration produced identical results"
        ),
    )


def run_checks(api: str, frontend: str | None, timeout: float) -> list[Check]:
    checks: list[Check] = []

    try:
        status, headers, health = fetch(f"{api}/api/health", timeout)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return [Check("API reachable", False, f"{api} did not respond: {exc}")]
    checks.append(
        Check("API reachable", True, f"{api}/api/health answered HTTP {status}")
    )

    db = (
        health.get("components", {}).get("database", {})
        if isinstance(health, dict)
        else {}
    )
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
            f"latency {db.get('latency_ms')} ms"
            if db.get("status") == "ok"
            else str(db),
        )
    )
    checks.append(
        Check(
            "Correlation ID propagated",
            headers.get("x-correlation-id", headers.get("X-Correlation-ID"))
            == "validate-system",
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

    # Business data must never be served to anonymous callers.
    status, _, _ = fetch(f"{api}/api/v1/employees", timeout)
    checks.append(
        Check(
            "Business API requires authentication",
            status == 401,
            f"anonymous GET /api/v1/employees answered HTTP {status}",
        )
    )

    if frontend:
        try:
            status, _, page = fetch(frontend, timeout)
            ok = status == 200 and isinstance(page, str) and 'id="root"' in page
            checks.append(
                Check("Frontend serving", ok, f"{frontend} answered HTTP {status}")
            )
            status, _, proxied = fetch(f"{frontend}/api/health", timeout)
            checks.append(
                Check(
                    "Frontend reaches API",
                    status == 200 and isinstance(proxied, dict),
                    f"{frontend}/api/health answered HTTP {status}",
                )
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            checks.append(
                Check("Frontend serving", False, f"{frontend} did not respond: {exc}")
            )

    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--frontend", default="http://localhost:5173")
    parser.add_argument("--skip-frontend", action="store_true")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument(
        "--login",
        metavar="USERNAME",
        help="Also sign in (password from ATLAS_DEMO_PASSWORD) and reconcile the ledger, "
        "e.g. --login auditor",
    )
    args = parser.parse_args()

    checks = run_checks(
        args.api.rstrip("/"),
        None if args.skip_frontend else args.frontend.rstrip("/"),
        args.timeout,
    )
    if args.login:
        password = os.environ.get("ATLAS_DEMO_PASSWORD", "atlas-demo-password")
        checks += ledger_checks(
            args.api.rstrip("/"), args.login, password, args.timeout
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
