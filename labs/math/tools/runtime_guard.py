#!/usr/bin/env python3
"""Fail-closed process limits for trusted mathematics runtime adapters."""

from __future__ import annotations

import os
import resource
import shutil
import signal
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Sequence


MIB = 1024 * 1024


def host_memory_mib(meminfo: Path = Path("/proc/meminfo")) -> int:
    """Return kernel-visible physical memory, which reflects the WSL VM limit."""

    try:
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                kib = int(line.split()[1])
                if kib > 0:
                    return max(1, kib // 1024)
    except (OSError, ValueError, IndexError) as exc:
        raise RuntimeError(f"could not determine host memory from {meminfo}: {exc}") from exc
    raise RuntimeError(f"could not determine host memory from {meminfo}")


def host_cpu_threads() -> int:
    """Return the CPU set available to this WSL process."""

    try:
        count = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        count = os.cpu_count() or 1
    return max(1, count)


def _fractional_limit(total: int, fraction: float, name: str) -> int:
    if isinstance(fraction, bool) or not isinstance(fraction, (int, float)):
        raise ValueError(f"{name} must be a number")
    if not 0 < float(fraction) <= 1:
        raise ValueError(f"{name} must be greater than 0 and at most 1")
    return max(1, int(total * float(fraction)))


def _positive_environment(name: str, fallback: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return fallback
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


@dataclass(frozen=True)
class ResourceLimits:
    memory_mib: int
    cpu_seconds: int
    wall_seconds: int
    file_mib: int
    open_files: int
    threads: int
    output_mib: int = 4
    address_space_mib: int = 0
    processes: int = 64

    def to_dict(self) -> dict[str, int]:
        value = asdict(self)
        if value["address_space_mib"] < 1:
            value["address_space_mib"] = max(self.memory_mib * 4, 8192)
        return value


@dataclass(frozen=True)
class GuardedResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    output_overflow: bool
    limits: ResourceLimits


def limits_from_environment(
    *,
    wall_seconds: int,
    max_memory_mib: int | None = None,
    memory_fraction_of_host: float | None = None,
    max_cpu_seconds: int,
    max_file_mib: int,
    max_threads: int | None = None,
    threads_fraction_of_host: float | None = None,
    output_mib: int = 4,
    respect_task_reservations: bool = True,
) -> ResourceLimits:
    if wall_seconds < 1:
        raise ValueError("wall_seconds must be positive")
    if max_memory_mib is None and memory_fraction_of_host is None:
        raise ValueError("a memory ceiling or host-memory fraction is required")
    if max_threads is None and threads_fraction_of_host is None:
        raise ValueError("a thread ceiling or host-CPU fraction is required")

    memory_ceiling = (
        _fractional_limit(
            host_memory_mib(),
            memory_fraction_of_host,
            "memory_fraction_of_host",
        )
        if memory_fraction_of_host is not None
        else int(max_memory_mib or 0)
    )
    if max_memory_mib is not None:
        memory_ceiling = min(memory_ceiling, max_memory_mib)
    thread_ceiling = (
        _fractional_limit(
            host_cpu_threads(),
            threads_fraction_of_host,
            "threads_fraction_of_host",
        )
        if threads_fraction_of_host is not None
        else int(max_threads or 0)
    )
    if max_threads is not None:
        thread_ceiling = min(thread_ceiling, max_threads)

    if respect_task_reservations:
        reserved_memory = _positive_environment("OPENLABS_MEMORY_MIB", memory_ceiling)
        reserved_scratch = _positive_environment("OPENLABS_SCRATCH_MIB", max_file_mib)
        reserved_threads = _positive_environment("OPENLABS_CPU_THREADS", thread_ceiling)
    else:
        reserved_memory = memory_ceiling
        reserved_scratch = max_file_mib
        reserved_threads = thread_ceiling
    memory_mib = min(reserved_memory, memory_ceiling)
    threads = min(reserved_threads, thread_ceiling)
    bounded_wall = min(wall_seconds, max_cpu_seconds * 2)
    return ResourceLimits(
        memory_mib=memory_mib,
        cpu_seconds=min(max_cpu_seconds, max(1, bounded_wall * threads)),
        wall_seconds=bounded_wall,
        file_mib=min(reserved_scratch, max_file_mib),
        open_files=256,
        threads=threads,
        output_mib=output_mib,
        address_space_mib=max(memory_mib * 4, 8192),
        processes=max(32, threads * 16),
    )


def guarded_environment(
    limits: ResourceLimits,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    environment = dict(base or os.environ)
    thread_count = str(limits.threads)
    for name in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "LEAN_NUM_THREADS",
    ):
        environment[name] = thread_count
    return environment


def _install_limits(limits: ResourceLimits) -> None:
    address_space_mib = limits.to_dict()["address_space_mib"]
    memory_bytes = address_space_mib * MIB
    file_bytes = limits.file_mib * MIB
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    resource.setrlimit(
        resource.RLIMIT_CPU,
        (limits.cpu_seconds, limits.cpu_seconds + 1),
    )
    resource.setrlimit(resource.RLIMIT_FSIZE, (file_bytes, file_bytes))
    resource.setrlimit(resource.RLIMIT_NOFILE, (limits.open_files, limits.open_files))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _read_bounded(handle, limit: int) -> tuple[str, bool]:
    size = handle.seek(0, os.SEEK_END)
    overflow = size > limit
    handle.seek(0)
    raw = handle.read(min(size, limit))
    return raw.decode("utf-8", errors="replace"), overflow


def run_guarded(
    command: Sequence[str],
    *,
    cwd: Path,
    limits: ResourceLimits,
    environment: Mapping[str, str] | None = None,
    stdin: str | None = None,
) -> GuardedResult:
    if not command or any(not isinstance(item, str) or not item for item in command):
        raise ValueError("guarded command must be a non-empty argv sequence")
    systemd_run = shutil.which("systemd-run")
    scope_available = False
    if systemd_run is not None:
        try:
            probe = subprocess.run(
                [systemd_run, "--user", "--scope", "--quiet", "--", "true"],
                cwd=cwd,
                env=guarded_environment(limits, environment),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
            scope_available = probe.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            scope_available = False
    # Native Codex workspace isolation may intentionally hide the user D-Bus.
    # In that case execute directly with RLIMIT_AS/CPU/FSIZE/NOFILE. Factory
    # runs additionally inherit the aggregate openlabs-workers.slice MemoryMax.
    guarded_command = list(command)
    if scope_available and systemd_run is not None:
        guarded_command = [
            systemd_run,
            "--user",
            "--scope",
            "--slice=openlabs-workers.slice",
            "--quiet",
            "-p",
            "PartOf=openlabs-workers.target",
            "-p",
            f"MemoryMax={limits.memory_mib}M",
            "-p",
            "MemorySwapMax=0",
            "-p",
            f"TasksMax={limits.processes}",
            "-p",
            "OOMPolicy=stop",
            "--",
            *command,
        ]
    output_limit = limits.output_mib * MIB
    with tempfile.TemporaryFile() as stdout_handle, tempfile.TemporaryFile() as stderr_handle:
        process = subprocess.Popen(
            guarded_command,
            cwd=cwd,
            env=guarded_environment(limits, environment),
            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
            start_new_session=True,
            preexec_fn=lambda: _install_limits(limits),
        )
        timed_out = False
        try:
            process.communicate(input=stdin, timeout=limits.wall_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        stdout, stdout_overflow = _read_bounded(stdout_handle, output_limit)
        stderr, stderr_overflow = _read_bounded(stderr_handle, output_limit)
    return GuardedResult(
        args=tuple(command),
        returncode=int(process.returncode),
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        output_overflow=stdout_overflow or stderr_overflow,
        limits=limits,
    )
