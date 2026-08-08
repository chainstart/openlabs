"""Minimal module entrypoint used by people and the systemd timer."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .config import load_settings, workspace_paths
from .db import FactoryDB
from .engine import tick
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m openlabs")
    parser.add_argument("--workspace", help="Override OPENLABS_WORKSPACE")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Initialize the local SQLite schema")
    commands.add_parser("tick", help="Run one idempotent scheduling tick")
    commands.add_parser("status", help="Print task counts")

    enqueue = commands.add_parser("enqueue", help="Add one bounded task")
    enqueue.add_argument("--campaign-id", required=True)
    enqueue.add_argument("--domain", required=True, choices=("math", "ai", "materials"))
    enqueue.add_argument("--title")
    enqueue.add_argument("--task-type", default="research")
    enqueue.add_argument("--objective", required=True)
    enqueue.add_argument("--priority", type=int, default=0)
    enqueue.add_argument("--skill")
    enqueue.add_argument(
        "--agent-role",
        choices=("researcher", "experimenter", "writer", "reviewer"),
        help="Defaults from task type; reviewers always start blank",
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

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(argv) if argv is not None else sys.argv[1:]
    if arguments is not None and arguments[:1] == ["_worker"]:
        if len(arguments) != 2:
            raise SystemExit("usage: python -m openlabs _worker JOB_FILE")
        return run_worker(arguments[1])
    args = _parser().parse_args(arguments)
    paths = workspace_paths(args.workspace)
    paths.ensure_runtime_directories()
    db = FactoryDB(paths.database_file)
    db.initialize()
    settings = load_settings(paths)
    if args.command == "init":
        payload = {"schema_version": "openlabs.init.v1", "database": str(paths.database_file)}
    elif args.command == "tick":
        payload = tick(paths, load_settings(paths)).to_dict()
    elif args.command == "status":
        reserved = db.active_resource_totals()
        payload = {
            "schema_version": "openlabs.status.v1",
            "tasks": db.status_counts(),
            "research_records": db.research_record_counts(),
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
                    "agent_seconds_used": item["agent_seconds_used"],
                    "max_agent_seconds": item["max_agent_seconds"],
                }
                for item in db.campaigns()
            ],
        }
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
            runner=args.runner,
            max_attempts=settings.max_attempts,
            agent_role=args.agent_role or _agent_role(args.task_type),
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
