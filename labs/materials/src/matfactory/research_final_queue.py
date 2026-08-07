"""Persistent branch-aware LLZTO publication, attestation, audit, and readiness queue."""

from __future__ import annotations

import copy
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from .attestation import (
    _verify_manifest_outputs,
    _verify_manuscript_manifest_outputs,
    run_test_attestation,
)
from .evidence_audit import build_evidence_audit, validate_exclusion_ledger
from .mechanism_queue import acquire_analysis_lock, release_analysis_lock
from .provenance import atomic_write_json, fingerprint, sha256_file
from .research_attestation import (
    build_research_environment_attestation,
    run_research_clean_regeneration_attestation,
)
from .research_manuscript import build_research_manuscript_package
from .research_publication import build_research_publication_package
from .research_readiness import build_research_readiness_assessment


_ROOT = Path(__file__).resolve().parents[2]
_TERMINAL_PREFIXES = ("failed", "blocked")


def _read_json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {source}")
    return payload


def _repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (_ROOT / path).resolve()


def _write_or_verify(path: Path, payload: dict[str, Any], label: str) -> Path:
    if path.exists():
        if _read_json(path) != payload:
            raise RuntimeError(f"stored {label} differs from deterministic derivation: {path}")
    else:
        atomic_write_json(path, payload)
    return path


def _verify_fingerprint(payload: dict[str, Any], field: str, label: str) -> None:
    unsigned = dict(payload)
    stored = unsigned.pop(field, None)
    if stored != fingerprint(unsigned):
        raise RuntimeError(f"{label} fingerprint mismatch")


def _provenance_amendments(protocol: dict[str, Any]) -> list[dict[str, Any]]:
    """Return versioned G0-only amendments in their frozen declaration order."""
    return [
        amendment
        for key in (
            "numerical_resource_amendment",
            "source_equivalence_amendment",
        )
        if isinstance((amendment := protocol.get(key)), dict)
    ]


def validate_research_final_protocol(
    path: Path | str,
) -> tuple[dict[str, Any], Path]:
    """Verify all frozen templates and the single branch-selection upstream."""
    source = Path(path).resolve()
    protocol = _read_json(source)
    if protocol.get("schema_version") != "1.0":
        raise ValueError("research publication supervisor schema_version must be '1.0'")
    protocol_id = protocol.get("protocol_id")
    if protocol_id not in {
        "llzto-research-publication-supervisor-v2",
        "llzto-research-publication-supervisor-v3",
        "llzto-research-publication-supervisor-v4",
    }:
        raise ValueError("unexpected research publication supervisor protocol id")
    declared = [
        (
            protocol["upstream"]["protocol"],
            protocol["upstream"]["protocol_sha256"],
        ),
        *[
            (row["path"], row["sha256"])
            for row in protocol["templates"].values()
        ],
        (
            protocol["environment"]["qe_manifest"],
            protocol["environment"]["qe_manifest_sha256"],
        ),
        (
            protocol["environment"]["python_lock"],
            protocol["environment"]["python_lock_sha256"],
        ),
        (
            protocol["environment"]["qe_lock"],
            protocol["environment"]["qe_lock_sha256"],
        ),
    ]
    numerical_amendment = protocol.get("numerical_resource_amendment")
    if protocol_id.endswith(("-v3", "-v4")) and (
        not isinstance(numerical_amendment, dict)
        or not numerical_amendment.get("artifacts")
    ):
        raise ValueError(
            "v3/v4 publication supervisor requires resource-amendment evidence"
        )
    source_amendment = protocol.get("source_equivalence_amendment")
    if protocol_id.endswith("-v4") and (
        not isinstance(source_amendment, dict)
        or not source_amendment.get("artifacts")
    ):
        raise ValueError(
            "v4 publication supervisor requires source-equivalence evidence"
        )
    for amendment in _provenance_amendments(protocol):
        declared.extend(
            (row["path"], row["sha256"]) for row in amendment["artifacts"]
        )
    for value, expected in declared:
        candidate = _repo_path(value)
        if sha256_file(candidate) != expected:
            raise RuntimeError(f"research final declared hash mismatch: {candidate}")
    if set(protocol["branches"]) != {"universal", "finetuned"}:
        raise ValueError("research final supervisor requires exactly two model branches")
    if int(protocol["environment"]["minimum_tests_passed"]) < 300:
        raise ValueError("research final test floor is unexpectedly low")
    return protocol, source


def _inspect_analysis_upstream(protocol: dict[str, Any]) -> dict[str, Any]:
    specification = protocol["upstream"]
    path = _repo_path(specification["state"])
    if not path.is_file():
        return {"status": "waiting", "reason": "analysis-state-missing", "path": str(path)}
    payload = _read_json(path)
    observed_protocol = payload.get("config", {}).get("protocol_sha256")
    if observed_protocol != specification["protocol_sha256"]:
        return {
            "status": "blocked",
            "reason": "analysis-protocol-hash-mismatch",
            "path": str(path),
            "expected": specification["protocol_sha256"],
            "observed": observed_protocol,
        }
    status = str(payload.get("status", ""))
    if status == "complete":
        branch = payload.get("active_branch")
        manifest_path = Path(str(payload.get("analysis_manifest_path", ""))).resolve()
        if (
            payload.get("disposition") != specification["complete_disposition"]
            or branch not in {"universal", "finetuned"}
            or not manifest_path.is_file()
            or sha256_file(manifest_path) != payload.get("analysis_manifest_sha256")
        ):
            return {
                "status": "blocked",
                "reason": "analysis-complete-state-invalid",
                "path": str(path),
            }
        manifest = _read_json(manifest_path)
        _verify_fingerprint(manifest, "manifest_fingerprint", "research analysis manifest")
        if (
            manifest.get("branch") != branch
            or manifest.get("model_branch_isolation") is not True
            or manifest.get("analysis_completeness_gate_pass") is not True
        ):
            return {
                "status": "blocked",
                "reason": "analysis-manifest-not-released",
                "path": str(manifest_path),
            }
        return {
            "status": "ready",
            "branch": branch,
            "state_path": str(path),
            "state_sha256": sha256_file(path),
            "analysis_manifest_path": str(manifest_path),
            "analysis_manifest_sha256": sha256_file(manifest_path),
        }
    if status.startswith(_TERMINAL_PREFIXES):
        return {
            "status": "blocked",
            "reason": "analysis-upstream-terminal",
            "path": str(path),
            "upstream_status": status,
        }
    return {
        "status": "waiting",
        "reason": "analysis-upstream-incomplete",
        "path": str(path),
        "upstream_status": status or "missing-status",
    }


def _formatted_path(protocol: dict[str, Any], name: str, branch: str) -> Path:
    return _repo_path(protocol["paths"][name].format(branch=branch))


