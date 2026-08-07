from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.provenance import fingerprint, sha256_file  # noqa: E402
from matfactory.research_final_queue import (  # noqa: E402
    _inspect_analysis_upstream,
    derive_all_branch_protocols,
    validate_research_final_protocol,
)


PROTOCOL = ROOT / "analysis/protocols/llzto_research_publication_supervisor_v4.json"


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_repository_final_protocol_freezes_one_branch_outcome_aware_dossier():
    protocol, source = validate_research_final_protocol(PROTOCOL)

    assert source == PROTOCOL.resolve()
    assert set(protocol["branches"]) == {"universal", "finetuned"}
    assert protocol["environment"]["minimum_tests_passed"] >= 321
    assert "physical non-equivalence" in protocol["claim_boundary"]
    assert protocol["branches"]["universal"]["domain_evidence"][0][
        "publication_claim_gate"
    ] is False
    assert protocol["branches"]["finetuned"]["model_branch"][
        "training_records"
    ] == 62
    watchdog = json.loads(
        (
            ROOT
            / "analysis/protocols/llzto_research_publication_watchdog_v4.json"
        ).read_text()
    )
    assert watchdog["managed"][0]["expected_protocol_sha256"] == sha256_file(
        source
    )


def test_final_router_requires_hash_verified_complete_analysis(tmp_path):
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    manifest = {
        "branch": "universal",
        "model_branch_isolation": True,
        "analysis_completeness_gate_pass": True,
    }
    manifest["manifest_fingerprint"] = fingerprint(manifest)
    manifest_path = tmp_path / "analysis-manifest.json"
    _write(manifest_path, manifest)
    state = {
        "status": "complete",
        "disposition": protocol["upstream"]["complete_disposition"],
        "active_branch": "universal",
        "analysis_manifest_path": str(manifest_path),
        "analysis_manifest_sha256": sha256_file(manifest_path),
        "config": {"protocol_sha256": protocol["upstream"]["protocol_sha256"]},
    }
    state_path = tmp_path / "analysis-state.json"
    _write(state_path, state)
    protocol["upstream"]["state"] = str(state_path)

    ready = _inspect_analysis_upstream(protocol)

    assert ready["status"] == "ready"
    assert ready["branch"] == "universal"

    state["analysis_manifest_sha256"] = "wrong"
    _write(state_path, state)
    blocked = _inspect_analysis_upstream(protocol)
    assert blocked["status"] == "blocked"
    assert blocked["reason"] == "analysis-complete-state-invalid"


def test_universal_derivation_has_twelve_outputs_and_negative_result_semantics(
    tmp_path,
):
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    protocol["paths"] = {
        "analysis_root_template": str(tmp_path / "analysis/{branch}"),
        "derived_protocol_root_template": str(tmp_path / "protocols/{branch}"),
        "publication_root_template": str(tmp_path / "publication/{branch}"),
        "manuscript_root_template": str(tmp_path / "manuscript/{branch}"),
    }
    protocol_path = tmp_path / "supervisor.json"
    _write(protocol_path, protocol)

    derived = derive_all_branch_protocols(protocol_path, "universal")

    publication = json.loads(Path(derived["publication"]["path"]).read_text())
    manuscript = json.loads(Path(derived["manuscript"]["path"]).read_text())
    audit = json.loads(Path(derived["evidence_audit"]["path"]).read_text())
    readiness = json.loads(Path(derived["readiness"]["path"]).read_text())
    ledger = json.loads(Path(derived["exclusion_ledger"]["path"]).read_text())

    assert publication["branch"] == "universal"
    assert len(publication["figures"]) == 12
    assert len(publication["tables"]) == 12
    assert publication["domain_gate"]["evidence"][0][
        "publication_claim_gate"
    ] is False
    assert manuscript["documents"]["main"]["minimum_bytes"] == 18000
    assert len(audit["gates"]) == 8
    g0 = next(gate for gate in audit["gates"] if gate["gate_id"].startswith("G0"))
    g0_ids = {artifact["artifact_id"] for artifact in g0["artifacts"]}
    assert {
        "dft-numerical-supervisor-v2-protocol",
        "kpoint-ladder-v3-medium-io-protocol",
        "unsafe-default-io-interruption",
        "medium-io-resource-assessment",
        "medium-io-resource-release",
        "source-equivalence-protocol",
        "source-equivalence-implementation",
        "source-equivalence-certificate",
    } <= g0_ids
    numerical = next(
        artifact
        for gate in audit["gates"]
        for artifact in gate["artifacts"]
        if artifact["artifact_id"] == "dft-numerical-supervisor"
    )
    assert {
        row["json_path"] for row in numerical["assertions"]
    } == {"status", "config.protocol_sha256"}
    sensitivity = next(
        artifact
        for gate in audit["gates"]
        for artifact in gate["artifacts"]
        if artifact["artifact_id"] == "transport-sensitivity"
    )
    assertion_paths = {row["json_path"] for row in sensitivity["assertions"]}
    assert "finite_size.comparison_gate_pass" in assertion_paths
    assert "sensitivity_gate_pass" not in assertion_paths
    assert readiness["audit"]["required_hard_gates"] == 8
    assert readiness["hard_rules"]["negative_results_must_not_be_deleted"] is True
    assert ledger["branch"] == "universal"
