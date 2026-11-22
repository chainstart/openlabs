"""Helpers for OpenLabs figure sources (palette, widths, saving, SVG assets).

Importable from every ``figure-src/*.py`` built by ``paper-writing figures build``
(the build puts this directory on ``PYTHONPATH`` and applies ``openlabs.mplstyle``).
Only the standard library is needed at import time; matplotlib is imported lazily.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Iterable, Mapping

# Extended Okabe-Ito palette; the first four also differ in grey value.
PALETTE = {
    "blue": "#0072B2", "orange": "#E69F00", "wine": "#882255", "green": "#009E73",
    "sky": "#56B4E9", "vermilion": "#D55E00", "purple": "#CC79A7", "yellow": "#F0E442",
    "ink": "#222222", "gray": "#666666", "light": "#E4E4E4", "paper": "#F5F5F5",
}
CYCLE = [PALETTE[k] for k in ("blue", "orange", "wine", "green", "sky", "vermilion", "purple", "gray")]

MM_PER_IN = 25.4
_catalog = json.loads(Path(__file__).with_name("profiles.json").read_text())


def profile_name(journal):
    names = {k.casefold().replace("&", "and"): v for k, v in _catalog["journals"].items()}
    return names.get(str(journal).casefold().replace("&", "and"), "generic")


PROFILE_NAMES = frozenset(_catalog["profiles"])
PROFILE = _catalog["profiles"][os.environ.get("OPENLABS_FIG_PROFILE", "generic")]
WIDTHS_IN = {k: PROFILE[k] / MM_PER_IN for k in ("single", "onehalf", "double") if PROFILE[k]}
SINGLE_COLUMN_MM, ONE_HALF_COLUMN_MM, DOUBLE_COLUMN_MM = (PROFILE[k] for k in ("single", "onehalf", "double"))
SINGLE_COLUMN_IN, ONE_HALF_COLUMN_IN, DOUBLE_COLUMN_IN = (WIDTHS_IN.get(k) for k in ("single", "onehalf", "double"))


def apply_profile(plt):
    p = PROFILE
    plt.rcParams.update({"figure.figsize": (SINGLE_COLUMN_IN, SINGLE_COLUMN_IN * .68),
                         "font.size": p["body"], "axes.labelsize": p["body"], "axes.titlesize": p["body"],
                         "xtick.labelsize": p["small"], "ytick.labelsize": p["small"], "legend.fontsize": p["small"],
                         "lines.linewidth": p["line"], "axes.linewidth": p["axis"],
                         "xtick.major.width": p["axis"], "ytick.major.width": p["axis"]})


def panel_label(ax, letter):
    return ax.text(0, 1, letter, transform=ax.transAxes, va="top", ha="left",
                   fontsize=PROFILE["panel"], fontweight="bold", fontstyle="normal")


def tex_profile(name):
    p = _catalog["profiles"][name]
    return "".join(r"\def\ol%s{%s}" % (key, value) + "\n"
                   for key, value in p.items() if value is not None)


STYLE_SHEET = Path(__file__).with_name("openlabs.mplstyle")
DEFAULT_ASSET_LIBRARY = "/workspace/openlabs/build/figure-assets"


def tint(color: str, amount: float) -> str:
    """Mix ``color`` with white; ``amount`` 0 is white, 1 the colour itself."""
    r, g, b = _rgb(color)
    mix = [round(255 - (255 - c) * amount) for c in (r, g, b)]
    return "#%02X%02X%02X" % tuple(mix)


def figure(width: str | float = "single", height: float | None = None, **kwargs):
    """A matplotlib figure at its final printed width (``single``/``onehalf``/``double`` or inches)."""
    import matplotlib.pyplot as plt

    w = WIDTHS_IN[width] if isinstance(width, str) else float(width)
    return plt.figure(figsize=(w, height if height is not None else w * 0.62), **kwargs)


def output_path(default: str = "figure.pdf") -> Path:
    """Where the build expects the PDF (``$FIG_OUT``); a local default when run by hand."""
    return Path(os.environ.get("FIG_OUT") or default)


def save(fig, path: str | os.PathLike | None = None) -> Path:
    target = Path(path) if path is not None else output_path()
    suffix = target.suffix.lower().lstrip(".")
    if suffix not in {"pdf", "svg", "png", "tif", "tiff", "jpg", "jpeg", "eps"}:
        raise ValueError(f"Unsupported figure extension: {target.suffix}")
    fig.savefig(target, format=suffix)
    return target


# ---------------------------------------------------------------- SVG assets
def asset_roots(source_dir: str | os.PathLike | None = None) -> list[Path]:
    """``figure-src/assets/`` of this paper first, then the shared library (``OPENLABS_FIG_ASSETS``)."""
    roots = []
    base = Path(source_dir or os.environ.get("FIG_SRC_DIR") or ".")
    roots.append(base / "assets")
    roots.append(Path(os.environ.get("OPENLABS_FIG_ASSETS") or DEFAULT_ASSET_LIBRARY))
    return roots


def find_asset(name: str, source_dir: str | os.PathLike | None = None) -> Path:
    for root in asset_roots(source_dir):
        candidate = root / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"asset {name!r} not found in " + ", ".join(map(str, asset_roots(source_dir))))


def license_path(asset: str | os.PathLike) -> Path | None:
    """``<asset>.license.json`` or ``<stem>.license.json`` next to the asset."""
    path = Path(asset)
    for candidate in (path.with_name(path.name + ".license.json"), path.with_name(path.stem + ".license.json")):
        if candidate.is_file():
            return candidate
    return None


def asset_license(asset: str | os.PathLike) -> dict | None:
    meta = license_path(asset)
    return json.loads(meta.read_text(encoding="utf-8")) if meta else None


def credit_line(meta: Mapping[str, str]) -> str:
    """Attribution sentence for a caption or the acknowledgments (CC BY and similar)."""
    parts = [str(meta.get("attribution") or "").strip()]
    if meta.get("source"):
        parts.append(str(meta["source"]).strip())
    text = ", ".join(p for p in parts if p)
    licence = str(meta.get("license") or "").strip()
    url = str(meta.get("url") or "").strip()
    return f"Icon: {text}" + (f" ({licence}" + (f", {url})" if url else ")") if licence else "") + "."


def _rgb(color: str) -> tuple[int, int, int]:
    value = color.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _nearest_palette(color: str, palette: Mapping[str, str]) -> str:
    r, g, b = _rgb(color)
    if max(r, g, b) - min(r, g, b) < 24:  # greys keep their lightness
        return color
    def dist(item: str) -> float:
        pr, pg, pb = _rgb(item)
        return (r - pr) ** 2 * 0.3 + (g - pg) ** 2 * 0.59 + (b - pb) ** 2 * 0.11
    chromatic = [v for k, v in palette.items() if k not in {"ink", "gray", "light", "paper"}]
    return min(chromatic, key=dist)


_HEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")


def recolor_svg(svg: str, mapping: Mapping[str, str] | None = None,
                palette: Mapping[str, str] = PALETTE) -> str:
    """Map an asset's colours onto the shared palette.

    ``mapping`` maps source hex colours (or palette names as targets) explicitly,
    e.g. ``{"#ff0000": "vermilion"}``; colours not listed snap to the nearest
    chromatic palette colour, greys are kept. Only hex colours in attributes and
    inline styles are changed; named CSS colours and gradients' stop colours given
    as hex are included.
    """
    explicit = {k.lower(): palette.get(v, v) for k, v in (mapping or {}).items()}

    def replace(match: re.Match) -> str:
        source = match.group(0).lower()
        if len(source) == 4:
            source = "#" + "".join(ch * 2 for ch in source[1:])
        return explicit.get(source) or _nearest_palette(source, palette)

    return _HEX.sub(replace, svg)


def svg_fragment(asset: str | os.PathLike, *, x: float, y: float, width: float,
                 recolor: Mapping[str, str] | bool | None = False, ident: str | None = None) -> str:
    """Inline an SVG asset as a nested ``<svg>`` at (x, y) scaled to ``width`` user units."""
    text = Path(asset).read_text(encoding="utf-8")
    if recolor:
        text = recolor_svg(text, recolor if isinstance(recolor, Mapping) else None)
    text = re.sub(r"<\?xml[^>]*\?>|<!DOCTYPE[^>]*>", "", text).strip()
    view = re.search(r'viewBox="([^"]+)"', text)
    if not view:
        raise ValueError(f"{asset}: asset SVG needs a viewBox")
    vx, vy, vw, vh = (float(v) for v in view.group(1).replace(",", " ").split())
    height = width * vh / vw
    inner = re.sub(r"^<svg\b[^>]*>|</svg>\s*$", "", text, flags=re.S)
    if ident:  # keep gradient/marker ids unique when an asset is placed twice
        inner = re.sub(r'id="([^"]+)"', lambda m: f'id="{ident}-{m.group(1)}"', inner)
        inner = re.sub(r"url\(#([^)]+)\)", lambda m: f"url(#{ident}-{m.group(1)})", inner)
    return (f'<svg x="{x:g}" y="{y:g}" width="{width:g}" height="{height:g}" '
            f'viewBox="{vx:g} {vy:g} {vw:g} {vh:g}">{inner}</svg>')


def credits(assets: Iterable[str | os.PathLike]) -> list[str]:
    """Credit lines of every attribution-requiring asset used in a figure."""
    lines = []
    for asset in assets:
        meta = asset_license(asset) or {}
        licence = str(meta.get("license") or "").lower().replace(" ", "")
        if "by" in licence and "cc0" not in licence:
            lines.append(credit_line(meta))
    return lines
