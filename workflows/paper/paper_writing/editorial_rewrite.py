"""Editor-facing rewrite pass: abstract, Introduction and closing section only.

User decision 2026-11-07, based on the blind rewrite experiment of the same day:

* rewriting the opening and closing for the target venue's editor clearly beat the
  original in every model, while GPT-6.1-sol and Opus-5.5 tied overall;
* every model judge strongly preferred its own model's text (4/5 each).

So the pass runs every configured rewriter in a fresh, empty process, then lets judges
from *both* model families compare the original and all candidates blind, in a random
order unknown to them.  A candidate replaces the original only when

1. it passes the deterministic checks (no new citation keys, labels kept, references
   resolve, no sectioning commands, length within tolerance);
2. no judge reports a major fidelity issue for it;
3. every judge ranks it above the original;
4. every judge clears the absolute editorial floors and complete-manuscript readiness.

Keeping the original is a pass only when it also clears the absolute checks. Approvals
bind every reachable TeX source and bibliography file, not just the three edited parts.

and among the surviving candidates the lowest summed rank wins (self-preference is
symmetric when both families judge), then fewer fidelity issues, then the higher mean
overall score.  Nothing here edits the manuscript unless ``apply`` is called on a run
whose source files are unchanged.  The unified review then reviews the rewritten text.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Mapping

from paper_writing.registry import load_paper_metadata, load_registry_settings, settings_path
from paper_writing.review_launcher import LaunchError, run_role

PARTS = ("abstract", "introduction", "closing")
VOICE_DIMENSIONS = ("naturalness", "restraint", "clarity", "venue_fit")
MIN_EDITORIAL_SCORE = 7
_END = r"(?=\\section\*?\{|\\appendix\b|\\begin\{appendix\}|\\bibliography\{|\\printbibliography|\\end\{document\}|\Z)"
_CITE = re.compile(r"\\[A-Za-z]*cite[A-Za-z]*\*?(?:\s*\[[^\]]*\])*\s*\{([^}]*)\}")
_LABEL = re.compile(r"\\label\{([^}]*)\}")
_REF = re.compile(r"\\(?:[cC]ref|[aA]utoref|eqref|ref|pageref)\*?\{([^}]*)\}")
_BIBKEY = re.compile(r"@[A-Za-z]+\s*\{\s*([^,\s]+)\s*,")
_BIBITEM = re.compile(r"\\bibitem(?:\[[^\]]*\])?\{([^}]*)\}")
DEFAULT_ROLES = {
    "gpt": {"provider": "openai-codex", "tool": "Codex", "model": "gpt-6.1-sol"},
    "opus": {"provider": "anthropic", "tool": "Claude Code", "model": "claude-opus-5-5"},
}

WRITER_SYSTEM = """You are an experienced researcher in the manuscript's field. You revise only the
abstract, the Introduction and the closing section of a manuscript before it goes to a
journal or conference editor. You never invent results, data, numbers or references."""

WRITER_TASK = """# Task: rewrite three parts of a manuscript for {venue}

Rewrite ONLY these parts: {targets}. Everything else stays exactly as it is, and your text must
fit it.{closing_note}

Rules:
- Use only facts, results, numbers, definitions and citations that appear in the manuscript.
  Every \\cite key you use must already occur in the manuscript. Keep every \\label{{...}} the
  original part defines: {labels}.
- Stay accurate to the evidence. Do not overstate generality, causality or significance.
- Write for the readers of {venue}: the question, why it matters to them, the main result and
  how it compares with the closest prior work. State necessary limitations once, in one place,
  instead of qualifying every sentence. Do not narrate the authors' workflow, verification
  history, versions, replications of internal checks or review rounds.
- Keep each part within about ±{tolerance}% of its current length ({words}).
- Return LaTeX bodies only: no \\section commands, no \\begin{{abstract}}, no preamble.

Previous editorial decisions on this paper (context only):
{rejections}

