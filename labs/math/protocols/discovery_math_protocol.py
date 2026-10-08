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


def review_target_errors(project, state, root):
    """Bind an optional project-owned review stage to its exact frozen candidate."""
    errors = []
    try:
        targets = project.get("discovery_review_targets", {})
        if not isinstance(targets, dict):
            raise ValueError("discovery_review_targets must be an object")
        for stage, target in targets.items():
            if isinstance(target, dict) and "from_observation_kind" in target:
                candidates = [o for o in state.get("observations", [])
                              if o.get("kind") == target["from_observation_kind"]]
                if not candidates:
                    if state.get("stage") == stage:
                        raise ValueError("review stage has no frozen current candidate")
                    continue
                latest = candidates[-1]
                paths = [p for p in latest.get("evidence", [])
                         if p.endswith("review-input-manifest.json")]
                if len(paths) != 1:
                    raise ValueError("candidate observation requires one review input manifest")
                current_hash = discovery.evidence_hash(root, paths[0])
                current = discovery.read(root / paths[0])
                if current.get("creator_task_id") != latest.get("source_task_id"):
                    raise ValueError("review manifest does not belong to the current candidate creator")
                target = {**target, "manifest_path": paths[0], "manifest_sha256": current_hash,
                          "candidate_id": current.get("candidate_id")}
            discovery.strings(target, ("manifest_path", "manifest_sha256", "candidate_id"))
            if not isinstance(target.get("outcomes"), dict):
                raise ValueError("review target outcomes must be an object")
            manifest_path = target["manifest_path"]
            manifest_hash = discovery.evidence_hash(root, manifest_path)
            if manifest_hash != target["manifest_sha256"]:
                raise ValueError(f"review manifest changed for stage {stage}")
            manifest = discovery.read(root / manifest_path)
            if manifest.get("candidate_id") != target["candidate_id"]:
                raise ValueError(f"review candidate identity mismatch for stage {stage}")
            for observation in state.get("observations", []):
                if observation.get("stage") != stage:
                    continue
                verdict = target["outcomes"].get(observation.get("kind"))
                if verdict is None:
                    continue
                if observation.get("actor_role") != "reviewer":
                    raise ValueError("bound reconstruction requires a reviewer")
                matched = False
                for name in observation.get("evidence", []):
                    discovery.evidence_hash(root, name)
                    if not name.endswith(".json"):
                        continue
                    report = json.loads((root / name).read_text())
                    if (isinstance(report, dict)
                        and report.get("schema_version") == "openlabs.math_discovery_review.v1"
                        and report.get("candidate_id") == target["candidate_id"]
                        and report.get("manifest_sha256") == manifest_hash
                        and report.get("task_id") == observation.get("source_task_id")
                        and report.get("verdict") == verdict
                        and report.get("source_problem_resolved") is False):
                        matched = True
                if not matched:
                    raise ValueError("reconstruction lacks a verdict bound to the current candidate and task")
    except (ValueError, KeyError, TypeError, OSError) as exc:
        errors.append(str(exc))
    return errors


def ledger_errors(args):
    try:
        project, policy, _, _ = machine._load_policy(args.project)
        state = discovery.read(args.workstream)
        if project.get("protocol", {}).get("id") != "math-discovery" or policy["policy_id"] != "math-discovery-v1":
            raise ValueError("discovery protocol requires math-discovery-v1")
        ledger = discovery.validate(args.workstream.parent / "discovery-ledger.json")
        if ledger["project_id"] != project["project_id"] or ledger["workstream_id"] != state["workstream_id"]:
            raise ValueError("ledger identity does not match project/workstream")
        bound_errors = review_target_errors(project, state, args.workstream.parent)
        if bound_errors:
            raise ValueError("; ".join(bound_errors))
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
