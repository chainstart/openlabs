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


def test_protocol_routing_usage_counts_tasks_and_actual_attempt_time(tmp_path) -> None:
    db = FactoryDB(tmp_path / "factory.sqlite")
    db.initialize()
    db.register_campaign("policy-campaign", domain="math", title="Policy campaign")
    db.enqueue_task(
        task_id="stage-a-1",
        campaign_id="policy-campaign",
        domain="math",
        task_type="research",
        objective="Run stage A.",
        routing_reason="protocol_hook:policy:stage-a",
    )
    task = db.claim_next_task(owner="test", lease_seconds=60)
    assert task is not None
    attempt_id = str(task["current_attempt_id"])
    db.mark_running(
        "stage-a-1",
        attempt_id=attempt_id,
        owner="test",
        pid=123,
        lease_seconds=60,
    )
    db.ingest_result(
        "stage-a-1",
        attempt_id=attempt_id,
        status="completed",
        result_path="/tmp/result.json",
        result_sha256="0" * 64,
        valid=True,
        gate_passed=True,
        blockers=[],
        run_seconds=12.5,
        runtime={},
    )
    db.enqueue_task(
        task_id="stage-a-2",
        campaign_id="policy-campaign",
        domain="math",
        task_type="research",
        objective="Run stage A again.",
        routing_reason="protocol_hook:policy:stage-a",
    )
    db.enqueue_task(
        task_id="stage-b-1",
        campaign_id="policy-campaign",
        domain="math",
        task_type="research",
        objective="Run stage B.",
        routing_reason="protocol_hook:policy:stage-b",
    )

    usage = db.campaign_routing_usage("policy-campaign")

    assert usage["protocol_hook:policy:stage-a"] == {
        "task_count": 2,
        "agent_seconds": 12.5,
    }
    assert usage["protocol_hook:policy:stage-b"] == {
        "task_count": 1,
        "agent_seconds": 0.0,
    }


def test_protocol_failure_replay_is_narrow_and_does_not_double_charge(tmp_path) -> None:
    db = FactoryDB(tmp_path / "factory.sqlite")
    db.initialize()
    db.register_campaign("physics", domain="physics", title="Physics")
    task_id = db.enqueue_task(
        task_id="physics-task",
        campaign_id="physics",
        domain="physics",
        task_type="research",
        objective="Replay only a protocol infrastructure failure.",
    )
    task = db.claim_next_task(owner="test", lease_seconds=60)
    assert task is not None
    attempt_id = str(task["current_attempt_id"])
    db.mark_running(
        task_id,
        attempt_id=attempt_id,
        owner="test",
        pid=123,
        lease_seconds=60,
    )
    error = "attempt_commit_failed:protocol validator emitted invalid JSON"
    final = db.ingest_result(
        task_id,
        attempt_id=attempt_id,
        status="needs_replan",
        result_path="/tmp/result.json",
        result_sha256="0" * 64,
        valid=True,
        gate_passed=True,
        blockers=[],
        run_seconds=12.5,
        runtime={"transaction_error": error},
        error=error,
    )
    assert final == "needs_replan"
    assert db.campaign("physics")["agent_seconds_used"] == 12.5

    replay = db.reopen_protocol_failed_attempt(
        task_id,
        attempt_id=attempt_id,
        expected_error_fragment="protocol validator emitted invalid JSON",
    )
    assert replay["prior_run_seconds"] == 12.5
    assert db.task(task_id)["status"] == "running"
    assert db.campaign("physics")["agent_seconds_used"] == 0

    final = db.ingest_result(
        task_id,
        attempt_id=attempt_id,
        status="completed",
        result_path="/tmp/result.json",
        result_sha256="0" * 64,
        valid=True,
        gate_passed=True,
        blockers=[],
        run_seconds=12.5,
        runtime={},
    )
    assert final == "succeeded"
    assert db.campaign("physics")["agent_seconds_used"] == 12.5


