"""Figure sources, rendering and checks for manuscript figures (``paper-writing figures``).

Every figure has a committed source in ``manuscript/figure-src/`` (``.tex`` TikZ,
``.py`` matplotlib, ``.svg`` or ``.html``) with an optional ``<stem>.json`` sidecar
(``purpose``, ``key_point``, ``kind`` = schematic|result, ``data_inputs``; also
``engine``, ``style_options``, or ``source`` for a figure produced by an external
script). ``build`` renders each one to ``manuscript/figures/<stem>.pdf`` (vector,
single page, cropped, metadata-normalized so the bytes depend only on the source),
writes PNG previews outside the manuscript and refreshes
``production/figure-artifacts.json``. ``check`` reports blocking and advisory
findings; ``sheet`` makes one contact-sheet PNG; ``new`` copies a template.

These are the writer's own tools (owner mode): nothing here is a review gate.
External programs are configurable: ``OPENLABS_FIG_PYTHON`` (default
``paperfig-python``), ``OPENLABS_FIG_CHROMIUM_PDF`` (default ``chromium-pdf``),
``OPENLABS_FIG_TEX_ENGINE`` (default ``lualatex``), ``OPENLABS_FIG_ASSETS`` (the
shared licensed-asset library, default ``/workspace/openlabs/build/figure-assets``).
"""
from __future__ import annotations

import colorsys
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from paper_writing.figure_standard import findings as standard_findings
from paper_writing.figure_quality import PLOT_FINDINGS, plot_findings, read_plan
from paper_writing import figure_markup

TEMPLATES = Path(__file__).resolve().parents[1] / "figure-templates"
STYLE_DIR = TEMPLATES / "style"
FIGURE_SRC = "figure-src"
FIGURE_OUT = "figures"
RENDERABLE = (".tex", ".py", ".svg", ".html")
GRAPHIC_SUFFIXES = (".pdf", ".png", ".jpg", ".jpeg")
DEFAULT_ASSET_LIBRARY = "/workspace/openlabs/build/figure-assets"
MIN_FONT_PT = 6.0
FONT_TOLERANCE_PT = 0.25
PREVIEW_DPI = 200
FIGURE_MANIFEST = "figure-artifacts.json"


class FigureToolError(RuntimeError):
    """A figure could not be rendered or inspected (missing tool, failed build)."""


# --------------------------------------------------------------------------- environment
def _fitz():
    try:
        import pymupdf as fitz  # noqa: PLC0415
    except ImportError:
        try:
            import fitz  # type: ignore  # noqa: PLC0415
        except ImportError as exc:
            raise FigureToolError("PyMuPDF (pymupdf) is required to inspect figure PDFs; run under "
                                  "paperfig-python or install pymupdf") from exc
    return fitz


def resolve_tool(env: str, default: str) -> str | None:
    """``$env`` if set (must exist), else ``default`` on PATH or in ``~/.local/bin``."""
    configured = os.environ.get(env)
    if configured:
        found = shutil.which(configured) or (configured if Path(configured).is_file() else None)
        if not found:
            raise FigureToolError(f"{env}={configured} does not name an executable")
        return found
    found = shutil.which(default)
    if found:
        return found
    local = Path.home() / ".local" / "bin" / default
    return str(local) if local.is_file() and os.access(local, os.X_OK) else None


def require_tool(env: str, default: str, purpose: str) -> str:
    found = resolve_tool(env, default)
    if not found:
        hint = " (source ~/.local/opt/texenv.sh for the TeX tools)" if default.endswith("latex") else ""
        raise FigureToolError(f"{default} not found for {purpose}: put it on PATH or set {env}{hint}")
    return found


