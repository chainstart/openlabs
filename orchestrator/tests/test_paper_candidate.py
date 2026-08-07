from __future__ import annotations

from openlabs.config import FactorySettings, WorkspacePaths
from openlabs.contracts import RECEIPT_SCHEMA, RESULT_SCHEMA, atomic_write_json, sha256_file
from openlabs.db import FactoryDB
from openlabs.engine import TickReport, ingest_results


def test_valid_paper_candidate_enqueues_one_frontier_readiness_task(tmp_path) -> None:
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
    db.register_campaign("campaign-1", domain="math", title="Campaign")
    db.enqueue_task(
        task_id="research-1",
        campaign_id="campaign-1",
        domain="math",
        task_type="research",
        objective="Produce a result.",
    )
    result_root = paths.data / "workspaces" / "math" / "campaign-1" / "results" / "research-1"
    evidence = atomic_write_json(result_root / "evidence.json", {"value": 1})
    result = atomic_write_json(
        result_root / "result.json",
        {
            "schema_version": RESULT_SCHEMA,
            "task_id": "research-1",
            "campaign_id": "campaign-1",
            "lab_id": "math",
            "domain": "math",
            "status": "completed",
            "summary": "One evidence-bound result.",
            "artifacts": [
                {
                    "artifact_id": "evidence",
                    "uri": evidence.resolve().as_uri(),
                    "sha256": sha256_file(evidence),
                }
            ],
            "claims": [
                {
                    "claim_id": "claim-1",
                    "text": "The bounded result holds for the recorded input.",
                    "status": "supported",
                    "evidence": ["evidence"],
                    "limitations": ["No broader claim is made."],
                }
            ],
            "next_actions": [],
            "paper_candidate": True,
        },
    )
    task = db.claim_next_task(owner="test", lease_seconds=60)
    assert task is not None
    attempt_id = str(task["current_attempt_id"])
    db.bind_attempt_spec(
        "research-1",
        attempt_id=attempt_id,
        lab_id="math",
        output_path=str(result),
    )
    db.mark_running(
        "research-1",
        attempt_id=attempt_id,
        owner="test",
        pid=123,
        lease_seconds=60,
    )
    atomic_write_json(
        paths.result_inbox / "research-1.json",
        {
            "schema_version": RECEIPT_SCHEMA,
            "task_id": "research-1",
            "attempt_id": attempt_id,
            "campaign_id": "campaign-1",
            "lab_id": "math",
            "domain": "math",
            "agent_role": "researcher",
            "result_path": str(result),
            "sha256": sha256_file(result),
            "runtime": {
                "duration_seconds": 1.0,
                "exit_code": 0,
                "session_id": "research-session",
            },
        },
    )

    report = TickReport()
    ingest_results(db, paths, FactorySettings(), report)

    assert report.enqueued == ["research-1:paper-readiness"]
    paper_task = db.task("research-1:paper-readiness")
    assert paper_task is not None
    assert paper_task["skill_path"] == "openlabs-math-paper"
    assert paper_task["runner"] == "frontier"
    assert paper_task["agent_role"] == "reviewer"
    assert paper_task["session_mode"] == "fresh"
    assert paper_task["agent_session_id"] is None

    claimed_review = db.claim_next_task(owner="review", lease_seconds=60)
    assert claimed_review is not None
    review_attempt = str(claimed_review["current_attempt_id"])
    review_result = atomic_write_json(
        result_root / "review-result.json",
        {
            "schema_version": RESULT_SCHEMA,
            "task_id": paper_task["task_id"],
            "campaign_id": "campaign-1",
            "lab_id": "math",
            "domain": "math",
            "status": "completed",
            "summary": "The frozen evidence is ready for bounded drafting.",
            "artifacts": [
                {
                    "artifact_id": "audited-evidence",
                    "uri": evidence.resolve().as_uri(),
                    "sha256": sha256_file(evidence),
                }
            ],
            "claims": [
                {
                    "claim_id": "readiness",
                    "text": "The frozen bounded claim has hash-bound evidence.",
                    "status": "supported",
                    "evidence": ["audited-evidence"],
                    "limitations": ["This is a readiness decision, not publication approval."],
                }
            ],
            "next_actions": [],
            "paper_candidate": True,
        },
    )
    db.bind_attempt_spec(
        str(paper_task["task_id"]),
        attempt_id=review_attempt,
        lab_id="math",
        output_path=str(review_result),
    )
    db.mark_running(
        str(paper_task["task_id"]),
        attempt_id=review_attempt,
        owner="review",
        pid=124,
        lease_seconds=60,
    )
    atomic_write_json(
        paths.result_inbox / "review.json",
        {
            "schema_version": RECEIPT_SCHEMA,
            "task_id": paper_task["task_id"],
            "attempt_id": review_attempt,
            "campaign_id": "campaign-1",
            "lab_id": "math",
            "domain": "math",
            "agent_role": "reviewer",
            "result_path": str(review_result),
            "sha256": sha256_file(review_result),
            "runtime": {
                "duration_seconds": 1.0,
                "exit_code": 0,
                "session_id": "one-shot-review-session",
            },
        },
    )

    review_report = TickReport()
    ingest_results(db, paths, FactorySettings(), review_report)

    assert review_report.enqueued == [f"{paper_task['task_id']}:paper-write"]
    writer = db.task(review_report.enqueued[0])
    assert writer is not None
    assert writer["agent_role"] == "writer"
    assert writer["session_mode"] == "fresh"
    assert writer["agent_session_id"] is None
    assert writer["parent_task_id"] == paper_task["task_id"]
