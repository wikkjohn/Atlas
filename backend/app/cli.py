"""Command-line administration for ATLAS Global Bank.

    python -m app.cli seed-demo                 # demo bank + one sign-in per role
    python -m app.cli create-user --username ops.admin --role platform_administrator \\
        --email ops.admin@example.com --display-name "Ops Admin"   # prompts for a password
    python -m app.cli simulate --profile small --seed 42          # one simulation run
    python -m app.cli service-loans --as-of 2026-12-31 --as-user admin   # loan servicing run
    python -m app.cli bench-ledger --accounts 2000 --entries 50000      # ledger benchmark
    python -m app.cli load-population --customers 100000 --seed 2026    # bulk customers
    python -m app.cli worker --processes 2                              # background jobs
    python -m app.cli simulation-history archive --older-than-days 30   # archive old runs
    python -m app.cli simulation-history reset --archive --yes          # clear sim history
    python -m app.cli simulate --profile large --shards 8               # 100k cases, parallel
    python -m app.cli perf --quick                                      # performance suite
    python -m app.cli workflows validate my-workflow.json               # check a definition
    python -m app.cli workflows import my-workflow.json --as-user admin # store a definition
    python -m app.cli workflows export WF-1001 --output wf-1001.json    # any definition
    python -m app.cli workflows import-template my-template.json        # store a template
    python -m app.cli workflows generate TPL-PAPER-STATEMENT --grid grid.json  # variants
"""

import argparse
import getpass
import json
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
    if report.stored_definitions:
        print(f"Imported stored workflow definitions: {', '.join(report.stored_definitions)}")
    if report.templates:
        print(f"Imported workflow templates: {', '.join(report.templates)}")
    if report.generated_variants:
        print(f"Generated {report.generated_variants} workflow variant(s) from templates.")
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
            shards=args.shards,
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
    shard_jobs = runner.execute_run(factory, run_id)
    if shard_jobs:
        processes = max(1, min(args.processes or len(shard_jobs), len(shard_jobs)))
        print(f"{len(shard_jobs)} shards queued; running them in {processes} worker process(es).")
        _run_workers(processes)
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
        bulk=args.bulk,
    )
    print(json.dumps(report, indent=2))
    return 0


def _load_population(args: argparse.Namespace) -> int:
    import json

    from app.simulation.population import PopulationError, load

    settings = get_settings()
    if settings.environment in {"staging", "production"}:
        print(f"Refusing to load a synthetic population in the {settings.environment} environment.")
        return 1
    try:
        report = load(
            get_sessionmaker(),
            customers=args.customers,
            seed=args.seed,
            batch=args.batch,
            progress=lambda done, seconds: print(
                f"  {done:,} customers in {seconds:.1f}s", flush=True
            ),
        )
    except PopulationError as exc:
        print(f"Could not load the population: {exc}")
        return 1
    print(json.dumps(report.as_dict(), indent=2))
    return 0


def _worker_process(index: int, schedules: bool, drain: bool) -> None:
    """One worker process: runs jobs until SIGTERM / Ctrl-C (or, with drain, until idle)."""
    import signal
    import threading

    from app.core.database import get_engine
    from app.jobs import engine, handlers  # noqa: F401  (registers the job kinds)
    from app.observability.slow_queries import SLOW_QUERIES

    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    SLOW_QUERIES.install(
        get_engine(), source=f"worker:{os.getpid()}", threshold_ms=get_settings().slow_query_ms
    )
    stats = engine.run_worker(
        get_sessionmaker(), stop=stop, schedules=schedules and index == 0, idle_exit=drain
    )
    SLOW_QUERIES.stop(get_engine())  # write what is still queued
    print(
        f"Worker {stats.worker}: {stats.succeeded} succeeded, {stats.failed} failed, "
        f"{stats.retried} retried, {stats.recovered} recovered, {stats.scheduled} scheduled.",
        flush=True,
    )


