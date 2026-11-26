"""Idle-spin protections (2026-11-16): empty scout draws, remote re-yield loops,
the generic no-progress guard, the idle metrics and the production-stop switches."""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import test_paper_templates as templates
import test_remote_wait as rw
import test_research_lines as lines
import test_research_program_flow as flow
from openlabs import budget as budget_control
from openlabs import engine, program_flow, remote_wait, spin_guard
from openlabs.config import FactorySettings
from openlabs.contracts import atomic_write_json
from openlabs.engine import TickReport
from test_remote_wait import queue  # noqa: F401 - pytest fixture

# --------------------------------------------------------------------- empty scout draws


def _queued_line(tmp_path: Path):
    paths = flow._paths(tmp_path)
    flow._install_program(paths)
    lines._make_line_project(paths)
    path = templates._templates_file(paths)
    queue = tmp_path / "queue" / "queue.json"
    queue.parent.mkdir(parents=True, exist_ok=True)
    queue.write_text(json.dumps({"candidates": [{"entry_id": "TIC 1"}]}), encoding="utf-8")
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "        minimum_content: [phonon stability of the host]\n",
            "        minimum_content: [phonon stability of the host]\n"
            f"        candidate_queue: {queue}\n",
        ),
        encoding="utf-8",
    )
    return paths, queue


def _empty_scout(paths, db, settings, monkeypatch) -> engine.TickReport:
    """Tick (schedules and claims a scout), deliver no card, tick again."""

    first = flow._tick(paths, settings, monkeypatch)
    scouts = first.program["scouts_scheduled"]
    assert len(scouts) == 1, first.program
    flow._complete(db, paths, scouts[0]["task_id"], extra={
        "topic_cards": [], "summary": "No topic cards: every queue entry is in the ledger."},
        receipt_files={"data-access.json": flow.RECEIPT})
    return flow._tick(paths, settings, monkeypatch)


def _later(monkeypatch, hours: float) -> None:
    moment = datetime.now(UTC) + timedelta(hours=hours)
    monkeypatch.setattr(program_flow, "_now_moment", lambda: moment)


def test_empty_draw_backs_off_and_a_queue_change_releases_at_once(tmp_path, monkeypatch):
    paths, queue = _queued_line(tmp_path)
    db = flow._db(paths)
    settings = flow._settings(scout_min_interval_hours=0)

    report = _empty_scout(paths, db, settings, monkeypatch)
    assert report.program["scouts_scheduled"] == []
    assert report.program["scout_blocked"] == "scout_empty_backoff"
    block = report.program["scout_supply_blocked"][0]
    assert block["empty_draws"] == 1 and block["backoff_hours"] == 1.0
    assert block["empty_reason"] == "candidate_queue_exhausted"
    assert "every queue entry" in block["last_summary"]

    # One hour later the second draw runs, comes back empty: six hours now.
    _later(monkeypatch, 1.1)
    report = _empty_scout(paths, db, settings, monkeypatch)
    assert report.program["scout_blocked"] == "scout_empty_backoff"
    assert report.program["scout_supply_blocked"][0]["backoff_hours"] == 6.0
    assert flow._tick(paths, settings, monkeypatch).program["scouts_scheduled"] == []

    # The queue is refreshed: the backoff is released on the next tick.
    queue.write_text(json.dumps({"candidates": [{"entry_id": "TIC 2"}]}), encoding="utf-8")
    report = flow._tick(paths, settings, monkeypatch)
    assert len(report.program["scouts_scheduled"]) == 1
    released = [e for e in db.events(entity_type="program", entity_id=lines.LINE)
                if e["event_type"] == "topic_scout_backoff_released"]
    assert released and released[-1]["payload"]["reason"] == "candidate_supply_changed"


