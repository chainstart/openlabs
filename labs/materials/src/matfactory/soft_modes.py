"""Screen model phonons and materialize unstable-mode distortions with Phonopy."""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .discovery_relax import load_model_calculator
from .provenance import (
    atomic_write_json,
    environment_versions,
    fingerprint,
    sha256_file,
)

_ROOT = Path(__file__).resolve().parents[2]
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


@dataclass(frozen=True)
class SoftModeProtocol:
    soft_mode_id: str
    protocol_path: Path
    protocol_sha256: str
    root_dir: Path
    enabled: bool
    relaxation_manifest: Path
    approved_relaxation_manifest_fingerprint: str
    model_registry: Path
    approved_registry_content_fingerprint: str
    selected_job_fingerprints: tuple[str, ...]
    dynamical_model_id: str
    device: str
    model_dtype: str
    supercell_matrix: tuple[tuple[int, int, int], ...]
    mesh: tuple[int, int, int]
    displacement_distance_angstrom: float
    plus_minus_displacements: bool
    imaginary_threshold_thz: float
    max_modes_per_structure: int
    mode_amplitudes_angstrom: tuple[float, ...]
    max_selected_structures: int
    max_atoms_per_supercell: int
    max_force_calls: int
    gpu_hours: float
    wall_time_hours: float
    estimated_seconds_per_force_call: float


def _read_json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {source}")
    return payload


def _repo_path(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (_ROOT / path).resolve()


def _digest(value: Any, field: str, *, allow_empty: bool) -> str:
    if allow_empty and value == "":
        return ""
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _positive(mapping: dict[str, Any], field: str) -> float:
    value = mapping.get(field)
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or float(value) <= 0
    ):
        raise ValueError(f"{field} must be positive")
    return float(value)


def _integer(mapping: dict[str, Any], field: str, minimum: int, maximum: int) -> int:
    value = mapping.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{field} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{field} must be from {minimum} to {maximum}")
    return value


def _integer_vector(value: Any, field: str) -> tuple[int, int, int]:
    if (
        not isinstance(value, list)
        or len(value) != 3
        or any(not isinstance(item, int) or item <= 0 for item in value)
    ):
        raise ValueError(f"{field} must contain three positive integers")
    return tuple(value)


def _matrix_row(value: Any) -> tuple[int, int, int]:
    if (
        not isinstance(value, list)
        or len(value) != 3
        or any(not isinstance(item, int) or isinstance(item, bool) for item in value)
    ):
        raise ValueError("supercell_matrix rows must contain three integers")
    return tuple(value)


