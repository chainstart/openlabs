"""Recoverable single-GPU queue for preregistered MD campaign entries.

The queue is intentionally conservative. It will not launch publication-scale
CHGNet trajectories until an explicit, hash-bearing release gate exists, and it
will never overwrite a partial run directory. Scientific adequacy is evaluated
after a run finishes; an unresolved 0.5 ns result remains a completed run and
must be extended under a new protocol rather than silently discarded.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from contextlib import suppress
from pathlib import Path
from typing import Any, BinaryIO

from .campaign import Campaign, CampaignRun, load_campaign
from .provenance import atomic_write_json, fingerprint, sha256_file


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {path}")
    return payload


def active_campaign_pids() -> list[int]:
    """Return live processes whose command line invokes matfactory-campaign."""
    pids: list[int] = []
    own_pid = os.getpid()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == own_pid:
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if b"matfactory-campaign" in command:
            pids.append(int(entry.name))
    return sorted(pids)


def gpu_compute_pids() -> list[int]:
    """Return compute-process PIDs reported by nvidia-smi."""
    executable = shutil.which("nvidia-smi")
    if executable is None:
        raise FileNotFoundError("nvidia-smi")
    completed = subprocess.run(
        [
            executable,
            "--query-compute-apps=pid",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    pids: list[int] = []
    for line in completed.stdout.splitlines():
        value = line.strip()
        if value and value != "[N/A]":
            pids.append(int(value))
    return sorted(set(pids))


def acquire_gpu_lock(path: Path | str) -> BinaryIO | None:
    """Try to acquire the shared single-GPU launch lock without blocking."""
    import fcntl

    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = target.open("a+b")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def release_gpu_lock(handle: BinaryIO) -> None:
    """Release and close a handle returned by :func:`acquire_gpu_lock`."""
    import fcntl

    with suppress(OSError):
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    handle.close()


def missing_structure_inputs(item: CampaignRun) -> list[str]:
    """Return future derived structure files that are not available yet."""
    value = item.config.structure_file
    if not value:
        return []
    path = Path(value)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    return [] if path.is_file() else [str(path.resolve())]


def verify_release_gate(path: Path | str, *, gate_id: str) -> dict[str, Any]:
    """Require an explicit pass and immutable evidence hash before launch."""
    source = Path(path).resolve()
    payload = _read_json(source)
    if payload.get("schema_version") != "1.0":
        raise ValueError(f"unsupported release-gate schema: {source}")
    if payload.get("gate_id") != gate_id:
        raise ValueError(f"release gate is not {gate_id}: {source}")
    if payload.get("status") != "pass":
        raise RuntimeError(f"release gate has not passed: {source}")
    evidence = payload.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError(f"release gate has no evidence: {source}")
    for record in evidence:
        evidence_path = Path(record["path"])
        if not evidence_path.is_absolute():
            evidence_path = source.parent / evidence_path
        evidence_path = evidence_path.resolve()
        if sha256_file(evidence_path) != record.get("sha256"):
            raise RuntimeError(f"release-gate evidence hash mismatch: {evidence_path}")
    return {
        "path": str(source),
        "sha256": sha256_file(source),
        "gate_id": gate_id,
        "evidence_count": len(evidence),
    }


def inspect_run(campaign: Campaign, item: CampaignRun) -> dict[str, Any]:
    """Classify one run without modifying it or accepting partial outputs."""
    directory = item.run_dir.resolve()
    if not directory.exists():
        return {"state": "ready", "run_id": item.run_id}
    files = [path for path in directory.iterdir()]
    if not files:
        return {"state": "ready", "run_id": item.run_id}

    manifest_path = directory / "run_manifest.json"
    result_path = directory / "result.json"
    if not manifest_path.is_file() or not result_path.is_file():
        raise RuntimeError(
            "refusing to overwrite a partial MD run; archive it under a new, "
            f"hash-recorded interruption directory first: {directory}"
        )
    manifest = _read_json(manifest_path)
    result = _read_json(result_path)
    provenance = manifest.get("config", {}).get("provenance", {})
    checks = {
        "run_id": provenance.get("campaign_run_id") == item.run_id,
        "campaign_id": provenance.get("campaign_id") == campaign.campaign_id,
        "campaign_protocol": provenance.get("campaign_protocol_sha256")
        == campaign.protocol_sha256,
        "protocol_fingerprint": result.get("protocol_fingerprint")
        == manifest.get("protocol_fingerprint"),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(
            f"completed MD run provenance failed for {directory}: {', '.join(failed)}"
        )
    return {
        "state": "already_complete",
        "run_id": item.run_id,
        "result_status": result.get("status"),
        "manifest_sha256": sha256_file(manifest_path),
        "result_sha256": sha256_file(result_path),
    }


def _selected_runs(campaign: Campaign, run_ids: list[str]) -> list[CampaignRun]:
    by_id = {item.run_id: item for item in campaign.runs}
    missing = [run_id for run_id in run_ids if run_id not in by_id]
    if missing:
        raise ValueError("unknown campaign run(s): " + ", ".join(missing))
    if len(set(run_ids)) != len(run_ids):
        raise ValueError("MD queue run IDs must be unique")
    return [by_id[run_id] for run_id in run_ids]


def run_queue(
    protocol_path: Path | str,
    run_ids: list[str],
    *,
    release_gate_path: Path | str,
    release_gate_id: str,
    poll_seconds: float,
    state_path: Path | str,
    gpu_lock_path: Path | str = "runs/supervisor/md-gpu.lock",
) -> dict[str, Any]:
    """Wait for G2 and GPU availability, then run campaign entries serially."""
    if not 1 <= poll_seconds <= 60:
        raise ValueError("poll_seconds must be between 1 and 60")
    campaign = load_campaign(protocol_path)
    selected = _selected_runs(campaign, run_ids)
    gate_path = Path(release_gate_path).resolve()
    output_state = Path(state_path).resolve()
    lock_path = Path(gpu_lock_path).resolve()
    output_state.parent.mkdir(parents=True, exist_ok=True)
    config = {
        "campaign_id": campaign.campaign_id,
        "protocol_path": str(campaign.protocol_path),
        "protocol_sha256": campaign.protocol_sha256,
        "run_ids": run_ids,
        "release_gate_path": str(gate_path),
        "release_gate_id": release_gate_id,
        "gpu_lock_path": str(lock_path),
        "poll_seconds": poll_seconds,
        "implementation_sha256": sha256_file(Path(__file__)),
    }
    queue_fingerprint = fingerprint(config)
    if output_state.exists():
        state = _read_json(output_state)
        if state.get("queue_fingerprint") != queue_fingerprint:
            raise RuntimeError(f"MD queue configuration changed: {output_state}")
    else:
        state = {
            "schema_version": "1.0",
            "queue_fingerprint": queue_fingerprint,
            "config": config,
            "status": "created",
            "created_unix_time": time.time(),
            "jobs": {},
        }
        atomic_write_json(output_state, state)

    while True:
        if gate_path.is_file():
            gate = verify_release_gate(gate_path, gate_id=release_gate_id)
            break
        state["status"] = "waiting_for_release_gate"
        state["waiting"] = {
            "release_gate_path": str(gate_path),
            "checked_unix_time": time.time(),
        }
        state["updated_unix_time"] = time.time()
        atomic_write_json(output_state, state)
        time.sleep(poll_seconds)

    state["release_gate"] = gate
    for item in selected:
        lock_handle: BinaryIO | None = None
        while True:
            missing_inputs = missing_structure_inputs(item)
            if missing_inputs:
                state["status"] = "waiting_for_input"
                state["waiting"] = {
                    "run_id": item.run_id,
                    "missing_structure_inputs": missing_inputs,
                    "checked_unix_time": time.time(),
                }
                state["updated_unix_time"] = time.time()
                atomic_write_json(output_state, state)
                time.sleep(poll_seconds)
                continue
            lock_handle = acquire_gpu_lock(lock_path)
            if lock_handle is None:
                state["status"] = "waiting_for_gpu_lock"
                state["waiting"] = {
                    "run_id": item.run_id,
                    "gpu_lock_path": str(lock_path),
                    "checked_unix_time": time.time(),
                }
                state["updated_unix_time"] = time.time()
                atomic_write_json(output_state, state)
                time.sleep(poll_seconds)
                continue
            campaign_pids = active_campaign_pids()
            compute_pids = gpu_compute_pids()
            if not campaign_pids and not compute_pids:
                break
            release_gpu_lock(lock_handle)
            lock_handle = None
            state["status"] = "waiting_for_gpu"
            state["waiting"] = {
                "run_id": item.run_id,
                "active_campaign_pids": campaign_pids,
                "gpu_compute_pids": compute_pids,
                "checked_unix_time": time.time(),
            }
            state["updated_unix_time"] = time.time()
            atomic_write_json(output_state, state)
            time.sleep(poll_seconds)

        if lock_handle is None:
            raise AssertionError("GPU lock was not retained for launch")
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
                "matfactory-campaign",
                str(campaign.protocol_path),
                "--run",
                item.run_id,
                "--quiet",
            ]
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
            raise RuntimeError(f"MD campaign run failed: {item.run_id}")
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
    state["status"] = "complete"
    state["finished_unix_time"] = time.time()
    state["updated_unix_time"] = time.time()
    atomic_write_json(output_state, state)
    return state


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol")
    parser.add_argument("--run", action="append", required=True)
    parser.add_argument("--release-gate", required=True)
    parser.add_argument("--release-gate-id", default="g2-potential-domain")
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--state", required=True)
    parser.add_argument("--gpu-lock", default="runs/supervisor/md-gpu.lock")
    args = parser.parse_args()
    result = run_queue(
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
