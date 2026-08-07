from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from openlabs.db import FactoryDB


def test_task_lease_recovery_and_ingestion(tmp_path) -> None:
    db = FactoryDB(tmp_path / "factory.sqlite")
    db.initialize()
    db.register_campaign("campaign-1", domain="math", title="Campaign 1")
    task_id = db.enqueue_task(
        task_id="task-1",
        campaign_id="campaign-1",
        domain="math",
        task_type="smoke",
        objective="Exercise recovery.",
        max_attempts=2,
    )
    task = db.claim_next_task(owner="test", lease_seconds=60)
    assert task and task["task_id"] == task_id
    first_attempt = str(task["current_attempt_id"])
    db.mark_running(
        task_id,
        attempt_id=first_attempt,
        owner="test",
        pid=123,
        lease_seconds=60,
    )
    with db.connect() as connection:
        connection.execute(
            "UPDATE tasks SET lease_expires_at='2000-01-01T00:00:00Z' WHERE task_id=?",
            (task_id,),
        )
    recovery = db.recover_expired()
    assert recovery.requeued == (task_id,)
    assert db.task(task_id)["status"] == "queued"
    recovered_seconds = db.campaign("campaign-1")["agent_seconds_used"]

    task = db.claim_next_task(owner="test-2", lease_seconds=60)
    assert task and task["attempt"] == 2
    second_attempt = str(task["current_attempt_id"])
    assert second_attempt != first_attempt
    db.mark_running(
        task_id,
        attempt_id=second_attempt,
        owner="test-2",
        pid=456,
        lease_seconds=60,
    )
    final = db.ingest_result(
        task_id,
        attempt_id=second_attempt,
        status="completed",
        result_path="/tmp/result.json",
        result_sha256="0" * 64,
        valid=True,
        gate_passed=True,
        blockers=[],
        run_seconds=2.5,
        runtime={"session_id": "session-1"},
    )
    assert final == "succeeded"
    assert db.status_counts() == {"succeeded": 1}
    attempts = db.task_attempts(task_id)
    assert [item["status"] for item in attempts] == ["lease_expired", "succeeded"]
    assert db.campaign("campaign-1")["agent_seconds_used"] == recovered_seconds + 2.5


def test_research_records_are_a_file_owned_query_index(tmp_path) -> None:
    db = FactoryDB(tmp_path / "factory.sqlite")
    db.initialize()
    db.upsert_research_record(
        "paper:test",
        kind="paper",
        domain="math",
        title="A test paper",
        status="draft",
        source_path="papers/test/paper.yaml",
        metadata={"version": "0.1.0"},
    )

    assert db.research_record_counts() == {"paper": 1}
    record = db.research_records()[0]
    assert record["source_path"] == "papers/test/paper.yaml"
    assert record["metadata"] == {"version": "0.1.0"}

    with db.connect() as connection:
        events_before = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    db.upsert_research_record(
        "paper:test",
        kind="paper",
        domain="math",
        title="A test paper",
        status="draft",
        source_path="papers/test/paper.yaml",
        metadata={"version": "0.1.0"},
    )
    with db.connect() as connection:
        events_after = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert events_after == events_before


def test_expired_task_obeys_retry_backoff(tmp_path) -> None:
    db = FactoryDB(tmp_path / "factory.sqlite")
    db.initialize()
    db.register_campaign("campaign-1", domain="ai", title="Campaign 1")
    db.enqueue_task(
        task_id="task-1",
        campaign_id="campaign-1",
        domain="ai",
        task_type="research",
        objective="Exercise retry delay.",
    )
    task = db.claim_next_task(owner="test", lease_seconds=60)
    assert task is not None
    db.mark_running(
        "task-1",
        attempt_id=str(task["current_attempt_id"]),
        owner="test",
        pid=123,
        lease_seconds=60,
    )
    with db.connect() as connection:
        connection.execute(
            "UPDATE tasks SET lease_expires_at='2000-01-01T00:00:00Z' WHERE task_id='task-1'"
        )

    recovery = db.recover_expired(retry_backoff_seconds=120)

    assert recovery.requeued == ("task-1",)
    assert db.task("task-1")["not_before"] is not None
    assert db.claim_next_task(owner="too-early", lease_seconds=60) is None


def test_sessions_cannot_cross_roles_or_enter_reviewer_tasks(tmp_path) -> None:
    db = FactoryDB(tmp_path / "factory.sqlite")
    db.initialize()
    db.register_campaign("campaign", domain="math", title="Campaign")
    db.enqueue_task(
        task_id="research",
        campaign_id="campaign",
        domain="math",
        task_type="research",
        objective="Research.",
        agent_session_id="research-session",
    )

    with pytest.raises(ValueError, match="role"):
        db.enqueue_task(
            task_id="writer",
            campaign_id="campaign",
            domain="math",
            task_type="paper_write",
            objective="Write independently.",
            parent_task_id="research",
            agent_role="writer",
            session_mode="resume",
        )
    with pytest.raises(ValueError, match="reviewer"):
        db.enqueue_task(
            task_id="review",
            campaign_id="campaign",
            domain="math",
            task_type="review",
            objective="Review independently.",
            agent_role="reviewer",
            session_mode="resume",
        )

    db.enqueue_task(
        task_id="review",
        campaign_id="campaign",
        domain="math",
        task_type="review",
        objective="Review independently.",
        parent_task_id="research",
        agent_role="reviewer",
    )
    review = db.task("review")
    assert review["session_mode"] == "fresh"
    assert review["agent_session_id"] is None


