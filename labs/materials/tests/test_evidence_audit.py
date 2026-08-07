from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.evidence_audit import (  # noqa: E402
    audit_artifact,
    build_evidence_audit,
    evaluate_assertion,
    json_path,
)
from matfactory.provenance import fingerprint, sha256_file  # noqa: E402


def _write_protocol(path: Path, artifact: dict) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "protocol_id": "test-audit",
                "claim_boundary": "completeness is not journal acceptance",
                "gates": [
                    {
                        "gate_id": "G-test",
                        "hard_gate": True,
                        "artifacts": [artifact],
                    }
                ],
            }
        )
    )


def test_json_path_and_assertion_operators_are_explicit():
    payload = {"nested": {"value": 3, "rows": [1, 2, 3]}, "flag": False}
    assert json_path(payload, "nested.value") == 3
    assert evaluate_assertion(
        payload,
        {"json_path": "nested.value", "operator": "at_least", "value": 2},
    )["pass"] is True
    assert evaluate_assertion(
        payload,
        {"json_path": "nested.rows", "operator": "length_equals", "value": 3},
    )["pass"] is True
    assert evaluate_assertion(
        payload, {"json_path": "flag", "operator": "is_false"}
    )["pass"] is True
    missing = evaluate_assertion(
        payload, {"json_path": "absent", "operator": "is_true"}
    )
    assert missing["pass"] is False
    assert "KeyError" in missing["error"]


def test_complete_fingerprinted_artifact_releases_evidence_chain(tmp_path):
    artifact_path = tmp_path / "artifact.json"
    payload = {"schema_version": "1.0", "gate_pass": True, "rows": [1, 2, 3]}
    payload["report_fingerprint"] = fingerprint(payload)
    artifact_path.write_text(json.dumps(payload))
    protocol_path = tmp_path / "protocol.json"
    _write_protocol(
        protocol_path,
        {
            "artifact_id": "result",
            "path": str(artifact_path),
            "format": "json",
            "fingerprint_field": "report_fingerprint",
            "assertions": [
                {"json_path": "gate_pass", "operator": "is_true"},
                {
                    "json_path": "rows",
                    "operator": "length_at_least",
                    "value": 3,
                },
            ],
        },
    )
    report = build_evidence_audit(protocol_path)
    assert report["evidence_chain_complete"] is True
    assert report["ready_for_final_qualitative_q1_assessment"] is True
    assert report["q1_journal_acceptance_guaranteed"] is False
    unsigned = dict(report)
    stored = unsigned.pop("report_fingerprint")
    assert stored == fingerprint(unsigned)


def test_missing_or_tampered_artifact_is_a_named_blocker(tmp_path):
    artifact_path = tmp_path / "artifact.json"
    payload = {"gate_pass": True}
    payload["report_fingerprint"] = fingerprint(payload)
    artifact_path.write_text(json.dumps(payload))
    protocol_path = tmp_path / "protocol.json"
    _write_protocol(
        protocol_path,
        {
            "artifact_id": "result",
            "path": str(artifact_path),
            "format": "json",
            "fingerprint_field": "report_fingerprint",
            "assertions": [{"json_path": "gate_pass", "operator": "is_true"}],
        },
    )
    payload["changed"] = True
    artifact_path.write_text(json.dumps(payload))
    report = build_evidence_audit(protocol_path)
    assert report["evidence_chain_complete"] is False
    assert report["blockers"][0]["artifact_id"] == "result"
    assert "fingerprint" in report["blockers"][0]["failed_checks"]

    artifact_path.unlink()
    missing = build_evidence_audit(protocol_path)
    assert missing["blockers"][0]["failed_checks"] == ["exists"]


def test_exclusion_ledger_verifies_referenced_artifact_hashes(tmp_path):
    excluded = tmp_path / "excluded.json"
    excluded.write_text("{}\n")
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "entry_id": "old-result",
                        "disposition": "excluded",
                        "scope": "all claims",
                        "reason": "incomplete",
                        "artifacts": [
                            {
                                "path": str(excluded),
                                "sha256": sha256_file(excluded),
                            }
                        ],
                    }
                ]
            }
        )
    )
    specification = {
        "artifact_id": "ledger",
        "path": str(ledger_path),
        "format": "exclusion_ledger",
    }
    assert audit_artifact(specification)["artifact_gate_pass"] is True
    excluded.write_text("tampered\n")
    audited = audit_artifact(specification)
    assert audited["artifact_gate_pass"] is False
    assert audited["exclusion_ledger"]["artifact_checks"][0]["pass"] is False


def test_plain_file_enforces_expected_hash_and_minimum_size(tmp_path):
    source = tmp_path / "lock"
    source.write_text("locked content")
    passing = audit_artifact(
        {
            "artifact_id": "lock",
            "path": str(source),
            "format": "file",
            "expected_sha256": sha256_file(source),
            "minimum_bytes": 5,
        }
    )
    assert passing["artifact_gate_pass"] is True
    failing = audit_artifact(
        {
            "artifact_id": "lock",
            "path": str(source),
            "format": "file",
            "expected_sha256": "0" * 64,
            "minimum_bytes": 100,
        }
    )
    assert failing["artifact_gate_pass"] is False
    assert failing["checks"]["expected_sha256"] is False
    assert failing["checks"]["minimum_bytes"] is False
