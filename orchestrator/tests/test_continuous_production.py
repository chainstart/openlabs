from __future__ import annotations

import json
from pathlib import Path

from openlabs.config import FactorySettings, WorkspacePaths
from openlabs.contracts import atomic_write_json
from openlabs.db import FactoryDB
from openlabs.engine import _production_workspace_authority, tick


def _paths(tmp_path) -> WorkspacePaths:
    paths = WorkspacePaths(
        workspace=tmp_path,
        code=tmp_path / "openlabs",
        data=tmp_path / "openlabs-data",
        artifacts=tmp_path / "openlabs-artifacts",
        database=tmp_path / "openlabs-database",
        database_file=tmp_path / "openlabs-database" / "live" / "factory.sqlite",
    )
    paths.ensure_runtime_directories()
    return paths


def _write_active_plan(paths: WorkspacePaths, lane_id: str) -> tuple[str, str]:
    plan_path = (
        paths.data / "workspaces" / "math" / "production" / "test-plan" / "production_plan.json"
    )
    lane_path = paths.data / "workspaces" / "math" / lane_id / "production_lane.json"
    atomic_write_json(
        plan_path,
        {
            "schema_version": "openlabs.math_production_plan.v1",
            "plan_id": "test-plan",
            "status": "active",
            "objective": "Continuously produce audited mathematical results.",
            "lanes": [
                {
                    "lane_id": lane_id,
                    "config_path": f"../../{lane_id}/production_lane.json",
                    "startup": "active",
                    "priority": 17,
                }
            ],
        },
    )
    atomic_write_json(
        lane_path,
        {
            "schema_version": "openlabs.math_production_lane.v1",
            "plan_id": "test-plan",
            "lane_id": lane_id,
            "plan_path": "../production/test-plan/production_plan.json",
            "stage": "radar",
            "cycle": 1,
            "theme": {"name": "Test lane"},
            "selection_gate": {},
            "node_policy": {},
            "selected_target": None,
            "archived_targets": [],
            "nodes": [],
            "history": [],
        },
    )
    return str(plan_path), str(lane_path)


def test_active_plan_rolls_a_full_task_window_and_reseeds(tmp_path) -> None:
    paths = _paths(tmp_path)
    lane_id = "continuous-math-lane"
    plan_path, lane_path = _write_active_plan(paths, lane_id)
    db = FactoryDB(paths.database_file)
    db.initialize()
    db.register_campaign(lane_id, domain="math", title="Continuous lane")
    for task_id in ("old-1", "old-2"):
        db.enqueue_task(
            task_id=task_id,
            campaign_id=lane_id,
            domain="math",
            task_type="research",
            objective="Complete one bounded research node.",
            skill_path="math-production-supervisor",
        )
    with db.connect() as connection:
        connection.execute(
            "UPDATE tasks SET status='succeeded' WHERE campaign_id=?",
            (lane_id,),
        )

    report = tick(
        paths,
        FactorySettings(
            launch_jobs=False,
            max_auto_tasks_per_campaign=2,
        ),
    )

    campaign = db.campaign(lane_id)
    assert campaign is not None
    assert campaign["continuous"] == 1
    assert campaign["production_plan_path"] == plan_path
    assert campaign["production_lane_path"] == lane_path
    assert campaign["production_epoch"] == 2
    assert campaign["rollover_count"] == 1
    assert campaign["priority"] == 17
    assert db.task_count(lane_id) == 3
    assert db.current_epoch_task_count(lane_id) == 1
    successor = db.task(report.enqueued[0])
    assert successor is not None
    assert successor["campaign_epoch"] == 2
    assert successor["routing_reason"] == "production_rollover"
    assert successor["session_mode"] == "fresh"
    assert successor["status"] == "queued"
    assert report.rollovers == [
        {
            "campaign_id": lane_id,
            "epoch": 2,
            "reason": "automatic_task_window_exhausted",
        }
    ]
    assert report.production_reseeded == [lane_id]