def _style_helpers():
    spec = importlib.util.spec_from_file_location("openlabs_fig", STYLE_DIR / "openlabs_fig.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def asset_library() -> Path:
    return Path(os.environ.get("OPENLABS_FIG_ASSETS") or DEFAULT_ASSET_LIBRARY)


def search_assets(query: Iterable[str] = (), *, field: str | None = None, library: str | None = None,
                  no_credit: bool = False) -> list[dict[str, Any]]:
    """Entries of the library's ``catalog.json`` matching every query word (best first)."""
    catalog = asset_library() / "catalog.json"
    if not catalog.is_file():
        raise FigureToolError(f"No asset catalog at {catalog}: run workflows/paper/figure-assets/fetch_assets.py")
    items = json.loads(catalog.read_text(encoding="utf-8")).get("assets") or []
    words = [w.lower() for w in query if w.strip()]
    scored = []
    for item in items:
        if field and item.get("field") != field or library and item.get("library") != library:
            continue
        if no_credit and item.get("credit_required"):
            continue
        haystack = " ".join([item.get("path", ""), item.get("name", ""), *item.get("keywords", [])]).lower()
        if not all(w in haystack for w in words):
            continue
        exact = sum(w in item.get("keywords", []) or w in item.get("name", "").split() for w in words)
        scored.append((-exact, item.get("library") != "openlabs", item["path"], item))
    return [entry[-1] for entry in sorted(scored, key=lambda e: e[:3])]


# --------------------------------------------------------------------------- workspace
@dataclass
class Workspace:
    manuscript: Path
    preview_dir: Path
    paper_id: str | None = None
    root: Path | None = None
    manifest: Path | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def src_dir(self) -> Path:
        return self.manuscript / FIGURE_SRC

    @property
    def out_dir(self) -> Path:
        return self.manuscript / FIGURE_OUT


def workspace(paper_id: str | None = None, *, root: str | Path | None = None,
              manuscript: str | Path | None = None, preview_dir: str | Path | None = None) -> Workspace:
    """A paper (registry record or ``papers/<id>/manuscript``) or a bare manuscript directory."""
    if manuscript is not None:
        ms = Path(manuscript).resolve()
        if not ms.is_dir():
            raise FigureToolError(f"Manuscript directory not found: {ms}")
        preview = Path(preview_dir).resolve() if preview_dir else ms.parent / "build" / "figures"
        return Workspace(manuscript=ms, preview_dir=preview)
    if not paper_id:
        raise FigureToolError("Give a paper id or --manuscript DIR")
    from paper_writing.registry import load_paper_metadata, paper_metadata_path

    base = Path(root).resolve() if root else _default_root()
    metadata: Mapping[str, Any] = {}
    if paper_metadata_path(paper_id, base).is_file():
        metadata = load_paper_metadata(paper_id, base)
    paper_dir = base / str(metadata.get("workspace") or f"papers/{paper_id}")
    ms = base / str(metadata.get("manuscript_dir") or paper_dir / "manuscript")
    if not ms.is_dir():
        raise FigureToolError(f"Manuscript directory not found: {ms}")
    preview = Path(preview_dir).resolve() if preview_dir else paper_dir / "build" / "figures"
    return Workspace(manuscript=ms, preview_dir=preview, paper_id=paper_id, root=base,
                     manifest=paper_dir / "production" / FIGURE_MANIFEST, metadata=metadata)


def _default_root() -> Path:
    from paper_writing.inventory import default_repo_root

    return default_repo_root()


@dataclass
class FigureSource:
    stem: str
    path: Path
    sidecar: dict[str, Any]

    @property
    def kind(self) -> str:
        return str(self.sidecar.get("kind") or ("schematic" if self.path.suffix in (".tex", ".svg", ".html")
                                                 else "unspecified"))


def _sidecar(path: Path) -> dict[str, Any]:
    side = path.with_suffix(".json")
    if not side.is_file():
        return {}
    try:
        value = json.loads(side.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FigureToolError(f"{side}: invalid JSON sidecar ({exc})") from exc
    if not isinstance(value, dict):
        raise FigureToolError(f"{side}: sidecar must be a JSON object")
    return value


def discover(ws: Workspace) -> list[FigureSource]:
    """Renderable sources at the top of ``figure-src/`` (``_*`` helpers and ``assets/`` excluded)."""
    if not ws.src_dir.is_dir():
        return []
    helpers = _style_helpers()
    profile = helpers.profile_name(ws.metadata.get("target_journal"))
    found: dict[str, FigureSource] = {}
    for path in sorted(ws.src_dir.iterdir()):
        if not path.is_file() or path.name.startswith(("_", ".")) or path.suffix.lower() not in RENDERABLE:
            continue
        if path.stem in found:
            raise FigureToolError(f"Two sources for figure {path.stem}: {found[path.stem].path.name}, {path.name}")
        sidecar = {"profile": profile, **_sidecar(path)}
        if sidecar["profile"] not in helpers.PROFILE_NAMES:
            raise FigureToolError(f"{path.name}: unknown figure profile {sidecar['profile']!r}")
        found[path.stem] = FigureSource(path.stem, path, sidecar)
    return list(found.values())


def _select(sources: list[FigureSource], only: Iterable[str] | None) -> list[FigureSource]:
    if not only:
        return sources
    wanted = set(only)
    chosen = [s for s in sources if s.stem in wanted or s.stem.removeprefix("fig-") in wanted]
    missing = wanted - {s.stem for s in chosen} - {s.stem.removeprefix("fig-") for s in chosen}
    if missing:
        raise FigureToolError("No figure source named " + ", ".join(sorted(missing)))
    return chosen


# --------------------------------------------------------------------------- renderers
def _run(command: list[str], *, cwd: Path, env: Mapping[str, str], timeout: int, log: Path) -> None:
    try:
        proc = subprocess.run(command, cwd=cwd, env=dict(env), capture_output=True, text=True,
                              errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise FigureToolError(f"{Path(command[0]).name} timed out after {timeout}s") from exc
    log.write_text(proc.stdout[-30000:] + "\n" + proc.stderr[-10000:], encoding="utf-8")
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-12:])
        raise FigureToolError(f"{Path(command[0]).name} failed (exit {proc.returncode}):\n{tail}")


def _tex_errors(log: Path) -> str:
    text = log.read_text(errors="replace") if log.is_file() else ""
    lines = [line for line in text.splitlines() if line.startswith("!") or "Error" in line]
    return "\n".join(lines[:8])


TEX_WRAPPER = r"""\documentclass{{article}}
\usepackage[{options}]{{openlabs-fig}}
{preamble}
\ifdefined\pdftrailerid \pdftrailerid{{}}\fi
\ifdefined\pdfvariable \pdfvariable trailerid {{}}\fi
\newsavebox{{\olfigbox}}
\pagestyle{{empty}}
\begin{{document}}
\begin{{lrbox}}{{\olfigbox}}\olfigfont\input{{{source}}}\unskip\end{{lrbox}}
\ifdefined\pagewidth
  \pagewidth=\wd\olfigbox \pageheight=\dimexpr\ht\olfigbox+\dp\olfigbox\relax
\else
  \pdfpagewidth=\wd\olfigbox \pdfpageheight=\dimexpr\ht\olfigbox+\dp\olfigbox\relax
\fi
\hoffset=-1in \voffset=-1in
\shipout\hbox{{\usebox{{\olfigbox}}}}
\end{{document}}
"""


def _render_tex(src: FigureSource, tmp: Path) -> Path:
    text = src.path.read_text(encoding="utf-8")
    engine_name = str(src.sidecar.get("engine") or os.environ.get("OPENLABS_FIG_TEX_ENGINE") or "lualatex")
    if Path(engine_name).name not in {"lualatex", "pdflatex", "xelatex"}:
        raise FigureToolError(f"{src.path.name}: unsupported TeX engine {engine_name}")
    engine = shutil.which(engine_name)
    if not engine:
        raise FigureToolError(f"{engine_name} not found for TikZ figure {src.path.name}: source "
                              "~/.local/opt/texenv.sh or set OPENLABS_FIG_TEX_ENGINE")
    full = bool(re.search(r"^\s*\\documentclass", text, re.M))
    document = tmp / "figure.tex"
    if full:
        document.write_text(text, encoding="utf-8")
    else:
        preamble = "\n".join(line.split("%!preamble", 1)[1].strip()
                             for line in text.splitlines() if line.lstrip().startswith("%!preamble"))
        options = ",".join(str(o) for o in src.sidecar.get("style_options") or [])
        document.write_text(TEX_WRAPPER.format(options=options, preamble=preamble,
                                               source=src.path.resolve().as_posix()), encoding="utf-8")
    env = dict(os.environ)
    (tmp / "openlabs-profile.tex").write_text(_style_helpers().tex_profile(src.sidecar.get("profile", "generic")))
    env["TEXINPUTS"] = os.pathsep.join([str(tmp), str(src.path.parent), str(STYLE_DIR), env.get("TEXINPUTS", "")])
    env["SOURCE_DATE_EPOCH"], env["FORCE_SOURCE_DATE"] = "1767225600", "1"  # 2026-01-01; stable bytes
    command = [engine, "-interaction=nonstopmode", "-halt-on-error", f"-output-directory={tmp}", str(document)]
    try:
        _run(command, cwd=src.path.parent, env=env, timeout=600, log=tmp / "engine.log")
    except FigureToolError as exc:
        detail = _tex_errors(tmp / "figure.log")
        raise FigureToolError(f"{src.path.name}: {exc}" + (f"\n{detail}" if detail else "")) from exc
    pdf = tmp / "figure.pdf"
    if not pdf.is_file():
        raise FigureToolError(f"{src.path.name}: the TeX run produced no PDF")
    if full and not re.search(r"\\documentclass(\[[^\]]*\])?\{standalone\}", text):
        _crop_to_content(pdf)
    return pdf


PY_BOOT = """import os, runpy, sys
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.style.use(os.environ["OPENLABS_FIG_MPLSTYLE"])
    from openlabs_fig import apply_profile
    apply_profile(plt)
except ImportError:
    pass
script = sys.argv[1]
sys.argv = sys.argv[1:]
sys.path.insert(0, os.path.dirname(os.path.abspath(script)))
runpy.run_path(script, run_name="__main__")
"""


def _run_python(script: Path, src: FigureSource, tmp: Path, out_pdf: Path, out_svg: Path, log: str,
                inset: str = "") -> None:
    python = require_tool("OPENLABS_FIG_PYTHON", "paperfig-python", f"matplotlib figure {script.name}")
    boot = tmp / "_olfig_boot.py"
    boot.write_text(PY_BOOT, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
    env |= {"FIG_OUT": str(out_pdf), "FIG_SVG": str(out_svg), "FIG_NAME": src.stem,
            "OPENLABS_FIG_PROFILE": src.sidecar.get("profile", "generic"),
            "FIG_SRC_DIR": str(src.path.parent), "OPENLABS_FIG_MPLSTYLE": str(STYLE_DIR / "openlabs.mplstyle"),
            "PYTHONPATH": str(STYLE_DIR), "MPLBACKEND": "Agg", "SOURCE_DATE_EPOCH": "1767225600",
            "FIG_INSET": inset}
    _run([python, str(boot), str(script.resolve())], cwd=src.path.parent, env=env, timeout=900, log=tmp / log)


def _render_py(src: FigureSource, tmp: Path) -> Path:
    out_pdf, out_svg = tmp / "figure.pdf", tmp / "figure.svg"
    _run_python(src.path, src, tmp, out_pdf, out_svg, "python.log")
    if out_pdf.is_file():
        return out_pdf
    if out_svg.is_file():  # a script that composes an SVG (e.g. with licensed assets)
        return _render_svg(out_svg, tmp, label=src.path.name, base=src.path.parent)
    raise FigureToolError(f"{src.path.name}: the script wrote neither $FIG_OUT (PDF) nor $FIG_SVG")


def _insets(src: FigureSource, tmp: Path) -> dict[str, Path]:
    """Run the sidecar's ``insets`` scripts (matplotlib, ``$FIG_OUT`` ends in .svg, ``$FIG_INSET`` is
    the inset name, so one script can draw several)."""
    declared = src.sidecar.get("insets") or {}
    if not isinstance(declared, dict):
        raise FigureToolError(f"{src.path.name}: sidecar \"insets\" must map NAME to a script")
    made = {}
    for name, script in declared.items():
        path = (src.path.parent / str(script)).resolve()
        if not path.is_file() or src.path.parent.resolve() not in path.parents:
            raise FigureToolError(f"{src.path.name}: inset script {script} not found next to the figure")
        out = tmp / f"inset-{name}.svg"
        _run_python(path, src, tmp, out, out, f"inset-{name}.log", inset=str(name))
        if not out.is_file():
            raise FigureToolError(f"{src.path.name}: inset script {script} wrote no SVG to $FIG_OUT")
        made[str(name)] = out
    return made


def _render_markup(src: FigureSource, tmp: Path) -> Path:
    """HTML/SVG schematics: inline library assets and insets, inject the profile style, print."""
    text = src.path.read_text(encoding="utf-8", errors="replace")
    is_html = src.path.suffix.lower() in (".html", ".htm")
    if not is_html and not re.search(r"(?:asset|inset):", text):
        return _render_svg(src.path, tmp, label=src.path.name)
    helpers = _style_helpers()

    def find(name: str) -> Path:
        try:
            return helpers.find_asset(name, src.path.parent)
        except FileNotFoundError as exc:
            raise FigureToolError(f"{src.path.name}: {exc}") from exc

    try:
        prepared = figure_markup.prepare(
            src.path, tmp=tmp, find_asset=find, style_dir=STYLE_DIR,
            profile=helpers._catalog["profiles"][src.sidecar.get("profile", "generic")],
            insets=_insets(src, tmp), recolor=helpers.recolor_svg)
    except figure_markup.MarkupError as exc:
        raise FigureToolError(str(exc)) from exc
    return _render_svg(prepared, tmp, label=src.path.name, base=src.path.parent)


FONT_DIRS = ("~/.local/opt/lo/usr/share/fonts/truetype/liberation2", "/usr/share/fonts/truetype/liberation2",
             "/usr/share/fonts/truetype/liberation", "~/.local/opt/texlive/texmf-dist/fonts/opentype",
             "~/.local/opt/texlive/texmf-dist/fonts/truetype")
SANS_ALIASES = ("Arial", "Helvetica", "sans-serif", "Nimbus Sans", "TeX Gyre Heros")


def _font_config(tmp: Path) -> Path:
    """A fontconfig file for Chromium: TrueType sans fonts first (Liberation Sans, metric-compatible
    with Arial). Skia embeds TrueType outlines as real fonts; CFF/OpenType fonts (the TeX Gyre
    .otf files) become Type 3 fonts, which some journals reject. ``OPENLABS_FIG_FONT_DIRS``
    (os.pathsep-separated) adds directories in front."""
    extra = [d for d in os.environ.get("OPENLABS_FIG_FONT_DIRS", "").split(os.pathsep) if d]
    dirs = [Path(d).expanduser() for d in (*extra, *FONT_DIRS)]
    body = "".join(f"<dir>{d}</dir>" for d in dirs if d.is_dir())
    alias = "".join(f"<alias binding=\"same\"><family>{name}</family><prefer><family>Liberation Sans</family>"
                    "</prefer></alias>" for name in SANS_ALIASES)
    conf = tmp / "fonts.conf"
    conf.write_text("<?xml version=\"1.0\"?><!DOCTYPE fontconfig SYSTEM \"fonts.dtd\"><fontconfig>"
                    f"{body}<cachedir>{Path.home() / '.cache' / 'fontconfig'}</cachedir>{alias}</fontconfig>\n",
                    encoding="utf-8")
    return conf


def _render_svg(path: Path, tmp: Path, *, label: str, base: Path | None = None) -> Path:
    out = tmp / "figure-svg.pdf"
    chromium = resolve_tool("OPENLABS_FIG_CHROMIUM_PDF", "chromium-pdf")
    if chromium:
        env = dict(os.environ)
        env["FONTCONFIG_FILE"] = str(_font_config(tmp))
        _run([chromium, str(path.resolve()), str(out)], cwd=base or path.parent, env=env, timeout=300,
             log=tmp / "chromium.log")
        if not out.is_file():
            raise FigureToolError(f"{label}: chromium-pdf produced no PDF")
        return out
    if path.suffix.lower() != ".svg":
        raise FigureToolError(f"{label}: HTML figures need chromium-pdf (set OPENLABS_FIG_CHROMIUM_PDF)")
    fitz = _fitz()  # fallback: MuPDF's SVG interpreter (drops some markers; check the preview)
    doc = fitz.open(str(path))
    pdf = fitz.open("pdf", doc.convert_to_pdf())
    pdf.save(str(out))
    (tmp / "renderer-note.txt").write_text("chromium-pdf unavailable: rendered with the MuPDF SVG fallback\n")
    return out


def _crop_to_content(pdf: Path, pad: float = 1.0) -> None:
    """Shrink the page to its drawn content (Ghostscript bbox, else PyMuPDF's own extents)."""
    fitz = _fitz()
    doc = fitz.open(str(pdf))
    page = doc[0]
    rect = None
    gs = shutil.which("gs")
    if gs:
        proc = subprocess.run([gs, "-q", "-dBATCH", "-dNOPAUSE", "-dSAFER", "-sDEVICE=bbox", "-dFirstPage=1",
                               "-dLastPage=1", str(pdf)], capture_output=True, text=True, timeout=120)
        match = re.search(r"%%HiResBoundingBox:\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)", proc.stderr)
        if match:
            x0, y0, x1, y1 = map(float, match.groups())
            height = page.mediabox.height
            rect = fitz.Rect(x0, height - y1, x1, height - y0)
    if rect is None or rect.is_empty:
        boxes = [fitz.Rect(d["rect"]) for d in page.get_drawings()]
        boxes += [fitz.Rect(b["bbox"]) for b in page.get_text("dict")["blocks"]]
        if not boxes:
            return
        rect = boxes[0]
        for box in boxes[1:]:
            rect |= box
    rect = fitz.Rect(rect.x0 - pad, rect.y0 - pad, rect.x1 + pad, rect.y1 + pad) & page.mediabox
    page.set_cropbox(rect)
    page.set_mediabox(rect)  # some viewers and pdflatex use the media box
    doc.save(str(pdf) + ".crop.pdf")
    doc.close()
    os.replace(str(pdf) + ".crop.pdf", pdf)


def _normalize(pdf: Path, target: Path) -> None:
    """One page, no creation dates or random IDs: the bytes depend on the drawing only."""
    fitz = _fitz()
    doc = fitz.open(str(pdf))
    if doc.page_count != 1:
        raise FigureToolError(f"{target.name}: a figure PDF must have exactly one page (got {doc.page_count})")
    doc.set_metadata({})
    try:
        doc.del_xml_metadata()
    except Exception:  # noqa: BLE001 - older PyMuPDF without XMP support
        pass
    doc.xref_set_key(-1, "ID", "[<00000000000000000000000000000000><00000000000000000000000000000000>]")
    temporary = target.with_name(f".{target.name}.tmp")
    doc.save(str(temporary), garbage=3, deflate=True, no_new_id=True)
    doc.close()
    os.replace(temporary, target)


def render(src: FigureSource, destination: Path) -> dict[str, Any]:
    """Render one source to ``destination`` (PDF); returns the build record."""
    with tempfile.TemporaryDirectory(prefix="olfig-") as name:
        tmp = Path(name)
        suffix = src.path.suffix.lower()
        if suffix == ".tex":
            pdf = _render_tex(src, tmp)
        elif suffix == ".py":
            pdf = _render_py(src, tmp)
        else:
            pdf = _render_markup(src, tmp)
        destination.parent.mkdir(parents=True, exist_ok=True)
        _normalize(pdf, destination)
        note = tmp / "renderer-note.txt"
        notes = [note.read_text().strip()] if note.is_file() else []
    fitz = _fitz()
    with fitz.open(str(destination)) as doc:
        rect = doc[0].rect
    return {"figure": src.stem, "source": src.path.name, "pdf": str(destination),
            "width_mm": round(rect.width / 72 * 25.4, 1), "height_mm": round(rect.height / 72 * 25.4, 1),
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(), "notes": notes}


def render_png(pdf: Path, png: Path, *, dpi: int = PREVIEW_DPI, max_pixels: int | None = None) -> Path:
    fitz = _fitz()
    png.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open(str(pdf)) as doc:
        page = doc[0]
        zoom = dpi / 72
        if max_pixels:
            zoom = min(zoom, max_pixels / max(page.rect.width, page.rect.height))
        page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False).save(str(png))
    return png


# --------------------------------------------------------------------------- build
def build(ws: Workspace, *, only: Iterable[str] | None = None, manifest: bool = True) -> dict[str, Any]:
    sources = _select(discover(ws), only)
    if not sources:
        raise FigureToolError(f"No figure sources in {ws.src_dir} (.tex, .py, .svg or .html)")
    built, failed = [], []
    for src in sources:
        target = ws.out_dir / f"{src.stem}.pdf"
        try:
            record = render(src, target)
        except FigureToolError as exc:
            failed.append({"figure": src.stem, "source": src.path.name, "error": str(exc)})
            continue
        record["preview"] = str(render_png(target, ws.preview_dir / f"{src.stem}.png"))
        built.append(record)
    result: dict[str, Any] = {"manuscript": str(ws.manuscript), "built": built, "failed": failed,
                              "preview_dir": str(ws.preview_dir)}
    if manifest and ws.manifest is not None and ws.root is not None and built:
        result["manifest"] = str(update_manifest(ws))
    return result


def update_manifest(ws: Workspace) -> Path:
    """Bind every figure PDF of the manuscript (plus still-present earlier entries)."""
    from paper_writing.support import write_support_artifact_manifest

    assert ws.manifest is not None and ws.root is not None
    paths = {p.resolve() for p in ws.out_dir.glob("*.pdf")}
    if ws.manifest.is_file():
        try:
            earlier = json.loads(ws.manifest.read_text()).get("files") or []
        except json.JSONDecodeError:
            earlier = []
        for entry in earlier:
            candidate = (ws.root / str(entry.get("path") or "")).resolve()
            if candidate.is_file():
                paths.add(candidate)
    return write_support_artifact_manifest(ws.root, sorted(paths), ws.manifest)


# --------------------------------------------------------------------------- sheet
def contact_sheet(ws: Workspace, out: Path | None = None, *, columns: int = 2) -> Path:
    """All manuscript figures on one PNG (for the writer and the reviewers)."""
    files = sorted(p for p in ws.out_dir.glob("*") if p.suffix.lower() in GRAPHIC_SUFFIXES) \
        if ws.out_dir.is_dir() else []
    if not files:
        raise FigureToolError(f"No figures in {ws.out_dir}; run figures build first")
    return sheet_from_files(files, out or ws.preview_dir / "contact-sheet.png", columns=columns)


def sheet_from_files(files: list[Path], out: Path, *, columns: int = 2, labels: list[str] | None = None) -> Path:
    fitz = _fitz()
    width, gap, label_h = 1100.0, 24.0, 16.0
    cell_w = (width - gap * (columns + 1)) / columns
    cells = []
    for path in files:
        if path.suffix.lower() == ".pdf":
            with fitz.open(str(path)) as doc:
                rect = doc[0].rect
        else:
            with fitz.open(str(path)) as doc:
                rect = doc[0].rect
        scale = min(cell_w / rect.width, 1.8)
        cells.append((path, rect.width * scale, rect.height * scale))
    rows = [cells[i:i + columns] for i in range(0, len(cells), columns)]
    height = gap + sum(max(c[2] for c in row) + label_h + gap for row in rows)
    sheet = fitz.open()
    page = sheet.new_page(width=width, height=height)
    page.draw_rect(page.rect, color=None, fill=(1, 1, 1))
    y = gap
    index = 0
    for row in rows:
        row_h = max(c[2] for c in row)
        for column, (path, w, h) in enumerate(row):
            x = gap + column * (cell_w + gap)
            target = fitz.Rect(x, y + label_h, x + w, y + label_h + h)
            label = labels[index] if labels else path.name
            page.insert_text((x, y + 11), label, fontsize=10, fontname="helv", color=(0.25, 0.25, 0.25))
            if path.suffix.lower() == ".pdf":
                with fitz.open(str(path)) as doc:
                    page.show_pdf_page(target, doc, 0)
            else:
                page.insert_image(target, filename=str(path))
            page.draw_rect(target, color=(0.85, 0.85, 0.85), width=0.5)
            index += 1
        y += row_h + label_h + gap
    out.parent.mkdir(parents=True, exist_ok=True)
    zoom = 1.6
    page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False).save(str(out))
    sheet.close()
    return out


