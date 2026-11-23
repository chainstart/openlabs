"""Presentation revision review (2026-11-23): restructuring without a scientific round."""
import copy
import json
import subprocess

import pytest

from paper_writing import presentation, reader_check, review_flow as flow

BASIS = "20200101T000000Z"
OLD = r"""\documentclass{article}
\newcommand{\effect}{0.42}
\begin{document}
\title{County water prices}
\begin{abstract}Prices fell by \effect{} after reform.\end{abstract}
\section{Introduction}
We study water prices.
\section{Data and methods}
We use 120 counties. The estimator follows a standard design.
\begin{figure}\includegraphics[width=0.8\textwidth]{fig1.png}\caption{Prices over time.}\end{figure}
\section{Results}
The effect is \effect{} across 120 counties.
\begin{table}\begin{tabular}{cc}a & 1.5\\\end{tabular}\end{table}
\section{Discussion}
Prices fell.
\end{document}
"""
# Venue class, byline, funding with grant numbers, a minipage layout, a literal cross-reference,
# a new Conclusions section restating existing numbers, and methods moved to an appendix.
RESTRUCTURED = r"""\documentclass[preprint,12pt]{elsarticle}
\newcommand{\effect}{0.42}
\begin{document}
\begin{frontmatter}
\title{Water prices fell by 0.42 after the county reform}
\author[a]{A. Author}\affiliation[a]{organization={University 201209}, city={Shanghai}}
\begin{abstract}Across 120 counties, prices fell by \effect{} after reform.\end{abstract}
\begin{keyword}water prices\end{keyword}
\end{frontmatter}
\section{Introduction}
We study water prices; Figure 1 shows the series and Section 3 the estimate.
\begin{figure}\begin{minipage}{0.48\textwidth}\includegraphics[width=\linewidth]{fig1.png}\end{minipage}
\caption{Prices over time in 120 counties.}\end{figure}
\section{Results}
The effect is \effect{} across 120 counties.
\begin{table}[htbp]\begin{tabular}{cc}\multicolumn{2}{c}{Head}\\a & 1.5\\\end{tabular}\end{table}
\section{Discussion}
Prices fell.
\section{Conclusions}
Prices fell by 0.42 in 120 counties.
\section*{Funding}
Grant 2023YFC3000 from the foundation.
\appendix
\section{Data and methods}
We use 120 counties. The estimator follows a standard design.
\end{document}
"""


def test_restructuring_is_presentation():
    result = presentation.compare(OLD, RESTRUCTURED)
    assert result["reasons"] == [], result


@pytest.mark.parametrize("edit,reason", [
    (("across 120 counties.", "across 118 counties."), "numbers added"),
    (("\\newcommand{\\effect}{0.42}", "\\newcommand{\\effect}{0.40}"), "numbers added"),
    (("a & 1.5", "a & 1.6"), "numbers added"),
    (("Prices fell.\n\\section{Conclusions}", "Prices fell, a causal effect of the reform.\n\\section{Conclusions}"),
     "claim-strength wording introduced: causal"),
    (("Prices fell.\n\\section{Conclusions}", "We demonstrate that prices fell.\n\\section{Conclusions}"),
     "claim-strength wording introduced: demonstration"),
])
def test_scientific_changes_are_detected(edit, reason):
    new = RESTRUCTURED.replace(*edit)
    assert new != RESTRUCTURED
    reasons = presentation.compare(OLD, new)["reasons"]
    assert any(r.startswith(reason) for r in reasons), reasons


