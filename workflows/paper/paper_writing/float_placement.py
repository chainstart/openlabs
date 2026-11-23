"""Where each main-text figure lands in the compiled PDF relative to its first mention.

A single-column class (elsarticle ``preprint``, ``onecolumn``) only lets a ``figure*`` or a
``[t]``-only float go to the top of a page; when those slots run out LaTeX defers every later
figure to the end of the document. The check reads the compiled PDF and reports each body
figure that prints more than ``MAX_PAGE_DISTANCE`` pages after (or before) the page that first
refers to it.

The figure page comes from the pdfTeX ``PTEX.FileName`` of the included graphics, else from the
caption lead ("Figure 3:", "Fig. 3."), else from ``main.aux``. The first-reference page is the
first page whose text names the figure ("Fig. 3", "Figure 3a", "Figs. 2 and 3", "Figures 2-4")
outside its own caption lead. Appendix figures and ``endfloat`` manuscripts are not checked.
"""
from __future__ import annotations

from pathlib import Path
import re
from typing import Any

MAX_PAGE_DISTANCE = 1
_ENV = re.compile(r"\\begin\{(figure\*?|wrapfigure|SCfigure)\}(.*?)\\end\{\1\}", re.S)
_LABEL = re.compile(r"\\label\{([^}]*)\}")
_GRAPHIC = re.compile(r"\\includegraphics\*?\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")
_NUM = r"(?:[A-Z]\.?)?\d+(?:\.\d+)?"
_REF = re.compile(r"\b(?:Figs?\.|Figures?)\s*(" + _NUM + r"(?:[a-z](?![a-z]))?"
                  r"(?:\s*(?:,|;|and|&|to|[-\u2013\u2014])\s*(?:" + _NUM + r")?(?:[a-z](?![a-z]))?)*)")
_NEWLABEL = re.compile(r"\\newlabel\{([^}]*)\}\{\{([^}]*)\}\{([^}]*)\}")


def _fitz():
    try:
        import pymupdf as fitz  # noqa: PLC0415
    except ImportError:
        import fitz  # type: ignore  # noqa: PLC0415
    return fitz


def _caption_lead(number: str) -> re.Pattern:
    return re.compile(r"(?m)^\s*(?:Figure|Fig\.?)\s*" + re.escape(number) + r"\s*[:.|]")


def _source(manuscript: Path, main: Path) -> str:
    from paper_writing.review_flow import expand_tex

    return re.sub(r"(?<!\\)%[^\n]*", "", expand_tex(main, manuscript))


def body_figures(source: str) -> list[dict[str, Any]]:
    """Figure environments of the main body in order, numbered as LaTeX would number them."""
    body = re.split(r"\\begin\{document\}", source, maxsplit=1)[-1]
    body = re.split(r"\\appendix\b|\\begin\{appendices\}|\\bibliography\{|\\begin\{thebibliography\}"
                    r"|\\printbibliography", body, maxsplit=1)[0]
    figures = []
    for match in _ENV.finditer(body):
        content = match.group(2)
        if not re.search(r"\\caption\s*(?:\[[^\]]*\])?\s*\{", content):
            continue
        figures.append({"number": str(len(figures) + 1), "environment": match.group(1),
                        "labels": _LABEL.findall(content),
                        "graphics": [Path(g.strip()).stem for g in _GRAPHIC.findall(content)]})
    return figures


def _aux_labels(aux: Path) -> dict[str, tuple[str, str]]:
    if not aux.is_file():
        return {}
    return {label: (number, page) for label, number, page in _NEWLABEL.findall(aux.read_text(errors="replace"))}


def _numbers(group: str) -> set[str]:
    found: set[str] = set()
    tokens = re.findall(r"(" + _NUM + r")|(\bto\b|[-\u2013\u2014])", group)
    previous = None
    pending_range = False
    for number, dash in tokens:
        if dash:
            pending_range = previous is not None
            continue
        if pending_range and previous and previous.isdigit() and number.isdigit() and int(number) - int(previous) < 50:
            found.update(str(n) for n in range(int(previous), int(number) + 1))
        found.add(number)
        previous, pending_range = number, False
    return found


def _page_texts(doc) -> list[str]:
    return [page.get_text("text").replace("\u00a0", " ") for page in doc]


