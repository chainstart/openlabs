"""Set up a separate orchestrator instance that shares the data and artifact stores.

``python -m openlabs program init-instance`` prints (dry run, the default) or
creates (``--write``) everything one named instance needs:

- ``<instance-dir>/database/``: its own runtime database directory (empty; the
  first tick creates the SQLite file) with its own job/result inbox;
- ``<instance-dir>/openlabs.toml``: the repository's ``config/openlabs.toml``
  with the instance settings applied (the repository file is never changed);
- ``<instance-dir>/instance.env``: ``OPENLABS_INSTANCE``,
  ``OPENLABS_DATABASE_ROOT``, ``OPENLABS_CONFIG_FILE`` (read by
  ``bin/openlabs-container-loop``);
- ``<instance-dir>/state/``: loop lock, pid and logs;
- in the shared data repository, one research-program project per domain under
  ``workspaces/<domain>/instances/<name>/projects/`` (never scanned by the
  default instance), plus an empty topic ledger and asset index under
  ``registry/instances/<name>/``.

Idempotent: an existing file is never overwritten (it is reported as
``unchanged`` or ``differs``), except the instance TOML with ``--update-config``,
which keeps the previous file as ``openlabs.toml.<timestamp>.bak``.
"""

from __future__ import annotations

import json
import re
import shutil
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .assets import empty_index
from .config import INSTANCE_NAME, WorkspacePaths
from .labs import discover_labs, lab_for_domain
from .program import empty_ledger

SCHEMA = "openlabs.instance_init.v1"
# Mathematics needs the WSL host's dedicated memory cap; the container launcher
# refuses it, so a container instance gets no mathematics project.
PROGRAM_DOMAINS = ("ai", "biology", "materials", "physics", "quant")
CONTAINER_COMPUTE_LOCATIONS = ("container_cpu", "container_gpu", "ailab")

RUNNERS: dict[str, dict[str, str]] = {
    "lead_gpt": {"provider": "openai-codex", "tier": "lead", "model": "gpt-6-astra"},
    "lead_claude": {"provider": "anthropic", "tier": "lead", "model": "claude-fable-5-2"},
    "worker_gpt": {"provider": "openai-codex", "tier": "worker", "model": "gpt-6.1-sol"},
    "worker_claude": {"provider": "anthropic", "tier": "worker", "model": "claude-opus-5-5"},
    "light_gpt": {"provider": "openai-codex", "tier": "light", "model": "gpt-6-luna"},
    "light_claude": {"provider": "anthropic", "tier": "light", "model": "claude-haiku-5-5"},
}

# Safe first-enable order: observe the research program and quota routing
# first; asset reuse, retrospectives, release and delivery come later (full).
PRESETS: dict[str, dict[str, bool]] = {
    "observe": {
        "program.enabled": True,
        "routing (six [runners])": True,
        "program.enforce_admission": True,
        "program.assets.enabled": False,
        "program.assets.retrospective_enabled": False,
        "program.auto_handoff": False,
        "program.auto_release": False,
    },
    "full": {
        "program.enabled": True,
        "routing (six [runners])": True,
        "program.enforce_admission": True,
        "program.assets.enabled": True,
        "program.assets.retrospective_enabled": True,
        "program.auto_handoff": True,
        "program.auto_release": True,
    },
}


# Throughput settings both presets recommend (the repository defaults keep the
# original single-scout, static-ceiling, headroom-ranked behaviour):
# * one scout per domain may run at once, limited by the candidate pool;
# * two admission batches per domain may be reviewed at once;
# * each quota window should be ~90% used when it resets (the last tenth, and
#   the stricter review/lead reserves, stay for reviews and decisions), work is
#   spread by relative abundance, stale Codex readings are refreshed from the
#   session file every 10 minutes and extrapolated for up to 48 hours;
# * the launch ceiling adapts to demand, measured load (80% target) and quota
#   pace below max_parallel_agents.
THROUGHPUT_PROGRAM: dict[str, Any] = {
    "max_concurrent_scouts": len(PROGRAM_DOMAINS),
    "max_admissions_per_domain": 2,
}
THROUGHPUT_ROUTING: dict[str, Any] = {
    "utilization_target": 0.9,
    "stale_refresh_minutes": 10,
    "stale_estimate_hours": 48,
}
THROUGHPUT_BUDGET: dict[str, Any] = {
    "adaptive_parallel": True,
    "adaptive_step": 2,
    "host_utilization_target": 0.8,
    "ailab_utilization_target": 0.9,
}