def _artifact_if_file(value: str | Path) -> list[dict[str, str]]:
    path = _repo_path(value)
    if not path.is_file():
        return []
    return [{"path": str(path), "sha256": sha256_file(path)}]


def derive_branch_exclusion_ledger(
    supervisor_protocol: dict[str, Any], branch: str
) -> Path:
    template_path = _repo_path(
        supervisor_protocol["templates"]["exclusion_ledger"]["path"]
    )
    ledger = copy.deepcopy(_read_json(template_path))
    ledger["ledger_id"] = f"llzto-research-exclusions-v2-{branch}"
    ledger["branch"] = branch
    ledger["rule"] = (
        "All excluded, interrupted, development-only, superseded, cross-model, and "
        "retained-negative artifacts remain visible. Complete physical non-equivalence, "
        "null association, and experimental incompatibility remain scientific outcomes."
    )
    if branch == "finetuned":
        config = supervisor_protocol["branches"][branch]
        ledger["entries"].extend(
            [
                {
                    "entry_id": "universal-domain-failure-triggered-finetuning",
                    "disposition": "retained_negative_result",
                    "scope": "model selection and universal-model publication claims",
                    "reason": "The frozen universal CHGNet domain route failed before release. The failure triggered, but was not erased by, the separately versioned outcome-blind fine-tuning contingency.",
                    "identifiers": {
                        "universal_model_formal_claim_eligible": False,
                        "trigger_rule_frozen_before_outcome": True,
                    },
                    "artifacts": _artifact_if_file(config["universal_domain_state"]),
                },
                {
                    "entry_id": "universal-model-trajectories-excluded-from-finetuned-estimators",
                    "disposition": "cross_model_excluded",
                    "scope": "all fine-tuned transport, mechanism, sensitivity, and publication estimators",
                    "reason": "Every universal-model trajectory belongs to a different potential surface. Fine-tuned results were rerun in full and no universal trajectory is pooled or substituted.",
                    "identifiers": {
                        "excluded_campaign_roots": [
                            "runs/campaigns/llzto_q1_v1",
                            "runs/campaigns/llzto_q1_ensemble_nve_matched_v1",
                        ],
                        "model_branch_isolation": True,
                    },
                    "artifacts": [],
                },
                {
                    "entry_id": "universal-heldout-not-finetuned-publication-test",
                    "disposition": "retained_negative_or_diagnostic_result",
                    "scope": "fine-tuned training and final publication-domain authorization",
                    "reason": "The universal-model heldout outcome is retained but is neither training data nor the fresh heldout test for the fine-tuned model.",
                    "identifiers": {
                        "set_id": "publication-heldout",
                        "fine_tuned_training_eligible": False,
                        "fine_tuned_publication_test_eligible": False,
                    },
                    "artifacts": _artifact_if_file(config["universal_heldout_report"]),
                },
                {
                    "entry_id": "fine-tuning-labels-development-only",
                    "disposition": "development_and_training_only",
                    "scope": "fresh fine-tuned publication-domain test",
                    "reason": "All 62 fine-tuning labels are development data. None is counted among the fresh 30-snapshot publication-heldout set, and none is a formal transport trajectory.",
                    "identifiers": {
                        "training_records": 62,
                        "fresh_publication_records": 30,
                        "formal_transport_eligible": False,
                    },
                    "artifacts": _artifact_if_file(config["training_report"]),
                },
            ]
        )
    root = _formatted_path(
        supervisor_protocol, "derived_protocol_root_template", branch
    )
    path = root / "exclusion-ledger.json"
    _write_or_verify(path, ledger, "branch exclusion ledger")
    validation = validate_exclusion_ledger(ledger, ledger_path=path)
    if not validation["ledger_gate_pass"]:
        raise RuntimeError("derived branch exclusion ledger failed validation")
    return path


def _analysis_source_paths(
    supervisor_protocol: dict[str, Any], branch: str
) -> dict[str, Path]:
    root = _formatted_path(supervisor_protocol, "analysis_root_template", branch)
    return {
        "campaign_report": root / "campaign-report.json",
        "hierarchical_transport": root / "hierarchical-transport.json",
        "nested_velocity": root / "nested-velocity.json",
        "transport_sensitivity": root / "transport-sensitivity.json",
        "mechanism_association": root / "mechanism-transport-association.json",
        "experimental_validation": root
        / "hierarchical-experimental-validation.json",
        "ensemble_sensitivity": root / "ensemble-sensitivity.json",
        "mechanism_temperature_robustness": root
        / "mechanism-temperature-robustness.json",
        "haven_validation": root / "haven-convention-validation.json",
        "analysis_manifest": root / "analysis-manifest.json",
    }


