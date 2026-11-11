"""Unified editor-and-referee review: the only path to ``writing_release.status: ready``.

Stages: deterministic preflight -> editor screen at the named target journal ->
mandatory reference/prerequisite verification -> configured blind referee panel
-> deterministic merge plus an editor's
decision letter. Revisions re-enter the same stages with the authors' response
letter and the cumulative source diff. Models judge; this module only prepares
inputs, runs isolated processes, validates records, merges (only scientific substance blocks) and
binds the result to the exact manuscript snapshot.
"""
from __future__ import annotations

import concurrent.futures
import copy
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
from paper_writing.review_launcher import LaunchError, role_runtime, run_role
from paper_writing import formal_checks

PROCESS = "unified_v1"
RECOMMENDATIONS = ("accept", "minor_revision", "major_revision", "reject")
EDITOR_DECISIONS = ("send_to_review", "revise_before_submission", "desk_reject")
DESK_CATEGORIES = ("scope", "significance", "readership", "novelty_unclear", "presentation", "incremental", "none")
CHANGE_TYPES = ("text", "claim_narrowing", "evidence")
# Desk-reject categories that no amount of manuscript polishing answers: the
# automated orchestrator must choose a direction instead of remediating text.
DIRECTION_CATEGORIES = ("significance", "incremental")
DIRECTION_OPTIONS = ("targeted_core_analysis", "retarget_or_short_format", "freeze")
# stalled: significance and novelty did not rise over this many consecutive round
# transitions (current plus the two preceding refereed rounds).
STALL_TRANSITIONS = 2
ROLES = ("editor", "referee_a", "referee_b")
# Optional cheaper role for the mechanical reference/core-mathematics verification.
# Absent, the editor's model runs it (the behaviour before this role existed).
FORMAL_ROLE = "formal_verifier"
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
                 "optional_suggestions", "previous_items", "confidence", "formal_check_assessment"],
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
            "type": "object", "additionalProperties": False,
            "required": ["change", "type", "location", "main_claim"],
            "properties": {"change": _TEXT, "type": {"type": "string", "enum": list(CHANGE_TYPES)}, "location": _TEXT,
                           # True when the item concerns a headline conclusion (title, abstract,
                           # stated main result). Only then can claim_narrowing block readiness.
                           "main_claim": {"type": "boolean"}}}},
        "optional_suggestions": _TEXT_LIST,
        "previous_items": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["item", "resolved", "evidence"],
            "properties": {"item": _TEXT, "resolved": {"type": "boolean"}, "evidence": _TEXT}}},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "formal_check_assessment": formal_checks.object_schema({
            "coverage_complete": {"type": "boolean"}, "omissions_or_errors": _TEXT_LIST}),
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
    cross = review.get("cross_model") or {}
    if not isinstance(cross, Mapping):
        raise ValueError("review.cross_model must be a mapping")
    previous = review.get("previous_panels") or []
    if not isinstance(previous, list) or any(
            not isinstance(p, Mapping) or not isinstance(p.get("roles"), Mapping)
            or not isinstance(p.get("referee_roles"), list) or not _parse_time(p.get("valid_for_reviews_started_before"))
            for p in previous):
        raise ValueError("review.previous_panels entries need roles, referee_roles and valid_for_reviews_started_before")
    roles = review.get("roles") or {}
    if FORMAL_ROLE in roles:
        verifier = roles[FORMAL_ROLE]
        if (not isinstance(verifier, Mapping)
                or any(not isinstance(verifier.get(k), str) or not verifier[k].strip()
                       for k in ("provider", "tool", "model"))):
            raise ValueError(f"review.roles.{FORMAL_ROLE} needs provider, tool and model, like the other roles")
        if verifier["provider"] != "openai-codex":
            raise ValueError(f"review.roles.{FORMAL_ROLE} must use an independent Codex process (provider openai-codex)")
        try:
            role_runtime(verifier)
        except LaunchError as exc:
            raise ValueError(f"review.roles.{FORMAL_ROLE}: {exc}") from exc
    return {"process": gate.get("review_process"), "roles": roles,
            "referee_roles": panel, "rejection_clearance_required": True,
            "max_rounds_per_target": int(review.get("max_rounds_per_target", 10)),
            "timeout_seconds": int(review.get("timeout_seconds", 3600)),
            "writer_model": str(review.get("writer_model") or ""),
            "cross_model_required": bool(cross.get("required", False)),
            "previous_panels": [dict(p) for p in previous]}


def formal_role_name(roles: Mapping[str, Any]) -> str:
    """Which configured role runs the formal verification: the verifier, else the editor."""
    return FORMAL_ROLE if FORMAL_ROLE in roles else "editor"


