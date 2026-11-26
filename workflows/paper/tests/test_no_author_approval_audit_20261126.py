"""Author approval is out of scope (UD-20261126-no-author-approval-audit, user 2026-11-26 "1"):
作者签字确认不再列为必改项，最多作为提醒；作者同意由投稿前的人工审核和期刊投稿系统负责."""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from paper_writing import materiality as m
from paper_writing import review_flow as flow
from paper_writing import review_round_guard as guard

# The item the P5 chain round-7 editor and referee B kept (20261126T132103Z).
P5_ITEM = ("[evidence] Supply confirmation traceable to all six authors covering responsibility for and "
           "approval of the complete current manuscript, including the minimum-sector additions, and consent "
           "to submission; alternatively, supply existing authority delegated by each coauthor to the approving "
           "representative. Separate signatures are not intrinsically necessary, but the evidence must establish "
           "the collective approval or delegation requested. Reconcile the contribution statement with that "
           "evidence while preserving the complete AI disclosure and original-P5-only human "
           "computational-validation scope. (Statements and Declarations)")
SCIENCE_ITEM = "[evidence] The bound in Eq. (4) has the wrong sign; correct the derivation (Section 3)"


@pytest.mark.parametrize("text", [
    P5_ITEM,
    "Obtain approval of the final manuscript from all authors.",
    "Provide signatures of all coauthors.",
    "Show that each coauthor consented to submission.",
    "Supply authority delegated by every coauthor to the corresponding author.",
    "请提供全体作者签字确认",
])
def test_author_approval_requests_are_recognised(text):
    assert m.author_approval_request(text)


@pytest.mark.parametrize("text", [
    SCIENCE_ITEM,
    "Report the bootstrap confidence interval for the fitted slope.",
    "State that ethics approval was obtained and informed consent from participants.",
    "The contribution statement claims human verification of the code that did not happen; correct it.",
    "Name every AI tool and model used in the generative-AI declaration.",
    "Confirm by rerunning the fit that the bound holds.",
    "The result confirmed by the authors numerically must be shown in a table.",
    "请作者确认公式 (3) 的符号",
])
def test_other_requests_are_not(text):
    assert not m.author_approval_request(text)


def test_author_approval_finding_is_advice_for_every_source():
    review = {"repair": "Supply approval of the complete manuscript by all six authors.",
              "kind": "unsupported_claim", "category": "body_claim", "location": "Declarations",
              "reader_misconclusion": "An editor would think all authors approved.", "in_changed_region": True,
              "requests": ["new_artifact"], "why_missed": "New.", "previous_item": ""}
    for source in ("dimension", "new_finding", "reader"):
        assert m.decide(review, source=source, context=m.Context()).rule == "author_approval_out_of_scope"
    previous = {"item": P5_ITEM, "kind": "unsupported_claim", "category": "body_claim", "requests": ["new_artifact"],
                "evidence": "No record from each author.", "reader_misconclusion": "Editors would assume approval."}
    decision = m.decide(previous, source="previous", context=m.Context(followup_protocol=True))
    assert not decision.blocks and decision.rule == "author_approval_out_of_scope"
    # A genuine scientific item with the same fields still blocks.
    assert m.decide(dict(previous, item=SCIENCE_ITEM), source="previous", context=m.Context()).blocks
    assert m.decide(dict(review, repair="Correct the sign of the bound in Eq. (4)."), source="dimension",
                    context=m.Context()).blocks


def _decision(unresolved):
    return {"merged": {"scientific_blockers": [], "required_changes": [],
                       "unresolved_previous_items": [dict(item=text, advisory=False, resolved=False)
                                                     for text in unresolved]},
            "followup_items": []}


def test_an_earlier_decision_does_not_track_author_approval():
    last = _decision([P5_ITEM, SCIENCE_ITEM])
    assert flow.previous_tracked_items(last) == [SCIENCE_ITEM]
    assert flow.blocking_count(last["merged"]) == 1
    assert flow.item_is_advisory(P5_ITEM) and not flow.item_is_advisory(SCIENCE_ITEM)


LONG_OLD = "\\title{T}\n" + " ".join(f"word{i}" for i in range(1000)) + "\n"
LONG_NEW = "\\title{T}\n" + " ".join(f"other{i}" for i in range(1000)) + "\n"


def _check(tmp_path, items, raw=None):
    snapshot = tmp_path / "manuscript-expanded.tex"
    snapshot.write_text(LONG_OLD)
    last = {"_path": tmp_path / "decision.json", "round_evidence_files": {}, "figure_files": []}
    return guard.check(tmp_path, "p", "J", last, {"expanded": LONG_NEW, "figure_files": []}, {}, {}, raw,
                       items, {}, "digest", None, datetime.now(UTC), guard.settings({}))


def test_author_approval_item_does_not_trigger_the_rewrite_guard(tmp_path):
    result = _check(tmp_path, [P5_ITEM])
    assert result["required_items"] == [] and result["blockers"] == []
    # A response that still answers the out-of-scope item is not "unknown".
    raw = json.dumps({"decision_sha256": "digest", "items": [
        {"item": P5_ITEM, "status": "rebutted", "explanation": "Out of scope.", "evidence": []}]})
    assert _check(tmp_path, [P5_ITEM], raw)["blockers"] == []


def test_a_scientific_must_fix_still_needs_an_answer_but_may_rewrite(tmp_path):
    # UD-20261126-review-pass-two-minor: a revision answering a substantive scientific must-fix
    # is not held by the 15% rewrite share; it must still be answered in the response.
    blockers = _check(tmp_path, [P5_ITEM, SCIENCE_ITEM])["blockers"]
    assert not any("separate rounds" in b for b in blockers)
    assert any("Provide --response" in b for b in blockers)