def test_hook_receipt_failure_replay_requires_exact_named_error(tmp_path) -> None:
    db = FactoryDB(tmp_path / "factory.sqlite")
    db.initialize()
    db.register_campaign("physics", domain="physics", title="Physics")
    task_id = db.enqueue_task(
        task_id="physics-hook-task",
        campaign_id="physics",
        domain="physics",
        task_type="research",
        objective="Replay only a known hook compatibility failure.",
    )
    task = db.claim_next_task(owner="test", lease_seconds=60)
    assert task is not None
    attempt_id = str(task["current_attempt_id"])
    db.mark_running(
        task_id,
        attempt_id=attempt_id,
        owner="test",
        pid=123,
        lease_seconds=60,
    )
    error = "Codex lifecycle hook receipts are incomplete"
    final = db.ingest_result(
        task_id,
        attempt_id=attempt_id,
        status="needs_replan",
        result_path="/tmp/result.json",
        result_sha256="0" * 64,
        valid=True,
        gate_passed=True,
        blockers=[],
        run_seconds=7.5,
        runtime={"hook_receipt_error": error},
        error=error,
    )
    assert final == "needs_replan"
    assert db.campaign("physics")["agent_seconds_used"] == 7.5

    with pytest.raises(ValueError, match="expected infrastructure error"):
        db.reopen_protocol_failed_attempt(
            task_id,
            attempt_id=attempt_id,
            expected_error_fragment="different hook failure",
            runtime_error_key="hook_receipt_error",
        )

    replay = db.reopen_protocol_failed_attempt(
        task_id,
        attempt_id=attempt_id,
        expected_error_fragment=error,
        runtime_error_key="hook_receipt_error",
    )
    assert replay["runtime_error_key"] == "hook_receipt_error"
    assert replay["prior_run_seconds"] == 7.5
    assert db.task(task_id)["status"] == "running"
    assert db.campaign("physics")["agent_seconds_used"] == 0


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


def test_initialize_never_copies_attempt_output_into_task_intent(tmp_path) -> None:
    db = FactoryDB(tmp_path / "factory.sqlite")
    db.initialize()
    db.register_campaign("campaign", domain="math", title="Campaign")
    db.enqueue_task(
        task_id="task",
        campaign_id="campaign",
        domain="math",
        task_type="research",
        objective="Keep requested output immutable across ticks.",
    )
    task = db.claim_next_task(owner="test", lease_seconds=60)
    assert task is not None
    attempt_output = tmp_path / "artifacts" / "attempt-workspaces" / "one" / "result.json"
    db.bind_attempt_spec(
        "task",
        attempt_id=str(task["current_attempt_id"]),
        lab_id="math",
        output_path=str(attempt_output),
    )

    db.initialize()
    row = db.task("task")

    assert row["requested_output_path"] is None
    assert row["output_path"] == str(attempt_output)


def test_v6_migration_removes_only_attempt_local_requested_outputs(tmp_path) -> None:
    db = FactoryDB(tmp_path / "factory.sqlite")
    db.initialize()
    db.register_campaign("campaign", domain="math", title="Campaign")
    canonical = "/data/workspaces/math/campaign/result.json"
    db.enqueue_task(
        task_id="canonical",
        campaign_id="campaign",
        domain="math",
        task_type="research",
        objective="Preserve explicit task intent.",
        output_path=canonical,
    )
    db.enqueue_task(
        task_id="polluted",
        campaign_id="campaign",
        domain="math",
        task_type="research",
        objective="Clean an attempt-local migration artifact.",
        output_path="/artifacts/attempt-workspaces/campaign/attempt/result.json",
    )
    with db.connect() as connection:
        connection.execute("UPDATE meta SET value='5' WHERE key='schema_version'")

    db.initialize()

    assert db.task("canonical")["requested_output_path"] == canonical
    assert db.task("polluted")["requested_output_path"] is None


def test_expired_task_from_paused_production_is_cancelled_not_requeued(tmp_path) -> None:
    db = FactoryDB(tmp_path / "factory.sqlite")
    db.initialize()
    db.register_campaign("route", domain="math", title="Route")
    db.configure_continuous_campaign(
        "route",
        production_plan_path="/data/production_plan.json",
        production_lane_path="/data/production_lane.json",
    )
    db.enqueue_task(
        task_id="in-flight",
        campaign_id="route",
        domain="math",
        task_type="research",
        objective="Do not resurrect after route retirement.",
    )
    task = db.claim_next_task(owner="test", lease_seconds=60)
    assert task is not None
    db.mark_running(
        "in-flight",
        attempt_id=str(task["current_attempt_id"]),
        owner="test",
        pid=123,
        lease_seconds=60,
    )
    db.pause_production_campaign("route", reason="plan_retired")
    with db.connect() as connection:
        connection.execute(
            "UPDATE tasks SET lease_expires_at='2000-01-01T00:00:00Z' WHERE task_id='in-flight'"
        )

    recovery = db.recover_expired()

    assert recovery.requeued == ()
    assert recovery.quarantined == ()
    assert recovery.cancelled == ("in-flight",)
    assert db.task("in-flight")["status"] == "cancelled"


