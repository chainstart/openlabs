from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from openlabs import budget as budget_control
from openlabs import engine
from openlabs.config import (
    BudgetSettings,
    FactorySettings,
    ProgramSettings,
    WorkspacePaths,
    load_settings,
)
from openlabs.contracts import RECEIPT_SCHEMA, RESULT_SCHEMA, atomic_write_json, sha256_file
from openlabs.db import FactoryDB
from openlabs.engine import TickReport, ingest_results
from openlabs.program import activate_topic, admit_topic, open_topic_ledger, propose_topic

NOW = datetime.now(UTC).replace(microsecond=0)


def _paths(tmp_path: Path) -> WorkspacePaths:
    paths = WorkspacePaths(
        workspace=tmp_path,
        code=tmp_path / "openlabs",
        data=tmp_path / "data",
        artifacts=tmp_path / "artifacts",
        database=tmp_path / "database",
        database_file=tmp_path / "database" / "live" / "factory.sqlite",
    )
    paths.ensure_runtime_directories()
    return paths


def _settings(**budget) -> FactorySettings:
    return FactorySettings(
        max_worker_processes=8,
        retry_backoff_seconds=0,
        budget=replace(BudgetSettings(max_parallel_agents=4), **budget),
    )


def _setup(tmp_path: Path) -> tuple[WorkspacePaths, FactoryDB]:
    paths = _paths(tmp_path)
    db = FactoryDB(paths.database_file)
    db.initialize()
    return paths, db


def _enqueue(db: FactoryDB, task_id: str, campaign_id: str, *, runner: str = "balanced",
             priority: int = 0, max_attempts: int = 3) -> None:
    if db.campaign(campaign_id) is None:
        db.register_campaign(campaign_id, domain="math", title=campaign_id)
    db.enqueue_task(
        task_id=task_id,
        campaign_id=campaign_id,
        domain="math",
        task_type="research",
        objective="Bounded step.",
        runner=runner,
        priority=priority,
        max_attempts=max_attempts,
    )


def _start(db: FactoryDB, paths: WorkspacePaths, task_id: str) -> tuple[str, Path]:
    with db.connect() as connection:
        connection.execute("UPDATE tasks SET not_before=NULL WHERE task_id=?", (task_id,))
    task = db.claim_next_task(owner="test", lease_seconds=600)
    assert task is not None and task["task_id"] == task_id
    attempt_id = str(task["current_attempt_id"])
    output = paths.data / "workspaces" / "math" / str(task["campaign_id"]) / attempt_id / "r.json"
    db.bind_attempt_spec(task_id, attempt_id=attempt_id, lab_id="math", output_path=str(output))
    db.mark_running(task_id, attempt_id=attempt_id, owner="test", pid=1, lease_seconds=600)
    return attempt_id, output


def _deliver(db: FactoryDB, paths: WorkspacePaths, task_id: str, attempt_id: str,
             output: Path, *, quota: bool, reset_at: str | None = None,
             status: str = "failed") -> None:
    task = db.task(task_id)
    assert task is not None
    atomic_write_json(
        output,
        {
            "schema_version": RESULT_SCHEMA,
            "task_id": task_id,
            "campaign_id": task["campaign_id"],
            "lab_id": "math",
            "domain": "math",
            "status": status,
            "summary": "Agent provider quota stop." if quota else "Agent failed.",
            "artifacts": [],
            "claims": [],
            "next_actions": ["Retry later."],
        },
    )
    runtime: dict = {"duration_seconds": 2.0, "exit_code": 0, "runner": task["runner"]}
    if quota:
        runtime.update(
            failure_class="agent_quota",
            quota={"kind": "usage_limit", "source": "stdout_jsonl", "excerpt": "hit limit"},
            quota_reset_at=reset_at,
        )
    atomic_write_json(
        paths.result_inbox / f"{attempt_id}.json",
        {
            "schema_version": RECEIPT_SCHEMA,
            "task_id": task_id,
            "attempt_id": attempt_id,
            "campaign_id": task["campaign_id"],
            "lab_id": "math",
            "domain": "math",
            "agent_role": "researcher",
            "result_path": str(output),
            "sha256": sha256_file(output),
            "runtime": runtime,
        },
    )


@pytest.fixture
def clock(monkeypatch):
    state = {"now": NOW}
    monkeypatch.setattr(budget_control, "current_time", lambda: state["now"])
    return state


