from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.dft_mpi import analyze_mpi_results  # noqa: E402


def _records(*, force_shift: float = 0.0) -> list[dict]:
    rows = []
    settings = {
        "ecutwfc_ry": 90.0,
        "ecutrho_ry": 720.0,
        "kpoints": [2, 2, 2],
        "conv_thr_ry": 1e-8,
    }
    for rank in (1, 2, 4, 8):
        for structure_index, structure_id in enumerate(("relaxed", "thermal")):
            shift = 0.0 if rank == 1 else rank * 1e-9
            forces = np.full((3, 3), structure_index * 0.1 + shift)
            if rank == 8 and structure_id == "thermal":
                forces[0, 0] += force_shift
            rows.append(
                {
                    "mpi_ranks": rank,
                    "structure_id": structure_id,
                    "structure_fingerprint": f"structure-{structure_id}",
                    "n_atoms": 3,
                    "settings": settings,
                    "total_energy_ev": -100.0 - structure_index + shift,
                    "forces_ev_angstrom": forces,
                    "stress_gpa": np.eye(3) * (1.0 + shift),
                }
            )
    return rows


def _analyze(records):
    return analyze_mpi_results(
        records,
        required_ranks=[1, 2, 4, 8],
        baseline_rank=1,
        structure_ids=["relaxed", "thermal"],
        energy_abs_change_mev_atom_max=0.001,
        force_component_max_abs_change_ev_angstrom=1e-5,
        stress_component_max_abs_change_gpa=1e-5,
    )


def test_mpi_equivalence_requires_complete_rank_by_structure_grid():
    report = _analyze(_records())
    assert report["n_cells"] == 8
    assert report["n_comparisons"] == 6
    assert report["mpi_equivalence_gate_pass"] is True
    assert all(report["checks"].values())

    incomplete = _records()
    incomplete.pop()
    with pytest.raises(ValueError, match="complete rank grid"):
        _analyze(incomplete)


def test_mpi_force_difference_fails_without_changing_other_checks():
    report = _analyze(_records(force_shift=2e-4))
    assert report["checks"]["force_component_max_abs_change_ev_angstrom"] is False
    assert report["checks"]["energy_abs_change_mev_atom_max"] is True
    assert report["checks"]["stress_component_max_abs_change_gpa"] is True
    assert report["mpi_equivalence_gate_pass"] is False


def test_mpi_comparison_rejects_changed_physics_settings():
    records = _records()
    changed = dict(records[-1]["settings"])
    changed["conv_thr_ry"] = 1e-10
    records[-1]["settings"] = changed
    with pytest.raises(ValueError, match="different QE settings"):
        _analyze(records)