def derive_branch_publication_protocol(
    supervisor_protocol: dict[str, Any],
    branch: str,
    *,
    exclusion_ledger_path: Path,
) -> Path:
    template_path = _repo_path(
        supervisor_protocol["templates"]["publication"]["path"]
    )
    protocol = copy.deepcopy(_read_json(template_path))
    branch_config = supervisor_protocol["branches"][branch]
    analysis = _analysis_source_paths(supervisor_protocol, branch)
    derived_root = _formatted_path(
        supervisor_protocol, "derived_protocol_root_template", branch
    )
    audit_protocol_path = derived_root / "evidence-audit-protocol.json"
    publication_root = _formatted_path(
        supervisor_protocol, "publication_root_template", branch
    )
    protocol.update(
        protocol_id=f"llzto-research-publication-package-v2-{branch}",
        branch=branch,
        preregistration_note=supervisor_protocol["preregistration_note"],
        claim_boundary=(
            "All sources are hash-verified and belong to exactly one model branch. "
            "Missing, unresolved, provenance-invalid, or numerically unstable inputs "
            "block the package; complete non-equivalence, null association, or "
            "experimental incompatibility is retained and narrows the claim."
        ),
    )
    base_sources = protocol["sources"]
    protocol["sources"] = {
        "campaign_root": branch_config["formal_campaign_root"],
        "campaign_report": str(analysis["campaign_report"]),
        "cutoff_decision": base_sources["cutoff_decision"],
        "kpoint_decision": base_sources["kpoint_decision"],
        "scf_decision": base_sources["scf_decision"],
        "mpi_report": base_sources["mpi_report"],
        "g2_release": branch_config["g2_release"],
        "hierarchical_transport": str(analysis["hierarchical_transport"]),
        "nested_velocity": str(analysis["nested_velocity"]),
        "transport_sensitivity": str(analysis["transport_sensitivity"]),
        "mechanism_root": branch_config["mechanism_root"],
        "mechanism_association": str(analysis["mechanism_association"]),
        "experimental_validation": str(analysis["experimental_validation"]),
        "ensemble_sensitivity": str(analysis["ensemble_sensitivity"]),
        "mechanism_temperature_robustness": str(
            analysis["mechanism_temperature_robustness"]
        ),
        "haven_validation": str(analysis["haven_validation"]),
        "analysis_manifest": str(analysis["analysis_manifest"]),
        "exclusion_ledger": str(exclusion_ledger_path),
        "evidence_audit_protocol": str(audit_protocol_path),
    }
    protocol["domain_gate"] = {
        "gate_id": branch_config["g2_release_id"],
        "evidence": copy.deepcopy(branch_config["domain_evidence"]),
    }
    protocol["output"] = {
        "root": str(publication_root),
        "figure_directory": str(publication_root / "figures"),
        "table_directory": str(publication_root / "tables"),
        "artifact_manifest": str(publication_root / "artifact-manifest.json"),
        "figure_formats": ["svg", "pdf", "png"],
        "table_formats": ["csv", "json"],
        "png_dpi": 300,
    }
    extra_figures = [
        {
            "figure_id": "fig10-production-ensemble",
            "title": "Matched 500 ps NVE/NVT production-ensemble sensitivity",
            "required_content": "tracer, collective, and ratio equivalence intervals plus NVE stability diagnostics",
        },
        {
            "figure_id": "fig11-temperature-robustness",
            "title": "Mechanism associations under categorical-temperature adjustment",
            "required_content": "all twelve primary associations retained, downgraded, or null after the frozen robustness audit",
        },
        {
            "figure_id": "fig12-haven-convention",
            "title": "Explicit reciprocal Haven convention and experimental comparison",
            "required_content": "trajectory R_sigma, hierarchical extrapolation, H_R reciprocal mapping, and compatibility disposition",
        },
    ]
    extra_tables = [
        {
            "table_id": "table10-production-ensemble",
            "title": "Matched NVE/NVT effects and NVE stability diagnostics",
        },
        {
            "table_id": "table11-temperature-robustness",
            "title": "All categorical-temperature mechanism robustness outcomes",
        },
        {
            "table_id": "table12-haven-convention",
            "title": "Trajectory and experimental Haven-convention validation",
        },
    ]
    protocol["figures"] = [*protocol["figures"], *extra_figures]
    protocol["tables"] = [*protocol["tables"], *extra_tables]
    protocol["hard_rules"].update(
        model_branch_isolation_required=True,
        complete_negative_results_retained=True,
        twelve_figures_and_tables_required=True,
        scientific_non_equivalence_does_not_fake_incompleteness=True,
    )
    path = derived_root / "publication-protocol.json"
    return _write_or_verify(path, protocol, "branch publication protocol")


def derive_branch_manuscript_protocol(
    supervisor_protocol: dict[str, Any],
    branch: str,
    *,
    publication_protocol_path: Path,
) -> Path:
    template_path = _repo_path(
        supervisor_protocol["templates"]["manuscript"]["path"]
    )
    template = _read_json(template_path)
    branch_config = supervisor_protocol["branches"][branch]
    publication_root = _formatted_path(
        supervisor_protocol, "publication_root_template", branch
    )
    manuscript_root = _formatted_path(
        supervisor_protocol, "manuscript_root_template", branch
    )
    derived_root = _formatted_path(
        supervisor_protocol, "derived_protocol_root_template", branch
    )
    output = {
        "directory": str(manuscript_root),
        "main": str(manuscript_root / "main.md"),
        "supplement": str(manuscript_root / "supplement.md"),
        "data_availability": str(manuscript_root / "data_availability.md"),
        "manifest": str(publication_root / "manuscript-manifest.json"),
    }
    protocol: dict[str, Any] = {
        "schema_version": "1.0",
        "protocol_id": f"llzto-research-manuscript-v2-{branch}",
        "material": supervisor_protocol["material"],
        "branch": branch,
        "language": "English",
        "preregistration_note": supervisor_protocol["preregistration_note"],
        "claim_boundary": supervisor_protocol["claim_boundary"],
        "sources": {
            "publication_protocol": str(publication_protocol_path),
            "publication_protocol_sha256": sha256_file(publication_protocol_path),
            "publication_manifest": str(
                publication_root / "artifact-manifest.json"
            ),
        },
        "output": output,
        "documents": {
            "main": {
                "minimum_bytes": 18000,
                "required_sections": [
                    "Abstract",
                    "Introduction",
                    "Methods",
                    "Results",
                    "Discussion",
                    "Conclusions",
                    "Data and code availability",
                    "References",
                ],
            },
            "supplement": {
                "minimum_bytes": 18000,
                "required_sections": [
                    "Supplementary methods",
                    "Numerical convergence",
                    "Potential-domain validation",
                    "All formal transport points",
                    "Hierarchical transport inference",
                    "Replication, finite-size, volume, and ensemble sensitivity",
                    "Mechanism descriptors and associations",
                    "Categorical-temperature robustness",
                    "Haven convention and experimental comparisons",
                    "Exclusions and retained negative results",
                    "Artifact inventory",
                ],
            },
            "data_availability": {
                "minimum_bytes": 2200,
                "required_sections": [
                    "Data availability",
                    "Code and computational environment",
                    "Reproduction commands",
                    "Licensing boundary",
                ],
            },
        },
        "model_branch": copy.deepcopy(branch_config["model_branch"]),
        "study_parameters": copy.deepcopy(template["study_parameters"]),
        "references": copy.deepcopy(template["references"]),
        "canonical_locations": {
            "tables": str(publication_root / "tables"),
            "figures": str(publication_root / "figures"),
            "formal_campaign": branch_config["formal_campaign_root"],
            "mechanisms": branch_config["mechanism_root"],
            "publication_manifest": str(
                publication_root / "artifact-manifest.json"
            ),
            "manuscript_manifest": str(
                publication_root / "manuscript-manifest.json"
            ),
            "evidence_audit": str(publication_root / "evidence-audit.json"),
            "readiness": str(publication_root / "readiness-assessment.json"),
        },
        "reproduction_commands": [
            (
                "uv run python -m matfactory.research_publication --protocol "
                + str(publication_protocol_path)
            ),
            (
                "uv run python -m matfactory.research_manuscript --protocol "
                + str(derived_root / "manuscript-protocol.json")
            ),
            "uv run pytest -q",
            (
                "uv run python -m matfactory.research_final_queue --protocol "
                "analysis/protocols/llzto_research_publication_supervisor_v2.json "
                "--state runs/supervisor/research-publication-supervisor-v2.json"
            ),
        ],
        "generation_command": (
            "uv run python -m matfactory.research_manuscript --protocol "
            + str(derived_root / "manuscript-protocol.json")
        ),
        "hard_rules": {
            "publication_manifest_must_pass_and_verify": True,
            "all_twelve_tables_are_the_only_numerical_narrative_source": True,
            "all_twelve_figures_and_tables_must_be_cited": True,
            "negative_and_incompatible_outcomes_must_be_stated": True,
            "universal_and_finetuned_branches_must_not_be_pooled": True,
            "mechanism_language_must_remain_noncausal": True,
            "room_temperature_predictions_must_be_called_extrapolations": True,
            "overwrite_forbidden": True,
            "manifest_written_last": True,
        },
        "prohibited_tokens": copy.deepcopy(template["prohibited_tokens"]),
    }
    path = derived_root / "manuscript-protocol.json"
    return _write_or_verify(path, protocol, "branch manuscript protocol")