def _graphic_pages(doc) -> dict[str, list[int]]:
    pages: dict[str, list[int]] = {}
    for page in doc:
        for xref, *_ in page.get_xobjects():
            kind, name = doc.xref_get_key(xref, "PTEX.FileName")
            if kind == "string":
                pages.setdefault(Path(name).stem, []).append(page.number + 1)
    return pages


def check(manuscript: str | Path, *, pdf: str | Path | None = None, main: str | Path | None = None,
          max_distance: int = MAX_PAGE_DISTANCE) -> dict[str, Any]:
    """Return ``status`` (ok, errors, no_pdf, no_source, no_figures, endfloat, unreadable), figures, errors."""
    manuscript = Path(manuscript).resolve()
    main = Path(main) if main else manuscript / "main.tex"
    pdf = Path(pdf) if pdf else main.with_suffix(".pdf")
    result: dict[str, Any] = {"pdf": str(pdf), "max_page_distance": max_distance, "figures": [], "errors": [],
                              "notes": []}
    if not main.is_file():
        return result | {"status": "no_source", "notes": [f"{main} is missing"]}
    source = _source(manuscript, main)
    if re.search(r"\\usepackage\s*(?:\[[^\]]*\])?\s*\{[^}]*\bendfloat\b", source):
        return result | {"status": "endfloat", "notes": ["endfloat puts figures at the end by design"]}
    figures = body_figures(source)
    if not figures:
        return result | {"status": "no_figures"}
    if not pdf.is_file():
        return result | {"status": "no_pdf", "notes": [f"{pdf.name} is missing: compile the manuscript first"]}
    aux = _aux_labels(pdf.with_suffix(".aux"))
    try:
        fitz = _fitz()
        with fitz.open(str(pdf)) as doc:
            texts = _page_texts(doc)
            graphics = _graphic_pages(doc)
    except Exception as exc:  # noqa: BLE001 - an unreadable proof is a status, not a crash
        return result | {"status": "unreadable", "notes": [f"{pdf.name}: {exc}"]}
    shared = {stem for i, fig in enumerate(figures) for stem in fig["graphics"]
              if any(stem in other["graphics"] for j, other in enumerate(figures) if j != i)}
    for fig in figures:
        known = [aux[label] for label in fig["labels"] if label in aux]
        if known:
            fig["number"] = known[0][0]
        lead = _caption_lead(fig["number"])
        pages = [p for stem in fig["graphics"] if stem not in shared for p in graphics.get(stem, [])]
        if pages:
            fig["figure_page"], fig["page_source"] = min(pages), "graphic"
        else:
            caption = next((i + 1 for i, text in enumerate(texts) if lead.search(text)), None)
            if caption:
                fig["figure_page"], fig["page_source"] = caption, "caption"
            elif known and known[0][1].isdigit():
                fig["figure_page"], fig["page_source"] = int(known[0][1]), "aux"
            else:
                fig["figure_page"], fig["page_source"] = None, None
        fig["first_reference_page"] = None
        for index, text in enumerate(texts):
            text = re.sub(r"\s+", " ", lead.sub(" ", text))
            if any(fig["number"] in _numbers(match.group(1)) for match in _REF.finditer(text)):
                fig["first_reference_page"] = index + 1
                break
        page, first = fig["figure_page"], fig["first_reference_page"]
        name = fig["labels"][0] if fig["labels"] else f"Figure {fig['number']}"
        if page is None:
            result["notes"].append(f"{name}: Figure {fig['number']} was not located in {pdf.name}")
        elif first is None:
            result["notes"].append(f"{name}: no text reference to Figure {fig['number']} found in {pdf.name}")
        else:
            fig["distance"] = page - first
            if page - first > max_distance:
                result["errors"].append({"figure": name, "code": "FIG-FLOAT-FAR-FROM-REFERENCE", "message": (
                    f"Figure {fig['number']} prints on page {page}, {page - first} pages after its first "
                    f"mention on page {first}. Use \\begin{{figure}}[!htbp] (not figure* or [t] alone in a "
                    "single-column layout) right after the paragraph that first cites it, and recompile.")})
            elif first - page > max_distance:
                result["errors"].append({"figure": name, "code": "FIG-FLOAT-BEFORE-REFERENCE", "message": (
                    f"Figure {fig['number']} prints on page {page}, {first - page} pages before its first "
                    f"mention on page {first}. Move the figure environment after the paragraph that first "
                    "cites it, and recompile.")})
        result["figures"].append(fig)
    return result | {"status": "errors" if result["errors"] else "ok"}
