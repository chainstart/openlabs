"""Read-only mechanical checks shared by the author seat and delivery."""
from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
import re
import unicodedata

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


def _letters(text):
    """Casefolded letters only; TeX accents and commands dropped (M\\"uller, \\fnm{A} -> a)."""
    text = re.sub(r"\\[A-Za-z]+\*?|\\.", "", str(text or ""))
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return re.sub(r"[^\w]|[\d_]", "", text).casefold()


def registry_byline_issues(metadata, byline_text=None):
    """The registered byline the management site, Zenodo and declarations read (2026-11-24).

    The manuscript byline alone is not enough: TIC 236779149 v0.1.2 was delivered with authors
    and affiliations in main.tex but none in its registry record, so the site showed "authors
    missing" and the submitter fell back to the default roster. ``byline_text`` (the manuscript's
    author arguments) is also checked to name every registered author's family name.
    """
    raw = metadata.get("authors")
    people = raw.get("people") if isinstance(raw, Mapping) else raw
    people = [p for p in people if isinstance(p, Mapping)] if isinstance(people, list) else []
    named = [p for p in people if str(p.get("name") or "").strip()]
    if not named:
        return [("REGISTRY-AUTHORS-MISSING",
                 "Register the approved byline (authors with affiliation_ids, default roster "
                 "registry/settings.yaml#defaults.authors unless the paper has its own) in the paper "
                 "record: the management site, Zenodo and the declarations read the registry, not main.tex.")]
    issues = []
    known = {str(item.get("id")) for item in metadata.get("affiliations") or []
             if isinstance(item, Mapping) and item.get("id") and str(item.get("name") or "").strip()}
    wanted = {str(ref) for person in named for ref in person.get("affiliation_ids") or []}
    if any(not person.get("affiliation_ids") for person in named) or wanted - known:
        issues.append(("REGISTRY-AFFILIATIONS-MISSING",
                       "Give every registered author affiliation_ids that resolve to the paper record's "
                       "affiliations (id and name)."))
    if byline_text is not None and byline_text.strip():
        present = _letters(byline_text)
        missing = [str(p["name"]) for p in named
                   if (family := _letters(str(p["name"]).split()[-1])) and family not in present]
        if missing:
            issues.append(("BYLINE-REGISTRY-MISMATCH",
                           "The manuscript byline does not name these registered authors: "
                           + ", ".join(missing) + ". Make main.tex and the registry byline agree."))
    return issues


def _main_figure_entries(source, manuscript, plan):
    """Main-text figures in order: the panel files each introduces and their classified kind."""
    kinds = {item.stem: item.kind for item in discover(workspace(manuscript=manuscript))}
    kinds.update({row["figure"]: row["kind"] for row in plan.get("figures", [])})
    entries = []
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
        new_panels = panels - seen
        seen.update(panels)
        entries.append({"panels": panels, "new_panels": new_panels,
                        "kinds": {path.stem: kinds.get(path.stem) for path in new_panels}})
    return entries


def _main_figures(source, manuscript, plan):
    counts = {"schematic": 0, "result": 0, "main_figures": 0}
    files = set()
    for entry in _main_figure_entries(source, manuscript, plan):
        files.update(entry["panels"])
        if entry["new_panels"]:
            counts["main_figures"] += 1
        for kind in set(entry["kinds"].values()) & {"schematic", "result"}:
            counts[kind] += 1
    return counts, files


VECTOR_ROUTES = {".svg": "svg_html", ".html": "svg_html", ".htm": "svg_html", ".tex": "tikz"}
_LOCAL_IMPORT = re.compile(r"^\s*(?:import|from)\s+([A-Za-z_]\w*)", re.M)


