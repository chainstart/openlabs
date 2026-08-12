"""Lifecycle hooks for an orchestrator-generated Codex attempt runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .agent_runtime import runtime_context
from .authority import action_authority_errors, resolve_workspace_authority
from .contracts import validate_result_bundle
from .reproduction import preflight_reproductions

HOOK_RECEIPT_SCHEMA = "openlabs.codex_hook_receipt.v1"
HOOK_VERSION = "openlabs.codex_hook.v2"


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
        policy_paths = [
            Path(str(item)).expanduser().resolve()
            for item in context.get("authority_policy_paths", [])
            if str(item).strip()
        ]
        authority = resolve_workspace_authority(
            Path(str(context.get("agent_workspace") or "")).expanduser().resolve(),
            policy_paths,
        )
        problems.extend(
            action_authority_errors(
                payload,
                current_role=str(context.get("role") or "researcher"),
                authority=authority,
            )
        )
        if not validation.errors and str(payload.get("status") or "") in {
            "completed",
            "succeeded",
        }:
            reproduction_errors, _receipts = preflight_reproductions(
                payload,
                workspace_root=Path(str(context.get("agent_workspace") or ""))
                .expanduser()
                .resolve(),
            )
            problems.extend(reproduction_errors)
    elif payload is not None:
        problems.append("result bundle must be a JSON object")
    if not problems:
        return {}
    reason = "OpenLabs result gate is incomplete: " + "; ".join(problems[:8])
    return {"decision": "block", "reason": reason}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _receipt_outcome(event_name: str, output: Mapping[str, Any]) -> str:
    if event_name == "session-start":
        return "context_injected"
    if output.get("decision") is None and output.get("reason") is None:
        # Stop-hook re-entry is deliberately ignored to prevent an infinite
        # continue loop, but it is not evidence that the result gate ran.
        return "result_gate_passed"
    if output.get("decision") == "block":
        return "result_gate_blocked"
    return "result_gate_passed"


def _append_hook_receipt(
    context: Mapping[str, Any],
    *,
    event_name: str,
    event: Mapping[str, Any],
    output: Mapping[str, Any],
    started_at: str,
    finished_at: str,
) -> None:
    raw_path = str(context.get("hook_receipt_path") or "").strip()
    if not raw_path:
        return
    path = Path(raw_path).expanduser().resolve()
    workspace = Path(str(context.get("agent_workspace") or "")).expanduser().resolve()
    expected = (workspace / ".codex" / "hook-receipts.jsonl").resolve()
    if path != expected:
        raise ValueError("Hook receipt path is outside the generated runtime directory")
    reason = str(output.get("reason") or "")
    receipt = {
        "schema_version": HOOK_RECEIPT_SCHEMA,
        "hook_version": HOOK_VERSION,
        "hook_event_name": "SessionStart" if event_name == "session-start" else "Stop",
        "started_at": started_at,
        "finished_at": finished_at,
        "exit_code": 0,
        "session_id": event.get("session_id"),
        "turn_id": event.get("turn_id"),
        "stop_hook_active": event.get("stop_hook_active") is True,
        "outcome": (
            "stop_reentry_ignored"
            if event_name == "stop" and event.get("stop_hook_active") is True
            else _receipt_outcome(event_name, output)
        ),
        "decision": output.get("decision"),
        "output_summary": reason[:512] if reason else _receipt_outcome(event_name, output),
        "output_sha256": hashlib.sha256(
            json.dumps(output, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(descriptor, line)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("event", choices=("session-start", "stop"))
    parser.add_argument("--context", type=Path, required=True)
    args = parser.parse_args()
    context = runtime_context(args.context.resolve())
    event = _read_event()
    started_at = _utc_now()
    output = (
        _session_context(context)
        if args.event == "session-start"
        else _stop_decision(event, context)
    )
    _append_hook_receipt(
        context,
        event_name=args.event,
        event=event,
        output=output,
        started_at=started_at,
        finished_at=_utc_now(),
    )
    json.dump(output, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