# --------------------------------------------------------------------------- templates
def template_catalog() -> list[dict[str, Any]]:
    import yaml

    data = yaml.safe_load((TEMPLATES / "catalog.yaml").read_text(encoding="utf-8")) or {}
    return list(data.get("templates") or [])


def new_figure(ws: Workspace, name: str, *, template: str | None = None, kind: str | None = None,
               force: bool = False) -> dict[str, Any]:
    catalog = template_catalog()
    suffix = {"tikz": ".tex", "tex": ".tex", "py": ".py", "python": ".py", "svg": ".svg", "html": ".html"}
    if template:
        entry = next((t for t in catalog if t["name"] == template), None)
        if entry is None:
            raise FigureToolError(f"Unknown template {template}; see figures new --list")
        source = TEMPLATES / entry["file"]
        if kind and suffix.get(kind) != source.suffix:
            raise FigureToolError(f"Template {template} is {source.suffix}, not --kind {kind}")
    else:
        if kind not in suffix:
            raise FigureToolError("Give --template NAME or --kind tikz|py|svg|html")
        source = TEMPLATES / "blank" / f"blank{suffix[kind]}"
        entry = {"use_when": "", "kind": "schematic"}
    stem = name if name.startswith("fig") else f"fig-{name}"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", stem):
        raise FigureToolError("Figure names use letters, digits, '-' and '_' only")
    target = ws.src_dir / f"{stem}{source.suffix}"
    if any((ws.src_dir / f"{stem}{s}").exists() for s in RENDERABLE) and not force:
        raise FigureToolError(f"A source for {stem} already exists (use --force to replace)")
    ws.src_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    companions = []
    for name in entry.get("companions") or []:  # inset scripts and other helpers (``_*`` files)
        helper = ws.src_dir / Path(name).name
        if not helper.exists() or force:
            shutil.copyfile(TEMPLATES / name, helper)
        companions.append(str(helper))
    sidecar = target.with_suffix(".json")
    if not sidecar.exists() or force:
        sidecar.write_text(json.dumps({
            "kind": entry.get("figure_kind", "schematic"),
            "purpose": "What the reader should see in this figure (one sentence).",
            "key_point": "The story-line point this figure carries.",
            "data_inputs": [],
            "template": template,
            **(entry.get("sidecar") or {}),
        }, indent=2) + "\n", encoding="utf-8")
    return {"source": str(target), "sidecar": str(sidecar), "template": template, "companions": companions}


