"""Score LLZTO v2 evidence readiness while retaining scientific negative outcomes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .provenance import atomic_write_json, fingerprint, sha256_file
from .research_analysis_queue import _sensitivity_analysis_complete


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


def _verify_fingerprint(payload: dict[str, Any], field: str, label: str) -> None:
    unsigned = dict(payload)
    stored = unsigned.pop(field, None)
    if stored != fingerprint(unsigned):
        raise RuntimeError(f"{label} fingerprint mismatch")


def _source_record(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "report_kind": payload.get("report_kind")
        or payload.get("manifest_kind")
        or payload.get("attestation_kind"),
    }


def build_research_readiness_assessment(protocol_path: Path | str) -> dict[str, Any]:
    """Authorize later literature review only after all eight v2 audit gates pass."""
    source = Path(protocol_path).resolve()
    protocol = _read_json(source)
    if protocol.get("schema_version") != "1.0":
        raise ValueError("research readiness protocol schema_version must be '1.0'")
    branch = str(protocol.get("branch", ""))
    if branch not in {"universal", "finetuned"}:
        raise ValueError("research readiness branch must be universal or finetuned")
    dimensions = protocol.get("dimensions")
    if not isinstance(dimensions, dict) or sum(
        int(row["maximum"]) for row in dimensions.values()
    ) != 100:
        raise ValueError("research readiness dimensions must sum to 100")
    audit_path = _repo_path(protocol["audit"]["report"])
    audit = _read_json(audit_path)
    _verify_fingerprint(audit, "report_fingerprint", "research evidence audit")
    required_gates = int(protocol["audit"]["required_hard_gates"])
    audit_checks = {
        "evidence_chain_complete": audit.get("evidence_chain_complete") is True,
        "assessment_authorized": audit.get(
            "ready_for_final_qualitative_q1_assessment"
        )
        is True,
        "hard_gate_count": audit.get("n_hard_gates") == required_gates,
        "passing_hard_gate_count": audit.get("n_passing_hard_gates")
        == required_gates,
        "no_blockers": audit.get("blockers") == [],
    }
    if not all(audit_checks.values()):
        failed = [name for name, passed in audit_checks.items() if not passed]
        raise RuntimeError(
            "research readiness is forbidden before complete audit: "
            + ", ".join(failed)
        )

    loaded: dict[str, tuple[Path, dict[str, Any]]] = {}
    for name, value in protocol["sources"].items():
        path = _repo_path(value)
        loaded[name] = (path, _read_json(path))
    fingerprint_fields = {
        "analysis_manifest": "manifest_fingerprint",
        "g2_release": "gate_fingerprint",
        "hierarchical_transport": "report_fingerprint",
        "nested_velocity": "report_fingerprint",
        "transport_sensitivity": "report_fingerprint",
        "mechanism_association": "report_fingerprint",
        "mechanism_temperature_robustness": "report_fingerprint",
        "experimental_validation": "report_fingerprint",
        "ensemble_sensitivity": "report_fingerprint",
        "haven_validation": "report_fingerprint",
        "artifact_manifest": "manifest_fingerprint",
        "manuscript_manifest": "manifest_fingerprint",
        "test_attestation": "attestation_fingerprint",
        "environment_attestation": "attestation_fingerprint",
        "clean_regeneration_attestation": "attestation_fingerprint",
    }
    for name, field in fingerprint_fields.items():
        _verify_fingerprint(loaded[name][1], field, name)
    analysis = loaded["analysis_manifest"][1]
    g2 = loaded["g2_release"][1]
    hierarchy = loaded["hierarchical_transport"][1]
    velocity = loaded["nested_velocity"][1]
    sensitivity = loaded["transport_sensitivity"][1]
    mechanism = loaded["mechanism_association"][1]
    temperature = loaded["mechanism_temperature_robustness"][1]
    experiment = loaded["experimental_validation"][1]
    ensemble = loaded["ensemble_sensitivity"][1]
    haven = loaded["haven_validation"][1]
    artifacts = loaded["artifact_manifest"][1]
    manuscript = loaded["manuscript_manifest"][1]
    tests = loaded["test_attestation"][1]
    environment = loaded["environment_attestation"][1]
    regeneration = loaded["clean_regeneration_attestation"][1]
    numerical = loaded["dft_numerical_supervisor"][1]

    domain_kinds = {
        str(row.get("kind"))
        for row in g2.get("evidence", [])
        if str(row.get("kind")) in set(protocol["domain_gate"]["evidence_kinds"])
    }
    expected_domain_kinds = set(protocol["domain_gate"]["evidence_kinds"])
    reference_checks = {
        "analysis_branch_isolated": analysis.get("branch") == branch
        and analysis.get("model_branch_isolation") is True
        and analysis.get("analysis_completeness_gate_pass") is True,
        "numerical_supervisor_complete": numerical.get("status") == "complete",
        "branch_g2_release": g2.get("gate_id")
        == protocol["domain_gate"]["gate_id"]
        and g2.get("status") == "pass",
        "branch_domain_inventory": domain_kinds == expected_domain_kinds,
    }
    transport_checks = {
        "hierarchical_grid": hierarchy.get("hierarchical_gate_pass") is True
        and hierarchy.get("estimators", {}).get("tracer", {}).get(
            "n_configurations"
        )
        == 5
        and hierarchy.get("estimators", {}).get("collective", {}).get(
            "n_configurations"
        )
        == 5,
        "nested_velocity_grid": velocity.get("result", {}).get(
            "nested_velocity_gate_pass"
        )
        is True
        and len(velocity.get("records", [])) == 15,
    }
    robustness_checks = {
        "size_volume_estimable": _sensitivity_analysis_complete(sensitivity),
        "ensemble_estimable_and_stable": ensemble.get(
            "analysis_completeness_gate_pass"
        )
        is True
        and ensemble.get("nve_stability", {}).get("stability_gate_pass") is True,
        "negative_equivalence_retained": analysis.get(
            "negative_scientific_outcomes_retained"
        )
        is True,
    }
    mechanism_checks = {
        "complete_primary_family": mechanism.get("input_gate_pass") is True
        and mechanism.get("analysis", {}).get("grid_gate_pass") is True
        and mechanism.get("analysis", {}).get("family_size") == 12
        and len(mechanism.get("analysis_records", [])) == 25,
        "complete_temperature_robustness": temperature.get(
            "robustness_completeness_gate_pass"
        )
        is True
        and temperature.get("analysis", {}).get("family_size") == 12,
        "noncausal_qualification": mechanism.get("analysis", {}).get(
            "causal_mechanism_claim_allowed"
        )
        is False,
    }
    experiment_checks = {
        "nine_evaluated": experiment.get("n_eligible_measurements") == 9
        and experiment.get("n_evaluated") == 9
        and experiment.get("n_blocked") == 0,
        "roles_and_scope_retained": all(
            row.get("benchmark_role")
            and isinstance(row.get("scope_notes"), list)
            and row.get("compatibility_assessment")
            for row in experiment.get("comparisons", [])
        ),
        "haven_convention_complete": haven.get(
            "analysis_completeness_gate_pass"
        )
        is True
        and haven.get("convention_mapping", {}).get("bare_haven_label_allowed")
        is False,
    }
    reporting_checks = {
        "publication_manifest": artifacts.get("branch") == branch
        and artifacts.get("manifest_gate_pass") is True
        and len(artifacts.get("figures", [])) == 12
        and len(artifacts.get("tables", [])) == 12,
        "manuscript_manifest": manuscript.get("branch") == branch
        and manuscript.get("manuscript_gate_pass") is True,
        "tests": tests.get("tests_failed") == 0
        and tests.get("git_dirty") is False,
        "environment": environment.get("branch") == branch
        and environment.get("environment_gate_pass") is True,
        "clean_regeneration": regeneration.get("branch") == branch
        and regeneration.get("git_dirty") is False
        and regeneration.get("all_declared_artifact_hashes_verified") is True
        and regeneration.get("comparison", {}).get("all_hashes_match") is True
        and regeneration.get("manuscript_comparison", {}).get(
            "all_hashes_match"
        )
        is True,
    }
    retained = int(
        temperature.get("analysis", {}).get("retained_association_count", 0)
    )
    dimension_scores = {
        "independent_reference_and_applicability": (
            20 if all(reference_checks.values()) else 0
        ),
        "transport_design_and_inference": (
            20 if all(transport_checks.values()) else 0
        ),
        "robustness_and_sensitivity": (
            15 if all(robustness_checks.values()) else 0
        ),
        "mechanistic_depth": (
            12 + (3 if retained > 0 else 0)
            if all(mechanism_checks.values())
            else 0
        ),
        "experimental_relevance": (
            15 if all(experiment_checks.values()) else 0
        ),
        "reproducibility_and_reporting": (
            15 if all(reporting_checks.values()) else 0
        ),
    }
    score = sum(dimension_scores.values())
    q1_threshold = int(
        protocol["thresholds"]["q1_target_evidence_candidate_minimum"]
    )
    specialist_threshold = int(
        protocol["thresholds"]["strong_specialist_journal_evidence_minimum"]
    )
    evidence_class = (
        "q1-target-evidence-candidate"
        if score >= q1_threshold
        else (
            "strong-specialist-journal-evidence"
            if score >= specialist_threshold
            else "additional-evidence-required"
        )
    )
    claim_flags = analysis.get("claim_narrowing_flags", {})
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "report_kind": "llzto-research-readiness-assessment-v2",
        "branch": branch,
        "protocol_path": str(source),
        "protocol_sha256": sha256_file(source),
        "audit_path": str(audit_path),
        "audit_sha256": sha256_file(audit_path),
        "audit_fingerprint": audit["report_fingerprint"],
        "audit_checks": audit_checks,
        "score": score,
        "maximum_score": 100,
        "dimension_scores": {
            name: {
                "score": dimension_scores[name],
                "maximum": int(dimensions[name]["maximum"]),
            }
            for name in dimensions
        },
        "evidence_checks": {
            "independent_reference_and_applicability": reference_checks,
            "transport_design_and_inference": transport_checks,
            "robustness_and_sensitivity": robustness_checks,
            "mechanistic_depth": mechanism_checks,
            "experimental_relevance": experiment_checks,
            "reproducibility_and_reporting": reporting_checks,
        },
        "scientific_outcome_flags": {
            "claim_narrowing_flags": claim_flags,
            "claim_narrowing_flag_count": sum(value is True for value in claim_flags.values()),
            "size_volume_robustness_supported": sensitivity.get(
                "sensitivity_gate_pass"
            ),
            "production_ensemble_robustness_supported": ensemble.get(
                "ensemble_robustness_gate_pass"
            ),
            "primary_mechanism_association_count": mechanism.get(
                "analysis", {}
            ).get("association_support_count"),
            "temperature_robust_mechanism_association_count": retained,
            "experimental_haven_compatible": haven.get(
                "experimental_comparison", {}
            ).get("compatible_with_new_configuration_prediction"),
            "experimental_points_inside_prediction_interval": sum(
                row.get("compatible_with_simulation_prediction") is True
                for row in experiment.get("comparisons", [])
            ),
            "experimental_points_outside_prediction_interval": sum(
                row.get("compatible_with_simulation_prediction") is False
                for row in experiment.get("comparisons", [])
            ),
            "negative_outcomes_change_claim_not_completeness": True,
        },
        "evidence_class": evidence_class,
        "q1_target_evidence_threshold_met": score >= q1_threshold,
        "external_novelty_and_journal_fit_review_required": True,
        "final_q1_level_judgment_authorized": True,
        "final_q1_level_judgment_completed": False,
        "cas_q1_acceptance_or_classification_guaranteed": False,
        "interpretation": (
            "This score audits evidence design and reproducibility. Favorable physical "
            "outcomes are reported separately; current literature and journal fit remain "
            "mandatory before a final Q1-level judgment."
        ),
        "sources": [
            {"source_id": name, **_source_record(path, payload)}
            for name, (path, payload) in sorted(loaded.items())
        ],
        "implementation_path": str(Path(__file__).resolve()),
        "implementation_sha256": sha256_file(__file__),
    }
    report["report_fingerprint"] = fingerprint(report)
    return report


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--out")
    args = parser.parse_args()
    protocol = _read_json(args.protocol)
    destination = _repo_path(args.out or protocol["output"])
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite research readiness report: {destination}")
    report = build_research_readiness_assessment(args.protocol)
    atomic_write_json(destination, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
