"""SVG/HTML schematic route: asset inlining, insets, profile CSS, asset search and the library fetcher."""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import shutil
import sys
import tarfile
from pathlib import Path

import pytest

from paper_writing import figure_markup as fm
from paper_writing import figures as fig

fitz = pytest.importorskip("pymupdf")

ICON = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M2 2h20v20H2z"/></svg>'
STROKE = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
          'stroke-width="2"><path d="M4 4l16 16"/></svg>')
STYLED = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><defs><style>.a,.b{fill:url(#g);}'
          '.b{stroke:#123456;}</style><linearGradient id="g"><stop offset="0" stop-color="#fff"/></linearGradient>'
          '</defs><rect class="a" width="5" height="5"/><circle class="b" cx="7" cy="7" r="2" style="opacity:.5"/></svg>')
PROFILE = {"single": 89.0, "onehalf": None, "double": 183.0, "body": 7, "small": 6.5, "panel": 8, "line": 0.9,
           "axis": 0.6}


def _library(tmp_path: Path) -> Path:
    lib = tmp_path / "lib"
    (lib / "energy").mkdir(parents=True, exist_ok=True)
    (lib / "energy/icon.svg").write_text(ICON)
    (lib / "energy/line.svg").write_text(STROKE)
    (lib / "energy/styled.svg").write_text(STYLED)
    (lib / "energy/bad.svg").write_text('<svg viewBox="0 0 1 1"><script>alert(1)</script></svg>')
    return lib


def _prepare(tmp_path: Path, text: str, suffix: str = ".html", insets=None) -> str:
    lib = _library(tmp_path)
    src = tmp_path / f"fig{suffix}"
    src.write_text(text)
    out = fm.prepare(src, tmp=tmp_path, find_asset=lambda name: lib / name, style_dir=fig.STYLE_DIR,
                     profile=PROFILE, insets=insets or {}, recolor=fig._style_helpers().recolor_svg)
    return out.read_text()


def test_html_assets_are_inlined_with_profile_style_and_script(tmp_path):
    html = _prepare(tmp_path, '<html><head></head><body><!-- <img src="asset:energy/missing.svg"> -->'
                    '<img class="ol-icon l" src="asset:energy/icon.svg" alt="pv">'
                    '<img class="ol-icon" src="asset:energy/line.svg" data-stroke="1.5">'
                    '<img src="photo.png"></body></html>')
    body = html.split("</style>")[-1]
    assert 'src="asset:' not in body and "missing.svg" not in body
    assert '<svg fill="currentColor" class="ol-icon l"' in html and 'aria-label="pv"' in html
    assert 'stroke-width="1.5"' in html and 'viewBox="0 0 24 24"' in html
    assert '<img src="photo.png">' in html                      # ordinary images untouched
    assert "--ol-double: 183.0mm;" in html and "--ol-body: 7pt;" in html and "--ol-onehalf: 136.0mm;" in html
    assert ".ol-figure" in html and "ol-flow" in html and "<base href=\"file://" in html
    assert html.index("<script>") < html.index("</body>")


def test_asset_styles_move_onto_elements_and_ids_are_prefixed(tmp_path):
    html = _prepare(tmp_path, '<body><img src="asset:energy/styled.svg"><img src="asset:energy/styled.svg"></body>')
    assert "<style>.a" not in html
    first, second = (part for part in html.split("</svg>")[:2])
    assert 'id="ol' in first and "url(#ol" in first
    prefix = first.split('id="')[1].split("-g")[0]
    assert f"url(#{prefix}-g)" in first and f"url(#{prefix}-g)" not in second
    assert 'style="fill:url(#' in first and "stroke:#123456;opacity:.5" in first


def test_unsafe_or_unknown_references_are_refused(tmp_path):
    with pytest.raises(fm.MarkupError, match="unsafe"):
        _prepare(tmp_path, '<body><img src="asset:energy/bad.svg"></body>')
    with pytest.raises(fm.MarkupError, match="no inset 'curve'"):
        _prepare(tmp_path, '<body><img src="inset:curve"></body>')


def test_insets_keep_their_drawn_size_and_lose_page_wide_rules(tmp_path):
    inset = tmp_path / "inset.svg"
    inset.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="150pt" height="80pt" viewBox="0 0 150 80">'
                     '<defs><style type="text/css">*{stroke-linejoin: round}</style></defs><path id="p1" d="M0 0"/>'
                     '<use xlink:href="#p1"/></svg>')
    html = _prepare(tmp_path, '<body><img class="ol-inset" src="inset:curve"></body>', insets={"curve": inset})
    assert 'width="150pt"' in html and 'height="80pt"' in html and "stroke-linejoin: round" not in html
    assert 'xlink:href="#ol' in html


