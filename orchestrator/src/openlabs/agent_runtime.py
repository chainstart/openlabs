"""Prepare the small, trusted agent runtime surface for one private attempt.

The research agent owns scientific analysis and decisions.  This module only
exposes selected Skills and installs lifecycle hooks that restate the transaction
boundary and validate the result envelope before the agent stops.  The same
Skills, context and Stop gate are generated for Codex (``.agents``/``.codex``)
and Claude Code (``.claude``); the lab runner picks the one its adapter reads.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .contracts import RESULT_SCHEMA, atomic_write_json

RUNTIME_POLICY_SCHEMA = "openlabs.codex_runtime.v1"
# Agent CLIs whose attempts run behind the generated result-gate hooks.  The
# engine requires a passing Stop receipt from every one of them.
HOOK_GATED_ADAPTERS = frozenset({"codex", "claude"})
# Claude Code reads hooks from a settings file passed with ``--settings``; the
# file lives in the attempt-private ``.claude`` runtime directory so the
# operator's user-level settings are never modified.
CLAUDE_SETTINGS_NAME = "openlabs-settings.json"
_SKILL_NAME = re.compile(r"^name:\s*([^\s]+)\s*$", re.MULTILINE)


def _inside(path: Path, root: Path) -> bool:
    resolved = path.resolve()
    base = root.resolve()
    return resolved == base or resolved.is_relative_to(base)


def _skill_name(skill_dir: Path) -> str:
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        raise ValueError(f"Skill has no SKILL.md: {skill_dir}")
    match = _SKILL_NAME.search(skill_file.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"Skill frontmatter has no name: {skill_file}")
    name = match.group(1).strip()
    # Numeric Skill names need quoting in YAML to remain strings.
    if len(name) >= 2 and name[0] == name[-1] and name[0] in {"'", '"'}:
        name = name[1:-1]
    if not re.fullmatch(r"[a-z0-9-]+", name):
        raise ValueError(f"Unsafe Skill name {name!r}: {skill_file}")
    return name


def _replace_runtime_directory(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def configure_codex_runtime(
    campaign_workspace: Path,
    *,
    task: Mapping[str, Any],
    output_path: Path,
    skill_dirs: Iterable[Path],
    available_skill_dirs: Iterable[Path] = (),
) -> dict[str, Any]:
    """Install available Skills while activating only the protocol-selected subset."""

    workspace = campaign_workspace.resolve()
    result = output_path.resolve()
    if not workspace.is_dir() or not _inside(result, workspace):
        raise ValueError("Codex runtime must stay inside the private campaign workspace")

    agents_root = workspace / ".agents"
    codex_root = workspace / ".codex"
    claude_root = workspace / ".claude"
    _replace_runtime_directory(agents_root)
    _replace_runtime_directory(codex_root)
    _replace_runtime_directory(claude_root)
    skills_root = agents_root / "skills"
    optional_root = agents_root / "optional-methods"
    claude_skills_root = claude_root / "skills"
    skills_root.mkdir(parents=True)
    optional_root.mkdir(parents=True)
    codex_root.mkdir(parents=True)
    claude_skills_root.mkdir(parents=True)

    active_sources = tuple(raw_path.expanduser().resolve() for raw_path in skill_dirs)
    active_source_set = set(active_sources)
    installed: dict[str, str] = {}
    active_names: list[str] = []
    optional_methods: list[dict[str, str]] = []
    optional_sources: dict[str, str] = {}
    for raw_path in active_sources:
        skill_dir = raw_path.expanduser().resolve()
        name = _skill_name(skill_dir)
        prior = installed.get(name)
        if prior is not None and prior != str(skill_dir):
            raise ValueError(f"Conflicting Skill name {name!r}: {prior} and {skill_dir}")
        if prior is None:
            (skills_root / name).symlink_to(skill_dir, target_is_directory=True)
            # Claude Code discovers project Skills under ``.claude/skills``.
            (claude_skills_root / name).symlink_to(skill_dir, target_is_directory=True)
            installed[name] = str(skill_dir)
        if name not in active_names:
            active_names.append(name)
    for raw_path in available_skill_dirs:
        skill_dir = raw_path.expanduser().resolve()
        name = _skill_name(skill_dir)
        prior = installed.get(name)
        if prior is not None and prior != str(skill_dir):
            raise ValueError(f"Conflicting Skill name {name!r}: {prior} and {skill_dir}")
        if skill_dir in active_source_set:
            continue
        prior = optional_sources.get(name)
        if prior is not None and prior != str(skill_dir):
            raise ValueError(f"Conflicting optional method {name!r}: {prior} and {skill_dir}")
        if prior is not None:
            continue
        target = optional_root / name
        if not target.exists() and not target.is_symlink():
            target.symlink_to(skill_dir, target_is_directory=True)
        optional_methods.append(
            {"name": name, "path": str(target / "SKILL.md")}
        )
        optional_sources[name] = str(skill_dir)

    expected = {
        "schema_version": RESULT_SCHEMA,
        "task_id": task["task_id"],
        "campaign_id": task["campaign_id"],
        "lab_id": task["lab_id"],
        "domain": task["domain"],
    }
    project = task.get("project")
    protocol_binding: dict[str, Any] | None = None
    if isinstance(project, Mapping):
        binding = {
            "lab_manifest": task.get("lab_manifest"),
            "protocol_id": project.get("protocol_id"),
            "project_config": project.get("config_path"),
            "workstream_state": project.get("workstream_state_path"),
        }
        if any(str(value or "").strip() for value in binding.values()):
            protocol_binding = binding
    skill_invocations = [f"${name}" for name in active_names]
    hook_receipt_path = codex_root / "hook-receipts.jsonl"
    context = {
        "schema_version": RUNTIME_POLICY_SCHEMA,
        "expected_result": expected,
        "result_path": str(result),
        "agent_workspace": str(workspace),
        "canonical_campaign_workspace": task.get("transaction", {}).get(
            "canonical_campaign_workspace"
        ),
        "role": task.get("agent", {}).get("role"),
        "session_mode": task.get("agent", {}).get("session_mode"),
        "objective": task.get("objective"),
        "project": task.get("project"),
        "protocol_binding": protocol_binding,
        "execution_policy": task.get("execution_policy"),
        "research_program": task.get("research_program"),
        "skills": skill_invocations,
        "optional_methods": optional_methods,
        "skill_source_root": str(skills_root),
        "claude_skill_source_root": str(claude_skills_root),
        "hook_receipt_path": str(hook_receipt_path),
    }
    owner = task.get("owner")
    if isinstance(owner, Mapping):
        # Owner-mode seat: the Stop gate completes the owner's small status packet.
        context["owner"] = {
            key: owner.get(key)
            for key in ("schema_version", "artifact_staging_root", "preregistration_sha256",
                        "work_log", "deadline")
        }
    context_path = atomic_write_json(codex_root / "openlabs-context.json", context)
    # Codex deliberately sanitizes hook subprocess environments.  In particular,
    # it does not preserve the orchestrator's PYTHONPATH, so ``python -m openlabs``
    # cannot be resolved from an isolated attempt workspace unless the generated
    # command carries the package source root explicitly.
    package_source_root = Path(__file__).resolve().parents[1]
    hook_command = [
        "/usr/bin/env",
        f"PYTHONPATH={package_source_root}",
        sys.executable,
        "-m",
        "openlabs.codex_hook",
        "{event}",
        "--context",
        str(context_path),
    ]

    def command(event: str, adapter: str = "codex") -> str:
        argv = [event if item == "{event}" else item for item in hook_command]
        if adapter != "codex":
            argv.extend(["--adapter", adapter])
        return shlex.join(argv)

    def lifecycle_hooks(adapter: str) -> dict[str, Any]:
        return {
            "SessionStart": [
                {
                    "matcher": "startup|resume|clear|compact",
                    "hooks": [
                        {
                            "type": "command",
                            "command": command("session-start", adapter),
                            "timeout": 10,
                        }
                    ],
                }
            ],
            "Stop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": command("stop", adapter),
                            "timeout": 330,
                        }
                    ]
                }
            ],
        }

    hooks = {"hooks": lifecycle_hooks("codex")}
    hooks_path = atomic_write_json(codex_root / "hooks.json", hooks)
    # The same result gate and receipt file serve a Claude Code attempt.  Claude
    # silently ignores a settings file that fails validation, so this file holds
    # only the two hooks and the memory exclusion below (both verified with
    # claude 2.1.322 on 2026-11-11); the engine fails closed without a Stop receipt.
    # ``--setting-sources project`` still loads the operator's user-level
    # CLAUDE.md. Exclude it here as well as masking it in the bubblewrap sandbox,
    # so it stays hidden when no sandbox is available.
    claude_settings_path = atomic_write_json(
        claude_root / CLAUDE_SETTINGS_NAME,
        {
            "hooks": lifecycle_hooks("claude"),
            "claudeMdExcludes": [str(Path.home() / ".claude" / "CLAUDE.md")],
        },
    )
    return {
        "schema_version": RUNTIME_POLICY_SCHEMA,
        "sandbox": "danger-full-access",
        "hooks": str(hooks_path),
        "claude_settings": str(claude_settings_path),
        "hook_trust": "orchestrator-generated",
        "hook_receipts": str(hook_receipt_path),
        "skills": skill_invocations,
        "optional_methods": optional_methods,
    }


def runtime_context(path: Path) -> dict[str, Any]:
    """Read a generated context with a strict, testable outer shape."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != RUNTIME_POLICY_SCHEMA:
        raise ValueError(f"Invalid OpenLabs Codex runtime context: {path}")
    return payload
