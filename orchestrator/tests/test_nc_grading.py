"""NC-aim journal grade before writing (user 2026-11-25, item 3); no re-check at review-ready."""

from __future__ import annotations

from dataclasses import replace

from openlabs import nc_grading, owner, program_autonomy
from openlabs.config import FunnelSettings, OwnerSettings, load_program_settings
from test_owner_mode import _first_seat, _latest, _owner_program, _seat_packet
from test_program_autonomy import _decide, _direction_task, _lease, _retarget_decision, _topic
from test_research_program_flow import _packet, _tick

WRITER = "worker_claude"
READY = {key: {"done": True, "evidence": f"results/{key}.json"}
         for key in nc_grading.READINESS_ITEMS}
VENUES = [{"journal": "Nature Communications", "cas_2025_zone": 1},
          {"journal": "Applied Energy", "cas_2025_zone": 1},
          {"journal": "Energy", "cas_2025_zone": 2}]
REGISTRY = """\
venues:
- journal: Nature Communications
  aliases: [NC]
  article_types:
    Article:
      max_body_words: 5000
      max_abstract_words: 200
      max_title_words: 15
      max_display_items: 10
      source: https://www.nature.com/ncomms/submit/article
"""


def _retarget(band, journal, *, met=("generality", "counterintuitive"), match="nc",
              confidence="high", **extra) -> dict:
    return {"venue_or_format": journal, "why_fits": "scope", "achieved_band": band,
            "nc_scorecard": {key: {"met": key in met, "evidence": "e" if key in met else ""}
                             for key in nc_grading.THRESHOLDS},
            "calibration_match": match, "calibration_neighbours": ["N6"],
            "confidence": confidence, **extra}


def _nc_program(tmp_path, monkeypatch, *, writer=WRITER, **funnel):
    owner_settings = OwnerSettings(runners=("worker_gpt",), writing_runner=writer)
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch,
                                                   owner_settings=owner_settings)
    settings = replace(settings, program=replace(settings.program,
                                                 funnel=FunnelSettings(**funnel)))
    monkeypatch.setattr(nc_grading, "admitted_stage", lambda _topic: "nc_aim")
    registry = paths.data / "registry"
    registry.mkdir(parents=True, exist_ok=True)
    (paths.data / nc_grading.CALIBRATION_PATH).write_text("papers: []\n", encoding="utf-8")
    (registry / "verified-venues.yaml").write_text(REGISTRY, encoding="utf-8")
    original = program_autonomy._run_paper_command

    def paper_command(*args, **kwargs):
        if args[2] == ["venue", "alternatives"]:
            return {"venues": VENUES}
        return original(*args, **kwargs)

    monkeypatch.setattr(program_autonomy, "_run_paper_command", paper_command)
    return paths, db, settings, topic


def _declare(paths, db, settings, monkeypatch, seat, packet):
    _seat_packet(db, paths, seat["task_id"], packet, artifact=True)
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    return report


def test_config_keys_parse() -> None:
    funnel = load_program_settings({"funnel": {"grade_before_writing": False,
                                               "readiness_returns": 0}}).funnel
    assert funnel.grade_before_writing is False and funnel.readiness_returns == 0
    default = load_program_settings({}).funnel
    assert default.grade_before_writing is True and default.readiness_returns == 2


def test_research_done_without_the_required_checks_goes_back_to_the_owner(
        tmp_path, monkeypatch) -> None:
    paths, db, settings, topic = _nc_program(tmp_path, monkeypatch, readiness_returns=1)
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    partial = {k: v for k, v in READY.items() if k != "external_validation"}
    _declare(paths, db, settings, monkeypatch, seat,
             {"status": "continuing", "phase": "writing", "nc_readiness": partial})
    back = _latest(db, topic["campaign_id"])
    assert back["routing_reason"] == nc_grading.ROUTING_READINESS
    assert back["runner"] == "worker_gpt" and "external validation" in back["objective"]
    assert owner.writing_state(db, topic["campaign_id"]) == {}
    # Still missing after the allowed return: the grade is taken, the gap is a reason.
    again = _lease(paths, settings, monkeypatch, db, back["task_id"])
    _declare(paths, db, settings, monkeypatch, again,
             {"status": "continuing", "phase": "writing", "nc_readiness": partial})
    task = _direction_task(db)
    packet = _packet(task)
    assert packet["trigger"]["reason"] == nc_grading.TRIGGER_PRE_WRITING
    assert packet["trigger"]["detail"]["missing"] == ["external_validation"]
    assert any("external validation" in reason for reason in packet["reasons_to_answer"])
    assert program_autonomy.campaign_on_hold(db, settings, topic["campaign_id"])


