from __future__ import annotations

import json

import pytest

from openlabs.config import FactorySettings, WorkspacePaths
from openlabs.contracts import RECEIPT_SCHEMA, RESULT_SCHEMA, atomic_write_json, sha256_file
from openlabs.db import FactoryDB
from openlabs.engine import (
    TickReport,
    _next_action_plan,
    _replenish_continuous_campaign,
    ingest_results,
)


def _start_task(db: FactoryDB, task_id: str, output: str, *, lab_id: str) -> dict:
    task = db.claim_next_task(owner=f"test:{task_id}", lease_seconds=60)
    assert task is not None and task["task_id"] == task_id
    attempt_id = str(task["current_attempt_id"])
    db.bind_attempt_spec(
        task_id,
        attempt_id=attempt_id,
        lab_id=lab_id,
        output_path=output,
    )
    db.mark_running(
        task_id,
        attempt_id=attempt_id,
        owner=f"test:{task_id}",
        pid=123,
        lease_seconds=60,
    )
    return db.task(task_id) or {}


def _receipt(
    task: dict,
    result: str,
    digest: str,
    *,
    session_id: str | None = None,
    failure_class: str | None = None,
) -> dict:
    return {
        "schema_version": RECEIPT_SCHEMA,
        "task_id": task["task_id"],
        "attempt_id": task["current_attempt_id"],
        "campaign_id": task["campaign_id"],
        "lab_id": task["lab_id"],
        "domain": task["domain"],
        "agent_role": task["agent_role"],
        "result_path": result,
        "sha256": digest,
        "runtime": {
            "duration_seconds": 1.0,
            "exit_code": 0,
            "session_id": session_id,
            "failure_class": failure_class,
        },
    }


def test_independent_replication_forces_a_fresh_same_role_session() -> None:
    plan = _next_action_plan(
        {
            "objective": "Repeat the frozen experiment without inheriting its interpretation.",
            "agent_role": "experimenter",
            "session_mode": "resume",
            "handoff_kind": "independent_replication",
            "wall_seconds": 2400,
        },
        current_role="experimenter",
    )

    assert plan is not None
    assert plan.session_mode == "fresh"
    assert plan.wall_seconds == 2400


@pytest.mark.parametrize(
    "directive",
    [
        "No automatic continuation is requested. If separately authorized, audit it.",
        "Do not automatically continue this route.",
    ],
)
def test_negative_prose_directive_is_not_an_action(directive: str) -> None:
    assert _next_action_plan(directive, current_role="researcher") is None


def test_static_project_honors_paused_workstream_state(tmp_path) -> None:
    paths = WorkspacePaths(
        workspace=tmp_path,
        code=tmp_path / "openlabs",
        data=tmp_path / "data",
        artifacts=tmp_path / "artifacts",
        database=tmp_path / "database",
        database_file=tmp_path / "database" / "live" / "factory.sqlite",
    )
    paths.ensure_runtime_directories()
    state_path = atomic_write_json(tmp_path / "state.json", {"status": "paused"})
    db = FactoryDB(paths.database_file)
    db.initialize()
    db.register_campaign("static-paused", domain="math", title="Static project")
    db.configure_project_campaign(
        "static-paused",
        project_config_path=str(tmp_path / "project.json"),
        workstream_state_path=str(state_path),
        protocol_id="autonomous-math",
        primary_skill="math-autonomous-research",
        execution_policy={"default_session_mode": "resume"},
        workstream_policy={"continuation": "continuous"},
    )

    report = TickReport()
    campaign = db.campaign("static-paused")
    assert campaign is not None
    _replenish_continuous_campaign(
        db,
        paths,
        FactorySettings(max_auto_tasks_per_campaign=4),
        report,
        campaign,
    )

    assert report.production_paused == ["static-paused"]
    assert db.task_count("static-paused") == 0
    assert db.campaign("static-paused")["status"] == "production_paused"


