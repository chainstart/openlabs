"""Conservative liveness watchdog for the persistent LLZTO process graph."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .provenance import atomic_write_json, fingerprint, sha256_file


_ROOT = Path(__file__).resolve().parents[2]
_TERMINAL_PREFIXES = ("failed", "blocked")


def _read_json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {source}")
    return payload


def _repo_path(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (_ROOT / path).resolve()


def matching_pids(marker: str) -> list[int]:
    """Return live process IDs whose NUL-separated command line has marker."""
    own_pid = os.getpid()
    encoded = marker.encode("utf-8")
    pids = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == own_pid:
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if encoded in command:
            pids.append(int(entry.name))
    return sorted(pids)


def _latest_progress(specification: dict[str, Any]) -> dict[str, Any] | None:
    pattern = specification.get("progress_glob")
    if not pattern:
        return None
    matches = list(_ROOT.glob(pattern))
    if not matches:
        return {"status": "not_materialized", "glob": pattern}
    latest = max(matches, key=lambda path: path.stat().st_mtime)
    age = max(0.0, time.time() - latest.stat().st_mtime)
    limit = float(specification["progress_stale_seconds"])
    return {
        "status": "fresh" if age <= limit else "stale",
        "path": str(latest.resolve()),
        "size_bytes": latest.stat().st_size,
        "age_seconds": age,
        "stale_after_seconds": limit,
    }


def _observed_protocol_sha256(state: dict[str, Any]) -> str | None:
    config = state.get("config", {})
    if not isinstance(config, dict):
        return None
    return (
        config.get("protocol_sha256")
        or config.get("association_protocol_sha256")
    )


def inspect_managed_process(
    specification: dict[str, Any],
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Classify one managed process and validate any state protocol hash."""
    current_time = time.time() if now is None else float(now)
    pids = matching_pids(str(specification["marker"]))
    completion_path = specification.get("completion_path")
    complete_by_artifact = bool(
        completion_path and _repo_path(completion_path).is_file()
    )
    row: dict[str, Any] = {
        "process_id": specification["process_id"],
        "policy": specification["policy"],
        "observed_pids": pids,
        "process_active": bool(pids),
        "complete_by_artifact": complete_by_artifact,
    }
    state_path_value = specification.get("state_path")
    if state_path_value:
        state_path = _repo_path(state_path_value)
        row["state_path"] = str(state_path)
        if state_path.is_file():
            state = _read_json(state_path)
            state_status = str(state.get("status", "missing_status"))
            updated = state.get("updated_unix_time")
            age = (
                max(0.0, current_time - float(updated))
                if isinstance(updated, (int, float))
                else None
            )
            row.update(
                state_status=state_status,
                state_sha256=sha256_file(state_path),
                state_age_seconds=age,
                state_complete=state_status == "complete",
                terminal_block=state_status.startswith(_TERMINAL_PREFIXES),
            )
            expected = specification.get("expected_protocol_sha256")
            if expected is not None:
                observed = _observed_protocol_sha256(state)
                row["protocol_sha256_expected"] = expected
                row["protocol_sha256_observed"] = observed
                row["protocol_hash_valid"] = observed == expected
                if observed != expected:
                    row["disposition"] = "protocol_mismatch"
                    row["healthy"] = False
                    return row
        else:
            row.update(
                state_status="missing",
                state_age_seconds=None,
                state_complete=False,
                terminal_block=False,
            )
    else:
        row.update(state_status=None, state_complete=complete_by_artifact)

    progress = _latest_progress(specification)
    if progress is not None:
        row["progress"] = progress

    if row.get("state_complete") or complete_by_artifact:
        row["disposition"] = "complete"
        row["healthy"] = True
    elif row.get("terminal_block"):
        row["disposition"] = "scientific_or_runtime_block"
        row["healthy"] = False
    elif pids:
        state_status = str(row.get("state_status", ""))
        stale_state = bool(
            row.get("state_age_seconds") is not None
            and row["state_age_seconds"]
            > float(specification.get("state_stale_seconds", 180))
            and (state_status == "created" or state_status.startswith("waiting_"))
        )
        stale_progress = progress is not None and progress.get("status") == "stale"
        row["disposition"] = (
            "active_but_stale" if stale_state or stale_progress else "active"
        )
        row["healthy"] = not (stale_state or stale_progress)
    else:
        state_status = str(row.get("state_status", "missing"))
        restartable = bool(
            specification["policy"] == "restart-waiting-only"
            and (state_status == "created" or state_status.startswith("waiting_"))
        )
        row["restart_allowed"] = restartable
        row["disposition"] = "restartable_waiter_missing" if restartable else "missing"
        row["healthy"] = False
    return row