def _event_types(db: FactoryDB) -> list[str]:
    return [event["event_type"] for event in db.events()]


def test_quota_failure_requeues_without_consuming_attempts(tmp_path, clock) -> None:
    paths, db = _setup(tmp_path)
    settings = _settings()
    _enqueue(db, "t", "c", max_attempts=3)
    attempt_id, output = _start(db, paths, "t")
    _deliver(db, paths, "t", attempt_id, output, quota=True)

    report = TickReport()
    ingest_results(db, paths, settings, report)

    task = db.task("t")
    assert task["status"] == "queued"
    assert int(task["max_attempts"]) - int(task["attempt"]) == 3  # nothing consumed
    expected_until = (NOW + timedelta(minutes=15)).isoformat().replace("+00:00", "Z")
    assert task["not_before"] == expected_until
    assert db.task_attempts("t")[-1]["status"] == "quota_deferred"
    assert report.quota_deferred[0]["not_before"] == expected_until
    assert report.ingested == []
    types = _event_types(db)
    assert "quota_deferred" in types and "quota_backoff" in types
    assert "parallel_reduced" in types and "task_needs_human" not in types
    assert budget_control.effective_parallel(db, settings) == 2
    assert budget_control.runner_backoffs(db, now=NOW) == {"balanced": expected_until}
    # The unchanged task is not claimable before its backoff ends.
    assert db.claim_next_task(owner="x", lease_seconds=60) is None


def test_consecutive_quota_failures_fall_back_to_ordinary_failure(tmp_path, clock) -> None:
    paths, db = _setup(tmp_path)
    settings = _settings(quota_retry_limit=2)
    _enqueue(db, "t", "c", max_attempts=2)
    for _ in range(2):
        attempt_id, output = _start(db, paths, "t")
        _deliver(db, paths, "t", attempt_id, output, quota=True)
        ingest_results(db, paths, settings, TickReport())
        assert db.task("t")["status"] == "queued"
    # Third consecutive quota stop exceeds the limit: ordinary failure handling.
    attempt_id, output = _start(db, paths, "t")
    _deliver(db, paths, "t", attempt_id, output, quota=True)
    report = TickReport()
    ingest_results(db, paths, settings, report)

    task = db.task("t")
    assert report.quota_deferred == []
    assert report.ingested == [{"task_id": "t", "status": "queued"}]
    assert int(task["max_attempts"]) - int(task["attempt"]) == 1  # this one counted
    assert "quota retry limit exhausted" in str(task["last_error"])
    exhausted = [e for e in db.events() if e["event_type"] == "quota_retry_exhausted"]
    assert exhausted and exhausted[0]["payload"]["consecutive_quota_failures"] == 3
    assert exhausted[0]["payload"]["handling"] == "ordinary_failure"
    # Once attempts run out the ordinary path quarantines (no infinite quota loop).
    attempt_id, output = _start(db, paths, "t")
    _deliver(db, paths, "t", attempt_id, output, quota=True)
    ingest_results(db, paths, settings, TickReport())
    assert db.task("t")["status"] == "quarantined"


def test_backoff_blocks_only_that_runner(tmp_path, clock) -> None:
    _paths_, db = _setup(tmp_path)
    settings = _settings()
    _enqueue(db, "frontier-task", "c1", runner="frontier", priority=10)
    _enqueue(db, "balanced-task", "c2", runner="balanced", priority=0)
    budget_control.record_quota_failure(db, settings, runner="frontier", now=NOW)

    blocked = budget_control.runner_backoffs(db, now=NOW)
    assert set(blocked) == {"frontier"}
    claimed = db.claim_next_task(owner="x", lease_seconds=60, excluded_runners=tuple(blocked))
    assert claimed is not None and claimed["task_id"] == "balanced-task"
    assert db.claim_next_task(owner="x", lease_seconds=60, excluded_runners=tuple(blocked)) is None
    # After the window the frontier runner is claimable again, one probe at a time.
    later = NOW + timedelta(minutes=16)
    assert budget_control.runner_backoffs(db, now=later) == {}
    assert budget_control.probe_limits(db, now=later) == {"frontier": 1}