def test_valid_next_action_enqueues_one_bounded_successor(tmp_path) -> None:
    paths = WorkspacePaths(
        workspace=tmp_path,
        code=tmp_path / "openlabs",
        data=tmp_path / "data",
        artifacts=tmp_path / "artifacts",
        database=tmp_path / "database",
        database_file=tmp_path / "database" / "live" / "factory.sqlite",
    )
    paths.ensure_runtime_directories()
    db = FactoryDB(paths.database_file)
    db.initialize()
    db.register_campaign("campaign-1", domain="ai", title="Campaign")
    db.enqueue_task(
        task_id="research-1",
        campaign_id="campaign-1",
        domain="ai",
        task_type="research",
        objective="Run one bounded pilot.",
        input_path=str(paths.data / "workspaces" / "ai" / "campaign-1"),
        skill_path="ai-research-loop",
        runner="cheap",
    )
    result_root = paths.data / "workspaces" / "ai" / "campaign-1" / "results" / "research-1"
    result = atomic_write_json(
        result_root / "result.json",
        {
            "schema_version": RESULT_SCHEMA,
            "task_id": "research-1",
            "campaign_id": "campaign-1",
            "lab_id": "ai",
            "domain": "ai",
            "status": "completed",
            "summary": "The pilot completed without a promoted claim.",
            "artifacts": [],
            "claims": [],
            "next_actions": ["Run the frozen two-seed falsification experiment."],
            "paper_candidate": False,
        },
    )
    task = _start_task(db, "research-1", str(result), lab_id="ai")
    atomic_write_json(
        paths.result_inbox / "research-1.json",
        _receipt(task, str(result), sha256_file(result), session_id="session-1"),
    )

    report = TickReport()
    ingest_results(db, paths, FactorySettings(max_auto_tasks_per_campaign=2), report)

    assert len(report.enqueued) == 1
    successor = db.task(report.enqueued[0])
    assert successor is not None
    assert successor["task_type"] == "research_continue"
    assert successor["objective"] == "Run the frozen two-seed falsification experiment."
    assert successor["runner"] == "cheap"
    assert successor["agent_role"] == "researcher"
    assert successor["agent_session_id"] == "session-1"
    assert successor["parent_task_id"] == "research-1"


def test_explicit_freeze_does_not_execute_prose_next_action(tmp_path) -> None:
    paths = WorkspacePaths(
        workspace=tmp_path,
        code=tmp_path / "openlabs",
        data=tmp_path / "data",
        artifacts=tmp_path / "artifacts",
        database=tmp_path / "database",
        database_file=tmp_path / "database" / "live" / "factory.sqlite",
    )
    paths.ensure_runtime_directories()
    db = FactoryDB(paths.database_file)
    db.initialize()
    db.register_campaign("campaign-freeze", domain="math", title="Campaign")
    db.enqueue_task(
        task_id="audit-freeze",
        campaign_id="campaign-freeze",
        domain="math",
        task_type="research",
        objective="Independently audit the frozen result.",
        skill_path="amra-research-loop",
        runner="frontier",
    )
    result = atomic_write_json(
        paths.data / "workspaces" / "math" / "campaign-freeze" / "result.json",
        {
            "schema_version": RESULT_SCHEMA,
            "task_id": "audit-freeze",
            "campaign_id": "campaign-freeze",
            "lab_id": "math",
            "domain": "math",
            "status": "completed",
            "summary": "The local theorem reconstructs, but promotion is frozen.",
            "artifacts": [],
            "claims": [],
            "next_actions": ["Do not initiate paper writing or promotion."],
            "paper_candidate": False,
            "gate_result": {"promotion_decision": "freeze"},
        },
    )
    task = _start_task(db, "audit-freeze", str(result), lab_id="math")
    atomic_write_json(
        paths.result_inbox / "audit-freeze.json",
        _receipt(task, str(result), sha256_file(result), session_id="audit-session"),
    )

    report = TickReport()
    ingest_results(db, paths, FactorySettings(max_auto_tasks_per_campaign=2), report)

    assert report.enqueued == []
    assert db.task("audit-freeze")["status"] == "succeeded"