def test_numbers_inside_tikz_labels_still_count():
    schematic = r"\begin{tikzpicture}\draw (0,0) -- (3.5,2); \node at (1,1) {n = 7 sites};\end{tikzpicture}"
    new = RESTRUCTURED.replace(r"\section{Results}", schematic + "\n\\section{Results}")
    assert presentation.compare(OLD, new)["numbers_added"] == ["7"]


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _fixture(tmp_path, monkeypatch, new_text, *, figures=None, data_change=False, review=None):
    flow_config = {'process': flow.PROCESS, 'roles': {'editor': {'provider': 'openai-codex'},
                   'referee_a': {'provider': 'anthropic', 'model': 'opus'},
                   'referee_b': {'provider': 'openai-codex', 'model': 'gpt'}},
                   'referee_roles': ['referee_a', 'referee_b'], 'rejection_clearance_required': True,
                   'timeout_seconds': 1, 'max_rounds_per_target': 4, 'previous_panels': []}
    monkeypatch.setattr(flow, 'review_config', lambda root: flow_config)
    monkeypatch.setattr(flow.formal_checks, 'run_checks', lambda *args: {'valid': True, 'blockers': []})
    monkeypatch.setattr(flow.formal_checks, 'validate_binding', lambda *args: [])
    monkeypatch.setattr(flow.formal_checks, 'packet', lambda *args: 'Formal audit fixture')
    from paper_writing import delivery_floor
    monkeypatch.setattr(delivery_floor, 'check', lambda *args, **kwargs: {"issues": []})
    root = tmp_path
    _git(root, "init", "-q")
    base = root / "reviews/unified/p" / BASIS
    base.mkdir(parents=True)
    (base / "manuscript-expanded.tex").write_text(OLD)
    data = root / "papers/p/support/results/prices.csv"
    data.parent.mkdir(parents=True)
    data.write_text("year,price\n2020,1.0\n")
    record = {"paper_id": "p", "process": flow.PROCESS, "stage_reached": "decision", "target_journal": "J",
              "run_id": BASIS, "finished_at": "2020-01-01T01:00:00Z",
              "figure_files": [{"path": "fig1.png", "sha256": "a" * 64}], "round_evidence_files": {},
              "review_policy_sha256": flow.review_policy_sha256(flow_config), "review_track": {"track": "routine"},
              "editor_screen": {"decision": "send_to_review", "desk_reject_category": "none",
                                "prior_rejections_addressed": []},
              "referee_reports": {name: {"recommendation": "accept", "scientific_blockers": [],
                                         "required_changes": [], "previous_items": [], "scores": {"overall": 7},
                                         "formal_check_assessment": {"coverage_complete": True,
                                                                     "omissions_or_errors": []}}
                                  for name in ("referee_a", "referee_b")},
              "merged": {"outcome": "ready", "scientific_blockers": [], "required_changes": []},
              "prior_decisions": [], "letter": "Accepted.", "receipts": {}, "fingerprints": {}}
    (base / "decision.json").write_text(json.dumps(record))
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "basis")
    if data_change:
        data.write_text("year,price\n2020,1.1\n")
    figure_files = [{"path": "fig1.png", "sha256": ("b" if figures is not None else "a") * 64}]
    meta = {'paper_id': 'p', 'version': '1.1', 'target_journal': 'J'}
    pre = {'metadata': meta, 'target': 'J', 'blockers': [], 'fingerprints': {}, 'expanded': new_text,
           'bibliography': '', 'figure_files': figure_files}
    monkeypatch.setattr(flow, 'preflight', lambda *args: pre)
    calls = []
    monkeypatch.setattr(flow, 'run_role', lambda **kw: calls.append(kw['role_name']) or ({}, {}))
    assessment = review or {"form_meets_venue": True, "narrative_meets_standard": True,
                            "figures_meet_standard": True, "form_repairs": [], "amplified_claims": [],
                            "summary": "Looks like the venue."}
    reads = []

    def read(*args, **kwargs):
        reads.append(kwargs.get("presentation"))
        return dict.fromkeys(("question", "comparison", "answer", "meaning"), "supported") | {
            "repairs": [], "presentation": assessment}, {}
    monkeypatch.setattr(reader_check, "delivery_read", read)
    request = {"schema": presentation.SCHEMA, "summary": "Venue class, conclusions section, methods to appendix",
               "basis_decision_sha256": flow._sha256((base / "decision.json").read_bytes()),
               "figures": figures or []}
    path = root / "presentation-request.json"
    path.write_text(json.dumps(request))
    return root, path, calls, reads, meta


def test_presentation_review_is_ready_without_a_scientific_round(tmp_path, monkeypatch):
    from paper_writing import operations
    root, request, calls, reads, meta = _fixture(tmp_path, monkeypatch, RESTRUCTURED)
    written = []
    monkeypatch.setattr(flow, 'load_paper_metadata', lambda *args: meta)
    monkeypatch.setattr(flow, 'write_paper_metadata', lambda pid, value, root: written.append(copy.deepcopy(value)))
    monkeypatch.setattr(operations, '_review_workspace_fingerprints', lambda *args: {})
    record = flow.run_review('p', root=root, response_letter=request, apply=True, presentation=True)
    assert calls == []  # no editor, referee or letter model
    assert len(reads) == 1 and "Presentation review" in reads[0]  # one light review session
    assert record["review_mode"] == "presentation" and record["merged"]["outcome"] == "ready"
    assert record["consumes_scientific_round"] is False and record["round_for_target"] == 1
    assert record["delta_review"]["basis_run_id"] == BASIS
    release = written[-1]["writing_release"]
    assert release["status"] == "ready" and release["review_mode"] == "presentation"
    assert release["presentation_basis_run_id"] == BASIS
    assert len(flow.scientific_rounds(root, "p", "J")) == 1
    # The ready presentation decision is the basis of later delta and presentation reviews.
    assert flow.ready_basis(root, "p", "J")["review_mode"] == "presentation"
    path = root / record["run_dir"] / "decision.json"
    assert presentation.validate(json.loads(path.read_text()), path, root) == []
    (path.parent / "presentation-request.json").write_text("{}")
    assert presentation.validate(json.loads(path.read_text()), path, root)


