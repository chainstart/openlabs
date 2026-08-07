"""Auditable numerical-convergence comparisons for frozen QE calculations."""

from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np

from .dft import STRESS_CONVENTION
from .provenance import atomic_write_json, sha256_file


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {path}")
    return payload


def load_completed_qe_run(run_dir: Path | str) -> dict[str, Any]:
    """Load one QE label after verifying its frozen input and output hashes."""
    directory = Path(run_dir).resolve()
    manifest_path = directory / "run_manifest.json"
    label_path = directory / "dft_label.json"
    manifest = _read_json(manifest_path)
    label = _read_json(label_path)

    input_path = Path(manifest["input_path"])
    output_path = Path(label["output_path"])
    checks = {
        "run_id": label.get("run_id") == manifest.get("run_id"),
        "run_fingerprint": label.get("run_fingerprint")
        == manifest.get("run_fingerprint"),
        "input_sha256": sha256_file(input_path)
        == manifest.get("input_sha256")
        == label.get("input_sha256"),
        "output_sha256": sha256_file(output_path) == label.get("output_sha256"),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(
            f"QE run provenance failed for {directory}: {', '.join(failed)}"
        )

    result = label.get("result")
    if not isinstance(result, dict):
        raise ValueError(f"QE label has no result object: {label_path}")
    forces = np.asarray(result.get("forces_ev_angstrom"), dtype=float)
    stress = np.asarray(result.get("stress_gpa"), dtype=float)
    raw_stress = np.asarray(result.get("qe_printed_stress_gpa"), dtype=float)
    n_atoms = int(manifest["n_atoms"])
    if forces.shape != (n_atoms, 3):
        raise ValueError(f"QE force array is not {n_atoms} x 3: {label_path}")
    if stress.shape != (3, 3):
        raise ValueError(f"QE stress array is not 3 x 3: {label_path}")
    if result.get("stress_convention") != STRESS_CONVENTION:
        raise ValueError(
            f"QE label does not use the standardized stress convention: {label_path}"
        )
    if raw_stress.shape != (3, 3) or not np.allclose(
        stress, -raw_stress, atol=1e-12
    ):
        raise ValueError(f"QE raw/standardized stress tensors disagree: {label_path}")
    return {
        "run_dir": str(directory),
        "run_id": manifest["run_id"],
        "run_manifest_path": str(manifest_path),
        "run_manifest_sha256": sha256_file(manifest_path),
        "label_path": str(label_path),
        "label_sha256": sha256_file(label_path),
        "structure_fingerprint": manifest["structure_fingerprint"],
        "n_atoms": n_atoms,
        "settings": manifest["settings"],
        "total_energy_ev": float(result["total_energy_ev"]),
        "forces_ev_angstrom": forces,
        "stress_gpa": stress,
    }


def compare_qe_settings(
    run_pairs: list[tuple[Path | str, Path | str]],
    *,
    relative_energy_mev_atom_max: float,
    force_component_max_abs_change_ev_angstrom: float,
    stress_component_max_abs_change_gpa: float,
) -> dict[str, Any]:
    """Compare lower/upper numerical settings on matched frozen structures.

    Relative-energy convergence is the largest pairwise difference in the
    per-atom upper-minus-lower energy shift. This removes the common total-energy
    offset introduced by changing the plane-wave basis.
    """
    if len(run_pairs) < 2:
        raise ValueError("relative-energy convergence requires at least two structures")
    records: list[dict[str, Any]] = []
    energy_shifts: list[float] = []
    force_changes: list[np.ndarray] = []
    stress_changes: list[np.ndarray] = []
    atom_counts: set[int] = set()

    for lower_dir, upper_dir in run_pairs:
        lower = load_completed_qe_run(lower_dir)
        upper = load_completed_qe_run(upper_dir)
        if lower["structure_fingerprint"] != upper["structure_fingerprint"]:
            raise ValueError(
                f"numerical comparison structures differ: {lower['run_id']} and "
                f"{upper['run_id']}"
            )
        if lower["n_atoms"] != upper["n_atoms"]:
            raise ValueError("matched numerical-comparison runs have different sizes")
        n_atoms = lower["n_atoms"]
        atom_counts.add(n_atoms)
        energy_shift = (
            (upper["total_energy_ev"] - lower["total_energy_ev"]) * 1000.0 / n_atoms
        )
        force_delta = upper["forces_ev_angstrom"] - lower["forces_ev_angstrom"]
        stress_delta = upper["stress_gpa"] - lower["stress_gpa"]
        energy_shifts.append(float(energy_shift))
        force_changes.append(force_delta)
        stress_changes.append(stress_delta)
        records.append(
            {
                "structure_fingerprint": lower["structure_fingerprint"],
                "n_atoms": n_atoms,
                "lower": {
                    key: lower[key]
                    for key in (
                        "run_dir",
                        "run_id",
                        "run_manifest_sha256",
                        "label_sha256",
                        "settings",
                    )
                },
                "upper": {
                    key: upper[key]
                    for key in (
                        "run_dir",
                        "run_id",
                        "run_manifest_sha256",
                        "label_sha256",
                        "settings",
                    )
                },
                "upper_minus_lower_energy_shift_mev_atom": float(energy_shift),
                "force_component_max_abs_change_ev_angstrom": float(
                    np.max(np.abs(force_delta))
                ),
                "stress_component_max_abs_change_gpa": float(
                    np.max(np.abs(stress_delta))
                ),
            }
        )

    if len(atom_counts) != 1:
        raise ValueError("relative-energy test structures must have equal atom counts")
    pairwise_energy_changes = [
        abs(energy_shifts[first] - energy_shifts[second])
        for first, second in combinations(range(len(energy_shifts)), 2)
    ]
    force = np.concatenate([values.reshape(-1) for values in force_changes])
    stress = np.concatenate([values.reshape(-1) for values in stress_changes])
    metrics = {
        "n_structures": len(records),
        "max_pairwise_relative_energy_change_mev_atom": float(
            max(pairwise_energy_changes)
        ),
        "force_component_max_abs_change_ev_angstrom": float(np.max(np.abs(force))),
        "force_component_rmse_change_ev_angstrom": float(
            np.sqrt(np.mean(np.square(force)))
        ),
        "stress_component_max_abs_change_gpa": float(np.max(np.abs(stress))),
        "stress_component_rmse_change_gpa": float(np.sqrt(np.mean(np.square(stress)))),
    }
    limits = {
        "max_pairwise_relative_energy_change_mev_atom": float(
            relative_energy_mev_atom_max
        ),
        "force_component_max_abs_change_ev_angstrom": float(
            force_component_max_abs_change_ev_angstrom
        ),
        "stress_component_max_abs_change_gpa": float(
            stress_component_max_abs_change_gpa
        ),
    }
    checks = {name: metrics[name] <= limit for name, limit in limits.items()}
    return {
        "schema_version": "1.0",
        "comparison_kind": "qe-numerical-convergence",
        "records": records,
        "metrics": metrics,
        "limits": limits,
        "checks": checks,
        "numerically_converged": all(checks.values()),
    }


def write_convergence_report(path: Path | str, report: dict[str, Any]) -> None:
    """Write one immutable convergence report, allowing only exact replay."""
    destination = Path(path).resolve()
    if destination.exists():
        existing = _read_json(destination)
        if existing == report:
            return
        raise RuntimeError(
            f"refusing to overwrite an existing convergence report: {destination}"
        )
    atomic_write_json(destination, report)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pair",
        nargs=2,
        action="append",
        metavar=("LOWER_RUN", "UPPER_RUN"),
        required=True,
    )
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    protocol_path = Path(args.protocol).resolve()
    protocol = _read_json(protocol_path)
    acceptance = protocol["acceptance"]
    report = compare_qe_settings(
        [(lower, upper) for lower, upper in args.pair],
        relative_energy_mev_atom_max=acceptance["relative_energy_mev_atom_max"],
        force_component_max_abs_change_ev_angstrom=acceptance[
            "force_component_max_abs_change_ev_angstrom"
        ],
        stress_component_max_abs_change_gpa=acceptance[
            "stress_component_max_abs_change_gpa"
        ],
    )
    report["protocol_path"] = str(protocol_path)
    report["protocol_sha256"] = sha256_file(protocol_path)
    report["implementation_path"] = str(Path(__file__).resolve())
    report["implementation_sha256"] = sha256_file(Path(__file__))
    output = Path(args.out).resolve()
    write_convergence_report(output, report)
    print(json.dumps(report, indent=2, default=lambda value: value.tolist()))


if __name__ == "__main__":
    main()