def test_needs_replan_escalates_but_needs_human_stops(tmp_path) -> None:
    paths = WorkspacePaths(
        workspace=tmp_path,
        code=tmp_path / "openlabs",
        data=tmp_path / "data",
        artifacts=tmp_path / "artifacts",
        database=tmp_path / "database",
        database_file=tmp_path / "database" / "live" / "factory.sqlite",
    )
    paths.ensure_runtime_directories()
    db = FactoryDB(paths.database_file)
    db.initialize()
    for index, (task_id, status) in enumerate(
        (("route-1", "needs_replan"), ("route-2", "needs_human")),
        start=1,
    ):
        campaign_id = f"campaign-{index}"
        db.register_campaign(campaign_id, domain="math", title="Campaign")
        db.enqueue_task(
            task_id=task_id,
            campaign_id=campaign_id,
            domain="math",
            task_type="research",
            objective="Test a route.",
            skill_path="amra-research-loop",
            runner="balanced",
        )
        result = atomic_write_json(
            paths.data / "workspaces" / "math" / campaign_id / task_id / "result.json",
            {
                "schema_version": RESULT_SCHEMA,
                "task_id": task_id,
                "campaign_id": campaign_id,
                "lab_id": "math",
                "domain": "math",
                "status": status,
                "summary": "The current route cannot proceed as stated.",
                "artifacts": [],
                "claims": [],
                "next_actions": ["Replan from the recorded obstruction."],
            },
        )
        task = _start_task(db, task_id, str(result), lab_id="math")
        atomic_write_json(
            paths.result_inbox / f"{task_id}.json",
            _receipt(task, str(result), sha256_file(result)),
        )

    report = TickReport()
    ingest_results(db, paths, FactorySettings(max_auto_tasks_per_campaign=4), report)

    assert len(report.enqueued) == 1
    successor = db.task(report.enqueued[0])
    assert successor is not None
    assert successor["task_type"] == "replan"
    assert successor["runner"] == "frontier"
    assert successor["agent_role"] == "researcher"
    assert successor["session_mode"] == "fresh"
    assert successor["agent_session_id"] is None


@pytest.mark.parametrize("result_status", ["completed", "needs_replan"])
def test_legacy_one_shot_metadata_no_longer_stops_research(
    tmp_path, result_status: str
) -> None:
    paths = WorkspacePaths(
        workspace=tmp_path,
        code=tmp_path / "openlabs",
        data=tmp_path / "data",
        artifacts=tmp_path / "artifacts",
        database=tmp_path / "database",
        database_file=tmp_path / "database" / "live" / "factory.sqlite",
    )
    paths.ensure_runtime_directories()
    db = FactoryDB(paths.database_file)
    db.initialize()
    db.register_campaign("one-shot", domain="math", title="One bounded round")
    with db.connect() as connection:
        connection.execute(
            """
            UPDATE campaigns
            SET continuous=1, workstream_policy_json=?
            WHERE campaign_id='one-shot'
            """,
            (json.dumps({"continuation": "one_shot"}),),
        )
    db.enqueue_task(
        task_id="one-shot-task",
        campaign_id="one-shot",
        domain="math",
        task_type="research",
        objective="Run exactly one bounded research round.",
        skill_path="amra-research-loop",
    )
    result = atomic_write_json(
        paths.data / "workspaces" / "math" / "one-shot" / "result.json",
        {
            "schema_version": RESULT_SCHEMA,
            "task_id": "one-shot-task",
            "campaign_id": "one-shot",
            "lab_id": "math",
            "domain": "math",
            "status": result_status,
            "summary": "The bounded round ended with an explicit next action.",
            "artifacts": [],
            "claims": [],
            "next_actions": ["Continue with another bounded route."],
            "paper_candidate": False,
        },
    )
    task = _start_task(db, "one-shot-task", str(result), lab_id="math")
    atomic_write_json(
        paths.result_inbox / "one-shot-task.json",
        _receipt(task, str(result), sha256_file(result), session_id="bounded-session"),
    )
    report = TickReport()

    ingest_results(db, paths, FactorySettings(max_auto_tasks_per_campaign=4), report)

    assert len(report.enqueued) == 1
    assert report.rollovers == []
    assert db.task_count("one-shot") == 2
    pause_report = TickReport()
    campaign = db.campaign("one-shot")
    assert campaign is not None
    _replenish_continuous_campaign(
        db,
        paths,
        FactorySettings(max_auto_tasks_per_campaign=4),
        pause_report,
        campaign,
    )
    assert pause_report.production_paused == []
    assert db.campaign("one-shot")["status"] == "active"


