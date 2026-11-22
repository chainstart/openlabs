"""Owner to minor revision (2026-11-16): recompute review loop, fresh sessions, card
prechecks and the compute floor, per-attempt token increments and topic economics."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import test_research_lines as lines_tests
import test_research_program_flow as flow
from openlabs import card_precheck, owner, usage
from openlabs.config import (
    OWNER_TASK_TYPE,
    FactorySettings,
    ModelPrice,
    OwnerSettings,
    ReportingSettings,
    load_program_settings,
    load_reporting_settings,
)
from openlabs.program import open_topic_ledger
from openlabs.projects import load_project
from test_owner_mode import _first_seat, _latest, _owner_program, _seat_packet
from test_program_autonomy import _direction_tasks, _finish, _lease, _outcome, _topic
from test_research_program_flow import RUNNERS, _tick

PAPER = "20261116-ai-owner-recompute"


def _ready(db, paths, seat, *, session="s1", risk="disputed_data"):
    return _seat_packet(db, paths, seat["task_id"], {
        "status": "ready_for_review", "paper_id": PAPER, "primary_endpoint_verdict": "met",
        "phase": "writing", "recompute_risk": risk}, session=session, artifact=True)


def _verdict(verdict: str, **extra) -> dict:
    return {"recompute_review": {
        "verdict": verdict, "required": extra.get("required", []),
        "optional": ["Shorten the abstract."], "unverified": [],
        "checks": [{"item": "key numbers", "outcome": "reproduced", "detail": "q 0.142"}],
        "scripts": ["/tmp/recompute/q.py"], "summary": f"Verdict {verdict}."}}


def _review_of(db, campaign_id: str) -> dict:
    task = _latest(db, campaign_id)
    assert task["task_type"] == "paper_review", task
    return task


# --------------------------------------------------------------------------- the loop


def test_major_then_minor_then_unified_then_ready(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    campaign_id = topic["campaign_id"]
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _ready(db, paths, seat)
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    review = _review_of(db, campaign_id)
    assert review["routing_reason"] == owner.ROUTING_RECOMPUTE
    assert review["skill_path"] == owner.RECOMPUTE_SKILL
    assert review["session_mode"] == "fresh" and review["parent_task_id"] == seat["task_id"]
    assert "unified-run" in review["objective"] and "round 1 of 3" in review["objective"]
    packet = json.loads(Path(review["input_path"]).read_text(encoding="utf-8"))
    assert packet["schema_version"] == owner.RECOMPUTE_PACKET_SCHEMA
    assert packet["round"] == 1 and packet["previous_rounds"] == []
    assert packet["checklist"]["source"] == "generic"
    assert packet["paper_id"] == PAPER
    # The recompute review does not move the topic to in_review (the unified review does).
    assert _topic(paths, settings, topic["topic_id"])["status"] == "active"
    assert owner.topic_phase(db, campaign_id) == "recompute_review_1"
    review = _lease(paths, settings, monkeypatch, db, review["task_id"])
    # Independent: another model family than the owner.
    assert RUNNERS[review["runner"]].provider != RUNNERS[seat["runner"]].provider
    _finish(db, paths, review["task_id"], supported=False, extra=_verdict(
        "major", required=["BJD_TDB of sector 95 is 41 s off; recompute the O-C."]))
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    back = _latest(db, campaign_id)
    assert back["task_type"] == OWNER_TASK_TYPE
    assert back["routing_reason"] == owner.ROUTING_RECOMPUTED
    assert "major revision" in back["objective"] and "41 s off" in back["objective"]
    assert "round 2" in back["objective"]
    # Default: a fresh session that starts from the handover, same owner runner.
    assert back["session_mode"] == "fresh" and back["runner"] == seat["runner"]
    state = owner.owner_state(db, campaign_id)
    assert state["review_round"] == 1 and state["review_stage"] == owner.STAGE_MAJOR
    assert owner.topic_phase(db, campaign_id) == "revision_after_round_1"

    # The owner answers the items and returns the manuscript: round 2, fresh reviewer.
    root = Path(db.campaign(campaign_id)["state_path"])
    (root / owner.RESPONSE_NAME).write_text("1. O-C recomputed with own BJD_TDB.\n")
    back = _lease(paths, settings, monkeypatch, db, back["task_id"])
    _seat_packet(db, paths, back["task_id"], {
        "status": "ready_for_review", "paper_id": PAPER, "primary_endpoint_verdict": "met",
        "response": "All required items addressed."}, session="s2", artifact=True)
    _tick(paths, settings, monkeypatch)
    second = _review_of(db, campaign_id)
    assert second["routing_reason"] == owner.ROUTING_RECOMPUTE and second["task_id"] != review[
        "task_id"]
    packet = json.loads(Path(second["input_path"]).read_text(encoding="utf-8"))
    assert packet["round"] == 2
    (previous,) = packet["previous_rounds"]
    assert previous["verdict"] == "major" and "41 s off" in previous["required"][0]
    assert previous["owner_response"]["path"].endswith(owner.RESPONSE_NAME)
    assert previous["owner_response"]["note"] == "All required items addressed."
    second = _lease(paths, settings, monkeypatch, db, second["task_id"])
    _finish(db, paths, second["task_id"], supported=False, extra=_verdict(
        "minor", required=["Table 2 rounds q to two digits; use three."]))
    _tick(paths, settings, monkeypatch)
    minor = _latest(db, campaign_id)
    assert minor["task_type"] == OWNER_TASK_TYPE and "minor" in minor["objective"]
    assert "consistency" in minor["objective"]
    assert owner.topic_phase(db, campaign_id) == "minor_revision"

    # After the minor changes the manuscript goes to the unified review, not a 3rd round.
    minor = _lease(paths, settings, monkeypatch, db, minor["task_id"])
    _ready(db, paths, minor, session="s3", risk=None)
    _tick(paths, settings, monkeypatch)
    unified = _review_of(db, campaign_id)
    assert unified["routing_reason"] == owner.ROUTING_REVIEW
    assert "unified-run" in unified["objective"]
    assert "already recomputed" in unified["objective"]
    assert "Do not repeat that recomputation" in unified["objective"]
    assert _topic(paths, settings, topic["topic_id"])["status"] == "in_review"
    assert owner.topic_phase(db, campaign_id) == "unified_review"
    unified = _lease(paths, settings, monkeypatch, db, unified["task_id"])
    _finish(db, paths, unified["task_id"], extra={
        "paper_candidate": True, "review_outcome": _outcome(status="ready")})
    _tick(paths, settings, monkeypatch)
    ready = _topic(paths, settings, topic["topic_id"])
    assert ready["status"] == "ready_queue"
    assert owner.topic_phase(db, campaign_id, topic=ready) == "awaiting_confirmation"


def test_accept_goes_straight_to_the_unified_review(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _ready(db, paths, seat)
    _tick(paths, settings, monkeypatch)
    review = _lease(paths, settings, monkeypatch, db, _review_of(db, topic["campaign_id"])[
        "task_id"])
    _finish(db, paths, review["task_id"], supported=False, extra=_verdict("accept"))
    _tick(paths, settings, monkeypatch)
    unified = _review_of(db, topic["campaign_id"])
    assert unified["routing_reason"] == owner.ROUTING_REVIEW
    assert unified["parent_task_id"] == seat["task_id"]  # independence from the owner
    assert PAPER in unified["objective"]


def test_major_in_the_last_round_goes_to_a_direction_decision(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _owner_program(
        tmp_path, monkeypatch, owner_settings=OwnerSettings(review_max_rounds=1))
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _ready(db, paths, seat)
    _tick(paths, settings, monkeypatch)
    review = _lease(paths, settings, monkeypatch, db, _review_of(db, topic["campaign_id"])[
        "task_id"])
    _finish(db, paths, review["task_id"], supported=False, extra=_verdict(
        "major", required=["The q interval is set by the l3 prior."]))
    _tick(paths, settings, monkeypatch)
    (decision,) = _direction_tasks(db)
    packet = json.loads(Path(decision["input_path"]).read_text(encoding="utf-8"))
    assert packet["trigger"]["reason"] == owner.TRIGGER_REVIEW_ROUNDS
    assert packet["trigger"]["detail"]["round"] == 1
    assert "round 1 of 1" in packet["reasons_to_answer"][0]
    # No owner seat while the decision is pending.
    assert _latest(db, topic["campaign_id"])["task_id"] == review["task_id"]
    assert owner.topic_phase(db, topic["campaign_id"]) == "direction_decision"


def test_reject_goes_to_a_direction_decision_and_a_kept_topic_starts_over(
    tmp_path, monkeypatch
):
    from test_program_autonomy import _analysis_decision, _decide

    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _ready(db, paths, seat)
    _tick(paths, settings, monkeypatch)
    review = _lease(paths, settings, monkeypatch, db, _review_of(db, topic["campaign_id"])[
        "task_id"])
    _finish(db, paths, review["task_id"], supported=False, extra=_verdict("reject"))
    _tick(paths, settings, monkeypatch)
    (decision,) = _direction_tasks(db)
    packet = json.loads(Path(decision["input_path"]).read_text(encoding="utf-8"))
    assert packet["trigger"]["reason"] == owner.TRIGGER_REVIEW_REJECTED
    report = _decide(paths, settings, monkeypatch, db,
                     _analysis_decision(packet["reasons_to_answer"][0]))
    executed = db.task(report.program["direction_decisions"][-1]["executed_task_id"])
    assert executed["task_type"] == OWNER_TASK_TYPE
    state = owner.owner_state(db, topic["campaign_id"])
    assert state["review_round"] == 0 and state["review_cycle"] == 1
    assert [item["verdict"] for item in state["review_history"]] == ["reject"]


def test_an_unusable_verdict_is_re_reviewed_once_then_returns_to_the_owner(
    tmp_path, monkeypatch
):
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _ready(db, paths, seat)
    _tick(paths, settings, monkeypatch)
    first = _lease(paths, settings, monkeypatch, db, _review_of(db, topic["campaign_id"])[
        "task_id"])
    _finish(db, paths, first["task_id"], supported=False,
            extra={"recompute_review": {"verdict": "looks fine"}})
    _tick(paths, settings, monkeypatch)
    retry = _review_of(db, topic["campaign_id"])
    assert retry["task_id"] != first["task_id"] and retry["routing_reason"] == (
        owner.ROUTING_RECOMPUTE)
    assert json.loads(Path(retry["input_path"]).read_text())["round"] == 1
    retry = _lease(paths, settings, monkeypatch, db, retry["task_id"])
    _finish(db, paths, retry["task_id"], supported=False, extra={})
    _tick(paths, settings, monkeypatch)
    back = _latest(db, topic["campaign_id"])
    assert back["task_type"] == OWNER_TASK_TYPE and "without a usable verdict" in back[
        "objective"]
    assert owner.owner_state(db, topic["campaign_id"]).get("review_round", 0) == 0


def test_recompute_off_keeps_the_unified_review_only(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _owner_program(
        tmp_path, monkeypatch, owner_settings=OwnerSettings(recompute_review=False))
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _ready(db, paths, seat)
    _tick(paths, settings, monkeypatch)
    assert _review_of(db, topic["campaign_id"])["routing_reason"] == owner.ROUTING_REVIEW


def test_recompute_block_and_line_checklist(tmp_path) -> None:
    assert owner.recompute_block({"recompute_review": {"verdict": "Minor_Revision"}})[
        "verdict"] == "minor"
    assert owner.recompute_block({"recompute_review": {"verdict": "fine"}}) is None
    assert owner.recompute_block({}) is None
    paths = flow._paths(tmp_path)
    sop = paths.data / "registry" / "sop.md"
    sop.parent.mkdir(parents=True, exist_ok=True)
    sop.write_text("# SOP\n## 8. Package\n### 8.3 Floor\nx\n### 8.4 Recompute list\n1. **Time**"
                   ": run tess_time.\n2. ephemeris\n## 9. Next\nnot this\n", encoding="utf-8")
    (paths.data / "registry" / "research-lines.yaml").write_text(
        "schema_version: openlabs.research_lines.v1\nlines:\n  - id: astro\n    host_domain: "
        "physics\n    title: t\n    review_checklist:\n      path: registry/sop.md\n"
        "      section: '8.4'\n  - id: listed\n    host_domain: ai\n    title: t\n"
        "    review_checklist: [recompute q, check BJD]\n", encoding="utf-8")
    settings = FactorySettings(program=load_program_settings({"enabled": True}))
    section = owner.recompute_checklist(paths, settings, "astro")
    assert "tess_time" in section["text"] and "not this" not in section["text"]
    assert "8.3" not in section["text"] and section["reference"].endswith("section 8.4")
    assert owner.recompute_checklist(paths, settings, "listed")["items"] == [
        "recompute q", "check BJD"]
    assert owner.recompute_checklist(paths, settings, "other")["source"] == "generic"
    assert owner.recompute_checklist(paths, settings, None)["source"] == "generic"


# --------------------------------------------------------------------------- sessions


def test_default_successor_seat_is_a_fresh_session_with_the_owners_handover(
    tmp_path, monkeypatch
):
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    campaign_id = topic["campaign_id"]
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _seat_packet(db, paths, seat["task_id"], {"status": "continuing", "phase": "solving"},
                 session="s1", artifact=True)
    root = Path(db.campaign(campaign_id)["state_path"])
    (root / owner.HANDOVER_NAME).write_text("State: two sectors fitted; next: profile S95.\n")
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    nxt = _latest(db, campaign_id)
    assert nxt["task_type"] == OWNER_TASK_TYPE and nxt["session_mode"] == "fresh"
    assert nxt["agent_session_id"] is None and nxt["runner"] == seat["runner"]
    seats = report.program["owner_seats"]
    assert seats[-1]["session_reason"].startswith("session_max_seats")
    state = owner.owner_state(db, campaign_id)
    assert state["handover"]["present"] and not state["handover"]["over_limit"]
    assert state["phase"] == "solving" and owner.topic_phase(db, campaign_id) == "solving"
    from test_owner_mode import _spec

    block = owner.spec_block(paths, settings, task=nxt, spec=_spec(tmp_path, nxt["task_id"]),
                             campaign=db.campaign(campaign_id), wall_seconds=600, db=db)
    assert block["fresh"] and "profile S95" in block["request"]
    assert "## Hard limits" in block["request"]  # a fresh session gets the whole brief


def test_handover_is_cut_to_its_limit_and_a_missing_one_is_named(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _owner_program(
        tmp_path, monkeypatch, owner_settings=OwnerSettings(handover_max_bytes=64))
    campaign = db.campaign(topic["campaign_id"])
    text = owner.handover_text(db, settings, campaign)
    assert f"left no {owner.HANDOVER_NAME}" in text
    root = Path(campaign["state_path"])
    (root / owner.HANDOVER_NAME).write_text("x" * 60 + "TAIL" * 40)
    text = owner.handover_text(db, settings, campaign)
    assert "cut at 64 bytes of 220" in text and "TAILTAIL" not in text


def test_a_session_is_resumed_until_its_token_threshold(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _owner_program(
        tmp_path, monkeypatch,
        owner_settings=OwnerSettings(session_max_seats=0, session_max_tokens_read=1_000_000))
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    assert owner.keep_session(db, settings, dict(seat, agent_session_id=None)) == (
        False, "no_session")
    _seat_packet(db, paths, seat["task_id"], {"status": "continuing"}, session="s1",
                 artifact=True)
    _tick(paths, settings, monkeypatch)
    nxt = _latest(db, topic["campaign_id"])
    assert nxt["session_mode"] == "resume"  # no tokens recorded yet
    finished = db.task(seat["task_id"])
    with db.connect() as connection:
        connection.execute(
            "UPDATE task_attempts SET runtime_json=? WHERE task_id=?",
            (json.dumps({"adapter": "claude", "session_id": "s1", "input_tokens": 10,
                         "cached_input_tokens": 1_200_000}), seat["task_id"]))
    keep, reason = owner.keep_session(db, settings, finished)
    assert not keep and reason.startswith("session_max_tokens_read")


# --------------------------------------------------------------------------- card intake


def _intake(tmp_path, monkeypatch, line_yaml_extra: str, card: dict | None = None, **program):
    paths, db, settings = lines_tests._line_setup(tmp_path, "ready")
    path = paths.data / "registry" / "research-lines.yaml"
    path.write_text(path.read_text(encoding="utf-8") + line_yaml_extra, encoding="utf-8")
    if program:
        from dataclasses import replace

        settings = replace(settings, program=replace(settings.program, **program))
    from openlabs.program_flow import intake_card

    project = load_project(paths.data / "workspaces" / "ai" / "projects" / "research-program"
                           / "project.json")
    receipt = paths.data / "receipts" / "data-access.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_bytes(flow.RECEIPT)
    outcome = intake_card(db, paths, settings, project, card or _queued_card(),
                          decided_by="manual:t", provider="human", source_task_id=None,
                          receipt_digests=None)
    topic = open_topic_ledger(paths, settings.program).topic(outcome["topic_id"])
    return paths, db, settings, outcome, topic


def _queued_card(n: int = 0, template: str = "contact-binary-solution",
                 entry: str = "TIC441806604") -> dict:
    return lines_tests._line_card(
        n, paper_template=template,
        occupancy_search={"queries": ["SIMBAD TIC"], "databases": ["SIMBAD"],
                          "searched_at": "2026-11-13", "findings": "none"},
        candidate_queue_entry={"entry_id": entry, "queue": "/q/queue.json"})


def _script(tmp_path, body: str) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    script = tmp_path / "admission_precheck.py"
    script.write_text(body, encoding="utf-8")
    return script


def _precheck_yaml(script: Path, extra: str = "") -> str:
    """The astro line's draft schema (research-lines.yaml, 2026-11-16), one template."""

    return ("    admission_precheck:\n"
            "      schema: draft-2026-11-16\n"
            "      model_calls: none\n"
            "      network: none\n"
            "      per_template:\n"
            "        contact-binary-solution:\n"
            f"          command: {sys.executable} {script} {{entry_id}} --json\n"
            "          pass_condition: exit code 0 and JSON verdict == \"pass\"\n"
            "          hard_checks: [data availability]\n"
            "          typical_seconds: 0.1-1\n" + extra)