class InstanceInitError(ValueError):
    """The instance cannot be set up as requested."""


@dataclass
class _Action:
    path: Path
    kind: str  # "directory" | "file"
    content: str | None = None
    status: str = ""


def _toml_key(key: str) -> str:
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else json.dumps(key)


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    raise InstanceInitError(f"cannot write {type(value).__name__} to TOML")


def render_toml(document: dict[str, Any], header: str = "") -> str:
    """Minimal TOML writer for the scalar/array/table shapes openlabs.toml uses."""

    lines: list[str] = [header.rstrip()] if header else []

    def table(prefix: tuple[str, ...], body: dict[str, Any]) -> None:
        scalars = {k: v for k, v in body.items() if not isinstance(v, dict)}
        tables = {k: v for k, v in body.items() if isinstance(v, dict)}
        if prefix and (scalars or not tables):
            lines.append("")
            lines.append("[" + ".".join(_toml_key(part) for part in prefix) + "]")
        for key, value in scalars.items():
            lines.append(f"{_toml_key(key)} = {_toml_value(value)}")
        for key, value in tables.items():
            table((*prefix, key), value)

    table((), document)
    return "\n".join(lines).lstrip("\n") + "\n"


def instance_settings(
    repository: dict[str, Any],
    *,
    name: str,
    preset: str,
    paper_writing_command: list[str] | None,
    git_user_name: str | None,
    git_user_email: str | None,
) -> dict[str, Any]:
    """The repository settings with one instance's overrides applied."""

    if preset not in PRESETS:
        raise InstanceInitError(f"unknown preset {preset!r}; choose one of {sorted(PRESETS)}")
    flags = PRESETS[preset]
    document = json.loads(json.dumps(repository))  # deep copy of plain TOML data
    program = document.setdefault("program", {})
    program.update(
        {
            "enabled": flags["program.enabled"],
            "max_active_topics": 5,
            "ledger_path": f"registry/instances/{name}/topic-ledger.json",
            "asset_index_path": f"registry/instances/{name}/reusable-assets.json",
            "enforce_admission": flags["program.enforce_admission"],
            "domains": list(PROGRAM_DOMAINS),
            "compute_locations": list(CONTAINER_COMPUTE_LOCATIONS),
            "auto_handoff": flags["program.auto_handoff"],
            "auto_release": flags["program.auto_release"],
        }
    )
    if paper_writing_command:
        program["paper_writing_command"] = list(paper_writing_command)
    git = program.setdefault("git", {})
    if git_user_name:
        git["user_name"] = git_user_name
    if git_user_email:
        git["user_email"] = git_user_email
    assets = program.setdefault("assets", {})
    assets.update(
        {
            "enabled": flags["program.assets.enabled"],
            "retrospective_enabled": flags["program.assets.retrospective_enabled"],
            "root": f"assets/instances/{name}",
        }
    )
    program.update(THROUGHPUT_PROGRAM)
    budget = document.setdefault("budget", {})
    budget["max_parallel_agents"] = 3
    budget.update(THROUGHPUT_BUDGET)
    document.setdefault("routing", {}).update(THROUGHPUT_ROUTING)
    document["runners"] = {runner: dict(spec) for runner, spec in RUNNERS.items()}
    return document


