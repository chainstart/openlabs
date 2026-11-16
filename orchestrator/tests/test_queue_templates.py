"""Enumerated multi-template lines (2026-11-16, queue qp-2.0): reopening cards copied from a
queue entry, two templates sharing targets, and per-template draw state."""

from __future__ import annotations

import json
from pathlib import Path

import test_research_lines as lines_tests
import test_research_program_flow as flow
from openlabs.program import open_topic_ledger
from openlabs.program_flow import (
    _record_template_draws,
    intake_card,
    queue_scout_instruction,
    template_supply,
)
from openlabs.projects import load_project
from test_owner_mode import _first_seat, _owner_program, _seat_packet
from test_program_autonomy import _topic
from test_research_program_flow import _tick

NEW_METHOD = {"type": "new_method",
              "description": "New card under template v2: profile-likelihood endpoint, no "
                             "absolute control tolerance; the frozen record is unchanged."}


def _project(paths):
    return load_project(paths.data / "workspaces" / "ai" / "projects" / "research-program"
                        / "project.json")


def _receipt(paths) -> None:
    receipt = paths.data / "receipts" / "data-access.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_bytes(flow.RECEIPT)


def _frozen(tmp_path, monkeypatch, **packet):
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _seat_packet(db, paths, seat["task_id"], {
        "status": "frozen", "freeze_reason_class": "feasibility_precheck_failed",
        "reason": "Absolute control tolerance missed.", **packet}, session="s1", artifact=True)
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    assert _topic(paths, settings, topic["topic_id"])["status"] == "frozen"
    _receipt(paths)
    return paths, db, settings, topic


def test_a_queue_card_with_reopens_and_new_method_supersedes_the_frozen_topic(
    tmp_path, monkeypatch
):
    paths, db, settings, topic = _frozen(tmp_path, monkeypatch)
    # Same question, data and endpoint (same fingerprint): a duplicate unless it reopens.
    reworded = flow._card(0, flow.RECEIPT_SHA)
    reworded["cost_estimate"]["basis"] = "A different estimate wording."
    duplicate = intake_card(db, paths, settings, _project(paths), reworded,
                            decided_by="manual:dup", provider="human", source_task_id=None,
                            receipt_digests=None)
    assert duplicate["status"] == "rejected" and duplicate["reason"] == "duplicate_fingerprint"
    card = flow._card(0, flow.RECEIPT_SHA, reopens=topic["topic_id"], reopen_basis=NEW_METHOD)
    outcome = intake_card(db, paths, settings, _project(paths), card, decided_by="scout:1",
                          provider="openai-codex", source_task_id=None, receipt_digests=None)
    assert outcome["status"] == "proposed", outcome
    ledger = open_topic_ledger(paths, settings.program)
    reopening = ledger.topic(outcome["topic_id"])
    assert reopening["supersedes"] == topic["topic_id"]
    stored = json.loads(Path(reopening["card_path"]).read_text(encoding="utf-8"))
    assert stored["reopens"] == topic["topic_id"] and stored["reopen_basis"] == NEW_METHOD
    assert ledger.topic(topic["topic_id"])["status"] == "frozen"  # the record is unchanged


def test_a_reopen_basis_the_frozen_topic_did_not_allow_is_refused(tmp_path, monkeypatch):
    paths, db, settings, topic = _frozen(tmp_path, monkeypatch, reopen_conditions=[
        {"type": "external_result", "description": "A spectroscopic q is published."}])
    card = flow._card(0, flow.RECEIPT_SHA, reopens=topic["topic_id"], reopen_basis=NEW_METHOD)
    outcome = intake_card(db, paths, settings, _project(paths), card, decided_by="scout:1",
                          provider="openai-codex", source_task_id=None, receipt_digests=None)
    assert outcome["status"] == "rejected"
    assert outcome["reason"] == "reopen_basis_not_declared_by_frozen_topic"


def test_one_target_in_two_templates_is_two_topics(tmp_path, monkeypatch) -> None:
    paths, db, settings = lines_tests._line_setup(tmp_path, "ready")
    _receipt(paths)
    project = _project(paths)
    single = lines_tests._line_card(
        0, paper_template="contact-binary-solution",
        candidate_queue_entry={"entry_id": "TIC441806604"},
        occupancy_search={"queries": ["TIC 441806604"], "databases": ["SIMBAD"],
                          "searched_at": "2026-11-13", "findings": "batch only"})
    audit = lines_tests._line_card(
        1, paper_template="nn-catalogue-audit",
        candidate_queue_entry={"entry_id": "NNAUDIT-J_ApJS_277_51-B1"},
        series={"members": ["TIC441806604", "TIC229791283"],
                "shared_pipeline": "refine + qprofile_run + nnaudit"},
        occupancy_search={"queries": ["citing 2025ApJS..277...51L"], "databases": ["ADS"],
                          "searched_at": "2026-11-16", "findings": "no independent test"})
    outcomes = [intake_card(db, paths, settings, project, card, decided_by=f"scout:{n}",
                            provider="openai-codex", source_task_id=None, receipt_digests=None)
                for n, card in enumerate((single, audit))]
    assert [item["status"] for item in outcomes] == ["proposed", "proposed"], outcomes


def _queue(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"metadata": {}, "candidates": entries}), encoding="utf-8")


def test_per_template_draw_state_and_the_scout_instruction(tmp_path) -> None:
    paths = flow._paths(tmp_path)
    single = tmp_path / "queue" / "queue.json"
    batches = tmp_path / "queue" / "nn_audit_batches.json"
    _queue(single, [{"entry_id": "TIC1", "rank": 1, "ledger_occupancy": {"state": "free"}},
                    {"entry_id": "TIC2", "rank": 2,
                     "ledger_occupancy": {"state": "reopenable"}},
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
    queues = {"contact-binary-solution": str(single), "nn-catalogue-audit": str(batches)}
    supply = template_supply(queues)
    assert supply["contact-binary-solution"]["drawable"] == 2
    assert supply["nn-catalogue-audit"]["drawable"] == 1
    settings = flow._settings()
    # A scout that drew an audit card: the audit template resets, the other counts one.
    card = tmp_path / "card.json"
    card.write_text(json.dumps({"paper_template": "nn-catalogue-audit"}))
    state: dict = {}
    _record_template_draws(paths, settings, lines_tests.LINE, state,
                           [{"card_path": str(card)}])
    assert {k: v["count"] for k, v in state["templates"].items()} == {
        "contact-binary-solution": 1, "nn-catalogue-audit": 0}
    _record_template_draws(paths, settings, lines_tests.LINE, state, [])
    assert state["templates"]["contact-binary-solution"]["count"] == 2
    # A changed queue file restarts that template's count.
    _queue(single, [{"entry_id": "TIC9", "rank": 1}])
    _record_template_draws(paths, settings, lines_tests.LINE, state, [])
    assert state["templates"]["contact-binary-solution"]["count"] == 1
    assert state["templates"]["nn-catalogue-audit"]["count"] == 2
    text = queue_scout_instruction(queues, None, {
        "contact-binary-solution": {"drawable": 1, "empty_draws": 1},
        "nn-catalogue-audit": {"drawable": 1}})
    assert "contact-binary-solution: 1 drawable, 1 empty draw(s)" in text
    assert "nn-catalogue-audit: 1 drawable." in text
    assert "own queue and its own card rules" in text
