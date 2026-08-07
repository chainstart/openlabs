from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.dft_domain_queue import (  # noqa: E402
    _passing_numerical_reports,
    _queue_complete,
    build_runtime_domain_dft_protocol,
)
from matfactory.provenance import sha256_file  # noqa: E402


def test_frozen_domain_supervisor_protocol_hashes_both_snapshot_sets():
    protocol = json.loads(
        (ROOT / "analysis/protocols/llzto_dft_domain_supervisor_v1.json").read_text()
    )
    declared = [
        (protocol["analysis_protocol"]["path"], protocol["analysis_protocol"]["sha256"]),
        (
            protocol["pseudopotential_manifest"]["path"],
            protocol["pseudopotential_manifest"]["sha256"],
        ),
        (
            protocol["feasibility"]["snapshot_manifest"],
            protocol["feasibility"]["snapshot_manifest_sha256"],
        ),
        (
            protocol["heldout"]["selection_protocol"],
            protocol["heldout"]["selection_protocol_sha256"],
        ),
    ]
    assert all(sha256_file(ROOT / path) == expected for path, expected in declared)
    assert protocol["resources"]["prediction_device"] == "cpu"
    assert protocol["sampling_release_gate"] != protocol["g2_release_gate"]


def test_runtime_domain_protocol_copies_passed_scf_settings_and_mpi_hash():
    selected = {
        "ecutwfc_ry": 90.0,
        "ecutrho_ry": 720.0,
        "kpoints": "gamma",
        "conv_thr_ry": 1e-8,
        "electron_maxstep": 250,
        "mixing_mode": "plain",
        "mixing_beta": 0.3,
        "diagonalization": "david",
        "not_a_numerical_field": 123,
    }
    configuration = {
        "execution_environment": {"pw_executable_sha256": "a" * 64},
        "physics": {"exchange_correlation": "PBE"},
    }
    state = {
        "config": {"protocol_path": "/protocol", "protocol_sha256": "b" * 64},
        "stages": {
            "scf_decision": {"path": "/scf.json", "sha256": "c" * 64},
            "mpi_reproducibility": {"path": "/mpi.json", "sha256": "d" * 64},
        },
    }
    protocol = build_runtime_domain_dft_protocol(selected, configuration, state)
    calculation = protocol["calculations"][0]
    assert calculation["kpoints"] == "gamma"
    assert calculation["conv_thr_ry"] == 1e-8
    assert "not_a_numerical_field" not in calculation
    assert protocol["mpi_report_sha256"] == "d" * 64


def test_passing_numerical_reports_selects_only_passed_adjacent_pairs(tmp_path):
    cutoff = tmp_path / "cutoff.json"
    kpoint_fail = tmp_path / "kpoint-fail.json"
    kpoint_pass = tmp_path / "kpoint-pass.json"
    scf_pass = tmp_path / "scf-pass.json"
    for path, passed in (
        (cutoff, True),
        (kpoint_fail, False),
        (kpoint_pass, True),
        (scf_pass, True),
    ):
        path.write_text(json.dumps({"numerically_converged": passed}))
    state = {
        "stages": {
            "kpoint_gamma_2x2x2": {
                "status": "fail",
                "path": str(kpoint_fail),
                "sha256": sha256_file(kpoint_fail),
            },
            "kpoint_2x2x2_3x3x3": {
                "status": "pass",
                "path": str(kpoint_pass),
                "sha256": sha256_file(kpoint_pass),
            },
            "scf_comparison_0": {
                "status": "pass",
                "path": str(scf_pass),
                "sha256": sha256_file(scf_pass),
            },
        }
    }
    reports = _passing_numerical_reports(
        state, {"numerical_reports": {"cutoff": str(cutoff)}}
    )
    assert reports == {
        "cutoff": cutoff.resolve(),
        "kpoint": kpoint_pass.resolve(),
        "scf": scf_pass.resolve(),
    }


def test_domain_qe_queue_requires_exact_completed_grid(tmp_path):
    runs = [(tmp_path / name).resolve() for name in ("one", "two")]
    state = tmp_path / "queue.json"
    state.write_text(
        json.dumps(
            {
                "status": "complete",
                "config": {"run_dirs": [str(path) for path in runs]},
                "jobs": {
                    "one": {"status": "complete"},
                    "two": {"status": "complete"},
                },
            }
        )
    )
    assert _queue_complete(state, runs) is True
    with pytest.raises(RuntimeError, match="run-directory mismatch"):
        _queue_complete(state, runs[:1])
