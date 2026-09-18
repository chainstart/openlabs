"""Cooperative NVIDIA GPU admission and fail-closed workload supervision.

CUDA remains available. GPU workloads must declare a reservation; ordinary
commands still receive allocator limits and telemetry supervision as a backstop.
This is not a driver/kernel VRAM quota. In particular, non-PyTorch allocations
can exceed a budget between samples. No device-wide settings are modified.
"""
from __future__ import annotations

import argparse
import ctypes
import fcntl
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass

MAX_USED_FRACTION = 0.75
MIN_FREE_MIB = 2048
DEFAULT_BUDGET_MIB = 8192
CONTEXT_RESERVE_MIB = 768
MAX_TEMPERATURE_C = 85
POLL_SECONDS = 0.5
TELEMETRY_TIMEOUT = 2


class GuardError(RuntimeError):
    pass


@dataclass(frozen=True)
class GPU:
    index: int
    uuid: str
    total: int
    used: int
    temperature: int

    @property
    def ceiling(self) -> int:
        return min(math.floor(self.total * MAX_USED_FRACTION), self.total - MIN_FREE_MIB)


def snapshot() -> list[GPU]:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,uuid,memory.total,memory.used,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=TELEMETRY_TIMEOUT, check=True,
        )
        rows = []
        for line in result.stdout.splitlines():
            index, uuid, total, used, temperature = [part.strip() for part in line.split(",")]
            gpu = GPU(int(index), uuid, int(total), int(used), int(temperature))
            if gpu.total <= 0 or not 0 <= gpu.used <= gpu.total or not gpu.uuid.startswith("GPU-"):
                raise ValueError("invalid GPU telemetry")
            rows.append(gpu)
        if not rows or len({gpu.uuid for gpu in rows}) != len(rows):
            raise ValueError("empty or duplicate GPU telemetry")
        return rows
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise GuardError(f"GPU telemetry unavailable: {exc}") from exc


def check_limits(rows: list[GPU], baseline: GPU | None = None, budget: int = 0) -> None:
    for gpu in rows:
        if gpu.used > gpu.ceiling:
            raise GuardError(f"{gpu.uuid}: VRAM {gpu.used} MiB exceeds {gpu.ceiling} MiB ceiling")
        if gpu.temperature >= MAX_TEMPERATURE_C:
            raise GuardError(f"{gpu.uuid}: temperature {gpu.temperature} C reaches safety limit")
    if baseline is not None:
        matches = [gpu for gpu in rows if gpu.uuid == baseline.uuid]
        if len(matches) != 1 or matches[0].total != baseline.total:
            raise GuardError("reserved GPU disappeared or changed")
        if matches[0].used > baseline.used + budget:
            raise GuardError(f"{baseline.uuid}: global VRAM growth exceeds job budget {budget} MiB")


def reserve(gpu: GPU, budget: int, directory: Path):
    if budget <= CONTEXT_RESERVE_MIB or gpu.used + budget > gpu.ceiling:
        raise GuardError(
            f"GPU reservation rejected: baseline={gpu.used}, requested={budget}, "
            f"ceiling={gpu.ceiling} MiB; reduce workload or wait for headroom"
        )
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise GuardError("GPU lock directory must be private and owned by this user")
    handle = (directory / f"{gpu.uuid}.lock").open("a+")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise GuardError("GPU already reserved by another research job; retry after it finishes") from exc
    handle.seek(0)
    handle.truncate()
    json.dump({"supervisor_pid": os.getpid(), "gpu": gpu.uuid, "budget_mib": budget}, handle)
    handle.flush()
    return handle


def allocator_environment(environment: dict[str, str], rows: list[GPU], budget: int) -> dict[str, str]:
    env = dict(environment)
    # Installed PyTorch 2.10 supports this allocator key. CUDA contexts, driver
    # and third-party allocations require additional room outside its allocator.
    fraction = min((min(budget, gpu.ceiling) - CONTEXT_RESERVE_MIB) / gpu.total
                   for gpu in rows)
    if fraction <= 0:
        raise GuardError("insufficient GPU headroom even for allocator/context reserve")
    old = env.get("PYTORCH_ALLOC_CONF", env.get("PYTORCH_CUDA_ALLOC_CONF", ""))
    # Keep unrelated allocator settings, but enforce the native backend and cap.
    import re
    old = re.sub(r"(?:^|,)(?:backend|per_process_memory_fraction):[^,]*", "", old).strip(",")
    env.pop("PYTORCH_CUDA_ALLOC_CONF", None)
    env["PYTORCH_ALLOC_CONF"] = ",".join(filter(None, [old, "backend:native", f"per_process_memory_fraction:{fraction:.8f}"]))
    env["OPENLABS_GPU_ALLOCATOR_FRACTION"] = f"{fraction:.8f}"
    # Transformers 5.3 otherwise queues GPU copies of unquantized weights
    # ahead of conversion, retaining a large temporary full-precision backlog.
    env["HF_DEACTIVATE_ASYNC_LOAD"] = "1"
    return env


def parent_pid(pid: int) -> int:
    try:
        return int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[1])
    except (OSError, ValueError, IndexError):
        return 0


