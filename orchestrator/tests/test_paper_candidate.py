from __future__ import annotations

from openlabs.config import FactorySettings, WorkspacePaths
from openlabs.contracts import RECEIPT_SCHEMA, RESULT_SCHEMA, atomic_write_json, sha256_file
from openlabs.db import FactoryDB
from openlabs.engine import TickReport, ingest_results


def test_amra_reviewer_promotion_still_enters_fresh_paper_readiness(tmp_path) -> None:
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
    db.register_campaign("campaign-amra-audit", domain="math", title="AMRA audit")
    db.enqueue_task(
        task_id="amra-audit",
        campaign_id="campaign-amra-audit",
        domain="math",
        task_type="independent_review",
        objective="Independently reconstruct the decisive lemma.",
        agent_role="reviewer",
        session_mode="fresh",
    )
    root = paths.data / "workspaces" / "math" / "campaign-amra-audit"
    evidence = atomic_write_json(root / "audit.json", {"reconstructed": True})
    result = atomic_write_json(
        root / "result.json",
        {
            "schema_version": RESULT_SCHEMA,
            "task_id": "amra-audit",
            "campaign_id": "campaign-amra-audit",
            "lab_id": "math",
            "domain": "math",
            "status": "completed",
            "summary": "The independent AMRA reconstruction passed.",
            "artifacts": [
                {
                    "artifact_id": "audit",
                    "uri": evidence.resolve().as_uri(),
                    "sha256": sha256_file(evidence),
                }
            ],
            "claims": [
                {
                    "claim_id": "reconstructed",
                    "text": "The frozen lemma reconstructed under the declared assumptions.",
                    "status": "verified",
                    "evidence": ["audit"],
                    "limitations": ["Paper readiness remains a separate shadow gate."],
                }
            ],
            "next_actions": [],
            "paper_candidate": True,
        },
    )
    task = db.claim_next_task(owner="audit", lease_seconds=60)
    assert task is not None
    attempt_id = str(task["current_attempt_id"])
    db.bind_attempt_spec(
        "amra-audit",
        attempt_id=attempt_id,
        lab_id="math",
        output_path=str(result),
    )
    db.mark_running(
        "amra-audit",
        attempt_id=attempt_id,
        owner="audit",
        pid=123,
        lease_seconds=60,
    )
    atomic_write_json(
        paths.result_inbox / "amra-audit.json",
        {
            "schema_version": RECEIPT_SCHEMA,
            "task_id": "amra-audit",
            "attempt_id": attempt_id,
            "campaign_id": "campaign-amra-audit",
            "lab_id": "math",
            "domain": "math",
            "agent_role": "reviewer",
            "result_path": str(result),
            "sha256": sha256_file(result),
            "runtime": {"duration_seconds": 1.0, "exit_code": 0},
        },
    )

    report = TickReport()
    ingest_results(db, paths, FactorySettings(), report)

    assert report.enqueued == ["amra-audit:paper-readiness"]
    readiness = db.task(report.enqueued[0])
    assert readiness is not None
    assert readiness["task_type"] == "paper_readiness"
    assert readiness["agent_role"] == "reviewer"
    assert readiness["session_mode"] == "fresh"


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

    claimed_writer = db.claim_next_task(owner="writer", lease_seconds=60)
    assert claimed_writer is not None and claimed_writer["task_id"] == writer["task_id"]
    writer_attempt = str(claimed_writer["current_attempt_id"])
    writer_result = atomic_write_json(
        result_root / "writer-result.json",
        {
            "schema_version": RESULT_SCHEMA,
            "task_id": writer["task_id"],
            "campaign_id": "campaign-1",
            "lab_id": "math",
            "domain": "math",
            "status": "completed",
            "summary": "A bounded manuscript snapshot is ready for independent review.",
            "artifacts": [
                {
                    "artifact_id": "manuscript-evidence",
                    "uri": evidence.resolve().as_uri(),
                    "sha256": sha256_file(evidence),
                }
            ],
            "claims": [
                {
                    "claim_id": "draft-claim",
                    "text": "The draft preserves the bounded evidence claim.",
                    "status": "supported",
                    "evidence": ["manuscript-evidence"],
                    "limitations": ["The review panel has not yet accepted the draft."],
                }
            ],
            "next_actions": [],
            "paper_candidate": True,
        },
    )
    db.bind_attempt_spec(
        str(writer["task_id"]),
        attempt_id=writer_attempt,
        lab_id="math",
        output_path=str(writer_result),
    )
    db.mark_running(
        str(writer["task_id"]),
        attempt_id=writer_attempt,
        owner="writer",
        pid=125,
        lease_seconds=60,
    )
    atomic_write_json(
        paths.result_inbox / "writer.json",
        {
            "schema_version": RECEIPT_SCHEMA,
            "task_id": writer["task_id"],
            "attempt_id": writer_attempt,
            "campaign_id": "campaign-1",
            "lab_id": "math",
            "domain": "math",
            "agent_role": "writer",
            "result_path": str(writer_result),
            "sha256": sha256_file(writer_result),
            "runtime": {
                "duration_seconds": 1.0,
                "exit_code": 0,
                "session_id": "writer-session",
            },
        },
    )

    writer_report = TickReport()
    ingest_results(db, paths, FactorySettings(), writer_report)

    assert len(writer_report.enqueued) == 1
    paper_review = db.task(writer_report.enqueued[0])
    assert paper_review is not None
    assert paper_review["task_type"] == "paper_review"
    assert paper_review["agent_role"] == "reviewer"
    assert paper_review["session_mode"] == "fresh"
    assert paper_review["skill_path"] == "openlabs-paper-review"

    claimed_panel = db.claim_next_task(owner="panel", lease_seconds=60)
    assert claimed_panel is not None and claimed_panel["task_id"] == paper_review["task_id"]
    panel_attempt = str(claimed_panel["current_attempt_id"])
    panel_result = atomic_write_json(
        result_root / "panel-result.json",
        {
            "schema_version": RESULT_SCHEMA,
            "task_id": paper_review["task_id"],
            "campaign_id": "campaign-1",
            "lab_id": "math",
            "domain": "math",
            "status": "completed",
            "summary": "The panel requests a bounded text-only correction.",
            "artifacts": [],
            "claims": [],
            "next_actions": [
                {
                    "objective": "Correct the stated limitation without changing the claim.",
                    "agent_role": "writer",
                    "session_mode": "resume",
                    "handoff_kind": "text_revision",
                }
            ],
            "paper_candidate": False,
        },
    )
    db.bind_attempt_spec(
        str(paper_review["task_id"]),
        attempt_id=panel_attempt,
        lab_id="math",
        output_path=str(panel_result),
    )
    db.mark_running(
        str(paper_review["task_id"]),
        attempt_id=panel_attempt,
        owner="panel",
        pid=126,
        lease_seconds=60,
    )
    atomic_write_json(
        paths.result_inbox / "panel.json",
        {
            "schema_version": RECEIPT_SCHEMA,
            "task_id": paper_review["task_id"],
            "attempt_id": panel_attempt,
            "campaign_id": "campaign-1",
            "lab_id": "math",
            "domain": "math",
            "agent_role": "reviewer",
            "result_path": str(panel_result),
            "sha256": sha256_file(panel_result),
            "runtime": {
                "duration_seconds": 1.0,
                "exit_code": 0,
                "session_id": "discarded-review-session",
            },
        },
    )

    panel_report = TickReport()
    ingest_results(db, paths, FactorySettings(), panel_report)

    assert len(panel_report.enqueued) == 1
    revision = db.task(panel_report.enqueued[0])
    assert revision is not None
    assert revision["task_type"] == "paper_revision"
    assert revision["agent_role"] == "writer"
    assert revision["session_mode"] == "resume"
    assert revision["agent_session_id"] == "writer-session"
    assert revision["session_source_task_id"] == writer["task_id"]
