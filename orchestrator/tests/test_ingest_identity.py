from __future__ import annotations

from openlabs.config import FactorySettings, WorkspacePaths
from openlabs.contracts import RECEIPT_SCHEMA, RESULT_SCHEMA, atomic_write_json, sha256_file
from openlabs.db import FactoryDB
from openlabs.engine import TickReport, ingest_results


def test_result_cannot_cross_campaign_or_domain_boundaries(tmp_path) -> None:
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
    db.register_campaign("campaign-a", domain="math", title="A")
    db.register_campaign("campaign-b", domain="ai", title="B")
    db.enqueue_task(
        task_id="task-a",
        campaign_id="campaign-a",
        domain="math",
        task_type="research",
        objective="Stay inside campaign A.",
    )
    task = db.claim_next_task(owner="test", lease_seconds=60)
    assert task is not None
    attempt_id = str(task["current_attempt_id"])
    result = atomic_write_json(
        paths.data / "workspaces" / "math" / "campaign-a" / "result.json",
        {
            "schema_version": RESULT_SCHEMA,
            "task_id": "task-a",
            "campaign_id": "campaign-b",
            "lab_id": "ai",
            "domain": "ai",
            "status": "completed",
            "summary": "Forged cross-campaign result.",
            "artifacts": [],
            "claims": [],
            "next_actions": ["Continue in campaign B."],
        },
    )
    db.bind_attempt_spec(
        "task-a",
        attempt_id=attempt_id,
        lab_id="math",
        output_path=str(result),
    )
    db.mark_running(
        "task-a",
        attempt_id=attempt_id,
        owner="test",
        pid=123,
        lease_seconds=60,
    )
    atomic_write_json(
        paths.result_inbox / "forged.json",
        {
            "schema_version": RECEIPT_SCHEMA,
            "task_id": "task-a",
            "attempt_id": attempt_id,
            "campaign_id": "campaign-a",
            "lab_id": "math",
            "domain": "math",
            "agent_role": "researcher",
            "result_path": str(result),
            "sha256": sha256_file(result),
            "runtime": {"duration_seconds": 1.0, "exit_code": 0},
        },
    )

    report = TickReport()
    ingest_results(db, paths, FactorySettings(), report)

    assert report.ingested == []
    assert report.enqueued == []
    assert any("Result campaign_id mismatch" in error for error in report.errors)
    assert db.task("task-a")["status"] == "running"
    assert db.task_count("campaign-b") == 0
    assert not list(paths.result_inbox.glob("*.json"))


def test_stale_attempt_receipt_is_rejected(tmp_path) -> None:
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
    db.register_campaign("campaign", domain="math", title="Campaign")
    db.enqueue_task(
        task_id="task",
        campaign_id="campaign",
        domain="math",
        task_type="research",
        objective="Reject stale work.",
    )
    first = db.claim_next_task(owner="old", lease_seconds=60)
    assert first is not None
    old_attempt = str(first["current_attempt_id"])
    db.mark_running(
        "task",
        attempt_id=old_attempt,
        owner="old",
        pid=1,
        lease_seconds=60,
    )
    with db.connect() as connection:
        connection.execute(
            "UPDATE tasks SET lease_expires_at='2000-01-01T00:00:00Z' WHERE task_id='task'"
        )
    db.recover_expired()
    current = db.claim_next_task(owner="new", lease_seconds=60)
    assert current is not None
    current_attempt = str(current["current_attempt_id"])
    current_output = paths.data / "workspaces" / "math" / "campaign" / "current.json"
    db.bind_attempt_spec(
        "task",
        attempt_id=current_attempt,
        lab_id="math",
        output_path=str(current_output),
    )
    db.mark_running(
        "task",
        attempt_id=current_attempt,
        owner="new",
        pid=2,
        lease_seconds=60,
    )
    stale = atomic_write_json(
        paths.data / "workspaces" / "math" / "campaign" / "stale.json",
        {
            "schema_version": RESULT_SCHEMA,
            "task_id": "task",
            "campaign_id": "campaign",
            "lab_id": "math",
            "domain": "math",
            "status": "completed",
            "summary": "Stale result.",
            "artifacts": [],
            "claims": [],
            "next_actions": [],
        },
    )
    atomic_write_json(
        paths.result_inbox / "stale.json",
        {
            "schema_version": RECEIPT_SCHEMA,
            "task_id": "task",
            "attempt_id": old_attempt,
            "campaign_id": "campaign",
            "lab_id": "math",
            "domain": "math",
            "agent_role": "researcher",
            "result_path": str(stale),
            "sha256": sha256_file(stale),
            "runtime": {"duration_seconds": 1.0, "exit_code": 0},
        },
    )

    report = TickReport()
    ingest_results(db, paths, FactorySettings(), report)

    assert report.ingested == []
    assert any("attempt_id mismatch" in error for error in report.errors)
    assert db.task("task")["current_attempt_id"] == current_attempt
    assert db.task("task")["status"] == "running"
