"""Admission policy v2: conditional admits, card repair, hold release and revision cards."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import test_research_lines as lines
import test_research_program_flow as flow
from openlabs import program_autonomy
from openlabs import program_flow as pf
from openlabs.contracts import (
    ADMISSION_POLICY_VERSION,
    validate_topic_admission,
    validate_topic_card,
)
from openlabs.program import (
    IllegalTopicTransition,
    TopicLedger,
    admit_topic,
    last_rejection_reason,
    open_topic_ledger,
    propose_topic,
    reject_topic,
    revision_eligible,
    transition_topic,
)

CONDITIONS = [
    {"description": "Freeze the bootstrap seed and the multiplicity rule.",
     "due": "before_precheck"},
    {"description": "Add the tuned gradient-boosting baseline.",
     "due": "before_decisive_analysis"},
    {"description": "Confirm the CAS 2025 zone of the second routine venue.",
     "due": "before_submission"},
]


def _setup(tmp_path):
    paths = flow._paths(tmp_path)
    project_path = flow._install_program(paths)
    db = flow._db(paths)
    return paths, project_path, db, flow._settings()


def _ledger(paths, settings) -> TopicLedger:
    return open_topic_ledger(paths, settings.program)


def _tasks(db, task_type: str) -> list[dict]:
    with db.connect() as connection:
        rows = connection.execute(
            "SELECT * FROM tasks WHERE task_type=? ORDER BY created_at, task_id", (task_type,)
        ).fetchall()
    return [dict(row) for row in rows]


def _open_admission(db) -> dict:
    """The admission task still to be decided (several can share one creation second)."""

    with db.connect() as connection:
        row = connection.execute(
            "SELECT * FROM tasks WHERE routing_reason='topic_admission' "
            "AND status IN ('queued','leased','running') ORDER BY created_at DESC, task_id DESC "
            "LIMIT 1"
        ).fetchone()
    assert row is not None
    return dict(row)


def _judge(paths, db, settings, monkeypatch, branches_for):
    """Complete the latest admission task with ``branches_for(entries)`` and tick."""

    admission = _open_admission(db)
    entries = flow._packet(admission)["topic_cards"]
    flow._complete(db, paths, admission["task_id"],
                   extra={"candidate_branches": branches_for(entries)})
    return entries, flow._tick(paths, settings, monkeypatch)


# --------------------------------------------------------------------------- contracts


def test_admission_conditions_are_validated_and_optional() -> None:
    entry = {"topic_id": "t", "source_result_id": "s", "card": flow._card()}
    plain = flow._branch(entry)["admission"]
    assert validate_topic_admission(plain).valid
    conditional = flow._branch(entry, conditions=CONDITIONS)["admission"]
    assert validate_topic_admission(conditional).valid
    bad = flow._branch(entry, conditions=[{"description": "x", "due": "someday"}])["admission"]
    assert any("conditions[0] needs a description and due" in e
               for e in validate_topic_admission(bad).errors)
    flag = flow._branch(entry, "reject", revisable="yes")["admission"]
    assert "admission.revisable must be a boolean when present" in validate_topic_admission(
        flag).errors


def test_card_contract_accepts_audience_papers_outside_the_candidate_venues() -> None:
    card = flow._card()
    card["audience"]["citations"].append(
        {"citation": "Reader paper in another journal", "year": flow.YEAR - 1,
         "venue": "Journal of Infection"})
    assert validate_topic_card(card, current_year=flow.YEAR).valid
    # The candidate-venue minimum still holds.
    few = flow._card()
    for item in few["audience"]["citations"]:
        item["venue"] = "Some Other Journal"
    errors = validate_topic_card(few, current_year=flow.YEAR).errors
    assert any("at least two papers" in e for e in errors)
    # An escalation may list its venues instead of a single name.
    listed = flow._card()
    listed["venues"]["escalation"] = {"condition": "only if H1 holds on both cohorts",
                                      "venues": ["International Journal of Thermal Sciences"]}
    assert validate_topic_card(listed, current_year=flow.YEAR).valid
    empty = flow._card()
    empty["venues"]["escalation"] = {"condition": "never named"}
    assert any(e.startswith("venues.escalation must be null")
               for e in validate_topic_card(empty, current_year=flow.YEAR).errors)


# --------------------------------------------------------------------------- conditional admit


def test_conditional_admit_reaches_the_first_task_and_blocks_the_handler(tmp_path, monkeypatch):
    paths, _, db, settings = _setup(tmp_path)
    _, admission, _ = flow._to_admission(paths, db, settings, monkeypatch,
                                         [flow._card(0, flow.RECEIPT_SHA)])
    assert flow._packet(admission)["admission_policy"] == ADMISSION_POLICY_VERSION
    assert "admission.conditions" in admission["objective"] or "conditions" in admission[
        "objective"]
    entries, report = _judge(paths, db, settings, monkeypatch,
                             lambda entries: [flow._branch(entries[0], conditions=CONDITIONS)])
    assert report.errors == []
    assert report.program["admission_decisions"][0]["outcome"] == "admitted"
    ledger = _ledger(paths, settings)
    topic = ledger.topic(entries[0]["topic_id"])
    assert topic["status"] == "active"
    assert topic["admission"]["conditions"] == CONDITIONS
    assert topic["admission"]["policy"] == ADMISSION_POLICY_VERSION
    campaign = db.campaign(topic["campaign_id"])
    state = json.loads(Path(campaign["workstream_state_path"]).read_text(encoding="utf-8"))
    assert state["admission_conditions"] == CONDITIONS
    first = db.latest_task(topic["campaign_id"])
    for item in CONDITIONS:
        assert item["description"] in first["objective"]
    record = json.loads(pf._admission_record_path(paths, topic["topic_id"]).read_text())
    assert record["schema_version"] == pf.ADMISSION_RECORD_SCHEMA
    assert record["conditions"] == CONDITIONS

    # before_submission conditions travel with the handoff and block the handler.
    assert program_autonomy.submission_conditions(topic) == CONDITIONS[2:]
    ledger_doc = ledger.read()
    for item in ledger_doc["topics"]:
        if item["topic_id"] == topic["topic_id"]:
            item["paper_id"] = "paper-x"
    with ledger.transaction() as document:
        document["topics"][:] = ledger_doc["topics"]
    calls: list[str] = []
    monkeypatch.setattr(program_autonomy, "run_handler_assignment",
                        lambda *_a, **_k: calls.append("x") or {"submission_handler": "B"})
    with pytest.raises(program_autonomy.DeliveryError, match="before submission"):
        program_autonomy.assign_submission_handler(db, paths, settings, paper_id="paper-x")
    assert calls == []
    result = program_autonomy.assign_submission_handler(db, paths, settings, paper_id="paper-x",
                                                        conditions_met=True)
    assert result["submission_handler"] == "B" and calls == ["x"]


def test_v1_ledger_is_read_and_upgraded_on_write(tmp_path) -> None:
    paths, _, db, settings = _setup(tmp_path)
    ledger = _ledger(paths, settings)
    ledger.path.parent.mkdir(parents=True, exist_ok=True)
    ledger.path.write_text(json.dumps(
        {"schema_version": "openlabs.topic_ledger.v1", "updated_at": None, "topics": []}))
    assert ledger.read()["topics"] == []
    propose_topic(ledger, {"topic_id": "t", "domain": "ai", "question": "q",
                           "data_sources": ["s"], "primary_endpoint": "e"}, db=db, decided_by="s")
    assert json.loads(ledger.path.read_text())["schema_version"] == "openlabs.topic_ledger.v2"


def test_rejected_is_left_only_through_the_guarded_releases(tmp_path) -> None:
    paths, _, db, settings = _setup(tmp_path)
    ledger = _ledger(paths, settings)
    propose_topic(ledger, {"topic_id": "t", "domain": "ai", "question": "q",
                           "data_sources": ["s"], "primary_endpoint": "e"}, db=db, decided_by="s")
    reject_topic(ledger, "t", db=db, reason="admission_rejected", decided_by="g")
    with pytest.raises(IllegalTopicTransition):
        transition_topic(ledger, "t", "proposed", db=db, reason="resubmitted", decided_by="x")
    with pytest.raises(IllegalTopicTransition):
        admit_topic(ledger, "t", db=db, settings=settings.program, decided_by="x",
                    admission_task_id="x", queue_when_full=True)


# --------------------------------------------------------------------------- card repair


def _bad_card(n: int) -> dict:
    card = flow._card(n, flow.RECEIPT_SHA)
    card["audience"].pop("who")
    return card


def test_invalid_card_gets_one_repair_task_and_the_fixed_card_is_proposed(tmp_path, monkeypatch):
    paths, _, db, settings = _setup(tmp_path)
    _, report = flow._scout_round(paths, db, settings, monkeypatch, [_bad_card(0)])
    rejected = report.program["rejected_cards"]
    assert len(rejected) == 1 and rejected[0]["card_repair"] == "pending"
    original_id = rejected[0]["topic_id"]
    repairs = report.program["card_repairs"]
    assert [item["outcome"] for item in repairs] == ["scheduled"]
    task = db.task(repairs[0]["task_id"])
    assert task["task_type"] == pf.REPAIR_TASK_TYPE
    assert task["routing_reason"] == pf.REPAIR_ROUTING_REASON
    assert task["runner"] in {"worker_gpt", "worker_claude"} or task["runner"].startswith("light")
    packet = json.loads(Path(task["input_path"]).read_text(encoding="utf-8"))
    assert packet["repair_of"] == original_id
    assert any("audience.who" in error for error in packet["errors"])
    assert flow.RECEIPT_SHA in packet["receipt_digests"]
    ledger = _ledger(paths, settings)
    assert ledger.topic(original_id)["card_repair"]["status"] == "scheduled"
    assert Path(ledger.topic(original_id)["card_path"]).is_file()

    fixed = flow._card(0, flow.RECEIPT_SHA)
    # The repair reuses the scout's receipt: no new artifact is needed.
    flow._complete(db, paths, task["task_id"], extra={"topic_cards": [fixed]})
    later = flow._tick(paths, settings, monkeypatch)
    assert later.errors == []
    registered = later.program["cards_registered"]
    assert len(registered) == 1
    new = ledger.topic(registered[0]["topic_id"])
    assert new["status"] in {"proposed"} and new["repair_of"] == original_id
    original = ledger.topic(original_id)
    assert original["card_repair"]["status"] == "resubmitted"
    assert original["card_repair"]["topic_id"] == new["topic_id"]
    # Nothing is repaired twice.
    assert len(_tasks(db, pf.REPAIR_TASK_TYPE)) == 1


def test_a_repair_that_fails_again_is_final(tmp_path, monkeypatch):
    paths, _, db, settings = _setup(tmp_path)
    _, report = flow._scout_round(paths, db, settings, monkeypatch, [_bad_card(0)])
    original_id = report.program["rejected_cards"][0]["topic_id"]
    task_id = report.program["card_repairs"][0]["task_id"]
    flow._complete(db, paths, task_id, extra={"topic_cards": [_bad_card(0)]})
    later = flow._tick(paths, settings, monkeypatch)
    again = later.program["rejected_cards"]
    assert len(again) == 1 and again[0]["card_repair"] == "not_repairable"
    ledger = _ledger(paths, settings)
    assert ledger.topic(original_id)["card_repair"]["status"] == "failed"
    second = ledger.topic(again[0]["topic_id"])
    assert second["repair_of"] == original_id
    assert last_rejection_reason(second) == "card_invalid"
    flow._tick(paths, settings, monkeypatch)
    assert len(_tasks(db, pf.REPAIR_TASK_TYPE)) == 1


def test_legacy_invalid_card_passing_the_current_checks_is_resubmitted_without_a_task(
    tmp_path, monkeypatch
):
    paths, _, db, settings = _setup(tmp_path)
    real = pf.card_problems
    # The card fails a check that was relaxed later.
    monkeypatch.setattr(pf, "card_problems",
                        lambda *a, **k: ["audience.citations[3].venue must be one of the card's "
                                         "candidate venues"] + real(*a, **k))
    monkeypatch.setattr(pf, "schedule_card_repairs", lambda *_a, **_k: [])
    _, report = flow._scout_round(paths, db, settings, monkeypatch,
                                  [flow._card(0, flow.RECEIPT_SHA)])
    original_id = report.program["rejected_cards"][0]["topic_id"]
    ledger = _ledger(paths, settings)
    # As a v1 ledger recorded it: no card_repair, no stored card.
    with ledger.transaction() as document:
        for topic in document["topics"]:
            if topic["topic_id"] == original_id:
                topic.pop("card_repair", None)
                topic["card_path"] = None
    monkeypatch.undo()
    outcomes = pf.schedule_card_repairs(db, paths, settings)
    assert [item["outcome"] for item in outcomes] == ["resubmitted"]
    assert outcomes[0]["mode"] == "revalidated"
    new = ledger.topic(outcomes[0]["new_topic_id"])
    assert new["status"] == "proposed" and new["repair_of"] == original_id
    assert _tasks(db, pf.REPAIR_TASK_TYPE) == []
    assert pf.schedule_card_repairs(db, paths, settings) == []


# --------------------------------------------------------------------------- hold release


def _line_hold(tmp_path, monkeypatch, branch_for):
    paths, db, settings = lines._line_setup(tmp_path, "not_ready")
    flow._to_admission(paths, db, settings, monkeypatch, [lines._line_card(0)])
    entries, report = _judge(paths, db, settings, monkeypatch,
                             lambda entries: [branch_for(entries[0])])
    return paths, db, settings, entries[0]["topic_id"], report


def test_control_plane_hold_is_admitted_when_the_line_becomes_ready(tmp_path, monkeypatch):
    paths, db, settings, topic_id, report = _line_hold(
        tmp_path, monkeypatch, lambda entry: flow._branch(entry, conditions=CONDITIONS[:1]))
    assert report.program["admission_decisions"][0]["outcome"] == "held"
    ledger = _ledger(paths, settings)
    assert not revision_eligible(ledger.topic(topic_id))  # nothing for a revision to answer
    record = json.loads(pf._admission_record_path(paths, topic_id).read_text())
    assert record["held_for_line"] == lines.LINE
    quiet = flow._tick(paths, settings, monkeypatch)
    assert quiet.program["holds_released"] == []

    lines._lines_file(paths, "ready")
    released = flow._tick(paths, settings, monkeypatch)
    assert released.errors == []
    assert released.program["holds_released"] == [
        {"topic_id": topic_id, "outcome": "admitted", "line": lines.LINE}]
    topic = ledger.topic(topic_id)
    assert topic["status"] == "active"
    assert topic["preregistration_sha256"] == record["preregistration"]["sha256"]
    first = db.latest_task(topic["campaign_id"])
    assert "feasibility_precheck" in first["objective"]
    assert CONDITIONS[0]["description"] in first["objective"]
    # Released once only.
    assert flow._tick(paths, settings, monkeypatch).program["holds_released"] == []


def test_gate_hold_on_the_environment_alone_goes_back_to_the_gate(tmp_path, monkeypatch):
    def hold(entry):
        return flow._branch(entry, "hold", reopen_conditions=[
            {"type": "line_environment_ready", "description": "line environment ready"}])

    paths, db, settings, topic_id, _ = _line_hold(tmp_path, monkeypatch, hold)
    ledger = _ledger(paths, settings)
    assert last_rejection_reason(ledger.topic(topic_id)) == "admission_hold"
    lines._lines_file(paths, "ready")
    report = flow._tick(paths, settings, monkeypatch)
    assert report.program["holds_released"][0]["outcome"] == "returned_to_gate"
    topic = ledger.topic(topic_id)
    assert topic["status"] == "proposed"
    admission = _open_admission(db)
    entry = flow._packet(admission)["topic_cards"][0]
    assert entry["topic_id"] == topic_id and "released_from_hold" in entry
    flow._complete(db, paths, admission["task_id"],
                   extra={"candidate_branches": [flow._branch(entry)]})
    flow._tick(paths, settings, monkeypatch)
    assert ledger.topic(topic_id)["status"] == "active"


# --------------------------------------------------------------------------- revision


def _revision_card(n: int, responses) -> dict:
    card = flow._card(n, flow.RECEIPT_SHA)
    card["primary_endpoint"]["matched_baseline"] = "tuned gradient boosting (revised)"
    card["condition_responses"] = responses
    return card


def test_hold_gets_one_revision_task_and_the_gate_checks_only_its_conditions(
    tmp_path, monkeypatch
):
    paths, _, db, settings = _setup(tmp_path)
    flow._to_admission(paths, db, settings, monkeypatch, [flow._card(0, flow.RECEIPT_SHA)])
    entries, report = _judge(paths, db, settings, monkeypatch, lambda entries: [flow._branch(
        entries[0], "hold", reopen_conditions=[
            {"type": "new_method", "description": "Add the tuned baseline."},
            {"type": "external_result", "description": "Attach a timing probe."}])])
    held_id = entries[0]["topic_id"]
    ledger = _ledger(paths, settings)
    assert revision_eligible(ledger.topic(held_id))
    scheduled = report.program["revisions_scheduled"]
    assert [item["topic_id"] for item in scheduled] == [held_id]
    task = db.task(scheduled[0]["task_id"])
    assert task["task_type"] == pf.REVISION_TASK_TYPE
    packet = json.loads(Path(task["input_path"]).read_text(encoding="utf-8"))
    assert packet["revision_of"] == held_id
    assert [c["condition"] for c in packet["target"]["reopen_conditions"]] == [0, 1]
    assert ledger.topic(held_id)["revision"]["status"] == "scheduled"

    # A revised card that leaves a condition unanswered goes to its format repair.
    flow._complete(db, paths, task["task_id"], extra={"topic_cards": [
        _revision_card(0, [{"condition": 0, "response": "Baseline added."}])]})
    partial = flow._tick(paths, settings, monkeypatch)
    rejected = partial.program["rejected_cards"]
    assert len(rejected) == 1 and rejected[0]["card_repair"] == "pending"
    assert any("reopen condition(s) 1" in e for e in rejected[0]["errors"])
    assert ledger.topic(held_id)["revision"]["status"] == "card_repair_pending"
    repair = partial.program["card_repairs"][0]
    assert "task_id" in repair, partial.program["card_repairs"]
    repair_packet = json.loads(Path(db.task(repair["task_id"])["input_path"]).read_text())
    assert repair_packet["revises"] == held_id

    flow._complete(db, paths, repair["task_id"], extra={"topic_cards": [_revision_card(0, [
        {"condition": 0, "response": "Baseline added."},
        {"condition": 1, "response": "Timing probe receipt attached."}])]})
    done = flow._tick(paths, settings, monkeypatch)
    assert done.errors == []
    new_id = done.program["cards_registered"][0]["topic_id"]
    new = ledger.topic(new_id)
    assert new["revision_of"] == held_id and new["supersedes"] == held_id
    assert not revision_eligible(new)  # a revision is not revised again
    admission = _open_admission(db)
    entry = next(e for e in flow._packet(admission)["topic_cards"] if e["topic_id"] == new_id)
    assert entry["revision_of"]["topic_id"] == held_id
    assert len(entry["revision_of"]["reopen_conditions"]) == 2
    assert "revision card" in admission["objective"]
    # One revision per topic.
    assert len(_tasks(db, pf.REVISION_TASK_TYPE)) == 1


def test_a_declined_revision_is_recorded_and_not_retried(tmp_path, monkeypatch):
    paths, _, db, settings = _setup(tmp_path)
    flow._to_admission(paths, db, settings, monkeypatch, [flow._card(0, flow.RECEIPT_SHA)])
    entries, report = _judge(paths, db, settings, monkeypatch,
                             lambda entries: [flow._branch(entries[0], "hold")])
    held_id = entries[0]["topic_id"]
    task_id = report.program["revisions_scheduled"][0]["task_id"]
    flow._complete(db, paths, task_id, extra={"topic_cards": []})
    later = flow._tick(paths, settings, monkeypatch)
    assert later.program["revisions_scheduled"] == []
    assert _ledger(paths, settings).topic(held_id)["revision"]["status"] == "declined"


def test_rejections_are_revisable_only_when_marked_fixable(tmp_path, monkeypatch):
    paths, project_path, db, _ = _setup(tmp_path)
    settings = flow._settings(max_concurrent_scouts=2)
    flow._to_admission(paths, db, settings, monkeypatch,
                       [flow._card(0, flow.RECEIPT_SHA), flow._card(1, flow.RECEIPT_SHA)])
    entries, report = _judge(paths, db, settings, monkeypatch, lambda entries: [
        flow._branch(entries[0], "reject"),
        flow._branch(entries[1], "reject", revisable=True)])
    plain, fixable = entries[0]["topic_id"], entries[1]["topic_id"]
    ledger = _ledger(paths, settings)
    assert not revision_eligible(ledger.topic(plain))
    assert revision_eligible(ledger.topic(fixable))
    assert [item["topic_id"] for item in report.program["revisions_scheduled"]] == [fixable]

    assert pf.mark_revisable(db, paths, settings, plain, decided_by="manual:lead",
                             reason="difference accepted; design details fixable")
    assert revision_eligible(ledger.topic(plain))
    assert ledger.topic(plain)["revision"]["marked_by"] == "manual:lead"
    later = flow._tick(paths, settings, monkeypatch)
    assert [item["topic_id"] for item in later.program["revisions_scheduled"]] == [plain]
    # Only a judged rejection can be marked.
    propose_topic(ledger, {"topic_id": "fresh", "domain": "ai", "question": "fresh q",
                           "data_sources": ["s"], "primary_endpoint": "e"}, db=db, decided_by="s")
    with pytest.raises(ValueError, match="not a judged rejection"):
        pf.mark_revisable(db, paths, settings, "fresh", decided_by="x", reason="y")
