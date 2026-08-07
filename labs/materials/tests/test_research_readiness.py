from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.provenance import fingerprint  # noqa: E402
from matfactory.research_readiness import (  # noqa: E402
    build_research_readiness_assessment,
)


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fingerprinted(payload: dict, field: str) -> dict:
    payload[field] = fingerprint(payload)
    return payload


def _comparison() -> dict:
    return {
        "comparison_gate_pass": True,
        "estimators": {
            estimator: {
                "analysis_gate_pass": True,
                "equivalence_supported": False,
            }
            for estimator in (
                "tracer",
                "collective",
                "collective_to_tracer_ratio",
            )
        },
    }


def test_readiness_scores_complete_negative_results_as_evidence_not_missing(tmp_path):
    audit = _fingerprinted(
        {
            "evidence_chain_complete": True,
            "ready_for_final_qualitative_q1_assessment": True,
            "n_hard_gates": 8,
            "n_passing_hard_gates": 8,
            "blockers": [],
        },
        "report_fingerprint",
    )
    audit_path = tmp_path / "audit.json"
    _write(audit_path, audit)
    payloads = {
        "analysis_manifest": _fingerprinted(
            {
                "branch": "finetuned",
                "model_branch_isolation": True,
                "analysis_completeness_gate_pass": True,
                "negative_scientific_outcomes_retained": True,
                "claim_narrowing_flags": {
                    "size_or_volume_non_equivalence": True,
                    "production_ensemble_non_equivalence": True,
                    "experimental_haven_incompatibility": True,
                },
            },
            "manifest_fingerprint",
        ),
        "dft_numerical_supervisor": {"status": "complete"},
        "g2_release": _fingerprinted(
            {
                "gate_id": "g2-finetuned-potential-domain",
                "status": "pass",
                "evidence": [{"kind": "fine-tuned-domain"}],
            },
            "gate_fingerprint",
        ),
        "hierarchical_transport": _fingerprinted(
            {
                "hierarchical_gate_pass": True,
                "estimators": {
                    "tracer": {"n_configurations": 5},
                    "collective": {"n_configurations": 5},
                },
            },
            "report_fingerprint",
        ),
        "nested_velocity": _fingerprinted(
            {
                "records": [{} for _ in range(15)],
                "result": {"nested_velocity_gate_pass": True},
            },
            "report_fingerprint",
        ),
        "transport_sensitivity": _fingerprinted(
            {
                "finite_size": _comparison(),
                "fixed_experimental_volume": _comparison(),
                "npt_volume": {
                    "by_temperature": [_comparison() for _ in range(5)],
                    "activation_energy_difference": {
                        "tracer": {"analysis_gate_pass": True},
                        "collective": {"analysis_gate_pass": True},
                    },
                },
                "sensitivity_gate_pass": False,
            },
            "report_fingerprint",
        ),
        "mechanism_association": _fingerprinted(
            {
                "input_gate_pass": True,
                "analysis_records": [{} for _ in range(25)],
                "analysis": {
                    "grid_gate_pass": True,
                    "family_size": 12,
                    "association_support_count": 0,
                    "causal_mechanism_claim_allowed": False,
                },
            },
            "report_fingerprint",
        ),
        "mechanism_temperature_robustness": _fingerprinted(
            {
                "robustness_completeness_gate_pass": True,
                "analysis": {"family_size": 12, "retained_association_count": 0},
            },
            "report_fingerprint",
        ),
        "experimental_validation": _fingerprinted(
            {
                "n_eligible_measurements": 9,
                "n_evaluated": 9,
                "n_blocked": 0,
                "comparisons": [
                    {
                        "benchmark_role": "primary_direct_measurement",
                        "scope_notes": ["synthetic"],
                        "compatibility_assessment": "inside" if index < 4 else "outside",
                        "compatible_with_simulation_prediction": index < 4,
                    }
                    for index in range(9)
                ],
            },
            "report_fingerprint",
        ),
        "ensemble_sensitivity": _fingerprinted(
            {
                "analysis_completeness_gate_pass": True,
                "ensemble_robustness_gate_pass": False,
                "nve_stability": {"stability_gate_pass": True},
            },
            "report_fingerprint",
        ),
        "haven_validation": _fingerprinted(
            {
                "analysis_completeness_gate_pass": True,
                "convention_mapping": {"bare_haven_label_allowed": False},
                "experimental_comparison": {
                    "compatible_with_new_configuration_prediction": False
                },
            },
            "report_fingerprint",
        ),
        "artifact_manifest": _fingerprinted(
            {
                "branch": "finetuned",
                "manifest_gate_pass": True,
                "figures": [{} for _ in range(12)],
                "tables": [{} for _ in range(12)],
            },
            "manifest_fingerprint",
        ),
        "manuscript_manifest": _fingerprinted(
            {"branch": "finetuned", "manuscript_gate_pass": True},
            "manifest_fingerprint",
        ),
        "test_attestation": _fingerprinted(
            {"tests_failed": 0, "git_dirty": False},
            "attestation_fingerprint",
        ),
        "environment_attestation": _fingerprinted(
            {
                "branch": "finetuned",
                "environment_gate_pass": True,
            },
            "attestation_fingerprint",
        ),
        "clean_regeneration_attestation": _fingerprinted(
            {
                "branch": "finetuned",
                "git_dirty": False,
                "all_declared_artifact_hashes_verified": True,
                "comparison": {"all_hashes_match": True},
                "manuscript_comparison": {"all_hashes_match": True},
            },
            "attestation_fingerprint",
        ),
    }
    sources = {}
    for name, payload in payloads.items():
        path = tmp_path / f"{name}.json"
        _write(path, payload)
        sources[name] = str(path)
    protocol = {
        "schema_version": "1.0",
        "branch": "finetuned",
        "audit": {"report": str(audit_path), "required_hard_gates": 8},
        "domain_gate": {
            "gate_id": "g2-finetuned-potential-domain",
            "evidence_kinds": ["fine-tuned-domain"],
        },
        "sources": sources,
        "dimensions": {
            "independent_reference_and_applicability": {"maximum": 20},
            "transport_design_and_inference": {"maximum": 20},
            "robustness_and_sensitivity": {"maximum": 15},
            "mechanistic_depth": {"maximum": 15},
            "experimental_relevance": {"maximum": 15},
            "reproducibility_and_reporting": {"maximum": 15},
        },
        "thresholds": {
            "q1_target_evidence_candidate_minimum": 85,
            "strong_specialist_journal_evidence_minimum": 70,
        },
    }
    protocol_path = tmp_path / "readiness.json"
    _write(protocol_path, protocol)

    report = build_research_readiness_assessment(protocol_path)

    assert report["score"] == 97
    assert report["q1_target_evidence_threshold_met"] is True
    assert report["scientific_outcome_flags"][
        "size_volume_robustness_supported"
    ] is False
    assert report["scientific_outcome_flags"][
        "production_ensemble_robustness_supported"
    ] is False
    assert report["scientific_outcome_flags"][
        "temperature_robust_mechanism_association_count"
    ] == 0
    assert report["final_q1_level_judgment_completed"] is False
