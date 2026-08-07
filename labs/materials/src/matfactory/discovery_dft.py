"""Prepare hash-locked Quantum ESPRESSO confirmation inputs for discoveries."""

from __future__ import annotations

import hashlib
import json
import math
import re
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .dft import atoms_fingerprint, prepare_qe_inputs
from .provenance import (
    atomic_write_json,
    atomic_write_text,
    fingerprint,
    sha256_bytes,
    sha256_file,
)

_ROOT = Path(__file__).resolve().parents[2]
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


@dataclass(frozen=True)
class DFTConfirmationProtocol:
    confirmation_id: str
    protocol_path: Path
    protocol_sha256: str
    root_dir: Path
    enabled: bool
    source_manifest: Path
    approved_source_manifest_fingerprint: str
    selected_structures: tuple[dict[str, str], ...]
    qe_manifest: Path
    qe_manifest_sha256: str
    qe_executable: Path
    qe_executable_sha256: str
    qe_lock: Path
    qe_lock_sha256: str
    sssp_index: Path
    sssp_index_sha256: str
    sssp_archive: Path
    sssp_archive_sha256: str
    max_structures: int
    max_atoms: int
    cutoff_multipliers: tuple[float, ...]
    kpoint_cutoff_multiplier: float
    kpoint_mesh: tuple[int, int, int]
    scf_thresholds_ry: tuple[float, ...]
    numerical_thresholds: dict[str, float]
    physics_review: dict[str, Any]


def _read_json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {source}")
    return payload


