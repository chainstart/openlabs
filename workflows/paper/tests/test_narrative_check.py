from __future__ import annotations

import json
from pathlib import Path

import pytest

from paper_writing import narrative_check as nc
from paper_writing import reader_check
from paper_writing.__main__ import main as cli
from paper_writing.manuscript_style import audit_manuscript_style, manuscript_style_review_findings


def _doc(body: str, *, abstract: str = "We measure the period of a binary star.", tail: str = "") -> str:
    return ("\\documentclass{article}\n"
            "\\newcommand{\\qAdopt}{0.275}\n"
            "\\begin{document}\n"
            "\\title{A binary}\n"
            f"\\begin{{abstract}}\n{abstract}\n\\end{{abstract}}\n"
            "\\maketitle\n"
            f"{body}\n"
            f"{tail}"
            "\\bibliography{references}\n"
            "\\section*{Author contributions}\nA. Author: Writing -- original draft.\n"
            "\\end{document}\n")


def _words(n: int, word: str = "period") -> str:
    return " ".join([word] * n) + "."


def _check(tmp_path: Path, text: str, limits: dict | None = None, **kwargs) -> dict:
    path = tmp_path / "main.tex"
    path.write_text(text, encoding="utf-8")
    return nc.analyze(nc.flatten_tex(path, tmp_path), {**nc.DEFAULT_LIMITS, **(limits or {})}, **kwargs)


def _codes(items: list[dict]) -> set[str]:
    return {item["code"] for item in items}


def test_main_text_over_limit_fails_and_appendix_tables_math_do_not_count(tmp_path: Path) -> None:
    body = ("\\section{Introduction}\n" + _words(80) + "\n"
            "\\begin{table}\\begin{tabular}{ll}" + " & ".join(["cell"] * 400) + "\\end{tabular}"
            "\\caption{Fitted values.}\\end{table}\n"
            "\\begin{equation}" + " + ".join(["x"] * 400) + "\\end{equation}\n")
    tail = "\\appendix\n\\section{Checks}\n" + _words(500) + "\n"
    result = _check(tmp_path, _doc(body, tail=tail), {"max_body_words": 100})
    metrics = result["metrics"]
    assert 80 <= metrics["body_words"] <= 100
    assert metrics["appendix_words"] >= 500
    assert result["valid"]
    result = _check(tmp_path, _doc(body + _words(50), tail=tail), {"max_body_words": 100})
    assert "NARRATIVE-BODY-LENGTH" in _codes(result["errors"])
    failure = next(e for e in result["errors"] if e["code"] == "NARRATIVE-BODY-LENGTH")
    assert "appendix" in failure["message"] and "Introduction" in failure["message"]


def test_page_limit_is_optional_and_estimated(tmp_path: Path) -> None:
    body = "\\section{Results}\n" + _words(1100) + "\n\\begin{figure}\\caption{A.}\\end{figure}\n"
    assert "NARRATIVE-BODY-PAGES" not in _codes(_check(tmp_path, _doc(body))["errors"])
    result = _check(tmp_path, _doc(body), {"max_body_pages": 1.5})
    assert "NARRATIVE-BODY-PAGES" in _codes(result["errors"])
    assert result["metrics"]["body_pages_estimate"] == pytest.approx(1100 / 550 + 0.35, abs=0.1)


def test_revision_history_fails_with_source_line_in_an_input_file(tmp_path: Path) -> None:
    (tmp_path / "sec-results.tex").write_text(
        "\\section{Results}\n"
        "The profiles are smooth.\n"
        "The high-resolution profiles replace all points, including those that had previously been excluded.\n"
        "经复核后，我们改用了新的星历。\n", encoding="utf-8")
    result = _check(tmp_path, _doc("\\input{sec-results}"))
    hits = [e for e in result["errors"] if e["code"] == "NARRATIVE-REVISION-HISTORY"]
    assert [(h["path"], h["line"]) for h in hits] == [("sec-results.tex", 3), ("sec-results.tex", 4)]
    assert not result["valid"]


@pytest.mark.parametrize("sentence", [
    "In the previous version of this paper we used a linear ephemeris.",
    "As requested by the referee, we have now added a timing analysis.",
    "This revision adds a third-light analysis.",
    "在上一版中我们使用了线性星历。",
    "根据审稿意见，补充了误差分析。",
])
def test_revision_history_phrases(tmp_path: Path, sentence: str) -> None:
    result = _check(tmp_path, _doc("\\section{Data}\n" + sentence))
    assert "NARRATIVE-REVISION-HISTORY" in _codes(result["errors"])