def test_svg_image_elements_become_nested_svg(tmp_path):
    svg = _prepare(tmp_path, '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50">'
                   '<image href="asset:energy/icon.svg" x="5" y="6" width="20" height="20"/></svg>', ".svg")
    assert '<svg fill="currentColor" x="5" y="6" width="20" height="20" viewBox="0 0 24 24"' in svg
    assert ".ol-figure" not in svg  # SVG sources get no page CSS


def test_search_assets_ranks_keyword_hits(tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "catalog.json").write_text(json.dumps({"assets": [
        {"path": "energy/tabler-windmill.svg", "name": "windmill", "field": "energy", "library": "tabler",
         "keywords": ["wind", "turbine"], "license": "MIT", "credit_required": True},
        {"path": "energy/wind.svg", "name": "wind", "field": "energy", "library": "openlabs",
         "keywords": ["wind", "turbine"], "license": "CC0 1.0", "credit_required": False},
        {"path": "general/tabler-cloud.svg", "name": "cloud", "field": "general", "library": "tabler",
         "keywords": ["weather"], "license": "MIT", "credit_required": True}]}))
    monkeypatch.setenv("OPENLABS_FIG_ASSETS", str(lib))
    found = fig.search_assets(["wind"])
    assert [a["path"] for a in found] == ["energy/wind.svg", "energy/tabler-windmill.svg"]
    assert [a["path"] for a in fig.search_assets(["turbine"], no_credit=True)] == ["energy/wind.svg"]
    assert fig.search_assets([], field="general")[0]["name"] == "cloud"
    monkeypatch.setenv("OPENLABS_FIG_ASSETS", str(tmp_path / "none"))
    with pytest.raises(fig.FigureToolError, match="fetch_assets"):
        fig.search_assets(["x"])


def test_html_templates_copy_their_inset_scripts(tmp_path):
    ms = tmp_path / "manuscript"
    ms.mkdir()
    ws = fig.workspace(manuscript=ms)
    catalog = {t["name"]: t for t in fig.template_catalog()}
    for name in ("schematic-flow", "pv-storage-grid", "contact-binary", "bearing-testbed", "isolate-tracing"):
        entry = catalog[name]
        assert entry["file"].endswith(".html")
        for helper in entry.get("companions", []):
            assert (fig.TEMPLATES / helper).is_file() and helper.startswith("_")
            assert helper in set((entry.get("sidecar") or {}).get("insets", {}).values())
    result = fig.new_figure(ws, "plant", template="pv-storage-grid")
    sidecar = json.loads(Path(result["sidecar"]).read_text())
    assert sidecar["insets"] == {"day": "_pv-storage-day.py"}
    assert (ms / "figure-src" / "_pv-storage-day.py").is_file()
    assert [s.stem for s in fig.discover(ws)] == ["fig-plant"]   # helpers are not figures


def test_check_reports_type3_and_overwide_figures(tmp_path):
    ms = tmp_path / "manuscript"
    (ms / "figures").mkdir(parents=True)
    (ms / "main.tex").write_text("\\documentclass{article}\\begin{document}x\\end{document}\n")
    doc = fitz.open()
    page = doc.new_page(width=200 / 25.4 * 72, height=100)
    page.insert_text((20, 50), "Label text", fontsize=9, fontname="helv")
    doc.save(str(ms / "figures" / "fig-wide.pdf"))
    result = fig.check(fig.workspace(manuscript=ms), rebuild=False, text_width="183mm")
    codes = {f["code"] for f in result["advisory"]}
    assert "FIG-WIDER-THAN-PROFILE" in codes
    info = fig.inspect_pdf(ms / "figures" / "fig-wide.pdf")
    assert info["type3_fonts"] == 0 and info["unembedded_fonts"] == ["Helvetica"]
    assert "FIG-FONT-NOT-EMBEDDED" in codes


