"""Unified editor-and-referee review: the only path to ``writing_release.status: ready``.

Stages: deterministic preflight -> editor screen at the named target journal ->
two blind referees on different models -> deterministic merge plus an editor's
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
            "type": "object", "additionalProperties": False, "required": ["journal", "concern", "answered", "evidence"],
            "properties": {"journal": _TEXT, "concern": _TEXT, "answered": {"type": "boolean"}, "evidence": _TEXT}}},
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
    return {"process": gate.get("review_process"), "roles": review.get("roles") or {},
            "max_rounds_per_target": int(review.get("max_rounds_per_target", 10)),
            "timeout_seconds": int(review.get("timeout_seconds", 3600))}


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
        match = _INPUT.search(code)
        if match:
            target = base / match.group(1).strip()
            out.append(code[:match.start()])
            out.append(f"% ---- begin {target.relative_to(base)} ----")
            out.append(expand_tex(target, base, seen))
            out.append(f"% ---- end {target.relative_to(base)} ----")
            out.append(code[match.end():])
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
    return {"title": title.strip(), "abstract": abstract.strip(), "introduction": intro.strip(),
            "main_statements": "\n\n".join(statements[:30])}


def bibliography_text(manuscript: Path) -> str:
    bbl = manuscript / "main.bbl"
    if bbl.is_file():
        return bbl.read_text(errors="replace")
    return "\n".join(p.read_text(errors="replace") for p in sorted(manuscript.glob("*.bib")))


def _build(manuscript: Path, workdir: Path) -> tuple[Path, set[str]]:
    copy = workdir / "build"
    shutil.copytree(manuscript, copy)
    proc = subprocess.run(["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error", "main.tex"],
                          cwd=copy, capture_output=True, text=True, errors="replace", timeout=1800)
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

def prior_decisions(paper_id: str, metadata: Mapping[str, Any]) -> list[dict[str, str]]:
    """Editorial decisions on this paper: registry rejections, enriched from the management site when available."""
    rows = {(r.get("journal"), r.get("manuscript_number")): {
        "journal": str(r.get("journal")), "manuscript_number": str(r.get("manuscript_number")),
        "date": str(r.get("rejected_at")), "editor_letter_summary": "", "summary_kind": "not available"}
        for r in metadata.get("journal_rejections") or [] if isinstance(r, Mapping)}
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
    return sorted(rows.values(), key=lambda r: r["date"])


def _target_block(metadata: Mapping[str, Any]) -> str:
    fit = metadata.get("target_journal_fit") or {}
    recent = "\n".join(f"- {u}" for u in fit.get("recent_article_sources") or [])
    return (f"Journal: {metadata.get('target_journal')}\n"
            f"Official journal page: {metadata.get('target_journal_source')}\n"
            f"CAS 2025 major-category zone: {metadata.get('target_journal_tier')}\n"
            f"Recent topically related articles in this journal:\n{recent}")


def editor_packet(pre: Mapping[str, Any], decisions: list[dict[str, str]]) -> str:
    parts = front_matter(pre["expanded"])
    letters = "\n".join(
        f"- {d['journal']} ({d['manuscript_number']}, {d['date']}): "
        f"{d['editor_letter_summary'] or '[no text available]'} [{d['summary_kind']}]" for d in decisions) or "- none"
    return (f"## Target journal\n{_target_block(pre['metadata'])}\n\n"
            f"## Prior editorial decisions on this paper\n{letters}\n\n"
            f"## Title\n{parts['title']}\n\n## Abstract\n{parts['abstract']}\n\n"
            f"## Introduction\n{parts['introduction']}\n\n## Statements of the main results\n{parts['main_statements']}\n\n"
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
    return "\n\n".join(texts) + f"\n\nFiles in the supporting materials:\n{listing}"


def referee_packet(pre: Mapping[str, Any], root: Path, previous: Mapping[str, Any] | None) -> str:
    text = (f"## Target journal\n{_target_block(pre['metadata'])}\n\n"
            f"## Manuscript (LaTeX, all inputs expanded)\n{pre['expanded']}\n\n"
            f"## Bibliography\n{pre['bibliography']}\n\n"
            f"## Supporting materials\n{support_description(pre['metadata'], root)}\n")
    if previous:
        text += (f"\n## Previous round\nDecision letter:\n{previous['letter']}\n\n"
                 f"Items to check:\n" + "\n".join(f"- {i}" for i in previous["items"]) +
                 f"\n\nAuthors' response:\n{previous['response']}\n\n"
                 f"Source changes since the previous round (unified diff):\n{previous['diff']}\n")
    return text


# --------------------------------------------------------------------------- merge

def merge(editor: Mapping[str, Any], referees: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Conservative deterministic merge. It can only make the outcome stricter."""
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
    rec = max((r["recommendation"] for r in referees.values()), key=RECOMMENDATIONS.index)
    blockers = sorted({b for r in referees.values() for b in r["scientific_blockers"]})
    changes = [dict(c, referee=name) for name, r in referees.items() for c in r["required_changes"]]
    unresolved_previous = [dict(p, referee=name) for name, r in referees.items()
                           for p in r["previous_items"] if not p["resolved"]]
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


