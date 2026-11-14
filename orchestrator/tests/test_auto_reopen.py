"""Automatic reopening of topics frozen for a research-line fact (reopen.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from openlabs import owner, reopen
from openlabs.config import OWNER_TASK_TYPE
from openlabs.contracts import atomic_write_json
from openlabs.program import open_topic_ledger
from test_owner_mode import _first_seat, _latest, _owner_program, _seat_packet, _tasks
from test_program_autonomy import _lease, _topic
from test_research_program_flow import _tick

LINE = "astro-survey-photometry"


def _receipt(tmp_path: Path, *, incl_pass: bool, tau: float, rhat: list[float]) -> Path:
    results = tmp_path / "control" / "results"
    summary = results / "outputs" / "TIC55522736" / "summary.json"
    atomic_write_json(summary, {"diagnostics": {"n_post_over_tau": tau, "rhat": rhat,
                                                "ess": 458.0}})
    path = tmp_path / "control" / "CONTROL_RECEIPT.json"
    atomic_write_json(path, {
        "state": "succeeded", "tag": "TIC55522736", "job_id": "c" * 32, "converged": True,
        "config_version": "astro-std-1", "results_dir": str(results),
        "comparison": {
            "q": {"pass_2sigma": True, "pass_tolerance": True, "z_combined": 0.76},
            "incl": {"pass_2sigma": True, "pass_tolerance": incl_pass, "z_combined": 1.64,
                     "delta": 2.2 if not incl_pass else 1.1},
        },
    })
    return path


def _control_condition(path: Path) -> dict:
    return {
        "kind": "control_receipt", "receipt": str(path),
        "description": "shared control meets the registered strict criteria",
        "checks": [["state", "==", "succeeded"], ["comparison.q.pass_tolerance", "==", True],
                   ["comparison.incl.pass_tolerance", "==", True],
                   ["comparison.incl.z_combined", "<=", 2],
                   ["summary.diagnostics.n_post_over_tau", ">=", 50],
                   ["summary.diagnostics.rhat", "<=", 1.05]],
    }


def _lines(paths, settings, *, spot: object = None) -> Path:
    environment: dict = {"status": "ready", "standard_solver": {"config": "astro-std-1"}}
    if spot is not None:
        environment["standard_solver"]["spot_config"] = spot
    path = paths.data / settings.program.research_lines_path
    path.parent.mkdir(parents=True, exist_ok=True)
    # JSON is valid YAML; the loader accepts it either way.
    path.write_text(json.dumps({"lines": [{"id": LINE, "environment": environment}]}),
                    encoding="utf-8")
    return path


def _freeze_with(paths, db, settings, monkeypatch, topic, packet: dict) -> None:
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _seat_packet(db, paths, seat["task_id"], packet, session="s1", artifact=True)
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors


# --------------------------------------------------------------------------- conditions


def test_conditions_are_validated_and_kept_simple() -> None:
    assert reopen.normalize_conditions(None) == []
    clean = reopen.normalize_conditions([{"kind": "line_capability", "key": "a.b",
                                          "note": "dropped"}])
    assert clean == [{"kind": "line_capability", "key": "a.b"}]
    for bad in ([{"kind": "anything"}], [{"kind": "control_receipt", "checks": []}],
                [{"kind": "control_receipt", "checks": [["x", "~", 1]]}],
                [{"kind": "control_receipt", "checks": [["x", "==", [1]]]}],
                [{"kind": "line_capability"}], "text"):
        with pytest.raises(reopen.ReopenConditionError):
            reopen.normalize_conditions(bad)


def test_receipt_checks_read_the_summary_and_reduce_lists(tmp_path) -> None:
    path = _receipt(tmp_path, incl_pass=True, tau=60.0, rhat=[1.01, 1.049])
    condition = reopen.normalize_conditions([_control_condition(path)])[0]
    result = reopen.evaluate_condition(condition, topic={}, lines_document=None, lines_path=None)
    assert result["met"], result
    assert result["evidence"]["path"] == str(path)
    worse = _receipt(tmp_path, incl_pass=False, tau=28.6, rhat=[1.01, 1.06])
    result = reopen.evaluate_condition(condition, topic={}, lines_document=None,
                                       lines_path=None)
    assert worse == path and not result["met"]
    assert "comparison.incl.pass_tolerance" in result["detail"]
    assert "n_post_over_tau" in result["detail"] and "rhat" in result["detail"]
    missing = dict(condition, checks=[["summary.diagnostics.nothing", ">=", 1]])
    assert not reopen.evaluate_condition(missing, topic={}, lines_document=None,
                                         lines_path=None)["met"]


def test_line_capability_needs_a_truthy_validated_key() -> None:
    def doc(value):
        return {"lines": [{"id": LINE, "environment": {"standard_solver": {"spot_config": value}}}]}

    cond = {"kind": "line_capability", "key": "environment.standard_solver.spot_config"}
    topic = {"research_line": LINE}
    for value, met in ((None, False), ("astro-std-2-spot", True), ({"validated": False}, False),
                       ({"validated": True, "config": "astro-std-2"}, True)):
        assert reopen.evaluate_condition(cond, topic=topic, lines_document=doc(value),
                                         lines_path=None)["met"] is met, value
    assert not reopen.evaluate_condition(cond, topic={}, lines_document=doc("x"),
                                         lines_path=None)["met"]  # no line known


# --------------------------------------------------------------------------- end to end


def test_frozen_topic_reopens_once_when_the_control_requalifies(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    receipt = _receipt(tmp_path, incl_pass=False, tau=28.6, rhat=[1.047])
    _freeze_with(paths, db, settings, monkeypatch, topic, {
        "status": "frozen", "reason": "shared control misses |di| <= 2 deg and 50 tau",
        # nested like the owners of 2026-11-14 wrote it
        "gate_result": {"freeze_reason_class": "feasibility_precheck_failed",
                        "reopen_when": [_control_condition(receipt)]},
    })
    frozen = _topic(paths, settings, topic["topic_id"])
    assert frozen["status"] == "frozen"
    assert frozen["freeze_reason_class"] == "feasibility_precheck_failed"  # nested class read
    assert frozen["auto_reopen"]["when"][0]["kind"] == "control_receipt"
    freeze_seat = _latest(db, topic["campaign_id"])

    report = _tick(paths, settings, monkeypatch)  # receipt still failing
    assert report.errors == [], report.errors
    assert _topic(paths, settings, topic["topic_id"])["status"] == "frozen"
    outcome = report.program["auto_reopen"][0]
    assert outcome["outcome"] == "conditions_unmet" and outcome["unmet"]

    _receipt(tmp_path, incl_pass=True, tau=61.0, rhat=[1.02])
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    reopened = _topic(paths, settings, topic["topic_id"])
    assert reopened["status"] == "active"
    assert reopened["preregistration_sha256"] == topic["preregistration_sha256"]
    assert reopened["history"][-1]["reason"] == "auto_reopen_conditions_met"
    assert reopened["auto_reopen"]["reopens"][0]["evidence"][0]["path"] == str(receipt)
    assert db.campaign(topic["campaign_id"])["status"] == "active"
    seat = _latest(db, topic["campaign_id"])
    assert seat["task_type"] == OWNER_TASK_TYPE and seat["status"] in {"queued", "leased"}
    assert seat["routing_reason"] == reopen.ROUTING_REOPENED
    assert seat["session_mode"] == "resume" and seat["runner"] == freeze_seat["runner"]
    assert "Conditions now met" in seat["objective"] and "all checks pass" in seat["objective"]
    assert db.count_events("campaign", topic["campaign_id"], "campaign_reopened") == 1
    # One seat only, even if the tick repeats.
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    seats = [t for t in _tasks(db, topic["campaign_id"])
             if t["routing_reason"] == reopen.ROUTING_REOPENED]
    assert len(seats) == 1

    # Frozen again without new conditions: the old (still true) ones are cleared.
    _lease(paths, settings, monkeypatch, db, seat["task_id"])
    _seat_packet(db, paths, seat["task_id"], {
        "status": "frozen", "freeze_reason_class": "feasibility_precheck_failed",
        "reason": "target asymmetry under the registered symmetric gate"},
        session="s1", artifact=True)
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    refrozen = _topic(paths, settings, topic["topic_id"])
    assert refrozen["status"] == "frozen"
    assert refrozen["auto_reopen"]["when"] == []
    assert len(refrozen["auto_reopen"]["reopens"]) == 1
    _tick(paths, settings, monkeypatch)
    assert _topic(paths, settings, topic["topic_id"])["status"] == "frozen"


def test_reopen_count_is_capped_and_slots_and_switch_are_respected(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    _lines(paths, settings)
    capability = {"kind": "line_capability", "line": LINE,
                  "key": "environment.standard_solver.spot_config",
                  "description": "validated shared spot configuration"}
    _freeze_with(paths, db, settings, monkeypatch, topic, {
        "status": "frozen", "freeze_reason_class": "feasibility_precheck_failed",
        "reason": "O'Connell asymmetry; the shared solver has no spot model",
        "reopen_when": [capability]})
    ledger = open_topic_ledger(paths, settings.program)
    # Pretend the topic was already reopened once: the cap (1) is reached.
    with ledger.transaction() as document:
        entry = next(t for t in document["topics"] if t["topic_id"] == topic["topic_id"])
        entry["auto_reopen"]["reopens"] = [{"at": "2026-11-14T00:00:00Z", "count": 1}]
    _lines(paths, settings, spot={"validated": True, "config": "astro-std-2"})
    report = _tick(paths, settings, monkeypatch)
    assert report.program["auto_reopen"][0]["outcome"] == "reopen_limit_reached"
    assert _topic(paths, settings, topic["topic_id"])["status"] == "frozen"

    with ledger.transaction() as document:
        entry = next(t for t in document["topics"] if t["topic_id"] == topic["topic_id"])
        entry["auto_reopen"]["reopens"] = []
    off = settings.__class__(**{**settings.__dict__, "program": settings.program.__class__(
        **{**settings.program.__dict__, "auto_reopen_max": 0})})
    report = _tick(paths, off, monkeypatch)
    assert report.program.get("auto_reopen") == []
    no_slot = settings.__class__(**{**settings.__dict__, "program": settings.program.__class__(
        **{**settings.program.__dict__, "max_active_topics": 0})})
    assert reopen.reopen_ready_topics(db, paths, no_slot, None)[0]["outcome"] == (
        "waiting_for_slot")
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    assert _topic(paths, settings, topic["topic_id"])["status"] == "active"
    assert "spot_config" in _latest(db, topic["campaign_id"])["objective"]


def test_register_cli_is_ledger_only_and_needs_a_frozen_topic(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    ledger = open_topic_ledger(paths, settings.program)
    receipt = _receipt(tmp_path, incl_pass=False, tau=28.6, rhat=[1.047])
    with pytest.raises(Exception, match="not frozen"):
        reopen.register_auto_reopen(ledger, topic["topic_id"], [_control_condition(receipt)],
                                    decided_by="manual:test")
    _freeze_with(paths, db, settings, monkeypatch, topic, {
        "status": "frozen", "freeze_reason_class": "feasibility_precheck_failed",
        "reason": "control"})
    assert "auto_reopen" not in _topic(paths, settings, topic["topic_id"]) or not _topic(
        paths, settings, topic["topic_id"]).get("auto_reopen")
    before = db.count_events("topic", topic["topic_id"], "topic_activated")
    block = reopen.register_auto_reopen(ledger, topic["topic_id"], [_control_condition(receipt)],
                                        decided_by="manual:test", note="control-level freeze")
    assert block["max_reopens"] == 1 and block["registered"][0]["by"] == "manual:test"
    stored = _topic(paths, settings, topic["topic_id"])
    assert stored["history"][-1]["kind"] == "auto_reopen_registered"
    assert db.count_events("topic", topic["topic_id"], "topic_activated") == before
    check = reopen.check_report(paths, settings)
    assert check["topics"][0]["all_met"] is False


def test_brief_documents_reopen_when(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    seat = _latest(db, topic["campaign_id"])
    text = owner.render_brief(
        paths, settings, task=seat, campaign=db.campaign(topic["campaign_id"]), topic=topic,
        adapter_family=None, deadline=__import__("datetime").datetime(2026, 11, 14))
    assert "reopen_when" in text and "line_capability" in text and "control_receipt" in text


def test_scout_instruction_names_the_draw_order_and_held_entries() -> None:
    from openlabs.program_flow import queue_scout_instruction

    text = queue_scout_instruction({"contact-binary-solution": "/q.json"},
                                   {"environment.standard_solver.spot_config": False})
    assert "rank is the draw order" in text and "held_candidates" in text
    assert "spot_config not met" in text and "control_status" in text
    assert "held_candidates" not in queue_scout_instruction({"t": "/q.json"})


def test_held_queue_entries_are_released_by_the_line_capability(tmp_path, monkeypatch):
    from openlabs.program_flow import held_queue_releases

    paths, db, settings, _ = _owner_program(tmp_path, monkeypatch)
    queue = tmp_path / "queue.json"
    key = "environment.standard_solver.spot_config"
    atomic_write_json(queue, {"candidates": [], "held_candidates": [
        {"entry_id": "TIC1", "draw_hold": {"reason": "needs_spot", "release_when": {
            "kind": "line_capability", "line": LINE, "key": key}}}]})
    _lines(paths, settings)
    assert held_queue_releases(paths, settings, LINE, {"t": str(queue)}) == {key: False}
    _lines(paths, settings, spot="astro-std-2")
    assert held_queue_releases(paths, settings, LINE, {"t": str(queue)}) == {key: True}
    assert held_queue_releases(paths, settings, LINE, {"t": str(tmp_path / "none.json")}) == {}
