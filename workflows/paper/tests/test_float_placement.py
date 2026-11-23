import shutil
import subprocess

import pytest

from paper_writing import delivery_floor, float_placement

pdflatex = pytest.mark.skipif(not shutil.which("pdflatex"), reason="pdflatex not available")
FILLER = ("The measured quantity changes with the operating point and the comparison uses the same "
          "inputs in both arms of the experiment. ") * 9


def _graphic(path, height=200):
    fitz = float_placement._fitz()
    doc = fitz.open()
    page = doc.new_page(width=300, height=height)
    page.draw_rect(fitz.Rect(10, 10, 290, height - 10), color=(0, 0, 0), fill=(0.2, 0.4, 0.8))
    doc.save(str(path))
    doc.close()


def _paragraphs(count):
    return "\n\n".join(FILLER for _ in range(count))


def _compile(manuscript, body, preamble=""):
    (manuscript / "main.tex").write_text(
        "\\documentclass[12pt]{article}\n\\usepackage{graphicx}\n" + preamble +
        "\\begin{document}\n" + body + "\n\\end{document}\n")
    for _ in range(2):
        subprocess.run(["pdflatex", "-interaction=nonstopmode", "main.tex"], cwd=manuscript,
                       capture_output=True, timeout=120, check=False)
    assert (manuscript / "main.pdf").is_file()


@pdflatex
def test_figure_deferred_to_the_end_is_an_error_and_a_nearby_one_is_not(tmp_path):
    _graphic(tmp_path / "near.pdf")
    _graphic(tmp_path / "far.pdf", height=900)
    body = (
        "Figure~\\ref{fig:near} shows the design.\n\n"
        "\\begin{figure}[!htbp]\\centering\\includegraphics[width=.5\\linewidth]{near}"
        "\\caption{Design.}\\label{fig:near}\\end{figure}\n\n"
        + _paragraphs(2) +
        "\n\nThe outcome is in Fig.~\\ref{fig:far}b and Figs.~\\ref{fig:near} and~\\ref{fig:far}.\n\n"
        # A bottom-only float taller than \bottomfraction can never be placed and drifts to the end.
        "\\begin{figure}[b]\\centering\\includegraphics[height=.8\\textheight]{far}"
        "\\caption{Outcome.}\\label{fig:far}\\end{figure}\n\n" + _paragraphs(12))
    _compile(tmp_path, body)
    result = float_placement.check(tmp_path)
    near, far = result["figures"]
    assert near["page_source"] == "graphic" and near["distance"] == 0
    assert far["figure_page"] - far["first_reference_page"] > 1
    assert result["status"] == "errors"
    assert [(e["figure"], e["code"]) for e in result["errors"]] == [("fig:far", "FIG-FLOAT-FAR-FROM-REFERENCE")]


@pdflatex
def test_figure_far_before_its_first_mention_uses_the_caption_lead(tmp_path):
    body = (
        "\\begin{figure}[h]\\centering\\rule{4cm}{3cm}\\caption{Early.}\\label{fig:early}\\end{figure}\n\n"
        + _paragraphs(10) + "\n\nOnly now does Figure~\\ref{fig:early} come up.\n\n"
        "\\appendix\n\\section{Extra}\n"
        "\\begin{figure}[h]\\rule{2cm}{2cm}\\caption{Appendix only.}\\label{fig:app}\\end{figure}\n")
    _compile(tmp_path, body)
    result = float_placement.check(tmp_path)
    assert len(result["figures"]) == 1  # appendix figures are not checked
    fig = result["figures"][0]
    assert fig["page_source"] == "caption" and fig["figure_page"] == 1
    assert fig["first_reference_page"] > 2
    assert [e["code"] for e in result["errors"]] == ["FIG-FLOAT-BEFORE-REFERENCE"]


def test_reference_forms():
    found = lambda text: set().union(*(float_placement._numbers(m.group(1))
                                       for m in float_placement._REF.finditer(text)))
    assert found("as Fig. 3a,b shows") == {"3"}
    assert found("Figs. 2 and 4 compare") == {"2", "4"}
    assert found("Figures 2\u20135 and Figure A.1") == {"2", "3", "4", "5", "A.1"}
    assert found("Figure 7 summarises") == {"7"}
    assert not float_placement._caption_lead("3").search("see Figure 3 for details")
    assert float_placement._caption_lead("3").search("text\nFigure 3: Caption")


def test_states_without_a_proof(tmp_path):
    assert float_placement.check(tmp_path)["status"] == "no_source"
    (tmp_path / "main.tex").write_text("\\begin{document}No figures.\\end{document}")
    assert float_placement.check(tmp_path)["status"] == "no_figures"
    (tmp_path / "main.tex").write_text(
        "\\begin{document}See Figure~\\ref{f}.\\begin{figure*}[t]\\caption{X}\\label{f}\\end{figure*}"
        "\\end{document}")
    result = float_placement.check(tmp_path)
    assert result["status"] == "no_pdf" and not result["errors"]
    (tmp_path / "main.pdf").write_bytes(b"not a pdf")
    assert float_placement.check(tmp_path)["status"] == "unreadable"
    (tmp_path / "main.tex").write_text("\\usepackage{endfloat}" + (tmp_path / "main.tex").read_text())
    assert float_placement.check(tmp_path)["status"] == "endfloat"


def test_delivery_floor_reports_placement_errors(tmp_path, monkeypatch):
    manuscript = tmp_path / "papers/p/manuscript"
    manuscript.mkdir(parents=True)
    (manuscript / "main.tex").write_text(r"\author{A}\begin{document}Text.\end{document}")
    error = {"figure": "fig:x", "code": "FIG-FLOAT-FAR-FROM-REFERENCE", "message": "Figure 1 prints late."}
    monkeypatch.setattr(float_placement, "check",
                        lambda *a, **k: {"status": "errors", "errors": [error], "notes": [], "figures": []})
    result = delivery_floor.check("p", {"narrative_limits": {"min_body_words": 1}}, tmp_path, author=True)
    assert result["metrics"]["float_placement"] == "errors"
    assert "FIG-FLOAT-FAR-FROM-REFERENCE" in {i["code"] for i in result["issues"]}