def _assertion(path: str, operator: str, value: Any | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"json_path": path, "operator": operator}
    if value is not None:
        row["value"] = value
    return row


def _artifact(
    artifact_id: str,
    path: str | Path,
    *,
    artifact_format: str = "json",
    expected_sha256: str | None = None,
    fingerprint_field: str | None = None,
    assertions: list[dict[str, Any]] | None = None,
    minimum_bytes: int | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "artifact_id": artifact_id,
        "path": str(path),
        "format": artifact_format,
    }
    if expected_sha256 is not None:
        row["expected_sha256"] = expected_sha256
    if fingerprint_field is not None:
        row["fingerprint_field"] = fingerprint_field
    if assertions:
        row["assertions"] = assertions
    if minimum_bytes is not None:
        row["minimum_bytes"] = minimum_bytes
    return row


def derive_branch_evidence_audit_protocol(
    supervisor_protocol: dict[str, Any],
    supervisor_protocol_path: Path,
    branch: str,
    *,
    publication_protocol_path: Path,
    manuscript_protocol_path: Path,
    exclusion_ledger_path: Path,
) -> Path:
    branch_config = supervisor_protocol["branches"][branch]
    environment = supervisor_protocol["environment"]
    analysis = _analysis_source_paths(supervisor_protocol, branch)
    publication_root = _formatted_path(
        supervisor_protocol, "publication_root_template", branch
    )
    derived_root = _formatted_path(
        supervisor_protocol, "derived_protocol_root_template", branch
    )
    test_attestation = publication_root / "test-attestation.json"
    environment_attestation = publication_root / "environment-attestation.json"
    regeneration = publication_root / "clean-regeneration-attestation.json"
    publication_manifest = publication_root / "artifact-manifest.json"
    manuscript_manifest = publication_root / "manuscript-manifest.json"
    gates: list[dict[str, Any]] = []
    g0 = [
        _artifact(
            "python-lock",
            environment["python_lock"],
            artifact_format="file",
            expected_sha256=environment["python_lock_sha256"],
            minimum_bytes=1000,
        ),
        _artifact(
            "qe-lock",
            environment["qe_lock"],
            artifact_format="file",
            expected_sha256=environment["qe_lock_sha256"],
            minimum_bytes=100,
        ),
        _artifact(
            "research-publication-supervisor-protocol",
            supervisor_protocol_path,
            artifact_format="file",
            expected_sha256=sha256_file(supervisor_protocol_path),
        ),
        _artifact(
            "research-analysis-supervisor-protocol",
            supervisor_protocol["upstream"]["protocol"],
            artifact_format="file",
            expected_sha256=supervisor_protocol["upstream"]["protocol_sha256"],
        ),
        _artifact(
            "formal-campaign-protocol",
            branch_config["formal_campaign_protocol"],
            artifact_format="file",
            expected_sha256=sha256_file(
                _repo_path(branch_config["formal_campaign_protocol"])
            ),
        ),
        _artifact(
            "publication-protocol",
            publication_protocol_path,
            artifact_format="file",
            expected_sha256=sha256_file(publication_protocol_path),
        ),
        _artifact(
            "manuscript-protocol",
            manuscript_protocol_path,
            artifact_format="file",
            expected_sha256=sha256_file(manuscript_protocol_path),
        ),
        _artifact(
            "exclusion-ledger",
            exclusion_ledger_path,
            artifact_format="exclusion_ledger",
            expected_sha256=sha256_file(exclusion_ledger_path),
            assertions=[
                _assertion("schema_version", "equals", "1.0"),
                _assertion("entries", "length_at_least", 10),
            ],
        ),
        _artifact(
            "test-attestation",
            test_attestation,
            fingerprint_field="attestation_fingerprint",
            assertions=[
                _assertion("tests_failed", "equals", 0),
                _assertion(
                    "tests_passed",
                    "at_least",
                    environment["minimum_tests_passed"],
                ),
                _assertion("git_dirty", "is_false"),
            ],
        ),
        _artifact(
            "environment-attestation",
            environment_attestation,
            fingerprint_field="attestation_fingerprint",
            assertions=[
                _assertion("branch", "equals", branch),
                _assertion("environment_gate_pass", "is_true"),
            ],
        ),
    ]
    numerical_amendment = supervisor_protocol.get("numerical_resource_amendment")
    for amendment in _provenance_amendments(supervisor_protocol):
        g0.extend(
            _artifact(
                row["artifact_id"],
                row["path"],
                artifact_format=row.get("format", "file"),
                expected_sha256=row["sha256"],
                fingerprint_field=row.get("fingerprint_field"),
                assertions=row.get("assertions"),
            )
            for row in amendment["artifacts"]
        )
    gates.append(
        {"gate_id": "G0-provenance-and-reproducibility", "hard_gate": True, "artifacts": g0}
    )
    gates.append(
        {
            "gate_id": "G1-time-step",
            "hard_gate": True,
            "artifacts": [
                _artifact(
                    "campaign-report",
                    analysis["campaign_report"],
                    assertions=[
                        _assertion(
                            "numerical_gate.all_energy_drift_checks_pass", "is_true"
                        ),
                        _assertion(
                            "numerical_gate.selected_timestep_fs", "equals", 2.0
                        ),
                    ],
                )
            ],
        }
    )
    numerical_assertions = [_assertion("status", "equals", "complete")]
    if isinstance(numerical_amendment, dict):
        numerical_assertions.append(
            _assertion(
                "config.protocol_sha256",
                "equals",
                numerical_amendment["numerical_supervisor_protocol_sha256"],
            )
        )
    g2_artifacts = [
        _artifact(
            "dft-numerical-supervisor",
            "runs/supervisor/dft-numerical-supervisor-v1.json",
            assertions=numerical_assertions,
        ),
        _artifact(
            "g2-release",
            branch_config["g2_release"],
            fingerprint_field="gate_fingerprint",
            assertions=[
                _assertion("gate_id", "equals", branch_config["g2_release_id"]),
                _assertion("status", "equals", "pass"),
            ],
        ),
        _artifact(
            "research-analysis-manifest",
            analysis["analysis_manifest"],
            fingerprint_field="manifest_fingerprint",
            assertions=[
                _assertion("branch", "equals", branch),
                _assertion("model_branch_isolation", "is_true"),
                _assertion("analysis_completeness_gate_pass", "is_true"),
                _assertion("negative_scientific_outcomes_retained", "is_true"),
            ],
        ),
    ]
    if branch == "universal":
        g2_artifacts.append(
            _artifact(
                "universal-domain-supervisor",
                "runs/supervisor/dft-domain-supervisor-v1.json",
                assertions=[_assertion("status", "equals", "complete")],
            )
        )
    else:
        g2_artifacts.extend(
            [
                _artifact(
                    "fine-tuning-contingency",
                    branch_config["fine_tuning_state"],
                    assertions=[_assertion("status", "equals", "complete")],
                ),
                _artifact(
                    "fine-tuned-full-rerun",
                    branch_config["fine_rerun_state"],
                    assertions=[
                        _assertion("status", "equals", "complete"),
                        _assertion(
                            "disposition",
                            "equals",
                            "fine_tuned_transport_and_mechanisms_complete_requires_versioned_final_analysis",
                        ),
                    ],
                ),
                _artifact(
                    "universal-domain-failure-retained",
                    branch_config["universal_domain_state"],
                ),
            ]
        )
    gates.append(
        {"gate_id": "G2-dft-and-potential-domain", "hard_gate": True, "artifacts": g2_artifacts}
    )
    gates.append(
        {
            "gate_id": "G3-formal-trajectory-convergence",
            "hard_gate": True,
            "artifacts": [
                _artifact(
                    "hierarchical-transport",
                    analysis["hierarchical_transport"],
                    fingerprint_field="report_fingerprint",
                    assertions=[
                        _assertion("hierarchical_gate_pass", "is_true"),
                        _assertion(
                            "estimators.tracer.n_configurations", "equals", 5
                        ),
                        _assertion(
                            "estimators.collective.n_configurations", "equals", 5
                        ),
                    ],
                )
            ],
        }
    )
    sensitivity_assertions = [
        _assertion("finite_size.comparison_gate_pass", "is_true"),
        _assertion(
            "fixed_experimental_volume.comparison_gate_pass", "is_true"
        ),
        _assertion("npt_volume.by_temperature", "length_equals", 5),
        *[
            _assertion(
                f"npt_volume.by_temperature.{index}.comparison_gate_pass",
                "is_true",
            )
            for index in range(5)
        ],
        _assertion(
            "npt_volume.activation_energy_difference.tracer.analysis_gate_pass",
            "is_true",
        ),
        _assertion(
            "npt_volume.activation_energy_difference.collective.analysis_gate_pass",
            "is_true",
        ),
    ]
    gates.append(
        {
            "gate_id": "G4-replication-size-volume-and-ensemble",
            "hard_gate": True,
            "artifacts": [
                _artifact(
                    "nested-velocity",
                    analysis["nested_velocity"],
                    fingerprint_field="report_fingerprint",
                    assertions=[
                        _assertion("result.nested_velocity_gate_pass", "is_true"),
                        _assertion("records", "length_equals", 15),
                    ],
                ),
                _artifact(
                    "transport-sensitivity",
                    analysis["transport_sensitivity"],
                    fingerprint_field="report_fingerprint",
                    assertions=sensitivity_assertions,
                ),
                _artifact(
                    "production-ensemble-sensitivity",
                    analysis["ensemble_sensitivity"],
                    fingerprint_field="report_fingerprint",
                    assertions=[
                        _assertion(
                            "analysis_completeness_gate_pass", "is_true"
                        ),
                        _assertion("nve_stability.stability_gate_pass", "is_true"),
                    ],
                ),
            ],
        }
    )
    gates.append(
        {
            "gate_id": "G5-experimental-comparison-and-haven",
            "hard_gate": True,
            "artifacts": [
                _artifact(
                    "experimental-validation",
                    analysis["experimental_validation"],
                    fingerprint_field="report_fingerprint",
                    assertions=[
                        _assertion("n_eligible_measurements", "equals", 9),
                        _assertion("n_evaluated", "equals", 9),
                        _assertion("n_blocked", "equals", 0),
                    ],
                ),
                _artifact(
                    "haven-convention-validation",
                    analysis["haven_validation"],
                    fingerprint_field="report_fingerprint",
                    assertions=[
                        _assertion(
                            "analysis_completeness_gate_pass", "is_true"
                        ),
                        _assertion(
                            "convention_mapping.bare_haven_label_allowed", "is_false"
                        ),
                    ],
                ),
            ],
        }
    )
    gates.append(
        {
            "gate_id": "G6-mechanisms-and-temperature-robustness",
            "hard_gate": True,
            "artifacts": [
                _artifact(
                    "mechanism-association",
                    analysis["mechanism_association"],
                    fingerprint_field="report_fingerprint",
                    assertions=[
                        _assertion("input_gate_pass", "is_true"),
                        _assertion("analysis.grid_gate_pass", "is_true"),
                        _assertion("analysis.family_size", "equals", 12),
                        _assertion("analysis_records", "length_equals", 25),
                        _assertion(
                            "analysis.causal_mechanism_claim_allowed", "is_false"
                        ),
                    ],
                ),
                _artifact(
                    "mechanism-temperature-robustness",
                    analysis["mechanism_temperature_robustness"],
                    fingerprint_field="report_fingerprint",
                    assertions=[
                        _assertion(
                            "robustness_completeness_gate_pass", "is_true"
                        ),
                        _assertion("analysis.family_size", "equals", 12),
                    ],
                ),
            ],
        }
    )
    gates.append(
        {
            "gate_id": "G7-publication-manuscript-and-regeneration",
            "hard_gate": True,
            "artifacts": [
                _artifact(
                    "publication-manifest",
                    publication_manifest,
                    fingerprint_field="manifest_fingerprint",
                    assertions=[
                        _assertion("branch", "equals", branch),
                        _assertion("manifest_gate_pass", "is_true"),
                        _assertion("figures", "length_equals", 12),
                        _assertion("tables", "length_equals", 12),
                    ],
                ),
                _artifact(
                    "manuscript-manifest",
                    manuscript_manifest,
                    fingerprint_field="manifest_fingerprint",
                    assertions=[
                        _assertion("branch", "equals", branch),
                        _assertion("manuscript_gate_pass", "is_true"),
                        _assertion(
                            "publication_logical_output_hashes_verified", "equals", 60
                        ),
                    ],
                ),
                _artifact(
                    "clean-regeneration-attestation",
                    regeneration,
                    fingerprint_field="attestation_fingerprint",
                    assertions=[
                        _assertion("branch", "equals", branch),
                        _assertion(
                            "all_declared_artifact_hashes_verified", "is_true"
                        ),
                        _assertion("comparison.all_hashes_match", "is_true"),
                        _assertion(
                            "manuscript_comparison.all_hashes_match", "is_true"
                        ),
                        _assertion("git_dirty", "is_false"),
                    ],
                ),
            ],
        }
    )
    audit = {
        "schema_version": "1.0",
        "protocol_id": f"llzto-research-evidence-audit-v2-{branch}",
        "branch": branch,
        "claim_boundary": supervisor_protocol["claim_boundary"],
        "preregistration_note": supervisor_protocol["preregistration_note"],
        "gates": gates,
    }
    path = derived_root / "evidence-audit-protocol.json"
    return _write_or_verify(path, audit, "branch evidence-audit protocol")