def test_repeated_empty_draws_mark_the_line_exhausted(tmp_path, monkeypatch):
    paths, queue = _queued_line(tmp_path)
    db = flow._db(paths)
    settings = flow._settings(scout_min_interval_hours=0, scout_exhausted_after=2)

    _empty_scout(paths, db, settings, monkeypatch)
    _later(monkeypatch, 1.1)
    report = _empty_scout(paths, db, settings, monkeypatch)
    assert report.program["scout_blocked"] == "candidates_exhausted"
    blocked = [item for item in report.production_blocked
               if item["reason"] == "candidates_exhausted"]
    assert blocked and blocked[0]["research_line"] == lines.LINE
    assert blocked[0]["empty_draws"] == 2

    # Time alone does not release an exhausted line ...
    _later(monkeypatch, 24 * 30)
    report = flow._tick(paths, settings, monkeypatch)
    assert report.program["scouts_scheduled"] == []
    assert report.program["scout_blocked"] == "candidates_exhausted"
    # ... a new line capability (its research-lines.yaml entry) does.
    lines_path = paths.data / "registry" / "research-lines.yaml"
    lines_path.write_text(lines_path.read_text(encoding="utf-8").replace(
        "    title: test line\n", "    title: test line (spot configuration validated)\n"),
        encoding="utf-8")
    report = flow._tick(paths, settings, monkeypatch)
    assert len(report.program["scouts_scheduled"]) == 1


def test_a_productive_scout_clears_the_streak(tmp_path, monkeypatch):
    paths, _queue = _queued_line(tmp_path)
    db = flow._db(paths)
    settings = flow._settings(scout_min_interval_hours=0, scout_exhausted_after=2)
    _empty_scout(paths, db, settings, monkeypatch)
    _later(monkeypatch, 1.1)
    first = flow._tick(paths, settings, monkeypatch)
    scout_id = first.program["scouts_scheduled"][0]["task_id"]
    flow._complete(db, paths, scout_id, extra={"topic_cards": [templates._templated_card(0)]},
                   receipt_files={"data-access.json": flow.RECEIPT})
    report = flow._tick(paths, settings, monkeypatch)
    assert report.program["cards_registered"]
    assert report.program["scout_supply_blocked"] == []
    state = json.loads(db.meta_get(program_flow.SCOUT_SUPPLY_PREFIX + lines.LINE))
    assert state["count"] == 0


# ------------------------------------------------------------- remote re-yield loops


def test_yield_on_a_missing_job_stops_for_a_human(tmp_path, queue):
    paths = rw._paths(tmp_path)
    db = rw._db(paths)
    report = rw._run(db, paths, "research-1", rw._yield_payload(rw.JOB_A))
    successor = db.task(report.enqueued[0])
    assert successor["status"] == "needs_human"
    assert successor["last_error"].startswith("remote_job_missing")
    assert remote_wait.release_ready_waits(db)["released"] == []


def test_yield_again_on_released_terminal_jobs_stops_the_loop(tmp_path, queue):
    paths = rw._paths(tmp_path)
    db = rw._db(paths)
    rw._job(queue, rw.JOB_A, "queued")
    parked_id = rw._run(db, paths, "research-1", rw._yield_payload(rw.JOB_A)).enqueued[0]
    rw._job(queue, rw.JOB_A, "succeeded")
    assert remote_wait.release_ready_waits(db)["released"] == [parked_id]
    record = remote_wait.wait_record(db, parked_id)
    assert record["released_at"] and record["expired"] is False  # committed with the release

    # The resumed agent yields on the same finished job: no second park/release cycle.
    again = rw._run(db, paths, parked_id, rw._yield_payload(rw.JOB_A), enqueue=False)
    successor = db.task(again.enqueued[0])
    assert successor["status"] == "needs_human"
    assert "remote_jobs_already_released" in successor["last_error"]
    assert remote_wait.release_ready_waits(db) == {"released": [], "expired": [], "waiting": []}


def test_first_yield_on_quickly_finished_jobs_still_parks_once(tmp_path, queue):
    paths = rw._paths(tmp_path)
    db = rw._db(paths)
    rw._job(queue, rw.JOB_A, "succeeded")
    parked_id = rw._run(db, paths, "research-1", rw._yield_payload(rw.JOB_A)).enqueued[0]
    assert db.task(parked_id)["status"] == "awaiting_remote"
    assert remote_wait.release_ready_waits(db)["released"] == [parked_id]