def _project_files(name: str, domain: str, primary_skill: str) -> dict[str, dict[str, Any]]:
    project_id = f"{name}-{domain}-research-program"
    scout_id = f"{name}-{domain}-program-scout"
    admission_id = f"{name}-{domain}-program-admission"
    project = {
        "schema_version": "openlabs.project.v1",
        "project_id": project_id,
        "domain": domain,
        "status": "active",
        "program": True,
        "objective": (
            f"Propose, admit and run computational, real-data {domain} research topics under "
            f"the research program's slot limit and independent admission gate ({name} "
            "instance)."
        ),
        "protocol": {"id": "research-program", "primary_skill": primary_skill},
        "execution": {
            "default_session_mode": "resume",
            "fresh_session_boundaries": [
                "independent_replication",
                "adversarial_review",
                "portfolio_review",
                "route_reselection",
            ],
        },
        "portfolio": {
            "allow_dynamic_candidate_workstreams": True,
            "candidate_state_template": {
                "schema_version": "openlabs.research_program_state.v1",
                "status": "active",
                "research_log": [],
            },
            "candidate_maturation_instruction": (
                "Keep the pre-registered primary endpoint fixed; report a failed endpoint as "
                "such and stop when its stop rule fires."
            ),
        },
        "workstreams": [
            {
                "workstream_id": scout_id,
                "title": f"{domain} topic scout ({name})",
                "state_path": "scout_state.json",
                "agent_role": "researcher",
                "session_mode": "fresh",
                "continuation": "on_demand",
                "wall_seconds": 7200,
            },
            {
                "workstream_id": admission_id,
                "title": f"{domain} admission gate ({name})",
                "state_path": "admission_state.json",
                "agent_role": "reviewer",
                "session_mode": "fresh",
                "continuation": "review_on_new_results",
                "spawn_candidate_workstreams": True,
                "review_batch_size": 6,
            },
        ],
    }

    def state(workstream_id: str, role: str) -> dict[str, Any]:
        return {
            "schema_version": "openlabs.research_program_state.v1",
            "project_id": project_id,
            "workstream_id": workstream_id,
            "program_role": role,
            "status": "active",
        }

    return {
        "project.json": project,
        "scout_state.json": state(scout_id, "scout"),
        "admission_state.json": state(admission_id, "admission"),
    }


