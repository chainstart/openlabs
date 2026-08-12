"""Lifecycle hooks for an orchestrator-generated Codex attempt runtime."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .agent_runtime import runtime_context
from .contracts import validate_result_bundle


def _read_event() -> dict[str, Any]:
    try:
        value = json.load(sys.stdin)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _session_context(context: Mapping[str, Any]) -> dict[str, Any]:
    skills = ", ".join(str(item) for item in context.get("skills", [])) or "the assigned Skill"
    message = (
        f"OpenLabs task {context.get('expected_result', {}).get('task_id')} runs as role "
        f"{context.get('role')}. Invoke {skills}; their trusted project sources are under "
        f"{context.get('skill_source_root')}. You own the scientific analysis, decomposition, "
        "tool use, and route decisions within the time budget. Work only in the private campaign "
        f"workspace {context.get('agent_workspace')}; never modify the canonical campaign "
        f"{context.get('canonical_campaign_workspace')}. Before stopping, atomically write the "
        f"required result bundle to {context.get('result_path')}."
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": message,
        }
    }


def _stop_decision(event: Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, Any]:
    if event.get("stop_hook_active") is True:
        return {}
    result_path = Path(str(context.get("result_path") or "")).expanduser()
    problems: list[str] = []
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        payload = None
        problems.append(f"required result file is missing: {result_path}")
    except (OSError, json.JSONDecodeError) as exc:
        payload = None
        problems.append(f"required result file is unreadable JSON: {exc}")
    if isinstance(payload, Mapping):
        validation = validate_result_bundle(payload)
        problems.extend(validation.errors)
        expected = context.get("expected_result")
        if isinstance(expected, Mapping):
            for key, value in expected.items():
                if payload.get(key) != value:
                    problems.append(f"{key} must be {value!r}")
    elif payload is not None:
        problems.append("result bundle must be a JSON object")
    if not problems:
        return {}
    reason = "OpenLabs result gate is incomplete: " + "; ".join(problems[:8])
    return {"decision": "block", "reason": reason}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("event", choices=("session-start", "stop"))
    parser.add_argument("--context", type=Path, required=True)
    args = parser.parse_args()
    context = runtime_context(args.context.resolve())
    event = _read_event()
    output = (
        _session_context(context)
        if args.event == "session-start"
        else _stop_decision(event, context)
    )
    json.dump(output, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