FAIL_SCRIPT = (
    "import json, sys\nentry = sys.argv[1]\nassert sys.argv[2] == '--json'\n"
    "print(json.dumps({'entry_id': entry, 'verdict': 'fail', 'failed': ['totality'], "
    "'checks': [{'name': 'totality', 'pass': False, 'hard': True, 'value': 0.3, "
    "'rule': 'R_max >= 0.42'}, {'name': 'brightness', 'pass': True, 'hard': True}]}))\n"
    "sys.exit(1)\n")
PASS_SCRIPT = (
    "import json, os, sys\nassert os.environ['OPENLABS_QUEUE_ENTRY_ID'] == sys.argv[1]\n"
    "print('checking', sys.argv[1])\n"
    "print(json.dumps({'entry_id': sys.argv[1], 'verdict': 'pass', 'failed': [], "
    "'warnings': ['product list not cached'], 'checks': []}, indent=1))\n")


def test_a_failed_line_precheck_keeps_the_card_from_admission(tmp_path, monkeypatch):
    script = _script(tmp_path, FAIL_SCRIPT)
    paths, db, settings, outcome, topic = _intake(tmp_path, monkeypatch, _precheck_yaml(script))
    assert outcome["status"] == "rejected" and outcome["reason"] == "card_precheck_failed"
    assert outcome["precheck"] == "fail"
    assert topic["status"] == "rejected"
    assert topic["history"][-1]["reason"] == "card_precheck_failed"
    assert "totality" in topic["card_errors"][0] and "R_max >= 0.42" in topic["card_errors"][0]
    assert "brightness" not in topic["card_errors"][0]
    assert topic["card_repair"]["status"] == "not_repairable"
    precheck = topic["card_check"]["precheck"]
    assert precheck["status"] == "fail" and precheck["entry_id"] == "TIC441806604"
    assert precheck["command"][-2:] == ["TIC441806604", "--json"]
    from openlabs.program_flow import precheck_statistics

    stats = precheck_statistics(open_topic_ledger(paths, settings.program).read())
    assert stats == {lines_tests.LINE: {"rejected": 1, "waiting_on_error": 0}}


