"""Protocol validator for research-program projects (``program: true``).

Shared by every lab that registers the ``research-program`` protocol. It checks
the envelope only: which workstreams a program project may contain and that a
research campaign carries the admission record it was created from. It never
judges a topic or a result.

A program project has exactly two kinds of declared (static) workstreams:

* ``scout``     -- researcher, ``continuation: on_demand``; proposes topic cards;
* ``admission`` -- reviewer, ``continuation: review_on_new_results`` with
  ``spawn_candidate_workstreams``; the admission gate.

Research campaigns are dynamic: they exist only because the admission gate
admitted a topic, so a research state must name its ``topic_id`` and carry the
hash-bound pre-registered primary endpoint.

Stdlib only; prints ``{"valid": bool, "errors": [...]}`` and exits 1 on errors.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

PROTOCOL_ID = "research-program"
STATE_SCHEMA = "openlabs.research_program_state.v1"
ENDPOINT_FIELDS = ("metric", "matched_baseline", "split", "decision_rule", "stop_rule")
CONTROL_STATUSES = {"active", "paused", "completed"}
RESEARCH_STATUSES = {"active", "paused", "completed", "failed", "needs_replan"}
TIERS = {"routine", "escalation"}


def canonical_sha256(value) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _control_errors(role: str, declared: dict, state: dict) -> list[str]:
    errors: list[str] = []
    if declared.get("workstream_id") != state.get("workstream_id"):
        errors.append("workstream identity mismatch")
    continuation = declared.get("continuation") or "continuous"
    agent_role = declared.get("agent_role") or "researcher"
    if role == "scout" and (continuation != "on_demand" or agent_role != "researcher"):
        errors.append("the scout workstream must be a researcher with continuation on_demand")
    if role == "admission" and (
        continuation != "review_on_new_results"
        or agent_role != "reviewer"
        or declared.get("spawn_candidate_workstreams") is not True
    ):
        errors.append(
            "the admission workstream must be a reviewer with continuation "
            "review_on_new_results and spawn_candidate_workstreams"
        )
    if state.get("status") not in CONTROL_STATUSES:
        errors.append("invalid program workstream status")
    return errors


def _research_errors(state: dict) -> list[str]:
    errors: list[str] = []
    for name in ("workstream_id", "topic_id", "admission_task_id"):
        if not _text(state.get(name)):
            errors.append(f"research state needs {name}")
    if state.get("target_tier") not in TIERS:
        errors.append("research state target_tier must be routine or escalation")
    fallback = state.get("routine_fallback")
    if not isinstance(fallback, list) or not fallback:
        errors.append("research state needs the routine_fallback venues")
    if not isinstance(state.get("cost_budget"), dict):
        errors.append("research state needs cost_budget")
    preregistration = state.get("preregistration")
    if not isinstance(preregistration, dict):
        errors.append("research state needs the preregistration block")
    else:
        endpoint = preregistration.get("primary_endpoint")
        if not isinstance(endpoint, dict) or any(
            not _text(endpoint.get(name)) for name in ENDPOINT_FIELDS
        ):
            errors.append("preregistration.primary_endpoint is incomplete")
        elif preregistration.get("sha256") != canonical_sha256(endpoint):
            errors.append("preregistration.sha256 does not match the primary endpoint")
    if state.get("status") not in RESEARCH_STATUSES:
        errors.append("invalid research status")
    return errors


def validate(project_path: Path, workstream_path: Path, mode: str) -> list[str]:
    if mode not in {"discovery", "commit"}:
        return ["unknown validation mode"]
    project_path = project_path.resolve()
    workstream_path = workstream_path.resolve()
    root = project_path.parent
    project = json.loads(project_path.read_text(encoding="utf-8"))
    state = json.loads(workstream_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if project.get("schema_version") != "openlabs.project.v1":
        errors.append("openlabs.project.v1 required")
    if project.get("program") is not True:
        errors.append("the research-program protocol requires program: true")
    protocol = project.get("protocol") if isinstance(project.get("protocol"), dict) else {}
    if protocol.get("id") != PROTOCOL_ID:
        errors.append(f"project protocol id must be {PROTOCOL_ID}")
    if not isinstance(state, dict):
        return errors + ["workstream state must be an object"]
    if state.get("schema_version") != STATE_SCHEMA:
        errors.append(f"workstream state schema must be {STATE_SCHEMA}")
    if not project.get("project_id") or state.get("project_id") != project.get("project_id"):
        errors.append("project identity mismatch")
    declared: dict[Path, dict] = {}
    for item in project.get("workstreams") or []:
        if isinstance(item, dict) and _text(item.get("state_path")):
            declared[(root / item["state_path"]).resolve()] = item
    role = state.get("program_role")
    if role in {"scout", "admission"}:
        entry = declared.get(workstream_path)
        if entry is None:
            errors.append("program control workstreams must be declared in the project")
        else:
            errors.extend(_control_errors(role, entry, state))
    elif role == "research":
        if workstream_path in declared:
            errors.append(
                "program projects create research campaigns only through the admission gate"
            )
        errors.extend(_research_errors(state))
    else:
        errors.append("program_role must be scout, admission or research")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--workstream", type=Path, required=True)
    parser.add_argument("--mode", choices=["discovery", "commit"], required=True)
    args = parser.parse_args()
    try:
        errors = validate(args.project, args.workstream, args.mode)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        errors = [str(exc)]
    print(json.dumps({"valid": not errors, "errors": errors}))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
