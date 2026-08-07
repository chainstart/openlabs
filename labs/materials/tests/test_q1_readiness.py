from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.provenance import fingerprint, sha256_file  # noqa: E402
from matfactory.q1_readiness import build_q1_readiness_assessment  # noqa: E402


def _signed(payload, field):
    payload = dict(payload)
    payload[field] = fingerprint(payload)
    return payload


def _write(path, payload):
    path.write_text(json.dumps(payload))
    return str(path)


def test_frozen_q1_readiness_protocol_scores_one_hundred_points():
    protocol = json.loads(
        (ROOT / "analysis/protocols/llzto_q1_readiness_v1.json").read_text()
    )
    assert sum(row["maximum"] for row in protocol["dimensions"].values()) == 100
    assert protocol["hard_rules"]["complete_evidence_audit_required_before_scoring"]
    assert protocol["hard_rules"][
        "current_external_novelty_and_journal_fit_review_required_for_final_judgment"
    ]


def test_readiness_is_forbidden_before_all_hard_gates_pass(tmp_path):
    audit = _signed(
        {
            "evidence_chain_complete": False,
            "ready_for_final_qualitative_q1_assessment": False,
            "n_hard_gates": 8,
            "n_passing_hard_gates": 7,
            "blockers": [{"gate": "G7"}],
        },
        "report_fingerprint",
    )
    audit_path = tmp_path / "audit.json"
    _write(audit_path, audit)
    protocol = json.loads(
        (ROOT / "analysis/protocols/llzto_q1_readiness_v1.json").read_text()
    )
    protocol["audit"]["report"] = str(audit_path)
    protocol["sources"] = {}
    protocol_path = tmp_path / "protocol.json"
    _write(protocol_path, protocol)
    with pytest.raises(RuntimeError, match="forbidden before the complete audit"):
        build_q1_readiness_assessment(protocol_path)


def test_complete_null_mechanism_package_is_still_scored_without_claim_inflation(
    tmp_path,
):
    audit = _signed(
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

    comparisons = [
        {
            "benchmark_role": "primary_direct_measurement",
            "scope_notes": [],
            "compatibility_assessment": "observed_point_inside_simulation_prediction_interval",
            "compatible_with_simulation_prediction": index < 6,
        }
        for index in range(9)
    ]
    raw_sources = {
        "dft_numerical_supervisor": {"status": "complete"},
        "dft_domain_supervisor": {"status": "complete"},
        "mpi_report": _signed(
            {"mpi_equivalence_gate_pass": True}, "report_fingerprint"
        ),
        "g2_release": _signed(
            {
                "status": "pass",
                "evidence": [
                    {"kind": "domain:feasibility"},
                    {"kind": "domain:publication-heldout"},
                ],
            },
            "gate_fingerprint",
        ),
        "hierarchical_transport": _signed(
            {
                "hierarchical_gate_pass": True,
                "estimators": {
                    "tracer": {"n_configurations": 5},
                    "collective": {"n_configurations": 5},
                },
            },
            "report_fingerprint",
        ),
        "nested_velocity": _signed(
            {
                "result": {"nested_velocity_gate_pass": True},
                "records": [{} for _ in range(15)],
            },
            "report_fingerprint",
        ),
        "transport_sensitivity": _signed(
            {
                "finite_size": {"finite_size_equivalence_gate_pass": True},
                "fixed_experimental_volume": {
                    "fixed_volume_robustness_gate_pass": True
                },
                "npt_volume": {"volume_robustness_gate_pass": True},
            },
            "report_fingerprint",
        ),
        "mechanism_association": _signed(
            {
                "input_gate_pass": True,
                "analysis_records": [{} for _ in range(25)],
                "analysis": {
                    "grid_gate_pass": True,
                    "family_size": 12,
                    "causal_mechanism_claim_allowed": False,
                    "association_support_count": 0,
                },
                "string_claim_qualification": {
                    "all_25_trajectories_support_cooperative_strings_across_grid": False
                },
            },
            "report_fingerprint",
        ),
        "experimental_validation": _signed(
            {
                "n_eligible_measurements": 9,
                "n_evaluated": 9,
                "n_blocked": 0,
                "comparisons": comparisons,
            },
            "report_fingerprint",
        ),
        "artifact_manifest": _signed(
            {"manifest_gate_pass": True}, "manifest_fingerprint"
        ),
        "manuscript_manifest": _signed(
            {"manuscript_gate_pass": True}, "manifest_fingerprint"
        ),
        "test_attestation": _signed(
            {"tests_failed": 0, "git_dirty": False}, "attestation_fingerprint"
        ),
        "environment_attestation": _signed(
            {"environment_gate_pass": True}, "attestation_fingerprint"
        ),
        "clean_regeneration_attestation": _signed(
            {
                "all_declared_artifact_hashes_verified": True,
                "comparison": {"all_hashes_match": True},
                "manuscript_comparison": {"all_hashes_match": True},
            },
            "attestation_fingerprint",
        ),
    }
    source_paths = {
        name: _write(tmp_path / f"{name}.json", payload)
        for name, payload in raw_sources.items()
    }
    protocol = json.loads(
        (ROOT / "analysis/protocols/llzto_q1_readiness_v1.json").read_text()
    )
    protocol["audit"]["report"] = str(audit_path)
    protocol["sources"] = source_paths
    protocol_path = tmp_path / "protocol.json"
    _write(protocol_path, protocol)

    report = build_q1_readiness_assessment(protocol_path)
    assert report["score"] == 97
    assert report["evidence_class"] == "q1-target-evidence-candidate"
    assert report["scientific_outcome_flags"][
        "supported_mechanism_association_count"
    ] == 0
    assert report["final_q1_level_judgment_authorized"] is True
    assert report["final_q1_level_judgment_completed"] is False
    assert report["cas_q1_acceptance_or_classification_guaranteed"] is False
    assert sha256_file(protocol_path) == report["protocol_sha256"]