def test_a_passed_precheck_travels_with_the_card_to_admission(tmp_path, monkeypatch):
    script = _script(tmp_path, PASS_SCRIPT)
    paths, db, settings, outcome, topic = _intake(tmp_path, monkeypatch, _precheck_yaml(script))
    assert outcome["status"] == "proposed", outcome
    precheck = topic["card_check"]["precheck"]
    assert precheck["status"] == "pass" and precheck["warnings"] == ["product list not cached"]
    assert Path(precheck["output_path"]).is_file()


def test_templates_without_a_declared_precheck_and_cards_without_an_entry(tmp_path, monkeypatch):
    script = _script(tmp_path, PASS_SCRIPT)
    # Another template of the line declares no precheck: nothing runs.
    *_, outcome, topic = _intake(tmp_path / "a", monkeypatch, _precheck_yaml(script),
                                 card=_queued_card(template="nn-catalogue-audit"))
    assert outcome["status"] == "proposed" and "precheck" not in (topic.get("card_check") or {})
    # A card of the template without its queue entry cannot be checked: a card defect.
    card = _queued_card()
    card.pop("candidate_queue_entry")
    *_, outcome, topic = _intake(tmp_path / "b", monkeypatch, _precheck_yaml(script), card=card)
    assert outcome["reason"] == "card_precheck_failed"
    assert "candidate_queue_entry" in topic["card_errors"][0]
    # The instance switch turns prechecks off.
    *_, outcome, topic = _intake(tmp_path / "c", monkeypatch, _precheck_yaml(script),
                                 card_precheck=False)
    assert outcome["status"] == "proposed" and "precheck" not in (topic.get("card_check") or {})


