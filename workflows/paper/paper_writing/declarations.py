"""Render and check paper-bound declarations, never infer contributor facts."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from paper_writing.registry import load_paper_metadata
from paper_writing.ai_disclosure import configured_attempts_for_record, model_disclosure_issues, model_usage_for_record

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
    tail = re.split(r"\\(?:bibliograph\w*|begin\{thebibliography\}|end\{document\}|sloppy\b|hbadness\b|appendix\b)", tail, maxsplit=1)[0]
    # Bibliography inclusion commands produce no declaration prose. Remove only
    # the command, so any actual text following it still participates in binding.
    tail = re.sub(r"\\nocite\s*\{[^{}]*\}", "", tail)
    # A final explicit references include is bibliography, not inline prose.
    # Do not remove arbitrary inputs or an include followed by declaration text.
    tail = re.sub(r"\s*\\input\s*\{references(?:\.tex)?\}\s*$", "", tail)
    # A final appendix include starts the appendices, which are not declaration prose.
    tail = re.sub(r"\s*\\input\s*\{appendi(?:x|ces)\w*(?:\.tex)?\}\s*$", "", tail)
    # A locally sized bibliography may start its group before bibliographystyle.
    # Strip only trailing layout tokens; prose after a token stays hash-bound.
    tail = re.sub(r"(?:\s*\\(?:begingroup|small|footnotesize)\b)+\s*$", "", tail)
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


def contribution_authors(metadata: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Read explicit roles from legacy lists or the canonical people mapping."""
    authors = metadata.get("authors", [])
    if isinstance(authors, Mapping):
        people = authors.get("people")
        names = authors.get("names")
    else:
        people, names = authors, None
    if not isinstance(people, list) or any(not isinstance(p, Mapping) for p in people):
        raise ValueError("Explicit author records are required")
    if names is not None and (not isinstance(names, list) or
                              names != [p.get("name") for p in people]):
        raise ValueError("Author names must match the explicit people in byline order")
    # Reuse the same nonempty, unique-name and explicit-role checks for both schemas.
    render_contributions(people)
    return people


def ai_template_id(templates: Mapping[str, Any], journal: Any = None, root: Path | None = None) -> str:
    """The default AI template, or the one registered for the journal's publisher family.

    ``venue_ai_templates`` maps a family (``nature_portfolio``) to a template id; the
    wording stays the user's default two sentences, only the heading (and so the place in
    the end matter) follows the family's precedent.
    """
    from paper_writing.publisher_family import venue_family

    family = venue_family(journal, root)
    by_family = templates.get("venue_ai_templates") or {}
    if family and isinstance(by_family, Mapping) and by_family.get(family) in (templates.get("ai_templates") or {}):
        return str(by_family[family])
    return str(templates["default_ai_template_id"])


def default_ai_wording(root: Path, usage: Any, *, plural: bool, journal: Any = None) -> tuple[str, str]:
    """Return the registered template filled with the paper's actual tools and purposes."""
    import yaml

    path = root / "registry/paper-declarations/templates.yaml"
    if not path.is_file() or not isinstance(usage, list) or not usage:
        return "", ""
    if not all(isinstance(item, Mapping) and item.get("model") and item.get("purpose") for item in usage):
        return "", ""
    templates = yaml.safe_load(path.read_text())
    template = templates["ai_templates"][ai_template_id(templates, journal, root)]
    if not template.get("automatically_reusable"):
        return "", ""
    tools = ", ".join(dict.fromkeys(f"{item['model']} through {item.get('tool')}" for item in usage))
    purposes = ", ".join(dict.fromkeys(str(item["purpose"]) for item in usage))
    if re.search(r"[\\{}%$&#_^~]", purposes + tools):
        return "", ""
    text = template["text_template"].replace("[NAME OF TOOL/SERVICE]", tools).replace("[REASON]", purposes)
    text = text.replace("author(s)", "authors" if plural else "author")
    text = text.replace("reviewed and edited the output as needed and take", "take" if plural else "takes")
    return template["heading_latex"], text


def missing_default_contributions(metadata: Mapping[str, Any], root: Path) -> bool:
    from paper_writing.review_flow import expand_tex

    declaration = (metadata.get("declarations") or {}).get("author_contributions") or {}
    if not declaration.get("include_in_manuscript", True):
        return False
    path = (root / str(metadata.get("latest_source") or "")).resolve()
    if not path.is_file() or not path.is_relative_to(root / "papers" / str(metadata.get("paper_id") or "")):
        return False
    if not (root / "registry/paper-declarations/templates.yaml").is_file():
        return False
    return not any("contribution" in match.group(1).lower()
                   for match in HEADING.finditer(expand_tex(path, path.parent)))


def apply_default_declarations(paper_id: str, root: Path, *, contributions_only: bool = False) -> dict[str, Any]:
    """Repair inline declarations using the registered byline and verified model uses."""
    from paper_writing.registry import load_registry_settings

    root = Path(root).resolve()
    metadata = load_paper_metadata(paper_id, root)
    path = (root / str(metadata.get("latest_source") or "")).resolve()
    paper = root / "papers" / paper_id
    if not path.is_relative_to(paper) or not path.is_file():
        return {"changed": False}
    usage = model_usage_for_record(metadata)
    authors = metadata.get("authors") or load_registry_settings(root).get("defaults", {}).get("authors", [])
    try:
        people = contribution_authors({"authors": authors})
    except ValueError:
        return {"changed": False}
    source = path.read_text()
    heading, old = section(source, "ai_use")
    if heading:
        start = source.index(heading)
    else:
        anchor = re.search(r"\\(?:bibliographystyle|bibliography|end\{document\})", source)
        if not anchor:
            return {"changed": False}
        start = anchor.start()
    replacement = ""
    end = start
    if not contributions_only and not (metadata.get("declarations") or {}).get("ai_use", {}).get("text_sha256"):
        default_heading, text = default_ai_wording(root, usage, plural=len(people) > 1,
                                                   journal=metadata.get("target_journal"))
        if text and not model_disclosure_issues(text, usage, root=root):
            if not heading or (old and old in source and "\\" not in old):
                if heading:
                    end = source.index(old, start + len(heading)) + len(old)
                replacement = default_heading + "\n" + text + ("\n\n" if not heading else "")
    if missing_default_contributions({**metadata, "paper_id": paper_id}, root):
        replacement = r"\section*{Author contributions}" + "\n" + contributions_latex(people) + "\n\n" + replacement
    updated = source[:start] + replacement + source[end:]
    if updated != source:
        path.write_text(updated)
    return {"changed": updated != source}


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
            try:
                authors = contribution_authors(metadata)
                names = [a["name"] for a in authors]
                positions = [text.find(n) for n in names]
                if any(p < 0 for p in positions) or positions != sorted(positions) or any(text.count(n) != 1 for n in names):
                    errors.append("author_contributions: all byline authors must appear once, in order")
                role_text = contributions_latex(authors)
                if normalized(text) != normalized(role_text):
                    errors.append("author_contributions: statement differs from explicit author roles")
            except ValueError as exc:
                errors.append(f"author_contributions: {exc}")
        if kind == "ai_use" and model_usage_for_record(metadata) is not None:
            errors.extend("ai_use: " + message for _, message in
                          model_disclosure_issues(text, model_usage_for_record(metadata), root=root,
                              configured_attempts=configured_attempts_for_record(metadata)))
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