def load_soft_mode_protocol(path: Path | str) -> SoftModeProtocol:
    source = Path(path).resolve()
    payload = _read_json(source)
    if payload.get("schema_version") != "1.0":
        raise ValueError("soft-mode schema_version must be '1.0'")
    soft_mode_id = payload.get("soft_mode_id")
    if not isinstance(soft_mode_id, str) or not _SAFE_ID.fullmatch(soft_mode_id):
        raise ValueError("soft_mode_id must be a safe lowercase identifier")
    enabled = bool(payload.get("enabled", False))
    budget = payload.get("budget")
    phonons = payload.get("phonons")
    if not isinstance(budget, dict) or not isinstance(phonons, dict):
        raise TypeError("budget and phonons must be objects")
    selected = payload.get("selected_job_fingerprints", [])
    if not isinstance(selected, list):
        raise TypeError("selected_job_fingerprints must be a list")
    selected_digests = tuple(
        _digest(value, "selected_job_fingerprints", allow_empty=False)
        for value in selected
    )
    if len(set(selected_digests)) != len(selected_digests):
        raise ValueError("selected_job_fingerprints contains duplicates")
    if enabled and not selected_digests:
        raise ValueError("enabled soft-mode protocol needs selected jobs")
    matrix_raw = phonons.get("supercell_matrix")
    if not isinstance(matrix_raw, list) or len(matrix_raw) != 3:
        raise ValueError("supercell_matrix must be a 3x3 integer matrix")
    matrix = tuple(_matrix_row(row) for row in matrix_raw)
    matrix_array = np.asarray(matrix, dtype=int)
    if round(float(np.linalg.det(matrix_array))) <= 0:
        raise ValueError("supercell_matrix must have positive determinant")
    mesh = _integer_vector(phonons.get("mesh"), "mesh")
    threshold = phonons.get("imaginary_threshold_thz")
    if (
        not isinstance(threshold, (int, float))
        or isinstance(threshold, bool)
        or float(threshold) >= 0
    ):
        raise ValueError("imaginary_threshold_thz must be negative")
    amplitudes = phonons.get("mode_amplitudes_angstrom")
    if (
        not isinstance(amplitudes, list)
        or not amplitudes
        or any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or float(value) == 0
            for value in amplitudes
        )
    ):
        raise ValueError("mode_amplitudes_angstrom must be non-zero numbers")
    wall_hours = _positive(budget, "wall_time_hours")
    gpu_hours = _positive(budget, "gpu_hours")
    if wall_hours > 24 or gpu_hours > wall_hours:
        raise ValueError("soft-mode screen must fit one single-GPU day")
    dtype = payload.get("model_dtype", "float32")
    if dtype not in {"float32", "float64"}:
        raise ValueError("model_dtype must be float32 or float64")
    return SoftModeProtocol(
        soft_mode_id=soft_mode_id,
        protocol_path=source,
        protocol_sha256=sha256_file(source),
        root_dir=_repo_path(
            str(payload.get("root_dir", f"runs/soft-modes/{soft_mode_id}"))
        ),
        enabled=enabled,
        relaxation_manifest=_repo_path(str(payload.get("relaxation_manifest", ""))),
        approved_relaxation_manifest_fingerprint=_digest(
            payload.get("approved_relaxation_manifest_fingerprint", ""),
            "approved_relaxation_manifest_fingerprint",
            allow_empty=not enabled,
        ),
        model_registry=_repo_path(str(payload.get("model_registry", ""))),
        approved_registry_content_fingerprint=_digest(
            payload.get("approved_registry_content_fingerprint", ""),
            "approved_registry_content_fingerprint",
            allow_empty=not enabled,
        ),
        selected_job_fingerprints=selected_digests,
        dynamical_model_id=str(payload.get("dynamical_model_id", "")),
        device=str(payload.get("device", "cuda")),
        model_dtype=str(dtype),
        supercell_matrix=matrix,
        mesh=mesh,
        displacement_distance_angstrom=_positive(
            phonons, "displacement_distance_angstrom"
        ),
        plus_minus_displacements=bool(phonons.get("plus_minus_displacements", True)),
        imaginary_threshold_thz=float(threshold),
        max_modes_per_structure=_integer(phonons, "max_modes_per_structure", 1, 48),
        mode_amplitudes_angstrom=tuple(float(value) for value in amplitudes),
        max_selected_structures=_integer(budget, "max_selected_structures", 1, 20),
        max_atoms_per_supercell=_integer(budget, "max_atoms_per_supercell", 1, 2000),
        max_force_calls=_integer(budget, "max_force_calls", 1, 10_000),
        gpu_hours=gpu_hours,
        wall_time_hours=wall_hours,
        estimated_seconds_per_force_call=_positive(
            budget, "estimated_seconds_per_force_call"
        ),
    )


def _to_phonopy(atoms: Any) -> Any:
    from phonopy.structure.atoms import PhonopyAtoms

    return PhonopyAtoms(
        symbols=atoms.get_chemical_symbols(),
        cell=atoms.cell.array,
        scaled_positions=atoms.get_scaled_positions(wrap=False),
    )


def _to_ase(atoms: Any) -> Any:
    from ase import Atoms

    return Atoms(
        symbols=atoms.symbols,
        cell=atoms.cell,
        scaled_positions=atoms.scaled_positions,
        pbc=True,
    )


def prepare_phonopy(
    atoms: Any,
    *,
    supercell_matrix: tuple[tuple[int, int, int], ...],
    displacement_distance_angstrom: float,
    plus_minus_displacements: bool,
) -> Any:
    """Materialize deterministic finite displacements with identity primitive."""
    from phonopy import Phonopy

    phonon = Phonopy(
        _to_phonopy(atoms),
        np.asarray(supercell_matrix, dtype=int),
        primitive_matrix=np.eye(3),
    )
    phonon.generate_displacements(
        distance=displacement_distance_angstrom,
        is_plusminus=plus_minus_displacements,
    )
    return phonon


