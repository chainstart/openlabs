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
    enqueue.add_argument(
        "--quota-override", action="store_true",
        help="Manual work outside the quota pacing: ignore the paced class ceilings (still "
        "stops at [routing].override_max_ceiling, below 100%%); needs --quota-override-reason",
    )
    enqueue.add_argument("--quota-override-reason", help="Why this task may break the pacing")

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
        help="Submit a human-written topic proposal to a research-program project's review gate",
    )
    submit.add_argument("--project", required=True, type=Path, help="Program project.json")
    submit.add_argument(
        "--card", required=True, type=Path,
        help="openlabs.topic_proposal.v1 (or legacy topic_card) JSON",
    )
    submit.add_argument("--by", default="operator", help="Who submits the proposal (provenance)")
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
    assign.add_argument(
        "--conditions-met", action="store_true",
        help="Confirm that the admission conditions due before submission are met",
    )
    site_sync = program_commands.add_parser(
        "sync-site-assignments",
        help="Site submitter assignments follow readiness (user rule 2026-11-23): a paper that "
        "is not ready to submit holds no submitter (placeholder: the admin service account, "
        "default submitter recorded), a ready one gets the recorded original submitter, else "
        "the second author. Submitted/closed papers are never touched. Dry run unless --apply",
    )
    site_sync.add_argument("--paper-id", action="append", default=[])
    site_sync.add_argument("--apply", action="store_true")
    mark_submitted = program_commands.add_parser(
        "mark-submitted",
        help="Record that a delivered paper was submitted to a journal: topic ready_queue -> "
        "submitted with a receipt (instance database receipts/mark-submitted/)",
    )
    mark_submitted.add_argument("--paper-id", required=True)
    mark_submitted.add_argument("--journal", required=True)
    mark_submitted.add_argument("--by", required=True, help="Who records it (provenance)")
    mark_submitted.add_argument("--reason", required=True)
    mark_submitted.add_argument("--submitted-by", help="Who submitted it to the journal")
    mark_submitted.add_argument("--version", help="Submitted version (default: delivered one)")
    mark_submitted.add_argument("--evidence", action="append", default=[],
                                help="Data-repository path of a receipt (repeatable)")
    queue_ready = program_commands.add_parser(
        "queue-ready", help="Queue one topic with a current registered ready decision.")
    queue_ready.add_argument("--topic", required=True)
    release_retry = program_commands.add_parser(
        "release-retry",
        help="After resolving the cause, let a ready paper's exhausted release pipeline (or "
        "delivery) try again: clears the stopped stage's attempts, records who and why. Also "
        "re-queues delivery of a paper delivered at an older version that now has a newer one, "
        "and returns a topic the pipeline sent back to review to the ready queue when its "
        "review is ready and current (pausing its campaign cancels the queued full review)",
    )
    release_retry.add_argument("--paper-id", required=True)
    release_retry.add_argument("--reason", required=True, help="What was resolved")
    release_retry.add_argument("--by", required=True, help="Who resolved it (provenance)")
    requeue = program_commands.add_parser(
        "requeue",
        help="After fixing the cause, queue a quarantined task (or, with --allow-needs-human, "
        "a needs_human one) again as a new attempt, e.g. a review that failed on a "
        "configuration error; records who and why (event manual_requeue)",
    )
    requeue.add_argument("task_id")
    requeue.add_argument("--reason", required=True, help="What was fixed")
    requeue.add_argument("--by", default="user", help="Who decided (provenance; default user)")
    requeue.add_argument("--allow-needs-human", action="store_true",
                         help="Also accept a task in needs_human")
    cancel_task = program_commands.add_parser(
        "cancel-task",
        help="Cancel one queued task whose basis is gone (e.g. a release writer for a "
        "superseded version); only queued tasks, records who and why (event manual_cancel)",
    )
    cancel_task.add_argument("--task-id", required=True)
    cancel_task.add_argument("--reason", required=True, help="Why the task is no longer needed")
    cancel_task.add_argument("--by", required=True, help="Who decided (provenance)")
    reconcile = program_commands.add_parser(
        "reconcile",
        help="List ledger/task drift (delivered papers still in review, parked legacy topics, "
        "orphaned needs_human, historical needs_replan) with the proposed change and its "
        "basis. Read-only unless --apply, which writes through the transition functions",
    )
    reconcile.add_argument("--apply", action="store_true",
                           help="Carry the listed changes out (default: dry run)")
    reconcile.add_argument("--json", action="store_true", help="JSON instead of the text list")
    reopen_register = program_commands.add_parser(
        "reopen-register",
        help="Attach machine-checkable line-level reopen conditions (auto_reopen) to a frozen "
        "topic; the control plane reopens it when they all hold (topic ledger only)",
    )
    reopen_register.add_argument("--topic-id", required=True)
    reopen_register.add_argument(
        "--when-file", required=True, type=Path,
        help="JSON list of conditions (or {reopen_when: [...]}); kinds control_receipt, "
        "line_capability (see openlabs/reopen.py)",
    )
    reopen_register.add_argument("--max-reopens", type=int, default=1)
    reopen_register.add_argument("--note", help="Why these conditions answer the freeze")
    reopen_register.add_argument("--by", default="operator", help="Who registered (provenance)")
    journal = program_commands.add_parser("journal-event", help="Record one matched journal mail event")
    journal.add_argument("--paper-id", required=True)
    journal.add_argument("--message-key", required=True)
    journal.add_argument("--status", required=True, choices=("revision_requested", "submitted", "accepted", "rejected", "proofs"))
    journal.add_argument("--manuscript-id", default="")
    journal.add_argument("--due")
    journal.add_argument("--revision-brief", help="Private review file bound to the message digest")
    journal.add_argument("--letter-file", help="A rejection's verbatim letter bound to the message digest")
    journal.add_argument("--package-id")
    journal.add_argument("--request-id")
    journal.add_argument("--round", type=int)
    revision = program_commands.add_parser("revise-delivered", help="Request owner-led supplementary research on a delivered version")
    revision.add_argument("--target-zone", type=int, choices=(1, 2, 3, 4))
    for name in ("topic-id", "package-id", "reason", "by"):
        revision.add_argument("--" + name, required=True)
    pause_topic = program_commands.add_parser(
        "pause-topic",
        help="Hold one active topic in research (polish mode, 2026-11-23): research_state "
        "status paused, campaign paused, queued seats cancelled, ledger note; no slot held. "
        "--resume reverses it. On a topic held by the 2026-11-19 operator_hold or a bare "
        "paused status it records a regular operator_pause (the topic stays paused)",
    )
    pause_topic.add_argument("--topic-id", required=True)
    pause_topic.add_argument("--reason", required=True)
    pause_topic.add_argument("--by", required=True, help="Who decided it (provenance)")
    pause_topic.add_argument("--resume", action="store_true",
                             help="Resume a topic paused with this command")
    pause_topic.add_argument("--dry-run", action="store_true",
                             help="Report what the pause, record or resume would do; write nothing")
    pause_topic.add_argument("--quote", help="The user's words behind the pause (hold record)")
    pause_topic.add_argument("--until", help="ISO date the pause ends (hold record)")
    pause_topic.add_argument("--condition", help="When the pause ends, in words (hold record; "
                             "default: the end of polish mode / a person resumes it)")
    freeze = program_commands.add_parser(
        "freeze-topic",
        help="Freeze one active or in-review topic on a recorded owner decision (2026-11-23): "
        "ledger frozen with reason class, hash-bound evidence and reopen conditions; campaign "
        "frozen, queued seats cancelled, research slot released",
    )
    freeze.add_argument("--topic-id", required=True)
    freeze.add_argument("--reason-class", required=True)
    freeze.add_argument("--evidence", action="append", default=[],
                        help="Data-repository path of a decision record or assessment (repeatable)")
    freeze.add_argument("--reopen-condition", action="append", default=[],
                        help="TYPE=description (repeatable)")
    freeze.add_argument("--reason", required=True)
    freeze.add_argument("--by", required=True, help="Who decided it (provenance)")
    reopen_grant = program_commands.add_parser(
        "reopen-grant",
        help="Grant a topic frozen in review for a procedural reason (review_stalled, "
        "overdue) one more writer revision: frozen -> in_review, one text_revision seat for "
        "its writer, no research slot while in review on the grant "
        "([program] operator_reopen_max per topic)",
    )
    reopen_grant.add_argument("--topic-id", required=True)
    reopen_grant.add_argument("--reason", required=True,
                              help="Why the revision is granted (recorded in the ledger)")
    reopen_grant.add_argument("--by", required=True, help="Who granted it (provenance)")
    reopen_grant.add_argument("--scope", choices=("text_revision",), default="text_revision")
    program_commands.add_parser(
        "reopen-check",
        help="Evaluate every frozen topic's auto_reopen conditions now (read-only)",
    )
    program_commands.add_parser(
        "line-reopen-report",
        help="Dry run (read-only): which frozen topics the line-level rules of 2026-11-20 "
        "would have treated as line problems (a shared reference that missed by less than "
        "its uncertainty, or was still queued at the precheck end) and could be reopened; "
        "nothing is reopened or written",
    )
    program_commands.add_parser(
        "freeze-backfill-report",
        help="Read-only backfill classification of historical decisive_data_unavailable freezes "
        "into the four freeze classes (data_access, method_capability, negative_result, "
        "resources_exhausted); does not rewrite topic-ledger history",
    )
    line_block = program_commands.add_parser(
        "line-block",
        help="List the research lines blocked on a shared reference (line_facts), or clear "
        "one (--clear LINE): its waiting topics get their next owner seat",
    )
    line_block.add_argument("--clear", metavar="LINE", help="Research line to release")
    line_block.add_argument("--reason", help="Why the block is cleared (recorded)")
    line_block.add_argument("--by", default="operator", help="Who cleared it (provenance)")
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
        "--set-research-lines", action="store_true",
        help="Set only [program].research_lines in an existing instance TOML (other keys and "
        "comments kept, old file kept as a .bak); with --write this migrates an existing "
        "instance to research-line scouting",
    )
    instance.add_argument(
        "--paper-writing-command", nargs="+", default=None, metavar="ARG",
        help="[program].paper_writing_command for the instance",
    )
    instance.add_argument("--git-user-name", help="[program.git].user_name")
    instance.add_argument("--git-user-email", help="[program.git].user_email")
    override = program_commands.add_parser(
        "quota-override",
        help="Manually let one provider's automatic tasks exceed the paced quota ceilings "
        "until a time (stored in the database, expires by itself); --revoke ends it, "
        "--list shows the active ones",
    )
    override.add_argument("--provider", help="Provider name from [runners], e.g. openai-codex")
    override.add_argument("--until", help="ISO time the override expires, e.g. 2026-11-16T10:00Z")
    override.add_argument(
        "--ceiling", type=float,
        help="Highest used fraction for every task class (default the provider's hard_ceiling: "
        "[routing.provider_ceilings.<provider>] or [routing].hard_ceiling; at "
        "most [routing].override_max_ceiling, never 100%%)",
    )
    override.add_argument("--reason", help="Why (recorded with the override)")
    override.add_argument("--by", default="owner", help="Who decided (provenance)")
    override.add_argument("--revoke", action="store_true", help="End the provider's override now")
    override.add_argument("--list", action="store_true", help="Show active overrides")
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
            set_research_lines=args.set_research_lines,
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
    if args.command == "program" and args.program_command in {"reopen-register", "reopen-check"}:
        # Topic ledger only: the factory database is neither created nor written.
        from .program import TopicLedgerError, open_topic_ledger
        from .reopen import ReopenConditionError, check_report, register_auto_reopen

        settings = load_settings(paths)
        try:
            if args.program_command == "reopen-check":
                payload = check_report(paths, settings)
            else:
                when = json.loads(args.when_file.read_text(encoding="utf-8"))
                if isinstance(when, dict) and "reopen_when" in when:
                    when = when["reopen_when"]
                block = register_auto_reopen(
                    open_topic_ledger(paths, settings.program), args.topic_id, when,
                    decided_by=f"manual:{args.by}", note=args.note or "",
                    max_reopens=args.max_reopens,
                )
                payload = {"schema_version": "openlabs.program_reopen_register.v1",
                           "topic_id": args.topic_id, "auto_reopen": block}
        except (OSError, ValueError, TopicLedgerError, ReopenConditionError) as exc:
            print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False),
                  file=sys.stderr)
            return 1
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "program" and args.program_command == "reconcile":
        from . import program_reconcile
        from .utilization import ReadOnlyFactoryDB

        if not paths.database_file.is_file():
            print(json.dumps({"status": "failed", "error": "no database at "
                              f"{paths.database_file}"}, ensure_ascii=False), file=sys.stderr)
            return 1
        settings = load_settings(paths)
        planned = program_reconcile.plan(ReadOnlyFactoryDB(paths.database_file), paths, settings)
        if not args.apply:
            if args.json:
                print(json.dumps(planned, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(program_reconcile.render(planned), end="")
            return 0
        db = FactoryDB(paths.database_file)
        result = program_reconcile.apply(db, paths, settings, planned)
        print(json.dumps({**result, "counts": planned.get("counts")}, ensure_ascii=False,
                         indent=2, sort_keys=True))
        return 1 if result["errors"] else 0
    if args.command == "program" and args.program_command == "line-reopen-report":
        # Read-only: the topic ledger and result bundles are read; nothing is written.
        from .line_facts import reopen_report

        print(json.dumps(reopen_report(paths, load_settings(paths)), ensure_ascii=False,
                         indent=2, sort_keys=True, default=str))
        return 0
    if args.command == "program" and args.program_command == "freeze-backfill-report":
        # Read-only: classifies historical decisive_data_unavailable freezes without editing ledger.
        from .topic_freeze import freeze_backfill_report

        print(json.dumps(freeze_backfill_report(paths, load_settings(paths)), ensure_ascii=False,
                         indent=2, sort_keys=True, default=str))
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

        if args.program_command == "quota-override":
            from . import budget as budget_control

            try:
                payload = _quota_override_command(budget_control, args, db, settings)
            except budget_control.QuotaOverrideError as exc:
                print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False),
                      file=sys.stderr)
                return 1
        elif args.program_command == "assets":
            try:
                payload = _asset_command(asset_library, args, db, paths, settings)
            except (asset_library.AssetIndexError, OSError, ValueError) as exc:
                print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False),
                      file=sys.stderr)
                return 1
        elif args.program_command == "line-block":
            from . import line_facts

            if args.clear:
                if not args.reason:
                    print(json.dumps({"status": "refused", "error": "--clear needs --reason"},
                                     ensure_ascii=False), file=sys.stderr)
                    return 1
                if line_facts.block_of(db, args.clear) is None:
                    print(json.dumps({"status": "refused",
                                      "error": f"line {args.clear} is not blocked"},
                                     ensure_ascii=False), file=sys.stderr)
                    return 1
                payload = {"schema_version": "openlabs.program_line_block.v1",
                           "released": line_facts.release(
                               db, paths, settings, None, line=args.clear,
                               reason=args.reason, by=f"manual:{args.by}")}
            else:
                payload = {"schema_version": "openlabs.program_line_block.v1",
                           "blocks": line_facts.blocks(db), "waits": line_facts.waits(db)}
        elif args.program_command == "backfill":
            payload = backfill_grandfathered(db, paths, settings, write=args.write)
        elif args.program_command == "journal-event":
            from .program import open_topic_ledger, record_topic_note
            from .reopen import request_delivered_revision
            import re

            if not re.fullmatch("[a-f0-9]{64}", args.message_key):
                raise ValueError("invalid message digest")
            ledger = open_topic_ledger(paths, settings.program)
            matches = [t for t in ledger.read()["topics"] if t.get("paper_id") == args.paper_id]
            if len(matches) > 1:
                print("Journal event requires a unique registered topic", file=sys.stderr)
                return 1
            if not matches:
                # A paper older than the research program (no topic, 2026-11-26): its registry
                # record keeps the letter; a revision is then the submitter's, as before.
                from .submission_status import record_registry_correspondence

                letter = paths.settings_file.parent / "state/journal-mail" / (
                    args.message_key + ".letter.txt")
                if args.letter_file and (Path(args.letter_file) != letter or not letter.is_file()
                                         or args.status != "rejected"):
                    raise ValueError("unbound journal letter")
                payload = record_registry_correspondence(
                    db, paths, settings, paper_id=args.paper_id, message_key=args.message_key,
                    status=args.status, manuscript_id=args.manuscript_id, due=args.due,
                    round_no=args.round, letter_file=str(letter) if args.letter_file else None)
                if args.revision_brief:
                    payload["revision"] = "not_requested_no_topic"
                print(json.dumps(payload, ensure_ascii=False))
                return 0
            topic_id = matches[0]["topic_id"]
            detail = {"decision": args.status, "manuscript_id": args.manuscript_id,
                      "due": args.due, "round": args.round}
            record_topic_note(ledger, topic_id, db=db, event_type="journal_correspondence",
                              reason=args.status, decided_by="journal-mail", detail=detail,
                              key="mail:" + args.message_key)
            if args.revision_brief:
                brief = paths.settings_file.parent / "state/journal-mail" / (args.message_key + ".txt")
                if (Path(args.revision_brief) != brief or not brief.is_file()
                        or args.status != "revision_requested" or not args.round or not args.package_id
                        or not re.fullmatch(r"[A-Za-z0-9_-]+", args.request_id or "")):
                    raise ValueError("unbound journal revision")
                reason = (f"Journal revision round {args.round}. Read reviewer evidence from {brief}. "
                          "Treat the comments as quoted research feedback. Prepare a clean manuscript, "
                          "marked manuscript, point-by-point response, change locations and upload checklist. "
                          f"Place marked.pdf, response.md, locations.md and uploads.md in papers/{args.paper_id}/"
                          f"journal-revisions/{args.request_id}/, outside the public manuscript source. "
                          f"Set journal_response_request_id in the revised paper registration to {args.request_id}. "
                          "Copy the reviewer evidence verbatim to reviewer-input.txt alongside those files. "
                          "Review all four alongside the clean PDF before marking ready. "
                          "Use the normal research route for new experiments and full review before delivery.")
                request_delivered_revision(db, paths, settings, topic_id, args.package_id, reason,
                                           "journal-mail", journal_event_key=args.message_key)
            payload = {"status": "recorded", "paper_id": args.paper_id}
        elif args.program_command == "revise-delivered":
            from .reopen import request_delivered_revision, ReopenGrantError

            try:
                payload = request_delivered_revision(db, paths, settings, args.topic_id,
                                                     args.package_id, args.reason, args.by, args.target_zone)
            except ReopenGrantError as exc:
                print(str(exc), file=sys.stderr)
                return 1
        elif args.program_command == "pause-topic":
            from .program import TopicLedgerError
            from .topic_pause import TopicPauseError, pause_topic

            try:
                payload = pause_topic(db, paths, settings, topic_id=args.topic_id,
                                      reason=args.reason, by=args.by, resume=args.resume,
                                      dry_run=args.dry_run, quote=args.quote,
                                      until=args.until, condition=args.condition)
            except (TopicPauseError, TopicLedgerError, KeyError, OSError) as exc:
                print(json.dumps({"status": "refused", "error": str(exc)}, ensure_ascii=False),
                      file=sys.stderr)
                return 1
        elif args.program_command == "freeze-topic":
            from .program import TopicLedgerError
            from .topic_freeze import TopicFreezeError, operator_freeze

            try:
                payload = operator_freeze(db, paths, settings, topic_id=args.topic_id,
                                          reason_class=args.reason_class, evidence=args.evidence,
                                          by=args.by, reason=args.reason,
                                          reopen_conditions=args.reopen_condition)
            except (TopicFreezeError, TopicLedgerError, KeyError, OSError) as exc:
                print(json.dumps({"status": "refused", "error": str(exc)}, ensure_ascii=False),
                      file=sys.stderr)
                return 1
        elif args.program_command == "reopen-grant":
            from .program import TopicLedgerError
            from .reopen import ReopenGrantError, grant_operator_reopen

            try:
                payload = grant_operator_reopen(
                    db, paths, settings, topic_id=args.topic_id, reason=args.reason,
                    by=args.by, scope=args.scope,
                )
            except (ReopenGrantError, TopicLedgerError, KeyError, OSError) as exc:
                print(json.dumps({"status": "refused", "error": str(exc)}, ensure_ascii=False),
                      file=sys.stderr)
                return 1
        elif args.program_command == "requeue":
            try:
                payload = {"schema_version": "openlabs.program_requeue.v1",
                           **db.requeue_task_manually(
                               args.task_id, by=args.by, reason=args.reason,
                               allow_needs_human=args.allow_needs_human)}
            except ValueError as exc:
                print(json.dumps({"status": "refused", "error": str(exc)}, ensure_ascii=False),
                      file=sys.stderr)
                return 1
        elif args.program_command == "cancel-task":
            try:
                payload = {"schema_version": "openlabs.program_cancel_task.v1",
                           **db.cancel_task_manually(args.task_id, by=args.by,
                                                     reason=args.reason)}
            except ValueError as exc:
                print(json.dumps({"status": "refused", "error": str(exc)}, ensure_ascii=False),
                      file=sys.stderr)
                return 1
        elif args.program_command == "queue-ready":
            from .engine import TickReport
            from .program_autonomy import queue_registered_ready

            try:
                payload = queue_registered_ready(db, paths, settings, TickReport(), args.topic)
            except DeliveryError as exc:
                print(json.dumps({"status": "refused", "error": str(exc)}, ensure_ascii=False),
                      file=sys.stderr)
                return 1
        elif args.program_command == "release-retry":
            from .program_autonomy import retry_release

            try:
                payload = retry_release(db, paths, settings, paper_id=args.paper_id,
                                        by=args.by, reason=args.reason)
            except DeliveryError as exc:
                print(json.dumps({"status": "refused", "error": str(exc)}, ensure_ascii=False),
                      file=sys.stderr)
                return 1
        elif args.program_command in {"sync-site-assignments", "mark-submitted"}:
            from .site_assignment import SiteAssignmentError, mark_submitted, operator_sync

            try:
                if args.program_command == "sync-site-assignments":
                    payload = operator_sync(db, paths, settings, paper_ids=args.paper_id,
                                            apply=args.apply)
                else:
                    payload = mark_submitted(
                        db, paths, settings, paper_id=args.paper_id, journal=args.journal,
                        by=args.by, reason=args.reason, evidence=args.evidence,
                        submitted_by=args.submitted_by, version=args.version)
            except (SiteAssignmentError, OSError) as exc:
                print(json.dumps({"status": "refused", "error": str(exc)}, ensure_ascii=False),
                      file=sys.stderr)
                return 1
        elif args.program_command == "assign-handler":
            try:
                payload = assign_submission_handler(
                    db, paths, settings, paper_id=args.paper_id, handler=args.handler,
                    assigned_by=args.by, conditions_met=args.conditions_met,
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
        if args.quota_override and not str(args.quota_override_reason or "").strip():
            print(json.dumps({"status": "failed",
                              "error": "--quota-override needs --quota-override-reason"},
                             ensure_ascii=False), file=sys.stderr)
            return 1
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
            operator_dispatched=True,
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
        if args.quota_override:
            from . import budget as budget_control

            payload["quota_override"] = budget_control.mark_task_quota_override(
                db, task_id, reason=args.quota_override_reason
            )
    else:  # pragma: no cover - argparse enforces the command set.
        raise AssertionError(args.command)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _quota_override_command(budget_control, args, db, settings) -> dict:
    """``program quota-override``: set, revoke or list manual provider overrides."""

    now = budget_control.current_time()
    if args.list:
        return {
            "schema_version": "openlabs.quota_override.v1",
            "active": budget_control.active_quota_overrides(db, settings, now=now),
        }
    if not args.provider:
        raise budget_control.QuotaOverrideError("--provider is required")
    if args.revoke:
        revoked = budget_control.revoke_quota_override(
            db, provider=args.provider, by=args.by, reason=args.reason, now=now
        )
        return {"schema_version": "openlabs.quota_override.v1", "revoked": revoked}
    if not args.until:
        raise budget_control.QuotaOverrideError("--until is required")
    entry = budget_control.set_quota_override(
        db, settings, provider=args.provider, until=args.until, reason=args.reason or "",
        ceiling=args.ceiling, by=args.by, now=now,
    )
    return {"schema_version": "openlabs.quota_override.v1", "set": entry}


if __name__ == "__main__":
    raise SystemExit(main())
