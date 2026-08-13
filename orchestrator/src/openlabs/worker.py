"""Run one isolated lab command and publish a hash-bound result receipt."""

from __future__ import annotations

import json
import os
import signal
import sqlite3
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


def _stop_lab_runner(process: subprocess.Popen[bytes], *, grace_seconds: int = 30) -> int:
    """Stop a runner after lease loss without abandoning its descendants or receipt."""

    if process.poll() is not None:
        return int(process.returncode)
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return int(process.wait())
    try:
        return int(process.wait(timeout=max(1, grace_seconds)))
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return int(process.wait())


def _heartbeat_with_contention_tolerance(
    db: FactoryDB,
    task_id: str,
    *,
    attempt_id: str,
    owner: str,
    lease_seconds: int,
) -> bool | None:
    """Keep research alive across a transient SQLite writer collision.

    The authoritative lease is deliberately much longer than one heartbeat.  A
    single busy/locked write must therefore be retried on the next heartbeat,
    rather than terminating a healthy agent and losing its in-memory context.
    ``None`` means no state transition was observed and the retry is safe.
    """

    try:
        return db.heartbeat(
            task_id,
            attempt_id=attempt_id,
            owner=owner,
            lease_seconds=lease_seconds,
        )
    except sqlite3.OperationalError as exc:
        code = getattr(exc, "sqlite_errorcode", None)
        detail = str(exc).lower()
        retryable = code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED} or any(
            marker in detail
            for marker in ("database is locked", "database table is locked", "locking protocol")
        )
        if not retryable:
            raise
        print(
            f"Transient SQLite contention during heartbeat for {task_id}; "
            "the live agent will retry within its lease.",
            file=sys.stderr,
            flush=True,
        )
        return None


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
    process = subprocess.Popen(command, cwd=manifest.root, start_new_session=True)
    heartbeat_lost = False
    while True:
        try:
            return_code = process.wait(timeout=settings.heartbeat_seconds)
            break
        except subprocess.TimeoutExpired:
            heartbeat = _heartbeat_with_contention_tolerance(
                db,
                task_id,
                attempt_id=attempt_id,
                owner=owner,
                lease_seconds=settings.lease_seconds,
            )
            if heartbeat is False:
                heartbeat_lost = True
                return_code = _stop_lab_runner(process)
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
            "heartbeat_lost": heartbeat_lost,
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