# --------------------------------------------------------------------------- check helpers
_AI_TOOLS = re.compile(r"\b(?:OpenAI|ChatGPT|Codex|Claude|Anthropic|GPT-?\d[\w.-]*|Gemini|Copilot|Midjourney|"
                       r"DALL[·\-]?E|Stable Diffusion|LLM[- ]generated|AI[- ]generated)\b", re.I)
_PATHS = re.compile(r"(?:/workspace/|/home/|/tmp/|/mnt/|[A-Za-z]:\\\\|\bpapers/\d|\bmanuscript/|"
                    r"\b[\w-]+\.(?:py|json|ya?ml|ipynb|sh|log|tex)\b)")
_JOB_IDS = re.compile(r"\b(?:job[-_ ]?id|job[-_][0-9a-f]{6,}|run[-_]\d{6,}|\d{8}T\d{6}Z|[0-9a-f]{16,})\b", re.I)
_PLACEHOLDERS = re.compile(r"\b(?:TODO|TBD|FIXME|XXX|lorem ipsum|placeholder)\b", re.I)


def _vocabulary_findings(text: str) -> list[tuple[str, str]]:
    from paper_writing.manuscript_style import PROHIBITED_BODY_PATTERNS

    findings = []
    for code, pattern, message in (
            ("FIG-AI-TOOL-NAME", _AI_TOOLS, "AI tool names belong only in the AI-use declaration"),
            ("FIG-PATH", _PATHS, "file paths and script names are internal"),
            ("FIG-JOB-ID", _JOB_IDS, "job/run identifiers and hashes are internal"),
            ("FIG-PLACEHOLDER", _PLACEHOLDERS, "unfinished placeholder text")):
        match = pattern.search(text)
        if match:
            findings.append((code, f"'{match.group(0)}': {message}"))
    for code, pattern, message in PROHIBITED_BODY_PATTERNS:
        match = pattern.search(text)
        if match:
            findings.append(("FIG-INTERNAL-WORD", f"'{match.group(0)}' ({code}): {message}"))
    return findings


def _lab(rgb: tuple[float, float, float]) -> float:
    def lin(u: float) -> float:
        return u / 12.92 if u <= 0.04045 else ((u + 0.055) / 1.055) ** 2.4
    y = 0.2126 * lin(rgb[0]) + 0.7152 * lin(rgb[1]) + 0.0722 * lin(rgb[2])
    return 116 * y ** (1 / 3) - 16 if y > 0.008856 else 903.3 * y


def _hex(rgb: Iterable[float]) -> str:
    return "#" + "".join(f"{round(max(0.0, min(1.0, c)) * 255):02X}" for c in rgb)


def _color_findings(page) -> list[str]:
    """Chromatic colours that would merge in greyscale (only a hint: labels may carry the category)."""
    usage: dict[str, float] = {}
    page_area = max(1.0, page.rect.width * page.rect.height)
    for drawing in page.get_drawings():
        rect, rgb = drawing.get("rect"), drawing.get("fill")
        if rect is None or not rgb or len(rgb) != 3 or drawing.get("fill_opacity", 1) < 0.5:
            continue
        if max(rgb) - min(rgb) < 0.18 or _lab(rgb) > 85:
            continue  # greys and pale background tints
        usage[_hex(rgb)] = usage.get(_hex(rgb), 0.0) + rect.width * rect.height
    colors = [c for c in sorted(usage, key=usage.get, reverse=True)[:8] if usage[c] > 0.004 * page_area]
    pairs = []
    for i, a in enumerate(colors):
        for b in colors[i + 1:]:
            ra = tuple(int(a[k:k + 2], 16) / 255 for k in (1, 3, 5))
            rb = tuple(int(b[k:k + 2], 16) / 255 for k in (1, 3, 5))
            hue_a, hue_b = colorsys.rgb_to_hls(*ra)[0], colorsys.rgb_to_hls(*rb)[0]
            hue_gap = min(abs(hue_a - hue_b), 1 - abs(hue_a - hue_b))
            if hue_gap > 0.06 and abs(_lab(ra) - _lab(rb)) < 6:
                pairs.append(f"{a}/{b} (L* {_lab(ra):.0f}/{_lab(rb):.0f})")
    return pairs


def _segments(drawing) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    segs = []
    for item in drawing.get("items", []):
        op = item[0]
        if op == "l":
            segs.append(((item[1].x, item[1].y), (item[2].x, item[2].y)))
        elif op == "c":
            pts = [item[1], item[2], item[3], item[4]]
            prev = (pts[0].x, pts[0].y)
            for step in range(1, 9):
                t = step / 8
                x = ((1 - t) ** 3 * pts[0].x + 3 * (1 - t) ** 2 * t * pts[1].x
                     + 3 * (1 - t) * t ** 2 * pts[2].x + t ** 3 * pts[3].x)
                y = ((1 - t) ** 3 * pts[0].y + 3 * (1 - t) ** 2 * t * pts[1].y
                     + 3 * (1 - t) * t ** 2 * pts[2].y + t ** 3 * pts[3].y)
                segs.append((prev, (x, y)))
                prev = (x, y)
        elif op == "re":
            r = item[1]
            corners = [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)]
            segs += [(corners[k], corners[(k + 1) % 4]) for k in range(4)]
        elif op == "qu":
            q = item[1]
            corners = [(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.lr.x, q.lr.y), (q.ll.x, q.ll.y)]
            segs += [(corners[k], corners[(k + 1) % 4]) for k in range(4)]
    return segs


def _segment_hits_rect(a, b, rect) -> bool:
    """Liang-Barsky clip: does segment a-b pass through the rectangle's interior?"""
    x0, y0 = a
    dx, dy = b[0] - a[0], b[1] - a[1]
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - rect.x0), (dx, rect.x1 - x0), (-dy, y0 - rect.y0), (dy, rect.y1 - y0)):
        if abs(p) < 1e-9:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return False
    return t1 - t0 > 1e-6


def inspect_pdf(pdf: Path, *, scale: float = 1.0, result_plot: bool = False) -> dict[str, Any]:
    """Text sizes, overlaps, clipping, strokes through text, raster share and colour pairs."""
    fitz = _fitz()
    with fitz.open(str(pdf)) as doc:
        page = doc[0]
        page_rect = page.rect
        lines = []
        texts = []
        flags = fitz.TEXTFLAGS_DICT & ~fitz.TEXT_MEDIABOX_CLIP  # keep text that leaves the page
        for block in page.get_text("dict", flags=flags, clip=fitz.Rect(-1e4, -1e4, 1e4, 1e4))["blocks"]:
            for line in block.get("lines", []):
                spans = [s for s in line["spans"] if s["text"].strip()]
                if not spans:
                    continue
                text = "".join(s["text"] for s in spans).strip()
                texts.append(text)
                # Base size: the largest span of the line. Sub- and superscripts (short
                # spans clearly smaller than the base) are judged separately.
                base = max(s["size"] for s in spans)
                scripts = [s["size"] for s in spans if s["size"] < 0.85 * base and len(s["text"].strip()) <= 4]
                body = [s["size"] for s in spans if not (s["size"] < 0.85 * base and len(s["text"].strip()) <= 4)]
                lines.append({"text": text, "bbox": fitz.Rect(line["bbox"]), "size": min(body or [base]),
                              "script_size": min(scripts) if scripts else None,
                              "rotated": tuple(round(v, 3) for v in line.get("dir", (1, 0))) != (1.0, 0.0)})
        drawings = page.get_drawings()
        # Raster share: area covered by real image XObjects (shadings and patterns that
        # PyMuPDF also lists as image blocks are vector and do not count).
        grid = 60
        covered = set()
        for item in page.get_images(full=True):
            for box in page.get_image_rects(item[0]):
                box = fitz.Rect(box) & page_rect
                if box.is_empty:
                    continue
                gx0, gx1 = (int((v - page_rect.x0) / page_rect.width * grid) for v in (box.x0, box.x1))
                gy0, gy1 = (int((v - page_rect.y0) / page_rect.height * grid) for v in (box.y0, box.y1))
                covered.update((i, j) for i in range(gx0, min(gx1 + 1, grid)) for j in range(gy0, min(gy1 + 1, grid)))
        raster_fraction = len(covered) / grid ** 2
        colour_pairs = _color_findings(page)
        all_text = page.get_text("text")
        fonts = page.get_fonts(full=True)
        unembedded = sorted({f[3] for f in fonts if f[2] != "Type3" and f[1] in ("", "n/a")})
        type3 = sum(1 for f in fonts if f[2] == "Type3")
        plot = plot_findings(fitz, drawings, lines, _segments, _segment_hits_rect) if result_plot else []
    def core(rect, fx: float = 0.12, fy: float = 0.22):
        w, h = rect.width, rect.height
        return fitz.Rect(rect.x0 + w * fx, rect.y0 + h * fy, rect.x1 - w * fx, rect.y1 - h * fy)

    overlaps, clipped, crossings = [], [], []
    for i, a in enumerate(lines):
        # Line boxes include the font's ascender/descender, so text set tight to the top
        # or bottom edge pokes out a little; clipped means the glyph core leaves the page.
        glyph_core = core(a["bbox"], 0.3, 0.0) if a["rotated"] else core(a["bbox"], 0.0, 0.3)
        if not (glyph_core in fitz.Rect(page_rect.x0 - 0.75, page_rect.y0 - 0.75,
                                                      page_rect.x1 + 0.75, page_rect.y1 + 0.75)):
            clipped.append(a["text"][:40])
        ca = core(a["bbox"])
        for b in lines[i + 1:]:
            cb = core(b["bbox"])
            inter = ca & cb
            if inter.is_empty:
                continue
            smaller = min(ca.width * ca.height, cb.width * cb.height) or 1.0
            if inter.width * inter.height > 0.25 * smaller:
                overlaps.append(f"'{a['text'][:30]}' / '{b['text'][:30]}'")
    fills = [(d.get("seqno", 0), fitz.Rect(d["rect"])) for d in drawings
             if d.get("fill") is not None and d.get("fill_opacity", 1) > 0.9]
    for d in drawings:
        if d.get("type") not in ("s", "fs") or not d.get("color"):
            continue
        seq = d.get("seqno", 0)
        for line in lines:
            box = core(line["bbox"], 0.08, 0.28)
            if box.is_empty or not fitz.Rect(d["rect"]).intersects(line["bbox"]):
                continue
            if any(_segment_hits_rect(a, b, box) for a, b in _segments(d)):
                covered = any(s > seq and r.contains(box) for s, r in fills)
                if not covered and line["text"][:40] not in crossings:
                    crossings.append(line["text"][:40])
    sizes = sorted((round(l["size"] * scale, 2), l["text"][:40]) for l in lines)
    scripts = sorted((round(l["script_size"] * scale, 2), l["text"][:40]) for l in lines if l["script_size"])
    return {"page_mm": [round(page_rect.width / 72 * 25.4, 1), round(page_rect.height / 72 * 25.4, 1)],
            "page_pt": [round(page_rect.width, 2), round(page_rect.height, 2)],
            "text_lines": len(lines), "text": all_text,
            "min_font_pt": sizes[0][0] if sizes else None, "smallest_text": [t for s, t in sizes[:3]],
            "font_sizes": sizes, "min_script_pt": scripts[0][0] if scripts else None,
            "smallest_script_text": [t for _, t in scripts[:3]],
            "overlaps": overlaps[:10], "clipped": clipped[:10],
            "strokes_through_text": crossings[:10], "raster_fraction": round(raster_fraction, 3),
            "drawings": len(drawings), "grey_merge_pairs": colour_pairs, "plot_findings": plot,
            "unembedded_fonts": unembedded, "type3_fonts": type3}


