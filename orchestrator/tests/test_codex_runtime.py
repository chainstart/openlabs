from __future__ import annotations

import json

import pytest
from openlabs.agent_runtime import configure_codex_runtime, runtime_context
from openlabs.codex_hook import _append_hook_receipt, _session_context, _stop_decision
from openlabs.contracts import RESULT_SCHEMA, atomic_write_json


def _skill(path, name: str) -> None:
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Test Skill.\n---\n\n# Test\n",
        encoding="utf-8",
    )


def test_attempt_runtime_exposes_skills_and_checks_result_before_stop(tmp_path) -> None:
    workspace = tmp_path / "attempt" / "campaign"
    workspace.mkdir(parents=True)
    factory_skill = tmp_path / "code" / "factory-skill"
    domain_skill = tmp_path / "code" / "domain-skill"
    _skill(factory_skill, "factory-skill")
    _skill(domain_skill, "domain-skill")
    result = workspace / "results" / "result.json"
    task = {
        "task_id": "task-1",
        "campaign_id": "campaign",
        "lab_id": "math",
        "domain": "math",
        "objective": "Advance a theorem.",
        "agent": {"role": "researcher"},
        "transaction": {"canonical_campaign_workspace": "/canonical/campaign"},
    }

    policy = configure_codex_runtime(
        workspace,
        task=task,
        output_path=result,
        skill_dirs=(factory_skill, domain_skill),
    )

    assert policy["sandbox"] == "workspace-write"
    assert policy["skills"] == ["$factory-skill", "$domain-skill"]
    assert (workspace / ".agents" / "skills" / "factory-skill").resolve() == factory_skill
    hooks = json.loads((workspace / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    assert set(hooks["hooks"]) == {"SessionStart", "Stop"}
    context = runtime_context(workspace / ".codex" / "openlabs-context.json")
    session = _session_context(context)
    assert "$factory-skill" in session["hookSpecificOutput"]["additionalContext"]
    assert _stop_decision({}, context)["decision"] == "block"

    atomic_write_json(
        result,
        {
            "schema_version": RESULT_SCHEMA,
            "task_id": "task-1",
            "campaign_id": "campaign",
            "lab_id": "math",
            "domain": "math",
            "status": "completed",
            "summary": "A valid transport checkpoint.",
            "artifacts": [],
            "claims": [],
            "next_actions": [],
        },
    )
    assert _stop_decision({}, context) == {}


def test_stop_hook_cannot_create_an_infinite_continue_loop(tmp_path) -> None:
    context = {
        "result_path": str(tmp_path / "missing.json"),
        "expected_result": {},
    }

    assert _stop_decision({"stop_hook_active": True}, context) == {}


def _authority_policy(path) -> None:
    (path / "authority-policy.json").write_text(
        json.dumps(
            {
                "schema_version": "openlabs.authority_policy.v1",
                "policy_id": "test-phase-authority",
                "state_glob": "**/campaign_state.json",
                "state_schema_version": "test-state.v1",
                "phase_field": "phase",
                "exclude_path_parts": ["evidence", "audit", "results"],
                "phase_authority": {
                    "research": {
                        "allowed_roles": ["researcher"],
                        "default_role": "researcher",
                    },
                    "independent_audit": {
                        "allowed_roles": ["reviewer"],
                        "default_role": "reviewer",
                        "required_session_mode": "fresh",
                        "required_handoff_kind": "independent_replication",
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def test_skill_authority_rejects_creator_at_audit_and_gates_successor(tmp_path) -> None:
    workspace = tmp_path / "attempt" / "campaign"
    workspace.mkdir(parents=True)
    domain_skill = tmp_path / "domain-skill"
    _skill(domain_skill, "domain-skill")
    _authority_policy(domain_skill)
    atomic_write_json(
        workspace / "nested" / "campaign_state.json",
        {
            "schema_version": "test-state.v1",
            "phase": "independent_audit",
            "updated_at": "2026-08-12T00:00:00Z",
        },
    )
    atomic_write_json(
        workspace / "nested" / "evidence" / "snapshot" / "campaign_state.json",
        {
            "schema_version": "test-state.v1",
            "phase": "research",
            "updated_at": "2026-08-12T01:00:00Z",
        },
    )
    base_task = {
        "task_id": "task-audit",
        "campaign_id": "campaign",
        "lab_id": "math",
        "domain": "math",
        "objective": "Independently reconstruct the claim.",
        "transaction": {"canonical_campaign_workspace": "/canonical/campaign"},
    }
    with pytest.raises(ValueError, match="allows roles"):
        configure_codex_runtime(
            workspace,
            task={
                **base_task,
                "agent": {"role": "researcher", "session_mode": "fresh"},
            },
            output_path=workspace / "result.json",
            skill_dirs=(domain_skill,),
        )

    result_path = workspace / "result.json"
    policy = configure_codex_runtime(
        workspace,
        task={
            **base_task,
            "agent": {"role": "reviewer", "session_mode": "fresh"},
        },
        output_path=result_path,
        skill_dirs=(domain_skill,),
    )
    assert policy["authority"]["phase"] == "independent_audit"
    context = runtime_context(workspace / ".codex" / "openlabs-context.json")
    payload = {
        "schema_version": RESULT_SCHEMA,
        "task_id": "task-audit",
        "campaign_id": "campaign",
        "lab_id": "math",
        "domain": "math",
        "status": "completed",
        "summary": "One reconstruction checkpoint completed.",
        "artifacts": [],
        "claims": [],
        "next_actions": ["Repeat the audit."],
    }
    atomic_write_json(result_path, payload)
    blocked = _stop_decision({}, context)
    assert blocked["decision"] == "block"
    assert "requires session_mode 'fresh'" in blocked["reason"]

    payload["next_actions"] = [
        {
            "objective": "Repeat the reconstruction from frozen evidence.",
            "agent_role": "reviewer",
            "session_mode": "fresh",
            "handoff_kind": "independent_replication",
        }
    ]
    atomic_write_json(result_path, payload)
    assert _stop_decision({}, context) == {}


def test_hook_persists_structured_receipt(tmp_path) -> None:
    workspace = tmp_path / "attempt" / "campaign"
    receipt_path = workspace / ".codex" / "hook-receipts.jsonl"
    context = {
        "agent_workspace": str(workspace),
        "hook_receipt_path": str(receipt_path),
    }
    _append_hook_receipt(
        context,
        event_name="stop",
        event={"session_id": "session-1", "turn_id": "turn-1"},
        output={},
        started_at="2026-08-12T00:00:00.000Z",
        finished_at="2026-08-12T00:00:00.001Z",
    )

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["hook_event_name"] == "Stop"
    assert receipt["outcome"] == "result_gate_passed"
    assert receipt["exit_code"] == 0
    assert receipt["session_id"] == "session-1"