def inherited_supervisor() -> bool:
    try:
        expected = int(os.environ.get("OPENLABS_GPU_SUPERVISOR_PID", "0"))
    except ValueError:
        return False
    pid = os.getppid()
    while pid > 1:
        if pid == expected:
            return True
        pid = parent_pid(pid)
    return False


def descendants(root: int) -> set[int]:
    parents = {}
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            pid = int(entry.name)
            parents[pid] = parent_pid(pid)
    found = {root}
    while True:
        expanded = found | {pid for pid, parent in parents.items() if parent in found}
        if expanded == found:
            return found - {root}
        found = expanded


def stop_children(process: subprocess.Popen) -> None:
    # A subreaper also owns orphaned grandchildren that called setsid().
    for sig, grace in ((signal.SIGINT, 1.0), (signal.SIGTERM, 1.0), (signal.SIGKILL, 0.2)):
        for pid in descendants(os.getpid()):
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            process.poll()
            try:
                while os.waitpid(-1, os.WNOHANG)[0] > 0:
                    pass
            except ChildProcessError:
                return
            time.sleep(0.05)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpu-memory-mib", type=int)
    parser.add_argument("--gpu-device", type=int, default=0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("a command is required")
    if inherited_supervisor():
        inherited_budget = int(os.environ.get("OPENLABS_GPU_BUDGET_MIB", "0"))
        if args.gpu_memory_mib is None:
            os.execvpe(command[0], command, os.environ)
        if inherited_budget:
            if args.gpu_memory_mib != inherited_budget or args.gpu_device != int(os.environ["OPENLABS_GPU_DEVICE"]):
                raise GuardError("nested GPU invocation must reuse the same reservation")
            # Retain the stronger outer reservation and its watchdog.
            os.execvpe(command[0], command, os.environ)
    if shutil.which("nvidia-smi") is None:
        if args.gpu_memory_mib is not None or Path("/dev/dxg").exists() or Path("/dev/nvidiactl").exists():
            raise GuardError("GPU present/requested but nvidia-smi is unavailable")
        os.execvpe(command[0], command, os.environ)
    rows = snapshot()
    check_limits(rows)
    baseline = None
    lease = None
    budget = args.gpu_memory_mib if args.gpu_memory_mib is not None else DEFAULT_BUDGET_MIB
    env = dict(os.environ)
    # Discard stale reservation metadata from a different ancestor/service.
    for key in ("OPENLABS_GPU_BUDGET_MIB", "OPENLABS_GPU_DEVICE"):
        env.pop(key, None)
    if args.gpu_memory_mib is not None:
        matches = [gpu for gpu in rows if gpu.index == args.gpu_device]
        if len(matches) != 1:
            raise GuardError("requested GPU index is unavailable")
        baseline = matches[0]
        runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
        lease = reserve(baseline, budget, runtime / "openlabs-gpu-guard")
        # Check again under the lock; another workload may have just finished.
        rows = snapshot()
        check_limits(rows)
        baseline = next(gpu for gpu in rows if gpu.uuid == baseline.uuid)
        if baseline.used + budget > baseline.ceiling:
            raise GuardError("GPU headroom changed during admission")
        env["CUDA_VISIBLE_DEVICES"] = baseline.uuid
        env["OPENLABS_GPU_BUDGET_MIB"] = str(budget)
        env["OPENLABS_GPU_DEVICE"] = str(args.gpu_device)
    env = allocator_environment(env, [baseline] if baseline else rows, budget)
    env["OPENLABS_GPU_SUPERVISOR_PID"] = str(os.getpid())
    print(f"OpenLabs GPU guard: reservation={args.gpu_memory_mib or 'monitor'} MiB; "
          f"max VRAM=75%, reserve>=2048 MiB; allocator fraction={env['OPENLABS_GPU_ALLOCATOR_FRACTION']}",
          file=sys.stderr, flush=True)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise GuardError("cannot establish GPU supervisor as child subreaper")
    interrupted = []
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda number, frame: interrupted.append(number))
    supervisor_pid = os.getpid()

    def child_setup():
        if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0 or os.getppid() != supervisor_pid:
            os._exit(125)  # PR_SET_PDEATHSIG, also close the parent-death race

    process = None
    try:
        process = subprocess.Popen(command, env=env, start_new_session=True, preexec_fn=child_setup)
        expected = {(gpu.uuid, gpu.total) for gpu in rows}
        while process.poll() is None:
            if interrupted:
                return 128 + interrupted[0]
            current = snapshot()
            if {(gpu.uuid, gpu.total) for gpu in current} != expected:
                raise GuardError("GPU inventory changed during execution")
            check_limits(current, baseline, budget)
            time.sleep(POLL_SECONDS)
        return process.returncode if process.returncode >= 0 else 128 - process.returncode
    finally:
        if process is not None:
            stop_children(process)
        if lease is not None:
            lease.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (GuardError, OSError) as exc:
        print(f"OpenLabs GPU guard: STOP: {exc}", file=sys.stderr, flush=True)
        sys.exit(75)
