"""Narrative and length checks for the main text of a manuscript.

Single-object papers grew to 44 pages and 15,000 words because every review round and
formal check asked for one more qualification and nothing ever asked for a cut. These
deterministic counts make the symptoms visible and give the writer line numbers:

* main-text length against generic length guidance and the recorded venue limit;
* revision-history narration ("in the previous version", "经复核后") anywhere in the
  scientific text (warning);
* abstract length, the number of numbers, test statistics and parenthetical qualifiers
  in it (warnings);
* hedging density, sentences with stacked qualifiers, conclusion sentences with more than
  one layer of qualification, and empty transitions (warnings).

The counts are heuristics, not a prose score. The writing rules they support are in
``skills/openlabs-paper-readability/SKILL.md``. Limits resolve, from weakest to strongest:
code defaults, the article type, ``registry/settings.yaml#quality_gate.narrative``, the
research line (``research-lines.yaml`` ``lines[].paper_narrative``) and the paper record
(``narrative_limits``).
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

# --------------------------------------------------------------------------- limits

DEFAULT_LIMITS: dict[str, Any] = {
    # Main text = from the end of the abstract to the first appendix, back-matter heading or
    # bibliography; captions count, tables, displayed mathematics and declarations do not.
    "max_body_words": 7000,
    # Estimated pages (words / words_per_page + floats * pages_per_float). Off unless set.
    "max_body_pages": None,
    "words_per_page": 550,
    "pages_per_float": 0.35,
    # Chinese text: characters per English-word equivalent.
    "cjk_chars_per_word": 1.7,
    "abstract_max_words": 250,
    "abstract_max_numbers": 10,
    "abstract_max_parentheticals": 3,
    "abstract_max_test_statistics": 0,
    "hedges_per_1000_words": 4.0,
    "fillers_per_1000_words": 1.5,
    # A sentence with this many qualifier markers or more is "stacked".
    "sentence_max_qualifiers": 4,
    "max_stacked_sentences": 5,
    # Distinct layers of qualification (hedge, scope restriction, concession, aside)
    # allowed in a conclusion sentence.
    "conclusion_max_layers": 1,
    "max_overqualified_conclusions": 2,
    # Relative main-text growth over the last reviewed snapshot that is tolerated.
    "body_growth_tolerance": 0.02,
    # Promote every warning to a failure (the hard checks always fail).
    "warnings_blocking": False,
}

# Article-type defaults. ``letter``/``short`` and ``conference`` are tighter, a review or a
# mathematics paper longer. Venue limits recorded for a paper override these.
ARTICLE_TYPE_LIMITS: dict[str, dict[str, Any]] = {
    "article": {},
    "letter": {"max_body_words": 3500, "abstract_max_words": 150, "abstract_max_numbers": 6},
    "conference": {"max_body_words": 6500, "abstract_max_words": 200},
    "review": {"max_body_words": 12000, "abstract_max_words": 300},
    "math": {"max_body_words": 14000, "abstract_max_numbers": 6},
}

HARD_CODES = frozenset({"NARRATIVE-BODY-LENGTH", "NARRATIVE-BODY-PAGES"})


def article_type(metadata: Mapping[str, Any]) -> str:
    """The limit family of a paper: explicit, else from the venue type, article type, domain."""
    explicit = str(metadata.get("narrative_article_type") or "").strip().lower()
    if explicit in ARTICLE_TYPE_LIMITS:
        return explicit
    if str(metadata.get("venue_type") or "") == "conference":
        return "conference"
    kind = " ".join(str(metadata.get(key) or "") for key in
                    ("target_journal_article_type", "article_type")).lower()
    if re.search(r"\b(?:letter|short communication|brief|rapid communication|note)\b", kind):
        return "letter"
    if re.search(r"\breview\b", kind):
        return "review"
    if str(metadata.get("domain") or "").lower() in {"math", "mathematics"}:
        return "math"
    return "article"


def _known(values: Any) -> dict[str, Any]:
    if not isinstance(values, Mapping):
        return {}
    return {key: value for key, value in values.items() if key in DEFAULT_LIMITS}


def resolve_limits(
    metadata: Mapping[str, Any] | None = None,
    *,
    settings: Mapping[str, Any] | None = None,
    line: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Merged limits and the list of layers that contributed (for the report)."""
    metadata = metadata or {}
    kind = article_type(metadata)
    limits = dict(DEFAULT_LIMITS)
    sources = ["defaults"]
    if ARTICLE_TYPE_LIMITS.get(kind):
        limits.update(ARTICLE_TYPE_LIMITS[kind])
    sources.append(f"article_type:{kind}")
    config = ((settings or {}).get("quality_gate") or {}).get("narrative") if settings else None
    if isinstance(config, Mapping):
        if _known(config):
            limits.update(_known(config))
            sources.append("settings.quality_gate.narrative")
        types = config.get("article_types")
        if isinstance(types, Mapping) and _known(types.get(kind)):
            limits.update(_known(types.get(kind)))
            sources.append(f"settings.quality_gate.narrative.article_types.{kind}")
    if line and _known(line.get("paper_narrative")):
        limits.update(_known(line.get("paper_narrative")))
        sources.append(f"research_line:{line.get('id')}")
    if _known(metadata.get("narrative_limits")):
        limits.update(_known(metadata.get("narrative_limits")))
        sources.append("paper.narrative_limits")
    limits["body_limit_binding"] = "max_body_words" in _known(metadata.get("narrative_limits"))
    return limits, sources


# --------------------------------------------------------------------------- source mapping


@dataclass(frozen=True)
class SourceLine:
    path: str
    line: int
    text: str


_INPUT = re.compile(r"\\(?:input|include|subfile)\s*\{([^}]+)\}")


