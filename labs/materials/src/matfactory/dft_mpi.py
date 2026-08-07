"""Verify that frozen Quantum ESPRESSO labels are invariant to MPI rank count."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from .dft_convergence import load_completed_qe_run
from .provenance import atomic_write_json, fingerprint, sha256_file


def _read_json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {source}")
    return payload


def analyze_mpi_results(
    records: list[dict[str, Any]],
    *,
    required_ranks: list[int],
    baseline_rank: int,
    structure_ids: list[str],
    energy_abs_change_mev_atom_max: float,
    force_component_max_abs_change_ev_angstrom: float,
    stress_component_max_abs_change_gpa: float,
) -> dict[str, Any]:
    """Compare every rank to the declared one-rank (or other) baseline."""
    ranks = sorted({int(record["mpi_ranks"]) for record in records})
    structures = sorted({str(record["structure_id"]) for record in records})
    required = sorted(int(value) for value in required_ranks)
    expected_structures = sorted(str(value) for value in structure_ids)
    if ranks != required:
        raise ValueError(f"MPI rank grid is {ranks}, expected {required}")
    if structures != expected_structures:
        raise ValueError(
            f"MPI structure grid is {structures}, expected {expected_structures}"
        )
    if baseline_rank not in required:
        raise ValueError("MPI baseline rank is not in the required grid")
    by_cell: dict[tuple[int, str], dict[str, Any]] = {}
    for record in records:
        key = (int(record["mpi_ranks"]), str(record["structure_id"]))
        if key in by_cell:
            raise ValueError(f"duplicate MPI reproducibility cell {key}")
        by_cell[key] = record
    expected_cells = {
        (rank, structure) for rank in required for structure in expected_structures
    }
    if set(by_cell) != expected_cells:
        raise ValueError("MPI reproducibility design is not a complete rank grid")

    comparisons = []
    energy_changes = []
    force_changes = []
    stress_changes = []
    for structure_id in expected_structures:
        baseline = by_cell[(baseline_rank, structure_id)]
        baseline_forces = np.asarray(baseline["forces_ev_angstrom"], dtype=float)
        baseline_stress = np.asarray(baseline["stress_gpa"], dtype=float)
        n_atoms = int(baseline["n_atoms"])
        if baseline_forces.shape != (n_atoms, 3) or baseline_stress.shape != (3, 3):
            raise ValueError(f"invalid baseline arrays for {structure_id}")
        for rank in required:
            if rank == baseline_rank:
                continue
            comparison = by_cell[(rank, structure_id)]
            if comparison["structure_fingerprint"] != baseline["structure_fingerprint"]:
                raise ValueError(f"MPI ranks use different structures for {structure_id}")
            if comparison["settings"] != baseline["settings"]:
                raise ValueError(f"MPI ranks use different QE settings for {structure_id}")
            if int(comparison["n_atoms"]) != n_atoms:
                raise ValueError(f"MPI ranks use different atom counts for {structure_id}")
            forces = np.asarray(comparison["forces_ev_angstrom"], dtype=float)
            stress = np.asarray(comparison["stress_gpa"], dtype=float)
            if forces.shape != baseline_forces.shape or stress.shape != baseline_stress.shape:
                raise ValueError(f"MPI result arrays differ in shape for {structure_id}")
            energy = (
                abs(
                    float(comparison["total_energy_ev"])
                    - float(baseline["total_energy_ev"])
                )
                * 1000.0
                / n_atoms
            )
            force_delta = forces - baseline_forces
            stress_delta = stress - baseline_stress
            energy_changes.append(energy)
            force_changes.append(force_delta.reshape(-1))
            stress_changes.append(stress_delta.reshape(-1))
            comparisons.append(
                {
                    "structure_id": structure_id,
                    "baseline_mpi_ranks": baseline_rank,
                    "comparison_mpi_ranks": rank,
                    "energy_abs_change_mev_atom": energy,
                    "force_component_max_abs_change_ev_angstrom": float(
                        np.max(np.abs(force_delta))
                    ),
                    "stress_component_max_abs_change_gpa": float(
                        np.max(np.abs(stress_delta))
                    ),
                }
            )
    force_vector = np.concatenate(force_changes)
    stress_vector = np.concatenate(stress_changes)
    metrics = {
        "energy_abs_change_mev_atom_max": float(max(energy_changes)),
        "force_component_max_abs_change_ev_angstrom": float(
            np.max(np.abs(force_vector))
        ),
        "force_component_rmse_change_ev_angstrom": float(
            np.sqrt(np.mean(force_vector**2))
        ),
        "stress_component_max_abs_change_gpa": float(
            np.max(np.abs(stress_vector))
        ),
        "stress_component_rmse_change_gpa": float(
            np.sqrt(np.mean(stress_vector**2))
        ),
    }
    limits = {
        "energy_abs_change_mev_atom_max": float(energy_abs_change_mev_atom_max),
        "force_component_max_abs_change_ev_angstrom": float(
            force_component_max_abs_change_ev_angstrom
        ),
        "stress_component_max_abs_change_gpa": float(
            stress_component_max_abs_change_gpa
        ),
    }
    if any(not math.isfinite(value) or value <= 0 for value in limits.values()):
        raise ValueError("MPI equivalence limits must be finite and positive")
    checks = {name: metrics[name] <= limit for name, limit in limits.items()}
    return {
        "required_mpi_ranks": required,
        "baseline_mpi_ranks": baseline_rank,
        "structure_ids": expected_structures,
        "n_cells": len(records),
        "n_comparisons": len(comparisons),
        "comparisons": comparisons,
        "metrics": metrics,
        "limits": limits,
        "checks": checks,
        "mpi_equivalence_gate_pass": all(checks.values()),
    }


def _verify_queue_state(
    path: Path,
    *,
    mpi_ranks: int,
    run_dirs: list[Path],
) -> dict[str, Any]:
    state = _read_json(path)
    config = state.get("config", {})
    configured_dirs = {str(Path(value).resolve()) for value in config.get("run_dirs", [])}
    expected_dirs = {str(value.resolve()) for value in run_dirs}
    checks = {
        "schema_version": state.get("schema_version") == "1.0",
        "queue_complete": state.get("status") == "complete",
        "mpi_ranks": int(config.get("mpi_ranks", -1)) == mpi_ranks,
        "run_dirs": configured_dirs == expected_dirs,
        "job_count": len(state.get("jobs", {})) == len(run_dirs),
        "jobs_complete": bool(state.get("jobs"))
        and all(
            job.get("status")
            in {"complete", "already_labelled", "collected_existing_output"}
            for job in state["jobs"].values()
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(
            f"MPI queue-state provenance failed for rank {mpi_ranks}: "
            + ", ".join(failed)
        )
    elapsed = []
    for job in state["jobs"].values():
        start = job.get("started_unix_time")
        finish = job.get("finished_unix_time")
        if isinstance(start, (int, float)) and isinstance(finish, (int, float)):
            elapsed.append(float(finish) - float(start))
    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "queue_fingerprint": state.get("queue_fingerprint"),
        "total_recorded_wall_seconds": sum(elapsed) if len(elapsed) == len(run_dirs) else None,
    }


def build_mpi_report(
    protocol_path: Path | str,
    run_entries: list[tuple[int, str, Path | str]],
    queue_state_entries: list[tuple[int, Path | str]],
) -> dict[str, Any]:
    """Load hash-verified QE labels and their rank-specific queue attestations."""
    source = Path(protocol_path).resolve()
    protocol = _read_json(source)
    if protocol.get("schema_version") != "1.0":
        raise ValueError("MPI protocol schema_version must be '1.0'")
    required_ranks = [int(value) for value in protocol["required_mpi_ranks"]]
    structure_ids = [str(value) for value in protocol["structure_ids"]]
    by_rank: dict[int, list[tuple[str, Path]]] = {}
    for rank, structure_id, directory in run_entries:
        by_rank.setdefault(int(rank), []).append((str(structure_id), Path(directory).resolve()))
    if sorted(by_rank) != sorted(required_ranks):
        raise ValueError("MPI run entries do not cover the required ranks")
    if any(sorted(item[0] for item in rows) != sorted(structure_ids) for rows in by_rank.values()):
        raise ValueError("MPI run entries do not cover every required structure")
    queue_paths: dict[int, Path] = {}
    for rank, path in queue_state_entries:
        if int(rank) in queue_paths:
            raise ValueError(f"duplicate MPI queue-state rank {rank}")
        queue_paths[int(rank)] = Path(path).resolve()
    if sorted(queue_paths) != sorted(required_ranks):
        raise ValueError("MPI queue-state entries do not cover the required ranks")

    records = []
    sources = []
    queue_sources = []
    runtime_by_rank = {}
    for rank in required_ranks:
        run_dirs = [directory for _structure, directory in by_rank[rank]]
        queue = _verify_queue_state(queue_paths[rank], mpi_ranks=rank, run_dirs=run_dirs)
        queue_sources.append({"mpi_ranks": rank, **queue})
        runtime_by_rank[str(rank)] = queue["total_recorded_wall_seconds"]
        for structure_id, directory in by_rank[rank]:
            completed = load_completed_qe_run(directory)
            records.append(
                {
                    "mpi_ranks": rank,
                    "structure_id": structure_id,
                    **{
                        key: completed[key]
                        for key in (
                            "structure_fingerprint",
                            "n_atoms",
                            "settings",
                            "total_energy_ev",
                            "forces_ev_angstrom",
                            "stress_gpa",
                        )
                    },
                }
            )
            sources.append(
                {
                    "mpi_ranks": rank,
                    "structure_id": structure_id,
                    "run_id": completed["run_id"],
                    "run_dir": completed["run_dir"],
                    "run_manifest_sha256": completed["run_manifest_sha256"],
                    "label_sha256": completed["label_sha256"],
                }
            )
    acceptance = protocol["acceptance"]
    result = analyze_mpi_results(
        records,
        required_ranks=required_ranks,
        baseline_rank=int(protocol["baseline_mpi_ranks"]),
        structure_ids=structure_ids,
        energy_abs_change_mev_atom_max=float(
            acceptance["energy_abs_change_mev_atom_max"]
        ),
        force_component_max_abs_change_ev_angstrom=float(
            acceptance["force_component_max_abs_change_ev_angstrom"]
        ),
        stress_component_max_abs_change_gpa=float(
            acceptance["stress_component_max_abs_change_gpa"]
        ),
    )
    finite_runtimes = {
        rank: value for rank, value in runtime_by_rank.items() if value is not None
    }
    baseline_runtime = runtime_by_rank.get(str(protocol["baseline_mpi_ranks"]))
    scaling = {
        rank: (
            baseline_runtime / value
            if baseline_runtime is not None and value is not None and value > 0
            else None
        )
        for rank, value in runtime_by_rank.items()
    }
    report = {
        "schema_version": "1.0",
        "report_kind": "qe-mpi-reproducibility",
        "protocol_path": str(source),
        "protocol_sha256": sha256_file(source),
        **result,
        "runtime_scaling_descriptive_only": {
            "total_recorded_wall_seconds_by_rank": runtime_by_rank,
            "speedup_relative_to_baseline": scaling,
            "complete_runtime_count": len(finite_runtimes),
            "used_for_equivalence_gate": False,
        },
        "sources": sources,
        "queue_sources": queue_sources,
        "implementation_path": str(Path(__file__).resolve()),
        "implementation_sha256": sha256_file(__file__),
    }
    report["report_fingerprint"] = fingerprint(report)
    return report


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    parser.add_argument(
        "--run",
        nargs=3,
        action="append",
        metavar=("MPI_RANKS", "STRUCTURE_ID", "RUN_DIR"),
        required=True,
    )
    parser.add_argument(
        "--queue-state",
        nargs=2,
        action="append",
        metavar=("MPI_RANKS", "STATE_JSON"),
        required=True,
    )
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = build_mpi_report(
        args.protocol,
        [(int(rank), structure, path) for rank, structure, path in args.run],
        [(int(rank), path) for rank, path in args.queue_state],
    )
    destination = Path(args.out).resolve()
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite MPI report: {destination}")
    atomic_write_json(destination, report)
    print(json.dumps(report, indent=2, default=lambda value: value.tolist()))


if __name__ == "__main__":
    main()
