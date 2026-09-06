"""Render and check paper-bound declarations, never infer contributor facts."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from paper_writing.registry import load_paper_metadata
from paper_writing.ai_disclosure import model_disclosure_issues, model_usage_for_record

HEADING = re.compile(r"\\(?:section|subsection|paragraph)\*?\{([^}\n]*)\}")
AI = re.compile(r"\bAI\b|\bgenerative\b|artificial intelligence", re.I)
CREDIT_ROLES = frozenset({
    "Conceptualization", "Data curation", "Formal analysis", "Funding acquisition",
    "Investigation", "Methodology", "Project administration", "Resources", "Software",
    "Supervision", "Validation", "Visualization", "Writing – original draft",
    "Writing – review & editing",
})


def normalized(text: str) -> str:
    return " ".join(text.split())


def section(source: str, kind: str) -> tuple[str, str]:
    """Read an inline declaration; do not include following TeX layout commands."""
    headings = list(HEADING.finditer(source))
    found = [i for i, h in enumerate(headings)
             if (bool(AI.search(h.group(1))) if kind == "ai_use" else "contribution" in h.group(1).lower())]
    if len(found) > 1:
        raise ValueError(f"Duplicate {kind} sections")
    if not found:
        return "", ""
    i = found[0]
    h = headings[i]
    end = headings[i + 1].start() if i + 1 < len(headings) else len(source)
    tail = source[h.end():end]
    tail = re.split(r"\\(?:bibliograph\w*|end\{document\}|sloppy\b|hbadness\b)", tail, maxsplit=1)[0]
    return h.group(0), tail.strip()


def render_contributions(authors: list[Mapping[str, Any]]) -> str:
    """Require complete explicit roles and output them in this paper's byline order."""
    names = [str(a.get("name") or "") for a in authors]
    if not names or any(not n for n in names) or len(set(names)) != len(names):
        raise ValueError("Nonempty unique author names are required")
    lines = []
    for author, name in zip(authors, names):
        roles = author.get("credit_roles")
        if not isinstance(roles, list) or not roles or any(not isinstance(r, str) or not r.strip() for r in roles):
            raise ValueError(f"Missing explicit contributor roles: {name}")
        if len(roles) != len(set(roles)) or any(r not in CREDIT_ROLES for r in roles):
            raise ValueError(f"Invalid or duplicate CRediT roles: {name}")
        lines.append(f"{name}: {', '.join(roles)}.")
    return "\n".join(lines)


def contributions_latex(authors: list[Mapping[str, Any]]) -> str:
    return render_contributions(authors).replace("–", "--").replace("&", r"\&")


def check_record(metadata: Mapping[str, Any], source: str, *, root: Path | None = None) -> dict[str, Any]:
    """Check completeness and text binding, not scientific truth or journal acceptance."""
    errors = []
    declarations = metadata.get("declarations") or {}
    rendered = {}
    for kind in ("author_contributions", "ai_use"):
        record = declarations.get(kind)
        if not isinstance(record, Mapping):
            errors.append(f"{kind}: metadata missing")
            continue
        expected_heading = str(record.get("heading_latex") or "")
        expected_text = str(record.get("text_latex") or "")
        heading, text = section(source, kind)
        included = record.get("include_in_manuscript", True)
        if included:
            if not expected_heading or not expected_text:
                errors.append(f"{kind}: metadata text or heading missing")
            if normalized(heading) != normalized(expected_heading) or normalized(text) != normalized(expected_text):
                errors.append(f"{kind}: canonical source differs from metadata")
            rendered[kind] = expected_heading + "\n" + expected_text
        elif kind == "author_contributions":
            if record.get("requirement") not in ("recommended", "optional", "not_required") or not record.get("requirement_sources"):
                errors.append("author_contributions: omission requires a sourced nonmandatory policy")
            if heading or text:
                errors.append("author_contributions: omitted declaration remains in source")
            rendered[kind] = ""
        else:
            errors.append("ai_use: an existing required disclosure cannot be suppressed by metadata")
        if kind == "author_contributions" and included:
            names = [a["name"] for a in metadata.get("authors", [])]
            positions = [text.find(n) for n in names]
            if not names or any(p < 0 for p in positions) or positions != sorted(positions) or any(text.count(n) != 1 for n in names):
                errors.append("author_contributions: all byline authors must appear once, in order")
            try:
                role_text = contributions_latex(metadata.get("authors", []))
                if normalized(text) != normalized(role_text):
                    errors.append("author_contributions: statement differs from explicit author roles")
            except ValueError as exc:
                errors.append(f"author_contributions: {exc}")
        if kind == "ai_use" and model_usage_for_record(metadata) is not None:
            errors.extend("ai_use: " + message for _, message in
                          model_disclosure_issues(text, model_usage_for_record(metadata), root=root))
        if kind == "ai_use" and re.search(r"human\s+authors", text, re.I):
            errors.append("ai_use: rejected wording remains in this extracted template")
        digest = hashlib.sha256(normalized(expected_text).encode()).hexdigest()
        if record.get("text_sha256") != digest:
            errors.append(f"{kind}: metadata text checksum mismatch")
    return {"paper_id": metadata.get("paper_id"), "version": metadata.get("version"),
            "valid": not errors, "errors": errors, "rendered_latex": rendered}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper-id", required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--latex", action="store_true", help="Print the paper-bound declarations only when checks pass")
    args = parser.parse_args(argv)
    metadata = load_paper_metadata(args.paper_id, args.root)
    source = (args.root / metadata["manuscript_dir"] / "main.tex").read_text()
    result = check_record(metadata, source, root=args.root.resolve())
    if args.latex and result["valid"]:
        print("\n\n".join(t for t in result["rendered_latex"].values() if t))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
