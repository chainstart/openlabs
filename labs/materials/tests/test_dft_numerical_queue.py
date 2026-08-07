from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.dft_numerical_queue import (  # noqa: E402
    _queue_complete,
    _resource_evidence_hashes,
    build_runtime_mpi_protocol,
    selected_scf_protocol,
)
from matfactory.dft_decision import NUMERICAL_FIELDS  # noqa: E402
from matfactory.provenance import sha256_file  # noqa: E402


def test_frozen_numerical_supervisor_protocol_hashes_and_conditional_branches():
    path = ROOT / "analysis/protocols/llzto_dft_numerical_supervisor_v1.json"
    protocol = json.loads(path.read_text())
    declared = [
        (protocol["snapshot_manifest"]["path"], protocol["snapshot_manifest"]["sha256"]),
        (
            protocol["pseudopotential_manifest"]["path"],
            protocol["pseudopotential_manifest"]["sha256"],
        ),
        (protocol["kpoint"]["protocol"], protocol["kpoint"]["protocol_sha256"]),
        (
            protocol["scf"]["gamma_protocol"],
            protocol["scf"]["gamma_protocol_sha256"],
        ),
        (
            protocol["scf"]["k2x2x2_protocol"],
            protocol["scf"]["k2x2x2_protocol_sha256"],
        ),
    ]
    assert all(sha256_file(ROOT / item) == expected for item, expected in declared)
    assert protocol["mpi"]["required_ranks"] == [1, 2, 4, 8]
    assert protocol["kpoint"]["extension_label"] == "ecut90-k3x3x3-scf1e8"

    gamma = ROOT / protocol["scf"]["gamma_protocol"]
    k2 = ROOT / protocol["scf"]["k2x2x2_protocol"]
    assert selected_scf_protocol(
        "gamma", gamma_protocol=gamma, k2_protocol=k2
    ) == gamma
    assert selected_scf_protocol(
        [2, 2, 2], gamma_protocol=gamma, k2_protocol=k2
    ) == k2

    for branch_path in (gamma, k2):
        branch = json.loads(branch_path.read_text())
        baseline_path = ROOT / next(iter(branch["baseline_runs"].values()))
        baseline = json.loads((baseline_path / "run_manifest.json").read_text())[
            "settings"
        ]
        ladder = [baseline, *branch["calculations"]]
        for lower, upper in zip(ladder, ladder[1:]):
            changed = {
                field for field in NUMERICAL_FIELDS if lower[field] != upper[field]
            }
            assert changed == {"conv_thr_ry"}
            assert upper["conv_thr_ry"] < lower["conv_thr_ry"]


def test_runtime_mpi_protocol_mechanically_copies_selected_settings(tmp_path):
    decision = tmp_path / "scf-decision.json"
    decision.write_text("{}\n")
    configuration = {
        "outputs": {"scf_decision": str(decision)},
        "execution_environment": {"pw_executable_sha256": "a" * 64},
        "physics": {"exchange_correlation": "PBE"},
        "convergence_structures": ["relaxed", "thermal"],
        "mpi": {
            "required_ranks": [1, 2, 4, 8],
            "baseline_rank": 1,
            "acceptance": {
                "energy_abs_change_mev_atom_max": 0.001,
                "force_component_max_abs_change_ev_angstrom": 1e-5,
                "stress_component_max_abs_change_gpa": 1e-5,
            },
        },
    }
    selected = {
        "ecutwfc_ry": 90.0,
        "ecutrho_ry": 720.0,
        "kpoints": "gamma",
        "conv_thr_ry": 1e-8,
        "electron_maxstep": 250,
        "mixing_mode": "plain",
        "mixing_beta": 0.3,
        "diagonalization": "david",
        "ignored": "not copied",
    }
    protocol = build_runtime_mpi_protocol(selected, configuration)
    calculation = protocol["calculations"][0]
    assert calculation["kpoints"] == "gamma"
    assert calculation["conv_thr_ry"] == 1e-8
    assert "ignored" not in calculation
    assert protocol["required_mpi_ranks"] == [1, 2, 4, 8]


def test_medium_io_resource_amendment_freezes_probes_without_changing_physics():
    supervisor_path = (
        ROOT / "analysis/protocols/llzto_dft_numerical_supervisor_v2.json"
    )
    supervisor = json.loads(supervisor_path.read_text())
    kpoint_path = ROOT / supervisor["kpoint"]["protocol"]
    kpoint = json.loads(kpoint_path.read_text())
    assert sha256_file(kpoint_path) == supervisor["kpoint"]["protocol_sha256"]
    assert kpoint["amendment_kind"] == "resource-only execution amendment"
    calculation = kpoint["calculations"][0]
    assert calculation["kpoints"] == [3, 3, 3]
    assert calculation["disk_io"] == "medium"
    assert calculation["conv_thr_ry"] == 1e-8
    assert supervisor["resources"]["kpoint_extension_min_memory_gib"] == 36
    assert (
        supervisor["resources"]["kpoint_extension_max_estimated_total_ram_gb"]
        == 30
    )
    extension_root = ROOT / supervisor["kpoint"]["extension_root"]
    first_report = ROOT / supervisor["outputs"]["kpoint_gamma_2x2x2_report"]
    assert not first_report.is_relative_to(extension_root)
    evidence = _resource_evidence_hashes(kpoint)
    assert len(evidence) == 5
    assert all(sha256_file(path) == expected for path, expected in evidence.items())
    assessment = ROOT / supervisor["kpoint"]["extension_resource_assessment"]
    assert sha256_file(assessment) == supervisor["kpoint"][
        "extension_resource_assessment_sha256"
    ]
    watchdog = json.loads(
        (ROOT / "analysis/protocols/llzto_master_watchdog_v1.json").read_text()
    )
    managed = {row["process_id"]: row for row in watchdog["managed"]}
    formal_md = managed["formal-primary-md"]
    assert formal_md["progress_glob"] == (
        "runs/campaigns/llzto_q1_v1/formal-occ00-vel1701/T*.log"
    )
    numerical = managed["dft-numerical-supervisor"]
    assert numerical["expected_protocol_sha256"] == sha256_file(supervisor_path)
    assert numerical["state_stale_seconds"] == 86400
    assert numerical["progress_glob"] == "runs/dft/llzto-qe-*/**/pw.out"
    assert numerical["progress_stale_seconds"] == 3600
    assert "analysis/protocols/llzto_dft_numerical_supervisor_v2.json" in numerical[
        "args"
    ]


def test_nested_queue_completion_verifies_exact_run_grid(tmp_path):
    first = (tmp_path / "run-a").resolve()
    second = (tmp_path / "run-b").resolve()
    state_path = tmp_path / "queue.json"
    state_path.write_text(
        json.dumps(
            {
                "status": "complete",
                "config": {"run_dirs": [str(first), str(second)]},
                "jobs": {
                    "a": {"status": "complete"},
                    "b": {"status": "already_labelled"},
                },
            }
        )
    )
    assert _queue_complete(state_path, [first, second]) is True
    with pytest.raises(RuntimeError, match="run-directory mismatch"):
        _queue_complete(state_path, [first])
