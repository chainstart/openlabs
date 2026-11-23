"""Lifecycle hooks for an orchestrator-generated agent attempt runtime.

Codex reads them from ``.codex/hooks.json``; Claude Code from the generated
``.claude/openlabs-settings.json`` (``--adapter claude``).  Both CLIs share the
hook protocol used here: JSON event on stdin, ``{"decision": "block", "reason"}``
on stdout to continue a Stop, ``hookSpecificOutput.additionalContext`` for
SessionStart.  The result gate and the receipt file are the same for both.

The Antigravity CLI (``--adapter agy``) reads ``.agents/hooks.json`` and speaks a
camelCase dialect: ``conversationId``/``transcriptPath``/``executionNum`` in, and
``{"decision": "continue", "reason"}`` (Stop) or ``{"injectSteps": [...]}``
(SessionStart) out. It is translated at the edges; the gate itself is shared.
"""

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
from .contracts import COMMITTABLE_RESULT_STATUSES, validate_result_bundle
from .result_normalize import normalize_result
from .gates import preregistration_advisories, preregistration_blockers
from .labs import load_lab
from .protocols import validate_protocol_state
from .reproduction import preflight_reproductions

HOOK_RECEIPT_SCHEMA = "openlabs.codex_hook_receipt.v1"
HOOK_VERSION = "openlabs.codex_hook.v4"


def _read_event() -> dict[str, Any]:
    try:
        value = json.load(sys.stdin)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _agy_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """An Antigravity hook payload in the Codex/Claude field names the gate reads.

    agy 1.5.14 counts Stop executions in ``executionNum`` (0 first) and documents
    ``continuationActive``; either marks the re-entry after a continuation (measured
    2026-11-23: ``continuationActive`` stayed false on the second Stop).
    """

    try:
        executions = int(event.get("executionNum") or 0)
    except (TypeError, ValueError):
        executions = 0
    return {
        **event,
        "session_id": event.get("conversationId"),
        "transcript_path": event.get("transcriptPath"),
        "stop_hook_active": event.get("continuationActive") is True or executions > 0,
    }


def _agy_output(event_name: str, output: Mapping[str, Any]) -> dict[str, Any]:
    """The shared hook output in the Antigravity hook contract."""

    if event_name == "session-start":
        specific = output.get("hookSpecificOutput")
        message = specific.get("additionalContext") if isinstance(specific, Mapping) else None
        if not message:
            return {}
        return {"injectSteps": [{"systemMessage": {"systemMessage": str(message)}}]}
    if output.get("decision") == "block":
        return {"decision": "continue", "reason": str(output.get("reason") or "")}
    return {}


def _owner_session_context(context: Mapping[str, Any]) -> dict[str, Any]:
    owner = context.get("owner") if isinstance(context.get("owner"), Mapping) else {}
    # Fixed wording first, the seat's ids and paths after it (2026-11-20, prompt caching).
    message = (
        "OpenLabs owner seat: you own this topic and decide the next step yourself. Work "
        "only in the private campaign workspace; never modify the canonical campaign. Keep "
        "the work log and OWNER_HANDOVER.md next to it current and, before the seat ends, "
        "write the status JSON to the result path. This seat: "
        f"{context.get('expected_result', {}).get('task_id')}; workspace "
        f"{context.get('agent_workspace')}; canonical campaign "
        f"{context.get('canonical_campaign_workspace')}; work log {owner.get('work_log')}; "
        f"ends {owner.get('deadline')}; result path {context.get('result_path')}."
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": message,
        }
    }


def _session_context(context: Mapping[str, Any], adapter: str = "codex") -> dict[str, Any]:
    if isinstance(context.get("owner"), Mapping):
        return _owner_session_context(context)
    if adapter == "claude":
        # Claude Code invokes Skills by bare name through its Skill tool.
        names = [str(item).removeprefix("$") for item in context.get("skills", [])]
        skills = (
            "the Skills " + ", ".join(names) + " (Skill tool)" if names else "the assigned Skill"
        )
        skill_root = context.get("claude_skill_source_root") or context.get("skill_source_root")
    elif adapter == "agy":
        # Antigravity discovers workspace Skills under ``.agents/skills`` by bare name.
        names = [str(item).removeprefix("$") for item in context.get("skills", [])]
        skills = "the Skills " + ", ".join(names) if names else "the assigned Skill"
        skill_root = context.get("skill_source_root")
    else:
        skills = ", ".join(str(item) for item in context.get("skills", [])) or "the assigned Skill"
        skill_root = context.get("skill_source_root")
    message = (
        f"OpenLabs task {context.get('expected_result', {}).get('task_id')} runs as role "
        f"{context.get('role')}. Invoke {skills}; their trusted project sources are under "
        f"{skill_root}. You own the scientific analysis, decomposition, "
        "tool use, and route decisions within the time budget. Work only in the private campaign "
        f"workspace {context.get('agent_workspace')}; never modify the canonical campaign "
        f"{context.get('canonical_campaign_workspace')}. Before stopping, atomically write the "
        f"required result bundle to {context.get('result_path')}."
    )
    if context.get("artifact_staging_root"):
        message += (
            " The workspace takes only small text files (<= 5 MB). Put downloaded documents "
            "(PDF specifications, papers), logs, archives and other payloads under "
            f"{context.get('artifact_staging_root')} and declare each in result.artifacts "
            "with its file:// URI and SHA-256; files elsewhere (/tmp, home) cannot be cited."
        )
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": message,
        }
    }


