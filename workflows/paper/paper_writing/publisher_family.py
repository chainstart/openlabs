"""Which publisher family a target journal belongs to (Nature Portfolio rules, 2026-11-25).

Nature Portfolio journals (Nature Communications, Scientific Reports, the Nature research
journals, npj and Communications journals) share two rules the pipeline applies by family:

* AI disclosure. Springer Nature's AI policy (nature.com/nature-portfolio/editorial-policies/ai,
  springernature.com/gp/policies/editorial-policies/ai-manuscript-preparation, read
  2026-11-25) asks for a clear description of AI use with author accountability and
  publishes no fixed wording. Nature Communications' how-to-submit page says "Use of an LLM
  should be properly documented in the Methods section (and if a Methods section is not
  available, in a suitable alternative part)". The user chose the end of the manuscript
  (2026-11-26, "如果可以的话，放文末"), as our Scientific Reports submission
  (papers/20260506aillm0007) carries it: a separate unnumbered "AI use declaration" section in
  the end-matter declarations, after Author contributions / Competing interests (else just
  before the references), not in Methods (``declarations.end_matter_insertion``).
* Generated images. Springer Nature does not permit AI-generated visual content "created
  from text prompts or without verifiable source data or material" (ai-manuscript-preparation)
  nor photorealistic images (ai). Code-drawn figures from data and licensed vector assets
  remain allowed; see ``figures.generated_image_findings``.

The register entry's ``portfolio`` field (registry/verified-venues.yaml) wins; otherwise
the journal name decides.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

NATURE_PORTFOLIO = "nature_portfolio"
_COMMUNICATIONS = {"biology", "chemistry", "earth & environment", "earth and environment",
                   "engineering", "materials", "medicine", "physics", "psychology",
                   "sustainability"}
_NAMED = {"scientific reports", "scientific data", "nature"}


def _key(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _by_name(journal: str) -> str | None:
    name = _key(journal)
    if not name:
        return None
    if name in _NAMED or name.startswith(("nature ", "npj ")) or (
            name.startswith("communications ") and name[len("communications "):] in _COMMUNICATIONS):
        return NATURE_PORTFOLIO
    return None


def venue_family(journal: Any, root: str | Path | None = None) -> str | None:
    """``nature_portfolio`` or None (other families keep their existing rules)."""

    if not journal:
        return None
    if root is not None:
        try:
            from paper_writing.venue_registry import find_venue, load_venues

            entry = find_venue(load_venues(root), journal=str(journal))
        except Exception:  # noqa: BLE001 - the name rule still applies
            entry = None
        if entry is not None and entry.get("portfolio"):
            value = _key(entry["portfolio"]).replace(" ", "_")
            return NATURE_PORTFOLIO if value == NATURE_PORTFOLIO else None
    return _by_name(str(journal))


def nature_portfolio(journal: Any, root: str | Path | None = None) -> bool:
    return venue_family(journal, root) == NATURE_PORTFOLIO
