"""Yielding to remote compute jobs: parked continuations, release, expiry, replan backoff."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from openlabs import remote_wait
from openlabs.config import FactorySettings, WorkspacePaths
from openlabs.contracts import (
    RECEIPT_SCHEMA,
    RESULT_SCHEMA,
    atomic_write_json,
    sha256_file,
    validate_result_bundle,
)
from openlabs.db import FactoryDB
from openlabs.engine import (
    REPLAN_STREAK_LIMIT,
    TickReport,
    _replenish_continuous_campaign,
    ingest_results,
)

JOB_A = "a" * 32
JOB_B = "b" * 32


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


@pytest.fixture()
def queue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "remote-queue"
    (root / "jobs").mkdir(parents=True)
    monkeypatch.setenv("OPENLABS_REMOTE_QUEUE", str(root))
    return root


def _job(queue: Path, job_id: str, state: str, *, wall: int = 3600, **extra) -> None:
    directory = queue / "jobs" / job_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "request.json").write_text(
        json.dumps({"job_id": job_id, "resources": {"cpu_threads": 4, "wall_seconds": wall}}),
        encoding="utf-8",
    )
    (directory / "status.json").write_text(
        json.dumps({"job_id": job_id, "state": state, "updated_at": "2026-11-13T15:00:00Z",
                    **extra}),
        encoding="utf-8",
    )


def _db(paths: WorkspacePaths, campaign_id: str = "campaign-1") -> FactoryDB:
    db = FactoryDB(paths.database_file)
    db.initialize()
    db.register_campaign(campaign_id, domain="physics", title="Campaign")
    return db


def _run(
    db: FactoryDB,
    paths: WorkspacePaths,
    task_id: str,
    payload: dict,
    *,
    task_type: str = "research",
    session_id: str | None = "session-1",
    duration: float = 120.0,
    enqueue: bool = True,
    settings: FactorySettings | None = None,
) -> TickReport:
    if enqueue:
        db.enqueue_task(
            task_id=task_id,
            campaign_id="campaign-1",
            domain="physics",
            task_type=task_type,
            objective="Solve the contact binary light curve.",
            skill_path="physics-research-loop",
            runner="balanced",
        )
    result = atomic_write_json(
        paths.data / "workspaces" / "physics" / "campaign-1" / task_id.replace(":", "_")
        / "result.json",
        {
            "schema_version": RESULT_SCHEMA,
            "task_id": task_id,
            "campaign_id": "campaign-1",
            "lab_id": "physics",
            "domain": "physics",
            "artifacts": [],
            "claims": [],
            "paper_candidate": False,
            **payload,
        },
    )
    task = db.claim_next_task(owner="test", lease_seconds=60)
    assert task is not None and task["task_id"] == task_id
    attempt_id = str(task["current_attempt_id"])
    db.bind_attempt_spec(task_id, attempt_id=attempt_id, lab_id="physics",
                         output_path=str(result))
    db.mark_running(task_id, attempt_id=attempt_id, owner="test", pid=1, lease_seconds=60)
    task = db.task(task_id) or {}
    atomic_write_json(
        paths.result_inbox / f"{task_id.replace(':', '_')}.json",
        {
            "schema_version": RECEIPT_SCHEMA,
            "task_id": task_id,
            "attempt_id": task["current_attempt_id"],
            "campaign_id": "campaign-1",
            "lab_id": "physics",
            "domain": "physics",
            "agent_role": task["agent_role"],
            "result_path": str(result),
            "sha256": sha256_file(result),
            "runtime": {"duration_seconds": duration, "exit_code": 0, "session_id": session_id},
        },
    )
    report = TickReport()
    ingest_results(db, paths, settings or FactorySettings(max_auto_tasks_per_campaign=50),
                   report)
    return report


def _yield_payload(*job_ids: str, **extra) -> dict:
    return {
        "status": "awaiting_remote",
        "summary": "Submitted the PHOEBE solve to ailab; nothing to do until it finishes.",
        "awaiting_remote": {
            "job_ids": list(job_ids),
            "resume_objective": "Read the solve receipts and write the first solution.",
            **extra,
        },
        "next_actions": [],
    }


def test_contract_requires_job_ids_for_awaiting_remote() -> None:
    base = {
        "schema_version": RESULT_SCHEMA,
        "task_id": "t",
        "campaign_id": "c",
        "lab_id": "physics",
        "summary": "s",
        "artifacts": [],
        "claims": [],
        "status": "awaiting_remote",
    }
    assert not validate_result_bundle(base).valid
    assert not validate_result_bundle({**base, "awaiting_remote": {"job_ids": ["xyz"]}}).valid
    assert validate_result_bundle({**base, "awaiting_remote": {"job_ids": [JOB_A]}}).valid


def test_yield_parks_continuation_without_agent_time_or_replan(tmp_path, queue) -> None:
    paths = _paths(tmp_path)
    db = _db(paths)
    _job(queue, JOB_A, "queued")
    report = _run(db, paths, "research-1", _yield_payload(JOB_A), duration=300.0)

    assert db.task("research-1")["status"] == "yielded"
    assert len(report.enqueued) == 1
    parked = db.task(report.enqueued[0])
    assert parked["status"] == "awaiting_remote"
    assert parked["routing_reason"] == "remote_wait"
    assert parked["session_mode"] == "resume"
    assert parked["agent_session_id"] == "session-1"
    assert parked["task_type"] == "research_continue"
    # Only the attempt's own runtime is charged; waiting adds nothing.
    assert db.campaign("campaign-1")["agent_seconds_used"] == pytest.approx(300.0)
    # Not claimable, and replenishment does not seed anything else meanwhile.
    assert db.claim_next_task(owner="test", lease_seconds=60) is None
    replenish = TickReport()
    _replenish_continuous_campaign(
        db, paths, FactorySettings(max_auto_tasks_per_campaign=50), replenish,
        db.campaign("campaign-1"),
    )
    assert replenish.enqueued == []
    assert {"campaign_id": "campaign-1", "reason": "awaiting_remote"} in (
        replenish.production_blocked
    )

    waiting = remote_wait.release_ready_waits(db)
    assert waiting["released"] == [] and waiting["waiting"][0]["pending"] == [JOB_A]
    assert db.task(parked["task_id"])["status"] == "awaiting_remote"


def test_release_after_every_job_is_terminal(tmp_path, queue) -> None:
    paths = _paths(tmp_path)
    db = _db(paths)
    _job(queue, JOB_A, "running")
    _job(queue, JOB_B, "queued")
    report = _run(db, paths, "research-1", _yield_payload(JOB_A, JOB_B))
    parked_id = report.enqueued[0]

    _job(queue, JOB_A, "failed", error="solver diverged")
    assert remote_wait.release_ready_waits(db)["released"] == []
    (queue / "jobs" / JOB_B / "WITHDRAWN").write_text("x", encoding="utf-8")
    summary = remote_wait.release_ready_waits(db)

    assert summary["released"] == [parked_id]
    task = db.task(parked_id)
    assert task["status"] == "queued"
    assert task["attempt"] == 0
    assert f"{JOB_A} (ailab): failed (error: solver diverged)" in task["objective"]
    assert f"{JOB_B} (ailab): withdrawn" in task["objective"]
    assert task["objective"].rstrip().endswith(
        "Read the solve receipts and write the first solution."
    )
    assert "[Parked" not in task["objective"]
    claimed = db.claim_next_task(owner="test", lease_seconds=60)
    assert claimed is not None and claimed["task_id"] == parked_id


def test_missing_job_counts_as_terminal(tmp_path, queue) -> None:
    paths = _paths(tmp_path)
    db = _db(paths)
    report = _run(db, paths, "research-1", _yield_payload(JOB_A))
    summary = remote_wait.release_ready_waits(db)
    assert summary["released"] == report.enqueued
    assert f"{JOB_A} (ailab): missing" in db.task(report.enqueued[0])["objective"]


def test_expired_wait_releases_once_then_stops_for_a_human(tmp_path, queue) -> None:
    paths = _paths(tmp_path)
    db = _db(paths)
    _job(queue, JOB_A, "queued", wall=3600)
    report = _run(db, paths, "research-1", _yield_payload(JOB_A, max_wait_seconds=600))
    parked_id = report.enqueued[0]

    later = datetime.now(UTC) + timedelta(seconds=700)
    summary = remote_wait.release_ready_waits(db, now=later)
    assert summary["expired"] == [parked_id]
    assert "reached its deadline" in db.task(parked_id)["objective"]

    again = _run(db, paths, parked_id, _yield_payload(JOB_A), enqueue=False)
    successor = db.task(again.enqueued[0])
    assert successor["status"] == "needs_human"
    assert "remote_wait_expired_twice" in successor["last_error"]


def test_needs_replan_that_names_a_pending_job_parks_instead_of_replanning(
    tmp_path, queue
) -> None:
    paths = _paths(tmp_path)
    db = _db(paths)
    _job(queue, JOB_A, "queued")
    report = _run(
        db,
        paths,
        "replan-1",
        {
            "status": "needs_replan",
            "summary": f"Waiting for remote job {JOB_A} before the first solution.",
            "next_actions": [f"Wait for remote job {JOB_A} to finish, then continue."],
        },
        task_type="replan",
    )
    assert len(report.enqueued) == 1
    parked = db.task(report.enqueued[0])
    assert parked["status"] == "awaiting_remote"
    assert parked["task_type"] == "research_continue"
    # The wait itself needs no lead model.
    assert parked["runner"] == "balanced"


def test_needs_replan_with_finished_job_replans_normally(tmp_path, queue) -> None:
    paths = _paths(tmp_path)
    db = _db(paths)
    _job(queue, JOB_A, "succeeded")
    report = _run(
        db,
        paths,
        "research-1",
        {
            "status": "needs_replan",
            "summary": f"Job {JOB_A} finished; the model needs a new route.",
            "next_actions": ["Try the third-light model."],
        },
    )
    assert db.task(report.enqueued[0])["task_type"] == "replan"


def test_repeated_replans_back_off(tmp_path, queue) -> None:
    paths = _paths(tmp_path)
    db = _db(paths)
    payload = {
        "status": "needs_replan",
        "summary": "No executable step yet.",
        "next_actions": ["Replan from the recorded obstruction."],
    }
    report = _run(db, paths, "research-1", payload)
    for round_number in range(1, REPLAN_STREAK_LIMIT):
        successor = db.task(report.enqueued[0])
        assert successor["not_before"] is None
        payload = {**payload, "summary": f"No executable step yet ({round_number})."}
        report = _run(db, paths, successor["task_id"], payload, enqueue=False)
    held = db.task(report.enqueued[0])
    assert held["task_type"] == "replan"
    assert held["not_before"] is not None
    assert held["not_before"] > datetime.now(UTC).isoformat().replace("+00:00", "Z")
    assert any(item.get("reason") == "replan_loop_backoff" for item in report.production_blocked)
    assert db.claim_next_task(owner="test", lease_seconds=60) is None
    assert db.events(entity_type="campaign", entity_id="campaign-1")[-1]["event_type"] == "replan_loop_backoff"


def test_freeze_cancels_a_parked_continuation(tmp_path, queue) -> None:
    paths = _paths(tmp_path)
    db = _db(paths)
    _job(queue, JOB_A, "queued")
    report = _run(db, paths, "research-1", _yield_payload(JOB_A))
    cancelled = db.freeze_campaign("campaign-1", reason="test")
    assert cancelled == tuple(report.enqueued)
    assert db.task(report.enqueued[0])["status"] == "cancelled"
    assert remote_wait.release_ready_waits(db) == {"released": [], "expired": [], "waiting": []}


def test_reviewer_cannot_yield(tmp_path, queue) -> None:
    paths = _paths(tmp_path)
    db = _db(paths)
    _job(queue, JOB_A, "queued")
    db.enqueue_task(
        task_id="review-1",
        campaign_id="campaign-1",
        domain="physics",
        task_type="paper_readiness",
        objective="Audit.",
        agent_role="reviewer",
    )
    _run(db, paths, "review-1", _yield_payload(JOB_A), enqueue=False)
    task = db.task("review-1")
    assert task["status"] == "needs_replan"
    assert "only available to researcher/experimenter" in task["last_error"]
    assert db.awaiting_remote_tasks() == []


# ------------------------------------------------------------- local overflow queue


def _local_job(root: Path, tmp_path: Path, cpus: int = 4) -> str:
    from openlabs import local_compute

    source = tmp_path / f"src-{cpus}-{len(list(tmp_path.iterdir()))}"
    source.mkdir()
    (source / "solve.py").write_text("print('ok')\n", encoding="utf-8")
    (source / "__pycache__").mkdir()
    return local_compute.submit(source, ["python3", "solve.py"], cpu_threads=cpus,
                                memory_mib=4096, wall_seconds=600, queue_root=root)


def test_local_jobs_respect_limits_and_reap_dead_runners(tmp_path) -> None:
    from openlabs import local_compute

    root = tmp_path / "local"
    first, second, third = (_local_job(root, tmp_path) for _ in range(3))
    assert not (root / "jobs" / first / "source" / "__pycache__").exists()
    assert local_compute.dispatch(root, launch=False)["queued"] == 3
    # Two jobs already running (a live runner pid) fill the default 2 x 4 CPUs.
    for job in (first, second):
        local_compute._write_status(root / "jobs" / job, state="running", runner_pid=os.getpid())
    summary = local_compute.dispatch(root, max_jobs=2, max_cpus=8)
    assert summary["started"] == [] and summary["running"] == 2
    # A runner that died with the container is reaped as failed, freeing its slot.
    local_compute._write_status(root / "jobs" / second, state="running", runner_pid=999_999_999)
    summary = local_compute.dispatch(root, max_jobs=2, max_cpus=8, launch=False)
    assert summary["reaped"] == [second]
    status = json.loads((root / "jobs" / second / "status.json").read_text(encoding="utf-8"))
    assert status["state"] == "failed"
    assert third


def test_parked_task_waits_on_a_local_job(tmp_path, queue, monkeypatch) -> None:
    from openlabs import local_compute

    local_root = tmp_path / "local"
    monkeypatch.setenv("OPENLABS_LOCAL_QUEUE", str(local_root))
    job = _local_job(local_root, tmp_path)
    paths = _paths(tmp_path)
    db = _db(paths)
    report = _run(db, paths, "research-1", _yield_payload(job))
    parked = report.enqueued[0]
    assert db.task(parked)["status"] == "awaiting_remote"
    assert remote_wait.release_ready_waits(db)["waiting"][0]["pending"] == [job]
    local_compute._write_status(local_root / "jobs" / job, state="succeeded", exit_code=0)
    assert remote_wait.release_ready_waits(db)["released"] == [parked]
    assert f"{job} (local): succeeded" in db.task(parked)["objective"]


def test_replenishment_parks_a_legacy_wait_only_replan(tmp_path, queue) -> None:
    """A needs_replan left before this mechanism existed is parked on restart."""

    paths = _paths(tmp_path)
    db = _db(paths)
    payload = {
        "status": "needs_replan",
        "summary": f"Waiting for remote job {JOB_A}.",
        "next_actions": [f"Wait for {JOB_A}, then continue."],
    }
    report = _run(db, paths, "replan-1", payload, task_type="replan",
                  settings=FactorySettings(auto_continue=False))
    assert report.enqueued == []
    _job(queue, JOB_A, "running")
    replenish = TickReport()
    _replenish_continuous_campaign(
        db, paths, FactorySettings(max_auto_tasks_per_campaign=50), replenish,
        db.campaign("campaign-1"),
    )
    assert len(replenish.enqueued) == 1
    assert db.task(replenish.enqueued[0])["status"] == "awaiting_remote"
