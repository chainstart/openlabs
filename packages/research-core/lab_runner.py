#!/usr/bin/env python3
"""File-only runner shared by labs without importing the OpenLabs control plane."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any

TASK_SCHEMA = "openlabs.task.v3"
RESULT_SCHEMA = "openlabs.result_bundle.v1"
HOOK_RECEIPT_SCHEMA = "openlabs.codex_hook_receipt.v1"
HOOK_RUNTIME_SCHEMA = "openlabs.hook_runtime.v1"
LAB_RUNTIME_SCHEMA = "openlabs.lab_runtime_setup.v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _terminate_process_group(process: subprocess.Popen[str], *, grace_seconds: int = 30) -> None:
    """Terminate one session leader and all of its descendants, then reap it."""

    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=max(1, grace_seconds))
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def _smoke(task: dict[str, Any], manifest: dict[str, Any], output: Path) -> None:
    artifact = output.parent / "smoke-capabilities.json"
    write_json(
        artifact,
        {
            "lab_id": manifest["lab_id"],
            "domain": manifest["domain"],
            "capabilities": manifest.get("capabilities", []),
            "manifest_schema": manifest.get("schema_version"),
        },
    )
    write_json(
        output,
        {
            "schema_version": RESULT_SCHEMA,
            "task_id": task["task_id"],
            "campaign_id": task["campaign_id"],
            "lab_id": manifest["lab_id"],
            "domain": manifest["domain"],
            "status": "completed",
            "summary": f"{manifest['lab_id']} file-contract smoke task completed.",
            "artifacts": [
                {
                    "artifact_id": "smoke-capabilities",
                    "uri": artifact.resolve().as_uri(),
                    "sha256": sha256_file(artifact),
                    "kind": "capability_manifest",
                }
            ],
            "claims": [
                {
                    "claim_id": "lab-file-contract-smoke",
                    "text": (
                        "The lab accepted a versioned task and emitted a hash-bound result bundle."
                    ),
                    "status": "verified",
                    "evidence": ["smoke-capabilities"],
                    "limitations": ["This smoke task makes no scientific claim."],
                }
            ],
            "next_actions": [],
            "paper_candidate": False,
        },
    )


def _agent_request(task: dict[str, Any], manifest: dict[str, Any], output: Path) -> str:
    factory_skill = (
        Path(str(task["lab_manifest"])).resolve().parents[2]
        / "orchestrator"
        / "skills"
        / "openlabs-research-factory"
        / "SKILL.md"
    )
    agent = task["agent"]
    independence = (
        "Start from the frozen evidence only. Do not seek or read a creator's conversation or "
        "another reviewer's draft before submitting this review."
        if agent["role"] == "reviewer"
        else "Keep conclusions inside this role; do not review or approve your own work."
    )
    transaction = task.get("transaction") if isinstance(task.get("transaction"), Mapping) else {}
    transaction_notice = ""
    if transaction.get("mode") == "isolated_attempt_workspace":
        transaction_notice = f"""
This task runs in an isolated transaction workspace:

- writable staged campaign: `{transaction.get("staged_campaign_workspace")}`
- canonical campaign (do not write): `{transaction.get("canonical_campaign_workspace")}`
- promotion rule: `{transaction.get("promotion_policy")}`

Use only staged paths for every edit, generated proof object, state transition, and artifact URI.
The control plane promotes the staged tree only after a completed result passes all gates. A failed,
cancelled, interrupted, or invalid attempt is quarantined automatically. Never copy staged changes
to the canonical campaign yourself.
"""
    runtime_policy = (
        task.get("runtime_policy") if isinstance(task.get("runtime_policy"), Mapping) else {}
    )
    configured_skills = runtime_policy.get("skills")
    optional_methods = runtime_policy.get("optional_methods")
    skill_instruction = (
        "Invoke and follow "
        + ", ".join(str(item) for item in configured_skills)
        + "; read their trusted project copies under `.agents/skills/`."
        if isinstance(configured_skills, list) and configured_skills
        else (
            f"Read and follow the factory coordinator at `{factory_skill}` and the domain Skill "
            f"at `{task.get('skill_path')}`."
        )
    )
    optional_skill_instruction = (
        " Other laboratory method guides are readable but not registered as active Skills: "
        + json.dumps(optional_methods, ensure_ascii=False, sort_keys=True)
        + ". They are optional references, not active constraints; inspect one only when you "
        "decide it helps this research."
        if isinstance(optional_methods, list) and optional_methods
        else ""
    )
    execution = task.get("execution_policy")
    continuity_notice = ""
    if isinstance(execution, Mapping):
        if execution.get("continue_across_protocol_phases") is True:
            continuity_notice = """