def test_grade_before_writing_then_the_writer_writes_for_that_journal(
        tmp_path, monkeypatch) -> None:
    paths, db, settings, topic = _nc_program(tmp_path, monkeypatch)
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _declare(paths, db, settings, monkeypatch, seat,
             {"status": "continuing", "phase": "writing", "nc_readiness": READY})
    # Held: no writer seat while the grade is pending.
    assert _latest(db, topic["campaign_id"])["task_id"] == seat["task_id"]
    assert owner.writing_state(db, topic["campaign_id"]) == {}
    task = _direction_task(db)
    packet = _packet(task)
    assert packet["grading"]["point"] == "pre_writing"
    assert "venue-calibration" in {item["label"] for item in packet["read_resources"]}
    assert "BEFORE writing" in task["objective"] and "research looks like" in task["objective"]
    assert task["exclude_provider"]  # cross-family: not the research executor's family
    # A medium-confidence NC grade breaks the rule: retried, nothing recorded.
    decision = _retarget_decision(packet["reasons_to_answer"][0], "Nature Communications")
    decision["retarget"] = _retarget("nc", "Nature Communications", confidence="medium")
    report = _decide(paths, settings, monkeypatch, db, decision)
    assert "invalid" in [d["outcome"] for d in report.program["direction_decisions"]]
    assert not _topic(paths, settings, topic["topic_id"]).get("venue_grade")
    retry = _packet(_direction_task(db))
    decision["retarget"] = _retarget("nc", "Nature Communications")
    decision["answers_reason"] = retry["reasons_to_answer"][0]
    report = _decide(paths, settings, monkeypatch, db, decision)
    assert report.errors == [], report.errors
    outcomes = [d["outcome"] for d in report.program["direction_decisions"]]
    assert "venue_graded_before_writing" in outcomes
    grade = _topic(paths, settings, topic["topic_id"])["venue_grade"]
    assert grade["point"] == "pre_writing" and grade["achieved_band"] == "nc"
    assert grade["format"]["max_abstract_words"] == 200
    writer = _latest(db, topic["campaign_id"])
    assert writer["runner"] == WRITER and writer["routing_reason"] == owner.ROUTING_WRITING
    assert "Nature Communications" in writer["objective"]
    assert "abstract <= 200 words" in writer["objective"]
    assert owner.writing_state(db, topic["campaign_id"])["status"] == owner.WRITING_ACTIVE
    # The writer's own ready_for_review is not graded again before review.
    state = owner.owner_state(db, topic["campaign_id"])
    assert not nc_grading.pre_writing_due(
        settings, _topic(paths, settings, topic["topic_id"]), state,
        {"status": "ready_for_review"}, successful=True)


def test_owner_who_writes_gets_the_graded_journal_in_its_next_seat(tmp_path, monkeypatch) -> None:
    paths, db, settings, topic = _nc_program(tmp_path, monkeypatch, writer=None)
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _declare(paths, db, settings, monkeypatch, seat,
             {"status": "continuing", "phase": "writing", "nc_readiness": READY})
    packet = _packet(_direction_task(db))
    decision = _retarget_decision(packet["reasons_to_answer"][0], "Energy")
    decision["retarget"] = _retarget("zone_2", "Energy", match="zone_2", confidence="medium")
    _decide(paths, settings, monkeypatch, db, decision)
    nxt = _latest(db, topic["campaign_id"])
    assert nxt["routing_reason"] == nc_grading.ROUTING_GRADED and nxt["runner"] == "worker_gpt"
    assert "Energy (band zone_2" in nxt["objective"]
    assert _topic(paths, settings, topic["topic_id"])["venue_grade"]["journal"] == "Energy"


def test_switch_off_and_non_nc_topics_keep_the_old_hand_over(tmp_path, monkeypatch) -> None:
    paths, db, settings, topic = _nc_program(tmp_path, monkeypatch, grade_before_writing=False)
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _declare(paths, db, settings, monkeypatch, seat,
             {"status": "continuing", "phase": "writing"})
    assert _latest(db, topic["campaign_id"])["runner"] == WRITER
    monkeypatch.setattr(nc_grading, "admitted_stage", lambda _topic: "tier2_aim")
    assert not nc_grading.enabled(replace(settings, program=replace(
        settings.program, funnel=FunnelSettings())), topic)