## Full manuscript (LaTeX, all inputs expanded)

{manuscript}
"""

JUDGE_SYSTEM = """You are an experienced editor and referee. You compare alternative versions of a
manuscript's opening and closing blind and judge only what is on the page."""

JUDGE_TASK = """# Blind editorial comparison for {venue}

{count} alternative versions ({labels}) of the {targets} of the same
manuscript are given below, with the rest of the manuscript (those parts omitted). They are in
random order and you are not told who or what wrote them. Judge each as the opening and closing of
THIS manuscript for THIS venue.

Score each version with integers 1-10 (10 best):
- naturalness: reads like an experienced human researcher; 1 = conspicuously machine-generated
  prose (stock phrasing, formulaic structure, mechanical enumerations);
- restraint: limitations stated once and proportionately; 1 = pervasive defensive hedging and
  repeated qualification;
- clarity: the question, main result and advance over the closest prior work are clear;
- venue_fit: framed for this venue's readership and level;
- overall: which you would rather see in a submission to this venue.
Also give send_to_review_probability (0-100) for the paper opening and closing with that version.

Fidelity check (most important): compare every claim, number and citation in each version with
the manuscript body. List each overstatement, unsupported claim, wrong number, invented citation
or misrepresentation (severity "major" if it would mislead a reader about what the paper shows).
Over-claiming is worse than hedging. Rank all versions from best to worst.

For EACH version also assess the COMPLETE manuscript, combining that version with the body.
Set editorial_ready=true only when no substantial presentation repair remains anywhere:
the contribution and argument are recoverable, prose is concrete rather than formulaic,
limitations are proportionate without repetitive defensive qualifications, and internal
workflow/revision dialogue is absent. Preserve necessary hypotheses, uncertainty, negative
results, reproducibility methods and truthful AI disclosures. List located actionable defects
in editorial_blockers; an empty list and all four editorial scores >=7 are required to pass.
Relative improvement alone is insufficient. Do not predict actual editorial acceptance.

{versions}
## Manuscript body (the rewritten parts are omitted)

{body}
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _sha(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def manuscript_sources(manuscript: Path) -> dict[str, str]:
    """Bind all reachable TeX and bibliography files, including changes outside rewritten parts."""
    files = set(_tex_files(manuscript)) | set(manuscript.rglob("*.bib"))
    return {p.relative_to(manuscript).as_posix(): _sha(p.read_bytes()) for p in sorted(files)}


def editorial_problems(scores: Mapping[str, Any]) -> list[str]:
    problems = [f"{name} below {MIN_EDITORIAL_SCORE}" for name in VOICE_DIMENSIONS
                if scores.get(name, 0) < MIN_EDITORIAL_SCORE]
    if scores.get("editorial_ready") is not True:
        problems.append("complete manuscript needs presentation repair")
    problems.extend(str(item) for item in scores.get("editorial_blockers", []))
    return problems


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


# --------------------------------------------------------------------------- configuration

def rewrite_config(root: Path) -> dict[str, Any]:
    settings = load_registry_settings(root) if settings_path(root).is_file() else {}
    raw = dict((settings.get("quality_gate") or {}).get("editorial_rewrite") or {})
    rewriters = raw.get("rewriters") or DEFAULT_ROLES
    judges = raw.get("judges") or DEFAULT_ROLES
    for group in (rewriters, judges):
        if not isinstance(group, Mapping) or not group:
            raise ValueError("editorial_rewrite rewriters/judges must be non-empty mappings")
    if len({str(role.get("provider")) for role in judges.values()}) < 2:
        raise ValueError("editorial_rewrite judges must come from at least two model families "
                         "(a single family prefers its own text)")
    return {"enabled": bool(raw.get("enabled", True)), "required": bool(raw.get("required", False)),
            "required_from": _date(raw.get("required_from")),
            "rewriters": {str(k): dict(v) for k, v in rewriters.items()},
            "judges": {str(k): dict(v) for k, v in judges.items()},
            "length_tolerance": float(raw.get("length_tolerance", 0.25)),
            "length_hard_limit": float(raw.get("length_hard_limit", 0.5)),
            "timeout_seconds": int(raw.get("timeout_seconds", 3600))}


def runs_dir(root: Path, paper_id: str) -> Path:
    return root / "reviews" / "editorial-rewrite" / paper_id


def target_of(metadata: Mapping[str, Any]) -> str:
    if str(metadata.get("venue_type") or "journal") == "conference":
        return str(metadata.get("target_conference") or "")
    return str(metadata.get("target_journal") or "")


def _target_checked(metadata: Mapping[str, Any]) -> date | None:
    key = "target_conference_checked_at" if metadata.get("target_conference") else "target_journal_checked_at"
    return _date(metadata.get(key))


# --------------------------------------------------------------------------- source parts

@dataclass(frozen=True)
class Part:
    name: str
    file: str
    start: int
    end: int
    heading: str
    body: str


_INCLUDE = re.compile(r"\\(?:input|include|subfile)\s*\{([^}]+)\}")
_BACKMATTER = re.compile(r"availability|declaration|disclosure|funding|acknowledg|competing|contribution|ethic|"
                         r"conflict|appendix|supplement", re.I)
_CLOSING = re.compile(r"conclu|discussion|outlook|summary|remarks|implication|future work", re.I)


def _resolve(manuscript: Path, name: str) -> Path | None:
    path = manuscript / name.strip()
    path = path if path.suffix else path.with_suffix(".tex")
    return path if path.is_file() and manuscript in path.resolve().parents else None


def _tex_files(manuscript: Path) -> list[Path]:
    """Files reachable from main.tex via \\input/\\include, in document order."""
    order: list[Path] = []

    def walk(path: Path) -> None:
        if path in order:
            return
        order.append(path)
        for m in _INCLUDE.finditer(_uncommented(path.read_text(errors="replace"))):
            child = _resolve(manuscript, m.group(1))
            if child is not None:
                walk(child)

    main = manuscript / "main.tex"
    if main.is_file():
        walk(main)
    return order


def _uncommented(text: str) -> str:
    """Blank out comments (keeping offsets) so commented-out drafts are never matched."""
    return re.sub(r"(?<!\\)%[^\n]*", lambda m: " " * len(m.group(0)), text)


def _sole_include(manuscript: Path, body: str) -> Path | None:
    m = re.fullmatch(r"\s*\\(?:input|include)\s*\{([^}]+)\}\s*", body)
    return _resolve(manuscript, m.group(1)) if m else None


def _brace_end(text: str, open_at: int) -> int | None:
    depth = 0
    for index in range(open_at, len(text)):
        if text[index] == "{" and text[index - 1] != "\\":
            depth += 1
        elif text[index] == "}" and text[index - 1] != "\\":
            depth -= 1
            if depth == 0:
                return index
    return None


def _part(manuscript: Path, name: str, rel: str, text: str, start: int, end: int, heading: str) -> Part:
    body = text[start:end]
    included = _sole_include(manuscript, _uncommented(body))
    if included is not None:  # e.g. \begin{abstract}\input{abstract}\end{abstract}
        whole = included.read_text(errors="replace")
        return Part(name, included.relative_to(manuscript).as_posix(), 0, len(whole), heading, whole)
    return Part(name, rel, start, end, heading, body)


def locate_parts(manuscript: Path) -> dict[str, Part]:
    """Abstract and Introduction are required; the closing section is optional."""
    abstracts: list[Part] = []
    sections: list[tuple[str, Part]] = []
    for path in _tex_files(manuscript):
        text = path.read_text(errors="replace")
        clean = _uncommented(text)
        rel = path.relative_to(manuscript).as_posix()
        for m in re.finditer(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", clean, re.S):
            abstracts.append(_part(manuscript, "abstract", rel, text, m.start(1), m.end(1), ""))
        for m in re.finditer(r"\\abstract\s*\{", clean):
            close = _brace_end(clean, m.end() - 1)
            if close is not None:
                abstracts.append(_part(manuscript, "abstract", rel, text, m.end(), close, ""))
        backmatter_from = re.search(r"\\appendix\b|\\begin\{appendix\}|\\backmatter\b", clean)
        for m in re.finditer(r"\\section\*?\{([^}]*)\}[^\n]*\n?(.*?)" + _END, clean, re.S):
            if backmatter_from and m.start() > backmatter_from.start():
                break
            sections.append((m.group(1), _part(manuscript, "section", rel, text, m.start(2), m.end(2), m.group(1))))
    if len(abstracts) != 1:
        raise ValueError(f"Expected exactly one abstract in the manuscript sources, found {len(abstracts)}")
    body = [(title, part) for title, part in sections if not _BACKMATTER.search(title)]
    intro = [(t, p) for t, p in body if re.match(r"\s*introduction", t, re.I)]
    if len(intro) != 1:
        raise ValueError(f"Expected exactly one Introduction section, found {len(intro)}")
    closing = [(t, p) for t, p in body if _CLOSING.search(t) and p is not intro[0][1]]
    parts = {"abstract": abstracts[0],
             "introduction": Part("introduction", *[getattr(intro[0][1], f) for f in ("file", "start", "end", "heading", "body")])}
    if closing:
        last = closing[-1][1]
        parts["closing"] = Part("closing", last.file, last.start, last.end, last.heading, last.body)
    for name, part in parts.items():
        if re.search(r"\\(?:input|include|subfile)\b", _uncommented(part.body)):
            raise ValueError(f"The {name} pulls in other files; rewrite it by hand")
    return parts


def _words(text: str) -> int:
    return len(_uncommented(text).split())


def _keys(pattern: re.Pattern[str], text: str) -> set[str]:
    return {k.strip() for group in pattern.findall(_uncommented(text)) for k in group.split(",") if k.strip()}


def bibliography_keys(manuscript: Path, expanded: str) -> set[str]:
    keys = _keys(_CITE, expanded) | set(_BIBITEM.findall(expanded))
    for bib in manuscript.rglob("*.bib"):
        keys |= set(_BIBKEY.findall(bib.read_text(errors="replace")))
    for bbl in manuscript.rglob("*.bbl"):
        keys |= set(_BIBITEM.findall(bbl.read_text(errors="replace")))
    return keys


def candidate_problems(candidate: Mapping[str, str], parts: Mapping[str, Part], *, expanded: str,
                       known_keys: set[str], tolerance: float) -> list[str]:
    """Deterministic checks that need no model."""
    problems = []
    labels = _keys(_LABEL, expanded)
    for name in parts:
        text, original = candidate[name], parts[name].body
        if re.search(r"\\(?:sub)*section\*?\{|\\begin\{abstract\}|\\documentclass|\\(?:input|include)\b", text):
            problems.append(f"{name}: contains sectioning, abstract environment or file inclusion")
        new_keys = _keys(_CITE, text) - known_keys
        if new_keys:
            problems.append(f"{name}: citation keys not in the manuscript: {sorted(new_keys)}")
        lost = _keys(_LABEL, original) - _keys(_LABEL, text)
        if lost:
            problems.append(f"{name}: drops labels defined by the original: {sorted(lost)}")
        duplicate = (_keys(_LABEL, text) - _keys(_LABEL, original)) & labels
        if duplicate:
            problems.append(f"{name}: labels already defined elsewhere: {sorted(duplicate)}")
        unresolved = _keys(_REF, text) - labels - _keys(_LABEL, text)
        if unresolved:
            problems.append(f"{name}: references to unknown labels: {sorted(unresolved)}")
        before, after = _words(original), _words(text)
        if before and abs(after - before) / before > tolerance:
            problems.append(f"{name}: length {after} words vs {before} (limit ±{tolerance:.0%})")
    return problems


# --------------------------------------------------------------------------- prompts and schemas

WRITER_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["abstract", "introduction", "closing", "change_notes"],
    "properties": {"abstract": {"type": "string", "minLength": 1},
                   "introduction": {"type": "string", "minLength": 1},
                   "closing": {"type": "string"},
                   "change_notes": {"type": "string"}},
}


def judge_schema(labels: list[str]) -> dict[str, Any]:
    score = {"type": "integer", "minimum": 1, "maximum": 10}
    issue = {"type": "object", "additionalProperties": False, "required": ["quote", "problem", "severity"],
             "properties": {"quote": {"type": "string"}, "problem": {"type": "string"},
                            "severity": {"type": "string", "enum": ["minor", "major"]}}}
    version = {"type": "object", "additionalProperties": False,
               "required": ["naturalness", "restraint", "clarity", "venue_fit", "overall",
                            "send_to_review_probability", "fidelity_issues", "comments",
                            "editorial_ready", "editorial_blockers"],
               "properties": {"naturalness": score, "restraint": score, "clarity": score, "venue_fit": score,
                              "overall": score,
                              "send_to_review_probability": {"type": "integer", "minimum": 0, "maximum": 100},
                              "fidelity_issues": {"type": "array", "items": issue},
                              "comments": {"type": "string"},
                              "editorial_ready": {"type": "boolean"},
                              "editorial_blockers": {"type": "array", "items": {"type": "string", "minLength": 1}}}}
    return {"type": "object", "additionalProperties": False, "required": ["versions", "ranking", "rationale"],
            "properties": {"versions": {"type": "object", "additionalProperties": False, "required": labels,
                                        "properties": {label: version for label in labels}},
                           "ranking": {"type": "array", "minItems": len(labels), "maxItems": len(labels),
                                       "items": {"type": "string", "enum": labels}},
                           "rationale": {"type": "string"}}}


def _clean(text: str) -> str:
    return re.sub(r"(?<!\\)%[^\n]*", "", text).strip()


def render_version(label: str, version: Mapping[str, str], closing: str | None) -> str:
    text = (f"## Version {label}\n### Abstract\n{_clean(version['abstract'])}\n\n### Introduction\n"
            f"{_clean(version['introduction'])}\n\n")
    if closing:
        text += f"### {closing}\n{_clean(version['closing'])}\n\n"
    return text


def targets_text(closing: str | None) -> str:
    return (f"abstract, the Introduction section and the {closing} section" if closing
            else "abstract and the Introduction section")


def body_without_parts(expanded: str, parts: Mapping[str, Part]) -> str:
    body = expanded
    for name in parts:
        original = parts[name].body.strip()
        if original and original in body:
            body = body.replace(original, f"[{name.upper()} OMITTED]", 1)
    return body


def _rejections(paper_id: str, root: Path) -> str:
    path = root / "registry" / "journal-rejections.json"
    if not path.is_file():
        return "- none"
    rows = [r for r in json.loads(path.read_text()).get("rejections", []) if r.get("paper_id") == paper_id]
    return "\n".join(f"- {r.get('journal')}: {r.get('reason_summary') or '(no reason recorded)'}" for r in rows) or "- none"


# --------------------------------------------------------------------------- selection

def select(original: str, candidates: list[str], judgments: Mapping[str, Mapping[str, Any]],
           keys: Mapping[str, Mapping[str, str]], disqualified: Mapping[str, list[str]]) -> dict[str, Any]:
    """Pure selection rule; ``keys[judge][label] -> version`` unblinds each judgment."""
    table: dict[str, dict[str, Any]] = {v: {"ranks": {}, "overall": {}, "major": 0, "minor": 0,
                                         "editorial_problems": {}}
                                        for v in [original, *candidates]}
    for judge, result in judgments.items():
        mapping = keys[judge]
        order = [mapping[label] for label in result["ranking"]]
        if len(order) != len(mapping) or set(order) != set(mapping.values()):
            raise ValueError("Judge ranking must contain every version exactly once")
        for label, version in mapping.items():
            scores = result["versions"][label]
            row = table[version]
            row["ranks"][judge] = order.index(version) + 1
            row["overall"][judge] = scores["overall"]
            row["editorial_problems"][judge] = editorial_problems(scores)
            issues = scores.get("fidelity_issues") or []
            row["major"] += sum(i.get("severity") == "major" for i in issues)
            row["minor"] += sum(i.get("severity") != "major" for i in issues)
    eligible, reasons = [], {}
    for version in candidates:
        row = table[version]
        why = list(disqualified.get(version, []))
        why.extend(f"{judge}: {problem}" for judge, problems in row["editorial_problems"].items()
                   for problem in problems)
        if row["major"]:
            why.append(f"{row['major']} major fidelity issue(s) reported")
        beaten = [j for j in judgments if row["ranks"][j] > table[original]["ranks"][j]]
        if beaten:
            why.append("ranked below the original by " + ", ".join(sorted(beaten)))
        if why:
            reasons[version] = why
        else:
            eligible.append(version)

    def order(version: str) -> tuple[float, int, float]:
        row = table[version]
        return (sum(row["ranks"].values()), row["minor"], -sum(row["overall"].values()) / len(row["overall"]))

    eligible.sort(key=order)
    selected = eligible[0] if eligible else original
    ready = bool(judgments) and not table[selected]["major"] and not any(
        table[selected]["editorial_problems"].values())
    return {"selected": selected, "editorial_ready": ready, "eligible_ranked": eligible,
            "rejected_candidates": reasons, "table": table,
            "rule": "unanimously above original, no major fidelity issue, deterministic checks pass; "
                    "absolute editorial floors and complete-manuscript readiness; "
                    "then lowest summed rank, fewer fidelity issues, higher mean overall"}


# --------------------------------------------------------------------------- run / apply

def run_rewrite(paper_id: str, *, root: str | Path, rewriters: list[str] | None = None,
                runner=run_role) -> dict[str, Any]:
    from paper_writing.review_flow import expand_tex

    root = Path(root).resolve()
    config = rewrite_config(root)
    if not config["enabled"]:
        raise ValueError("quality_gate.editorial_rewrite is disabled")
    metadata = load_paper_metadata(paper_id, root)
    venue = target_of(metadata)
    if not venue:
        raise ValueError(f"{paper_id} has no registered target venue")
    manuscript = root / str(metadata.get("manuscript_dir") or f"papers/{paper_id}/manuscript")
    parts = locate_parts(manuscript)
    expanded = expand_tex(manuscript / "main.tex", manuscript)
    known = bibliography_keys(manuscript, expanded)
    tolerance = int(round(config["length_tolerance"] * 100))
    labels = {n: sorted(_keys(_LABEL, p.body)) for n, p in parts.items()}
    words = ", ".join(f"{n} ≈ {_words(p.body)} words" for n, p in parts.items())
    closing = parts["closing"].heading if "closing" in parts else None
    writer_prompt = WRITER_TASK.format(
        venue=venue, targets="the " + targets_text(closing), tolerance=tolerance, words=words,
        closing_note="" if closing else " Return an empty string for the closing field.",
        labels=json.dumps(labels, ensure_ascii=False), rejections=_rejections(paper_id, root), manuscript=expanded)
    chosen = rewriters or list(config["rewriters"])
    unknown = set(chosen) - set(config["rewriters"])
    if unknown:
        raise ValueError(f"Unknown rewriter(s): {sorted(unknown)}")

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run = runs_dir(root, paper_id) / run_id
    run.mkdir(parents=True)
    sources = manuscript_sources(manuscript)
    record: dict[str, Any] = {
        "schema_version": "openlabs.editorial_rewrite.v1", "paper_id": paper_id, "run_id": run_id,
        "target": venue, "manuscript_version": str(metadata.get("version") or ""), "started_at": _now(),
        "source_sha256": sources, "parts": {n: {"file": p.file, "heading": p.heading, "words": _words(p.body)}
                                             for n, p in parts.items()},
        "rewriters": {k: config["rewriters"][k] for k in chosen}, "judges": config["judges"]}
    record["outcome"] = "in_progress"
    _finish(run, root, record)
    versions: dict[str, dict[str, str]] = {"original": {n: p.body.strip() for n, p in parts.items()}}
    receipts: dict[str, Any] = {}
    failures: dict[str, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(chosen)) as pool:
        futures = {name: pool.submit(runner, role_name=f"rewriter_{name}", role=config["rewriters"][name],
                                     system_prompt=WRITER_SYSTEM, user_prompt=writer_prompt, schema=WRITER_SCHEMA,
                                     workdir=run / f"rewriter-{name}", timeout=config["timeout_seconds"])
                   for name in chosen}
        for name, future in futures.items():
            try:
                output, receipts[f"rewriter_{name}"] = future.result()
                versions[name] = {n: str(output[n]).strip() for n in parts}
            except (LaunchError, ValueError, OSError) as exc:
                failures[name] = str(exc)
    candidates = [name for name in chosen if name in versions]
    disqualified = {name: candidate_problems(versions[name], parts, expanded=expanded, known_keys=known,
                                             tolerance=config["length_hard_limit"])
                    for name in candidates}
    record |= {"rewriter_failures": failures, "deterministic_problems": disqualified}
    (run / "versions.json").write_text(json.dumps(versions, ensure_ascii=False, indent=1) + "\n")
    if not candidates:
        record |= {"outcome": "rewrite_failed", "selection": None, "receipts": receipts, "finished_at": _now()}
        return _finish(run, root, record)

    body = body_without_parts(expanded, parts)
    rng = secrets.SystemRandom()
    keys: dict[str, dict[str, str]] = {}
    judgments: dict[str, Any] = {}
    names = ["original", *candidates]
    labels_all = [f"V{i + 1}" for i in range(len(names))]
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(config["judges"])) as pool:
        futures = {}
        for judge, role in config["judges"].items():
            order = names[:]
            rng.shuffle(order)
            keys[judge] = dict(zip(labels_all, order))
            prompt = JUDGE_TASK.format(
                venue=venue, count=len(order), labels=", ".join(labels_all), targets=targets_text(closing),
                versions="".join(render_version(l, versions[v], closing) for l, v in keys[judge].items()), body=body)
            futures[judge] = pool.submit(runner, role_name=f"judge_{judge}", role=role, system_prompt=JUDGE_SYSTEM,
                                         user_prompt=prompt, schema=judge_schema(labels_all),
                                         workdir=run / f"judge-{judge}", timeout=config["timeout_seconds"])
        for judge, future in futures.items():
            try:
                judgments[judge], receipts[f"judge_{judge}"] = future.result()
            except (LaunchError, ValueError, OSError) as exc:
                record |= {"outcome": "judge_failed", "judge_failure": {judge: str(exc)},
                           "receipts": receipts, "finished_at": _now()}
                return _finish(run, root, record)
    selection = select("original", candidates, judgments, keys, disqualified)
    record |= {"blind_keys": keys, "judgments": judgments, "selection": selection, "receipts": receipts,
               "outcome": ("editorial_failed" if not selection["editorial_ready"] else
                           "candidate_selected" if selection["selected"] != "original" else "original_kept"),
               "finished_at": _now()}
    return _finish(run, root, record)


def _finish(run: Path, root: Path, record: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
    (run / "record.json").write_text(text)
    return record | {"run_dir": run.relative_to(root).as_posix(), "record_sha256": _sha(text)}


def apply_rewrite(paper_id: str, *, root: str | Path, run_dir: str | Path) -> dict[str, Any]:
    """Write the selected candidate into the source files if they are unchanged since the run."""
    root = Path(root).resolve()
    run = (root / run_dir).resolve()
    if runs_dir(root, paper_id).resolve() not in run.parents:
        raise ValueError("run_dir is not an editorial-rewrite run of this paper")
    record = json.loads((run / "record.json").read_text())
    if (run / "applied.json").exists():
        raise ValueError("This rewrite run was already applied")
    if record.get("outcome") != "candidate_selected":
        raise ValueError("No candidate was selected; the original stays")
    metadata = load_paper_metadata(paper_id, root)
    if target_of(metadata) != record["target"]:
        raise ValueError("Target venue changed since the rewrite run")
    manuscript = root / str(metadata.get("manuscript_dir") or f"papers/{paper_id}/manuscript")
    if manuscript_sources(manuscript) != record["source_sha256"]:
        raise ValueError("Manuscript sources changed after the rewrite run; run the pass again")
    chosen = json.loads((run / "versions.json").read_text())[record["selection"]["selected"]]
    parts = locate_parts(manuscript)
    by_file: dict[str, list[Part]] = {}
    for part in parts.values():
        by_file.setdefault(part.file, []).append(part)
    for rel, rows in by_file.items():
        path = manuscript / rel
        text = path.read_text(errors="replace")
        for part in sorted(rows, key=lambda p: p.start, reverse=True):
            new = chosen[part.name].strip()
            new = "\n" + new + "\n" if part.name == "abstract" else new + "\n\n"
            text = text[:part.start] + new + text[part.end:]
        path.write_text(text)
    applied = {"applied_at": _now(), "selected": record["selection"]["selected"],
               "files": manuscript_sources(manuscript)}
    (run / "applied.json").write_text(json.dumps(applied, indent=2) + "\n")
    return applied


def latest_record(root: Path, paper_id: str, target: str) -> dict[str, Any] | None:
    base = runs_dir(root, paper_id)
    for path in sorted(base.glob("*/record.json"), reverse=True) if base.is_dir() else []:
        record = json.loads(path.read_text())
        if record.get("target") == target:
            record["_applied"] = (path.parent / "applied.json").is_file()
            record["_run_dir"] = path.parent.relative_to(root).as_posix()
            return record
    return None


def preflight_blockers(metadata: Mapping[str, Any], root: Path, paper_id: str) -> list[str]:
    """Unified-review preflight: new targets need a finished rewrite pass for that target."""
    try:
        config = rewrite_config(root)
    except ValueError as exc:
        return [f"Editorial rewrite configuration: {exc}"]
    if not (config["enabled"] and config["required"]):
        return []
    checked = _target_checked(metadata)
    if config["required_from"] and (checked is None or checked < config["required_from"]):
        return []
    target = target_of(metadata)
    record = latest_record(root, paper_id, target)
    if record is None:
        return [f"Run the editor-facing rewrite pass for {target} first (`paper-writing rewrite run {paper_id}`)"]
    if record.get("outcome") not in {"candidate_selected", "original_kept"} or not (
            record.get("selection") or {}).get("editorial_ready"):
        return ["Editorial rewrite has not passed absolute, complete-manuscript presentation checks; rerun after repair"]
    if record["outcome"] == "candidate_selected" and not record["_applied"]:
        return [f"Apply or supersede the selected rewrite in {record['_run_dir']} before the unified review"]
    run = root / record["_run_dir"]
    expected = (json.loads((run / "applied.json").read_text()).get("files")
                if record["outcome"] == "candidate_selected" else record.get("source_sha256"))
    manuscript = root / str(metadata.get("manuscript_dir") or f"papers/{paper_id}/manuscript")
    if not expected or manuscript_sources(manuscript) != expected:
        return ["Manuscript sources changed since editorial approval; rerun the editor-facing rewrite pass"]
    return []