def test_missing_agent_bundle_retries_the_original_objective(tmp_path) -> None:
    paths = WorkspacePaths(
        workspace=tmp_path,
        code=tmp_path / "openlabs",
        data=tmp_path / "data",
        artifacts=tmp_path / "artifacts",
        database=tmp_path / "database",
        database_file=tmp_path / "database" / "live" / "factory.sqlite",
    )
    paths.ensure_runtime_directories()
    db = FactoryDB(paths.database_file)
    db.initialize()
    db.register_campaign("campaign-infra", domain="math", title="Campaign")
    original_objective = "Run the frozen first kill test without changing the target."
    db.enqueue_task(
        task_id="research-infra",
        campaign_id="campaign-infra",
        domain="math",
        task_type="research_continue",
        objective=original_objective,
        skill_path="math-production-supervisor",
        runner="frontier",
        max_wall_seconds=3600,
    )
    result = atomic_write_json(
        paths.data / "workspaces" / "math" / "campaign-infra" / "result.json",
        {
            "schema_version": RESULT_SCHEMA,
            "task_id": "research-infra",
            "campaign_id": "campaign-infra",
            "lab_id": "math",
            "domain": "math",
            "status": "needs_replan",
            "summary": "No scientific result bundle was emitted.",
            "artifacts": [],
            "claims": [],
            "next_actions": [
                "Inspect the bounded agent logs and repair the runner or task prompt."
            ],
            "paper_candidate": False,
        },
    )
    task = _start_task(db, "research-infra", str(result), lab_id="math")
    atomic_write_json(
        paths.result_inbox / "research-infra.json",
        _receipt(
            task,
            str(result),
            sha256_file(result),
            failure_class="agent_transport",
        ),
    )

    report = TickReport()
    ingest_results(db, paths, FactorySettings(max_auto_tasks_per_campaign=3), report)

    assert len(report.enqueued) == 1
    successor = db.task(report.enqueued[0])
    assert successor is not None
    assert successor["routing_reason"] == "infrastructure_retry"
    assert original_objective in successor["objective"]
    assert successor["session_mode"] == "fresh"
    assert successor["max_wall_seconds"] == 3600


def test_structured_handoff_starts_an_independent_experimenter(tmp_path) -> None:
    paths = WorkspacePaths(
        workspace=tmp_path,
        code=tmp_path / "openlabs",
        data=tmp_path / "data",
        artifacts=tmp_path / "artifacts",
        database=tmp_path / "database",
        database_file=tmp_path / "database" / "live" / "factory.sqlite",
    )
    paths.ensure_runtime_directories()
    db = FactoryDB(paths.database_file)
    db.initialize()
    db.register_campaign("campaign-handoff", domain="ai", title="Campaign")
    db.enqueue_task(
        task_id="design-experiment",
        campaign_id="campaign-handoff",
        domain="ai",
        task_type="research",
        objective="Freeze one falsification protocol.",
        skill_path="ai-research-loop",
        runner="balanced",
    )
    result = atomic_write_json(
        paths.data / "workspaces" / "ai" / "campaign-handoff" / "design-experiment" / "result.json",
        {
            "schema_version": RESULT_SCHEMA,
            "task_id": "design-experiment",
            "campaign_id": "campaign-handoff",
            "lab_id": "ai",
            "domain": "ai",
            "status": "completed",
            "summary": "The protocol and kill criterion are frozen.",
            "artifacts": [],
            "claims": [],
            "next_actions": [
                {
                    "objective": "Execute the frozen protocol without changing it.",
                    "agent_role": "experimenter",
                    "session_mode": "resume",
                }
            ],
            "paper_candidate": False,
        },
    )
    task = _start_task(db, "design-experiment", str(result), lab_id="ai")
    atomic_write_json(
        paths.result_inbox / "design-experiment.json",
        _receipt(task, str(result), sha256_file(result), session_id="research-session"),
    )

    report = TickReport()
    ingest_results(db, paths, FactorySettings(max_auto_tasks_per_campaign=2), report)

    assert len(report.enqueued) == 1
    successor = db.task(report.enqueued[0])
    assert successor is not None
    assert successor["task_type"] == "experiment_continue"
    assert successor["agent_role"] == "experimenter"
    assert successor["session_mode"] == "fresh"
    assert successor["agent_session_id"] is None
    assert successor["input_path"] == db.task("design-experiment")["result_path"]
    assert "result-bundles" in successor["input_path"]
    assert successor["routing_reason"] == "role_handoff"


