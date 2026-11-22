"""Read-only mechanical checks shared by the author seat and delivery."""
import hashlib
import json
from pathlib import Path
import re

from . import declarations, narrative_check
from .ai_disclosure import (
    configured_attempts_for_record, model_disclosure_issues, model_usage_for_record, tool_disclosure_issues,
)
from .figure_quality import read_plan
from .figure_standard import ENV, GRAPHIC, STANDARD
from .figures import discover, workspace
from . import registry, venue_registry


def _arguments(source, names):
    pattern = r"\\(?:" + names + r")\*?\s*(?:\[([^\]]*)\]\s*)?\{"
    for match in re.finditer(pattern, source):
        opening = match.end() - 1
        end = narrative_check._balanced(source, opening)
        if end > opening:
            value = source[match.end():end - 1]
            if re.search(r"\w", re.sub(r"\\[A-Za-z]+", "", value)):
                yield (match.group(1) or ""), value


def _main_figures(source, manuscript, plan):
    kinds = {item.stem: item.kind for item in discover(workspace(manuscript=manuscript))}
    kinds.update({row["figure"]: row["kind"] for row in plan.get("figures", [])})
    counts = {"schematic": 0, "result": 0, "main_figures": 0}
    files = set()
    seen = set()
    for figure in ENV.finditer(source):
        panels = set()
        for graphic in GRAPHIC.findall(figure[2]):
            path = manuscript / graphic
            candidates = [path] if path.suffix else [path.with_suffix(s) for s in (".pdf", ".png", ".jpg", ".jpeg")]
            candidates += [manuscript / "figures" / p.name for p in candidates]
            resolved = {p.resolve() for p in candidates if p.is_file() and p.resolve().is_relative_to(manuscript)}
            if len(resolved) == 1:
                panels.update(resolved)
        files.update(panels)
        new_panels = panels - seen
        seen.update(panels)
        if new_panels:
            counts["main_figures"] += 1
        for kind in {kinds.get(path.stem) for path in new_panels} & {"schematic", "result"}:
            counts[kind] += 1
    return counts, files


def _reviewed_images(record, manuscript, files):
    reader = record.get("delivery_reader") or {}
    receipt = (record.get("receipts") or {}).get("delivery_reader") or {}
    bindings = reader.get("image_inputs") or {}
    attached = {item.get("sha256") for item in receipt.get("images") or []}
    return bool(files and attached and receipt.get("independent_context")
                and str(reader.get("supporting_panel") or "").strip() and not reader.get("image_errors")
                and set(reader.get("image_sha256") or []) == attached
                and all(bindings.get(path.relative_to(manuscript).as_posix()) ==
                        hashlib.sha256(path.read_bytes()).hexdigest() for path in files))


