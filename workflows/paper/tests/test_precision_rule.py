"""Owner rule 2026-11-23 ("抓大放小"): precision and wording never block; real errors do."""
import pytest

from paper_writing import formal_checks as formal, review_flow as flow


def finding(category, status, message):
    return dict(category=category, status=status, message=message, root="r", location="L1",
                aggregate=False, reason="why")


SUMMARY = formal.issue_summary([
    finding("scientific", "gap", "L25: gap — contact phases alone do not fix q"),
    finding("scientific", "error", "L92: error — interval overlap is not a bound"),
    finding("source_routing", None, "ref: no queryable authoritative bibliographic evidence"),
    finding("advisory", "error", "title metadata"),
])
BLOCKERS = ["L25: gap — contact phases alone do not fix q", "L92: error — interval overlap is not a bound",
            "ref: no queryable authoritative bibliographic evidence"]


def test_scientific_gaps_are_downgraded_and_errors_and_references_still_block():
    material, downgraded = formal.material_blockers(BLOCKERS, SUMMARY)
    assert downgraded == ["L25: gap — contact phases alone do not fix q"]
    assert material == BLOCKERS[1:]
    view = formal.precision_view(SUMMARY)
    assert "L25: gap — contact phases alone do not fix q" in view["by_category"]["advisory"]
    assert view["by_category"]["scientific"] == ["L92: error — interval overlap is not a bound"]
    assert view["by_category"]["source_routing"] == BLOCKERS[2:]


def test_only_gaps_leave_no_material_blocker():
    summary = formal.issue_summary([finding("scientific", "gap", "a"), finding("scientific", "gap", "b")])
    assert formal.material_blockers(["a", "b"], summary) == ([], ["a", "b"])
    # Without structured findings nothing is downgraded.
    assert formal.material_blockers(["a"], None) == (["a"], [])


def test_formal_stage_records_the_precision_rule_and_passes_a_gap_only_report(tmp_path, monkeypatch):
    report = {"valid": False, "blockers": ["a"], "path": "x",
              "issue_summary": formal.issue_summary([finding("scientific", "gap", "a")])}
    monkeypatch.setattr(formal, "run_checks", lambda *args: report)
    seen = {}
    monkeypatch.setattr(formal, "validate_binding",
                        lambda *args, **kwargs: seen.update(kwargs) or [])
    monkeypatch.setattr(formal, "packet", lambda *args: "packet")
    monkeypatch.setattr(flow, "formal_role", lambda roles: {"provider": "openai-codex"})
    record = {"paper_id": "p"}
    pre, blockers, summary = flow._formal_stage({"target": None}, tmp_path, tmp_path, {}, {"timeout_seconds": 1},
                                                {}, record)
    assert blockers == [] and seen == {"precision": True}
    assert record["formal_precision"] == {"rule": formal.PRECISION_RULE, "downgraded": ["a"]}
    assert summary["by_category"]["advisory"] == ["a"]
    assert flow.formal_precision(record)


def _reports(recommendations, finding_dimension):
    material = {"repair": "Say 'constrains' rather than 'fixes'", "kind": "substantive",
                "wrong_conclusion": "A reader could think q is unique", "why_missed": "", "previous_item": ""}
    def report(rec, dims):
        return {"recommendation": rec, "scientific_blockers": [], "required_changes": [], "previous_items": [],
                "scores": {"overall": 7}, "review_standard": "materiality_v1",
                "formal_check_assessment": {"coverage_complete": True, "omissions_or_errors": []},
                "dimension_repairs": {d: ([material] if d == dims else []) for d in flow.DIMENSIONS}}
    editor = {"decision": "send_to_review", "desk_reject_category": "none", "review_standard": "materiality_v1",
              "dimension_repairs": {d: [] for d in flow.DIMENSIONS}, "previous_items": []}
    return editor, {f"referee_{i}": report(rec, finding_dimension if i == 0 else None)
                    for i, rec in enumerate(recommendations)}


@pytest.mark.parametrize("recs,dimension,ready", [
    (("accept", "minor_revision"), "readability", True),    # wording only: advice
    (("minor_revision", "major_revision"), "readability", False),  # a referee wants more
    (("accept", "minor_revision"), "science", False),       # evidence does not support a conclusion
    (("accept", "minor_revision"), "formal_accuracy", False),  # wrong numbers or citations
])
def test_wording_with_accept_or_minor_referees_is_ready(recs, dimension, ready):
    editor, referees = _reports(recs, dimension)
    merged = flow._material_decision(editor, referees, [], [], None)
    assert (merged["outcome"] == "ready") is ready
    if ready:
        downgraded = [c for c in merged["required_changes"] if c.get("precision_downgraded")]
        assert downgraded and all(c["advisory"] for c in downgraded)


def test_sentence_level_unsupported_claim_errors_are_advice_but_numeric_errors_block():
    report = {"references": [], "passages": [
        {"passage_id": "main:L111", "finding_kind": "unsupported_claim", "citations": [], "formulas": [],
         "prerequisites": []},
        {"passage_id": "main:L92", "finding_kind": "numeric_or_statistical_error", "citations": [],
         "formulas": [{"formula_id": "main:L92:F1", "finding_kind": "formula_error"}], "prerequisites": []}]}
    kinds = formal.finding_kinds(report)
    assert kinds == {"main:L111": "unsupported_claim", "main:L92": "numeric_or_statistical_error",
                     "main:L92:F1": "formula_error"}
    summary = formal.issue_summary([
        dict(finding("scientific", "error", "L111 overstates"), location="main:L111"),
        dict(finding("scientific", "error", "L92 wrong"), location="main:L92"),
        dict(finding("scientific", "error", "F1 wrong"), location="main:L92:F1")])
    material, downgraded = formal.material_blockers(["L111 overstates", "L92 wrong", "F1 wrong"], summary, kinds)
    assert downgraded == ["L111 overstates"] and material == ["L92 wrong", "F1 wrong"]