def run_review(paper_id: str, *, root: str | Path, response_letter: str | Path | None = None,
               apply: bool = True) -> dict[str, Any]:
    root = Path(root).resolve()
    config = review_config(root)
    if config["process"] != PROCESS:
        raise ValueError(f"quality_gate.review_process must be {PROCESS}")
    roles = config["roles"]
    if set(ROLES) - set(roles):
        raise ValueError(f"settings review.roles must define {ROLES}")
    if roles["referee_a"].get("model") == roles["referee_b"].get("model"):
        raise ValueError("The two referees must use different models")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run = runs_dir(root, paper_id) / run_id
    run.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="unified-build-") as tmp:
        pre = preflight(paper_id, root, Path(tmp))
    metadata, target = pre["metadata"], pre["target"]
    (run / "manuscript-expanded.tex").write_text(pre["expanded"])
    record: dict[str, Any] = {"schema_version": "openlabs.review.decision.v1", "process": PROCESS,
                              "paper_id": paper_id, "run_id": run_id, "target_journal": target,
                              "target_journal_tier": metadata.get("target_journal_tier"),
                              "manuscript_version": str(metadata.get("version") or ""),
                              "fingerprints": pre["fingerprints"], "started_at": _now()}
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

    decisions = prior_decisions(paper_id, metadata)
    _json_dump(run / "prior-decisions.json", decisions)
    editor, editor_receipt = run_role(role_name="editor", role=roles["editor"],
                                      system_prompt=(PROMPTS / "editor.md").read_text(),
                                      user_prompt=editor_packet(pre, decisions), schema=EDITOR_SCHEMA,
                                      workdir=run / "editor", timeout=config["timeout_seconds"])
    referees: dict[str, Any] = {}
    receipts = {"editor": editor_receipt}
    if editor["decision"] == "send_to_review":
        packet = referee_packet(pre, root, previous)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = {name: pool.submit(run_role, role_name=name, role=roles[name],
                                         system_prompt=(PROMPTS / "referee.md").read_text(), user_prompt=packet,
                                         schema=REFEREE_SCHEMA, workdir=run / name,
                                         timeout=config["timeout_seconds"])
                       for name in ("referee_a", "referee_b")}
            for name, future in futures.items():
                referees[name], receipts[name] = future.result()
    merged = merge(editor, referees)
    letter_packet = json.dumps({"fixed_decision": merged, "editor_screen": editor, "referee_reports": referees},
                               indent=2, ensure_ascii=False)
    letter, letter_receipt = run_role(role_name="decision_letter", role=roles["editor"],
                                      system_prompt=(PROMPTS / "decision.md").read_text(), user_prompt=letter_packet,
                                      schema=LETTER_SCHEMA, workdir=run / "decision-letter",
                                      timeout=config["timeout_seconds"])
    receipts["decision_letter"] = letter_receipt
    record |= {"stage_reached": "decision", "round_for_target": len(rounds) + 1, "editor_screen": editor,
               "referee_reports": referees, "merged": merged, "letter": letter["letter"], "receipts": receipts,
               "same_provider_panel": roles["referee_a"]["provider"] == roles["referee_b"]["provider"],
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
    metadata = load_paper_metadata(paper_id, root)
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
