"""Cold read of the title and abstract (pipeline slimming 2026-11-26, report section 4a).

The rejected 20260415aiuncertainty0003 was cleared by an editor who restated what was derived,
not what problem it solves, and who could lean on the introduction. Editor step 1 now states
the problem from the title and abstract alone; the delivery reader says whether they state it.
Both go through existing outcomes: ``revise_before_submission`` and the materiality table.
"""
from __future__ import annotations

from paper_writing import materiality, reader_check
from paper_writing import review_flow as flow

from test_review_flow import editor, referee


def test_editor_who_cannot_state_the_problem_does_not_send_to_review():
    report = referee("accept")
    screen = {**editor(), "presentation_fails_restatement": True,
              "presentation_problems": ["The abstract never says whose decision the bound serves."]}
    merged = flow.merge(screen, {"a": report, "b": report})
    assert merged["outcome"] == "revise_before_submission"
    assert merged["next_action"] == "text_revision"
    assert flow.merge({**screen, "presentation_fails_restatement": False},
                      {"a": report, "b": report})["outcome"] == "ready"


def test_reader_schema_and_prompt_ask_the_cold_read():
    assert reader_check.QUESTION_FIELD == "question_stated_in_title_abstract"
    assert set(reader_check.QUESTION_SCHEMA["required"]) == {"stated", "quote"}
    editor_md = (flow.PROMPTS / "editor.md").read_text()
    assert "Read the title and abstract alone first" in editor_md
    assert "Read the title, abstract and opening against the decisive panel" not in editor_md


def test_unstated_question_is_a_headline_finding_of_the_reader():
    stated = {"question_stated_in_title_abstract": {"stated": True, "quote": "Which ranking?"}}
    assert materiality.question_finding(stated) == []
    assert materiality.question_finding({}) == []  # a review started before the field existed
    finding, = materiality.question_finding(
        {"question_stated_in_title_abstract": {"stated": False, "quote": ""}})
    assert finding["category"] == "headline_claim" and finding["reader_misconclusion"]
    first_round = materiality.decide(finding, source="reader", context=materiality.Context())
    assert first_round.blocks
    # Existing rules still apply: with every referee accepting, the reader's items are advice.
    accepting = materiality.decide(finding, source="reader",
                                   context=materiality.Context(accepting=True))
    assert not accepting.blocks and accepting.rule == "accepting_reader"


def test_reader_without_the_question_blocks_a_ready_merge():
    merged = dict(outcome="ready", required_changes=[], scientific_blockers=[],
                  referee_recommendations={"a": "major_revision"})
    recall = {"question": "q", "comparison": "c", "answer": "a", "meaning": "m", "repairs": [],
              "question_stated_in_title_abstract": {"stated": False, "quote": ""}}
    flow._merge_reader(merged, recall)
    assert merged["outcome"] == "revision_required" and merged["next_action"] == "text_revision"
    assert merged["dimension_repairs"]["readability"][0]["category"] == "headline_claim"
