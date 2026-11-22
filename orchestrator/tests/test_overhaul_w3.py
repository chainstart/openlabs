"""W3 (2026-11-20): writer plan, same-state stalls, ledger reconciliation, usage view."""

from __future__ import annotations

import importlib.util
import itertools
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from openlabs import owner, program_reconcile, spin_guard, usage
from openlabs.config import OWNER_TASK_TYPE, OwnerSettings
from openlabs.contracts import atomic_write_json
from openlabs.program import (
    IllegalTopicTransition,
    LEGACY_ARCHIVE_REASON,
    open_topic_ledger,
    transition_topic,
)
from test_owner_mode import _first_seat, _latest, _owner_program, _release, _seat_packet
from test_program_autonomy import _analysis_decision, _decide, _direction_tasks, _lease, _topic
from test_research_program_flow import RUNNERS, _tick

WRITER = "worker_claude"
OWNER = "worker_gpt"


def _with(settings, *, writer: str | None = WRITER, owners=(OWNER,), **factory):
    program = replace(settings.program, owner=replace(
        settings.program.owner, writing_runner=writer, runners=tuple(owners)))
    return replace(settings, program=program, **factory)


# --------------------------------------------------------------------------- writer plan


HANDOVER_TEXT = "do not draft the paper"


@pytest.mark.parametrize("writer", [WRITER, OWNER, None, "no_such_runner"])
def test_brief_and_hand_over_never_disagree(tmp_path, monkeypatch, writer) -> None:
    """The defect of topic-943f53cf: told to hand over, but no writer seat ever came.

    For every owner state and both writer configurations (writer = owner runner, writer =
    another runner), a brief that tells the owner to hand over implies that a seat
    declaring ``phase: writing`` does switch; and when no switch is due the brief either
    says nothing (the owner writes, as before 2026-11-19) or says the owner writes.
    """

    paths, db, settings, _topics = _owner_program(
        tmp_path, monkeypatch, owner_settings=OwnerSettings(runners=(OWNER,)))
    settings = _with(settings, writer=writer)
    states = [
        {}, {"phase": "solving"}, {"phase": "writing"}, {"review_round": 1},
        {"review_stage": owner.STAGE_MAJOR}, {"review_history": [{"round": 1}]},
        {"phase": "writing", "review_history": [{"round": 1}], "review_stage": "unified_review"},
        {"writing": {"status": owner.WRITING_FALLBACK, "runner": WRITER}},
        {"writing": {"status": owner.WRITING_OWNER, "reason": "review_history"}},
        {"writing": {"status": owner.WRITING_ACTIVE, "runner": WRITER, "solver_runner": OWNER}},
        {"writing": {"status": owner.WRITING_ACTIVE, "runner": "gone_runner"}},
    ]
    packet = {"status": "continuing", "phase": "writing"}
    for state, runner in itertools.product(states, (OWNER, WRITER)):
        task = {"runner": runner}
        lines = owner.writing_brief_lines(settings, task=task, writing=state.get("writing"),
                                          state=state)
        switch = owner.writing_switch_due(settings, state, packet, task, successful=True)
        text = " ".join(lines)
        if HANDOVER_TEXT in text:
            assert switch == "phase_writing", (state, runner, writer)
        else:
            assert switch is None, (state, runner, writer, text)
    # The incident's state: reviewed manuscript, writer elsewhere -> the owner is told so.
    incident = {"phase": "writing", "review_history": [{"round": 1}],
                "review_stage": "unified_review"}
    lines = owner.writing_brief_lines(settings, task={"runner": OWNER}, writing={},
                                      state=incident)
    if writer == WRITER:
        assert lines and "write this topic's manuscript" in lines[0], lines
        assert HANDOVER_TEXT not in " ".join(lines)