def _protocol_gate_problems(context: Mapping[str, Any]) -> list[str]:
    binding = context.get("protocol_binding")
    if binding is None:
        return []
    if not isinstance(binding, Mapping):
        return ["protocol binding must be an object"]
    required = ("lab_manifest", "protocol_id", "project_config", "workstream_state")
    values = {key: str(binding.get(key) or "").strip() for key in required}
    missing = [key for key, value in values.items() if not value]
    if missing:
        return ["protocol binding is incomplete: " + ", ".join(missing)]
    try:
        lab = load_lab(values["lab_manifest"])
        protocol = lab.protocol(values["protocol_id"])
        if protocol is None:
            return [
                f"lab {lab.lab_id} does not register protocol {values['protocol_id']!r}"
            ]
        validation = validate_protocol_state(
            lab,
            protocol,
            project_path=Path(values["project_config"]),
            workstream_path=Path(values["workstream_state"]),
            mode="commit",
        )
    except Exception as exc:  # noqa: BLE001 - the Stop gate must fail closed.
        return [f"protocol validation failed: {exc}"]
    return [f"protocol state: {error}" for error in validation.errors]


def _program_problems(
    payload: Mapping[str, Any], context: Mapping[str, Any]
) -> tuple[list[str], list[str]]:
    """Pre-registration checks of an admitted topic's result: (failures, advisories).

    A declared hash that differs from the ledger fails the gate (the engine would
    reject it too). A missing hash or verdict is only asked for once: the control
    plane fills the hash and reads an unstated verdict as pending.
    """

    program = context.get("research_program")
    expected = program.get("preregistration_sha256") if isinstance(program, Mapping) else None
    if not expected:
        return [], []
    return preregistration_blockers(payload, str(expected)), preregistration_advisories(payload)


def _data_boundary_problems(context: Mapping[str, Any]) -> list[str]:
    """Campaign files the promotion would refuse, while the agent can still move them.

    The same rule as ``attempts.enforce_campaign_data_boundary`` at ingest, where a
    violation discards the whole attempt (2026-11-20: a power scout's AEMO
    specification PDF under evidence/; astro and power reviewers' main.pdf and
    preflight-build.log). Owner seats have their strays moved by ``hook_normalize``
    first, so only what is left is reported.
    """

    from .attempts import ATTEMPT_SCHEMA, AttemptWorkspaceError, campaign_data_boundary_violations

    raw_root = str(context.get("attempt_root") or "").strip()
    if not raw_root:
        return []
    metadata_path = Path(raw_root).expanduser() / "attempt-workspace.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(metadata, Mapping) or metadata.get("schema_version") != ATTEMPT_SCHEMA:
        return []
    campaign = Path(str(metadata.get("staged_campaign_root") or context.get(
        "agent_workspace") or "")).expanduser()
    if not campaign.is_dir():
        return []
    try:
        _changed, violations = campaign_data_boundary_violations(campaign, metadata)
    except (AttemptWorkspaceError, OSError) as exc:
        return [f"campaign data boundary could not be checked: {exc}"]
    if not violations:
        return []
    staging = str(context.get("artifact_staging_root") or metadata.get(
        "artifact_staging_root") or "the artifact staging root")
    return [
        "campaign data boundary: the workspace takes only small text files (<= 5 MB; notes, "
        "JSON, CSV, scripts, receipts); move these to the artifact staging root "
        f"{staging} (same relative path), declare each in result.artifacts with its "
        "file:// URI and SHA-256, and update any path that cites them (an access_receipt "
        "stays a small text file in the workspace): " + "; ".join(violations[:8])
    ]


def _stop_gate_advisories(context: Mapping[str, Any]) -> list[str]:
    result_path = Path(str(context.get("result_path") or "")).expanduser()
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, Mapping):
        return []
    return _program_problems(payload, context)[1]