def test_creator_cannot_handoff_directly_to_a_new_writer(tmp_path) -> None:
    paths = WorkspacePaths(
        workspace=tmp_path,
        code=tmp_path / "openlabs",
        data=tmp_path / "data",
        artifacts=tmp_path / "artifacts",
        database=tmp_path / "database",
        database_file=tmp_path / "database" / "live" / "factory.sqlite",
    )
    paths.ensure_runtime_directories()
    db = FactoryDB(paths.database_file)
    db.initialize()
    db.register_campaign("campaign-no-self-promotion", domain="ai", title="Campaign")
    db.enqueue_task(
        task_id="creator",
        campaign_id="campaign-no-self-promotion",
        domain="ai",
        task_type="research",
        objective="Evaluate one claim.",
        skill_path="ai-research-loop",
    )
    result = atomic_write_json(
        paths.data / "workspaces" / "ai" / "campaign-no-self-promotion" / "creator" / "result.json",
        {
            "schema_version": RESULT_SCHEMA,
            "task_id": "creator",
            "campaign_id": "campaign-no-self-promotion",
            "lab_id": "ai",
            "domain": "ai",
            "status": "completed",
            "summary": "The creator requests a manuscript without an independent audit.",
            "artifacts": [],
            "claims": [],
            "next_actions": [
                {
                    "objective": "Write the paper.",
                    "agent_role": "writer",
                    "session_mode": "fresh",
                }
            ],
            "paper_candidate": False,
        },
    )
    task = _start_task(db, "creator", str(result), lab_id="ai")
    atomic_write_json(
        paths.result_inbox / "creator.json",
        _receipt(task, str(result), sha256_file(result), session_id="creator-session"),
    )

    report = TickReport()
    ingest_results(db, paths, FactorySettings(max_auto_tasks_per_campaign=2), report)

    assert report.enqueued == []
    assert db.task("creator")["status"] == "succeeded"
    assert any("without an independent paper-readiness review" in error for error in report.errors)


def test_fresh_role_must_return_a_session_before_resumable_followup(tmp_path) -> None:
    paths = WorkspacePaths(
        workspace=tmp_path,
        code=tmp_path / "openlabs",
        data=tmp_path / "data",
        artifacts=tmp_path / "artifacts",
        database=tmp_path / "database",
        database_file=tmp_path / "database" / "live" / "factory.sqlite",
    )
    paths.ensure_runtime_directories()
    db = FactoryDB(paths.database_file)
    db.initialize()
    db.register_campaign("campaign-writing", domain="math", title="Campaign")
    db.enqueue_task(
        task_id="draft",
        campaign_id="campaign-writing",
        domain="math",
        task_type="paper_write",
        objective="Write only from frozen evidence.",
        skill_path="openlabs-math-paper",
        agent_role="writer",
        session_mode="fresh",
    )
    result = atomic_write_json(
        paths.data / "workspaces" / "math" / "campaign-writing" / "draft" / "result.json",
        {
            "schema_version": RESULT_SCHEMA,
            "task_id": "draft",
            "campaign_id": "campaign-writing",
            "lab_id": "math",
            "domain": "math",
            "status": "completed",
            "summary": "A bounded draft pass completed.",
            "artifacts": [],
            "claims": [],
            "next_actions": ["Revise the same manuscript from the frozen comments."],
            "paper_candidate": False,
        },
    )
    task = _start_task(db, "draft", str(result), lab_id="math")
    atomic_write_json(
        paths.result_inbox / "draft.json",
        _receipt(task, str(result), sha256_file(result)),
    )

    report = TickReport()
    ingest_results(db, paths, FactorySettings(max_auto_tasks_per_campaign=2), report)

    assert report.enqueued == []
    assert db.task("draft")["status"] == "needs_human"
    assert "no session_id" in db.task("draft")["last_error"]