def test_reviewed_topic_is_written_by_its_owner_not_left_waiting(tmp_path, monkeypatch) -> None:
    paths, db, settings, (topic,) = _owner_program(
        tmp_path, monkeypatch, owner_settings=OwnerSettings(runners=(OWNER,)))
    settings = _with(settings)
    campaign_id = topic["campaign_id"]
    # A topic whose manuscript already went through a recompute round (943f53cf).
    owner.update_state(db, campaign_id, review_round=1, review_stage=owner.STAGE_MAJOR,
                       review_history=[{"round": 1, "verdict": "major"}])
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _seat_packet(db, paths, seat["task_id"],
                 {"status": "continuing", "phase": "writing",
                  "next_step": "Hand the revision to worker_claude for v0.2.2."}, artifact=True)
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    nxt = _latest(db, campaign_id)
    # Not a writer seat, and not a silent owner seat: the owner is told it writes.
    assert nxt["task_type"] == OWNER_TASK_TYPE and nxt["runner"] == OWNER
    assert nxt["routing_reason"] == owner.ROUTING_CONTINUE
    assert nxt["objective"].startswith("You write this topic's manuscript")
    writing = owner.writing_state(db, campaign_id)
    assert writing["status"] == owner.WRITING_OWNER and writing["reason"] == "review_history"
    history = _topic(paths, settings, topic["topic_id"]).get("history") or []
    assert any(entry.get("kind") == "writing_owner" for entry in history)
    # Sticky: later seats never wait for a hand-over either.
    state = owner.owner_state(db, campaign_id)
    assert owner.writing_switch_due(settings, state, {"status": "continuing", "phase": "writing"},
                                    {"runner": OWNER}, successful=True) is None


def test_same_runner_writer_keeps_the_owner_writing(tmp_path, monkeypatch) -> None:
    # Instance configuration of 2026-11-20: writing_runner = worker_gpt = the only owner.
    paths, db, settings, (topic,) = _owner_program(
        tmp_path, monkeypatch, owner_settings=OwnerSettings(runners=(OWNER,)))
    settings = _with(settings, writer=OWNER)
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    assert owner.writing_brief_lines(settings, task=seat, writing={}, state={}) == []
    _seat_packet(db, paths, seat["task_id"], {"status": "continuing", "phase": "writing"},
                 artifact=True)
    _tick(paths, settings, monkeypatch)
    nxt = _latest(db, topic["campaign_id"])
    assert nxt["runner"] == OWNER and nxt["routing_reason"] == owner.ROUTING_CONTINUE
    assert owner.writing_state(db, topic["campaign_id"]) == {}


def test_different_runner_writer_still_takes_over_a_fresh_topic(tmp_path, monkeypatch) -> None:
    paths, db, settings, (topic,) = _owner_program(
        tmp_path, monkeypatch, owner_settings=OwnerSettings(runners=(OWNER,)))
    settings = _with(settings)
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _seat_packet(db, paths, seat["task_id"], {"status": "continuing", "phase": "writing"},
                 artifact=True)
    _tick(paths, settings, monkeypatch)
    nxt = _latest(db, topic["campaign_id"])
    assert nxt["runner"] == WRITER and nxt["routing_reason"] == owner.ROUTING_WRITING


def test_unpromoted_writing_phase_does_not_block_the_hand_over(tmp_path) -> None:
    from types import SimpleNamespace

    settings = SimpleNamespace(
        program=SimpleNamespace(owner=OwnerSettings(runners=(OWNER,), writing_runner=WRITER)),
        runners=RUNNERS, stall_signature_repeats=0)
    db = SimpleNamespace()
    states: dict[str, str] = {}
    db.meta_get = lambda key: states.get(key)
    db.update_meta = lambda values, events=(): states.update(values)
    db.campaign = lambda _cid: {}
    import openlabs.owner as module

    module_state = module.record_seat.__globals__
    original = module_state["_seat_run_seconds"]
    module_state["_seat_run_seconds"] = lambda _db, _task: 900.0
    try:
        state = module.record_seat(
            db, task={"task_id": "owner:x", "campaign_id": "c", "runner": OWNER},
            payload={"owner_packet": {"status": "continuing", "phase": "writing"}},
            final_status="needs_replan", workspace_root=tmp_path, promoted=False)
    finally:
        module_state["_seat_run_seconds"] = original
    assert state.get("phase") is None
    assert owner.writing_switch_due(settings, state, {"status": "continuing", "phase": "writing"},
                                    {"runner": OWNER}, successful=True) == "phase_writing"


