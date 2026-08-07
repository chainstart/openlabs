from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

ase = pytest.importorskip("ase")

from ase import Atoms  # noqa: E402
from ase.io import write  # noqa: E402
from ase.io.trajectory import Trajectory  # noqa: E402

from matfactory.dft import (  # noqa: E402
    BOHR_TO_ANGSTROM,
    RY_TO_EV,
    STRESS_CONVENTION,
    compare_predictions,
    collect_qe_result,
    load_pseudopotential_manifest,
    migrate_qe_stress_label,
    parse_pw_output,
    periodic_rmsd,
    render_qe_input,
    select_snapshots,
)


def _atoms(li_x: float = 0.5) -> Atoms:
    return Atoms(
        "LiO",
        positions=[[li_x, 0.5, 0.5], [2.5, 2.5, 2.5]],
        cell=[5.0, 5.0, 5.0],
        pbc=True,
    )


def test_periodic_rmsd_removes_framework_translation_but_keeps_li_motion():
    first = _atoms()
    translated = first.copy()
    translated.positions += [0.4, -0.2, 0.1]
    assert periodic_rmsd(first, translated) == pytest.approx(0.0, abs=1e-12)

    moved = first.copy()
    moved.positions[0, 0] += 0.3
    assert periodic_rmsd(first, moved) > 0.1


