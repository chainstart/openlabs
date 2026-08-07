"""Gate the LLZTO Q1-readiness dossier behind the complete evidence audit."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .provenance import atomic_write_json, fingerprint, sha256_file


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


def build_q1_readiness_assessment(protocol_path: Path | str) -> dict[str, Any]:
    """Score evidence-package readiness only after every frozen hard gate passes."""
    source = Path(protocol_path).resolve()
    protocol = _read_json(source)
    if protocol.get("schema_version") != "1.0":
        raise ValueError("Q1-readiness protocol schema_version must be '1.0'")
    dimensions = protocol.get("dimensions")
    if not isinstance(dimensions, dict) or sum(
        int(row["maximum"]) for row in dimensions.values()
    ) != 100:
        raise ValueError("Q1-readiness dimensions must sum to 100")

    audit_path = _repo_path(protocol["audit"]["report"])
    audit = _read_json(audit_path)
    _verify_fingerprint(audit, "report_fingerprint", "evidence audit")
    required_gates = int(protocol["audit"]["required_hard_gates"])
    audit_checks = {
        "evidence_chain_complete": audit.get("evidence_chain_complete") is True,
        "assessment_authorized": audit.get(
            "ready_for_final_qualitative_q1_assessment"
        )
        is True,
        "hard_gate_count": int(audit.get("n_hard_gates", -1)) == required_gates,
        "passing_hard_gate_count": int(
            audit.get("n_passing_hard_gates", -1)
        )
        == required_gates,
        "no_blockers": audit.get("blockers") == [],
    }
    if not all(audit_checks.values()):
        failed = [name for name, passed in audit_checks.items() if not passed]
        raise RuntimeError(
            "Q1-readiness assessment is forbidden before the complete audit: "
            + ", ".join(failed)
        )

    loaded: dict[str, tuple[Path, dict[str, Any]]] = {}
    for name, value in protocol["sources"].items():
        path = _repo_path(value)
        loaded[name] = (path, _read_json(path))

    numerical = loaded["dft_numerical_supervisor"][1]
    domain = loaded["dft_domain_supervisor"][1]
    mpi = loaded["mpi_report"][1]
    g2 = loaded["g2_release"][1]
    hierarchical = loaded["hierarchical_transport"][1]
    velocity = loaded["nested_velocity"][1]
    sensitivity = loaded["transport_sensitivity"][1]
    mechanism = loaded["mechanism_association"][1]
    experiment = loaded["experimental_validation"][1]
    artifacts = loaded["artifact_manifest"][1]
    manuscript = loaded["manuscript_manifest"][1]
    tests = loaded["test_attestation"][1]
    environment = loaded["environment_attestation"][1]
    regeneration = loaded["clean_regeneration_attestation"][1]

    fingerprint_fields = {
        "mpi_report": "report_fingerprint",
        "g2_release": "gate_fingerprint",
        "hierarchical_transport": "report_fingerprint",
        "nested_velocity": "report_fingerprint",
        "transport_sensitivity": "report_fingerprint",
        "mechanism_association": "report_fingerprint",
        "experimental_validation": "report_fingerprint",
        "artifact_manifest": "manifest_fingerprint",
        "manuscript_manifest": "manifest_fingerprint",
        "test_attestation": "attestation_fingerprint",
        "environment_attestation": "attestation_fingerprint",
        "clean_regeneration_attestation": "attestation_fingerprint",
    }
    for name, field in fingerprint_fields.items():
        _verify_fingerprint(loaded[name][1], field, name)

    domain_evidence = {
        str(row.get("kind"))
        for row in g2.get("evidence", [])
        if str(row.get("kind", "")).startswith("domain:")
    }
    reference_checks = {
        "numerical_supervisor_complete": numerical.get("status") == "complete",
        "domain_supervisor_complete": domain.get("status") == "complete",
        "mpi_equivalence": mpi.get("mpi_equivalence_gate_pass") is True,
        "full_g2_release": g2.get("status") == "pass"
        and domain_evidence == {"domain:feasibility", "domain:publication-heldout"},
    }
    transport_checks = {
        "hierarchical_grid": hierarchical.get("hierarchical_gate_pass") is True
        and hierarchical.get("estimators", {}).get("tracer", {}).get(
            "n_configurations"
        )
        == 5
        and hierarchical.get("estimators", {}).get("collective", {}).get(
            "n_configurations"
        )
        == 5,
        "nested_velocity_grid": velocity.get("result", {}).get(
            "nested_velocity_gate_pass"
        )
        is True
        and len(velocity.get("records", [])) == 15,
    }
    sensitivity_checks = {
        "finite_size": sensitivity.get("finite_size", {}).get(
            "finite_size_equivalence_gate_pass"
        )
        is True,
        "fixed_volume": sensitivity.get("fixed_experimental_volume", {}).get(
            "fixed_volume_robustness_gate_pass"
        )
        is True,
        "npt_volume": sensitivity.get("npt_volume", {}).get(
            "volume_robustness_gate_pass"
        )
        is True,
    }
    mechanism_checks = {
        "complete_inputs": mechanism.get("input_gate_pass") is True
        and len(mechanism.get("analysis_records", [])) == 25,
        "complete_family": mechanism.get("analysis", {}).get("grid_gate_pass")
        is True
        and mechanism.get("analysis", {}).get("family_size") == 12,
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
    }
    reporting_checks = {
        "publication_manifest": artifacts.get("manifest_gate_pass") is True,
        "manuscript_manifest": manuscript.get("manuscript_gate_pass") is True,
        "tests": tests.get("tests_failed") == 0
        and tests.get("git_dirty") is False,
        "environment": environment.get("environment_gate_pass") is True,
        "clean_regeneration": regeneration.get(
            "all_declared_artifact_hashes_verified"
        )
        is True
        and regeneration.get("comparison", {}).get("all_hashes_match") is True
        and regeneration.get("manuscript_comparison", {}).get(
            "all_hashes_match"
        )
        is True,
    }

    supported_associations = int(
        mechanism.get("analysis", {}).get("association_support_count", 0)
    )
    dimension_scores = {
        "independent_reference_and_applicability": (
            20 if all(reference_checks.values()) else 0
        ),
        "transport_design_and_inference": (
            20 if all(transport_checks.values()) else 0
        ),
        "robustness_and_sensitivity": (
            15 if all(sensitivity_checks.values()) else 0
        ),
        "mechanistic_depth": (
            12 + (3 if supported_associations > 0 else 0)
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
    if score >= q1_threshold:
        evidence_class = "q1-target-evidence-candidate"
    elif score >= specialist_threshold:
        evidence_class = "strong-specialist-journal-evidence"
    else:
        evidence_class = "additional-evidence-required"

    report = {
        "schema_version": "1.0",
        "report_kind": "llzto-q1-readiness-assessment",
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
            "robustness_and_sensitivity": sensitivity_checks,
            "mechanistic_depth": mechanism_checks,
            "experimental_relevance": experiment_checks,
            "reproducibility_and_reporting": reporting_checks,
        },
        "scientific_outcome_flags": {
            "supported_mechanism_association_count": supported_associations,
            "all_formal_strings_robustly_cooperative": mechanism.get(
                "string_claim_qualification", {}
            ).get("all_25_trajectories_support_cooperative_strings_across_grid"),
            "experimental_points_inside_prediction_interval": sum(
                row.get("compatible_with_simulation_prediction") is True
                for row in experiment.get("comparisons", [])
            ),
            "experimental_points_outside_prediction_interval": sum(
                row.get("compatible_with_simulation_prediction") is False
                for row in experiment.get("comparisons", [])
            ),
        },
        "evidence_class": evidence_class,
        "q1_target_evidence_threshold_met": score >= q1_threshold,
        "external_novelty_and_journal_fit_review_required": True,
        "final_q1_level_judgment_authorized": True,
        "final_q1_level_judgment_completed": False,
        "cas_q1_acceptance_or_classification_guaranteed": False,
        "interpretation": (
            "This is a preregistered evidence-readiness score. A final Q1-level "
            "judgment must additionally compare the completed outcomes with the "
            "current literature and the scope of candidate journals."
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
        raise RuntimeError(f"refusing to overwrite Q1-readiness report: {destination}")
    report = build_q1_readiness_assessment(args.protocol)
    atomic_write_json(destination, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
