"""Command-line administration for ATLAS Global Bank.

    python -m app.cli seed-demo                 # demo bank + one sign-in per role
    python -m app.cli create-user --username ops.admin --role platform_administrator \\
        --email ops.admin@example.com --display-name "Ops Admin"   # prompts for a password
"""

import argparse
import getpass
import os
import sys

from app.config import get_settings
from app.core.database import get_sessionmaker
from app.core.errors import DomainError
from app.core.permissions import RoleCode
from app.modules.identity.schemas import UserCreate
from app.modules.identity.service import create_user
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

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