def test_global_concurrency_and_campaign_time_budget_are_hard_limits(tmp_path) -> None:
    db = FactoryDB(tmp_path / "factory.sqlite")
    db.initialize()
    db.register_campaign(
        "campaign-1",
        domain="ai",
        title="Campaign 1",
        max_agent_seconds=1,
    )
    db.register_campaign("campaign-2", domain="ai", title="Campaign 2")
    for campaign_id in ("campaign-1", "campaign-2"):
        db.enqueue_task(
            task_id=f"{campaign_id}:task",
            campaign_id=campaign_id,
            domain="ai",
            task_type="research",
            objective="Use a bounded slot.",
            priority=10 if campaign_id == "campaign-1" else 0,
        )
    db.enqueue_task(
        task_id="campaign-1:next",
        campaign_id="campaign-1",
        domain="ai",
        task_type="research",
        objective="Must stop at the campaign budget.",
    )

    task = db.claim_next_task(owner="one", lease_seconds=60, max_active=1)
    assert task is not None and task["campaign_id"] == "campaign-1"
    assert db.claim_next_task(owner="two", lease_seconds=60, max_active=1) is None
    attempt_id = str(task["current_attempt_id"])
    db.mark_running(
        str(task["task_id"]),
        attempt_id=attempt_id,
        owner="one",
        pid=1,
        lease_seconds=60,
    )
    db.ingest_result(
        str(task["task_id"]),
        attempt_id=attempt_id,
        status="completed",
        result_path="/tmp/result.json",
        result_sha256="0" * 64,
        valid=True,
        gate_passed=True,
        blockers=[],
        run_seconds=1.1,
        runtime={},
    )

    assert db.stop_budget_exhausted_tasks() == ["campaign-1:next"]
    assert db.campaign("campaign-1")["status"] == "budget_exhausted"
    assert db.task("campaign-1:next")["status"] == "needs_human"
    next_task = db.claim_next_task(owner="two", lease_seconds=60, max_active=1)
    assert next_task is not None and next_task["campaign_id"] == "campaign-2"


def test_overlapping_claims_cannot_exceed_global_capacity(tmp_path) -> None:
    db = FactoryDB(tmp_path / "factory.sqlite")
    db.initialize()
    for index in (1, 2):
        campaign_id = f"campaign-{index}"
        db.register_campaign(campaign_id, domain="ai", title=campaign_id)
        db.enqueue_task(
            task_id=f"task-{index}",
            campaign_id=campaign_id,
            domain="ai",
            task_type="research",
            objective="Compete for one slot.",
        )
    barrier = Barrier(2)

    def claim(owner: str) -> dict | None:
        barrier.wait()
        return db.claim_next_task(owner=owner, lease_seconds=60, max_active=1)

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(claim, ("one", "two")))

    assert sum(item is not None for item in claims) == 1
    assert db.active_count() == 1


def test_one_campaign_cannot_claim_two_simultaneous_tasks(tmp_path) -> None:
    db = FactoryDB(tmp_path / "factory.sqlite")
    db.initialize()
    db.register_campaign("campaign-1", domain="math", title="Campaign 1")
    db.register_campaign("campaign-2", domain="math", title="Campaign 2")
    for task_id in ("campaign-1:first", "campaign-1:second"):
        db.enqueue_task(
            task_id=task_id,
            campaign_id="campaign-1",
            domain="math",
            task_type="research",
            objective="Stay sequential.",
            priority=10,
        )
    db.enqueue_task(
        task_id="campaign-2:first",
        campaign_id="campaign-2",
        domain="math",
        task_type="research",
        objective="Use the other slot.",
    )

    first = db.claim_next_task(owner="one", lease_seconds=60, max_active=2)
    second = db.claim_next_task(owner="two", lease_seconds=60, max_active=2)

    assert first is not None and first["campaign_id"] == "campaign-1"
    assert second is not None and second["campaign_id"] == "campaign-2"


def test_expired_process_time_counts_against_campaign_budget(tmp_path) -> None:
    db = FactoryDB(tmp_path / "factory.sqlite")
    db.initialize()
    db.register_campaign(
        "campaign",
        domain="materials",
        title="Campaign",
        max_agent_seconds=5,
    )
    db.enqueue_task(
        task_id="task",
        campaign_id="campaign",
        domain="materials",
        task_type="experiment",
        objective="Account for a killed process.",
        max_wall_seconds=5,
    )
    task = db.claim_next_task(owner="test", lease_seconds=60)
    assert task is not None
    attempt_id = str(task["current_attempt_id"])
    db.mark_running(
        "task",
        attempt_id=attempt_id,
        owner="test",
        pid=1,
        lease_seconds=60,
    )
    with db.connect() as connection:
        connection.execute(
            "UPDATE tasks SET lease_expires_at='2000-01-01T00:00:00Z' WHERE task_id='task'"
        )
        connection.execute(
            "UPDATE task_attempts SET started_at='2000-01-01T00:00:00Z' WHERE attempt_id=?",
            (attempt_id,),
        )

    recovery = db.recover_expired()

    assert recovery.requeued == ("task",)
    assert db.campaign("campaign")["agent_seconds_used"] == 5
    assert db.stop_budget_exhausted_tasks() == ["task"]
    assert db.task("task")["status"] == "needs_human"