Continue inside this Codex process across as many same-role protocol phases and ordinary
checkpoints as the scientific work and wall budget allow. Protocol phases are durable state
records, not process boundaries. Do not stop merely because a phase advanced. Stop only at an
epistemic-role boundary, an explicitly fresh boundary, a terminal scientific result, a genuine
blocker, or when the remaining wall budget is needed to persist a safe result bundle. Other
workers run independently; do not terminate this process merely to make room for them.
"""
    project = task.get("project") if isinstance(task.get("project"), Mapping) else {}
    read_resources = project.get("read_resources", [])
    read_resource_notice = ""
    if isinstance(read_resources, list) and read_resources:
        read_resource_notice = (
            "\nCanonical read-only project resources (inspect freely; never write to them):\n\n"
            + json.dumps(read_resources, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        )
    lab_runtime = task.get("lab_runtime")
    runtime_notice = ""
    if isinstance(lab_runtime, Mapping) and lab_runtime.get("setups"):
        runtime_notice = (
            "\nTrusted laboratory runtimes prepared for this attempt:\n\n"
            + json.dumps(lab_runtime, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        )
    return f"""# OpenLabs autonomous research task

{skill_instruction}{optional_skill_instruction}

Own the analysis, decomposition, tool use, and scientific decisions needed to reach one coherent
checkpoint. You may perform as many safe intermediate research operations as are useful within the
declared budget; do not stop at an administrative micro-step when a material evidence advance is
still feasible. Durable evidence and the result contract, rather than conversational narration,
define completion.

No outer script is authorized to choose your scientific route, rank prospective ideas, or turn a
configured method into a mandatory sequence. Treat project routes, stages, and prior plans as
recoverable context only unless the objective itself logically requires one. Freely create, combine,
switch, pause, revive, or abandon approaches and use any installed laboratory capability that helps.

- task file: `{task.get("_task_file")}`
- task id: `{task["task_id"]}`
- attempt id: `{task["attempt_id"]}`
- campaign id: `{task["campaign_id"]}`
- domain: `{manifest["domain"]}`
- agent role: `{agent["role"]}`
- session policy: `{agent["session_mode"]}`
- runner tier: `{task.get("runner") or "balanced"}`
- reserved resources: `{json.dumps(task["resources"], sort_keys=True)}`
- objective: {task["objective"]}
- input state: `{task.get("input_path")}`
- required result path: `{output}`
- project config: `{project.get("config_path")}`
- workstream state: `{project.get("workstream_state_path")}`

{independence}
{continuity_notice}
{runtime_notice}
{read_resource_notice}
{transaction_notice}