def _launch_waiter(specification: dict[str, Any]) -> dict[str, Any]:
    module = specification.get("module")
    arguments = specification.get("args")
    if not isinstance(module, str) or not isinstance(arguments, list):
        raise ValueError(
            f"restartable process has no command: {specification['process_id']}"
        )
    log_path = _repo_path(specification["log_path"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", module, *[str(value) for value in arguments]]
    with log_path.open("ab") as output:
        process = subprocess.Popen(
            command,
            cwd=_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return {
        "pid": process.pid,
        "command": command,
        "log_path": str(log_path),
        "launched_unix_time": time.time(),
    }


def inspect_process_graph(configuration: dict[str, Any]) -> dict[str, Any]:
    """Inspect every process once without mutating or restarting anything."""
    rows = []
    for specification in configuration["managed"]:
        item = dict(specification)
        item.setdefault("state_stale_seconds", configuration["state_stale_seconds"])
        rows.append(inspect_managed_process(item))
    return {
        "healthy": all(row["healthy"] for row in rows),
        "n_managed": len(rows),
        "n_active": sum(row["process_active"] for row in rows),
        "n_complete": sum(row["disposition"] == "complete" for row in rows),
        "n_blocked": sum(
            row["disposition"] in {"scientific_or_runtime_block", "protocol_mismatch"}
            for row in rows
        ),
        "n_restartable_missing": sum(
            row["disposition"] == "restartable_waiter_missing" for row in rows
        ),
        "processes": rows,
    }


def run_watchdog(
    protocol_path: Path | str,
    *,
    state_path: Path | str,
    once: bool = False,
) -> dict[str, Any]:
    source = Path(protocol_path).resolve()
    configuration = _read_json(source)
    if configuration.get("schema_version") != "1.0":
        raise ValueError("watchdog protocol schema_version must be '1.0'")
    poll_seconds = float(configuration["poll_seconds"])
    if not 5 <= poll_seconds <= 60:
        raise ValueError("watchdog poll_seconds must be between 5 and 60")
    output_state = Path(state_path).resolve()
    config_record = {
        "protocol_path": str(source),
        "protocol_sha256": sha256_file(source),
        "implementation_path": str(Path(__file__).resolve()),
        "implementation_sha256": sha256_file(__file__),
    }
    watchdog_fingerprint = fingerprint(config_record)
    if output_state.is_file():
        state = _read_json(output_state)
        if state.get("watchdog_fingerprint") != watchdog_fingerprint:
            raise RuntimeError(f"watchdog configuration changed: {output_state}")
    else:
        state = {
            "schema_version": "1.0",
            "watchdog_fingerprint": watchdog_fingerprint,
            "config": config_record,
            "created_unix_time": time.time(),
            "restart_history": [],
        }
    while True:
        inspection = inspect_process_graph(configuration)
        restarted = []
        by_id = {row["process_id"]: row for row in inspection["processes"]}
        for specification in configuration["managed"]:
            row = by_id[specification["process_id"]]
            if row["disposition"] != "restartable_waiter_missing":
                continue
            launch = _launch_waiter(specification)
            record = {"process_id": specification["process_id"], **launch}
            state["restart_history"].append(record)
            restarted.append(record)
        status = "healthy" if inspection["healthy"] else "degraded"
        if inspection["n_blocked"]:
            status = "blocked"
        state.update(
            status=status,
            inspection=inspection,
            restarted_this_cycle=restarted,
            updated_unix_time=time.time(),
        )
        atomic_write_json(output_state, state)
        if once:
            return state
        time.sleep(poll_seconds)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    result = run_watchdog(args.protocol, state_path=args.state, once=args.once)
    if args.once:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
