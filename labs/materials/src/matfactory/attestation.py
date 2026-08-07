"""Create final test, environment, and clean-regeneration attestations."""

from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .provenance import (
    atomic_write_json,
    environment_versions,
    fingerprint,
    git_state,
    sha256_bytes,
    sha256_file,
)


_PASSED_RE = re.compile(r"(?:^|\s)(\d+) passed(?:,|\s)")


def _read_json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {source}")
    return payload


def _repo_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (Path(__file__).resolve().parents[2] / path).resolve()


def parse_pytest_pass_count(output: str) -> int:
    matches = [int(value) for value in _PASSED_RE.findall(output)]
    if not matches:
        raise ValueError("pytest output has no passed-test summary")
    return matches[-1]


def _write_attestation(path: Path | str, payload: dict[str, Any]) -> dict[str, Any]:
    destination = Path(path).resolve()
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite attestation: {destination}")
    payload["attestation_fingerprint"] = fingerprint(payload)
    atomic_write_json(destination, payload)
    return payload


def run_test_attestation(out_path: Path | str) -> dict[str, Any]:
    """Run the complete locked test suite and write a positive attestation only."""
    root = Path(__file__).resolve().parents[2]
    uv = shutil.which("uv")
    if uv is None:
        raise FileNotFoundError("uv")
    before = git_state(root)
    command = [uv, "run", "pytest", "-q"]
    completed = subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    combined = completed.stdout + completed.stderr
    if completed.returncode != 0:
        raise RuntimeError(
            f"test attestation aborted because pytest exited {completed.returncode}"
        )
    passed = parse_pytest_pass_count(combined)
    after = git_state(root)
    if before["dirty"] or after["dirty"]:
        raise RuntimeError("test attestation requires a clean tracked worktree")
    return _write_attestation(
        out_path,
        {
            "schema_version": "1.0",
            "attestation_kind": "full-pytest-suite",
            "command": "uv run pytest -q",
            "return_code": completed.returncode,
            "tests_passed": passed,
            "tests_failed": 0,
            "output_sha256": sha256_bytes(combined.encode("utf-8")),
            "summary_line": next(
                line.strip()
                for line in reversed(combined.splitlines())
                if " passed" in line
            ),
            "git_commit": after["commit"],
            "git_dirty": after["dirty"],
            "uv_lock_sha256": sha256_file(root / "uv.lock"),
            "implementation_path": str(Path(__file__).resolve()),
            "implementation_sha256": sha256_file(__file__),
        },
    )


def _audit_artifact_specification(
    audit_protocol: dict[str, Any], artifact_id: str
) -> dict[str, Any]:
    matches = [
        artifact
        for gate in audit_protocol["gates"]
        for artifact in gate["artifacts"]
        if artifact.get("artifact_id") == artifact_id
    ]
    if len(matches) != 1:
        raise ValueError(
            f"evidence audit contains {len(matches)} artifacts named {artifact_id}"
        )
    return matches[0]