def test_removed_writer_runner_leaves_the_writing_to_the_seat(tmp_path, monkeypatch) -> None:
    paths, db, settings, _topics = _owner_program(
        tmp_path, monkeypatch, owner_settings=OwnerSettings(runners=(OWNER,)))
    settings = _with(settings, writer=OWNER)
    state = {"writing": {"status": owner.WRITING_ACTIVE, "runner": "worker_removed"}}
    assert owner.writing_plan(settings, state, OWNER) == (owner.PLAN_OWNER, "writer_removed")
    lines = owner.writing_brief_lines(settings, task={"runner": OWNER},
                                      writing=state["writing"], state=state)
    assert lines and "no longer configured" in lines[0]


# --------------------------------------------------------------------------- stalls


def _quiet(db, campaign_id: str) -> None:
    """Test only: end every live task of a campaign (a parked or finished topic)."""

    with db.connect() as connection:
        connection.execute("UPDATE tasks SET status='cancelled' WHERE campaign_id=? AND status "
                           "IN ('queued','leased','running','awaiting_remote')", (campaign_id,))


def test_state_signature_ignores_text_and_order() -> None:
    first, _ = spin_guard.state_signature({"phase": "writing", "jobs": ["b", "a"],
                                           "status": "continuing"})
    second, fields = spin_guard.state_signature({"status": "continuing", "jobs": ["a", "b"],
                                                 "phase": "writing", "summary": "ignored"})
    assert first == second and fields["jobs"] == ["a", "b"] and "summary" not in fields
    third, _ = spin_guard.state_signature({"phase": "writing", "jobs": ["a", "b"],
                                           "status": "continuing", "digest": "d2"})
    assert third != first


def _same_seat(paths, db, settings, monkeypatch, task_id: str, n: int) -> None:
    _release(db, task_id)
    _lease(paths, settings, monkeypatch, db, task_id)
    _seat_packet(db, paths, task_id, {"status": "continuing", "phase": "writing",
                                      "next_step": "Hand the manuscript to the writer."},
                 session="s1", duration=600.0)
    _tick(paths, settings, monkeypatch)


def test_same_state_seats_get_one_decision_then_stop(tmp_path, monkeypatch) -> None:
    paths, db, settings, (topic,) = _owner_program(
        tmp_path, monkeypatch,
        owner_settings=OwnerSettings(runners=(OWNER,), no_progress_seats=50,
                                     session_max_seats=0))
    settings = _with(settings, writer=None, stall_signature_repeats=3,
                     stall_seats_after_decision=2)
    campaign_id = topic["campaign_id"]
    for n in range(1, 4):
        _same_seat(paths, db, settings, monkeypatch, _latest(db, campaign_id)["task_id"], n)
    assert not _direction_tasks(db)
    report = _tick(paths, settings, monkeypatch)
    _same_seat(paths, db, settings, monkeypatch, _latest(db, campaign_id)["task_id"], 4)
    assert owner.stalled(owner.owner_state(db, campaign_id)) is None
    _same_seat(paths, db, settings, monkeypatch, _latest(db, campaign_id)["task_id"], 5)
    state = owner.owner_state(db, campaign_id)
    stall = owner.stalled(state)
    assert stall is not None and not stall.get("decision_task")
    last = _latest(db, campaign_id)
    assert last["status"] == "succeeded"  # no further seat was queued
    # Replenishment respects the stop and the tick reports the topic as stuck.
    report = _tick(paths, settings, monkeypatch)
    assert _latest(db, campaign_id)["task_id"] == last["task_id"]
    assert any(item.get("reason") == "owner_stalled" for item in report.production_blocked)
    stuck = report.program.get("stuck_topics") or []
    assert any(item["source"] == "same_state" and item["action"] == "stopped" for item in stuck)
    missing = report.program.get("topics_without_next_step") or []
    assert any(item["reason"] == "owner_stalled" for item in missing)
    assert any(entry.get("kind") == "owner_stalled"
               for entry in _topic(paths, settings, topic["topic_id"]).get("history") or [])
    # A change of the research files (someone acted) clears the stop.
    campaign = db.campaign(campaign_id)
    target = Path(str(campaign["state_path"])) / "analysis" / "fix.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("print('fixed')\n", encoding="utf-8")
    _tick(paths, settings, monkeypatch)
    assert _latest(db, campaign_id)["task_id"] != last["task_id"]
    assert owner.stalled(owner.owner_state(db, campaign_id)) is None