def test_a_job_that_vanishes_after_the_start_keeps_waiting(tmp_path, queue):
    paths = rw._paths(tmp_path)
    db = rw._db(paths)
    rw._job(queue, rw.JOB_A, "running")
    parked_id = rw._run(db, paths, "research-1", rw._yield_payload(rw.JOB_A)).enqueued[0]
    (queue / "jobs" / rw.JOB_A / "status.json").rename(queue / "status.json.moved")
    (queue / "jobs" / rw.JOB_A / "request.json").rename(queue / "request.json.moved")
    (queue / "jobs" / rw.JOB_A).rename(queue / "gone")
    summary = remote_wait.release_ready_waits(db)
    assert summary["released"] == [] and summary["waiting"][0]["task_id"] == parked_id


def test_legacy_wait_on_a_never_existing_job_stops_for_a_human(tmp_path, queue):
    paths = rw._paths(tmp_path)
    db = rw._db(paths)
    db.enqueue_task(task_id="await:x", campaign_id="campaign-1", domain="physics",
                    task_type="research_continue", objective="[Parked by the orchestrator "
                    "until remote jobs x finish; ...]\n\nContinue.", initial_status="awaiting_remote")
    db.update_meta({remote_wait.WAIT_META_PREFIX + "await:x": json.dumps({
        "job_ids": [rw.JOB_B], "queue_root": str(queue), "since": "2026-11-15T00:00:00Z",
        "deadline": "2026-11-20T00:00:00Z", "states_at_start": {rw.JOB_B: "missing"}})})
    summary = remote_wait.release_ready_waits(db)
    assert summary["needs_human"] == ["await:x"]
    assert db.task("await:x")["status"] == "needs_human"


def test_one_broken_wait_does_not_block_the_others(tmp_path, queue, monkeypatch):
    paths = rw._paths(tmp_path)
    db = rw._db(paths)
    rw._job(queue, rw.JOB_A, "queued")
    rw._job(queue, rw.JOB_B, "queued")
    first = rw._run(db, paths, "research-1", rw._yield_payload(rw.JOB_A)).enqueued[0]
    db.register_campaign("campaign-2", domain="physics", title="Second")
    db.enqueue_task(task_id="await:y", campaign_id="campaign-2", domain="physics",
                    task_type="research_continue", objective="Continue.",
                    initial_status="awaiting_remote")
    db.update_meta({remote_wait.WAIT_META_PREFIX + "await:y": json.dumps({
        "job_ids": [rw.JOB_B], "queue_root": str(queue), "since": "2026-11-15T00:00:00Z",
        "deadline": "2026-11-20T00:00:00Z", "states_at_start": {rw.JOB_B: "queued"}})})
    rw._job(queue, rw.JOB_A, "succeeded")
    rw._job(queue, rw.JOB_B, "succeeded")
    real = remote_wait.job_state

    def flaky(root, job_id, **kwargs):
        if job_id == rw.JOB_A:
            raise OSError("stale NFS handle")
        return real(root, job_id, **kwargs)

    monkeypatch.setattr(remote_wait, "job_state", flaky)
    summary = remote_wait.release_ready_waits(db)
    assert summary["released"] == ["await:y"]
    assert summary["errors"][0]["task_id"] == first


# ------------------------------------------------------------ generic no-progress guard


def _finished(db, campaign_id: str, n: int, status: str, task_type: str = "replan",
              start: int = 0) -> None:
    for index in range(start, start + n):
        _task(db, f"{campaign_id}-done-{index}", campaign_id, status, task_type=task_type)


def _task(db, task_id: str, campaign_id: str, status: str, *, task_type: str = "replan",
          result_path: str | None = None, updated_at: str | None = None) -> None:
    db.enqueue_task(task_id=task_id, campaign_id=campaign_id, domain="physics",
                    task_type=task_type, objective="step")
    with db.connect() as connection:  # test fixture: a finished task of the chain
        connection.execute(
            "UPDATE tasks SET status=?, result_path=?, updated_at=COALESCE(?, updated_at) "
            "WHERE task_id=?", (status, result_path, updated_at, task_id))