def test_stale_queue_of_inactive_campaign_is_cancelled(tmp_path) -> None:
    db = FactoryDB(tmp_path / "factory.sqlite")
    db.initialize()
    db.register_campaign("paused", domain="math", title="Paused")
    db.enqueue_task(
        task_id="stale",
        campaign_id="paused",
        domain="math",
        task_type="research",
        objective="Must not remain queued after campaign pause.",
    )
    db.register_campaign("paused", domain="math", title="Paused", status="paused")

    assert db.cancel_queued_tasks_for_inactive_campaigns() == ("stale",)
    assert db.task("stale")["status"] == "cancelled"


def test_operator_cancellation_stops_active_attempt_and_accounts_time(tmp_path) -> None:
    db = FactoryDB(tmp_path / "factory.sqlite")
    db.initialize()
    db.register_campaign("route", domain="math", title="Route")
    db.enqueue_task(
        task_id="in-flight",
        campaign_id="route",
        domain="math",
        task_type="research",
        objective="Stop cleanly at the run deadline.",
        max_wall_seconds=3600,
    )
    task = db.claim_next_task(owner="test", lease_seconds=60)
    assert task is not None
    attempt_id = str(task["current_attempt_id"])
    db.mark_running(
        "in-flight",
        attempt_id=attempt_id,
        owner="test",
        pid=4321,
        lease_seconds=60,
    )

    cancelled = db.cancel_active_tasks(("route",), reason="timebox_expired")

    assert len(cancelled) == 1
    assert cancelled[0]["task_id"] == "in-flight"
    assert cancelled[0]["worker_pid"] == 4321
    assert cancelled[0]["run_seconds"] >= 0
    row = db.task("in-flight")
    assert row["status"] == "cancelled"
    assert row["worker_pid"] is None
    assert row["current_attempt_id"] is None
    attempt = db.task_attempts("in-flight")[0]
    assert attempt["status"] == "cancelled"
    assert attempt["error"] == "operator_cancelled:timebox_expired"
    assert db.campaign("route")["agent_seconds_used"] == cancelled[0]["run_seconds"]