def derive_branch_readiness_protocol(
    supervisor_protocol: dict[str, Any],
    branch: str,
    *,
    evidence_audit_protocol_path: Path,
) -> Path:
    branch_config = supervisor_protocol["branches"][branch]
    analysis = _analysis_source_paths(supervisor_protocol, branch)
    publication_root = _formatted_path(
        supervisor_protocol, "publication_root_template", branch
    )
    derived_root = _formatted_path(
        supervisor_protocol, "derived_protocol_root_template", branch
    )
    protocol: dict[str, Any] = {
        "schema_version": "1.0",
        "protocol_id": f"llzto-research-readiness-v2-{branch}",
        "branch": branch,
        "material": supervisor_protocol["material"],
        "claim_boundary": supervisor_protocol["claim_boundary"],
        "preregistration_note": supervisor_protocol["preregistration_note"],
        "audit": {
            "protocol": str(evidence_audit_protocol_path),
            "report": str(publication_root / "evidence-audit.json"),
            "required_hard_gates": 8,
        },
        "domain_gate": {
            "gate_id": branch_config["g2_release_id"],
            "evidence_kinds": [
                row["kind"] for row in branch_config["domain_evidence"]
            ],
        },
        "sources": {
            "analysis_manifest": str(analysis["analysis_manifest"]),
            "dft_numerical_supervisor": "runs/supervisor/dft-numerical-supervisor-v1.json",
            "g2_release": branch_config["g2_release"],
            "hierarchical_transport": str(analysis["hierarchical_transport"]),
            "nested_velocity": str(analysis["nested_velocity"]),
            "transport_sensitivity": str(analysis["transport_sensitivity"]),
            "mechanism_association": str(analysis["mechanism_association"]),
            "mechanism_temperature_robustness": str(
                analysis["mechanism_temperature_robustness"]
            ),
            "experimental_validation": str(analysis["experimental_validation"]),
            "ensemble_sensitivity": str(analysis["ensemble_sensitivity"]),
            "haven_validation": str(analysis["haven_validation"]),
            "artifact_manifest": str(publication_root / "artifact-manifest.json"),
            "manuscript_manifest": str(
                publication_root / "manuscript-manifest.json"
            ),
            "test_attestation": str(publication_root / "test-attestation.json"),
            "environment_attestation": str(
                publication_root / "environment-attestation.json"
            ),
            "clean_regeneration_attestation": str(
                publication_root / "clean-regeneration-attestation.json"
            ),
        },
        "dimensions": {
            "independent_reference_and_applicability": {
                "maximum": 20,
                "rule": "Complete model-blind numerical reference and branch-specific independent model-domain release.",
            },
            "transport_design_and_inference": {
                "maximum": 20,
                "rule": "Complete five-by-five hierarchical transport and balanced five-by-three nested velocity inference.",
            },
            "robustness_and_sensitivity": {
                "maximum": 15,
                "rule": "All matched controls are estimable and NVE is stable; physical non-equivalence is retained as claim narrowing.",
            },
            "mechanistic_depth": {
                "maximum": 15,
                "rule": "Complete twelve-test primary and categorical-temperature families; retained associations add evidence but complete null remains reportable.",
            },
            "experimental_relevance": {
                "maximum": 15,
                "rule": "All nine scoped comparisons and explicit reciprocal Haven convention are complete; compatibility is an outcome.",
            },
            "reproducibility_and_reporting": {
                "maximum": 15,
                "rule": "Twelve figures/tables, three documents, full tests, environment identity, and byte-identical regeneration pass.",
            },
        },
        "thresholds": {
            "q1_target_evidence_candidate_minimum": 85,
            "strong_specialist_journal_evidence_minimum": 70,
        },
        "hard_rules": {
            "complete_eight_gate_audit_required_before_scoring": True,
            "negative_results_must_not_be_deleted": True,
            "score_is_evidence_readiness_not_journal_guarantee": True,
            "current_external_novelty_and_journal_fit_review_required": True,
        },
        "output": str(publication_root / "readiness-assessment.json"),
    }
    path = derived_root / "readiness-protocol.json"
    return _write_or_verify(path, protocol, "branch readiness protocol")