@pytest.mark.skipif(not fig.resolve_tool("OPENLABS_FIG_CHROMIUM_PDF", "chromium-pdf"), reason="chromium-pdf missing")
def test_html_schematic_renders_connectors_and_embeds_truetype(tmp_path, monkeypatch):
    lib = _library(tmp_path)
    monkeypatch.setenv("OPENLABS_FIG_ASSETS", str(lib))
    ms = tmp_path / "manuscript"
    (ms / "figure-src").mkdir(parents=True)
    (ms / "figure-src" / "fig-a.html").write_text(
        '<html><head></head><body><div class="ol-figure single"><div class="ol-row">'
        '<div class="ol-card" id="a"><img class="ol-icon" src="asset:energy/icon.svg"><span class="ol-name">Source</span></div>'
        '<div class="ol-card" id="b"><span class="ol-name">Sink</span></div></div>'
        '<i class="ol-flow energy" data-from="a" data-to="b" data-value="2" data-label="2 MW"></i></div></body></html>')
    (ms / "figure-src" / "fig-a.json").write_text('{"profile": "nature"}')
    result = fig.build(fig.workspace(manuscript=ms, preview_dir=tmp_path / "prev"))
    assert not result["failed"], result["failed"]
    record = result["built"][0]
    assert abs(record["width_mm"] - 89.0) < 1.5
    with fitz.open(record["pdf"]) as doc:
        page = doc[0]
        text = page.get_text()
        assert "Source" in text and "2 MW" in text
        assert any(d.get("fill") and d["fill"][0] > 0.7 for d in page.get_drawings())  # the energy arrow head
        fonts = page.get_fonts(full=True)
    if any(Path(d).expanduser().is_dir() for d in fig.FONT_DIRS[:3]):
        assert fonts and all(f[2] != "Type3" for f in fonts)