Before stopping, atomically write one `openlabs.result_bundle.v1` JSON object to the required
result path. Do not write to SQLite. Preserve unsupported, negative, and inconclusive outcomes. Do
not submit, publish, spend unbounded resources, or perform another irreversible external action.
For a portfolio-review task, include `candidate_branches` (possibly empty); the control plane will
mechanically start each branch in a separate researcher campaign without altering your judgment.
"""


def _lab_runtime_setup(
    task: dict[str, Any],
    manifest: Mapping[str, Any],
    *,
    workspace: Path,
    agent_workspace: Path,
) -> dict[str, Any]:
    """Run trusted lab-declared setup commands before the Agent starts."""

    configured = manifest.get("runtime_setup", [])
    if not isinstance(configured, list):
        raise TypeError("lab runtime_setup must be an array")
    manifest_path = Path(str(task["lab_manifest"])).expanduser().resolve()
    lab_root = manifest_path.parent
    attempt_root = str(
        (task.get("transaction") or {}).get("attempt_root") or agent_workspace
    )
    replacements = {
        "{python}": sys.executable,
        "{workspace}": str(workspace),
        "{artifacts_root}": str((workspace / "openlabs-artifacts").resolve()),
        "{lab_root}": str(lab_root),
        "{agent_workspace}": str(agent_workspace),
        "{attempt_root}": attempt_root,
        "{task_file}": str(task.get("_task_file") or ""),
    }
    results: list[dict[str, Any]] = []
    for index, item in enumerate(configured):
        if not isinstance(item, Mapping):
            raise TypeError(f"lab runtime_setup[{index}] must be an object")
        setup_id = str(item.get("setup_id") or "").strip()
        raw_command = item.get("command")
        if (
            not setup_id
            or not isinstance(raw_command, list)
            or not raw_command
            or any(not isinstance(token, str) or not token for token in raw_command)
        ):
            raise ValueError(f"invalid lab runtime setup entry {index}")
        command: list[str] = []
        for command_index, raw in enumerate(raw_command):
            token = replacements.get(raw, raw)
            if command_index > 0 and token.endswith(".py") and not Path(token).is_absolute():
                token = str((lab_root / token).resolve())
            command.append(token)
        timeout = item.get("timeout_seconds", 1800)
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1:
            raise ValueError(f"runtime setup {setup_id} timeout must be positive")
        completed = subprocess.run(
            command,
            cwd=lab_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(
                f"runtime setup {setup_id} emitted invalid JSON: {detail[:1000]}"
            ) from exc
        if (
            completed.returncode != 0
            or not isinstance(payload, Mapping)
            or payload.get("valid") is not True
        ):
            detail = (
                payload.get("errors") if isinstance(payload, Mapping) else completed.stderr.strip()
            )
            raise RuntimeError(f"runtime setup {setup_id} failed: {detail}")
        results.append({"setup_id": setup_id, **dict(payload)})
    return {"schema_version": LAB_RUNTIME_SCHEMA, "setups": results}


def _command_template(raw_command: str) -> list[str]:
    try:
        template = json.loads(raw_command)
    except json.JSONDecodeError:
        template = shlex.split(raw_command)
    if (
        not isinstance(template, list)
        or not template
        or any(not isinstance(item, str) for item in template)
    ):
        raise ValueError("Agent command must be a JSON array of argv strings")
    return template


def _configured_agent_adapter(task: Mapping[str, Any]) -> str | None:
    """Return the configured executable name without starting or preparing the agent."""

    runner = str(task.get("runner") or "balanced")
    runner_key = "".join(
        character if character.isalnum() else "_" for character in runner
    ).upper()
    agent = task.get("agent") if isinstance(task.get("agent"), Mapping) else {}
    session_id = (
        str(agent.get("session_id") or "").strip()
        if agent.get("role") != "reviewer" and agent.get("session_mode") == "resume"
        else ""
    )
    command_kind = "RESUME_COMMAND" if session_id else "COMMAND"
    raw_command = os.environ.get(f"OPENLABS_AGENT_{command_kind}_{runner_key}_JSON", "").strip()
    raw_command = raw_command or os.environ.get(f"OPENLABS_AGENT_{command_kind}_JSON", "").strip()
    if not raw_command:
        return None
    return Path(_command_template(raw_command)[0]).name


def _command_option(command: list[str], *names: str) -> str | None:
    for index, token in enumerate(command):
        if token in names and index + 1 < len(command):
            return command[index + 1]
        for name in names:
            prefix = f"{name}="
            if token.startswith(prefix):
                return token[len(prefix) :]
    return None


def _positive_environment_number(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _codex_base_url(command: list[str]) -> str | None:
    override = os.environ.get("OPENLABS_AGENT_PREFLIGHT_URL", "").strip()
    if override:
        return override
    assignments: list[str] = []
    for index, token in enumerate(command):
        if token == "-c" and index + 1 < len(command):
            assignments.append(command[index + 1])
        elif token.startswith("-c="):
            assignments.append(token[3:])
    for assignment in assignments:
        key, separator, raw_value = assignment.partition("=")
        if not separator or not key.strip().endswith(".base_url"):
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value or None
    return None


def _agent_connectivity_preflight(command: list[str]) -> str | None:
    """Return a redacted connectivity error, or None when reachable/not applicable."""

    if Path(command[0]).name != "codex":
        return None
    target = _codex_base_url(command)
    if target is None:
        return None
    parsed = urllib.parse.urlsplit(target)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return "configured Agent provider URL is not a valid HTTP(S) endpoint"
    endpoint = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port is not None:
        endpoint += f":{parsed.port}"
    request = urllib.request.Request(
        target,
        method="HEAD",
        headers={"User-Agent": "openlabs-agent-preflight/1"},
    )
    timeout = _positive_environment_number(
        "OPENLABS_AGENT_PREFLIGHT_TIMEOUT_SECONDS",
        10.0,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout):  # noqa: S310 - configured endpoint
            return None
    except urllib.error.HTTPError:
        # Authentication and method errors still prove DNS, proxy, TLS, and the
        # configured provider endpoint are reachable. Codex owns auth details.
        return None
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        return f"Agent provider {endpoint} is unreachable: {type(exc).__name__}: {exc}"


def _jsonl_startup_health(path: Path) -> tuple[int, bool]:
    """Count transport failures and detect any meaningful Codex progress."""

    failures = 0
    meaningful_progress = False
    if not path.is_file():
        return failures, meaningful_progress
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, Mapping):
            continue
        serialized = json.dumps(event, ensure_ascii=False).lower()
        if any(
            marker in serialized
            for marker in (
                "connection failed",
                "error sending request",
                "waiting for network",
                "connection reset",
                "connection refused",
            )
        ):
            failures += 1
        event_type = str(event.get("type") or "")
        item = event.get("item") if isinstance(event.get("item"), Mapping) else {}
        item_type = str(item.get("type") or "")
        if event_type == "turn.completed" or (
            event_type == "item.completed" and item_type not in {"", "error"}
        ):
            meaningful_progress = True
    return failures, meaningful_progress


def _jsonl_runtime(path: Path) -> dict[str, Any]:
    runtime: dict[str, Any] = {}
    if not path.is_file():
        return runtime
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, Mapping):
            continue
        thread_id = event.get("thread_id") or event.get("session_id")
        if isinstance(thread_id, str) and thread_id:
            runtime["session_id"] = thread_id
        for key in ("model", "provider", "effort", "cost_usd"):
            value = event.get(key)
            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                runtime[key] = value
        usage = event.get("usage")
        if isinstance(usage, Mapping):
            for key in (
                "input_tokens",
                "cached_input_tokens",
                "output_tokens",
                "reasoning_output_tokens",
            ):
                value = usage.get(key)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    runtime[key] = value
    return runtime


def _hook_runtime(path: Path, *, agent_workspace: Path) -> dict[str, Any]:
    """Collect generated lifecycle-hook receipts without interpreting research content."""

    expected = (agent_workspace / ".codex" / "hook-receipts.jsonl").resolve()
    if path.expanduser().resolve() != expected:
        raise ValueError("Generated hook receipt path does not match the attempt runtime")
    events: list[dict[str, Any]] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, Mapping) or event.get("schema_version") != (
                HOOK_RECEIPT_SCHEMA
            ):
                continue
            events.append(dict(event))
    starts = [item for item in events if item.get("hook_event_name") == "SessionStart"]
    stops = [item for item in events if item.get("hook_event_name") == "Stop"]
    return {
        "schema_version": HOOK_RUNTIME_SCHEMA,
        "receipt_path": str(path.resolve()),
        "events": events,
        "session_start_count": len(starts),
        "stop_count": len(stops),
        "stop_passed": any(item.get("outcome") == "result_gate_passed" for item in stops),
        "stop_blocked": sum(item.get("outcome") == "result_gate_blocked" for item in stops),
        "stop_failed_final": sum(
            item.get("outcome") == "result_gate_failed_final" for item in stops
        ),
    }


def _adapter_version(command: list[str]) -> str | None:
    if Path(command[0]).name != "codex":
        return None
    try:
        completed = subprocess.run(
            [command[0], "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    version = completed.stdout.strip()
    return version or None


def _configuration_result(
    task: dict[str, Any],
    manifest: dict[str, Any],
    output: Path,
    summary: str,
) -> None:
    write_json(
        output,
        {
            "schema_version": RESULT_SCHEMA,
            "task_id": task["task_id"],
            "campaign_id": task["campaign_id"],
            "lab_id": manifest["lab_id"],
            "domain": manifest["domain"],
            "status": "needs_human",
            "summary": summary,
            "artifacts": [],
            "claims": [],
            "next_actions": ["Repair the local Agent command configuration, then retry."],
            "paper_candidate": False,
        },
    )


def _remove_flags(command: list[str], names: set[str]) -> list[str]:
    return [
        token
        for token in command
        if token not in names and not any(token.startswith(f"{name}=") for name in names)
    ]


def _remove_value_options(command: list[str], names: set[str]) -> list[str]:
    filtered: list[str] = []
    skip_next = False
    for token in command:
        if skip_next:
            skip_next = False
            continue
        if token in names:
            skip_next = True
            continue
        if any(token.startswith(f"{name}=") for name in names):
            continue
        filtered.append(token)
    if skip_next:
        raise ValueError("Codex command ends with an option that requires a value")
    return filtered


def _config_override_keys(command: list[str]) -> set[str]:
    keys: set[str] = set()
    for index, token in enumerate(command):
        value: str | None = None
        if token in {"-c", "--config"} and index + 1 < len(command):
            value = command[index + 1]
        elif token.startswith(("-c=", "--config=")):
            value = token.split("=", 1)[1]
        if value:
            keys.add(value.split("=", 1)[0].strip())
    return keys


def _prepare_codex_command(
    command: list[str],
    *,
    agent_workspace: Path,
    trust_generated_hooks: bool,
) -> list[str]:
    """Apply the factory's invariant Codex policy without wrapping Codex itself."""

    if Path(command[0]).name != "codex":
        return command
    if len(command) < 2 or command[1] != "exec":
        raise ValueError("The Codex adapter must use `codex exec`")
    forbidden = {
        "--dangerously-bypass-approvals-and-sandbox",
        "--yolo",
    }
    if any(
        token in forbidden or any(token.startswith(f"{name}=") for name in forbidden)
        for token in command
    ):
        raise ValueError("The Codex adapter may not override the factory's full-access policy")
    if any(token == "--add-dir" or token.startswith("--add-dir=") for token in command):
        raise ValueError("OpenLabs Codex tasks do not need extra writable roots in full-access mode")
    if any(
        (token == "--disable" and index + 1 < len(command) and command[index + 1] == "hooks")
        or token == "--disable=hooks"
        for index, token in enumerate(command)
    ):
        raise ValueError("OpenLabs Codex tasks require lifecycle hooks")
    protected_config = {
        "approval_policy",
        "features.hooks",
        "sandbox_mode",
        "sandbox_permissions",
        "sandbox_workspace_write.writable_roots",
        "sandbox_workspace_write.network_access",
    }
    if _config_override_keys(command) & protected_config:
        raise ValueError("The Codex adapter may not override factory runtime policy")
    configured_sandbox = _command_option(command, "--sandbox", "-s")
    if configured_sandbox not in {None, "danger-full-access"}:
        raise ValueError("OpenLabs Codex tasks require the danger-full-access runtime")

    tail = _remove_value_options(command[2:], {"--sandbox", "-s", "--cd", "-C"})
    tail = _remove_flags(
        tail,
        {
            "--approve-for-me",
            "--full-auto",
            "--json",
            "--skip-git-repo-check",
            "--dangerously-bypass-hook-trust",
        },
    )
    policy = [
        "-c",
        'approval_policy="never"',
        "--enable",
        "hooks",
        "--sandbox",
        "danger-full-access",
        "--json",
        "--skip-git-repo-check",
        "-C",
        str(agent_workspace),
    ]
    if trust_generated_hooks:
        policy.append("--dangerously-bypass-hook-trust")
    return [command[0], "exec", *policy, *tail]