def test_stall_detection_off_keeps_the_old_path(tmp_path, monkeypatch) -> None:
    paths, db, settings, (topic,) = _owner_program(
        tmp_path, monkeypatch,
        owner_settings=OwnerSettings(runners=(OWNER,), no_progress_seats=50))
    settings = _with(settings, writer=None, stall_signature_repeats=0)
    for n in range(1, 5):
        _same_seat(paths, db, settings, monkeypatch, _latest(db, topic["campaign_id"])["task_id"],
                   n)
    assert not _direction_tasks(db)
    assert owner.owner_state(db, topic["campaign_id"])["signature_streak"] == 4


def test_topic_without_next_step_is_reported(tmp_path, monkeypatch) -> None:
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    campaign_id = topic["campaign_id"]
    db.pause_production_campaign(campaign_id, reason="test_pause")
    _quiet(db, campaign_id)
    report = spin_guard.stuck_report(db, paths, settings)
    rows = [item for item in report["topics_without_next_step"]
            if item["topic_id"] == topic["topic_id"]]
    assert rows and rows[0]["reason"] == "campaign_production_paused"


# --------------------------------------------------------------------------- reconcile


def _receipt(paths, paper_id: str, version: str = "0.1.4") -> Path:
    path = paths.data / "papers" / paper_id / "releases" / f"pkg_{paper_id}_{version}_x.json"
    atomic_write_json(path, {"schema_version": "ara.paper_writing.release_receipt.v1",
                             "paper_id": paper_id, "package_id": f"pkg_{paper_id}_{version}_x",
                             "version": version, "released_at": "2026-11-15T15:29:37+00:00"})
    return path


