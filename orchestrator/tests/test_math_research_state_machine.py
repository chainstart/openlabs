from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from openlabs.contracts import atomic_write_json

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "labs"
    / "math"
    / "protocols"
    / "research_state_machine.py"
)


def _run(
    *args: str,
    stdin: dict | None = None,
    validation_context: dict | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("OPENLABS_PROTOCOL_VALIDATION_CONTEXT", None)
    if validation_context is not None:
        environment["OPENLABS_PROTOCOL_VALIDATION_CONTEXT"] = json.dumps(
            validation_context
        )
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=(json.dumps(stdin) if stdin is not None else None),
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


def _project(tmp_path: Path, *, binding: dict | None = None) -> tuple[Path, Path]:
    project_path = tmp_path / "project.json"
    state_path = tmp_path / "workstreams" / "candidate-one" / "research_state.json"
    atomic_write_json(
        tmp_path / "research_policy.json",
        binding
        or {
            "schema_version": "openlabs.math_research_policy_binding.v1",
            "policy": {"profile": "open-problem-closure-v1"},
        },
    )
    atomic_write_json(
        project_path,
        {
            "schema_version": "openlabs.project.v1",
            "project_id": "policy-test",
            "domain": "math",
            "status": "active",
            "objective": "Test a configured mathematics research policy.",
            "protocol": {
                "id": "math-state-machine",
                "primary_skill": "math-research-state-machine",
            },
            "domain_config": {"path": "research_policy.json"},
            "workstreams": [
                {
                    "workstream_id": "candidate-one",
                    "state_path": "workstreams/candidate-one/research_state.json",
                    "startup": "active",
                }
            ],
        },
    )
    initialized = _run(
        "init",
        "--project",
        str(project_path),
        "--workstream",
        str(state_path),
        "--workstream-id",
        "candidate-one",
    )
    assert initialized.returncode == 0, initialized.stderr
    return project_path, state_path


def _context(*, task_count: int = 0, agent_seconds: float = 0) -> dict:
    return {
        "schema_version": "openlabs.protocol_hook_context.v1",
        "event": "continuation",
        "campaign": {
            "campaign_id": "candidate-one",
            "domain": "math",
            "project_id": "policy-test",
            "workstream_id": "candidate-one",
            "agent_seconds_used": agent_seconds,
            "max_agent_seconds": 200000,
            "production_epoch": 1,
        },
        "latest_task": None,
        "latest_result": None,
        "routing_usage": {
            "protocol_hook:open-problem-closure-v1:admission_probe": {
                "task_count": task_count,
                "agent_seconds": agent_seconds,
            }
        },
        "project_workstreams": [],
    }


def _attempt_context(project: Path, state: Path) -> dict:
    return {
        "schema_version": "openlabs.protocol_validation_context.v1",
        "event": "attempt_commit",
        "task": {
            "task_id": "actual-task",
            "attempt_id": "attempt-one",
            "agent_role": "researcher",
            "session_mode": "fresh",
            "routing_reason": (
                "protocol_hook:open-problem-closure-v1:admission_probe"
            ),
        },
        "canonical": {
            "project_config": str(project),
            "workstream_state": str(state),
        },
    }


def test_closure_profile_initializes_and_returns_a_bounded_admission_task(tmp_path) -> None:
    project, state = _project(tmp_path)

    validation = _run(
        "validate",
        "--project",
        str(project),
        "--workstream",
        str(state),
        "--mode",
        "discovery",
    )
    decision = _run(
        "decide",
        "--project",
        str(project),
        "--workstream",
        str(state),
        stdin=_context(),
    )

    assert validation.returncode == 0, validation.stdout + validation.stderr
    payload = json.loads(decision.stdout)
    assert payload["decision"] == "continue"
    assert payload["routing_key"] == "open-problem-closure-v1:admission_probe"
    assert payload["action"]["runner"] == "balanced"
    assert payload["action"]["wall_seconds"] == 1800
    assert payload["action"]["resources"]["memory_mib"] == 4096


def test_commit_binds_new_observations_to_the_authenticated_task_and_role(tmp_path) -> None:
    project, canonical = _project(tmp_path)
    context = _attempt_context(project, canonical)

    def staged_state(name: str) -> Path:
        candidate = tmp_path / name / "research_state.json"
        candidate.parent.mkdir(parents=True)
        shutil.copy2(canonical, candidate)
        evidence = candidate.parent / "evidence" / "statement.md"
        evidence.parent.mkdir()
        evidence.write_text("The exact statement is frozen.\n", encoding="utf-8")
        return candidate

    forged = staged_state("forged-attempt")
    observed = _run(
        "observe",
        "--project",
        str(project),
        "--workstream",
        str(forged),
        "--observation-id",
        "forged-observation",
        "--kind",
        "statement_frozen",
        "--verdict",
        "accepted",
        "--actor-role",
        "reviewer",
        "--source-task-id",
        "invented-task",
        "--summary",
        "A forged role and task identity must not pass the commit gate.",
        "--evidence",
        "evidence/statement.md",
    )
    assert observed.returncode == 0, observed.stderr
    rejected = _run(
        "validate",
        "--project",
        str(project),
        "--workstream",
        str(forged),
        "--mode",
        "commit",
        validation_context=context,
    )
    rejected_errors = json.loads(rejected.stdout)["errors"]
    assert rejected.returncode == 1
    assert any("current task_id" in item for item in rejected_errors)
    assert any("current agent role" in item for item in rejected_errors)

    authentic = staged_state("authentic-attempt")
    observed = _run(
        "observe",
        "--project",
        str(project),
        "--workstream",
        str(authentic),
        "--observation-id",
        "authentic-observation",
        "--kind",
        "statement_frozen",
        "--verdict",
        "accepted",
        "--actor-role",
        "researcher",
        "--source-task-id",
        "actual-task",
        "--summary",
        "The scheduled researcher froze the exact statement.",
        "--evidence",
        "evidence/statement.md",
    )
    assert observed.returncode == 0, observed.stderr
    accepted = _run(
        "validate",
        "--project",
        str(project),
        "--workstream",
        str(authentic),
        "--mode",
        "commit",
        validation_context=context,
    )
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr


def test_transition_requires_all_configured_evidence_then_unlocks_bridge(tmp_path) -> None:
    project, state = _project(tmp_path)
    evidence_dir = state.parent / "evidence"
    evidence_dir.mkdir(parents=True)
    evidence_kinds = (
        "statement_frozen",
        "authoritative_source_verified",
        "open_status_verified",
        "duplicate_risk_cleared",
        "decisive_kill_test_defined",
        "bridge_relevance_established",
    )
    observation_ids: list[str] = []
    for index, kind in enumerate(evidence_kinds, start=1):
        evidence = evidence_dir / f"{kind}.md"
        evidence.write_text(f"evidence for {kind}\n", encoding="utf-8")
        observation_id = f"admission-{index}"
        observation_ids.append(observation_id)
        observed = _run(
            "observe",
            "--project",
            str(project),
            "--workstream",
            str(state),
            "--observation-id",
            observation_id,
            "--kind",
            kind,
            "--verdict",
            "accepted",
            "--actor-role",
            "researcher",
            "--source-task-id",
            "admission-task",
            "--summary",
            f"Established {kind}.",
            "--evidence",
            f"evidence/{kind}.md",
        )
        assert observed.returncode == 0, observed.stderr

    incomplete = _run(
        "transition",
        "--project",
        str(project),
        "--workstream",
        str(state),
        "--to",
        "bridge_search",
        "--reason",
        "Try to advance with incomplete evidence.",
        "--observation",
        observation_ids[0],
    )
    assert incomplete.returncode == 2
    assert "evidence gate did not pass" in incomplete.stderr

    arguments = [
        "transition",
        "--project",
        str(project),
        "--workstream",
        str(state),
        "--to",
        "bridge_search",
        "--reason",
        "All admission facts and the closure bridge are now evidence-bound.",
    ]
    for observation_id in observation_ids:
        arguments.extend(("--observation", observation_id))
    advanced = _run(*arguments)
    assert advanced.returncode == 0, advanced.stderr
    current = json.loads(state.read_text(encoding="utf-8"))
    assert current["stage"] == "bridge_search"
    assert current["status"] == "active"


def test_actual_routing_usage_exhausts_stage_without_a_scientific_verdict(tmp_path) -> None:
    project, state = _project(tmp_path)
    decision = _run(
        "decide",
        "--project",
        str(project),
        "--workstream",
        str(state),
        stdin=_context(task_count=2, agent_seconds=1200),
    )

    assert decision.returncode == 0, decision.stderr
    payload = json.loads(decision.stdout)
    assert payload == {
        "schema_version": "openlabs.protocol_hook_decision.v1",
        "decision": "defer",
        "reason": "math_stage_budget_exhausted:admission_probe",
    }


def test_project_stage_capacity_defers_without_marking_math_failure(tmp_path) -> None:
    project, state = _project(
        tmp_path,
        binding={
            "schema_version": "openlabs.math_research_policy_binding.v1",
            "policy": {
                "profile": "open-problem-closure-v1",
                "overrides": {
                    "portfolio": {
                        "max_concurrent_tasks_by_stage": {"admission_probe": 1}
                    }
                },
            },
        },
    )
    peer_path = tmp_path / "workstreams" / "candidate-two" / "research_state.json"
    peer = json.loads(state.read_text(encoding="utf-8"))
    peer["workstream_id"] = "candidate-two"
    atomic_write_json(peer_path, peer)
    context = _context()
    context["project_workstreams"] = [
        {
            "campaign_id": "candidate-two",
            "priority": 1,
            "status": "active",
            "workstream_state_path": str(peer_path),
            "has_active_tasks": False,
            "has_queued_tasks": True,
        }
    ]

    decision = _run(
        "decide",
        "--project",
        str(project),
        "--workstream",
        str(state),
        stdin=context,
    )

    assert decision.returncode == 0, decision.stderr
    assert json.loads(decision.stdout) == {
        "schema_version": "openlabs.protocol_hook_decision.v1",
        "decision": "defer",
        "reason": "math_stage_capacity_wait:admission_probe",
    }
    assert json.loads(state.read_text(encoding="utf-8"))["status"] == "active"


def test_inline_policy_accepts_arbitrary_stage_and_observation_names(tmp_path) -> None:
    policy = {
        "schema_version": "openlabs.math_research_policy.v1",
        "policy_id": "conjecture-garden-v1",
        "description": "A deliberately different configured research graph.",
        "initial_stage": "conjecture_garden",
        "observation_types": {
            "fruit_found": {
                "description": "A useful theorem-shaped result exists.",
                "evidence_required": True,
            }
        },
        "stages": {
            "conjecture_garden": {
                "description": "Explore freely.",
                "task": {
                    "objective": "Explore and choose the mathematics autonomously.",
                    "agent_role": "researcher",
                    "session_mode": "resume",
                    "handoff_kind": "role_handoff",
                    "runner": "cheap",
                    "wall_seconds": 600,
                },
                "budget": {"max_tasks": 3, "on_exhaustion": "pause"},
                "transitions": [
                    {
                        "to": "harvest",
                        "requires": {"all": [{"kind": "fruit_found"}]},
                    }
                ],
            },
            "harvest": {
                "description": "Preserve the result.",
                "terminal": True,
                "completion": "completed",
                "transitions": [],
            },
        },
    }
    project, state = _project(
        tmp_path,
        binding={
            "schema_version": "openlabs.math_research_policy_binding.v1",
            "policy": {"inline": policy},
        },
    )
    context = _context()
    context["routing_usage"] = {}
    decision = _run(
        "decide",
        "--project",
        str(project),
        "--workstream",
        str(state),
        stdin=context,
    )

    assert decision.returncode == 0, decision.stderr
    payload = json.loads(decision.stdout)
    assert payload["routing_key"] == "conjecture-garden-v1:conjecture_garden"
    assert payload["action"]["runner"] == "cheap"
    assert payload["action"]["wall_seconds"] == 600


def test_compatible_policy_change_requires_an_audited_rebind(tmp_path) -> None:
    project, state = _project(tmp_path)
    old_state = json.loads(state.read_text(encoding="utf-8"))
    binding_path = tmp_path / "research_policy.json"
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    binding["policy"]["overrides"] = {
        "stages": {"admission_probe": {"task": {"wall_seconds": 900}}}
    }
    atomic_write_json(binding_path, binding)

    rejected = _run(
        "validate",
        "--project",
        str(project),
        "--workstream",
        str(state),
        "--mode",
        "commit",
    )
    assert rejected.returncode == 1
    assert "policy_digest" in rejected.stdout

    rebound = _run(
        "rebind-policy",
        "--project",
        str(project),
        "--workstream",
        str(state),
        "--expected-old-digest",
        old_state["policy_digest"],
        "--reason",
        "Reduce only the admission episode ceiling for this project.",
    )
    assert rebound.returncode == 0, rebound.stderr
    current = json.loads(state.read_text(encoding="utf-8"))
    assert current["policy_digest"] != old_state["policy_digest"]
    assert current["policy_rebindings"][-1]["old_digest"] == old_state["policy_digest"]

    decision = _run(
        "decide",
        "--project",
        str(project),
        "--workstream",
        str(state),
        stdin=_context(),
    )
    assert json.loads(decision.stdout)["action"]["wall_seconds"] == 900


def test_pause_requires_an_explicit_audited_resume(tmp_path) -> None:
    project, state = _project(tmp_path)

    paused = _run(
        "pause",
        "--project",
        str(project),
        "--workstream",
        str(state),
        "--reason",
        "The current route needs operator review before more allocation.",
    )
    assert paused.returncode == 0, paused.stderr
    assert json.loads(state.read_text(encoding="utf-8"))["status"] == "paused"

    resumed = _run(
        "resume",
        "--project",
        str(project),
        "--workstream",
        str(state),
        "--reason",
        "The review approved another bounded research episode.",
    )
    assert resumed.returncode == 0, resumed.stderr
    current = json.loads(state.read_text(encoding="utf-8"))
    assert current["status"] == "active"
    assert [item["decision"] for item in current["dispositions"]] == [
        "paused_by_research_agent",
        "resumed",
    ]


def test_gate_can_require_independent_observations_from_distinct_tasks(tmp_path) -> None:
    policy = {
        "schema_version": "openlabs.math_research_policy.v1",
        "policy_id": "double-audit-v1",
        "description": "Require two task-distinct reviewer observations.",
        "initial_stage": "audit",
        "observation_types": {
            "audit_passed": {
                "description": "One independent reconstruction passed.",
                "evidence_required": False,
            }
        },
        "stages": {
            "audit": {
                "description": "Run independent audits.",
                "task": {
                    "objective": "Reconstruct the result independently.",
                    "agent_role": "reviewer",
                    "session_mode": "fresh",
                    "handoff_kind": "adversarial_review",
                    "runner": "frontier",
                    "wall_seconds": 600,
                },
                "transitions": [
                    {
                        "to": "done",
                        "requires": {
                            "all": [
                                {
                                    "kind": "audit_passed",
                                    "actor_role": "reviewer",
                                    "min_count": 2,
                                    "distinct_source_tasks": True,
                                }
                            ]
                        },
                    }
                ],
            },
            "done": {
                "description": "Two audits passed.",
                "terminal": True,
                "completion": "completed",
                "transitions": [],
            },
        },
    }
    project, state = _project(
        tmp_path,
        binding={
            "schema_version": "openlabs.math_research_policy_binding.v1",
            "policy": {"inline": policy},
        },
    )

    def observe(observation_id: str, source_task_id: str) -> None:
        result = _run(
            "observe",
            "--project",
            str(project),
            "--workstream",
            str(state),
            "--observation-id",
            observation_id,
            "--kind",
            "audit_passed",
            "--verdict",
            "accepted",
            "--actor-role",
            "reviewer",
            "--source-task-id",
            source_task_id,
            "--summary",
            "The reconstruction passed.",
        )
        assert result.returncode == 0, result.stderr

    observe("audit-one", "review-task-one")
    observe("audit-two", "review-task-one")
    repeated = _run(
        "transition",
        "--project",
        str(project),
        "--workstream",
        str(state),
        "--to",
        "done",
        "--reason",
        "Two labels from only one task are insufficient.",
        "--observation",
        "audit-one",
        "--observation",
        "audit-two",
    )
    assert repeated.returncode == 2

    observe("audit-three", "review-task-two")
    independent = _run(
        "transition",
        "--project",
        str(project),
        "--workstream",
        str(state),
        "--to",
        "done",
        "--reason",
        "Two fresh task lineages reconstructed the result.",
        "--observation",
        "audit-one",
        "--observation",
        "audit-three",
    )
    assert independent.returncode == 0, independent.stderr
    assert json.loads(state.read_text(encoding="utf-8"))["status"] == "completed"
