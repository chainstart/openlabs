"""Card shapes the control plane fixes itself instead of sending to topic_card_repair.

2026-11-16: the astro line's first scout after the restart wrote 4 contact-binary-solution v2
cards with ``venues.routine`` as bare names (the template lists them so) and
``feasibility_precheck.budget`` as an object; every card went to a light-model repair (4 calls,
1 needs_replan, only 1 card through). Both are shapes, not content: they are normalized and
noted in ``card_check.normalized``.
"""

from __future__ import annotations

import json
from pathlib import Path

import test_research_lines as lines_tests
import test_research_program_flow as flow
from openlabs.card_precheck import fill_precheck_budget
from openlabs.contracts import budget_text, normalize_topic_card, validate_topic_card
from openlabs.program import open_topic_ledger
from openlabs.program_flow import intake_card
from openlabs.projects import load_project

FIXTURE = Path(__file__).parent / "fixtures" / "astro_scout_cards_20261116.json"
SHAPE_ERRORS = {
    "venues.routine needs a named routine target venue (two preferred)",
    "feasibility_precheck.budget is missing",
}


def _real_cards() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["cards"]


def test_the_four_real_scout_cards_validate_after_normalization() -> None:
    cards = _real_cards()
    assert len(cards) == 4
    for card in cards:
        before = set(validate_topic_card(card, current_year=2026).errors)
        assert before == SHAPE_ERRORS  # exactly what the 4 repairs were sent for
        fixed, notes = normalize_topic_card(card)
        assert validate_topic_card(fixed, current_year=2026).errors == ()
        assert fixed["venues"]["routine"] == [
            {"name": "Astrophysics and Space Science"}, {"name": "New Astronomy"}]
        budget = fixed["feasibility_precheck"]["budget"]
        assert budget.startswith("agent seconds 5400; ailab cpus 4")
        assert fixed["feasibility_precheck"]["budget_detail"] == card[
            "feasibility_precheck"]["budget"]  # the numbers are kept
        assert any("venues.routine[0]" in note for note in notes)
        assert any("budget object written as text" in note for note in notes)


def test_normalization_does_not_invent_a_venue_or_a_budget() -> None:
    card = _real_cards()[0]
    card["venues"]["routine"] = ["", None]
    card["feasibility_precheck"]["budget"] = {}
    fixed, _notes = normalize_topic_card(card)
    errors = set(validate_topic_card(fixed, current_year=2026).errors)
    assert SHAPE_ERRORS <= errors
    assert budget_text({"note": ""}) == ""
    assert budget_text(3600) == "3600"


def test_a_missing_budget_is_filled_only_from_the_line_spec() -> None:
    card = {"feasibility_precheck": {"description": "d", "pass_criterion": "p"}}
    untouched, notes = fill_precheck_budget(card, {}, {})
    assert "budget" not in untouched["feasibility_precheck"] and notes == []
    filled, notes = fill_precheck_budget(
        card, {"feasibility_precheck_budget": "line text"},
        {"feasibility_precheck_budget": {"agent_seconds": 5400, "cpu_core_hours": 40}})
    assert filled["feasibility_precheck"]["budget"] == "agent seconds 5400; cpu core hours 40"
    assert notes == ["feasibility_precheck.budget filled from the template "
                     "feasibility_precheck_budget"]
    stated = {"feasibility_precheck": {"budget": "card's own"}}
    assert fill_precheck_budget(stated, {"feasibility_precheck_budget": "x"}, {})[0] == stated


def test_intake_registers_such_a_card_without_a_repair(tmp_path, monkeypatch) -> None:
    paths, db, settings = lines_tests._line_setup(tmp_path, "ready")
    receipt = paths.data / "receipts" / "data-access.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_bytes(flow.RECEIPT)
    project = load_project(paths.data / "workspaces" / "ai" / "projects" / "research-program"
                           / "project.json")
    card = lines_tests._line_card(0)
    card["venues"]["routine"] = [item["name"] for item in card["venues"]["routine"]]
    card["feasibility_precheck"]["budget"] = {"agent_seconds": 7200, "gpu_hours": 1,
                                              "note": "queued time excluded"}
    outcome = intake_card(db, paths, settings, project, card, decided_by="scout:1",
                          provider="openai-codex", source_task_id="topic-scout:1",
                          receipt_digests=None)
    assert outcome["status"] == "proposed", outcome
    assert outcome["errors"] == []
    topic = open_topic_ledger(paths, settings.program).topic(outcome["topic_id"])
    normalized = topic["card_check"]["normalized"]
    assert any("venues.routine[1]" in note for note in normalized)
    assert any("budget object written as text" in note for note in normalized)
    assert "card_repair" not in topic or not topic["card_repair"]
    with db.connect() as connection:
        repairs = connection.execute(
            "SELECT COUNT(*) FROM tasks WHERE task_type='topic_card_repair'").fetchone()[0]
    assert repairs == 0
