"""Branch-aware environment and clean-regeneration attestations for LLZTO v2."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .attestation import (
    _verify_manifest_outputs,
    _verify_manuscript_manifest_outputs,
    compare_manifest_outputs,
    compare_manuscript_outputs,
)
from .provenance import (
    atomic_write_json,
    environment_versions,
    fingerprint,
    git_state,
    sha256_file,
)
from .research_manuscript import build_research_manuscript_package
from .research_publication import build_research_publication_package


_ROOT = Path(__file__).resolve().parents[2]


def _read_json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {source}")
    return payload


def _repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (_ROOT / path).resolve()


def _write_attestation(path: Path | str, payload: dict[str, Any]) -> dict[str, Any]:
    destination = Path(path).resolve()
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite research attestation: {destination}")
    payload["attestation_fingerprint"] = fingerprint(payload)
    atomic_write_json(destination, payload)
    return payload


def _audit_artifact(audit: dict[str, Any], artifact_id: str) -> dict[str, Any]:
    matches = [
        artifact
        for gate in audit["gates"]
        for artifact in gate.get("artifacts", [])
        if artifact.get("artifact_id") == artifact_id
    ]
    if len(matches) != 1:
        raise ValueError(
            f"research evidence audit contains {len(matches)} artifacts named {artifact_id}"
        )
    return matches[0]


def validate_formal_model_identity(
    formal_manifest: dict[str, Any],
    campaign_protocol: dict[str, Any],
    *,
    campaign_protocol_path: Path,
    branch: str,
) -> dict[str, bool]:
    """Validate campaign/model identity without assuming the universal protocol path."""
    config = formal_manifest.get("config", {})
    model = formal_manifest.get("model", {})
    expected_model = config.get("expected_model_state_dict_sha256")
    observed_model = model.get("state_dict_sha256")
    provenance = config.get("provenance", {})
    checks = {
        "model_state_dictionary": bool(expected_model)
        and observed_model == expected_model,
        "formal_campaign_protocol": provenance.get("campaign_protocol_sha256")
        == sha256_file(campaign_protocol_path),
        "campaign_protocol_materialized": isinstance(
            campaign_protocol.get("campaign_id"), str
        ),
    }
    if branch == "universal":
        checks["universal_model_name"] = config.get("model_name") == "CHGNet-default"
        checks["no_custom_model_artifact"] = (
            campaign_protocol.get("derived_model_artifact") is None
        )
    elif branch == "finetuned":
        artifact = campaign_protocol.get("derived_model_artifact")
        checks["fine_tuned_model_name"] = bool(config.get("model_name")) and config.get(
            "model_name"
        ) != "CHGNet-default"
        checks["custom_model_artifact_declared"] = isinstance(artifact, dict)
        checks["custom_state_dictionary"] = bool(
            isinstance(artifact, dict)
            and artifact.get("state_dict_sha256") == observed_model
        )
        if isinstance(artifact, dict):
            artifact_path = Path(artifact["path"]).resolve()
            report_path = Path(artifact["training_report_path"]).resolve()
            checks["custom_model_artifact_hash"] = bool(
                artifact_path.is_file()
                and sha256_file(artifact_path) == artifact.get("sha256")
            )
            checks["training_report_hash"] = bool(
                report_path.is_file()
                and sha256_file(report_path)
                == artifact.get("training_report_sha256")
            )
    else:
        raise ValueError("formal model branch must be universal or finetuned")
    return checks


def build_research_environment_attestation(
    audit_protocol_path: Path | str,
    *,
    qe_manifest_path: Path | str,
    formal_run_manifest_path: Path | str,
    formal_campaign_protocol_path: Path | str,
    branch: str,
    out_path: Path | str,
) -> dict[str, Any]:
    """Verify locks, QE/MPI/GPU, exact campaign protocol, and active model identity."""
    audit_path = Path(audit_protocol_path).resolve()
    qe_path = Path(qe_manifest_path).resolve()
    formal_path = Path(formal_run_manifest_path).resolve()
    campaign_path = Path(formal_campaign_protocol_path).resolve()
    audit = _read_json(audit_path)
    qe = _read_json(qe_path)
    formal = _read_json(formal_path)
    campaign = _read_json(campaign_path)
    python_lock = _audit_artifact(audit, "python-lock")
    qe_lock = _audit_artifact(audit, "qe-lock")
    python_lock_path = _repo_path(python_lock["path"])
    qe_lock_path = _repo_path(qe_lock["path"])
    executable = Path(qe["executable"]).resolve()
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
        **validate_formal_model_identity(
            formal,
            campaign,
            campaign_protocol_path=campaign_path,
            branch=branch,
        ),
    }
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi is None:
        gpu = {"error": "nvidia-smi not found"}
        checks["gpu_runtime"] = False
    else:
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
            "records": [
                line.strip() for line in queried.stdout.splitlines() if line.strip()
            ],
        }
        checks["gpu_runtime"] = queried.returncode == 0 and bool(gpu["records"])
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
        "attestation_kind": "llzto-research-compute-environment-v2",
        "branch": branch,
        "environment_gate_pass": all(checks.values()),
        "checks": checks,
        "python_lock_path": str(python_lock_path),
        "python_lock_sha256": sha256_file(python_lock_path),
        "qe_lock_path": str(qe_lock_path),
        "qe_lock_sha256": sha256_file(qe_lock_path),
        "qe_manifest_path": str(qe_path),
        "qe_manifest_sha256": sha256_file(qe_path),
        "qe_executable_path": str(executable),
        "qe_executable_sha256": (
            sha256_file(executable) if executable.is_file() else None
        ),
        "formal_run_manifest_path": str(formal_path),
        "formal_run_manifest_sha256": sha256_file(formal_path),
        "formal_campaign_protocol_path": str(campaign_path),
        "formal_campaign_protocol_sha256": sha256_file(campaign_path),
        "model_state_dict_sha256": formal["model"]["state_dict_sha256"],
        "gpu": gpu,
        "torch_runtime": torch_runtime,
        "versions": environment_versions(
            (
                "numpy",
                "scipy",
                "matplotlib",
                "ase",
                "chgnet",
                "torch",
                "pymatgen",
            )
        ),
        "git_state": git_state(_ROOT),
        "audit_protocol_path": str(audit_path),
        "audit_protocol_sha256": sha256_file(audit_path),
        "implementation_path": str(Path(__file__).resolve()),
        "implementation_sha256": sha256_file(__file__),
    }
    if not payload["environment_gate_pass"]:
        failed = [name for name, passed in checks.items() if not passed]
        raise RuntimeError("research environment attestation failed: " + ", ".join(failed))
    return _write_attestation(out_path, payload)


def run_research_clean_regeneration_attestation(
    publication_protocol_path: Path | str,
    artifact_manifest_path: Path | str,
    *,
    manuscript_protocol_path: Path | str,
    manuscript_manifest_path: Path | str,
    out_path: Path | str,
) -> dict[str, Any]:
    """Rebuild v2 figures, tables, and documents and compare logical bytes."""
    publication_path = Path(publication_protocol_path).resolve()
    artifact_path = Path(artifact_manifest_path).resolve()
    manuscript_path = Path(manuscript_protocol_path).resolve()
    manuscript_artifact_path = Path(manuscript_manifest_path).resolve()
    publication_protocol = _read_json(publication_path)
    manuscript_protocol = _read_json(manuscript_path)
    expected_publication = _read_json(artifact_path)
    expected_manuscript = _read_json(manuscript_artifact_path)
    _verify_manifest_outputs(expected_publication)
    _verify_manuscript_manifest_outputs(expected_manuscript)
    if expected_publication.get("manifest_gate_pass") is not True:
        raise RuntimeError("clean regeneration requires a passed publication manifest")
    if expected_manuscript.get("manuscript_gate_pass") is not True:
        raise RuntimeError("clean regeneration requires a passed manuscript manifest")
    state = git_state(_ROOT)
    if state["dirty"]:
        raise RuntimeError("research clean regeneration requires a clean tracked worktree")

    with tempfile.TemporaryDirectory(
        prefix="matfactory-research-regeneration-"
    ) as directory:
        temporary_root = Path(directory).resolve()
        regenerated_publication_protocol = copy.deepcopy(publication_protocol)
        regenerated_publication_protocol["output"].update(
            root=str(temporary_root / "publication"),
            figure_directory=str(temporary_root / "publication/figures"),
            table_directory=str(temporary_root / "publication/tables"),
            artifact_manifest=str(
                temporary_root / "publication/artifact-manifest.json"
            ),
        )
        temporary_publication_protocol = temporary_root / "publication-protocol.json"
        atomic_write_json(
            temporary_publication_protocol, regenerated_publication_protocol
        )
        regenerated_publication = build_research_publication_package(
            temporary_publication_protocol
        )
        publication_comparison = compare_manifest_outputs(
            expected_publication, regenerated_publication
        )

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
        temporary_manuscript_protocol = temporary_root / "manuscript-protocol.json"
        atomic_write_json(
            temporary_manuscript_protocol, regenerated_manuscript_protocol
        )
        regenerated_manuscript = build_research_manuscript_package(
            temporary_manuscript_protocol,
            publication_protocol_path_override=temporary_publication_protocol,
            publication_manifest_path_override=(
                temporary_root / "publication/artifact-manifest.json"
            ),
        )
        manuscript_comparison = compare_manuscript_outputs(
            expected_manuscript, regenerated_manuscript
        )
    if not publication_comparison["all_hashes_match"]:
        raise RuntimeError(
            "research publication regeneration produced non-identical outputs: "
            + ", ".join(publication_comparison["mismatches"])
        )
    if not manuscript_comparison["all_hashes_match"]:
        raise RuntimeError(
            "research manuscript regeneration produced non-identical outputs: "
            + ", ".join(manuscript_comparison["mismatches"])
        )
    command = (
        "uv run python -m matfactory.research_attestation regenerate "
        f"--publication-protocol {publication_path} --manifest {artifact_path} "
        f"--manuscript-protocol {manuscript_path} "
        f"--manuscript-manifest {manuscript_artifact_path} --out {Path(out_path).resolve()}"
    )
    return _write_attestation(
        out_path,
        {
            "schema_version": "1.0",
            "attestation_kind": (
                "clean-research-publication-and-manuscript-regeneration-v2"
            ),
            "branch": expected_publication["branch"],
            "publication_protocol_path": str(publication_path),
            "publication_protocol_sha256": sha256_file(publication_path),
            "artifact_manifest_path": str(artifact_path),
            "artifact_manifest_sha256": sha256_file(artifact_path),
            "manuscript_protocol_path": str(manuscript_path),
            "manuscript_protocol_sha256": sha256_file(manuscript_path),
            "manuscript_manifest_path": str(manuscript_artifact_path),
            "manuscript_manifest_sha256": sha256_file(manuscript_artifact_path),
            "command": command,
            "all_commands_exit_zero": True,
            "all_declared_artifact_hashes_verified": True,
            "comparison": publication_comparison,
            "manuscript_comparison": manuscript_comparison,
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
    environment = subparsers.add_parser("environment")
    environment.add_argument("--audit-protocol", required=True)
    environment.add_argument("--qe-manifest", required=True)
    environment.add_argument("--formal-run-manifest", required=True)
    environment.add_argument("--formal-campaign-protocol", required=True)
    environment.add_argument("--branch", choices=("universal", "finetuned"), required=True)
    environment.add_argument("--out", required=True)
    regenerate = subparsers.add_parser("regenerate")
    regenerate.add_argument("--publication-protocol", required=True)
    regenerate.add_argument("--manifest", required=True)
    regenerate.add_argument("--manuscript-protocol", required=True)
    regenerate.add_argument("--manuscript-manifest", required=True)
    regenerate.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.command == "environment":
        result = build_research_environment_attestation(
            args.audit_protocol,
            qe_manifest_path=args.qe_manifest,
            formal_run_manifest_path=args.formal_run_manifest,
            formal_campaign_protocol_path=args.formal_campaign_protocol,
            branch=args.branch,
            out_path=args.out,
        )
    else:
        result = run_research_clean_regeneration_attestation(
            args.publication_protocol,
            args.manifest,
            manuscript_protocol_path=args.manuscript_protocol,
            manuscript_manifest_path=args.manuscript_manifest,
            out_path=args.out,
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
