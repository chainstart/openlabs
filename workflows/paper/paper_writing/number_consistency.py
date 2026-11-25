"""Number consistency across abstract, body, figure captions and tables (2026-11-25, NC aim).

An author self-check: the same quantity should carry the same value wherever the manuscript
states it. The checker pulls "label + number" statements out of the LaTeX source (for
example ``an AUROC of 0.87``, ``R^2 = 0.81``, ``472 stations``), groups them by label and
reports labels whose values differ between parts of the manuscript.

Findings are advice by default (``severity: advice``). A finding is an ``error`` only when it
is a definite conflict: the identical label of at least ``MIN_LABEL_WORDS`` content words,
the same unit, different values, and no range, comparison or uncertainty wording around
either statement. ``delivery_floor`` reports errors as ``NUMBER-CONFLICT`` (blocking) and the
rest as metrics.

Run: ``python -m paper_writing.number_consistency main.tex``.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

MIN_LABEL_WORDS = 3
CONTEXT = 60
_STOP = frozenset("""a an the of in on for to and or with by from at as is are was were be
we our this that these those which its their than then there here also only all each per
about around approximately nearly roughly""".split())
# Words around a number that mean two different values may legitimately share a label.
_QUALIFIERS = re.compile(
    r"\b(from|to|between|range|ranged|ranging|versus|vs\.?|compared|baseline|than|"
    r"increase[sd]?|decrease[sd]?|rose|fell|drop(?:ped)?|gain(?:ed)?|lower|higher|up to|"
    r"at least|at most|median|mean|interval|CI|±|\\pm|minimum|maximum|before|after|each|"
    r"respectively|per)\b", re.I)
_NUMBER = r"[-−]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[-−]?\d+(?:\.\d+)?"
_UNIT = r"(?:\s*(?:\\,|~)?\s*(%|\\%|percent|K|kpc|Myr|Gyr|GW|MW|kW|TWh|GWh|MWh|kWh|h|s|ms|"\
        r"km|m|cm|mm|kg|g|eV|meV|°C|\\textdegree C|USD|\$|EUR|days?|years?|stations?|sites?|"\
        r"patients?|stars?|samples?|events?|records?|markets?|countries?|cities?))?"
# "<label words> of|= <number><unit>"  and  "<number><unit> <noun words>"
_LABEL_FIRST = re.compile(
    r"((?:[A-Za-z][A-Za-z\-^{}\\$]*\s+){1,6}?)(?:of|=|was|is|reached|equal to|:)\s*\$?\s*("
    + _NUMBER + r")\s*\$?" + _UNIT)
_NUMBER_FIRST = re.compile(r"(?<![\w.])(" + _NUMBER + r")" + _UNIT
                           + r"\s+((?:[a-z][a-z\-]+\s+){0,3}[a-z][a-z\-]+)")


def _strip(tex: str) -> str:
    text = re.sub(r"(?<!\\)%[^\n]*", "", tex)
    text = re.sub(r"\\(?:cite[tp]?|ref|eqref|label|url|href)\*?\{[^}]*\}", " ", text)
    text = re.sub(r"\\(?:textbf|textit|emph|mathrm|text)\{([^}]*)\}", r"\1", text)
    return text


def _sections(tex: str) -> dict[str, str]:
    """``{"abstract", "body", "captions", "tables"}`` text of a LaTeX manuscript."""

    text = _strip(tex)
    abstract = " ".join(re.findall(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", text, re.S))
    tables = " ".join(re.findall(r"\\begin\{tabular\*?\}(.*?)\\end\{tabular\*?\}", text, re.S))
    captions = " ".join(re.findall(r"\\caption\*?\{((?:[^{}]|\{[^{}]*\})*)\}", text, re.S))
    body = re.sub(r"\\begin\{abstract\}.*?\\end\{abstract\}", " ", text, flags=re.S)
    body = re.sub(r"\\begin\{(table|figure)\*?\}.*?\\end\{\1\*?\}", " ", body, flags=re.S)
    body = re.split(r"\\begin\{thebibliography\}|\\bibliography\{", body)[0]
    return {"abstract": abstract, "body": body, "captions": captions, "tables": tables}


def _label(words: str) -> tuple[str, ...]:
    tokens = [w.lower().strip("\\{}$^") for w in re.findall(r"[A-Za-z][A-Za-z\-^{}\\]*", words)]
    return tuple(w for w in tokens if w and w not in _STOP)


def _value(text: str) -> float | None:
    try:
        return float(text.replace(",", "").replace("−", "-"))
    except ValueError:
        return None


def statements(tex: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for part, text in _sections(tex).items():
        if part == "tables":
            continue  # cells carry no labels; tables are compared through captions
        flat = " ".join(text.split())
        for match in _LABEL_FIRST.finditer(flat):
            label = _label(match.group(1))[-4:]
            value = _value(match.group(2))
            if label and value is not None:
                found.append(_item(part, label, value, match.group(3) or "", flat, match))
        for match in _NUMBER_FIRST.finditer(flat):
            label = _label(match.group(3))
            value = _value(match.group(1))
            if label and value is not None and len(label) >= 1:
                found.append(_item(part, label, value, match.group(2) or "", flat, match))
    return found


def _item(part, label, value, unit, flat, match) -> dict[str, Any]:
    start, end = max(0, match.start() - CONTEXT), min(len(flat), match.end() + CONTEXT)
    window = flat[start:end]
    return {"part": part, "label": " ".join(label), "words": len(label), "value": value,
            "unit": unit.replace("\\%", "%").replace("percent", "%"),
            "qualified": bool(_QUALIFIERS.search(window)), "context": window}


def check(tex: str) -> dict[str, Any]:
    """Findings: labels stated with different values in different parts of the manuscript."""

    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in statements(tex):
        groups[(item["label"], item["unit"])].append(item)
    findings = []
    for (label, unit), items in sorted(groups.items()):
        parts = {item["part"] for item in items}
        values = {item["value"] for item in items}
        if len(values) < 2 or len(parts) < 2:
            continue
        exact = (len(label.split()) >= MIN_LABEL_WORDS and not any(
            item["qualified"] for item in items))
        findings.append({
            "label": label, "unit": unit or None, "severity": "error" if exact else "advice",
            "values": [{"part": item["part"], "value": item["value"],
                        "context": item["context"][:160]} for item in items[:6]],
        })
    return {"findings": findings,
            "errors": sum(item["severity"] == "error" for item in findings),
            "advice": sum(item["severity"] == "advice" for item in findings)}


def check_file(path: str | Path) -> dict[str, Any]:
    from .review_flow import expand_tex

    main = Path(path).resolve()
    return check(expand_tex(main, main.parent))


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: python -m paper_writing.number_consistency MAIN.tex", file=sys.stderr)
        return 2
    report = check_file(args[0])
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
