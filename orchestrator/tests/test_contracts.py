from __future__ import annotations

import json
from pathlib import Path

from openlabs.contracts import sha256_file, validate_result_bundle, validate_task
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


def test_task_contract_accepts_complete_project_execution_envelope() -> None:
    task = json.loads(
        (CODE_ROOT / "packages/contracts/examples/smoke-task.json").read_text(
            encoding="utf-8"
        )
    )
    task["project"] = {
        "config_path": "/attempt/workspaces/math/project.json",
        "workstream_state_path": "/attempt/workspaces/math/state.json",
        "protocol_id": "amra-math",
    }
    task["execution_policy"] = {
        "default_session_mode": "resume",
        "fresh_session_boundaries": ["adversarial_review", "route_reselection"],
    }

    assert validate_task(task).valid


def test_task_contract_accepts_artifact_boundary_and_rejects_partial_policy() -> None:
    task = json.loads(
        (CODE_ROOT / "packages/contracts/examples/smoke-task.json").read_text(encoding="utf-8")
    )
    task["transaction"] = {
        "mode": "isolated_attempt_workspace",
        "attempt_root": "/workspace/artifacts/attempt",
        "staged_campaign_workspace": "/workspace/artifacts/attempt/workspaces/math/campaign",
        "canonical_campaign_workspace": "/workspace/data/workspaces/math/campaign",
        "artifact_staging_root": "/workspace/artifacts/attempt/artifact-stage",
        "artifact_policy": {
            "schema_version": "openlabs.artifact_policy.v1",
            "max_data_file_bytes": 5 * 1024 * 1024,
            "max_changed_files": 1000,
            "max_changed_bytes": 50 * 1024 * 1024,
            "artifact_only_suffixes": [".jsonl", ".parquet"],
            "undeclared_staging_policy": "reject",
        },
        "promotion_policy": "validated_results_and_checkpoints",
    }

    assert validate_task(task).valid

    task["transaction"]["artifact_policy"]["artifact_only_suffixes"] = []
    task["transaction"]["artifact_policy"]["undeclared_staging_policy"] = "ignore"
    validation = validate_task(task)
    assert not validation.valid
    assert any("artifact_only_suffixes" in error for error in validation.errors)
    assert any("undeclared_staging_policy" in error for error in validation.errors)


def test_task_contract_rejects_partial_or_ill_typed_execution_policy() -> None:
    task = json.loads(
        (CODE_ROOT / "packages/contracts/examples/smoke-task.json").read_text(
            encoding="utf-8"
        )
    )
    task["project"] = {
        "config_path": "/attempt/project.json",
        "workstream_state_path": "/attempt/state.json",
        "protocol_id": "amra-math",
    }
    validation = validate_task(task)
    assert not validation.valid
    assert "project and execution_policy must be supplied together" in validation.errors

    task["execution_policy"] = {
        "default_session_mode": "resume",
        "fresh_session_boundaries": ["unknown_boundary"],
    }
    validation = validate_task(task)
    assert not validation.valid
    assert any("unknown kinds" in error for error in validation.errors)


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


def test_gate_classifies_missing_executable_closure_as_reproducibility(tmp_path) -> None:
    script = tmp_path / "verify.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    payload = {
        "schema_version": "openlabs.result_bundle.v1",
        "task_id": "task-replay",
        "campaign_id": "campaign",
        "lab_id": "math",
        "domain": "math",
        "status": "completed",
        "summary": "A script was emitted without its replay closure.",
        "artifacts": [
            {
                "artifact_id": "validator",
                "uri": script.resolve().as_uri(),
                "sha256": sha256_file(script),
                "kind": "verification_script",
            }
        ],
        "claims": [],
        "next_actions": [],
    }

    gate = evaluate_result_bundle(payload, allowed_roots=(tmp_path,))

    assert not gate.passed
    assert "reproducibility" in gate.failure_classes


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


def test_result_contract_accepts_reviewer_selected_candidate_branches() -> None:
    result = json.loads(
        (CODE_ROOT / "packages/contracts/examples/smoke-result.json").read_text(
            encoding="utf-8"
        )
    )
    result["candidate_branches"] = [
        {
            "candidate_id": "negative-theorem-sharp-boundary",
            "title": "A sharp obstruction theorem",
            "objective": "Determine the maximal natural scope and prove or refute it.",
            "rationale": "The reviewed computation exposes a stable structural obstruction.",
            "source_result_ids": ["research-task-7"],
        }
    ]

    assert validate_result_bundle(result).valid

    result["candidate_branches"][0]["source_result_ids"] = []
    validation = validate_result_bundle(result)
    assert not validation.valid
    assert any("source_result_ids" in error for error in validation.errors)
