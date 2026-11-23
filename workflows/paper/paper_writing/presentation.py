"""Presentation revision review (2026-11-23): restructure without a scientific round.

The owner asked (2026-11-23) to polish delivered papers until they *look* like papers in a
leading journal -- text structure, narrative, figure layout and redrawing, typesetting, the
venue's document class -- without changing their science, and agreed to a separate review
channel for such revisions ("1-同意"). A presentation revision does not consume a
scientific review round for the target journal:

1. Deterministic check (this module, no model): against the last ready unified decision
   (the same basis rule as the delta review, so formal-only, resynthesized and earlier
   presentation decisions qualify), the revised manuscript may add no number (body, tables,
   captions, generated value macros; layout, cross-references, delivery identifiers,
   author metadata, declarations and the bibliography excluded), may not change a
   theorem-like statement, may not introduce a claim-strength word family that the reviewed
   text never used, and every changed or new figure must be declared: a schematic, or a
   result figure redrawn only from data files that are byte-identical to the files committed
   with the basis decision. The author-mode delivery floor (GQ1) must already pass.
2. One light review by a single independent model session (the delivery reader, chosen by
   the cross-family rule) that also judges form, narrative and figures against the venue
   standard and compares the old and new claim-bearing text for amplified conclusions.
3. Ready: the carried scientific judgment, a fresh mandatory formal check and that reading
   are recorded as ``review_mode: presentation`` (``consumes_scientific_round: false``) and
   the release pipeline publishes and delivers as for any ready decision.

Any scientific change found by step 1, or an amplified claim found in step 2, is recorded
as ``full_review_required`` (registry untouched): the paper goes to a normal unified review,
which counts rounds as usual. Material form findings return ``revision_required`` without a
round. Following the GATE1 materiality rule only blocking findings stop the paper; the rest
is advice.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "openlabs.presentation_revision.v1"
RULE = ("Presentation revision: no added number, no changed theorem-like statement, no newly "
        "introduced claim-strength word family; changed figures declared as schematics or as "
        "result figures redrawn from data byte-identical to the basis commit; GQ1 author floor "
        "passing; one independent light review of form, narrative, figures and claim strength.")
BASIS_MODES = ("formal_only", "resynthesize", "presentation")

_COMMENT = re.compile(r"(?<!\\)%[^\n]*")
_MACRO_NUMBER = re.compile(r"\\(?:newcommand|renewcommand|providecommand)\s*\{\\([A-Za-z]+)\}"
                           r"\s*\{([-+0-9.,]+)\}")
_BIBLIOGRAPHY = re.compile(r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}", re.S)
_AUTHOR_COMMANDS = ("author", "affiliation", "affil", "address", "institute", "institution", "ead",
                    "email", "orcid", "cortext", "fntext", "tnotetext", "thanks", "corref",
                    "IEEEauthorblockN", "IEEEauthorblockA", "authorrunning", "titlerunning")
_DECLARATION_HEADING = re.compile(
    r"acknowledg|funding|declaration|competing|conflicts? of interest|credit|author contribution|"
    r"data (?:and code )?availability|code availability|ethic|generative ai|consent|"
    r"supplementary (?:material|data)|appendix data", re.I)
_SECTION = re.compile(r"\\(?:section|subsection)\*?\s*\{([^}]*)\}")
_LAYOUT = re.compile(r"\\(?:includegraphics|label|ref|cref|Cref|eqref|autoref|pageref|nameref|cite[A-Za-z]*|"
                     r"url|href|input|include|vspace|hspace|setlength|addtolength|setcounter|"
                     r"bibliography[A-Za-z]*|documentclass|usepackage|linenumbers|graphicspath)"
                     r"\*?(?:\s*\[[^\]]*\])*\s*\{[^}]*\}")
_TABLE_SPANS = re.compile(r"\\(?:multicolumn|multirow)\s*\{[^}]*\}|\\(?:cline|cmidrule)(?:\([^)]*\))?\s*\{[^}]*\}")
_FLOAT_PLACEMENT = re.compile(r"\\begin\{[A-Za-z*]+\}\s*\[[^\]]*\]")
_DIMENSION = re.compile(r"[-+]?\d*\.?\d+\s*(?:pt|mm|cm|in|em|ex|bp)\b|[-+]?\d*\.?\d+\s*\\(?:text|line|column)width"
                        r"|[-+]?\d*\.?\d+\s*\\(?:text|paper)height")
_CROSS_REFERENCE = re.compile(r"\b(?:Fig(?:ure)?s?|Tables?|Tab|Sections?|Sect|Sec|Eqs?|Equations?|"
                              r"Appendix|Appendices|Panels?|Algorithm|Step)\.?~?\s*[A-Z]?\d+(?:[a-z])?"
                              r"(?:\s*(?:[-–,]|and|--)\s*[A-Z]?\d+[a-z]?)*", re.I)
_TIKZ = re.compile(r"\\begin\{tikzpicture\}.*?\\end\{tikzpicture\}", re.S)
_TIKZ_LABEL = re.compile(r"\bnode\b[^{;]*\{([^{}]*)\}")
_IDENTIFIER = re.compile(r"(?:\bdoi:\s*|https?://\S+|\b10\.\d{4,9}/[^\s{}]+|\b[Vv]ersion\s*v?\d+(?:\.\d+)*\b"
                         r"|\bv\d+(?:\.\d+)+\b|\bzenodo\.\d+\b)")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_STATEMENT = re.compile(r"\\begin\{(theorem|proposition|corollary|conjecture|lemma)(\*?)\}(.*?)\\end\{\1\2\}", re.S)
# Word families whose first appearance would strengthen what the paper claims.
CLAIM_FAMILIES = {
    "causal": r"\bcaus(?:al|ally|ation|es|ed|ing)\b|\bcause\b",
    "proof": r"\bprov(?:e|es|ed|en|ing)\b",
    "demonstration": r"\bdemonstrat(?:e|es|ed|ing)\b",
    "establishment": r"\bestablish(?:es|ed|ing)?\b",
    "confirmation": r"\bconfirm(?:s|ed|ing|ation)?\b",
    "definitiveness": r"\b(?:definitive|conclusive)(?:ly)?\b|\bunambiguous(?:ly)?\b",
    "priority": r"\bfor the first time\b|\bfirst (?:study|report|evidence|demonstration)\b|\bnovel\b"
                r"|\bunprecedented\b|\bbreakthrough\b",
    "significance": r"\bsignificant(?:ly)?\b",
    "generality": r"\buniversal(?:ly)?\b|\bgeneraliz(?:e|es|able|ability)\b|\bin general\b",
    "superiority": r"\boutperform(?:s|ed|ing)?\b|\bsuperior(?:ity)?\b|\bstate[- ]of[- ]the[- ]art\b",
}


class PresentationError(ValueError):
    """The presentation request is malformed or not bound to the basis decision."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _balanced_end(text: str, start: int) -> int | None:
    depth = 0
    index = start
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
    return None


