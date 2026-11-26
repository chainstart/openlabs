"""UD-20261126-review-pass-two-minor (user 2026-11-26): "2个评审，只要都是小修以上就过关".

With both referees at minor revision or better the paper passes; the editor, the delivery
reader and the referees' own items are advice, except a hard error (``materiality.hard_error``).
A referee at major revision or reject keeps the paper in revision only through its substantive
items.
"""
from __future__ import annotations

from paper_writing import materiality as m
from paper_writing import review_flow as flow


def finding(**fields):
    row = {"repair": "Restate the conclusion.", "kind": "unsupported_claim", "category": "body_claim",
           "reader_misconclusion": "A reader would take the effect as general.", "location": "Discussion, para 2",
           "in_changed_region": False, "requests": ["text_edit"], "why_missed": "", "previous_item": ""}
    row.update(fields)
    return row


def report(recommendation, **dims):
    return {"recommendation": recommendation, "previous_items": [], "scores": {"overall": 7},
            "dimension_repairs": {"science": [], "readability": [], "formal_accuracy": [], **dims}}


def editor(**dims):
    return {"review_standard": "materiality_v1", "decision": "revise_before_submission",
            "desk_reject_category": "presentation",
            "dimension_repairs": {"science": [], "readability": [], "formal_accuracy": [], **dims}}


def reader(*repairs):
    return {"question": "q", "comparison": "c", "answer": "a", "meaning": "m", "repairs": list(repairs),
            "image_errors": []}


def blocking(merged):
    return [c for c in merged["required_changes"] if not c.get("advisory")]


def test_both_referees_minor_pass_even_if_the_editor_and_reader_want_revision():
    referees = {"referee_a": report("minor_revision", science=[finding()]),
                "referee_b": report("accept", readability=[finding(category="method_or_data")])}
    merged = flow.merge(editor(science=[finding(repair="Add a robustness check.", requests=["new_analysis"])]),
                        referees, reader_report=reader(finding(repair="Clarify the abstract.",
                                                               category="headline_claim", kind="advisory")))
    assert merged["outcome"] == "ready" and merged["next_action"] is None
    assert not blocking(merged)
    reasons = {c.get("downgrade_reason") for c in merged["required_changes"] if c.get("referee") != "delivery_reader"}
    assert "accepting_panel" in reasons and reasons <= {"accepting_panel", "accepting_readability"}


def test_referee_major_with_only_wording_items_passes():
    wording = [finding(category="wording", kind="advisory", reader_misconclusion=""),
               finding(category="style"), finding(category="definition_detail")]
    merged = flow.merge(editor(), {"referee_a": report("major_revision", readability=wording),
                                   "referee_b": report("minor_revision")})
    assert merged["outcome"] == "ready"


def test_referee_major_blocks_only_on_its_substantive_item():
    science = finding(repair="The pooled estimate does not support a causal reading; add the within-site test.",
                      category="method_or_data", requests=["new_analysis"])
    merged = flow.merge(editor(), {"referee_a": report("major_revision", science=[science],
                                                       readability=[finding(category="wording")]),
                                   "referee_b": report("minor_revision")})
    assert merged["outcome"] == "revision_required" and merged["next_action"] == "evidence_remediation"
    assert [c["change"] for c in blocking(merged)] == [science["repair"]]


def test_hard_errors_still_block_with_both_referees_at_minor():
    referees = {"referee_a": report("minor_revision"), "referee_b": report("accept")}
    for row in (finding(kind="numeric_or_statistical_error", category="figure_or_table"),
                finding(kind="figure_result_mismatch"), finding(kind="formula_error"),
                finding(kind="citation_nonexistent"), finding(kind="preregistration_violation")):
        merged = flow.merge(editor(science=[row]), referees)
        assert merged["outcome"] == "revision_required", row["kind"]
    # A headline claim the evidence does not support (claim-data mismatch) blocks too.
    headline = finding(category="headline_claim", location="Abstract")
    assert flow.merge(editor(), {"referee_a": report("minor_revision", science=[headline]),
                                 "referee_b": report("accept")})["outcome"] == "revision_required"
    # The delivery reader's own headline item stays advice.
    assert flow.merge(editor(), referees, reader_report=reader(headline))["outcome"] == "ready"


def test_formal_verifier_and_rejection_history_are_not_overridden():
    referees = {"referee_a": report("minor_revision"), "referee_b": report("accept")}
    formal = ["main:L10:abc: error — the stated bound is false"]
    merged = flow.merge(editor(), referees, formal_blockers=formal,
                        formal_summary={"by_category": {"scientific": formal}})
    assert merged["outcome"] == "formal_check_blocked"
    merged = flow.merge(editor(), referees, ["Prior editor: insufficient novelty remains unanswered"])
    assert merged["outcome"] == "rejection_history_blocked"


def test_followup_with_both_referees_accepting_drops_open_non_hard_items():
    item = "[evidence] Qualify the mechanism sentence."
    open_row = {"item": item, "resolved": False, "evidence": "The sentence is unchanged.",
                "reader_misconclusion": "A reader would take the mechanism as shown.",
                "kind": "unsupported_claim", "category": "body_claim", "requests": ["text_edit"]}
    resolved = dict(open_row, resolved=True, kind="advisory", requests=[])
    ed = {"review_standard": "materiality_v1", "decision": "send_to_review", "previous_items": [open_row],
          "new_findings": []}
    referees = {"referee_a": {"recommendation": "accept", "previous_items": [resolved], "new_findings": []},
                "referee_b": {"recommendation": "minor_revision", "previous_items": [open_row], "new_findings": []}}
    merged = flow.merge(ed, referees, followup_items=[item])
    assert merged["outcome"] == "ready"
    assert merged["unresolved_previous_items"][0]["downgrade_reason"] == "previous_accepting_panel"
    # A formal error tracked from the previous round is a hard error: it still blocks.
    error = "main:L667:5b6f58b465c9:F2: error — the variance formula is wrong"
    hard_row = dict(open_row, item=error, kind=None, category=None, requests=None)
    hard_row = {k: v for k, v in hard_row.items() if v is not None}
    ed["previous_items"] = [hard_row]
    referees["referee_b"]["previous_items"] = [hard_row]
    referees["referee_a"]["previous_items"] = [dict(hard_row, resolved=True)]
    assert flow.merge(ed, referees, followup_items=[error])["outcome"] == "revision_required"


def test_hard_error_list_is_narrow():
    assert m.HARD_KINDS == {"numeric_or_statistical_error", "formula_error", "figure_result_mismatch",
                            "preregistration_violation", "citation_nonexistent"}
    soft = m.normalize(finding(kind="citation_error_or_unsupported"), source="dimension", context=m.Context())
    assert not m.hard_error(soft)