def _repo_path(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (_ROOT / path).resolve()


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


def _integer(mapping: dict[str, Any], field: str, minimum: int, maximum: int) -> int:
    value = mapping.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{field} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{field} must be from {minimum} to {maximum}")
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


def load_dft_confirmation_protocol(path: Path | str) -> DFTConfirmationProtocol:
    source = Path(path).resolve()
    payload = _read_json(source)
    if payload.get("schema_version") != "1.0":
        raise ValueError("DFT confirmation schema_version must be '1.0'")
    confirmation_id = payload.get("confirmation_id")
    if not isinstance(confirmation_id, str) or not _SAFE_ID.fullmatch(confirmation_id):
        raise ValueError("confirmation_id must be a safe lowercase identifier")
    enabled = bool(payload.get("enabled", False))
    selected = payload.get("selected_structures", [])
    if not isinstance(selected, list):
        raise TypeError("selected_structures must be a list")
    normalized: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    for row in selected:
        if not isinstance(row, dict):
            raise TypeError("each selected structure must be an object")
        structure_id = row.get("structure_id")
        role = row.get("role")
        if (
            not isinstance(structure_id, str)
            or not _SAFE_ID.fullmatch(structure_id)
            or structure_id in seen_ids
        ):
            raise ValueError("selected structure_id is unsafe or duplicated")
        if not isinstance(role, str) or not role:
            raise ValueError("selected structure role must be non-empty")
        artifact_hash = _digest(row.get("artifact_sha256"), "artifact_sha256")
        if artifact_hash in seen_hashes:
            raise ValueError("selected structure hashes must be unique")
        seen_ids.add(structure_id)
        seen_hashes.add(artifact_hash)
        normalized.append(
            {
                "structure_id": structure_id,
                "role": role,
                "artifact_sha256": artifact_hash,
            }
        )
    if enabled and len(normalized) < 2:
        raise ValueError("enabled DFT confirmation requires at least two structures")
    execution = payload.get("execution")
    sssp = payload.get("sssp")
    numerics = payload.get("numerics")
    budget = payload.get("budget")
    review = payload.get("physics_review")
    if not all(
        isinstance(item, dict) for item in (execution, sssp, numerics, budget, review)
    ):
        raise TypeError(
            "execution, sssp, numerics, budget, and physics_review must be objects"
        )
    required_reviews = (
        "magnetism_reviewed",
        "hubbard_u_reviewed",
        "metallicity_reviewed",
        "spin_orbit_reviewed",
    )
    if enabled and any(review.get(field) is not True for field in required_reviews):
        raise RuntimeError("enabled DFT protocol lacks all manual physics reviews")
    if enabled and review.get("approved_model") != "closed-shell-nonmagnetic-pbe":
        raise RuntimeError(
            "current renderer is released only for closed-shell nonmagnetic PBE"
        )
    multipliers = numerics.get("cutoff_multipliers")
    scf = numerics.get("scf_thresholds_ry")
    kpoints = numerics.get("kpoint_mesh")
    if (
        not isinstance(multipliers, list)
        or len(multipliers) < 2
        or any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or float(value) < 1
            for value in multipliers
        )
        or sorted(float(value) for value in multipliers)
        != [float(value) for value in multipliers]
    ):
        raise ValueError("cutoff_multipliers must be sorted numbers >= 1")
    kpoint_cutoff = numerics.get("kpoint_cutoff_multiplier", multipliers[-1])
    if (
        not isinstance(kpoint_cutoff, (int, float))
        or isinstance(kpoint_cutoff, bool)
        or float(kpoint_cutoff) not in {float(value) for value in multipliers}
    ):
        raise ValueError(
            "kpoint_cutoff_multiplier must equal one cutoff_multipliers entry"
        )
    if (
        not isinstance(scf, list)
        or len(scf) < 2
        or any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or float(value) <= 0
            for value in scf
        )
    ):
        raise ValueError("scf_thresholds_ry must contain at least two positive values")
    if (
        not isinstance(kpoints, list)
        or len(kpoints) != 3
        or any(not isinstance(value, int) or value < 1 for value in kpoints)
    ):
        raise ValueError("kpoint_mesh must contain three positive integers")
    thresholds = {
        field: _positive(numerics, field)
        for field in (
            "relative_energy_mev_atom",
            "force_component_ev_a",
            "stress_component_gpa",
        )
    }
    return DFTConfirmationProtocol(
        confirmation_id=confirmation_id,
        protocol_path=source,
        protocol_sha256=sha256_file(source),
        root_dir=_repo_path(
            str(payload.get("root_dir", f"runs/dft-discovery/{confirmation_id}"))
        ),
        enabled=enabled,
        source_manifest=_repo_path(str(payload.get("source_manifest", ""))),
        approved_source_manifest_fingerprint=_digest(
            payload.get("approved_source_manifest_fingerprint", ""),
            "approved_source_manifest_fingerprint",
            allow_empty=not enabled,
        ),
        selected_structures=tuple(normalized),
        qe_manifest=_repo_path(str(execution.get("manifest", ""))),
        qe_manifest_sha256=_digest(
            execution.get("manifest_sha256"), "execution.manifest_sha256"
        ),
        qe_executable=_repo_path(str(execution.get("pw_executable", ""))),
        qe_executable_sha256=_digest(
            execution.get("pw_executable_sha256"),
            "execution.pw_executable_sha256",
        ),
        qe_lock=_repo_path(str(execution.get("explicit_lock", ""))),
        qe_lock_sha256=_digest(
            execution.get("explicit_lock_sha256"),
            "execution.explicit_lock_sha256",
        ),
        sssp_index=_repo_path(str(sssp.get("index", ""))),
        sssp_index_sha256=_digest(sssp.get("index_sha256"), "sssp.index_sha256"),
        sssp_archive=_repo_path(str(sssp.get("archive", ""))),
        sssp_archive_sha256=_digest(sssp.get("archive_sha256"), "sssp.archive_sha256"),
        max_structures=_integer(budget, "max_structures", 2, 20),
        max_atoms=_integer(budget, "max_atoms", 1, 1000),
        cutoff_multipliers=tuple(float(value) for value in multipliers),
        kpoint_cutoff_multiplier=float(kpoint_cutoff),
        kpoint_mesh=tuple(kpoints),
        scf_thresholds_ry=tuple(float(value) for value in scf),
        numerical_thresholds=thresholds,
        physics_review=dict(review),
    )


