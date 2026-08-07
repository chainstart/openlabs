from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.mechanism_queue import (  # noqa: E402
    acquire_analysis_lock,
    inspect_analysis_job,
    release_analysis_lock,
)
from matfactory.provenance import sha256_file  # noqa: E402


def _write_report(
    path: Path,
    trajectory: Path,
    *,
    protocol_sha256: str,
    implementation: Path,
) -> None:
    path.write_text(
        json.dumps(
            {
                "trajectory_path": str(trajectory.resolve()),
                "trajectory_sha256": sha256_file(trajectory),
                "protocol_sha256": protocol_sha256,
                "implementation_path": str(implementation.resolve()),
                "implementation_sha256": sha256_file(implementation),
            }
        )
    )


def test_formal_mechanism_cpu_lock_is_exclusive(tmp_path):
    lock_path = tmp_path / "analysis.lock"
    first = acquire_analysis_lock(lock_path)
    assert first is not None
    try:
        assert acquire_analysis_lock(lock_path) is None
    finally:
        release_analysis_lock(first)
    second = acquire_analysis_lock(lock_path)
    assert second is not None
    release_analysis_lock(second)


def test_analysis_job_waits_for_complete_transport_then_resumes_components(tmp_path):
    trajectory = tmp_path / "T800.traj"
    transport = tmp_path / "T800.transport.json"
    primary = tmp_path / "T800.json"
    sensitivity = tmp_path / "T800.sensitivity.json"
    protocol_hash = "frozen-mechanism-protocol"
    waiting = inspect_analysis_job(
        trajectory,
        transport,
        primary,
        sensitivity,
        mechanism_protocol_sha256=protocol_hash,
    )
    assert waiting["state"] == "waiting_for_input"

    trajectory.write_bytes(b"completed trajectory")
    transport.write_text(json.dumps({"temperature_k": 800, "transport": {}}))
    ready = inspect_analysis_job(
        trajectory,
        transport,
        primary,
        sensitivity,
        mechanism_protocol_sha256=protocol_hash,
    )
    assert ready["state"] == "ready"
    assert ready["components_to_run"] == ["primary", "sensitivity"]

    _write_report(
        primary,
        trajectory,
        protocol_sha256=protocol_hash,
        implementation=ROOT / "src/matfactory/mechanisms.py",
    )
    resumed = inspect_analysis_job(
        trajectory,
        transport,
        primary,
        sensitivity,
        mechanism_protocol_sha256=protocol_hash,
    )
    assert resumed["components_to_run"] == ["sensitivity"]

    _write_report(
        sensitivity,
        trajectory,
        protocol_sha256=protocol_hash,
        implementation=ROOT / "src/matfactory/mechanism_sensitivity.py",
    )
    completed = inspect_analysis_job(
        trajectory,
        transport,
        primary,
        sensitivity,
        mechanism_protocol_sha256=protocol_hash,
    )
    assert completed["state"] == "already_complete"
    assert set(completed["outputs"]) == {"primary", "sensitivity"}


def test_analysis_job_rejects_stale_trajectory_hash(tmp_path):
    trajectory = tmp_path / "T800.traj"
    transport = tmp_path / "T800.transport.json"
    primary = tmp_path / "T800.json"
    sensitivity = tmp_path / "T800.sensitivity.json"
    trajectory.write_bytes(b"first")
    transport.write_text(json.dumps({"temperature_k": 800, "transport": {}}))
    _write_report(
        primary,
        trajectory,
        protocol_sha256="frozen",
        implementation=ROOT / "src/matfactory/mechanisms.py",
    )
    trajectory.write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="trajectory_sha256"):
        inspect_analysis_job(
            trajectory,
            transport,
            primary,
            sensitivity,
            mechanism_protocol_sha256="frozen",
        )
