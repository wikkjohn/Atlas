"""Command-line administration for ATLAS Global Bank.

    python -m app.cli seed-demo                 # demo bank + one sign-in per role
    python -m app.cli create-user --username ops.admin --role platform_administrator \\
        --email ops.admin@example.com --display-name "Ops Admin"   # prompts for a password
    python -m app.cli simulate --profile small --seed 42          # one simulation run
    python -m app.cli service-loans --as-of 2026-12-31 --as-user admin   # loan servicing run
    python -m app.cli bench-ledger --accounts 2000 --entries 50000      # ledger benchmark
"""

import argparse
import getpass
import os
import sys

from app import models  # noqa: F401  (registers every table, as the API does)
from app.config import get_settings
from app.core.database import get_sessionmaker
from app.core.errors import DomainError
from app.core.permissions import RoleCode
from app.modules.identity.schemas import UserCreate
from app.modules.identity.service import create_user
from app.modules.workflows import catalog  # noqa: F401  (registers the workflows for the seed)
from app.seed import DEFAULT_SEED, DEMO_USERS, seed_demo

DEFAULT_DEMO_PASSWORD = "atlas-demo-password"


def _seed_demo(args: argparse.Namespace) -> int:
    settings = get_settings()
    if settings.environment in {"staging", "production"}:
        print(f"Refusing to seed demo data in the {settings.environment} environment.")
        return 2
    password = os.environ.get("ATLAS_DEMO_PASSWORD", DEFAULT_DEMO_PASSWORD)
    with get_sessionmaker()() as db, db.begin():
        report = seed_demo(db, password, seed=args.seed)
    if report.skipped_structure:
        print("Organization structure already exists; left unchanged.")
    else:
        print(
            f"Created {report.organizations} organizations and {report.employees} synthetic "
            f"employees (seed {args.seed})."
        )
    if report.users:
        print(f"Created demo users: {', '.join(report.users)}")
    if report.skipped_banking:
        print("Customers already exist (or demo users are missing); banking data unchanged.")
    else:
        print(
            f"Created {report.customers} synthetic customers, {report.accounts} accounts, "
            f"{report.pending_requests} pending account requests and "
            f"{report.journal_entries} ledger postings."
        )
    if report.skipped_workflows:
        print("Workflow executions already exist; WF-0001 demo cases unchanged.")
    else:
        print(f"Ran {report.workflow_cases} WF-0001 account-opening cases through the engine.")
    if report.skipped_payments_and_loans:
        print("Payment workflow cases already exist (or no accounts); WF-0002/3 cases unchanged.")
    else:
        print(
            f"Ran {report.payment_cases} WF-0002 payments and {report.loan_cases} WF-0003 loan "
            "applications through the engine."
        )
    if report.ai_tools:
        print(f"Registered AI tools: {', '.join(report.ai_tools)}")
    print("\nDemo sign-ins (local development only):")
    for username, _, label in DEMO_USERS:
        print(f"  {username:<12} {label}")
    shown = "ATLAS_DEMO_PASSWORD" if "ATLAS_DEMO_PASSWORD" in os.environ else password
    print(f"  password:    {shown}")
    return 0


def _create_user(args: argparse.Namespace) -> int:
    password = os.environ.get("ATLAS_NEW_USER_PASSWORD") or getpass.getpass("Password: ")
    try:
        data = UserCreate(
            username=args.username,
            email=args.email,
            display_name=args.display_name,
            password=password,
            role=RoleCode(args.role),
        )
        with get_sessionmaker()() as db, db.begin():
            user = create_user(db, data, actor_id=None)
            print(f"Created user {user.username} ({args.role}).")
    except (ValueError, DomainError) as exc:
        print(f"Could not create user: {exc}")
        return 1
    return 0


def _run_workflows(args: argparse.Namespace) -> int:
    import time

    from app.modules.workflows import engine  # noqa: F401  (registers the workflows)

    while True:
        report = engine.run_due(get_sessionmaker())
        print(
            f"Advanced {report.executions} executions: {report.steps} steps run, "
            f"{report.timers} timers applied, {report.skipped_locked} skipped (locked)."
        )
        if not args.watch:
            return 0
        time.sleep(args.interval)


