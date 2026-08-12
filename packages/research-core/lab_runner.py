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
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

TASK_SCHEMA = "openlabs.task.v3"
RESULT_SCHEMA = "openlabs.result_bundle.v1"


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
    return f"""# OpenLabs bounded research task

Read and follow the factory coordinator at `{factory_skill}` and the domain skill at
`{task.get("skill_path")}`. Work only on this task and its declared inputs.

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

{independence}
{transaction_notice}

Write one `openlabs.result_bundle.v1` JSON object to the required result path. Do not write to
SQLite. Preserve unsupported, negative, and inconclusive outcomes. Do not submit, publish, spend
unbounded resources, or perform another irreversible external action.
"""


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


def _command_option(command: list[str], *names: str) -> str | None:
    for index, token in enumerate(command):
        if token in names and index + 1 < len(command):
            return command[index + 1]
        for name in names:
            prefix = f"{name}="
            if token.startswith(prefix):
                return token[len(prefix) :]
    return None


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


def _transaction_sandbox(
    command: list[str],
    task: Mapping[str, Any],
    workspace: Path,
) -> tuple[list[str], str | None]:
    """Make canonical factory state read-only for a transactional research agent."""

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
    command, sandbox = _transaction_sandbox(agent_command, task, workspace)
    environment_timeout = max(
        1,
        int(os.environ.get("OPENLABS_AGENT_TIMEOUT_SECONDS", "14400")),
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
        try:
            process.communicate(input=request, timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_process_group(process, grace_seconds=1)
        finally:
            for signum, previous in previous_handlers.items():
                signal.signal(signum, previous)
    runtime = _jsonl_runtime(stdout_path)
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
            "agent_exit_code": process.returncode,
            "interrupted": termination_signal is not None,
            "termination_signal": termination_signal,
        }
    )
    if output.is_file():
        return runtime
    if termination_signal is not None:
        summary = (
            f"Agent was interrupted by signal {termination_signal} before writing a result bundle."
        )
        status = "failed"
        next_action = "Resume this task from its persisted checkpoint and bounded agent session."
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
    if task.get("task_type") == "smoke":
        _smoke(task, manifest, output)
        runtime: dict[str, Any] = {"adapter": "deterministic", "runner": "none"}
    else:
        runtime = _run_agent(task, manifest, output)
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
