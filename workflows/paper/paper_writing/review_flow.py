"""Unified editor-and-referee review: the only path to ``writing_release.status: ready``.

Stages: deterministic preflight -> editor screen at the named target journal ->
configured blind referee panel -> deterministic merge plus an editor's
decision letter. Revisions re-enter the same stages with the authors' response
letter and the cumulative source diff. Models judge; this module only prepares
inputs, runs isolated processes, validates records, merges conservatively and
binds the result to the exact manuscript snapshot.
"""
from __future__ import annotations

import concurrent.futures
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from paper_writing.registry import load_paper_metadata, load_registry, load_registry_settings, write_paper_metadata
from paper_writing.review_launcher import LaunchError, run_role

PROCESS = "unified_v1"
RECOMMENDATIONS = ("accept", "minor_revision", "major_revision", "reject")
EDITOR_DECISIONS = ("send_to_review", "revise_before_submission", "desk_reject")
DESK_CATEGORIES = ("scope", "significance", "readership", "novelty_unclear", "presentation", "incremental", "none")
CHANGE_TYPES = ("text", "claim_narrowing", "evidence")
ROLES = ("editor", "referee_a", "referee_b")
PROMPTS = Path(__file__).resolve().parents[1] / "skills" / "openlabs-paper-review" / "references" / "unified"
CLEAN_SOURCE_SUFFIXES = {".tex", ".sty", ".cls", ".bst", ".bib", ".eps", ".png", ".jpg", ".jpeg", ".svg",
                         ".tikz", ".pgf", ".clo", ".def", ".fd", ".cfg"}

_TEXT = {"type": "string"}
_TEXT_LIST = {"type": "array", "items": _TEXT}
EDITOR_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": ["contribution_in_two_sentences", "presentation_fails_restatement", "closest_prior_work",
                 "advance_over_prior_work", "significance_for_journal", "readership_for_journal",
                 "presentation_problems", "prior_rejections_addressed", "strongest_desk_reject_reason",
                 "desk_reject_category", "decision", "decision_rationale"],
    "properties": {
        "contribution_in_two_sentences": _TEXT,
        "presentation_fails_restatement": {"type": "boolean"},
        "closest_prior_work": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["work", "source", "known_result"],
            "properties": {"work": _TEXT, "source": {"type": "string", "enum": ["reference_list", "editor_knowledge"]},
                           "known_result": _TEXT}}},
        "advance_over_prior_work": _TEXT,
        "significance_for_journal": _TEXT,
        "readership_for_journal": _TEXT,
        "presentation_problems": _TEXT_LIST,
        "prior_rejections_addressed": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["decision_id", "journal", "concern", "answered", "judgment", "evidence"],
            "properties": {"decision_id": _TEXT, "journal": _TEXT, "concern": _TEXT,
                           "answered": {"type": "boolean"}, "evidence": _TEXT,
                           "judgment": {"type": "string", "enum": ["resolved", "compatible", "unresolved", "unverifiable"]}}}},
        "strongest_desk_reject_reason": _TEXT,
        "desk_reject_category": {"type": "string", "enum": list(DESK_CATEGORIES)},
        "decision": {"type": "string", "enum": list(EDITOR_DECISIONS)},
        "decision_rationale": _TEXT,
    },
}
_SCORE = {"type": "integer", "minimum": 1, "maximum": 10}
REFEREE_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": ["summary", "correctness_findings", "novelty_and_context", "significance", "presentation",
                 "evidence_consistency", "scores", "recommendation", "scientific_blockers", "required_changes",
                 "optional_suggestions", "previous_items", "confidence"],
    "properties": {
        "summary": _TEXT,
        "correctness_findings": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["location", "kind", "finding"],
            "properties": {"location": _TEXT, "kind": {"type": "string", "enum": ["error", "gap", "unchecked", "verified"]},
                           "finding": _TEXT}}},
        "novelty_and_context": _TEXT,
        "significance": _TEXT,
        "presentation": _TEXT,
        "evidence_consistency": _TEXT,
        "scores": {"type": "object", "additionalProperties": False,
                   "required": ["clarity", "soundness", "significance", "novelty", "overall"],
                   "properties": {k: _SCORE for k in ("clarity", "soundness", "significance", "novelty", "overall")}},
        "recommendation": {"type": "string", "enum": list(RECOMMENDATIONS)},
        "scientific_blockers": _TEXT_LIST,
        "required_changes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["change", "type", "location"],
            "properties": {"change": _TEXT, "type": {"type": "string", "enum": list(CHANGE_TYPES)}, "location": _TEXT}}},
        "optional_suggestions": _TEXT_LIST,
        "previous_items": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["item", "resolved", "evidence"],
            "properties": {"item": _TEXT, "resolved": {"type": "boolean"}, "evidence": _TEXT}}},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
}
LETTER_SCHEMA: dict[str, Any] = {"type": "object", "additionalProperties": False,
                                 "required": ["letter"], "properties": {"letter": _TEXT}}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_dump(path: Path, value: Any) -> str:
    text = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text)
    return _sha256(text.encode())


# --------------------------------------------------------------------------- configuration