def test_added_number_routes_to_full_review(tmp_path, monkeypatch):
    root, request, calls, reads, _ = _fixture(
        tmp_path, monkeypatch, RESTRUCTURED.replace("across 120 counties.", "across 118 counties."))
    record = flow.run_review('p', root=root, response_letter=request, apply=False, presentation=True)
    assert record["merged"]["outcome"] == "full_review_required" and reads == [] and calls == []
    assert record["stage_reached"] == "presentation_check" and record["consumes_scientific_round"] is False
    assert len(flow.scientific_rounds(root, "p", "J")) == 1


def test_amplified_claims_route_to_full_review(tmp_path, monkeypatch):
    claim = {"form_meets_venue": True, "narrative_meets_standard": True, "figures_meet_standard": True,
             "form_repairs": [], "summary": "s",
             "amplified_claims": [{"before": "Prices fell.", "after": "Reform always lowers prices.",
                                   "why": "generalizes beyond the sample"}]}
    root, request, calls, reads, _ = _fixture(tmp_path, monkeypatch, RESTRUCTURED, review=claim)
    record = flow.run_review('p', root=root, response_letter=request, apply=False, presentation=True)
    assert record["merged"]["outcome"] == "full_review_required"
    assert record["stage_reached"] == "presentation_check"
    assert len(flow.scientific_rounds(root, "p", "J")) == 1


def test_blocking_form_repair_returns_revision_without_a_round(tmp_path, monkeypatch):
    form = {"form_meets_venue": False, "narrative_meets_standard": True, "figures_meet_standard": True,
            "amplified_claims": [], "summary": "s",
            "form_repairs": [{"location": "front matter", "repair": "Use the venue class", "blocking": True},
                             {"location": "Fig. 1", "repair": "Larger ticks", "blocking": False}]}
    root, request, _, _, _ = _fixture(tmp_path, monkeypatch, RESTRUCTURED, review=form)
    record = flow.run_review('p', root=root, response_letter=request, apply=False, presentation=True)
    assert record["merged"]["outcome"] == "revision_required"
    assert record["merged"]["next_action"] == "text_revision"
    assert record["consumes_scientific_round"] is False
    assert len(flow.scientific_rounds(root, "p", "J")) == 1


def test_redrawn_result_figure_needs_frozen_data(tmp_path, monkeypatch):
    figure = [{"path": "fig1.png", "kind": "result", "data": ["papers/p/support/results/prices.csv"]}]
    root, request, _, _, _ = _fixture(tmp_path, monkeypatch, RESTRUCTURED, figures=figure)
    record = flow.run_review('p', root=root, response_letter=request, apply=False, presentation=True)
    assert record["merged"]["outcome"] == "ready"
    assert record["presentation_review"]["figures"][0]["data"][0]["path"].endswith("prices.csv")


def test_redrawn_figure_with_changed_data_routes_to_full_review(tmp_path, monkeypatch):
    figure = [{"path": "fig1.png", "kind": "result", "data": ["papers/p/support/results/prices.csv"]}]
    root, request, _, _, _ = _fixture(tmp_path, monkeypatch, RESTRUCTURED, figures=figure, data_change=True)
    record = flow.run_review('p', root=root, response_letter=request, apply=False, presentation=True)
    assert record["merged"]["outcome"] == "full_review_required"
    assert any("figure data changed" in r for r in record["merged"]["full_review_reasons"])


def test_undeclared_changed_figure_routes_to_full_review(tmp_path, monkeypatch):
    root, request, _, _, _ = _fixture(tmp_path, monkeypatch, RESTRUCTURED, figures=[])
    pre = flow.preflight()
    pre["figure_files"] = [{"path": "fig1.png", "sha256": "c" * 64}]
    record = flow.run_review('p', root=root, response_letter=request, apply=False, presentation=True)
    assert record["merged"]["outcome"] == "full_review_required"
    assert any("not declared" in r for r in record["merged"]["full_review_reasons"])


def test_request_must_bind_the_basis_decision(tmp_path, monkeypatch):
    root, request, _, reads, _ = _fixture(tmp_path, monkeypatch, RESTRUCTURED)
    body = json.loads(request.read_text())
    body["basis_decision_sha256"] = "0" * 64
    request.write_text(json.dumps(body))
    record = flow.run_review('p', root=root, response_letter=request, apply=False, presentation=True)
    assert record["merged"]["outcome"] == "full_review_required" and reads == []


def test_failing_author_floor_stops_before_the_light_review(tmp_path, monkeypatch):
    root, request, _, reads, _ = _fixture(tmp_path, monkeypatch, RESTRUCTURED)
    from paper_writing import delivery_floor
    monkeypatch.setattr(delivery_floor, 'check', lambda *args, **kwargs: {"issues": [{"text": "BYLINE-MISSING"}]})
    record = flow.run_review('p', root=root, response_letter=request, apply=False, presentation=True)
    assert record["merged"]["outcome"] == "preflight_failed" and reads == []
    assert record["merged"]["presentation_blockers"] == ["BYLINE-MISSING"]


def test_modes_are_exclusive():
    with pytest.raises(ValueError):
        flow.run_review('p', root='.', delta_only=True, presentation=True)