def test_snapshot_selection_is_deterministic_and_label_blind(tmp_path):
    static = tmp_path / "static.extxyz"
    write(static, _atoms(), format="extxyz")
    trajectory = tmp_path / "thermal.traj"
    writer = Trajectory(trajectory, "w")
    for index in range(9):
        writer.write(_atoms(0.5 + 0.06 * index))
    writer.close()
    protocol = tmp_path / "selection.json"
    protocol.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "selection_id": "test-selection",
                "expected_snapshot_count": 3,
                "static_snapshots": [
                    {"snapshot_id": "relaxed", "structure": static.name}
                ],
                "trajectory_matrices": [
                    {
                        "id_prefix_template": "thermal",
                        "trajectory_template": trajectory.name,
                        "occupancy_seeds": [7],
                        "temperatures_k": [800],
                        "frame_spacing_ps": 0.1,
                        "count": 2,
                        "start_fraction": 0.0,
                        "stop_fraction": 1.0,
                        "min_frame_separation": 2,
                        "min_rmsd_angstrom": 0.01,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    first = select_snapshots(
        protocol, out_dir=tmp_path / "out-1", project_root=tmp_path
    )
    second = select_snapshots(
        protocol, out_dir=tmp_path / "out-2", project_root=tmp_path
    )
    assert first["selection_is_label_blind"] is True
    assert first["n_snapshots"] == 3
    assert [row["source_frame_index"] for row in first["snapshots"]] == [
        row["source_frame_index"] for row in second["snapshots"]
    ]
    assert all(Path(row["snapshot_path"]).is_file() for row in first["snapshots"])
    assert first["snapshots"][1]["metadata"]["occupancy_seed"] == 7
    with pytest.raises(RuntimeError, match="refusing to overwrite non-empty"):
        select_snapshots(
            protocol, out_dir=tmp_path / "out-1", project_root=tmp_path
        )


def test_pseudopotential_manifest_verifies_both_hashes(tmp_path):
    upf = tmp_path / "Li.UPF"
    upf.write_bytes(b"pinned pseudo\n")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "elements": {
                    "Li": {
                        "filename": upf.name,
                        "md5": hashlib.md5(
                            upf.read_bytes(), usedforsecurity=False
                        ).hexdigest(),
                        "sha256": hashlib.sha256(upf.read_bytes()).hexdigest(),
                        "cutoff_wfc_ry": 40,
                        "cutoff_rho_ry": 320,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    loaded = load_pseudopotential_manifest(
        manifest, pseudo_dir=tmp_path, verify_files=True
    )
    assert loaded["elements"]["Li"]["filename"] == "Li.UPF"
    upf.write_bytes(b"changed\n")
    with pytest.raises(RuntimeError, match="MD5 mismatch"):
        load_pseudopotential_manifest(manifest, pseudo_dir=tmp_path, verify_files=True)


def test_qe_input_freezes_pbe_forces_stress_cutoffs_and_gamma():
    text = render_qe_input(
        _atoms(),
        pseudopotentials={
            "Li": {"filename": "Li.UPF"},
            "O": {"filename": "O.UPF"},
        },
        settings={
            "ecutwfc_ry": 75.0,
            "ecutrho_ry": 600.0,
            "conv_thr_ry": 1e-8,
            "kpoints": "gamma",
        },
        prefix="test-gamma",
    )
    assert "calculation = 'scf'" in text
    assert "input_dft = 'PBE'" in text
    assert "ecutwfc = 75" in text
    assert "ecutrho = 600" in text
    assert "tprnfor = .true." in text
    assert "tstress = .true." in text
    assert "disk_io = 'low'" in text
    assert "nosym = .true." in text
    assert "K_POINTS gamma" in text
    assert "ATOMIC_POSITIONS angstrom" in text


def test_qe_input_allows_frozen_medium_disk_io_for_memory_safe_kpoint_extension():
    settings = {
        "ecutwfc_ry": 90.0,
        "ecutrho_ry": 720.0,
        "conv_thr_ry": 1e-8,
        "kpoints": [3, 3, 3],
        "disk_io": "medium",
    }
    text = render_qe_input(
        _atoms(),
        pseudopotentials={
            "Li": {"filename": "Li.UPF"},
            "O": {"filename": "O.UPF"},
        },
        settings=settings,
        prefix="test-k3-medium-io",
    )
    assert "disk_io = 'medium'" in text
    assert "K_POINTS automatic\n  3 3 3 0 0 0" in text
    with pytest.raises(ValueError, match="unsupported Quantum ESPRESSO disk_io"):
        render_qe_input(
            _atoms(),
            pseudopotentials={
                "Li": {"filename": "Li.UPF"},
                "O": {"filename": "O.UPF"},
            },
            settings={**settings, "disk_io": "unsafe"},
            prefix="test-invalid-disk-io",
        )


def test_qe_output_parser_converts_energy_forces_stress_and_requires_completion():
    output = """
     convergence has been achieved in 9 iterations
!    total energy              =   -10.00000000 Ry
     Forces acting on atoms (cartesian axes, Ry/au):
     atom    1 type  1   force =     0.01000000   -0.02000000    0.03000000
     atom    2 type  2   force =    -0.01000000    0.02000000   -0.03000000
     The non-local contrib. to forces
     atom    1 type  1   force =     9.00000000    9.00000000    9.00000000
     atom    2 type  2   force =     9.00000000    9.00000000    9.00000000
     The SCF correction term to forces
     atom    1 type  1   force =     0.00000100    0.00000100    0.00000100
     atom    2 type  2   force =     0.00000100    0.00000100    0.00000100
     total   stress  (Ry/bohr**3)                   (kbar)     P=       50.00
       0.0  0.0  0.0   10.0  20.0  30.0
       0.0  0.0  0.0   40.0  50.0  60.0
       0.0  0.0  0.0   70.0  80.0  90.0
     JOB DONE.
    """
    result = parse_pw_output(output, expected_n_atoms=2)
    assert result.total_energy_ev == pytest.approx(-10 * RY_TO_EV)
    assert result.forces_ev_angstrom[0][0] == pytest.approx(
        0.01 * RY_TO_EV / BOHR_TO_ANGSTROM
    )
    assert result.stress_gpa[1] == pytest.approx((-4.0, -5.0, -6.0))
    assert result.qe_printed_stress_gpa[1] == pytest.approx((4.0, 5.0, 6.0))
    assert result.as_dict()["stress_convention"] == STRESS_CONVENTION
    assert result.pressure_gpa == pytest.approx(5.0)
    assert result.scf_iterations == 9
    with pytest.raises(ValueError, match="incomplete"):
        parse_pw_output(output.replace("JOB DONE.", ""), expected_n_atoms=2)


def test_model_domain_comparison_uses_centered_energies_and_all_components():
    records = []
    for index, dft_energy in enumerate((-20.0, -19.0, -18.2)):
        dft_force = np.array([[0.1, 0.2, 0.3], [-0.1, -0.2, -0.3]])
        model_force = dft_force + 0.01 * (index + 1)
        records.append(
            {
                "n_atoms": 2,
                "symbols": ["Li", "O"],
                "dft": {
                    "total_energy_ev": dft_energy,
                    "forces_ev_angstrom": dft_force.tolist(),
                    "stress_gpa": np.eye(3).tolist(),
                },
                "model": {
                    "total_energy_ev": dft_energy + 0.01 * index,
                    "forces_ev_angstrom": model_force.tolist(),
                    "stress_gpa": (np.eye(3) + 0.02).tolist(),
                },
            }
        )
    report = compare_predictions(records)
    assert report["numerical_gate_pass"] is True
    assert report["metrics"]["centered_energy_mae_ev_atom"] < 0.015
    assert set(report["metrics"]["element_resolved_forces"]) == {"Li", "O"}


def test_legacy_stress_label_migration_archives_and_hashes_old_label(tmp_path):
    run_dir = tmp_path / "qe-run"
    run_dir.mkdir()
    input_path = run_dir / "pw.in"
    input_path.write_text("frozen\n")
    output_path = run_dir / "pw.out"
    output_path.write_text(
        """
! total energy = -1.0 Ry
Forces acting on atoms (cartesian axes, Ry/au):
atom 1 type 1 force = 0.0 0.0 0.0
total stress (Ry/bohr**3) (kbar) P= 2.0
0 0 0 1 0 0
0 0 0 0 2 0
0 0 0 0 0 3
JOB DONE.
"""
    )
    manifest = {
        "run_id": "test",
        "run_fingerprint": "fingerprint",
        "input_path": str(input_path),
        "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        "n_atoms": 1,
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest))
    modern = collect_qe_result(run_dir)
    legacy = dict(modern)
    legacy["schema_version"] = "1.0"
    legacy["result"] = dict(modern["result"])
    legacy["result"]["stress_gpa"] = legacy["result"].pop(
        "qe_printed_stress_gpa"
    )
    legacy["result"].pop("qe_printed_stress_convention")
    legacy["result"].pop("stress_convention")
    (run_dir / "dft_label.json").write_text(json.dumps(legacy))

    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        collect_qe_result(run_dir)
    migrated = migrate_qe_stress_label(run_dir)
    assert migrated["label"]["schema_version"] == "1.1"
    assert migrated["label"]["result"]["stress_gpa"][0][0] == pytest.approx(-0.1)
    archive = run_dir / "dft_label.schema1.0-qe-printed-stress.json"
    assert json.loads(archive.read_text()) == legacy
    assert migrated["migration"]["legacy_label_sha256"] == hashlib.sha256(
        archive.read_bytes()
    ).hexdigest()
    assert collect_qe_result(run_dir) == migrated["label"]
