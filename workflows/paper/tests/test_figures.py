"""paper-writing figures: sources, rendering, checks, licences and review support."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from pathlib import Path

import pytest

from paper_writing import figures as fig
from paper_writing.__main__ import main

fitz = pytest.importorskip("pymupdf")

SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="200" height="80" viewBox="0 0 200 80">
<rect x="10" y="10" width="80" height="40" fill="#0072B2"/>
<text x="20" y="70" font-family="Arial" font-size="10">Label text</text></svg>"""


def _manuscript(tmp_path: Path, main_tex: str = "") -> Path:
    ms = tmp_path / "papers" / "p" / "manuscript"
    (ms / "figure-src").mkdir(parents=True)
    (ms / "figures").mkdir()
    (ms / "main.tex").write_text(main_tex or "\\documentclass{article}\\begin{document}x\\end{document}\n")
    return ms


def _pdf(path: Path, width: float, height: float, texts=(), image=False) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    page.draw_rect(fitz.Rect(2, 2, width - 2, height - 2), color=(0, 0, 0), width=0.5)
    for point, text, size in texts:
        page.insert_text(point, text, fontsize=size, fontname="helv")
    if image:
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 20), False)
        pix.clear_with(200)
        page.insert_image(page.rect, pixmap=pix, keep_proportion=False)
    doc.save(str(path))
    return path


@pytest.fixture
def no_chromium(monkeypatch):
    """Force the PyMuPDF SVG fallback so the tests do not need Chromium."""
    real = fig.resolve_tool
    monkeypatch.setattr(fig, "resolve_tool", lambda env, default: None if default == "chromium-pdf"
                        else real(env, default))


