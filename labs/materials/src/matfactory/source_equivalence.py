"""Audit a source transition without changing an active scientific run."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .mlipmd import MDConfig, _load_structure, unwrap_trajectory
from .provenance import atomic_write_json, fingerprint, sha256_file
from .structures import structure_fingerprint
from .transport import estimate_transport


_ROOT = Path(__file__).resolve().parents[2]


def _read_json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {source}")
    return payload


def _repo_path(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (_ROOT / path).resolve()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git_output(*arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=_ROOT,
        check=True,
        capture_output=True,
    )
    return completed.stdout


def _assert_file_hash(path: Path, expected: str) -> None:
    observed = sha256_file(path)
    if observed != expected:
        raise RuntimeError(
            f"source-equivalence file hash mismatch: {path}; "
            f"expected {expected}, observed {observed}"
        )


def _verify_source_transition(
    protocol: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, Any]:
    baseline = protocol["baseline"]
    amendment = protocol["amendment"]
    baseline_commit = baseline["git_commit"]
    amendment_commit = amendment["git_commit"]
    if manifest.get("git", {}).get("commit") != baseline_commit:
        raise RuntimeError("formal run manifest does not identify the baseline commit")
    if manifest.get("git", {}).get("dirty") is not False:
        raise RuntimeError("formal run manifest baseline was not clean")

    subprocess.run(
        ["git", "merge-base", "--is-ancestor", baseline_commit, amendment_commit],
        cwd=_ROOT,
        check=True,
        capture_output=True,
    )
    manifest_sources = manifest.get("source_files", {})
    source_rows: list[dict[str, Any]] = []
    for relative_path in amendment["changed_files"]:
        baseline_sha = baseline["source_files"][relative_path]
        amendment_sha = amendment["source_files"][relative_path]
        if manifest_sources.get(relative_path) != baseline_sha:
            raise RuntimeError(
                f"run manifest source hash mismatch for {relative_path}"
            )
        baseline_blob = _git_output("show", f"{baseline_commit}:{relative_path}")
        amendment_blob = _git_output("show", f"{amendment_commit}:{relative_path}")
        if _sha256_bytes(baseline_blob) != baseline_sha:
            raise RuntimeError(f"baseline Git blob mismatch for {relative_path}")
        if _sha256_bytes(amendment_blob) != amendment_sha:
            raise RuntimeError(f"amendment Git blob mismatch for {relative_path}")
        current_path = _repo_path(relative_path)
        _assert_file_hash(current_path, amendment_sha)
        source_rows.append(
            {
                "path": relative_path,
                "baseline_sha256": baseline_sha,
                "amendment_sha256": amendment_sha,
                "current_sha256": amendment_sha,
            }
        )

    declared_paths = list(amendment["changed_files"])
    observed_paths = _git_output(
        "diff",
        "--name-only",
        f"{baseline_commit}..{amendment_commit}",
        "--",
        *declared_paths,
    ).decode("utf-8").splitlines()
    if observed_paths != declared_paths:
        raise RuntimeError(
            "source-equivalence changed-file set or order does not match protocol"
        )
    binary_diff = _git_output(
        "diff",
        "--binary",
        f"{baseline_commit}..{amendment_commit}",
        "--",
        *declared_paths,
    )
    binary_diff_sha = _sha256_bytes(binary_diff)
    if binary_diff_sha != amendment["binary_diff_sha256"]:
        raise RuntimeError("source-equivalence binary diff hash mismatch")
    return {
        "baseline_git_commit": baseline_commit,
        "amendment_git_commit": amendment_commit,
        "baseline_is_ancestor": True,
        "changed_files": observed_paths,
        "binary_diff_sha256": binary_diff_sha,
        "source_files": source_rows,
    }


def _verify_structure_preparation(
    protocol: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, Any]:
    from pymatgen.core import Structure

    reference = protocol["completed_reference"]
    stored_path = _repo_path(reference["prepared_structure"])
    _assert_file_hash(stored_path, reference["prepared_structure_sha256"])
    stored = Structure.from_dict(_read_json(stored_path))
    stored_fingerprint = structure_fingerprint(stored)
    if stored_fingerprint != reference["prepared_structure_fingerprint"]:
        raise RuntimeError("stored prepared-structure fingerprint mismatch")
    if manifest.get("prepared_structure_sha256") != stored_fingerprint:
        raise RuntimeError("run manifest prepared-structure fingerprint mismatch")

    config = MDConfig(**manifest["config"])
    current, metadata = _load_structure(config)
    current_fingerprint = structure_fingerprint(current)
    if current_fingerprint != stored_fingerprint:
        raise RuntimeError(
            "current raw-CIF structure preparation differs from the loaded baseline"
        )
    if metadata.get("prepared_structure_sha256") != stored_fingerprint:
        raise RuntimeError("current structure metadata fingerprint mismatch")
    if "derived_structure_provenance" in metadata:
        raise RuntimeError("raw-CIF formal input unexpectedly used derived provenance")
    return {
        "input_kind": "raw_cif",
        "stored_structure_sha256": reference["prepared_structure_sha256"],
        "stored_structure_fingerprint": stored_fingerprint,
        "current_structure_fingerprint": current_fingerprint,
        "exact_fingerprint_match": True,
        "derived_structure_provenance_branch_used": False,
    }


def _recompute_transport(
    protocol: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, Any]:
    from ase.io import Trajectory

    reference = protocol["completed_reference"]
    trajectory_path = _repo_path(reference["trajectory"])
    transport_path = _repo_path(reference["transport"])
    point_path = _repo_path(reference["point"])
    _assert_file_hash(trajectory_path, reference["trajectory_sha256"])
    _assert_file_hash(transport_path, reference["transport_sha256"])
    _assert_file_hash(point_path, reference["point_sha256"])

    frames = list(Trajectory(str(trajectory_path)))
    if len(frames) != int(reference["expected_frames"]):
        raise RuntimeError("source-equivalence trajectory frame count mismatch")
    config = manifest["config"]
    symbols = frames[0].get_chemical_symbols()
    mobile = [
        index
        for index, symbol in enumerate(symbols)
        if symbol == config["mobile_species"]
    ]
    framework = [
        index
        for index, symbol in enumerate(symbols)
        if symbol != config["mobile_species"]
    ]
    unwrapped = unwrap_trajectory(frames)
    current = estimate_transport(
        unwrapped[:, mobile],
        unwrapped[:, framework],
        frame_ps=config["loginterval"] * config["timestep_fs"] / 1000.0,
        framework_weights=frames[0].get_masses()[framework],
        n_blocks=config["uncertainty_blocks"],
        max_lags=config["max_lags"],
        fit_from_fraction=config["fit_from_fraction"],
        fit_to_fraction=config["fit_to_fraction"],
        min_final_msd_a2=config["min_final_msd_a2"],
        alpha_range=(
            config["min_diffusive_exponent"],
            config["max_diffusive_exponent"],
        ),
        max_relative_stderr=config["max_relative_diffusivity_stderr"],
    ).as_dict()
    baseline_payload = _read_json(transport_path)
    baseline = baseline_payload["transport"]
    current_legacy = copy.deepcopy(current)
    block_records = current_legacy.pop("block_estimates")
    if current_legacy != baseline:
        raise RuntimeError(
            "current transport implementation changed a legacy transport value"
        )
    expected_blocks = int(reference["expected_paired_blocks"])
    if len(block_records) != expected_blocks:
        raise RuntimeError("paired transport block count mismatch")
    tracer_blocks = baseline["tracer"]["block_diffusivities_cm2_s"]
    collective_blocks = baseline["collective"]["block_diffusivities_cm2_s"]
    if len(tracer_blocks) != expected_blocks or len(collective_blocks) != expected_blocks:
        raise RuntimeError("legacy transport block arrays are incomplete")
    paired_exact = all(
        row["block_index"] == index
        and row["tracer_diffusivity_cm2_s"] == tracer_blocks[index]
        and row["collective_diffusivity_cm2_s"] == collective_blocks[index]
        and row["tracer_fit_error"] is None
        and row["collective_fit_error"] is None
        for index, row in enumerate(block_records)
    )
    if not paired_exact:
        raise RuntimeError("explicit paired records differ from legacy block arrays")

    point = _read_json(point_path)["point"]
    point_checks = {
        "tracer_diffusivity": point["diffusivity_cm2_s"]
        == baseline["tracer"]["diffusivity_cm2_s"],
        "collective_diffusivity": point["collective_diffusivity_cm2_s"]
        == baseline["collective"]["diffusivity_cm2_s"],
        "ratio": point["collective_to_tracer_ratio"]
        == baseline["collective_to_tracer_ratio"],
        "tracer_resolved": point["resolved"] == baseline["resolved"],
        "collective_resolved": point["collective_resolved"]
        == baseline["collective_resolved"],
    }
    if not all(point_checks.values()):
        raise RuntimeError("immutable point identity differs from transport report")
    return {
        "temperature_k": reference["temperature_k"],
        "n_frames": len(frames),
        "legacy_tree_sha256": fingerprint(baseline),
        "current_legacy_tree_sha256": fingerprint(current_legacy),
        "all_legacy_transport_fields_exactly_equal": True,
        "maximum_absolute_legacy_numeric_difference": 0.0,
        "paired_block_count": len(block_records),
        "paired_records_reproduce_legacy_block_arrays": True,
        "point_identity_checks": point_checks,
        "point_identity_matches_transport": True,
        "legacy_pairing_is_recoverable_by_position": True,
    }


def build_source_equivalence_certificate(
    protocol_path: Path | str,
) -> dict[str, Any]:
    """Build a hash-bound certificate for the frozen source transition."""
    source = Path(protocol_path).resolve()
    protocol = _read_json(source)
    if protocol.get("protocol_id") != "llzto-source-equivalence-v1":
        raise ValueError("unsupported source-equivalence protocol")
    manifest_path = _repo_path(protocol["baseline"]["run_manifest"])
    _assert_file_hash(
        manifest_path, protocol["baseline"]["run_manifest_sha256"]
    )
    manifest = _read_json(manifest_path)
    transition = _verify_source_transition(protocol, manifest)
    structure = _verify_structure_preparation(protocol, manifest)
    transport = _recompute_transport(protocol, manifest)
    checks = {
        "baseline_git_commit_matches_run_manifest": True,
        "baseline_source_blobs_match_manifest": True,
        "current_source_blobs_match_amendment_commit": True,
        "changed_files_equal_declared_set": True,
        "binary_diff_hash_matches": True,
        "current_raw_cif_preparation_matches_stored_structure": True,
        "all_legacy_transport_fields_exactly_equal": True,
        "paired_records_reproduce_legacy_block_arrays": True,
        "point_identity_matches_transport": True,
    }
    if checks != protocol["acceptance"]:
        raise RuntimeError("source-equivalence acceptance declaration mismatch")
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "certificate_id": protocol["protocol_id"],
        "material": protocol["material"],
        "status": "pass",
        "equivalence_scope": "scientific values and gates; added provenance metadata retained",
        "protocol": {
            "path": str(source),
            "sha256": sha256_file(source),
        },
        "implementation": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256_file(Path(__file__)),
        },
        "source_transition": transition,
        "structure_preparation": structure,
        "transport_recomputation": transport,
        "evidence": {
            key: {
                "path": str(_repo_path(protocol["completed_reference"][key])),
                "sha256": protocol["completed_reference"][f"{key}_sha256"],
            }
            for key in ("trajectory", "transport", "point", "prepared_structure")
        },
        "checks": checks,
        "claim_boundary": protocol["claim_boundary"],
        "reproduction_command": protocol["reproduction_command"],
    }
    payload["certificate_fingerprint"] = fingerprint(payload)
    return payload


def verify_source_equivalence_certificate(
    protocol_path: Path | str, certificate_path: Path | str
) -> dict[str, Any]:
    """Verify a materialized certificate and all immutable input hashes."""
    protocol_source = Path(protocol_path).resolve()
    certificate_source = Path(certificate_path).resolve()
    protocol = _read_json(protocol_source)
    certificate = _read_json(certificate_source)
    fingerprint_value = certificate.pop("certificate_fingerprint", None)
    if fingerprint(certificate) != fingerprint_value:
        raise RuntimeError("source-equivalence certificate fingerprint mismatch")
    certificate["certificate_fingerprint"] = fingerprint_value
    if certificate.get("status") != "pass":
        raise RuntimeError("source-equivalence certificate did not pass")
    if certificate.get("protocol", {}).get("sha256") != sha256_file(protocol_source):
        raise RuntimeError("source-equivalence protocol hash mismatch")
    if certificate.get("implementation", {}).get("sha256") != sha256_file(
        Path(__file__)
    ):
        raise RuntimeError("source-equivalence implementation hash mismatch")
    manifest_path = _repo_path(protocol["baseline"]["run_manifest"])
    _assert_file_hash(
        manifest_path, protocol["baseline"]["run_manifest_sha256"]
    )
    transition = _verify_source_transition(protocol, _read_json(manifest_path))
    if certificate.get("source_transition") != transition:
        raise RuntimeError("source-equivalence transition evidence mismatch")
    for key in ("trajectory", "transport", "point", "prepared_structure"):
        specification = protocol["completed_reference"]
        _assert_file_hash(
            _repo_path(specification[key]), specification[f"{key}_sha256"]
        )
    if not all(certificate.get("checks", {}).values()):
        raise RuntimeError("source-equivalence certificate contains a failed check")
    return certificate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    payload = build_source_equivalence_certificate(args.protocol)
    output = Path(args.output).resolve()
    atomic_write_json(output, payload)
    verify_source_equivalence_certificate(args.protocol, output)
    print(output)


if __name__ == "__main__":
    main()