def formal_role(roles: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The role a formal report must have been produced by under ``roles``.

    Records made under a policy without ``formal_verifier`` (current or a
    ``previous_panels`` entry, see ``policy_for_record``) stay bound to the editor.
    """
    return roles.get(formal_role_name(roles))


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def writer_model(metadata: Mapping[str, Any], config: Mapping[str, Any]) -> str:
    """The model that drafted the manuscript: paper-level record first, then the team default."""
    return str(metadata.get("writer_model") or config.get("writer_model") or "")


def cross_model_blockers(config: Mapping[str, Any], writer: str) -> list[str]:
    """User decision 2026-11-07: the same model must not be the only judge of its own text."""
    if not config.get("cross_model_required"):
        return []
    if not writer:
        return ["review.writer_model (or the paper's writer_model) must name the drafting model"]
    roles = config["roles"]
    independent = [n for n in config["referee_roles"] if roles.get(n, {}).get("model") != writer]
    if not independent:
        return [f"Cross-model review requires an active referee whose model differs from the writer {writer}"]
    if len(config["referee_roles"]) < 2:
        return ["Cross-model review requires two active referees from different model families"]
    return []


def policy_for_record(record: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    """Current config, or the recorded earlier panel a review started under.

    Changing the panel must not silently invalidate decisions made under the panel that was
    configured when they started; those stay bound to the historical panel they used.
    """
    started = _parse_time(record.get("started_at"))
    for panel in config.get("previous_panels", []):
        until = _parse_time(panel["valid_for_reviews_started_before"])
        if started and started < until and list(record.get("active_referee_roles") or []) == list(panel["referee_roles"]):
            return dict(config, roles=dict(panel["roles"]), referee_roles=list(panel["referee_roles"]))
    return dict(config)


def rejection_history_policy(metadata: Mapping[str, Any], root: Path,
                             paper_id: str | None = None) -> dict[str, Any] | None:
    """Validate a paper-scoped user instruction; missing originals remain unknown."""
    policy = metadata.get("missing_rejection_letter_policy")
    if policy is None:
        return None
    identity = paper_id or metadata.get("paper_id")
    if (not isinstance(policy, Mapping) or policy.get("mode") != "available_originals_only"
            or not identity or policy.get("paper_id") != identity):
        raise ValueError("Invalid paper-scoped missing rejection letter policy")
    ids = policy.get("missing_decision_ids")
    if (not isinstance(ids, list)
            or any(not isinstance(i, str) or not re.fullmatch(r"[0-9a-f]{20}", i) for i in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError("Missing-letter policy requires distinct exact decision IDs")
    auth = policy.get("authorization")
    if (not isinstance(auth, Mapping) or not isinstance(auth.get("summary"), str)
            or not auth["summary"].strip()):
        raise ValueError("Missing-letter policy requires explicit user authorization")
    source = auth.get("path")
    digest = auth.get("sha256")
    if (not isinstance(source, str) or not source or "\\" in source
            or Path(source).is_absolute() or ".." in Path(source).parts
            or Path(source).as_posix() != source
            or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
        raise ValueError("Unsafe or unbound missing-letter authorization")
    base = root.resolve()
    path = base / source
    component = base
    for part in Path(source).parts:
        component /= part
        if component.is_symlink():
            raise ValueError("Unsafe missing-letter authorization: symlink")
    if not path.is_file() or path.stat().st_size > 2_000_000 or _sha256(path.read_bytes()) != digest:
        raise ValueError("Missing-letter authorization missing or changed")
    receipt = json.loads(path.read_text())
    if (not isinstance(receipt, Mapping) or receipt.get("schema") != "openlabs.actual_author_instruction.v1"
            or receipt.get("source") != "actual user message in this session"
            or not str(receipt.get("user_text") or "").strip()):
        raise ValueError("Missing-letter policy requires an actual user instruction receipt")
    grant = receipt
    pointer = auth.get("json_pointer")
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("Missing-letter authorization requires a JSON pointer")
    try:
        for token in pointer[1:].split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            grant = grant[int(token)] if isinstance(grant, list) else grant[token]
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise ValueError("Missing-letter authorization pointer does not resolve") from exc
    if (not isinstance(grant, Mapping) or grant.get("mode") != "available_originals_only"
            or not isinstance(grant.get("paper_ids"), list) or identity not in grant["paper_ids"]
            or auth["summary"] != grant.get("authorization")):
        raise ValueError("User authorization does not cover this paper or missing original letters")
    scopes = grant.get("decision_scope")
    scope = [s for s in scopes if isinstance(s, Mapping) and s.get("paper_id") == identity] if isinstance(scopes, list) else []
    if len(scope) != 1 or scope[0].get("missing_decision_ids") != ids:
        raise ValueError("Missing-letter decision scope differs from the actual user receipt")
    return copy.deepcopy(dict(policy))


def review_round_limit_override(metadata: Mapping[str, Any], root: Path,
                                paper_id: str, target: str | None = None) -> dict[str, Any] | None:
    """Accept only an exact, authenticated user grant for this paper and target."""
    policy = metadata.get("review_round_limit_override")
    if policy is None:
        return None
    target = target if target is not None else metadata.get("target_journal")
    if (not isinstance(policy, Mapping) or policy.get("paper_id") != paper_id
            or not isinstance(target, str) or not target.strip()
            or policy.get("target_journal") != target
            or type(policy.get("max_rounds_per_target")) is not int
            or policy["max_rounds_per_target"] < 1):
        raise ValueError("Invalid paper/target-scoped review round limit override")
    auth = policy.get("authorization")
    if (not isinstance(auth, Mapping) or not isinstance(auth.get("summary"), str)
            or not auth["summary"].strip()):
        raise ValueError("Review round limit override requires explicit user authorization")
    source, digest = auth.get("path"), auth.get("sha256")
    if (not isinstance(source, str) or not source or "\\" in source
            or Path(source).is_absolute() or ".." in Path(source).parts
            or Path(source).as_posix() != source
            or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
        raise ValueError("Unsafe or unbound review round limit authorization")
    base = root.resolve()
    path, component = base / source, base
    for part in Path(source).parts:
        component /= part
        if component.is_symlink():
            raise ValueError("Unsafe review round limit authorization: symlink")
    if not path.is_file() or path.stat().st_size > 2_000_000 or _sha256(path.read_bytes()) != digest:
        raise ValueError("Review round limit authorization missing or changed")
    receipt = json.loads(path.read_text())
    if (not isinstance(receipt, Mapping) or receipt.get("schema") != "openlabs.actual_author_instruction.v1"
            or receipt.get("source") != "actual user message in this session"
            or not isinstance(receipt.get("user_text"), str) or not receipt["user_text"].strip()):
        raise ValueError("Review round limit requires an actual user instruction receipt")
    pointer, grant = auth.get("json_pointer"), receipt
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("Review round limit authorization requires a JSON pointer")
    try:
        for token in pointer[1:].split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            grant = grant[int(token)] if isinstance(grant, list) else grant[token]
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise ValueError("Review round limit authorization pointer does not resolve") from exc
    if (not isinstance(grant, Mapping) or grant.get("paper_id") != paper_id
            or grant.get("target_journal") != target
            or type(grant.get("max_rounds_per_target")) is not int
            or grant["max_rounds_per_target"] != policy["max_rounds_per_target"]
            or grant.get("authorization") != auth["summary"]):
        raise ValueError("User authorization does not cover this paper, target and round limit")
    return copy.deepcopy(dict(policy))


def review_policy_sha256(config: Mapping[str, Any], history_policy: Mapping[str, Any] | None = None,
                         round_limit_override: Mapping[str, Any] | None = None, *,
                         formal_policy: Mapping[str, Any] | None = None) -> str:
    policy = {k: config[k] for k in ("process", "roles", "referee_roles", "rejection_clearance_required")}
    policy["formal_check"] = dict(formal_policy) if formal_policy is not None else formal_checks.policy()
    policy['stage_order'] = 'editor_scientific_referee_core_verification_decision'
    if history_policy is not None:
        policy["missing_rejection_letter_policy"] = history_policy
    if round_limit_override is not None:
        policy["review_round_limit_override"] = round_limit_override
    return _sha256(json.dumps(policy, sort_keys=True).encode())


def review_policy_matches(record: Mapping[str, Any], config: Mapping[str, Any], root: Path,
                          history_policy: Mapping[str, Any] | None = None,
                          round_limit_override: Mapping[str, Any] | None = None) -> bool:
    """Whether a decision record was made under the current review policy.

    Records written before formal_checks.POLICY_VERSION embedded the file-hash
    formal policy. They still match when every other policy element is unchanged
    and their bound formal report carries a legacy policy that the current
    version accepts; the formal report itself is fully revalidated elsewhere.
    """
    recorded = record.get("review_policy_sha256")
    if recorded == review_policy_sha256(config, history_policy, round_limit_override):
        return True
    binding = record.get("formal_check")
    legacy = formal_checks.recorded_policy(binding, root) if isinstance(binding, Mapping) else None
    return (legacy is not None and legacy != formal_checks.policy() and formal_checks.policy_accepted(legacy)
            and recorded == review_policy_sha256(config, history_policy, round_limit_override,
                                                 formal_policy=legacy))


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


def _build(manuscript: Path, workdir: Path, *, document: str = "main.tex") -> tuple[Path, set[str]]:
    if Path(document).name != document or Path(document).suffix != ".tex":
        raise ValueError("Build document must be a manuscript-root TeX filename")
    stem = Path(document).stem
    copy = workdir / "build"
    shutil.copytree(manuscript, copy, ignore=shutil.ignore_patterns(
        '*.aux', '*.blg', '*.fdb_latexmk', '*.fls', '*.log', '*.out',
        '*.synctex.gz', '*.toc', '*.spl', '__pycache__'))
    proc = subprocess.run(["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error", document],
                          cwd=copy, capture_output=True, text=True, errors="replace", timeout=1800)
    (workdir / "build.log").write_text(proc.stdout[-20000:] + proc.stderr[-5000:])
    if proc.returncode != 0 or not (copy / (stem + ".pdf")).is_file():
        raise ValueError(f"LaTeX build failed; see {workdir / 'build.log'}")
    used = set()
    for line in (copy / (stem + ".fls")).read_text(errors="replace").splitlines():
        if line.startswith("INPUT ") and not line[6:].startswith("/"):
            used.add(os.path.normpath(line[6:].removeprefix("./")))
    blg = copy / (stem + ".blg")
    if blg.is_file():
        for name in re.findall(r"(?:Database file #\d+|The style file): (\S+)", blg.read_text(errors="replace")):
            used.add(os.path.normpath(name))
    # A class can declare its bibliography style even when the standalone
    # document currently has no citations and BibTeX is therefore not run.
    aux = copy / (stem + ".aux")
    if aux.is_file():
        for name in re.findall(r"\\bibstyle\{([^{}]+)\}", aux.read_text(errors="replace")):
            if (copy / (name + ".bst")).is_file():
                used.add(os.path.normpath(name + ".bst"))
    return copy / (stem + ".pdf"), used


def build_registered_supplement(metadata: Mapping[str, Any], root: Path,
                                manuscript: Path, workdir: Path) -> set[str]:
    """Freshen the scientific SI and collect its actual standalone dependencies."""
    relative = metadata.get("latest_supplementary_pdf")
    if not relative:
        return set()
    pdf = root / str(relative)
    source = pdf.with_suffix(".tex")
    if (pdf.suffix.lower() != ".pdf" or source.parent.resolve() != manuscript.resolve()
            or not source.is_file()):
        raise ValueError("Registered supplementary PDF requires its manuscript-root TeX source")
    fresh_pdf, used = _build(manuscript, workdir / "supplement", document=source.name)
    shutil.copyfile(fresh_pdf, pdf)
    bbl = fresh_pdf.with_suffix(".bbl")
    if bbl.is_file():
        shutil.copyfile(bbl, source.with_suffix(".bbl"))
    return used | {source.name}


def standalone_document_files(manuscript: Path) -> set[str]:
    """Files read by other top-level documents (supplement, title page) built separately from main.tex."""
    seen: set[Path] = set()
    for path in sorted(manuscript.glob("*.tex")):
        if path.name != "main.tex" and re.search(r"^\s*\\documentclass", path.read_text(errors="replace"), re.M):
            expand_tex(path, manuscript, seen)
    return {item.relative_to(manuscript).as_posix() for item in seen}


def expanded_review_documents(manuscript: Path) -> str:
    """Include separately supplied tables and SI without changing journal layout.

    These top-level documents already belong to the preflight source inventory.
    A journal's separate-file requirement must not hide them from the reviewers.
    """
    seen: set[Path] = set()
    text = expand_tex(manuscript / "main.tex", manuscript, seen)
    for path in sorted(manuscript.glob("*.tex")):
        if path in seen or not re.search(r"^\s*\\documentclass", path.read_text(errors="replace"), re.MULTILINE):
            continue
        text += (f"\n\n## Separately supplied manuscript document: {path.name}\n"
                 "This is a separate journal file, not an embedded main-text document.\n"
                 + expand_tex(path, manuscript, seen))
    return text


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


def _preparation_advisory(source: str, code: str, message: str, *, kind: str = "preparation",
                          location: str = "", context: str = "") -> dict[str, Any]:
    item = {"source": source, "kind": kind, "code": code, "location": location, "message": message}
    if context:
        item["context"] = context
    return item


def preflight(paper_id: str, root: Path, workdir: Path) -> dict[str, Any]:
    """Deterministic checks; no model is started when any blocker is found.

    Only what makes a review impossible or meaningless blocks here: a manuscript
    that does not build, missing registration, broken evidence/data hash bindings,
    the user's venue policy (excluded journals, fee-free route, SCIE/zone
    eligibility) and a declared source routed to an absent bibliography key.
    Presentation and preparation findings (internal vocabulary, AI-declaration
    wording, abstract length/person, TODO markers, unused source files,
    support-record identifiers and the pre-review Zenodo draft) are returned as
    ``preparation_advisories``: they never fail the preflight, and the delivery exit
    enforces them (see ``delivery_blockers``). Registered passage selectors and
    local evidence files that no longer match are advisories too; nothing uses them
    since the formal check was narrowed, so the delivery exit only notes them.
    """
    from paper_writing.journal_history import tolerate_stale_ledger

    # Internal review: a stale team rejection ledger is a warning here. Journal
    # selection, retargeting and delivery keep requiring a fresh ledger.
    with tolerate_stale_ledger() as ledger_warnings:
        return _preflight(paper_id, root, workdir, ledger_warnings)


def _preflight(paper_id: str, root: Path, workdir: Path, ledger_warnings: list[str]) -> dict[str, Any]:
    from paper_writing.journal_history import guard_target
    from paper_writing.manuscript_style import audit_manuscript_style, manuscript_style_review_findings
    from paper_writing.operations import _review_workspace_fingerprints
    from paper_writing.support_citations import audit_manuscript_support, support_review_findings

    load_registry(root, include_local_repositories=False, paper_ids=[paper_id])  # target-policy validation
    metadata = load_paper_metadata(paper_id, root)
    guard_target(root, metadata)  # New reviews cannot reuse an excluded historical target.
    blockers: list[str] = []
    advisories: list[dict[str, Any]] = []
    venue_type = str(metadata.get("venue_type") or "journal")
    if venue_type == "conference":
        # CCF-ranked conference targets (policy 2026-11-07); target_journal_fit is the
        # venue-neutral fit record shared with journals.
        target = str(metadata.get("target_conference") or "")
        if not target:
            blockers.append("A verified CCF-ranked target conference is required")
    elif venue_type == "journal":
        target = str(metadata.get("target_journal") or "")
    else:
        target = ""
        blockers.append("The unified review supports journal and conference manuscripts only")
    fit = metadata.get("target_journal_fit") or {}
    if not target or not isinstance(fit, Mapping) or fit.get("status") != "approved":
        blockers.append("A verified target venue with an approved fit record is required")
    manuscript = root / str(metadata.get("manuscript_dir") or f"papers/{paper_id}/manuscript")
    pdf, used = _build(manuscript, workdir)  # a manuscript that does not build stops here
    canonical = root / str(metadata.get("latest_pdf") or f"papers/{paper_id}/manuscript/main.pdf")
    shutil.copyfile(pdf, canonical)
    fresh_bbl = pdf.with_suffix(".bbl")
    if fresh_bbl.is_file():
        # A stale committed .bbl would reach referees and the journal source package.
        shutil.copyfile(fresh_bbl, manuscript / "main.bbl")
    used |= build_registered_supplement(metadata, root, manuscript, workdir)
    used |= standalone_document_files(manuscript)
    unused = unused_source_files(manuscript, used)
    if unused:
        advisories.append(_preparation_advisory(
            "review_flow", "UNUSED-SOURCE-FILES",
            "Source files not read by the build would enter the journal package: " + ", ".join(unused[:12]),
            location=manuscript.relative_to(root).as_posix()))
    style_blockers, style_advice = manuscript_style_review_findings(
        audit_manuscript_style(paper_id, root=root, require_ai_declaration=True))
    blockers.extend(style_blockers)
    advisories.extend(style_advice)
    support_blockers, support_advice = support_review_findings(audit_manuscript_support(paper_id, root=root))
    blockers.extend(support_blockers)
    advisories.extend(support_advice)
    try:
        claim_maps = selected_claim_evidence_maps(metadata, root)
    except ValueError as exc:
        blockers.append(f"Selected support claim-evidence map: {exc}")
        claim_maps = []
    fingerprints = _review_workspace_fingerprints(paper_id, metadata, root)
    expanded = expanded_review_documents(manuscript)
    bibliography = bibliography_text(manuscript)
    try:
        documents, bibliography = formal_checks.current_inputs(metadata, root)
        formal_inventory = formal_checks.inventory(documents, bibliography)
        formal_checks.source_plan(metadata)
        # Only an absent bibliography key still stops the reference verification;
        # stale selectors and local evidence files bind nothing (ADVISORY_ROUTE_KINDS).
        for finding in formal_checks.route_findings(metadata, formal_inventory, root):
            if finding["kind"] in formal_checks.ADVISORY_ROUTE_KINDS:
                advisories.append(_route_advisory(finding))
            else:
                blockers.append(finding["message"])
        for problem in formal_checks.artifact_inventory(metadata, root)['blockers']:
            # A stale or missing journal source archive is a delivery artifact; the
            # handoff rebuilds and verifies it. Every other artifact binds evidence.
            if problem.startswith("Artifact preparation: journal_source_archive:"):
                advisories.append(_preparation_advisory("formal_checks", "JOURNAL-SOURCE-ARCHIVE", problem))
            else:
                blockers.append(problem)
    except (ValueError, OSError) as exc:
        blockers.append(f"Formal-check inventory: {exc}")
        formal_inventory = None
    try:
        revision_context = active_revision_context(metadata, root)
    except ValueError as exc:
        blockers.append(f"Active journal revision context: {exc}")
        revision_context = None
    from paper_writing.editorial_rewrite import (abstract_findings, advisory as rewrite_advisory,
                                                 preflight_blockers as rewrite_blockers)
    blockers.extend(rewrite_blockers(metadata, root, paper_id))
    advisories.extend(_preparation_advisory("editorial_rewrite", "ABSTRACT-VENUE-FORMAT", problem)
                      for problem in abstract_findings(metadata, root, paper_id))
    advisories.extend(_preparation_advisory("journal_history", "LEDGER-STALE", warning, kind="warning")
                      for warning in ledger_warnings)
    try:
        rewrite_advice = rewrite_advisory(metadata, root, paper_id)
    except (ValueError, OSError) as exc:  # advice must never stop the review
        rewrite_advice = {"notes": [f"rewrite record unreadable: {exc}"], "blocking": False}
    return {"blockers": blockers, "fingerprints": fingerprints, "expanded": expanded,
            "editorial_rewrite_advisory": rewrite_advice, "preparation_advisories": advisories,
            "build_inputs": sorted(used),
            "bibliography": bibliography, "metadata": metadata, "target": target,
            "support_claim_evidence_maps": claim_maps, "formal_inventory": formal_inventory,
            "active_revision_context": revision_context,
            "expanded_includes_standalone_documents": True}


ROUTE_ADVISORY_CODES = {"stale_selector": "SOURCE-SELECTOR-STALE",
                        "local_evidence_file": "LOCAL-EVIDENCE-UNBOUND"}


def _route_advisory(finding: Mapping[str, Any]) -> dict[str, Any]:
    """A declared route that no verification or delivery path uses; names source and selector."""
    if finding["kind"] == "stale_selector":
        message = (f"Registered source {finding['route']}: passage selector {finding['selector']!r} matches no "
                   "current manuscript passage. The formal check no longer uses passage selectors; update "
                   "or remove it in formal_check of the paper registration.")
    else:
        message = (f"{finding['message']}. The formal check no longer reads registered local evidence; "
                   "update or remove the entry in formal_check.local_evidence of the paper registration.")
    return _preparation_advisory("formal_checks", ROUTE_ADVISORY_CODES[finding["kind"]], message,
                                 location=str(finding["route"]))


# --------------------------------------------------------------------------- packets

def active_revision_context(metadata: Mapping[str, Any], root: Path | None) -> dict[str, Any] | None:
    """Read bound original reports for an ongoing revision, not a prior refusal.

    An invitation supplies context, never a favorable decision or a gate waiver.
    Keep these records separate from the rejection ledger.
    """
    context = metadata.get('journal_revision_context')
    if context is None:
        return None
    if not isinstance(context, Mapping) or root is None:
        raise ValueError('Active journal revision requires a source-bound context and data root')
    provenance = context.get('provenance')
    if (not isinstance(provenance, Mapping) or provenance.get('authenticated') is not True
            or not isinstance(provenance.get('source'), str) or not provenance['source'].strip()):
        raise ValueError('Active journal revision requires authenticated journal-source provenance')
    followup = metadata.get('submission_followup') or {}
    if (context.get('stage') != 'revision_invited'
            or context.get('journal') != metadata.get('target_journal')
            or context.get('journal') != followup.get('journal')
            or not context.get('manuscript_number')
            or context.get('manuscript_number') != followup.get('manuscript_number')):
        raise ValueError('Active journal revision identity or stage does not match the current follow-up')
    documents = context.get('documents')
    if not isinstance(documents, list) or not documents:
        raise ValueError('Active journal revision has no original documents')
    base = root.resolve()
    loaded = []
    kinds = set()
    for document in documents:
        if (not isinstance(document, Mapping) or 'text' in document
                or document.get('kind') not in {'decision_letter', 'reviewer_report', 'submitted_manuscript_text'}):
            raise ValueError('Active revision documents must be original bound sources, not inline summaries')
        source, digest = document.get('path'), document.get('sha256')
        if (not isinstance(source, str) or not source or '\\' in source
                or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)):
            raise ValueError('Active revision document requires a safe path and SHA256')
        relative = Path(source)
        if (relative.is_absolute() or '..' in relative.parts or relative.as_posix() != source
                or 'reviews' in relative.parts):
            raise ValueError('Active revision document path is unsafe')
        path = base
        for part in relative.parts:
            path /= part
            if path.is_symlink():
                raise ValueError('Active revision document path is unsafe: symlink')
        if not path.is_file() or not path.resolve().is_relative_to(base) or path.stat().st_size > 2_000_000:
            raise ValueError('Active revision original is missing, unsafe or too large')
        raw = path.read_bytes()
        if _sha256(raw) != digest or (document.get('bytes') is not None and document['bytes'] != len(raw)):
            raise ValueError('Active revision original hash or size changed')
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise ValueError('Active revision original must be UTF-8 text') from exc
        if not text.strip():
            raise ValueError('Active revision original is empty')
        kinds.add(document['kind'])
        loaded.append({'kind': document['kind'], 'path': source, 'sha256': digest, 'text': text})
    if not {'decision_letter', 'reviewer_report'} <= kinds:
        raise ValueError('Active revision needs both the actual decision and reviewer report')
    return {'journal': context['journal'], 'manuscript_number': context['manuscript_number'],
            'stage': 'revision_invited', 'documents': loaded}


def _active_revision_packet(pre: Mapping[str, Any]) -> str:
    context = pre.get('active_revision_context')
    if context is None:
        return ''
    return ('## Actual ongoing external journal revision\n'
            'The following are complete source-bound original journal documents, not an author '
            'summary or an internal review verdict. Evaluate the current manuscript and its response '
            'to the actual external objections independently under the same journal standards. '
            'An invitation to revise does not establish acceptance, correctness, novelty or readiness. '
            'The submitted manuscript, if supplied, is a historical baseline, not current numerical evidence.\n'
            + json.dumps(context, ensure_ascii=False, indent=2) + '\n\n'
            + ('## Authors response to the actual external revision\n'
               'This is an author-supplied response, not independent evidence.\n'
               + str(pre['author_response']) + '\n\n' if pre.get('author_response') else ''))


def _prior_review_documents(metadata: Mapping[str, Any], root: Path | None,
                            decisions: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Load authenticated pre-final reports, never as substitutes for refusal letters."""
    documents = metadata.get('journal_prior_review_documents', [])
    if not isinstance(documents, list):
        raise ValueError('Historical expert report bindings must be a list')
    if documents and root is None:
        raise ValueError('Historical expert reports require a data root')
    allowed = {(d.get('journal'), d.get('manuscript_number')) for d in decisions}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    seen: set[tuple[str, str, str]] = set()
    base = root.resolve() if root is not None else None
    for document in documents:
        if not isinstance(document, Mapping):
            raise ValueError('Malformed historical expert report binding')
        if 'text' in document or 'text_sha256' in document:
            raise ValueError('Historical expert report text must come from the bound file')
        journal, number = document.get('journal'), document.get('manuscript_number')
        if (not isinstance(journal, str) or not journal.strip()
                or not isinstance(number, str) or not number.strip() or (journal, number) not in allowed):
            raise ValueError('Historical expert report does not match a recorded journal decision')
        provenance = document.get('provenance')
        if (document.get('source_kind') != 'authenticated_journal_expert_report'
                or document.get('stage') != 'pre_final'
                or not isinstance(provenance, Mapping) or provenance.get('authenticated') is not True
                or not isinstance(provenance.get('source'), str) or not provenance['source'].strip()):
            raise ValueError('Historical expert report requires authenticated pre-final provenance')
        source, digest = document.get('path'), document.get('sha256')
        if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('Historical expert report requires a SHA256 binding')
        if not isinstance(source, str) or not source or '\\' in source:
            raise ValueError('Historical expert report path is unsafe')
        relative = Path(source)
        if (relative.is_absolute() or '..' in relative.parts or relative.as_posix() != source
                or base is None):
            raise ValueError('Historical expert report path is unsafe')
        path = base / relative
        component = base
        for part in relative.parts:
            component /= part
            if component.is_symlink():
                raise ValueError('Historical expert report path is unsafe: symlink')
        if not path.resolve().is_relative_to(base) or not path.is_file():
            raise ValueError('Historical expert report source is missing or unsafe')
        if path.stat().st_size > 2_000_000:
            raise ValueError('Historical expert report exceeds the size limit')
        with path.open('rb') as stream:
            raw = stream.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError('Historical expert report exceeds the size limit')
        if _sha256(raw) != digest:
            raise ValueError('Historical expert report source changed')
        if 'bytes' in document and (type(document['bytes']) is not int or document['bytes'] != len(raw)):
            raise ValueError('Historical expert report size binding does not match')
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise ValueError('Historical expert report must be UTF-8 text') from exc
        if not text.strip():
            raise ValueError('Historical expert report text is empty')
        identity = (journal, number, source)
        if identity in seen:
            raise ValueError('Duplicate historical expert report binding')
        seen.add(identity)
        grouped.setdefault((journal, number), []).append({
            **copy.deepcopy(document), 'text': text, 'text_sha256': _sha256(text.encode()), 'bytes': len(raw)})
    for group in grouped.values():
        group.sort(key=lambda document: document['path'])
    return grouped


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
    if not isinstance(bindings, list):
        raise ValueError("Original rejection letter bindings must be a list")
    seen_bindings = set()
    for binding in bindings:
        if not isinstance(binding, Mapping):
            raise ValueError("Malformed original rejection letter binding")
        key = (binding.get("journal"), str(binding.get("manuscript_number")))
        if key not in {(r['journal'], r['manuscript_number']) for r in rows.values()} or key in seen_bindings:
            raise ValueError("Original rejection letter binding does not match one distinct decision")
        seen_bindings.add(key)
        source, digest = binding.get("path"), binding.get("sha256")
        if not root or not isinstance(source, str) or not source or not re.fullmatch(r"[0-9a-f]{64}", str(digest or "")):
            raise ValueError("Original rejection letter requires a file and SHA256 binding")
        path = root / source
        allowed = path.resolve().is_relative_to(root.resolve()) or path.resolve().is_relative_to(root.parent / "maintenance")
        if not allowed or any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file() or path.stat().st_size > 2_000_000:
            raise ValueError("Bound original rejection letter is missing or unsafe")
        if _sha256(path.read_bytes()) != digest:
            raise ValueError(f"Rejection letter changed: {source}")
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
        if binding and not row["letter_available"]:
            raise ValueError("Bound original rejection letter has no readable verbatim text")
        # A source comparison is evidence only when tied to the actual external
        # submission, rather than an arbitrarily chosen earlier local draft.
        submitted = next((s for s in metadata.get('journal_submitted_versions', [])
                          if s.get('journal') == row['journal']
                          and str(s.get('manuscript_number')) == row['manuscript_number']), {})
        if root and submitted and submitted.get('authenticated_submission_binding') is True:
            old_path = (root / str(submitted.get('path') or '')).resolve()
            if (not old_path.is_relative_to(root.resolve()) or not old_path.is_file()
                    or old_path.stat().st_size > 4_000_000):
                raise ValueError('Submitted manuscript comparison source unavailable or unsafe')
            old_raw = old_path.read_bytes()
            if not submitted.get('sha256') or submitted['sha256'] != _sha256(old_raw):
                raise ValueError('Submitted manuscript comparison source changed')
            row['submitted_manuscript'] = {**submitted, 'text': old_raw.decode(errors='replace')}
    documents = _prior_review_documents(metadata, root, list(rows.values()))
    for row in rows.values():
        reports = documents.get((row['journal'], row['manuscript_number']))
        if reports:
            row['prior_review_documents'] = reports
    return sorted(rows.values(), key=lambda r: r["date"])


