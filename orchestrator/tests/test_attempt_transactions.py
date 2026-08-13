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
from openlabs.config import FactorySettings, WorkspacePaths
from openlabs.contracts import (
    RESULT_SCHEMA,
    atomic_write_json,
    sha256_file,
    validate_result_bundle,
)
from openlabs.db import FactoryDB
from openlabs.engine import TickReport, _launch_task, ingest_results, tick
from openlabs.reproduction import preflight_reproductions


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
    (workspace.campaign_root / ".codex").mkdir()
    (workspace.campaign_root / ".codex" / "hooks.json").write_text("{}\n", encoding="utf-8")
    (workspace.campaign_root / ".agents" / "skills").mkdir(parents=True)
    (workspace.campaign_root / ".agents" / "skills" / "test").symlink_to(tmp_path)

    metadata = promote_attempt_workspace(workspace)

    canonical = workspace.canonical_campaign_root
    assert json.loads((canonical / "production_lane.json").read_text(encoding="utf-8")) == {
        "nodes": ["node-1"]
    }
    assert (canonical / "evidence.txt").read_text(encoding="utf-8") == "proof bytes\n"
    assert not (canonical / ".codex").exists()
    assert not (canonical / ".agents").exists()
    assert metadata["status"] == "committed"


def test_lease_recovery_quarantines_the_private_attempt_checkpoint(tmp_path) -> None:
    paths = _paths(tmp_path)
    db, task = _leased_task(paths)
    workspace = prepare_attempt_workspace(paths, task, {})
    attempt_id = str(task["current_attempt_id"])
    db.mark_running(
        "task",
        attempt_id=attempt_id,
        owner="test",
        pid=123,
        lease_seconds=60,
    )
    with db.connect() as connection:
        connection.execute(
            "UPDATE tasks SET lease_expires_at='2000-01-01T00:00:00Z' WHERE task_id='task'"
        )

    report = tick(paths, FactorySettings(launch_jobs=False, retry_backoff_seconds=0))

    metadata = json.loads(workspace.metadata_path.read_text(encoding="utf-8"))
    assert report.recovered == ["task"]
    assert metadata["status"] == "quarantined"
    assert metadata["quarantine_reason"] == "lease_expired"


def test_launch_failure_closes_and_quarantines_the_created_attempt(tmp_path, monkeypatch) -> None:
    code_root = Path(__file__).resolve().parents[2]
    paths = _paths(tmp_path, code_root)
    campaign = paths.data / "workspaces" / "math" / "campaign"
    campaign.mkdir(parents=True)
    atomic_write_json(campaign / "production_lane.json", {"nodes": []})
    db = FactoryDB(paths.database_file)
    db.initialize()
    db.register_campaign("campaign", domain="math", title="Campaign", state_path=str(campaign))
    db.enqueue_task(
        task_id="task",
        campaign_id="campaign",
        domain="math",
        task_type="research",
        objective="Exercise launch failure cleanup.",
    )

    def fail_worker(**_kwargs):
        raise RuntimeError("synthetic launch failure")

    monkeypatch.setattr("openlabs.engine._launch_worker", fail_worker)
    report = tick(
        paths,
        FactorySettings(
            launch_jobs=True,
            max_worker_processes=1,
            retry_backoff_seconds=0,
        ),
    )

    task = db.task("task")
    attempt = db.task_attempts("task")[0]
    workspace = find_attempt_workspace(
        paths,
        campaign_id="campaign",
        attempt_id=str(attempt["attempt_id"]),
    )
    assert task["status"] == "queued"
    assert attempt["status"] == "launch_failed"
    assert workspace is not None
    metadata = json.loads(workspace.metadata_path.read_text(encoding="utf-8"))
    assert metadata["status"] == "quarantined"
    assert "synthetic launch failure" in metadata["quarantine_reason"]
    assert report.attempts_quarantined[0]["attempt_id"] == attempt["attempt_id"]


