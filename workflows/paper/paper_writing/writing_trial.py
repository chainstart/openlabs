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


def run(evidence, output, authors, reader):
    output.mkdir(parents=True, exist_ok=False)
    packet = "\n\n".join(p.name + "\n" + p.read_text() for p in evidence)
    (output / "evidence.txt").write_text(packet)
    authors = list(authors)
    SystemRandom().shuffle(authors)
    results = []
    for index, model in enumerate(authors):
        slot = output / str(index + 1)

        def call(name, model_id, instruction, body, schema):
            role = {"provider": "anthropic" if model_id.startswith("claude") else "openai-codex", "tool": "Claude Code" if model_id.startswith("claude") else "Codex", "model": model_id}
            return run_role(role_name=name, role=role, system_prompt=instruction, user_prompt=body,
                            schema=schema, workdir=slot / name)[0]

        draft = call("author", model, "Write a journal opening and one results section. Order and describe "
                     "the figures the supplied evidence supports. Preserve the main comparison and limitations.",
                     packet, fields(["title", "abstract", "figure_sequence", "results"]))
        points = ["question", "comparison", "answer", "meaning"]
        recall = call("reader", reader, "Retell each point and identify the supporting figure. Use only the draft.",
                      json.dumps(draft), fields(points))
        schema = fields(points)
        schema["properties"] = {p: {"type": "string", "enum": ["accurate", "missing", "misread"]} for p in points}
        marks = call("scorer", reader, "Compare each recalled point to the evidence, checking direction, magnitude "
                     "and conditions. Mark unsupported inferences misread.", packet + "\n" + json.dumps(recall), schema)
        results.append(dict(slot=index + 1, author=model, marks=marks,
                            score=sum({"accurate": 1, "missing": 0, "misread": -1}[v] for v in marks.values())))
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
