"""Same-venue materiality and evidence-bound delta verification."""
import json

import pytest

from paper_writing import formal_checks as formal, review_flow as flow
import test_formal_checks as fixtures


def test_followup_ready_with_only_cosmetic_or_unsubstantiated_findings():
    note = dict(kind="advisory", location="Fig. 2", finding="Shorten the caption",
                reader_misconclusion="", why_missed="")
    referee = {
        "recommendation": "reject", "scientific_blockers": ["Use a different term"],
        "previous_items": [{"item": "Fix A", "resolved": True, "evidence": "Fixed."}],
        "new_findings": [note, dict(note, kind="citation_error_or_unsupported",
                                    finding="Check Citation B", reader_misconclusion="It may be outdated")],
    }
    editor = {"decision": "revise_before_submission", "presentation_problems": ["Trim the introduction"]}
    result = flow.merge(editor, {"referee": referee}, followup_items=["Fix A"])
    assert result["outcome"] == "ready"
    assert not result["required_changes"]
    assert {row["change"] for row in result["advisory_items"]} == {
        "Shorten the caption", "Check Citation B", "Use a different term", "Trim the introduction"}


def test_followup_keeps_only_tracked_and_justified_new_blockers():
    item = dict(item="Previously invalid denominator", resolved=False, evidence="Still divides by total.",
                reader_misconclusion="Readers would infer a subgroup rate of 10% instead of 50%.")
    new = dict(kind="figure_result_mismatch", location="Fig. 2", finding="Legend swaps the groups",
               reader_misconclusion="Readers would infer the control outperformed treatment.",
               why_missed="The replacement figure first appeared in this revision.")
    reports = {"referee": dict(recommendation="accept", previous_items=[item, dict(item, item="Invented ID")],
                               new_findings=[new])}
    result = flow.merge({"decision": "send_to_review"}, reports, followup_items=[item["item"]])
    assert result["outcome"] == "revision_required"
    assert [row["item"] for row in result["unresolved_previous_items"]] == [item["item"]]
    assert "replacement figure" in result["required_changes"][0]["change"]
    assert item["item"] in flow.previous_tracked_items({"merged": result, "followup_items": [item["item"]]})
    with pytest.raises(ValueError, match="duplicated"):
        flow._check_followup_items({"previous_items": [item, item]}, {"items": [item["item"]]})


def test_delta_only_checks_changed_and_prior_blocking_paragraphs(tmp_path, monkeypatch):
    metadata = fixtures.fixture_workspace(tmp_path)
    fixtures.mock_http(monkeypatch)
    tex = tmp_path / metadata["manuscript_dir"] / "main.tex"
    tex.write_text(tex.read_text().replace(r"\end{document}",
        "Untouched formula $y=2$.\n\nOld prose.\n\nUnchanged prose.\n\n" + r"\end{document}"))
    original_output = fixtures.simulated_output
    packets = []

    def output(packet):
        packets.append(packet)
        result = original_output(packet)
        for unit, row in zip(packet["items"], result["passages"]):
            if "materiality" in packet:
                for item in [row, *row["formulas"], *row["citations"], *row["prerequisites"]]:
                    item.update(finding_kind="advisory", reader_misconclusion="")
                if "New prose" in unit["text"]:
                    row.update(status="gap", coverage_rationale="Caption date could be clearer.")
            elif "real" in unit["text"]:
                row["status"] = "error"
        for row in result["references"]:
            if "materiality" in packet:
                row.update(finding_kind="advisory", reader_misconclusion="")
        return result

    monkeypatch.setattr(fixtures, "simulated_output", output)
    run_a, run_b, run_c = [tmp_path / f"run-{name}" for name in ("a", "b", "c")]
    for run in (run_a, run_b, run_c):
        run.mkdir()
    first = formal.run_checks({"metadata": metadata}, tmp_path, run_a, fixtures.ROLE, 1, fixtures.simulated_runner)
    assert not first["valid"]
    tex.write_text(tex.read_text().replace("Old prose.", "New prose."))
    packets.clear()
    second = formal.run_checks({"metadata": metadata, "previous_formal_check": first},
                               tmp_path, run_b, fixtures.ROLE, 1, fixtures.simulated_runner)
    assert second["valid"], second
    assert formal.validate_binding(second, metadata, tmp_path, fixtures.ROLE) == []
    assert "Caption date" in second["issue_summary"]["by_category"]["advisory"][0]
    assert [unit["text"] for packet in packets for unit in packet["items"]] == [
        r"For real $x$, $x^2\ge0$ by \cite{s}.", "New prose."]
    packets.clear()
    third = formal.run_checks({"metadata": metadata, "previous_formal_check": second},
                              tmp_path, run_c, fixtures.ROLE, 1, fixtures.simulated_runner)
    assert third["valid"] and packets == []
    assert formal.validate_binding(third, metadata, tmp_path, fixtures.ROLE) == []


def test_formal_material_error_and_missing_consequence():
    docs = [{"id": "main", "text": "Rates are 10% and 30%."}]
    inv = formal.inventory(docs, "")
    row = dict(passage_id=inv["passages"][0]["id"], status="error", coverage_rationale="Rates swapped.",
               prerequisites=[], citations=[], formulas=[], finding_kind="numeric_or_statistical_error",
               reader_misconclusion="Readers would reverse the direction of the effect.")
    report = {"references": [], "passages": [row]}
    assert formal.report_blockers(report, inv, [], followup=True)
    row["reader_misconclusion"] = ""
    findings = []
    assert formal.report_blockers(report, inv, [], findings=findings, followup=True) == []
    assert findings[0]["category"] == "advisory"


def test_new_formal_blocker_requires_reason_for_prior_omission():
    inv = formal.inventory([dict(id="main", text="The two estimates have opposite signs.")], "")
    inv["previous_blocker_roots"] = []
    row = dict(passage_id=inv["passages"][0]["id"], status="error", coverage_rationale="Signs swapped.",
               prerequisites=[], citations=[], formulas=[], finding_kind="numeric_or_statistical_error",
               reader_misconclusion="Readers would reverse the direction of the effect.")
    report = {"references": [], "passages": [row]}
    assert not formal.report_blockers(report, inv, [], followup=True)
    row["coverage_rationale"] += "\nWhy missed: the sign was changed in this revision."
    assert formal.report_blockers(report, inv, [], followup=True)
