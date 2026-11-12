"""Minimal module entrypoint used by people and the systemd timer."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

from .config import (
    FactorySettings,
    WorkspacePaths,
    load_local_environment,
    load_settings,
    workspace_paths,
)
from .contracts import atomic_write_json
from .control import halt_production, halt_project
from .db import FactoryDB
from .engine import per_command_guard_refusal, tick
from .math_catalog import (
    KINDS, CatalogValidationError, catalog_receipt_path, catalog_stats, ingest_bundle,
    parse_metadata_filters, show_catalog,
)
from .proxy import ProxyPreflightError, ensure_proxy_ready
from .resources import effective_capacity
from .worker import run_worker


def _agent_role(task_type: str) -> str:
    normalized = task_type.lower()
    if any(token in normalized for token in ("review", "audit", "readiness")):
        return "reviewer"
    if any(token in normalized for token in ("experiment", "replication", "reproduction")):
        return "experimenter"
    if any(token in normalized for token in ("paper", "manuscript", "write")):
        return "writer"
    return "researcher"


def _asset_command(library, args, db, paths, settings) -> dict:
    command = args.assets_command
    if command == "seed":
        payload = library.seed_candidates(paths, settings)
        if args.output is not None:
            atomic_write_json(args.output, payload)
            payload = {**payload, "written_to": str(args.output)}
        return payload
    if command == "register":
        return library.register_draft(db, paths, settings, args.draft, by=args.by)
    if command == "list":
        return library.list_assets(paths, settings, include_archived=args.all)
    if command == "show":
        return library.show_asset(paths, settings, args.asset_id)
    if command == "archive":
        return library.archive_asset(db, paths, settings, args.asset_id, reason=args.reason,
                                     decided_by=f"manual:{args.by}")
    return library.reuse_cost_comparison(db, paths, settings)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m openlabs")
    parser.add_argument("--workspace", help="Override OPENLABS_WORKSPACE")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Initialize the local SQLite schema")
    commands.add_parser("tick", help="Run one idempotent scheduling tick")
    commands.add_parser("status", help="Print task counts")
    catalog = commands.add_parser("math-catalog", help="Import or query the isolated mathematics catalog")
    catalog_commands = catalog.add_subparsers(dest="catalog_command", required=True)
    catalog_ingest = catalog_commands.add_parser("ingest", help="Atomically import a hash-pinned data bundle")
    catalog_ingest.add_argument("--bundle", required=True, type=Path)
    catalog_ingest.add_argument("--expected-sha256", required=True)
    catalog_ingest.add_argument("--receipt", type=Path, help="Save the full receipt under a data catalog root and print a compact summary")
    for name in ("show", "stats"):
        query = catalog_commands.add_parser(name, help=f"{name.title()} catalog records without scheduling work")
        query.add_argument("--record-id")
        query.add_argument("--kind", choices=sorted(KINDS))
        query.add_argument("--status")
        query.add_argument("--metadata", action="append", metavar="KEY=JSON", help="Exact metadata match; dot paths allowed")
        if name == "show":
            query.add_argument("--limit", type=int, default=100)
            query.add_argument("--offset", type=int, default=0)
    network = commands.add_parser(
        "network-preflight",
        help="Probe Agent connectivity and synchronize a reachable proxy",
    )
    network.add_argument(
        "--exec",
        action="store_true",
        dest="execute",
        help="Execute a command with the selected proxy environment",
    )
    network.add_argument("exec_command", nargs=argparse.REMAINDER)

    halt = commands.add_parser(
        "halt-production",
        help="Pause a production plan, cancel its work, and stop the local factory",
    )
    halt.add_argument("--plan", type=Path, required=True)
    halt.add_argument("--reason", required=True)
    halt.add_argument("--report", type=Path)
    halt.add_argument(
        "--keep-factory",
        action="store_true",
        help="Cancel only this plan's workers and leave the shared factory online",
    )

    halt_generic = commands.add_parser(
        "halt-project",
        help="Pause a generic project, cancel its work, and stop the local factory",
    )
    halt_generic.add_argument("--project", type=Path, required=True)
    halt_generic.add_argument("--reason", required=True)
    halt_generic.add_argument("--report", type=Path)
    halt_generic.add_argument(
        "--keep-factory",
        action="store_true",
        help="Cancel only this project's workers and leave the shared factory online",
    )

    enqueue = commands.add_parser("enqueue", help="Add one bounded task")
    enqueue.add_argument("--campaign-id", required=True)
    enqueue.add_argument(
        "--domain", required=True, choices=("math", "ai", "materials", "quant", "physics", "biology")
    )
    enqueue.add_argument("--title")
    enqueue.add_argument("--task-type", default="research")
    enqueue.add_argument("--objective", required=True)
    enqueue.add_argument("--priority", type=int, default=0)
    enqueue.add_argument("--routing-reason", default="manual",
                         help="Administrator scheduling provenance, including a bound protocol stage")
    enqueue.add_argument("--skill")
    enqueue.add_argument(
        "--agent-role",
        choices=("researcher", "experimenter", "writer", "reviewer"),
        help="Defaults from task type; reviewers always start blank",
    )
    enqueue.add_argument(
        "--session-mode",
        choices=("resume", "fresh"),
        help="Start a fresh epistemic context or allow same-lineage continuation",
    )
    enqueue.add_argument("--max-wall-seconds", type=int)
    enqueue.add_argument("--cpu-threads", type=int)
    enqueue.add_argument("--memory-mib", type=int)
    enqueue.add_argument("--scratch-mib", type=int)
    enqueue.add_argument("--input", help="Campaign directory or immutable input file")
    enqueue.add_argument("--output", help="Explicit result path inside this campaign workspace")
    enqueue.add_argument(
        "--runner",
        choices=("cheap", "balanced", "frontier"),
        default="balanced",
        help="Capability/cost tier; concrete model commands stay in local environment config",
    )

    program = commands.add_parser(
        "program", help="Research-program topic ledger maintenance"
    )
    program_commands = program.add_subparsers(dest="program_command", required=True)
    backfill = program_commands.add_parser(
        "backfill",
        help="Register existing active research campaigns as grandfathered active topics "
        "(dry-run unless --write)",
    )
    backfill.add_argument("--write", action="store_true", help="Write the topic ledger")
    submit = program_commands.add_parser(
        "submit-card",
        help="Submit a human-written topic card to a research-program project's admission gate",
    )
    submit.add_argument("--project", required=True, type=Path, help="Program project.json")
    submit.add_argument("--card", required=True, type=Path, help="openlabs.topic_card.v1 JSON")
    submit.add_argument("--by", default="operator", help="Who submits the card (provenance)")
    assign = program_commands.add_parser(
        "assign-handler",
        help="After the owner's review of a delivered paper, assign its submission handler "
        "(default: the second author of the registry's default roster)",
    )
    assign.add_argument("--paper-id", required=True)
    assign.add_argument(
        "--handler", default="second_author",
        help="second_author (default) or an author name from the paper's byline",
    )
    assign.add_argument("--by", default="owner", help="Who completed the review (provenance)")
    instance = program_commands.add_parser(
        "init-instance",
        help="Create a separate orchestrator instance (own database, settings and projects; "
        "shared data and artifact repositories). Dry run unless --write",
    )
    instance.add_argument("--name", default="cc-sg", help="Instance name (default cc-sg)")
    instance.add_argument(
        "--instance-dir", type=Path,
        default=Path("/workspace/openlabs/openlabs-instances/cc-sg"),
        help="Instance directory (default /workspace/openlabs/openlabs-instances/cc-sg)",
    )
    instance.add_argument("--preset", choices=("observe", "full"), default="observe")
    instance.add_argument("--write", action="store_true", help="Create what is missing")
    instance.add_argument(
        "--update-config", action="store_true",
        help="Rewrite an existing instance TOML (the old one is kept as a .bak)",
    )
    instance.add_argument(
        "--paper-writing-command", nargs="+", default=None, metavar="ARG",
        help="[program].paper_writing_command for the instance",
    )
    instance.add_argument("--git-user-name", help="[program.git].user_name")
    instance.add_argument("--git-user-email", help="[program.git].user_email")
    utilization_parser = program_commands.add_parser(
        "utilization",
        help="Read-only throughput view: tasks by tier/provider, quota windows with relative "
        "abundance and projected use at reset, host and ailab load against their targets, "
        "recent launch ceilings and what limits them",
    )
    utilization_parser.add_argument(
        "--history", type=int, default=10, help="Recent launch ceilings to show (default 10)"
    )
    utilization_parser.add_argument(
        "--no-gpu", action="store_true", help="Skip the nvidia-smi query"
    )
    assets = program_commands.add_parser(
        "assets", help="Reusable-asset index: seed drafts, register, list, show, archive"
    )
    asset_commands = assets.add_subparsers(dest="assets_command", required=True)
    seed = asset_commands.add_parser(
        "seed",
        help="Scan [program.assets].seed_paths for standalone tools and print registration "
        "drafts (never registers)",
    )
    seed.add_argument("--dry-run", action="store_true", default=True,
                      help="Always on: seeding only proposes drafts")
    seed.add_argument("--output", type=Path, help="Also write the drafts to this file")
    register = asset_commands.add_parser(
        "register", help="Register a confirmed draft (one proposal or asset_proposals[])"
    )
    register.add_argument("draft", type=Path)
    register.add_argument("--by", default="operator", help="Who confirmed it (provenance)")
    listing = asset_commands.add_parser("list", help="One line per asset")
    listing.add_argument("--all", action="store_true", help="Include archived assets")
    show = asset_commands.add_parser("show", help="Full index entry of one asset")
    show.add_argument("asset_id")
    archive = asset_commands.add_parser("archive", help="Archive an asset (never deletes)")
    archive.add_argument("asset_id")
    archive.add_argument("--reason", default="manual")
    archive.add_argument("--by", default="operator")
    asset_commands.add_parser(
        "cost", help="Tasks, tokens and Agent time of topics with vs without reused assets"
    )
    return parser


def configured_providers(settings: FactorySettings) -> tuple[str, ...] | None:
    """Providers of the configured runners; None (Codex only) without a [runners] table."""

    providers = sorted({spec.provider for spec in settings.runners.values()})
    return tuple(providers) or None


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _init_instance(args: argparse.Namespace) -> int:
    from .instance import InstanceInitError, init_instance

    try:
        payload = init_instance(
            _shared_paths(args.workspace),
            name=args.name,
            instance_dir=args.instance_dir,
            preset=args.preset,
            write=args.write,
            update_config=args.update_config,
            paper_writing_command=args.paper_writing_command,
            git_user_name=args.git_user_name,
            git_user_email=args.git_user_email,
        )
    except (InstanceInitError, OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False),
              file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _shared_paths(workspace: str | None) -> WorkspacePaths:
    """Shared repository paths, whatever instance the environment selects."""

    saved = {name: os.environ.pop(name) for name in
             ("OPENLABS_INSTANCE", "OPENLABS_DATABASE_ROOT", "OPENLABS_CONFIG_FILE")
             if name in os.environ}
    try:
        return workspace_paths(workspace)
    finally:
        os.environ.update(saved)


def main(argv: Sequence[str] | None = None) -> int:
    # Keep manual CLI invocations, transient workers, and the systemd timer on
    # one local Agent/proxy configuration path. Explicit inherited values win.
    inherited_environment = dict(os.environ)
    load_local_environment()
    arguments = list(argv) if argv is not None else sys.argv[1:]
    if arguments is not None and arguments[:1] == ["_worker"]:
        if len(arguments) != 2:
            raise SystemExit("usage: python -m openlabs _worker JOB_FILE")
        return run_worker(arguments[1])
    args = _parser().parse_args(arguments)
    if args.command == "program" and args.program_command == "init-instance":
        return _init_instance(args)
    if args.command in {"network-preflight", "tick"}:
        try:
            preflight_paths = workspace_paths(args.workspace)
            providers = configured_providers(load_settings(preflight_paths))
        except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
            print(json.dumps({"status": "refused", "error": str(exc)}, ensure_ascii=False),
                  file=sys.stderr)
            return 78
        if args.command == "tick" and _flag("OPENLABS_REQUIRE_INSTANCE") and (
            preflight_paths.instance is None
        ):
            print(json.dumps({
                "status": "refused",
                "error": "OPENLABS_REQUIRE_INSTANCE is set but no OPENLABS_INSTANCE is selected; "
                         "run ticks through bin/openlabs-container-loop (instance.env), never "
                         "against the shared default database",
            }, ensure_ascii=False), file=sys.stderr)
            return 78
        try:
            network_report = ensure_proxy_ready(
                environment=os.environ,
                inherited_environment=inherited_environment,
                providers=providers,
            )
        except ProxyPreflightError as exc:
            print(
                json.dumps(
                    {
                        "schema_version": "openlabs.proxy_preflight.v1",
                        "status": "failed",
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 69
        if args.command == "network-preflight":
            exec_command = list(args.exec_command or ())
            if exec_command[:1] == ["--"]:
                exec_command = exec_command[1:]
            if args.execute and exec_command:
                os.execvpe(exec_command[0], exec_command, os.environ)
            if args.execute:
                print("network-preflight --exec requires a command", file=sys.stderr)
                return 64
            print(json.dumps(network_report, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
    paths = workspace_paths(args.workspace)
    if args.command == "math-catalog":
        # The catalog is an explicit, narrow write path. It neither initializes
        # runtime directories/schema nor enters research scheduling.
        db = FactoryDB(paths.database_file)
        try:
            if args.catalog_command == "ingest":
                receipt_path = catalog_receipt_path(paths.data, args.receipt) if args.receipt is not None else None
                payload = ingest_bundle(db, data_root=paths.data, bundle=args.bundle,
                                        expected_sha256=args.expected_sha256)
                if receipt_path is not None:
                    summary = {key: value for key, value in payload.items() if key != "record_ids"}
                    summary["receipt_path"] = receipt_path.relative_to(paths.data.resolve()).as_posix()
                    try:
                        atomic_write_json(receipt_path, payload)
                    except OSError as exc:
                        # SQLite already committed and retains the full receipt
                        # event; do not claim that the import was rejected.
                        print(json.dumps({"status": "imported_receipt_write_failed", "error": str(exc),
                                          "receipt_summary": summary}, ensure_ascii=False), file=sys.stderr)
                        return 74
                    payload = summary
            else:
                filters = {"kind": args.kind, "status": args.status, "record_id": args.record_id,
                           "metadata_filters": parse_metadata_filters(args.metadata)}
                if args.catalog_command == "show":
                    payload = show_catalog(db, limit=args.limit, offset=args.offset, **filters)
                else:
                    payload = catalog_stats(db, **filters)
        except (CatalogValidationError, OSError, sqlite3.Error) as exc:
            print(json.dumps({"status": "rejected", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
            return 65
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if (
        args.command == "program" and args.program_command == "assets"
        and args.assets_command in {"seed", "list", "show"}
    ):
        # Read-only: neither runtime directories nor the database are touched.
        from . import assets as asset_library

        try:
            payload = _asset_command(asset_library, args, None, paths, load_settings(paths))
        except (asset_library.AssetIndexError, OSError, ValueError) as exc:
            print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False),
                  file=sys.stderr)
            return 1
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "program" and args.program_command == "utilization":
        # Read-only: the database is opened with mode=ro and nothing is created.
        from .utilization import ReadOnlyFactoryDB, utilization_report

        if not paths.database_file.is_file():
            print(json.dumps({"status": "failed", "error": "no database at "
                              f"{paths.database_file}"}, ensure_ascii=False), file=sys.stderr)
            return 1
        payload = utilization_report(
            ReadOnlyFactoryDB(paths.database_file), paths, load_settings(paths),
            history=args.history, include_gpu=not args.no_gpu,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    paths.ensure_runtime_directories()
    db = FactoryDB(paths.database_file)
    db.initialize()
    settings = load_settings(paths)
    if args.command == "init":
        payload = {"schema_version": "openlabs.init.v1", "database": str(paths.database_file)}
    elif args.command == "tick":
        refusal = per_command_guard_refusal()
        if refusal is not None:
            print(json.dumps({"status": "refused", "error": refusal}, ensure_ascii=False),
                  file=sys.stderr)
            return 78
        payload = tick(paths, load_settings(paths)).to_dict()
    elif args.command == "program":
        from . import assets as asset_library
        from .program_autonomy import DeliveryError, assign_submission_handler
        from .program_flow import backfill_grandfathered, submit_topic_card

        if args.program_command == "assets":
            try:
                payload = _asset_command(asset_library, args, db, paths, settings)
            except (asset_library.AssetIndexError, OSError, ValueError) as exc:
                print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False),
                      file=sys.stderr)
                return 1
        elif args.program_command == "backfill":
            payload = backfill_grandfathered(db, paths, settings, write=args.write)
        elif args.program_command == "assign-handler":
            try:
                payload = assign_submission_handler(
                    db, paths, settings, paper_id=args.paper_id, handler=args.handler,
                    assigned_by=args.by,
                )
            except DeliveryError as exc:
                print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False),
                      file=sys.stderr)
                return 1
        else:
            card = json.loads(args.card.read_text(encoding="utf-8"))
            payload = {
                "schema_version": "openlabs.program_card_submission.v1",
                **submit_topic_card(
                    db, paths, settings, args.project, card, submitted_by=args.by
                ),
            }
    elif args.command == "status":
        reserved = db.active_resource_totals()
        campaigns = db.campaigns()
        production_lanes = []
        for campaign in campaigns:
            if not bool(campaign.get("continuous")):
                continue
            campaign_id = str(campaign["campaign_id"])
            latest = db.latest_task(campaign_id)
            if str(campaign.get("status")) != "active":
                health = str(campaign.get("status"))
            elif db.has_active_tasks(campaign_id):
                health = "running"
            elif db.has_queued_tasks(campaign_id):
                health = "queued"
            elif latest and str(latest.get("status")) in {
                "needs_human",
                "quarantined",
            }:
                health = "blocked"
            else:
                health = "idle_reseed_due"
            production_lanes.append(
                {
                    "campaign_id": campaign_id,
                    "health": health,
                    "production_epoch": campaign.get("production_epoch"),
                    "rollover_count": campaign.get("rollover_count"),
                    "latest_task_id": latest.get("task_id") if latest else None,
                    "latest_task_status": latest.get("status") if latest else None,
                    "last_rollover_at": campaign.get("last_rollover_at"),
                    "last_rollover_reason": campaign.get("last_rollover_reason"),
                }
            )
        payload = {
            "schema_version": "openlabs.status.v1",
            "tasks": db.status_counts(),
            "research_records": db.research_record_counts(),
            "production": {
                "continuous_lanes": production_lanes,
                "healthy": bool(production_lanes)
                and all(lane["health"] in {"running", "queued"} for lane in production_lanes),
            },
            "resources": {
                "capacity": effective_capacity(
                    paths.workspace,
                    settings,
                    reserved,
                ).to_dict(),
                "reserved": reserved,
                "max_worker_processes": settings.max_worker_processes,
            },
            "campaigns": [
                {
                    "campaign_id": item["campaign_id"],
                    "status": item["status"],
                    "continuous": bool(item.get("continuous")),
                    "production_epoch": item.get("production_epoch"),
                    "rollover_count": item.get("rollover_count"),
                    "epoch_agent_seconds_used": item.get("epoch_agent_seconds_used"),
                    "agent_seconds_used": item["agent_seconds_used"],
                    "max_agent_seconds": item["max_agent_seconds"],
                }
                for item in campaigns
            ],
        }
    elif args.command == "halt-production":
        payload = halt_production(
            paths,
            plan_path=args.plan,
            reason=args.reason,
            report_path=args.report,
            stop_systemd=not args.keep_factory,
        )
    elif args.command == "halt-project":
        payload = halt_project(
            paths,
            project_path=args.project,
            reason=args.reason,
            report_path=args.report,
            stop_systemd=not args.keep_factory,
        )
    elif args.command == "enqueue":
        input_path = str(Path(args.input).expanduser().resolve()) if args.input else None
        campaign = db.campaign(args.campaign_id)
        if campaign is None:
            db.register_campaign(
                args.campaign_id,
                domain=args.domain,
                title=args.title or args.campaign_id,
                priority=args.priority,
                state_path=input_path,
                max_agent_seconds=settings.max_campaign_agent_seconds,
            )
            campaign = db.campaign(args.campaign_id)
        if not input_path and campaign and campaign.get("state_path"):
            candidate = Path(str(campaign["state_path"]))
            input_path = str(candidate if candidate.is_absolute() else paths.data / candidate)
        task_id = db.enqueue_task(
            campaign_id=args.campaign_id,
            domain=args.domain,
            task_type=args.task_type,
            objective=args.objective,
            input_path=input_path,
            output_path=str(Path(args.output).expanduser().resolve()) if args.output else None,
            priority=args.priority,
            skill_path=args.skill,
            routing_reason=args.routing_reason,
            runner=args.runner,
            max_attempts=settings.max_attempts,
            agent_role=args.agent_role or _agent_role(args.task_type),
            session_mode=args.session_mode,
            max_wall_seconds=args.max_wall_seconds or settings.max_task_wall_seconds,
            cpu_threads=(
                args.cpu_threads
                if args.cpu_threads is not None
                else settings.default_task_cpu_threads
            ),
            memory_mib=(
                args.memory_mib if args.memory_mib is not None else settings.default_task_memory_mib
            ),
            scratch_mib=(
                args.scratch_mib
                if args.scratch_mib is not None
                else settings.default_task_scratch_mib
            ),
        )
        payload = {"schema_version": "openlabs.enqueue.v1", "task_id": task_id}
    else:  # pragma: no cover - argparse enforces the command set.
        raise AssertionError(args.command)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