def review_config(root: str | Path) -> dict[str, Any]:
    settings = load_registry_settings(root)
    gate = settings.get("quality_gate") or {}
    review = settings.get("review") or {}
    panel = review.get("referee_roles", ["referee_a", "referee_b"])
    if not isinstance(panel, list) or len(panel) not in {1, 2} or len(set(panel)) != len(panel):
        raise ValueError("review.referee_roles must select one or two distinct referees")
    if any(name not in {"referee_a", "referee_b"} for name in panel):
        raise ValueError("Unknown referee role")
    if len(panel) == 1 and not review.get("single_referee_authorization"):
        raise ValueError("A single referee requires an explicit recorded user authorization")
    return {"process": gate.get("review_process"), "roles": review.get("roles") or {},
            "referee_roles": panel, "rejection_clearance_required": True,
            "max_rounds_per_target": int(review.get("max_rounds_per_target", 10)),
            "timeout_seconds": int(review.get("timeout_seconds", 3600))}


def review_policy_sha256(config: Mapping[str, Any]) -> str:
    policy = {k: config[k] for k in ("process", "roles", "referee_roles", "rejection_clearance_required")}
    return _sha256(json.dumps(policy, sort_keys=True).encode())


def unified_enabled(root: str | Path) -> bool:
    """Settings errors propagate: a broken configuration must stop every path, not choose one."""
    return review_config(root)["process"] == PROCESS


def require_legacy_review_allowed(root: str | Path, action: str) -> None:
    """Refuse every legacy route that could set ``ready`` once the unified process is configured."""
    if unified_enabled(root):
        raise ValueError(
            f"{action} is disabled: quality_gate.review_process is {PROCESS}; "
            "only `review unified-run` can make a paper ready"
        )


# --------------------------------------------------------------------------- manuscript inputs

_INPUT = re.compile(r"\\(?:input|include)\s*\{([^}]+)\}")


def expand_tex(path: Path, base: Path, seen: set[Path] | None = None) -> str:
    seen = seen if seen is not None else set()
    path = path if path.suffix else path.with_suffix(".tex")
    if path in seen or not path.is_file():
        return ""
    seen.add(path)
    out = []
    for line in path.read_text(errors="replace").splitlines():
        code = re.split(r"(?<!\\)%", line, maxsplit=1)[0]
        cursor = 0
        matches = list(_INPUT.finditer(code))
        if matches:
            for match in matches:
                target = base / match.group(1).strip()
                out.append(code[cursor:match.start()])
                out.append(f"% ---- begin {target.relative_to(base)} ----")
                out.append(expand_tex(target, base, seen))
                out.append(f"% ---- end {target.relative_to(base)} ----")
                cursor = match.end()
            out.append(code[cursor:])
        else:
            out.append(line)
    return "\n".join(out)


def _balanced(text: str, start: int) -> str:
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:index]
    return ""


def front_matter(expanded: str) -> dict[str, str]:
    # Generated scalar results are often zero-argument LaTeX macros. Resolve
    # only literal numbers, never arbitrary commands or executable TeX.
    numeric = dict(re.findall(
        r"\\(?:newcommand|renewcommand|providecommand)\s*\{\\([A-Za-z]+)\}"
        r"\s*\{([-+0-9.,]+)\}", expanded))
    if numeric:
        expanded = re.sub(r"\\([A-Za-z]+)\b",
                          lambda m: numeric.get(m.group(1), m.group(0)), expanded)
    title = ""
    match = re.search(r"\\title(?:\[[^\]]*\])?\s*\{", expanded)
    if match:
        title = _balanced(expanded, match.end() - 1)
    abstract = ""
    env = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", expanded, re.S)
    if env:
        abstract = env.group(1)
    else:
        macro = re.search(r"\\abstract(?:\[[^\]]*\])?\s*\{", expanded)
        if macro:
            abstract = _balanced(expanded, macro.end() - 1)
    sections = [m.start() for m in re.finditer(r"\\section\*?\{", expanded)]
    intro = expanded[sections[0]:sections[1]] if len(sections) >= 2 else expanded[sections[0]:][:20000] if sections else ""
    statements = []
    for m in re.finditer(r"\\begin\{(theorem|proposition|corollary|conjecture)\}(.*?)\\end\{\1\}", expanded, re.S):
        statements.append(f"[{m.group(1)}] {m.group(2).strip()}")
    # Empirical papers express their main findings in sections, not theorem
    # environments. Supply those findings and their information budgets.
    section_matches = list(re.finditer(r"\\section\*?\{([^}]+)\}", expanded))
    methods = []
    for i, match in enumerate(section_matches):
        end = section_matches[i + 1].start() if i + 1 < len(section_matches) else len(expanded)
        body = expanded[match.start():end]
        heading = match.group(1).lower()
        if re.search(r"\b(results?|findings?|experiments?|empirical|numerical)\b", heading):
            statements.append(body)
        if re.search(r"\b(methods?|materials?|experimental setup)\b", heading):
            methods.append(body)
    return {"title": title.strip(), "abstract": abstract.strip(), "introduction": intro.strip(),
            "main_statements": "\n\n".join(statements[:30]),
            "methods": "\n\n".join(methods)}