# --------------------------------------------------------------------------- library fetcher
def _fetcher():
    path = fig.TEMPLATES.parent / "figure-assets" / "fetch_assets.py"
    spec = importlib.util.spec_from_file_location("fetch_assets", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_is_consistent():
    fetch = _fetcher()
    manifest = json.loads(fetch.MANIFEST.read_text())
    paths = [a["path"] for a in manifest["assets"]]
    assert len(paths) == len(set(paths)) and len(paths) >= 250
    fields = {a["field"] for a in manifest["assets"]}
    assert fields == {"general", "energy", "reliability", "astronomy", "biomedical"}
    for name, lib in manifest["libraries"].items():
        assert lib["license"] and lib["attribution"] and lib["homepage"]
        if lib["kind"] == "npm-tarball":
            assert lib["integrity"].startswith("sha512-") and "npmmirror" in lib["url"]
    for asset in manifest["assets"]:
        licence = asset.get("license") or manifest["libraries"][asset["library"]]["license"]
        assert "sa" not in licence.lower().split() and "nc" not in licence.lower()
        assert fig.classify_license(licence)[0] in {"ok", "attribution"}, asset
        if asset["library"] == "bioicons":
            assert len(asset["git_blob"]) == 40 and asset["bytes"] > 0


def test_fetcher_helpers():
    fetch = _fetcher()
    assert fetch.git_blob(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"
    assert fetch.quote("https://h.example/a/Simon_Dürr/x y.svg") == "https://h.example/a/Simon_D%C3%BCrr/x%20y.svg"
    assert fetch.svg_problem(ICON) is None
    assert "unsafe" in fetch.svg_problem('<svg viewBox="0 0 1 1" onload="x()"></svg>')
    assert "unsafe" in fetch.svg_problem('<svg viewBox="0 0 1 1"><use href="http://e.com/a.svg#x"/></svg>')


def test_fetcher_builds_library_through_the_bridge(tmp_path, monkeypatch):
    fetch = _fetcher()
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    # an npm tarball and a single-file icon, served by a fake bridge that copies files
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in (("package/icons/a.svg", ICON.encode()), ("package/LICENSE", b"MIT text")):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    (upstream / "pkg.tgz").write_bytes(buf.getvalue())
    (upstream / "b.svg").write_text(STROKE)
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(buf.getvalue()).digest()).decode()
    bridge = tmp_path / "bridge.py"
    bridge.write_text(
        "import json, shutil, sys, urllib.parse\n"
        "a = sys.argv[1:]\n"
        "if '--status' in a:\n print(json.dumps({'id': a[1], 'state': 'completed', 'route': 'direct'})); sys.exit(0)\n"
        "url, out = a[a.index('--url') + 1], a[a.index('--output') + 1]\n"
        f"shutil.copyfile({str(upstream)!r} + '/' + urllib.parse.unquote(url.rsplit('/', 1)[1]), out)\n"
        "print(json.dumps({'id': 'job-' + url.rsplit('/', 1)[1], 'state': 'queued'}))\n")
    launcher = tmp_path / "download-submit"
    launcher.write_text(f"#!/bin/sh\nexec {sys.executable} {bridge} \"$@\"\n")
    launcher.chmod(0o755)
    monkeypatch.setattr(fetch, "BRIDGE", str(launcher))
    local = tmp_path / "local"
    (local / "energy").mkdir(parents=True)
    (local / "energy/pv.svg").write_text(ICON)
    (local / "energy/pv.license.json").write_text(json.dumps({"license": "CC0 1.0", "attribution": "OpenLabs"}))
    monkeypatch.setattr(fetch, "LOCAL_ASSETS", local)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "libraries": {
            "npmlib": {"title": "Npm", "version": "1", "license": "MIT", "license_url": "https://l", "attribution": "Npm",
                       "homepage": "https://n", "kind": "npm-tarball", "url": "https://m.example/pkg.tgz",
                       "official_url": "https://o.example/pkg.tgz", "tarball": "npm/pkg.tgz", "integrity": integrity,
                       "member": "package/icons/{name}.svg", "license_member": "package/LICENSE"},
            "files": {"title": "Files", "version": "1", "license": "per icon", "license_url": "https://l",
                      "attribution": "Files", "homepage": "https://f", "kind": "file", "base_url": "https://f.example/"}},
        "local_keywords": {"energy/pv.svg": "photovoltaic"},
        "assets": [
            {"field": "general", "library": "npmlib", "upstream": "package/icons/a.svg", "path": "general/npmlib-a.svg",
             "name": "a", "keywords": ["a"]},
            {"field": "energy", "library": "files", "upstream": "b.svg", "path": "energy/files-b.svg", "name": "b",
             "keywords": ["b"], "license": "CC BY 4.0", "creator": "Someone",
             "git_blob": fetch.git_blob(STROKE.encode()), "bytes": len(STROKE)}]}))
    library = tmp_path / "library"
    assert fetch.main(["--manifest", str(manifest), "--library", str(library), "--record"]) == 0
    catalog = json.loads((library / "catalog.json").read_text())["assets"]
    assert {a["path"] for a in catalog} == {"general/npmlib-a.svg", "energy/files-b.svg", "energy/pv.svg"}
    meta = json.loads((library / "energy/files-b.license.json").read_text())
    assert meta["license"] == "CC BY 4.0" and meta["url"].endswith("/by/4.0/") and meta["sha256"]
    assert next(a for a in catalog if a["path"] == "energy/pv.svg")["keywords"][-1] == "photovoltaic"
    assert (library / "_sources/licenses/npmlib-LICENSE").read_text() == "MIT text"
    assert all("sha256" in a for a in json.loads(manifest.read_text())["assets"])
    # a changed upstream file is refused, never placed
    (upstream / "b.svg").write_text(STROKE.replace("M4", "M5"))
    shutil.move(str(library / "_sources/files/b.svg"), str(tmp_path / "old-b.svg"))
    assert fetch.main(["--manifest", str(manifest), "--library", str(library)]) in (1, 2)