def _drop_commands(text: str, names: tuple[str, ...]) -> str:
    pattern = re.compile(r"\\(" + "|".join(names) + r")\*?\s*(?:\[[^\]]*\]\s*)*(?=\{)")
    output, index = [], 0
    while match := pattern.search(text, index):
        end = _balanced_end(text, match.end())
        if end is None:
            break
        output.append(text[index:match.start()])
        index = end
    output.append(text[index:])
    return "".join(output)


def _drop_declarations(text: str) -> str:
    headings = list(_SECTION.finditer(text))
    keep, index = [], 0
    for position, heading in enumerate(headings):
        if not _DECLARATION_HEADING.search(heading.group(1)):
            continue
        end = headings[position + 1].start() if position + 1 < len(headings) else len(text)
        tail = re.search(r"\\(?:bibliography|printbibliography|end\{document\}|appendix\b)", text[heading.end():end])
        if tail:
            end = heading.end() + tail.start()
        keep.append(text[index:heading.start()])
        index = end
    keep.append(text[index:])
    return "".join(keep)


def scientific_text(expanded: str) -> str:
    """The expanded manuscript with everything that is not scientific content removed."""
    text = _COMMENT.sub("", expanded)
    numeric = dict(_MACRO_NUMBER.findall(text))
    text = _BIBLIOGRAPHY.sub(" ", text)
    title = re.search(r"\\title(?:\[[^\]]*\])?\s*\{", text)
    head = ""
    if title:
        end = _balanced_end(text, title.end() - 1)
        head = text[title.end():end - 1] if end else ""
    body = re.split(r"\\begin\{document\}", text, maxsplit=1)
    body_text = body[1] if len(body) == 2 else text
    if title and title.start() > len(text) - len(body_text):
        head = ""  # the title is in the body and is kept there
    text = head + "\n" + body_text
    if numeric:  # generated result macros count as the numbers they print
        text = re.sub(r"\\([A-Za-z]+)\b", lambda m: numeric.get(m.group(1), m.group(0)), text)
    text = _drop_commands(text, _AUTHOR_COMMANDS)
    text = _drop_declarations(text)
    text = _TIKZ.sub(lambda m: " ".join(_TIKZ_LABEL.findall(m.group(0))), text)
    for pattern in (_LAYOUT, _TABLE_SPANS, _FLOAT_PLACEMENT, _IDENTIFIER, _CROSS_REFERENCE):
        text = pattern.sub(" ", text)
    return _DIMENSION.sub(" ", text)