def test_sessions_cannot_cross_roles_or_enter_reviewer_tasks(tmp_path) -> None:
    db = FactoryDB(tmp_path / "factory.sqlite")
    db.initialize()
    db.register_campaign("campaign", domain="math", title="Campaign")
    with pytest.raises(ValueError, match="source task"):
        db.enqueue_task(
            task_id="unscoped-session",
            campaign_id="campaign",
            domain="math",
            task_type="research",
            objective="Must not accept an unscoped session.",
            agent_session_id="unknown-session",
        )
    db.enqueue_task(
        task_id="research",
        campaign_id="campaign",
        domain="math",
        task_type="research",
        objective="Research.",
    )
    with db.connect() as connection:
        connection.execute(
            "UPDATE tasks SET agent_session_id='research-session' WHERE task_id='research'"
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


def test_continuous_campaign_cannot_roll_over_its_lifetime_budget(tmp_path) -> None:
    db = FactoryDB(tmp_path / "factory.sqlite")
    db.initialize()
    db.register_campaign(
        "continuous",
        domain="math",
        title="Continuous lane",
        max_agent_seconds=10,
    )
    db.configure_continuous_campaign(
        "continuous",
        production_plan_path="/data/production_plan.json",
        production_lane_path="/data/production_lane.json",
    )
    db.enqueue_task(
        task_id="epoch-1",
        campaign_id="continuous",
        domain="math",
        task_type="research",
        objective="Use the first production window.",
    )
    with db.connect() as connection:
        connection.execute("UPDATE tasks SET status='succeeded' WHERE task_id='epoch-1'")
        connection.execute(
            """
            UPDATE campaigns
            SET agent_seconds_used=12, epoch_agent_seconds_used=12
            WHERE campaign_id='continuous'
            """
        )

    db.enqueue_task(
        task_id="epoch-2",
        campaign_id="continuous",
        domain="math",
        task_type="research",
        objective="Must not receive a renewed time budget.",
    )

    assert db.stop_budget_exhausted_tasks() == ["epoch-2"]
    campaign = db.campaign("continuous")
    assert campaign["status"] == "budget_exhausted"
    assert campaign["continuous"] == 0
    assert campaign["agent_seconds_used"] == 12
    assert campaign["epoch_agent_seconds_used"] == 12
    assert campaign["rollover_count"] == 0
    assert db.task("epoch-2")["status"] == "needs_human"
    with pytest.raises(ValueError, match="not continuous"):
        db.rollover_campaign_epoch(
            "continuous",
            reason="agent_time_window_exhausted",
            source_task_id="epoch-1",
        )
    assert db.claim_next_task(owner="test", lease_seconds=60) is None


def test_overlapping_claims_cannot_overbook_resources(tmp_path) -> None:
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
        return db.claim_next_task(
            owner=owner,
            lease_seconds=60,
            max_active=8,
            resource_capacity={
                "cpu_threads": 2,
                "memory_mib": 4_096,
                "scratch_mib": 4_096,
            },
        )

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


def test_resource_admission_skips_an_oversized_queue_head(tmp_path) -> None:
    db = FactoryDB(tmp_path / "factory.sqlite")
    db.initialize()
    for campaign_id in ("large", "small"):
        db.register_campaign(campaign_id, domain="ai", title=campaign_id)
    db.enqueue_task(
        task_id="large-task",
        campaign_id="large",
        domain="ai",
        task_type="experiment",
        objective="Wait for a larger resource window.",
        priority=10,
        cpu_threads=8,
        memory_mib=16_384,
        scratch_mib=32_768,
    )
    db.enqueue_task(
        task_id="small-task",
        campaign_id="small",
        domain="ai",
        task_type="research",
        objective="Fit the current resource window.",
        cpu_threads=1,
        memory_mib=1_024,
        scratch_mib=2_048,
    )

    task = db.claim_next_task(
        owner="scheduler",
        lease_seconds=60,
        max_active=8,
        resource_capacity={
            "cpu_threads": 4,
            "memory_mib": 8_192,
            "scratch_mib": 16_384,
        },
    )

    assert task is not None and task["task_id"] == "small-task"
    assert db.task("large-task")["status"] == "queued"
    assert db.active_resource_totals() == {
        "cpu_threads": 1,
        "memory_mib": 1_024,
        "scratch_mib": 2_048,
    }
    assert db.task_attempts("small-task")[0]["resources"] == {
        "cpu_threads": 1,
        "memory_mib": 1_024,
        "scratch_mib": 2_048,
    }


def test_cross_role_resume_uses_only_an_ancestor_session(tmp_path) -> None:
    db = FactoryDB(tmp_path / "factory.sqlite")
    db.initialize()
    db.register_campaign("campaign", domain="math", title="Campaign")
    db.enqueue_task(
        task_id="writer",
        campaign_id="campaign",
        domain="math",
        task_type="paper_write",
        objective="Write.",
        agent_role="writer",
    )
    with db.connect() as connection:
        connection.execute(
            "UPDATE tasks SET agent_session_id='writer-session' WHERE task_id='writer'"
        )
    db.enqueue_task(
        task_id="review",
        campaign_id="campaign",
        domain="math",
        task_type="paper_review",
        objective="Review.",
        parent_task_id="writer",
        agent_role="reviewer",
        session_mode="fresh",
    )
    db.enqueue_task(
        task_id="revision",
        campaign_id="campaign",
        domain="math",
        task_type="paper_revision",
        objective="Revise.",
        parent_task_id="review",
        agent_role="writer",
        session_mode="resume",
        session_source_task_id="writer",
    )

    revision = db.task("revision")
    assert revision["agent_session_id"] == "writer-session"
    assert revision["session_source_task_id"] == "writer"

    db.enqueue_task(
        task_id="unrelated-writer",
        campaign_id="campaign",
        domain="math",
        task_type="paper_write",
        objective="Unrelated draft.",
        agent_role="writer",
    )
    with db.connect() as connection:
        connection.execute(
            """
            UPDATE tasks SET agent_session_id='other-session'
            WHERE task_id='unrelated-writer'
            """
        )
    with pytest.raises(ValueError, match="parent lineage"):
        db.enqueue_task(
            task_id="contaminated-revision",
            campaign_id="campaign",
            domain="math",
            task_type="paper_revision",
            objective="Must not inherit a sibling conversation.",
            parent_task_id="review",
            agent_role="writer",
            session_mode="resume",
            session_source_task_id="unrelated-writer",
        )


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
