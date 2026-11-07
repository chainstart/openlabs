"""Editorial-voice heuristics for reader-facing manuscripts.

Desk editors rejected team papers as "AI-slop" (JLMS 2026-09-26) and a PRD referee wrote
that "technical details and repeated qualifications obscure the main conclusions".  These
deterministic counts flag the symptoms: dense self-limiting hedges, repository/provenance
vocabulary in the scientific body, stock LLM phrasing and an over-long abstract.  They are
not a prose score.  By default they are warnings; ``quality_gate.editorial_voice.blocking``
turns threshold breaches into style errors.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

HEDGE = re.compile(
    r"\bwe do not claim\b|\bno claim\b|\bis not a claim\b|\bdoes not (?:establish|imply|prove|show)\b|"
    r"\bshould not be (?:read|interpreted)\b|\bmust not be (?:read|interpreted)\b|\bwe caution\b|"
    r"\bnot (?:a|an) (?:general|universal|population-level)\b|\bwithin (?:this|the) (?:bounded|frozen|registered)\b|"
    r"\bonly (?:within|for) the (?:registered|frozen|declared)\b|\bdescriptive only\b",
    re.IGNORECASE,
)
INTERNAL = re.compile(
    # Domain-ambiguous words (replay, ledger, lineage, campaign) are deliberately excluded.
    r"\b(?:receipts?|quality[- ]gates?|attempt[- ]ids?|result bundles?|manifests?|"
    r"frozen (?:panel|selection|protocol)|provenance chain|SHA-?256|checksums?)\b",
    re.IGNORECASE,
)
STOCK = re.compile(
    r"\b(?:delve[sd]?|intricate|pivotal|underscores?|showcases?|tapestry|meticulous(?:ly)?|"
    r"it is worth noting|plays a crucial role|in the realm of|a testament to|seamless(?:ly)?)\b",
    re.IGNORECASE,
)
TEX_COMMAND = re.compile(r"\\[A-Za-z@]+\*?(?:\[[^\]]*\])?")
ABSTRACT = re.compile(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", re.DOTALL)
BACK_MATTER = re.compile(
    r"\\(?:sub)*section\*?\{[^}]*(?:data|code)[^}]*availab[^}]*\}|\\(?:sub)*section\*?\{[^}]*reproducib[^}]*\}",
    re.IGNORECASE,
)

DEFAULT_LIMITS = {
    "hedges_per_1000_words": 3.0,
    "internal_terms_per_1000_words": 2.0,
    "stock_phrases_per_1000_words": 1.0,
    "abstract_max_words": 300,
}


def _words(text: str) -> int:
    return len(re.findall(r"[A-Za-z][A-Za-z'-]+", TEX_COMMAND.sub(" ", text)))


def editorial_voice_metrics(body_text: str) -> dict[str, Any]:
    """Count symptoms in the scientific body (data/code availability sections excluded)."""

    cut = BACK_MATTER.search(body_text)
    body = body_text[: cut.start()] if cut else body_text
    words = max(_words(body), 1)
    abstract = ABSTRACT.search(body_text)
    per_k = lambda n: round(n * 1000 / words, 2)  # noqa: E731
    hedges = HEDGE.findall(body)
    internal = INTERNAL.findall(body)
    stock = STOCK.findall(body)
    return {
        "words": words,
        "hedges": len(hedges),
        "hedges_per_1000_words": per_k(len(hedges)),
        "internal_terms": len(internal),
        "internal_terms_per_1000_words": per_k(len(internal)),
        "internal_examples": sorted({m.lower() for m in internal})[:8],
        "stock_phrases": len(stock),
        "stock_phrases_per_1000_words": per_k(len(stock)),
        "stock_examples": sorted({m.lower() for m in stock})[:8],
        "abstract_words": _words(abstract.group(1)) if abstract else None,
    }


def editorial_voice_issues(body_text: str, limits: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    config = {**DEFAULT_LIMITS, **{k: v for k, v in dict(limits or {}).items() if k in DEFAULT_LIMITS}}
    metrics = editorial_voice_metrics(body_text)
    issues: list[dict[str, Any]] = []
    if metrics["words"] >= 500:
        if metrics["hedges_per_1000_words"] > config["hedges_per_1000_words"]:
            issues.append({"code": "VOICE-HEDGE-DENSITY", "message":
                           f"{metrics['hedges']} self-limiting qualifications ({metrics['hedges_per_1000_words']}/1000 words); "
                           "state the main result plainly once and gather limitations in one section"})
        if metrics["internal_terms_per_1000_words"] > config["internal_terms_per_1000_words"]:
            issues.append({"code": "VOICE-INTERNAL-VOCABULARY", "message":
                           f"repository/provenance vocabulary in the scientific body ({', '.join(metrics['internal_examples'])}); "
                           "move reproducibility mechanics to the data/code availability section"})
        if metrics["stock_phrases_per_1000_words"] > config["stock_phrases_per_1000_words"]:
            issues.append({"code": "VOICE-STOCK-PHRASING", "message":
                           f"stock generated phrasing ({', '.join(metrics['stock_examples'])}); rewrite in plain disciplinary prose"})
    if metrics["abstract_words"] is not None and metrics["abstract_words"] > config["abstract_max_words"]:
        issues.append({"code": "VOICE-ABSTRACT-LENGTH", "message":
                       f"abstract has {metrics['abstract_words']} words (limit {config['abstract_max_words']}); "
                       "lead with the question, the finding and why readers of the target venue care"})
    return metrics, issues