def bibliography_text(manuscript: Path) -> str:
    expanded = expand_tex(manuscript / 'main.tex', manuscript)
    inline = re.findall(r'\\begin\{thebibliography\}.*?\\end\{thebibliography\}', expanded, re.S)
    if inline:
        return '\n\n'.join(inline)
    bbl = manuscript / "main.bbl"
    if bbl.is_file():
        return bbl.read_text(errors="replace")
    return "\n".join(p.read_text(errors="replace") for p in sorted(manuscript.glob("*.bib")))


def _build(manuscript: Path, workdir: Path) -> tuple[Path, set[str]]:
    copy = workdir / "build"
    shutil.copytree(manuscript, copy, ignore=shutil.ignore_patterns(
        '*.aux', '*.blg', '*.fdb_latexmk', '*.fls', '*.log', '*.out',
        '*.synctex.gz', '*.toc', '*.spl', '__pycache__'))
    proc = subprocess.run(["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error", "main.tex"],
                          cwd=copy, capture_output=True, text=True, timeout=1800)
    (workdir / "build.log").write_text(proc.stdout[-20000:] + proc.stderr[-5000:])
    if proc.returncode != 0 or not (copy / "main.pdf").is_file():
        raise ValueError(f"LaTeX build failed; see {workdir / 'build.log'}")
    used = set()
    for line in (copy / "main.fls").read_text(errors="replace").splitlines():
        if line.startswith("INPUT ") and not line[6:].startswith("/"):
            used.add(os.path.normpath(line[6:].removeprefix("./")))
    blg = copy / "main.blg"
    if blg.is_file():
        for name in re.findall(r"(?:Database file #\d+|The style file): (\S+)", blg.read_text(errors="replace")):
            used.add(os.path.normpath(name))
    return copy / "main.pdf", used


def standalone_document_files(manuscript: Path) -> set[str]:
    """Files read by other top-level documents (supplement, title page) built separately from main.tex."""
    seen: set[Path] = set()
    for path in sorted(manuscript.glob("*.tex")):
        if path.name != "main.tex" and re.search(r"^\s*\\documentclass", path.read_text(errors="replace"), re.M):
            expand_tex(path, manuscript, seen)
    return {item.relative_to(manuscript).as_posix() for item in seen}


def unused_source_files(manuscript: Path, used: set[str]) -> list[str]:
    unused = []
    for path in sorted(manuscript.rglob("*")):
        rel = path.relative_to(manuscript)
        if not path.is_file() or path.suffix.lower() not in CLEAN_SOURCE_SUFFIXES or rel.as_posix() == "main.tex":
            continue
        if rel.as_posix() == "references.bib":
            continue  # canonical bibliography record read by support-check, even with an inline bibliography
        if rel.parts[0].lower() in {"supplement", "supplementary", "supplements", "support-materials", "build"}:
            continue
        if rel.as_posix() not in used and rel.with_suffix("").as_posix() not in used:
            unused.append(rel.as_posix())
    return unused


def preflight(paper_id: str, root: Path, workdir: Path) -> dict[str, Any]:
    """Deterministic checks; no model is started when any blocker is found."""
    from paper_writing.manuscript_style import audit_manuscript_style, manuscript_style_blockers
    from paper_writing.operations import _review_workspace_fingerprints
    from paper_writing.support_citations import audit_manuscript_support, support_audit_blockers

    load_registry(root, include_local_repositories=False, paper_ids=[paper_id])  # target-policy validation
    metadata = load_paper_metadata(paper_id, root)
    blockers: list[str] = []
    if str(metadata.get("venue_type") or "journal") != "journal":
        blockers.append("The unified review currently supports journal manuscripts only")
    target = str(metadata.get("target_journal") or "")
    fit = metadata.get("target_journal_fit") or {}
    if not target or not isinstance(fit, Mapping) or fit.get("status") != "approved":
        blockers.append("A verified target journal with an approved fit record is required")
    manuscript = root / str(metadata.get("manuscript_dir") or f"papers/{paper_id}/manuscript")
    pdf, used = _build(manuscript, workdir)
    canonical = root / str(metadata.get("latest_pdf") or f"papers/{paper_id}/manuscript/main.pdf")
    shutil.copyfile(pdf, canonical)
    fresh_bbl = pdf.with_suffix(".bbl")
    if fresh_bbl.is_file():
        # A stale committed .bbl would reach referees and the journal source package.
        shutil.copyfile(fresh_bbl, manuscript / "main.bbl")
    supplement = metadata.get("latest_supplementary_pdf")
    if supplement:  # a registered supplementary document is built separately and is part of the package
        used.add((root / str(supplement)).with_suffix(".tex").relative_to(manuscript).as_posix())
    used |= standalone_document_files(manuscript)
    unused = unused_source_files(manuscript, used)
    if unused:
        blockers.append("Source files not read by the build would enter the journal package: " + ", ".join(unused[:12]))
    style = audit_manuscript_style(paper_id, root=root, require_ai_declaration=True)
    blockers.extend(manuscript_style_blockers(style))
    blockers.extend(support_audit_blockers(audit_manuscript_support(paper_id, root=root)))
    fingerprints = _review_workspace_fingerprints(paper_id, metadata, root)
    expanded = expand_tex(manuscript / "main.tex", manuscript)
    return {"blockers": blockers, "fingerprints": fingerprints, "expanded": expanded,
            "bibliography": bibliography_text(manuscript), "metadata": metadata, "target": target}