def select_soft_modes(
    qpoints: Any,
    frequencies: Any,
    weights: Any,
    *,
    threshold_thz: float,
    max_modes: int,
) -> list[dict[str, Any]]:
    """Select the most imaginary symmetry-reduced mesh modes."""
    rows = [
        {
            "frequency_thz": float(frequency),
            "qpoint": [float(value) for value in qpoints[q_index]],
            "band_index": band_index,
            "mesh_weight": int(weights[q_index]),
        }
        for q_index, row in enumerate(frequencies)
        for band_index, frequency in enumerate(row)
        if float(frequency) < threshold_thz
    ]
    rows.sort(key=lambda row: (row["frequency_thz"], row["qpoint"], row["band_index"]))
    return rows[:max_modes]


def finish_phonons(
    phonon: Any,
    forces: list[np.ndarray],
    *,
    mesh: tuple[int, int, int],
    threshold_thz: float,
    max_modes: int,
) -> dict[str, Any]:
    """Fit force constants and compute a symmetry-reduced phonon mesh."""
    phonon.forces = forces
    phonon.produce_force_constants(
        calculate_full_force_constants=True,
        fc_calculator="traditional",
        show_drift=False,
    )
    mesh_result = phonon.run_mesh(
        mesh,
        is_gamma_center=True,
        with_eigenvectors=True,
    )
    qpoints = np.asarray(mesh_result.qpoints)
    frequencies = np.asarray(mesh_result.frequencies)
    weights = np.asarray(mesh_result.weights)
    modes = select_soft_modes(
        qpoints,
        frequencies,
        weights,
        threshold_thz=threshold_thz,
        max_modes=max_modes,
    )
    return {
        "n_irreducible_qpoints": len(qpoints),
        "mesh": list(mesh),
        "minimum_frequency_thz": float(np.min(frequencies)),
        "maximum_frequency_thz": float(np.max(frequencies)),
        "n_modes_below_threshold": int(np.sum(frequencies < threshold_thz)),
        "selected_soft_modes": modes,
    }


def finite_displacement_phonons(
    atoms: Any,
    calculator: Any,
    *,
    supercell_matrix: tuple[tuple[int, int, int], ...],
    displacement_distance_angstrom: float,
    plus_minus_displacements: bool,
    mesh: tuple[int, int, int],
    threshold_thz: float,
    max_modes: int,
) -> tuple[Any, dict[str, Any]]:
    """In-memory reference path used by tests and small interactive checks."""
    phonon = prepare_phonopy(
        atoms,
        supercell_matrix=supercell_matrix,
        displacement_distance_angstrom=displacement_distance_angstrom,
        plus_minus_displacements=plus_minus_displacements,
    )
    forces: list[np.ndarray] = []
    maximum_drifts: list[float] = []
    for displaced in phonon.supercells_with_displacements:
        frame = _to_ase(displaced)
        frame.calc = calculator
        raw = np.asarray(frame.get_forces(), dtype=float)
        drift = np.mean(raw, axis=0)
        maximum_drifts.append(float(np.linalg.norm(drift)))
        forces.append(raw - drift)
    report = finish_phonons(
        phonon,
        forces,
        mesh=mesh,
        threshold_thz=threshold_thz,
        max_modes=max_modes,
    )
    report.update(
        {
            "n_displacements": len(forces),
            "maximum_force_drift_ev_a": max(maximum_drifts, default=0.0),
        }
    )
    return phonon, report


def _force_cache(
    path: Path,
    displaced: Any,
    calculator: Any,
    payload: dict[str, Any],
) -> np.ndarray:
    job_fingerprint = fingerprint(payload)
    if path.is_file():
        record = _read_json(path)
        if record.get("job_fingerprint") != job_fingerprint:
            raise RuntimeError(f"force cache inputs changed: {path}")
        forces = np.asarray(record.get("forces_ev_a"), dtype=float)
        if forces.shape != (len(displaced), 3):
            raise RuntimeError(f"force cache shape changed: {path}")
        return forces
    frame = _to_ase(displaced)
    frame.calc = calculator
    raw = np.asarray(frame.get_forces(), dtype=float)
    drift = np.mean(raw, axis=0)
    forces = raw - drift
    atomic_write_json(
        path,
        {
            "schema_version": "1.0",
            "job_fingerprint": job_fingerprint,
            "n_atoms": len(frame),
            "force_drift_ev_a": drift.tolist(),
            "forces_ev_a": forces.tolist(),
        },
    )
    return forces