def _numbers(text: str) -> set[str]:
    return {value.replace(",", "") if re.fullmatch(r"\d{1,3}(?:,\d{3})+", value) else value
            for value in _NUMBER.findall(text)}


def _statements(text: str) -> list[str]:
    return sorted(" ".join(m.group(3).split()) for m in _STATEMENT.finditer(_COMMENT.sub("", text)))


def claim_families(text: str) -> dict[str, int]:
    plain = scientific_text(text)
    return {name: len(re.findall(pattern, plain, re.I)) for name, pattern in CLAIM_FAMILIES.items()}


def compare(old: str, new: str) -> dict[str, Any]:
    """Deterministic science-invariance check of two expanded manuscripts."""
    reasons: list[str] = []
    old_numbers, new_numbers = _numbers(scientific_text(old)), _numbers(scientific_text(new))
    added = sorted(new_numbers - old_numbers)
    if added:
        reasons.append(f"numbers added or changed: {added[:15]}")
    if _statements(old) != _statements(new):
        reasons.append("theorem-like statements changed")
    old_claims, new_claims = claim_families(old), claim_families(new)
    introduced = sorted(name for name, count in new_claims.items() if count and not old_claims[name])
    if introduced:
        reasons.append("claim-strength wording introduced: " + ", ".join(introduced))
    return {"reasons": reasons, "numbers_added": added,
            "numbers_removed": sorted(old_numbers - new_numbers)[:200],
            "claim_families": {"basis": old_claims, "revised": new_claims}}


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, timeout=60).stdout


def basis_commit(root: Path, decision: Path) -> str:
    """The data-repository commit that recorded the basis decision."""
    relative = decision.resolve().relative_to(root.resolve()).as_posix()
    try:
        commit = _git(root, "log", "--diff-filter=A", "--format=%H", "-1", "--", relative).decode().strip()
    except (subprocess.SubprocessError, OSError) as exc:
        raise PresentationError(f"cannot read the commit of the basis decision: {exc}") from exc
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise PresentationError("the basis decision is not committed; commit it before a presentation review")
    return commit


def _safe_relative(value: Any) -> str:
    if (not isinstance(value, str) or not value or "\\" in value or Path(value).is_absolute()
            or ".." in Path(value).parts or Path(value).as_posix() != value):
        raise PresentationError(f"unsafe path in the presentation request: {value!r}")
    return value


def frozen_data(root: Path, commit: str, paths: list[str]) -> tuple[list[dict[str, str]], list[str]]:
    """Bind each data file to the basis commit; returns (bindings, reasons)."""
    bindings, reasons = [], []
    for path in paths:
        current = root / path
        if current.is_symlink() or not current.is_file():
            reasons.append(f"figure data file is missing: {path}")
            continue
        digest = _sha256(current.read_bytes())
        try:
            frozen = _git(root, "show", f"{commit}:{path}")
        except (subprocess.SubprocessError, OSError):
            reasons.append(f"figure data was not committed with the basis decision: {path}")
            continue
        if _sha256(frozen) != digest:
            reasons.append(f"figure data changed since the basis decision: {path}")
            continue
        bindings.append({"path": path, "sha256": digest})
    return bindings, reasons


