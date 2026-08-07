"""Recoverable, provenance-checked serial queue for frozen QE run directories."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from .dft import collect_qe_result
from .dft_convergence import load_completed_qe_run
from .provenance import atomic_write_json, fingerprint, sha256_file

_SAFE_ATTEMPT_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {path}")
    return payload


def available_memory_gib() -> float:
    """Return Linux MemAvailable without counting swap as available memory."""
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        if line.startswith("MemAvailable:"):
            return float(line.split()[1]) / 1024.0**2
    raise RuntimeError("/proc/meminfo has no MemAvailable entry")


def active_pw_pids() -> list[int]:
    """List live Quantum ESPRESSO pw.x processes visible in /proc."""
    pids: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "comm").read_text(encoding="utf-8").strip()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if command == "pw.x":
            pids.append(int(entry.name))
    return sorted(pids)


def build_qe_command(
    *,
    timer: Path,
    micromamba: str,
    prefix: Path,
    mpirun: Path,
    mpi_ranks: int,
    kpoint_pools: int,
) -> list[str]:
    """Build the recorded QE command after validating pool divisibility."""
    if mpi_ranks <= 0:
        raise ValueError("mpi_ranks must be positive")
    if kpoint_pools <= 0 or mpi_ranks % kpoint_pools:
        raise ValueError("kpoint_pools must be positive and divide mpi_ranks")
    return [
        str(timer),
        "-v",
        "-o",
        "resource_usage.txt",
        micromamba,
        "run",
        "-p",
        str(prefix),
        str(mpirun),
        "-np",
        str(mpi_ranks),
        "pw.x",
        "-nk",
        str(kpoint_pools),
        "-in",
        "pw.in",
    ]


def archive_interrupted_run(
    run_dir: Path | str,
    *,
    state_path: Path | str,
    attempt_id: str,
    reason: str,
) -> dict[str, Any]:
    """Archive a stopped partial QE attempt without deleting its evidence."""
    if not _SAFE_ATTEMPT_ID.fullmatch(attempt_id):
        raise ValueError("attempt_id must be a safe lowercase identifier")
    if not reason.strip():
        raise ValueError("archive reason must be non-empty")
    if active_pw_pids():
        raise RuntimeError("cannot archive while a pw.x process is active")
    directory = Path(run_dir).resolve()
    run_manifest = _read_json(directory / "run_manifest.json")
    input_path = Path(run_manifest["input_path"])
    if sha256_file(input_path) != run_manifest.get("input_sha256"):
        raise RuntimeError("cannot archive a run with a changed frozen input")
    queue_path = Path(state_path).resolve()
    state = _read_json(queue_path)
    run_id = str(run_manifest["run_id"])
    if run_id not in state.get("jobs", {}):
        raise RuntimeError("queue state does not contain the interrupted run")
    destination = directory / "attempts" / attempt_id
    if destination.exists():
        raise RuntimeError(f"attempt archive already exists: {destination}")
    sources = [
        path
        for path in (
            directory / "pw.out",
            directory / "resource_usage.txt",
            directory / "scratch",
        )
        if path.exists()
    ]
    if not sources:
        raise RuntimeError("interrupted run contains no partial artifacts")
    destination.mkdir(parents=True)
    for source in sources:
        shutil.move(str(source), str(destination / source.name))
    artifacts = [
        {
            "path": str(path.resolve()),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for path in sorted(destination.rglob("*"))
        if path.is_file()
    ]
    archive: dict[str, Any] = {
        "schema_version": "1.0",
        "attempt_id": attempt_id,
        "run_id": run_id,
        "reason": reason,
        "archived_unix_time": time.time(),
        "input_path": str(input_path.resolve()),
        "input_sha256": run_manifest["input_sha256"],
        "queue_fingerprint": state.get("queue_fingerprint"),
        "artifacts": artifacts,
    }
    archive["archive_fingerprint"] = fingerprint(archive)
    archive_path = destination / "attempt-manifest.json"
    atomic_write_json(archive_path, archive)
    state["status"] = "interrupted"
    state["jobs"][run_id].update(
        status="interrupted",
        interruption_reason=reason,
        attempt_manifest_path=str(archive_path),
        attempt_manifest_sha256=sha256_file(archive_path),
        finished_unix_time=time.time(),
    )
    state["updated_unix_time"] = time.time()
    atomic_write_json(queue_path, state)
    return archive


def verify_frozen_run(run_dir: Path | str, qe_executable: Path | str) -> dict[str, Any]:
    """Verify an unstarted frozen run and refuse to overwrite partial output."""
    directory = Path(run_dir).resolve()
    manifest_path = directory / "run_manifest.json"
    manifest = _read_json(manifest_path)
    input_path = Path(manifest["input_path"])
    if sha256_file(input_path) != manifest.get("input_sha256"):
        raise RuntimeError(f"frozen QE input hash mismatch: {input_path}")
    executable = Path(qe_executable).resolve()
    expected_binary = manifest.get("pw_executable_sha256")
    if expected_binary and sha256_file(executable) != expected_binary:
        raise RuntimeError(f"QE executable hash mismatch: {executable}")

    label_path = directory / "dft_label.json"
    if label_path.exists():
        load_completed_qe_run(directory)
        return {"state": "already_labelled", "run_id": manifest["run_id"]}
    output_path = directory / "pw.out"
    if output_path.exists() and output_path.stat().st_size:
        output = output_path.read_text(encoding="utf-8", errors="replace")
        if "JOB DONE." in output:
            collect_qe_result(directory)
            load_completed_qe_run(directory)
            return {"state": "collected_existing_output", "run_id": manifest["run_id"]}
        raise RuntimeError(
            f"refusing to overwrite incomplete QE output; archive and prepare a "
            f"new run first: {output_path}"
        )
    return {"state": "ready", "run_id": manifest["run_id"]}


def run_queue(
    run_dirs: list[Path | str],
    *,
    qe_prefix: Path | str,
    mpi_ranks: int,
    kpoint_pools: int = 1,
    min_available_memory_gib: float,
    poll_seconds: float,
    state_path: Path | str,
) -> dict[str, Any]:
    """Run frozen QE directories serially, waiting for other pw.x jobs."""
    if mpi_ranks <= 0:
        raise ValueError("mpi_ranks must be positive")
    if kpoint_pools <= 0 or mpi_ranks % kpoint_pools:
        raise ValueError("kpoint_pools must be positive and divide mpi_ranks")
    if min_available_memory_gib <= 0:
        raise ValueError("min_available_memory_gib must be positive")
    if not 1 <= poll_seconds <= 60:
        raise ValueError("poll_seconds must be between 1 and 60")

    directories = [Path(path).resolve() for path in run_dirs]
    prefix = Path(qe_prefix).resolve()
    executable = prefix / "bin" / "pw.x"
    micromamba = shutil.which("micromamba")
    mpirun = prefix / "bin" / "mpirun"
    timer = Path("/usr/bin/time")
    for required in (executable, mpirun, timer):
        if not required.is_file():
            raise FileNotFoundError(required)
    if micromamba is None:
        raise FileNotFoundError("micromamba")

    config = {
        "run_dirs": [str(path) for path in directories],
        "qe_prefix": str(prefix),
        "qe_executable_sha256": sha256_file(executable),
        "mpi_ranks": mpi_ranks,
        "kpoint_pools": kpoint_pools,
        "min_available_memory_gib": min_available_memory_gib,
        "poll_seconds": poll_seconds,
    }
    queue_fingerprint = fingerprint(config)
    output_state = Path(state_path).resolve()
    output_state.parent.mkdir(parents=True, exist_ok=True)
    if output_state.exists():
        state = _read_json(output_state)
        if state.get("queue_fingerprint") != queue_fingerprint:
            raise RuntimeError(f"queue configuration changed: {output_state}")
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

    for directory in directories:
        check = verify_frozen_run(directory, executable)
        run_id = check["run_id"]
        if check["state"] != "ready":
            state["jobs"][run_id] = {
                "status": check["state"],
                "finished_unix_time": time.time(),
            }
            state["updated_unix_time"] = time.time()
            atomic_write_json(output_state, state)
            continue

        while True:
            other_pids = active_pw_pids()
            memory_gib = available_memory_gib()
            if not other_pids and memory_gib >= min_available_memory_gib:
                break
            state["status"] = "waiting_for_resources"
            state["waiting"] = {
                "run_id": run_id,
                "active_pw_pids": other_pids,
                "available_memory_gib": memory_gib,
                "checked_unix_time": time.time(),
            }
            state["updated_unix_time"] = time.time()
            atomic_write_json(output_state, state)
            time.sleep(poll_seconds)

        state.pop("waiting", None)
        state["status"] = "running"
        state["jobs"][run_id] = {
            "status": "running",
            "run_dir": str(directory),
            "started_unix_time": time.time(),
            "available_memory_gib_at_start": available_memory_gib(),
        }
        state["updated_unix_time"] = time.time()
        atomic_write_json(output_state, state)

        command = build_qe_command(
            timer=timer,
            micromamba=micromamba,
            prefix=prefix,
            mpirun=mpirun,
            mpi_ranks=mpi_ranks,
            kpoint_pools=kpoint_pools,
        )
        environment = os.environ.copy()
        environment.update(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
        output_path = directory / "pw.out"
        with output_path.open("wb") as output:
            process = subprocess.Popen(
                command,
                cwd=directory,
                env=environment,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
            state["jobs"][run_id]["supervisor_child_pid"] = process.pid
            state["updated_unix_time"] = time.time()
            atomic_write_json(output_state, state)
            try:
                return_code = process.wait()
            except KeyboardInterrupt:
                process.send_signal(signal.SIGINT)
                try:
                    return_code = process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    return_code = process.wait()
                state["jobs"][run_id].update(
                    status="interrupted",
                    return_code=return_code,
                    finished_unix_time=time.time(),
                )
                state["status"] = "interrupted"
                state["updated_unix_time"] = time.time()
                atomic_write_json(output_state, state)
                raise

        state["jobs"][run_id]["return_code"] = return_code
        state["jobs"][run_id]["finished_unix_time"] = time.time()
        if return_code != 0:
            state["jobs"][run_id]["status"] = "failed"
            state["status"] = "failed"
            state["updated_unix_time"] = time.time()
            atomic_write_json(output_state, state)
            raise RuntimeError(
                f"QE run failed with exit code {return_code}: {directory}"
            )

        collect_qe_result(directory)
        completed = load_completed_qe_run(directory)
        state["jobs"][run_id].update(
            status="complete",
            output_sha256=sha256_file(output_path),
            label_sha256=completed["label_sha256"],
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
    parser.add_argument("run_dir", nargs="+")
    parser.add_argument("--qe-prefix", required=True)
    parser.add_argument("--mpi-ranks", type=int, default=8)
    parser.add_argument("--kpoint-pools", type=int, default=1)
    parser.add_argument("--min-available-memory-gib", type=float, default=20.0)
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--state", required=True)
    args = parser.parse_args()
    result = run_queue(
        args.run_dir,
        qe_prefix=args.qe_prefix,
        mpi_ranks=args.mpi_ranks,
        kpoint_pools=args.kpoint_pools,
        min_available_memory_gib=args.min_available_memory_gib,
        poll_seconds=args.poll_seconds,
        state_path=args.state,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