# --------------------------------------------------------------------------- packets

def prior_decisions(paper_id: str, metadata: Mapping[str, Any], root: Path | None = None) -> list[dict[str, Any]]:
    """Editorial decisions on this paper: registry rejections, enriched from the management site when available."""
    rows = {(r.get("journal"), r.get("manuscript_number")): {
        "journal": str(r.get("journal")), "manuscript_number": str(r.get("manuscript_number")),
        "date": str(r.get("rejected_at")), "editor_letter_summary": str(r.get("reason_summary") or ""),
        "source": r.get("source"), "summary_kind": "internal paraphrase; not the original letter"}
        for field in ("journal_rejections", "prior_conference_rejections", "prior_unidentified_journal_rejections")
        for r in metadata.get(field) or [] if isinstance(r, Mapping)}
    url, key = os.environ.get("ARA_PAPER_MANAGE_API_URL"), os.environ.get("ARA_PAPER_MANAGE_API_KEY")
    if url and key:
        try:
            import httpx
            data = httpx.get(f"{url.rstrip('/')}/v1/papers/{paper_id}", headers={"Authorization": f"Bearer {key}"},
                             timeout=60).json()
            data = data.get("data", data)
            attempts = {a["id"]: a for a in data.get("submission_attempts", [])}
            for event in data.get("submission_events", []):
                attempt = attempts.get(event.get("attempt_id"), {})
                if event.get("event_type") != "rejected":
                    continue
                k = (attempt.get("journal_name"), attempt.get("manuscript_number"))
                row = rows.setdefault(k, {"journal": str(k[0]), "manuscript_number": str(k[1]),
                                          "date": str(event.get("occurred_at", ""))[:10]})
                summary = (event.get("payload") or {}).get("reason_summary") or ""
                row["editor_letter_summary"] = summary
                row["summary_kind"] = "internal paraphrase of the decision letter" if summary else "not available"
        except Exception:  # noqa: BLE001 - the site is optional context, the registry is authoritative
            pass
    bindings = metadata.get("journal_rejection_letters") or []
    for row in rows.values():
        row["decision_id"] = _sha256(json.dumps([row['journal'], row['manuscript_number']], ensure_ascii=False).encode())[:20]
        row["letter_text"] = ""
        row["letter_available"] = False
        binding = next((b for b in bindings if b.get("journal") == row["journal"]
                        and str(b.get("manuscript_number")) == row["manuscript_number"]), {})
        source = binding.get("path") or row.get("source")
        if root and source:
            path = (root / str(source)).resolve()
            # Decision letters may be in the sibling private mailbox-maintenance store.
            allowed = path.is_relative_to(root.resolve()) or path.is_relative_to(root.parent / "maintenance")
            if allowed and path.is_file() and path.stat().st_size <= 2_000_000:
                raw = path.read_bytes()
                if binding.get("sha256") and binding["sha256"] != _sha256(raw):
                    raise ValueError(f"Rejection letter changed: {source}")
                text = ""
                if path.suffix == ".json":
                    obj = json.loads(raw)
                    obj = obj if isinstance(obj, dict) else {}
                    text = obj.get("body") or obj.get("letter_text") or ""
                    if not text:
                        text = "\n".join(p.get("text", "") for p in obj.get("parts", [])
                                         if p.get("content_type") == "text/plain")
                elif binding.get("kind") == "verbatim_decision_letter":
                    text = raw.decode(errors="replace")
                if isinstance(text, str) and text.strip():
                    row.update(letter_text=text, letter_available=True, letter_source=str(source),
                               source_sha256=_sha256(raw), letter_sha256=_sha256(text.encode()))
    return sorted(rows.values(), key=lambda r: r["date"])


def rejection_clearance_blockers(editor: Mapping[str, Any], decisions: list[dict[str, Any]]) -> list[str]:
    """No send-to-review may silently omit or contradict a sourced previous rejection."""
    reports = editor.get("prior_rejections_addressed") or []
    blockers = []
    expected = {d["decision_id"] for d in decisions}
    if len(reports) != len(decisions) or {r.get("decision_id") for r in reports} != expected:
        blockers.append("The editor did not address each distinct prior rejection exactly once")
    for d in decisions:
        r = next((r for r in reports if r.get("decision_id") == d["decision_id"]), {})
        if not d.get("letter_available"):
            blockers.append(f"Original rejection letter unavailable: {d['journal']} {d['manuscript_number']}")
        if r.get("journal") != d["journal"] or not str(r.get("evidence") or "").strip():
            blockers.append(f"Missing located rejection-response evidence: {d['decision_id']}")
        if r.get("judgment") not in {"resolved", "compatible"}:
            blockers.append(f"Previous rejection not overcome or compatible: {d['decision_id']}")
        if r.get("judgment") == "resolved" and r.get("answered") is not True:
            blockers.append(f"Contradictory rejection assessment: {d['decision_id']}")
    return blockers