def load_request(raw: bytes, basis_sha256: str) -> dict[str, Any]:
    try:
        request = json.loads(raw) if raw else None
    except ValueError as exc:
        raise PresentationError(f"the presentation request is not JSON: {exc}") from exc
    if not isinstance(request, dict) or request.get("schema") != SCHEMA:
        raise PresentationError(f"Provide --response with a {SCHEMA} request")
    if request.get("basis_decision_sha256") != basis_sha256:
        raise PresentationError("basis_decision_sha256 must be the SHA-256 of the basis ready decision")
    if not isinstance(request.get("summary"), str) or not request["summary"].strip():
        raise PresentationError("Summarize the presentation changes in `summary`")
    figures = request.get("figures", [])
    if not isinstance(figures, list) or any(not isinstance(item, dict) for item in figures):
        raise PresentationError("`figures` must be a list of objects")
    return request


def check_figures(root: Path, commit: str, changed: list[str], request: Mapping[str, Any],
                  present: set[str]) -> tuple[list[dict[str, Any]], list[str]]:
    declared: dict[str, Mapping[str, Any]] = {}
    for item in request.get("figures", []):
        declared[str(item.get("path"))] = item
    records, reasons = [], []
    for path in changed:
        if path not in present:
            continue  # a figure removed from the build needs no data
        item = declared.get(path)
        if item is None:
            reasons.append(f"changed figure not declared in the presentation request: {path}")
            continue
        kind = item.get("kind")
        if kind == "schematic":
            records.append({"path": path, "kind": "schematic"})
        elif kind == "result":
            data = item.get("data")
            if not isinstance(data, list) or not data:
                reasons.append(f"result figure {path} must list the frozen data files it was drawn from")
                continue
            try:
                bindings, problems = frozen_data(root, commit, [_safe_relative(value) for value in data])
            except PresentationError as exc:
                reasons.append(str(exc))
                continue
            reasons.extend(problems)
            records.append({"path": path, "kind": "result", "data": bindings})
        else:
            reasons.append(f"figure {path}: kind must be 'schematic' or 'result'")
    return records, reasons


def claim_text(expanded: str) -> dict[str, str]:
    """Title, abstract and the claim-bearing sections, for the light reviewer."""
    from paper_writing.review_flow import front_matter

    head = front_matter(expanded)
    text = _COMMENT.sub("", expanded)
    headings = list(re.finditer(r"\\section\*?\{([^}]*)\}", text))
    parts = []
    for index, match in enumerate(headings):
        if re.search(r"\b(results?|findings?|discussion|conclusions?|concluding|summary|implications?)\b",
                     match.group(1), re.I):
            end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
            parts.append(text[match.start():end][:20000])
    highlights = re.search(r"\\begin\{highlights\}(.*?)\\end\{highlights\}", text, re.S)
    return {"title": head["title"], "abstract": head["abstract"],
            "highlights": highlights.group(1).strip() if highlights else "",
            "claim_sections": "\n\n".join(parts)[:60000]}


def reviewer_packet(old: str, new: str, metadata: Mapping[str, Any], request: Mapping[str, Any]) -> str:
    return (
        "\n\n## Presentation review (no new scientific judgment)\n"
        "The scientific content passed an earlier independent review; the authors revised only the "
        "presentation. Judge only whether the revised paper now looks like a paper in the target venue: "
        "structure and story (problem, gap, approach, finding, meaning), main text versus appendix, "
        "figures (schematic, multi-panel results, consistent colours and type, self-contained captions, "
        "placement near first citation) and typesetting (venue document class, byline, keywords, "
        "declarations). Report a form repair as blocking only when an editor of the venue would return "
        "the paper for it; everything else is advice. Then compare the claim-bearing text before and "
        "after and list every passage whose wording states a stronger, broader or more certain conclusion "
        "than the reviewed text supported (amplified_claims); reorganized or narrowed wording is fine.\n"
        f"Target venue: {metadata.get('target_journal')}\n"
        f"Author's summary of the changes: {str(request.get('summary'))[:4000]}\n"
        "Reviewed claim-bearing text (basis):\n" + json.dumps(claim_text(old), ensure_ascii=False) + "\n"
        "Revised claim-bearing text:\n" + json.dumps(claim_text(new), ensure_ascii=False) + "\n")


_FINDING = {"type": "object", "additionalProperties": False, "required": ["location", "repair", "blocking"],
            "properties": {"location": {"type": "string"}, "repair": {"type": "string"},
                           "blocking": {"type": "boolean"}}}
_CLAIM = {"type": "object", "additionalProperties": False, "required": ["before", "after", "why"],
          "properties": {"before": {"type": "string"}, "after": {"type": "string"}, "why": {"type": "string"}}}
