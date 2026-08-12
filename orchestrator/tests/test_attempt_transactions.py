from __future__ import annotations

import json
from pathlib import Path

from openlabs.attempts import (
    begin_attempt_promotion,
    find_attempt_workspace,
    freeze_result_bundle,
    prepare_attempt_workspace,
    promote_attempt_workspace,
    quarantine_attempt_workspace,
    recover_attempt_promotion,
)
from openlabs.config import WorkspacePaths
from openlabs.contracts import RESULT_SCHEMA, atomic_write_json, sha256_file
from openlabs.db import FactoryDB
from openlabs.engine import TickReport, _launch_task, ingest_results


def _paths(tmp_path: Path, code_root: Path | None = None) -> WorkspacePaths:
    paths = WorkspacePaths(
        workspace=tmp_path,
        code=code_root or tmp_path / "openlabs",
        data=tmp_path / "openlabs-data",
        artifacts=tmp_path / "openlabs-artifacts",
        database=tmp_path / "openlabs-database",
        database_file=tmp_path / "openlabs-database" / "live" / "factory.sqlite",
    )
    paths.ensure_runtime_directories()
    return paths


def _leased_task(paths: WorkspacePaths, campaign_id: str = "campaign") -> tuple[FactoryDB, dict]:
    campaign = paths.data / "workspaces" / "math" / campaign_id
    campaign.mkdir(parents=True)
    atomic_write_json(campaign / "production_lane.json", {"nodes": []})
    db = FactoryDB(paths.database_file)
    db.initialize()
    db.register_campaign(
        campaign_id,
        domain="math",
        title="Transactional campaign",
        state_path=str(campaign),
    )
    db.enqueue_task(
        task_id="task",
        campaign_id=campaign_id,
        domain="math",
        task_type="research",
        objective=f"Update {campaign / 'production_lane.json'} in staging.",
        input_path=str(campaign),
    )
    task = db.claim_next_task(owner="test", lease_seconds=60)
    assert task is not None
    return db, task


def test_cancelled_attempt_cannot_mutate_canonical_campaign(tmp_path) -> None:
    paths = _paths(tmp_path)
    _db, task = _leased_task(paths)
    campaign = {"production_plan_path": None}
    workspace = prepare_attempt_workspace(paths, task, campaign)
    staged_lane = workspace.campaign_root / "production_lane.json"
    atomic_write_json(staged_lane, {"nodes": ["partial-uncommitted-work"]})

    checkpoint = quarantine_attempt_workspace(
        paths,
        campaign_id=str(task["campaign_id"]),
        attempt_id=str(task["current_attempt_id"]),
        reason="timebox_expired",
    )

    canonical = json.loads(
        (workspace.canonical_campaign_root / "production_lane.json").read_text(encoding="utf-8")
    )
    assert canonical == {"nodes": []}
    assert json.loads(staged_lane.read_text(encoding="utf-8"))["nodes"] == [
        "partial-uncommitted-work"
    ]
    assert checkpoint is not None and checkpoint["status"] == "quarantined"


def test_valid_attempt_is_promoted_as_one_campaign_transaction(tmp_path) -> None:
    paths = _paths(tmp_path)
    _db, task = _leased_task(paths)
    workspace = prepare_attempt_workspace(paths, task, {})
    atomic_write_json(workspace.campaign_root / "production_lane.json", {"nodes": ["node-1"]})
    (workspace.campaign_root / "evidence.txt").write_text("proof bytes\n", encoding="utf-8")

    metadata = promote_attempt_workspace(workspace)

    canonical = workspace.canonical_campaign_root
    assert json.loads((canonical / "production_lane.json").read_text(encoding="utf-8")) == {
        "nodes": ["node-1"]
    }
    assert (canonical / "evidence.txt").read_text(encoding="utf-8") == "proof bytes\n"
    assert metadata["status"] == "committed"


def test_crash_recovery_rolls_back_uncommitted_filesystem_promotion(tmp_path) -> None:
    paths = _paths(tmp_path)
    _db, task = _leased_task(paths)
    workspace = prepare_attempt_workspace(paths, task, {})
    atomic_write_json(workspace.campaign_root / "production_lane.json", {"nodes": ["node-1"]})
    begin_attempt_promotion(workspace)
    assert json.loads(
        (workspace.canonical_campaign_root / "production_lane.json").read_text(encoding="utf-8")
    ) == {"nodes": ["node-1"]}

    recovered = recover_attempt_promotion(workspace, database_committed=False)

    assert recovered["status"] == "quarantined"
    assert json.loads(
        (workspace.canonical_campaign_root / "production_lane.json").read_text(encoding="utf-8")
    ) == {"nodes": []}