def schematic_route(manuscript, stem, plan):
    """How a schematic is drawn, from its registered source (2026-11-25, B2; static, no build).

    ``svg_html`` (an .svg/.html source, or a script that composes an SVG through ``$FIG_SVG``,
    itself or through a helper module in figure-src), ``tikz`` (.tex), ``plot`` (a script that
    only writes a matplotlib PDF) or ``unregistered`` (no source in figure-src). ``library``:
    the source draws on the figure asset library (``find_asset``/``svg_fragment``/``assets/``).
    """
    src_dir = manuscript / "figure-src"
    row = next((r for r in plan.get("figures", []) if r.get("figure") == stem), None)
    path = manuscript / row["source"] if row and isinstance(row.get("source"), str) else None
    if path is None or not path.is_file():
        path = next((src_dir / f"{stem}{suffix}" for suffix in (".svg", ".html", ".tex", ".py")
                     if (src_dir / f"{stem}{suffix}").is_file()), None)
    if path is None or not path.resolve().is_relative_to(manuscript):
        return {"figure": stem, "route": "unregistered", "source": None, "library": False}
    text = path.read_text(encoding="utf-8", errors="ignore")
    texts = [text]
    if path.suffix.lower() == ".py":
        for name in set(_LOCAL_IMPORT.findall(text)):
            helper = path.parent / f"{name}.py"
            if helper.is_file() and helper.resolve().is_relative_to(manuscript):
                texts.append(helper.read_text(encoding="utf-8", errors="ignore"))
        route = "svg_html" if any("FIG_SVG" in item for item in texts) else "plot"
    else:
        route = VECTOR_ROUTES.get(path.suffix.lower(), "plot")
    library = any(re.search(r"find_asset|svg_fragment|asset:|assets/", item) for item in texts)
    return {"figure": stem, "route": route, "library": library,
            "source": path.relative_to(manuscript).as_posix()}


def _schematics_reviewed(record, manuscript, files):
    """The ready decision's delivery reader saw exactly these (current) schematic files."""
    if (record.get("merged") or {}).get("outcome") != "ready":
        return False
    bindings = (record.get("delivery_reader") or {}).get("image_inputs") or {}
    return bool(files) and all(
        bindings.get(path.relative_to(manuscript).as_posix()) == hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files)


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
    for code, message in registry_byline_issues(metadata, " ".join(value for _, value in authors)):
        issue(code, message)
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
    entries = _main_figure_entries(source[body_start:body_end], manuscript, plan)
    counts, paths = _main_figures(source[body_start:body_end], manuscript, plan)
    if not counts["schematic"]:
        issue("SCHEMATIC-MISSING", "Include and classify at least one main-text design schematic.")
    # SCHEMATIC-ROUTE (2026-11-25, B2; user 2026-11-23 "既然图都没有画好，怎么能交付呢", criterion
    # approved 2026-11-25): every main-text schematic is drawn from a registered vector source
    # (SVG/HTML with the asset library, or TikZ), and at delivery the ready decision's delivery
    # reader has seen the current schematic files (the presentation/delta review after a redraw).
    schematic_files = {path for entry in entries for path in entry["new_panels"]
                       if entry["kinds"].get(path.stem) == "schematic"}
    routes = [schematic_route(manuscript, stem, plan)
              for stem in sorted({path.stem for path in schematic_files})]
    off_route = [item for item in routes if item["route"] not in {"svg_html", "tikz"}]
    if off_route:
        issue("SCHEMATIC-ROUTE-NOT-VECTOR",
              "Draw these main-text schematics from a registered vector source (SVG/HTML with the "
              "figure asset library, or TikZ) in figure-src: "
              + ", ".join(f"{item['figure']} ({item['route']}: {item['source'] or 'no source'})"
                          for item in off_route) + ".")
    if not author and schematic_files and not _schematics_reviewed(record or {}, manuscript,
                                                                    schematic_files):
        issue("SCHEMATIC-ROUTE-UNREVIEWED",
              "The ready review's delivery reader has not seen the current schematic figures; run "
              "the presentation review (review unified-run --presentation) on the redrawn figures.")
    if counts["result"] < min_results:
        issue("RESULT-FIGURES-BELOW-MINIMUM",
              f"Main text has {counts['result']} classified result figures; minimum is {min_results}.")
    if not author and not _reviewed_images(record or {}, manuscript, paths):
        issue("FIGURES-NOT-REVIEWED", "Obtain an independent visual review with image receipts bound to these figures.")
    from .float_placement import check as placement_check
    pdf = (root / str(metadata.get("latest_pdf") or manuscript / "main.pdf")).resolve()
    placement = placement_check(manuscript, pdf=pdf, main=main)
    for item in placement["errors"]:
        issue(item["code"], f"{item['figure']}: {item['message']}")
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
                        "figure_profile": profile_id, "min_result_figures": min_results, **counts,
                        "schematic_routes": routes,
                        "float_placement": placement["status"]}, "issues": issues}


def audit(paper_id, root, *, author=False):
    from .registry import load_paper_metadata

    root = Path(root).resolve()
    metadata = load_paper_metadata(paper_id, root)
    path = (root / str((metadata.get("writing_release") or {}).get("decision_record") or "")).resolve()
    record = json.loads(path.read_text()) if not author and path.is_relative_to(root) and path.is_file() else None
    return check(paper_id, metadata, root, record, author=author)
