"""Submission package (投稿包) and single-file LaTeX flattening (2026-11-25)."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import pytest

from paper_writing import flatten_tex, submission_bundle
from paper_writing.handoff import _receipt_matches_artifacts, build_handoff_package


# --------------------------------------------------------------------------- flatten

def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_flatten_inlines_inputs_packages_and_one_bibliography(tmp_path: Path) -> None:
    _write(tmp_path / "main.tex", "\n".join([
        "\\documentclass{journal}",
        "\\usepackage{amsmath,mymacros}",
        "\\usepackage[draft]{optioned}",
        "\\graphicspath{{img/}}",
        "\\input{numbers}",
        "\\begin{document}",
        "% \\input{commented}",
        "Text \\input{inline} more.",
        "\\include{chapter}",
        "\\begin{tabular}{ll}",
        "\\input{rows}",
        "\\end{tabular}",
        "\\includegraphics[width=\\textwidth]{fig1}",
        "\\bibliographystyle{journalstyle}",
        "\\bibliography{refs,extra}",
        "\\end{document}",
    ]))
    _write(tmp_path / "journal.cls", "\\RequirePackage{helper}\n")
    _write(tmp_path / "helper.sty", "% loaded by the class\n")
    _write(tmp_path / "journalstyle.bst", "ENTRY")
    _write(tmp_path / "mymacros.sty", "\\ProvidesPackage{mymacros}\n\\newcommand{\\R}{\\mathbb{R}}\n\\endinput\nignored\n")
    _write(tmp_path / "optioned.sty", "\\DeclareOption{draft}{}\\ProcessOptions\n")
    _write(tmp_path / "numbers.tex", "\\newcommand{\\N}{42}\n")
    _write(tmp_path / "inline.tex", "inlined words\n")
    _write(tmp_path / "chapter.tex", "Chapter text\n")
    _write(tmp_path / "rows.tex", "a & b \\\\\n\\bottomrule\n")
    _write(tmp_path / "commented.tex", "must not appear\n")
    _write(tmp_path / "refs.bib", "@article{a, title={A}}\n")
    _write(tmp_path / "extra.bib", "@article{b, title={B}}\n")
    (tmp_path / "img").mkdir()
    (tmp_path / "img/fig1.pdf").write_bytes(b"%PDF fig")
    (tmp_path / "img/unused.pdf").write_bytes(b"%PDF unused")
    _write(tmp_path / "notes.md", "internal")

    result = flatten_tex.flatten(tmp_path)

    text = result.main_tex
    assert "\\newcommand{\\R}{\\mathbb{R}}" in text and "ignored" not in text
    assert "\\usepackage{amsmath}" in text and "\\usepackage[draft]{optioned}" in text
    assert "\\newcommand{\\N}{42}" in text and "must not appear" not in text
    assert "Text %\n% ---- begin inline.tex ----\ninlined words\n% ---- end inline.tex ----\n\\relax{} more." in text
    assert "\\clearpage%\n% ---- begin chapter.tex (\\include) ----\nChapter text" in text
    # LaTeX's \input{...} hooks open an empty table row; \relax{} keeps that row.
    assert "\\bottomrule\n% ---- end rows.tex ----\n\\relax{}" in text
    assert "\\bibliography{references}" in text
    assert result.bib.count("@article") == 2
    assert set(result.files) == {"journal.cls", "helper.sty", "journalstyle.bst", "optioned.sty",
                                 "img/fig1.pdf"}
    assert "img/unused.pdf" in result.report["excluded"] and "notes.md" in result.report["excluded"]

    out = tmp_path.parent / "flat"
    written = flatten_tex.write(result, out)
    assert sorted(written) == sorted(["main.tex", "references.bib", *result.files])
    assert flatten_tex.flatten(tmp_path).main_tex == text  # deterministic


def test_flatten_takes_a_bibliography_style_named_by_a_class_option(tmp_path: Path) -> None:
    _write(tmp_path / "main.tex", "\\documentclass[sn-mathphys-ay]{sn-jnl}\\begin{document}x\\end{document}")
    _write(tmp_path / "sn-jnl.cls", "% class")
    _write(tmp_path / "sn-mathphys-ay.bst", "ENTRY")
    _write(tmp_path / "unrelated.bst", "ENTRY")
    assert set(flatten_tex.flatten(tmp_path).files) == {"sn-jnl.cls", "sn-mathphys-ay.bst"}


def test_flatten_refuses_missing_figures_and_unsupported_reads(tmp_path: Path) -> None:
    _write(tmp_path / "main.tex", "\\begin{document}\\includegraphics{missing}\\end{document}")
    with pytest.raises(flatten_tex.FlattenError, match="missing"):
        flatten_tex.flatten(tmp_path)
    _write(tmp_path / "main.tex", "\\begin{document}\\lstinputlisting{code.py}\\end{document}")
    with pytest.raises(flatten_tex.FlattenError, match="unsupported"):
        flatten_tex.flatten(tmp_path)


@pytest.mark.skipif(not (shutil.which("latexmk") or
                         (Path.home() / ".local/opt/texlive/bin/x86_64-linux/latexmk").is_file())
                    or not shutil.which("pdftotext"), reason="TeX tools not installed")
def test_verify_compiles_both_and_compares_pages(tmp_path: Path) -> None:
    _write(tmp_path / "main.tex", "\\documentclass{article}\n\\begin{document}\nIntro \\input{part} end.\n"
                                  "\\begin{tabular}{l}\nx\\\\\n\\input{rows}\n\\end{tabular}\n\\end{document}\n")
    _write(tmp_path / "part.tex", "middle")
    _write(tmp_path / "rows.tex", "y\\\\\n")
    result = flatten_tex.verify(tmp_path)
    assert result["equivalent"], result


# --------------------------------------------------------------------------- reviewers and numbers

BIB = """
@article{calafat, author={Calafat, Antonia M. and Kato, Kayoko}, title={Trends}, year={2019},
  journal={Env}, doi={10.1/abc}}