# --------------------------------------------------------------------------- manuscript references
_INCLUDE = re.compile(r"\\includegraphics\s*(?:\[([^\]]*)\])?\s*\{([^}]*)\}")
_GRAPHICSPATH = re.compile(r"\\graphicspath\s*\{((?:\{[^}]*\})+)\}")


def _expanded(ws: Workspace) -> str:
    from paper_writing.review_flow import expand_tex

    main = ws.manuscript / "main.tex"
    if not main.is_file():
        return ""
    return expand_tex(main, ws.manuscript)


def _length_pt(value: str, widths: Mapping[str, float]) -> float | None:
    value = value.strip()
    match = re.fullmatch(r"([0-9]*\.?[0-9]+)?\s*\\(textwidth|linewidth|columnwidth|hsize|textheight)", value)
    if match:
        factor = float(match.group(1) or 1)
        return factor * widths.get(match.group(2), widths["linewidth"])
    match = re.fullmatch(r"([0-9]*\.?[0-9]+)\s*(pt|bp|mm|cm|in|pc)", value)
    if match:
        unit = {"pt": 1.0, "bp": 72.27 / 72, "mm": 72.27 / 25.4, "cm": 72.27 / 2.54, "in": 72.27, "pc": 12.0}
        return float(match.group(1)) * unit[match.group(2)] * 72 / 72.27  # to PostScript points
    return None


def layout_widths(ws: Workspace, override: str | None = None) -> dict[str, Any]:
    """Text and column widths in bp: ``--text-width``, a LaTeX probe of the preamble, or a default."""
    if override:
        width = _length_pt(override, {"linewidth": 0.0})
        if not width:
            raise FigureToolError(f"Unreadable --text-width {override!r} (use e.g. 160mm or 6.3in)")
        return {"textwidth": width, "columnwidth": width, "linewidth": width, "source": "--text-width"}
    probed = _probe_widths(ws)
    if probed:
        return probed
    return {"textwidth": 6.3 * 72, "columnwidth": 6.3 * 72, "linewidth": 6.3 * 72,
            "source": "default 6.3in (the manuscript preamble could not be probed)"}


def _probe_widths(ws: Workspace) -> dict[str, Any] | None:
    main = ws.manuscript / "main.tex"
    engine = shutil.which(os.environ.get("OPENLABS_FIG_PROBE_ENGINE") or "pdflatex")
    if not main.is_file() or not engine:
        return None
    text = main.read_text(errors="replace")
    if "\\begin{document}" not in text:
        return None
    preamble = text.split("\\begin{document}", 1)[0]
    probe = (preamble + "\n\\begin{document}\n\\typeout{OLFIGWIDTHS:\\the\\textwidth:\\the\\columnwidth}\n"
             "\\end{document}\n")
    with tempfile.TemporaryDirectory(prefix="olfig-probe-") as name:
        tmp = Path(name)
        (tmp / "probe.tex").write_text(probe, encoding="utf-8")
        env = dict(os.environ)
        env["TEXINPUTS"] = os.pathsep.join([str(ws.manuscript), env.get("TEXINPUTS", "")])
        try:
            proc = subprocess.run([engine, "-interaction=nonstopmode", "-draftmode", "probe.tex"], cwd=tmp,
                                  env=env, capture_output=True, text=True, errors="replace", timeout=120)
        except (subprocess.TimeoutExpired, OSError):
            return None
        match = re.search(r"OLFIGWIDTHS:([\d.]+)pt:([\d.]+)pt", proc.stdout)
    if not match:
        return None
    text_w, col_w = (float(v) * 72 / 72.27 for v in match.groups())
    return {"textwidth": text_w, "columnwidth": col_w, "linewidth": col_w,
            "source": "LaTeX probe of the manuscript preamble"}


def manuscript_uses(ws: Workspace, widths: Mapping[str, float]) -> dict[str, list[dict[str, Any]]]:
    """For each included graphic (keyed by manuscript-relative path without suffix): width, caption, ref."""
    expanded = re.sub(r"(?<!\\)%[^\n]*", "", _expanded(ws))
    graphic_dirs = [""]
    match = _GRAPHICSPATH.search(expanded)
    if match:
        graphic_dirs += [d.strip().rstrip("/") + "/" for d in re.findall(r"\{([^}]*)\}", match.group(1))]
    envs = [(m.start(), m.end(), m.group(1)) for m in
            re.finditer(r"\\begin\{(figure\*?|wrapfigure|SCfigure)\}.*?\\end\{\1\}", expanded, re.S)]
    uses: dict[str, list[dict[str, Any]]] = {}
    for inc in _INCLUDE.finditer(expanded):
        options, target = inc.group(1) or "", inc.group(2).strip().removeprefix("./")
        env = next(((s, e, name) for s, e, name in envs if s <= inc.start() < e), None)
        env_text = expanded[env[0]:env[1]] if env else ""
        local = dict(widths)
        if env and env[2] == "figure*":
            local["linewidth"] = widths["textwidth"]
        mini = re.findall(r"\\begin\{(?:minipage|subfigure)\}(?:\[[^\]]*\])*\{([^}]*)\}",
                          expanded[env[0]:inc.start()] if env else "")
        if mini:
            inner = _length_pt(mini[-1], local)
            if inner:
                local["linewidth"] = inner
        width = scale = None
        for part in options.split(","):
            key, _, value = part.partition("=")
            if key.strip() == "width":
                width = _length_pt(value, local)
            elif key.strip() == "scale":
                try:
                    scale = float(value)
                except ValueError:
                    pass
        labels = re.findall(r"\\label\{([^}]*)\}", env_text)
        referenced = [lab for lab in labels if re.search(
            r"\\(?:ref|cref|Cref|autoref|pageref|subref|vref|nameref)\*?\{[^}]*\b" + re.escape(lab) + r"\b",
            expanded)]
        record = {"options": options, "width_bp": width, "scale": scale, "environment": env[2] if env else None,
                  "caption": bool(re.search(r"\\caption(?:of)?\s*(?:\[[^\]]*\])?\s*\{", env_text)),
                  "labels": labels, "referenced": bool(referenced)}
        for prefix in graphic_dirs:
            key = os.path.normpath(prefix + target)
            record["suffix"] = Path(target).suffix.lower()
            uses.setdefault(re.sub(r"\.(pdf|png|jpe?g|eps)$", "", key, flags=re.I), []).append(record)
    return uses


# --------------------------------------------------------------------------- licences
_LICENSE_FIELDS = ("source", "license", "attribution", "url")


def classify_license(value: str) -> tuple[str, str]:
    """('ok'|'attribution'|'share_alike'|'incompatible'|'unknown', note)."""
    norm = re.sub(r"[\s_]+", "-", value.strip().lower())
    if not norm:
        return "unknown", "no licence given"
    if re.search(r"\bnc\b|non-?commercial|\bnd\b|no-?deriv", norm):
        return "incompatible", ("non-commercial or no-derivatives terms: not usable in a journal figure that "
                                "is recoloured and published by a commercial or open-access publisher")
    if re.search(r"cc0|public-?domain|\bpd\b|pdm|us-gov|own-work|authors?-own|original", norm):
        return "ok", "no attribution required"
    if re.search(r"cc-?by-?sa", norm):
        return "share_alike", "CC BY-SA: credit the source and check that the journal accepts share-alike figure terms"
    if re.search(r"cc-?by", norm):
        return "attribution", "CC BY: credit the creator, source and licence in the caption or acknowledgments"
    if re.search(r"\bmit\b|apache|bsd|ofl", norm):
        return "attribution", "permissive licence: keep the copyright notice (credit in the acknowledgments)"
    return "unknown", f"licence '{value}' is not recognised; verify it allows publication with modification"