def _validate_codex_transaction(
    task: Mapping[str, Any],
    *,
    workspace: Path,
    agent_workspace: Path,
) -> None:
    """Validate the staged transaction layout before an unrestricted Codex run."""

    transaction = task.get("transaction")
    if not isinstance(transaction, Mapping) or transaction.get("mode") != (
        "isolated_attempt_workspace"
    ):
        raise ValueError("Codex research tasks require an isolated attempt transaction")
    attempt_root = Path(str(transaction.get("attempt_root") or "")).expanduser().resolve()
    staged = Path(str(transaction.get("staged_campaign_workspace") or "")).expanduser().resolve()
    canonical = (
        Path(str(transaction.get("canonical_campaign_workspace") or "")).expanduser().resolve()
    )
    expected_attempts = (workspace / "openlabs-artifacts" / "attempt-workspaces").resolve()
    expected_data = (workspace / "openlabs-data").resolve()
    if not attempt_root.is_relative_to(expected_attempts):
        raise ValueError("Codex attempt root is outside the artifact transaction store")
    if staged != agent_workspace or not staged.is_relative_to(attempt_root):
        raise ValueError("Codex writable root is not the declared private campaign")
    if not canonical.is_relative_to(expected_data):
        raise ValueError("Canonical campaign is outside the authoritative data store")
    if canonical == staged or canonical.is_relative_to(staged) or staged.is_relative_to(canonical):
        raise ValueError("Canonical and private campaign roots overlap")
    temporary_roots = {
        Path(tempfile.gettempdir()).resolve(),
        Path("/tmp").resolve(),
        Path("/var/tmp").resolve(),
        Path("/dev/shm").resolve(),
    }
    for root in temporary_roots:
        if workspace == root or workspace.is_relative_to(root):
            raise ValueError("Codex factory workspace may not live under a system temporary root")
        if canonical == root or canonical.is_relative_to(root):
            raise ValueError("Canonical campaign may not live under a system temporary root")


