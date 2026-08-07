"""Persistent waiter for convention-explicit LLZTO Haven validation."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .haven_validation import build_haven_validation_report
from .provenance import atomic_write_json, fingerprint, sha256_file


_ROOT = Path(__file__).resolve().parents[2]


def _read_json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {source}")
    return payload


def _repo_path(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (_ROOT / path).resolve()


def _update(path: Path, state: dict[str, Any], status: str, **fields: Any) -> None:
    state["status"] = status
    state.update(fields)
    state["updated_unix_time"] = time.time()
    atomic_write_json(path, state)


def _verify_report(path: Path, protocol_sha256: str) -> dict[str, Any]:
    report = _read_json(path)
    unsigned = dict(report)
    stored = unsigned.pop("report_fingerprint", None)
    if stored != fingerprint(unsigned):
        raise RuntimeError(f"Haven report fingerprint mismatch: {path}")
    if report.get("protocol_sha256") != protocol_sha256:
        raise RuntimeError("existing Haven report uses a different protocol")
    return report


def run_haven_queue(
    protocol_path: Path | str,
    *,
    state_path: Path | str,
    poll_seconds: float = 30.0,
) -> dict[str, Any]:
    """Wait for the hierarchy, then create one immutable Haven report."""
    if not 5.0 <= poll_seconds <= 60.0:
        raise ValueError("poll_seconds must be between 5 and 60")
    source = Path(protocol_path).resolve()
    protocol = _read_json(source)
    if protocol.get("schema_version") != "1.0":
        raise ValueError("Haven protocol schema_version must be '1.0'")
    locked_paths = [
        source,
        Path(__file__).resolve(),
        Path(__file__).with_name("haven_validation.py").resolve(),
        Path(__file__).with_name("transport_statistics.py").resolve(),
        Path(__file__).with_name("velocity_statistics.py").resolve(),
        Path(__file__).with_name("provenance.py").resolve(),
        _repo_path(protocol["primary_hierarchical_input"]["analysis_protocol_path"]),
        _repo_path(protocol["formal_campaign"]["protocol_path"]),
        _repo_path(protocol["experimental_benchmark"]["path"]),
    ]
    locked_files = [
        {"path": str(path), "sha256": sha256_file(path)} for path in locked_paths
    ]
    protocol_sha = sha256_file(source)
    config = {
        "protocol_path": str(source),
        "protocol_sha256": protocol_sha,
        "primary_report_path": str(
            _repo_path(protocol["primary_hierarchical_input"]["report_path"])
        ),
        "output_path": str(_repo_path(protocol["output_path"])),
        "poll_seconds": poll_seconds,
        "locked_files": locked_files,
    }
    queue_fingerprint = fingerprint(config)
    output_state = Path(state_path).resolve()
    if output_state.is_file():
        state = _read_json(output_state)
        if state.get("queue_fingerprint") != queue_fingerprint:
            raise RuntimeError(f"Haven queue configuration changed: {output_state}")
    else:
        state = {
            "schema_version": "1.0",
            "queue_fingerprint": queue_fingerprint,
            "config": config,
            "created_unix_time": time.time(),
        }
        _update(output_state, state, "created")

    def verify_locks() -> None:
        for record in locked_files:
            if sha256_file(record["path"]) != record["sha256"]:
                raise RuntimeError(f"Haven queue locked file changed: {record['path']}")

    primary_path = Path(config["primary_report_path"])
    destination = Path(config["output_path"])
    try:
        while not primary_path.is_file():
            verify_locks()
            _update(
                output_state,
                state,
                "waiting_for_hierarchical_transport_report",
                waiting={
                    "path": str(primary_path),
                    "checked_unix_time": time.time(),
                },
            )
            time.sleep(poll_seconds)
        verify_locks()
        _update(
            output_state,
            state,
            "building_haven_convention_validation",
            primary_report_sha256=sha256_file(primary_path),
        )
        if destination.is_file():
            report = _verify_report(destination, protocol_sha)
        else:
            report = build_haven_validation_report(source)
            atomic_write_json(destination, report)
            if _verify_report(destination, protocol_sha) != report:
                raise RuntimeError("stored Haven report differs from builder output")
        complete = report.get("analysis_completeness_gate_pass") is True
        _update(
            output_state,
            state,
            "complete" if complete else "blocked_scientific_gate",
            waiting=None,
            output={
                "path": str(destination),
                "sha256": sha256_file(destination),
                "report_fingerprint": report["report_fingerprint"],
                "analysis_completeness_gate_pass": complete,
                "compatible_with_new_configuration_prediction": report[
                    "experimental_comparison"
                ]["compatible_with_new_configuration_prediction"],
            },
        )
        return state
    except Exception as exc:
        _update(
            output_state,
            state,
            "failed_exception",
            error={"type": type(exc).__name__, "message": str(exc)},
        )
        raise


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    args = parser.parse_args()
    run_haven_queue(
        args.protocol,
        state_path=args.state,
        poll_seconds=args.poll_seconds,
    )


if __name__ == "__main__":
    main()