def rejection_context_blockers(record: Mapping[str, Any], metadata: Mapping[str, Any], root: Path) -> list[str]:
    """A later historical refusal or changed letter invalidates an earlier clearance."""
    bound = record.get('prior_decisions', [])
    ids = {d['decision_id'] for d in bound}
    blockers = []
    for key in ('journal_rejections', 'prior_conference_rejections', 'prior_unidentified_journal_rejections'):
        for r in metadata.get(key, []):
            identity = _sha256(json.dumps([str(r['journal']), str(r.get('manuscript_number'))],
                                         ensure_ascii=False).encode())[:20]
            if identity not in ids:
                blockers.append('Rejection history changed after the independent editorial screen')
    for d in bound:
        if d.get('letter_available'):
            path = root / str(d.get('letter_source') or '')
            if not path.is_file() or _sha256(path.read_bytes()) != d.get('source_sha256'):
                blockers.append(f"The screened original letter is missing or changed: {d['decision_id']}")
    return blockers


def _target_block(metadata: Mapping[str, Any]) -> str:
    fit = metadata.get("target_journal_fit") or {}
    recent = "\n".join(f"- {u}" for u in fit.get("recent_article_sources") or [])
    return (f"Journal: {metadata.get('target_journal')}\n"
            f"Official journal page: {metadata.get('target_journal_source')}\n"
            f"CAS 2025 major-category zone: {metadata.get('target_journal_tier')}\n"
            f"Recent topically related articles in this journal:\n{recent}\n"
            f"Recorded target fit evidence (author-supplied; assess critically):\n"
            f"{json.dumps(fit, ensure_ascii=False, indent=2)}")


def editor_packet(pre: Mapping[str, Any], decisions: list[dict[str, Any]]) -> str:
    parts = front_matter(pre["expanded"])
    letters = json.dumps(decisions, ensure_ascii=False, indent=2) if decisions else "No prior rejections recorded."
    return (f"## Target journal\n{_target_block(pre['metadata'])}\n\n"
            f"## Prior editorial decisions on this paper\n{letters}\n\n"
            f"## Title\n{parts['title']}\n\n## Abstract\n{parts['abstract']}\n\n"
            f"## Introduction\n{parts['introduction']}\n\n## Statements of the main results\n{parts['main_statements']}\n\n"
            f"## Methods and information budgets\n{parts['methods']}\n\n"
            f"## Reference list\n{pre['bibliography']}\n")


def support_description(metadata: Mapping[str, Any], root: Path) -> str:
    files = ((metadata.get("support") or {}).get("publication") or {}).get("source_files") or []
    texts = []
    for rel in files:
        if Path(rel).name in {"README.md", "CLAIMS.yaml", "REPRODUCE.md"}:
            texts.append(f"### {Path(rel).name}\n{(root / rel).read_text(errors='replace')}")
    # Paths relative to the package root, so directories such as verification/ stay visible.
    base = os.path.commonpath([str(Path(f).parent) for f in files]) if files else ""
    listing = "\n".join(f"- {os.path.relpath(f, base) if base else f}" for f in files)
    locations = "\n".join(f"- {(root / f).resolve()}" for f in files)
    return ("\n\n".join(texts) + f"\n\nFiles in the supporting materials:\n{listing}"
            + "\n\nRegistered material locations (read-only inspection is permitted):\n"
            + locations + "\nInspect only these scientific materials; private preparation notes are not review inputs.")


def referee_packet(pre: Mapping[str, Any], root: Path, previous: Mapping[str, Any] | None,
                   decisions: list[dict[str, Any]] | None = None) -> str:
    metadata = pre['metadata']
    mapping = root / str(metadata.get('evidence_dir') or f"papers/{metadata.get('paper_id')}/evidence") / 'claim_evidence_map.md'
    evidence = mapping.read_text(errors='replace') if mapping.is_file() else '[No canonical claim-evidence map available]'
    text = (f"## Target journal\n{_target_block(pre['metadata'])}\n\n"
            f"## Manuscript (LaTeX, all inputs expanded)\n{pre['expanded']}\n\n"
            f"## Bibliography\n{pre['bibliography']}\n\n"
            f"## Claim-evidence map\n{evidence}\n\n"
            f"## Supporting materials\n{support_description(pre['metadata'], root)}\n")
    manuscript = root / str(metadata.get('manuscript_dir') or f"papers/{metadata.get('paper_id')}/manuscript")
    supplement = metadata.get('latest_supplementary_pdf')
    supplement_path = (root / str(supplement)).with_suffix('.tex') if supplement else manuscript / 'supplementary.tex'
    if supplement_path.is_file():
        text += ("\n## Supplementary material (LaTeX, all inputs expanded)\n"
                 + expand_tex(supplement_path, manuscript) + "\n")
    if decisions:
        text += ("\n## Original historical refusal context\n"
                 "These are the original sourced letters, independent of this round's editor verdict. "
                 "Check previous requests against these current documents; do not assume an old "
                 "missing-letter diagnosis still holds when the original is now supplied.\n"
                 + json.dumps(decisions, ensure_ascii=False, indent=2) + "\n")
    if previous:
        text += (f"\n## Previous round\nDecision letter:\n{previous['letter']}\n\n"
                 f"Items to check:\n" + "\n".join(f"- {i}" for i in previous["items"]) +
                 f"\n\nAuthors' response:\n{previous['response']}\n\n"
                 f"Source changes since the previous round (unified diff):\n{previous['diff']}\n")
    return text


