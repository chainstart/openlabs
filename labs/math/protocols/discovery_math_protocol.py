"""Discovery policy adapter: existing routing plus authenticated durable checkpoints."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import sys

import research_state_machine as machine

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/722/scripts"))
import discovery


def ledger_errors(args):
    try:
        project, policy, _, _ = machine._load_policy(args.project)
        state = discovery.read(args.workstream)
        if project.get("protocol", {}).get("id") != "math-discovery" or policy["policy_id"] != "math-discovery-v1":
            raise ValueError("discovery protocol requires math-discovery-v1")
        ledger = discovery.validate(args.workstream.parent / "discovery-ledger.json")
        if ledger["project_id"] != project["project_id"] or ledger["workstream_id"] != state["workstream_id"]:
            raise ValueError("ledger identity does not match project/workstream")
        context = machine._validation_context() if args.mode == "commit" else None
        if context:
            canonical_path = Path(context["canonical"]["workstream_state"])
            old = discovery.validate(canonical_path.parent / "discovery-ledger.json")
            if {key: value for key, value in ledger.items() if key != "entries"} != {key: value for key, value in old.items() if key != "entries"}:
                raise ValueError("attempt rewrote frozen ledger identity or statement")
            count = len(old["entries"])
            if ledger["entries"][:count] != old["entries"] or len(ledger["entries"]) < count:
                raise ValueError("attempt rewrote checkpoint history")
            new = ledger["entries"][count:]
            if not new or any(entry["source_task_id"] != context["task"]["task_id"] for entry in new):
                raise ValueError("commit requires new checkpoints bound to the current task_id")
        return []
    except (ValueError, OSError, KeyError, TypeError, machine.StateMachineError) as exc:
        return [str(exc)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "decide"))
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--workstream", type=Path, required=True)
    parser.add_argument("--mode", choices=("discovery", "commit"), default="discovery")
    args = parser.parse_args()
    args.project = args.project.resolve()
    args.workstream = args.workstream.resolve()
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output):
            machine._validate_command(args)
        result = json.loads(output.getvalue())
        result["errors"].extend(ledger_errors(args))
        result["valid"] = not result["errors"]
        if args.command == "validate" or not result["valid"]:
            print(json.dumps(result))
            return 0 if result["valid"] else 1
        return machine._decision_command(args)
    except (ValueError, OSError, TypeError, machine.StateMachineError) as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