@article{nodoi, author={Smith, Jane}, title={No identifier}, year={2020}}
@article{ours, author={Chen, Zhipeng and Doe, John}, title={Coauthored}, year={2021}, doi={10.1/x}}
@article{uncited, author={Brown, Bob}, title={Uncited}, year={2022}, doi={10.1/y}}
"""


def test_reviewers_must_be_verifiable_authors_of_cited_work_without_conflicts() -> None:
    bib = submission_bundle.parse_bib(BIB)
    cited = {"calafat", "nodoi", "ours"}
    candidates = [
        {"name": "Antonia M. Calafat", "bib_key": "calafat", "institution": "CDC", "reason": "expert"},
        {"name": "Jane Smith", "bib_key": "nodoi", "institution": "", "reason": "r"},
        {"name": "John Doe", "bib_key": "ours", "institution": "", "reason": "r"},
        {"name": "Bob Brown", "bib_key": "uncited", "institution": "", "reason": "r"},
        {"name": "Invented Person", "bib_key": "calafat", "institution": "", "reason": "r"},
        {"name": "Kayoko Kato", "bib_key": "calafat", "institution": "Our Lab", "reason": "r"},
        {"name": "Zhipeng Chen", "bib_key": "ours", "institution": "", "reason": "r"},
    ]
    kept, dropped = submission_bundle.verify_reviewers(
        candidates, bib=bib, cited=cited, authors=["Zhipeng Chen"], affiliations=["Our Lab"])
    assert [item["name"] for item in kept] == ["Antonia M. Calafat"]
    assert kept[0]["evidence"]["link"] == "https://doi.org/10.1/abc"
    assert kept[0]["status"] == submission_bundle.PENDING_HUMAN
    reasons = {item["name"]: item["reason"] for item in dropped}
    assert "no DOI" in reasons["Jane Smith"]
    assert "co-authored" in reasons["John Doe"]
    assert "not cited" in reasons["Bob Brown"]
    assert "not an author" in reasons["Invented Person"]
    assert "affiliation" in reasons["Kayoko Kato"]
    assert "author of this paper" in reasons["Zhipeng Chen"]


def test_cover_letter_numbers_must_occur_in_the_manuscript() -> None:
    manuscript = "The share fell from 79.3% to 2.6% (95% CI 1.7–3.8) among 15,162 adults."
    assert submission_bundle.number_mismatches("fell to 2.6% in 15,162 adults (1.7–3.8)", manuscript) == []
    assert submission_bundle.number_mismatches("fell to 2.5%", manuscript) == ["2.5"]


def test_latex_to_text_keeps_run_in_headings_and_cited_links() -> None:
    text = submission_bundle.latex_to_text(
        "\\noindent\\textbf{Background:} 2.6\\% (CI 1.7--3.8) archived~\\citep{z}.",
        cite=lambda keys: " (https://doi.org/10.5281/zenodo.1)")
    assert text == "Background: 2.6% (CI 1.7–3.8) archived (https://doi.org/10.5281/zenodo.1)."


# --------------------------------------------------------------------------- package and handoff

def _repo(tmp_path: Path) -> tuple[str, Path]:
    paper_id = "20261125-biology-exposure-package-test"
    manuscript = tmp_path / "papers" / paper_id / "manuscript"
    _write(manuscript / "main.tex", "\n".join([
        "\\documentclass{article}", "\\begin{document}",
        "\\begin{abstract}We find 12.5\\% fewer cases.\\end{abstract}",
        "\\section{Results}\\input{results}",
        "\\includegraphics{figures/fig1.pdf}",
        "\\section*{Declaration of competing interest}None.",
        "\\section*{Data availability}Data are archived~\\cite{zen}.",
        "\\bibliography{refs}", "\\end{document}"]))
    _write(manuscript / "results.tex", "Cases fell by 12.5\\%~\\cite{calafat}.\n")
    _write(manuscript / "refs.bib", BIB + "@misc{zen, title={Support}, doi={10.5281/zenodo.9}}\n")
    (manuscript / "figures").mkdir()
    (manuscript / "figures/fig1.pdf").write_bytes(b"%PDF fig")
    (manuscript / "figures/unused.png").write_bytes(b"png")
    (manuscript / "main.pdf").write_bytes(b"%PDF main")
    _write(manuscript / "highlights.txt", "- One\n")
    _write(tmp_path / "registry/papers" / f"{paper_id}.yaml", "\n".join([
        f"paper_id: {paper_id}", "title: Package test", "version: 1.0.0", "domain: biology",
        f"manuscript_dir: papers/{paper_id}/manuscript",
        f"latest_pdf: papers/{paper_id}/manuscript/main.pdf",
        "target_journal: Nature Communications",
        "authors:", "- name: Zhipeng Chen", "  corresponding: true", "  affiliation_ids: [lab]",
        "affiliations:", "- id: lab", "  name: Our Lab",
        "funding_statement:", "  text: No funding.", ""]))
    return paper_id, manuscript


def test_handoff_uploads_a_deterministic_submission_package(tmp_path: Path) -> None:
    paper_id, _ = _repo(tmp_path)
    first = build_handoff_package(paper_id, root=tmp_path, output=tmp_path / "dist1")
    second = build_handoff_package(paper_id, root=tmp_path, output=tmp_path / "dist2")
    assert first["source"]["filename"] == "submission-package.zip"
    assert first["source"]["kind"] == "submission_package"
    assert first["source"]["sha256"] == second["source"]["sha256"]
    assert first["package_id"] == second["package_id"]
    assert first["release"]["source_artifact"]["kind"] == "submission_package"
    assert first["release"]["source_artifact"]["profile"] == "nature_communications"
    with zipfile.ZipFile(tmp_path / "dist1/submission-package.zip") as archive:
        names = set(archive.namelist())
        main = archive.read("01-manuscript/latex/main.tex").decode()
        readme = archive.read("README.md").decode()
        fields = archive.read("04-declarations/portal-fields.md").decode()
        manifest = json.loads(archive.read("submission-package.json"))
    assert {"README.md", "submission-package.json", "01-manuscript/manuscript.pdf",
            "01-manuscript/latex/main.tex", "01-manuscript/latex/references.bib",
            "01-manuscript/latex/figures/fig1.pdf", "03-cover-letter/cover-letter-TEMPLATE.md",
            "04-declarations/portal-fields.md"} <= names
    assert "01-manuscript/latex/figures/unused.png" not in names
    # NC takes no highlights; the file stays out of an NC package.
    assert "05-journal-items/highlights.txt" not in names
    assert "Cases fell by 12.5" in main and "\\input{results}" not in main
    assert "CV" in readme and "Reporting Summary" in readme and "适用" in readme
    assert "https://doi.org/10.5281/zenodo.9" in fields and "No funding." in fields
    # Nothing drafted yet and no contribution statement: reported, not blocking.
    assert manifest["missing_required"] == ["cover_letter", "author_contributions"]
    assert manifest["cover_letter"]["present"] is False


def test_a_version_delivered_with_the_old_source_zip_keeps_it(tmp_path: Path) -> None:
    paper_id, _ = _repo(tmp_path)
    receipt = tmp_path / "papers" / paper_id / "releases" / "pkg_old.json"
    _write(receipt, json.dumps({"paper_id": paper_id, "version": "1.0.0",
                                "source": {"filename": "source.zip"}}))
    result = build_handoff_package(paper_id, root=tmp_path, output=tmp_path / "dist")
    assert result["source"]["filename"] == "source.zip"
    assert "source_artifact" not in result["release"]


def test_receipts_match_a_package_by_its_manuscript_members(tmp_path: Path) -> None:
    paper_id, _ = _repo(tmp_path)
    manifest = build_handoff_package(paper_id, root=tmp_path, output=tmp_path / "dist")
    receipt = {"paper_id": paper_id, "version": "1.0.0", "pdf": dict(manifest["pdf"]),
               "source": {"filename": manifest["source"]["filename"], "size": 1, "sha256": "0" * 64,
                          "identity_sha256": manifest["source"]["identity_sha256"]}}
    assert _receipt_matches_artifacts(receipt, manifest)  # README/letter changed, manuscript not
    receipt["source"]["identity_sha256"] = "1" * 64
    assert not _receipt_matches_artifacts(receipt, manifest)


def test_prepare_drafts_a_checked_letter_and_verified_reviewers(tmp_path: Path, monkeypatch) -> None:
    paper_id, _ = _repo(tmp_path)
    monkeypatch.setattr(submission_bundle, "drafter_roles",
                        lambda _root: [("fake", {"provider": "fake", "model": "fake-model"})])
    calls = []

    def runner(*, role_name, role, system_prompt, user_prompt, schema, workdir, timeout):
        calls.append(user_prompt)
        number = "13.0" if len(calls) == 1 else "12.5"
        return ({"significance": f"Cases fell by {number}%.", "novelty": "New.", "fit": "Fits.",
                 "suggested_reviewers": [
                     {"name": "Calafat, Antonia M.", "bib_key": "calafat", "institution": "", "reason": "x"},
                     {"name": "Made Up", "bib_key": "calafat", "institution": "", "reason": "x"}]}, {})

    result = submission_bundle.prepare(paper_id, root=tmp_path, runner=runner, skip_verify=True)
    assert result["draft"]["status"] == "drafted" and len(calls) == 2
    assert "13.0" in calls[1] and "do not occur in the manuscript" in calls[1]
    drafts = submission_bundle.drafts_dir(tmp_path, paper_id)
    letter = (drafts / "cover-letter.md").read_text()
    assert "12.5%" in letter and "Zhipeng Chen" in letter and "Nature Communications" in letter
    reviewers = json.loads((drafts / "suggested-reviewers.json").read_text())
    assert [r["name"] for r in reviewers["suggested"]] == ["Antonia M. Calafat"]
    status = submission_bundle.materials_status(paper_id, root=tmp_path)
    assert status["reasons"] == ["verify"]  # drafted for 1.0.0; the LaTeX check was skipped
    manifest = build_handoff_package(paper_id, root=tmp_path, output=tmp_path / "dist")
    with zipfile.ZipFile(tmp_path / "dist/submission-package.zip") as archive:
        assert "03-cover-letter/cover-letter.md" in archive.namelist()
        assert "06-reviewers/suggested-reviewers.md" in archive.namelist()
    assert manifest["release"]["source_artifact"]["missing_required"] == ["author_contributions"]


def test_profiles_follow_journal_then_publisher(tmp_path: Path) -> None:
    select = submission_bundle.select_profile
    assert select({"target_journal": "Scientific Reports"}, tmp_path)[0] == "scientific_reports"
    assert select({"target_journal": "X", "target_journal_publisher": "Elsevier (Urban & Fischer)"},
                  tmp_path)[0] == "elsevier"
    assert select({"target_journal": "Y"}, tmp_path)[0] == "generic"
    nc = select({"target_journal": "Nature Communications"}, tmp_path)[1]
    assert next(i for i in nc["items"] if i["id"] == "cv")["status"] == "not_required"


def test_a_supplemented_version_keeps_its_submission_package(tmp_path: Path) -> None:
    """User 2026-11-26: delivered, unsubmitted versions get the package as a new upload."""
    paper_id, _ = _repo(tmp_path)
    releases = tmp_path / "papers" / paper_id / "releases"
    _write(releases / "pkg_old.json", json.dumps({"paper_id": paper_id, "version": "1.0.0",
                                                  "source": {"filename": "source.zip"}}))
    assert submission_bundle.legacy_source_required(tmp_path, paper_id, "1.0.0")
    forced = build_handoff_package(paper_id, root=tmp_path, output=tmp_path / "forced",
                                   submission_package=True)
    assert forced["source"]["filename"] == "submission-package.zip"
    _write(releases / "pkg_new.json", json.dumps({"paper_id": paper_id, "version": "1.0.0",
                                                  "source": {"filename": "submission-package.zip"}}))
    assert not submission_bundle.legacy_source_required(tmp_path, paper_id, "1.0.0")
    again = build_handoff_package(paper_id, root=tmp_path, output=tmp_path / "again")
    assert again["source"]["identity_sha256"] == forced["source"]["identity_sha256"]


def test_reviewer_verification_record_travels_with_the_package(tmp_path: Path) -> None:
    paper_id, _ = _repo(tmp_path)
    drafts = submission_bundle.drafts_dir(tmp_path, paper_id)
    _write(drafts / "suggested-reviewers.json", json.dumps({"suggested": [{
        "name": "Antonia M. Calafat", "institution": "CDC", "institution_verified": True,
        "evidence": {"title": "PFAS", "link": "https://doi.org/10.1/x"}, "reason": "r"}]}))
    _write(drafts / submission_bundle.VERIFICATION_FILENAME, json.dumps({
        "schema_version": submission_bundle.VERIFICATION_SCHEMA, "version": "1.0.0",
        "checked_on": "2026-11-26", "checked_by": "agent",
        "reviewers": [{"name": "Antonia M. Calafat", "decision": "keep", "exists": True,
                       "institution": "CDC", "research_area": "biomonitoring",
                       "recent_papers": [{"title": "T", "year": 2025, "url": "https://example.org/t"}],
                       "conflict_check": "no co-authorship", "sources": ["https://example.org/p"]},
                      {"name": "Gone Person", "decision": "remove", "exists": False,
                       "note": "no trace"}]}))
    manifest = submission_bundle.assemble(paper_id, root=tmp_path, metadata={
        **__import__("yaml").safe_load((tmp_path / "registry/papers" / f"{paper_id}.yaml").read_text())},
        output=tmp_path / "pkg")
    record = (tmp_path / "pkg/06-reviewers/reviewer-verification.md").read_text()
    assert "2026-11-26" in record and "https://example.org/p" in record and "删去" in record
    listing = (tmp_path / "pkg/06-reviewers/suggested-reviewers.md").read_text()
    assert "已核实 2026-11-26" in listing
    assert manifest["reviewers_verified_on"] == "2026-11-26"
    # A record of another version is not used.
    _write(drafts / submission_bundle.VERIFICATION_FILENAME, json.dumps({
        "schema_version": submission_bundle.VERIFICATION_SCHEMA, "version": "0.9.0",
        "checked_on": "2026-11-20", "reviewers": []}))
    other = submission_bundle.assemble(paper_id, root=tmp_path, metadata={
        **__import__("yaml").safe_load((tmp_path / "registry/papers" / f"{paper_id}.yaml").read_text())},
        output=tmp_path / "pkg2")
    assert other["reviewers_verified_on"] is None
    assert any("不属于 v1.0.0" in note for note in other["notes"])