def _seal_result_envelope(
    task: Mapping[str, Any],
    manifest: Mapping[str, Any],
    output: Path,
) -> tuple[bool, str | None]:
    """Bind transport identity while leaving every scientific field agent-owned."""

    try:
        raw = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"Agent result is not readable JSON: {exc}"
    if not isinstance(raw, dict):
        return False, "Agent result must be a JSON object"
    expected = {
        "schema_version": RESULT_SCHEMA,
        "task_id": task.get("task_id"),
        "campaign_id": task.get("campaign_id"),
        "lab_id": task.get("lab_id") or manifest.get("lab_id"),
        "domain": task.get("domain") or manifest.get("domain"),
    }
    repaired = False
    for key, value in expected.items():
        if value is None:
            continue
        current = raw.get(key)
        if current is None or current == "":
            raw[key] = value
            repaired = True
        elif current != value:
            return False, f"Agent result {key} conflicts with the task identity"
    if repaired:
        write_json(output, raw)
    return repaired, None


def _replace_rejected_result(
    task: dict[str, Any],
    manifest: dict[str, Any],
    output: Path,
    reason: str,
) -> None:
    rejected = output.parent / "agent-result-rejected.json"
    if output.exists():
        os.replace(output, rejected)
    write_json(
        output,
        {
            "schema_version": RESULT_SCHEMA,
            "task_id": task["task_id"],
            "campaign_id": task["campaign_id"],
            "lab_id": task.get("lab_id") or manifest["lab_id"],
            "domain": task.get("domain") or manifest["domain"],
            "status": "failed",
            "summary": reason,
            "artifacts": [],
            "claims": [],
            "next_actions": ["Retry from the quarantined checkpoint with a valid result bundle."],
            "paper_candidate": False,
        },
    )