def test_restart_reseed_recovers_reviewer_authority_from_durable_phase(tmp_path) -> None:
    paths = _paths(tmp_path)
    lane_id = "authority-restart-lane"
    plan_path, lane_path = _write_active_plan(paths, lane_id)
    lab_root = paths.code / "labs" / "math"
    skill_root = lab_root / "skills" / "phase-skill"
    skill_root.mkdir(parents=True)
    atomic_write_json(
        lab_root / "lab.json",
        {
            "schema_version": "openlabs.lab.v1",
            "lab_id": "math",
            "domain": "math",
            "runner": {"command": ["{python}", "runner.py"]},
            "skills": [
                {
                    "skill_id": "phase-skill",
                    "path": "skills/phase-skill/SKILL.md",
                }
            ],
        },
    )
    (skill_root / "SKILL.md").write_text(
        "---\nname: phase-skill\ndescription: Test phase authority.\n---\n",
        encoding="utf-8",
    )
    atomic_write_json(
        skill_root / "authority-policy.json",
        {
            "schema_version": "openlabs.authority_policy.v1",
            "policy_id": "test-authority",
            "state_glob": "**/campaign_state.json",
            "state_schema_version": "test-state.v1",
            "phase_field": "phase",
            "exclude_path_parts": ["evidence"],
            "phase_authority": {
                "independent_audit": {
                    "allowed_roles": ["reviewer"],
                    "default_role": "reviewer",
                    "required_session_mode": "fresh",
                    "required_handoff_kind": "independent_replication",
                }
            },
        },
    )
    atomic_write_json(
        Path(lane_path).parent / "research" / "campaign_state.json",
        {
            "schema_version": "test-state.v1",
            "phase": "independent_audit",
            "updated_at": "2026-08-12T00:00:00Z",
        },
    )
    db = FactoryDB(paths.database_file)
    db.initialize()
    db.register_campaign(lane_id, domain="math", title="Authority restart")
    db.configure_continuous_campaign(
        lane_id,
        production_plan_path=plan_path,
        production_lane_path=lane_path,
    )
    campaign = db.campaign(lane_id)
    assert campaign is not None

    authority = _production_workspace_authority(paths, campaign)

    assert authority is not None
    assert authority.phase == "independent_audit"
    assert authority.allowed_roles == ("reviewer",)
    db.enqueue_task(
        task_id="cancelled-author-task",
        campaign_id=lane_id,
        domain="math",
        task_type="research_continue",
        objective="An author task that was stopped at the timebox.",
        skill_path="phase-skill",
        agent_role="researcher",
        session_mode="fresh",
    )
    with db.connect() as connection:
        connection.execute(
            "UPDATE tasks SET status='cancelled' WHERE task_id='cancelled-author-task'"
        )

    report = tick(paths, FactorySettings(launch_jobs=False))

    successor = db.task(report.enqueued[0])
    assert successor is not None
    assert successor["agent_role"] == "reviewer"
    assert successor["session_mode"] == "fresh"
    assert successor["task_type"] == "independent_review"


def test_idle_binding_failure_is_repaired_without_repeating_science(tmp_path) -> None:
    paths = _paths(tmp_path)
    lane_id = "artifact-repair-lane"
    _write_active_plan(paths, lane_id)
    db = FactoryDB(paths.database_file)
    db.initialize()
    db.register_campaign(lane_id, domain="math", title="Artifact repair")
    db.enqueue_task(
        task_id="rejected-result",
        campaign_id=lane_id,
        domain="math",
        task_type="research",
        objective="Audit exact solver inputs.",
        skill_path="math-production-supervisor",
        runner="balanced",
    )
    with db.connect() as connection:
        connection.execute(
            """
            UPDATE tasks
            SET status='needs_replan',
                last_error='opaque gate detail that policy must not parse'
            WHERE task_id='rejected-result'
            """
        )
        connection.execute(
            """
            INSERT INTO result_bundles(
                task_id, attempt_id, path, sha256, valid, gate_passed,
                blockers_json, runtime_json, ingested_at
            ) VALUES(
                'rejected-result', NULL, '/tmp/rejected.json', ?, 1, 0,
                '[]', ?, '2026-08-12T00:00:00Z'
            )
            """,
            (
                "0" * 64,
                json.dumps({"gate_failure_classes": ["artifact_binding"]}),
            ),
        )

    report = tick(
        paths,
        FactorySettings(
            launch_jobs=False,
            max_auto_tasks_per_campaign=4,
        ),
    )

    assert len(report.enqueued) == 1
    successor = db.task(report.enqueued[0])
    assert successor is not None
    assert successor["campaign_epoch"] == 1
    assert successor["task_type"] == "replan"
    assert successor["runner"] == "frontier"
    assert successor["routing_reason"] == "production_gate_repair"
    assert successor["session_mode"] == "fresh"
    assert "materialize the exact referenced bytes" in successor["objective"]
    assert "Do not repeat the literature audit" in successor["objective"]


