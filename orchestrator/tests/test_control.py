from __future__ import annotations

import json

from openlabs.attempts import prepare_attempt_workspace
from openlabs.config import workspace_paths
from openlabs.contracts import atomic_write_json
from openlabs.control import halt_production
from openlabs.db import FactoryDB


def test_halt_production_pauses_plan_and_cancels_all_work(tmp_path) -> None:
    paths = workspace_paths(tmp_path)
    paths.ensure_runtime_directories()
    plan_path = paths.data / "workspaces/math/production/run/production_plan.json"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(
        json.dumps(
            {
                "schema_version": "openlabs.math_production_plan.v1",
                "plan_id": "timeboxed-run",
                "status": "active",
                "run_control": {"deadline_at": "2026-08-12T01:58:44Z"},
            }
        ),
        encoding="utf-8",
    )
    db = FactoryDB(paths.database_file)
    db.initialize()
    db.register_campaign("route", domain="math", title="Route")
    campaign_root = paths.data / "workspaces" / "math" / "route"
    lane_path = atomic_write_json(campaign_root / "production_lane.json", {"nodes": []})
    db.configure_continuous_campaign(
        "route",
        production_plan_path=str(plan_path.resolve()),
        production_lane_path=str(lane_path),
    )
    db.enqueue_task(
        task_id="running",
        campaign_id="route",
        domain="math",
        task_type="research",
        objective="Run until the deadline.",
    )
    task = db.claim_next_task(owner="test", lease_seconds=60)
    assert task is not None
    db.mark_running(
        "running",
        attempt_id=str(task["current_attempt_id"]),
        owner="test",
        pid=999_999_999,
        lease_seconds=60,
    )
    running = db.task("running")
    assert running is not None
    attempt_workspace = prepare_attempt_workspace(
        paths,
        running,
        db.campaign("route") or {},
    )
    atomic_write_json(
        attempt_workspace.campaign_root / "production_lane.json",
        {"nodes": ["partial-node"]},
    )
    db.enqueue_task(
        task_id="queued",
        campaign_id="route",
        domain="math",
        task_type="research",
        objective="Must never start after the deadline.",
    )
    report_path = plan_path.parent / "halt-report.json"

    report = halt_production(
        paths,
        plan_path=plan_path,
        reason="timebox_expired",
        report_path=report_path,
        stop_systemd=False,
    )

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert plan["status"] == "paused_timebox_complete"
    assert plan["run_control"]["stop_reason"] == "timebox_expired"
    assert db.campaign("route")["status"] == "production_paused"
    assert db.campaign("route")["continuous"] == 0
    assert db.task("running")["status"] == "cancelled"
    assert db.task("queued")["status"] == "cancelled"
    assert [item["task_id"] for item in report["active_cancelled"]] == ["running"]
    assert report["queued_cancelled"] == ["queued"]
    assert report["attempt_checkpoints"][0]["status"] == "quarantined"
    assert json.loads(lane_path.read_text(encoding="utf-8")) == {"nodes": []}
    assert json.loads(
        (attempt_workspace.campaign_root / "production_lane.json").read_text(encoding="utf-8")
    ) == {"nodes": ["partial-node"]}
    assert json.loads(report_path.read_text(encoding="utf-8"))["final_status"] == (
        "paused_timebox_complete"
    )