def test_an_erring_precheck_holds_the_card_reports_it_and_is_retried(tmp_path, monkeypatch):
    from openlabs import engine
    from openlabs.program_flow import retry_held_prechecks, schedule_topic_admission

    flag = tmp_path / "mode.txt"
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("broken")
    script = _script(tmp_path, (
        "import json, sys\nmode = open(%r).read()\n"
        "if mode == 'broken':\n    print('Traceback: cache missing')\n    sys.exit(1)\n"
        "if mode == 'slow':\n    import time; time.sleep(5)\n"
        "print(json.dumps({'verdict': mode}))\nsys.exit(0 if mode == 'pass' else 1)\n"
    ) % str(flag))
    paths, db, settings, outcome, topic = _intake(
        tmp_path, monkeypatch, _precheck_yaml(script, "          timeout_seconds: 2\n"))
    # Not JSON: an infrastructure error, neither a pass nor a fail.
    assert outcome["status"] == "proposed" and outcome["precheck"] == "error"
    assert "not a JSON object" in outcome["precheck_error"]
    engine._sync_active_projects(db, paths, settings, engine.TickReport())
    with db.connect() as connection:
        admission_campaign = dict(connection.execute(
            "SELECT * FROM campaigns WHERE campaign_id LIKE '%admission%' LIMIT 1").fetchone())
    schedule = schedule_topic_admission(db, paths, settings, admission_campaign, epoch=1)
    assert schedule.task_id is None and schedule.reason == "admission_precheck_error"
    report = engine.TickReport()
    flag.write_text("slow")
    (retried,) = retry_held_prechecks(db, paths, settings, report)
    assert retried["status"] == "error" and retried["attempts"] == 2
    assert any("timed out" in error and topic["topic_id"] in error for error in report.errors)
    flag.write_text("pass")
    (retried,) = retry_held_prechecks(db, paths, settings, engine.TickReport())
    assert retried["status"] == "pass"
    held = open_topic_ledger(paths, settings.program).topic(topic["topic_id"])
    assert held["status"] == "proposed" and held["card_check"]["precheck"]["attempts"] == 3
    schedule = schedule_topic_admission(db, paths, settings, admission_campaign, epoch=1)
    assert schedule.task_id is not None
    assert retry_held_prechecks(db, paths, settings, engine.TickReport()) == []


