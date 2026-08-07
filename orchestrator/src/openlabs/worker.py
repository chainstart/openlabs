"""Run one isolated lab command and publish a hash-bound result receipt."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from .config import load_settings, workspace_paths
from .contracts import RECEIPT_SCHEMA, RESULT_SCHEMA, atomic_write_json, sha256_file, validate_task
from .db import FactoryDB
from .labs import load_lab


def _command_tokens(command: tuple[str, ...], lab_root: Path) -> list[str]:
    tokens: list[str] = []
    for index, token in enumerate(command):
        if token == "{python}":
            tokens.append(sys.executable)
        elif index > 0 and token.endswith(".py") and not Path(token).is_absolute():
            tokens.append(str((lab_root / token).resolve()))
        else:
            tokens.append(token)
    return tokens


def _failure_result(task: dict[str, object], message: str) -> dict[str, object]:
    return {
        "schema_version": RESULT_SCHEMA,
        "task_id": task["task_id"],
        "campaign_id": task["campaign_id"],
        "lab_id": task["lab_id"],
        "domain": task["domain"],
        "status": "failed",
        "summary": message,
        "artifacts": [],
        "claims": [],
        "next_actions": ["Inspect worker.log and choose a bounded retry or replan."],
    }


def run_worker(job_file: str) -> int:
    paths = workspace_paths()
    settings = load_settings(paths)
    db = FactoryDB(paths.database_file)
    job_path = Path(job_file).expanduser().resolve()
    if job_path.parent != paths.job_inbox.resolve():
        raise ValueError("Worker job file is outside the job inbox")
    task = json.loads(job_path.read_text(encoding="utf-8"))
    validation = validate_task(task)
    if not validation.valid:
        raise ValueError("; ".join(validation.errors))
    task_id = str(task["task_id"])
    attempt_id = str(task["attempt_id"])
    row = db.task(task_id)
    if row is None:
        raise KeyError(task_id)
    expected = {
        "campaign_id": row.get("campaign_id"),
        "domain": row.get("domain"),
        "lab_id": row.get("lab_id"),
        "agent_role": row.get("agent_role"),
        "attempt_id": row.get("current_attempt_id"),
    }
    actual = {
        "campaign_id": task.get("campaign_id"),
        "domain": task.get("domain"),
        "lab_id": task.get("lab_id"),
        "agent_role": task.get("agent", {}).get("role"),
        "attempt_id": attempt_id,
    }
    if row.get("status") != "running" or actual != expected:
        raise ValueError(f"Job identity or state differs from task {task_id}")
    owner = str(row.get("lease_owner") or "")
    manifest = load_lab(str(task["lab_manifest"]))
    output = Path(str(task["output_path"])).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    command = _command_tokens(manifest.command, manifest.root)
    command.extend(["--task", str(job_path), "--output", str(output)])

    started = time.monotonic()
    process = subprocess.Popen(command, cwd=manifest.root)
    while True:
        try:
            return_code = process.wait(timeout=settings.heartbeat_seconds)
            break
        except subprocess.TimeoutExpired:
            if not db.heartbeat(
                task_id,
                attempt_id=attempt_id,
                owner=owner,
                lease_seconds=settings.lease_seconds,
            ):
                process.terminate()
                return_code = process.wait(timeout=30)
                break
    duration_seconds = max(0.0, time.monotonic() - started)

    if not output.is_file():
        atomic_write_json(
            output,
            _failure_result(
                task,
                f"Lab runner exited with code {return_code} without a result bundle.",
            ),
        )
    runtime: dict[str, object] = {}
    metadata_path = Path(str(task["run_metadata_path"])).expanduser().resolve()
    if metadata_path.is_file() and metadata_path.parent == output.parent:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if (
            isinstance(metadata, dict)
            and metadata.get("task_id") == task_id
            and metadata.get("attempt_id") == attempt_id
            and isinstance(metadata.get("runtime"), dict)
        ):
            runtime.update(metadata["runtime"])
    runtime.update(
        {
            "duration_seconds": duration_seconds,
            "exit_code": int(return_code),
        }
    )
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "task_id": task_id,
        "attempt_id": attempt_id,
        "campaign_id": task["campaign_id"],
        "lab_id": task["lab_id"],
        "domain": task["domain"],
        "agent_role": task["agent"]["role"],
        "result_path": str(output),
        "sha256": sha256_file(output),
        "runtime": runtime,
    }
    atomic_write_json(paths.result_inbox / f"{task_id}-{attempt_id}.json", receipt)
    return 0 if return_code == 0 else int(return_code)