def _strip_comment(line: str) -> str:
    for index, char in enumerate(line):
        if char == "%":
            slashes = len(line[:index]) - len(line[:index].rstrip("\\"))
            if slashes % 2 == 0:
                return line[:index]
    return line


def flatten_tex(main_tex: Path, manuscript: Path | None = None) -> list[SourceLine]:
    """Inline ``\\input`` files, keeping the source path and line of every output line."""
    manuscript = (manuscript or main_tex.parent).resolve()
    seen: set[Path] = set()
    out: list[SourceLine] = []

    def label(path: Path) -> str:
        try:
            return path.relative_to(manuscript).as_posix()
        except ValueError:
            return path.name

    def visit(path: Path) -> None:
        resolved = path.resolve()
        if resolved in seen or not resolved.is_file():
            return
        seen.add(resolved)
        for number, raw in enumerate(resolved.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            text = _strip_comment(raw)
            cursor = 0
            for match in _INPUT.finditer(text):
                before = text[cursor:match.start()]
                if before.strip():
                    out.append(SourceLine(label(resolved), number, before))
                target = manuscript / match.group(1).strip()
                if target.suffix == "":
                    target = target.with_suffix(".tex")
                visit(target)
                cursor = match.end()
            rest = text[cursor:]
            if cursor == 0 or rest.strip():
                out.append(SourceLine(label(resolved), number, rest))

    visit(main_tex)
    return out


def lines_from_text(text: str, path: str = "manuscript-expanded.tex") -> list[SourceLine]:
    return [SourceLine(path, number, _strip_comment(raw)) for number, raw in enumerate(text.splitlines(), 1)]


class _Doc:
    """The flattened document as one string with an offset -> source-line map."""

    def __init__(self, lines: list[SourceLine]):
        self.lines = lines
        self.starts: list[int] = []
        parts: list[str] = []
        offset = 0
        for item in lines:
            self.starts.append(offset)
            parts.append(item.text)
            offset += len(item.text) + 1
        self.text = "\n".join(parts)

    def where(self, offset: int) -> tuple[str, int]:
        index = max(0, bisect.bisect_right(self.starts, offset) - 1)
        if not self.lines:
            return "", 0
        return self.lines[index].path, self.lines[index].line


# --------------------------------------------------------------------------- regions


def _balanced(text: str, open_at: int) -> int:
    """Offset after the brace group starting at ``open_at`` (which holds ``{``)."""
    depth = 0
    index = open_at
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return len(text)


_ABSTRACT_ENV = re.compile(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", re.S)
_ABSTRACT_CMD = re.compile(r"\\abstract\s*\{")
_BACK_MATTER_HEAD = (
    r"\\(?:section|chapter)\*?\s*\{\s*(?:Statements? and Declarations|Declarations?\b|Data (?:and code )?"
    r"availability|Code availability|Acknowledge?ments?|Funding|Author contributions|CRediT|Competing interests"
    r"|Conflicts? of interest|References|Supplementary (?:material|information)|致谢|参考文献|附录)"
    r"|\\bibliography\s*\{|\\printbibliography\b|\\begin\{thebibliography\}|\\bmhead\s*\{|\\end\{document\}")
_BODY_END = re.compile(r"\\appendix\b|\\begin\{appendices\}|\\backmatter\b|" + _BACK_MATTER_HEAD, re.I)
_APPENDIX_END = re.compile(r"\\end\{appendices\}|\\backmatter\b|" + _BACK_MATTER_HEAD, re.I)
_DECLARATION_HEAD = re.compile(
    r"\\(?:sub)*section\*?\s*\{[^}]*(?:generative\s+AI|AI[- ]use|AI-assisted)[^}]*\}", re.I)
_SECTIONING = re.compile(r"\\(?:chapter|section|subsection|subsubsection|paragraph)\*?\s*[\[{]")
_SECTION_TITLE = re.compile(r"\\(?:chapter|section|subsection)\*?\s*\{([^{}]*)\}")


@dataclass
class Regions:
    abstract: tuple[int, int] | None
    body: tuple[int, int]
    appendix: tuple[int, int] | None


def find_regions(text: str) -> Regions:
    abstract = None
    match = _ABSTRACT_ENV.search(text)
    if match:
        abstract = (match.start(1), match.end(1))
    else:
        match = _ABSTRACT_CMD.search(text)
        if match:
            end = _balanced(text, match.end() - 1)
            abstract = (match.end(), end - 1)
    start_candidates = [0]
    begin = text.find("\\begin{document}")
    if begin >= 0:
        start_candidates.append(begin + len("\\begin{document}"))
    if abstract:
        start_candidates.append(abstract[1])
    title = text.find("\\maketitle")
    if title >= 0:
        start_candidates.append(title + len("\\maketitle"))
    start = max(start_candidates)
    end_match = _BODY_END.search(text, start)
    end = end_match.start() if end_match else len(text)
    appendix = None
    marker = re.compile(r"\\appendix\b|\\begin\{appendices\}").search(text, end)
    if marker:
        a_start = marker.end()
        a_end_match = _APPENDIX_END.search(text, a_start)
        appendix = (a_start, a_end_match.start() if a_end_match else len(text))
    return Regions(abstract, (start, end), appendix)


# --------------------------------------------------------------------------- cleaning

_MATH_ENVS = ("equation", "align", "gather", "multline", "eqnarray", "displaymath", "math", "split",
              "alignat", "flalign")
_DROP_ENVS = ("tabular", "tabularx", "tabular*", "longtable", "array", "lstlisting", "verbatim",
              "algorithmic", "tikzpicture")
_DROP_COMMANDS = re.compile(
    r"\\(?:cite[a-zA-Z]*|ref|eqref|autoref|cref|Cref|label|url|href|includegraphics|bibliographystyle"
    r"|newcommand|renewcommand|def|usepackage|documentclass|setlength|hypersetup)\*?"
    r"(?:\s*\[[^\]]*\])*")


def _blank(chars: list[str], start: int, end: int) -> None:
    for index in range(max(0, start), min(len(chars), end)):
        if chars[index] != "\n":
            chars[index] = " "


def clean_prose(text: str) -> str:
    """Same-length copy of ``text`` with markup, mathematics and tables blanked out.

    Keeping offsets lets every finding be mapped back to its source line.
    """
    chars = list(text)
    # Headings are not prose: blank them and break the sentence there.
    for match in re.finditer(r"\\(?:chapter|section|subsection|subsubsection|paragraph|bmhead)\*?\s*\{", text):
        end = _balanced(text, match.end() - 1)
        _blank(chars, match.start(), end)
        chars[match.start()] = "\n"
        if end - 1 > match.start():
            chars[end - 1] = "\n"
    for env in (*_MATH_ENVS, *_DROP_ENVS):
        name = re.escape(env)
        for match in re.finditer(rf"\\begin\{{{name}\*?\}}.*?\\end\{{{name}\*?\}}", text, re.S):
            _blank(chars, match.start(), match.end())
    for pattern in (r"\$\$.*?\$\$", r"\\\[.*?\\\]", r"\\\(.*?\\\)", r"(?<!\\)\$(?:\\\$|[^$])+?(?<!\\)\$"):
        for match in re.finditer(pattern, "".join(chars), re.S):
            # Inline mathematics reads as one token; keep a placeholder so sentences survive.
            _blank(chars, match.start(), match.end())
            if match.end() - match.start() >= 1:
                chars[match.start()] = "X"
    current = "".join(chars)
    for match in _DROP_COMMANDS.finditer(current):
        end = match.end()
        if end < len(current) and current[end] == "{":
            end = _balanced(current, end)
        _blank(chars, match.start(), end)
    current = "".join(chars)
    for match in re.finditer(r"\\(?:begin|end)\s*\{[^}]*\}(?:\s*\[[^\]]*\])?", current):
        _blank(chars, match.start(), match.end())
    current = "".join(chars)
    for match in re.finditer(r"\\[A-Za-z@]+\*?|\\[^A-Za-z]", current):
        token = match.group(0)
        if token in {"\\%", "\\&", "\\_", "\\#"}:
            chars[match.start()] = " "
            continue
        _blank(chars, match.start(), match.end())
    for index, char in enumerate(chars):
        if char in "{}~":
            chars[index] = " "
    return "".join(chars)


_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z'’\-]*|\d+(?:[.,]\d+)*")
_CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")


def count_words(prose: str, cjk_chars_per_word: float = 1.7) -> dict[str, Any]:
    latin = len(_LATIN_WORD.findall(prose))
    cjk = len(_CJK.findall(prose))
    return {"latin_words": latin, "cjk_chars": cjk,
            "words": int(round(latin + cjk / max(cjk_chars_per_word, 0.1)))}


# --------------------------------------------------------------------------- lexicons

HEDGES_EN = re.compile(
    r"\b(?:may|might|could|possibly|perhaps|plausibl[ey]|presumably|apparently|tentative(?:ly)?"
    r"|suggests?|suggestive(?: of)?|appears? to|seems? to|is likely|are likely|unlikely"
    r"|cannot be (?:excluded|ruled out)|can(?:not|'t) exclude|do(?:es)? not (?:exclude|rule out|establish"
    r"|imply|prove|show|demonstrate|guarantee)|not (?:necessarily|conclusive(?:ly)?)|to (?:some|a certain)"
    r" extent|in principle|we do not claim|should not be (?:read|interpreted)|heuristic(?:ally)?"
    r"|not a calibrated|not an independent)\b",
    re.I,
)
HEDGES_ZH = re.compile(
    r"可能|或许|也许|似乎|大概|初步|尚(?:不能|无法|不足以)|不能排除|无法排除|并不(?:意味着|表明|说明|证明)"
    r"|在一定程度上|倾向于|推测|疑似|不宜(?:解读|理解)为")
SCOPE_EN = re.compile(
    r"\b(?:only|alone|within (?:the|this|these|our)\b|in the [\w-]+(?: [\w-]+)? (?:we )?(?:tested|considered"
    r"|examined|explored|sampled|studied)|under the assumptions?|assuming|provided that|unless"
    r"|at the [\w.\-]+ (?:level|resolution|precision)|to the precision of|for the (?:adopted|chosen|present)"
    r"|in (?:all|every|each) (?:of the )?[\w-]+)\b",
    re.I,
)
SCOPE_ZH = re.compile(r"仅|只(?:在|有|对)|在(?:本文|所|我们)(?:考察|测试|研究|检验)的|假设|前提下|范围内|条件下")
CONCESSION_EN = re.compile(r"\b(?:although|though|whereas|however|but|even if|nevertheless|nonetheless)\b", re.I)
CONCESSION_ZH = re.compile(r"虽然|尽管|但是|然而|不过")
# A parenthetical aside: at least two real words (math placeholders and panel labels excluded).
ASIDE = re.compile(r"\((?=(?:[^()]*?\b[A-Za-z]{3,}\b){2})[^()]{6,}\)|（[^（）]{4,}）")

FILLERS_EN = re.compile(
    r"\b(?:it is worth (?:noting|mentioning)(?: that)?|it should be (?:noted|emphasi[sz]ed|stressed)(?: that)?"
    r"|it is important to (?:note|stress|emphasi[sz]e)(?: that)?|notably|importantly|interestingly"
    r"|remarkably|crucially|in summary|to summari[sz]e|in conclusion|taken together|overall"
    r"|all in all|needless to say|as (?:mentioned|noted|discussed|stated|shown) (?:above|earlier|before"
    r"|previously)|in this (?:context|regard)|it is (?:clear|evident|obvious) that|moreover|furthermore"
    r"|additionally|in addition)\b",
    re.I,
)
FILLERS_ZH = re.compile(
    r"值得注意的是|需要指出的是|需要注意的是|值得一提的是|综上所述|总而言之|总的来说|总之|不难看出"
    r"|显而易见|众所周知|毋庸置疑|此外|另外|与此同时|进一步地|更重要的是")

REVISION_EN = re.compile(
    r"\b(?:in|from|of|than|since) (?:the|our|a|an) (?:previous|earlier|prior|original|first|last)"
    r" (?:draft|submission|revision|round|manuscript|version of (?:this|the|our) (?:paper|manuscript|article"
    r"|work|study|analysis))\b"
    r"|(?<!writing -- )(?<!writing - )(?<!writing – )\b(?:previous|earlier|prior|original) (?:draft|submission|revision)s?\b"
    r"|\b(?:this|the present|the current) revision\b"
    r"|\brevised (?:manuscript|version|draft|submission)\b"
    r"|\b(?:after|upon|on|following) (?:a )?(?:re-?examination|re-?checking|re-?inspection|re-?analysis"
    r"|re-?evaluation|further checks?|closer inspection|re-?verification)\b"
    r"|\b(?:as )?(?:requested|suggested|pointed out|noted|raised|asked) by (?:the |an |one |a )?"
    r"(?:anonymous )?(?:referees?|reviewers?|editors?)\b"
    r"|\bthe (?:referee|reviewer|editor)'?s? (?:comments?|suggestions?|requests?|concerns?)\b"
    r"|\bwe (?:have now|now have|now) (?:added|revised|corrected|removed|replaced|updated|rewritten|rewrote"
    r"|recomputed|re-?ran|re-?run|clarified|expanded|extended|included)\b"
    r"|\b(?:was|were|has been|have been) (?:corrected|revised|updated|changed) (?:from|since)\b"
    r"|\b(?:previously|earlier) (?:reported|quoted|stated|adopted|given) (?:here|in this (?:paper|work"
    r"|manuscript|study))\b"
    r"|\b(?:this|the present|the current) version (?:of the (?:paper|manuscript) )?(?:now )?(?:adds|includes"
    r"|replaces|corrects)\b"
    r"|\b(?:had|have|has) (?:previously|earlier|originally|initially) been (?:excluded|included|adopted|used"
    r"|computed|fitted|assumed|discarded|rejected|quoted)\b"
    r"|\b(?:replac(?:e|es|ed|ing)|supersed(?:e|es|ed|ing)) (?:the|our) (?:earlier|previous|original|initial|old)"
    r" (?:analysis|solution|values?|results?|fits?|profiles?|estimates?|points?|version)\b"
    r"|\b(?:was|were) (?:initially|originally) (?:computed|fitted|adopted|used|excluded|reported)\b"
    r"|\bno longer (?:used|adopted|included|needed|required|reported)\b",
    re.I,
)
REVISION_ZH = re.compile(
    r"上一?版|上一稿|前一(?:版|稿)|此前(?:的)?版本|原稿|初稿中|修订(?:稿|版)|(?:本|此)次修订|经(?:过)?复核"
    r"|复核后|重新核查|经重新(?:计算|分析|核对)|根据审稿(?:人|意见)|按审稿|审稿人(?:指出|建议|要求)|评审意见"
    r"|回复审稿")

TEST_STATISTICS = re.compile(
    r"\\Delta\s*\\?ln\s*\\?(?:mathcal\s*)?\{?L|\\Delta\s*\\chi|\\chi\s*\^\s*\{?2|Δ\s*ln\s*L|(?-i:\bp)\s*[<≤]"
    r"|\bp-values?\b|\bAIC\b|\bBIC\b|\bBayes factors?\b|\blikelihoods?\b|\bposteriors?\b|\bMCMC\b"
    r"|Markov chain Monte Carlo|\bbootstrap\b|显著性水平|似然|后验",
    re.I,
)
CONCLUSION_CUE = re.compile(
    r"\b(?:we (?:find|found|show|showed|conclude|demonstrate|establish|obtain|derive)|our (?:results?|analysis"
    r"|findings?) (?:show|indicate|demonstrate|suggest|establish)|(?:this|the present) (?:paper|work|study)"
    r" (?:shows|demonstrates|establishes|finds)|(?:the )?results? (?:show|indicate|demonstrate|establish))\b"
    r"|表明|结果显示|我们发现|本文(?:证明|发现|表明)|结论是",
    re.I,
)
ABBREVIATIONS = re.compile(
    r"(?:\b(?:e\.g|i\.e|cf|vs|al|Fig|Figs|Eq|Eqs|Sect|Sects|Sec|Ref|Refs|Tab|No|approx|ca|resp|etc|Dr|Mr|Ms"
    r"|St|Vol|pp|Ch|Chap|Appx|App)\.|\b[A-Z]\.)$")


@dataclass
class Sentence:
    start: int
    end: int
    text: str


def split_sentences(prose: str, start: int, end: int) -> list[Sentence]:
    out: list[Sentence] = []
    cursor = start
    pattern = re.compile(r"[.!?](?=\s)|[。！？；]|\n\s*\n")
    def add(a: int, b: int) -> None:
        piece = prose[a:b]
        if piece.strip():
            # The sentence starts at its first visible character (markup is blanked).
            first = a + (len(piece) - len(piece.lstrip()))
            out.append(Sentence(first, b, " ".join(piece.split())))

    for match in pattern.finditer(prose, start, end):
        if match.group(0) == "." and ABBREVIATIONS.search(prose[max(cursor, match.start() - 8):match.end()]):
            continue
        add(cursor, match.end())
        cursor = match.end()
    add(cursor, end)
    return out


def _qualifiers(text: str) -> dict[str, int]:
    return {
        "hedge": len(HEDGES_EN.findall(text)) + len(HEDGES_ZH.findall(text)),
        "scope": len(SCOPE_EN.findall(text)) + len(SCOPE_ZH.findall(text)),
        "concession": len(CONCESSION_EN.findall(text)) + len(CONCESSION_ZH.findall(text)),
        "aside": len(ASIDE.findall(text)),
    }


def _macros(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for match in re.finditer(r"\\(?:newcommand|renewcommand|providecommand)\*?\s*\{?\\([A-Za-z@]+)\}?\s*\{", text):
        end = _balanced(text, match.end() - 1)
        found[match.group(1)] = text[match.end():end - 1]
    for match in re.finditer(r"\\def\s*\\([A-Za-z@]+)\s*\{", text):
        end = _balanced(text, match.end() - 1)
        found[match.group(1)] = text[match.end():end - 1]
    return found


def _expand_macros(text: str, macros: Mapping[str, str]) -> str:
    for _ in range(3):
        text = re.sub(r"\\([A-Za-z@]+)(?![A-Za-z@])",
                      lambda m: macros[m.group(1)] if m.group(1) in macros and len(macros[m.group(1)]) < 80
                      and "#" not in macros[m.group(1)] else m.group(0), text)
    return text


# A number in running text or mathematics; sub- and superscript indices are not numbers.
_NUMBER = re.compile(r"(?<![A-Za-z\d._^{])\d+(?:[.,]\d+)*(?:\(\d+\))?")


# --------------------------------------------------------------------------- analysis


def _hit(doc: _Doc, offset: int, code: str, message: str, excerpt: str = "") -> dict[str, Any]:
    path, line = doc.where(offset)
    item: dict[str, Any] = {"code": code, "message": message, "path": path, "line": line}
    if excerpt:
        item["context"] = excerpt[:300]
    return item


def _excerpt(prose: str, start: int, end: int, pad: int = 60) -> str:
    return " ".join(prose[max(0, start - pad):min(len(prose), end + pad)].split())


def _section_titles(text: str, start: int, end: int) -> list[tuple[int, str]]:
    return [(m.start(), m.group(1)) for m in _SECTION_TITLE.finditer(text, start, end)]


def analyze(lines: list[SourceLine], limits: Mapping[str, Any] | None = None, *,
            previous_body_words: int | None = None, previous_source: str | None = None,
            main_text_growth_requested: bool = False) -> dict[str, Any]:
    """Run every narrative check on a flattened manuscript."""
    config = {**DEFAULT_LIMITS, **dict(limits or {})}
    # Short argument-free user macros (value macros such as \qAdopt, names such as \TESS) are
    # expanded line by line so numbers and words count; source locations stay unchanged.
    macros = _macros("\n".join(item.text for item in lines))
    definition = re.compile(r"\\(?:newcommand|renewcommand|providecommand|def)\b")
    lines = [item if definition.search(item.text) else
             SourceLine(item.path, item.line, _expand_macros(item.text, macros)) for item in lines]
    doc = _Doc(lines)
    text = doc.text
    regions = find_regions(text)
    prose = clean_prose(text)
    body_start, body_end = regions.body

    # Declarations inside the body (for example an AI-use subsection in Methods) do not count.
    excluded: list[tuple[int, int]] = []
    for match in _DECLARATION_HEAD.finditer(text, body_start, body_end):
        nxt = _SECTIONING.search(text, match.end(), body_end)
        excluded.append((match.start(), nxt.start() if nxt else body_end))
    body_prose = list(prose[body_start:body_end])
    for a, b in excluded:
        _blank(body_prose, a - body_start, b - body_start)
    body_text = "".join(body_prose)
    ratio = float(config["cjk_chars_per_word"])
    body_count = count_words(body_text, ratio)
    floats = len(re.findall(r"\\begin\{(?:figure|table|sidewaystable|sidewaysfigure)\*?\}",
                            text[body_start:body_end]))
    est_pages = round(body_count["words"] / float(config["words_per_page"])
                      + floats * float(config["pages_per_float"]), 1)
    appendix_words = (count_words(prose[regions.appendix[0]:regions.appendix[1]], ratio)["words"]
                      if regions.appendix else 0)
    sections = []
    titles = _section_titles(text, body_start, body_end)
    for index, (offset, title) in enumerate(titles):
        stop = titles[index + 1][0] if index + 1 < len(titles) else body_end
        words = count_words(body_text[offset - body_start:stop - body_start], ratio)["words"]
        path, line = doc.where(offset)
        sections.append({"title": " ".join(title.split()), "words": words, "path": path, "line": line})

    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    biggest = ", ".join(f"{s['title']} ({s['words']})" for s in sorted(sections, key=lambda s: -s["words"])[:4])
    limit = config.get("max_body_words")
    if limit and body_count["words"] > int(limit):
        findings = errors if config.get("body_limit_binding") else warnings
        findings.append(_hit(doc, body_start, "NARRATIVE-BODY-LENGTH",
                           f"main text has {body_count['words']} words, limit {int(limit)} "
                           f"({body_count['words'] - int(limit)} over). Keep the problem-method-experiment-"
                           "result line in the main text and move robustness checks, numerical-resolution "
                           "tests, item-by-item sensitivity analyses, secondary comparisons and long "
                           "derivations to the appendix or supplement, each replaced by one sentence with a "
                           f"reference. Largest sections: {biggest}."))
    page_limit = config.get("max_body_pages")
    if page_limit and est_pages > float(page_limit):
        errors.append(_hit(doc, body_start, "NARRATIVE-BODY-PAGES",
                           f"main text is about {est_pages} pages ({body_count['words']} words, {floats} "
                           f"figures/tables), limit {page_limit}; move secondary figures, tables and checks "
                           "to the appendix or supplement."))

    # Revision history: anywhere in abstract, body and appendix.
    scan_ranges = [regions.body]
    if regions.abstract:
        scan_ranges.append(regions.abstract)
    if regions.appendix:
        scan_ranges.append(regions.appendix)
    revision_hits = []
    for a, b in scan_ranges:
        for pattern in (REVISION_EN, REVISION_ZH):
            for match in pattern.finditer(prose, a, b):
                revision_hits.append(_hit(doc, match.start(), "NARRATIVE-REVISION-HISTORY",
                                          f"revision-history wording \"{match.group(0)}\": describe the "
                                          "current result as it stands; the history of the analysis and "
                                          "answers to reviewers belong in the response letter",
                                          _excerpt(prose, match.start(), match.end())))
    warnings.extend(sorted(revision_hits, key=lambda h: (h["path"], h["line"])))

    # Abstract.
    abstract: dict[str, Any] | None = None
    if regions.abstract:
        a, b = regions.abstract
        raw = _expand_macros(text[a:b], _macros(text[:body_start] + text))
        abstract_prose = prose[a:b]
        words = count_words(abstract_prose, ratio)["words"]
        numbers = _NUMBER.findall(re.sub(r"\\[A-Za-z@]+", " ", raw))
        statistics = TEST_STATISTICS.findall(raw)
        asides = ASIDE.findall(abstract_prose)
        abstract = {"words": words, "numbers": len(numbers), "test_statistics": len(statistics),
                    "test_statistic_terms": sorted({" ".join(s.split()) for s in statistics})[:8],
                    "parentheticals": len(asides)}
        if words > int(config["abstract_max_words"]):
            warnings.append(_hit(doc, a, "NARRATIVE-ABSTRACT-WORDS",
                                 f"abstract has {words} words (limit {config['abstract_max_words']}): one "
                                 "question, one main result with its key number, one sentence of meaning"))
        if len(numbers) > int(config["abstract_max_numbers"]):
            warnings.append(_hit(doc, a, "NARRATIVE-ABSTRACT-NUMBERS",
                                 f"abstract carries {len(numbers)} numbers (limit "
                                 f"{config['abstract_max_numbers']}): keep the main result's value and "
                                 "uncertainty, move per-subsample ranges and secondary parameters to the text"))
        if len(statistics) > int(config["abstract_max_test_statistics"]):
            warnings.append(_hit(doc, a, "NARRATIVE-ABSTRACT-TEST-STATISTICS",
                                 f"abstract uses test thresholds or inference machinery "
                                 f"({', '.join(abstract['test_statistic_terms'])}): state what was found, "
                                 "not the likelihood thresholds or sampler that found it"))
        if len(asides) > int(config["abstract_max_parentheticals"]):
            warnings.append(_hit(doc, a, "NARRATIVE-ABSTRACT-PARENTHETICALS",
                                 f"abstract has {len(asides)} parenthetical qualifiers (limit "
                                 f"{config['abstract_max_parentheticals']}): an abstract states the result; "
                                 "caveats go to the limitations paragraph"))

    # Sentence-level qualification, hedging and fillers over abstract + body.
    ranges = [regions.body] + ([regions.abstract] if regions.abstract else [])
    sentences: list[tuple[Sentence, bool]] = []
    conclusion_spans = []
    for index, (offset, title) in enumerate(titles):
        if re.search(r"conclu|summary|结论|总结", title, re.I):
            stop = titles[index + 1][0] if index + 1 < len(titles) else body_end
            conclusion_spans.append((offset, stop))
    # Captions legitimately carry panel descriptions in parentheses; they count as words but
    # not as qualified sentences.
    captions = []
    for match in re.finditer(r"\\caption\*?(?:\[[^\]]*\])?\s*\{", text):
        captions.append((match.start(), _balanced(text, match.end() - 1)))
    for a, b in ranges:
        for sentence in split_sentences(prose, a, b):
            if any(x <= sentence.start < y for x, y in (*excluded, *captions)):
                continue
            in_abstract = regions.abstract is not None and regions.abstract[0] <= sentence.start < regions.abstract[1]
            in_conclusion = any(x <= sentence.start < y for x, y in conclusion_spans)
            is_conclusion = in_abstract or in_conclusion or bool(CONCLUSION_CUE.search(sentence.text))
            sentences.append((sentence, is_conclusion))
    scanned_words = body_count["words"] + (abstract["words"] if abstract else 0)
    per_k = lambda n: round(n * 1000 / max(scanned_words, 1), 2)  # noqa: E731

    hedge_hits = []
    filler_hits = []
    for a, b in ranges:
        for pattern in (HEDGES_EN, HEDGES_ZH):
            hedge_hits += [m for m in pattern.finditer(prose, a, b)
                           if not any(x <= m.start() < y for x, y in excluded)]
        for pattern in (FILLERS_EN, FILLERS_ZH):
            filler_hits += [m for m in pattern.finditer(prose, a, b)
                            if not any(x <= m.start() < y for x, y in excluded)]
    stacked = []
    overqualified = []
    for sentence, is_conclusion in sentences:
        counts = _qualifiers(sentence.text)
        total = sum(counts.values())
        layers = sum(1 for value in counts.values() if value)
        record = {"markers": total, "layers": layers, "counts": counts}
        if is_conclusion and layers > int(config["conclusion_max_layers"]):
            overqualified.append((sentence, record))
        elif total >= int(config["sentence_max_qualifiers"]):
            stacked.append((sentence, record))

    def listed(items: list[tuple[Sentence, dict[str, Any]]], code: str, label: str) -> list[dict[str, Any]]:
        out = []
        for sentence, record in sorted(items, key=lambda x: -x[1]["markers"])[:12]:
            kinds = ", ".join(f"{k} {v}" for k, v in record["counts"].items() if v)
            out.append(_hit(doc, sentence.start, code, f"{label} ({kinds})", sentence.text))
        return sorted(out, key=lambda h: (h["path"], h["line"]))

    metrics = {
        "body_words": body_count["words"], "body_latin_words": body_count["latin_words"],
        "body_cjk_chars": body_count["cjk_chars"], "body_floats": floats, "body_pages_estimate": est_pages,
        "appendix_words": appendix_words, "sections": sections, "abstract": abstract,
        "hedges": len(hedge_hits), "hedges_per_1000_words": per_k(len(hedge_hits)),
        "fillers": len(filler_hits), "fillers_per_1000_words": per_k(len(filler_hits)),
        "sentences": len(sentences), "stacked_qualifier_sentences": len(stacked),
        "overqualified_conclusions": len(overqualified),
        "revision_history_hits": len(revision_hits),
    }
    if metrics["hedges_per_1000_words"] > float(config["hedges_per_1000_words"]):
        common: dict[str, int] = {}
        for m in hedge_hits:
            common[m.group(0).lower()] = common.get(m.group(0).lower(), 0) + 1
        top = ", ".join(f"{k} x{v}" for k, v in sorted(common.items(), key=lambda kv: -kv[1])[:8])
        warnings.append(_hit(doc, body_start, "NARRATIVE-HEDGE-DENSITY",
                             f"{len(hedge_hits)} hedges ({metrics['hedges_per_1000_words']}/1000 words, limit "
                             f"{config['hedges_per_1000_words']}): {top}. State each result once at the "
                             "strength the evidence supports; collect limitations in one section"))
    if len(stacked) > int(config["max_stacked_sentences"]):
        warnings.append(_hit(doc, body_start, "NARRATIVE-STACKED-QUALIFIERS",
                             f"{len(stacked)} sentences carry {config['sentence_max_qualifiers']} or more "
                             "qualifiers; split them or move the caveats to the limitations section"))
        warnings.extend(listed(stacked, "NARRATIVE-STACKED-QUALIFIERS", "stacked qualifiers"))
    if len(overqualified) > int(config["max_overqualified_conclusions"]):
        warnings.append(_hit(doc, body_start, "NARRATIVE-CONCLUSION-QUALIFIERS",
                             f"{len(overqualified)} conclusion sentences carry more than "
                             f"{config['conclusion_max_layers']} layer of qualification: state the finding, "
                             "then (if needed) one limit; the rest belongs to the limitations section"))
        warnings.extend(listed(overqualified, "NARRATIVE-CONCLUSION-QUALIFIERS", "over-qualified conclusion"))
    if filler_hits and metrics["fillers_per_1000_words"] > float(config["fillers_per_1000_words"]):
        warnings.append(_hit(doc, body_start, "NARRATIVE-FILLER-TRANSITIONS",
                             f"{len(filler_hits)} empty transitions ({metrics['fillers_per_1000_words']}/1000 "
                             f"words, limit {config['fillers_per_1000_words']}): delete them or say the "
                             "actual logical link"))
        for m in filler_hits[:20]:
            warnings.append(_hit(doc, m.start(), "NARRATIVE-FILLER-TRANSITIONS",
                                 f"empty transition \"{m.group(0)}\"", _excerpt(prose, m.start(), m.end(), 40)))
    if previous_body_words:
        growth = (body_count["words"] - previous_body_words) / max(previous_body_words, 1)
        metrics["previous_body_words"] = previous_body_words
        metrics["body_growth"] = round(growth, 3)
        if previous_source:
            metrics["previous_source"] = previous_source
        if growth > float(config["body_growth_tolerance"]):
            if main_text_growth_requested:
                metrics["body_growth_note"] = ("the previous round asked for main-text additions "
                                               "(placement main_text); growth is allowed")
            else:
                warnings.append(_hit(doc, body_start, "NARRATIVE-BODY-GROWTH",
                                     f"main text grew from {previous_body_words} to {body_count['words']} "
                                     f"words (+{round(growth * 100, 1)}%) since the last reviewed version "
                                     "without a main-text request from the reviewers: put added "
                                     "qualifications and checks in the appendix and the response letter"))
    if config.get("warnings_blocking"):
        advisory = {"NARRATIVE-REVISION-HISTORY", "NARRATIVE-BODY-LENGTH"}
        errors.extend(row for row in warnings if row["code"] not in advisory)
        warnings = [row for row in warnings if row["code"] in advisory]
    return {"valid": not errors, "limits": {k: config[k] for k in DEFAULT_LIMITS}, "metrics": metrics,
            "errors": errors, "warnings": warnings}


# --------------------------------------------------------------------------- paper entry points


def _research_line(root: Path, line_id: str | None) -> dict[str, Any] | None:
    if not line_id:
        return None
    import yaml

    path = root / "registry" / "research-lines.yaml"
    if not path.is_file():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for entry in data.get("lines") or []:
        if isinstance(entry, Mapping) and str(entry.get("id")) == line_id:
            return dict(entry)
    return None


def previous_review_snapshot(root: Path, paper_id: str) -> tuple[Path, dict[str, Any]] | None:
    """The expanded manuscript and decision record of the most recent completed review."""
    import json

    runs = root / "reviews" / "unified" / paper_id
    if not runs.is_dir():
        return None
    for run in sorted((p for p in runs.iterdir() if p.is_dir()), reverse=True):
        expanded = run / "manuscript-expanded.tex"
        decision = run / "decision.json"
        if not expanded.is_file() or not decision.is_file():
            continue
        try:
            record = json.loads(decision.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if record.get("stage_reached") == "decision":
            return expanded, record
    return None


def main_text_requested(record: Mapping[str, Any]) -> bool:
    merged = record.get("merged") or {}
    changes = list(merged.get("required_changes") or [])
    for report in (record.get("referee_reports") or {}).values():
        if isinstance(report, Mapping):
            changes += list(report.get("required_changes") or [])
    return any(isinstance(c, Mapping) and c.get("placement") == "main_text" for c in changes)


def body_words_of_text(text: str, limits: Mapping[str, Any] | None = None) -> int:
    return int(analyze(lines_from_text(text), limits)["metrics"]["body_words"])


def check_paper(paper_id: str, *, root: str | Path, line_id: str | None = None,
                main_tex: str | Path | None = None) -> dict[str, Any]:
    """Narrative check of the registered manuscript of ``paper_id``."""
    from paper_writing.registry import load_paper_metadata, load_registry

    repo_root = Path(root).resolve()
    settings = load_registry(repo_root, include_local_repositories=False, paper_ids=[paper_id])
    metadata = load_paper_metadata(paper_id, repo_root)
    manuscript = repo_root / str(metadata.get("manuscript_dir") or f"papers/{paper_id}/manuscript")
    main = Path(main_tex) if main_tex else repo_root / str(
        metadata.get("latest_source") or f"papers/{paper_id}/manuscript/main.tex")
    line = _research_line(repo_root, line_id or str(metadata.get("research_line") or "") or None)
    limits, sources = resolve_limits(metadata, settings=settings, line=line)
    if not main.is_file():
        return {"paper_id": paper_id, "valid": False, "limits": limits, "limit_sources": sources,
                "metrics": {}, "warnings": [],
                "errors": [{"code": "NARRATIVE-MANUSCRIPT-MISSING", "message": f"{main} is missing"}]}
    previous = previous_review_snapshot(repo_root, paper_id)
    previous_words = None
    previous_source = None
    requested = False
    if previous is not None:
        expanded, record = previous
        previous_words = body_words_of_text(expanded.read_text(encoding="utf-8", errors="replace"), limits)
        previous_source = expanded.relative_to(repo_root).as_posix()
        requested = main_text_requested(record)
    result = analyze(flatten_tex(main, manuscript), limits, previous_body_words=previous_words,
                     previous_source=previous_source, main_text_growth_requested=requested)
    for item in (*result["errors"], *result["warnings"]):
        if item.get("path"):
            item["path"] = f"{manuscript.relative_to(repo_root).as_posix()}/{item['path']}"
    return {"paper_id": paper_id, "article_type": article_type(metadata), "limit_sources": sources,
            "main_tex": main.relative_to(repo_root).as_posix() if main.is_relative_to(repo_root) else str(main),
            **result}


def render_report(result: Mapping[str, Any]) -> str:
    """Human-readable report (Markdown)."""
    metrics = result.get("metrics") or {}
    limits = result.get("limits") or {}
    abstract = metrics.get("abstract") or {}
    lines = [f"# Narrative check: {result.get('paper_id') or result.get('main_tex') or ''}", "",
             f"Result: {'pass' if result.get('valid') else 'FAIL'} "
             f"({len(result.get('errors') or [])} failures, {len(result.get('warnings') or [])} warnings)",
             f"Limits from: {', '.join(result.get('limit_sources') or ['defaults'])}", "",
             "| Measure | Value | Limit |", "|---|---|---|",
             f"| Main-text words | {metrics.get('body_words')} | {limits.get('max_body_words')} |",
             f"| Main-text pages (estimate) | {metrics.get('body_pages_estimate')} | "
             f"{limits.get('max_body_pages') or '-'} |",
             f"| Figures/tables in main text | {metrics.get('body_floats')} | - |",
             f"| Appendix words | {metrics.get('appendix_words')} | - |",
             f"| Abstract words | {abstract.get('words')} | {limits.get('abstract_max_words')} |",
             f"| Numbers in abstract | {abstract.get('numbers')} | {limits.get('abstract_max_numbers')} |",
             f"| Test statistics in abstract | {abstract.get('test_statistics')} | "
             f"{limits.get('abstract_max_test_statistics')} |",
             f"| Parentheticals in abstract | {abstract.get('parentheticals')} | "
             f"{limits.get('abstract_max_parentheticals')} |",
             f"| Hedges per 1000 words | {metrics.get('hedges_per_1000_words')} | "
             f"{limits.get('hedges_per_1000_words')} |",
             f"| Empty transitions per 1000 words | {metrics.get('fillers_per_1000_words')} | "
             f"{limits.get('fillers_per_1000_words')} |",
             f"| Sentences with stacked qualifiers | {metrics.get('stacked_qualifier_sentences')} | "
             f"{limits.get('max_stacked_sentences')} |",
             f"| Over-qualified conclusion sentences | {metrics.get('overqualified_conclusions')} | "
             f"{limits.get('max_overqualified_conclusions')} |",
             f"| Revision-history phrases | {metrics.get('revision_history_hits')} | 0 |"]
    if metrics.get("previous_body_words"):
        lines.append(f"| Main-text growth since last review | {metrics.get('body_growth')} | "
                     f"{limits.get('body_growth_tolerance')} |")
    if metrics.get("sections"):
        lines += ["", "Main-text sections (words): " + "; ".join(
            f"{s['title']} {s['words']}" for s in metrics["sections"])]
    for title, key in (("Failures", "errors"), ("Warnings", "warnings")):
        items = result.get(key) or []
        if not items:
            continue
        lines += ["", f"## {title}", ""]
        for item in items:
            where = f"{item.get('path')}:{item.get('line')}" if item.get("path") else ""
            lines.append(f"- {item['code']} {where}: {item['message']}")
            if item.get("context"):
                lines.append(f"  > {item['context']}")
    return "\n".join(lines) + "\n"


def iter_codes(items: Iterable[Mapping[str, Any]]) -> list[str]:
    return sorted({str(i.get("code")) for i in items})