def test_a_retried_precheck_that_fails_rejects_the_card(tmp_path, monkeypatch):
    from openlabs import engine
    from openlabs.program_flow import retry_held_prechecks

    flag = tmp_path / "mode.txt"
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("broken")
    script = _script(tmp_path, (
        "import json, sys\nif open(%r).read() == 'broken':\n    sys.exit(7)\n"
        "print(json.dumps({'verdict': 'not_found'}))\nsys.exit(2)\n") % str(flag))
    paths, db, settings, outcome, topic = _intake(tmp_path, monkeypatch, _precheck_yaml(script))
    assert outcome["precheck"] == "error"
    flag.write_text("ok")
    (retried,) = retry_held_prechecks(db, paths, settings, engine.TickReport())
    assert retried["status"] == "fail"
    rejected = open_topic_ledger(paths, settings.program).topic(topic["topic_id"])
    assert rejected["status"] == "rejected"
    assert rejected["history"][-1]["reason"] == "card_precheck_failed"


def test_the_real_astro_entry_parses_into_a_command(tmp_path) -> None:
    data = Path("/workspace/openlabs/openlabs-data/registry/research-lines.yaml")
    if not data.is_file():
        return
    from openlabs.research_lines import line_entry, load_research_lines

    entry = line_entry(load_research_lines(data), "astro-survey-photometry") or {}
    if not isinstance(entry.get("admission_precheck"), dict):
        return  # the data repository has not got the field (yet)
    for template in ("contact-binary-solution", "nn-catalogue-audit"):
        spec = card_precheck.precheck_spec(entry, template)
        assert spec is not None and "{entry_id}" in spec["command"], template


