"""Presentation requirements for numbered TeX figures, shared by repair and review."""
import json
from pathlib import Path
import re

from .narrative_check import _balanced

STANDARD = json.loads(Path(__file__).with_name("figure-standards.json").read_text())
ENV = re.compile(r"\\begin\{(figure\*?|wrapfigure|SCfigure)\}(.*?)\\end\{\1\}", re.S)
GRAPHIC = re.compile(r"\\includegraphics\*?(?:\s*\[[^\]]*\])?\s*\{([^{}]+)\}")
CAPTION = re.compile(r"\\caption\*?(?:\s*\[[^\]]*\])?\s*\{")
ENCODING = re.compile(r"\b(points?|dots?|lines?|bands?|shad\w*|colou?rs?|symbols?|markers?|bars?|dashed|solid|diamonds?|crosses|circles?|curves?|blue|orange)\b", re.I)


def findings(plan, tex):
    issues = []

    def issue(name, code, message):
        issues.append(dict(figure=name, code="FIG-STANDARD-" + code, message=message))

    genre = plan.get("manuscript_type")
    profile = STANDARD["profiles"].get(genre) if isinstance(genre, str) else None
    reason = plan.get("count_reason")
    justified = isinstance(reason, str) and bool(reason.strip())
    if not profile and not (genre == "other" and justified):
        issue("plan", "TYPE", "Declare manuscript_type from figure-standards.json and map figures to evidence_stages.")
    main = re.split(r"\\(?:appendix\b|begin\{appendices\})", re.sub(r"(?<!\\)%[^\n]*", "", tex))[0]
    figures = list(ENV.finditer(main))
    if profile and not profile["main_figures"][0] <= len(figures) <= profile["main_figures"][1] and not justified:
        issue("plan", "COUNT", f"{len(figures)} main figures; reference {profile['main_figures']}. Supply a count_reason.")
    by_name = {item["figure"]: item for item in plan.get("figures", [])}
    covered = set()
    if profile:
        for item in by_name.values():
            stages = item.get("evidence_stages")
            if not isinstance(stages, list) or not stages or not all(
                isinstance(stage, str) and stage in profile["stages"] for stage in stages
            ):
                issue(item["figure"], "MAPPING", "List applicable profile stage IDs in evidence_stages.")

    for number, match in enumerate(figures, 1):
        body = match[2]
        names = [Path(path).stem for path in GRAPHIC.findall(body)]
        items = [by_name[name] for name in dict.fromkeys(names) if name in by_name]
        stages = set()
        for item in items:
            declared = item.get("evidence_stages")
            if isinstance(declared, list):
                stages.update(s for s in declared if isinstance(s, str))
        covered.update(stages)
        name = f"Figure {number}"
        if profile and number == 1 and profile["first_stage"] not in stages:
            issue(name, "FIRST", profile["figure_one"])
        result = any(item["kind"] == "result" for item in items)
        if result and len(items) == 1:
            item = items[0]
            panels = item.get("panels")
            if type(panels) is not int or panels < 1:
                issue(name, "PANELS", "Declare the number of distinct panels.")
            elif panels == 1 and not (isinstance(item.get("single_panel_reason"), str) and item["single_panel_reason"].strip()):
                issue(name, "GROUP", "Pair the result with its aligned comparison or justify the single panel.")
        heading = CAPTION.search(body)
        caption = body[heading.end():_balanced(body, heading.end()-1)-1] if heading else ""
        if len(re.findall(r"\b[\w-]+\b", caption)) < STANDARD["caption_review_floor_words"]:
            issue(name, "CAPTION", "Review short caption at column width; explain the comparison, units and sample.")
        if result and not ENCODING.search(caption):
            issue(name, "ENCODING", STANDARD["caption_rule"])
    if profile:
        for stage in profile["stages"]:
            if stage not in covered:
                issue("plan", "STAGE", f"Map main-text evidence to {stage}.")
        coverage = plan.get("supplement_coverage")
        if not isinstance(coverage, dict) or not coverage or not all(
            isinstance(value, str) and value.strip() for value in coverage.values()
        ):
            issue("plan", "SUPPLEMENT", profile["supplement"])
    return issues