def test_tick_launch_loop_uses_effective_parallel_and_skips_backoff(
    tmp_path, clock, monkeypatch
) -> None:
    paths, db = _setup(tmp_path)
    settings = replace(
        _settings(),
        reserve_cpu_threads=0,
        reserve_memory_mib=0,
        reserve_scratch_mib=0,
        auto_continue=False,
    )
    for index in range(4):
        _enqueue(db, f"b{index}", f"cb{index}", runner="balanced")
    _enqueue(db, "f0", "cf0", runner="frontier", priority=5)
    for task_id in [f"b{i}" for i in range(4)] + ["f0"]:
        with db.connect() as connection:
            connection.execute(
                "UPDATE tasks SET cpu_threads=0, memory_mib=0, scratch_mib=0 WHERE task_id=?",
                (task_id,),
            )
    launched: list[str] = []
    monkeypatch.setattr(
        engine,
        "_launch_task",
        lambda _db, _paths, _settings, task, owner: launched.append(str(task["task_id"])),
    )
    budget_control.record_quota_failure(db, settings, runner="frontier", now=NOW)  # 4 -> 2

    report = engine.tick(paths, settings)

    assert report.effective_parallel == 2
    assert set(report.provider_backoff_until) == {"frontier"}
    assert report.to_dict()["provider_backoff_until"] == report.provider_backoff_until
    assert launched == ["b0", "b1"]  # frontier (higher priority) is in backoff


def test_parallel_halves_and_restores_stepwise(tmp_path) -> None:
    _paths_, db = _setup(tmp_path)
    settings = _settings()  # ceiling min(8, 4) == 4
    assert budget_control.effective_parallel(db, settings) == 4
    first = budget_control.record_quota_failure(db, settings, runner="balanced", now=NOW)
    assert (first.parallel_before, first.parallel_after, first.escalated) == (4, 2, True)
    # Other agents launched before the hit report quota too: no further halving.
    echo = budget_control.record_quota_failure(
        db, settings, runner="balanced", now=NOW + timedelta(minutes=1)
    )
    assert (echo.parallel_after, echo.escalated, echo.until) == (2, False, first.until)
    # A healthy completion inside the window proves nothing.
    assert budget_control.record_healthy_completion(
        db, settings, runner="balanced", now=NOW + timedelta(minutes=5)
    ) is None
    after = NOW + timedelta(minutes=16)
    assert budget_control.probe_limits(db, now=after) == {"balanced": 1}
    assert budget_control.record_healthy_completion(
        db, settings, runner="balanced", now=after
    ) == 3
    assert budget_control.probe_limits(db, now=after) == {}
    assert budget_control.record_healthy_completion(
        db, settings, runner="balanced", now=after
    ) == 4
    assert db.meta_get(budget_control.EFFECTIVE_PARALLEL_KEY) is None  # fully restored
    assert budget_control.record_healthy_completion(
        db, settings, runner="balanced", now=after
    ) is None
    types = _event_types(db)
    assert types.count("parallel_reduced") == 1
    assert types.count("parallel_restored") == 2
    # Halving bottoms out at one.
    for step in range(4):
        moment = after + timedelta(hours=6 * (step + 1))
        budget_control.record_quota_failure(db, settings, runner="balanced", now=moment)
    assert budget_control.effective_parallel(db, settings) == 1


def test_exponential_sequence_and_reset_time_with_cap(tmp_path) -> None:
    _paths_, db = _setup(tmp_path)
    settings = _settings()
    iso = budget_control._iso
    # Consecutive escalations without a healthy completion walk the sequence.
    moment = NOW
    for minutes in (15, 30, 60, 120, 300, 300):
        result = budget_control.record_quota_failure(db, settings, runner="r", now=moment)
        assert result.until == iso(moment + timedelta(minutes=minutes))
        moment = budget_control.parse_time(result.until) + timedelta(seconds=1)
    # A parsed reset later than the exponential step wins...
    later = budget_control.record_quota_failure(
        db, settings, runner="p", reset_at=iso(NOW + timedelta(minutes=90)), now=NOW
    )
    assert later.until == iso(NOW + timedelta(minutes=90))
    # ...an earlier one does not...
    early = budget_control.record_quota_failure(
        db, settings, runner="q", reset_at=iso(NOW + timedelta(minutes=5)), now=NOW
    )
    assert early.until == iso(NOW + timedelta(minutes=15))
    # ...and the cap bounds both.
    capped = budget_control.record_quota_failure(
        db, settings, runner="s", reset_at=iso(NOW + timedelta(hours=10)), now=NOW
    )
    assert capped.until == iso(NOW + timedelta(minutes=300))
    # A later reset reported during an active backoff extends it (still capped).
    extended = budget_control.record_quota_failure(
        db, settings, runner="p", reset_at=iso(NOW + timedelta(hours=4)), now=NOW
    )
    assert extended.until == iso(NOW + timedelta(hours=4)) and not extended.escalated