def test_card_core_hours_are_raised_to_the_line_floor(tmp_path, monkeypatch):
    card = lines_tests._line_card(0)
    card["cost_estimate"]["agent_seconds"] = 7_200
    card["cost_estimate"]["compute_plan"] = {
        "locations": ["container_cpu", "container_gpu", "ailab"], "gpu_memory_mib": 8000,
        "ailab": {"cpus": 4, "memory_mib": 5120, "hours": 2}}
    floor = "    card_compute_floor: {ailab_core_hours: 60, agent_hours: 6}\n"
    paths, db, settings, outcome, topic = _intake(tmp_path, monkeypatch, floor, card=card)
    assert outcome["status"] == "proposed", outcome
    stored = json.loads(Path(topic["card_path"]).read_text(encoding="utf-8"))
    assert stored["cost_estimate"]["compute_plan"]["ailab"]["hours"] == 15
    assert stored["cost_estimate"]["agent_seconds"] == 21_600
    notes = " ".join(topic["card_check"]["normalized"])
    assert "raised from 2 to 15" in notes and "60 core-hours" in notes


def test_compute_floor_reads_per_paper_cost_lower_bounds() -> None:
    template = {"per_paper_cost": {"cpu_core_hours": "8-12 per symmetric target",
                                   "agent_hours": "6-10"}}
    assert card_precheck.compute_floor({}, template) == {
        "source": "template per_paper_cost", "core_hours": 8.0, "agent_seconds": 21_600}
    assert card_precheck.compute_floor({"per_paper_cost": {"cpu_core_hours": "< 5"}}, {}) == {}
    explicit = {"card_compute_floor": {"ailab_core_hours": 60}}
    assert card_precheck.compute_floor({}, explicit)["core_hours"] == 60
    card = {"cost_estimate": {"agent_seconds": 50_000, "compute_plan": {
        "locations": ["ailab"], "ailab": {"cpus": 7, "hours": 130, "memory_mib": 9000}}}}
    fixed, notes = card_precheck.apply_compute_floor(card, {"core_hours": 60,
                                                            "agent_seconds": 3600})
    assert fixed == card and notes == []
    line = {"admission_precheck": {"per_template": {"a": {"command": "x {entry_id}"}}}}
    assert card_precheck.precheck_spec(line, "a")["command"] == "x {entry_id}"
    assert card_precheck.precheck_spec(line, "b") is None
    assert card_precheck.precheck_spec({}, "a") is None