def derive_all_branch_protocols(
    protocol_path: Path | str, branch: str
) -> dict[str, dict[str, str]]:
    supervisor, source = validate_research_final_protocol(protocol_path)
    ledger = derive_branch_exclusion_ledger(supervisor, branch)
    publication = derive_branch_publication_protocol(
        supervisor, branch, exclusion_ledger_path=ledger
    )
    manuscript = derive_branch_manuscript_protocol(
        supervisor, branch, publication_protocol_path=publication
    )
    audit = derive_branch_evidence_audit_protocol(
        supervisor,
        source,
        branch,
        publication_protocol_path=publication,
        manuscript_protocol_path=manuscript,
        exclusion_ledger_path=ledger,
    )
    readiness = derive_branch_readiness_protocol(
        supervisor, branch, evidence_audit_protocol_path=audit
    )
    return {
        name: {"path": str(path), "sha256": sha256_file(path)}
        for name, path in {
            "exclusion_ledger": ledger,
            "publication": publication,
            "manuscript": manuscript,
            "evidence_audit": audit,
            "readiness": readiness,
        }.items()
    }


def _update_state(
    path: Path, state: dict[str, Any], status: str, **fields: Any
) -> None:
    state["status"] = status
    state.update(fields)
    state["updated_unix_time"] = time.time()
    atomic_write_json(path, state)


def _stage_record(path: Path, payload: dict[str, Any], **fields: Any) -> dict[str, Any]:
    return {
        "status": "complete",
        "path": str(path),
        "sha256": sha256_file(path),
        **fields,
    }


