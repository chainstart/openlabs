from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.dft import STRESS_CONVENTION  # noqa: E402
from matfactory.dft_convergence import (  # noqa: E402
    compare_qe_settings,
    write_convergence_report,
)
from matfactory.provenance import fingerprint, sha256_file  # noqa: E402


def _run(
    root: Path,
    name: str,
    structure: str,
    energy: float,
    force: float,
    stress: float,
) -> Path:
    directory = root / name
    directory.mkdir()
    input_path = directory / "pw.in"
    output_path = directory / "pw.out"
    input_path.write_text("input\n")
    output_path.write_text("output\n")
    manifest = {
        "run_id": name,
        "run_fingerprint": fingerprint({"name": name}),
        "input_path": str(input_path),
        "input_sha256": sha256_file(input_path),
        "structure_fingerprint": structure,
        "n_atoms": 2,
        "settings": {"label": name},
    }
    (directory / "run_manifest.json").write_text(json.dumps(manifest))
    label = {
        "run_id": name,
        "run_fingerprint": manifest["run_fingerprint"],
        "input_sha256": manifest["input_sha256"],
        "output_path": str(output_path),
        "output_sha256": sha256_file(output_path),
        "result": {
            "total_energy_ev": energy,
            "forces_ev_angstrom": [[force, 0.0, 0.0], [0.0, -force, 0.0]],
            "stress_gpa": [
                [stress, 0.0, 0.0],
                [0.0, stress, 0.0],
                [0.0, 0.0, stress],
            ],
            "stress_convention": STRESS_CONVENTION,
            "qe_printed_stress_gpa": [
                [-stress, 0.0, 0.0],
                [0.0, -stress, 0.0],
                [0.0, 0.0, -stress],
            ],
        },
    }
    (directory / "dft_label.json").write_text(json.dumps(label))
    return directory


def test_convergence_uses_relative_energy_and_all_force_stress_components(tmp_path):
    a_low = _run(tmp_path, "a-low", "a", -20.0, 0.10, 1.00)
    a_high = _run(tmp_path, "a-high", "a", -20.2, 0.105, 1.05)
    b_low = _run(tmp_path, "b-low", "b", -18.0, 0.20, 2.00)
    b_high = _run(tmp_path, "b-high", "b", -18.199, 0.205, 2.05)

    report = compare_qe_settings(
        [(a_low, a_high), (b_low, b_high)],
        relative_energy_mev_atom_max=1.0,
        force_component_max_abs_change_ev_angstrom=0.01,
        stress_component_max_abs_change_gpa=0.1,
    )
    assert report["numerically_converged"] is True
    assert report["metrics"]["max_pairwise_relative_energy_change_mev_atom"] == (
        pytest.approx(0.5)
    )
    assert report["metrics"]["force_component_max_abs_change_ev_angstrom"] == (
        pytest.approx(0.005)
    )


def test_convergence_rejects_structure_mismatch_and_tampered_output(tmp_path):
    lower = _run(tmp_path, "lower", "a", -20.0, 0.1, 1.0)
    upper = _run(tmp_path, "upper", "b", -20.0, 0.1, 1.0)
    with pytest.raises(ValueError, match="structures differ"):
        compare_qe_settings(
            [(lower, upper), (lower, upper)],
            relative_energy_mev_atom_max=1.0,
            force_component_max_abs_change_ev_angstrom=0.01,
            stress_component_max_abs_change_gpa=0.1,
        )

    (upper / "pw.out").write_text("changed\n")
    with pytest.raises(RuntimeError, match="output_sha256"):
        compare_qe_settings(
            [(lower, upper), (lower, upper)],
            relative_energy_mev_atom_max=1.0,
            force_component_max_abs_change_ev_angstrom=0.01,
            stress_component_max_abs_change_gpa=0.1,
        )


def test_convergence_report_is_immutable_but_exact_replay_is_idempotent(tmp_path):
    path = tmp_path / "convergence.json"
    report = {"schema_version": "1.0", "numerically_converged": True}
    write_convergence_report(path, report)
    write_convergence_report(path, report)
    assert json.loads(path.read_text()) == report
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        write_convergence_report(
            path,
            {"schema_version": "1.0", "numerically_converged": False},
        )