def test_backoff_state_survives_restart(tmp_path) -> None:
    paths, db = _setup(tmp_path)
    settings = _settings()
    budget_control.record_quota_failure(db, settings, runner="frontier", now=NOW)
    reopened = FactoryDB(paths.database_file)
    reopened.initialize()
    assert budget_control.effective_parallel(reopened, settings) == 2
    assert set(budget_control.runner_backoffs(reopened, now=NOW)) == {"frontier"}
    assert budget_control.probe_limits(reopened, now=NOW + timedelta(hours=1)) == {
        "frontier": 1
    }


def test_without_quota_failures_scheduling_is_unchanged(tmp_path, clock) -> None:
    paths, db = _setup(tmp_path)
    plain = FactorySettings(max_worker_processes=5, retry_backoff_seconds=0)
    assert plain.budget.max_parallel_agents is None
    assert budget_control.launch_limit(db, plain) == 5
    assert budget_control.runner_backoffs(db) == {}
    assert budget_control.probe_limits(db) == {}
    _enqueue(db, "low", "c1", priority=0)
    _enqueue(db, "high", "c2", runner="frontier", priority=3)
    claimed = db.claim_next_task(owner="x", lease_seconds=60, excluded_runners=(),
                                 runner_active_limits={})
    assert claimed is not None and claimed["task_id"] == "high"
    # A healthy result with no quota history writes nothing.
    _enqueue(db, "t", "c3")
    with db.connect() as connection:
        connection.execute("UPDATE tasks SET priority=99 WHERE task_id='t'")
    attempt_id, output = _start(db, paths, "t")
    _deliver(db, paths, "t", attempt_id, output, quota=False, status="completed")
    events_before = len(db.events())
    report = TickReport()
    ingest_results(db, paths, replace(plain, auto_continue=False), report)
    assert report.ingested and report.quota_deferred == []
    assert db.meta_items("provider_") == {}
    assert db.meta_get(budget_control.EFFECTIVE_PARALLEL_KEY) is None
    new_types = [e["event_type"] for e in db.events()[events_before:]]
    assert not {"quota_backoff", "parallel_reduced", "parallel_restored"} & set(new_types)


def test_paper_tasks_outrank_research_under_reduced_parallelism(tmp_path) -> None:
    _paths_, db = _setup(tmp_path)
    _enqueue(db, "research", "c1", priority=0)
    _enqueue(db, "paper-review", "c2", priority=1)  # _enqueue_paper_task adds +1
    claimed = db.claim_next_task(owner="x", lease_seconds=60, max_active=1)
    assert claimed is not None and claimed["task_id"] == "paper-review"


def _block(db: FactoryDB, paths: WorkspacePaths, task_id: str, *, status: str,
           failure_class: str | None) -> None:
    attempt_id, output = _start(db, paths, task_id)
    atomic_write_json(
        output,
        {"schema_version": RESULT_SCHEMA, "task_id": task_id, "status": status,
         "artifacts": [], "claims": []},
    )
    runtime = {"failure_class": failure_class} if failure_class else {}
    db.ingest_result(
        task_id,
        attempt_id=attempt_id,
        status=status,
        result_path=str(output),
        result_sha256=sha256_file(output),
        valid=True,
        gate_passed=False,
        blockers=[],
        run_seconds=1.0,
        runtime=runtime,
    )
    assert db.task(task_id)["status"] == status


def _replenish(db, paths, settings, campaign_id) -> TickReport:
    report = TickReport()
    engine._replenish_continuous_campaign(
        db, paths, settings, report, db.campaign(campaign_id)
    )
    return report