def test_no_progress_chain_backs_off_then_stops_for_a_human(tmp_path):
    paths = rw._paths(tmp_path)
    db = rw._db(paths)
    settings = FactorySettings()
    _finished(db, "campaign-1", 3, "needs_replan")
    db.enqueue_task(task_id="next", campaign_id="campaign-1", domain="physics",
                    task_type="candidate_maturation", objective="again")
    report = TickReport()
    assert spin_guard.guard_queued_tasks(db, settings, report) == []
    assert db.task("next")["not_before"] is None

    _finished(db, "campaign-1", 1, "needs_replan", start=3)
    actions = spin_guard.guard_queued_tasks(db, settings, report)
    assert actions[0]["reason"] == "no_progress_backoff"
    assert db.task("next")["not_before"] > datetime.now(UTC).isoformat()
    assert db.claim_next_task(owner="t", lease_seconds=60) is None
    # Idempotent within the same backoff.
    assert spin_guard.guard_queued_tasks(db, settings, TickReport()) == []

    _finished(db, "campaign-1", 4, "needs_replan", start=4)
    db.enqueue_task(task_id="next2", campaign_id="campaign-1", domain="physics",
                    task_type="replan", objective="again")
    actions = spin_guard.guard_queued_tasks(db, settings, report)
    assert {item["reason"] for item in actions} == {spin_guard.CIRCUIT_ERROR}
    assert db.task("next2")["status"] == "needs_human"
    assert db.task("next")["status"] == "needs_human"
    assert db.task("next")["last_error"].startswith(spin_guard.CIRCUIT_ERROR)
    # Replenishment then stops for the human (latest task needs_human).
    replenish = TickReport()
    engine._replenish_continuous_campaign(db, paths, settings, replenish,
                                          db.campaign("campaign-1"))
    assert replenish.enqueued == []


def test_progress_and_owner_seats_are_not_spin(tmp_path):
    paths = rw._paths(tmp_path)
    db = rw._db(paths)
    _finished(db, "campaign-1", 6, "needs_replan")
    # A succeeded step with a new artifact is progress and ends the streak.
    result = atomic_write_json(tmp_path / "r.json", {"artifacts": [
        {"artifact_id": "fit", "kind": "dataset", "sha256": "1" * 64}]})
    _task(db, "good", "campaign-1", "succeeded", task_type="research_continue",
          result_path=str(result), updated_at="2999-01-01T00:00:00Z")
    assert spin_guard.no_progress_streak(db, "campaign-1")[0] == 0
    # Owner seats are judged by the owner breaker, not here.
    db.register_campaign("campaign-2", domain="physics", title="Owner")
    _finished(db, "campaign-2", 9, "needs_replan", task_type="topic_owner")
    assert spin_guard.no_progress_streak(db, "campaign-2")[0] == 0


