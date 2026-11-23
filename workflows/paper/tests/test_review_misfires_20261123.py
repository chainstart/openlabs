"""Review-gate misfires of 2026-11-23 (owner: 抓大放小; no cooldown between rounds).

Each case is built from the archived review record that misfired:

1. round guard: wording/description items whose text merely contains "bootstrap",
   "collect" or "additional analysis" were treated as demands for a new data artifact
   (PFAS round 10, NEM five-minute settlement);
2. delta classifier: one added ``\\citep`` in the Discussion forced a full review
   (Campylobacter);
3. synthesis: with both referees at accept and nothing material left, a request to quote
   a claim-map entry in the response (TIC 421871796 round 6) or to show the corrected
   script (Campylobacter round 12) still opened another round;
4. a reviewer copying a long multi-line previous item with one sentence dropped aborted
   the review before a decision (NEM five-minute settlement round 4).
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from paper_writing import review_flow as flow
from paper_writing import review_round_guard as guard

# --- 1. round guard -------------------------------------------------------------------------

PFAS_BOOTSTRAP = (
    "main:L76:b41559f0c4fb: The rescaled PSU bootstrap supplies the reported decomposition uncertainty.: "
    "gap — The rescaled PSU bootstrap supplies the reported decomposition uncertainty.\n"
    "Rao and Wu (1988), rescaling bootstrap for stratified multistage designs\n"
    "Stratified PSU resampling with appropriate design scaling and regularity for the statistic whose "
    "sampling distribution is approximated.\n"
    "A rescaled survey bootstrap approximates sampling variability under the specified design and "
    "statistic conditions.\n"
    "PSU bootstrap replicates re-estimate the common GM factor, rank mapping and composition weights in "
    "both periods.\n"
    "The manuscript identifies masked strata and period-independent PSU resampling. The supplement needs "
    "the rescaling convention and the conditions under which it approximates variability for the fitted "
    "cutoffs and rank overlaps, particularly near ties or boundary masses.\n"
    "For the usual weight version, with n PSUs and n−1 multinomial draws in a stratum, a PSU gets "
    "multiplier nM/(n−1). Its mean is 1, and the covariance of the multiplier vector is n/(n−1) times "
    "the centering projection. This recovers the with-replacement variance of linear PSU contributions. "
    "That moment check alone leaves the fitted threshold and rank-functional interval approximation "
    "unresolved.\n"
    "Why missed: The PSU-level variance calculation can pass without checking the resampling variant or "
    "regularity of the fitted statistics.\n"
    "The reported intervals could be read as having established 95% coverage for the fitted threshold "
    "and rank statistics.")
PFAS_RAOWU = (
    "main:L76:b41559f0c4fb:C1:raowu1988: gap — A Rao–Wu rescaling bootstrap supplies the decomposition "
    "intervals.\nRao and Wu (1988) supports PSU rescaling, with its original formulation rescaling data "
    "values. A weight-rescaling implementation and inference for threshold indicators with a fitted cutoff "
    "need the relevant variant and applicability stated in the supplement.\n"
    "Why missed: The resampling method’s name does not identify the rescaling convention or the conditions "
    "for the nonlinear estimands.\n"
    "A reader could infer that the cited resampling result establishes interval calibration for the "
    "fitted threshold and rank estimators.")
NEM_NARROW = (
    "[narrative] Keep the conclusion’s measured sentence. Apply its scope to the introduction’s new "
    "“schedules committed hours ahead on lagged prices do not collect it” and to the summaries in the "
    "abstract and conclusion. Say “the two tested schedules collected little of the premium at the "
    "median.” In §4.3, specify that commitment prevents a response to prices released after the decision. "
    "A committed schedule can still vary its planned dispatch across five-minute slots. "
    "(Title, abstract, figures and conclusion)")
NEM_ATTRIBUTION = (
    "main:L209:a2bf0ecd3b14: Check the fixed-schedule repricing identity and the claimed inference from "
    "the rolling ratio.: gap — Check the fixed-schedule repricing identity and the claimed inference from "
    "the rolling ratio.\nFor constant net power q in a block, the repricing effect is Δq times the sum of "
    "the six deviations from their mean, which is zero. A negative total determines neither component's "
    "sign and supplies no condition on forecast-error timing. Supporting the attribution would require an "
    "additional analysis in the appendix or supplement, and the main sentence needs qualification because "
    "it presents the attribution as an implication of the ratio.")


@pytest.mark.parametrize("item, hint", [
    (PFAS_BOOTSTRAP, "bootstrap"), (PFAS_RAOWU, "bootstrap"),
    (NEM_NARROW, "collect"), (NEM_ATTRIBUTION, "additional analysis"),
])
def test_wording_items_need_no_new_artifact(item, hint):
    # The old vocabulary regex still matches (a hint), but the item demands no new work.
    assert guard.new_work_hint(item) == hint
    assert guard.new_work_basis(item) is None


@pytest.mark.parametrize("item, trigger", [
    ("Rerun the bootstrap with 2,000 replicates and report the new intervals.", "Rerun"),
    ("Quantify how the one-sided third-light prior affects the adopted q.", "Quantify"),
    ("The authors should re-estimate the model excluding the 2020 season.", "should re-estimate"),
    ("Add a sensitivity analysis that drops the two outlying sites.", "Add a sensitivity analysis"),
    ("A new simulation is required to support the coverage claim.", "new simulation is required"),
    ("请补做外部验证。", "补做"),
])
def test_explicit_demands_still_need_a_new_artifact(item, trigger):
    basis = guard.new_work_basis(item)
    assert basis is not None and basis["trigger"] == trigger


@pytest.mark.parametrize("item", [
    "No new analysis is required.",
    "This correction does not require new computations.",
    "Either provide batch-bootstrap intervals for the retentions, or label the increase as descriptive.",
    "Collect the scope caveats in one place instead of repeating them across subsections.",
])
def test_negated_optional_or_editorial_requests_are_not_demands(item):
    assert guard.new_work_basis(item) is None


def _guard(tmp_path, items, explicit, raw):
    snapshot = tmp_path / "manuscript-expanded.tex"
    snapshot.write_text("Old text")
    last = {"_path": tmp_path / "decision.json", "round_evidence_files": {}, "figure_files": []}
    return guard.check(tmp_path, "p", "J", last, {"expanded": "New text"}, {}, {}, raw, items, explicit,
                       "d" * 64, None, datetime.now(UTC), guard.settings({}))


def test_pfas_round10_text_locations_satisfy_bootstrap_description_items(tmp_path):
    (tmp_path / "supplement.tex").write_text("Rescaling convention and its limits.\n")
    items = [PFAS_BOOTSTRAP, PFAS_RAOWU]
    raw = json.dumps({"decision_sha256": "d" * 64, "items": [
        {"item": item, "status": "addressed", "explanation": "Stated in Note S2.",
         "evidence": ["supplement.tex:1"]} for item in items]})
    result = _guard(tmp_path, items, {}, raw)
    assert result["blockers"] == [] and result["requires_new_artifact"] == []
    assert result["new_artifact_hints"] == {PFAS_BOOTSTRAP: "bootstrap", PFAS_RAOWU: "bootstrap"}


def test_nem_narrowing_item_needs_only_a_text_location(tmp_path):
    (tmp_path / "main.tex").write_text("the two tested schedules collected little of the premium\n")
    raw = json.dumps({"decision_sha256": "d" * 64, "items": [
        {"item": NEM_NARROW, "status": "addressed", "explanation": "Narrowed.",
         "evidence": ["main.tex:1"]}]})
    assert _guard(tmp_path, [NEM_NARROW], {}, raw)["blockers"] == []


def test_a_real_demand_names_its_trigger_in_the_refusal(tmp_path):
    (tmp_path / "main.tex").write_text("text\n")
    item = "[evidence] Rerun the bootstrap with 2,000 replicates. (Methods)"
    flagged = "[evidence] External holdout. (Methods)"
    raw = json.dumps({"decision_sha256": "d" * 64, "items": [
        {"item": i, "status": "addressed", "explanation": "Done.", "evidence": ["main.tex:1"]}
        for i in (item, flagged)]})
    blockers = _guard(tmp_path, [item, flagged], {flagged: True}, raw)["blockers"]
    assert any("'Rerun' in \"Rerun the bootstrap with 2,000 replicates.\"" in b for b in blockers)
    assert any("the editor marked this change requires_new_artifact" in b for b in blockers)


# --- 2. delta classifier --------------------------------------------------------------------

DISCUSSION = ("\\section{Discussion}\nThe classifier was studied as an object of evaluation. The supporting "
              "material provides the code and fold assignments needed to refit it.\n")
PAPER = ("\\documentclass{article}\\begin{document}\\title{T}\\begin{abstract}A.\\end{abstract}\n"
         "\\section{Introduction}\nIntro.\n\\section{Results}\nAccuracy fell by 2.5 points.\n"
         "\\begin{figure}[t]\\includegraphics{f.pdf}\\caption{Accuracy by period.}\\end{figure}\n"
         "More results.\n" + DISCUSSION
         + "\\begin{thebibliography}{9}\\bibitem{a}A. Author. Water. 2019.\n\\end{thebibliography}\n"
         "\\end{document}\n")


def test_campylobacter_added_citation_in_discussion_is_not_substantive():
    cited = PAPER.replace("supporting material provides", "supporting material \\citep{zenodo支撑} provides")
    assert flow.substantive_delta(PAPER, cited)["reasons"] == []


@pytest.mark.parametrize("edit", [
    lambda t: t.replace("\\end{thebibliography}", "\\bibitem{b}B. Author. Air. 2024. "
                        "https://doi.org/10.1000/xyz\n\\end{thebibliography}"),        # bib entry added
    lambda t: t.replace("Accuracy fell by 2.5 points.", "Accuracy fell by 2.5 points (Fig.~\\ref{fig:a})."),
    lambda t: t.replace("\\begin{figure}[t]", "\\begin{figure}[htbp]"),                 # placement
    lambda t: t.replace("\\begin{figure}[t]\\includegraphics{f.pdf}\\caption{Accuracy by period.}\\end{figure}\n", "")
              .replace("More results.\n", "More results.\n\\begin{figure}[t]\\includegraphics{f.pdf}"
                       "\\caption{Accuracy by period.}\\end{figure}\n"),                 # float moved
    lambda t: t.replace("assignments needed", "assignments \\citep{x} needed \\url{https://e.org/2}"),
])
def test_reference_and_float_only_edits_stay_delta(edit):
    changed = edit(PAPER)
    assert changed != PAPER
    assert flow.substantive_delta(PAPER, changed)["reasons"] == []


@pytest.mark.parametrize("edit, reason", [
    (lambda t: t.replace("fell by 2.5", "fell by 3.5"), "numbers changed"),
    (lambda t: t.replace("needed to refit it", "needed to refit and deploy it"), "conclusion-bearing"),
    (lambda t: t.replace("Accuracy by period.", "Accuracy rose by period."), "conclusion-bearing"),
    (lambda t: t.replace("Water. 2019.", "Water. 2021."), "bibliography entries changed: a"),
])
def test_content_changes_still_require_a_full_review(edit, reason):
    assert any(r.startswith(reason) for r in flow.substantive_delta(PAPER, edit(PAPER))["reasons"])


# --- 3. documentation requests at synthesis ------------------------------------------------

TIC_ITEM = ("[narrative] Confirm that claim–evidence map C5 in the reproducibility archive now matches §4.2. "
            "It should describe the sector-67 QLP dilution as close to the l3=0 bound and keep the profiled "
            "median (0.005, 22 of 48 below 0.005) separate from the joint-chain median (0.006, 45% below "
            "0.005). The response cites only main.tex lines 111 and 168, and the diff does not cover the "
            "archive. (Title, abstract, figures and conclusion)")
TIC_READER = {
    "kind": "substantive", "previous_item": TIC_ITEM,
    "repair": ("Quote claim–evidence entry C5 verbatim from evidence/claim_evidence_map.md:11 in the "
               "response. Line 11 must describe the S67 QLP dilution as close to (not limited by) the "
               "l3 = 0 bound and must give the profiled median (0.005, 22 of 48 below 0.005) separately "
               "from the joint-chain median (0.006, 45% of draws below 0.005). The location has now been "
               "given; only the verbatim text is missing."),
    "wrong_conclusion": ("Not yet checkable: the archive entry has not been shown. If C5 still says the "
                         "bound limits the fit, or mixes the profiled and joint-chain medians, the archive "
                         "would state more than the positive medians in Fig. 5 and §4.2 support."),
    "why_missed": ("Not new; carried over from the previous round. The response paraphrases C5 and cites "
                   "its line instead of quoting it, and the diff still covers only main.tex."),
}
CAMPY_ITEM = ("[evidence] For “Delta > 0 (one-sided)”, the script selects primary.holm_level_ci and "
              "evaluates “low > 0 or high < 0”. At one-sided level 0.025 the applicable check is positivity "
              "of the lower bound of the central 95% interval, 0.01162643. (posthoc/rule_agreement_check.py)")
CAMPY_EDITOR_ROW = {
    "item": CAMPY_ITEM, "resolved": False,
    "evidence": ("Appendix A correctly identifies the lower endpoint of the central 95% interval for the "
                 "one-sided Holm level of 0.025 and distinguishes the extra central 97.5% interval. The "
                 "claim-evidence map makes the same distinction. The authors describe the correct script "
                 "change, but their evidence points to main.tex and a hash. The supplied diff is empty, "
                 "neither the script nor its regenerated JSON is included, and I could not retrieve the "
                 "cited archive. The implementation repair therefore remains unverified. Both reported "
                 "bounds are positive, so agreement of the saved decisions cannot distinguish the old check "
                 "from the corrected one."),
    "reader_misconclusion": ("If the cited archive still contains the earlier row, a reader reproducing it "
                             "would use the 1.25th percentile at a one-sided level of 0.025 and could treat "
                             "an interval wholly below zero as evidence that accuracy fell."),
}
CAMPY_READER = {
    "kind": "substantive", "previous_item": CAMPY_ITEM, "why_missed": "",
    "repair": ("Reported addressed. The response gives the correct directional check at the one-sided Holm "
               "level of 0.025. Both the original and corrected checks pass on these data. The supplied "
               "diff is empty and the workspace contains only the four figures, so the revised script and "
               "Appendix A wording could not be independently verified."),
    "wrong_conclusion": ("The previous implementation treated the 1.25th percentile as the applicable lower "
                         "bound and would have counted an interval wholly below zero as evidence of a "
                         "positive loss."),
}


def _referee(item, recommendation="accept", resolved=True):
    return {"recommendation": recommendation, "new_findings": [], "dimension_repairs": {},
            "previous_items": [{"item": item, "resolved": resolved, "evidence": "Done.",
                                "reader_misconclusion": ""}]}


def _reader(*repairs):
    return {"repairs": list(repairs), "question": "q", "comparison": "c", "answer": "a", "meaning": "m"}


def _merge(item, editor_row, referees, reader):
    editor = {"decision": "send_to_review", "new_findings": [], "dimension_repairs": {},
              "previous_items": [editor_row]}
    return flow.merge(editor, referees, [], formal_blockers=[], formal_summary=None, followup_items=[item],
                      reader_report=reader, previous={"items": [item]})


def test_tic_round6_quote_in_response_is_advice_and_ready():
    row = {"item": TIC_ITEM, "resolved": True, "evidence": "Matches.", "reader_misconclusion": ""}
    merged = _merge(TIC_ITEM, row, {"referee_a": _referee(TIC_ITEM), "referee_b": _referee(TIC_ITEM)},
                    _reader(TIC_READER))
    assert merged["outcome"] == "ready" and merged["next_action"] is None
    assert merged["documentation_requests_downgraded"]["rule"] == "gate1_precision_v1"
    change = next(c for c in merged["required_changes"] if c["referee"] == "delivery_reader")
    assert change["advisory"] and change["downgrade_reason"] == "documentation_request"
    assert not any(merged["dimension_repairs"].values())


def test_campylobacter_round12_unseen_script_is_advice_and_ready():
    merged = _merge(CAMPY_ITEM, CAMPY_EDITOR_ROW,
                    {"referee_a": _referee(CAMPY_ITEM), "referee_b": _referee(CAMPY_ITEM)},
                    _reader(CAMPY_READER))
    assert merged["outcome"] == "ready"
    assert all(item["advisory"] for item in merged["unresolved_previous_items"])
    # The next round tracks nothing from this decision.
    assert flow.previous_tracked_items({"merged": merged, "followup_items": [CAMPY_ITEM]}) == []


def test_a_present_error_keeps_blocking():
    row = dict(CAMPY_EDITOR_ROW, evidence=("The supplied diff is empty. The script still reports the "
                                           "97.5% interval, which is incorrect for the one-sided test."))
    merged = _merge(CAMPY_ITEM, row, {"referee_a": _referee(CAMPY_ITEM), "referee_b": _referee(CAMPY_ITEM)},
                    _reader())
    assert merged["outcome"] == "revision_required"


def test_documentation_requests_block_while_a_referee_wants_major_revision():
    row = {"item": TIC_ITEM, "resolved": True, "evidence": "Matches.", "reader_misconclusion": ""}
    merged = _merge(TIC_ITEM, row, {"referee_a": _referee(TIC_ITEM),
                                    "referee_b": _referee(TIC_ITEM, "major_revision")}, _reader(TIC_READER))
    assert merged["outcome"] == "revision_required"


# --- 4. previous-item copies ----------------------------------------------------------------

NEM_ITEM = ("main:L134:e227b258a064: error — The worked example moves 1/12 MWh each way. The half-hour cash "
            "flow is zero for equal metered volumes. For a fixed path, the general equality condition is "
            "that the sum of (fine price minus block mean) times net power, multiplied by interval length, "
            "vanishes. Constant net power is sufficient. The main text needs the corrected condition.\n"
            "Why missed: The prior blocker list does not include the converse in the worked example passage.")
NEM_COPY = NEM_ITEM.replace(" For a fixed path, the general equality condition is that the sum of (fine price "
                            "minus block mean) times net power, multiplied by interval length, vanishes.", "")
OTHER = "[narrative] Qualify the cycle-loss statement for negative prices. (Results)"


def test_nem_round4_inexact_copy_of_a_long_item_does_not_abort():
    previous = {"items": [NEM_ITEM, OTHER]}
    report = {"previous_items": [{"item": OTHER, "resolved": True},
                                 {"item": NEM_COPY, "resolved": False}]}
    flow._check_followup_items(report, previous)  # no ValueError
    rows = flow.canonical_previous_items(report, previous["items"])
    assert [row["item"] for row in rows] == [OTHER, NEM_ITEM] and rows[1]["item_as_returned"] == NEM_COPY


def test_duplicated_mandatory_items_count_once():
    flow._check_followup_items({"previous_items": [{"item": OTHER, "resolved": True}]},
                               {"items": [OTHER, OTHER]})


@pytest.mark.parametrize("returned", [
    [OTHER],                                     # omitted
    [OTHER, OTHER],                              # duplicated
    [OTHER, "[narrative] Something unrelated entirely. (Methods)"],  # introduced
])
def test_omitted_duplicated_or_introduced_items_still_abort(returned):
    with pytest.raises(ValueError, match="omitted, duplicated or introduced"):
        flow._check_followup_items({"previous_items": [{"item": i, "resolved": True} for i in returned]},
                                   {"items": [NEM_ITEM, OTHER]})
