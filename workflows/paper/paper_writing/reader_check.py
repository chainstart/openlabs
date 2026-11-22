"""One-pass simulated reader, run by the writer from inside the writing session.

``paper-writing reader-check --paper-id PID`` gives the title, abstract and main text (no
appendix, no supplement, no author notes) to a model in a fresh process with tools disabled
and asks the fixed questions of a peer reader of the target venue who reads the paper once:
what the paper did in one sentence, what the main result is, where they would stop reading,
which passages defend rather than state, and what could be cut. It is the writer's own
check, not a review: it starts no scheduler task, consumes no review round and its answer
is advice. The record is kept in the paper's writing notes (``papers/<id>/writing/reader-check.md``
and ``.json``, outside the manuscript snapshot and the journal package); the unified review's
editor sees it when writing the decision letter.

Why a fresh model rather than the writer's own reread: the writer knows the story line and
cannot tell where an outsider gets lost; a reader that has seen only the text can. When no
model can be called, ``--prompt-only`` writes the packet for any sub-agent the writer can
start, and ``--record ANSWER.json`` files that answer the same way.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from paper_writing import narrative_check

SCHEMA_VERSION = "openlabs.reader_check.v1"
_TEXT = {"type": "string"}
_PASSAGE = {"type": "object", "additionalProperties": False, "required": ["location", "quote", "why"],
            "properties": {"location": _TEXT, "quote": _TEXT, "why": _TEXT}}
READER_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": ["one_sentence_summary", "main_result", "stopped_reading", "defensive_passages",
                 "hard_to_follow", "cuts", "verdict"],
    "properties": {
        "one_sentence_summary": _TEXT,
        "main_result": _TEXT,
        "stopped_reading": {"type": "object", "additionalProperties": False,
                            "required": ["would_stop", "location", "reason"],
                            "properties": {"would_stop": {"type": "boolean"}, "location": _TEXT,
                                           "reason": _TEXT}},
        "defensive_passages": {"type": "array", "items": _PASSAGE},
        "hard_to_follow": {"type": "array", "items": _PASSAGE},
        "cuts": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                            "required": ["location", "what"],
                                            "properties": {"location": _TEXT, "what": _TEXT}}},
        "verdict": {"type": "string", "enum": ["would_read_to_the_end", "would_skim", "would_stop_early"]},
    },
}

SYSTEM_PROMPT = """You are a working researcher who reads the journal named in the packet. A colleague
sent you this paper. You read it once, from the title to the end of the main text, at the
speed you would read any paper in your field; you do not go back and you do not study the
equations. You are not a referee: do not judge correctness or ask for new analyses.

Answer from the text alone, in the language of the manuscript:

1. one_sentence_summary: in one sentence of your own, what did this paper do? If you cannot
   say it after the abstract and introduction, say so plainly.
2. main_result: the single main result as you understood it, with its key number if any.
3. stopped_reading: where (section or paragraph) you would have stopped reading or started
   skimming, and why. would_stop=false and location "none" if you would read to the end.
4. defensive_passages: passages that defend the authors rather than tell the reader something:
   stacked caveats, repeated limitations, disclaimers, answers to objections nobody raised,
   history of how the analysis changed. Quote a short phrase and give its location.
5. hard_to_follow: passages where you lost the thread (undefined labels, a detour that does
   not return to the main line, detail that belongs in an appendix).
6. cuts: what you would move to an appendix or delete so the main line reads straight through.
7. verdict: would_read_to_the_end, would_skim or would_stop_early.

