"""Prepare HTML and SVG figure sources for printing (the SVG/HTML schematic route).

Before Chromium prints an ``.html`` or ``.svg`` source, the build writes a prepared copy
in its temporary directory:

* ``<img src="asset:FIELD/NAME.svg">`` (HTML) and ``<image href="asset:...">`` (SVG) are
  replaced by the asset's own vector ``<svg>``, looked up in ``figure-src/assets/`` first
  and then in the shared library (``OPENLABS_FIG_ASSETS``). Ids are prefixed so an asset
  can be placed twice; ``data-recolor`` maps its colours onto the shared palette,
  ``data-stroke`` sets the stroke width of outline icons. Scripts, event handlers and
  external links in an asset are refused.
* ``<img src="inset:NAME">`` is replaced by the SVG that the sidecar's
  ``"insets": {"NAME": "_script.py"}`` matplotlib script writes (``$FIG_OUT`` ends in
  ``.svg``), so a schematic can carry a small result curve drawn from data. The inset keeps
  the size the script drew it at (draw it at its printed size so its text matches the page).
* HTML sources get ``openlabs-fig.css``, the journal profile as CSS variables
  (``--ol-single``, ``--ol-double``, ``--ol-body`` ...) and ``openlabs-fig.js`` (the
  ``.ol-flow`` connectors), plus a ``<base>`` so relative links still resolve.
"""
from __future__ import annotations

import html
import itertools
import re
from pathlib import Path
from typing import Callable, Mapping

ASSET_REF = re.compile(r"asset:([\w./-]+\.svg)")
UNSAFE_SVG = re.compile(r"<script|<foreignObject|\bon[a-z]+\s*=|javascript:|"
                        r"(?:xlink:)?href\s*=\s*[\"'](?!#|data:image/)", re.I)
_IMG = re.compile(r"<img\b([^>]*?)/?>", re.I | re.S)
_IMAGE = re.compile(r"<image\b([^>]*?)(?:/>|>\s*</image>)", re.I | re.S)
_ATTR = re.compile(r"([\w:-]+)\s*=\s*(\"[^\"]*\"|'[^']*')", re.S)


class MarkupError(RuntimeError):
    pass


def attributes(text: str) -> dict[str, str]:
    return {k.lower(): html.unescape(v[1:-1]) for k, v in _ATTR.findall(text)}


def asset_refs(text: str) -> list[str]:
    return ASSET_REF.findall(text)


def svg_problem(text: str) -> str | None:
    if "<svg" not in text:
        return "not an SVG document"
    match = UNSAFE_SVG.search(text)
    return f"unsafe content {match.group(0)!r}" if match else None


def profile_css(profile: Mapping[str, float | None]) -> str:
    widths = {k: profile.get(k) for k in ("single", "onehalf", "double")}
    if not widths["onehalf"]:
        widths["onehalf"] = round(((widths["single"] or 88) + (widths["double"] or 180)) / 2, 1)
    lines = [f"--ol-{k}: {v}mm;" for k, v in widths.items() if v]
    lines += [f"--ol-{k}: {profile[k]}pt;" for k in ("body", "small", "panel", "line", "axis") if profile.get(k)]
    return ":root{" + "".join(lines) + "}"


def _svg_root(text: str, label: str) -> tuple[str, str, str]:
    """(root attributes, inner markup, viewBox) of an SVG document."""
    text = re.sub(r"<\?xml[^>]*\?>|<!DOCTYPE[^>]*>|<!--.*?-->", "", text, flags=re.S).strip()
    match = re.search(r"<svg\b([^>]*)>(.*)</svg>\s*$", text, re.S)
    if not match:
        raise MarkupError(f"{label}: no <svg> root")
    root, inner = match.groups()
    attrs = attributes(root)
    view = attrs.get("viewbox")
    if not view:
        w, h = (re.sub(r"[a-z%]+$", "", attrs.get(k, "")) for k in ("width", "height"))
        if not (w and h):
            raise MarkupError(f"{label}: an inlined SVG needs a viewBox or width and height")
        view = f"0 0 {w} {h}"
    return root, inner, view


_counter = itertools.count(1)
_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")


def inline_styles(inner: str, label: str) -> str:
    """Move ``<style>`` class rules (``.cls-1{fill:#fff}``, as Illustrator and Inkscape write
    them) onto the elements' ``style`` attributes, so an inlined asset cannot restyle the page."""
    rules: dict[str, str] = {}
    for block in re.findall(r"<style[^>]*>(.*?)</style>", inner, flags=re.S | re.I):
        block = re.sub(r"/\*.*?\*/|<!\[CDATA\[|\]\]>", "", block, flags=re.S)
        for selectors, body in _RULE.findall(block):
            for selector in selectors.split(","):
                selector = selector.strip()
                if selector == "*":
                    continue
                if not re.fullmatch(r"\.[\w-]+", selector):
                    raise MarkupError(f"{label}: <style> selector {selector!r} is not a plain class; "
                                      "simplify the asset first")
                rules[selector[1:]] = rules.get(selector[1:], "") + body.strip().rstrip(";") + ";"
    inner = re.sub(r"<style[^>]*>.*?</style>", "", inner, flags=re.S | re.I)
    if not rules:
        return inner

    def apply(match: re.Match) -> str:
        tag = match.group(0)
        classes = re.search(r'\bclass="([^"]*)"', tag)
        if not classes:
            return tag
        css = "".join(rules.get(c, "") for c in classes.group(1).split())
        if not css:
            return tag
        if re.search(r'\bstyle="', tag):
            return re.sub(r'\bstyle="([^"]*)"', lambda m: f'style="{css}{m.group(1)}"', tag, count=1)
        return tag[:-2] + f' style="{css}"/>' if tag.endswith("/>") else tag[:-1] + f' style="{css}">'

    return re.sub(r"<[a-zA-Z][^<>]*>", apply, inner)