def test_review_evidence_request_returns_to_the_prior_writer(tmp_path) -> None:
    paths = WorkspacePaths(
        workspace=tmp_path,
        code=tmp_path / "openlabs",
        data=tmp_path / "data",
        artifacts=tmp_path / "artifacts",
        database=tmp_path / "database",
        database_file=tmp_path / "database" / "live" / "factory.sqlite",
    )
    paths.ensure_runtime_directories()
    db = FactoryDB(paths.database_file)
    db.initialize()
    db.register_campaign("campaign-remediation", domain="ai", title="Campaign")
    db.enqueue_task(
        task_id="writer",
        campaign_id="campaign-remediation",
        domain="ai",
        task_type="paper_write",
        objective="Write the frozen draft.",
        skill_path="openlabs-ai-paper",
        agent_role="writer",
    )
    with db.connect() as connection:
        connection.execute(
            """
            UPDATE tasks SET status='succeeded', agent_session_id='writer-session'
            WHERE task_id='writer'
            """
        )
    db.enqueue_task(
        task_id="panel",
        campaign_id="campaign-remediation",
        domain="ai",
        task_type="paper_review",
        objective="Review the frozen draft.",
        skill_path="openlabs-paper-review",
        parent_task_id="writer",
        agent_role="reviewer",
        session_mode="fresh",
    )
    panel_result = atomic_write_json(
        paths.data / "workspaces" / "ai" / "campaign-remediation" / "panel.json",
        {
            "schema_version": RESULT_SCHEMA,
            "task_id": "panel",
            "campaign_id": "campaign-remediation",
            "lab_id": "ai",
            "domain": "ai",
            "status": "completed",
            "summary": "The panel found one decisive missing ablation.",
            "artifacts": [],
            "claims": [],
            "next_actions": [
                {
                    "objective": "Run only the frozen missing ablation and report all outcomes.",
                    "agent_role": "experimenter",
                    "session_mode": "fresh",
                    "handoff_kind": "evidence_remediation",
                    "resources": {
                        "cpu_threads": 4,
                        "memory_mib": 8192,
                        "scratch_mib": 16384,
                    },
                }
            ],
            "paper_candidate": False,
        },
    )
    panel = _start_task(db, "panel", str(panel_result), lab_id="ai")
    atomic_write_json(
        paths.result_inbox / "panel.json",
        _receipt(panel, str(panel_result), sha256_file(panel_result)),
    )

    panel_report = TickReport()
    ingest_results(db, paths, FactorySettings(), panel_report)

    assert len(panel_report.enqueued) == 1
    remediation = db.task(panel_report.enqueued[0])
    assert remediation is not None
    assert remediation["task_type"] == "evidence_remediation"
    assert remediation["agent_role"] == "experimenter"
    assert remediation["session_mode"] == "fresh"
    assert remediation["skill_path"] == "ai-research-loop"
    assert remediation["cpu_threads"] == 4
    assert remediation["memory_mib"] == 8192
    assert remediation["scratch_mib"] == 16384

    evidence_result = atomic_write_json(
        paths.data / "workspaces" / "ai" / "campaign-remediation" / "remediation.json",
        {
            "schema_version": RESULT_SCHEMA,
            "task_id": remediation["task_id"],
            "campaign_id": "campaign-remediation",
            "lab_id": "ai",
            "domain": "ai",
            "status": "completed",
            "summary": "The requested ablation completed and all outcomes were recorded.",
            "artifacts": [],
            "claims": [],
            "next_actions": [],
            "paper_candidate": False,
        },
    )
    running_remediation = _start_task(
        db,
        str(remediation["task_id"]),
        str(evidence_result),
        lab_id="ai",
    )
    atomic_write_json(
        paths.result_inbox / "remediation.json",
        _receipt(
            running_remediation,
            str(evidence_result),
            sha256_file(evidence_result),
            session_id="experiment-session",
        ),
    )

    evidence_report = TickReport()
    ingest_results(db, paths, FactorySettings(), evidence_report)

    assert len(evidence_report.enqueued) == 1
    revision = db.task(evidence_report.enqueued[0])
    assert revision is not None
    assert revision["task_type"] == "paper_revision"
    assert revision["agent_role"] == "writer"
    assert revision["session_mode"] == "resume"
    assert revision["agent_session_id"] == "writer-session"
    assert revision["session_source_task_id"] == "writer"