# --------------------------------------------------------------------------- tools and discovery
def test_configured_tool_must_exist(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENLABS_FIG_PYTHON", str(tmp_path / "missing-python"))
    with pytest.raises(fig.FigureToolError, match="OPENLABS_FIG_PYTHON"):
        fig.resolve_tool("OPENLABS_FIG_PYTHON", "paperfig-python")


def test_missing_tool_error_names_the_variable(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENLABS_FIG_X", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(fig.FigureToolError, match="set OPENLABS_FIG_X"):
        fig.require_tool("OPENLABS_FIG_X", "no-such-tool", "a test")


def test_discover_reads_sidecars_and_skips_helpers(tmp_path):
    ms = _manuscript(tmp_path)
    src = ms / "figure-src"
    (src / "fig-a.svg").write_text(SVG)
    (src / "fig-a.json").write_text(json.dumps({"kind": "schematic", "purpose": "p"}))
    (src / "_helper.py").write_text("")
    (src / "notes.txt").write_text("")
    (src / "assets").mkdir()
    (src / "assets" / "icon.svg").write_text(SVG)
    ws = fig.workspace(manuscript=ms)
    found = fig.discover(ws)
    assert [s.stem for s in found] == ["fig-a"] and found[0].sidecar["purpose"] == "p"
    (src / "fig-a.py").write_text("")
    with pytest.raises(fig.FigureToolError, match="Two sources"):
        fig.discover(ws)


def test_catalog_templates_exist_and_new_copies_one(tmp_path):
    catalog = fig.template_catalog()
    assert len(catalog) >= 8
    assert {Path(t["file"]).suffix for t in catalog} >= {".tex", ".py", ".svg"}
    for entry in catalog:
        assert (fig.TEMPLATES / entry["file"]).is_file() and entry["use_when"]
    ms = _manuscript(tmp_path)
    ws = fig.workspace(manuscript=ms)
    result = fig.new_figure(ws, "design", template="study-design")
    assert Path(result["source"]).name == "fig-design.tex"
    assert json.loads(Path(result["sidecar"]).read_text())["kind"] == "schematic"
    with pytest.raises(fig.FigureToolError, match="already exists"):
        fig.new_figure(ws, "design", kind="svg")
    assert Path(fig.new_figure(ws, "flow", kind="py")["source"]).suffix == ".py"


# --------------------------------------------------------------------------- build
def test_svg_build_is_vector_byte_stable_and_previews_outside_manuscript(tmp_path, no_chromium):
    ms = _manuscript(tmp_path)
    (ms / "figure-src" / "fig-a.svg").write_text(SVG)
    ws = fig.workspace(manuscript=ms)
    first = fig.build(ws)
    assert not first["failed"] and len(first["built"]) == 1
    pdf = ms / "figures" / "fig-a.pdf"
    preview = Path(first["built"][0]["preview"])
    assert pdf.is_file() and preview.is_file() and ms not in preview.parents
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    fig.build(ws)
    assert hashlib.sha256(pdf.read_bytes()).hexdigest() == digest
    with fitz.open(str(pdf)) as doc:
        assert doc.page_count == 1 and not doc[0].get_images()


def test_build_reports_a_missing_python_without_stopping_others(tmp_path, monkeypatch, no_chromium):
    ms = _manuscript(tmp_path)
    (ms / "figure-src" / "fig-a.svg").write_text(SVG)
    (ms / "figure-src" / "fig-b.py").write_text("print('x')\n")
    monkeypatch.setenv("OPENLABS_FIG_PYTHON", str(tmp_path / "nope"))
    result = fig.build(fig.workspace(manuscript=ms))
    assert [b["figure"] for b in result["built"]] == ["fig-a"]
    assert "OPENLABS_FIG_PYTHON" in result["failed"][0]["error"]


def test_python_source_runs_with_fig_out(tmp_path, monkeypatch):
    """A fake interpreter stands in for paperfig-python: the contract is $FIG_OUT."""
    script = tmp_path / "fake-python"
    script.write_text("#!/bin/sh\n" + shutil.which("python3") + " -c \"import os, pymupdf; d=pymupdf.open(); "
                      "p=d.new_page(width=100,height=50); p.insert_text((10,30),'Axis',fontsize=8); "
                      "d.save(os.environ['FIG_OUT'])\"\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("OPENLABS_FIG_PYTHON", str(script))
    ms = _manuscript(tmp_path)
    (ms / "figure-src" / "fig-c.py").write_text("# drawn by the fake\n")
    result = fig.build(fig.workspace(manuscript=ms))
    assert not result["failed"] and (ms / "figures" / "fig-c.pdf").is_file()


@pytest.mark.skipif(not shutil.which("lualatex"), reason="lualatex not available")
def test_tikz_fragment_is_wrapped_and_cropped(tmp_path):
    ms = _manuscript(tmp_path)
    (ms / "figure-src" / "fig-t.tex").write_text(
        "\\begin{tikzpicture}\\node[ol/process] (a) {Step};\\node[ol/process, right=of a] (b) {Next};"
        "\\draw[ol/flow] (a) -- (b);\\end{tikzpicture}\n")
    result = fig.build(fig.workspace(manuscript=ms))
    assert not result["failed"], result["failed"]
    assert result["built"][0]["width_mm"] < 60  # cropped to the drawing, not a page


def test_paper_build_refreshes_the_figure_manifest(tmp_path, no_chromium):
    ms = _manuscript(tmp_path)
    (ms / "figure-src" / "fig-a.svg").write_text(SVG)
    _pdf(ms / "figures" / "fig9-result.pdf", 100, 50, [((10, 30), "Result", 8)])
    ws = fig.workspace("p", root=tmp_path)
    result = fig.build(ws)
    manifest = json.loads(Path(result["manifest"]).read_text())
    assert manifest["schema_version"] == "ara.paper_writing.support_artifacts.v1"
    assert sorted(e["path"] for e in manifest["files"]) == [
        "papers/p/manuscript/figures/fig-a.pdf", "papers/p/manuscript/figures/fig9-result.pdf"]
    assert ws.preview_dir == tmp_path / "papers" / "p" / "build" / "figures"


# --------------------------------------------------------------------------- check
MAIN = r"""\documentclass{article}
\begin{document}
As Figure~\ref{fig:a} shows, the design is simple.
\begin{figure}\includegraphics[width=%s]{figures/fig-a}\caption{Design.}\label{fig:a}\end{figure}
\begin{figure}\includegraphics[width=\linewidth]{figures/fig-b.pdf}\end{figure}
\end{document}
"""


def _check(ms: Path, **kw):
    return fig.check(fig.workspace(manuscript=ms), rebuild=False, text_width="160mm", **kw)


def _codes(result, key="blocking"):
    return {(f["figure"], f["code"]) for f in result[key]}


def test_check_scales_fonts_to_the_printed_width(tmp_path):
    ms = _manuscript(tmp_path, MAIN % "40mm")
    (ms / "figure-src" / "fig-a.svg").write_text(SVG)
    _pdf(ms / "figures" / "fig-a.pdf", 300, 100, [((20, 50), "Readable at full size", 8)])
    result = _check(ms)
    record = next(f for f in result["figures"] if f["figure"] == "fig-a")
    assert record["final_width_mm"] == 40.0 and record["min_font_pt"] < 4
    assert ("fig-a", "FIG-FONT-TOO-SMALL") in _codes(result)
    ms2 = _manuscript(tmp_path / "ok", MAIN % "0.66\\textwidth")
    (ms2 / "figure-src" / "fig-a.svg").write_text(SVG)
    _pdf(ms2 / "figures" / "fig-a.pdf", 300, 100, [((20, 50), "Readable at full size", 8)])
    assert ("fig-a", "FIG-FONT-TOO-SMALL") not in _codes(_check(ms2))


def test_check_finds_missing_source_caption_and_citation(tmp_path):
    ms = _manuscript(tmp_path, MAIN.replace("As Figure~\\ref{fig:a} shows, the", "The") % "\\linewidth")
    (ms / "figure-src" / "fig-a.svg").write_text(SVG)
    _pdf(ms / "figures" / "fig-a.pdf", 300, 100, [((20, 50), "Design", 8)])
    _pdf(ms / "figures" / "fig-b.pdf", 300, 100, [((20, 50), "Result", 8)])
    codes = _codes(_check(ms))
    assert ("fig-a", "FIG-NOT-CITED") in codes
    assert ("fig-b", "FIG-NO-CAPTION") in codes and ("fig-b", "FIG-NO-SOURCE") in codes
    (ms / "figure-src" / "fig-b.json").write_text(json.dumps({"source": "../main.tex", "kind": "result"}))
    assert ("fig-b", "FIG-NO-SOURCE") not in _codes(_check(ms))


def test_check_flags_overlap_clipping_internal_words_and_raster(tmp_path):
    ms = _manuscript(tmp_path, MAIN % "\\linewidth")
    (ms / "figure-src" / "fig-a.svg").write_text(SVG)
    (ms / "figure-src" / "fig-b.svg").write_text(SVG)
    _pdf(ms / "figures" / "fig-a.pdf", 300, 100, [
        ((20, 50), "Overlapping label", 9), ((24, 51), "Second label here", 9),
        ((260, 90), "runs off the edge of the page", 8),
        ((20, 85), "see /workspace/run/plot.py from ChatGPT", 8)])
    _pdf(ms / "figures" / "fig-b.pdf", 300, 100, image=True)
    codes = _codes(_check(ms))
    for code in ("FIG-TEXT-OVERLAP", "FIG-TEXT-CLIPPED", "FIG-PATH", "FIG-AI-TOOL-NAME"):
        assert ("fig-a", code) in codes, code
    assert ("fig-b", "FIG-RASTER-PAGE") in codes


def test_check_reports_unbuilt_source_and_stale_pdf(tmp_path, no_chromium):
    ms = _manuscript(tmp_path, MAIN % "\\linewidth")
    (ms / "figure-src" / "fig-a.svg").write_text(SVG)
    (ms / "figure-src" / "fig-new.svg").write_text(SVG)
    _pdf(ms / "figures" / "fig-a.pdf", 300, 100, [((20, 50), "Old drawing", 8)])
    result = fig.check(fig.workspace(manuscript=ms), rebuild=True, text_width="160mm")
    assert ("fig-new", "FIG-NOT-BUILT") in _codes(result)
    assert ("fig-a", "FIG-STALE") in _codes(result, "advisory")


def test_width_parsing():
    widths = {"textwidth": 400.0, "columnwidth": 200.0, "linewidth": 200.0}
    assert fig._length_pt("0.5\\textwidth", widths) == 200.0
    assert fig._length_pt("\\linewidth", widths) == 200.0
    assert abs(fig._length_pt("25.4mm", widths) - 72.0) < 1e-6
    assert fig._length_pt("\\foo", widths) is None


@pytest.mark.skipif(not shutil.which("pdflatex"), reason="pdflatex not available")
def test_layout_probe_reads_the_preamble(tmp_path):
    ms = _manuscript(tmp_path, "\\documentclass[twocolumn]{article}\n\\begin{document}x\\end{document}\n")
    layout = fig.layout_widths(fig.workspace(manuscript=ms))
    assert layout["source"].startswith("LaTeX probe") and layout["columnwidth"] < layout["textwidth"]


# --------------------------------------------------------------------------- assets and licences
@pytest.mark.parametrize("licence,status", [
    ("CC0-1.0", "ok"), ("Public Domain", "ok"), ("CC BY 4.0", "attribution"),
    ("CC-BY-SA-4.0", "share_alike"), ("CC BY-NC 4.0", "incompatible"), ("CC BY-ND", "incompatible"),
    ("MIT", "attribution"), ("all rights reserved", "unknown"), ("", "unknown")])
def test_classify_license(licence, status):
    assert fig.classify_license(licence)[0] == status


def test_asset_licences_are_checked(tmp_path, no_chromium, monkeypatch):
    monkeypatch.setenv("OPENLABS_FIG_ASSETS", str(tmp_path / "library"))
    ms = _manuscript(tmp_path, MAIN % "\\linewidth")
    assets = ms / "figure-src" / "assets"
    assets.mkdir()
    (assets / "cell.svg").write_text(SVG)
    (assets / "mouse.svg").write_text(SVG)
    (assets / "mouse.license.json").write_text(json.dumps(
        {"source": "Bioicons", "license": "CC BY 4.0", "attribution": "Jane Doe", "url": "https://example.org"}))
    (assets / "pill.svg").write_text(SVG)
    (assets / "pill.svg.license.json").write_text(json.dumps(
        {"source": "x", "license": "CC BY-NC 4.0", "attribution": "y", "url": "z"}))
    library = tmp_path / "library" / "bio"
    library.mkdir(parents=True)
    (library / "dna.svg").write_text(SVG)
    (ms / "figure-src" / "fig-a.svg").write_text(SVG.replace("</svg>", "<!-- uses bio/dna.svg --></svg>"))
    codes = _codes(_check(ms))
    assert ("cell.svg", "FIG-ASSET-LICENSE-MISSING") in codes
    assert ("mouse.svg", "FIG-ASSET-CREDIT-MISSING") in codes
    assert ("pill.svg", "FIG-ASSET-LICENSE-INCOMPATIBLE") in codes
    assert ("dna.svg", "FIG-ASSET-LICENSE-MISSING") in codes
    (ms / "main.tex").write_text((MAIN % "\\linewidth").replace("Design.}", "Design. Mouse icon: Jane Doe.}"))
    assert ("mouse.svg", "FIG-ASSET-CREDIT-MISSING") not in _codes(_check(ms))


def test_recolor_maps_asset_colours_to_the_palette(tmp_path):
    helpers = fig._style_helpers()
    out = helpers.recolor_svg('<path fill="#ff0000" stroke="#123456"/><rect fill="#808080"/><g fill="#0f0"/>',
                              {"#123456": "wine"})
    assert '#D55E00' in out or '#882255' in out
    assert 'stroke="#882255"' in out and 'fill="#808080"' in out and "#0f0" not in out
    src = tmp_path / "a.svg"
    src.write_text(SVG.replace("#0072B2", "#1166aa"))
    assert main(["figures", "recolor", str(src), str(tmp_path / "b.svg")]) == 0
    assert "#0072B2" in (tmp_path / "b.svg").read_text()


# --------------------------------------------------------------------------- CLI and sheet
def test_cli_build_check_sheet(tmp_path, no_chromium, capsys):
    ms = _manuscript(tmp_path, MAIN % "\\linewidth")
    (ms / "figure-src" / "fig-a.svg").write_text(SVG)
    assert main(["figures", "build", "--manuscript", str(ms)]) == 0
    _pdf(ms / "figures" / "fig-b.pdf", 300, 100, [((20, 50), "Result", 8)])
    (ms / "figure-src" / "fig-b.json").write_text(json.dumps({"source": "../main.tex"}))
    (ms / "main.tex").write_text((MAIN % "\\linewidth").replace(
        "fig-b.pdf}\\end{figure}", "fig-b.pdf}\\caption{R.}\\label{fig:b}\\end{figure} See Figure~\\ref{fig:b}."))
    capsys.readouterr()
    code = main(["figures", "check", "--manuscript", str(ms), "--no-rebuild", "--text-width", "160mm", "--json"])
    result = json.loads(capsys.readouterr().out)
    assert code == (0 if result["valid"] else 1) and {"blocking", "advisory", "figures"} <= set(result)
    assert main(["figures", "sheet", "--manuscript", str(ms)]) == 0
    assert (ms.parent / "build" / "figures" / "contact-sheet.png").is_file()
    assert main(["figures", "new", "--list"]) == 0
    assert main(["figures", "build", "--manuscript", str(tmp_path / "missing")]) == 2


# --------------------------------------------------------------------------- review support
def test_review_figure_files_and_images(tmp_path):
    ms = _manuscript(tmp_path)
    _pdf(ms / "figures" / "fig-a.pdf", 300, 100, [((20, 50), "A", 8)])
    _pdf(ms / "main.pdf", 300, 100)
    files = fig.review_figure_files(ms, ["figures/fig-a.pdf", "main.pdf", "main.tex", "figures/missing.pdf"])
    assert [f["path"] for f in files] == ["figures/fig-a.pdf"]
    out = fig.review_images(ms, files, tmp_path / "run" / "figures")
    assert len(out["images"]) == 1 and Path(out["images"][0]["png"]).is_file()
    many = []
    for i in range(4):
        _pdf(ms / "figures" / f"f{i}.pdf", 200, 80, [((20, 50), f"F{i}", 8)])
        many.append({"path": f"figures/f{i}.pdf", "sha256": "x"})
    sheet = fig.review_images(ms, many, tmp_path / "run2", max_images=2)
    assert len(sheet["images"]) == 1 and sheet["notes"]
    broken = fig.review_images(ms, [{"path": "figures/none.pdf", "sha256": "x"}], tmp_path / "run3")
    assert broken["images"] == [] and "unavailable" in broken["notes"][0]


def test_method_plan_needs_included_source_built_schematic(tmp_path):
    ms = _manuscript(tmp_path, r"""
\documentclass{article}\begin{document}
See Figure~\ref{fig:design}.
\begin{figure}\includegraphics{figures/design.pdf}
\caption{Two specimen groups follow the same measurement protocol. Arrows connect each physical specimen to its assigned split and show the timing of segmentation before model evaluation.}\label{fig:design}\end{figure}
\end{document}
""")
    (ms / "figure-plan.json").write_text(json.dumps({
        "paper_type": "method", "manuscript_type": "other", "count_reason": "Split design only", "figures": [{
            "figure": "design", "kind": "schematic", "point": "See the split",
            "figure_type": "study design", "source": "figure-src/design.svg", "data_source": "Methods",
        }],
    }))
    ws = fig.workspace(manuscript=ms)
    result = fig.check(ws, rebuild=False, text_width="160mm")
    assert not result["repair_required"]
    assert {"FIG-PLAN-MISSING", "FIG-SCHEMATIC-MISSING"} <= {f["code"] for f in result["advisory"]}
    (ms / "figure-src/design.svg").write_text(SVG)
    _pdf(ms / "figures/design.pdf", 200, 80, [((30, 40), "Paired split", 9)])
    assert fig.check(ws, rebuild=False, text_width="160mm")["repair_required"] == []


def test_result_plot_checks_panels_reference_legend_and_units(tmp_path):
    pdf = tmp_path / "result.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=300, height=260)
        for y in (20, 138):
            page.draw_rect(fitz.Rect(40, y, 275, y + 78))
            page.insert_text((130, y + 100), "Time", fontsize=9)
        page.draw_line((40, 51), (275, 51), dashes="[4 2] 0", color=(0.35, 0.35, 0.35))
        page.draw_line((40, 85), (274, 24), color=(0, 0.3, 0.7))
        page.draw_rect(fitz.Rect(152, 39, 224, 65), color=None, fill=(1, 1, 1), fill_opacity=.8)
        page.insert_text((160, 61), "Treatment", fontsize=8)
        doc.save(str(pdf))
    diagnostic = dict(fig.inspect_pdf(pdf, result_plot=True)["plot_findings"])
    assert set(diagnostic) == {"FIG-PANEL-LABELS", "FIG-AXIS-UNITS", "FIG-REFERENCE-LABEL", "FIG-LEGEND-OVERLAP"}


def test_nature_profile_and_quantitative_colors(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENLABS_FIG_PROFILE", "nature")
    helpers = fig._style_helpers()
    assert helpers.SINGLE_COLUMN_MM == 89 and helpers.DOUBLE_COLUMN_MM == 183
    assert "onehalf" not in helpers.WIDTHS_IN
    assert helpers.profile_name("Energy Policy") == "elsevier"
    assert r"\def\olpanel{8}" in helpers.tex_profile("nature")
    asset = tmp_path / "data.svg"
    asset.write_text('<svg viewBox="0 0 1 1"><path fill="#123456"/></svg>')
    assert "#123456" in helpers.svg_fragment(asset, x=0, y=0, width=1)


def test_compiled_figure_placement(tmp_path):
    with fitz.open() as source, fitz.open() as doc:
        page = source.new_page(width=100, height=100)
        page.insert_text((5, 30), "Scale", fontsize=12)
        page.draw_line((4, 40), (94, 40), width=.4)
        target = doc.new_page()
        xref = target.show_pdf_page(fitz.Rect(20, 20, 70, 70), source, 0)
        doc.xref_set_key(xref, "PTEX.FileName", "(figures/result.pdf)")
        second = doc.new_page()
        second.show_pdf_page(fitz.Rect(10, 20, 110, 120), source, 0)
        doc.save(tmp_path / "main.pdf")
    item, repeated = fig.proof_figures(tmp_path)["result"]
    assert repeated["min_body_pt"] == pytest.approx(12)
    assert item["smallest_span_pt"] == pytest.approx(6)
    assert item["min_stroke_pt"] == pytest.approx(.2)
    assert item["unembedded_fonts"]


def test_printed_raster_uses_placed_pixels(tmp_path):
    image = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 120), False)
    image.clear_with(128)
    png = tmp_path / "camera.png"
    image.save(png)
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_image(fitz.Rect(15, 30, 87, 174), filename=str(png))
        doc.save(tmp_path / "main.pdf")
    item, = fig.proof_figures(tmp_path, [png])["camera.png"]
    assert item["min_ppi"] == pytest.approx(60)


def test_object_library_and_templates(tmp_path, monkeypatch):
    import runpy
    import xml.etree.ElementTree as ET

    root = fig.STYLE_DIR.parent
    library = root / "assets"
    monkeypatch.syspath_prepend(str(fig.STYLE_DIR))
    monkeypatch.setenv("OPENLABS_FIG_ASSETS", str(library))
    helpers = fig._style_helpers()
    for asset in library.glob("*/*.svg"):
        meta = helpers.asset_license(asset)
        assert all(meta[key] for key in ("source", "url", "license", "attribution"))
        assert meta["sha256"] == hashlib.sha256(asset.read_bytes()).hexdigest()
        assert fig.classify_license(meta["license"])[0] in {"ok", "attribution"}
    assert "Twitter" in helpers.credits([library / "astronomy/telescope.svg"])[0]
    drawings = ("plant-connections", "plant-dispatch", "market-interval",
                "rig-instrumentation", "bearing-protocol", "viewing-geometry", "transit-formation")
    catalog = {item["name"]: item for item in fig.template_catalog()}
    for name in drawings:
        output = tmp_path / (name + ".svg")
        monkeypatch.setenv("FIG_SVG", str(output))
        runpy.run_path(str(root / catalog[name]["file"]))
        svg = ET.parse(output).getroot()
        assert len(svg.findall(".//{*}path")) >= 3
        assert "ns0:" not in output.read_text()  # Chromium embeds SVG in HTML


def _fake_chromium(tmp_path: Path, body: str) -> Path:
    tool = tmp_path / "fake-chromium-pdf"
    tool.write_text("#!/usr/bin/env python3\nimport os, sys\n" + body, encoding="utf-8")
    tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    return tool


def test_chromium_gets_a_short_private_tmpdir(tmp_path, monkeypatch):
    # 2026-11-26: under a deep attempt-workspace TMPDIR Chromium's SingletonSocket path passed
    # the 108-byte sun_path limit and the first render aborted (FIG-REBUILD-FAILED).
    seen = tmp_path / "seen.txt"
    tool = _fake_chromium(tmp_path, (
        f"open({str(seen)!r}, 'w').write(os.environ['TMPDIR'])\n"
        "open(sys.argv[2], 'wb').write(b'%PDF-1.4\\n')\n"))
    monkeypatch.setenv("OPENLABS_FIG_CHROMIUM_PDF", str(tool))
    deep = tmp_path / ("d" * 60) / ("e" * 60) / "scratch"
    deep.mkdir(parents=True)
    monkeypatch.setenv("TMPDIR", str(deep))
    svg = tmp_path / "fig.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>')
    work = tmp_path / "work"
    work.mkdir()
    assert fig._render_svg(svg, work, label="fig").is_file()
    used = seen.read_text()
    assert len(used) <= 60 and not used.startswith(str(deep))
    assert not Path(used).exists()                  # removed after the render


def test_a_chromium_crash_reports_its_fatal_line(tmp_path, monkeypatch):
    tool = _fake_chromium(tmp_path, (
        "print('[1:1:FATAL:process_singleton_posix.cc(307)] Check failed: Socket path too long',"
        " file=sys.stderr)\n"
        "[print(f'#{n} 0x55d1 (dump)', file=sys.stderr) for n in range(20)]\n"
        "sys.exit(1)\n"))
    monkeypatch.setenv("OPENLABS_FIG_CHROMIUM_PDF", str(tool))
    svg = tmp_path / "fig.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>')
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(fig.FigureToolError, match="Socket path too long"):
        fig._render_svg(svg, work, label="fig")