def test_corrupt_continuous_lane_is_reported_without_crashing_tick(tmp_path) -> None:
    paths = _paths(tmp_path)
    lane_id = "corrupt-state-lane"
    _, lane_path = _write_active_plan(paths, lane_id)
    db = FactoryDB(paths.database_file)
    db.initialize()
    db.register_campaign(lane_id, domain="math", title="Corrupt state")
    db.configure_continuous_campaign(
        lane_id,
        production_plan_path=str(
            paths.data / "workspaces" / "math" / "production" / "test-plan" / "production_plan.json"
        ),
        production_lane_path=lane_path,
    )
    # Simulate a partially written operator-owned lane after initial plan discovery.
    with open(lane_path, "w", encoding="utf-8") as handle:
        handle.write("not-json")

    report = tick(paths, FactorySettings(launch_jobs=False))

    assert report.enqueued == []
    assert any("Invalid production plan" in error for error in report.errors)
    assert report.production_paused == [lane_id]
    assert db.campaign(lane_id)["status"] == "production_paused"
    assert db.campaign(lane_id)["continuous"] == 0


def test_auto_continue_false_syncs_but_does_not_seed(tmp_path) -> None:
    paths = _paths(tmp_path)
    lane_id = "manual-production-lane"
    _write_active_plan(paths, lane_id)

    report = tick(
        paths,
        FactorySettings(auto_continue=False, launch_jobs=False),
    )
    db = FactoryDB(paths.database_file)

    assert report.production_synced == [lane_id]
    assert report.enqueued == []
    assert db.campaign(lane_id)["continuous"] == 1
    assert db.task_count(lane_id) == 0


def test_inactive_plan_pauses_campaign_and_cancels_queued_work(tmp_path) -> None:
    paths = _paths(tmp_path)
    lane_id = "retired-production-lane"
    plan_path, _ = _write_active_plan(paths, lane_id)
    plan_path = Path(plan_path)

    tick(paths, FactorySettings(auto_continue=False, launch_jobs=False))
    db = FactoryDB(paths.database_file)
    db.enqueue_task(
        task_id="stale-queued-task",
        campaign_id=lane_id,
        domain="math",
        task_type="research",
        objective="This must not survive plan retirement.",
    )
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["status"] = "paused"
    atomic_write_json(plan_path, plan)

    report = tick(paths, FactorySettings(launch_jobs=False))

    campaign = db.campaign(lane_id)
    assert report.production_paused == [lane_id]
    assert campaign["status"] == "production_paused"
    assert campaign["continuous"] == 0
    assert db.task("stale-queued-task")["status"] == "cancelled"
    assert report.enqueued == []


def test_reactivating_plan_resumes_only_production_paused_campaign(tmp_path) -> None:
    paths = _paths(tmp_path)
    lane_id = "resumable-production-lane"
    plan_path, _ = _write_active_plan(paths, lane_id)
    plan_path = Path(plan_path)
    db = FactoryDB(paths.database_file)

    tick(paths, FactorySettings(auto_continue=False, launch_jobs=False))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["status"] = "paused"
    atomic_write_json(plan_path, plan)
    tick(paths, FactorySettings(auto_continue=False, launch_jobs=False))
    assert db.campaign(lane_id)["status"] == "production_paused"

    plan["status"] = "active"
    atomic_write_json(plan_path, plan)
    report = tick(paths, FactorySettings(auto_continue=False, launch_jobs=False))

    assert report.production_synced == [lane_id]
    assert db.campaign(lane_id)["status"] == "active"
    assert db.campaign(lane_id)["continuous"] == 1


def test_malformed_priority_is_isolated_and_does_not_crash_tick(tmp_path) -> None:
    paths = _paths(tmp_path)
    lane_id = "malformed-priority-lane"
    plan_path, _ = _write_active_plan(paths, lane_id)
    plan_path = Path(plan_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["lanes"][0]["priority"] = {"not": "an integer"}
    atomic_write_json(plan_path, plan)

    report = tick(paths, FactorySettings(launch_jobs=False))

    assert report.enqueued == []
    assert any("Invalid production plan" in error for error in report.errors)