REVIEW_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["form_meets_venue", "narrative_meets_standard", "figures_meet_standard",
                 "form_repairs", "amplified_claims", "summary"],
    "properties": {"form_meets_venue": {"type": "boolean"}, "narrative_meets_standard": {"type": "boolean"},
                   "figures_meet_standard": {"type": "boolean"},
                   "form_repairs": {"type": "array", "items": _FINDING},
                   "amplified_claims": {"type": "array", "items": _CLAIM},
                   "summary": {"type": "string"}},
}


def merge_review(merged: dict[str, Any], review: Mapping[str, Any]) -> str | None:
    """Apply the light review to a merged decision; returns the routing reason, if any."""
    claims = [item for item in review.get("amplified_claims") or [] if str(item.get("after") or "").strip()]
    if claims:
        merged.update(outcome="full_review_required", next_action="full_review",
                      full_review_reasons=["the light review found amplified claims: "
                                           + "; ".join(str(c.get("why"))[:200] for c in claims[:5])])
        return "amplified_claims"
    blocking = [item for item in review.get("form_repairs") or [] if item.get("blocking")]
    advice = [item for item in review.get("form_repairs") or [] if not item.get("blocking")]
    required = merged.setdefault("required_changes", [])
    for item in review.get("form_repairs") or []:
        required.append({"type": "presentation", "referee": "presentation_reviewer",
                         "location": item.get("location", ""), "change": item.get("repair", ""),
                         "advisory": not item.get("blocking"), "placement": "main_text"})
    if blocking and merged.get("outcome") == "ready":
        merged.update(outcome="revision_required", recommendation="minor_revision", next_action="text_revision")
        return "form_repairs"
    if advice:
        merged.setdefault("advisory_items", []).extend(
            {"referee": "presentation_reviewer", "location": item.get("location", ""),
             "change": item.get("repair", "")} for item in advice)
    return None


def validate(record: Mapping[str, Any], path: Path, root: Path) -> list[str]:
    """Re-verify a presentation decision's bindings (at apply, delivery and as a delta basis)."""
    if record.get("review_mode") != "presentation":
        return []
    try:
        delta, provenance = record["delta_review"], record["presentation_review"]
        basis_path = (root / delta["basis_decision"]).resolve()
        if basis_path.parent.parent != path.resolve().parent.parent:
            raise ValueError("the basis decision belongs to another paper")
        raw = basis_path.read_bytes()
        basis = json.loads(raw)
        if (_sha256(raw) != delta["basis_decision_sha256"] or basis.get("run_id") != delta["basis_run_id"]
                or (basis.get("merged") or {}).get("outcome") != "ready"
                or any(basis.get(key) != record.get(key) for key in
                       ("paper_id", "target_journal", "editor_screen", "referee_reports", "prior_decisions"))):
            raise ValueError("the basis decision or its carried judgments changed")
        directory = path.parent
        files = ((directory / "presentation-request.json", provenance["request_sha256"]),
                 (directory / "manuscript-expanded.tex", provenance["revised_expanded_sha256"]),
                 (basis_path.parent / "manuscript-expanded.tex", provenance["basis_expanded_sha256"]))
        if any(_sha256(file.read_bytes()) != digest for file, digest in files):
            raise ValueError("a bound request or manuscript snapshot changed")
        if provenance.get("rule") != RULE or provenance.get("deterministic", {}).get("reasons"):
            raise ValueError("the deterministic check did not pass under the current rule")
        if basis.get("review_mode") == "presentation":
            return validate(basis, basis_path, root)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return [f"Presentation provenance: {exc}"]
    return []


def validate_delta_basis(record: Mapping[str, Any], root: Path) -> list[str]:
    """A delta decision built on a presentation decision re-verifies that decision."""
    delta = record.get("delta_review") or {}
    if record.get("review_mode") == "presentation" or delta.get("basis_mode") != "presentation":
        return []
    try:
        path = (root / delta["basis_decision"]).resolve()
        raw = path.read_bytes()
        basis = json.loads(raw)
        if (_sha256(raw) != delta["basis_decision_sha256"] or basis.get("review_mode") != "presentation"
                or any(basis.get(key) != record.get(key) for key in
                       ("editor_screen", "referee_reports", "prior_decisions"))):
            raise ValueError("the presentation basis or its carried judgments changed")
        return validate(basis, path, root)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return [f"Presentation delta basis: {exc}"]