@pytest.mark.parametrize("sentence", [
    "The previous version of the catalogue (DR2) listed a shorter period.",
    "Smith et al. previously reported a period of 0.5 d.",
    "We removed outliers before fitting.",
])
def test_ordinary_scientific_sentences_are_not_revision_history(tmp_path: Path, sentence: str) -> None:
    result = _check(tmp_path, _doc("\\section{Data}\n" + sentence))
    assert "NARRATIVE-REVISION-HISTORY" not in _codes(result["errors"])


def test_credit_role_in_back_matter_is_not_scanned(tmp_path: Path) -> None:
    result = _check(tmp_path, _doc("\\section{Data}\n" + _words(30)))
    assert result["valid"], result["errors"]


def test_abstract_numbers_statistics_and_parentheticals_warn(tmp_path: Path) -> None:
    abstract = ("We obtain $q=\\qAdopt\\pm0.007$ (heuristic) and $i=81.3\\pm0.3\\pm2.0$ deg; "
                "profile likelihoods give $\\Delta\\ln L\\le2$ for $-0.24\\le l_3\\le0.02$ (sector 62 of the "
                "survey) and $-0.19\\le l_3\\le0.03$ (sector 89 of the survey), $f=0.31\\pm0.01$ "
                "(non-negative third light chains) and $T_2/T_1=1.005\\pm0.002$ (both products used).")
    result = _check(tmp_path, _doc("\\section{Data}\n" + _words(30), abstract=abstract))
    codes = _codes(result["warnings"])
    assert {"NARRATIVE-ABSTRACT-NUMBERS", "NARRATIVE-ABSTRACT-TEST-STATISTICS",
            "NARRATIVE-ABSTRACT-PARENTHETICALS"} <= codes
    abstract_metrics = result["metrics"]["abstract"]
    assert abstract_metrics["numbers"] >= 15  # the value macro \qAdopt counts as a number
    assert result["valid"]  # warnings only


def test_plain_abstract_has_no_warnings(tmp_path: Path) -> None:
    abstract = ("V0651 Hya is a contact binary. Six TESS sectors show a total eclipse, and the light-curve "
                "solution gives a mass ratio of $0.28\\pm0.03$. The period has increased since 2001.")
    result = _check(tmp_path, _doc("\\section{Data}\n" + _words(30), abstract=abstract))
    assert not {c for c in _codes(result["warnings"]) if c.startswith("NARRATIVE-ABSTRACT")}


def test_hedges_fillers_and_overqualified_conclusions_are_located(tmp_path: Path) -> None:
    body = ("\\section{Results}\n" + _words(200) + "\n"
            "It is worth noting that the period may increase. Moreover, the fit could suggest a spot.\n"
            "值得注意的是，周期可能在增加。综上所述，结果似乎可靠。\n"
            "\\section{Conclusions}\n"
            "Within the geometries tested, the light curves alone do not exclude negative third light "
            "(sector 62 and sector 89 of the survey), although the mass ratio is well defined.\n"
            "The light curves suggest, only within the tested models, a total eclipse (in every resolved "
            "sector of the data), but the ridge remains.\n"
            "We find, assuming the adopted mesh, that the period may increase (secular or cyclic form), "
            "though the form is open.\n")
    result = _check(tmp_path, _doc(body))
    codes = _codes(result["warnings"])
    assert {"NARRATIVE-HEDGE-DENSITY", "NARRATIVE-FILLER-TRANSITIONS",
            "NARRATIVE-CONCLUSION-QUALIFIERS"} <= codes
    fillers = [w for w in result["warnings"] if w["code"] == "NARRATIVE-FILLER-TRANSITIONS" and "\"" in w["message"]]
    assert {w["line"] for w in fillers} >= {11, 12}
    assert any("综上所述" in w["message"] for w in fillers)
    conclusions = [w for w in result["warnings"]
                   if w["code"] == "NARRATIVE-CONCLUSION-QUALIFIERS" and w.get("context")]
    assert all(w["line"] >= 14 for w in conclusions) and len(conclusions) == 3
    assert result["valid"]


def test_stacked_qualifiers_skip_captions(tmp_path: Path) -> None:
    caption = ("\\begin{figure}\\caption{Profiles (solid: signed third light) and chains (dashed: "
               "non-negative third light), shown (top panel) with bands (light shading).}\\end{figure}\n")
    result = _check(tmp_path, _doc("\\section{Results}\n" + _words(40) + "\n" + caption * 8),
                    {"max_stacked_sentences": 0})
    assert "NARRATIVE-STACKED-QUALIFIERS" not in _codes(result["warnings"])