def test_reconcile_lists_then_applies_through_the_transitions(tmp_path, monkeypatch) -> None:
    paths, db, settings, topics = _owner_program(tmp_path, monkeypatch, cards=2)
    delivered, parked = topics
    ledger = open_topic_ledger(paths, settings.program)
    transition_topic(ledger, delivered["topic_id"], "in_review", db=db,
                     reason="manuscript_entered_review", decided_by="test:review")
    paper_id = "20261113-biology-genetics-campylobacter-source-forward-validation"
    campaign = db.campaign(delivered["campaign_id"])
    state_path = Path(str(campaign["workstream_state_path"]))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    atomic_write_json(state_path, {**state, "paper_id": paper_id})
    receipt = _receipt(paths, paper_id)
    db.pause_production_campaign(parked["campaign_id"], reason="test_pause")
    for item in topics:
        _quiet(db, item["campaign_id"])
    later = datetime.now(UTC) + timedelta(days=10)
    planned = program_reconcile.plan(db, paths, settings, now=later)
    rows = {row["id"]: row for row in planned["rows"] if row["kind"] == "topic"}
    assert rows[delivered["topic_id"]]["action"] == "mark_delivered"
    assert rows[delivered["topic_id"]]["paper_id_source"] == "research_state.json"
    assert rows[delivered["topic_id"]]["receipt"]["path"] == str(receipt)
    assert rows[parked["topic_id"]]["action"] == "archive"
    text = program_reconcile.render(planned)
    assert "mark_delivered" in text and "basis:" in text
    # The dry run wrote nothing.
    assert _topic(paths, settings, delivered["topic_id"])["status"] == "in_review"
    before = len(_topic(paths, settings, parked["topic_id"])["history"])
    result = program_reconcile.apply(db, paths, settings, planned)
    assert result["errors"] == []
    done = _topic(paths, settings, delivered["topic_id"])
    assert done["status"] == "ready_queue" and done["paper_id"] == paper_id
    assert done["handoff"]["status"] == "delivered" and done["release"]["status"] == "done"
    archived = _topic(paths, settings, parked["topic_id"])
    assert archived["status"] == "frozen"
    assert archived["freeze_reason_class"] == LEGACY_ARCHIVE_REASON
    assert len(archived["history"]) == before + 1  # history kept, one entry added
    # The release pipeline leaves a reconciled delivery alone.
    report = _tick(paths, settings, monkeypatch)
    assert not [item for item in report.program.get("handoffs") or []
                if item.get("topic_id") == delivered["topic_id"]]


def test_delivery_reconcile_needs_evidence_and_archive_is_guarded(tmp_path, monkeypatch) -> None:
    from openlabs.program import TopicLedgerError, mark_topic_delivered

    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    ledger = open_topic_ledger(paths, settings.program)
    with pytest.raises(TopicLedgerError):
        mark_topic_delivered(ledger, topic["topic_id"], db=db, decided_by="test", paper_id="p",
                             evidence=[], handoff={}, release={})
    # admitted -> frozen exists only for the legacy archive.
    document = ledger.read()
    entry = next(item for item in document["topics"] if item["topic_id"] == topic["topic_id"])
    assert entry["status"] == "active"
    from openlabs.program import GUARDED_TRANSITIONS

    assert GUARDED_TRANSITIONS[("admitted", "frozen")] == frozenset({LEGACY_ARCHIVE_REASON})
    with pytest.raises(IllegalTopicTransition):
        from openlabs.program import _apply_transition

        _apply_transition({"topic_id": "t", "status": "admitted",
                           "history": [{"to": "admitted"}]}, "frozen", reason="overdue",
                          decided_by="x", evidence=[], updates={}, at="now")


def test_reconcile_closes_orphaned_needs_human_and_annotates_old_replans(tmp_path,
                                                                        monkeypatch) -> None:
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    campaign_id = topic["campaign_id"]
    seat = _latest(db, campaign_id)
    with db.connect() as connection:
        connection.execute("UPDATE tasks SET status='needs_human', last_error='stop' "
                           "WHERE task_id=?", (seat["task_id"],))
    db.pause_production_campaign(campaign_id, reason="test_pause")
    planned = program_reconcile.plan(db, paths, settings,
                                     now=datetime.now(UTC) + timedelta(days=10))
    rows = [row for row in planned["rows"] if row["id"] == seat["task_id"]]
    assert rows and rows[0]["action"] == "close"
    program_reconcile.apply(db, paths, settings,
                            {"rows": [row for row in planned["rows"] if row["kind"] == "task"]})
    closed = db.task(seat["task_id"])
    assert closed["status"] == "cancelled"
    assert closed["last_error"].startswith("closed_by_reconcile:") and "was: stop" in closed[
        "last_error"]


# --------------------------------------------------------------------------- usage