def _run_parallel_attestations(
    supervisor_protocol: dict[str, Any],
    branch: str,
    *,
    audit_protocol_path: Path,
    publication_root: Path,
) -> dict[str, tuple[Path, dict[str, Any]]]:
    branch_config = supervisor_protocol["branches"][branch]
    environment = supervisor_protocol["environment"]
    formal_manifest = (
        _repo_path(branch_config["formal_campaign_root"])
        / branch_config["formal_run_id"]
        / "run_manifest.json"
    )
    test_path = publication_root / "test-attestation.json"
    environment_path = publication_root / "environment-attestation.json"
    definitions: dict[str, tuple[Path, Callable[[], dict[str, Any]]]] = {
        "tests": (
            test_path,
            lambda: run_test_attestation(test_path),
        ),
        "environment": (
            environment_path,
            lambda: build_research_environment_attestation(
                audit_protocol_path,
                qe_manifest_path=_repo_path(environment["qe_manifest"]),
                formal_run_manifest_path=formal_manifest,
                formal_campaign_protocol_path=_repo_path(
                    branch_config["formal_campaign_protocol"]
                ),
                branch=branch,
                out_path=environment_path,
            ),
        ),
    }
    outputs: dict[str, tuple[Path, dict[str, Any]]] = {}
    with ThreadPoolExecutor(
        max_workers=int(supervisor_protocol["resources"]["parallel_attestations"])
    ) as pool:
        futures = {pool.submit(builder): name for name, (_, builder) in definitions.items()}
        for future in as_completed(futures):
            name = futures[future]
            path = definitions[name][0]
            payload = future.result()
            _verify_fingerprint(payload, "attestation_fingerprint", name)
            outputs[name] = (path, payload)
    return outputs


def _build_final_dossier_manifest(
    supervisor_protocol: dict[str, Any],
    supervisor_protocol_path: Path,
    branch: str,
    *,
    routing: dict[str, Any],
    derived: dict[str, dict[str, str]],
    publication_root: Path,
) -> tuple[Path, dict[str, Any]]:
    artifacts = {
        "analysis_manifest": Path(routing["analysis_manifest_path"]),
        "publication_manifest": publication_root / "artifact-manifest.json",
        "manuscript_manifest": publication_root / "manuscript-manifest.json",
        "test_attestation": publication_root / "test-attestation.json",
        "environment_attestation": publication_root / "environment-attestation.json",
        "clean_regeneration_attestation": publication_root
        / "clean-regeneration-attestation.json",
        "evidence_audit": publication_root / "evidence-audit.json",
        "readiness_assessment": publication_root / "readiness-assessment.json",
    }
    records = []
    for artifact_id, path in artifacts.items():
        payload = _read_json(path)
        records.append(
            {
                "artifact_id": artifact_id,
                "path": str(path),
                "sha256": sha256_file(path),
                "kind": payload.get("report_kind")
                or payload.get("manifest_kind")
                or payload.get("attestation_kind"),
            }
        )
    readiness = _read_json(artifacts["readiness_assessment"])
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "manifest_kind": "llzto-complete-research-dossier-v2",
        "branch": branch,
        "supervisor_protocol_path": str(supervisor_protocol_path),
        "supervisor_protocol_sha256": sha256_file(supervisor_protocol_path),
        "routing": routing,
        "derived_protocols": derived,
        "artifacts": records,
        "checks": {
            "one_model_branch": branch in {"universal", "finetuned"},
            "artifact_count": len(records) == 8,
            "all_artifact_hashes_verified": all(
                Path(row["path"]).is_file()
                and sha256_file(row["path"]) == row["sha256"]
                for row in records
            ),
            "evidence_audit_complete": _read_json(
                artifacts["evidence_audit"]
            ).get("evidence_chain_complete")
            is True,
            "readiness_authorizes_external_review": readiness.get(
                "final_q1_level_judgment_authorized"
            )
            is True,
            "journal_guarantee_forbidden": readiness.get(
                "cas_q1_acceptance_or_classification_guaranteed"
            )
            is False,
        },
        "evidence_readiness": {
            "score": readiness["score"],
            "maximum_score": readiness["maximum_score"],
            "class": readiness["evidence_class"],
            "q1_target_evidence_threshold_met": readiness[
                "q1_target_evidence_threshold_met"
            ],
        },
        "scientific_outcome_flags": readiness["scientific_outcome_flags"],
        "external_novelty_and_journal_fit_review_required": True,
        "final_q1_level_judgment_completed": False,
        "implementation_path": str(Path(__file__).resolve()),
        "implementation_sha256": sha256_file(__file__),
    }
    manifest["dossier_gate_pass"] = all(manifest["checks"].values())
    manifest["manifest_fingerprint"] = fingerprint(manifest)
    path = publication_root / "dossier-manifest.json"
    _write_or_verify(path, manifest, "final research dossier manifest")
    return path, manifest


