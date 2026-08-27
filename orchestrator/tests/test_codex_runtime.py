from __future__ import annotations

import json

from openlabs.agent_runtime import configure_codex_runtime, runtime_context
from openlabs.codex_hook import (
    _append_hook_receipt,
    _session_context,
    _stop_decision,
    _stop_evaluation,
)
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

    assert policy["sandbox"] == "danger-full-access"
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

    event = {"stop_hook_active": True}
    assert _stop_decision(event, context) == {}
    output, outcome, summary = _stop_evaluation(event, context)
    assert output == {}
    assert outcome == "result_gate_failed_final"
    assert "required result file is missing" in summary


def test_stop_hook_reentry_revalidates_completed_result(tmp_path) -> None:
    result = tmp_path / "result.json"
    receipt_path = tmp_path / ".codex" / "hook-receipts.jsonl"
    context = {
        "result_path": str(result),
        "expected_result": {
            "task_id": "task-1",
            "campaign_id": "campaign",
            "lab_id": "math",
            "domain": "math",
        },
        "agent_workspace": str(tmp_path),
        "hook_receipt_path": str(receipt_path),
    }
    atomic_write_json(
        result,
        {
            "schema_version": RESULT_SCHEMA,
            "task_id": "task-1",
            "campaign_id": "campaign",
            "lab_id": "math",
            "domain": "math",
            "status": "completed",
            "summary": "The continuation completed the required result.",
            "artifacts": [],
            "claims": [],
            "next_actions": [],
        },
    )

    output, outcome, summary = _stop_evaluation({"stop_hook_active": True}, context)

    assert output == {}
    assert outcome == "result_gate_passed"
    assert summary == "result_gate_passed"
    _append_hook_receipt(
        context,
        event_name="stop",
        event={"stop_hook_active": True},
        output=output,
        started_at="2026-08-12T00:00:00.000Z",
        finished_at="2026-08-12T00:00:00.001Z",
        outcome=outcome,
        output_summary=summary,
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["stop_hook_active"] is True
    assert receipt["outcome"] == "result_gate_passed"


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


def test_hook_persists_terminal_reentry_failure(tmp_path) -> None:
    workspace = tmp_path / "attempt" / "campaign"
    receipt_path = workspace / ".codex" / "hook-receipts.jsonl"
    context = {
        "agent_workspace": str(workspace),
        "hook_receipt_path": str(receipt_path),
    }
    _append_hook_receipt(
        context,
        event_name="stop",
        event={"stop_hook_active": True},
        output={},
        started_at="2026-08-12T00:00:00.000Z",
        finished_at="2026-08-12T00:00:00.001Z",
        outcome="result_gate_failed_final",
        output_summary="required result remains missing",
    )

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["stop_hook_active"] is True
    assert receipt["outcome"] == "result_gate_failed_final"
    assert receipt["output_summary"] == "required result remains missing"