def test_warnings_blocking_promotes_warnings(tmp_path: Path) -> None:
    text = _doc("\\section{Results}\nIt is worth noting that X holds. Notably, Y holds. " + _words(20))
    assert _check(tmp_path, text)["valid"]
    result = _check(tmp_path, text, {"warnings_blocking": True})
    assert not result["valid"] and "NARRATIVE-FILLER-TRANSITIONS" in _codes(result["errors"])


def test_body_growth_warns_unless_main_text_was_requested(tmp_path: Path) -> None:
    text = _doc("\\section{Results}\n" + _words(300))
    result = _check(tmp_path, text, previous_body_words=250)
    assert "NARRATIVE-BODY-GROWTH" in _codes(result["warnings"])
    result = _check(tmp_path, text, previous_body_words=250, main_text_growth_requested=True)
    assert "NARRATIVE-BODY-GROWTH" not in _codes(result["warnings"])
    assert "allowed" in result["metrics"]["body_growth_note"]
    assert "NARRATIVE-BODY-GROWTH" not in _codes(_check(tmp_path, text, previous_body_words=300)["warnings"])


def test_limit_layers() -> None:
    limits, sources = nc.resolve_limits({"target_journal_article_type": "Letter"})
    assert limits["max_body_words"] == 3500 and sources[-1] == "article_type:letter"
    assert nc.resolve_limits({"venue_type": "conference"})[0]["max_body_words"] == 6500
    assert nc.resolve_limits({"domain": "math"})[0]["max_body_words"] == 14000
    settings = {"quality_gate": {"narrative": {"max_body_words": 8000, "unknown": 1,
                                               "article_types": {"letter": {"max_body_words": 4000}}}}}
    assert nc.resolve_limits({}, settings=settings)[0]["max_body_words"] == 8000
    assert "unknown" not in nc.resolve_limits({}, settings=settings)[0]
    assert nc.resolve_limits({"article_type": "letter"}, settings=settings)[0]["max_body_words"] == 4000
    line = {"id": "astro-survey-photometry", "paper_narrative": {"max_body_words": 6000}}
    limits, sources = nc.resolve_limits({}, settings=settings, line=line)
    assert limits["max_body_words"] == 6000 and "research_line:astro-survey-photometry" in sources
    limits, sources = nc.resolve_limits({"narrative_limits": {"max_body_words": 9000}}, settings=settings,
                                        line=line)
    assert limits["max_body_words"] == 9000 and sources[-1] == "paper.narrative_limits"


# --------------------------------------------------------------------------- registry integration


PAPER = "20261119-physics-photometry-example"


def _paper(tmp_path: Path, body: str, *, record_extra: str = "", lines_yaml: str | None = None) -> Path:
    manuscript = tmp_path / "papers" / PAPER / "manuscript"
    manuscript.mkdir(parents=True)
    (manuscript / "main.tex").write_text(_doc(body), encoding="utf-8")
    registry = tmp_path / "registry" / "papers"
    registry.mkdir(parents=True)
    (registry / f"{PAPER}.yaml").write_text(
        f"paper_id: {PAPER}\ncreated_at: '2026-11-19'\ndomain: physics\nsubdomain: photometry\n"
        f"manuscript_dir: papers/{PAPER}/manuscript\nlatest_source: papers/{PAPER}/manuscript/main.tex\n"
        f"target_journal: Example Journal\nversion: 0.1.0\n{record_extra}", encoding="utf-8")
    (tmp_path / "registry" / "settings.yaml").write_text(
        "schema_version: ara.paper_writing.registry.v1\nquality_gate:\n  require_ai_use_declaration: false\n"
        "  narrative:\n    max_body_words: 120\n", encoding="utf-8")
    if lines_yaml:
        (tmp_path / "registry" / "research-lines.yaml").write_text(lines_yaml, encoding="utf-8")
    return manuscript


def test_style_check_carries_narrative_failures_and_blocks_review(tmp_path: Path) -> None:
    _paper(tmp_path, "\\section{Results}\n" + _words(200) + "\nNotably, it holds.")
    result = audit_manuscript_style(PAPER, root=tmp_path, require_ai_declaration=False)
    assert not result["valid"]
    failure = next(e for e in result["errors"] if e["code"] == "NARRATIVE-BODY-LENGTH")
    assert failure["path"] == f"papers/{PAPER}/manuscript/main.tex"
    assert result["narrative"]["limits"]["max_body_words"] == 120
    assert "settings.quality_gate.narrative" in result["narrative"]["limit_sources"]
    blockers, advisories = manuscript_style_review_findings(result)
    assert any(b.startswith("NARRATIVE-BODY-LENGTH") for b in blockers)
    assert {a["kind"] for a in advisories if a["source"] == "narrative_check"} <= {"narrative"}