def _asset_files(ws: Workspace, sources: list[FigureSource]) -> list[Path]:
    assets: list[Path] = []
    local = ws.src_dir / "assets"
    if local.is_dir():
        assets += [p for p in sorted(local.rglob("*")) if p.is_file() and not p.name.endswith(".license.json")
                   and not p.name.startswith(".")]
    library = asset_library()
    if library.is_dir():
        pattern = re.compile(r"[\w./-]+\.(?:svg|png|jpe?g|pdf)")
        for src in sources:
            for token in pattern.findall(src.path.read_text(errors="replace")):
                candidate = (library / token.lstrip("/")).resolve()
                if candidate.is_file() and library.resolve() in candidate.parents and candidate not in assets:
                    assets.append(candidate)
    return assets


def license_findings(ws: Workspace, sources: list[FigureSource], manuscript_text: str) -> tuple[list, list, list]:
    helpers = _style_helpers()
    blocking, advisory, records = [], [], []
    plain = re.sub(r"\s+", " ", re.sub(r"\\[A-Za-z]+\*?|[{}~]", " ", manuscript_text)).lower()
    for asset in _asset_files(ws, sources):
        meta_path = helpers.license_path(asset)
        name = asset.name
        if meta_path is None:
            blocking.append(_finding(name, "FIG-ASSET-LICENSE-MISSING",
                                     f"{name}: no {asset.stem}.license.json (fields: {', '.join(_LICENSE_FIELDS)})"))
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            blocking.append(_finding(name, "FIG-ASSET-LICENSE-INVALID", f"{meta_path.name}: {exc}"))
            continue
        missing = [k for k in _LICENSE_FIELDS if not str(meta.get(k) or "").strip()]
        status, note = classify_license(str(meta.get("license") or ""))
        record = {"asset": str(asset), "license": meta.get("license"), "status": status}
        if missing and status != "ok":
            blocking.append(_finding(name, "FIG-ASSET-LICENSE-INCOMPLETE",
                                     f"{meta_path.name}: missing {', '.join(missing)}"))
        if status in ("incompatible", "unknown"):
            blocking.append(_finding(name, "FIG-ASSET-LICENSE-INCOMPATIBLE", f"{name}: {note}"))
        elif status in ("attribution", "share_alike"):
            credit = str(meta.get("attribution") or "").strip()
            record["credit_line"] = helpers.credit_line(meta)
            if credit and credit.lower() not in plain:
                blocking.append(_finding(name, "FIG-ASSET-CREDIT-MISSING",
                                         f"{name}: {note}; the manuscript does not name '{credit}'. Suggested: "
                                         f"{record['credit_line']}"))
            elif status == "share_alike":
                advisory.append(_finding(name, "FIG-ASSET-SHARE-ALIKE", f"{name}: {note}"))
        if meta.get("ai_generated"):
            if _nature_target(ws):
                blocking.append(_finding(name, NATURE_AI_IMAGE_CODE,
                                         f"{name}: generated artwork in a Nature Portfolio target. "
                                         + NATURE_AI_IMAGE_RULE))
            else:
                advisory.append(_finding(name, "FIG-ASSET-AI-GENERATED",
                                         f"{name}: generated artwork; follow the artwork_disclosures rule and the "
                                         "target journal's AI-image policy"))
        records.append(record)
    return blocking, advisory, records


# --------------------------------------------------------------------------- generated images
# Springer Nature (ai-manuscript-preparation, read 2026-11-25): AI-generated visual content
# "created from text prompts or without verifiable source data or material" is not
# permitted; photorealistic images are not permitted (editorial-policies/ai). For a Nature
# Portfolio target every generated bitmap or illustration is refused: figures are drawn in
# code from data, rendered by domain software, or composed from licensed library assets.
NATURE_AI_IMAGE_CODE = "FIG-AI-IMAGE-NATURE"
NATURE_AI_IMAGE_RULE = (
    "Springer Nature does not accept generative-AI images made from text prompts; use a "
    "code-drawn vector figure, a render from data (rdkit, CIF, FITS ...) or licensed library "
    "assets, and move the generated file to revisions/unused-source-preserved/.")
_GENERATOR_TOOL = re.compile(r"image[_ ]?gen|gpt[- ]?image|dall[- ·]?e|midjourney|stable[- ]?diffusion|"
                             r"imagen|firefly|generative", re.I)


def _nature_target(ws: Workspace) -> bool:
    from paper_writing.publisher_family import nature_portfolio

    return nature_portfolio((ws.metadata or {}).get("target_journal"), ws.root)