def _lab_runner():
    path = Path(__file__).resolve().parents[2] / "packages" / "research-core" / "lab_runner.py"
    spec = importlib.util.spec_from_file_location("lab_runner_w3", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_claude_result_stretches_are_summed(tmp_path) -> None:
    stream = tmp_path / "agent-stdout.log"
    events = [
        {"type": "system", "session_id": "s"},
        {"type": "result", "session_id": "s", "total_cost_usd": 4.7,
         "usage": {"input_tokens": 10, "cache_read_input_tokens": 9_000_000,
                   "cache_creation_input_tokens": 100, "output_tokens": 60_698}},
        {"type": "result", "session_id": "s", "total_cost_usd": 6.3,
         "usage": {"input_tokens": 2, "cache_read_input_tokens": 200_000,
                   "cache_creation_input_tokens": 0, "output_tokens": 94}},
    ]
    stream.write_text("\n".join(json.dumps(item) for item in events) + "\n")
    runtime = _lab_runner()._jsonl_runtime(stream)
    assert runtime["output_tokens"] == 60_792 and runtime["result_segments"] == 2
    assert runtime["cached_input_tokens"] == 9_200_000 and runtime["cost_usd"] == 6.3
    # Codex: the thread total of the last turn wins (unchanged).
    codex = tmp_path / "codex.log"
    codex.write_text("\n".join(json.dumps(item) for item in [
        {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}},
        {"type": "turn.completed", "usage": {"input_tokens": 30, "output_tokens": 9}},
    ]) + "\n")
    assert _lab_runner()._jsonl_runtime(codex)["output_tokens"] == 9


def test_old_claude_attempt_is_priced_by_its_cli_cost() -> None:
    from types import SimpleNamespace

    from openlabs.config import ReportingSettings

    settings = SimpleNamespace(reporting=ReportingSettings(), runners={})
    old = {"runtime": {"adapter": "claude", "model": "claude-opus-5-5", "output_tokens": 154,
                       "input_tokens": 4, "cached_input_tokens": 240_377, "cost_usd": 6.83},
           "run_seconds": 5688}
    figures = usage.attempt_figures(old, settings)
    assert figures["cost_from_cli"] and figures["equivalent_usd"] == pytest.approx(6.83)
    new = {"runtime": {**old["runtime"], "result_segments": 3}, "run_seconds": 5688}
    assert not usage.attempt_figures(new, settings)["cost_from_cli"]


def test_external_reviewer_processes_are_read_from_the_run(tmp_path) -> None:
    run = tmp_path / "reviews" / "unified" / "paper" / "20261120T000000Z"
    claude = run / "referee_a"
    codex = run / "editor"
    for folder in (claude, codex):
        folder.mkdir(parents=True)
    atomic_write_json(claude / "receipt.json", {"role": "referee_a", "tool": "Claude Code",
                                                "provider": "anthropic", "model": "m"})
    (claude / "stdout.txt").write_text(json.dumps({
        "type": "result", "total_cost_usd": 1.37,
        "usage": {"input_tokens": 2, "cache_creation_input_tokens": 44_268,
                  "cache_read_input_tokens": 0, "output_tokens": 16_653}}) + "\n")
    atomic_write_json(codex / "receipt.json", {"role": "editor", "tool": "Codex",
                                               "provider": "openai-codex", "model": "g"})
    (codex / "stdout.txt").write_text("{}\n")
    (codex / "stderr.txt").write_text("model: g\n...\ntokens used\n67,713\n")
    atomic_write_json(run / "decision.json", {})
    rows = {row["role"]: row for row in usage.external_review_usage(
        tmp_path, "reviews/unified/paper/20261120T000000Z/decision.json")}
    assert rows["referee_a"]["output_tokens"] == 16_653
    assert rows["referee_a"]["tokens_read"] == 44_270
    assert rows["referee_a"]["equivalent_usd"] == pytest.approx(1.37)
    assert rows["editor"]["tokens_total_unsplit"] == 67_713
    assert rows["editor"]["equivalent_usd"] is None
    # Outside reviews/ nothing is read.
    assert usage.external_review_usage(tmp_path, "../elsewhere/decision.json") == []