# --------------------------------------------------------------------------- tokens


def test_codex_session_totals_become_attempt_increments() -> None:
    first = {"adapter": "codex", "session_id": "t1", "input_tokens": 1_000_000,
             "cached_input_tokens": 900_000, "output_tokens": 10_000}
    second = {"adapter": "codex", "session_id": "t1", "resumed_from": "t1",
              "input_tokens": 1_600_000, "cached_input_tokens": 1_450_000,
              "output_tokens": 14_000}
    first_inc = usage.to_increment(first, [])
    assert first_inc["input_tokens"] == 1_000_000 and first_inc["usage_basis"] == (
        usage.INCREMENT_BASIS)
    inc = usage.to_increment(second, [first_inc])
    assert (inc["input_tokens"], inc["cached_input_tokens"], inc["output_tokens"]) == (
        600_000, 550_000, 4_000)
    assert inc["usage_cumulative"]["input_tokens"] == 1_600_000
    assert inc["usage_session_base"]["input_tokens"] == 1_000_000
    # Idempotent, and an old (cumulative) row works as a base too.
    assert usage.to_increment(inc, [first_inc]) == inc
    assert usage.to_increment(second, [first])["input_tokens"] == 600_000
    # Another session or a restarted counter is left alone.
    other = dict(second, session_id="t2")
    assert usage.to_increment(other, [first])["input_tokens"] == 1_600_000
    restarted = dict(second, input_tokens=5)
    assert usage.to_increment(restarted, [first])["input_tokens"] == 5


def test_claude_tokens_are_per_run_but_its_cost_is_a_session_total() -> None:
    first = {"adapter": "claude", "session_id": "c1", "input_tokens": 30,
             "cached_input_tokens": 4_000_000, "output_tokens": 20_000, "cost_usd": 9.11}
    second = {"adapter": "claude", "session_id": "c1", "input_tokens": 12,
              "cached_input_tokens": 1_120_000, "output_tokens": 13_000, "cost_usd": 17.64}
    inc = usage.to_increment(second, [usage.to_increment(first, [])])
    assert inc["cached_input_tokens"] == 1_120_000 and inc["input_tokens"] == 12
    assert abs(inc["cost_usd"] - 8.53) < 1e-6
    assert usage.tokens_read(inc) == 1_120_012
    price = ModelPrice(input=4.0, cached_input=0.2, output=20.0, cache_write=5.0,
                       cache_write_1h=8.0)
    cost = usage.equivalent_cost(dict(inc, cache_write_input_tokens=100_000,
                                      cache_write_1h_input_tokens=100_000), price)
    assert abs(cost - (12 * 4 + 1_120_000 * 0.2 + 100_000 * 8 + 13_000 * 20) / 1e6) < 1e-9
    codex = {"adapter": "codex", "input_tokens": 1_000_000, "cached_input_tokens": 900_000,
             "output_tokens": 10_000}
    sol = ModelPrice(input=2.0, cached_input=0.1, output=10.0)
    assert abs(usage.equivalent_cost(codex, sol) - (100_000 * 2 + 900_000 * 0.1
                                                    + 10_000 * 10) / 1e6) < 1e-9