def _run_workers(processes: int) -> None:
    """Drain the job queue with worker processes (no schedules), then return."""
    import multiprocessing

    context = multiprocessing.get_context("spawn")
    workers = [
        context.Process(target=_worker_process, args=(i, False, True)) for i in range(processes)
    ]
    for process in workers:
        process.start()
    for process in workers:
        process.join()


def _worker(args: argparse.Namespace) -> int:
    import multiprocessing
    import signal

    if args.processes == 1:
        _worker_process(0, not args.no_schedules, args.drain)
        return 0
    context = multiprocessing.get_context("spawn")
    processes = [
        context.Process(target=_worker_process, args=(i, not args.no_schedules, args.drain))
        for i in range(args.processes)
    ]
    for process in processes:
        process.start()
    # SIGTERM (docker stop) reaches only this parent: pass it on, so every worker finishes
    # its current job and stops instead of being killed mid-job.
    signal.signal(signal.SIGTERM, lambda *_: [p.terminate() for p in processes if p.is_alive()])
    try:
        for process in processes:
            process.join()
    except KeyboardInterrupt:
        for process in processes:
            process.join()
    return 0 if all(p.exitcode == 0 for p in processes) else 1


def _run_number_id(db, run_number: int):
    from sqlalchemy import select

    from app.simulation.models import SimulationRun

    run_id = db.execute(
        select(SimulationRun.id).where(SimulationRun.run_number == run_number)
    ).scalar_one_or_none()
    if run_id is None:
        raise DomainError(f"There is no simulation run {run_number}.")
    return run_id


def _workflows(args: argparse.Namespace) -> int:
    from sqlalchemy import select

    from app.modules.identity.models import User
    from app.modules.workflows import authoring, service

    factory = get_sessionmaker()

    def problems(report_out) -> None:
        for kind, items in (("error", report_out.errors), ("warning", report_out.warnings)):
            for p in items:
                print(f"  {kind:<7} {p.location}: {p.message} [{p.code}]")

    try:
        if args.action == "list":
            with factory() as db:
                for w in service.list_workflows(db):
                    print(
                        f"{w.workflow_id}  v{w.version:<3} {w.source:<6} {w.status:<7} "
                        f"{w.name} (versions {', '.join(map(str, w.versions))})"
                    )
        elif args.action == "templates":
            with factory() as db:
                for t in service.list_templates(db):
                    print(
                        f"{t.template_id}  v{t.version:<3} {t.status:<7} ids "
                        f"{t.id_range[0]}-{t.id_range[1]}  {t.variants} variant(s)  {t.name}"
                    )
        elif args.action == "import-template":
            from app.modules.workflows import templates

            with open(args.file) as f:
                document = json.load(f)
            with factory() as db, db.begin():
                actor = db.execute(
                    select(User.id).where(User.username == args.as_user)
                ).scalar_one_or_none()
                if actor is None:
                    print(f"No user '{args.as_user}'.")
                    return 2
                report = templates.validate_template(db, document)
                for kind, items in (("error", report.errors), ("warning", report.warnings)):
                    for p in items:
                        print(f"  {kind:<7} {p['location']}: {p['message']} [{p['code']}]")
                if not report.valid:
                    return 1
                record, created, _ = templates.import_template(db, document, actor)
                verb = "Imported" if created else "Already stored (unchanged):"
                print(f"{verb} {record.template_id} v{record.version}")
        elif args.action == "generate":
            import time

            from app.modules.workflows import templates

            with open(args.grid) as f:
                spec = json.load(f)
            param_sets = templates.expand(spec.get("grid"), spec.get("variants"), spec.get("fixed"))
            started = time.perf_counter()
            with factory() as db, db.begin():
                actor = db.execute(
                    select(User.id).where(User.username == args.as_user)
                ).scalar_one_or_none()
                report = templates.generate(
                    db, args.template_id, param_sets, actor, dry_run=args.dry_run, limit=None
                )
            seconds = time.perf_counter() - started
            for r in report.results:
                if r.status == "invalid":
                    for p in r.errors:
                        print(f"  invalid {r.variant_key}: {p['location']}: {p['message']}")
            counts = ", ".join(
                f"{report.count(s)} {s}" for s in ("created", "updated", "unchanged", "invalid")
            )
            stored = "dry run" if args.dry_run else ("stored" if report.valid else "NOT stored")
            print(
                f"{args.template_id} v{report.template_version}: {len(report.results)} "
                f"variant(s): {counts} — {stored} in {seconds:.1f} s"
            )
            if not report.valid:
                return 1
        elif args.action == "export":
            with factory() as db:
                document = authoring.export(db, args.workflow_id, args.version)
            text = json.dumps(document, indent=2) + "\n"
            if args.output:
                with open(args.output, "w") as f:
                    f.write(text)
                print(f"Wrote {args.workflow_id} v{document['version']} to {args.output}")
            else:
                print(text, end="")
        else:
            with open(args.file) as f:
                document = json.load(f)
            with factory() as db, db.begin():
                report = service.report_out(authoring.validate(db, document))
                if args.action == "validate" or not report.valid:
                    state = "valid" if report.valid else "INVALID"
                    print(f"{report.workflow_id} v{report.version}: {state} ({report.existing})")
                    problems(report)
                    return 0 if report.valid else 1
                actor = db.execute(
                    select(User.id).where(User.username == args.as_user)
                ).scalar_one_or_none()
                if actor is None:
                    print(f"No user '{args.as_user}'.")
                    return 2
                record, created, _ = authoring.import_definition(db, document, actor)
                verb = "Imported" if created else "Already stored (unchanged):"
                print(f"{verb} {record.workflow_id} v{record.version} ({record.content_hash[:12]})")
                problems(report)
    except DomainError as exc:
        print(f"Refused: {exc.message}")
        return 1
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Cannot read the definition: {exc}")
        return 2
    return 0