def rejection_clearance_blockers(editor: Mapping[str, Any], decisions: list[dict[str, Any]],
                                 history_policy: Mapping[str, Any] | None = None) -> list[str]:
    """No send-to-review may silently omit or contradict a sourced previous rejection."""
    reports = editor.get("prior_rejections_addressed") or []
    blockers = []
    expected = {d["decision_id"] for d in decisions}
    permitted_missing = set(history_policy["missing_decision_ids"]) if history_policy else set()
    if not permitted_missing <= expected:
        blockers.append("Missing-letter authorization lists an unrecorded decision")
    if len(reports) != len(decisions) or {r.get("decision_id") for r in reports} != expected:
        blockers.append("The editor did not address each distinct prior rejection exactly once")
    for d in decisions:
        r = next((r for r in reports if r.get("decision_id") == d["decision_id"]), {})
        if not d.get("letter_available") and d['decision_id'] in permitted_missing:
            if (r.get("judgment") != "not_assessable" or r.get("answered") is not False
                    or r.get("journal") != d["journal"] or not str(r.get("evidence") or "").strip()):
                blockers.append(f"Missing original must remain explicitly not assessable: {d['decision_id']}")
            continue
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
    try:
        current_policy = rejection_history_policy(metadata, root, record.get('paper_id'))
        if current_policy != record.get('missing_rejection_letter_policy'):
            blockers.append('Paper-scoped rejection policy changed after review')
    except (ValueError, OSError) as exc:
        blockers.append(f'Paper-scoped rejection policy is invalid: {exc}')
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
        submitted = d.get('submitted_manuscript') or {}
        if submitted:
            path = root / str(submitted.get('path') or '')
            if not path.is_file() or _sha256(path.read_bytes()) != submitted.get('sha256'):
                blockers.append(f"The screened submitted manuscript is missing or changed: {d['decision_id']}")
    # For opted-in papers a missing original becoming available, or a newly corrupt
    # registered binding, must trigger a fresh assessment rather than keep a waiver.
    if metadata.get('missing_rejection_letter_policy') is not None:
        try:
            current = prior_decisions(str(record.get('paper_id') or metadata.get('paper_id')), metadata, root)
        except (ValueError, OSError) as exc:
            blockers.append(f'The current rejection letter context is invalid: {exc}')
        else:
            if {x['decision_id'] for x in current} != ids:
                blockers.append('Current rejection decision scope changed after review')
            for d in bound:
                now = next((x for x in current if x['decision_id'] == d['decision_id']), {})
                for field in ('letter_available', 'source_sha256', 'letter_sha256'):
                    if now.get(field) != d.get(field):
                        blockers.append(f'Original rejection letter context changed: {d["decision_id"]}')
                        break
    try:
        current_documents = _prior_review_documents(metadata, root, bound)
    except (ValueError, OSError) as exc:
        blockers.append(f'The screened historical expert report context is invalid: {exc}')
    else:
        for d in bound:
            current = current_documents.get((d.get('journal'), d.get('manuscript_number')), [])
            if d.get('prior_review_documents', []) != current:
                blockers.append('Historical expert reports or their authenticated bindings changed after review')
    return blockers