def test_infrastructure_needs_human_is_retried_then_blocked(tmp_path) -> None:
    paths, db = _setup(tmp_path)
    settings = _settings(infrastructure_retry_limit=2)
    _enqueue(db, "t", "c")
    for retry in (1, 2):
        _block(db, paths, "t", status="needs_human", failure_class="agent_transport")
        report = _replenish(db, paths, settings, "c")
        assert report.infrastructure_retried[0]["retry"] == retry
        assert report.production_blocked == []
        assert db.task("t")["status"] == "queued"
    _block(db, paths, "t", status="needs_human", failure_class="agent_transport")
    report = _replenish(db, paths, settings, "c")
    assert report.infrastructure_retried == []
    assert report.production_blocked == [{"campaign_id": "c", "reason": "needs_human"}]
    assert "infrastructure_retry_exhausted" in _event_types(db)


def test_scientific_or_unknown_needs_human_keeps_existing_behaviour(tmp_path) -> None:
    paths, db = _setup(tmp_path)
    settings = _settings()
    _enqueue(db, "t", "c")
    _block(db, paths, "t", status="needs_human", failure_class=None)
    report = _replenish(db, paths, settings, "c")
    assert report.production_blocked == [{"campaign_id": "c", "reason": "needs_human"}]
    assert db.task("t")["status"] == "needs_human"
    _enqueue(db, "u", "d")
    _block(db, paths, "u", status="quarantined", failure_class="result_contract")
    report = _replenish(db, paths, settings, "d")
    assert report.production_blocked == [{"campaign_id": "d", "reason": "quarantined"}]


def test_exhausted_infrastructure_retries_freeze_program_topic(tmp_path) -> None:
    paths, db = _setup(tmp_path)
    program = ProgramSettings(enabled=True)
    settings = replace(_settings(infrastructure_retry_limit=1), program=program)
    ledger = open_topic_ledger(paths, program)
    propose_topic(
        ledger,
        {"topic_id": "topic-1", "domain": "math", "question": "Q?", "data_sources": ["s"],
         "primary_endpoint": "e", "target_tier": 3},
        db=db,
        decided_by="scout",
    )
    admit_topic(ledger, "topic-1", db=db, settings=program, decided_by="gate",
                admission_task_id="gate", preregistration_sha256="b" * 64)
    db.register_campaign("c", domain="math", title="c")
    activate_topic(ledger, "topic-1", db=db, campaign_id="c", decided_by="materialize")
    _enqueue(db, "t", "c")
    _block(db, paths, "t", status="quarantined", failure_class="agent_quota")
    assert _replenish(db, paths, settings, "c").infrastructure_retried
    _block(db, paths, "t", status="quarantined", failure_class="agent_quota")
    report = _replenish(db, paths, settings, "c")

    assert report.production_blocked == [
        {"campaign_id": "c", "reason": "topic_frozen:infrastructure:agent_quota"}
    ]
    assert db.campaign("c")["status"] == "frozen"
    topic = ledger.topic("topic-1")
    assert topic["status"] == "frozen" and topic["freeze_reason_class"] == "infrastructure"


def test_budget_settings_load_from_toml(tmp_path) -> None:
    paths = _paths(tmp_path)
    config = paths.code / "config" / "openlabs.toml"
    config.parent.mkdir(parents=True)
    config.write_text("[factory]\nmax_worker_processes = 6\n", encoding="utf-8")
    defaults = load_settings(paths)
    assert defaults.budget == BudgetSettings()
    assert budget_control.parallel_ceiling(defaults) == 6
    config.write_text(
        "[factory]\nmax_worker_processes = 6\n[budget]\nmax_parallel_agents = 3\n"
        "quota_backoff_minutes = [1, 2]\nquota_backoff_cap_minutes = 90\nrestore_step = 2\n"
        "quota_retry_limit = 4\ninfrastructure_retry_limit = 0\n",
        encoding="utf-8",
    )
    loaded = load_settings(paths).budget
    assert loaded == BudgetSettings(
        max_parallel_agents=3,
        quota_backoff_minutes=(1, 2),
        quota_backoff_cap_minutes=90,
        restore_step=2,
        quota_retry_limit=4,
        infrastructure_retry_limit=0,
    )
    repo = WorkspacePaths(
        workspace=tmp_path, code=Path(__file__).resolve().parents[2], data=tmp_path / "d",
        artifacts=tmp_path / "a", database=tmp_path / "db", database_file=tmp_path / "db" / "f",
    )
    shipped = load_settings(repo).budget
    assert shipped.max_parallel_agents == 3
    assert shipped.quota_backoff_minutes == (15, 30, 60, 120, 300)
