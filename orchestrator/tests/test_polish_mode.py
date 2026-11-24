"""Polish mode (2026-11-23) and operator pause of a topic in research.

Owner: "现在应该停止产线的新任务，新实验，应该转向对已经产出的多篇论文全面进行梳理". With
``[program] polish_mode = true`` no new topic supply or research start is scheduled,
while writing, review, delivery and delivered-version revisions keep running; a topic in
research without a manuscript is held with ``program pause-topic`` and resumed with
``--resume``.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from openlabs import program_flow
from openlabs.config import load_program_settings
from openlabs.program import open_topic_ledger, paused_topic_campaigns
from openlabs.program_flow import (
    materialize_waiting_topics,
    schedule_card_repairs,
    schedule_revisions,
    schedule_scouts,
)
from openlabs.reopen import reopen_ready_topics
from openlabs.topic_pause import TopicPauseError, pause_topic
from test_research_program_flow import (
    RECEIPT_SHA,
    _branch,
    _card,
    _complete,
    _db,
    _install_program,
    _packet,
    _paths,
    _settings,
    _tick,
    _to_admission,
)


def _polish(settings, on: bool = True):
    return dataclasses.replace(
        settings, program=dataclasses.replace(settings.program, polish_mode=on))


def test_config_key_defaults_off() -> None:
    assert load_program_settings({}).polish_mode is False
    assert load_program_settings({"polish_mode": True}).polish_mode is True
    # Only a real boolean true turns it on.
    assert load_program_settings({"polish_mode": "yes"}).polish_mode is False


def test_polish_mode_holds_scouts_admissions_repairs_and_materialization(
        tmp_path, monkeypatch) -> None:
    paths = _paths(tmp_path)
    _install_program(paths)
    db = _db(paths)
    settings = _settings()
    polish = _polish(settings)

    assert schedule_scouts(db, paths, polish, lead_short=False) == ([], "polish_mode")
    assert schedule_revisions(db, paths, polish, lead_short=False) == ([], "polish_mode")
    assert schedule_card_repairs(db, paths, polish) == []
    assert reopen_ready_topics(db, paths, polish, None) == []
    campaign = db.campaign("ai-program-scout") or {"campaign_id": "x"}
    assert program_flow.schedule_topic_admission(
        db, paths, polish, campaign, epoch=1).reason == "polish_mode"

    report = _tick(paths, polish, monkeypatch)
    assert report.errors == []
    assert report.program["scouts_scheduled"] == []
    assert report.program["scout_blocked"] == "polish_mode"
    assert report.program["polish_mode"]["on"] is True
    assert "topic_scout" in report.program["polish_mode"]["paused"]
    assert "delivered_revisions" in report.program["polish_mode"]["running"]

    # Off again: the next tick schedules the scout as before.
    report = _tick(paths, settings, monkeypatch)
    assert [item["domain"] for item in report.program["scouts_scheduled"]] == ["ai"]
    assert "polish_mode" not in report.program


def test_admitted_topic_waits_in_polish_mode_and_starts_after(tmp_path, monkeypatch) -> None:
    paths = _paths(tmp_path)
    _install_program(paths)
    db = _db(paths)
    settings = _settings()
    # An admission review already in flight when polish mode is switched on.
    _, admission, _ = _to_admission(paths, db, settings, monkeypatch, [_card(0, RECEIPT_SHA)])
    entry = _packet(admission)["topic_cards"][0]
    _complete(db, paths, admission["task_id"], extra={"candidate_branches": [_branch(entry)]})
    polish = _polish(settings)

    report = _tick(paths, polish, monkeypatch)
    assert report.errors == []
    ledger = open_topic_ledger(paths, settings.program)
    topic = ledger.topic(entry["topic_id"])
    assert topic["status"] == "admitted" and not topic.get("campaign_id")
    assert materialize_waiting_topics(db, paths, polish).campaign_ids == ()

    spawned = materialize_waiting_topics(db, paths, settings)
    assert len(spawned.campaign_ids) == 1
    assert ledger.topic(entry["topic_id"])["status"] == "active"


def _active_topic(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    _install_program(paths)
    db = _db(paths)
    settings = _settings()
    _, admission, _ = _to_admission(paths, db, settings, monkeypatch, [_card(0, RECEIPT_SHA)])
    entry = _packet(admission)["topic_cards"][0]
    _complete(db, paths, admission["task_id"], extra={"candidate_branches": [_branch(entry)]})
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == []
    topic = open_topic_ledger(paths, settings.program).topic(entry["topic_id"])
    assert topic["status"] == "active"
    return paths, db, settings, topic


def _queued_or_leased(db, campaign_id):
    with db.connect() as connection:
        return {str(row["task_id"]): str(row["status"]) for row in connection.execute(
            "SELECT task_id, status FROM tasks WHERE campaign_id=?", (campaign_id,))}


def test_pause_topic_holds_the_campaign_and_resume_restores_it(tmp_path, monkeypatch) -> None:
    paths, db, settings, topic = _active_topic(tmp_path, monkeypatch)
    campaign_id = topic["campaign_id"]
    state_path = Path(db.campaign(campaign_id)["workstream_state_path"])
    # The first research task is in flight: pausing waits for it.
    tasks = _queued_or_leased(db, campaign_id)
    if any(status in {"leased", "running"} for status in tasks.values()):
        with pytest.raises(TopicPauseError, match="running"):
            pause_topic(db, paths, settings, topic_id=topic["topic_id"],
                        reason="polish mode", by="operator")
        with db.connect() as connection:
            connection.execute("UPDATE tasks SET status='queued' WHERE campaign_id=?",
                               (campaign_id,))

    result = pause_topic(db, paths, settings, topic_id=topic["topic_id"],
                         reason="polish mode: no manuscript yet", by="operator")
    assert result["status"] == "paused" and result["cancelled_tasks"]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["status"] == "paused"
    assert state["operator_pause"]["reason"] == "polish mode: no manuscript yet"
    assert db.campaign(campaign_id)["status"] == "production_paused"
    assert campaign_id in paused_topic_campaigns(db)
    assert set(_queued_or_leased(db, campaign_id).values()) == {"cancelled"}
    ledger = open_topic_ledger(paths, settings.program)
    assert ledger.topic(topic["topic_id"])["status"] == "active"
    assert any(item.get("kind") == "topic_operator_paused"
               for item in ledger.topic(topic["topic_id"])["history"])
    # Idempotent; synchronization keeps it paused and schedules no seat.
    again = pause_topic(db, paths, settings, topic_id=topic["topic_id"],
                        reason="polish mode: no manuscript yet", by="operator")
    assert again["status"] == "already_paused"
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == []
    assert db.campaign(campaign_id)["status"] == "production_paused"
    assert not [s for s in _queued_or_leased(db, campaign_id).values()
                if s in {"queued", "leased", "running"}]

    resumed = pause_topic(db, paths, settings, topic_id=topic["topic_id"],
                          reason="polish finished", by="operator", resume=True)
    assert resumed["status"] == "resumed" and resumed["campaign_resumed"] is True
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["status"] == "active" and "operator_pause" not in state
    assert state["operator_pause_history"][-1]["resumed_by"] == "operator"
    assert db.campaign(campaign_id)["status"] == "active"
    assert campaign_id not in paused_topic_campaigns(db)
    with pytest.raises(TopicPauseError, match="nothing to resume"):
        pause_topic(db, paths, settings, topic_id=topic["topic_id"],
                    reason="again", by="operator", resume=True)


def test_pause_topic_refuses_topics_not_in_research(tmp_path, monkeypatch) -> None:
    paths = _paths(tmp_path)
    _install_program(paths)
    db = _db(paths)
    settings = _settings()
    with pytest.raises(TopicPauseError, match="unknown topic"):
        pause_topic(db, paths, settings, topic_id="topic-missing", reason="x", by="operator")
    with pytest.raises(TopicPauseError, match="required"):
        pause_topic(db, paths, settings, topic_id="topic-missing", reason=" ", by="operator")


def test_polish_mode_cancels_queued_scouts_but_not_leased_ones(tmp_path, monkeypatch) -> None:
    paths = _paths(tmp_path)
    _install_program(paths)
    db = _db(paths)
    settings = _settings()
    report = _tick(paths, settings, monkeypatch)
    scout_id = report.program["scouts_scheduled"][0]["task_id"]
    assert db.task(scout_id)["status"] == "leased"
    report = _tick(paths, _polish(settings), monkeypatch)
    assert report.program["polish_mode"]["cancelled"] == []
    assert db.task(scout_id)["status"] == "leased"
    # A scout still waiting in the queue (e.g. behind a quota pause) is withdrawn.
    with db.connect() as connection:
        connection.execute("UPDATE tasks SET status='queued' WHERE task_id=?", (scout_id,))
    report = _tick(paths, _polish(settings), monkeypatch)
    assert report.errors == []
    assert report.program["polish_mode"]["cancelled"] == [scout_id]
    assert db.task(scout_id)["status"] == "cancelled"
    assert db.task(scout_id)["last_error"] == "polish_mode"


def test_operator_freeze_records_the_decision_and_releases_the_topic(tmp_path, monkeypatch) -> None:
    from openlabs.topic_freeze import TopicFreezeError, operator_freeze

    paths, db, settings, topic = _active_topic(tmp_path, monkeypatch)
    campaign_id = topic["campaign_id"]
    record = Path(paths.data) / "papers/p/revisions/FREEZE-20261123.md"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text("contribution insufficient\n", encoding="utf-8")
    common = dict(topic_id=topic["topic_id"], reason_class="contribution_insufficient",
                  by="operator", reason="owner: freeze",
                  reopen_conditions=["new_method=clean-data accuracy well above chance first"])
    with pytest.raises(TopicFreezeError, match="evidence"):
        operator_freeze(db, paths, settings, evidence=[], **common)
    with pytest.raises(TopicFreezeError, match="inside the data repository"):
        operator_freeze(db, paths, settings, evidence=["../x.md"], **common)
    with pytest.raises(TopicFreezeError, match="reason-class"):
        operator_freeze(db, paths, settings, evidence=["papers/p/revisions/FREEZE-20261123.md"],
                        **dict(common, reason_class="bored"))
    if any(status in {"leased", "running"} for status in _queued_or_leased(db, campaign_id).values()):
        with pytest.raises(TopicFreezeError, match="running"):
            operator_freeze(db, paths, settings, evidence=["papers/p/revisions/FREEZE-20261123.md"], **common)
        with db.connect() as connection:
            connection.execute("UPDATE tasks SET status='queued' WHERE campaign_id=?", (campaign_id,))
    result = operator_freeze(db, paths, settings, evidence=["papers/p/revisions/FREEZE-20261123.md"], **common)
    assert result["status"] == "frozen" and result["from_status"] == "active"
    assert result["cancelled_tasks"]
    frozen = open_topic_ledger(paths, settings.program).topic(topic["topic_id"])
    assert frozen["status"] == "frozen" and frozen["freeze_reason_class"] == "contribution_insufficient"
    assert frozen["freeze_evidence"][0]["path"] == "papers/p/revisions/FREEZE-20261123.md"
    assert frozen["reopen_conditions"][0]["type"] == "new_method"
    assert not [s for s in _queued_or_leased(db, campaign_id).values() if s in {"queued", "leased", "running"}]
    again = operator_freeze(db, paths, settings, evidence=["papers/p/revisions/FREEZE-20261123.md"], **common)
    assert again["status"] == "already_frozen"
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == []
    assert open_topic_ledger(paths, settings.program).topic(topic["topic_id"])["status"] == "frozen"


@pytest.mark.parametrize("form", ["operator_hold", "unrecorded"])
def test_pause_topic_records_older_holds_and_resume_dry_run_sees_them(
        tmp_path, monkeypatch, form) -> None:
    """2026-11-24: the 2026-11-19 operator_hold and a bare paused status become regular
    operator_pause records (still paused); --dry-run writes nothing."""
    paths, db, settings, topic = _active_topic(tmp_path, monkeypatch)
    campaign_id = topic["campaign_id"]
    state_path = Path(db.campaign(campaign_id)["workstream_state_path"])
    with db.connect() as connection:
        connection.execute("UPDATE tasks SET status='cancelled' WHERE campaign_id=?",
                           (campaign_id,))
    db.pause_production_campaign(campaign_id, reason="hand hold")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(status="paused", previous_status="active")
    if form == "operator_hold":
        state["operator_hold"] = {"set_at": "2026-11-19T00:59:30Z", "set_by": "operator",
                                  "reason": "astro focus", "resume": "re-submit jobs"}
    state_path.write_text(json.dumps(state), encoding="utf-8")
    original = state_path.read_bytes()

    with pytest.raises(TopicPauseError, match="record it first"):
        pause_topic(db, paths, settings, topic_id=topic["topic_id"], reason="r", by="op",
                    resume=True, dry_run=True)
    preview = pause_topic(db, paths, settings, topic_id=topic["topic_id"],
                          reason="record the 11-19 hold", by="op", dry_run=True)
    assert preview["status"] == "would_record_pause" and preview["dry_run"] is True
    assert state_path.read_bytes() == original

    recorded = pause_topic(db, paths, settings, topic_id=topic["topic_id"],
                           reason="record the 11-19 hold", by="op")
    assert recorded["status"] == "pause_recorded"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    pause = state["operator_pause"]
    assert state["status"] == "paused" and "operator_hold" not in state
    assert pause["recorded_from"] == form and pause["prior_status"] == "active"
    if form == "operator_hold":
        assert pause["at"] == "2026-11-19T00:59:30Z"
        assert pause["operator_hold"]["resume"] == "re-submit jobs"
    assert db.campaign(campaign_id)["status"] == "production_paused"
    assert campaign_id in paused_topic_campaigns(db)
    history = open_topic_ledger(paths, settings.program).topic(topic["topic_id"])["history"]
    assert any(item.get("kind") == "topic_operator_pause_recorded" for item in history)
    assert pause_topic(db, paths, settings, topic_id=topic["topic_id"], reason="r",
                       by="op")["status"] == "already_paused"

    before = state_path.read_bytes()
    dry = pause_topic(db, paths, settings, topic_id=topic["topic_id"], reason="check",
                      by="op", resume=True, dry_run=True)
    assert dry["status"] == "would_resume" and dry["prior_status"] == "active"
    assert dry["resume_note"] == ("re-submit jobs" if form == "operator_hold" else None)
    assert state_path.read_bytes() == before
    assert db.campaign(campaign_id)["status"] == "production_paused"
