"""The materiality decision table (B6, 2026-11-25): structured fields decide, keyword patterns
only classify records written before the fields existed."""
from __future__ import annotations

import dataclasses

import pytest

from paper_writing import formal_checks
from paper_writing import materiality as m
from paper_writing import presentation
from paper_writing import review_flow as flow
from paper_writing.review_launcher import _validate_against_schema

FOLLOWUP = m.Context(followup=True, prior_items=frozenset({"[evidence] old item"}), followup_protocol=True,
                     changed_text=m.plain("We now state that the shift is at most 0.1 point in every tier."))
ACCEPTING = m.Context(accepting=True, dimensions_clear=True, science_clear=True)


def finding(**fields):
    row = {"repair": "Correct the sentence.", "kind": "unsupported_claim", "category": "body_claim",
           "reader_misconclusion": "A reader would take the bound as proven.", "location": "Section 4",
           "in_changed_region": False, "requests": ["text_edit"], "why_missed": "", "previous_item": ""}
    row.update(fields)
    return row


def new_finding(**fields):
    row = {"kind": "unsupported_claim", "category": "body_claim", "location": "Section 4",
           "finding": "The new sentence “the shift is at most 0.1 point in every tier” is wrong: 0.152.",
           "reader_misconclusion": "A reader would understate the shift.", "in_changed_region": True,
           "requests": ["text_edit"], "why_missed": "The sentence is new in this revision."}
    row.update(fields)
    return row


def rule(raw, source="dimension", context=m.Context(), **kwargs):
    return m.decide(raw, source=source, context=context, **kwargs).rule


def test_table_is_ordered_and_ends_with_a_catch_all():
    assert len(set(m.RULE_IDS)) == len(m.RULE_IDS)
    assert m.RULES[-1].id == "material" and m.RULES[-1].verdict == m.BLOCK
    assert m.HARD_KINDS <= set(m.FINDING_KINDS) and "citation_nonexistent" in m.HARD_KINDS
    assert {row["rule"] for row in m.explain()} == set(m.RULE_IDS)


@pytest.mark.parametrize("kind", sorted(m.HARD_KINDS))
def test_hard_kinds_block_under_every_panel_rule(kind):
    context = m.Context(followup=True, prior_items=frozenset(), changed_text="unrelated text",
                        accepting=True, final_check=True, science_clear=True, dimensions_clear=True)
    raw = new_finding(kind=kind, in_changed_region=False, requests=["text_edit"])
    assert m.decide(raw, source="new_finding", context=context).blocks
    reader = finding(kind=kind, why_missed="New.", requests=["text_edit"])
    assert rule(reader, "reader", context) == "hard_kind"
    # UD-20261126-review-pass-two-minor: with both referees at minor or better, an error that lives
    # only in the archive or the response does not make the paper wrong; it is advice.
    archive = new_finding(kind=kind, in_changed_region=False, requests=["archive_or_response_format"])
    assert rule(archive, "new_finding", context) == "accepting_archive_only"
    assert rule(archive, "new_finding", dataclasses.replace(context, accepting=False)) == "hard_kind"


def test_a_blocker_needs_a_reader_misconclusion():
    assert rule(finding(reader_misconclusion="")) == "no_reader_misconclusion"
    assert rule(finding(kind="numeric_or_statistical_error", reader_misconclusion="")) == "no_reader_misconclusion"
    assert rule(finding()) == "material"


def test_form_categories_and_advisory_kind_are_advice():
    for category in ("wording", "definition_detail", "caption_detail", "style", "length"):
        assert rule(finding(category=category)) == "form_category"
    assert rule(finding(kind="advisory")) == "classified_advisory"


def test_requests_for_length_or_the_archive_only_are_advice():
    assert rule(finding(requests=["length"]), dimension="readability") == "length_only"
    assert rule(finding(requests=["length"]), dimension="science") == "material"
    assert rule(finding(requests=["length", "text_edit"]), dimension="readability") == "material"
    # The reader sees only the manuscript (TIC 421871796 R5/R6, structured form).
    reader = finding(requests=["archive_or_response_format"], why_missed="New.")
    assert rule(reader, "reader") == "reader_cannot_see"
    assert rule(finding(category="archive_or_response_format", requests=[]), "reader") == "reader_cannot_see"
    # Editor and referees: advice once the science is clear and the panel accepts.
    assert rule(finding(requests=["archive_or_response_format"]), context=ACCEPTING,
                dimension="readability") == "accepting_documentation"
    assert rule(finding(requests=["archive_or_response_format"]), dimension="readability") == "material"


def test_followup_new_finding_must_concern_changed_text():
    assert m.decide(new_finding(), source="new_finding", context=FOLLOWUP).blocks
    assert rule(new_finding(in_changed_region=False), "new_finding", FOLLOWUP) == "outside_changed_region"
    # The flag alone is not enough: the quoted text must be among the added lines.
    unquoted = new_finding(finding="The bound is overstated.", location="Section 4")
    assert rule(unquoted, "new_finding", FOLLOWUP) == "outside_changed_region"
    assert rule(new_finding(why_missed=""), "new_finding", FOLLOWUP) == "new_without_why_missed"