def _atomic_save_array(path: Path, array: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".npy", dir=path.parent
    )
    os.close(descriptor)
    try:
        np.save(temporary, array, allow_pickle=False)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _inputs(protocol: SoftModeProtocol) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    relaxation = _read_json(protocol.relaxation_manifest)
    if (
        relaxation.get("manifest_fingerprint")
        != protocol.approved_relaxation_manifest_fingerprint
    ):
        raise RuntimeError("relaxation manifest lacks the approved fingerprint")
    jobs = {
        str(row.get("job_fingerprint")): row
        for row in relaxation.get("jobs", [])
        if isinstance(row, dict)
    }
    missing = sorted(set(protocol.selected_job_fingerprints) - jobs.keys())
    if missing:
        raise RuntimeError("selected relaxation jobs are missing")
    selected = [jobs[key] for key in protocol.selected_job_fingerprints]
    for row in selected:
        output = Path(str(row.get("output_path", "")))
        if (
            row.get("status") != "completed"
            or row.get("converged") is not True
            or not output.is_file()
            or sha256_file(output) != row.get("output_sha256")
        ):
            raise RuntimeError("selected relaxation job is not a verified convergence")
    registry = _read_json(protocol.model_registry)
    if (
        registry.get("content_fingerprint")
        != protocol.approved_registry_content_fingerprint
    ):
        raise RuntimeError("model registry lacks the approved content fingerprint")
    return selected, registry


def _model_record(registry: dict[str, Any], model_id: str) -> dict[str, Any]:
    records = [
        row
        for row in registry.get("models", [])
        if isinstance(row, dict) and row.get("model_id") == model_id
    ]
    if len(records) != 1:
        raise RuntimeError(f"model registry does not uniquely contain {model_id!r}")
    record = dict(records[0])
    artifact = Path(str(record.get("artifact_path", "")))
    if not artifact.is_file() or sha256_file(artifact) != record.get("artifact_sha256"):
        raise RuntimeError("dynamical model artifact changed or vanished")
    return record