TRACK_TEXT = {
    "routine": ("Review track: routine. Judge by this venue's actual level as shown by its recent "
                "articles; do not demand the significance expected at the very top venues."),
    "escalation": ("Review track: escalation. The authors are aiming above their routine venues "
                   "(CAS Zone 1-2 journal or CCF-A conference). Apply this venue's full selectivity; "
                   "a result that would only suit a routine venue should be declined or sent back."),
}


def review_track(metadata: Mapping[str, Any], root: Path | None = None) -> dict[str, Any]:
    """Routine or escalation review, derived from the registered target and venue policy."""
    from paper_writing import venue_policy
    from paper_writing.registry import settings_path
    settings = load_registry_settings(root) if root and settings_path(root).is_file() else {}
    policy = settings.get("journal_target_policy") or {}
    config = venue_policy.eligibility_config(policy)
    escalation = bool(config) and venue_policy.is_escalation_venue(metadata, policy)
    return {"track": "escalation" if escalation else "routine",
            "minimum_overall_score": config["escalation"]["minimum_internal_score"] if escalation else None}


def apply_review_track(merged: Mapping[str, Any], referees: Mapping[str, Mapping[str, Any]],
                       track: Mapping[str, Any]) -> dict[str, Any]:
    """An escalation target needs every referee at or above the score bar; it can only tighten."""
    result = dict(merged)
    if track.get("track") != "escalation" or result.get("outcome") != "ready":
        return result
    minimum = float(track["minimum_overall_score"])
    blockers = [f"Escalation bar: {name} overall score {r['scores']['overall']} is below {minimum:g}"
                for name, r in referees.items() if r["scores"]["overall"] < minimum]
    blockers += [f"Escalation bar: {name} reported low confidence" for name, r in referees.items()
                 if r.get("confidence") == "low"]
    if blockers:
        result.update(outcome="revision_required", next_action="evidence_remediation",
                      escalation_blockers=blockers,
                      scientific_blockers=sorted(set(result.get("scientific_blockers", [])) | set(blockers)))
    return result


def _target_block(metadata: Mapping[str, Any], track: str = "routine") -> str:
    fit = metadata.get("target_journal_fit") or {}
    recent = "\n".join(f"- {u}" for u in fit.get("recent_article_sources") or [])
    if str(metadata.get("venue_type") or "journal") == "conference":
        ccf = metadata.get("target_conference_ccf") or {}
        return (f"Conference: {metadata.get('target_conference')}\n"
                f"CCF recommended list {ccf.get('edition')}: class {ccf.get('rank')} ({ccf.get('category')})\n"
                f"{TRACK_TEXT.get(track, TRACK_TEXT['routine'])}\n"
                f"Recent topically related papers at this conference:\n{recent}\n"
                f"Recorded target fit evidence (author-supplied; assess critically):\n"
                f"{json.dumps(fit, ensure_ascii=False, indent=2)}")
    return (f"Journal: {metadata.get('target_journal')}\n"
            f"Official journal page: {metadata.get('target_journal_source')}\n"
            f"CAS 2025 major-category zone: {metadata.get('target_journal_tier')}\n"
            f"{TRACK_TEXT.get(track, TRACK_TEXT['routine'])}\n"
            f"Recent topically related articles in this journal:\n{recent}\n"
            f"Recorded target fit evidence (author-supplied; assess critically):\n"
            f"{json.dumps(fit, ensure_ascii=False, indent=2)}")


def editor_packet(pre: Mapping[str, Any], decisions: list[dict[str, Any]]) -> str:
    parts = front_matter(pre["expanded"])
    letters = json.dumps(decisions, ensure_ascii=False, indent=2) if decisions else "No prior rejections recorded."
    return (_active_revision_packet(pre) + f"## Target journal\n{_target_block(pre['metadata'], pre.get('review_track', 'routine'))}\n\n"
            f"## Prior editorial decisions on this paper\n"
            "Any prior_review_documents are authenticated pre-final expert reports, not the final "
            "refusal letter. Read their complete texts as historical context; they cannot replace "
            f"a missing final letter.\n{letters}\n\n{_history_policy_packet(pre)}"
            f"## Title\n{parts['title']}\n\n## Abstract\n{parts['abstract']}\n\n"
            f"## Introduction\n{parts['introduction']}\n\n## Statements of the main results\n{parts['main_statements']}\n\n"
            f"## Methods and information budgets\n{parts['methods']}\n\n"
            f"## Complete current manuscript (all LaTeX inputs expanded)\n{pre['expanded']}\n\n"
            f"## Reference list\n{pre['bibliography']}\n"
            + ("\n## Current selected supporting-material claim-evidence maps\n"
               + _claim_map_text(pre['support_claim_evidence_maps']) + "\n"
               if pre.get('support_claim_evidence_maps') else "")
            + str(pre.get('formal_check_packet') or ""))


def _history_policy_packet(pre: Mapping[str, Any]) -> str:
    policy = pre.get('history_policy')
    if not policy:
        return ""
    return ("## Explicit paper-scoped user instruction on missing originals\n"
            + json.dumps(policy, ensure_ascii=False, indent=2)
            + "\nMissing original decision IDs listed here are unknown, not resolved or compatible. "
            "For each actually missing listed original, the editor must report not_assessable, "
            "answered=false and explain the unavailable source. Its absence alone must not cause "
            "desk rejection, an evidence demand or prevention of refereeing. Apply the target's "
            "ordinary contribution, novelty, correctness and readership standards independently. "
            "Read all available original letters and authenticated expert reports completely; "
            "real unaddressed concerns, contradictory assessments and scientific gaps still block. "
            "An internal summary is not an original letter. When checking previous mandatory items, "
            "determine whether an item concerns only an authorized missing original: it may be "
            "marked resolved as no longer required under this instruction, with the policy as evidence, "
            "without claiming the original arrived or its substantive concerns were answered. "
            "This includes both a request for the unavailable original and a prior requirement "
            "to establish that that same unknown original rejection was overcome or compatible. "
            "For such an item, previous_items.resolved means the old prerequisite is no longer "
            "applicable, not that the historical rejection itself has been substantively resolved. "
            "The historical assessment remains not_assessable and answered=false. Independently "
            "assess the current paper and explicitly explain any remaining substantive concern. "
            "Do not remove combined scientific or available-letter concerns on that basis.\n\n")


def editor_schema_for_policy(history_policy: Mapping[str, Any] | None) -> dict[str, Any]:
    schema = copy.deepcopy(EDITOR_SCHEMA)
    if history_policy:
        schema['properties']['prior_rejections_addressed']['items']['properties']['judgment']['enum'].append('not_assessable')
    return schema


