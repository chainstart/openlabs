"""Single-GPU queue for campaigns derived from a hash-locked CHGNet artifact."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, BinaryIO

from .campaign import load_campaign
from .custom_campaign import validate_custom_campaign
from .md_queue import (
    acquire_gpu_lock,
    active_campaign_pids,
    gpu_compute_pids,
    inspect_run,
    missing_structure_inputs,
    release_gpu_lock,
    verify_release_gate,
)
from .provenance import atomic_write_json, fingerprint, sha256_file


def _read_json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {source}")
    return payload


def run_model_md_queue(
    protocol_path: Path | str,
    run_ids: list[str],
    *,
    release_gate_path: Path | str,
    release_gate_id: str,
    poll_seconds: float,
    state_path: Path | str,
    gpu_lock_path: Path | str = "runs/supervisor/md-gpu.lock",
) -> dict[str, Any]:
    """Wait for a model-specific gate/GPU and run selected derived entries."""
    if not 1 <= poll_seconds <= 60:
        raise ValueError("poll_seconds must be between 1 and 60")
    if len(run_ids) != len(set(run_ids)):
        raise ValueError("model MD queue run IDs must be unique")
    custom = validate_custom_campaign(protocol_path, set(run_ids))
    campaign = load_campaign(protocol_path)
    by_id = {run.run_id: run for run in campaign.runs}
    selected = [by_id[value] for value in run_ids]
    gate_path = Path(release_gate_path).resolve()
    output_state = Path(state_path).resolve()
    lock_path = Path(gpu_lock_path).resolve()
    config = {
        "campaign_id": campaign.campaign_id,
        "protocol_path": str(campaign.protocol_path),
        "protocol_sha256": campaign.protocol_sha256,
        "run_ids": run_ids,
        "model_artifact_path": custom["artifact_path"],
        "model_artifact_sha256": custom["artifact_sha256"],
        "model_state_dict_sha256": custom["model_state_dict_sha256"],
        "release_gate_path": str(gate_path),
        "release_gate_id": release_gate_id,
        "gpu_lock_path": str(lock_path),
        "poll_seconds": poll_seconds,
        "implementation_sha256": sha256_file(__file__),
    }
    queue_fingerprint = fingerprint(config)
    output_state.parent.mkdir(parents=True, exist_ok=True)
    if output_state.exists():
        state = _read_json(output_state)
        if state.get("queue_fingerprint") != queue_fingerprint:
            raise RuntimeError(f"model MD queue configuration changed: {output_state}")
    else:
        state = {
            "schema_version": "1.0",
            "queue_fingerprint": queue_fingerprint,
            "config": config,
            "created_unix_time": time.time(),
            "status": "created",
            "jobs": {},
        }
        atomic_write_json(output_state, state)

    while not gate_path.is_file():
        state.update(
            status="waiting_for_model_release_gate",
            waiting={"path": str(gate_path), "checked_unix_time": time.time()},
            updated_unix_time=time.time(),
        )
        atomic_write_json(output_state, state)
        time.sleep(poll_seconds)
    gate = verify_release_gate(gate_path, gate_id=release_gate_id)
    gate_payload = _read_json(gate_path)
    if gate_payload.get("model_state_dict_sha256") != custom["model_state_dict_sha256"]:
        raise RuntimeError("model release gate belongs to different weights")
    state["release_gate"] = gate

    for item in selected:
        lock_handle: BinaryIO | None = None
        while True:
            missing = missing_structure_inputs(item)
            if missing:
                state.update(
                    status="waiting_for_input",
                    waiting={
                        "run_id": item.run_id,
                        "missing_structure_inputs": missing,
                        "checked_unix_time": time.time(),
                    },
                    updated_unix_time=time.time(),
                )
                atomic_write_json(output_state, state)
                time.sleep(poll_seconds)
                continue
            lock_handle = acquire_gpu_lock(lock_path)
            if lock_handle is None:
                state.update(
                    status="waiting_for_gpu_lock",
                    waiting={
                        "run_id": item.run_id,
                        "gpu_lock_path": str(lock_path),
                        "checked_unix_time": time.time(),
                    },
                    updated_unix_time=time.time(),
                )
                atomic_write_json(output_state, state)
                time.sleep(poll_seconds)
                continue
            campaign_pids = active_campaign_pids()
            compute_pids = gpu_compute_pids()
            if not campaign_pids and not compute_pids:
                break
            release_gpu_lock(lock_handle)
            lock_handle = None
            state.update(
                status="waiting_for_gpu",
                waiting={
                    "run_id": item.run_id,
                    "active_campaign_pids": campaign_pids,
                    "gpu_compute_pids": compute_pids,
                    "checked_unix_time": time.time(),
                },
                updated_unix_time=time.time(),
            )
            atomic_write_json(output_state, state)
            time.sleep(poll_seconds)

        if lock_handle is None:
            raise AssertionError("model MD queue did not retain the GPU lock")
        try:
            check = inspect_run(campaign, item)
            if check["state"] != "ready":
                state["jobs"][item.run_id] = {
                    **check,
                    "status": check["state"],
                    "finished_unix_time": time.time(),
                }
                state["updated_unix_time"] = time.time()
                atomic_write_json(output_state, state)
                continue
            uv = shutil.which("uv")
            if uv is None:
                raise FileNotFoundError("uv")
            log_path = campaign.root_dir / f"{item.run_id}.supervisor.log"
            state.pop("waiting", None)
            state["status"] = "running"
            state["jobs"][item.run_id] = {
                "status": "running",
                "run_dir": str(item.run_dir),
                "log_path": str(log_path),
                "gpu_lock_path": str(lock_path),
                "started_unix_time": time.time(),
            }
            state["updated_unix_time"] = time.time()
            atomic_write_json(output_state, state)
            command = [
                uv,
                "run",
                "python",
                "-m",
                "matfactory.custom_campaign",
                str(campaign.protocol_path),
                "--run",
                item.run_id,
                "--quiet",
            ]
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("wb") as output:
                process = subprocess.Popen(
                    command,
                    cwd=Path(__file__).resolve().parents[2],
                    stdout=output,
                    stderr=subprocess.STDOUT,
                )
                state["jobs"][item.run_id]["supervisor_child_pid"] = process.pid
                state["updated_unix_time"] = time.time()
                atomic_write_json(output_state, state)
                return_code = process.wait()
        finally:
            release_gpu_lock(lock_handle)
        state["jobs"][item.run_id].update(
            return_code=return_code,
            finished_unix_time=time.time(),
        )
        if return_code != 0:
            state["jobs"][item.run_id]["status"] = "failed"
            state["status"] = "failed"
            state["updated_unix_time"] = time.time()
            atomic_write_json(output_state, state)
            raise RuntimeError(f"custom model MD campaign failed: {item.run_id}")
        completed = inspect_run(campaign, item)
        state["jobs"][item.run_id].update(
            status="complete",
            result_status=completed.get("result_status"),
            manifest_sha256=completed["manifest_sha256"],
            result_sha256=completed["result_sha256"],
        )
        state["updated_unix_time"] = time.time()
        atomic_write_json(output_state, state)

    state.pop("waiting", None)
    state.update(
        status="complete",
        finished_unix_time=time.time(),
        updated_unix_time=time.time(),
    )
    atomic_write_json(output_state, state)
    return state


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol")
    parser.add_argument("--run", action="append", required=True)
    parser.add_argument("--release-gate", required=True)
    parser.add_argument("--release-gate-id", required=True)
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--state", required=True)
    parser.add_argument("--gpu-lock", default="runs/supervisor/md-gpu.lock")
    args = parser.parse_args()
    result = run_model_md_queue(
        args.protocol,
        args.run,
        release_gate_path=args.release_gate,
        release_gate_id=args.release_gate_id,
        poll_seconds=args.poll_seconds,
        state_path=args.state,
        gpu_lock_path=args.gpu_lock,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
