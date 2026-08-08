#!/usr/bin/env python3
"""Run one snapshot-bound Lean audit behind conservative resource guards.

This command is intentionally separate from the two score-bearing reviewers.
It serializes Lean builds across the host, limits Lean's task pool, constrains
CPU affinity and per-process address space, watches aggregate descendant RSS
and process count, enforces a wall-clock deadline, and writes one objective
receipt that both reviewers may read.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Sequence


SCHEMA_VERSION = "ara.paper_writing.lean_objective_audit.v1"
DEFAULT_THREADS = 2
MAX_THREADS = 4
DEFAULT_AGGREGATE_RSS_MIB = 16384
MAX_AGGREGATE_RSS_MIB = 24576
DEFAULT_PER_PROCESS_AS_MIB = 24576
MAX_PER_PROCESS_AS_MIB = 32768
DEFAULT_MAX_PROCESSES = 12
MAX_PROCESSES = 24
DEFAULT_TIMEOUT_SECONDS = 3600
MAX_TIMEOUT_SECONDS = 3600
DEFAULT_MIN_DISK_MIB = 4096
MIN_HOST_MEMORY_RESERVE_MIB = 8192
POLL_SECONDS = 0.25
OUTPUT_TAIL_BYTES = 16 * 1024
GLOBAL_LOCK_NAME = "openlabs-paper-writing-lean-audit.lock"


class AuditError(RuntimeError):
    """Bounded audit failure with a stable machine-facing reason."""

    def __init__(
        self,
        reason: str,
        message: str,
        *,
        command_result: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.command_result = command_result


@dataclass(frozen=True)
class ResourceLimits:
    threads: int = DEFAULT_THREADS
    aggregate_rss_mib: int = DEFAULT_AGGREGATE_RSS_MIB
    per_process_as_mib: int = DEFAULT_PER_PROCESS_AS_MIB
    max_processes: int = DEFAULT_MAX_PROCESSES
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    min_disk_mib: int = DEFAULT_MIN_DISK_MIB

    def validate(self) -> None:
        bounded = (
            ("threads", self.threads, 1, MAX_THREADS),
            ("aggregate_rss_mib", self.aggregate_rss_mib, 1024, MAX_AGGREGATE_RSS_MIB),
            ("per_process_as_mib", self.per_process_as_mib, 1024, MAX_PER_PROCESS_AS_MIB),
            ("max_processes", self.max_processes, 2, MAX_PROCESSES),
            ("timeout_seconds", self.timeout_seconds, 60, MAX_TIMEOUT_SECONDS),
            ("min_disk_mib", self.min_disk_mib, 1024, 16384),
        )
        for name, value, minimum, maximum in bounded:
            if not minimum <= value <= maximum:
                raise AuditError(
                    "invalid_limits",
                    f"{name} must be between {minimum} and {maximum}; got {value}",
                )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_hashes(project: Path) -> dict[str, str]:
    selected: set[Path] = set()
    for name in ("lean-toolchain", "lake-manifest.json", "lakefile.lean", "lakefile.toml"):
        path = project / name
        if path.is_file():
            selected.add(path)
    selected.update(
        path
        for path in project.rglob("*.lean")
        if ".lake" not in path.relative_to(project).parts
    )
    if not selected:
        raise AuditError("missing_sources", "Lean project has no auditable source/configuration files")
    return {
        path.relative_to(project).as_posix(): _sha256_file(path)
        for path in sorted(selected)
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _memory_mib() -> tuple[int, int]:
    values: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        name, separator, remainder = line.partition(":")
        if separator and name in {"MemTotal", "MemAvailable"}:
            values[name] = int(remainder.split()[0]) // 1024
    if set(values) != {"MemTotal", "MemAvailable"}:
        raise AuditError(
            "preflight_unavailable",
            "cannot read MemTotal and MemAvailable from /proc/meminfo",
        )
    return values["MemTotal"], values["MemAvailable"]


def _cpu_sample() -> tuple[int, int]:
    fields = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()[1:]
    values = [int(value) for value in fields]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return idle, sum(values)


def _cpu_utilization() -> float:
    idle_before, total_before = _cpu_sample()
    time.sleep(0.25)
    idle_after, total_after = _cpu_sample()
    total_delta = max(1, total_after - total_before)
    return 1.0 - ((idle_after - idle_before) / total_delta)


def _preflight(project: Path, limits: ResourceLimits) -> dict[str, float | int]:
    total_mib, available_mib = _memory_mib()
    reserved_headroom_mib = max(MIN_HOST_MEMORY_RESERVE_MIB, total_mib // 4)
    required_mib = limits.aggregate_rss_mib + reserved_headroom_mib
    if available_mib < required_mib:
        raise AuditError(
            "insufficient_memory",
            f"Lean audit requires {limits.aggregate_rss_mib} MiB for the audit plus "
            f"{reserved_headroom_mib} MiB reserved for the host "
            f"({required_mib} MiB available in total); found {available_mib} MiB",
        )
    disk_mib = shutil.disk_usage(project).free // (1024 * 1024)
    if disk_mib < limits.min_disk_mib:
        raise AuditError(
            "insufficient_disk",
            f"Lean audit requires at least {limits.min_disk_mib} MiB free; found {disk_mib} MiB",
        )
    cpu = _cpu_utilization()
    if cpu > 0.85:
        raise AuditError(
            "host_busy",
            f"host CPU utilization is {cpu:.1%}; retry when it is at or below 85%",
        )
    return {
        "total_memory_mib": total_mib,
        "available_memory_mib": available_mib,
        "reserved_headroom_mib": reserved_headroom_mib,
        "required_available_memory_mib": required_mib,
        "free_disk_mib": disk_mib,
        "cpu_utilization": round(cpu, 4),
    }


def _process_table() -> dict[int, tuple[int, int]]:
    table: dict[int, tuple[int, int]] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            status = (entry / "status").read_text(encoding="utf-8")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        parent = 0
        rss_kib = 0
        for line in status.splitlines():
            if line.startswith("PPid:"):
                parent = int(line.split()[1])
            elif line.startswith("VmRSS:"):
                rss_kib = int(line.split()[1])
        table[int(entry.name)] = (parent, rss_kib)
    return table


def _descendant_usage(root_pid: int) -> tuple[list[int], int]:
    table = _process_table()
    descendants = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, (parent, _) in table.items():
            if parent in descendants and pid not in descendants:
                descendants.add(pid)
                changed = True
    rss_kib = sum(table.get(pid, (0, 0))[1] for pid in descendants)
    return sorted(descendants), rss_kib // 1024


def _terminate_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=5)


def _log_summary(handle: BinaryIO) -> dict[str, str | int]:
    handle.flush()
    size = handle.seek(0, os.SEEK_END)
    digest = hashlib.sha256()
    handle.seek(0)
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
    handle.seek(max(0, size - OUTPUT_TAIL_BYTES))
    tail = handle.read().decode("utf-8", errors="replace")
    return {"bytes": size, "sha256": digest.hexdigest(), "tail": tail}


def _portable_log(log: dict[str, str | int], project: Path) -> dict[str, str | int]:
    """Redact machine-specific absolute prefixes without changing log hashes."""

    portable = dict(log)
    tail = str(portable.get("tail", ""))
    tail = tail.replace(str(project), "<lean-project>")
    tail = tail.replace(str(Path.home()), "<user-home>")
    portable["tail"] = tail
    return portable


def _preexec(cpu_ids: Sequence[int], per_process_as_mib: int) -> None:
    os.setsid()
    os.nice(10)
    if hasattr(os, "sched_setaffinity"):
        os.sched_setaffinity(0, set(cpu_ids))
    address_space = per_process_as_mib * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (address_space, address_space))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    file_size = 2 * 1024 * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_FSIZE, (file_size, file_size))


def _run_command(
    command: list[str],
    *,
    project: Path,
    environment: dict[str, str],
    limits: ResourceLimits,
    cpu_ids: Sequence[int],
    deadline: float,
) -> dict[str, object]:
    started = time.monotonic()
    peak_rss_mib = 0
    peak_processes = 0
    with tempfile.TemporaryFile(mode="w+b") as output:
        process = subprocess.Popen(
            command,
            cwd=project,
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
            preexec_fn=lambda: _preexec(cpu_ids, limits.per_process_as_mib),
        )
        violation: str | None = None
        while process.poll() is None:
            pids, rss_mib = _descendant_usage(process.pid)
            peak_rss_mib = max(peak_rss_mib, rss_mib)
            peak_processes = max(peak_processes, len(pids))
            if len(pids) > limits.max_processes:
                violation = "process_limit"
            elif rss_mib > limits.aggregate_rss_mib:
                violation = "memory_limit"
            elif time.monotonic() >= deadline:
                violation = "timeout"
            if violation:
                _terminate_group(process)
                break
            time.sleep(POLL_SECONDS)
        return_code = process.poll()
        elapsed = round(time.monotonic() - started, 3)
        log = _portable_log(_log_summary(output), project)
    result: dict[str, object] = {
        "command": command,
        "return_code": return_code,
        "elapsed_seconds": elapsed,
        "peak_descendant_rss_mib": peak_rss_mib,
        "peak_processes": peak_processes,
        "output": log,
    }
    if violation:
        result["resource_violation"] = violation
        raise AuditError(
            violation,
            json.dumps(result, sort_keys=True),
            command_result=result,
        )
    if return_code != 0:
        raise AuditError(
            "command_failed",
            json.dumps(result, sort_keys=True),
            command_result=result,
        )
    return result


def _commands(audit_file: Path) -> list[list[str]]:
    return [
        ["lake", "build", "--quiet"],
        ["lake", "env", "lean", audit_file.as_posix()],
    ]


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _matching_pass_receipt(
    path: Path,
    *,
    paper_id: str,
    snapshot: str,
    support_sha256: str,
    source_hashes: dict[str, str],
) -> bool:
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        payload.get("schema_version") == SCHEMA_VERSION
        and payload.get("status") == "PASS"
        and payload.get("paper_id") == paper_id
        and payload.get("manuscript_snapshot_sha256") == snapshot
        and payload.get("support_package_sha256") == support_sha256
        and payload.get("source_sha256") == source_hashes
        and payload.get("formal_validation_execution_count") == 1
        and payload.get("cumulative_formal_validation_execution_count") == 1
    )


def _is_formal_validation_result(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    command = entry.get("command")
    return isinstance(command, list) and command[:3] == ["lake", "env", "lean"]


def _formal_validation_execution_count(payload: dict[str, object]) -> int:
    recorded = payload.get("formal_validation_execution_count")
    if isinstance(recorded, int) and not isinstance(recorded, bool) and recorded >= 0:
        return recorded
    commands = payload.get("commands")
    if not isinstance(commands, list):
        return 0
    return sum(1 for entry in commands if _is_formal_validation_result(entry))


def _prior_failed_attempt(
    path: Path,
    *,
    root: Path,
    paper_id: str,
    snapshot: str,
    support_sha256: str,
    source_hashes: dict[str, str],
) -> dict[str, str | int]:
    resolved = path.resolve()
    try:
        source = resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise AuditError(
            "outside_repository", "prior failed receipt must stay inside the repository"
        ) from exc
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditError("invalid_prior_receipt", f"cannot read prior failed receipt: {exc}") from exc
    expected = {
        "schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "paper_id": paper_id,
        "manuscript_snapshot_sha256": snapshot,
        "support_package_sha256": support_sha256,
        "source_sha256": source_hashes,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise AuditError(
                "invalid_prior_receipt",
                f"prior failed receipt {key} does not match the frozen audit input",
            )
    failure = payload.get("failure")
    reason = failure.get("reason") if isinstance(failure, dict) else None
    if not isinstance(reason, str) or not reason:
        raise AuditError("invalid_prior_receipt", "prior failed receipt has no failure reason")
    cumulative_count = payload.get("cumulative_formal_validation_execution_count")
    if not isinstance(cumulative_count, int) or isinstance(cumulative_count, bool):
        cumulative_count = _formal_validation_execution_count(payload)
    if cumulative_count != 0:
        raise AuditError(
            "formal_validation_already_executed",
            "the prior audit already executed formal validation; it may not be repeated",
        )
    return {
        "source": source,
        "sha256": _sha256_file(resolved),
        "reason": reason,
        "cumulative_formal_validation_execution_count": cumulative_count,
    }


def run(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    project = (root / args.project).resolve()
    output = (root / args.output).resolve()
    if not project.is_dir():
        raise AuditError("missing_project", f"Lean project does not exist: {project}")
    try:
        project.relative_to(root)
        output.relative_to(root)
    except ValueError as exc:
        raise AuditError("outside_repository", "project and output must stay inside the repository") from exc
    audit_file = Path(args.audit_file)
    if audit_file.is_absolute() or ".." in audit_file.parts or not (project / audit_file).is_file():
        raise AuditError("missing_audit_file", f"invalid audit file: {audit_file}")
    if not re_full_sha256(args.manuscript_snapshot) or not re_full_sha256(args.support_sha256):
        raise AuditError("invalid_binding", "snapshot and support hashes must be lowercase SHA-256 values")

    limits = ResourceLimits(
        threads=args.threads,
        aggregate_rss_mib=args.aggregate_rss_mib,
        per_process_as_mib=args.per_process_as_mib,
        max_processes=args.max_processes,
        timeout_seconds=args.timeout_seconds,
        min_disk_mib=args.min_disk_mib,
    )
    limits.validate()
    source_hashes = _source_hashes(project)
    prior_failed_attempt = None
    if args.prior_failed_receipt:
        prior_path = Path(args.prior_failed_receipt)
        if not prior_path.is_absolute():
            prior_path = root / prior_path
        prior_failed_attempt = _prior_failed_attempt(
            prior_path,
            root=root,
            paper_id=args.paper_id,
            snapshot=args.manuscript_snapshot,
            support_sha256=args.support_sha256,
            source_hashes=source_hashes,
        )
    if _matching_pass_receipt(
        output,
        paper_id=args.paper_id,
        snapshot=args.manuscript_snapshot,
        support_sha256=args.support_sha256,
        source_hashes=source_hashes,
    ):
        print(json.dumps({"status": "PASS", "receipt": output.as_posix(), "reused": True}))
        return 0
    if output.exists():
        raise AuditError(
            "receipt_conflict",
            "an existing receipt does not match this frozen input; use a new snapshot-bound path",
        )

    # This lock is deliberately host-global rather than project-specific. Two
    # unrelated formal projects can otherwise each stay under their local cap
    # while exhausting the host together.
    lock_path = Path(tempfile.gettempdir()) / GLOBAL_LOCK_NAME
    with lock_path.open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AuditError("already_running", "another Lean audit is already running for this project") from exc

        preflight = _preflight(project, limits)
        available_cpus = sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else list(range(os.cpu_count() or 1))
        cpu_ids = available_cpus[: limits.threads]
        if not cpu_ids:
            raise AuditError("no_cpu", "no CPU is available to the Lean audit")
        environment = dict(os.environ)
        environment.update(
            {
                "LEAN_NUM_THREADS": str(limits.threads),
                "OMP_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1",
                "NUMEXPR_NUM_THREADS": "1",
            }
        )
        started_at = _utc_now()
        deadline = time.monotonic() + limits.timeout_seconds
        command_results: list[dict[str, object]] = []
        status = "PASS"
        failure: dict[str, str] | None = None
        try:
            for command in _commands(audit_file):
                command_results.append(
                    _run_command(
                        command,
                        project=project,
                        environment=environment,
                        limits=limits,
                        cpu_ids=cpu_ids,
                        deadline=deadline,
                    )
                )
        except AuditError as exc:
            status = "FAIL"
            if exc.command_result is not None:
                command_results.append(exc.command_result)
            failure = {"reason": exc.reason, "message": str(exc)}

        receipt: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "status": status,
            "paper_id": args.paper_id,
            "manuscript_snapshot_sha256": args.manuscript_snapshot,
            "support_package_sha256": args.support_sha256,
            "project": project.relative_to(root).as_posix(),
            "audit_file": audit_file.as_posix(),
            "source_sha256": source_hashes,
            "resource_limits": {**asdict(limits), "cpu_affinity": cpu_ids},
            "preflight": preflight,
            "commands": command_results,
            "started_at": started_at,
            "completed_at": _utc_now(),
            "objective_only": True,
            "score_bearing": False,
            "execution_count": 1,
            "formal_validation_execution_count": sum(
                1 for result in command_results if _is_formal_validation_result(result)
            ),
        }
        receipt["cumulative_formal_validation_execution_count"] = (
            int(receipt["formal_validation_execution_count"])
            + (
                int(prior_failed_attempt["cumulative_formal_validation_execution_count"])
                if prior_failed_attempt is not None
                else 0
            )
        )
        if prior_failed_attempt is not None:
            receipt["reconstruction_continuation"] = True
            receipt["prior_failed_attempt"] = prior_failed_attempt
        if failure is not None:
            receipt["failure"] = failure
        _atomic_json(output, receipt)
        print(json.dumps({"status": status, "receipt": output.as_posix(), "reused": False}))
        return 0 if status == "PASS" else 1


def re_full_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--root", default=".")
    result.add_argument("--paper-id", required=True)
    result.add_argument("--project", required=True)
    result.add_argument("--audit-file", required=True)
    result.add_argument("--manuscript-snapshot", required=True)
    result.add_argument("--support-sha256", required=True)
    result.add_argument("--output", required=True)
    result.add_argument(
        "--prior-failed-receipt",
        help=(
            "same-snapshot FAIL receipt when continuing an interrupted incremental build; "
            "the failed receipt is retained and hash-linked"
        ),
    )
    result.add_argument("--threads", type=int, default=DEFAULT_THREADS)
    result.add_argument("--aggregate-rss-mib", type=int, default=DEFAULT_AGGREGATE_RSS_MIB)
    result.add_argument("--per-process-as-mib", type=int, default=DEFAULT_PER_PROCESS_AS_MIB)
    result.add_argument("--max-processes", type=int, default=DEFAULT_MAX_PROCESSES)
    result.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    result.add_argument("--min-disk-mib", type=int, default=DEFAULT_MIN_DISK_MIB)
    return result


if __name__ == "__main__":
    try:
        raise SystemExit(run(parser().parse_args()))
    except AuditError as exc:
        print(json.dumps({"status": "ERROR", "reason": exc.reason, "message": str(exc)}), file=sys.stderr)
        raise SystemExit(2)