def test_ingestion_stores_increments_and_the_tick_reports_cost(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _owner_program(
        tmp_path, monkeypatch, owner_settings=OwnerSettings(session_max_seats=0))
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _seat_packet(db, paths, seat["task_id"], {"status": "continuing"}, session="th-1",
                 artifact=True)
    receipt = sorted(paths.result_inbox.glob("*.json"))[-1]
    body = json.loads(receipt.read_text())
    body["runtime"].update({"adapter": "codex", "input_tokens": 1_000_000,
                            "cached_input_tokens": 900_000, "output_tokens": 10_000,
                            "model": "gpt-6.1-sol"})
    receipt.write_text(json.dumps(body))
    _tick(paths, settings, monkeypatch)
    second = _lease(paths, settings, monkeypatch, db, _latest(db, topic["campaign_id"])[
        "task_id"])
    assert second["session_mode"] == "resume"
    _seat_packet(db, paths, second["task_id"], {"status": "continuing"}, session="th-1",
                 artifact=True)
    receipt = sorted(paths.result_inbox.glob("*.json"))[-1]
    body = json.loads(receipt.read_text())
    body["runtime"].update({"adapter": "codex", "input_tokens": 1_500_000,
                            "cached_input_tokens": 1_350_000, "output_tokens": 15_000,
                            "model": "gpt-6.1-sol", "resumed_from": "th-1"})
    receipt.write_text(json.dumps(body))
    report = _tick(paths, settings, monkeypatch)
    (attempt,) = db.task_attempts(second["task_id"])
    runtime = attempt["runtime"]
    assert runtime["input_tokens"] == 500_000 and runtime["usage_basis"] == (
        usage.INCREMENT_BASIS)
    cost = report.to_dict()["token_cost"]
    owner_row = cost["by_task_type"][OWNER_TASK_TYPE]
    assert owner_row["tokens_read"] == 1_500_000
    expected = (100_000 * 2 + 900_000 * 0.1 + 10_000 * 10 + 50_000 * 2 + 450_000 * 0.1
                + 5_000 * 10) / 1e6
    assert abs(owner_row["equivalent_usd"] - round(expected, 2)) < 0.011
    economics = report.to_dict()["topic_economics"]
    (row,) = economics["topics"]
    assert row["topic_id"] == topic["topic_id"] and row["seats"] == 2
    assert row["tokens_read"] == 1_500_000 and row["phase"] == "research"


def test_core_hours_from_job_status_files(tmp_path) -> None:
    root = tmp_path / "jobs"
    ailab = root / ("a" * 32)
    (ailab / "result").mkdir(parents=True)
    (ailab / "request.json").write_text(json.dumps({"resources": {"cpu_threads": 4}}))
    (ailab / "result" / "receipt.json").write_text(json.dumps({"elapsed_seconds": 7200}))
    assert usage.job_core_hours(ailab) == 8.0
    local = root / ("b" * 32)
    local.mkdir()
    (local / "request.json").write_text(json.dumps({"resources": {"cpu_threads": 8},
                                                    "source": str(tmp_path / "ws" / "job")}))
    start = datetime(2026, 11, 16, 0, 0, tzinfo=UTC)
    (local / "status.json").write_text(json.dumps({
        "state": "running", "started_at": start.isoformat()}))
    assert usage.job_core_hours(local, now=start + timedelta(hours=1.5)) == 12.0
    queued = root / ("c" * 32)
    queued.mkdir()
    (queued / "request.json").write_text(json.dumps({"resources": {"cpu_threads": 8}}))
    (queued / "status.json").write_text(json.dumps({"state": "queued"}))
    assert usage.job_core_hours(queued) == 0.0


def test_reporting_prices_parse_and_default_to_the_cost_review() -> None:
    defaults = ReportingSettings()
    assert defaults.prices["claude-opus-5-5"].cached_input == 0.20
    assert defaults.prices["gpt-6-astra"].output == 50.0
    parsed = load_reporting_settings({"prices": {"gpt-7": {"input": 1, "output": 2}},
                                      "economics_since": "2026-11-17T00:00:00Z"})
    assert parsed.prices["gpt-7"].cached_input == 1.0 and "gpt-6.1-sol" in parsed.prices
    assert parsed.economics_since == "2026-11-17T00:00:00Z"
    assert load_program_settings({"owner": {"session_max_seats": 0, "review_max_rounds": 5,
                                            "recompute_review": False}}).owner == OwnerSettings(
        session_max_seats=0, review_max_rounds=5, recompute_review=False)


def test_routine_endpoint_routes_to_unified_review(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _seat_packet(db, paths, seat["task_id"], {"status": "ready_for_review", "paper_id": PAPER,
                 "primary_endpoint_verdict": "met"}, artifact=True)
    _tick(paths, settings, monkeypatch)
    assert _review_of(db, topic["campaign_id"])["routing_reason"] == owner.ROUTING_REVIEW


def test_sensitive_endpoint_reuses_only_a_matching_independent_review(tmp_path):
    report = tmp_path / "decision.json"
    report.write_text('{"verdict": "accept"}')
    state = {"digest": "current", "review_endpoint_verdict": "met", "review_history": [
        {"paper_id": PAPER, "workspace_digest": "current", "verdict": "accept",
         "result_path": str(report), "result_sha256": owner.sha256_file(report)}]}
    packet = {"paper_id": PAPER, "primary_endpoint_verdict": "met"}
    prereg = {"high_sensitivity": True}
    assert not owner.needs_specialist_review(state, packet, prereg)
    assert owner.needs_specialist_review(dict(state, digest="changed"), packet, prereg)
    assert owner.needs_specialist_review(state, dict(packet, paper_id="other"), prereg)
    assert owner.needs_specialist_review(state, dict(packet, primary_endpoint_verdict="failed"), {})
    report.write_text("{}")
    assert owner.needs_specialist_review(state, packet, prereg)


def test_decisive_figure_rebuild_is_optional_review_evidence():
    block = owner.recompute_block({"recompute_review": {
        "verdict": "accept",
        "figure_rebuild": {"figure": "2", "outcome": "missing", "unexpected": "ignored"},
    }})
    assert block["verdict"] == "accept"
    assert block["unverified"] == []
    assert block["figure_rebuild"] == {"figure": "2", "outcome": "missing"}