# --------------------------------------------------------------------------- merge

def merge(editor: Mapping[str, Any], referees: Mapping[str, Mapping[str, Any]],
          history_blockers: list[str] | None = None, *,
          previous_ids: set[str] | None = None) -> dict[str, Any]:
    """Conservative deterministic merge. It can only make the outcome stricter."""
    # Compatibility with the earlier numbered-item API; the current pipeline
    # supplies rejection blockers as a list and constrains exact mandatory items
    # in the referee schema before merging.
    if isinstance(history_blockers, set):
        if previous_ids is not None:
            raise ValueError("Previous item IDs supplied twice")
        previous_ids, history_blockers = history_blockers, None
    if history_blockers:
        return {"outcome": "rejection_history_blocked", "recommendation": None,
                "scientific_blockers": history_blockers, "required_changes": [],
                "next_action": "evidence_remediation"}
    if editor["decision"] != "send_to_review":
        category = editor["desk_reject_category"]
        if editor["decision"] == "revise_before_submission" or category == "presentation":
            action = "text_revision"
        elif category in {"scope", "readership"}:
            action = "retarget_required"
        else:
            action = "evidence_remediation"
        return {"outcome": editor["decision"], "recommendation": None, "scientific_blockers": [],
                "required_changes": [], "next_action": action}
    if not referees:
        raise ValueError("A send-to-review decision requires the configured referee panel")
    rec = max((r["recommendation"] for r in referees.values()), key=RECOMMENDATIONS.index)
    blockers = sorted({b for r in referees.values() for b in r["scientific_blockers"]})
    changes = [dict(c, referee=name) for name, r in referees.items() for c in r["required_changes"]]
    unresolved_previous = [dict(p, referee=name) for name, r in referees.items()
                           for p in r["previous_items"] if not p["resolved"]
                           and (previous_ids is None or str(p.get("id", "")).strip("[] ") in previous_ids)]
    types = {c["type"] for c in changes}
    ready = (rec in {"accept", "minor_revision"} and not blockers and types <= {"text"}
             and not unresolved_previous)
    if ready:
        action = None
    elif blockers or "evidence" in types or rec == "reject":
        action = "evidence_remediation"
    else:
        action = "text_revision"
    return {"outcome": "ready" if ready else "revision_required", "recommendation": rec,
            "scientific_blockers": blockers, "required_changes": changes,
            "unresolved_previous_items": unresolved_previous, "next_action": action}


# --------------------------------------------------------------------------- runs

def runs_dir(root: Path, paper_id: str) -> Path:
    return root / "reviews" / "unified" / paper_id


def completed_rounds(root: Path, paper_id: str, target: str) -> list[dict[str, Any]]:
    rows = []
    base = runs_dir(root, paper_id)
    for path in sorted(base.glob("*/decision.json")) if base.is_dir() else []:
        record = json.loads(path.read_text())
        if record.get("target_journal") == target:
            rows.append(record | {"_path": path})
    return rows


def _previous_round(root: Path, paper_id: str, target: str, expanded: str, response: str | None):
    rounds = [r for r in completed_rounds(root, paper_id, target) if r.get("stage_reached") == "decision"]
    if not rounds:
        return None
    last = rounds[-1]
    if not response:
        raise ValueError("A re-review requires the authors' response letter (--response)")
    old = (last["_path"].parent / "manuscript-expanded.tex").read_text()
    diff = "".join(difflib.unified_diff(old.splitlines(True), expanded.splitlines(True), "previous", "current", n=2))
    items = list(last["merged"].get("scientific_blockers", [])) + [
        f"[{c['type']}] {c['change']} ({c['location']})" for c in last["merged"].get("required_changes", [])]
    return {"letter": last.get("letter", ""), "items": items, "response": response, "diff": diff[:400000]}


def referee_schema_for_previous(previous: Mapping[str, Any] | None) -> dict[str, Any]:
    """Only the previous decision's mandatory items belong in resolution tracking.

    Optional suggestions remain visible in the letter, but cannot turn into blockers
    merely because a referee lists them as unimplemented previous items.
    """
    schema = json.loads(json.dumps(REFEREE_SCHEMA))
    items = list(previous['items']) if previous else []
    array = schema['properties']['previous_items']
    array['minItems'] = array['maxItems'] = len(items)
    if items:
        array['items']['properties']['item']['enum'] = items
    return schema