def _stamp(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def _attempt(db, task_id: str, stamp: str, seconds: float = 120.0) -> None:
    with db.connect() as connection:  # test fixture: one finished attempt of the task
        connection.execute(
            "INSERT INTO task_attempts (attempt_id, task_id, attempt_number, status, "
            "lease_owner, started_at, finished_at, run_seconds, created_at) "
            "VALUES (?, ?, 1, 'succeeded', 't', ?, ?, ?, ?)",
            (f"attempt-{task_id}", task_id, stamp, stamp, seconds, stamp))


def test_phase_a_prescreen_rejections_are_progress(tmp_path):
    """2026-11-26 supply stall: prescreens that stopped at the calibration phase (a
    verdict, no artifact) were counted as no progress, backed off and would have been
    stopped for a human before the cards were ever judged."""

    paths = rw._paths(tmp_path)
    db = rw._db(paths)
    db.register_campaign("scout-c", domain="physics", title="Scouts")
    settings = FactorySettings()
    now = datetime.now(UTC)
    verdict = atomic_write_json(tmp_path / "phase-a.json", {"artifacts": [], "topic_prescreen": {
        "calibration_match": "zone_1", "expected_band": "zone_1", "summary": "below floor"}})
    for index in range(9):
        stamp = _stamp(now - timedelta(minutes=60 - index))
        _task(db, f"pre-{index}", "scout-c", "succeeded", task_type="topic_prescreen",
              result_path=str(verdict), updated_at=stamp)
        _attempt(db, f"pre-{index}", stamp)
        _task(db, f"scout-{index}", "scout-c", "succeeded", task_type="topic_scout",
              updated_at=stamp)
    db.enqueue_task(task_id="pre-next", campaign_id="scout-c", domain="physics",
                    task_type="topic_prescreen", objective="judge the next card")
    assert spin_guard.no_progress_streak(db, "scout-c")[0] == 0
    assert spin_guard.guard_queued_tasks(db, settings, TickReport()) == []
    assert db.task("pre-next")["status"] == "queued"
    assert db.task("pre-next")["not_before"] is None
    # The idle metrics use the same reading: a verdict is output.
    metrics = spin_guard.idle_metrics(db, now=now)
    assert metrics["by_task_type"]["topic_prescreen"] == {
        "attempts": 9, "zero_output": 0, "agent_hours": round(9 * 120 / 3600, 2),
        "zero_output_agent_hours": 0.0}

    # A prescreen that keeps breaking (needs_replan) is still no progress.
    for index in range(4):
        _task(db, f"broken-{index}", "scout-c", "needs_replan", task_type="topic_prescreen",
              updated_at=_stamp(now - timedelta(minutes=5 - index)))
    assert spin_guard.no_progress_streak(db, "scout-c")[0] == 4
    actions = spin_guard.guard_queued_tasks(db, settings, TickReport())
    assert [item["reason"] for item in actions] == ["no_progress_backoff"]


def test_a_finishing_scout_does_not_push_the_backoff(tmp_path):
    """The backoff counts from the last non-neutral finish: scouts finishing later in
    the same campaign used to move not_before forward each time."""

    paths = rw._paths(tmp_path)
    db = rw._db(paths)
    db.register_campaign("scout-c", domain="physics", title="Scouts")
    settings = FactorySettings()
    now = datetime.now(UTC)
    failed_at = now - timedelta(minutes=20)
    for index in range(4):
        _task(db, f"pre-{index}", "scout-c", "needs_replan", task_type="topic_prescreen",
              updated_at=_stamp(failed_at - timedelta(minutes=3 - index)))
    _task(db, "scout-late", "scout-c", "succeeded", task_type="topic_scout",
          updated_at=_stamp(now - timedelta(minutes=1)))
    db.enqueue_task(task_id="pre-next", campaign_id="scout-c", domain="physics",
                    task_type="topic_prescreen", objective="judge the next card")
    streak, latest = spin_guard.no_progress_streak(db, "scout-c")
    assert streak == 4 and latest["task_id"] == "pre-3"
    actions = spin_guard.guard_queued_tasks(db, settings, TickReport(), now=now)
    assert actions[0]["last_task_id"] == "pre-3"
    expected = _stamp(failed_at + timedelta(minutes=settings.no_progress_backoff_minutes[0]))
    assert db.task("pre-next")["not_before"] == expected
    # Another scout finishing does not move it.
    _task(db, "scout-later", "scout-c", "succeeded", task_type="topic_scout",
          updated_at=_stamp(now))
    assert spin_guard.guard_queued_tasks(db, settings, TickReport(), now=now) == []
    assert db.task("pre-next")["not_before"] == expected


def test_same_artifacts_again_are_not_progress(tmp_path):
    paths = rw._paths(tmp_path)
    db = rw._db(paths)
    result = atomic_write_json(tmp_path / "same.json", {"artifacts": [
        {"artifact_id": "fit", "kind": "dataset", "sha256": "2" * 64},
        {"artifact_id": "packet", "kind": "source_document", "sha256": "3" * 64}]})
    for index in range(5):
        _task(db, f"c{index}", "campaign-1", "succeeded", task_type="research_continue",
              result_path=str(result), updated_at=f"2026-11-16T00:0{index}:00Z")
    # The first one added the artifact; the four identical repeats did not.
    assert spin_guard.no_progress_streak(db, "campaign-1")[0] == 4


# ------------------------------------------------------------------- idle metrics


def test_tick_report_carries_idle_metrics(tmp_path, monkeypatch):
    paths, _queue = _queued_line(tmp_path)
    db = flow._db(paths)
    settings = flow._settings(scout_min_interval_hours=0)
    report = _empty_scout(paths, db, settings, monkeypatch)
    metrics = report.to_dict()["idle_metrics"]
    scout = metrics["by_task_type"]["topic_scout"]
    assert scout["attempts"] == 1 and scout["zero_output"] == 1
    assert metrics["total"]["zero_output"] >= 1


# ------------------------------------------------------------- production stop


def test_production_stop_skips_probes_and_can_keep_local_compute(tmp_path, monkeypatch):
    paths = flow._paths(tmp_path)
    flow._install_program(paths)
    flow._db(paths)
    calls: list[str] = []
    monkeypatch.setattr(budget_control, "probe_stale_providers",
                        lambda *a, **k: calls.append("probe") or {})
    monkeypatch.setattr(engine.local_compute, "dispatch",
                        lambda *a, **k: calls.append("local") or {"started": [], "reaped": []})
    stopped = dataclasses.replace(flow._settings(), launch_jobs=False)
    report = flow._tick(paths, stopped, monkeypatch)
    assert calls == [] and report.launched == []
    keep_local = dataclasses.replace(stopped, launch_local_compute=True)
    flow._tick(paths, keep_local, monkeypatch)
    assert calls == ["local"]
    flow._tick(paths, flow._settings(), monkeypatch)
    assert calls == ["local", "local", "probe"]


def test_owner_seats_without_progress_count_as_zero_output(tmp_path):
    """2026-11-16: 75 quota-stop owner seats showed zero_output 0 in the tick report."""

    paths = rw._paths(tmp_path)
    db = rw._db(paths)
    db.register_campaign("campaign-o", domain="physics", title="Owner")
    now = datetime.now(UTC)
    stamp = (now - timedelta(minutes=5)).isoformat(timespec="seconds").replace("+00:00", "Z")
    for index, progress in enumerate([[], [], ["new_artifacts"]]):
        task_id = f"owner:{index}"
        _task(db, task_id, "campaign-o", "succeeded", task_type="topic_owner")
        with db.connect() as connection:  # test fixture: one finished attempt and its record
            connection.execute(
                "INSERT INTO task_attempts (attempt_id, task_id, attempt_number, status, "
                "lease_owner, started_at, finished_at, run_seconds, created_at) "
                "VALUES (?, ?, 1, 'succeeded', 't', ?, ?, 36.0, ?)",
                (f"a{index}", task_id, stamp, stamp, stamp))
            connection.execute(
                "INSERT INTO events (created_at, entity_type, entity_id, event_type, "
                "payload_json) VALUES (?, 'campaign', 'campaign-o', 'owner_seat_recorded', ?)",
                (stamp, json.dumps({"task_id": task_id, "progress": progress})))
    metrics = spin_guard.idle_metrics(db, now=now)
    seats = metrics["by_task_type"]["topic_owner"]
    assert seats["attempts"] == 3 and seats["zero_output"] == 2
    assert seats["zero_output_agent_hours"] == round(72 / 3600, 2)
    # Still neutral for the generic chain guard (the owner breaker owns that).
    assert spin_guard.no_progress_streak(db, "campaign-o")[0] == 0


def test_a_scout_whose_result_was_not_accepted_is_no_empty_draw(tmp_path, monkeypatch):
    """A scout result the control plane refused (needs_replan: an artifact outside the
    staging area, a hash mismatch) says nothing about the line's supply: no backoff."""

    paths, _queue = _queued_line(tmp_path)
    db = flow._db(paths)
    settings = flow._settings(scout_min_interval_hours=0)
    first = flow._tick(paths, settings, monkeypatch)
    task_id = first.program["scouts_scheduled"][0]["task_id"]
    bogus = tmp_path / "outside.json"
    bogus.write_text("{}", encoding="utf-8")
    flow._complete(db, paths, task_id, extra={
        "topic_cards": [{"question": "a card the gate never saw"}],
        "artifacts": [{"artifact_id": "queue", "kind": "data", "uri": bogus.resolve().as_uri(),
                       "sha256": "0" * 64}]},
        receipt_files={"data-access.json": flow.RECEIPT})
    # A failed workspace commit can leave a readable, hash-bound one-card bundle.
    monkeypatch.setattr(program_flow, "_scout_result_cards", lambda task: (1, "one card"))
    draws = []
    monkeypatch.setattr(program_flow, "_record_template_draws", lambda *args: draws.append(args))
    report = flow._tick(paths, settings, monkeypatch)
    assert db.task(task_id)["status"] != "succeeded"
    assert not [item for item in report.program.get("scout_outcomes") or []
                if item.get("event") == "topic_scout_empty"], report.program
    assert report.program["scout_blocked"] != "scout_empty_backoff"
    assert not report.program.get("scout_supply_blocked")
    assert not draws
