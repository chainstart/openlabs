"""Inactive discovery projects and an append-only, evidence-backed research ledger."""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile

LAB = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(LAB / "protocols"))
import research_state_machine as machine


def read(path):
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def strings(value, fields):
    if not isinstance(value, dict):
        raise ValueError("record must be a JSON object")
    for field in fields:
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise ValueError(f"{field} must be a nonempty string")


def card_valid(card):
    strings(card, ("source", "source_statement", "target_statement", "target_relation", "known_frontier", "remaining_gap", "success_criterion"))
    if card["target_relation"] not in {"exact", "specialization", "strengthening"}:
        raise ValueError("invalid target_relation")
    if card["target_relation"] == "exact" and card["source_statement"] != card["target_statement"]:
        raise ValueError("exact target differs from source statement")
    tests = card.get("boundary_tests")
    if not isinstance(tests, list) or not tests or not all(isinstance(x, str) and x.strip() for x in tests):
        raise ValueError("boundary_tests must be a nonempty string array")


def evidence_hash(root, name):
    if not isinstance(name, str) or Path(name).is_absolute() or ".." in Path(name).parts:
        raise ValueError("evidence must be workstream-relative")
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"missing or escaping evidence: {name}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def entry_valid(entry):
    strings(entry, ("id", "source_task_id", "mechanism", "new_evidence", "remaining_gap", "next_test"))
    if entry.get("disposition") not in {"continue", "blocked", "candidate", "refuted"}:
        raise ValueError("invalid disposition")
    if not isinstance(entry.get("losses"), list) or not all(isinstance(x, str) for x in entry["losses"]):
        raise ValueError("losses must be a string array")
    if not isinstance(entry.get("evidence"), list) or not entry["evidence"]:
        raise ValueError("evidence must be a nonempty array")
    usage = entry.get("usage", {})
    strings(usage, ("model", "reasoning_effort", "mode", "measurement_source"))
    for key in ("agent_seconds", "input_tokens", "output_tokens", "reasoning_tokens", "cost"):
        if key not in usage:
            raise ValueError(f"missing usage metric: {key}")
        value = usage[key]
        if value is None and key != "agent_seconds":
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"invalid usage metric: {key}")
        if key.endswith("tokens") and not isinstance(value, int):
            raise ValueError(f"{key} must be an integer or null")


def validate(ledger_path):
    path = Path(ledger_path)
    ledger = read(path)
    if ledger.get("schema_version") != "openlabs.math_discovery_ledger.v1":
        raise ValueError("unsupported ledger schema")
    strings(ledger, ("project_id", "workstream_id", "statement_sha256"))
    card = read(path.parent / "statement.json")
    card_valid(card)
    if digest(card) != ledger["statement_sha256"]:
        raise ValueError("frozen statement changed")
    if not isinstance(ledger.get("entries"), list):
        raise ValueError("entries must be an array")
    previous = ledger["statement_sha256"]
    ids = set()
    for entry in ledger["entries"]:
        entry_valid(entry)
        if entry["id"] in ids:
            raise ValueError("duplicate checkpoint id")
        ids.add(entry["id"])
        if entry.get("previous_sha256") != previous:
            raise ValueError("broken checkpoint chain")
        if entry.get("evidence_sha256") != {name: evidence_hash(path.parent, name) for name in entry["evidence"]}:
            raise ValueError("evidence changed")
        body = {key: value for key, value in entry.items() if key != "sha256"}
        if digest(body) != entry.get("sha256"):
            raise ValueError("checkpoint changed")
        previous = entry["sha256"]
    return ledger


def initialize(root, project_id, card):
    card_valid(card)
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}", project_id):
        raise ValueError("invalid project_id")
    root = Path(root)
    if not root.is_absolute():
        raise ValueError("root must be absolute")
    root.mkdir(parents=True, exist_ok=False)
    state = root / "workstreams/discovery/research_state.json"
    project = {"schema_version": "openlabs.project.v1", "project_id": project_id, "domain": "math", "status": "paused", "objective": card["target_statement"], "protocol": {"id": "math-discovery", "primary_skill": "722"}, "domain_config": {"path": "research_policy.json"}, "workstreams": [{"workstream_id": "discovery", "state_path": "workstreams/discovery/research_state.json", "startup": "paused"}]}
    write(root / "project.json", project)
    write(root / "research_policy.json", {"schema_version": "openlabs.math_research_policy_binding.v1", "policy": {"profile": "math-discovery-v1"}})
    write(state.parent / "statement.json", card)
    write(state.parent / "discovery-ledger.json", {"schema_version": "openlabs.math_discovery_ledger.v1", "project_id": project_id, "workstream_id": "discovery", "statement_sha256": digest(card), "entries": []})
    with contextlib.redirect_stdout(io.StringIO()):
        machine._init_command(argparse.Namespace(project=root / "project.json", workstream=state, workstream_id="discovery"))
    return project


def checkpoint(path, entry):
    path = Path(path)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ledger = validate(path)
        entry = dict(entry)
        entry_valid(entry)
        if any(old["id"] == entry["id"] for old in ledger["entries"]):
            raise ValueError("duplicate checkpoint id")
        if any(key in entry for key in ("sha256", "previous_sha256", "evidence_sha256")):
            raise ValueError("checkpoint hash fields are generated")
        entry["previous_sha256"] = ledger["entries"][-1]["sha256"] if ledger["entries"] else ledger["statement_sha256"]
        entry["evidence_sha256"] = {name: evidence_hash(path.parent, name) for name in entry["evidence"]}
        entry["sha256"] = digest(entry)
        ledger["entries"].append(entry)
        write(path, ledger)
    return entry


def status(path):
    ledger = validate(path)
    totals = {}
    for key in ("agent_seconds", "input_tokens", "output_tokens", "reasoning_tokens", "cost"):
        values = [entry["usage"][key] for entry in ledger["entries"]]
        totals[key] = None if any(value is None for value in values) else sum(values)
    return {"project_id": ledger["project_id"], "checkpoints": len(ledger["entries"]), "usage": totals}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--root", type=Path, required=True)
    init.add_argument("--project-id", required=True)
    init.add_argument("--statement", type=Path, required=True)
    append = commands.add_parser("checkpoint")
    append.add_argument("--ledger", type=Path, required=True)
    append.add_argument("--entry", type=Path, required=True)
    show = commands.add_parser("status")
    show.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "init":
            result = initialize(args.root, args.project_id, read(args.statement))
        elif args.command == "checkpoint":
            result = checkpoint(args.ledger, read(args.entry))
        else:
            result = status(args.ledger)
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, machine.StateMachineError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