def run_review(paper_id: str, *, root: str | Path, response_letter: str | Path | None = None,
               apply: bool = True) -> dict[str, Any]:
    root = Path(root).resolve()
    config = review_config(root)
    if config["process"] != PROCESS:
        raise ValueError(f"quality_gate.review_process must be {PROCESS}")
    roles = config["roles"]
    panel = config["referee_roles"]
    if {"editor", *panel} - set(roles):
        raise ValueError("settings review.roles must define editor and every active referee")
    if roles["editor"].get("provider") != "openai-codex":
        raise ValueError("The editorial screen must use an independent Codex process")
    if len(panel) == 2 and roles[panel[0]].get("model") == roles[panel[1]].get("model"):
        raise ValueError("The two referees must use different models")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run = runs_dir(root, paper_id) / run_id
    run.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="unified-build-") as tmp:
        try:
            pre = preflight(paper_id, root, Path(tmp))
        finally:
            log = Path(tmp) / 'build.log'
            if log.is_file():
                shutil.copyfile(log, run / 'preflight-build.log')
    metadata, target = pre["metadata"], pre["target"]
    (run / "manuscript-expanded.tex").write_text(pre["expanded"])
    record: dict[str, Any] = {"schema_version": "openlabs.review.decision.v1", "process": PROCESS,
                              "paper_id": paper_id, "run_id": run_id, "target_journal": target,
                              "target_journal_tier": metadata.get("target_journal_tier"),
                              "manuscript_version": str(metadata.get("version") or ""),
                              "fingerprints": pre["fingerprints"], "started_at": _now()}
    record |= {"review_policy_sha256": review_policy_sha256(config), "active_referee_roles": panel,
               "single_referee_panel": len(panel) == 1}
    if pre["blockers"]:
        record |= {"stage_reached": "preflight", "merged": {"outcome": "preflight_failed",
                   "preflight_blockers": pre["blockers"], "next_action": "text_revision"}}
        _json_dump(run / "decision.json", record)
        return record | {"run_dir": str(run.relative_to(root))}
    rounds = [r for r in completed_rounds(root, paper_id, target) if r.get("stage_reached") == "decision"]
    if len(rounds) >= config["max_rounds_per_target"]:
        raise ValueError(f"{paper_id} has used all {config['max_rounds_per_target']} review rounds for {target}; "
                         "a user decision (retarget, more research, or stop) is required")
    response = Path(response_letter).read_text() if response_letter else None
    previous = _previous_round(root, paper_id, target, pre["expanded"], response)
    if response:
        (run / "response-letter.md").write_text(response)

    decisions = prior_decisions(paper_id, metadata, root)
    _json_dump(run / "prior-decisions.json", decisions)
    editor, editor_receipt = run_role(role_name="editor", role=roles["editor"],
                                      system_prompt=(PROMPTS / "editor.md").read_text(),
                                      user_prompt=editor_packet(pre, decisions), schema=EDITOR_SCHEMA,
                                      workdir=run / "editor", timeout=config["timeout_seconds"])
    referees: dict[str, Any] = {}
    receipts = {"editor": editor_receipt}
    history_blockers = rejection_clearance_blockers(editor, decisions)
    if editor["decision"] == "send_to_review" and not history_blockers:
        packet = referee_packet(pre, root, previous, decisions)
        schema = referee_schema_for_previous(previous)
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(panel)) as pool:
            futures = {name: pool.submit(run_role, role_name=name, role=roles[name],
                                         system_prompt=(PROMPTS / "referee.md").read_text(), user_prompt=packet,
                                         schema=schema, workdir=run / name,
                                         timeout=config["timeout_seconds"])
                       for name in panel}
            for name, future in futures.items():
                referees[name], receipts[name] = future.result()
                expected = set(previous['items']) if previous else set()
                if {i['item'] for i in referees[name]['previous_items']} != expected:
                    raise ValueError('Referee omitted or introduced a previous mandatory item')
    merged = merge(editor, referees, history_blockers)
    letter_packet = json.dumps({"fixed_decision": merged, "editor_screen": editor, "referee_reports": referees},
                               indent=2, ensure_ascii=False)
    letter, letter_receipt = run_role(role_name="decision_letter", role=roles["editor"],
                                      system_prompt=(PROMPTS / "decision.md").read_text(), user_prompt=letter_packet,
                                      schema=LETTER_SCHEMA, workdir=run / "decision-letter",
                                      timeout=config["timeout_seconds"])
    receipts["decision_letter"] = letter_receipt
    record |= {"stage_reached": "decision", "round_for_target": len(rounds) + 1, "editor_screen": editor,
               "referee_reports": referees, "merged": merged, "letter": letter["letter"], "receipts": receipts,
               "prior_decisions": decisions, "editorial_history_blockers": history_blockers,
               "previous_required_items": list(previous['items']) if previous else [],
               "same_provider_panel": len({roles[n]["provider"] for n in panel}) == 1,
               "finished_at": _now()}
    digest = _json_dump(run / "decision.json", record)
    if apply:
        apply_decision(paper_id, root=root, decision_path=run / "decision.json", digest=digest)
    return record | {"run_dir": str(run.relative_to(root)), "decision_sha256": digest}