def _generated_records(paper_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Image-generation provenance files (``*.provenance.json`` written by the image tool)."""
    found = []
    skip = {"support-materials", "revisions", "build"}
    for path in sorted(paper_dir.rglob("*.provenance.json")):
        if skip & set(path.relative_to(paper_dir).parts[:-1]):
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(record, Mapping) and _GENERATOR_TOOL.search(
                " ".join(str(record.get(key) or "") for key in ("tool", "c2pa_software_agent", "model"))):
            found.append((path, dict(record)))
    return found


def generated_image_findings(ws: Workspace) -> list[dict[str, str]]:
    """Blocking findings for generated images used by a Nature Portfolio manuscript."""
    if not _nature_target(ws):
        return []
    paper_dir = ws.manuscript.parent
    texts = []
    for path in paper_dir.rglob("*"):
        if (path.is_file() and path.suffix.lower() in {".tex", ".py", ".svg", ".html", ".json", ".sh"}
                and not path.name.endswith(".provenance.json")
                and not ({"support-materials", "revisions", "build"} & set(path.relative_to(paper_dir).parts))
                and path.stat().st_size < 2_000_000):
            texts.append(path.read_text(encoding="utf-8", errors="replace"))
    corpus = "\n".join(texts)
    hashes = {}
    for graphic in ws.manuscript.rglob("*"):
        if graphic.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} and graphic.is_file():
            hashes[hashlib.sha256(graphic.read_bytes()).hexdigest()] = graphic
    findings = []
    for path, record in _generated_records(paper_dir):
        image = path.with_name(path.name[: -len(".provenance.json")])
        used = (image.name in corpus or image.stem in corpus
                or str(record.get("sha256") or "") in hashes)
        if used:
            findings.append(_finding(image.name, NATURE_AI_IMAGE_CODE,
                                     f"{image.name}: generated with {record.get('tool') or 'an image model'}. "
                                     + NATURE_AI_IMAGE_RULE))
    for entry in (ws.metadata or {}).get("artwork_disclosures") or []:
        if isinstance(entry, Mapping) and entry.get("figure"):
            findings.append(_finding(Path(str(entry["figure"])).name, NATURE_AI_IMAGE_CODE,
                                     f"{entry['figure']}: registered as generated artwork "
                                     "(artwork_disclosures). " + NATURE_AI_IMAGE_RULE))
    return findings


def _finding(figure: str, code: str, message: str) -> dict[str, str]:
    return {"figure": figure, "code": code, "message": message}


# --------------------------------------------------------------------------- check
def _image_ppi(image):
    a, b, c, d, _, _ = image["transform"]
    width, height = math.hypot(a, b), math.hypot(c, d)
    if width and height:
        return min(72 * image["width"] / width, 72 * image["height"] / height)
    return None


def proof_figures(manuscript: Path, raster_files=()):
    """Locate pdfTeX figure placements on the rendered page using in-memory marker rectangles."""
    fitz = _fitz()
    proof = manuscript / "main.pdf"
    results = {}
    if not proof.is_file():
        return results
    raster_names = {}
    for path in raster_files:
        raster_names.setdefault(fitz.Pixmap(str(path)).digest, []).append(path.name)
    with fitz.open(proof) as doc, fitz.open(proof) as markers:
        for page in doc:
            objects = {}
            for xref, _, _, _ in page.get_xobjects():
                kind, filename = doc.xref_get_key(xref, "PTEX.FileName")
                if kind != "string" or Path(filename).suffix.lower() != ".pdf":
                    continue
                bbox = doc.xref_get_key(xref, "BBox")[1]
                x, y, right, top = map(float, bbox.strip("[]").split())
                # Identify repeated placements independently, including transformed XObjects.
                color = ((xref % 251 + 1) / 255, ((xref // 251) % 251 + 1) / 255, .314159)
                stream = "%f %f %f rg %f %f %f %f re f" % (*color, x, y, right-x, top-y)
                markers.update_stream(xref, stream.encode())
                objects[tuple(round(c * 255) for c in color)] = (Path(filename).stem, xref)
            images = page.get_image_info(hashes=bool(raster_names))
            for image in images:
                for name in raster_names.get(image.get("digest"), []):
                    results.setdefault(name, []).append({"page": page.number + 1, "min_ppi": _image_ppi(image)})
            if not objects:
                continue
            drawings = page.get_drawings()
            for mark in markers[page.number].get_drawings():
                match = objects.get(tuple(round(c * 255) for c in mark.get("fill") or ()))
                if not match:
                    continue
                name, xref = match
                rect = mark["rect"]
                text = page.get_text("dict", clip=rect, flags=fitz.TEXTFLAGS_TEXT)
                lines = [[span for span in line["spans"] if span["text"].strip()]
                         for block in text["blocks"] for line in block.get("lines", [])]
                fonts = [span["size"] for line in lines for span in line]
                # Exclude short superscripts/subscripts from the body-text minimum.
                body = [span["size"] for line in lines for span in line
                        if len(span["text"].strip()) > 4 or span["size"] >= .85 * max(s["size"] for s in line)]
                strokes = [d["width"] for d in drawings if d["type"] in ("s", "fs") and rect.contains(d["rect"])
                           and d.get("width") is not None]
                ppi = [resolution for image in images if rect.contains(fitz.Rect(image["bbox"]))
                       if (resolution := _image_ppi(image)) is not None]
                owners = {xref}
                for child, _, parent, _ in page.get_xobjects():
                    if parent in owners:
                        owners.add(child)
                missing = [f[3] for f in page.get_fonts(full=True) if f[-1] in owners and f[2] != "Type3"
                           and not doc.extract_font(f[0])[-1]]
                results.setdefault(name, []).append(dict(page=page.number+1, width_mm=rect.width*25.4/72,
                    min_body_pt=min(body, default=None), smallest_span_pt=min(fonts, default=None), min_stroke_pt=min(strokes, default=None),
                    min_ppi=min(ppi, default=None), unembedded_fonts=missing))
    return results


def proof_pdf(ws: Workspace) -> Path:
    """The compiled manuscript PDF: the registered ``latest_pdf`` when there is one."""
    latest = ws.metadata.get("latest_pdf") if ws.root else None
    return (ws.root / str(latest)).resolve() if latest else ws.manuscript / "main.pdf"


def check(ws: Workspace, *, rebuild: bool = True, text_width: str | None = None,
          min_font_pt: float = MIN_FONT_PT) -> dict[str, Any]:
    """Blocking and advisory findings for every manuscript figure (no file is changed)."""
    sources = discover(ws)
    by_stem = {s.stem: s for s in sources}
    pdfs = sorted(ws.out_dir.glob("*.pdf")) if ws.out_dir.is_dir() else []
    rasters = sorted(p for p in ws.out_dir.glob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg")) \
        if ws.out_dir.is_dir() else []
    widths = layout_widths(ws, text_width)
    uses = manuscript_uses(ws, widths)
    manuscript_text = _expanded(ws)
    blocking: list[dict[str, str]] = []
    advisory: list[dict[str, str]] = []
    figures: list[dict[str, Any]] = []
    plan, plan_error = read_plan(ws.manuscript)
    planned = {item["figure"]: item for item in plan.get("figures", [])}
    def uses_of(path: Path) -> list[dict[str, Any]]:
        key = (path.parent / path.stem).relative_to(ws.manuscript).as_posix()
        return [item for item in uses.get(key, [])
                if item["suffix"] == path.suffix.lower()
                or (not item["suffix"] and (path.suffix == ".pdf" or not path.with_suffix(".pdf").exists()))]

    included = {pdf.stem for pdf in pdfs if uses_of(pdf)}
    included_rasters = {raster.stem for raster in rasters if uses_of(raster)}
    required = []
    advisory.extend(standard_findings(plan, manuscript_text))
    if plan_error:
        advisory.append(_finding("plan", "FIG-PLAN", plan_error))
    if plan.get("paper_type") in {"method", "mechanism", "study_design"} and not any(
        item["kind"] == "schematic" and name in included and name in by_stem
        for name, item in planned.items()
    ):
        advisory.append(_finding("plan", "FIG-SCHEMATIC-MISSING",
                                 "Include a source-built vector schematic of the method, mechanism or study design."))
    for name, item in planned.items():
        if name not in included and not (item["kind"] == "object" and name in included_rasters):
            advisory.append(_finding(name, "FIG-PLAN-MISSING",
                                     f"Include the planned {item['figure_type']} showing {item['point']}."))
        elif not (ws.manuscript / item["source"]).is_file():
            required.append(_finding(name, "FIG-PLAN-SOURCE",
                                     f"Update the plan to point to the existing source for {name}."))
    if plan:
        for name in sorted((included | included_rasters) - set(planned)):
            advisory.append(_finding(name, "FIG-PLAN-UNLISTED",
                                     f"Describe {name} in the figure plan and link its source and evidence."))

    for stem, src in by_stem.items():
        if not (ws.out_dir / f"{stem}.pdf").is_file():
            blocking.append(_finding(stem, "FIG-NOT-BUILT", f"{src.path.name} has no figures/{stem}.pdf; "
                                     "run figures build"))
    try:
        placements = proof_figures(ws.manuscript, [path for path in rasters if uses_of(path)])
    except (RuntimeError, ValueError, OSError) as exc:
        advisory.append(_finding("proof", "FIG-PROOF-UNREADABLE", str(exc)))
        placements = {}
    for pdf in pdfs:
        stem = pdf.stem
        src = by_stem.get(stem)
        record: dict[str, Any] = {"figure": stem, "pdf": str(pdf), "source": str(src.path) if src else None,
                                  "kind": src.kind if src else "unspecified"}
        external = None
        if src is None:
            side = _sidecar(ws.src_dir / f"{stem}.json") if (ws.src_dir / f"{stem}.json").is_file() else {}
            external = side.get("source")
            record["kind"] = str(side.get("kind") or "unspecified")
            if external and (ws.src_dir / str(external)).resolve().is_file():
                record["source"] = str((ws.src_dir / str(external)).resolve())
                record["source_external"] = True
            else:
                blocking.append(_finding(stem, "FIG-NO-SOURCE",
                                         f"figures/{pdf.name} has no source in {FIGURE_SRC}/ (a .tex/.py/.svg/.html "
                                         f"with the same stem, or {stem}.json naming the generating script)"))
        elif rebuild:
            with tempfile.TemporaryDirectory(prefix="olfig-check-") as name:
                fresh = Path(name) / f"{stem}.pdf"
                try:
                    render(src, fresh)
                except FigureToolError as exc:
                    blocking.append(_finding(stem, "FIG-REBUILD-FAILED", f"{src.path.name} does not rebuild: {exc}"))
                else:
                    if hashlib.sha256(fresh.read_bytes()).digest() != hashlib.sha256(pdf.read_bytes()).digest():
                        now, then = inspect_pdf(fresh), inspect_pdf(pdf)
                        if now["page_pt"] != then["page_pt"] or now["text"] != then["text"]:
                            advisory.append(_finding(stem, "FIG-STALE",
                                                     f"figures/{pdf.name} differs from a fresh build of "
                                                     f"{src.path.name}; run figures build"))
        use = uses_of(pdf)
        record["kind"] = planned.get(stem, {}).get("kind", record["kind"])
        try:
            info = inspect_pdf(pdf, result_plot=bool(use) and record["kind"] != "schematic"
                               and record["kind"] != "object")
        except Exception as exc:  # noqa: BLE001 - an unreadable PDF is a finding, not a crash
            blocking.append(_finding(stem, "FIG-UNREADABLE", f"figures/{pdf.name}: {exc}"))
            figures.append(record)
            continue
        natural = info["page_pt"][0]
        final_widths = [u["width_bp"] or (natural * u["scale"] if u["scale"] else natural) for u in use]
        record["proof_placements"] = placements.get(stem, [])
        if record["proof_placements"]:
            final_widths = [item["width_mm"] * 72 / 25.4 for item in record["proof_placements"]]
            for item in record["proof_placements"]:
                for field, limit, unit in (("min_stroke_pt", .25, "bp"), ("min_ppi", 300, "ppi")):
                    if item[field] is not None and item[field] < limit - .01:
                        required.append(_finding(stem, "FIG-PROOF-READABILITY",
                            f"Page {item['page']}: {field} {item[field]:.2f} {unit}; readability target {limit}."))
                if item["min_body_pt"] is not None and item["min_body_pt"] < min_font_pt - FONT_TOLERANCE_PT:
                    required.append(_finding(stem, "FIG-PROOF-TEXT",
                        f"Page {item['page']}: body text measures {item['min_body_pt']:.2f} bp."))
                if item["unembedded_fonts"]:
                    required.append(_finding(stem, "FIG-PROOF-FONT", str(item["unembedded_fonts"])))
        elif use:
            advisory.append(_finding(stem, "FIG-PROOF-UNMEASURED", "Placement unavailable in main.pdf; using source estimate."))
        final = min(final_widths) if final_widths else natural
        scale = final / natural if natural else 1.0
        record |= {"page_mm": info["page_mm"], "final_width_mm": round(final / 72 * 25.4, 1),
                   "scale": round(scale, 3),
                   "min_font_pt": round(info["min_font_pt"] * scale, 2) if info["min_font_pt"] else None,
                   "raster_fraction": info["raster_fraction"]}
        if not use:
            advisory.append(_finding(stem, "FIG-NOT-INCLUDED",
                                     f"figures/{pdf.name} is not included by the manuscript (sizes assume 100%)"))
        for u in use:
            if not u["caption"]:
                blocking.append(_finding(stem, "FIG-NO-CAPTION", f"figures/{pdf.name} is included without a caption"))
            elif not u["referenced"]:
                blocking.append(_finding(stem, "FIG-NOT-CITED",
                                         f"figures/{pdf.name}: the text never refers to it (\\label + \\ref)"))
        if record["min_font_pt"] is not None and record["min_font_pt"] < min_font_pt - FONT_TOLERANCE_PT:
            small = ", ".join(f"'{t}'" for t in info["smallest_text"])
            blocking.append(_finding(stem, "FIG-FONT-TOO-SMALL",
                                     f"smallest text {record['min_font_pt']} pt at the printed width "
                                     f"{record['final_width_mm']} mm (minimum {min_font_pt} pt): {small}"))
        if info.get("min_script_pt") and info["min_script_pt"] * scale < 4.5:
            advisory.append(_finding(stem, "FIG-SCRIPT-TOO-SMALL",
                                     f"sub/superscripts print at {info['min_script_pt'] * scale:.1f} pt: "
                                     + ", ".join(f"'{t}'" for t in info["smallest_script_text"])))
        if scale > 1.6 and info["text_lines"]:
            advisory.append(_finding(stem, "FIG-UPSCALED", f"drawn at {info['page_mm'][0]} mm but printed at "
                                     f"{record['final_width_mm']} mm (x{scale:.2f}); draw at the final width so "
                                     "strokes and text keep their designed size"))
        if info.get("unembedded_fonts"):
            advisory.append(_finding(stem, "FIG-FONT-NOT-EMBEDDED",  # the proof check (main.pdf) requires it
                                     "fonts not embedded in figures/" + pdf.name + ": "
                                     + ", ".join(info["unembedded_fonts"]) + "; journals require embedded fonts"))
        if info.get("type3_fonts") and info["text_lines"]:
            advisory.append(_finding(stem, "FIG-FONT-TYPE3",
                                     f"{info['type3_fonts']} Type 3 font(s) in figures/{pdf.name}: some journals "
                                     "(IEEE PDF eXpress) reject them; HTML/SVG figures embed TrueType when the "
                                     "text uses Liberation Sans or Arial"))
        profile = (src.sidecar.get("profile") if src else None) or "generic"
        double = _style_helpers()._catalog["profiles"].get(profile, {}).get("double")
        if double and info["page_mm"][0] > double + 1.0:
            advisory.append(_finding(stem, "FIG-WIDER-THAN-PROFILE",
                                     f"drawn {info['page_mm'][0]} mm wide; the {profile} double-column width is "
                                     f"{double} mm, so the figure will be shrunk (draw it at a column width)"))
        if info["raster_fraction"] > 0.9 and info["text_lines"] == 0:
            blocking.append(_finding(stem, "FIG-RASTER-PAGE",
                                     f"figures/{pdf.name} is a bitmap inside a PDF; render the figure as vectors"))
        elif info["raster_fraction"] > 0.5 and record["kind"] == "schematic":
            advisory.append(_finding(stem, "FIG-RASTER-SCHEMATIC",
                                     f"{info['raster_fraction']:.0%} of the schematic is raster; draw it as vectors"))
        for code, message in info["plot_findings"]:
            advisory.append(_finding(stem, code, message))
        for text in info["overlaps"]:
            blocking.append(_finding(stem, "FIG-TEXT-OVERLAP", f"overlapping text {text}"))
        for text in info["clipped"]:
            blocking.append(_finding(stem, "FIG-TEXT-CLIPPED", f"text runs past the figure edge: '{text}'"))
        for text in info["strokes_through_text"]:
            advisory.append(_finding(stem, "FIG-LINE-THROUGH-TEXT", f"a line or arrow crosses the text '{text}'"))
        for code, message in _vocabulary_findings(info["text"]):
            blocking.append(_finding(stem, code, message))
        if info["grey_merge_pairs"]:
            advisory.append(_finding(stem, "FIG-COLOR-ONLY",
                                     "colours with nearly equal grey value: " + "; ".join(info["grey_merge_pairs"])
                                     + " -- if colour is the only cue for a category, add labels, line styles "
                                     "or patterns"))
        figures.append(record)
    for raster in rasters:
        if uses_of(raster):
            for item in placements.get(raster.name, []):
                if item["min_ppi"] is not None and item["min_ppi"] < 299.99:
                    required.append(_finding(raster.stem, "FIG-PROOF-READABILITY",
                        f"Page {item['page']}: {raster.name} measures {item['min_ppi']:.1f} ppi."))
            if planned.get(raster.stem, {}).get("kind") == "result":
                required.append(_finding(raster.stem, "FIG-RASTER-RESULT",
                                         "Export the result plot as vector PDF and include that file."))
            advisory.append(_finding(raster.stem, "FIG-RASTER-FILE",
                                     f"figures/{raster.name} is a bitmap: fine for photographs and image data; "
                                     "schematics and plots belong in vector PDF"))
    from paper_writing.float_placement import check as placement_check
    placement = placement_check(ws.manuscript, pdf=proof_pdf(ws))
    blocking += placement["errors"]
    if placement["status"] in {"no_pdf", "unreadable"}:
        advisory.append(_finding("proof", "FIG-PLACEMENT-UNMEASURED", "; ".join(placement["notes"])))
    lic_block, lic_advice, licenses = license_findings(ws, sources, manuscript_text)
    blocking += lic_block
    blocking += generated_image_findings(ws)
    advisory += lic_advice
    required += [item for item in advisory if item["code"] in PLOT_FINDINGS]
    return {"manuscript": str(ws.manuscript), "paper_id": ws.paper_id,
            "layout": {k: (round(v / 72 * 25.4, 1) if isinstance(v, float) else v) for k, v in widths.items()},
            "raster_placements": {p.name: placements.get(p.name, []) for p in rasters if uses_of(p)},
            "layout_units": "mm", "min_font_pt": min_font_pt, "figures": figures, "assets": licenses,
            "float_placement": placement,
            "blocking": blocking, "advisory": advisory, "repair_required": required, "valid": not blocking}


def render_check(result: Mapping[str, Any]) -> str:
    layout = result["layout"]
    lines = [f"Figures: {len(result['figures'])} PDF(s) in {result['manuscript']}/figures; "
             f"layout text width {layout.get('textwidth')} mm, column {layout.get('columnwidth')} mm "
             f"({layout.get('source')})."]
    for fig in result["figures"]:
        lines.append(f"- {fig['figure']}: {fig.get('kind')}, printed {fig.get('final_width_mm')} mm "
                     f"(x{fig.get('scale')}), smallest text {fig.get('min_font_pt')} pt"
                     + ("" if fig.get("source") else ", NO SOURCE"))
    lines.append(f"Blocking ({len(result['blocking'])}):" if result["blocking"] else "Blocking: none.")
    lines += [f"  BLOCK {f['code']} [{f['figure']}]: {f['message']}" for f in result["blocking"]]
    repair = result.get("repair_required", [])
    lines.append(f"Figure repair ({len(repair)}):" if repair else "Figure repair: none.")
    lines += [f"  REPAIR {f['code']} [{f['figure']}]: {f['message']}" for f in repair]
    lines.append(f"Advisory ({len(result['advisory'])}):" if result["advisory"] else "Advisory: none.")
    lines += [f"  ADVICE {f['code']} [{f['figure']}]: {f['message']}" for f in result["advisory"]]
    lines.append("Look at every preview PNG yourself as well; the checks do not judge whether a figure "
                 "carries its point.")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- review support
REVIEW_GRAPHIC_SUFFIXES = (".pdf", ".png", ".jpg", ".jpeg")


def review_figure_files(manuscript: Path, build_inputs: Iterable[str]) -> list[dict[str, Any]]:
    """Graphics the build actually read (manuscript-relative), with their SHA-256."""
    files = []
    for rel in sorted(set(build_inputs)):
        path = (manuscript / rel).resolve()
        if (path.suffix.lower() not in REVIEW_GRAPHIC_SUFFIXES or not path.is_file()
                or manuscript.resolve() not in path.parents
                or (path.parent == manuscript.resolve() and path.name in {"main.pdf", "supplement.pdf"})):
            continue  # root PDFs are compiled outputs (main, supplement), not figures
        files.append({"path": Path(rel).as_posix(),
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return files


def review_images(manuscript: Path, figure_files: list[Mapping[str, Any]], outdir: Path, *,
                  max_images: int = 10, max_pixels: int = 1600) -> dict[str, Any]:
    """PNG renderings for the reviewers: one per figure, or a contact sheet when there are many.

    On rendering failure return no images and a diagnostic for the review gate.
    """
    if not figure_files:
        return {"images": [], "notes": []}
    outdir.mkdir(parents=True, exist_ok=True)
    images, notes = [], []
    try:
        pngs = []
        for index, item in enumerate(figure_files, start=1):
            source = manuscript / item["path"]
            png = outdir / f"figure-{index:02d}.png"
            if source.suffix.lower() == ".pdf":
                render_png(source, png, dpi=170, max_pixels=max_pixels)
            else:
                fitz = _fitz()
                with fitz.open(str(source)) as doc:
                    rect = doc[0].rect
                    zoom = min(1.0, max_pixels / max(rect.width, rect.height))
                    doc[0].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False).save(str(png))
            pngs.append((item, png))
        if len(pngs) <= max_images:
            images = [{"figure": item["path"], "sha256": item["sha256"], "png": str(png),
                       "png_sha256": hashlib.sha256(png.read_bytes()).hexdigest()} for item, png in pngs]
        else:
            sheet = sheet_from_files([manuscript / item["path"] for item, _ in pngs], outdir / "contact-sheet.png",
                                     columns=3, labels=[item["path"] for item, _ in pngs])
            images = [{"figure": "contact sheet of all figures", "sha256": "", "png": str(sheet),
                       "png_sha256": hashlib.sha256(sheet.read_bytes()).hexdigest()}]
            notes.append(f"{len(pngs)} figures: attached as one contact sheet")
    except Exception as exc:  # noqa: BLE001 - convert renderer errors into gate diagnostics
        notes.append(f"figure images unavailable: {exc}")
        images = []
    return {"images": images, "notes": notes}


def recolor_file(source: Path, target: Path, mapping: Mapping[str, str] | None = None) -> Path:
    helpers = _style_helpers()
    target.write_text(helpers.recolor_svg(source.read_text(encoding="utf-8"), mapping), encoding="utf-8")
    return target



def review_inventory(pre):
    """Count the graphics actually read by TeX and bind candidate sources to this review."""
    metrics = dict(schematic_count=0, result_count=0, check_passed=None,
                   figure_seats=None, required_changes=0)
    candidates = []
    if not pre.get("manuscript_path"):
        return metrics, candidates
    manuscript = Path(pre["manuscript_path"])
    if not manuscript.is_dir():
        return metrics, candidates
    seats = manuscript.parent / "build" / "figure-seats.json"
    if seats.is_file():
        try:
            count = json.loads(seats.read_text()).get("count")
            if type(count) is int and count >= 0:
                metrics["figure_seats"] = count
        except (OSError, ValueError, AttributeError):
            pass
    try:
        ws = workspace(manuscript=manuscript)
        audit = check(ws, rebuild=False)
    except (OSError, ValueError, FigureToolError):
        return metrics, candidates
    metrics["check_passed"] = not (audit["blocking"] or audit["repair_required"])
    included = {item["path"]: item["sha256"] for item in pre.get("figure_files", [])}
    plan, _ = read_plan(manuscript)
    planned = {item["figure"]: item["kind"] for item in plan.get("figures", [])}
    counted = set()
    for item in audit["figures"]:
        pdf = Path(item["pdf"])
        digest = included.get(pdf.relative_to(manuscript).as_posix())
        if not digest or item["kind"] not in {"schematic", "result"}:
            continue
        counted.add(pdf.relative_to(manuscript).as_posix())
        metrics[item["kind"] + "_count"] += 1
        if item["kind"] == "schematic" and item.get("source"):
            src = Path(item["source"])
            if src.parent == ws.src_dir and src.resolve() == src and src.is_file():
                candidates.append(dict(source=src.name, source_sha256=hashlib.sha256(src.read_bytes()).hexdigest(),
                                       pdf=pdf.name, pdf_sha256=digest))
    for name in included.keys() - counted:
        kind = planned.get(Path(name).stem)
        if kind in {"schematic", "result"}:
            metrics[kind + "_count"] += 1
    return metrics, candidates