Be concrete and brief. Quote only text that is in the packet. Return only the JSON object
required by the schema."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def main_text(paper_id: str, root: Path) -> tuple[str, dict[str, Any]]:
    """Title, abstract and main text (up to the appendix or back matter), macros expanded."""
    from paper_writing.registry import load_paper_metadata

    metadata = load_paper_metadata(paper_id, root)
    manuscript = root / str(metadata.get("manuscript_dir") or f"papers/{paper_id}/manuscript")
    main = root / str(metadata.get("latest_source") or f"papers/{paper_id}/manuscript/main.tex")
    lines = narrative_check.flatten_tex(main, manuscript)
    macros = narrative_check._macros("\n".join(item.text for item in lines))
    text = "\n".join(narrative_check._expand_macros(item.text, macros) for item in lines)
    regions = narrative_check.find_regions(text)
    begin = text.find("\\begin{document}")
    start = begin + len("\\begin{document}") if begin >= 0 else 0
    return text[start:regions.body[1]].strip() + "\n", metadata


def packet(paper_id: str, root: Path) -> tuple[str, str, dict[str, Any]]:
    text, metadata = main_text(paper_id, root)
    venue = metadata.get("target_journal") or metadata.get("target_conference") or "a journal in this field"
    body = (f"## Target venue\n{venue}\n\n"
            "## Paper (LaTeX source of the title, abstract and main text; appendices and supplement "
            f"omitted)\n{text}")
    return body, hashlib.sha256(text.encode("utf-8")).hexdigest(), metadata


