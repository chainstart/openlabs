"""Writer hand-over (user decision 2026-11-19): the owner solves, one writer writes."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from openlabs import owner
from openlabs.config import OWNER_TASK_TYPE, OwnerSettings, load_program_settings
from openlabs.db import utc_now
from test_owner_mode import _first_seat, _latest, _owner_program, _seat_packet, _tasks, engine_report
from test_program_autonomy import _lease, _topic
from test_research_program_flow import RUNNERS, _tick

CLAUDE = RUNNERS["worker_claude"].provider
WRITER = "worker_claude"


def _settings(**changes) -> OwnerSettings:
    base = dict(runners=("worker_gpt",), writing_runner=WRITER)
    base.update(changes)
    return OwnerSettings(**base)


def _with_writer(settings, writer: str | None = WRITER, **changes):
    return replace(settings, program=replace(
        settings.program, owner=replace(settings.program.owner, writing_runner=writer, **changes)))


def _hand_over(paths, db, settings, monkeypatch, topic, packet=None) -> tuple[dict, dict]:
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    assert seat["runner"] == "worker_gpt"
    _seat_packet(db, paths, seat["task_id"], packet or {"status": "continuing", "phase": "writing"},
                 artifact=True)
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    return seat, _latest(db, topic["campaign_id"])


def test_config_parses_the_writer_keys() -> None:
    parsed = load_program_settings({"owner": {"writing_runner": "worker_claude",
                                              "max_writing_topics": 3, "writing_wait_hours": 6}})
    assert parsed.owner.writing_runner == "worker_claude"
    assert parsed.owner.max_writing_topics == 3 and parsed.owner.writing_wait_hours == 6.0
    default = load_program_settings({}).owner
    assert default.writing_runner is None and default.max_writing_topics == 2
    assert default.writing_wait_hours == 12.0
    assert default.figure_runner is None
    assert load_program_settings({"owner": {"figure_runner": " light_claude "}}).owner.figure_runner \
        == "light_claude"


def test_declared_writing_phase_hands_the_topic_to_the_writer(tmp_path, monkeypatch) -> None:
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch, owner_settings=_settings())
    seat, nxt = _hand_over(paths, db, settings, monkeypatch, topic)
    assert nxt["task_type"] == OWNER_TASK_TYPE and nxt["runner"] == WRITER
    assert nxt["routing_reason"] == owner.ROUTING_WRITING and nxt["session_mode"] == "fresh"
    assert nxt["parent_task_id"] == seat["task_id"] and "writer of this topic" in nxt["objective"]
    writing = owner.writing_state(db, topic["campaign_id"])
    assert writing["status"] == owner.WRITING_ACTIVE and writing["solver_runner"] == "worker_gpt"
    assert writing["trigger"] == "phase_writing" and writing["trigger_task_id"] == seat["task_id"]
    history = _topic(paths, settings, topic["topic_id"]).get("history") or []
    assert any(entry.get("kind") == "writing_handover" for entry in history)
    # The writer keeps the topic seat after seat although it is not an owner runner.
    writer_seat = _lease(paths, settings, monkeypatch, db, nxt["task_id"])
    _seat_packet(db, paths, writer_seat["task_id"], {"status": "continuing"}, artifact=True)
    _tick(paths, settings, monkeypatch)
    assert _latest(db, topic["campaign_id"])["runner"] == WRITER


def test_reviews_of_the_writers_manuscript_avoid_the_writers_family(tmp_path, monkeypatch) -> None:
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch, owner_settings=_settings())
    _, nxt = _hand_over(paths, db, settings, monkeypatch, topic)
    writer_seat = _lease(paths, settings, monkeypatch, db, nxt["task_id"])
    _seat_packet(db, paths, writer_seat["task_id"], {
        "status": "ready_for_review", "paper_id": "20261119-ai-writer",
        "primary_endpoint_verdict": "met"}, artifact=True)
    _tick(paths, settings, monkeypatch)
    review = _latest(db, topic["campaign_id"])
    assert review["task_type"] == "paper_review"
    assert review["routing_reason"] == owner.ROUTING_REVIEW
    assert review["exclude_provider"] == CLAUDE and review["parent_task_id"] == writer_seat["task_id"]
    review = _lease(paths, settings, monkeypatch, db, review["task_id"])
    assert RUNNERS[review["runner"]].provider != CLAUDE
    # Even after a fallback seat of another family returned it, the active writer decides.
    assert owner.writer_provider(db, settings, topic["campaign_id"]) == CLAUDE


def test_unset_writer_keeps_the_owner_writing(tmp_path, monkeypatch) -> None:
    paths, db, settings, (topic,) = _owner_program(
        tmp_path, monkeypatch, owner_settings=OwnerSettings(runners=("worker_gpt",)))
    seat, nxt = _hand_over(paths, db, settings, monkeypatch, topic)
    assert nxt["runner"] == seat["runner"] == "worker_gpt"
    assert nxt["routing_reason"] == owner.ROUTING_CONTINUE
    assert owner.writing_state(db, topic["campaign_id"]) == {}
    assert owner.writing_brief_lines(settings, task=nxt, writing={}) == []


def test_topic_already_writing_or_in_review_keeps_its_writer(tmp_path, monkeypatch) -> None:
    # The owner declared phase writing before the setting existed: no change of writer.
    paths, db, settings, (topic,) = _owner_program(
        tmp_path, monkeypatch, owner_settings=OwnerSettings(runners=("worker_gpt",)))
    _, nxt = _hand_over(paths, db, settings, monkeypatch, topic)
    settings = _with_writer(settings)
    seat = _lease(paths, settings, monkeypatch, db, nxt["task_id"])
    _seat_packet(db, paths, seat["task_id"], {"status": "continuing", "phase": "writing"},
                 artifact=True)
    _tick(paths, settings, monkeypatch)
    assert _latest(db, topic["campaign_id"])["runner"] == "worker_gpt"
    # 2026-11-20: the owner keeps writing, and that is now recorded (never left implicit).
    writing = owner.writing_state(db, topic["campaign_id"])
    assert writing["status"] == owner.WRITING_OWNER and writing["reason"] == "already_writing"
    # A topic with a review round behind it: a manuscript by another model is in revision.
    before = {"phase": "solving", "review_round": 1}
    packet = {"status": "ready_for_review", "phase": "writing"}
    assert owner.writing_switch_due(settings, before, packet, {"runner": "worker_gpt"},
                                    successful=True) is None
    assert owner.writing_switch_due(settings, {"review_history": [{"round": 1}]}, packet,
                                    {"runner": "worker_gpt"}, successful=True) is None
    # Only a finished, promoted seat that says the research is done switches.
    assert owner.writing_switch_due(settings, {}, {"status": "awaiting_remote", "phase": "writing"},
                                    {"runner": "worker_gpt"}, successful=True) is None
    assert owner.writing_switch_due(settings, {}, {"status": "continuing", "phase": "solving"},
                                    {"runner": "worker_gpt"}, successful=True) is None
    assert owner.writing_switch_due(settings, {}, packet, {"runner": "worker_gpt"},
                                    successful=False) is None
    assert owner.writing_switch_due(settings, {}, packet, {"runner": WRITER}, successful=True) is None
    assert owner.writing_switch_due(settings, {"writing": {"status": "fallback"}}, packet,
                                    {"runner": "worker_gpt"}, successful=True) is None
    assert owner.writing_switch_due(settings, {}, packet, {"runner": "worker_gpt"},
                                    successful=True) == "phase_writing"
    assert owner.writing_switch_due(_with_writer(settings, "no_such_runner"), {}, packet,
                                    {"runner": "worker_gpt"}, successful=True) is None


def test_first_ready_for_review_before_any_review_also_hands_over(tmp_path, monkeypatch) -> None:
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch, owner_settings=_settings())
    _, nxt = _hand_over(paths, db, settings, monkeypatch, topic, packet={
        "status": "ready_for_review", "paper_id": "20261119-ai-writer",
        "primary_endpoint_verdict": "met"})
    assert nxt["task_type"] == OWNER_TASK_TYPE and nxt["runner"] == WRITER
    assert owner.writing_state(db, topic["campaign_id"])["trigger"] == "ready_for_review"
    assert not [t for t in _tasks(db, topic["campaign_id"]) if t["task_type"] == "paper_review"]


def test_owner_cap_does_not_count_or_block_writer_seats(tmp_path, monkeypatch) -> None:
    paths, db, settings, (topic,) = _owner_program(
        tmp_path, monkeypatch, owner_settings=_settings(max_topics_per_runner={WRITER: 0}))
    _, nxt = _hand_over(paths, db, settings, monkeypatch, topic)
    assert WRITER not in owner.current_owners(db)
    monkeypatch.setattr(owner, "runner_usable", lambda *_args: True)
    now = datetime.now(UTC)
    for minutes in (0, 200, 600):
        owner.supervise(db, settings, engine_report(), object(), now=now + timedelta(minutes=minutes))
    queued = db.task(nxt["task_id"])
    assert queued["runner"] == WRITER and queued["not_before"] is None
    # The writer seat is leased normally despite the owner cap of 0 for its runner.
    assert _lease(paths, settings, monkeypatch, db, nxt["task_id"])["runner"] == WRITER


def test_writer_seat_waits_for_quota_then_falls_back_to_the_owner(tmp_path, monkeypatch) -> None:
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch, owner_settings=_settings())
    _tick_settings = replace(settings, launch_jobs=False)
    seat, nxt = _hand_over(paths, db, _tick_settings, monkeypatch, topic)
    monkeypatch.setattr(owner, "runner_usable", lambda _s, _r, name: name != WRITER)
    now = datetime.now(UTC)
    report = engine_report()
    for hours in (0, 3, 11.9):
        assert owner.supervise(db, settings, report, object(), now=now + timedelta(hours=hours),
                               paths=paths) == []
        assert db.task(nxt["task_id"])["runner"] == WRITER
    moves = owner.supervise(db, settings, report, object(), now=now + timedelta(hours=12.1),
                            paths=paths)
    assert moves and moves[0]["to_runner"] == "worker_gpt" and moves[0]["reason"] == "writer_unavailable"
    moved = db.task(nxt["task_id"])
    assert moved["runner"] == "worker_gpt" and moved["session_mode"] == "fresh"
    writing = owner.writing_state(db, topic["campaign_id"])
    assert writing["status"] == owner.WRITING_FALLBACK and writing["fallback_runner"] == "worker_gpt"
    assert owner.active_writer(db, settings, topic["campaign_id"]) is None
    history = _topic(paths, settings, topic["topic_id"]).get("history") or []
    assert any(entry.get("kind") == "writing_fallback" for entry in history)
    assert report.program["owner_writing"][0]["kind"] == "fallback"
    # The owner now writes; later seats stay with it and get the fallback role line.
    lines = owner.writing_brief_lines(settings, task=moved, writing=writing)
    assert lines and "could not start" in lines[0]
    assert seat["runner"] == "worker_gpt"


def test_writer_seat_falls_back_to_a_configured_fallback_writer(tmp_path, monkeypatch) -> None:
    # UD-20261126-gemini-ultra: a listed fallback writer takes the seat before the solver;
    # the writer itself, unknown runners, non-owner runners and runners at their cap are skipped.
    paths, db, settings, (topic,) = _owner_program(
        tmp_path, monkeypatch,
        owner_settings=_settings(runners=("worker_gpt", "lead_claude", "lead_gpt"),
                                 max_topics_per_runner={"lead_claude": 0},
                                 writing_fallback_runners=(WRITER, "ghost", "worker_claude",
                                                           "lead_claude", "lead_gpt")))
    _tick_settings = replace(settings, launch_jobs=False)
    _, nxt = _hand_over(paths, db, _tick_settings, monkeypatch, topic)
    monkeypatch.setattr(owner, "runner_usable", lambda _s, _r, name: name != WRITER)
    now = datetime.now(UTC)
    report = engine_report()
    assert owner.supervise(db, settings, report, object(), now=now, paths=paths) == []
    moves = owner.supervise(db, settings, report, object(), now=now + timedelta(hours=12.1),
                            paths=paths)
    assert moves and moves[0]["to_runner"] == "lead_gpt"
    moved = db.task(nxt["task_id"])
    assert moved["runner"] == "lead_gpt" and moved["session_mode"] == "fresh"
    writing = owner.writing_state(db, topic["campaign_id"])
    assert writing["fallback_runner"] == "lead_gpt" and writing["solver_runner"] == "worker_gpt"
    lines = owner.writing_brief_lines(settings, task=moved, writing=writing)
    assert "could not start" in lines[0] and owner.HANDOVER_NAME in lines[0]


def test_unusable_fallback_writers_leave_the_seat_to_the_solver(tmp_path, monkeypatch) -> None:
    paths, db, settings, (topic,) = _owner_program(
        tmp_path, monkeypatch, owner_settings=_settings(writing_fallback_runners=("lead_gpt",)))
    _tick_settings = replace(settings, launch_jobs=False)
    _, nxt = _hand_over(paths, db, _tick_settings, monkeypatch, topic)
    monkeypatch.setattr(owner, "runner_usable",
                        lambda _s, _r, name: name not in {WRITER, "lead_gpt"})
    now = datetime.now(UTC)
    owner.supervise(db, settings, engine_report(), object(), now=now, paths=paths)
    moves = owner.supervise(db, settings, engine_report(), object(),
                            now=now + timedelta(hours=12.1), paths=paths)
    assert moves and moves[0]["to_runner"] == "worker_gpt"
    writing = owner.writing_state(db, topic["campaign_id"])
    lines = owner.writing_brief_lines(settings, task=db.task(nxt["task_id"]), writing=writing)
    assert owner.HANDOVER_NAME not in lines[0]


def test_config_parses_writing_fallback_runners() -> None:
    parsed = load_program_settings(
        {"owner": {"writing_fallback_runners": [" worker_gemini ", "", "worker_gemini", "x"]}})
    assert parsed.owner.writing_fallback_runners == ("worker_gemini", "x")
    assert load_program_settings({}).owner.writing_fallback_runners == ()


def test_writer_slots_hold_extra_writing_seats(tmp_path, monkeypatch) -> None:
    paths, db, settings, (first_topic, second_topic) = _owner_program(
        tmp_path, monkeypatch, cards=2, owner_settings=_settings(max_writing_topics=1))
    ids = [owner.start_writing(db, paths, settings, None, task=_latest(db, t["campaign_id"]),
                               campaign=db.campaign(t["campaign_id"]), trigger="phase_writing",
                               result_path=Path("/r.json"))
           for t in (first_topic, second_topic)]
    first, second_id = db.task(ids[0]), ids[1]
    assert first["runner"] == db.task(second_id)["runner"] == WRITER
    monkeypatch.setattr(owner, "runner_usable", lambda *_args: True)
    now = datetime.now(UTC)
    owner.supervise(db, settings, engine_report(), object(), now=now)
    first, second = db.task(first["task_id"]), db.task(second_id)
    # The first writer seat runs or may start; the second waits for the single slot.
    assert first["status"] in {"leased", "running"} or first["not_before"] is None
    assert second["status"] == "queued" and second["not_before"] is not None
    assert second["runner"] == WRITER
    # The slot frees once the first writer seat is no longer queued or running.
    with db.connect() as connection:
        connection.execute("UPDATE tasks SET status='succeeded', updated_at=? WHERE task_id=?",
                           (utc_now(), first["task_id"]))
    owner.supervise(db, settings, engine_report(), object(), now=now + timedelta(minutes=20))
    assert db.task(second_id)["runner"] == WRITER
    assert not db.meta_get(owner.BLOCKED_META_PREFIX + second_id)


def test_briefs_tell_the_owner_to_hand_over_and_the_writer_to_write(tmp_path, monkeypatch) -> None:
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch, owner_settings=_settings())
    seat = _latest(db, topic["campaign_id"])
    lines = owner.writing_brief_lines(settings, task=seat, writing={})
    assert lines and owner.HANDOVER_NAME in lines[0] and "phase writing" in lines[0]
    assert "file or script that produces it" in lines[0]
    assert "2–4 key points with suggested figure types" in lines[0]
    writing = {"status": owner.WRITING_ACTIVE, "runner": WRITER, "solver_runner": "worker_gpt"}
    lines = owner.writing_brief_lines(settings, task={"runner": WRITER}, writing=writing)
    assert lines and "writer" in lines[0] and "Do not split" in lines[0]
    brief = owner.render_brief(paths, settings, task=seat, campaign=db.campaign(topic["campaign_id"]),
                               topic=topic, adapter_family=None,
                               deadline=datetime(2026, 11, 19), writing={})
    assert "## Writing" in brief
    reviewed = owner.render_brief(paths, settings, task=seat, campaign=db.campaign(topic["campaign_id"]),
                                  topic=topic, adapter_family=None, deadline=datetime(2026, 11, 19),
                                  state={"review_round": 1}, writing={})
    assert owner.owner_writes_note("review_history") in reviewed
    assert "CODE/docs/owner-policy.md" in reviewed
