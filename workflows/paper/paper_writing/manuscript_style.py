"""Deterministic checks for reader-facing manuscript voice and AI disclosure.

The checker is intentionally narrow.  It rejects repository-workflow residue and
AI/tool narration in the scientific body, while allowing a truthful, final AI-use
declaration and a registered institutional affiliation whose name contains ``AI
Agent Lab``.  Repository policy requires the final declaration; the checker does
not attempt to score prose quality.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from paper_writing.funding import ineligible_funding
from paper_writing.registry import load_paper_metadata, load_registry


INPUT_PATTERN = re.compile(r"\\(?:input|include)\s*\{([^}]+)\}")
BIBLIOGRAPHY_PATTERN = re.compile(
    r"\\bibliography\s*\{([^}]+)\}"
    r"|\\addbibresource(?:\s*\[[^]]*\])?\s*\{([^}]+)\}",
    re.IGNORECASE,
)
DECLARATION_HEADING = re.compile(
    r"\\(?:sub)*section\*?\s*\{[^}]*"
    r"(?:generative\s+AI|AI[- ]use|AI-assisted)[^}]*\}"
    r"|\\aadmunnumberedsection\s*\{[^}]*"
    r"(?:generative\s+AI|AI[- ]use|AI-assisted)[^}]*\}"
    r"|\\(?:noindent\s*)?\\textbf\s*\{[^}]*AI[- ]use[^}]*\}",
    re.IGNORECASE,
)
DECLARATION_END = re.compile(
    r"\\(?:section|subsection|subsubsection|aadmunnumberedsection)\*?\s*\{"
    r"|\\bibliographystyle\s*\{"
    r"|\\bibliography\s*\{"
    r"|\\end\s*\{document\}",
    re.IGNORECASE,
)
AI_WORKFLOW_MARKER = re.compile(
    r"\b(?:OpenAI|ChatGPT|Codex|GPT[- ]?\d(?:\.\d+)*|LLM|large language model)\b"
    r"|\b(?:generative[- ]AI|AI-assisted)\b",
    re.IGNORECASE,
)
CODE_CUE = re.compile(
    r"\b(?:Python3?|GAP|SageMath|Mathematica|computer-assisted|source code|"
    r"scripts?|verifiers?|checkers?)\b",
    re.IGNORECASE,
)
LEAN_CUE = re.compile(
    r"(?:\bformaliz(?:ed|ation)\b.{0,100}\bLean\b)"
    r"|(?:\b(?:accompanying|archived|separate|our|this)\s+Lean"
    r"(?:\s*~?\s*\d+(?:\.\d+)*)?\s+"
    r"(?:project|source|formalization|development)\b)"
    r"|(?:\bLean[- ](?:checked|verified)\b)",
    re.IGNORECASE | re.DOTALL,
)


# These expressions target manuscript-production residue, not scientific subject
# matter.  For example, ordinary uses of "internal vertex" or "claim" are allowed.
PROHIBITED_BODY_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "STYLE-INTERNAL-AUDIT",
        re.compile(r"\baudit(?:s|ed|ing|ability|able)?\b", re.IGNORECASE),
        "replace internal audit terminology with a direct scientific description of the check, computation, or evidence",
    ),
    (
        "STYLE-READER-FACING",
        re.compile(r"\breader[- ]facing\b", re.IGNORECASE),
        "describe the cited record or material directly instead of using workflow-facing terminology",
    ),
    (
        "STYLE-REVIEW-WORKFLOW",
        re.compile(r"\breviewer[- ]facing\b|\bso (?:a|the) reviewer can\b", re.IGNORECASE),
        "state reproducibility properties directly without addressing the review workflow",
    ),
    (
        "STYLE-REPOSITORY-WORKFLOW",
        re.compile(
            r"\brepository[- ]local\b|\bfrozen evidence bundle\b|"
            r"\bevidence architecture\b|\bclaim[- ]by[- ]claim\b|"
            r"\bclaim[-–— ]evidence (?:map|registry)\b|\bclaim (?:map|registry)\b|"
            r"\bpriority certificate\b|\binternal QA\b|\bquality[- ]gate\b",
            re.IGNORECASE,
        ),
        "remove private repository, evidence-mapping, or gate terminology from the scientific manuscript",
    ),
    (
        "STYLE-PREPARATION-NARRATIVE",
        re.compile(
            r"\bpre[- ]submission\b|\bsearch was frozen\b|"
            r"\bsource check was frozen\b|\bliterature search cutoff\b|"
            r"\baudit log\b|\blive check\b",
            re.IGNORECASE,
        ),
        "replace manuscript-preparation chronology with a neutral, dated literature statement or omit it",
    ),
    (
        "STYLE-AGENT-WORKFLOW",
        re.compile(
            r"\b(?:writing|reviewer|research|revision) agents?\b|"
            r"\bthree[- ]agent\b|\bfresh[- ]context\b|\bagent-generated\b",
            re.IGNORECASE,
        ),
        "remove agent-orchestration language from the scientific manuscript",
    ),
)

INTERNAL_LITERAL_PATH_PATTERN = re.compile(
    r"\\(?:path|nolinkurl|url)\s*\{[^{}]*"
    r"(?:audit|claim[_-]evidence[_-](?:map|registry)|claim[_-](?:map|registry)|"
    r"research[_-]open|q1[_-][^{}]*(?:campaign|transfer))[^{}]*\}",
    re.IGNORECASE,
)
BIBLIOGRAPHY_WORKFLOW_MARKER = re.compile(
    r"\b(?:used in (?:the|this) audit|internal audit|source audit|"
    r"reader[- ]facing|reviewer[- ]facing)\b",
    re.IGNORECASE,
)
UNRESOLVED_SUBMISSION_MARKER = re.compile(
    r"\bauthor confirmation required\b|\bdraft for approval\b|"
    r"\brequires confirmation\b|\bsubmission draft\b|"
    r"\binternal drafting note\b|\bbefore portal upload\b|"
    r"\bnot submission[- ]ready\b|\binternal draft\b|"
    r"\bindependent validation pending\b|\bapproval remain(?:s)? required\b",
    re.IGNORECASE,
)
UNRESOLVED_SOURCE_MARKER = re.compile(
    r"(?:^|[^A-Za-z])(?:TODO|TBD|FIXME)(?:[^A-Za-z]|$)", re.IGNORECASE
)


def _strip_tex_comment(line: str) -> str:
    """Remove an unescaped LaTeX comment from one source line."""

    for index, char in enumerate(line):
        if char != "%":
            continue
        backslashes = 0
        cursor = index - 1
        while cursor >= 0 and line[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2 == 0:
            return line[:index]
    return line


def _mask_literal_paths(text: str) -> str:
    """Mask paths after the dedicated internal-path rule has examined them."""

    return re.sub(
        r"\\(?:path|nolinkurl|url)\s*\{[^{}]*\}",
        " ",
        text,
        flags=re.IGNORECASE,
    )


def _tex_tree(main_tex: Path, manuscript: Path) -> list[Path]:
    """Return the transitive, manuscript-local TeX inputs for one entry point."""

    ordered: list[Path] = []
    seen: set[Path] = set()
    root = manuscript.resolve()

    def visit(path: Path) -> None:
        resolved = path.resolve()
        if resolved in seen or not resolved.is_file():
            return
        try:
            resolved.relative_to(root)
        except ValueError:
            return
        seen.add(resolved)
        ordered.append(resolved)
        text = resolved.read_text(encoding="utf-8")
        for match in INPUT_PATTERN.finditer(text):
            target = match.group(1).strip()
            candidate = manuscript / target
            if candidate.suffix == "":
                candidate = candidate.with_suffix(".tex")
            visit(candidate)

    visit(main_tex)
    return ordered


def _bibliography_files(files: Iterable[Path], manuscript: Path) -> list[Path]:
    """Return manuscript-local bibliography resources referenced by TeX files."""

    ordered: list[Path] = []
    seen: set[Path] = set()
    root = manuscript.resolve()
    for path in files:
        if path.suffix.lower() != ".tex":
            continue
        text = path.read_text(encoding="utf-8")
        for match in BIBLIOGRAPHY_PATTERN.finditer(text):
            raw_targets = match.group(1) or match.group(2) or ""
            for raw_target in raw_targets.split(","):
                target = raw_target.strip()
                if not target:
                    continue
                candidate = manuscript / target
                if candidate.suffix == "":
                    candidate = candidate.with_suffix(".bib")
                resolved = candidate.resolve()
                try:
                    resolved.relative_to(root)
                except ValueError:
                    continue
                if resolved.is_file() and resolved not in seen:
                    seen.add(resolved)
                    ordered.append(resolved)
    return ordered


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _issue(
    code: str,
    message: str,
    *,
    path: Path | None = None,
    line: int | None = None,
    root: Path,
) -> dict[str, Any]:
    item: dict[str, Any] = {"code": code, "message": message}
    if path is not None:
        item["path"] = _relative(path, root)
    if line is not None:
        item["line"] = line
    return item


def _declaration_ranges(
    files: Iterable[Path], *, root: Path
) -> tuple[dict[Path, range], list[dict[str, Any]]]:
    ranges: dict[Path, range] = {}
    issues: list[dict[str, Any]] = []
    locations: list[tuple[Path, int]] = []

    for path in files:
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, raw in enumerate(lines):
            if DECLARATION_HEADING.search(_strip_tex_comment(raw)):
                locations.append((path, index))

    if len(locations) > 1:
        for path, index in locations:
            issues.append(
                _issue(
                    "STYLE-AI-DECLARATION-COUNT",
                    "the compiled manuscript must contain one consolidated AI-use declaration",
                    path=path,
                    line=index + 1,
                    root=root,
                )
            )
        return ranges, issues
    if not locations:
        return ranges, issues

    path, start = locations[0]
    lines = path.read_text(encoding="utf-8").splitlines()
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if DECLARATION_END.search(_strip_tex_comment(lines[index])):
            end = index
            break
    ranges[path] = range(start, end)

    # The declaration must be the final scientific prose/declaration block.
    # Once the bibliography begins, venue-mandated back matter such as author
    # addresses may follow without moving the AI declaration behind the
    # reference list.
    for index in range(end, len(lines)):
        visible = _strip_tex_comment(lines[index]).strip()
        if not visible:
            continue
        if re.match(r"\\bibliography\s*\{", visible, re.IGNORECASE):
            break
        if re.match(
            r"\\bibliographystyle\s*\{|\\end\s*\{document\}",
            visible,
            re.IGNORECASE,
        ):
            continue
        issues.append(
            _issue(
                "STYLE-AI-DECLARATION-POSITION",
                "place the AI-use declaration after all other manuscript prose and declarations",
                path=path,
                line=index + 1,
                root=root,
            )
        )
        break
    return ranges, issues


def audit_tex_tree(
    main_tex: str | Path,
    *,
    manuscript: str | Path | None = None,
    root: str | Path | None = None,
    require_ai_declaration: bool = True,
) -> dict[str, Any]:
    """Check one compiled TeX tree without assigning a prose score."""

    main_path = Path(main_tex).resolve()
    manuscript_path = Path(manuscript).resolve() if manuscript else main_path.parent
    report_root = Path(root).resolve() if root else manuscript_path
    files = _tex_tree(main_path, manuscript_path)
    bibliography_files = _bibliography_files(files, manuscript_path)
    issues: list[dict[str, Any]] = []
    declaration_ranges, range_issues = _declaration_ranges(files, root=report_root)
    issues.extend(range_issues)

    combined_body: list[str] = []
    declaration_parts: list[str] = []
    for path in files:
        declaration_range = declaration_ranges.get(path, range(0, 0))
        for index, raw in enumerate(path.read_text(encoding="utf-8").splitlines()):
            if UNRESOLVED_SOURCE_MARKER.search(raw):
                issues.append(
                    _issue(
                        "STYLE-UNRESOLVED-MARKER",
                        "remove unresolved TODO/TBD/FIXME markers from the submission manuscript",
                        path=path,
                        line=index + 1,
                        root=report_root,
                    )
                )
            visible = _strip_tex_comment(raw)
            if index in declaration_range:
                declaration_parts.append(visible)
                continue
            combined_body.append(visible)
            if INTERNAL_LITERAL_PATH_PATTERN.search(visible):
                issues.append(
                    _issue(
                        "STYLE-INTERNAL-PATH",
                        "remove internal audit, claim-mapping, or work-campaign filenames and paths from the reader manuscript",
                        path=path,
                        line=index + 1,
                        root=report_root,
                    )
                )
            scan_text = _mask_literal_paths(visible)
            if "AI Agent Lab" in scan_text:
                scan_text = scan_text.replace("AI Agent Lab", "registered affiliation")
            if AI_WORKFLOW_MARKER.search(scan_text):
                issues.append(
                    _issue(
                        "STYLE-AI-WORKFLOW-IN-BODY",
                        "AI tool or AI-assisted workflow narration is permitted only in the final AI-use declaration",
                        path=path,
                        line=index + 1,
                        root=report_root,
                    )
                )
            if UNRESOLVED_SUBMISSION_MARKER.search(scan_text):
                issues.append(
                    _issue(
                        "STYLE-UNCONFIRMED-SUBMISSION-TEXT",
                        "remove draft, pending-confirmation, or pre-submission gate language from reader-facing prose",
                        path=path,
                        line=index + 1,
                        root=report_root,
                    )
                )
            for code, pattern, message in PROHIBITED_BODY_PATTERNS:
                if pattern.search(scan_text):
                    issues.append(
                        _issue(
                            code,
                            message,
                            path=path,
                            line=index + 1,
                            root=report_root,
                        )
                    )

    for path in bibliography_files:
        for index, raw in enumerate(path.read_text(encoding="utf-8").splitlines()):
            visible = _strip_tex_comment(raw)
            if BIBLIOGRAPHY_WORKFLOW_MARKER.search(visible):
                issues.append(
                    _issue(
                        "STYLE-BIBLIOGRAPHY-WORKFLOW",
                        "remove manuscript-production or audit-process notes from bibliography metadata",
                        path=path,
                        line=index + 1,
                        root=report_root,
                    )
                )

    body_text = "\n".join(combined_body)
    declaration_text = " ".join(declaration_parts)
    has_declaration = bool(declaration_parts)
    code_assistance_relevant = bool(CODE_CUE.search(body_text))
    lean_assistance_relevant = bool(LEAN_CUE.search(body_text))

    if require_ai_declaration and not has_declaration:
        issues.append(
            _issue(
                "STYLE-AI-DECLARATION-MISSING",
                "add one truthful, final AI-use declaration as required by repository policy",
                path=main_path,
                root=report_root,
            )
        )

    if has_declaration:
        requirements: tuple[tuple[str, re.Pattern[str], str], ...] = (
            (
                "STYLE-AI-DISCLOSURE-TOOL",
                re.compile(r"OpenAI\s+GPT[- ]?5\.6.{0,80}Codex", re.IGNORECASE),
                "identify OpenAI GPT-5.6 through Codex in the AI-use declaration",
            ),
            (
                "STYLE-AI-DISCLOSURE-TEXT-PURPOSES",
                re.compile(
                    r"manuscript drafting.{0,120}editing.{0,120}technical preparation",
                    re.IGNORECASE | re.DOTALL,
                ),
                "state manuscript drafting, editing, and technical preparation among the disclosed purposes",
            ),
            (
                "STYLE-AI-DISCLOSURE-ACCOUNTABILITY",
                re.compile(r"(?:take|accept) full responsibility", re.IGNORECASE),
                "state full human-author responsibility for the article and associated materials",
            ),
            (
                "STYLE-AI-DISCLOSURE-EVIDENCE-BOUNDARY",
                re.compile(
                    r"(?:"
                    r"AI-generated output.{0,180}(?:not treated|did not serve).{0,100}"
                    r"(?:evidence|mathematical proof|formal verification)"
                    r"|unverified model responses.{0,100}(?:not used|did not serve).{0,100}"
                    r"(?:evidence|mathematical proof|formal verification)"
                    r"|all results.{0,120}established by.{0,80}self-contained proofs"
                    r".{0,120}do not depend on exploratory computations"
                    r")",
                    re.IGNORECASE | re.DOTALL,
                ),
                "distinguish unverified model responses from independently checked evidence, proof, or formal verification",
            ),
        )
        for code, pattern, message in requirements:
            if not pattern.search(declaration_text):
                issues.append(
                    _issue(code, message, path=next(iter(declaration_ranges)), root=report_root)
                )
        if code_assistance_relevant:
            if not re.search(
                r"source[- ]code development|development.{0,60}(?:source )?code",
                declaration_text,
                re.IGNORECASE | re.DOTALL,
            ):
                issues.append(
                    _issue(
                        "STYLE-AI-DISCLOSURE-CODE",
                        "disclose AI assistance with source-code development when computational code is part of the work",
                        path=next(iter(declaration_ranges)),
                        root=report_root,
                    )
                )
            if not re.search(
                r"(?:inspected|reviewed).{0,100}code.{0,120}"
                r"(?:tested|executed|validated|checked)",
                declaration_text,
                re.IGNORECASE | re.DOTALL,
            ):
                issues.append(
                    _issue(
                        "STYLE-AI-DISCLOSURE-CODE-VALIDATION",
                        "state that human authors inspected the AI-assisted code and executed or validated the checks",
                        path=next(iter(declaration_ranges)),
                        root=report_root,
                    )
                )
        if lean_assistance_relevant:
            if not re.search(r"Lean (?:code|formalization)", declaration_text, re.IGNORECASE):
                issues.append(
                    _issue(
                        "STYLE-AI-DISCLOSURE-LEAN",
                        "disclose preparation and checking of Lean code when the manuscript reports an AI-assisted Lean formalization",
                        path=next(iter(declaration_ranges)),
                        root=report_root,
                    )
                )
            if not re.search(
                r"(?:"
                r"pinned Lean toolchain.{0,160}(?:not|rather than).{0,100}AI output"
                r"|(?:formal-verification claims|formal checking).{0,160}"
                r"(?:based on|performed by).{0,160}pinned Lean toolchain"
                r")",
                declaration_text,
                re.IGNORECASE | re.DOTALL,
            ):
                issues.append(
                    _issue(
                        "STYLE-AI-DISCLOSURE-LEAN-BOUNDARY",
                        "attribute formal checking to the pinned Lean toolchain rather than to AI output",
                        path=next(iter(declaration_ranges)),
                        root=report_root,
                    )
                )

    unique: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for item in issues:
        marker = (item.get("code"), item.get("path"), item.get("line"), item.get("message"))
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(item)
    return {
        "valid": not unique,
        "main_tex": _relative(main_path, report_root),
        "checked_files": [
            _relative(path, report_root) for path in [*files, *bibliography_files]
        ],
        "ai_declaration": {
            "present": has_declaration,
            "code_assistance_relevant": code_assistance_relevant,
            "lean_assistance_relevant": lean_assistance_relevant,
        },
        "errors": unique,
        "warnings": [],
    }


def audit_manuscript_style(
    paper_id: str,
    *,
    root: str | Path,
    require_ai_declaration: bool | None = None,
) -> dict[str, Any]:
    """Audit the canonical compiled manuscript registered for ``paper_id``."""

    repo_root = Path(root).resolve()
    settings = load_registry(
        repo_root,
        include_local_repositories=False,
        paper_ids=[paper_id],
    )
    if require_ai_declaration is None:
        require_ai_declaration = bool(
            settings.get("quality_gate", {}).get("require_ai_use_declaration", True)
        )
    metadata = load_paper_metadata(paper_id, repo_root)
    manuscript = repo_root / str(
        metadata.get("manuscript_dir") or f"papers/{paper_id}/manuscript"
    )
    main_tex = repo_root / str(
        metadata.get("latest_source") or f"papers/{paper_id}/manuscript/main.tex"
    )
    if not manuscript.is_dir() or not main_tex.is_file():
        return {
            "paper_id": paper_id,
            "valid": False,
            "main_tex": _relative(main_tex, repo_root),
            "checked_files": [],
            "ai_declaration": {
                "present": False,
                "code_assistance_relevant": False,
                "lean_assistance_relevant": False,
            },
            "errors": [
                _issue(
                    "STYLE-MANUSCRIPT-MISSING",
                    "canonical manuscript source is missing",
                    path=main_tex,
                    root=repo_root,
                )
            ],
            "warnings": [],
        }
    result = audit_tex_tree(
        main_tex,
        manuscript=manuscript,
        root=repo_root,
        require_ai_declaration=require_ai_declaration,
    )
    version = str(metadata.get("version") or "").strip()
    submission_root = repo_root / f"papers/{paper_id}/journal-submissions"
    package_files: list[Path] = []
    if version and submission_root.is_dir():
        for package in sorted(submission_root.glob(f"*/v{version}")):
            for name in ("main.tex", "cover_letter.md", "submission_checklist.md"):
                candidate = package / name
                if candidate.is_file():
                    package_files.append(candidate)
                    for index, raw in enumerate(
                        candidate.read_text(encoding="utf-8").splitlines()
                    ):
                        if UNRESOLVED_SOURCE_MARKER.search(raw):
                            result["errors"].append(
                                _issue(
                                    "STYLE-UNRESOLVED-MARKER",
                                    "remove unresolved TODO/TBD/FIXME markers from the current submission package",
                                    path=candidate,
                                    line=index + 1,
                                    root=repo_root,
                                )
                            )
                        if UNRESOLVED_SUBMISSION_MARKER.search(raw):
                            result["errors"].append(
                                _issue(
                                    "STYLE-UNCONFIRMED-SUBMISSION-TEXT",
                                    "move human-only follow-up items to production/human_action_checklist.md outside the submission package",
                                    path=candidate,
                                    line=index + 1,
                                    root=repo_root,
                                )
                            )
                        if name == "submission_checklist.md" and re.match(
                            r"\s*-\s*\[\s\]", raw
                        ):
                            result["errors"].append(
                                _issue(
                                    "STYLE-UNCHECKED-SUBMISSION-ITEM",
                                    "submission packages must not contain unchecked internal workflow items",
                                    path=candidate,
                                    line=index + 1,
                                    root=repo_root,
                                )
                            )
    result["submission_package_checked_files"] = [
        _relative(path, repo_root) for path in package_files
    ]
    defaults = settings.get("defaults")
    defaults = defaults if isinstance(defaults, Mapping) else {}
    policies = defaults.get("funding")
    policies = policies if isinstance(policies, list) else []
    authors = metadata.get("authors")
    if isinstance(authors, Mapping):
        authors = authors.get("people")
    authors = authors if isinstance(authors, list) else []
    restricted = ineligible_funding(policies, authors, policies=policies)
    funding_issues: list[dict[str, Any]] = []
    for policy in restricted:
        grant_number = str(policy.get("grant_number") or "").strip()
        if not grant_number:
            continue
        eligibility = policy.get("eligibility")
        eligibility = eligibility if isinstance(eligibility, Mapping) else {}
        required = eligibility.get("requires_author")
        required = required if isinstance(required, Mapping) else {}
        required_name = str(
            required.get("name") or required.get("name_zh") or "required author"
        )
        required_name_zh = str(required.get("name_zh") or "").strip()
        if required_name_zh and required_name_zh != required_name:
            required_name = f"{required_name} ({required_name_zh})"
        for path in _tex_tree(main_tex, manuscript):
            for index, raw in enumerate(path.read_text(encoding="utf-8").splitlines()):
                if grant_number not in _strip_tex_comment(raw):
                    continue
                funding_issues.append(
                    _issue(
                        "STYLE-FUNDING-AUTHOR-ELIGIBILITY",
                        f"remove grant {grant_number}: it may be listed only when "
                        f"{required_name} is a registered author",
                        path=path,
                        line=index + 1,
                        root=repo_root,
                    )
                )
    result["errors"].extend(funding_issues)
    result["valid"] = not result["errors"]
    result["paper_id"] = paper_id
    return result


def manuscript_style_blockers(result: Mapping[str, Any]) -> list[str]:
    """Project style-check failures into stable quality-gate blockers."""

    blockers: list[str] = []
    for issue in result.get("errors", []):
        if not isinstance(issue, Mapping):
            continue
        location = str(issue.get("path") or "")
        if issue.get("line") is not None:
            location = f"{location}:{issue['line']}"
        prefix = f"{issue.get('code')}: "
        if location:
            prefix += f"{location}: "
        blockers.append(prefix + str(issue.get("message") or "manuscript style check failed"))
    return blockers