def check(paper_id, metadata, root, record=None, *, author=False):
    """Return counts and actionable issues without changing source or review state."""
    from .review_flow import expand_tex

    root = Path(root).resolve()
    manuscript = (root / str(metadata.get("manuscript_dir") or f"papers/{paper_id}/manuscript")).resolve()
    main = (root / str(metadata.get("latest_source") or manuscript / "main.tex")).resolve()
    if not main.is_file() or not main.is_relative_to(manuscript):
        message = "The registered manuscript source is missing or outside the manuscript directory."
        return {"metrics": {}, "issues": [dict(source="delivery_floor", code="FLOOR-SOURCE-MISSING",
                                               location="main.tex", message=message, text=message)]}
    source = re.sub(r"(?<!\\)%[^\n]*", "", expand_tex(main, manuscript))
    settings = registry.load_registry_settings(root) if (root / "registry/settings.yaml").is_file() else {}
    line = narrative_check._research_line(root, metadata.get("research_line"))
    limits, sources = narrative_check.resolve_limits(metadata, settings=settings, line=line)
    venue = venue_registry.find_venue(venue_registry.load_venues(root),
                                      journal=metadata.get("target_journal"), issn=metadata.get("target_journal_issn"))
    venue_limits = (venue or {}).get("article_types") or {}
    article_type = narrative_check.article_type(metadata)
    registered_type = metadata.get("target_journal_article_type") or article_type
    venue_minimum = (venue_limits.get(registered_type) or {}).get("min_body_words")
    if type(venue_minimum) is int and venue_minimum > 0 and "min_body_words" not in (metadata.get("narrative_limits") or {}):
        limits["min_body_words"] = venue_minimum
        sources.append(f"verified-venues:{registered_type}")
    words = narrative_check.body_words_of_text(source, limits)
    issues = []

    def issue(code, message):
        issues.append(dict(source="delivery_floor", code=code, location="main.tex",
                           message=message, text=f"{code}: {message}"))

    preamble = re.split(r"\\(?:section\*?\s*\{|begin\{abstract\})", source, maxsplit=1)[0]
    authors = list(_arguments(preamble, "author|Author"))
    affiliations = list(_arguments(preamble, "affiliation|affil|address|institute|institution"))
    if not authors:
        issue("BYLINE-MISSING", "Add the approved author byline to the manuscript.")
    inline = any(re.search(r"\\IEEEauthorblockA\s*\{", byline) or (
        re.search(r"\\\\|\\(?:and|thanks)\b", byline) and
        re.search(r"university|institute|laborator|college|department|centre|center|independent", byline, re.I)
    ) for _, byline in authors)
    author_ids = {part.strip() for ids, _ in authors for part in ids.split(",") if part.strip()}
    affiliation_ids = {part.strip() for ids, _ in affiliations for part in ids.split(",") if part.strip()}
    if (not affiliations and not inline) or author_ids - affiliation_ids:
        issue("AFFILIATION-MISSING", "Include the approved affiliations and resolve each byline affiliation label.")
    minimum = limits["min_body_words"]
    if type(minimum) is not int or minimum < 1:
        raise ValueError("min_body_words must be a positive integer")
    if words < minimum:
        issue("BODY-BELOW-MINIMUM", f"Main text has {words} words; the article-type minimum is {minimum}.")
    body_start, body_end = narrative_check.find_regions(source).body
    plan, _ = read_plan(manuscript)
    profiles = STANDARD["profiles"]
    line_id = metadata.get("research_line")
    line_profiles = {"power-market-backtest": "market_dispatch", "phm-evaluation-audit": "rank_audit",
                     "eb-photometry": "single_target"}
    profile_id = (plan.get("manuscript_type") or metadata.get("figure_profile")
                  or (line or {}).get("figure_profile") or line_profiles.get(line_id))
    if not profile_id and "photometry" in paper_id:
        profile_id = "single_target"
    profile = profiles.get(profile_id) if isinstance(profile_id, str) else None
    min_results = profile["main_figures"][0] - 1 if profile else 1
    counts, paths = _main_figures(source[body_start:body_end], manuscript, plan)
    if not counts["schematic"]:
        issue("SCHEMATIC-MISSING", "Include and classify at least one main-text design schematic.")
    if counts["result"] < min_results:
        issue("RESULT-FIGURES-BELOW-MINIMUM",
              f"Main text has {counts['result']} classified result figures; minimum is {min_results}.")
    if not author and not _reviewed_images(record or {}, manuscript, paths):
        issue("FIGURES-NOT-REVIEWED", "Obtain an independent visual review with image receipts bound to these figures.")
    usage = model_usage_for_record(metadata)
    try:
        _, statement = declarations.section(source, "ai_use")
    except ValueError:
        statement = ""
    tool_errors, _ = tool_disclosure_issues(statement, usage)
    if not statement or not usage or tool_errors or model_disclosure_issues(
        statement, usage, root=root, configured_attempts=configured_attempts_for_record(metadata)
    ):
        issue("AI-USE-UNVERIFIED", "Generate the AI-use declaration from verified runtime model records.")
    return {"metrics": {"main_text_words": words, "min_body_words": minimum, "length_sources": sources,
                        "figure_profile": profile_id, "min_result_figures": min_results, **counts}, "issues": issues}


def audit(paper_id, root, *, author=False):
    from .registry import load_paper_metadata

    root = Path(root).resolve()
    metadata = load_paper_metadata(paper_id, root)
    path = (root / str((metadata.get("writing_release") or {}).get("decision_record") or "")).resolve()
    record = json.loads(path.read_text()) if not author and path.is_relative_to(root) and path.is_file() else None
    return check(paper_id, metadata, root, record, author=author)