def _transaction_sandbox(
    command: list[str],
    task: Mapping[str, Any],
    workspace: Path,
) -> tuple[list[str], str | None]:
    """Apply the configured filesystem policy for a transactional research agent."""

    if Path(command[0]).name == "codex":
        return command, "codex-native-danger-full-access"
    transaction = task.get("transaction")
    if not isinstance(transaction, Mapping) or transaction.get("mode") != (
        "isolated_attempt_workspace"
    ):
        return command, None
    bubblewrap = shutil.which("bwrap")
    if bubblewrap is None:
        raise RuntimeError("bubblewrap is required for isolated attempt workspaces")
    attempt_root = Path(str(transaction["attempt_root"])).expanduser().resolve()
    if not attempt_root.is_dir() or not attempt_root.is_relative_to(workspace):
        raise ValueError("Transaction attempt_root is missing or outside OPENLABS_WORKSPACE")
    sandbox = [bubblewrap, "--die-with-parent", "--bind", "/", "/"]
    for relative in ("openlabs", "openlabs-data", "openlabs-artifacts", "openlabs-database"):
        root = (workspace / relative).resolve()
        if root.exists():
            sandbox.extend(["--ro-bind", str(root), str(root)])
    # A nested writable bind overrides the read-only artifact-store mount.
    sandbox.extend(["--bind", str(attempt_root), str(attempt_root), "--"])
    sandbox.extend(command)
    return sandbox, "bubblewrap"