def test_style_check_passes_a_short_plain_paper(tmp_path: Path) -> None:
    _paper(tmp_path, "\\section{Results}\n" + _words(60))
    result = audit_manuscript_style(PAPER, root=tmp_path, require_ai_declaration=False)
    assert result["valid"], result["errors"]


def test_research_line_limits_apply_through_the_paper_record(tmp_path: Path) -> None:
    _paper(tmp_path, "\\section{Results}\n" + _words(200), record_extra="research_line: astro\n",
           lines_yaml="lines:\n  - id: astro\n    paper_narrative:\n      max_body_words: 500\n")
    result = nc.check_paper(PAPER, root=tmp_path)
    assert result["valid"] and result["limits"]["max_body_words"] == 500


def test_growth_against_the_last_reviewed_snapshot(tmp_path: Path) -> None:
    manuscript = _paper(tmp_path, "\\section{Results}\n" + _words(100))
    run = tmp_path / "reviews" / "unified" / PAPER / "20261118T000000Z"
    run.mkdir(parents=True)
    (run / "manuscript-expanded.tex").write_text(_doc("\\section{Results}\n" + _words(60)), encoding="utf-8")
    decision = {"stage_reached": "decision", "merged": {"required_changes": [
        {"change": "add a check", "type": "evidence", "location": "Sect. 3", "main_claim": False,
         "placement": "appendix_or_response"}]}}
    (run / "decision.json").write_text(json.dumps(decision), encoding="utf-8")
    result = nc.check_paper(PAPER, root=tmp_path)
    assert result["metrics"]["previous_body_words"] < result["metrics"]["body_words"]
    assert "NARRATIVE-BODY-GROWTH" in _codes(result["warnings"])
    decision["merged"]["required_changes"][0]["placement"] = "main_text"
    (run / "decision.json").write_text(json.dumps(decision), encoding="utf-8")
    assert "NARRATIVE-BODY-GROWTH" not in _codes(nc.check_paper(PAPER, root=tmp_path)["warnings"])
    assert manuscript.is_dir()