def _simulation_history(args: argparse.Namespace) -> int:
    from app.simulation import history, service

    factory = get_sessionmaker()
    try:
        if args.action == "status":
            with factory() as db:
                overview = service.history_overview(db)
            print(json.dumps(overview.model_dump(mode="json"), indent=2))
        elif args.action == "archive":
            if args.older_than_days is not None:
                archived = history.archive_older_than(factory, args.older_than_days, None)
                print(f"Archived the history of {len(archived)} run(s): {archived}")
            else:
                with factory() as db:
                    run_id = _run_number_id(db, args.run)
                record = history.archive_run(factory, run_id, None)
                print(
                    f"Archived run {args.run}: {record.rows:,} rows, {record.bytes:,} bytes in "
                    f"{history.archive_root() / record.location}"
                )
        elif args.action == "restore":
            with factory() as db:
                run_id = _run_number_id(db, args.run)
            record = history.restore_run(factory, run_id, None)
            print(f"Restored run {args.run}: {record.rows:,} rows.")
        elif args.action == "reset":
            if not args.yes:
                print("Reset removes the workflow history of every simulation run; pass --yes.")
                return 1
            report = history.reset(factory, None, archive=args.archive)
            print(
                f"Reset: archived {len(report.archived)} run(s) first, dropped the history of "
                f"{len(report.purged)} run(s) ({report.rows:,} rows, "
                f"{report.bytes_freed:,} bytes)."
            )
    except DomainError as exc:
        print(f"Refused: {exc.message}")
        return 1
    return 0