def selected_claim_evidence_maps(metadata: Mapping[str, Any], root: Path) -> list[dict[str, Any]]:
    """Use only explicitly selected sources bound to the current verified archive."""
    from paper_writing.support import SupportPackageError, _archive_relative_path, verify_support_archive

    publication = ((metadata.get('support') or {}).get('publication') or {})
    files = publication.get('source_files') or []
    names = {'claim-evidence.md', 'claim-evidence-map.md', 'claim_evidence_map.md'}
    selected = [value for value in files if isinstance(value, str) and Path(value).name.casefold() in names]
    if not selected:
        return []
    if len(selected) != len(set(selected)):
        raise ValueError('Duplicate selected claim-evidence map')
    base = root.resolve()

    def safe_file(value: str) -> Path:
        relative = Path(value)
        if (not value or '\\' in value or relative.is_absolute() or '..' in relative.parts
                or relative.as_posix() != value):
            raise ValueError('Unsafe registered claim-map source or archive path')
        path = base
        for component in relative.parts:
            path /= component
            if path.is_symlink():
                raise ValueError('Registered claim-map source or archive is a symlink')
        if not path.is_file():
            raise ValueError(f'Registered claim-map source or archive is missing: {value}')
        return path

    paths = [(value, safe_file(value)) for value in selected]
    packages = [*(publication.get('package_files') or []), *(publication.get('verification_files') or [])]
    archives = [value for value in packages if isinstance(value, str) and Path(value).suffix.casefold() == '.zip']
    if len(archives) != 1:
        raise ValueError('Selected claim map requires the one registered current support ZIP')
    archive = safe_file(archives[0])
    expected = publication.get('package_sha256')
    if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected):
        raise ValueError('Selected claim map requires the current support ZIP SHA256 binding')
    try:
        verified = verify_support_archive(archive)
    except SupportPackageError as exc:
        raise ValueError(f'Current support archive verification failed: {exc}') from exc
    if verified['archive_sha256'] != expected:
        raise ValueError('Current support archive SHA256 changed')
    if verified['paper_id'] != metadata.get('paper_id'):
        raise ValueError('Current support archive belongs to another paper')
    result = []
    for value, path in paths:
        member_relative = _archive_relative_path(path, base, str(metadata['paper_id']))
        entries = [entry for entry in verified['files']
                   if str(entry.get('archive_path') or '').endswith('/' + member_relative)]
        if len(entries) != 1:
            raise ValueError(f'Selected claim map lacks a unique current archive binding: {value}')
        entry = entries[0]
        if path.stat().st_size > 2_000_000:
            raise ValueError('Selected claim-evidence map exceeds the text input size limit')
        content = path.read_bytes()
        if entry['size'] != len(content) or entry['sha256'] != _sha256(content):
            raise ValueError(f'Selected claim map bytes differ from the current support ZIP: {value}')
        result.append({'source': value, 'sha256': entry['sha256'],
                       'archive': archives[0], 'archive_sha256': expected,
                       'archive_member': entry['archive_path'], 'text': content.decode('utf-8', errors='replace')})
    return result


def _claim_map_text(maps: list[dict[str, Any]]) -> str:
    return '\n\n'.join('### Current registered supporting-material source\n'
                       + json.dumps({key: value for key, value in item.items() if key != 'text'},
                                    ensure_ascii=False, indent=2)
                       + '\n\n' + item['text'] for item in maps)


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
    maps = pre.get('support_claim_evidence_maps')
    if maps is None:
        maps = selected_claim_evidence_maps(metadata, root)
    if maps:
        evidence = _claim_map_text(maps)
    else:
        mapping = root / str(metadata.get('evidence_dir') or f"papers/{metadata.get('paper_id')}/evidence") / 'claim_evidence_map.md'
        evidence = mapping.read_text(errors='replace') if mapping.is_file() else '[No canonical claim-evidence map available]'
    text = (f"## Target journal\n{_target_block(pre['metadata'], pre.get('review_track', 'routine'))}\n\n"
            f"## Manuscript (LaTeX, all inputs expanded)\n{pre['expanded']}\n\n"
            f"## Bibliography\n{pre['bibliography']}\n\n"
            f"## Claim-evidence map\n{evidence}\n\n"
            f"## Supporting materials\n{support_description(pre['metadata'], root)}\n")
    manuscript = root / str(metadata.get('manuscript_dir') or f"papers/{metadata.get('paper_id')}/manuscript")
    supplement = metadata.get('latest_supplementary_pdf')
    supplement_path = (root / str(supplement)).with_suffix('.tex') if supplement else manuscript / 'supplementary.tex'
    if supplement_path.is_file() and not pre.get("expanded_includes_standalone_documents"):
        text += ("\n## Supplementary material (LaTeX, all inputs expanded)\n"
                 + expand_tex(supplement_path, manuscript) + "\n")
    if decisions:
        text += ("\n## Original historical refusal context\n"
                 "These are the original sourced letters, independent of this round's editor verdict. "
                 "Any prior_review_documents are authenticated pre-final expert reports, not final "
                 "refusal letters; read their complete texts without treating them as a replacement "
                 "for a missing final letter. "
                 "Check previous requests against these current documents; do not assume an old "
                 "missing-letter diagnosis still holds when the original is now supplied.\n"
                 + json.dumps(decisions, ensure_ascii=False, indent=2) + "\n")
    if previous:
        text += (f"\n## Previous round\nDecision letter:\n{previous['letter']}\n\n"
                 f"Items to check:\n" + "\n".join(f"- {i}" for i in previous["items"]) +
                 f"\n\nAuthors' response:\n{previous['response']}\n\n"
                 f"Source changes since the previous round (unified diff):\n{previous['diff']}\n")
    text += _active_revision_packet(pre)
    text += _history_policy_packet(pre)
    text += str(pre.get('formal_check_packet') or "")
    return text


# --------------------------------------------------------------------------- merge

def change_blocks(change: Mapping[str, Any]) -> bool:
    """Whether a typed required change bears on whether the conclusions hold.

    ``evidence`` always blocks. ``claim_narrowing`` blocks when it concerns a main
    claim; reports written before the ``main_claim`` field existed cannot say, so
    they keep blocking. ``text`` items are advisory: they reach the decision letter
    and the record, but cannot keep a scientifically sound paper in revision.
    """
    kind = change.get("type")
    if kind == "evidence":
        return True
    if kind == "claim_narrowing":
        return change.get("main_claim") is not False
    return False


def item_is_advisory(item: Any) -> bool:
    """A tracked previous item carrying the ``[text]`` prefix (older records tracked these)."""
    return str(item or "").lstrip().startswith("[text]")


def tracked_item(change: Mapping[str, Any]) -> str:
    return f"[{change['type']}] {change['change']} ({change['location']})"


def direction_context(editor: Mapping[str, Any]) -> dict[str, Any]:
    """What an automated orchestrator needs to choose a direction after a significance desk reject."""
    return {"desk_reject_category": editor.get("desk_reject_category"),
            "strongest_desk_reject_reason": str(editor.get("strongest_desk_reject_reason") or ""),
            "closest_prior_work": copy.deepcopy(list(editor.get("closest_prior_work") or [])),
            "advance_over_prior_work": str(editor.get("advance_over_prior_work") or ""),
            "significance_for_journal": str(editor.get("significance_for_journal") or ""),
            "decision_rationale": str(editor.get("decision_rationale") or ""),
            "options": list(DIRECTION_OPTIONS)}


def principal_rejection_reason(report: Mapping[str, Any]) -> tuple[str, str]:
    """A referee's leading reason for ``reject``, taken from the report itself (no model call).

    Order: the first scientific blocker, the first blocking required change, then the
    referee's significance assessment (referee.md asks for the most important reason first).
    """
    blockers = [str(b) for b in report.get("scientific_blockers") or [] if str(b).strip()]
    if blockers:
        return blockers[0], "scientific_blocker"
    for change in report.get("required_changes") or []:
        if isinstance(change, Mapping) and change_blocks(change) and str(change.get("change") or "").strip():
            return f"{change['change']} ({change.get('location', '')})", "required_change"
    for field in ("significance", "novelty_and_context", "summary"):
        if str(report.get(field) or "").strip():
            return str(report[field]), f"{field}_assessment"
    return "", "none"


def unanimous_rejection(referees: Mapping[str, Mapping[str, Any]]) -> bool:
    """Every referee of a two-referee panel recommends reject.

    A single-referee panel keeps the ordinary rule: one opinion does not stop the
    research direction (a split 1:1 decision likewise keeps the ordinary rule).
    """
    return len(referees) >= 2 and all(r.get("recommendation") == "reject" for r in referees.values())


