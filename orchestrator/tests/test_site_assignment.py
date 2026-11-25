"""Site submitter assignments follow readiness; operator registration of a submission (2026-11-23)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from openlabs import program_autonomy, site_assignment
from openlabs.engine import TickReport
from openlabs.program import mark_topic_in_review, mark_topic_ready
from openlabs.site_assignment import SiteAssignmentError, mark_submitted, sync_tick
from test_program_slots import _active_topic, _setup

PAPER = "paper-1"


def _ready_topic(tmp_path, **program):
    paths, db, program_settings, ledger = _setup(tmp_path, **program)
    _active_topic(paths, db, program_settings, ledger, 1)
    mark_topic_in_review(ledger, "topic-1", db=db, decided_by="r")
    mark_topic_ready(ledger, "topic-1", db=db, decided_by="r2", paper_id=PAPER)
    return paths, db, SimpleNamespace(program=program_settings), ledger


def test_tick_applies_the_sync_and_notes_changes(tmp_path, monkeypatch) -> None:
    paths, db, settings, ledger = _ready_topic(tmp_path, auto_handoff=True)
    monkeypatch.setenv("ARA_PAPER_MANAGE_API_URL", "https://manage.invalid")
    monkeypatch.setenv("ARA_PAPER_MANAGE_API_KEY", "k")
    calls = []

    def fake(paths_, settings_, arguments, environment=None, **_):
        calls.append((arguments, dict(environment or {})))
        return {"ok": True, "papers": [{}], "errors": [], "blocked": [], "changed": [
            {"paper_id": PAPER, "action": "park", "reasons": ["site readiness is not true"],
             "default_submitter": {"name": "詹静怡", "source": "current_assignee"},
             "assignment_id": "a1", "applied": True}]}

    monkeypatch.setattr(program_autonomy, "_run_paper_command", fake)
    report = TickReport()
    sync_tick(db, paths, settings, report)
    arguments, environment = calls[0]
    assert arguments[:2] == ["program", "sync-site-assignments"] and "--apply" in arguments
    assert environment["OPENLABS_ENABLE_EXTERNAL_WRITES"] == "1"
    info = report.program["site_assignments"]
    assert info["outcome"] == "ok" and info["changed"][0]["action"] == "park"
    history = ledger.topic("topic-1")["history"]
    assert history[-1]["kind"] == "site_assignment_parked"
    # The same change noted again is not duplicated.
    sync_tick(db, paths, settings, TickReport())
    assert sum(1 for h in ledger.topic("topic-1")["history"]
               if h.get("kind") == "site_assignment_parked") == 1


def test_tick_follows_its_own_switch_not_auto_handoff_and_failures_stay_out_of_errors(
        tmp_path, monkeypatch) -> None:
    # B1 (2026-11-25): auto_handoff = false holds deliveries, not the submitter reconciliation.
    paths, db, settings, _ = _ready_topic(tmp_path, auto_handoff=False)
    assert settings.program.site_assignment_sync is True
    calls = []
    monkeypatch.setenv("ARA_PAPER_MANAGE_API_URL", "https://manage.invalid")
    monkeypatch.setenv("ARA_PAPER_MANAGE_API_KEY", "k")
    monkeypatch.setattr(program_autonomy, "_run_paper_command",
                        lambda *a, **k: calls.append(a) or {"ok": True, "papers": [],
                                                             "changed": [], "held": ["p"]})
    report = TickReport()
    sync_tick(db, paths, settings, report)
    assert calls and report.program["site_assignments"]["outcome"] == "ok"
    assert report.program["site_assignments"]["held"] == ["p"]
    paths, db, settings, _ = _ready_topic(tmp_path / "off", auto_handoff=True,
                                          site_assignment_sync=False)
    report = TickReport()
    sync_tick(db, paths, settings, report)
    assert report.program["site_assignments"]["outcome"] == "skipped_site_assignment_sync_off"
    paths, db, settings, _ = _ready_topic(tmp_path / "b", auto_handoff=True)
    monkeypatch.delenv("ARA_PAPER_MANAGE_API_URL", raising=False)
    monkeypatch.delenv("ARA_PAPER_MANAGE_API_KEY", raising=False)
    report = TickReport()
    sync_tick(db, paths, settings, report)
    assert report.program["site_assignments"]["outcome"] == "failed"
    assert report.errors == []


def test_mark_submitted_moves_ready_queue_to_submitted_with_a_receipt(tmp_path) -> None:
    paths, db, settings, ledger = _ready_topic(tmp_path)
    evidence = paths.data / "papers" / PAPER / "revisions" / "SUBMITTED-site-receipt.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("{}")
    result = mark_submitted(db, paths, settings, paper_id=PAPER, journal="New Astronomy",
                            by="main-session", reason="投稿人已投 v0.1.18",
                            submitted_by="Zhidong Cheng", version="0.1.18",
                            evidence=[f"papers/{PAPER}/revisions/SUBMITTED-site-receipt.json"])
    assert result["status"] == "submitted"
    topic = ledger.topic("topic-1")
    assert topic["status"] == "submitted"
    receipt = json.loads(open(result["receipt"], encoding="utf-8").read())
    assert receipt["journal"] == "New Astronomy" and receipt["version"] == "0.1.18"
    assert receipt["evidence"][0]["path"].endswith("SUBMITTED-site-receipt.json")
    assert topic["history"][-1]["kind"] == "submission_registered"
    again = mark_submitted(db, paths, settings, paper_id=PAPER, journal="New Astronomy",
                           by="x", reason="again")
    assert again["status"] == "already_submitted"


def test_mark_submitted_refuses_a_topic_not_in_the_ready_queue(tmp_path) -> None:
    paths, db, program_settings, ledger = _setup(tmp_path)
    _active_topic(paths, db, program_settings, ledger, 1)
    ledger_doc = ledger.read()
    assert ledger_doc["topics"][0]["status"] == "active"
    with pytest.raises(SiteAssignmentError):
        mark_submitted(db, paths, SimpleNamespace(program=program_settings), paper_id=PAPER,
                       journal="J", by="x", reason="y")


def test_cli_parses_both_commands() -> None:
    from openlabs.__main__ import _parser as build_parser

    parser = build_parser()
    args = parser.parse_args(["program", "sync-site-assignments", "--paper-id", PAPER])
    assert args.paper_id == [PAPER] and not args.apply
    args = parser.parse_args(["program", "mark-submitted", "--paper-id", PAPER, "--journal", "J",
                              "--by", "me", "--reason", "r"])
    assert args.journal == "J"
    assert site_assignment.SiteAssignmentError is SiteAssignmentError
