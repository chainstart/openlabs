from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.provenance import fingerprint, sha256_file
from matfactory.qe_queue import (
    archive_interrupted_run,
    build_qe_command,
    verify_frozen_run,
)


def _frozen_run(tmp_path: Path, executable: Path) -> Path:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    input_path = run_dir / "pw.in"
    input_path.write_text("frozen input\n")
    manifest = {
        "run_id": "test-run",
        "run_fingerprint": fingerprint({"test": True}),
        "input_path": str(input_path),
        "input_sha256": sha256_file(input_path),
        "pw_executable_sha256": sha256_file(executable),
        "n_atoms": 1,
        "structure_fingerprint": "structure",
        "settings": {"label": "test"},
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest))
    return run_dir


def test_verify_frozen_run_accepts_ready_and_rejects_partial_output(tmp_path):
    executable = tmp_path / "pw.x"
    executable.write_text("binary")
    run_dir = _frozen_run(tmp_path, executable)
    assert verify_frozen_run(run_dir, executable)["state"] == "ready"

    (run_dir / "pw.out").write_text("incomplete")
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        verify_frozen_run(run_dir, executable)


def test_verify_frozen_run_rejects_input_or_binary_change(tmp_path):
    executable = tmp_path / "pw.x"
    executable.write_text("binary")
    run_dir = _frozen_run(tmp_path, executable)
    (run_dir / "pw.in").write_text("changed")
    with pytest.raises(RuntimeError, match="input hash mismatch"):
        verify_frozen_run(run_dir, executable)

    (run_dir / "pw.in").write_text("frozen input\n")
    executable.write_text("changed binary")
    with pytest.raises(RuntimeError, match="executable hash mismatch"):
        verify_frozen_run(run_dir, executable)


def test_qe_command_records_kpoint_pools():
    command = build_qe_command(
        timer=Path("/usr/bin/time"),
        micromamba="/opt/micromamba",
        prefix=Path("/opt/qe"),
        mpirun=Path("/opt/qe/bin/mpirun"),
        mpi_ranks=8,
        kpoint_pools=2,
    )
    assert command[-6:] == ["8", "pw.x", "-nk", "2", "-in", "pw.in"]
    with pytest.raises(ValueError, match="divide mpi_ranks"):
        build_qe_command(
            timer=Path("/usr/bin/time"),
            micromamba="/opt/micromamba",
            prefix=Path("/opt/qe"),
            mpirun=Path("/opt/qe/bin/mpirun"),
            mpi_ranks=8,
            kpoint_pools=3,
        )


def test_interrupted_attempt_is_archived_without_deletion(tmp_path, monkeypatch):
    executable = tmp_path / "pw.x"
    executable.write_text("binary")
    run_dir = _frozen_run(tmp_path, executable)
    (run_dir / "pw.out").write_text("partial output")
    scratch = run_dir / "scratch"
    scratch.mkdir()
    (scratch / "restart.dat").write_text("partial restart")
    state_path = tmp_path / "queue.json"
    state_path.write_text(
        json.dumps(
            {
                "queue_fingerprint": "a" * 64,
                "status": "running",
                "jobs": {"test-run": {"status": "running"}},
            }
        )
    )
    monkeypatch.setattr("matfactory.qe_queue.active_pw_pids", list)

    archive = archive_interrupted_run(
        run_dir,
        state_path=state_path,
        attempt_id="memory-gate-v1",
        reason="estimated memory exceeded the host capacity",
    )

    destination = run_dir / "attempts" / "memory-gate-v1"
    assert archive["run_id"] == "test-run"
    assert (destination / "pw.out").is_file()
    assert (destination / "scratch" / "restart.dat").is_file()
    assert not (run_dir / "pw.out").exists()
    assert json.loads(state_path.read_text())["status"] == "interrupted"