def _artifact_catalog(value: Any) -> dict[str, str]:
    catalog: dict[str, str] = {}

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            pairs = (("path", "sha256"), ("output_path", "output_sha256"))
            for path_key, hash_key in pairs:
                path = item.get(path_key)
                digest = item.get(hash_key)
                if isinstance(path, str) and isinstance(digest, str):
                    prior = catalog.get(digest)
                    if prior is not None and prior != path:
                        raise RuntimeError(
                            f"artifact hash maps to multiple paths: {digest}"
                        )
                    catalog[digest] = path
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return catalog


def _md5_bytes(value: bytes) -> str:
    return hashlib.md5(value, usedforsecurity=False).hexdigest()


def materialize_sssp_manifest(
    elements: set[str],
    *,
    index_path: Path,
    index_sha256: str,
    archive_path: Path,
    archive_sha256: str,
    output_dir: Path,
) -> tuple[dict[str, Any], Path]:
    """Extract only selected SSSP files and freeze their SHA-256 hashes."""
    if sha256_file(index_path) != index_sha256:
        raise RuntimeError("SSSP index hash mismatch")
    if sha256_file(archive_path) != archive_sha256:
        raise RuntimeError("SSSP archive hash mismatch")
    index = _read_json(index_path)
    missing = sorted(elements - index.keys())
    if missing:
        raise RuntimeError("SSSP has no entries for: " + ", ".join(missing))
    output_dir.mkdir(parents=True, exist_ok=True)
    records: dict[str, dict[str, Any]] = {}
    with tarfile.open(archive_path, mode="r:gz") as archive:
        members_by_name = {
            Path(member.name).name: member
            for member in archive.getmembers()
            if member.isfile()
        }
        for element in sorted(elements):
            source = index[element]
            filename = str(source["filename"])
            if Path(filename).name != filename or filename not in members_by_name:
                raise RuntimeError(f"unsafe or missing SSSP member for {element}")
            handle = archive.extractfile(members_by_name[filename])
            if handle is None:
                raise RuntimeError(f"cannot read SSSP member for {element}")
            content = handle.read()
            if _md5_bytes(content) != source["md5"]:
                raise RuntimeError(f"SSSP MD5 mismatch for {element}")
            target = output_dir / filename
            if target.is_file() and target.read_bytes() != content:
                raise RuntimeError(f"existing pseudopotential changed: {target}")
            if not target.exists():
                atomic_write_text(target, content.decode("utf-8"))
            records[element] = {
                "filename": filename,
                "md5": source["md5"],
                "sha256": sha256_bytes(content),
                "cutoff_wfc_ry": float(source["cutoff_wfc"]),
                "cutoff_rho_ry": float(source["cutoff_rho"]),
                "sssp_identifier": str(source["pseudopotential"]),
                "upstream_license": (
                    "Retained in the UPF header; local calculation use only"
                ),
            }
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "collection": "SSSP PBE Precision",
        "collection_version": "1.3.0",
        "exchange_correlation": "PBE",
        "source_index_path": str(index_path.resolve()),
        "source_index_sha256": index_sha256,
        "source_archive_path": str(archive_path.resolve()),
        "source_archive_sha256": archive_sha256,
        "elements": records,
    }
    manifest["manifest_fingerprint"] = fingerprint(manifest)
    manifest_path = output_dir.parent / "sssp-selected-manifest.json"
    atomic_write_json(manifest_path, manifest)
    return manifest, manifest_path