def reader_role(settings: Mapping[str, Any], override: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Explicit role, else ``quality_gate.reader_check.role``, else the review's worker tier."""
    if override and override.get("model"):
        return dict(override)
    configured = ((settings.get("quality_gate") or {}).get("reader_check") or {}).get("role")
    if isinstance(configured, Mapping) and configured.get("model"):
        return dict(configured)
    roles = (settings.get("review") or {}).get("roles") or {}
    for name in ("formal_verifier", "editor"):
        if isinstance(roles.get(name), Mapping) and roles[name].get("model"):
            return dict(roles[name])
    raise ValueError("No reader model: pass --provider/--tool/--model or set quality_gate.reader_check.role")


def render(record: Mapping[str, Any]) -> str:
    answer = record["answer"]
    stop = answer["stopped_reading"]
    lines = [f"# One-pass reader check: {record['paper_id']}", "",
             f"Manuscript version {record.get('manuscript_version') or '?'}; main text sha256 "
             f"{record['main_text_sha256'][:16]}; reader {record.get('reader_model') or 'unknown'}; "
             f"{record['created_at']}. Author-side self-check, not a review.", "",
             f"**What the paper did (reader's sentence):** {answer['one_sentence_summary']}", "",
             f"**Main result as understood:** {answer['main_result']}", "",
             f"**Verdict:** {answer['verdict']}", "",
             "**Would stop reading:** " + (f"{stop['location']}: {stop['reason']}" if stop["would_stop"]
                                          else "no" + (f" ({stop['reason']})" if stop.get("reason") else ""))]
    for title, key in (("Defensive passages", "defensive_passages"), ("Hard to follow", "hard_to_follow")):
        lines += ["", f"## {title}", ""]
        items = answer.get(key) or []
        lines += [f"- {i['location']}: \"{i['quote']}\" - {i['why']}" for i in items] or ["- none"]
    lines += ["", "## Suggested cuts", ""]
    lines += [f"- {c['location']}: {c['what']}" for c in answer.get("cuts") or []] or ["- none"]
    return "\n".join(lines) + "\n"


def notes_dir(paper_id: str, root: Path) -> Path:
    """``papers/<id>/writing``: the writer's story line and checks, outside the manuscript snapshot."""
    return root / "papers" / paper_id / "writing"


def save(paper_id: str, root: Path, metadata: Mapping[str, Any], digest: str, answer: Mapping[str, Any],
         *, reader: Mapping[str, Any] | None, receipt_dir: Path | None) -> dict[str, Any]:
    from paper_writing.review_launcher import _validate_against_schema

    _validate_against_schema(answer, READER_SCHEMA)
    notes = notes_dir(paper_id, root)
    notes.mkdir(parents=True, exist_ok=True)
    record = {"schema_version": SCHEMA_VERSION, "paper_id": paper_id,
              "manuscript_version": str(metadata.get("version") or ""), "main_text_sha256": digest,
              "created_at": _now(), "reader_model": (reader or {}).get("model"),
              "reader_provider": (reader or {}).get("provider"),
              "receipt_dir": receipt_dir.relative_to(root).as_posix() if receipt_dir else None,
              "answer": dict(answer)}
    (notes / "reader-check.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    (notes / "reader-check.md").write_text(render(record))
    return record | {"paths": [str((notes / name).relative_to(root))
                               for name in ("reader-check.md", "reader-check.json")]}


def run(paper_id: str, *, root: str | Path, role: Mapping[str, Any] | None = None, prompt_only: bool = False,
        record: str | Path | None = None, timeout: int = 1800) -> dict[str, Any]:
    from paper_writing.registry import load_review_settings
    from paper_writing.review_launcher import run_role

    repo_root = Path(root).resolve()
    user_prompt, digest, metadata = packet(paper_id, repo_root)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = notes_dir(paper_id, repo_root) / "reader-check-runs"
    if prompt_only:
        base.mkdir(parents=True, exist_ok=True)
        path = base / f"{stamp}-prompt.md"
        path.write_text(f"{SYSTEM_PROMPT}\n\nJSON schema:\n{json.dumps(READER_SCHEMA)}\n\n{user_prompt}")
        return {"paper_id": paper_id, "prompt": str(path.relative_to(repo_root)), "main_text_sha256": digest,
                "next": "give this file to a fresh sub-agent with no other context, then file its JSON "
                        "answer with `reader-check --record ANSWER.json`"}
    if record is not None:
        answer = json.loads(Path(record).read_text(encoding="utf-8"))
        return save(paper_id, repo_root, metadata, digest, answer, reader={"model": "recorded sub-agent"},
                    receipt_dir=None)
    settings = load_review_settings(repo_root)
    chosen = reader_role(settings, role)
    workdir = base / stamp
    workdir.parent.mkdir(parents=True, exist_ok=True)
    answer, _receipt = run_role(role_name="reader_check", role=chosen, system_prompt=SYSTEM_PROMPT,
                                user_prompt=user_prompt, schema=READER_SCHEMA, workdir=workdir, timeout=timeout)
    return save(paper_id, repo_root, metadata, digest, answer, reader=chosen, receipt_dir=workdir)


def current_record(notes: Path, main_text_sha256: str | None = None) -> dict[str, Any] | None:
    """The saved reader check of a paper, marked whether it matches the current main text."""
    path = notes / "reader-check.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("answer"), Mapping):
        return None
    if main_text_sha256 is not None:
        data["matches_current_main_text"] = data.get("main_text_sha256") == main_text_sha256
    return data


def delivery_packet(source: str) -> str:
    """Extract only reader-visible opening, captions and conclusion from expanded TeX."""
    import re
    source = re.sub(r"(?<!\\)%[^\n]*", "", source)
    source = narrative_check._expand_macros(source, narrative_check._macros(source))
    regions = narrative_check.find_regions(source)
    source = source[:regions.body[1]]
    chunks = []
    title = re.search(r"\\title\s*(?:\[[^\]]*\]\s*)?\{", source)
    if title:
        chunks.append(source[title.end():narrative_check._balanced(source, title.end()-1)-1])
    if regions.abstract:
        chunks.append(source[slice(*regions.abstract)])
    from paper_writing.figure_standard import ENV, CAPTION
    for number, figure in enumerate(ENV.finditer(source), 1):
        caption = CAPTION.search(figure[2])
        if caption:
            end = narrative_check._balanced(figure[2], caption.end()-1)
            chunks.append(f"Figure {number}. " + figure[2][caption.end():end-1])
    sections = list(re.finditer(r"\\section\*?\s*\{([^}]+)\}", source))
    for index, match in enumerate(sections):
        if re.search("conclu|summary|closing", match[1], re.I):
            end = sections[index+1].start() if index+1 < len(sections) else len(source)
            chunks.append(source[match.end():end])
    return "\n\n".join(chunks)


def delivery_images(pre, run):
    """Select compiled main-text graphics in figure/panel order, excluding supplementary images."""
    from paper_writing.figure_standard import ENV, GRAPHIC
    from paper_writing.figures import review_images

    source = pre["expanded"]
    source = source[:narrative_check.find_regions(source).body[1]]
    files = pre.get("figure_files") or []
    ordered = []
    problems = []
    for number, figure in enumerate(ENV.finditer(source), 1):
        graphics = GRAPHIC.findall(figure[2])
        if not graphics:
            problems.append(f"Figure {number}: no standalone panel could be associated with the rendered figure.")
        for graphic in graphics:
            key = Path(graphic).with_suffix("").as_posix()
            matches = [item for item in files if
                       ("/" + Path(item["path"]).with_suffix("").as_posix()).endswith("/" + key)]
            if len(matches) == 1:
                ordered.append(matches[0])
            else:
                problems.append(f"Figure {number}: could not resolve panel {graphic} uniquely.")
    if not ordered:
        return [], problems
    result = review_images(Path(pre["manuscript_path"]), ordered, run / "reader-figures")
    if not result["images"]:
        problems.extend(result["notes"])
    return [Path(row["png"]) for row in result["images"]], problems


def delivery_read(source, images, role, workdir, timeout):
    from paper_writing.review_launcher import run_role

    points = ["question", "comparison", "answer", "meaning"]
    schema = {"type": "object", "additionalProperties": False, "required": points + ["repairs"],
              "properties": {**{key: _TEXT for key in points},
                             "repairs": {"type": "array", "items": _TEXT}}}
    recall, receipt = run_role(role_name="delivery_reader", role=role, workdir=workdir, timeout=timeout,
                    images=images, user_prompt=delivery_packet(source), schema=schema,
                    system_prompt="Read once. Retell the question, comparison, answer and meaning in your own "
                    "words. First read only figures and captions. State one result with its panel, comparator and uncertainty. Identify the supporting panel for each. If a point is missing, unsupported, "
                    "unintelligible or only an internal criterion, list the necessary repair. Otherwise "
                    "leave repairs empty. Do not propose experiments.")
    judgment, _ = run_role(role_name="recall_verifier", role=role, workdir=workdir.parent / "recall-verifier",
                           timeout=timeout, images=images,
                           schema={"type": "object", "additionalProperties": False, "required": ["misreadings"],
                                   "properties": {"misreadings": {"type": "array", "items": _TEXT}}},
                           system_prompt="Check the independent recall against the manuscript and figures. "
                           "List only material differences in comparison, direction, magnitude, conditions "
                           "or panel attribution. Each finding must cite both statements.",
                           user_prompt=json.dumps({"manuscript": source, "recall": recall}, ensure_ascii=False))
    recall["repairs"].extend(judgment["misreadings"])
    return recall, receipt

def review_story(paper_id, root):
    from paper_writing.registry import load_paper_metadata
    from paper_writing.review_flow import review_config
    from paper_writing.review_launcher import run_role

    root = root.resolve()
    load_paper_metadata(paper_id, root)
    notes = notes_dir(paper_id, root)
    story = (notes / "storyline.md").read_text()
    config = review_config(root)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    feedback, _ = run_role(role_name="story_editor", role=config["roles"]["editor"],
                           workdir=notes / "story-reviews" / stamp, timeout=config["timeout_seconds"],
                           system_prompt="Read this storyline once before drafting. State the intended reader, "
                           "decisive comparison and quantitative answer as you understand them. Identify the "
                           "panel that distinguishes the closest alternative and whose decision changes. Give one actionable edit.",
                           user_prompt=story, schema={"type": "object", "additionalProperties": False,
                           "required": ["reading", "advice"], "properties": {"reading": _TEXT, "advice": _TEXT}})
    return feedback