def inline_svg(text: str, *, label: str, attrs: Mapping[str, str], recolor: Callable[[str], str] | None = None,
               stroke: str | None = None, keep_size: bool = False) -> str:
    """An asset or inset as an inline ``<svg>`` carrying the placement attributes."""
    problem = svg_problem(text)
    if problem:
        raise MarkupError(f"{label}: {problem}")
    if recolor is not None:
        text = recolor(text)
    root, inner, view = _svg_root(text, label)
    root_attrs = attributes(root)
    ident = f"ol{next(_counter)}"
    inner = re.sub(r'\bid="([^"]+)"', lambda m: f'id="{ident}-{m.group(1)}"', inner)
    inner = re.sub(r"url\(#([^)]+)\)", lambda m: f"url(#{ident}-{m.group(1)})", inner)
    inner = re.sub(r'((?:xlink:)?href)="#([^"]+)"', lambda m: f'{m.group(1)}="#{ident}-{m.group(2)}"', inner)
    # embedded <style> rules would restyle the whole page: move class rules onto the elements
    # (matplotlib's own "*{stroke-linejoin:round}" rule is dropped)
    inner = inline_styles(inner, label)
    keep = {k: v for k, v in root_attrs.items()
            if k in {"fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "fill-rule"}
            or (keep_size and k in {"width", "height"})}
    if stroke and "stroke" in keep:
        keep["stroke-width"] = stroke
    if "fill" not in keep and "stroke" not in keep:
        keep["fill"] = "currentColor"  # Material-style icons: single filled path, colour from CSS
    placed = {k: v for k, v in attrs.items() if k not in {"src", "href", "xlink:href", "alt", "data-recolor",
                                                         "data-stroke"}}
    out = {**keep, **placed, "viewBox": view, "xmlns": "http://www.w3.org/2000/svg"}
    if attrs.get("alt"):
        out["aria-label"] = attrs["alt"]
    rendered = " ".join(f'{k}="{html.escape(str(v), quote=True)}"' for k, v in out.items())
    return f"<svg {rendered}>{inner}</svg>"


def prepare(source: Path, *, tmp: Path, find_asset: Callable[[str], Path], style_dir: Path,
            profile: Mapping[str, float | None], insets: Mapping[str, Path] | None = None,
            recolor: Callable[[str, Mapping[str, str] | None], str] | None = None) -> Path:
    """Write the prepared copy of ``source`` into ``tmp`` and return its path."""
    text = re.sub(r"<!--.*?-->", "", source.read_text(encoding="utf-8"), flags=re.S)  # comments are notes
    insets = insets or {}
    is_html = source.suffix.lower() in (".html", ".htm")

    def resolve(ref: str, attrs: Mapping[str, str]) -> str | None:
        label = f"{source.name}: {ref}"
        if ref.startswith("asset:"):
            path = find_asset(ref[len("asset:"):])
        elif ref.startswith("inset:"):
            name = ref[len("inset:"):]
            if name not in insets:
                raise MarkupError(f"{label}: no inset {name!r} (declare it in the sidecar's \"insets\")")
            path = insets[name]
        else:
            return None
        mapping = None
        colour = attrs.get("data-recolor")
        if colour and recolor is not None:
            pairs = dict(item.split("=", 1) for item in colour.split(",") if "=" in item)
            mapping = (lambda svg: recolor(svg, pairs or None))
        return inline_svg(path.read_text(encoding="utf-8"), label=label, attrs=attrs, recolor=mapping,
                          stroke=attrs.get("data-stroke"), keep_size=ref.startswith("inset:"))

    def replace_img(match: re.Match) -> str:
        attrs = attributes(match.group(1))
        return resolve(attrs.get("src", ""), attrs) or match.group(0)

    def replace_image(match: re.Match) -> str:
        attrs = attributes(match.group(1))
        ref = attrs.get("href") or attrs.get("xlink:href") or ""
        if not ref.startswith(("asset:", "inset:")):
            return match.group(0)
        placement = {k: attrs[k] for k in ("x", "y", "width", "height", "class", "style", "transform",
                                           "preserveaspectratio", "data-recolor", "data-stroke", "color")
                     if k in attrs}
        if "preserveaspectratio" in placement:
            placement["preserveAspectRatio"] = placement.pop("preserveaspectratio")
        return resolve(ref, placement) or match.group(0)

    text = _IMG.sub(replace_img, text)
    text = _IMAGE.sub(replace_image, text)
    if is_html:
        css = (style_dir / "openlabs-fig.css").read_text(encoding="utf-8")
        js = (style_dir / "openlabs-fig.js").read_text(encoding="utf-8")
        base = html.escape(source.parent.resolve().as_uri() + "/", quote=True)
        head = (f'<base href="{base}"><style>{css}\n{profile_css(profile)}</style>')
        tail = f"<script>{js}</script>"
        if re.search(r"<head[^>]*>", text, re.I):
            text = re.sub(r"(<head[^>]*>)", lambda m: m.group(1) + head, text, count=1, flags=re.I)
        else:
            text = head + text
        if re.search(r"</body>", text, re.I):
            text = re.sub(r"</body>", lambda m: tail + m.group(0), text, count=1, flags=re.I)
        else:
            text += tail
    target = tmp / ("figure-prepared" + source.suffix.lower())
    target.write_text(text, encoding="utf-8")
    return target