def run_research_final_queue(
    protocol_path: Path | str,
    *,
    state_path: Path | str,
) -> dict[str, Any]:
    """Wait for one branch, then build and audit the complete research dossier."""
    protocol, source = validate_research_final_protocol(protocol_path)
    output = Path(state_path).resolve()
    poll_seconds = float(protocol["resources"]["poll_seconds"])
    if not 5 <= poll_seconds <= 60:
        raise ValueError("research final poll_seconds must be between 5 and 60")
    locked_paths = [
        source,
        Path(__file__).resolve(),
        Path(__file__).with_name("research_publication.py").resolve(),
        Path(__file__).with_name("research_manuscript.py").resolve(),
        Path(__file__).with_name("research_attestation.py").resolve(),
        Path(__file__).with_name("research_readiness.py").resolve(),
        Path(__file__).with_name("research_analysis_queue.py").resolve(),
        Path(__file__).with_name("publication.py").resolve(),
        Path(__file__).with_name("manuscript.py").resolve(),
        Path(__file__).with_name("attestation.py").resolve(),
        Path(__file__).with_name("evidence_audit.py").resolve(),
        Path(__file__).with_name("provenance.py").resolve(),
        *[
            _repo_path(row["path"]) for row in protocol["templates"].values()
        ],
        _repo_path(protocol["upstream"]["protocol"]),
        *[
            _repo_path(row["path"])
            for amendment in _provenance_amendments(protocol)
            for row in amendment.get("artifacts", [])
        ],
    ]
    locked_files = [
        {"path": str(path), "sha256": sha256_file(path)} for path in locked_paths
    ]

    def verify_locks() -> None:
        for row in locked_files:
            if sha256_file(row["path"]) != row["sha256"]:
                raise RuntimeError(f"research final locked file changed: {row['path']}")

    config = {
        "protocol_path": str(source),
        "protocol_sha256": sha256_file(source),
        "locked_files": locked_files,
    }
    queue_fingerprint = fingerprint(config)
    if output.is_file():
        state = _read_json(output)
        if state.get("queue_fingerprint") != queue_fingerprint:
            raise RuntimeError(f"research final configuration changed: {output}")
        if state.get("status") == "complete":
            dossier_path = Path(state["dossier_manifest_path"])
            dossier = _read_json(dossier_path)
            _verify_fingerprint(dossier, "manifest_fingerprint", "research dossier")
            if (
                sha256_file(dossier_path) != state.get("dossier_manifest_sha256")
                or dossier.get("dossier_gate_pass") is not True
            ):
                raise RuntimeError("stored complete research dossier is invalid")
            return state
    else:
        state = {
            "schema_version": "1.0",
            "queue_fingerprint": queue_fingerprint,
            "config": config,
            "created_unix_time": time.time(),
            "stages": {},
        }
        _update_state(output, state, "created")
    try:
        while True:
            verify_locks()
            routing = _inspect_analysis_upstream(protocol)
            if routing["status"] == "ready":
                branch = str(routing["branch"])
                state["routing"] = routing
                break
            if routing["status"] == "blocked":
                _update_state(
                    output,
                    state,
                    "blocked_upstream_evidence",
                    blocker=routing,
                    waiting=None,
                )
                return state
            _update_state(
                output,
                state,
                "waiting_for_complete_research_analysis",
                waiting={"checked_unix_time": time.time(), **routing},
            )
            time.sleep(poll_seconds)

        lock_path = _repo_path(protocol["resources"]["cpu_lock"])
        lock_handle = None
        while lock_handle is None:
            verify_locks()
            lock_handle = acquire_analysis_lock(lock_path)
            if lock_handle is None:
                _update_state(
                    output,
                    state,
                    "waiting_for_final_publication_cpu_lock",
                    active_branch=branch,
                    waiting={
                        "cpu_lock_path": str(lock_path),
                        "checked_unix_time": time.time(),
                    },
                )
                time.sleep(poll_seconds)
        try:
            _update_state(
                output,
                state,
                "deriving_branch_publication_protocols",
                active_branch=branch,
                waiting=None,
            )
            derived = derive_all_branch_protocols(source, branch)
            state["stages"]["derived_protocols"] = {
                "status": "complete",
                "protocols": derived,
            }
            _update_state(
                output,
                state,
                "building_publication_package",
                active_branch=branch,
            )
            publication = build_research_publication_package(
                derived["publication"]["path"]
            )
            publication_root = _formatted_path(
                protocol, "publication_root_template", branch
            )
            artifact_manifest_path = publication_root / "artifact-manifest.json"
            state["stages"]["publication"] = _stage_record(
                artifact_manifest_path,
                publication,
                logical_figures=len(publication["figures"]),
                logical_tables=len(publication["tables"]),
            )

            _update_state(
                output,
                state,
                "building_manuscript_package",
                active_branch=branch,
            )
            manuscript = build_research_manuscript_package(
                derived["manuscript"]["path"]
            )
            manuscript_manifest_path = publication_root / "manuscript-manifest.json"
            state["stages"]["manuscript"] = _stage_record(
                manuscript_manifest_path,
                manuscript,
                document_count=len(manuscript["documents"]),
            )

            _update_state(
                output,
                state,
                "running_test_and_environment_attestations",
                active_branch=branch,
            )
            attestations = _run_parallel_attestations(
                protocol,
                branch,
                audit_protocol_path=Path(derived["evidence_audit"]["path"]),
                publication_root=publication_root,
            )
            for name, (path, payload) in attestations.items():
                state["stages"][f"{name}_attestation"] = _stage_record(
                    path, payload
                )

            _update_state(
                output,
                state,
                "running_clean_regeneration_attestation",
                active_branch=branch,
            )
            regeneration_path = publication_root / "clean-regeneration-attestation.json"
            regeneration = run_research_clean_regeneration_attestation(
                derived["publication"]["path"],
                artifact_manifest_path,
                manuscript_protocol_path=derived["manuscript"]["path"],
                manuscript_manifest_path=manuscript_manifest_path,
                out_path=regeneration_path,
            )
            state["stages"]["clean_regeneration"] = _stage_record(
                regeneration_path, regeneration
            )

            _update_state(
                output,
                state,
                "building_evidence_audit",
                active_branch=branch,
            )
            audit_path = publication_root / "evidence-audit.json"
            audit = build_evidence_audit(derived["evidence_audit"]["path"])
            if audit.get("evidence_chain_complete") is not True:
                raise RuntimeError("derived research evidence audit has blockers")
            _write_or_verify(audit_path, audit, "research evidence audit")
            state["stages"]["evidence_audit"] = _stage_record(
                audit_path, audit, hard_gates=audit["n_hard_gates"]
            )

            _update_state(
                output,
                state,
                "building_readiness_assessment",
                active_branch=branch,
            )
            readiness_path = publication_root / "readiness-assessment.json"
            readiness = build_research_readiness_assessment(
                derived["readiness"]["path"]
            )
            _write_or_verify(
                readiness_path, readiness, "research readiness assessment"
            )
            state["stages"]["readiness"] = _stage_record(
                readiness_path,
                readiness,
                score=readiness["score"],
                evidence_class=readiness["evidence_class"],
            )

            dossier_path, dossier = _build_final_dossier_manifest(
                protocol,
                source,
                branch,
                routing=state["routing"],
                derived=derived,
                publication_root=publication_root,
            )
            state["stages"]["dossier_manifest"] = _stage_record(
                dossier_path, dossier
            )
        finally:
            release_analysis_lock(lock_handle)
        _update_state(
            output,
            state,
            "complete",
            active_branch=branch,
            disposition="complete_research_dossier_ready_for_external_q1_review",
            dossier_manifest_path=str(dossier_path),
            dossier_manifest_sha256=sha256_file(dossier_path),
            readiness_score=readiness["score"],
            readiness_class=readiness["evidence_class"],
            scientific_outcome_flags=readiness["scientific_outcome_flags"],
            final_q1_level_judgment_completed=False,
            waiting=None,
        )
        return state
    except BaseException as exc:
        _update_state(
            output,
            state,
            "failed",
            error={"type": type(exc).__name__, "message": str(exc)},
        )
        raise


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--derive-branch", choices=("universal", "finetuned"))
    args = parser.parse_args()
    if args.derive_branch:
        result = derive_all_branch_protocols(args.protocol, args.derive_branch)
    else:
        result = run_research_final_queue(args.protocol, state_path=args.state)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