def _simulate(args: argparse.Namespace) -> int:
    import json

    from sqlalchemy import select

    from app.modules.identity.models import User
    from app.simulation import runner, service
    from app.simulation.models import SimulationRun
    from app.simulation.schemas import StartSimulation

    factory = get_sessionmaker()
    try:
        body = StartSimulation(
            scenario_id=args.scenario,
            scenario_version=args.scenario_version,
            profile=args.profile,
            mode=args.mode,
            tool_id=args.tool,
            seed=args.seed,
            applications=args.applications,
            employees=args.employees,
        )
        with factory() as db, db.begin():
            actor = db.execute(
                select(User).where(User.username == args.as_user)
            ).scalar_one_or_none()
            if actor is None:
                print(f"No user '{args.as_user}'; runs are recorded against a user.")
                return 1
            run = service.start_run(db, body, actor.id)
            run_id, number = run.id, run.run_number
    except (ValueError, DomainError) as exc:
        print(f"Could not start the simulation: {exc}")
        return 1
    print(f"Simulation run #{number} started ({args.profile}, seed {args.seed}).")
    runner.execute_run(factory, run_id)
    with factory() as db:
        run = db.get(SimulationRun, run_id)
        assert run is not None
        print(f"Status: {run.status} in {(run.wall_ms or 0) / 1000:.1f}s")
        if run.failure_reason:
            print(f"Reason: {run.failure_reason}")
            return 1
        print(f"Result digest: {run.result_digest}")
        print(json.dumps(run.results, indent=2))
    return 0


def _service_loans(args: argparse.Namespace) -> int:
    import json
    from datetime import UTC, date, datetime

    from sqlalchemy import select

    from app.core.permissions import permissions_for
    from app.modules.identity.models import User
    from app.modules.identity.service import AuthenticatedUser
    from app.modules.lending import servicing

    try:
        as_of = date.fromisoformat(args.as_of) if args.as_of else datetime.now(UTC).date()
        with get_sessionmaker()() as db, db.begin():
            user = db.execute(
                select(User).where(User.username == args.as_user)
            ).scalar_one_or_none()
            if user is None or not user.is_active:
                print(f"No active user '{args.as_user}'; runs are recorded against a user.")
                return 1
            actor = AuthenticatedUser(
                id=user.id,
                username=user.username,
                role=user.role.code,
                permissions=permissions_for(user.role.code),
            )
            run = servicing.run(db, as_of, actor)
            print(f"Servicing run #{run.run_number} to {as_of.isoformat()}:")
            print(json.dumps(run.summary, indent=2))
    except (ValueError, DomainError) as exc:
        print(f"Could not run loan servicing: {exc}")
        return 1
    return 0


def _bench_ledger(args: argparse.Namespace) -> int:
    import json

    from app.modules.ledger import benchmark

    settings = get_settings()
    if settings.environment in {"staging", "production"}:
        print(f"Refusing to post benchmark entries in the {settings.environment} environment.")
        return 1
    report = benchmark.run(
        get_sessionmaker(),
        accounts=args.accounts,
        entries=args.entries,
        hot_share=args.hot_share,
        seed=args.seed,
    )
    print(json.dumps(report, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)

    seed = commands.add_parser("seed-demo", help="Create the demo bank and demo users")
    seed.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Random seed")
    seed.set_defaults(handler=_seed_demo)

    user = commands.add_parser("create-user", help="Create a user account")
    user.add_argument("--username", required=True)
    user.add_argument("--email", required=True)
    user.add_argument("--display-name", required=True)
    user.add_argument("--role", required=True, choices=[r.value for r in RoleCode])
    user.set_defaults(handler=_create_user)

    runner = commands.add_parser(
        "run-workflows", help="Resume due workflow steps and apply timeouts"
    )
    runner.add_argument("--watch", action="store_true", help="Keep running")
    runner.add_argument("--interval", type=float, default=5.0, help="Seconds between passes")
    runner.set_defaults(handler=_run_workflows)

    simulate = commands.add_parser("simulate", help="Run one simulation to completion")
    simulate.add_argument("--scenario", default="retail-onboarding")
    simulate.add_argument(
        "--profile", default="small", choices=["small", "department", "enterprise", "custom"]
    )
    simulate.add_argument("--scenario-version", type=int, help="Defaults to the latest")
    simulate.add_argument(
        "--mode", default="baseline", choices=["baseline", "ai_assisted", "ai_automated"]
    )
    simulate.add_argument(
        "--tool", help="AI tool id (AI modes), e.g. agb-intelligent-kyc-assistant"
    )
    simulate.add_argument("--seed", type=int, default=42)
    simulate.add_argument("--applications", type=int, help="Custom profile only")
    simulate.add_argument("--employees", type=int, help="Custom profile only")
    simulate.add_argument("--as-user", default="admin", help="User the run is recorded against")
    simulate.set_defaults(handler=_simulate)

    service = commands.add_parser(
        "service-loans", help="Accrue and collect loan instalments up to a business date"
    )
    service.add_argument("--as-of", help="Business date (YYYY-MM-DD); defaults to today")
    service.add_argument("--as-user", default="admin", help="User with loans:service")
    service.set_defaults(handler=_service_loans)

    bench = commands.add_parser(
        "bench-ledger", help="Post synthetic entries and time balance reads and reconciliation"
    )
    bench.add_argument("--accounts", type=int, default=2000)
    bench.add_argument("--entries", type=int, default=20000)
    bench.add_argument("--hot-share", type=float, default=0.5, help="Lines on one hot account")
    bench.add_argument("--seed", type=int, default=7)
    bench.set_defaults(handler=_bench_ledger)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