def test_unavailable_grade_lets_writing_go_on(tmp_path, monkeypatch) -> None:
    paths, db, settings, topic = _nc_program(tmp_path, monkeypatch)
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _declare(paths, db, settings, monkeypatch, seat,
             {"status": "continuing", "phase": "writing", "nc_readiness": READY})
    for _ in range(program_autonomy.MAX_DECISION_ATTEMPTS):
        packet = _packet(_direction_task(db))
        bad = _retarget_decision(packet["reasons_to_answer"][0], "Not A Journal")
        _decide(paths, settings, monkeypatch, db, bad)
    current = _topic(paths, settings, topic["topic_id"])
    assert current["status"] != "frozen" and not current.get("venue_grade")
    assert owner.owner_state(db, topic["campaign_id"])["nc_pre_writing"]["status"] == "ungraded"
    assert _latest(db, topic["campaign_id"])["runner"] == WRITER


# --------------------------------------------------------------------------- re-check


PRIOR = {"journal": "Nature Communications", "achieved_band": "nc", "point": "pre_writing",
         "confidence": "high", "nc_scorecard": {"generality": {"met": True}},
         "met_thresholds": ["generality", "counterintuitive"], "calibration_match": "nc"}


def test_review_ready_after_a_pre_writing_grade_goes_straight_to_the_queue(tmp_path, monkeypatch):
    paths, db, settings, topic = _nc_program(tmp_path, monkeypatch)
    from openlabs.program import record_topic_note

    record_topic_note(program_autonomy._ledger(paths, settings), topic["topic_id"], db=db,
                      event_type="venue_grade_decided", reason="nc", decided_by="test",
                      updates={"venue_grade": dict(PRIOR)})
    current = _topic(paths, settings, topic["topic_id"])
    from openlabs.engine import TickReport
    from test_program_autonomy import _direction_tasks

    report = TickReport()
    program_autonomy.queue_ready_topic(
        db, paths, settings, report, topic=current, task={"task_id": "review-1"},
        outcome={"paper_id": "p1", "target_journal": "Nature Communications"},
        payload={}, evidence=[])
    assert _direction_tasks(db) == []  # no grade re-check (pipeline slimming 2026-11-26)
    assert _topic(paths, settings, topic["topic_id"])["status"] == "ready_queue"


def test_a_grade_rechecked_before_the_slimming_also_goes_straight_to_the_queue(tmp_path,
                                                                                 monkeypatch):
    paths, db, settings, topic = _nc_program(tmp_path, monkeypatch)
    from openlabs.engine import TickReport
    from openlabs.program import record_topic_note
    from test_program_autonomy import _direction_tasks

    rechecked = {**PRIOR, "point": "recheck", "rechecked_for": "owner-review:old"}
    record_topic_note(program_autonomy._ledger(paths, settings), topic["topic_id"], db=db,
                      event_type="venue_grade_decided", reason="nc", decided_by="test",
                      updates={"venue_grade": rechecked})
    program_autonomy.queue_ready_topic(
        db, paths, settings, TickReport(), topic=_topic(paths, settings, topic["topic_id"]),
        task={"task_id": "review-2"}, payload={}, evidence=[],
        outcome={"paper_id": "p1", "target_journal": "Some Other Journal"})
    assert _direction_tasks(db) == []
    assert _topic(paths, settings, topic["topic_id"])["status"] == "ready_queue"


def test_the_reviewed_journal_is_read_from_a_decision_record_in_the_campaign_draft(
        tmp_path, monkeypatch):
    import json
    from pathlib import Path

    # NC trial 2026-11-26: the unified review of a paper written in the campaign wrote its
    # decision under the campaign draft root; read only under DATA, the journal was None and
    # a grade of the reviewed journal looked like a different one.
    paths, db, settings, topic = _nc_program(tmp_path, monkeypatch)
    from openlabs.engine import TickReport
    from openlabs.program import record_topic_note
    from test_program_autonomy import _direction_tasks

    graded = {**PRIOR, "point": "after_review"}
    record_topic_note(program_autonomy._ledger(paths, settings), topic["topic_id"], db=db,
                      event_type="venue_grade_decided", reason="nc", decided_by="test",
                      updates={"venue_grade": graded})
    current = _topic(paths, settings, topic["topic_id"])
    draft = Path(db.campaign(current["campaign_id"])["state_path"])
    record = draft / "reviews" / "unified" / "p1" / "run" / "decision.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps({"target_journal": PRIOR["journal"]}))
    program_autonomy.queue_ready_topic(
        db, paths, settings, TickReport(), topic=current, task={"task_id": "review-1"},
        outcome={"paper_id": "p1", "decision_record": "reviews/unified/p1/run/decision.json"},
        payload={}, evidence=[])
    assert _direction_tasks(db) == []
    assert _topic(paths, settings, topic["topic_id"])["status"] == "ready_queue"
