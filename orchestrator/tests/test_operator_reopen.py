"""Operator text-revision grants of topics frozen in review (``program reopen-grant``)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from openlabs import owner, reopen
from openlabs.config import OWNER_TASK_TYPE, LineSettings, OwnerSettings, ProgramSettings
from openlabs.program import (
    OPERATOR_REOPEN_REASON,
    grant_slot_exempt,
    open_topic_ledger,
    slot_status,
    transition_topic,
)
from test_owner_mode import _first_seat, _latest, _owner_program, _seat_packet, _tasks
from test_program_autonomy import _decide, _direction_task, _finish, _lease, _outcome, _topic
from test_research_program_flow import _tick

BYLINE = ("Correct the li2024 byline to Li X.-Z., Zhu Q.-F., Ding X. et al. in references.bib, "
          "the Introduction and Table 6; reword the Appendix B q = 0.3323 point as an NLL excess.")
COMPUTE = "A new compute allocation funds a dense common-q profile of Sectors 67 and 98."
REASON = "User 2026-11-20: grant one further writer revision"
NO_DECISIONS = {"targeted_core_analysis": 0, "retarget_or_short_format": 0}


def _setup(tmp_path, monkeypatch, **program):
    program.setdefault("direction_limits", dict(NO_DECISIONS))
    return _owner_program(
        tmp_path, monkeypatch,
        owner_settings=OwnerSettings(recompute_review=False, session_max_seats=0), **program)


def _ready(db, paths, settings, monkeypatch, seat) -> dict:
    _seat_packet(db, paths, seat["task_id"], {
        "status": "ready_for_review", "paper_id": "20261119-ai-owner",
        "primary_endpoint_verdict": "failed"}, session="s1", artifact=True)
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    review = _latest(db, seat["campaign_id"])
    assert review["task_type"] == "paper_review"
    return _lease(paths, settings, monkeypatch, db, review["task_id"])


def _review_then_freeze(paths, db, settings, monkeypatch, review, **outcome) -> None:
    _finish(db, paths, review["task_id"], supported=False,
            extra={"review_outcome": _outcome(**outcome)})
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    task = _direction_task(db)
    reason = json.loads(Path(task["input_path"]).read_text())["reasons_to_answer"][0]
    report = _decide(paths, settings, monkeypatch, db, {
        "choice": "freeze", "rationale": "No decision is left; two text defects remain.",
        "answers_reason": reason,
        "freeze": {"reason_class": "review_stalled", "reopen_conditions": [
            {"type": "venue_policy_change", "description": BYLINE},
            {"type": "new_method", "description": COMPUTE},
        ]},
    })
    assert report.errors == [], report.errors


def _frozen_in_review(tmp_path, monkeypatch, **program):
    """A topic whose manuscript reached unified round 3 of 4, then froze review_stalled."""

    paths, db, settings, (topic,) = _setup(tmp_path, monkeypatch, **program)
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    review = _ready(db, paths, settings, monkeypatch, seat)
    _review_then_freeze(paths, db, settings, monkeypatch, review, review_stalled=True,
                        next_action="text_revision", rounds_for_target=3)
    frozen = _topic(paths, settings, topic["topic_id"])
    assert frozen["status"] == "frozen" and frozen["freeze_reason_class"] == "review_stalled"
    assert db.campaign(topic["campaign_id"])["status"] == "frozen"
    return paths, db, settings, topic, seat


def _grant(paths, db, settings, topic, **extra):
    return reopen.grant_operator_reopen(db, paths, settings, topic_id=topic["topic_id"],
                                        reason=extra.pop("reason", REASON),
                                        by=extra.pop("by", "owner"), **extra)


# --------------------------------------------------------------------------- the grant


def test_grant_returns_the_topic_to_review_with_one_writer_seat(tmp_path, monkeypatch):
    paths, db, settings, topic, first = _frozen_in_review(tmp_path, monkeypatch)
    payload = _grant(paths, db, settings, topic)
    assert payload["status"] == "in_review" and payload["changed"]
    assert payload["grants_used"] == 1 and payload["operator_reopen_max"] == 1
    granted = _topic(paths, settings, topic["topic_id"])
    assert granted["status"] == "in_review"
    assert granted["preregistration_sha256"] == topic["preregistration_sha256"]
    move = [h for h in granted["history"] if h.get("to")][-1]
    assert move["from"] == "frozen" and move["reason"] == OPERATOR_REOPEN_REASON
    assert move["decided_by"] == "operator:owner"
    note = granted["history"][-1]
    assert note["kind"] == "operator_reopen_granted"
    assert note["detail"]["reason"] == REASON and note["detail"]["by"] == "owner"
    block = granted["reopen_grant"]
    assert block["scope"] == "text_revision" and block["slot_exempt"] is True
    assert block["grants"][0]["reason"] == REASON and block["grants"][0]["at"]
    assert not (granted.get("auto_reopen") or {}).get("reopens")  # automatic count untouched
    assert db.campaign(topic["campaign_id"])["status"] == "active"
    seat = db.task(payload["seat"])
    assert seat["task_type"] == OWNER_TASK_TYPE and seat["status"] == "queued"
    assert seat["routing_reason"] == reopen.ROUTING_OPERATOR_REOPEN
    assert seat["runner"] == first["runner"]  # the manuscript's writer, not a new owner
    text = seat["objective"]
    assert BYLINE in text and REASON in text and COMPUTE in text
    assert "do not run new analyses" in text and "ready_for_review" in text
    assert "Conditions now met" not in text and "precheck" not in text
    assert db.count_events("campaign", topic["campaign_id"], "campaign_reopened") == 1

    # The tick keeps one seat; the topic holds no slot while it is in review on the grant.
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    seats = [t for t in _tasks(db, topic["campaign_id"])
             if t["routing_reason"] == reopen.ROUTING_OPERATOR_REOPEN]
    assert len(seats) == 1
    assert report.program["grant_exempt_topics"] == 1 and report.program["in_review"] == 0
    assert report.program["warnings"] == []


def test_revision_goes_to_the_next_unified_review_and_refreezes_when_rounds_run_out(
    tmp_path, monkeypatch
):
    paths, db, settings, topic, _ = _frozen_in_review(tmp_path, monkeypatch)
    seat = _lease(paths, settings, monkeypatch, db, _grant(paths, db, settings, topic)["seat"])
    review = _ready(db, paths, settings, monkeypatch, seat)
    assert review["routing_reason"] == owner.ROUTING_REVIEW
    assert _topic(paths, settings, topic["topic_id"])["status"] == "in_review"
    # Round 4 of 4 is blocked again: the ordinary flow decides, and with no decision left
    # the topic freezes again.
    _review_then_freeze(paths, db, settings, monkeypatch, review, status="blocked",
                        rounds_for_target=4)
    refrozen = _topic(paths, settings, topic["topic_id"])
    assert refrozen["status"] == "frozen" and refrozen["freeze_reason_class"] == "review_stalled"
    assert db.campaign(topic["campaign_id"])["status"] == "frozen"
    assert not grant_slot_exempt(refrozen)
    # One grant per topic by default; and the last review used the last round anyway.
    with pytest.raises(reopen.ReopenGrantError, match="operator_reopen_max"):
        _grant(paths, db, settings, topic)
    more = replace(settings, program=replace(settings.program, operator_reopen_max=2))
    with pytest.raises(reopen.ReopenGrantError, match="no review round is left"):
        _grant(paths, db, more, topic)


def test_revision_that_passes_moves_the_topic_to_the_ready_queue(tmp_path, monkeypatch):
    paths, db, settings, topic, _ = _frozen_in_review(tmp_path, monkeypatch)
    seat = _lease(paths, settings, monkeypatch, db, _grant(paths, db, settings, topic)["seat"])
    review = _ready(db, paths, settings, monkeypatch, seat)
    _finish(db, paths, review["task_id"], extra={
        "paper_candidate": True, "review_outcome": _outcome(status="ready", rounds_for_target=4)})
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    assert _topic(paths, settings, topic["topic_id"])["status"] == "ready_queue"


# --------------------------------------------------------------------------- refusals


def _set_topic(paths, settings, topic_id: str, **fields) -> None:
    """Test-only ledger edit (the code under test never edits like this)."""

    ledger = open_topic_ledger(paths, settings.program)
    with ledger.transaction() as document:
        entry = next(t for t in document["topics"] if t["topic_id"] == topic_id)
        entry.update(fields)


def test_scientific_and_other_freezes_are_refused(tmp_path, monkeypatch):
    paths, db, settings, topic, _ = _frozen_in_review(tmp_path, monkeypatch)
    for reason_class in ("primary_endpoint_failed", "feasibility_precheck_failed",
                         "decisive_data_unavailable", "contribution_insufficient"):
        _set_topic(paths, settings, topic["topic_id"], freeze_reason_class=reason_class)
        with pytest.raises(reopen.ReopenGrantError, match="scientific reason"):
            _grant(paths, db, settings, topic)
    for reason_class in ("budget_exhausted", "infrastructure", "no_eligible_venue"):
        _set_topic(paths, settings, topic["topic_id"], freeze_reason_class=reason_class)
        with pytest.raises(reopen.ReopenGrantError, match="not a procedural"):
            _grant(paths, db, settings, topic)
    _set_topic(paths, settings, topic["topic_id"], freeze_reason_class="review_stalled")
    with pytest.raises(reopen.ReopenGrantError, match="required"):
        _grant(paths, db, settings, topic, reason=" ")
    with pytest.raises(reopen.ReopenGrantError, match="scope"):
        _grant(paths, db, settings, topic, scope="research")
    off = replace(settings, program=replace(settings.program, operator_reopen_max=0))
    with pytest.raises(reopen.ReopenGrantError, match="off"):
        _grant(paths, db, off, topic)
    with pytest.raises(reopen.ReopenGrantError, match="unknown topic"):
        reopen.grant_operator_reopen(db, paths, settings, topic_id="nope", reason=REASON,
                                     by="owner")
    # Nothing moved.
    assert _topic(paths, settings, topic["topic_id"])["status"] == "frozen"
    assert db.campaign(topic["campaign_id"])["status"] == "frozen"
    assert _grant(paths, db, settings, topic)["status"] == "in_review"
    with pytest.raises(reopen.ReopenGrantError, match="not frozen"):
        _grant(paths, db, settings, topic)


def test_topic_frozen_before_review_is_refused(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _setup(tmp_path, monkeypatch)
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _seat_packet(db, paths, seat["task_id"], {
        "status": "frozen", "freeze_reason_class": "overdue",
        "reason": "The calendar limit passed before any manuscript."}, session="s1", artifact=True)
    _tick(paths, settings, monkeypatch)
    assert _topic(paths, settings, topic["topic_id"])["status"] == "frozen"
    with pytest.raises(reopen.ReopenGrantError, match="in review"):
        _grant(paths, db, settings, topic)


def test_half_done_grant_is_finished_by_the_tick(tmp_path, monkeypatch):
    paths, db, settings, topic, _ = _frozen_in_review(tmp_path, monkeypatch)
    ledger = open_topic_ledger(paths, settings.program)
    # The ledger move happened, then the process died before the campaign and the seat.
    transition_topic(ledger, topic["topic_id"], "in_review", db=db,
                     reason=OPERATOR_REOPEN_REASON, decided_by="operator:owner",
                     updates={"reopen_grant": {"scope": "text_revision", "slot_exempt": True,
                                               "grants": [{"at": "2026-11-20T02:00:00Z",
                                                           "by": "owner", "reason": REASON,
                                                           "scope": "text_revision"}]}})
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    assert report.program["reopen_repaired"] == [topic["topic_id"]]
    assert db.campaign(topic["campaign_id"])["status"] == "active"
    seat = _latest(db, topic["campaign_id"])
    assert seat["routing_reason"] == reopen.ROUTING_OPERATOR_REOPEN and REASON in seat["objective"]


def test_cli_refuses_with_a_message(tmp_path, monkeypatch, capsys):
    from openlabs import __main__ as cli

    paths, db, settings, topic, _ = _frozen_in_review(tmp_path, monkeypatch)
    _set_topic(paths, settings, topic["topic_id"], freeze_reason_class="primary_endpoint_failed")
    monkeypatch.setattr(cli, "load_settings", lambda _paths: settings)
    monkeypatch.setattr(cli, "workspace_paths", lambda _workspace: paths)
    code = cli.main(["program", "reopen-grant", "--topic-id", topic["topic_id"],
                     "--reason", REASON, "--by", "owner"])
    assert code == 1
    error = json.loads(capsys.readouterr().err)
    assert error["status"] == "refused" and "scientific reason" in error["error"]


# --------------------------------------------------------------------------- slots


def _ledger_topic(topic_id: str, status: str, line: str, moves: list[tuple[str, str]],
                  *, grant: bool = True, notes: list[dict] | None = None) -> dict:
    history = [{"from": None, "to": "proposed", "reason": "topic_card_submitted"}]
    previous = "proposed"
    for to, reason in moves:
        history.append({"from": previous, "to": to, "reason": reason})
        previous = to
    history.extend(notes or [])
    topic = {"topic_id": topic_id, "status": status, "research_line": line,
             "campaign_id": f"c-{topic_id}", "history": history}
    if grant:
        topic["reopen_grant"] = {"scope": "text_revision", "slot_exempt": True, "grants": [{}]}
    return topic


REVIEW_PATH = [("admitted", "admission_gate_passed"), ("active", "campaign_materialized"),
               ("in_review", "manuscript_entered_review"), ("frozen", "review_stalled")]


def test_granted_topic_holds_no_slot_and_other_topics_count_as_before() -> None:
    line = "astro-survey-photometry"
    settings = ProgramSettings(enabled=True, max_active_topics=5,
                               lines={line: LineSettings(slots=2)})
    granted = _ledger_topic("g", "in_review", line,
                            [*REVIEW_PATH, ("in_review", OPERATOR_REOPEN_REASON)])
    reviewing = _ledger_topic("r", "in_review", line,
                              [("admitted", "a"), ("active", "m"),
                               ("in_review", "manuscript_entered_review")], grant=False)
    researching = _ledger_topic("a", "active", line, [("admitted", "a"), ("active", "m")],
                                grant=False)
    baseline = slot_status({"topics": [reviewing, researching]}, settings)
    status = slot_status({"topics": [granted, reviewing, researching]}, settings)
    assert grant_slot_exempt(granted) and not grant_slot_exempt(reviewing)
    for field in ("occupied", "free_slots", "in_review", "active", "research_free_slots"):
        assert getattr(status, field) == getattr(baseline, field), field
    assert status.line_occupied == baseline.line_occupied == {line: 2}
    assert status.grant_exempt == 1 and status.line_grant_exempt == {line: 1}
    lines = status.to_dict()["lines"][line]
    assert lines["occupied"] == 2 and lines["free_slots"] == 0 and lines["grant_exempt"] == 1
    assert status.to_dict()["grant_exempt_topics"] == 1


def test_exemption_ends_with_research_or_a_later_full_review() -> None:
    granted_path = [*REVIEW_PATH, ("in_review", OPERATOR_REOPEN_REASON)]
    analysis = {"kind": "direction_decided", "reason": "targeted_core_analysis",
                "detail": {"accepted": True}}
    refused = {"kind": "direction_decided", "reason": "direction_limit_exhausted",
               "detail": {"accepted": False}}
    assert grant_slot_exempt(_ledger_topic("t", "in_review", "x", granted_path, notes=[refused]))
    assert not grant_slot_exempt(_ledger_topic("t", "in_review", "x", granted_path,
                                               notes=[analysis]))
    after_ready = [*granted_path, ("ready_queue", "review_passed"),
                   ("in_review", "release_full_review_required")]
    assert not grant_slot_exempt(_ledger_topic("t", "in_review", "x", after_ready))
    assert not grant_slot_exempt(_ledger_topic("t", "ready_queue", "x",
                                               [*granted_path, ("ready_queue", "review_passed")]))
    unflagged = _ledger_topic("t", "in_review", "x", granted_path)
    unflagged["reopen_grant"]["slot_exempt"] = False
    assert not grant_slot_exempt(unflagged)