def test_result_archive_survives_later_live_file_mutation(tmp_path) -> None:
    paths = _paths(tmp_path)
    live = paths.data / "workspaces" / "math" / "campaign" / "production_lane.json"
    atomic_write_json(live, {"nodes": ["node-1"]})
    digest = sha256_file(live)
    payload = {
        "schema_version": RESULT_SCHEMA,
        "task_id": "task",
        "campaign_id": "campaign",
        "lab_id": "math",
        "domain": "math",
        "status": "completed",
        "summary": "One node completed.",
        "artifacts": [
            {
                "artifact_id": "lane-snapshot",
                "uri": live.resolve().as_uri(),
                "sha256": digest,
                "kind": "state_snapshot",
            }
        ],
        "claims": [
            {
                "claim_id": "node-recorded",
                "text": "The node was recorded.",
                "status": "supported",
                "evidence": ["lane-snapshot"],
                "limitations": [],
            }
        ],
        "next_actions": [],
        "paper_candidate": False,
    }
    source_result = atomic_write_json(tmp_path / "source-result.json", payload)

    frozen, result_path, _result_sha = freeze_result_bundle(
        paths,
        payload,
        attempt_id="attempt-1",
        source_result_path=source_result,
        source_result_sha256=sha256_file(source_result),
    )
    atomic_write_json(live, {"nodes": ["node-1", "node-2"]})

    archived = Path(frozen["artifacts"][0]["uri"].removeprefix("file://"))
    assert sha256_file(archived) == digest
    assert json.loads(archived.read_text(encoding="utf-8")) == {"nodes": ["node-1"]}
    assert json.loads(result_path.read_text(encoding="utf-8"))["artifacts"][0]["sha256"] == digest


def test_launch_writes_job_against_private_campaign_copy(tmp_path) -> None:
    code_root = Path(__file__).resolve().parents[2]
    paths = _paths(tmp_path, code_root)
    db, task = _leased_task(paths)
    from openlabs.config import FactorySettings

    settings = FactorySettings(launch_jobs=False)
    _launch_task(db, paths, settings, task, owner="test")

    running = db.task("task")
    assert running is not None
    workspace = find_attempt_workspace(
        paths,
        campaign_id="campaign",
        attempt_id=str(running["current_attempt_id"]),
    )
    assert workspace is not None
    job = json.loads(
        (paths.job_inbox / f"task-{running['current_attempt_id']}.json").read_text(encoding="utf-8")
    )
    assert job["agent_workspace"] == str(workspace.campaign_root)
    assert job["input_path"] == str(workspace.campaign_root)
    assert job["transaction"]["canonical_campaign_workspace"] == str(
        workspace.canonical_campaign_root
    )
    assert str(workspace.campaign_root) in job["objective"]
    assert Path(job["output_path"]).is_relative_to(workspace.campaign_root)


def test_ingestion_commits_staged_state_and_indexes_immutable_result(tmp_path) -> None:
    paths = _paths(tmp_path)
    db, task = _leased_task(paths)
    workspace = prepare_attempt_workspace(paths, task, {})
    output = workspace.campaign_root / "results" / "task" / "result.json"
    evidence = workspace.campaign_root / "evidence.json"
    atomic_write_json(evidence, {"proved": True})
    atomic_write_json(workspace.campaign_root / "production_lane.json", {"nodes": ["node-1"]})
    result = atomic_write_json(
        output,
        {
            "schema_version": RESULT_SCHEMA,
            "task_id": "task",
            "campaign_id": "campaign",
            "lab_id": "math",
            "domain": "math",
            "status": "completed",
            "summary": "Transactional node completed.",
            "artifacts": [
                {
                    "artifact_id": "proof",
                    "uri": evidence.resolve().as_uri(),
                    "sha256": sha256_file(evidence),
                    "kind": "proof_certificate",
                }
            ],
            "claims": [
                {
                    "claim_id": "proof-complete",
                    "text": "The bounded proof operation completed.",
                    "status": "supported",
                    "evidence": ["proof"],
                    "limitations": [],
                }
            ],
            "next_actions": [],
            "paper_candidate": False,
        },
    )
    attempt_id = str(task["current_attempt_id"])
    db.bind_attempt_spec("task", attempt_id=attempt_id, lab_id="math", output_path=str(result))
    db.mark_running("task", attempt_id=attempt_id, owner="test", pid=123, lease_seconds=60)
    receipt = {
        "schema_version": "openlabs.result_receipt.v2",
        "task_id": "task",
        "attempt_id": attempt_id,
        "campaign_id": "campaign",
        "lab_id": "math",
        "domain": "math",
        "agent_role": "researcher",
        "result_path": str(result),
        "sha256": sha256_file(result),
        "runtime": {"duration_seconds": 1.0, "exit_code": 0},
    }
    atomic_write_json(paths.result_inbox / "receipt.json", receipt)

    report = TickReport()
    from openlabs.config import FactorySettings

    ingest_results(db, paths, FactorySettings(), report)

    stored = db.task("task")
    assert stored is not None and stored["status"] == "succeeded"
    assert str(paths.artifacts / "result-bundles") in str(stored["result_path"])
    assert json.loads(
        (workspace.canonical_campaign_root / "production_lane.json").read_text(encoding="utf-8")
    ) == {"nodes": ["node-1"]}
    assert report.attempts_committed == [
        {"task_id": "task", "attempt_id": attempt_id, "campaign_id": "campaign"}
    ]
