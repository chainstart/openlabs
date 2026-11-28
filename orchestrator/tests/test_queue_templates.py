"""Reopening frozen topics and multi-queue candidate injection."""

from __future__ import annotations

import json
from pathlib import Path

import test_research_lines as lines_tests
import test_research_program_flow as flow
from openlabs.program import REJECTION_DUPLICATE_TOPIC, open_topic_ledger
from openlabs.program_flow import intake_proposal, queue_candidates
from openlabs.projects import load_project
from test_owner_mode import _first_seat, _owner_program, _seat_packet
from test_program_autonomy import _topic
from test_research_program_flow import _tick


def _project(paths):
    return load_project(paths.data / "workspaces" / "ai" / "projects" / "research-program"
                        / "project.json")


def _frozen(tmp_path, monkeypatch, **packet):
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _seat_packet(db, paths, seat["task_id"], {
        "status": "frozen", "freeze_reason_class": "method_capability",
        "reason": "Absolute control tolerance missed.", **packet}, session="s1", artifact=True)
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    assert _topic(paths, settings, topic["topic_id"])["status"] == "frozen"
    return paths, db, settings, topic


def test_a_proposal_with_reopens_supersedes_the_frozen_topic(tmp_path, monkeypatch):
    paths, db, settings, topic = _frozen(tmp_path, monkeypatch)
    reworded = flow._proposal(0, brief=flow._brief(0) + "\nReworded note.\n")
    duplicate = intake_proposal(db, paths, settings, _project(paths), reworded,
                                decided_by="manual:dup", provider="human", source_task_id=None)
    assert duplicate["status"] == "rejected" and duplicate["reason"] == REJECTION_DUPLICATE_TOPIC

    reopened = flow._proposal(0, brief=flow._brief(0) + "\nNew solver ready.\n",
                              reopens=topic["topic_id"])
    outcome = intake_proposal(db, paths, settings, _project(paths), reopened,
                              decided_by="scout:1", provider="openai-codex", source_task_id=None)
    assert outcome["status"] == "proposed", outcome
    ledger = open_topic_ledger(paths, settings.program)
    reopening = ledger.topic(outcome["topic_id"])
    assert reopening["supersedes"] == topic["topic_id"]
    stored = json.loads(Path(reopening["card_path"]).read_text(encoding="utf-8"))
    assert stored["reopens"] == topic["topic_id"]
    assert ledger.topic(topic["topic_id"])["status"] == "frozen"


def test_two_distinct_queue_entries_register_as_two_topics(tmp_path, monkeypatch) -> None:
    paths, db, settings = lines_tests._line_setup(tmp_path, "ready")
    project = _project(paths)
    single = lines_tests._line_card(0, queue_entry_id="TIC441806604")
    audit = lines_tests._line_card(1, queue_entry_id="NNAUDIT-J_ApJS_277_51-B1")
    outcomes = [intake_proposal(db, paths, settings, project, card, decided_by=f"scout:{n}",
                                provider="openai-codex", source_task_id=None)
                for n, card in enumerate((single, audit))]
    assert [item["status"] for item in outcomes] == ["proposed", "proposed"], outcomes


def _queue(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"metadata": {}, "candidates": entries}), encoding="utf-8")


def test_multi_queue_candidate_injection_collects_free_and_reopenable_entries(tmp_path) -> None:
    paths = flow._paths(tmp_path)
    single = tmp_path / "queue" / "queue.json"
    batches = tmp_path / "queue" / "nn_audit_batches.json"
    _queue(single, [{"entry_id": "TIC1", "rank": 1, "ledger_occupancy": {"state": "free"}},
                    {"entry_id": "TIC2", "rank": 2,
                     "ledger_occupancy": {"state": "reopenable", "reopens": "topic-old"}},
                    {"entry_id": "TIC3", "rank": 3,
                     "ledger_occupancy": {"state": "in_flight"}}])
    _queue(batches, [{"entry_id": "B1", "rank": 1}])
    path = paths.data / "registry" / "research-lines.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "schema_version: openlabs.research_lines.v1\nlines:\n"
        f"  - id: {lines_tests.LINE}\n    host_domain: ai\n    title: t\n"
        "    paper_templates:\n"
        f"      - id: contact-binary-solution\n        candidate_queue: {single}\n"
        f"      - id: nn-catalogue-audit\n        candidate_queue: {batches}\n"
        "    environment: {status: ready}\n", encoding="utf-8")
    settings = flow._settings()
    candidates = queue_candidates(paths, settings, lines_tests.LINE, {"topics": []})
    assert [c["entry_id"] for c in candidates] == ["TIC1", "TIC2", "B1"]
    assert candidates[1]["reopens"] == "topic-old"
