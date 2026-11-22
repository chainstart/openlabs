"""Blind writing comparison on one immutable evidence packet (python -m paper_writing.writing_trial)."""
import argparse
import hashlib
import json
from pathlib import Path
from secrets import SystemRandom

from .review_launcher import run_role


def fields(names):
    return {"type": "object", "additionalProperties": False, "required": names,
            "properties": {name: {"type": "string"} for name in names}}


POINTS = ["question", "comparison", "answer", "meaning"]
WEIGHTS = {"accurate": 1, "missing": 0, "misread": -1}


def call(slot, name, model, instruction, body, schema):
    provider, tool = ("anthropic", "Claude Code") if model.startswith("claude") else ("openai-codex", "Codex")
    return run_role(role_name=name, role={"model": model, "provider": provider, "tool": tool},
                    system_prompt=instruction, user_prompt=body, schema=schema, workdir=slot / name)[0]


def score_recall(slot, reader, packet, recall):
    schema = fields(POINTS + ["reasoning"])
    for point in POINTS:
        schema["properties"][point]["enum"] = list(WEIGHTS)
    judgment = call(slot, "scorer", reader, "Read the entire recall across field boundaries. For each of the "
                    "four points mark accurate, missing or misread. Missing means absent everywhere. Cite "
                    "the specific evidence and recalled wording for each mark in reasoning. Distinguish "
                    "a proposed panel citation from a scientific claim about its data.",
                    json.dumps({"evidence": packet, "recall": recall}), schema)
    marks = {point: judgment[point] for point in POINTS}
    return dict(marks=marks, reasoning=judgment["reasoning"], score=sum(WEIGHTS[v] for v in marks.values()))


def run(evidence, output, authors, reader):
    if len(set(authors)) < 2 or reader in authors:
        raise ValueError("Choose distinct writing candidates and an independent reader model")
    output.mkdir(parents=True, exist_ok=False)
    packet = "\n\n".join(p.name + "\n" + p.read_text() for p in evidence)
    (output / "evidence.txt").write_text(packet)
    authors = list(authors)
    SystemRandom().shuffle(authors)
    results = []
    for index, model in enumerate(authors):
        slot = output / str(index + 1)

        draft = call(slot, "author", model, "Write a journal opening and one results section. Order and describe "
                     "the figures the supplied evidence supports. Preserve the main comparison and limitations.",
                     packet, fields(["title", "abstract", "figure_sequence", "results"]))
        recall = call(slot, "reader", reader, "Retell each point and identify the supporting figure. Use only the draft.",
                      json.dumps(draft), fields(POINTS))
        results.append(dict(slot=index + 1, author=model, **score_recall(slot, reader, packet, recall)))
    summary = dict(evidence_sha256=hashlib.sha256(packet.encode()).hexdigest(), reader=reader, results=results)
    (output / "scores.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--author", action="append", required=True)
    parser.add_argument("--reader", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("evidence", nargs="+", type=Path)
    args = parser.parse_args()
    run(args.evidence, args.output.resolve(), args.author, args.reader)