def apply_decision(paper_id: str, *, root: Path, decision_path: Path, digest: str) -> dict[str, Any]:
    from paper_writing.operations import _review_workspace_fingerprints

    record = json.loads(decision_path.read_text())
    if _sha256(decision_path.read_bytes()) != digest:
        raise ValueError("Decision record changed after it was written")
    config = review_config(root)
    if record.get("review_policy_sha256") != review_policy_sha256(config):
        raise ValueError("Review policy changed; rerun the review")
    if record['merged']['outcome'] == 'ready':
        panel = config['referee_roles']
        if set(record.get('referee_reports', {})) != set(panel):
            raise ValueError("Ready decision is missing an active referee")
        blockers = rejection_clearance_blockers(record['editor_screen'], record.get('prior_decisions', []))
        if merge(record['editor_screen'], record['referee_reports'], blockers)['outcome'] != 'ready':
            raise ValueError("Ready decision contradicts the editor, rejection letters, or referees")
    metadata = load_paper_metadata(paper_id, root)
    if rejection_context_blockers(record, metadata, root):
        raise ValueError('Rejection history or original letter changed during the review; rerun')
    fingerprints = _review_workspace_fingerprints(paper_id, metadata, root)
    if fingerprints != record["fingerprints"]:
        raise ValueError("Manuscript, registry or support sources changed during the review; rerun")
    merged = record["merged"]
    max_rounds = review_config(root)["max_rounds_per_target"]
    status = ("ready" if merged["outcome"] == "ready" else
              "blocked" if record.get("round_for_target", 0) >= max_rounds or merged["next_action"] == "retarget_required"
              else "revision_required")
    publication = ((metadata.get("support") or {}).get("publication") or {})
    scores = [r["scores"]["overall"] for r in record.get("referee_reports", {}).values()]
    release = {
        "status": status, "review_process": PROCESS, "venue_type": "journal",
        "target_journal": record["target_journal"], "decision": merged.get("recommendation") or merged["outcome"],
        "editor_decision": record["editor_screen"]["decision"], "next_action": merged["next_action"],
        "score": min(scores) if scores else None, "score_role": "informational",
        "rounds_for_target": record.get("round_for_target"), "max_rounds_per_target": max_rounds,
        "reviewed_at": record["finished_at"], "manuscript_version": record["manuscript_version"],
        "decision_record": decision_path.relative_to(root).as_posix(), "decision_record_sha256": digest,
        **{k: v for k, v in fingerprints.items() if v is not None},
    }
    if re.fullmatch(r"[0-9a-f]{64}", str(publication.get("package_sha256") or "")):
        release["support_package_sha256"] = publication["package_sha256"]
    if merged.get("scientific_blockers"):
        release["unresolved_review_blockers"] = merged["scientific_blockers"]
    metadata["writing_release"] = release
    metadata["status_updated_at"] = _now()
    write_paper_metadata(paper_id, metadata, root)
    return release


def validate_unified_release(paper_id: str, metadata: Mapping[str, Any], root: Path, snapshot: str) -> list[str]:
    """Handoff check: the ready release must come from a bound, unchanged unified decision."""
    release = metadata.get("writing_release") or {}
    problems = []
    if release.get("review_process") != PROCESS:
        return ["The release was not produced by the unified review process; rerun `review unified-run`"]
    path = root / str(release.get("decision_record") or "")
    if not path.is_file() or _sha256(path.read_bytes()) != release.get("decision_record_sha256"):
        return ["The unified decision record is missing or changed"]
    record = json.loads(path.read_text())
    config = review_config(root)
    if record.get("review_policy_sha256") != review_policy_sha256(config):
        problems.append("Review policy changed after this decision; a fresh review is required")
    if set(record.get('referee_reports', {})) != set(config['referee_roles']):
        problems.append("The decision does not contain the configured referee panel")
    if rejection_clearance_blockers(record['editor_screen'], record.get('prior_decisions', [])):
        problems.append("The original rejection letters were not cleared by the independent editor")
    problems.extend(rejection_context_blockers(record, metadata, root))
    if record.get("merged", {}).get("outcome") != "ready" or record["editor_screen"]["decision"] != "send_to_review":
        problems.append("The unified decision is not a ready decision")
    if record["fingerprints"]["manuscript_snapshot_sha256"] != snapshot:
        problems.append("Manuscript changed after the unified review")
    if record.get("target_journal") != metadata.get("target_journal"):
        problems.append("Target journal changed after the unified review")
    return problems


def calibration(root: str | Path) -> list[dict[str, Any]]:
    """Compare unified editor decisions with real journal outcomes on the management site (read-only)."""
    import httpx

    root = Path(root).resolve()
    url, key = os.environ["ARA_PAPER_MANAGE_API_URL"], os.environ["ARA_PAPER_MANAGE_API_KEY"]
    rows = []
    for paper_dir in sorted((root / "reviews" / "unified").glob("*")) if (root / "reviews" / "unified").is_dir() else []:
        data = httpx.get(f"{url.rstrip('/')}/v1/papers/{paper_dir.name}",
                         headers={"Authorization": f"Bearer {key}"}, timeout=60).json()
        data = data.get("data", data)
        for decision in sorted(paper_dir.glob("*/decision.json")):
            record = json.loads(decision.read_text())
            attempts = [a for a in data.get("submission_attempts", []) if a.get("journal_name") == record.get("target_journal")
                        and str(a.get("submitted_at") or "") > str(record.get("finished_at") or "")]
            rows.append({"paper_id": paper_dir.name, "run": decision.parent.name, "target": record.get("target_journal"),
                         "internal_editor": (record.get("editor_screen") or {}).get("decision"),
                         "internal_outcome": record.get("merged", {}).get("outcome"),
                         "external": [a.get("status") for a in attempts] or ["not submitted"]})
    return rows
