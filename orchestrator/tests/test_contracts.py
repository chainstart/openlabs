from __future__ import annotations

import json
from pathlib import Path

from openlabs.contracts import validate_result_bundle, validate_task
from openlabs.gates import evaluate_result_bundle

CODE_ROOT = Path(__file__).resolve().parents[2]


def test_contract_examples_are_valid() -> None:
    task = json.loads(
        (CODE_ROOT / "packages/contracts/examples/smoke-task.json").read_text(encoding="utf-8")
    )
    result = json.loads(
        (CODE_ROOT / "packages/contracts/examples/smoke-result.json").read_text(encoding="utf-8")
    )
    assert validate_task(task).valid
    assert validate_result_bundle(result).valid
    assert evaluate_result_bundle(result).passed


def test_supported_claim_requires_hash_bound_evidence() -> None:
    result = json.loads(
        (CODE_ROOT / "packages/contracts/examples/smoke-result.json").read_text(encoding="utf-8")
    )
    result["artifacts"][0].pop("sha256")
    gate = evaluate_result_bundle(result)
    assert not gate.passed
    assert any("without sha256" in blocker for blocker in gate.blockers)


def test_gate_verifies_local_artifact_bytes(tmp_path) -> None:
    artifact = tmp_path / "artifact.json"
    artifact.write_text('{"value": 1}\n', encoding="utf-8")
    result = json.loads(
        (CODE_ROOT / "packages/contracts/examples/smoke-result.json").read_text(encoding="utf-8")
    )
    result["artifacts"][0]["uri"] = artifact.resolve().as_uri()
    result["artifacts"][0]["sha256"] = "0" * 64

    gate = evaluate_result_bundle(result, allowed_roots=(tmp_path,))

    assert not gate.passed
    assert "artifact smoke-evidence SHA-256 mismatch" in gate.blockers
    assert gate.failure_classes == ("artifact_binding",)


def test_result_contract_accepts_fresh_role_handoff_but_not_resumed_reviewer() -> None:
    result = json.loads(
        (CODE_ROOT / "packages/contracts/examples/smoke-result.json").read_text(encoding="utf-8")
    )
    result["next_actions"] = [
        {
            "objective": "Run the frozen protocol independently.",
            "agent_role": "experimenter",
            "session_mode": "fresh",
        }
    ]
    assert validate_result_bundle(result).valid

    result["next_actions"][0] = {
        "objective": "Audit the frozen evidence.",
        "agent_role": "reviewer",
        "session_mode": "resume",
    }
    validation = validate_result_bundle(result)
    assert not validation.valid
    assert any("reviewer handoffs must start fresh" in error for error in validation.errors)


def test_contract_accepts_typed_review_remediation_resources() -> None:
    result = json.loads(
        (CODE_ROOT / "packages/contracts/examples/smoke-result.json").read_text(encoding="utf-8")
    )
    result["next_actions"] = [
        {
            "objective": "Run the exact missing ablation.",
            "agent_role": "experimenter",
            "session_mode": "fresh",
            "handoff_kind": "evidence_remediation",
            "wall_seconds": 2400,
            "resources": {
                "cpu_threads": 4,
                "memory_mib": 8192,
                "scratch_mib": 16384,
            },
        }
    ]

    assert validate_result_bundle(result).valid

    result["next_actions"][0]["wall_seconds"] = 0
    validation = validate_result_bundle(result)
    assert not validation.valid
    assert any("wall_seconds" in error for error in validation.errors)
    result["next_actions"][0]["wall_seconds"] = 2400

    result["next_actions"][0]["resources"]["memory_mib"] = 0
    validation = validate_result_bundle(result)
    assert not validation.valid
    assert any("memory_mib" in error for error in validation.errors)