def _json_text(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def _check_instance_dir(paths: WorkspacePaths, instance_dir: Path) -> None:
    shared = {
        "code repository": paths.code,
        "data repository": paths.data,
        "artifact store": paths.artifacts,
        "default runtime database": paths.workspace / "openlabs-database",
    }
    for label, root in shared.items():
        root = root.resolve()
        if instance_dir == root or instance_dir.is_relative_to(root) or root.is_relative_to(
            instance_dir
        ):
            raise InstanceInitError(f"instance directory overlaps the {label}: {root}")


def plan_instance(
    paths: WorkspacePaths,
    *,
    name: str,
    instance_dir: Path,
    preset: str = "observe",
    paper_writing_command: list[str] | None = None,
    git_user_name: str | None = None,
    git_user_email: str | None = None,
) -> tuple[list[_Action], dict[str, Any]]:
    if not INSTANCE_NAME.fullmatch(name):
        raise InstanceInitError(f"instance name must be lower-case letters, digits and '-': {name!r}")
    instance_dir = instance_dir.expanduser().resolve()
    _check_instance_dir(paths, instance_dir)
    repository_config = paths.code / "config" / "openlabs.toml"
    with repository_config.open("rb") as handle:
        repository = tomllib.load(handle)
    settings = instance_settings(
        repository,
        name=name,
        preset=preset,
        paper_writing_command=paper_writing_command,
        git_user_name=git_user_name,
        git_user_email=git_user_email,
    )
    database = instance_dir / "database"
    config_file = instance_dir / "openlabs.toml"
    header = (
        f"# OpenLabs instance {name!r}, preset {preset!r}. Generated by\n"
        "# `python -m openlabs program init-instance` from the repository's\n"
        "# config/openlabs.toml (comments there explain every key). Edit this file, not\n"
        "# the repository one: only this instance reads it (OPENLABS_CONFIG_FILE).\n"
    )
    environment = (
        f"# OpenLabs instance {name!r}: read by bin/openlabs-container-loop (parsed, never\n"
        "# sourced). The data and artifact repositories stay shared with other instances.\n"
        f"OPENLABS_WORKSPACE={paths.workspace}\n"
        f"OPENLABS_INSTANCE={name}\n"
        f"OPENLABS_DATABASE_ROOT={database}\n"
        f"OPENLABS_CONFIG_FILE={config_file}\n"
    )
    actions: list[_Action] = [
        _Action(instance_dir, "directory"),
        _Action(database / "live", "directory"),
        _Action(database / "inbox" / "jobs", "directory"),
        _Action(database / "inbox" / "results", "directory"),
        _Action(instance_dir / "state", "directory"),
        _Action(config_file, "file", render_toml(settings, header)),
        _Action(instance_dir / "instance.env", "file", environment),
    ]
    labs = discover_labs(paths.code)
    projects: list[str] = []
    for domain in PROGRAM_DOMAINS:
        lab = lab_for_domain(labs, domain)
        protocol = lab.protocol("research-program")
        if protocol is None:
            raise InstanceInitError(f"lab {lab.lab_id} does not register research-program")
        files = _project_files(name, domain, protocol.primary_skill)
        root = (
            paths.data / "workspaces" / domain / "instances" / name / "projects"
            / files["project.json"]["project_id"]
        )
        projects.append(str(root / "project.json"))
        for file_name, payload in files.items():
            actions.append(_Action(root / file_name, "file", _json_text(payload)))
    registry = paths.data / "registry" / "instances" / name
    actions.append(_Action(registry / "topic-ledger.json", "file", _json_text(empty_ledger())))
    actions.append(_Action(registry / "reusable-assets.json", "file", _json_text(empty_index())))
    summary = {
        "instance": name,
        "instance_dir": str(instance_dir),
        "preset": preset,
        "switches": PRESETS[preset],
        "database_root": str(database),
        "config_file": str(config_file),
        "projects": projects,
        "ledger_path": settings["program"]["ledger_path"],
        "asset_index_path": settings["program"]["asset_index_path"],
        "attempt_workspaces": str(paths.artifacts / "instances" / name / "attempt-workspaces"),
        "runners": {runner: spec["model"] for runner, spec in RUNNERS.items()},
    }
    return actions, summary


def init_instance(
    paths: WorkspacePaths,
    *,
    name: str,
    instance_dir: Path,
    preset: str = "observe",
    write: bool = False,
    update_config: bool = False,
    paper_writing_command: list[str] | None = None,
    git_user_name: str | None = None,
    git_user_email: str | None = None,
) -> dict[str, Any]:
    actions, summary = plan_instance(
        paths,
        name=name,
        instance_dir=instance_dir,
        preset=preset,
        paper_writing_command=paper_writing_command,
        git_user_name=git_user_name,
        git_user_email=git_user_email,
    )
    config_file = Path(summary["config_file"])
    for action in actions:
        if action.kind == "directory":
            action.status = "exists" if action.path.is_dir() else "create"
            if write and action.status == "create":
                action.path.mkdir(parents=True, exist_ok=True)
            continue
        assert action.content is not None
        if not action.path.exists():
            action.status = "create"
        elif action.path.read_text(encoding="utf-8") == action.content:
            action.status = "unchanged"
        elif action.path == config_file and update_config:
            action.status = "update"
        else:
            action.status = "differs"  # kept as is; never overwritten
        if not write or action.status not in {"create", "update"}:
            continue
        action.path.parent.mkdir(parents=True, exist_ok=True)
        if action.status == "update":
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            shutil.copy2(action.path, action.path.with_name(f"{action.path.name}.{stamp}.bak"))
        temporary = action.path.with_name(f".{action.path.name}.tmp")
        temporary.write_text(action.content, encoding="utf-8")
        temporary.replace(action.path)
    return {
        "schema_version": SCHEMA,
        "dry_run": not write,
        **summary,
        "actions": [
            {"path": str(action.path), "kind": action.kind, "status": action.status}
            for action in actions
        ],
        "next": (
            "bin/openlabs-container-loop --instance-dir "
            f"{summary['instance_dir']} start"
        ),
    }
