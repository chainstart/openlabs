"""Prepare the small, trusted Codex runtime surface for one private attempt.

The research agent owns scientific analysis and decisions.  This module only
exposes selected Skills and installs lifecycle hooks that restate the transaction
boundary and validate the result envelope before Codex stops.
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
) -> dict[str, Any]:
    """Install attempt-local Skill links, concise context, and trusted hooks."""

    workspace = campaign_workspace.resolve()
    result = output_path.resolve()
    if not workspace.is_dir() or not _inside(result, workspace):
        raise ValueError("Codex runtime must stay inside the private campaign workspace")

    agents_root = workspace / ".agents"
    codex_root = workspace / ".codex"
    _replace_runtime_directory(agents_root)
    _replace_runtime_directory(codex_root)
    skills_root = agents_root / "skills"
    skills_root.mkdir(parents=True)
    codex_root.mkdir(parents=True)

    installed: dict[str, str] = {}
    for raw_path in skill_dirs:
        skill_dir = raw_path.expanduser().resolve()
        name = _skill_name(skill_dir)
        prior = installed.get(name)
        if prior is not None and prior != str(skill_dir):
            raise ValueError(f"Conflicting Skill name {name!r}: {prior} and {skill_dir}")
        if prior is not None:
            continue
        (skills_root / name).symlink_to(skill_dir, target_is_directory=True)
        installed[name] = str(skill_dir)

    expected = {
        "schema_version": RESULT_SCHEMA,
        "task_id": task["task_id"],
        "campaign_id": task["campaign_id"],
        "lab_id": task["lab_id"],
        "domain": task["domain"],
    }
    skill_invocations = [f"${name}" for name in installed]
    context = {
        "schema_version": RUNTIME_POLICY_SCHEMA,
        "expected_result": expected,
        "result_path": str(result),
        "agent_workspace": str(workspace),
        "canonical_campaign_workspace": task.get("transaction", {}).get(
            "canonical_campaign_workspace"
        ),
        "role": task.get("agent", {}).get("role"),
        "objective": task.get("objective"),
        "skills": skill_invocations,
        "skill_source_root": str(skills_root),
    }
    context_path = atomic_write_json(codex_root / "openlabs-context.json", context)
    hook_command = [
        sys.executable,
        "-m",
        "openlabs.codex_hook",
        "{event}",
        "--context",
        str(context_path),
    ]

    def command(event: str) -> str:
        return shlex.join(event if item == "{event}" else item for item in hook_command)

    hooks = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "startup|resume|clear|compact",
                    "hooks": [
                        {
                            "type": "command",
                            "command": command("session-start"),
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
                            "command": command("stop"),
                            "timeout": 10,
                        }
                    ]
                }
            ],
        }
    }
    hooks_path = atomic_write_json(codex_root / "hooks.json", hooks)
    return {
        "schema_version": RUNTIME_POLICY_SCHEMA,
        "sandbox": "workspace-write",
        "hooks": str(hooks_path),
        "hook_trust": "orchestrator-generated",
        "skills": skill_invocations,
    }


def runtime_context(path: Path) -> dict[str, Any]:
    """Read a generated context with a strict, testable outer shape."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != RUNTIME_POLICY_SCHEMA:
        raise ValueError(f"Invalid OpenLabs Codex runtime context: {path}")
    return payload