def test_accepting_panel_unsupported_claim_body_versus_headline():
    context = m.Context(followup=True, prior_items=frozenset(), accepting=True)
    assert rule(new_finding(), "new_finding", context) == "accepting_unsupported"
    assert rule(new_finding(category="headline_claim"), "new_finding", context) == "material"
    # A false bound typed as a formula error blocks (NEM settlement R2 "benchmark bounds").
    assert rule(new_finding(kind="formula_error"), "new_finding", context) == "hard_kind"


def test_legacy_records_use_the_keyword_fallback():
    legacy = {"kind": "substantive", "repair": "Quote entry C5 verbatim in the response.",
              "wrong_conclusion": "The archive would seem stale.", "why_missed": "", "previous_item": ""}
    assert not m.structured(legacy)
    assert rule(legacy, "reader") == "reader_cannot_see"
    assert rule(dict(legacy, kind="wording"), "reader") == "classified_advisory"
    present = dict(legacy, repair="The value in the response still contradicts Table 2; quote it verbatim.")
    assert rule(present, "reader") == "material"
    # Legacy follow-up findings located in the title or abstract are headline claims.
    old = {"kind": "unsupported_claim", "location": "Abstract, fourth sentence",
           "finding": "Overstated.", "reader_misconclusion": "Proven bound.", "why_missed": "New."}
    context = m.Context(followup=True, prior_items=frozenset(), accepting=True)
    assert rule(old, "new_finding", context) == "material"
    assert rule(dict(old, location="Discussion §5.3"), "new_finding", context) == "accepting_unsupported"


def test_previous_items():
    row = {"item": "[evidence] old item", "resolved": False, "evidence": "Still wrong.",
           "reader_misconclusion": "Wrong bound."}
    assert rule(row, "previous", FOLLOWUP) == "previous_open"
    assert rule(dict(row, evidence=""), "previous", FOLLOWUP) == "previous_incomplete"
    archive = dict(row, kind="unsupported_claim", category="archive_or_response_format", requests=[])
    assert rule(archive, "previous", ACCEPTING) == "previous_accepting_documentation"
    hard = dict(archive, kind="numeric_or_statistical_error")
    # Archive-only error with both referees at minor or better: advice (UD-20261126); in the
    # manuscript, or with a referee wanting more, it blocks.
    assert rule(hard, "previous", ACCEPTING) == "accepting_archive_only"
    assert rule(dict(hard, category="body_claim"), "previous", ACCEPTING) == "previous_hard_kind"
    assert rule(hard, "previous", m.Context()) == "previous_hard_kind"


def test_formal_and_presentation_rows():
    kinds = {"L1": "unsupported_claim"}
    context = m.Context(formal_kinds=kinds)
    assert rule({"category": "scientific", "status": "gap", "location": "L9"}, "formal") == "formal_precision"
    assert rule({"category": "scientific", "status": "error", "location": "L1"}, "formal", context) == "formal_precision"
    assert rule({"category": "scientific", "status": "error", "location": "L2"}, "formal", context) == "formal_material"
    assert rule({"category": "source_routing", "location": "k"}, "formal") == "formal_source_routing"
    assert rule({"category": "technical", "location": "L1"}, "formal") == "formal_material"
    assert rule({"category": "technical", "location": "L1"}, "formal",
                m.Context(accepting=True)) == "formal_accepting_technical"
    assert rule({"category": "scientific", "status": "error", "location": "L2"}, "formal",
                m.Context(accepting=True)) == "formal_material"
    assert formal_checks.precision_finding({"category": "scientific", "status": "gap", "location": "x"})
    item = {"location": "Fig. 2", "repair": "Panel b disagrees with Table 2.", "category": "claim_or_data_mismatch",
            "blocking": True, "previous_item": 0}
    assert presentation.is_blocking(item)
    assert not presentation.is_blocking(dict(item, reader_misconclusion=""))
    assert presentation.is_blocking(dict(item, reader_misconclusion="Readers take the wrong value."))
    assert not presentation.is_blocking(dict(item, category="layout"))
    assert not presentation.is_blocking(item, previous=[])


def test_live_schemas_require_the_structured_fields():
    for field in ("kind", "category", "reader_misconclusion", "location", "in_changed_region", "requests"):
        assert field in flow.DIMENSION_FINDING["required"]
        if field != "reader_misconclusion":
            assert field in flow._FOLLOWUP_FINDING["required"]
    previous = {"items": ["[evidence] old item"]}
    schema = flow.followup_schema(flow.referee_schema_for_previous(previous), previous)
    row = {"item": "[evidence] old item", "resolved": False, "evidence": "Still wrong.",
           "reader_misconclusion": "Wrong bound.", "kind": "formula_error", "category": "body_claim",
           "requests": ["text_edit"]}
    _validate_against_schema([row], schema["properties"]["previous_items"])
    assert "reader_misconclusion" in presentation.REVIEW_SCHEMA["properties"]["form_repairs"]["items"]["required"]


