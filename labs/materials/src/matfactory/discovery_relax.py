"""Run budgeted, resumable, dual-model relaxation of ordered candidates."""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .provenance import (
    atomic_write_json,
    environment_versions,
    fingerprint,
    git_state,
    sha256_file,
)

_ROOT = Path(__file__).resolve().parents[2]
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


@dataclass(frozen=True)
class RelaxationProtocol:
    relaxation_id: str
    protocol_path: Path
    protocol_sha256: str
    root_dir: Path
    enabled: bool
    ordering_manifest: Path
    approved_ordering_content_fingerprint: str
    model_registry: Path
    approved_registry_content_fingerprint: str
    device: str
    max_structures: int
    max_atoms: int
    gpu_hours: float
    wall_time_hours: float
    estimated_minutes_per_job: float
    fmax_ev_a: float
    max_steps: int
    relax_cell: bool
    optimizer: str
    model_dtype: str
    included_candidate_ids: tuple[str, ...]
    agreement: dict[str, float | int]


def _read_json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {source}")
    return payload


def _repo_path(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (_ROOT / path).resolve()


def _positive_number(
    mapping: dict[str, Any], field: str, *, allow_zero: bool = False
) -> float:
    value = mapping.get(field)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(f"{field} must be numeric")
    result = float(value)
    if result < 0 if allow_zero else result <= 0:
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{field} must be {qualifier}")
    return result


def _digest(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return ""
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


def load_relaxation_protocol(path: Path | str) -> RelaxationProtocol:
    source = Path(path).resolve()
    payload = _read_json(source)
    if payload.get("schema_version") != "1.0":
        raise ValueError("relaxation schema_version must be '1.0'")
    relaxation_id = payload.get("relaxation_id")
    if not isinstance(relaxation_id, str) or not _SAFE_ID.fullmatch(relaxation_id):
        raise ValueError("relaxation_id must be a safe lowercase identifier")
    enabled = bool(payload.get("enabled", False))
    ordering_approval = _digest(
        payload.get("approved_ordering_content_fingerprint", ""),
        "approved_ordering_content_fingerprint",
        allow_empty=not enabled,
    )
    registry_approval = _digest(
        payload.get("approved_registry_content_fingerprint", ""),
        "approved_registry_content_fingerprint",
        allow_empty=not enabled,
    )
    budget = payload.get("budget")
    optimizer = payload.get("optimizer")
    agreement = payload.get("agreement")
    if not isinstance(budget, dict) or not isinstance(optimizer, dict):
        raise TypeError("budget and optimizer must be objects")
    if not isinstance(agreement, dict):
        raise TypeError("agreement must be an object")

    def integer(mapping: dict[str, Any], field: str, minimum: int, maximum: int) -> int:
        value = mapping.get(field)
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"{field} must be an integer")
        if not minimum <= value <= maximum:
            raise ValueError(f"{field} must be from {minimum} to {maximum}")
        return value

    wall_hours = _positive_number(budget, "wall_time_hours")
    gpu_hours = _positive_number(budget, "gpu_hours", allow_zero=True)
    if wall_hours > 24 or gpu_hours > wall_hours:
        raise ValueError("single-GPU discovery must fit within 24 wall/GPU hours")
    optimizer_name = optimizer.get("name")
    if optimizer_name not in {"FIRE", "BFGS"}:
        raise ValueError("optimizer.name must be FIRE or BFGS")
    dtype = payload.get("model_dtype", "float32")
    if dtype not in {"float32", "float64"}:
        raise ValueError("model_dtype must be float32 or float64")
    included = payload.get("included_candidate_ids", [])
    if not isinstance(included, list) or any(
        not isinstance(candidate_id, str) or not _SAFE_ID.fullmatch(candidate_id)
        for candidate_id in included
    ):
        raise ValueError("included_candidate_ids must contain safe identifiers")
    if len(included) != len(set(included)):
        raise ValueError("included_candidate_ids must not contain duplicates")
    for field in (
        "minimum_spearman",
        "minimum_top_k_overlap",
        "maximum_median_rmsd_angstrom",
        "maximum_median_cell_strain",
    ):
        _positive_number(agreement, field, allow_zero=True)
    for field in (
        "minimum_energy_spread_mev_atom",
        "minimum_ground_state_margin_mev_atom",
    ):
        value = agreement.get(field, 0.0)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise TypeError(f"{field} must be numeric")
        if float(value) < 0:
            raise ValueError(f"{field} must be non-negative")
    if not 0 <= float(agreement["minimum_spearman"]) <= 1:
        raise ValueError("minimum_spearman must be from 0 to 1")
    if not 0 <= float(agreement["minimum_top_k_overlap"]) <= 1:
        raise ValueError("minimum_top_k_overlap must be from 0 to 1")
    top_k = integer(agreement, "top_k", 1, 100)
    minimum_pairs = integer(agreement, "minimum_pairs", 3, 100)
    normalized_agreement: dict[str, float | int] = {
        "minimum_spearman": float(agreement["minimum_spearman"]),
        "minimum_top_k_overlap": float(agreement["minimum_top_k_overlap"]),
        "maximum_median_rmsd_angstrom": float(
            agreement["maximum_median_rmsd_angstrom"]
        ),
        "maximum_median_cell_strain": float(agreement["maximum_median_cell_strain"]),
        "minimum_energy_spread_mev_atom": float(
            agreement.get("minimum_energy_spread_mev_atom", 0.0)
        ),
        "minimum_ground_state_margin_mev_atom": float(
            agreement.get("minimum_ground_state_margin_mev_atom", 0.0)
        ),
        "top_k": top_k,
        "minimum_pairs": minimum_pairs,
    }
    return RelaxationProtocol(
        relaxation_id=relaxation_id,
        protocol_path=source,
        protocol_sha256=sha256_file(source),
        root_dir=_repo_path(
            str(payload.get("root_dir", f"runs/relaxation/{relaxation_id}"))
        ),
        enabled=enabled,
        ordering_manifest=_repo_path(str(payload.get("ordering_manifest", ""))),
        approved_ordering_content_fingerprint=ordering_approval,
        model_registry=_repo_path(str(payload.get("model_registry", ""))),
        approved_registry_content_fingerprint=registry_approval,
        device=str(payload.get("device", "cuda")),
        max_structures=integer(budget, "max_structures", 1, 1000),
        max_atoms=integer(budget, "max_atoms", 1, 1000),
        gpu_hours=gpu_hours,
        wall_time_hours=wall_hours,
        estimated_minutes_per_job=_positive_number(budget, "estimated_minutes_per_job"),
        fmax_ev_a=_positive_number(optimizer, "fmax_ev_a"),
        max_steps=integer(optimizer, "max_steps", 1, 100_000),
        relax_cell=bool(optimizer.get("relax_cell", False)),
        optimizer=str(optimizer_name),
        model_dtype=str(dtype),
        included_candidate_ids=tuple(included),
        agreement=normalized_agreement,
    )


def _model_records(
    protocol: RelaxationProtocol,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    registry = _read_json(protocol.model_registry)
    if (
        registry.get("content_fingerprint")
        != protocol.approved_registry_content_fingerprint
    ):
        raise RuntimeError("model registry lacks the approved content fingerprint")
    records = registry.get("models")
    if not isinstance(records, list) or len(records) != 2:
        raise RuntimeError("relaxation requires exactly two frozen model records")
    if len({str(record.get("family")) for record in records}) != 2:
        raise RuntimeError("relaxation model records must have distinct families")
    for record in records:
        artifact = Path(str(record.get("artifact_path", "")))
        if not artifact.is_file() or sha256_file(artifact) != record.get(
            "artifact_sha256"
        ):
            raise RuntimeError(f"model artifact changed or vanished: {artifact}")
    return registry, [dict(record) for record in records]


def _ordering_rows(
    protocol: RelaxationProtocol,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = _read_json(protocol.ordering_manifest)
    if (
        manifest.get("content_fingerprint")
        != protocol.approved_ordering_content_fingerprint
    ):
        raise RuntimeError("ordering manifest lacks the approved content fingerprint")
    rows: list[dict[str, Any]] = []
    observed_candidates: set[str] = set()
    for candidate in manifest.get("results", []):
        if not isinstance(candidate, dict):
            continue
        candidate_id = str(candidate.get("candidate_id"))
        observed_candidates.add(candidate_id)
        if (
            protocol.included_candidate_ids
            and candidate_id not in protocol.included_candidate_ids
        ):
            continue
        for index, ordering in enumerate(candidate.get("orderings", [])):
            if not isinstance(ordering, dict):
                continue
            path = Path(str(ordering.get("path", "")))
            expected = ordering.get("sha256")
            if not path.is_file() or sha256_file(path) != expected:
                raise RuntimeError(f"ordering changed or vanished: {path}")
            rows.append(
                {
                    "candidate_id": candidate_id,
                    "ordering_id": f"{candidate_id}--{index:03d}",
                    "path": path,
                    "sha256": expected,
                    "n_atoms": int(ordering.get("n_atoms", 0)),
                }
            )
    missing = set(protocol.included_candidate_ids) - observed_candidates
    if missing:
        raise RuntimeError(
            "included candidates are absent from ordering manifest: "
            + ", ".join(sorted(missing))
        )
    if not rows:
        raise RuntimeError("approved ordering manifest contains no structures")
    if len(rows) > protocol.max_structures:
        raise RuntimeError("ordering count exceeds budget.max_structures")
    oversized = [
        row["ordering_id"] for row in rows if row["n_atoms"] > protocol.max_atoms
    ]
    if oversized:
        raise RuntimeError(
            "ordering atom count exceeds budget: " + ", ".join(oversized)
        )
    return manifest, rows


def load_model_calculator(record: dict[str, Any], *, device: str, dtype: str) -> Any:
    """Build an ASE calculator from one hash-verified registry record."""
    artifact = str(record["artifact_path"])
    family = str(record["family"])
    if family == "chgnet":
        from chgnet.model import CHGNet
        from chgnet.model.dynamics import CHGNetCalculator

        model = CHGNet.from_file(artifact)
        return CHGNetCalculator(
            model=model,
            use_device=device,
            on_isolated_atoms="error",
        )
    if family == "mace":
        from mace.calculators import MACECalculator

        return MACECalculator(
            model_paths=artifact,
            device=device,
            default_dtype=dtype,
        )
    raise ValueError(f"unsupported model family {family!r}")


def _minimum_distance(atoms: Any) -> float | None:
    if len(atoms) < 2:
        return None
    distances = np.asarray(atoms.get_all_distances(mic=True), dtype=float)
    distances[distances == 0] = np.inf
    return float(np.min(distances))


def _symmetry(atoms: Any, symprec: float = 0.1) -> dict[str, Any]:
    import spglib

    dataset = spglib.get_symmetry_dataset(
        (atoms.cell.array, atoms.get_scaled_positions(), atoms.numbers),
        symprec=symprec,
    )
    if dataset is None:
        return {"number": None, "international": None}
    return {"number": int(dataset.number), "international": str(dataset.international)}


def relax_atoms(
    atoms: Any,
    calculator: Any,
    *,
    fmax_ev_a: float,
    max_steps: int,
    relax_cell: bool,
    optimizer_name: str,
    deadline_monotonic: float,
) -> tuple[Any, dict[str, Any]]:
    """Relax one ASE Atoms object and return a compact convergence trace."""
    from ase.filters import FrechetCellFilter
    from ase.optimize import BFGS, FIRE

    working = atoms.copy()
    working.calc = calculator
    target = FrechetCellFilter(working) if relax_cell else working
    optimizer_class = {"FIRE": FIRE, "BFGS": BFGS}[optimizer_name]
    optimizer = optimizer_class(target, logfile=None)
    trace: list[dict[str, float | int]] = []

    def observe() -> None:
        if time.monotonic() > deadline_monotonic:
            raise TimeoutError("relaxation wall-time deadline reached")
        forces = np.asarray(working.get_forces(), dtype=float)
        trace.append(
            {
                "step": int(optimizer.get_number_of_steps()),
                "energy_ev": float(working.get_potential_energy()),
                "maximum_force_ev_a": float(np.linalg.norm(forces, axis=1).max()),
                "volume_angstrom3": float(working.get_volume()),
            }
        )

    optimizer.attach(observe, interval=1)
    converged = bool(optimizer.run(fmax=fmax_ev_a, steps=max_steps))
    if not trace:
        observe()
    record: dict[str, Any] = {
        "converged": converged,
        "n_steps": int(optimizer.get_number_of_steps()),
        "final_energy_ev": float(working.get_potential_energy()),
        "final_energy_ev_atom": float(working.get_potential_energy() / len(working)),
        "final_maximum_force_ev_a": float(
            np.linalg.norm(np.asarray(working.get_forces()), axis=1).max()
        ),
        "minimum_distance_angstrom": _minimum_distance(working),
        "symmetry": _symmetry(working),
        "trace": trace,
    }
    return working, record


def _pair_geometry(first: Any, second: Any) -> dict[str, float]:
    if first.get_chemical_symbols() != second.get_chemical_symbols():
        raise ValueError("paired relaxed structures changed atom ordering")
    first_fractional = first.get_scaled_positions(wrap=False)
    second_fractional = second.get_scaled_positions(wrap=False)
    delta = second_fractional - first_fractional
    delta -= np.round(delta)
    average_cell = 0.5 * (first.cell.array + second.cell.array)
    cartesian = delta @ average_cell
    rmsd = float(np.sqrt(np.mean(np.sum(cartesian * cartesian, axis=1))))
    denominator = float(np.linalg.norm(first.cell.array))
    strain = float(np.linalg.norm(second.cell.array - first.cell.array) / denominator)
    return {"rmsd_angstrom": rmsd, "cell_strain": strain}


def assess_model_agreement(
    results: list[dict[str, Any]],
    structures: dict[tuple[str, str], Any],
    thresholds: dict[str, float | int],
) -> dict[str, Any]:
    """Assess only ranks and paired geometries, never raw cross-model energies."""
    from scipy.stats import spearmanr

    completed = [row for row in results if row.get("status") == "completed"]
    families = sorted({str(row["model_family"]) for row in completed})
    candidates = sorted({str(row["candidate_id"]) for row in completed})
    assessments: list[dict[str, Any]] = []
    for candidate_id in candidates:
        by_family = {
            family: {
                str(row["ordering_id"]): row
                for row in completed
                if row["candidate_id"] == candidate_id
                and row["model_family"] == family
                and row.get("converged") is True
            }
            for family in families
        }
        common = (
            sorted(set.intersection(*(set(rows) for rows in by_family.values())))
            if len(families) == 2
            else []
        )
        reasons: list[str] = []
        minimum_pairs = int(thresholds["minimum_pairs"])
        if len(common) < minimum_pairs:
            reasons.append(
                f"only {len(common)} converged paired structures; need {minimum_pairs}"
            )
        spearman = None
        overlap = None
        energy_spreads: dict[str, float] = {}
        ground_state_margins: dict[str, float] = {}
        geometry: list[dict[str, Any]] = []
        if len(families) == 2 and common:
            energies = [
                [
                    float(by_family[family][item]["final_energy_ev_atom"])
                    for item in common
                ]
                for family in families
            ]
            for family, values in zip(families, energies, strict=True):
                ordered = np.sort(np.asarray(values, dtype=float))
                energy_spreads[family] = float(1000.0 * (ordered[-1] - ordered[0]))
                ground_state_margins[family] = (
                    float(1000.0 * (ordered[1] - ordered[0]))
                    if len(ordered) > 1
                    else 0.0
                )
            statistic = float(spearmanr(energies[0], energies[1]).statistic)
            spearman = statistic if math.isfinite(statistic) else 0.0
            k = min(int(thresholds["top_k"]), len(common))
            top = [
                {
                    common[index]
                    for index in np.argsort(np.asarray(values, dtype=float))[:k]
                }
                for values in energies
            ]
            overlap = len(top[0] & top[1]) / k
            for ordering_id in common:
                pair = _pair_geometry(
                    structures[(families[0], ordering_id)],
                    structures[(families[1], ordering_id)],
                )
                pair["ordering_id"] = ordering_id
                geometry.append(pair)
            median_rmsd = float(np.median([row["rmsd_angstrom"] for row in geometry]))
            median_strain = float(np.median([row["cell_strain"] for row in geometry]))
            if spearman < float(thresholds["minimum_spearman"]):
                reasons.append("within-model energy ranks disagree")
            if overlap < float(thresholds["minimum_top_k_overlap"]):
                reasons.append("low-energy sets disagree")
            if median_rmsd > float(thresholds["maximum_median_rmsd_angstrom"]):
                reasons.append("relaxed geometries disagree")
            if median_strain > float(thresholds["maximum_median_cell_strain"]):
                reasons.append("relaxed cells disagree")
            if min(energy_spreads.values()) < float(
                thresholds.get("minimum_energy_spread_mev_atom", 0.0)
            ):
                reasons.append("within-model energy spread is numerically unresolved")
            if min(ground_state_margins.values()) < float(
                thresholds.get("minimum_ground_state_margin_mev_atom", 0.0)
            ):
                reasons.append("ground-state margin is numerically unresolved")
        else:
            median_rmsd = None
            median_strain = None
        assessments.append(
            {
                "candidate_id": candidate_id,
                "model_families": families,
                "n_paired": len(common),
                "spearman_rank_correlation": spearman,
                "top_k_overlap_fraction": overlap,
                "within_model_energy_spread_mev_atom": energy_spreads,
                "within_model_ground_state_margin_mev_atom": ground_state_margins,
                "median_paired_rmsd_angstrom": median_rmsd,
                "median_paired_cell_strain": median_strain,
                "paired_geometry": geometry,
                "screen_passed": not reasons,
                "reasons": reasons,
            }
        )
    return {
        "schema_version": "1.0",
        "comparison_boundary": (
            "Energies were ranked within each model and were not compared on an "
            "absolute cross-model scale. Shared MPTrj lineage prevents independence."
        ),
        "thresholds": thresholds,
        "candidates": assessments,
    }


def _check_resume(path: Path, job_fingerprint: str) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    result = _read_json(path)
    if result.get("job_fingerprint") != job_fingerprint:
        raise RuntimeError(f"existing relaxation job has different inputs: {path}")
    output = Path(str(result.get("output_path", "")))
    if result.get("status") == "completed" and (
        not output.is_file() or sha256_file(output) != result.get("output_sha256")
    ):
        raise RuntimeError(f"completed relaxation output changed: {output}")
    return result


def run_relaxation_campaign(
    path: Path | str,
    *,
    calculator_factories: dict[str, Callable[[dict[str, Any]], Any]] | None = None,
) -> dict[str, Any]:
    """Execute all materialized jobs after registry, novelty, and budget releases."""
    from ase.io import read, write

    protocol = load_relaxation_protocol(path)
    if not protocol.enabled:
        raise RuntimeError("dual-model relaxation protocol is disabled")
    registry, models = _model_records(protocol)
    ordering_manifest, orderings = _ordering_rows(protocol)
    estimated_gpu_hours = (
        len(orderings) * len(models) * protocol.estimated_minutes_per_job / 60.0
    )
    if estimated_gpu_hours > protocol.gpu_hours:
        raise RuntimeError(
            f"materialized jobs estimate {estimated_gpu_hours:.2f} GPU-hours, "
            f"above frozen budget {protocol.gpu_hours:.2f}"
        )
    if calculator_factories is None and protocol.device.startswith("cuda"):
        import torch

        if not torch.cuda.is_available():
            raise RuntimeError(
                "CUDA protocol requested but no CUDA device is available"
            )
    protocol.root_dir.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    deadline = start + protocol.wall_time_hours * 3600.0
    results: list[dict[str, Any]] = []
    structures: dict[tuple[str, str], Any] = {}
    for model in models:
        family = str(model["family"])
        factory = (calculator_factories or {}).get(family)
        calculator = (
            factory(model)
            if factory is not None
            else load_model_calculator(
                model, device=protocol.device, dtype=protocol.model_dtype
            )
        )
        for ordering in orderings:
            ordering_id = str(ordering["ordering_id"])
            job_payload = {
                "protocol_sha256": protocol.protocol_sha256,
                "registry_content_fingerprint": registry["content_fingerprint"],
                "model_id": model["model_id"],
                "model_artifact_sha256": model["artifact_sha256"],
                "ordering_id": ordering_id,
                "ordering_sha256": ordering["sha256"],
            }
            job_fingerprint = fingerprint(job_payload)
            job_dir = protocol.root_dir / family / ordering_id
            result_path = job_dir / "result.json"
            prior = _check_resume(result_path, job_fingerprint)
            if prior is not None:
                results.append(prior)
                if prior.get("status") == "completed":
                    structures[(family, ordering_id)] = read(prior["output_path"])
                continue
            job_dir.mkdir(parents=True, exist_ok=True)
            started = time.monotonic()
            base: dict[str, Any] = {
                "schema_version": "1.0",
                "job_fingerprint": job_fingerprint,
                "candidate_id": ordering["candidate_id"],
                "ordering_id": ordering_id,
                "input_path": str(ordering["path"]),
                "input_sha256": ordering["sha256"],
                "model_id": model["model_id"],
                "model_family": family,
                "model_artifact_sha256": model["artifact_sha256"],
            }
            try:
                atoms = read(ordering["path"])
                relaxed, record = relax_atoms(
                    atoms,
                    calculator,
                    fmax_ev_a=protocol.fmax_ev_a,
                    max_steps=protocol.max_steps,
                    relax_cell=protocol.relax_cell,
                    optimizer_name=protocol.optimizer,
                    deadline_monotonic=deadline,
                )
                output_path = job_dir / "relaxed.cif"
                write(output_path, relaxed, format="cif")
                base.update(record)
                base.update(
                    {
                        "status": "completed",
                        "output_path": str(output_path.resolve()),
                        "output_sha256": sha256_file(output_path),
                        "wall_seconds": time.monotonic() - started,
                    }
                )
                structures[(family, ordering_id)] = relaxed
            except Exception as exc:  # noqa: BLE001 - preserve sibling jobs
                base.update(
                    {
                        "status": "failed",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "wall_seconds": time.monotonic() - started,
                    }
                )
            atomic_write_json(result_path, base)
            results.append(base)
            if time.monotonic() > deadline:
                break
        if time.monotonic() > deadline:
            break
    agreement = assess_model_agreement(results, structures, protocol.agreement)
    atomic_write_json(protocol.root_dir / "agreement.json", agreement)
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "manifest_kind": "dual-model-geometry-relaxation",
        "relaxation_id": protocol.relaxation_id,
        "created_unix_time": time.time(),
        "protocol_path": str(protocol.protocol_path),
        "protocol_sha256": protocol.protocol_sha256,
        "ordering_content_fingerprint": ordering_manifest["content_fingerprint"],
        "registry_content_fingerprint": registry["content_fingerprint"],
        "estimated_gpu_hours": estimated_gpu_hours,
        "included_candidate_ids": list(protocol.included_candidate_ids),
        "observed_wall_seconds": time.monotonic() - start,
        "environment": environment_versions(
            (
                "matfactory",
                "chgnet",
                "mace-torch",
                "torch",
                "ase",
                "numpy",
                "scipy",
                "spglib",
            )
        ),
        "git": git_state(_ROOT),
        "jobs": results,
        "agreement": agreement,
        "publication_assessment": {
            "q1_claim_ready": False,
            "reason": (
                "MLIP agreement is a screen only; independent DFT, full novelty "
                "review, robustness checks, and a complete scientific narrative remain."
            ),
        },
    }
    manifest["manifest_fingerprint"] = fingerprint(manifest)
    atomic_write_json(protocol.root_dir / "relaxation-manifest.json", manifest)
    return manifest


def relaxation_summary(protocol: RelaxationProtocol) -> dict[str, Any]:
    return {
        "relaxation_id": protocol.relaxation_id,
        "protocol_sha256": protocol.protocol_sha256,
        "enabled": protocol.enabled,
        "device": protocol.device,
        "max_structures": protocol.max_structures,
        "gpu_hours": protocol.gpu_hours,
        "included_candidate_ids": list(protocol.included_candidate_ids),
        "approved_ordering_content_fingerprint": (
            protocol.approved_ordering_content_fingerprint
        ),
        "approved_registry_content_fingerprint": (
            protocol.approved_registry_content_fingerprint
        ),
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol")
    parser.add_argument("--list", action="store_true", dest="list_only")
    args = parser.parse_args()
    protocol = load_relaxation_protocol(args.protocol)
    output = (
        relaxation_summary(protocol)
        if args.list_only
        else run_relaxation_campaign(protocol.protocol_path)
    )
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