def run_soft_mode_campaign(
    path: Path | str,
    *,
    calculator_factory: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """Compute finite-displacement phonons only for manually selected minima."""
    from ase.io import read, write

    protocol = load_soft_mode_protocol(path)
    if not protocol.enabled:
        raise RuntimeError("soft-mode protocol is disabled")
    selected, registry = _inputs(protocol)
    if len(selected) > protocol.max_selected_structures:
        raise RuntimeError("selected structure count exceeds soft-mode budget")
    model = _model_record(registry, protocol.dynamical_model_id)
    calculator = (
        calculator_factory(model)
        if calculator_factory is not None
        else load_model_calculator(
            model, device=protocol.device, dtype=protocol.model_dtype
        )
    )
    prepared: list[tuple[dict[str, Any], Any]] = []
    total_force_calls = 0
    for row in selected:
        atoms = read(row["output_path"])
        phonon = prepare_phonopy(
            atoms,
            supercell_matrix=protocol.supercell_matrix,
            displacement_distance_angstrom=protocol.displacement_distance_angstrom,
            plus_minus_displacements=protocol.plus_minus_displacements,
        )
        if len(phonon.supercell) > protocol.max_atoms_per_supercell:
            raise RuntimeError("phonon supercell exceeds atom-count budget")
        total_force_calls += len(phonon.supercells_with_displacements)
        prepared.append((row, phonon))
    if total_force_calls > protocol.max_force_calls:
        raise RuntimeError("finite-displacement force calls exceed frozen budget")
    estimated_gpu_hours = (
        total_force_calls * protocol.estimated_seconds_per_force_call / 3600.0
    )
    if estimated_gpu_hours > protocol.gpu_hours:
        raise RuntimeError("finite-displacement estimate exceeds frozen GPU budget")
    deadline = time.monotonic() + protocol.wall_time_hours * 3600.0
    results: list[dict[str, Any]] = []
    for parent, phonon in prepared:
        if time.monotonic() > deadline:
            raise TimeoutError("soft-mode campaign reached its wall-time deadline")
        parent_id = str(parent["ordering_id"])
        root = protocol.root_dir / parent_id
        forces: list[np.ndarray] = []
        for index, displaced in enumerate(phonon.supercells_with_displacements):
            forces.append(
                _force_cache(
                    root / "forces" / f"displacement-{index:04d}.json",
                    displaced,
                    calculator,
                    {
                        "protocol_sha256": protocol.protocol_sha256,
                        "parent_output_sha256": parent["output_sha256"],
                        "model_artifact_sha256": model["artifact_sha256"],
                        "displacement_index": index,
                        "displacement_dataset": phonon.dataset,
                    },
                )
            )
        report = finish_phonons(
            phonon,
            forces,
            mesh=protocol.mesh,
            threshold_thz=protocol.imaginary_threshold_thz,
            max_modes=protocol.max_modes_per_structure,
        )
        force_constants_path = root / "force_constants.npy"
        _atomic_save_array(force_constants_path, np.asarray(phonon.force_constants))
        distortions: list[dict[str, Any]] = []
        for mode_index, mode in enumerate(report["selected_soft_modes"]):
            for amplitude in protocol.mode_amplitudes_angstrom:
                modulation = phonon.run_modulations(
                    list(protocol.mesh),
                    [
                        [
                            mode["qpoint"],
                            mode["band_index"],
                            amplitude,
                            0.0,
                        ]
                    ],
                )
                distorted = _to_ase(modulation.modulated_supercells[0])
                output = (
                    root
                    / "distortions"
                    / (f"mode-{mode_index:03d}--amp-{amplitude:+.4f}.cif")
                )
                output.parent.mkdir(parents=True, exist_ok=True)
                write(output, distorted, format="cif")
                distortions.append(
                    {
                        "mode_index": mode_index,
                        "qpoint": mode["qpoint"],
                        "band_index": mode["band_index"],
                        "frequency_thz": mode["frequency_thz"],
                        "amplitude_angstrom": amplitude,
                        "path": str(output.resolve()),
                        "sha256": sha256_file(output),
                        "n_atoms": len(distorted),
                    }
                )
        report.update(
            {
                "candidate_id": parent["candidate_id"],
                "ordering_id": parent_id,
                "parent_job_fingerprint": parent["job_fingerprint"],
                "n_displacements": len(forces),
                "force_constants_path": str(force_constants_path.resolve()),
                "force_constants_sha256": sha256_file(force_constants_path),
                "distortions": distortions,
            }
        )
        atomic_write_json(root / "soft-mode-result.json", report)
        results.append(report)
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "manifest_kind": "mlip-finite-displacement-soft-mode-screen",
        "soft_mode_id": protocol.soft_mode_id,
        "created_unix_time": time.time(),
        "protocol_path": str(protocol.protocol_path),
        "protocol_sha256": protocol.protocol_sha256,
        "relaxation_manifest_fingerprint": (
            protocol.approved_relaxation_manifest_fingerprint
        ),
        "registry_content_fingerprint": registry["content_fingerprint"],
        "dynamical_model_id": protocol.dynamical_model_id,
        "total_force_calls": total_force_calls,
        "estimated_gpu_hours": estimated_gpu_hours,
        "environment": environment_versions(
            ("phonopy", "spglib", "ase", "numpy", "torch", "mace-torch")
        ),
        "results": results,
        "publication_assessment": {
            "q1_claim_ready": False,
            "reason": (
                "Model phonons and unstable-mode structures require dual-model "
                "relaxation plus independent DFT phonons/energetics."
            ),
        },
    }
    manifest["manifest_fingerprint"] = fingerprint(manifest)
    atomic_write_json(protocol.root_dir / "soft-mode-manifest.json", manifest)
    return manifest


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol")
    parser.add_argument("--list", action="store_true", dest="list_only")
    args = parser.parse_args()
    protocol = load_soft_mode_protocol(args.protocol)
    if args.list_only:
        output = {
            "soft_mode_id": protocol.soft_mode_id,
            "enabled": protocol.enabled,
            "selected_jobs": len(protocol.selected_job_fingerprints),
            "max_force_calls": protocol.max_force_calls,
            "gpu_hours": protocol.gpu_hours,
        }
    else:
        output = run_soft_mode_campaign(protocol.protocol_path)
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