def rejection_direction_context(editor: Mapping[str, Any],
                                referees: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Direction context after both referees reject: their reasons, scores and the editor's prior work."""
    rejections = []
    for name, report in referees.items():
        reason, source = principal_rejection_reason(report)
        scores = report.get("scores") if isinstance(report.get("scores"), Mapping) else {}
        rejections.append({"referee": name, "recommendation": report.get("recommendation"),
                           "principal_reason": reason, "principal_reason_source": source,
                           "scientific_blockers": list(report.get("scientific_blockers") or []),
                           "significance_score": scores.get("significance"),
                           "novelty_score": scores.get("novelty"),
                           "overall_score": scores.get("overall"),
                           "significance_assessment": str(report.get("significance") or ""),
                           "novelty_assessment": str(report.get("novelty_and_context") or "")})
    return {"trigger": "all_referees_reject", "referee_rejections": rejections,
            "mean_significance_score": _mean_score(referees, "significance"),
            "mean_novelty_score": _mean_score(referees, "novelty"),
            "editor_decision": editor.get("decision"),
            "closest_prior_work": copy.deepcopy(list(editor.get("closest_prior_work") or [])),
            "advance_over_prior_work": str(editor.get("advance_over_prior_work") or ""),
            "significance_for_journal": str(editor.get("significance_for_journal") or ""),
            "strongest_desk_reject_reason": str(editor.get("strongest_desk_reject_reason") or ""),
            "options": list(DIRECTION_OPTIONS)}


def merge(editor: Mapping[str, Any], referees: Mapping[str, Mapping[str, Any]],
          history_blockers: list[str] | None = None, *,
          previous_ids: set[str] | None = None, formal_blockers: list[str] | None = None,
          formal_summary: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Deterministic merge in which only scientific substance can block readiness.

    A paper is ready when no referee reports a scientific blocker, an ``evidence``
    change, a main-claim narrowing or an unresolved previous scientific/evidence
    item, scientific coverage is complete, and the recommendation is accept or
    minor revision. When referees disagree, the more favourable recommendation is
    used unless someone substantiated the stricter one with such an item; then the
    stricter recommendation stands. ``text`` changes are kept, marked advisory.
    When every referee of a two-referee panel recommends reject (with or without
    listed blockers), ``next_action`` is ``direction_decision`` with a
    ``direction_context``, as after a significance desk reject; a split decision
    with one reject keeps the rule above.
    """
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
    if formal_blockers:
        categories = (formal_summary or {}).get('by_category', {})
        # Legacy callers remain conservatively scientific. New runs retain the
        # complete raw blocker list separately and present distinct root causes.
        scientific = list(categories.get('scientific', formal_blockers))
        scientific.extend(b for r in referees.values() for b in r['scientific_blockers'])
        changes = [dict(c, referee=name, advisory=not change_blocks(c))
                   for name, r in referees.items() for c in r['required_changes']]
        unresolved = [dict(p, referee=name, advisory=item_is_advisory(p.get('item')))
                      for name, r in referees.items() for p in r['previous_items'] if not p['resolved']]
        return {"outcome": "formal_check_blocked", "recommendation": None,
                "scientific_blockers": sorted(set(scientific)), "required_changes": changes,
                "technical_blockers": categories.get('technical', []),
                "source_routing_blockers": categories.get('source_routing', []),
                "preparation_blockers": categories.get('preparation', []),
                "raw_formal_blockers": formal_blockers,
                "unresolved_previous_items": unresolved, "next_action": "evidence_remediation"}
    if editor["decision"] != "send_to_review":
        category = editor["desk_reject_category"]
        if editor["decision"] == "revise_before_submission" or category == "presentation":
            action = "text_revision"
        elif category in {"scope", "readership"}:
            action = "retarget_required"
        elif category in DIRECTION_CATEGORIES:
            # Polishing cannot answer "not enough of an advance": hand the choice
            # between a named core analysis, retargeting/short format and freezing
            # to the orchestrator, with the editor's strongest reason.
            action = "direction_decision"
        else:
            action = "evidence_remediation"
        required = ([{"type": "text", "change": item,
                      "location": "Editor screen: manuscript presentation", "referee": "editor",
                      "advisory": True}
                     for item in editor.get("presentation_problems", [])]
                    if editor["decision"] == "revise_before_submission" else [])
        result = {"outcome": editor["decision"], "recommendation": None, "scientific_blockers": [],
                  "required_changes": required, "next_action": action}
        if action == "direction_decision":
            result["direction_context"] = direction_context(editor)
        return result
    if not referees:
        raise ValueError("A send-to-review decision requires the configured referee panel")
    recommendations = {name: r["recommendation"] for name, r in referees.items()}
    blockers = sorted({b for r in referees.values() for b in r["scientific_blockers"]})
    for name, report in referees.items():
        assessment = report.get("formal_check_assessment")
        if assessment is not None:
            if assessment.get("coverage_complete") is not True:
                blockers.append(f"{name}: scientific argument coverage remains incomplete")
            # This pre-verification diagnostic is not the independent formal
            # report. Actual unsupported scientific claims must be recorded in
            # scientific_blockers; text requests remain typed required_changes.
            # Preserve diagnostic observations in the actual referee report,
            # without automatically upgrading every observation into a defect.
    changes = [dict(c, referee=name, advisory=not change_blocks(c))
               for name, r in referees.items() for c in r["required_changes"]]
    unresolved_previous = [dict(p, referee=name, advisory=item_is_advisory(p.get("item")))
                           for name, r in referees.items()
                           for p in r["previous_items"] if not p["resolved"]
                           and (previous_ids is None or str(p.get("id", "")).strip("[] ") in previous_ids)]
    blocking_changes = [c for c in changes if not c["advisory"]]
    blocking_previous = [p for p in unresolved_previous if not p["advisory"]]
    substantive = bool(blockers or blocking_changes or blocking_previous)
    worst = max(recommendations.values(), key=RECOMMENDATIONS.index)
    best = min(recommendations.values(), key=RECOMMENDATIONS.index)
    rec = worst if substantive else best
    ready = rec in {"accept", "minor_revision"} and not substantive
    unanimous_reject = unanimous_rejection(referees)
    if unanimous_reject:
        # Both referees decline, with or without itemized blockers: another
        # remediation round on the same framing rarely turns two rejects around.
        # Hand the orchestrator the same choice as a significance desk reject.
        rec, ready, action = "reject", False, "direction_decision"
    elif ready:
        action = None
    elif blockers or any(c["type"] == "evidence" for c in blocking_changes) or rec == "reject":
        action = "evidence_remediation"
    else:
        action = "text_revision"
    result = {"outcome": "ready" if ready else "revision_required", "recommendation": rec,
              "referee_recommendations": recommendations,
              "recommendation_basis": ("all referees recommend reject" if unanimous_reject else
                                       "stricter recommendation: substantive items reported" if substantive
                                       else "more favourable recommendation: no substantive items reported"),
              "scientific_blockers": blockers, "required_changes": changes,
              "unresolved_previous_items": unresolved_previous, "next_action": action}
    if unanimous_reject:
        result["direction_context"] = rejection_direction_context(editor, referees)
    return result


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


def scientific_rounds(root: Path, paper_id: str, target: str) -> list[dict[str, Any]]:
    # Old decisions keep their historical count. Only future explicit technical
    # records are excluded; no retrospective relabeling of prior rounds.
    return [r for r in completed_rounds(root, paper_id, target)
            if r.get('stage_reached') == 'decision' and r.get('consumes_scientific_round', True)]


def previous_tracked_items(last: Mapping[str, Any],
                           history_policy: Mapping[str, Any] | None = None) -> list[str]:
    """Items the next round must check one by one: scientific and evidence items only.

    Text requests (including an editor's presentation list) are advisory. They stay
    in the previous decision letter, which the next referees read, but they are no
    longer tracked as mandatory items that can keep the paper in revision.
    """
    merged = last.get("merged") or {}
    items = list(merged.get("scientific_blockers", []))
    items += [tracked_item(c) for c in merged.get("required_changes", []) if change_blocks(c)]
    # The opted-in four-paper continuation must not silently forget scientific
    # requests that the last referee explicitly left unresolved.
    if history_policy is not None:
        for item in merged.get('unresolved_previous_items', []):
            if not isinstance(item, Mapping) or not isinstance(item.get('item'), str) or not item['item'].strip():
                raise ValueError('Previous unresolved mandatory item is malformed')
            if item['item'] not in items and not item_is_advisory(item['item']):
                items.append(item['item'])
    return items


def _previous_round(root: Path, paper_id: str, target: str, expanded: str, response: str | None,
                    history_policy: Mapping[str, Any] | None = None):
    rounds = scientific_rounds(root, paper_id, target)
    if not rounds:
        return None
    last = rounds[-1]
    items = previous_tracked_items(last, history_policy)
    if not response:
        if items:
            raise ValueError("A re-review with open scientific or evidence items requires the authors' "
                             "response letter (--response)")
        response = ("[No response letter: the previous round left no scientific or evidence item "
                    "to answer. Its advisory text requests are in the decision letter above.]")
    old = (last["_path"].parent / "manuscript-expanded.tex").read_text()
    diff = "".join(difflib.unified_diff(old.splitlines(True), expanded.splitlines(True), "previous", "current", n=2))
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


def _mean_score(reports: Mapping[str, Mapping[str, Any]], key: str) -> float | None:
    values = [r["scores"][key] for r in reports.values()
              if isinstance(r.get("scores"), Mapping) and isinstance(r["scores"].get(key), (int, float))]
    return sum(values) / len(values) if values else None


def stalled_signal(rounds: list[Mapping[str, Any]], referees: Mapping[str, Mapping[str, Any]],
                   merged: Mapping[str, Any]) -> dict[str, Any]:
    """Flag a polishing loop for the orchestrator; never changes the ready decision.

    Stalled means: this round asks for no ``evidence`` change, and the mean referee
    significance and novelty scores did not rise over the last STALL_TRANSITIONS
    round transitions at this target (this round and the preceding refereed rounds).
    """
    if not referees:
        return {"stalled": False, "stalled_basis": "no referee reports in this round"}
    if any(c.get("type") == "evidence" for c in merged.get("required_changes", [])):
        return {"stalled": False, "stalled_basis": "this round requests evidence changes"}
    history = [r["referee_reports"] for r in rounds if r.get("referee_reports")][-STALL_TRANSITIONS:]
    if len(history) < STALL_TRANSITIONS:
        return {"stalled": False, "stalled_basis": "fewer refereed rounds than the stall window"}
    series = {key: [_mean_score(reports, key) for reports in [*history, referees]]
              for key in ("significance", "novelty")}
    flat = all(None not in values and all(later <= earlier for earlier, later in zip(values, values[1:]))
               for values in series.values())
    return {"stalled": flat, "stalled_basis": {"mean_scores_oldest_first": series,
                                               "transitions": STALL_TRANSITIONS,
                                               "evidence_changes_requested": False}}


# --------------------------------------------------------------------------- delta review after ready

# A manuscript that already passed may change afterwards only in ways that leave
# its scientific content where the referees saw it. The rule is deliberately
# simple and conservative; any doubt sends the paper to a full review.
DELTA_RULE = ("Reuse the last ready full review only when, after removing comments and layout "
              "commands, the title, abstract, introduction, theorem-like statements, every table, every "
              "results/evaluation/discussion/conclusion section and the multiset of numbers in the "
              "document bodies are identical, and at most {fraction:.0%} of lines changed. Figure image "
              "files are not compared. The mandatory reference/core verification always reruns.")
DELTA_MAX_CHANGED_FRACTION = 0.15
_DELTA_HEADINGS = re.compile(r"\b(results?|findings?|experiments?|empirical|numerical|evaluation|"
                             r"discussion|conclusions?|concluding|summary)\b", re.I)
_DELTA_STATEMENTS = re.compile(r"\\begin\{(theorem|proposition|corollary|conjecture|lemma)(\*?)\}"
                               r".*?\\end\{\1\2\}", re.S)
_DELTA_TABLES = re.compile(r"\\begin\{(table\*?|tabular\*?|tabularx|longtable)\}.*?\\end\{\1\}", re.S)
_DELTA_LAYOUT = re.compile(r"\\(?:includegraphics|label|ref|cref|Cref|eqref|autoref|pageref|cite[A-Za-z]*|"
                           r"url|href|input|include|vspace|hspace|setlength|addtolength|bibliography[A-Za-z]*)"
                           r"\*?(?:\s*\[[^\]]*\])*\s*\{[^}]*\}")
# Only key=value lengths (width=0.8\textwidth); "120 in total" in prose stays a number.
_DELTA_DIMENSION = re.compile(r"(?<==)\s*[-+]?\d*\.?\d+\s*(?:pt|mm|cm|in|em|ex|bp|\\(?:text|line|column)width|"
                              r"\\(?:text|paper)height)\b")
_DELTA_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def _norm(text: str) -> str:
    return " ".join(text.split())


def substantive_parts(expanded: str) -> dict[str, Any]:
    """The parts of an expanded manuscript whose change requires a full review."""
    text = re.sub(r"(?<!\\)%[^\n]*", "", expanded)
    numeric = dict(re.findall(r"\\(?:newcommand|renewcommand|providecommand)\s*\{\\([A-Za-z]+)\}"
                              r"\s*\{([-+0-9.,]+)\}", text))
    head = front_matter(text)
    body = re.sub(r"\\documentclass.*?\\begin\{document\}", "", text, flags=re.S)
    if numeric:  # generated result macros count as the numbers they print
        body = re.sub(r"\\([A-Za-z]+)\b", lambda m: numeric.get(m.group(1), m.group(0)), body)
    headings = list(re.finditer(r"\\section\*?\{([^}]*)\}", body))
    sections = []
    for index, match in enumerate(headings):
        if _DELTA_HEADINGS.search(match.group(1)):
            end = headings[index + 1].start() if index + 1 < len(headings) else len(body)
            sections.append([_norm(match.group(1)), _norm(body[match.start():end])])
    numbers = _DELTA_NUMBER.findall(_DELTA_LAYOUT.sub(" ", _DELTA_DIMENSION.sub(" ", body)))
    return {"title": _norm(head["title"]), "abstract": _norm(head["abstract"]),
            "introduction": _norm(head["introduction"]),
            "statements": [_norm(m.group(0)) for m in _DELTA_STATEMENTS.finditer(body)],
            "tables": [_norm(m.group(0)) for m in _DELTA_TABLES.finditer(body)],
            "sections": sections, "numbers": sorted(numbers)}


def substantive_delta(old: str, new: str) -> dict[str, Any]:
    """Compare a ready full review's expanded manuscript with the current one."""
    import collections

    a, b = substantive_parts(old), substantive_parts(new)
    reasons = [f"{name} changed" for name in ("title", "abstract", "introduction") if a[name] != b[name]]
    if a["statements"] != b["statements"]:
        reasons.append("theorem-like statements changed")
    if a["tables"] != b["tables"]:
        reasons.append("table content changed")
    if a["sections"] != b["sections"]:
        old_sections, new_sections = dict(map(tuple, a["sections"])), dict(map(tuple, b["sections"]))
        names = sorted(n for n in set(old_sections) | set(new_sections) if old_sections.get(n) != new_sections.get(n))
        reasons.append("conclusion-bearing sections changed: " + ", ".join(names or ["section order"]))
    old_numbers, new_numbers = collections.Counter(a["numbers"]), collections.Counter(b["numbers"])
    if old_numbers != new_numbers:
        removed, added = sorted((old_numbers - new_numbers).elements()), sorted((new_numbers - old_numbers).elements())
        reasons.append(f"numbers changed (removed {removed[:10]}, added {added[:10]})")
    old_lines, new_lines = old.splitlines(), new.splitlines()
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    removed_lines = added_lines = 0
    touched: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        removed_lines, added_lines = removed_lines + (i2 - i1), added_lines + (j2 - j1)
        heading = next((m.group(1) for line in reversed(new_lines[:j1 + 1])
                        for m in [re.search(r"\\section\*?\{([^}]*)\}", line)] if m), "(front matter)")
        if heading not in touched:
            touched.append(heading)
    fraction = (removed_lines + added_lines) / max(1, len(old_lines) + len(new_lines))
    if fraction > DELTA_MAX_CHANGED_FRACTION:
        reasons.append(f"{fraction:.1%} of lines changed (limit {DELTA_MAX_CHANGED_FRACTION:.0%})")
    return {"substantive_unchanged": not reasons, "reasons": reasons,
            "summary": {"identical": old == new, "lines_removed": removed_lines, "lines_added": added_lines,
                        "changed_fraction": round(fraction, 4), "sections_touched": touched}}


def delta_review_basis(root: Path, paper_id: str, target: str, pre: Mapping[str, Any],
                       config: Mapping[str, Any], track: Mapping[str, Any],
                       history_policy: Mapping[str, Any] | None,
                       round_limit: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Decide whether the last ready full review can carry over; None when there is none."""
    rounds = scientific_rounds(root, paper_id, target)
    base = rounds[-1] if rounds else None
    if (base is None or (base.get("merged") or {}).get("outcome") != "ready"
            or not base.get("referee_reports") or not base.get("editor_screen")):
        return None
    old_path = base["_path"].parent / "manuscript-expanded.tex"
    if not old_path.is_file():
        return None
    reasons = []
    if not review_policy_matches(base, config, root, history_policy, round_limit):
        reasons.append("review policy changed since the ready review")
    if set(base["referee_reports"]) != set(config["referee_roles"]):
        reasons.append("the referee panel changed since the ready review")
    if (base.get("review_track") or {}).get("track") != track.get("track"):
        reasons.append("the review track changed")
    if base.get("active_revision_context") != pre.get("active_revision_context"):
        reasons.append("the active journal revision context changed")
    try:
        context = rejection_context_blockers(base, pre["metadata"], root)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        context = [str(exc)]
    if context:
        reasons.append("rejection history changed: " + context[0])
    delta = substantive_delta(old_path.read_text(), pre["expanded"])
    reasons.extend(delta["reasons"])
    return {"base": base, "eligible": not reasons, "reasons": reasons, "summary": delta["summary"],
            "rule": DELTA_RULE.format(fraction=DELTA_MAX_CHANGED_FRACTION)}


def _formal_stage(pre: Mapping[str, Any], root: Path, run: Path, roles: Mapping[str, Any],
                  config: Mapping[str, Any], metadata: Mapping[str, Any],
                  record: dict[str, Any]) -> tuple[dict[str, Any], list[str], Any]:
    """Run the mandatory reference/core verification and return (pre, blockers, summary)."""
    try:
        verifier = formal_role(roles)
        formal = formal_checks.run_checks(pre, root, run, verifier, config['timeout_seconds'], run_role)
        formal_blockers = formal['blockers']
        if not formal_blockers:
            formal_blockers = formal_checks.validate_binding(formal, metadata, root, verifier)
    except (ValueError, OSError, LaunchError) as exc:
        formal = {'valid': False, 'schema': formal_checks.VERSION}
        formal_blockers = [f'Mandatory core-verification stage failed: {exc}']
        formal['issue_summary'] = {'by_category': {'scientific': [], 'technical': formal_blockers,
                                                   'source_routing': [], 'preparation': []}}
    record['formal_check'] = formal
    pre = dict(pre, formal_check_packet=formal_checks.packet(formal, root)) if formal.get('path') else dict(pre)
    summary = formal.get('issue_summary')
    if formal_blockers and summary and not any(summary.get('by_category', {}).values()):
        summary = {'by_category': {'scientific': [], 'technical': formal_blockers}}
    return pre, formal_blockers, summary


def _run_delta_review(paper_id: str, root: Path, run: Path, record: dict[str, Any], pre: Mapping[str, Any],
                      config: Mapping[str, Any], track: Mapping[str, Any], delta: Mapping[str, Any],
                      history_policy: Mapping[str, Any] | None, rounds: list[dict[str, Any]],
                      apply: bool) -> dict[str, Any]:
    """Carry an earlier ready judgment over a text/figure-only change; rerun the formal stage."""
    base = delta["base"]
    roles, panel = config["roles"], config["referee_roles"]
    editor, referees = copy.deepcopy(base["editor_screen"]), copy.deepcopy(base["referee_reports"])
    decisions = copy.deepcopy(base.get("prior_decisions", []))
    _json_dump(run / "prior-decisions.json", decisions)
    history_blockers = rejection_clearance_blockers(editor, decisions, history_policy)
    formal_blockers: list[str] = []
    formal_summary = None
    if apply_review_track(merge(editor, referees, history_blockers), referees, track)["outcome"] == "ready":
        pre, formal_blockers, formal_summary = _formal_stage(pre, root, run, roles, config, pre["metadata"], record)
    merged = apply_review_track(merge(editor, referees, history_blockers, formal_blockers=formal_blockers,
                                      formal_summary=formal_summary), referees, track)
    merged |= {"stalled": False, "stalled_basis": "delta review; no new referee judgment"}
    base_path = base["_path"]
    record |= {"stage_reached": "decision", "review_mode": "delta",
               "round_for_target": len(rounds), "consumes_scientific_round": False,
               "round_count_basis": "delta review reusing an earlier ready full review; no new scientific judgment",
               "delta_review": {"basis_run_id": base.get("run_id") or base_path.parent.name,
                                "basis_decision": base_path.relative_to(root).as_posix(),
                                "basis_decision_sha256": _sha256(base_path.read_bytes()),
                                "rule": delta["rule"], "summary": delta["summary"]},
               "editor_screen": editor, "referee_reports": referees, "merged": merged,
               "letter": base.get("letter", ""), "receipts": copy.deepcopy(base.get("receipts", {})),
               "receipts_from_run": base.get("run_id") or base_path.parent.name,
               "prior_decisions": decisions, "editorial_history_blockers": history_blockers,
               "previous_required_items": [],
               "same_provider_panel": len({roles[n]["provider"] for n in panel}) == 1,
               "finished_at": _now()}
    digest = _json_dump(run / "decision.json", record)
    if apply:
        apply_decision(paper_id, root=root, decision_path=run / "decision.json", digest=digest)
    return record | {"run_dir": str(run.relative_to(root)), "decision_sha256": digest}


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
    # Cross-model decision 2026-11-07 is checked after the paper metadata is loaded.
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
    history_policy = rejection_history_policy(metadata, root, paper_id)
    round_limit = review_round_limit_override(metadata, root, paper_id, target)
    if round_limit is not None:
        config = dict(config, max_rounds_per_target=round_limit["max_rounds_per_target"])
    track = review_track(metadata, root)
    writer = writer_model(metadata, config)
    pre = dict(pre, history_policy=history_policy, review_track=track["track"])
    pre["blockers"] = [*pre["blockers"], *cross_model_blockers(config, writer)]
    (run / "manuscript-expanded.tex").write_text(pre["expanded"])
    record: dict[str, Any] = {"schema_version": "openlabs.review.decision.v1", "process": PROCESS,
                              "paper_id": paper_id, "run_id": run_id, "target_journal": target,
                              "target_journal_tier": metadata.get("target_journal_tier"),
                              "venue_type": str(metadata.get("venue_type") or "journal"),
                              "review_track": track,
                              "manuscript_version": str(metadata.get("version") or ""),
                              "fingerprints": pre["fingerprints"], "started_at": _now()}
    record |= {"review_policy_sha256": review_policy_sha256(config, history_policy, round_limit), "active_referee_roles": panel,
               "formal_verifier_role": formal_role_name(roles),
               "single_referee_panel": len(panel) == 1, "writer_model": writer,
               "cross_model_referees": [n for n in panel if roles[n].get("model") != writer]}
    if pre.get('active_revision_context') is not None:
        record['active_revision_context'] = pre['active_revision_context']
    if history_policy is not None:
        record['missing_rejection_letter_policy'] = history_policy
    if round_limit is not None:
        record['review_round_limit_override'] = round_limit
    if pre.get("editorial_rewrite_advisory") is not None:
        record["editorial_rewrite_advisory"] = pre["editorial_rewrite_advisory"]
    # Presentation/preparation findings: reported with the review, never a reason
    # for preflight_failed, enforced at the delivery exit (``delivery_blockers``).
    record["preparation_advisories"] = list(pre.get("preparation_advisories", []))
    record["build_inputs"] = list(pre.get("build_inputs", []))
    if pre["blockers"]:
        record |= {"stage_reached": "preflight", "merged": {"outcome": "preflight_failed",
                   "preflight_blockers": pre["blockers"], "next_action": "text_revision"}}
        _json_dump(run / "decision.json", record)
        return record | {"run_dir": str(run.relative_to(root))}
    rounds = scientific_rounds(root, paper_id, target)
    delta = delta_review_basis(root, paper_id, target, pre, config, track, history_policy, round_limit)
    if delta is not None and delta["eligible"]:
        return _run_delta_review(paper_id, root, run, record, pre, config, track, delta,
                                 history_policy, rounds, apply)
    if delta is not None:
        record["delta_review_refused"] = {"basis_run_id": delta["base"].get("run_id"),
                                          "reasons": delta["reasons"], "summary": delta["summary"]}
    if len(rounds) >= config["max_rounds_per_target"]:
        raise ValueError(f"{paper_id} has used all {config['max_rounds_per_target']} review rounds for {target}; "
                         "no further round starts: under the research program the orchestrator takes a "
                         "direction decision (targeted analysis, retarget or freeze) on review_rounds_exhausted")
    response = Path(response_letter).read_text() if response_letter else None
    if response:
        pre = dict(pre, author_response=response)
    previous = _previous_round(root, paper_id, target, pre["expanded"], response, history_policy)
    if response:
        (run / "response-letter.md").write_text(response)

    decisions = prior_decisions(paper_id, metadata, root)
    _json_dump(run / "prior-decisions.json", decisions)
    editor, editor_receipt = run_role(role_name="editor", role=roles["editor"],
                                      system_prompt=(PROMPTS / "editor.md").read_text(),
                                      user_prompt=editor_packet(pre, decisions), schema=editor_schema_for_policy(history_policy),
                                      workdir=run / "editor", timeout=config["timeout_seconds"])
    referees: dict[str, Any] = {}
    receipts = {"editor": editor_receipt}
    history_blockers = rejection_clearance_blockers(editor, decisions, history_policy)
    formal_blockers: list[str] = []
    formal_summary = None
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
        # Scientific merit/correctness is evaluated before the narrower check;
        # an output-format defect must not prevent an overall referee report.
        scientific_decision = apply_review_track(merge(editor, referees, history_blockers), referees, track)
        if scientific_decision['outcome'] == 'ready':
            pre, formal_blockers, formal_summary = _formal_stage(pre, root, run, roles, config, metadata, record)
    merged = apply_review_track(merge(editor, referees, history_blockers, formal_blockers=formal_blockers,
                                      formal_summary=formal_summary), referees, track)
    merged |= stalled_signal(rounds, referees, merged)
    consumes_round = not (formal_blockers and formal_summary is not None
                          and not merged['scientific_blockers'] and not history_blockers)
    letter_packet = json.dumps({"fixed_decision": merged, "editor_screen": editor, "referee_reports": referees,
                               "formal_check": record.get("formal_check"),
                               "formal_check_report": pre.get("formal_check_packet")},
                               indent=2, ensure_ascii=False)
    letter, letter_receipt = run_role(role_name="decision_letter", role=roles["editor"],
                                      system_prompt=(PROMPTS / "decision.md").read_text(), user_prompt=letter_packet,
                                      schema=LETTER_SCHEMA, workdir=run / "decision-letter",
                                      timeout=config["timeout_seconds"])
    receipts["decision_letter"] = letter_receipt
    record |= {"stage_reached": "decision", "round_for_target": len(rounds) + int(consumes_round),
               "consumes_scientific_round": consumes_round,
               "round_count_basis": "substantive judgment; pure technical/source-routing/preparation failures excluded",
               "editor_screen": editor,
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
    metadata = load_paper_metadata(paper_id, root)
    history_policy = rejection_history_policy(metadata, root, paper_id)
    config = policy_for_record(record, review_config(root))
    round_limit = review_round_limit_override(metadata, root, paper_id)
    if not review_policy_matches(record, config, root, history_policy, round_limit):
        raise ValueError("Review policy changed; rerun the review")
    if record['merged']['outcome'] == 'ready':
        panel = config['referee_roles']
        if set(record.get('referee_reports', {})) != set(panel):
            raise ValueError("Ready decision is missing an active referee")
        formal_errors = formal_checks.validate_binding(record.get("formal_check"), metadata, root, formal_role(config["roles"]))
        if formal_errors:
            raise ValueError("; ".join(formal_errors))
        if any("formal_check_assessment" not in r for r in record["referee_reports"].values()):
            raise ValueError("Ready decision lacks independent scientific coverage assessment")
        blockers = rejection_clearance_blockers(record['editor_screen'], record.get('prior_decisions', []), history_policy)
        if merge(record['editor_screen'], record['referee_reports'], blockers)['outcome'] != 'ready':
            raise ValueError("Ready decision contradicts the editor, rejection letters, or referees")
    if rejection_context_blockers(record, metadata, root):
        raise ValueError('Rejection history or original letter changed during the review; rerun')
    if active_revision_context(metadata, root) != record.get('active_revision_context'):
        raise ValueError('Active journal revision context changed during the review; rerun')
    fingerprints = _review_workspace_fingerprints(paper_id, metadata, root)
    if fingerprints != record["fingerprints"]:
        raise ValueError("Manuscript, registry or support sources changed during the review; rerun")
    merged = record["merged"]
    max_rounds = round_limit["max_rounds_per_target"] if round_limit is not None else config["max_rounds_per_target"]
    status = ("ready" if merged["outcome"] == "ready" else
              "blocked" if record.get("round_for_target", 0) >= max_rounds
              or merged["next_action"] in {"retarget_required", "direction_decision"}
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
    if record.get("formal_check", {}).get("valid") is True:
        release["formal_check"] = record["formal_check"]
        access = record["formal_check"].get("unverifiable_source_access")
        if access:
            # Not manuscript defects; listed for manual or other-environment checking.
            release["unverifiable_source_access"] = access
    if re.fullmatch(r"[0-9a-f]{64}", str(publication.get("package_sha256") or "")):
        release["support_package_sha256"] = publication["package_sha256"]
    if merged.get("scientific_blockers"):
        release["unresolved_review_blockers"] = merged["scientific_blockers"]
    if merged.get("direction_context"):
        release["direction_context"] = merged["direction_context"]
    if merged.get("stalled"):
        release["review_stalled"] = True
    advisory = [c for c in merged.get("required_changes", []) if c.get("advisory")]
    if merged["outcome"] == "ready" and advisory:
        release["advisory_changes"] = advisory
    if record.get("preparation_advisories"):
        release["preparation_advisories"] = {
            "count": len(record["preparation_advisories"]),
            "codes": sorted({str(a.get("code")) for a in record["preparation_advisories"]}),
            "enforced_at": "delivery (handoff / Zenodo release)", "details": "decision_record"}
    if record.get("review_mode") == "delta":
        release["review_mode"] = "delta"
        release["delta_basis_run_id"] = record["delta_review"]["basis_run_id"]
    metadata["writing_release"] = release
    metadata["status_updated_at"] = _now()
    write_paper_metadata(paper_id, metadata, root)
    return release


def delivery_blockers(paper_id: str, metadata: Mapping[str, Any], root: Path,
                      record: Mapping[str, Any] | None = None, *,
                      notes: list[dict[str, Any]] | None = None) -> list[str]:
    """The formal checks moved from the review entry to the delivery exit.

    Everything the unified preflight reports as a preparation advisory is a hard
    requirement here: the full manuscript-style audit (AI-use declaration,
    TODO/draft markers, internal paths), the full support-record audit (Zenodo
    DOI, versions, filenames, titles, README wording, citation), the verified
    venue abstract limits and the absence of source files that the build does not
    read. Internal-vocabulary hits are reported with their sentence for a human
    decision and do not block (see manuscript_style.BLACKLIST_CODES); they are
    appended to ``notes`` together with references that could not be verified for
    lack of source access and with registered passage selectors / local evidence
    files that no longer match (nothing uses them; see ``stale_route_notes``).
    """
    from paper_writing.editorial_rewrite import abstract_findings
    from paper_writing.manuscript_style import audit_manuscript_style, manuscript_style_blockers
    from paper_writing.registry import load_registry_settings
    from paper_writing.support_citations import audit_manuscript_support, support_audit_blockers

    gate = load_registry_settings(root).get("quality_gate") or {}
    style = audit_manuscript_style(
        paper_id, root=root, require_ai_declaration=bool(gate.get("require_ai_use_declaration", True)))
    problems = manuscript_style_blockers(style)
    if notes is not None:
        notes.extend({"kind": "internal_vocabulary", **dict(item)} for item in style.get("blacklist_findings", []))
        access = ((record or {}).get("formal_check") or {}).get("unverifiable_source_access")
        if access:
            notes.append({"kind": "unverifiable_source_access", **dict(access)})
        notes.extend(stale_route_notes(metadata, root))
    problems += support_audit_blockers(audit_manuscript_support(paper_id, root=root))
    problems += [f"Venue abstract format: {p}" for p in abstract_findings(metadata, root, paper_id)]
    if record is not None:
        used = record.get("build_inputs")
        manuscript = root / str(metadata.get("manuscript_dir") or f"papers/{paper_id}/manuscript")
        if isinstance(used, list):
            # The manuscript snapshot is bound to the decision, so the reviewed build's
            # inputs are still the current build's inputs.
            unused = unused_source_files(manuscript, {str(u) for u in used})
            if unused:
                problems.append("Source files not read by the build would enter the journal package: "
                                + ", ".join(unused[:12]))
        # Decisions written before build_inputs existed were made by a preflight that
        # still rejected unused source files, and their snapshot is bound: nothing to add.
    return problems


def stale_route_notes(metadata: Mapping[str, Any], root: Path) -> list[dict[str, Any]]:
    """Registered selectors / local evidence nothing uses any more: cleanup notes, never blockers."""
    try:
        documents, bibliography = formal_checks.current_inputs(metadata, root)
        findings = formal_checks.route_findings(metadata, formal_checks.inventory(documents, bibliography), root)
    except (ValueError, OSError):
        return []  # the formal binding revalidation reports unreadable inputs
    return [{**f, "kind": "stale_registration_route", "route_kind": f["kind"],
             "code": ROUTE_ADVISORY_CODES[f["kind"]],
             "note": "Not used by the formal check or delivery; the registration entry can be updated or removed."}
            for f in findings if f["kind"] in formal_checks.ADVISORY_ROUTE_KINDS]


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
    config = policy_for_record(record, review_config(root))
    try:
        history_policy = rejection_history_policy(metadata, root, paper_id)
    except (ValueError, OSError) as exc:
        return [f'Paper-scoped rejection policy is invalid: {exc}']
    try:
        round_limit = review_round_limit_override(metadata, root, paper_id)
    except (ValueError, OSError) as exc:
        return [f'Paper/target-scoped review round limit is invalid: {exc}']
    if not review_policy_matches(record, config, root, history_policy, round_limit):
        problems.append("Review policy changed after this decision; a fresh review is required")
    problems.extend(formal_checks.validate_binding(record.get("formal_check"), metadata, root, formal_role(config["roles"])))
    if release.get("formal_check") != record.get("formal_check"):
        problems.append("The release is not bound to the actual mandatory formal check")
    if any("formal_check_assessment" not in r for r in record.get("referee_reports", {}).values()):
        problems.append("The active referee did not assess core mathematical coverage")
    if record.get("referee_reports"):
        try:
            history = rejection_clearance_blockers(record['editor_screen'], record.get('prior_decisions', []), history_policy)
            if merge(record['editor_screen'], record['referee_reports'], history)['outcome'] != "ready":
                problems.append("The merged gate contradicts the actual referee or formal-check assessment")
        except (KeyError, TypeError, ValueError):
            problems.append("The actual referee reports are incomplete or malformed")
    if round_limit is not None and release.get("max_rounds_per_target") != round_limit["max_rounds_per_target"]:
        problems.append("The release does not report the authorized paper/target round limit")
    if set(record.get('referee_reports', {})) != set(config['referee_roles']):
        problems.append("The decision does not contain the configured referee panel")
    if rejection_clearance_blockers(record['editor_screen'], record.get('prior_decisions', []), history_policy):
        problems.append("The original rejection letters were not cleared by the independent editor")
    problems.extend(rejection_context_blockers(record, metadata, root))
    try:
        if active_revision_context(metadata, root) != record.get('active_revision_context'):
            problems.append('Active journal revision context differs from the reviewed originals')
    except ValueError as exc:
        problems.append(f'Active journal revision context: {exc}')
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
