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


def call(slot, name, model, instruction, body, schema, *, images=None):
    provider, tool = ("anthropic", "Claude Code") if model.startswith("claude") else ("openai-codex", "Codex")
    return run_role(role_name=name, role={"model": model, "provider": provider, "tool": tool},
                    system_prompt=instruction, user_prompt=body, schema=schema, workdir=slot / name,
                    images=images)[0]


def score_recall(slot, reader, packet, recall, *, historical=False, **attachments):
    schema = fields(POINTS + ["reasoning"])
    for point in POINTS:
        schema["properties"][point]["enum"] = list(WEIGHTS)
    criterion = (" Grade fidelity to the supplied historical reader-facing excerpt. A faithful "
                 "recall of a scientifically flawed claim is accurate here. Mark misread only "
                 "when the recall contradicts the excerpt or adds an incorrect claim. "
                 "Mark a detail unavailable in the excerpt as missing." if historical else "")
    judgment = call(slot, "scorer", reader, "Read the entire recall across field boundaries. For each of the "
                    "four points mark accurate, missing or misread. Missing means absent everywhere. Cite "
                    "the specific evidence and recalled wording for each mark in reasoning. Distinguish "
                    "a proposed panel citation from a scientific claim about its data." + criterion,
                    json.dumps({"evidence": packet, "recall": recall}), schema, **attachments)
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


def calibrate(cases, output, scientist, reader):
    """Replay curated historical excerpts with an offline answer key."""
    if scientist == reader:
        raise ValueError("Choose independent science and reader models")
    output.mkdir(parents=True, exist_ok=False)
    cases = list(cases)
    SystemRandom().shuffle(cases)
    results = []
    for index, case in enumerate(cases, 1):
        slot = output / str(index)
        # Only these curated excerpts go to a seat. Keep source IDs and labels in the key.
        draft = {key: case["draft"][key] for key in
                 ("title", "abstract", "results", "figures")}
        evidence = case["evidence"]
        images = [Path(path) for path in case.get("figure_images", [])]
        attachments = {"images": images} if images else {}
        schema = fields(["verdict", "reasoning"])
        schema["properties"]["verdict"]["enum"] = ["pass", "return"]
        science = call(slot, "science", scientist,
                       "Judge scientific validity only. Return a claim unsupported by the "
                       "evidence. Pass scientifically valid claims even if prose or figures need edits.",
                       json.dumps({"draft": draft, "evidence": evidence}), schema, **attachments)
        reader_excerpt = json.dumps({key: value for key, value in draft.items() if key != "results"})
        recall = call(slot, "reader", reader,
                      "Retell the question, comparison, answer and meaning. Identify the "
                      "figure supporting the comparison and its magnitude.",
                      reader_excerpt, fields(POINTS), **attachments)
        score = score_recall(slot, scientist, reader_excerpt, recall, historical=True, **attachments)
        expected = case["expected_science"]
        results.append({"id": case["id"], "expected_science": expected, "science": science,
                        "recall": recall, "reader": score})
    summary = {
        "cases": len(results),
        "expected_returns": sum(row["expected_science"] == "return" for row in results),
        "expected_passes": sum(row["expected_science"] == "pass" for row in results),
        "science_false_pass": sum(row["expected_science"] == "return" and
                                  row["science"]["verdict"] == "pass" for row in results),
        "science_false_return": sum(row["expected_science"] == "pass" and
                                    row["science"]["verdict"] == "return" for row in results),
        "reader_misread_cases": sum("misread" in row["reader"]["marks"].values() for row in results),
        "reader_misread_points": sum(list(row["reader"]["marks"].values()).count("misread")
                                     for row in results),
        "reader_missing_points": sum(list(row["reader"]["marks"].values()).count("missing")
                                     for row in results),
        "results": results,
    }
    (output / "scores.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="Calibration JSON is a list of cases with id, expected_science (pass or "
               "return), blinded evidence, draft (title, abstract, results, figures), and optional "
               "figure_images (PNG/JPEG paths). "
               "Strip names, affiliations, identifying metadata and old decisions from excerpts."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--author", action="append")
    mode.add_argument("--calibration", type=Path)
    parser.add_argument("--scientist")
    parser.add_argument("--reader", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("evidence", nargs="*", type=Path)
    args = parser.parse_args()
    if args.calibration:
        if not args.scientist or args.evidence:
            parser.error("--calibration requires --scientist and takes evidence from the case file")
        calibrate(json.loads(args.calibration.read_text()), args.output.resolve(),
                  args.scientist, args.reader)
    else:
        if not args.evidence or args.scientist:
            parser.error("Writing comparison requires evidence files and uses --author")
        run(args.evidence, args.output.resolve(), args.author, args.reader)