def _stop_gate_problems(context: Mapping[str, Any]) -> list[str]:
    result_path = Path(str(context.get("result_path") or "")).expanduser()
    problems: list[str] = []
    if isinstance(context.get("owner"), Mapping):
        # Owner seat: complete the small status packet into a result bundle first.
        from .owner import hook_normalize

        try:
            hook_normalize(context)
        except Exception as exc:  # noqa: BLE001 - the gate below reports what is wrong.
            problems.append(f"owner packet could not be completed: {exc}")
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        payload = None
        problems.append(f"required result file is missing: {result_path}")
    except (OSError, json.JSONDecodeError) as exc:
        payload = None
        problems.append(f"required result file is unreadable JSON: {exc}")
    if isinstance(payload, Mapping):
        # The ingest fixes artifact ids and claim evidence references itself
        # (result_normalize); the gate here judges the form it will commit.
        payload, _registration = normalize_result(payload)
        validation = validate_result_bundle(payload)
        problems.extend(validation.errors)
        problems.extend(_program_problems(payload, context)[0])
        expected = context.get("expected_result")
        if isinstance(expected, Mapping):
            for key, value in expected.items():
                if payload.get(key) != value:
                    problems.append(f"{key} must be {value!r}")
        if (
            not validation.errors
            and str(payload.get("status") or "") in COMMITTABLE_RESULT_STATUSES
        ):
            reproduction_errors, _receipts = preflight_reproductions(
                payload,
                workspace_root=Path(str(context.get("agent_workspace") or ""))
                .expanduser()
                .resolve(),
            )
            problems.extend(reproduction_errors)
            if not reproduction_errors:
                problems.extend(_protocol_gate_problems(context))
    elif payload is not None:
        problems.append("result bundle must be a JSON object")
    problems.extend(_data_boundary_problems(context))
    return problems


def _stop_evaluation(
    event: Mapping[str, Any], context: Mapping[str, Any]
) -> tuple[dict[str, Any], str, str]:
    """Evaluate the result gate once and distinguish continuation from final re-entry."""

    problems = _stop_gate_problems(context)
    if not problems:
        advisories = _stop_gate_advisories(context)
        if advisories and event.get("stop_hook_active") is not True:
            # One more step in this session instead of a later replan task; on
            # re-entry the result passes as it stands.
            reason = "OpenLabs result is complete but should still state: " + "; ".join(
                advisories)
            return {"decision": "block", "reason": reason}, "result_gate_advisory", reason
        return {}, "result_gate_passed", "result_gate_passed"
    reason = "OpenLabs result gate is incomplete: " + "; ".join(problems[:8])
    if event.get("stop_hook_active") is True:
        # Codex has already continued this turn once.  Revalidate the finished
        # result, but do not request another continuation and risk a loop.  The
        # terminal failure receipt keeps the outer orchestrator fail-closed.
        return {}, "result_gate_failed_final", reason
    return {"decision": "block", "reason": reason}, "result_gate_blocked", reason


def _stop_decision(event: Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, Any]:
    output, _outcome, _summary = _stop_evaluation(event, context)
    return output


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _receipt_outcome(event_name: str, output: Mapping[str, Any]) -> str:
    if event_name == "session-start":
        return "context_injected"
    if output.get("decision") is None and output.get("reason") is None:
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
    outcome: str | None = None,
    output_summary: str | None = None,
    adapter: str = "codex",
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
    resolved_outcome = outcome or _receipt_outcome(event_name, output)
    resolved_summary = output_summary or reason or resolved_outcome
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
        "outcome": resolved_outcome,
        "decision": output.get("decision"),
        "output_summary": resolved_summary[:512],
        "output_sha256": hashlib.sha256(
            json.dumps(output, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }
    if adapter != "codex":
        # Claude Code events carry no turn_id but name the session transcript.
        receipt["agent_adapter"] = adapter
        receipt["transcript_path"] = event.get("transcript_path")
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
    parser.add_argument("--adapter", choices=("codex", "claude", "agy"), default="codex")
    args = parser.parse_args()
    context = runtime_context(args.context.resolve())
    event = _read_event()
    if args.adapter == "agy":
        event = _agy_event(event)
    started_at = _utc_now()
    if args.event == "session-start":
        output = _session_context(context, args.adapter)
        outcome = "context_injected"
        output_summary = outcome
    else:
        output, outcome, output_summary = _stop_evaluation(event, context)
    _append_hook_receipt(
        context,
        event_name=args.event,
        event=event,
        output=output,
        started_at=started_at,
        finished_at=_utc_now(),
        outcome=outcome,
        output_summary=output_summary,
        adapter=args.adapter,
    )
    if args.adapter == "agy":
        output = _agy_output(args.event, output)
    json.dump(output, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
