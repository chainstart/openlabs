"""Recoverable formal-mechanism queue gated behind the LLZTO DFT domain test."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Any, BinaryIO, Callable

from .md_queue import verify_release_gate
from .provenance import atomic_write_json, fingerprint, sha256_file
from .qe_queue import active_pw_pids, available_memory_gib


def _read_json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {source}")
    return payload


def _repo_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (Path(__file__).resolve().parents[2] / path).resolve()


def acquire_analysis_lock(path: Path | str) -> BinaryIO | None:
    """Acquire the shared heavy-CPU analysis lock without blocking."""
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


def release_analysis_lock(handle: BinaryIO) -> None:
    import fcntl

    with suppress(OSError):
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    handle.close()


def _verify_report(
    path: Path,
    *,
    trajectory: Path,
    mechanism_protocol_sha256: str,
    implementation_path: Path,
) -> dict[str, Any]:
    payload = _read_json(path)
    checks = {
        "trajectory_path": Path(payload.get("trajectory_path", "")).resolve()
        == trajectory.resolve(),
        "trajectory_sha256": payload.get("trajectory_sha256")
        == sha256_file(trajectory),
        "protocol_sha256": payload.get("protocol_sha256")
        == mechanism_protocol_sha256,
        "implementation_path": Path(payload.get("implementation_path", "")).resolve()
        == implementation_path.resolve(),
        "implementation_sha256": payload.get("implementation_sha256")
        == sha256_file(implementation_path),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(
            f"formal mechanism output provenance failed for {path}: "
            + ", ".join(failed)
        )
    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "quality_gate_pass": payload.get("quality_gate_pass"),
        "sensitivity_summary": payload.get("summary"),
    }


def inspect_analysis_job(
    trajectory_path: Path | str,
    transport_path: Path | str,
    primary_output_path: Path | str,
    sensitivity_output_path: Path | str,
    *,
    mechanism_protocol_sha256: str,
) -> dict[str, Any]:
    """Classify one formal point without reading a trajectory still being written."""
    trajectory = Path(trajectory_path).resolve()
    transport = Path(transport_path).resolve()
    primary = Path(primary_output_path).resolve()
    sensitivity = Path(sensitivity_output_path).resolve()
    missing = [
        str(path)
        for path in (trajectory, transport)
        if not path.is_file() or path.stat().st_size == 0
    ]
    if missing:
        return {"state": "waiting_for_input", "missing_inputs": missing}
    transport_payload = _read_json(transport)
    if "transport" not in transport_payload or "temperature_k" not in transport_payload:
        raise RuntimeError(f"temperature transport report is incomplete: {transport}")

    outputs: dict[str, Any] = {}
    implementations = {
        "primary": Path(__file__).with_name("mechanisms.py").resolve(),
        "sensitivity": Path(__file__).with_name("mechanism_sensitivity.py").resolve(),
    }
    for label, output in (("primary", primary), ("sensitivity", sensitivity)):
        if output.exists():
            outputs[label] = _verify_report(
                output,
                trajectory=trajectory,
                mechanism_protocol_sha256=mechanism_protocol_sha256,
                implementation_path=implementations[label],
            )
    if len(outputs) == 2:
        return {"state": "already_complete", "outputs": outputs}
    return {
        "state": "ready",
        "trajectory_sha256": sha256_file(trajectory),
        "transport_sha256": sha256_file(transport),
        "completed_outputs": outputs,
        "components_to_run": [
            label for label in ("primary", "sensitivity") if label not in outputs
        ],
    }


def _run_component(
    component: str,
    *,
    trajectory: Path,
    mechanism_protocol: Path,
    cif: Path,
    output: Path,
    log_path: Path,
    on_start: Callable[[int], None] | None = None,
) -> tuple[int, int]:
    module = (
        "matfactory.mechanisms"
        if component == "primary"
        else "matfactory.mechanism_sensitivity"
    )
    command = [
        sys.executable,
        "-m",
        module,
        str(trajectory),
        str(mechanism_protocol),
        "--cif",
        str(cif),
        "--out",
        str(output),
    ]
    environment = os.environ.copy()
    environment.update(
        OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
        NUMEXPR_NUM_THREADS="1",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab") as log:
        process = subprocess.Popen(
            command,
            cwd=Path(__file__).resolve().parents[2],
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        if on_start is not None:
            on_start(process.pid)
        return_code = process.wait()
    return process.pid, return_code


def run_queue(
    association_protocol_path: Path | str,
    *,
    release_gate_path: Path | str,
    release_gate_id: str,
    state_path: Path | str,
    cpu_lock_path: Path | str,
    poll_seconds: float,
    minimum_available_memory_gib: float,
) -> dict[str, Any]:
    """Wait for G2, then analyze completed formal points one at a time."""
    if not 1 <= poll_seconds <= 60:
        raise ValueError("poll_seconds must be between 1 and 60")
    if minimum_available_memory_gib <= 0:
        raise ValueError("minimum_available_memory_gib must be positive")
    association_path = Path(association_protocol_path).resolve()
    association = _read_json(association_path)
    if association.get("schema_version") != "1.0":
        raise ValueError("unsupported association protocol schema")
    formal = association["formal_campaign"]
    mechanism = association["mechanism_inputs"]
    campaign_root = _repo_path(formal["campaign_root"])
    mechanism_root = _repo_path(mechanism["analysis_root"])
    mechanism_protocol = _repo_path(mechanism["protocol_path"])
    mechanism_protocol_sha256 = sha256_file(mechanism_protocol)
    if mechanism_protocol_sha256 != mechanism["protocol_sha256"]:
        raise RuntimeError("mechanism protocol hash changed after queue registration")
    mechanism_payload = _read_json(mechanism_protocol)
    cif_path = _repo_path(mechanism_payload["site_model"]["source"])
    if sha256_file(cif_path) != mechanism_payload["site_model"]["source_sha256"]:
        raise RuntimeError("mechanism CIF hash changed after protocol freeze")

    gate_path = Path(release_gate_path).resolve()
    output_state = Path(state_path).resolve()
    lock_path = Path(cpu_lock_path).resolve()
    output_state.parent.mkdir(parents=True, exist_ok=True)
    jobs = [
        {
            "job_id": f"{run_id}/T{temperature}",
            "run_id": run_id,
            "temperature_k": int(temperature),
            "trajectory": campaign_root / run_id / f"T{temperature}.traj",
            "transport": campaign_root / run_id / f"T{temperature}.transport.json",
            "primary": mechanism_root / run_id / f"T{temperature}.json",
            "sensitivity": mechanism_root
            / run_id
            / f"T{temperature}.sensitivity.json",
            "log": mechanism_root / run_id / f"T{temperature}.supervisor.log",
        }
        for run_id in formal["run_ids"]
        for temperature in formal["temperatures_k"]
    ]
    config = {
        "association_protocol_path": str(association_path),
        "association_protocol_sha256": sha256_file(association_path),
        "mechanism_protocol_path": str(mechanism_protocol),
        "mechanism_protocol_sha256": mechanism_protocol_sha256,
        "mechanisms_implementation_sha256": sha256_file(
            Path(__file__).with_name("mechanisms.py")
        ),
        "sensitivity_implementation_sha256": sha256_file(
            Path(__file__).with_name("mechanism_sensitivity.py")
        ),
        "run_ids": formal["run_ids"],
        "temperatures_k": formal["temperatures_k"],
        "release_gate_path": str(gate_path),
        "release_gate_id": release_gate_id,
        "cpu_lock_path": str(lock_path),
        "poll_seconds": poll_seconds,
        "minimum_available_memory_gib": minimum_available_memory_gib,
        "implementation_sha256": sha256_file(__file__),
    }
    queue_fingerprint = fingerprint(config)
    if output_state.exists():
        state = _read_json(output_state)
        if state.get("queue_fingerprint") != queue_fingerprint:
            raise RuntimeError(f"mechanism queue configuration changed: {output_state}")
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

    for job in jobs:
        job_id = str(job["job_id"])
        while True:
            inspection = inspect_analysis_job(
                job["trajectory"],
                job["transport"],
                job["primary"],
                job["sensitivity"],
                mechanism_protocol_sha256=mechanism_protocol_sha256,
            )
            if inspection["state"] == "already_complete":
                state["jobs"][job_id] = {
                    "status": "already_complete",
                    "outputs": inspection["outputs"],
                    "finished_unix_time": time.time(),
                }
                state["updated_unix_time"] = time.time()
                atomic_write_json(output_state, state)
                break
            if inspection["state"] == "waiting_for_input":
                state["status"] = "waiting_for_input"
                state["waiting"] = {
                    "job_id": job_id,
                    "missing_inputs": inspection["missing_inputs"],
                    "checked_unix_time": time.time(),
                }
                state["updated_unix_time"] = time.time()
                atomic_write_json(output_state, state)
                time.sleep(poll_seconds)
                continue
            pw_pids = active_pw_pids()
            memory_gib = available_memory_gib()
            if pw_pids or memory_gib < minimum_available_memory_gib:
                state["status"] = "waiting_for_cpu_resources"
                state["waiting"] = {
                    "job_id": job_id,
                    "active_pw_pids": pw_pids,
                    "available_memory_gib": memory_gib,
                    "checked_unix_time": time.time(),
                }
                state["updated_unix_time"] = time.time()
                atomic_write_json(output_state, state)
                time.sleep(poll_seconds)
                continue
            lock_handle = acquire_analysis_lock(lock_path)
            if lock_handle is None:
                state["status"] = "waiting_for_cpu_lock"
                state["waiting"] = {
                    "job_id": job_id,
                    "cpu_lock_path": str(lock_path),
                    "checked_unix_time": time.time(),
                }
                state["updated_unix_time"] = time.time()
                atomic_write_json(output_state, state)
                time.sleep(poll_seconds)
                continue
            try:
                # Recheck after taking the lock so a concurrent queue cannot race us.
                inspection = inspect_analysis_job(
                    job["trajectory"],
                    job["transport"],
                    job["primary"],
                    job["sensitivity"],
                    mechanism_protocol_sha256=mechanism_protocol_sha256,
                )
                if inspection["state"] == "already_complete":
                    continue
                state.pop("waiting", None)
                state["status"] = "running"
                state["jobs"][job_id] = {
                    "status": "running",
                    "trajectory_sha256": inspection["trajectory_sha256"],
                    "transport_sha256": inspection["transport_sha256"],
                    "components_to_run": inspection["components_to_run"],
                    "started_unix_time": time.time(),
                    "log_path": str(Path(job["log"]).resolve()),
                }
                state["updated_unix_time"] = time.time()
                atomic_write_json(output_state, state)
                for component in inspection["components_to_run"]:
                    output = job[component]
                    component_start = time.time()

                    def record_pid(pid: int, *, label: str = component) -> None:
                        state["jobs"][job_id].setdefault("components", {})[
                            label
                        ] = {
                            "pid": pid,
                            "status": "running",
                            "started_unix_time": component_start,
                        }
                        state["updated_unix_time"] = time.time()
                        atomic_write_json(output_state, state)

                    pid, return_code = _run_component(
                        component,
                        trajectory=Path(job["trajectory"]),
                        mechanism_protocol=mechanism_protocol,
                        cif=cif_path,
                        output=Path(output),
                        log_path=Path(job["log"]),
                        on_start=record_pid,
                    )
                    state["jobs"][job_id].setdefault("components", {})[component] = {
                        "pid": pid,
                        "status": "complete" if return_code == 0 else "failed",
                        "return_code": return_code,
                        "started_unix_time": component_start,
                        "finished_unix_time": time.time(),
                    }
                    state["updated_unix_time"] = time.time()
                    atomic_write_json(output_state, state)
                    if return_code != 0:
                        state["jobs"][job_id]["status"] = "failed"
                        state["status"] = "failed"
                        state["updated_unix_time"] = time.time()
                        atomic_write_json(output_state, state)
                        raise RuntimeError(
                            f"formal mechanism {component} failed for {job_id}"
                        )
            finally:
                release_analysis_lock(lock_handle)

            completed = inspect_analysis_job(
                job["trajectory"],
                job["transport"],
                job["primary"],
                job["sensitivity"],
                mechanism_protocol_sha256=mechanism_protocol_sha256,
            )
            if completed["state"] != "already_complete":
                raise RuntimeError(f"formal mechanism job did not complete: {job_id}")
            state["jobs"][job_id].update(
                status="complete",
                outputs=completed["outputs"],
                finished_unix_time=time.time(),
            )
            state["updated_unix_time"] = time.time()
            atomic_write_json(output_state, state)
            break

    state.pop("waiting", None)
    state["status"] = "complete"
    state["finished_unix_time"] = time.time()
    state["updated_unix_time"] = time.time()
    atomic_write_json(output_state, state)
    return state


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--association-protocol", required=True)
    parser.add_argument("--release-gate", required=True)
    parser.add_argument("--release-gate-id", default="g2-potential-domain")
    parser.add_argument("--state", required=True)
    parser.add_argument(
        "--cpu-lock", default="runs/supervisor/mechanism-analysis-cpu.lock"
    )
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--minimum-available-memory-gib", type=float, default=16.0)
    args = parser.parse_args()
    result = run_queue(
        args.association_protocol,
        release_gate_path=args.release_gate,
        release_gate_id=args.release_gate_id,
        state_path=args.state,
        cpu_lock_path=args.cpu_lock,
        poll_seconds=args.poll_seconds,
        minimum_available_memory_gib=args.minimum_available_memory_gib,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