def _settings(
    maximum_wfc: float,
    maximum_rho: float,
    protocol: DFTConfirmationProtocol,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    base_scf = protocol.scf_thresholds_ry[0]
    for multiplier in protocol.cutoff_multipliers:
        rows.append(
            {
                "label": f"cutoff-{multiplier:.2f}".replace(".", "p"),
                "purpose": "pre-registered cutoff ladder",
                "ecutwfc_ry": maximum_wfc * multiplier,
                "ecutrho_ry": maximum_rho * multiplier,
                "kpoints": "gamma",
                "conv_thr_ry": base_scf,
                "electron_maxstep": 250,
                "mixing_mode": "plain",
                "mixing_beta": 0.3,
                "diagonalization": "david",
            }
        )
    kpoint_cutoff = protocol.kpoint_cutoff_multiplier
    kpoint_base = next(
        row
        for row in rows
        if math.isclose(
            float(row["ecutwfc_ry"]), maximum_wfc * kpoint_cutoff, abs_tol=1e-12
        )
    )
    rows.append(
        {
            **kpoint_base,
            "label": "kpoint-dense",
            "purpose": "pre-registered Gamma versus dense-mesh comparison",
            "kpoints": list(protocol.kpoint_mesh),
        }
    )
    rows.append(
        {
            **rows[-1],
            "label": "scf-tight",
            "purpose": "pre-registered SCF-threshold comparison",
            "ecutwfc_ry": maximum_wfc * kpoint_cutoff,
            "ecutrho_ry": maximum_rho * kpoint_cutoff,
            "conv_thr_ry": protocol.scf_thresholds_ry[-1],
        }
    )
    return rows


def prepare_discovery_dft(path: Path | str) -> dict[str, Any]:
    """Freeze a conservative numerical grid; never launch ``pw.x`` here."""
    from ase.io import read

    protocol = load_dft_confirmation_protocol(path)
    if not protocol.enabled:
        raise RuntimeError("DFT confirmation protocol is disabled")
    if len(protocol.selected_structures) > protocol.max_structures:
        raise RuntimeError("selected structure count exceeds DFT budget")
    for target, expected, label in (
        (protocol.qe_manifest, protocol.qe_manifest_sha256, "QE manifest"),
        (protocol.qe_lock, protocol.qe_lock_sha256, "QE lock"),
        (protocol.qe_executable, protocol.qe_executable_sha256, "pw.x"),
    ):
        if not target.is_file() or sha256_file(target) != expected:
            raise RuntimeError(f"{label} changed or vanished: {target}")
    source = _read_json(protocol.source_manifest)
    if (
        source.get("manifest_fingerprint")
        != protocol.approved_source_manifest_fingerprint
    ):
        raise RuntimeError("source manifest lacks the approved fingerprint")
    catalog = _artifact_catalog(source)
    snapshots: list[dict[str, Any]] = []
    all_elements: set[str] = set()
    for selected in protocol.selected_structures:
        digest = selected["artifact_sha256"]
        if digest not in catalog:
            raise RuntimeError(f"selected structure hash not found: {digest}")
        structure_path = Path(catalog[digest])
        if not structure_path.is_file() or sha256_file(structure_path) != digest:
            raise RuntimeError(f"selected structure changed: {structure_path}")
        atoms = read(structure_path)
        if len(atoms) > protocol.max_atoms:
            raise RuntimeError(
                f"selected structure exceeds atom budget: {structure_path}"
            )
        all_elements.update(atoms.get_chemical_symbols())
        snapshots.append(
            {
                "snapshot_id": selected["structure_id"],
                "snapshot_path": str(structure_path.resolve()),
                "snapshot_sha256": digest,
                "structure_fingerprint": atoms_fingerprint(atoms),
                "n_atoms": len(atoms),
                "scientific_role": selected["role"],
            }
        )
    snapshot_manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "selection_id": protocol.confirmation_id,
        "selection_protocol_path": str(protocol.protocol_path),
        "selection_protocol_sha256": protocol.protocol_sha256,
        "selection_is_label_blind": True,
        "n_snapshots": len(snapshots),
        "snapshots": snapshots,
    }
    snapshot_manifest["snapshot_set_fingerprint"] = fingerprint(snapshot_manifest)
    protocol.root_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = protocol.root_dir / "snapshot_manifest.json"
    atomic_write_json(snapshot_path, snapshot_manifest)
    pseudo_manifest, pseudo_manifest_path = materialize_sssp_manifest(
        all_elements,
        index_path=protocol.sssp_index,
        index_sha256=protocol.sssp_index_sha256,
        archive_path=protocol.sssp_archive,
        archive_sha256=protocol.sssp_archive_sha256,
        output_dir=protocol.root_dir / "pseudos" / "selected",
    )
    maximum_wfc = max(
        float(record["cutoff_wfc_ry"])
        for record in pseudo_manifest["elements"].values()
    )
    maximum_rho = max(
        float(record["cutoff_rho_ry"])
        for record in pseudo_manifest["elements"].values()
    )
    dft_protocol = {
        "schema_version": "1.0",
        "protocol_id": protocol.confirmation_id,
        "reference_code": "Quantum ESPRESSO 7.5 pw.x",
        "execution_environment": {
            "manifest": str(protocol.qe_manifest),
            "manifest_sha256": protocol.qe_manifest_sha256,
            "explicit_lock": str(protocol.qe_lock),
            "explicit_lock_sha256": protocol.qe_lock_sha256,
            "pw_executable_sha256": protocol.qe_executable_sha256,
            "omp_num_threads": 1,
        },
        "physics": protocol.physics_review,
        "calculations": _settings(maximum_wfc, maximum_rho, protocol),
        "numerical_acceptance": protocol.numerical_thresholds,
        "stop_rule": (
            "Do not run production DFT or interpret model errors unless adjacent "
            "cutoff, k-point, and SCF comparisons all pass the frozen thresholds."
        ),
    }
    dft_protocol_path = protocol.root_dir / "qe-protocol.json"
    atomic_write_json(dft_protocol_path, dft_protocol)
    qe_root = protocol.root_dir / "qe-inputs"
    if qe_root.exists():
        planning_manifest = _read_json(protocol.root_dir / "planning-manifest.json")
        if planning_manifest.get("protocol_sha256") != protocol.protocol_sha256:
            raise RuntimeError("existing DFT plan used a different protocol")
        return planning_manifest
    qe_campaign = prepare_qe_inputs(
        snapshot_path,
        dft_protocol_path,
        pseudo_manifest_path,
        pseudo_dir=protocol.root_dir / "pseudos" / "selected",
        out_dir=qe_root,
        qe_executable=protocol.qe_executable,
    )
    plan: dict[str, Any] = {
        "schema_version": "1.0",
        "manifest_kind": "discovery-dft-confirmation-plan",
        "confirmation_id": protocol.confirmation_id,
        "protocol_path": str(protocol.protocol_path),
        "protocol_sha256": protocol.protocol_sha256,
        "source_manifest_fingerprint": (protocol.approved_source_manifest_fingerprint),
        "snapshot_set_fingerprint": snapshot_manifest["snapshot_set_fingerprint"],
        "sssp_manifest_fingerprint": pseudo_manifest["manifest_fingerprint"],
        "qe_campaign_fingerprint": qe_campaign["campaign_fingerprint"],
        "n_structures": len(snapshots),
        "n_calculations_per_structure": len(dft_protocol["calculations"]),
        "execution_started": False,
        "publication_assessment": {
            "q1_claim_ready": False,
            "reason": "Inputs are prepared but no converged DFT result exists.",
        },
    }
    plan["manifest_fingerprint"] = fingerprint(plan)
    atomic_write_json(protocol.root_dir / "planning-manifest.json", plan)
    return plan


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol")
    parser.add_argument("--list", action="store_true", dest="list_only")
    args = parser.parse_args()
    protocol = load_dft_confirmation_protocol(args.protocol)
    if args.list_only:
        output = {
            "confirmation_id": protocol.confirmation_id,
            "enabled": protocol.enabled,
            "selected_structures": len(protocol.selected_structures),
            "max_structures": protocol.max_structures,
            "execution_policy": "prepare-only; pw.x is never launched by this command",
        }
    else:
        output = prepare_discovery_dft(protocol.protocol_path)
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