def test_cli_narrative_check_reports_and_exits(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "main.tex"
    path.write_text(_doc("\\section{Results}\n" + _words(60)), encoding="utf-8")
    out = tmp_path / "report.md"
    assert cli(["narrative-check", "--tex", str(path), "--out", str(out), "--root", str(tmp_path)]) == 0
    assert "Main-text words" in out.read_text()
    capsys.readouterr()
    path.write_text(_doc("\\section{Results}\nIn the previous draft we used a linear fit."), encoding="utf-8")
    assert cli(["narrative-check", "--tex", str(path), "--json", "--root", str(tmp_path)]) == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["errors"][0]["code"] == "NARRATIVE-REVISION-HISTORY" and printed["errors"][0]["line"]


# --------------------------------------------------------------------------- reader check


ANSWER = {
    "one_sentence_summary": "The paper solves the light curve of one contact binary.",
    "main_result": "Mass ratio 0.28 +- 0.03.",
    "stopped_reading": {"would_stop": True, "location": "Sect. 4.2", "reason": "mesh diagnostics"},
    "defensive_passages": [{"location": "Abstract", "quote": "do not exclude", "why": "caveat"}],
    "hard_to_follow": [],
    "cuts": [{"location": "Sect. 4.2", "what": "move the 1500-triangle profiles to an appendix"}],
    "verdict": "would_skim",
}


def test_reader_check_packet_omits_appendix_and_records_answer(tmp_path: Path, monkeypatch) -> None:
    manuscript = _paper(tmp_path, "\\section{Results}\nThe mass ratio is \\qAdopt.")
    main = manuscript / "main.tex"
    main.write_text(main.read_text().replace("\\bibliography", "\\appendix\n\\section{Mesh}\nSECRET-APPENDIX\n"
                                                                 "\\bibliography"), encoding="utf-8")
    text, digest, metadata = reader_check.packet(PAPER, tmp_path)
    assert "0.275" in text and "SECRET-APPENDIX" not in text and "Example Journal" in text
    seen = {}

    def fake_run_role(**kwargs):
        seen.update(kwargs)
        kwargs["workdir"].mkdir(parents=True)
        return dict(ANSWER), {"model": kwargs["role"]["model"]}

    monkeypatch.setattr("paper_writing.review_launcher.run_role", fake_run_role)
    role = {"provider": "anthropic", "tool": "Claude Code", "model": "claude-test"}
    record = reader_check.run(PAPER, root=tmp_path, role=role)
    assert seen["schema"] is reader_check.READER_SCHEMA and "SECRET-APPENDIX" not in seen["user_prompt"]
    notes = tmp_path / "papers" / PAPER / "writing"
    saved = json.loads((notes / "reader-check.json").read_text())
    assert saved["main_text_sha256"] == digest and saved["reader_model"] == "claude-test"
    assert "Sect. 4.2" in (notes / "reader-check.md").read_text()
    assert record["paths"][0].endswith("writing/reader-check.md")
    assert reader_check.current_record(notes, digest)["matches_current_main_text"] is True
    assert reader_check.current_record(notes, "0" * 64)["matches_current_main_text"] is False
    # Nothing is written inside the manuscript snapshot.
    assert not any(p.name.startswith("reader-check") for p in manuscript.rglob("*"))


def test_reader_check_prompt_only_and_record(tmp_path: Path) -> None:
    _paper(tmp_path, "\\section{Results}\nThe mass ratio is 0.28.")
    result = reader_check.run(PAPER, root=tmp_path, prompt_only=True)
    prompt = (tmp_path / result["prompt"]).read_text()
    assert "read it once" in prompt and "The mass ratio is 0.28." in prompt
    answer = tmp_path / "answer.json"
    answer.write_text(json.dumps(ANSWER))
    record = reader_check.run(PAPER, root=tmp_path, record=answer)
    assert record["answer"]["verdict"] == "would_skim"
    bad = dict(ANSWER, verdict="great")
    answer.write_text(json.dumps(bad))
    with pytest.raises(Exception):
        reader_check.run(PAPER, root=tmp_path, record=answer)


def test_reader_role_defaults_to_review_worker_tier() -> None:
    settings = {"review": {"roles": {"editor": {"provider": "openai-codex", "tool": "Codex", "model": "big"},
                                     "formal_verifier": {"provider": "openai-codex", "tool": "Codex",
                                                         "model": "small"}}}}
    assert reader_check.reader_role(settings)["model"] == "small"
    settings["quality_gate"] = {"reader_check": {"role": {"provider": "anthropic", "tool": "Claude Code",
                                                          "model": "reader"}}}
    assert reader_check.reader_role(settings)["model"] == "reader"
    assert reader_check.reader_role(settings, {"model": "cli"})["model"] == "cli"
    with pytest.raises(ValueError):
        reader_check.reader_role({})


# --------------------------------------------------------------------------- unified review wiring


def test_referee_items_carry_a_placement() -> None:
    from paper_writing import review_flow

    item = review_flow.REFEREE_SCHEMA["properties"]["required_changes"]["items"]
    assert "placement" in item["required"]
    assert item["properties"]["placement"]["enum"] == ["main_text", "supplement", "archive", "response_only", "cut"]
    # The derived per-round schema keeps it.
    derived = review_flow.referee_schema_for_previous(None)
    assert "placement" in derived["properties"]["required_changes"]["items"]["required"]


def test_body_length_and_reader_check_reach_the_editor(tmp_path: Path) -> None:
    from paper_writing import review_flow

    _paper(tmp_path, "\\section{Results}\n" + _words(200))
    block = review_flow.body_length_block(PAPER, tmp_path)
    assert block["main_text_words"] > block["limit_words"] == 120
    assert any(f.startswith("NARRATIVE-BODY-LENGTH") for f in block["findings"])
    assert "## Main-text length" in review_flow._body_length_packet({"body_length": block})
    assert review_flow._body_length_packet({}) == ""
    metadata = {"manuscript_dir": f"papers/{PAPER}/manuscript"}
    assert review_flow._reader_check_packet(PAPER, tmp_path, metadata) is None
    answer = tmp_path / "answer.json"
    answer.write_text(json.dumps(ANSWER))
    reader_check.run(PAPER, root=tmp_path, record=answer)
    packet = review_flow._reader_check_packet(PAPER, tmp_path, metadata)
    assert packet["matches_current_main_text"] is True and packet["answer"]["verdict"] == "would_skim"


def test_review_prompts_state_the_placement_rules() -> None:
    from paper_writing import review_flow

    referee = (review_flow.PROMPTS / "referee.md").read_text()
    assert "response_only" in referee and "ask for cuts" in referee
    assert "main_text_length" in (review_flow.PROMPTS / "decision.md").read_text()
    assert "main-text word count" in (review_flow.PROMPTS / "editor.md").read_text()
    assert "do not mark a gap or error because the main text does not repeat it" in \
        (review_flow.PROMPTS / "formal.md").read_text()