def _run_agent(
    task: dict[str, Any],
    manifest: dict[str, Any],
    output: Path,
) -> dict[str, Any]:
    runner = str(task.get("runner") or "balanced")
    runner_key = "".join(character if character.isalnum() else "_" for character in runner).upper()
    agent = task["agent"]
    session_id = (
        str(agent.get("session_id") or "").strip()
        if agent["role"] != "reviewer" and agent["session_mode"] == "resume"
        else ""
    )
    command_kind = "RESUME_COMMAND" if session_id else "COMMAND"
    raw_command = os.environ.get(f"OPENLABS_AGENT_{command_kind}_{runner_key}_JSON", "").strip()
    raw_command = raw_command or os.environ.get(f"OPENLABS_AGENT_{command_kind}_JSON", "").strip()
    output.parent.mkdir(parents=True, exist_ok=True)
    request_path = output.parent / "agent-request.md"
    request = _agent_request(task, manifest, output)
    request_path.write_text(request, encoding="utf-8")
    if not raw_command:
        label = "resume command" if session_id else "command"
        _configuration_result(
            task,
            manifest,
            output,
            f"No approved Agent {label} is configured for the {runner!r} runner tier.",
        )
        return {"adapter": "unconfigured", "runner": runner}
    template = _command_template(raw_command)
    if session_id and "{session_id}" not in template:
        raise ValueError("Agent resume command must contain a {session_id} argv token")
    if (
        not session_id
        and agent["session_mode"] == "resume"
        and agent["role"] != "reviewer"
        and "--ephemeral" in template
    ):
        _configuration_result(
            task,
            manifest,
            output,
            "The configured Agent command is ephemeral and cannot preserve this role's context.",
        )
        return {"adapter": "ephemeral", "runner": runner}
    configured_workspace = os.environ.get("OPENLABS_WORKSPACE", "").strip()
    workspace = (
        Path(configured_workspace).expanduser().resolve()
        if configured_workspace
        else Path(str(task["lab_manifest"])).resolve().parents[3]
    )
    if not (output == workspace or output.is_relative_to(workspace)):
        raise ValueError("Task output is outside OPENLABS_WORKSPACE")
    agent_workspace = Path(str(task["agent_workspace"])).expanduser().resolve()
    if not (agent_workspace == workspace or agent_workspace.is_relative_to(workspace)):
        raise ValueError("Agent workspace is outside OPENLABS_WORKSPACE")
    agent_workspace.mkdir(parents=True, exist_ok=True)
    replacements = {
        "{workspace}": str(workspace),
        "{agent_workspace}": str(agent_workspace),
        "{prompt_file}": str(request_path),
        "{output_file}": str(output),
        "{output_dir}": str(output.parent),
        "{skill_path}": str(task.get("skill_path") or ""),
        "{task_file}": str(task.get("_task_file") or ""),
        "{session_id}": session_id,
    }
    agent_command = [replacements.get(token, token) for token in template]
    if Path(agent_command[0]).name == "codex":
        _validate_codex_transaction(
            task,
            workspace=workspace,
            agent_workspace=agent_workspace,
        )
    runtime_policy = (
        task.get("runtime_policy") if isinstance(task.get("runtime_policy"), Mapping) else {}
    )
    hooks_path = Path(str(runtime_policy.get("hooks") or "")).expanduser()
    trust_generated_hooks = (
        runtime_policy.get("schema_version") == "openlabs.codex_runtime.v1"
        and runtime_policy.get("hook_trust") == "orchestrator-generated"
        and hooks_path.resolve() == (agent_workspace / ".codex" / "hooks.json").resolve()
        and hooks_path.is_file()
    )
    agent_command = _prepare_codex_command(
        agent_command,
        agent_workspace=agent_workspace,
        trust_generated_hooks=trust_generated_hooks,
    )
    preflight_error = _agent_connectivity_preflight(agent_command)
    if preflight_error is not None:
        _configuration_result(
            task,
            manifest,
            output,
            "Agent connectivity preflight failed closed: " + preflight_error,
        )
        return {
            "adapter": Path(agent_command[0]).name,
            "runner": runner,
            "failure_class": "agent_connectivity_preflight",
            "connectivity_preflight": {"passed": False, "error": preflight_error},
        }
    command, sandbox = _transaction_sandbox(agent_command, task, workspace)
    environment_timeout = max(
        1,
        int(os.environ.get("OPENLABS_AGENT_TIMEOUT_SECONDS", "43200")),
    )
    timeout = min(environment_timeout, int(task["budget"]["wall_seconds"]))
    stdout_path = output.parent / "agent-stdout.log"
    stderr_path = output.parent / "agent-stderr.log"
    with (
        stdout_path.open("w", encoding="utf-8") as stdout_handle,
        stderr_path.open("w", encoding="utf-8") as stderr_handle,
    ):
        process = subprocess.Popen(
            command,
            text=True,
            cwd=agent_workspace,
            stdin=subprocess.PIPE,
            stdout=stdout_handle,
            stderr=stderr_handle,
            start_new_session=True,
        )
        previous_handlers: dict[int, Any] = {}
        termination_signal: int | None = None

        def forward_termination(signum: int, _frame: Any) -> None:
            nonlocal termination_signal
            if termination_signal is None:
                termination_signal = signum
            _terminate_process_group(process)
            # Return to _run_agent so it can atomically persist a retryable bundle and
            # runtime metadata; raising here recreates an opaque exit-143 attempt.

        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, forward_termination)
        timed_out = False
        transport_failed = False
        transport_failure_count = 0
        try:
            try:
                assert process.stdin is not None
                process.stdin.write(request)
                process.stdin.close()
                process.stdin = None
            except BrokenPipeError:
                process.stdin = None
            deadline = time.monotonic() + timeout
            startup_grace = min(
                float(timeout),
                _positive_environment_number(
                    "OPENLABS_AGENT_STARTUP_GRACE_SECONDS",
                    120.0,
                ),
            )
            failure_threshold = max(
                1,
                int(
                    _positive_environment_number(
                        "OPENLABS_AGENT_TRANSPORT_FAILURE_THRESHOLD",
                        3.0,
                    )
                ),
            )
            process_started = time.monotonic()
            startup_monitoring = Path(agent_command[0]).name == "codex"
            while process.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    _terminate_process_group(process, grace_seconds=1)
                    break
                try:
                    process.wait(timeout=min(0.5, remaining))
                except subprocess.TimeoutExpired:
                    pass
                if startup_monitoring:
                    stdout_handle.flush()
                    transport_failure_count, meaningful_progress = _jsonl_startup_health(
                        stdout_path
                    )
                    startup_elapsed = time.monotonic() - process_started
                    if output.is_file() or meaningful_progress:
                        startup_monitoring = False
                    elif transport_failure_count >= failure_threshold or (
                        transport_failure_count > 0 and startup_elapsed >= startup_grace
                    ):
                        transport_failed = True
                        _terminate_process_group(process, grace_seconds=1)
                        break
                    elif startup_elapsed >= startup_grace:
                        # Bound the startup scan itself. A later generic hang is
                        # still covered by the task wall timeout.
                        startup_monitoring = False
        finally:
            for signum, previous in previous_handlers.items():
                signal.signal(signum, previous)
    runtime = _jsonl_runtime(stdout_path)
    raw_hook_receipts = str(runtime_policy.get("hook_receipts") or "").strip()
    if raw_hook_receipts:
        runtime["hooks"] = _hook_runtime(
            Path(raw_hook_receipts),
            agent_workspace=agent_workspace,
        )
    runtime.update(
        {
            "adapter": Path(agent_command[0]).name,
            "adapter_version": _adapter_version(agent_command),
            "runner": runner,
            "profile": _command_option(agent_command, "--profile", "-p"),
            "configured_model": _command_option(agent_command, "--model", "-m"),
            "filesystem_sandbox": sandbox,
            "resumed_from": session_id or None,
            "timed_out": timed_out,
            "transport_watchdog_triggered": transport_failed,
            "startup_transport_failure_count": transport_failure_count,
            "agent_exit_code": process.returncode,
            "interrupted": termination_signal is not None,
            "termination_signal": termination_signal,
        }
    )
    if termination_signal is not None:
        runtime["failure_class"] = "agent_interrupted"
    elif transport_failed:
        runtime["failure_class"] = "agent_transport"
    elif timed_out:
        runtime["failure_class"] = "agent_timeout"
    elif process.returncode != 0:
        runtime["failure_class"] = "agent_process"
    if output.is_file():
        repaired, envelope_error = _seal_result_envelope(task, manifest, output)
        runtime["result_envelope_repaired"] = repaired
        runtime["result_envelope_error"] = envelope_error
        if envelope_error:
            runtime["failure_class"] = "result_contract"
            _replace_rejected_result(task, manifest, output, envelope_error)
        return runtime
    runtime["failure_class"] = "agent_transport"
    if termination_signal is not None:
        summary = (
            f"Agent was interrupted by signal {termination_signal} before writing a result bundle."
        )
        status = "failed"
        next_action = "Resume this task from its persisted checkpoint and bounded agent session."
    elif transport_failed:
        summary = (
            "Agent transport remained unavailable without meaningful progress; "
            "the bounded startup watchdog stopped the process."
        )
        status = "needs_human"
        next_action = "Repair Agent network/proxy connectivity, then explicitly retry the task."
    elif timed_out:
        summary = f"Agent exceeded its bounded {timeout} second timeout."
        status = "needs_replan"
        next_action = "Inspect the bounded agent logs and replan the task within its budget."
    else:
        summary = f"Agent exited with code {process.returncode} without a result bundle."
        status = "needs_replan" if process.returncode == 0 else "failed"
        next_action = "Inspect the bounded agent logs and repair the runner or task prompt."
    write_json(
        output,
        {
            "schema_version": RESULT_SCHEMA,
            "task_id": task["task_id"],
            "campaign_id": task["campaign_id"],
            "lab_id": manifest["lab_id"],
            "domain": manifest["domain"],
            "status": status,
            "summary": summary,
            "artifacts": [],
            "claims": [],
            "next_actions": [next_action],
            "paper_candidate": False,
        },
    )
    return runtime


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    task_path = Path(args.task).resolve()
    task = json.loads(task_path.read_text(encoding="utf-8"))
    task["_task_file"] = str(task_path)
    if task.get("schema_version") != TASK_SCHEMA:
        raise ValueError(f"Unsupported task schema: {task.get('schema_version')}")
    manifest_path = Path(str(task["lab_manifest"])).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if task.get("lab_id") != manifest.get("lab_id"):
        raise ValueError("Task and manifest lab_id differ")
    if task.get("domain") != manifest.get("domain"):
        raise ValueError("Task and manifest domain differ")
    output = Path(args.output).resolve()
    started = time.monotonic()
    configured_workspace = os.environ.get("OPENLABS_WORKSPACE", "").strip()
    workspace = (
        Path(configured_workspace).expanduser().resolve()
        if configured_workspace
        else manifest_path.parents[3]
    )
    agent_workspace = Path(str(task["agent_workspace"])).expanduser().resolve()
    try:
        task_type = task.get("task_type")
        adapter = _configured_agent_adapter(task)
        if task_type == "smoke":
            lab_runtime = {
                "schema_version": LAB_RUNTIME_SCHEMA,
                "setups": [],
                "skipped": "deterministic smoke task",
            }
            _smoke(task, manifest, output)
            runtime: dict[str, Any] = {"adapter": "deterministic", "runner": "none"}
        elif adapter != "codex":
            # Non-Codex commands are retained solely for deterministic transport tests. Production
            # research uses the native Codex adapter and receives every trusted lab runtime.
            lab_runtime = {
                "schema_version": LAB_RUNTIME_SCHEMA,
                "setups": [],
                "skipped": "non-Codex adapter",
            }
            task["lab_runtime"] = lab_runtime
            runtime = _run_agent(task, manifest, output)
        else:
            lab_runtime = _lab_runtime_setup(
                task,
                manifest,
                workspace=workspace,
                agent_workspace=agent_workspace,
            )
            task["lab_runtime"] = lab_runtime
            runtime = _run_agent(task, manifest, output)
        runtime["lab_runtime"] = lab_runtime
    except (OSError, RuntimeError, subprocess.TimeoutExpired, TypeError, ValueError) as exc:
        _configuration_result(
            task,
            manifest,
            output,
            f"Laboratory runtime setup failed closed: {exc}",
        )
        runtime = {
            "adapter": "runtime_setup_failed",
            "runner": "none",
            "failure_class": "lab_runtime_setup",
            "error": str(exc),
        }
    runtime["lab_runner_seconds"] = max(0.0, time.monotonic() - started)
    metadata_path = Path(str(task["run_metadata_path"])).resolve()
    if metadata_path.parent != output.parent:
        raise ValueError("Run metadata must be adjacent to the result")
    write_json(
        metadata_path,
        {
            "task_id": task["task_id"],
            "attempt_id": task["attempt_id"],
            "runtime": runtime,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