def build_environment_attestation(
    audit_protocol_path: Path | str,
    *,
    qe_manifest_path: Path | str,
    formal_run_manifest_path: Path | str,
    out_path: Path | str,
) -> dict[str, Any]:
    """Verify locked Python/QE files, the QE binary, GPU runtime, and CHGNet weights."""
    root = Path(__file__).resolve().parents[2]
    audit_path = Path(audit_protocol_path).resolve()
    audit = _read_json(audit_path)
    qe_path = Path(qe_manifest_path).resolve()
    qe = _read_json(qe_path)
    formal_path = Path(formal_run_manifest_path).resolve()
    formal = _read_json(formal_path)
    python_lock = _audit_artifact_specification(audit, "python-lock")
    qe_lock = _audit_artifact_specification(audit, "qe-lock")
    python_lock_path = _repo_path(python_lock["path"])
    qe_lock_path = _repo_path(qe_lock["path"])
    executable = Path(qe["executable"]).resolve()
    model_expected = formal["config"]["expected_model_state_dict_sha256"]
    model_observed = formal["model"]["state_dict_sha256"]
    checks = {
        "python_lock": sha256_file(python_lock_path)
        == python_lock["expected_sha256"],
        "qe_lock_audit": sha256_file(qe_lock_path) == qe_lock["expected_sha256"],
        "qe_lock_manifest": sha256_file(qe_lock_path)
        == qe["explicit_lock_sha256"],
        "qe_executable": executable.is_file()
        and sha256_file(executable) == qe["executable_sha256"],
        "qe_version": qe.get("version") == "7.5",
        "mpi_version_recorded": bool(qe.get("mpi", {}).get("version")),
        "chgnet_model_hash": model_observed == model_expected,
        "formal_campaign_hash": formal["config"]["provenance"][
            "campaign_protocol_sha256"
        ]
        == sha256_file(root / "protocols/llzto_q1_v1.json"),
    }
    gpu: dict[str, Any] = {}
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi is not None:
        queried = subprocess.run(
            [
                nvidia_smi,
                "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        gpu = {
            "command": "nvidia-smi --query-gpu=name,driver_version,memory.total",
            "return_code": queried.returncode,
            "records": [line.strip() for line in queried.stdout.splitlines() if line.strip()],
        }
        checks["gpu_runtime"] = queried.returncode == 0 and bool(gpu["records"])
    else:
        checks["gpu_runtime"] = False
        gpu = {"error": "nvidia-smi not found"}
    try:
        import torch

        torch_runtime = {
            "version": torch.__version__,
            "cuda_available": torch.cuda.is_available(),
            "cuda_version": torch.version.cuda,
            "device_count": torch.cuda.device_count(),
        }
        checks["torch_cuda"] = bool(torch_runtime["cuda_available"])
    except ImportError as exc:
        torch_runtime = {"error": f"ImportError: {exc}"}
        checks["torch_cuda"] = False
    payload = {
        "schema_version": "1.0",
        "attestation_kind": "llzto-compute-environment",
        "environment_gate_pass": all(checks.values()),
        "checks": checks,
        "python_lock_path": str(python_lock_path),
        "python_lock_sha256": sha256_file(python_lock_path),
        "qe_lock_path": str(qe_lock_path),
        "qe_lock_sha256": sha256_file(qe_lock_path),
        "qe_manifest_path": str(qe_path),
        "qe_manifest_sha256": sha256_file(qe_path),
        "qe_executable_path": str(executable),
        "qe_executable_sha256": sha256_file(executable) if executable.is_file() else None,
        "formal_run_manifest_path": str(formal_path),
        "formal_run_manifest_sha256": sha256_file(formal_path),
        "chgnet_state_dict_sha256": model_observed,
        "gpu": gpu,
        "torch_runtime": torch_runtime,
        "versions": environment_versions(
            ("numpy", "scipy", "matplotlib", "ase", "chgnet", "torch", "pymatgen")
        ),
        "git_state": git_state(root),
        "audit_protocol_path": str(audit_path),
        "audit_protocol_sha256": sha256_file(audit_path),
        "implementation_path": str(Path(__file__).resolve()),
        "implementation_sha256": sha256_file(__file__),
    }
    if not payload["environment_gate_pass"]:
        failed = [name for name, passed in checks.items() if not passed]
        raise RuntimeError("environment attestation failed: " + ", ".join(failed))
    return _write_attestation(out_path, payload)


def _verify_manifest_outputs(manifest: dict[str, Any]) -> dict[str, str]:
    unsigned = dict(manifest)
    stored = unsigned.pop("manifest_fingerprint", None)
    if stored != fingerprint(unsigned):
        raise RuntimeError("publication artifact manifest fingerprint mismatch")
    outputs: dict[str, str] = {}
    for kind in ("figures", "tables"):
        for artifact in manifest[kind]:
            artifact_id = artifact[f"{kind[:-1]}_id"]
            for output in artifact["outputs"]:
                key = f"{kind}/{artifact_id}/{output['format']}"
                path = Path(output["path"]).resolve()
                actual = sha256_file(path)
                if actual != output["sha256"]:
                    raise RuntimeError(f"publication output hash mismatch: {path}")
                outputs[key] = actual
    for source in manifest["sources"]:
        path = Path(source["path"]).resolve()
        if sha256_file(path) != source["sha256"]:
            raise RuntimeError(f"publication source hash mismatch: {path}")
    return outputs


def compare_manifest_outputs(
    expected: dict[str, Any], regenerated: dict[str, Any]
) -> dict[str, Any]:
    """Compare logical output hashes while ignoring temporary absolute paths."""
    expected_hashes = _verify_manifest_outputs(expected)
    regenerated_hashes = _verify_manifest_outputs(regenerated)
    keys_match = set(expected_hashes) == set(regenerated_hashes)
    mismatches = {
        key: {
            "expected_sha256": expected_hashes.get(key),
            "regenerated_sha256": regenerated_hashes.get(key),
        }
        for key in sorted(set(expected_hashes) | set(regenerated_hashes))
        if expected_hashes.get(key) != regenerated_hashes.get(key)
    }
    return {
        "logical_output_keys_match": keys_match,
        "n_expected_outputs": len(expected_hashes),
        "n_regenerated_outputs": len(regenerated_hashes),
        "mismatches": mismatches,
        "all_hashes_match": bool(keys_match and not mismatches),
    }


def _verify_manuscript_manifest_outputs(manifest: dict[str, Any]) -> dict[str, str]:
    unsigned = dict(manifest)
    stored = unsigned.pop("manifest_fingerprint", None)
    if stored != fingerprint(unsigned):
        raise RuntimeError("manuscript manifest fingerprint mismatch")
    if manifest.get("manuscript_gate_pass") is not True:
        raise RuntimeError("manuscript manifest did not pass")
    protocol_path = Path(manifest["manuscript_protocol_path"]).resolve()
    if sha256_file(protocol_path) != manifest["manuscript_protocol_sha256"]:
        raise RuntimeError("manuscript protocol hash mismatch")
    publication_manifest_path = Path(manifest["publication_manifest_path"]).resolve()
    if sha256_file(publication_manifest_path) != manifest["publication_manifest_sha256"]:
        raise RuntimeError("linked publication manifest hash mismatch")
    outputs: dict[str, str] = {}
    for document in manifest["documents"]:
        document_id = str(document["document_id"])
        path = Path(document["path"]).resolve()
        actual = sha256_file(path)
        if actual != document["sha256"]:
            raise RuntimeError(f"manuscript output hash mismatch: {path}")
        outputs[f"documents/{document_id}"] = actual
    return outputs


def compare_manuscript_outputs(
    expected: dict[str, Any], regenerated: dict[str, Any]
) -> dict[str, Any]:
    """Compare manuscript bytes by logical document ID, independent of paths."""
    expected_hashes = _verify_manuscript_manifest_outputs(expected)
    regenerated_hashes = _verify_manuscript_manifest_outputs(regenerated)
    keys_match = set(expected_hashes) == set(regenerated_hashes)
    mismatches = {
        key: {
            "expected_sha256": expected_hashes.get(key),
            "regenerated_sha256": regenerated_hashes.get(key),
        }
        for key in sorted(set(expected_hashes) | set(regenerated_hashes))
        if expected_hashes.get(key) != regenerated_hashes.get(key)
    }
    return {
        "logical_output_keys_match": keys_match,
        "n_expected_outputs": len(expected_hashes),
        "n_regenerated_outputs": len(regenerated_hashes),
        "mismatches": mismatches,
        "all_hashes_match": bool(keys_match and not mismatches),
    }


def run_clean_regeneration_attestation(
    publication_protocol_path: Path | str,
    artifact_manifest_path: Path | str,
    *,
    manuscript_protocol_path: Path | str | None = None,
    manuscript_manifest_path: Path | str | None = None,
    out_path: Path | str,
) -> dict[str, Any]:
    """Rebuild figures/tables and, when supplied, manuscripts; compare bytes."""
    from .publication import build_publication_package

    if (manuscript_protocol_path is None) != (manuscript_manifest_path is None):
        raise ValueError(
            "manuscript protocol and manuscript manifest must be supplied together"
        )
    root = Path(__file__).resolve().parents[2]
    protocol_path = Path(publication_protocol_path).resolve()
    protocol = _read_json(protocol_path)
    original_manifest_path = Path(artifact_manifest_path).resolve()
    original_manifest = _read_json(original_manifest_path)
    _verify_manifest_outputs(original_manifest)
    original_manuscript_protocol_path = (
        Path(manuscript_protocol_path).resolve()
        if manuscript_protocol_path is not None
        else None
    )
    original_manuscript_manifest_path = (
        Path(manuscript_manifest_path).resolve()
        if manuscript_manifest_path is not None
        else None
    )
    original_manuscript_manifest = (
        _read_json(original_manuscript_manifest_path)
        if original_manuscript_manifest_path is not None
        else None
    )
    if original_manuscript_manifest is not None:
        _verify_manuscript_manifest_outputs(original_manuscript_manifest)
    state = git_state(root)
    if state["dirty"]:
        raise RuntimeError("clean regeneration requires a clean tracked worktree")
    with tempfile.TemporaryDirectory(prefix="matfactory-publication-regeneration-") as name:
        temporary_root = Path(name).resolve()
        regenerated_protocol = copy.deepcopy(protocol)
        regenerated_protocol["output"].update(
            root=str(temporary_root),
            figure_directory=str(temporary_root / "figures"),
            table_directory=str(temporary_root / "tables"),
            artifact_manifest=str(temporary_root / "artifact-manifest.json"),
        )
        temporary_protocol = temporary_root / "publication-protocol.json"
        atomic_write_json(temporary_protocol, regenerated_protocol)
        regenerated_manifest = build_publication_package(temporary_protocol)
        comparison = compare_manifest_outputs(original_manifest, regenerated_manifest)
        manuscript_comparison = None
        if original_manuscript_manifest is not None:
            from .manuscript import build_manuscript_package

            manuscript_protocol = _read_json(original_manuscript_protocol_path)
            regenerated_manuscript_protocol = copy.deepcopy(manuscript_protocol)
            regenerated_manuscript_protocol["output"].update(
                directory=str(temporary_root / "manuscript"),
                main=str(temporary_root / "manuscript/main.md"),
                supplement=str(temporary_root / "manuscript/supplement.md"),
                data_availability=str(
                    temporary_root / "manuscript/data_availability.md"
                ),
                manifest=str(temporary_root / "manuscript-manifest.json"),
            )
            temporary_manuscript_protocol = (
                temporary_root / "manuscript-protocol.json"
            )
            atomic_write_json(
                temporary_manuscript_protocol, regenerated_manuscript_protocol
            )
            regenerated_manuscript_manifest = build_manuscript_package(
                temporary_manuscript_protocol,
                publication_manifest_path_override=(
                    temporary_root / "artifact-manifest.json"
                ),
            )
            manuscript_comparison = compare_manuscript_outputs(
                original_manuscript_manifest, regenerated_manuscript_manifest
            )
    if not comparison["all_hashes_match"]:
        raise RuntimeError(
            "clean publication regeneration produced non-identical outputs: "
            + ", ".join(comparison["mismatches"])
        )
    if manuscript_comparison is not None and not manuscript_comparison[
        "all_hashes_match"
    ]:
        raise RuntimeError(
            "clean manuscript regeneration produced non-identical outputs: "
            + ", ".join(manuscript_comparison["mismatches"])
        )
    command = (
        "uv run python -m matfactory.attestation regenerate "
        "--publication-protocol analysis/protocols/llzto_publication_package_v1.json "
        "--manifest runs/analysis/publication-v1/artifact-manifest.json"
    )
    if manuscript_comparison is not None:
        command += (
            " --manuscript-protocol analysis/protocols/llzto_manuscript_v1.json "
            "--manuscript-manifest runs/analysis/publication-v1/manuscript-manifest.json"
        )
    manuscript_metadata = {}
    if original_manuscript_manifest_path is not None:
        manuscript_metadata = {
            "manuscript_protocol_path": str(original_manuscript_protocol_path),
            "manuscript_protocol_sha256": sha256_file(
                original_manuscript_protocol_path
            ),
            "manuscript_manifest_path": str(original_manuscript_manifest_path),
            "manuscript_manifest_sha256": sha256_file(
                original_manuscript_manifest_path
            ),
            "manuscript_comparison": manuscript_comparison,
        }
    return _write_attestation(
        out_path,
        {
            "schema_version": "1.0",
            "attestation_kind": (
                "clean-publication-and-manuscript-regeneration"
                if manuscript_comparison is not None
                else "clean-publication-regeneration"
            ),
            "publication_protocol_path": str(protocol_path),
            "publication_protocol_sha256": sha256_file(protocol_path),
            "artifact_manifest_path": str(original_manifest_path),
            "artifact_manifest_sha256": sha256_file(original_manifest_path),
            "command": command,
            "all_commands_exit_zero": True,
            "all_declared_artifact_hashes_verified": True,
            "comparison": comparison,
            **manuscript_metadata,
            "git_commit": state["commit"],
            "git_dirty": state["dirty"],
            "implementation_path": str(Path(__file__).resolve()),
            "implementation_sha256": sha256_file(__file__),
        },
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    tests = subparsers.add_parser("tests")
    tests.add_argument("--out", required=True)
    environment = subparsers.add_parser("environment")
    environment.add_argument("--audit-protocol", required=True)
    environment.add_argument("--qe-manifest", required=True)
    environment.add_argument("--formal-run-manifest", required=True)
    environment.add_argument("--out", required=True)
    regenerate = subparsers.add_parser("regenerate")
    regenerate.add_argument("--publication-protocol", required=True)
    regenerate.add_argument("--manifest", required=True)
    regenerate.add_argument("--manuscript-protocol")
    regenerate.add_argument("--manuscript-manifest")
    regenerate.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.command == "tests":
        result = run_test_attestation(args.out)
    elif args.command == "environment":
        result = build_environment_attestation(
            args.audit_protocol,
            qe_manifest_path=args.qe_manifest,
            formal_run_manifest_path=args.formal_run_manifest,
            out_path=args.out,
        )
    else:
        result = run_clean_regeneration_attestation(
            args.publication_protocol,
            args.manifest,
            manuscript_protocol_path=args.manuscript_protocol,
            manuscript_manifest_path=args.manuscript_manifest,
            out_path=args.out,
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