def _perf(args: argparse.Namespace) -> int:
    from app import perf

    report = perf.run(
        get_sessionmaker(),
        "quick" if args.quick else "full",
        args.only.split(",") if args.only else None,
    )
    print(perf.render(report))
    if args.output:
        perf.save(report, args.output)
        print(f"Results written to {args.output}")
    return 0 if report["passed"] else 1


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
        "--profile",
        default="small",
        choices=["small", "department", "large", "enterprise", "custom"],
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
    simulate.add_argument(
        "--shards", type=int, default=1, help="Parallel slices, each run by its own process"
    )
    simulate.add_argument(
        "--processes", type=int, help="Worker processes for the shards (default: one per shard)"
    )
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
    bench.add_argument("--bulk", action="store_true", help="Post through the bulk (COPY) path")
    bench.set_defaults(handler=_bench_ledger)

    population = commands.add_parser(
        "load-population", help="Bulk-load synthetic customers with open, funded accounts"
    )
    population.add_argument("--customers", type=int, required=True)
    population.add_argument("--seed", type=int, default=2026)
    population.add_argument("--batch", type=int, default=5_000)
    population.set_defaults(handler=_load_population)

    worker = commands.add_parser(
        "worker", help="Run background jobs and their schedules (stop with Ctrl-C / SIGTERM)"
    )
    worker.add_argument("--processes", type=int, default=1, help="Worker processes to start")
    worker.add_argument(
        "--no-schedules", action="store_true", help="Run queued jobs only; do not tick schedules"
    )
    worker.add_argument("--drain", action="store_true", help="Exit when no job is due")
    worker.set_defaults(handler=_worker)

    perf_parser = commands.add_parser(
        "perf", help="Performance suite: key paths against recorded targets (scratch DB only)"
    )
    perf_parser.add_argument("--quick", action="store_true", help="Smaller sizes (CI)")
    perf_parser.add_argument("--only", help="Comma-separated benchmark names")
    perf_parser.add_argument("--output", help="Write the results as JSON to this file")
    perf_parser.set_defaults(handler=_perf)

    sim_history = commands.add_parser(
        "simulation-history",
        help="Archive, restore or reset simulation runs' workflow history (results stay)",
    )
    actions = sim_history.add_subparsers(dest="action", required=True)
    actions.add_parser("status", help="Storage used by workflow history and recent archives")
    archive = actions.add_parser("archive", help="Archive one run, or every run older than N days")
    which = archive.add_mutually_exclusive_group(required=True)
    which.add_argument("--run", type=int, help="Run number")
    which.add_argument("--older-than-days", type=int)
    restore = actions.add_parser("restore", help="Restore an archived run's history")
    restore.add_argument("--run", type=int, required=True, help="Run number")
    reset = actions.add_parser(
        "reset", help="Drop the history of every simulation run (instant; live history stays)"
    )
    reset.add_argument("--archive", action="store_true", help="Archive each run first")
    reset.add_argument("--yes", action="store_true", help="Confirm")
    sim_history.set_defaults(handler=_simulation_history)

    workflows = commands.add_parser(
        "workflows", help="List, validate, import and export workflow definitions"
    )
    wf_actions = workflows.add_subparsers(dest="action", required=True)
    wf_actions.add_parser("list", help="Every workflow, code and stored")
    wf_validate = wf_actions.add_parser("validate", help="Check a definition file (no import)")
    wf_validate.add_argument("file")
    wf_import = wf_actions.add_parser("import", help="Validate and store a definition file")
    wf_import.add_argument("file")
    wf_import.add_argument("--as-user", default="admin", help="Recorded as the importer")
    wf_actions.add_parser("templates", help="Every template version")
    wf_template = wf_actions.add_parser("import-template", help="Validate and store a template")
    wf_template.add_argument("file")
    wf_template.add_argument("--as-user", default="admin", help="Recorded as the importer")
    wf_generate = wf_actions.add_parser(
        "generate", help="Generate variants of a template from a grid file (all or none)"
    )
    wf_generate.add_argument("template_id")
    wf_generate.add_argument(
        "--grid",
        required=True,
        help='JSON file: {"grid": {...}, "variants": [...], "fixed": {...}}',
    )
    wf_generate.add_argument("--dry-run", action="store_true")
    wf_generate.add_argument("--as-user", default="admin", help="Recorded as the generator")
    wf_export = wf_actions.add_parser("export", help="Write a definition as an importable file")
    wf_export.add_argument("workflow_id")
    wf_export.add_argument("--version", type=int)
    wf_export.add_argument("--output", help="File to write (default: standard output)")
    workflows.set_defaults(handler=_workflows)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