def test_structured_first_round_decision():
    def report(rec, **dims):
        return {"recommendation": rec, "previous_items": [],
                "dimension_repairs": {"science": [], "readability": [], "formal_accuracy": [], **dims}}
    editor = {"review_standard": "materiality_v1", "decision": "send_to_review",
              "dimension_repairs": {"science": [], "readability": [], "formal_accuracy": []}}
    readable = finding(category="body_claim")
    merged = flow.merge(editor, {"referee_a": report("minor_revision", readability=[readable])})
    assert merged["outcome"] == "ready"
    assert merged["required_changes"][0]["downgrade_reason"] == "accepting_readability"
    science = finding(kind="numeric_or_statistical_error", category="method_or_data")
    merged = flow.merge(editor, {"referee_a": report("accept", science=[science], readability=[readable])})
    assert merged["outcome"] == "revision_required" and merged["next_action"] == "evidence_remediation"
    # Both referees at minor or better (UD-20261126-review-pass-two-minor): the hard error blocks,
    # the readability repair is advice. With a referee at major revision it blocks too.
    assert [c["advisory"] for c in merged["required_changes"][:2]] == [False, True]
    assert merged["required_changes"][1]["downgrade_reason"] == "accepting_panel"
    merged = flow.merge(editor, {"referee_a": report("major_revision", science=[science], readability=[readable])})
    assert [c["advisory"] for c in merged["required_changes"][:2]] == [False, False]


def test_structured_followup_decision():
    item = "[evidence] old item"
    resolved = {"item": item, "resolved": True, "evidence": "Fixed.", "reader_misconclusion": "",
                "kind": "advisory", "category": "body_claim", "requests": []}
    editor = {"review_standard": "materiality_v1", "decision": "send_to_review", "previous_items": [resolved],
              "new_findings": [new_finding(kind="formula_error")]}
    referees = {name: {"recommendation": "accept", "previous_items": [resolved],
                       "new_findings": [new_finding()]} for name in ("referee_a", "referee_b")}
    changed = FOLLOWUP.changed_text
    merged = flow.merge(editor, referees, followup_items=[item], changed_text=changed)
    # One location: the editor's formula error and the referees' unsupported claims are one item.
    assert merged["outcome"] == "revision_required" and merged["next_action"] == "evidence_remediation"
    assert len(merged["required_changes"]) == 1
    assert merged["required_changes"][0]["also_raised_by"] == ["referee_a", "referee_b"]
    editor["new_findings"] = [new_finding()]
    merged = flow.merge(editor, referees, followup_items=[item], changed_text=changed)
    assert merged["outcome"] == "ready"
    assert {a.get("downgrade_reason") for a in merged["advisory_items"]} >= {"accepting_unsupported"}


def test_legacy_previous_item_keeps_the_first_reporting_role():
    """TIC 260161938 (2026-11-26): a pre-B6 follow-up item the editor reported as a documentation
    request was advice in the released decision; a referee's plain report of the same item must
    not turn it into a blocker on replay. Structured records still block when any role blocks."""
    item = "[evidence] old item"
    editor_row = {"item": item, "resolved": False,
                  "evidence": "The manuscript repair is visible. The regenerated JSON is not available here; "
                              "the archive portion of the request remains unverified.",
                  "reader_misconclusion": "A reader filtering on the legacy flag could miscount one sector."}
    referee_row = {"item": item, "resolved": False, "evidence": "Partly resolved. The legacy flag is still false.",
                   "reader_misconclusion": "Selecting by the legacy flag would include the sector."}
    editor = {"review_standard": "materiality_v1", "decision": "send_to_review", "previous_items": [editor_row],
              "new_findings": []}
    referees = {"referee_a": {"recommendation": "accept", "new_findings": [],
                              "previous_items": [dict(referee_row, resolved=True)]},
                "referee_b": {"recommendation": "minor_revision", "new_findings": [],
                              "previous_items": [referee_row]}}
    merged = flow.merge(editor, referees, followup_items=[item])
    assert merged["outcome"] == "ready"
    [entry] = merged["unresolved_previous_items"]
    assert entry["advisory"] and entry["referee"] == "editor" and entry["also_raised_by"] == ["referee_b"]
    assert entry["downgrade_reason"] == "previous_accepting_documentation"
    fields = {"kind": "unsupported_claim", "category": "body_claim", "requests": ["text_edit"]}
    editor["previous_items"] = [dict(editor_row, **dict(fields, category="archive_or_response_format", requests=[]))]
    referees["referee_b"]["previous_items"] = [dict(referee_row, **fields)]
    # With both referees at minor or better the open non-hard item is advice (UD-20261126);
    # a referee at major revision makes it block again.
    assert flow.merge(editor, referees, followup_items=[item])["outcome"] == "ready"
    referees["referee_b"]["recommendation"] = "major_revision"
    merged = flow.merge(editor, referees, followup_items=[item])
    assert merged["outcome"] == "revision_required"
    entry = merged["unresolved_previous_items"][0]
    assert not entry["advisory"] and "referee_b" in [entry["referee"], *entry.get("also_raised_by", [])]