def test_tick_reconciles_terminal_database_attempt_with_stale_active_metadata(tmp_path) -> None:
    paths = _paths(tmp_path)
    db, task = _leased_task(paths)
    workspace = prepare_attempt_workspace(paths, task, {})
    attempt_id = str(task["current_attempt_id"])
    db.fail_launch("task", "historical launch failure", retry_backoff_seconds=60)
    assert json.loads(workspace.metadata_path.read_text(encoding="utf-8"))["status"] == "active"

    report = tick(paths, FactorySettings(launch_jobs=False))

    metadata = json.loads(workspace.metadata_path.read_text(encoding="utf-8"))
    assert metadata["status"] == "quarantined"
    assert metadata["quarantine_reason"] == "reconciled_terminal_attempt:launch_failed"
    assert report.attempts_quarantined == [
        {
            "task_id": "task",
            "attempt_id": attempt_id,
            "campaign_id": "campaign",
            "reason": "reconciled_terminal_attempt:launch_failed",
        }
    ]


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


def test_result_archive_materializes_and_replays_declared_dependency_closure(tmp_path) -> None:
    paths = _paths(tmp_path)
    workspace = paths.data / "workspaces" / "math" / "campaign"
    input_path = atomic_write_json(workspace / "data" / "input.json", {"value": 7})
    script = workspace / "evidence" / "verify.py"
    script.parent.mkdir(parents=True)
    script.write_text(
        "from pathlib import Path\n"
        "import json\n"
        "root = Path(__file__).resolve().parents[1]\n"
        "assert json.loads((root / 'data/input.json').read_text())['value'] == 7\n",
        encoding="utf-8",
    )
    payload = {
        "schema_version": RESULT_SCHEMA,
        "task_id": "replay-task",
        "campaign_id": "campaign",
        "lab_id": "math",
        "domain": "math",
        "status": "completed",
        "summary": "The declared verification closure replays.",
        "artifacts": [
            {
                "artifact_id": "validator",
                "uri": script.resolve().as_uri(),
                "sha256": sha256_file(script),
                "kind": "verification_script",
                "reproduction": {
                    "command": ["python3", "{artifact}"],
                    "inputs": [
                        {
                            "path": "data/input.json",
                            "sha256": sha256_file(input_path),
                        }
                    ],
                    "timeout_seconds": 10,
                },
            }
        ],
        "claims": [],
        "next_actions": [],
    }
    assert validate_result_bundle(payload).valid
    preflight_errors, preflight_receipts = preflight_reproductions(
        payload,
        workspace_root=workspace,
    )
    assert preflight_errors == []
    assert preflight_receipts[0]["status"] == "passed"
    source_result = atomic_write_json(workspace / "result.json", payload)

    frozen, result_path, _result_sha = freeze_result_bundle(
        paths,
        payload,
        attempt_id="attempt-replay",
        source_result_path=source_result,
        source_result_sha256=sha256_file(source_result),
        source_workspace=workspace,
    )

    reproduction = frozen["artifacts"][0]["reproduction"]
    assert reproduction["replay"]["status"] == "passed"
    assert frozen["openlabs_archive"]["reproduction"]["reproducible"] is True
    assert Path(reproduction["workspace_uri"].removeprefix("file://")).is_dir()
    assert validate_result_bundle(json.loads(result_path.read_text(encoding="utf-8"))).valid


def test_preflight_rejects_undeclared_live_dependency(tmp_path) -> None:
    workspace = tmp_path / "campaign"
    dependency = atomic_write_json(workspace / "data" / "hidden.json", {"value": 7})
    script = workspace / "evidence" / "verify.py"
    script.parent.mkdir(parents=True)
    script.write_text(
        "from pathlib import Path\n"
        "root = Path(__file__).resolve().parents[1]\n"
        "assert (root / 'data/hidden.json').is_file()\n",
        encoding="utf-8",
    )
    payload = {
        "status": "completed",
        "artifacts": [
            {
                "artifact_id": "validator",
                "uri": script.resolve().as_uri(),
                "sha256": sha256_file(script),
                "kind": "verification_script",
                "reproduction": {
                    "command": ["python3", "{artifact}"],
                    "inputs": [],
                    "timeout_seconds": 10,
                },
            }
        ],
    }
    assert dependency.is_file()
    errors, receipts = preflight_reproductions(payload, workspace_root=workspace)
    assert errors
    assert receipts[0]["status"] == "failed"


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
    assert job["runtime_policy"]["sandbox"] == "danger-full-access"
    assert "$openlabs-research-factory" in job["runtime_policy"]["skills"]
    assert "$math-production-supervisor" not in job["runtime_policy"]["skills"]
    assert (workspace.campaign_root / ".codex" / "hooks.json").is_file()
    assert (workspace.campaign_root / ".agents" / "skills" / "amra-research-loop").is_symlink()
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
