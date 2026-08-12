#!/usr/bin/env python3
"""Validate and atomically update an adaptive mathematics production lane."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PLAN_SCHEMA = "openlabs.math_production_plan.v1"
LANE_SCHEMA = "openlabs.math_production_lane.v1"
STAGES = {"radar", "research", "terminal"}
NODE_OUTCOMES = {"progress", "no_progress", "promotion", "freeze"}
SELECTION_MODES = {"radar_scored", "operator_locked_route"}
EPISTEMIC_DELTAS = {
    "blocker_reduced",
    "mechanism_killed",
    "survivor_strengthened",
    "promotion_gate_advanced",
}
SCORE_MAXIMA = {
    "novelty": 25,
    "significance": 25,
    "closure": 20,
    "auditability": 15,
    "generality": 10,
    "venue_fit": 5,
}


class StateError(RuntimeError):
    """Raised when a plan or lane violates its contract."""


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StateError(f"missing file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise StateError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise StateError(f"expected an object in {path}")
    return value


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def validate_plan(path: Path) -> list[str]:
    plan = read_json(path)
    errors: list[str] = []
    if plan.get("schema_version") != PLAN_SCHEMA:
        errors.append("unsupported plan schema_version")
    for field in ("plan_id", "status", "objective"):
        if not _text(plan.get(field)):
            errors.append(f"plan {field} is required")
    for field in (
        "autonomy",
        "scheduler",
        "portfolio",
        "selection_gate",
        "paper_shadow_gate",
        "observation_policy",
    ):
        if not isinstance(plan.get(field), dict):
            errors.append(f"plan {field} must be an object")
    program = plan.get("program")
    if program is not None:
        if not isinstance(program, dict):
            errors.append("plan program must be an object")
        else:
            north_star = program.get("north_star")
            if not isinstance(north_star, dict):
                errors.append("program north_star must be an object")
            else:
                for field in ("statement", "source", "public_status"):
                    if not _text(north_star.get(field)):
                        errors.append(f"program north_star {field} is required")
            for field in (
                "research_fronts",
                "invalid_progress",
                "seed_maturation",
                "summary_policy",
                "north_star_claim_gate",
            ):
                expected = list if field in {"research_fronts", "invalid_progress"} else dict
                if not isinstance(program.get(field), expected):
                    errors.append(f"program {field} must be a {expected.__name__}")
    lanes = plan.get("lanes")
    if not isinstance(lanes, list) or not lanes:
        errors.append("plan lanes must be a nonempty list")
        return errors
    seen: set[str] = set()
    active_lanes = 0
    for index, item in enumerate(lanes):
        if not isinstance(item, dict):
            errors.append(f"lane entry {index} must be an object")
            continue
        lane_id = item.get("lane_id")
        lane_path = item.get("config_path")
        if not _text(lane_id) or not _text(lane_path):
            errors.append(f"lane entry {index} needs lane_id and config_path")
            continue
        startup = item.get("startup", "active")
        if startup not in {"active", "paused"}:
            errors.append(f"lane entry {index} has unknown startup state: {startup}")
        elif startup == "active":
            active_lanes += 1
        priority = item.get("priority", 0)
        if not isinstance(priority, int) or isinstance(priority, bool):
            errors.append(f"lane entry {index} priority must be an integer")
        if lane_id in seen:
            errors.append(f"duplicate lane_id: {lane_id}")
        seen.add(str(lane_id))
        resolved = (path.parent / str(lane_path)).resolve()
        if not resolved.is_file():
            errors.append(f"missing lane config: {resolved}")
            continue
        lane_errors = validate_lane(resolved, expected_plan_id=str(plan.get("plan_id") or ""))
        errors.extend(f"{lane_id}: {error}" for error in lane_errors)
    portfolio = plan.get("portfolio")
    maximum_lanes = (
        portfolio.get("maximum_research_lanes")
        if isinstance(portfolio, dict)
        else None
    )
    if not _positive_int(maximum_lanes):
        errors.append("portfolio maximum_research_lanes must be a positive integer")
    elif active_lanes > int(maximum_lanes):
        errors.append(
            f"active lanes {active_lanes} exceed maximum_research_lanes {maximum_lanes}"
        )
    return errors


def validate_lane(path: Path, *, expected_plan_id: str | None = None) -> list[str]:
    lane = read_json(path)
    errors: list[str] = []
    if lane.get("schema_version") != LANE_SCHEMA:
        errors.append("unsupported lane schema_version")
    for field in ("plan_id", "lane_id", "plan_path"):
        if not _text(lane.get(field)):
            errors.append(f"lane {field} is required")
    if expected_plan_id and lane.get("plan_id") != expected_plan_id:
        errors.append("lane plan_id does not match the production plan")
    if lane.get("stage") not in STAGES:
        errors.append(f"unknown lane stage: {lane.get('stage')}")
    selection_mode = lane.get("selection_mode", "radar_scored")
    if selection_mode not in SELECTION_MODES:
        errors.append(f"unknown lane selection_mode: {selection_mode}")
    if not _positive_int(lane.get("cycle")):
        errors.append("lane cycle must be a positive integer")
    if not isinstance(lane.get("theme"), dict):
        errors.append("lane theme must be an object")
    for field in ("selection_gate", "node_policy"):
        if not isinstance(lane.get(field), dict):
            errors.append(f"lane {field} must be an object")
    for field in ("archived_targets", "nodes", "history"):
        if not isinstance(lane.get(field), list):
            errors.append(f"lane {field} must be a list")
    program_id = lane.get("program_id")
    if program_id is not None:
        if not _text(program_id):
            errors.append("lane program_id must be nonempty text")
        for field in ("program_summary", "paper_seed_registry"):
            value = lane.get(field)
            if not _text(value):
                errors.append(f"lane {field} is required for a flagship program")
                continue
            resolved = (path.parent / str(value)).resolve()
            if not resolved.is_file():
                errors.append(f"lane {field} does not exist: {resolved}")
    selected = lane.get("selected_target")
    if lane.get("stage") == "research":
        if not isinstance(selected, dict):
            errors.append("research stage requires selected_target")
        elif not _text(selected.get("amra_campaign")):
            errors.append("selected_target needs amra_campaign")
        elif (
            selection_mode == "operator_locked_route"
            and selected.get("selection_basis") != "operator_locked_route"
            and selected.get("selection_basis") != "post_result_route_branch"
        ):
            errors.append("operator-locked research needs a route selection_basis")
    if selection_mode == "operator_locked_route" and not isinstance(lane.get("route"), dict):
        errors.append("operator-locked lane requires a route object")
    plan_path = lane.get("plan_path")
    if _text(plan_path):
        resolved_plan = (path.parent / str(plan_path)).resolve()
        if not resolved_plan.is_file():
            errors.append(f"lane plan_path does not exist: {resolved_plan}")
    return errors


def _score_payload(args: argparse.Namespace) -> dict[str, int]:
    scores = {name: int(getattr(args, name)) for name in SCORE_MAXIMA}
    for name, maximum in SCORE_MAXIMA.items():
        if not 0 <= scores[name] <= maximum:
            raise StateError(f"{name} score must be between 0 and {maximum}")
    scores["total"] = sum(scores.values())
    return scores


def _check_selection_gate(lane: dict[str, Any], scores: dict[str, int]) -> None:
    gate = lane.get("selection_gate", {})
    for key in ("total", "novelty", "significance", "closure"):
        minimum = gate.get(f"minimum_{key}")
        if not isinstance(minimum, int):
            raise StateError(f"selection gate minimum_{key} must be an integer")
        if scores[key] < minimum:
            raise StateError(f"selection failed: {key} {scores[key]} < {minimum}")


def select_target(args: argparse.Namespace) -> dict[str, Any]:
    lane_path = args.lane.resolve()
    lane = read_json(lane_path)
    errors = validate_lane(lane_path)
    if errors:
        raise StateError("; ".join(errors))
    if lane["stage"] != "radar" or lane.get("selected_target") is not None:
        raise StateError("target selection requires an empty radar-stage lane")
    if lane.get("selection_mode", "radar_scored") != "radar_scored":
        raise StateError("score-based select is forbidden for an operator-locked route")
    if args.blocking_novelty_risk:
        raise StateError("a target with blocking novelty risk cannot be selected")
    scores = _score_payload(args)
    _check_selection_gate(lane, scores)

    amra_scripts = Path(__file__).resolve().parents[1].parent / "amra-research-loop" / "scripts"
    sys.path.insert(0, str(amra_scripts))
    from loop_core import CampaignError, init_campaign  # type: ignore[import-not-found]

    research_root = lane_path.parent / "research" / f"cycle-{int(lane['cycle']):03d}"
    try:
        campaign = init_campaign(
            research_root,
            campaign_id=args.target_id,
            problem_id=args.problem_id,
            title=args.title,
            exact_statement=args.statement,
            source=args.source,
        )
    except CampaignError as exc:
        raise StateError(str(exc)) from exc

    now = utc_now()
    lane["stage"] = "research"
    lane["selected_target"] = {
        "target_id": args.target_id,
        "problem_id": args.problem_id,
        "title": args.title,
        "exact_statement": args.statement,
        "source": args.source,
        "first_kill_test": args.first_kill_test,
        "scores": scores,
        "selected_at": now,
        "amra_campaign": campaign.relative_to(lane_path.parent).as_posix(),
    }
    lane.setdefault("history", []).append(
        {"at": now, "event": "target_selected", "target_id": args.target_id, "scores": scores}
    )
    atomic_write_json(lane_path, lane)
    return lane["selected_target"]


def lock_route(args: argparse.Namespace) -> dict[str, Any]:
    """Initialize an administrator-chosen research route without candidate scoring."""

    lane_path = args.lane.resolve()
    lane = read_json(lane_path)
    errors = validate_lane(lane_path)
    if errors:
        raise StateError("; ".join(errors))
    if lane.get("selection_mode") != "operator_locked_route":
        raise StateError("lock-route requires selection_mode=operator_locked_route")
    if lane["stage"] != "radar" or lane.get("selected_target") is not None:
        raise StateError("lock-route requires an empty initialization-stage lane")

    amra_scripts = Path(__file__).resolve().parents[1].parent / "amra-research-loop" / "scripts"
    sys.path.insert(0, str(amra_scripts))
    from loop_core import CampaignError, init_campaign  # type: ignore[import-not-found]

    research_root = lane_path.parent / "research" / f"cycle-{int(lane['cycle']):03d}"
    try:
        campaign = init_campaign(
            research_root,
            campaign_id=args.target_id,
            problem_id=args.problem_id,
            title=args.title,
            exact_statement=args.statement,
            source=args.source,
        )
    except CampaignError as exc:
        raise StateError(str(exc)) from exc

    now = utc_now()
    lane["stage"] = "research"
    lane["selected_target"] = {
        "target_id": args.target_id,
        "problem_id": args.problem_id,
        "title": args.title,
        "exact_statement": args.statement,
        "source": args.source,
        "route_frontier": args.frontier,
        "first_kill_test": args.first_kill_test,
        "selection_basis": "operator_locked_route",
        "selected_at": now,
        "amra_campaign": campaign.relative_to(lane_path.parent).as_posix(),
    }
    lane.setdefault("history", []).append(
        {
            "at": now,
            "event": "operator_route_locked",
            "target_id": args.target_id,
            "candidate_scoring": "not_performed",
        }
    )
    lane["updated_at"] = now
    atomic_write_json(lane_path, lane)
    return lane["selected_target"]


def record_node(args: argparse.Namespace) -> dict[str, Any]:
    lane_path = args.lane.resolve()
    lane = read_json(lane_path)
    errors = validate_lane(lane_path)
    if errors:
        raise StateError("; ".join(errors))
    if lane["stage"] == "terminal":
        raise StateError("cannot record work on a terminal lane")
    if lane["stage"] == "radar" and lane.get("selected_target") is None:
        if args.outcome != "no_progress":
            raise StateError("an unselected radar pass can only be recorded as no_progress")
    if args.outcome == "progress":
        if args.delta_kind not in EPISTEMIC_DELTAS:
            raise StateError(
                "progress requires an epistemic delta-kind: "
                + ", ".join(sorted(EPISTEMIC_DELTAS))
            )
        if not args.evidence:
            raise StateError("progress requires at least one evidence path")
    now = utc_now()
    entry = {
        "at": now,
        "cycle": lane["cycle"],
        "outcome": args.outcome,
        "delta_kind": args.delta_kind,
        "summary": args.summary,
        "evidence": list(args.evidence or []),
    }
    lane.setdefault("nodes", []).append(entry)
    consecutive = 0
    for node in reversed(lane["nodes"]):
        if node.get("cycle") != lane["cycle"] or node.get("outcome") != "no_progress":
            break
        consecutive += 1
    limit = int(lane.get("node_policy", {}).get("consecutive_no_progress_limit", 3))
    radar_nodes = sum(
        1
        for node in lane["nodes"]
        if node.get("cycle") == lane["cycle"] and node.get("stage", "radar") == "radar"
    ) if lane["stage"] == "radar" else 0
    radar_limit = int(lane.get("node_policy", {}).get("max_radar_nodes_per_cycle", 3))
    radar_exhausted = lane["stage"] == "radar" and radar_nodes >= radar_limit
    if radar_exhausted:
        lane["stage"] = "terminal"
        lane.setdefault("history", []).append(
            {
                "at": now,
                "event": "radar_exhausted_without_selection",
                "cycle": lane["cycle"],
                "radar_nodes": radar_nodes,
            }
        )
    lane["consecutive_no_progress"] = consecutive
    lane["updated_at"] = now
    atomic_write_json(lane_path, lane)
    return {
        "node": entry,
        "consecutive_no_progress": consecutive,
        "limit": limit,
        "freeze_required": consecutive >= limit,
        "radar_nodes": radar_nodes,
        "radar_limit": radar_limit,
        "radar_exhausted": radar_exhausted,
        "stage": lane["stage"],
    }


def branch_route(args: argparse.Namespace) -> dict[str, Any]:
    """Start a new evidence-driven target inside an already locked route."""

    lane_path = args.lane.resolve()
    lane = read_json(lane_path)
    errors = validate_lane(lane_path)
    if errors:
        raise StateError("; ".join(errors))
    if lane.get("selection_mode") != "operator_locked_route":
        raise StateError("branch-route requires an operator-locked route")
    selected = lane.get("selected_target")
    if not isinstance(selected, dict):
        raise StateError("branch-route requires a current selected target")
    amra_path = (lane_path.parent / str(selected["amra_campaign"])).resolve()
    state = read_json(amra_path / "campaign_state.json")
    if state.get("phase") not in {"frozen", "promotion"}:
        raise StateError("finish, freeze, or promote the current AMRA target before branching")

    amra_scripts = Path(__file__).resolve().parents[1].parent / "amra-research-loop" / "scripts"
    sys.path.insert(0, str(amra_scripts))
    from loop_core import CampaignError, init_campaign  # type: ignore[import-not-found]

    now = utc_now()
    archived = dict(selected)
    archived.update(
        {
            "terminal_phase": state["phase"],
            "branched_at": now,
            "branch_reason": args.reason,
        }
    )
    lane.setdefault("archived_targets", []).append(archived)
    lane["cycle"] = int(lane["cycle"]) + 1
    research_root = lane_path.parent / "research" / f"cycle-{int(lane['cycle']):03d}"
    try:
        campaign = init_campaign(
            research_root,
            campaign_id=args.target_id,
            problem_id=args.problem_id,
            title=args.title,
            exact_statement=args.statement,
            source=args.source,
        )
    except CampaignError as exc:
        raise StateError(str(exc)) from exc
    lane["stage"] = "research"
    lane["consecutive_no_progress"] = 0
    lane["selected_target"] = {
        "target_id": args.target_id,
        "problem_id": args.problem_id,
        "title": args.title,
        "exact_statement": args.statement,
        "source": args.source,
        "route_frontier": lane.get("route", {}).get("frontier", ""),
        "first_kill_test": args.first_kill_test,
        "selection_basis": "post_result_route_branch",
        "selected_at": now,
        "amra_campaign": campaign.relative_to(lane_path.parent).as_posix(),
    }
    lane["updated_at"] = now
    lane.setdefault("history", []).append(
        {
            "at": now,
            "event": "post_result_route_branch_started",
            "target_id": args.target_id,
            "reason": args.reason,
            "candidate_scoring": "not_performed",
        }
    )
    atomic_write_json(lane_path, lane)
    return lane["selected_target"]


def recycle_lane(args: argparse.Namespace) -> dict[str, Any]:
    lane_path = args.lane.resolve()
    lane = read_json(lane_path)
    errors = validate_lane(lane_path)
    if errors:
        raise StateError("; ".join(errors))
    if lane.get("selection_mode", "radar_scored") == "operator_locked_route":
        raise StateError(
            "operator-locked routes cannot recycle into candidate radar; "
            "start a post-result branch inside the same route"
        )
    selected = lane.get("selected_target")
    if not isinstance(selected, dict):
        raise StateError("cannot recycle a lane without a selected target")
    amra_path = (lane_path.parent / str(selected["amra_campaign"])).resolve()
    state = read_json(amra_path / "campaign_state.json")
    if state.get("phase") not in {"frozen", "promotion"}:
        raise StateError("freeze or promote the AMRA campaign before recycling the lane")
    now = utc_now()
    archived = dict(selected)
    archived.update({"terminal_phase": state["phase"], "recycled_at": now, "reason": args.reason})
    lane.setdefault("archived_targets", []).append(archived)
    lane["selected_target"] = None
    lane["stage"] = "radar"
    lane["cycle"] = int(lane["cycle"]) + 1
    lane["consecutive_no_progress"] = 0
    lane["updated_at"] = now
    lane.setdefault("history", []).append(
        {"at": now, "event": "lane_recycled", "reason": args.reason, "next_cycle": lane["cycle"]}
    )
    atomic_write_json(lane_path, lane)
    return {"stage": lane["stage"], "cycle": lane["cycle"], "archived_target": archived}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate")
    validate.add_argument("--plan", type=Path)
    validate.add_argument("--lane", type=Path)

    status = commands.add_parser("status")
    status.add_argument("--lane", type=Path, required=True)

    select = commands.add_parser("select")
    select.add_argument("--lane", type=Path, required=True)
    select.add_argument("--target-id", required=True)
    select.add_argument("--problem-id", required=True)
    select.add_argument("--title", required=True)
    select.add_argument("--statement", required=True)
    select.add_argument("--source", required=True)
    select.add_argument("--first-kill-test", required=True)
    for name in SCORE_MAXIMA:
        select.add_argument(f"--{name.replace('_', '-')}", dest=name, type=int, required=True)
    select.add_argument("--blocking-novelty-risk", action="store_true")

    lock = commands.add_parser("lock-route")
    lock.add_argument("--lane", type=Path, required=True)
    lock.add_argument("--target-id", required=True)
    lock.add_argument("--problem-id", required=True)
    lock.add_argument("--title", required=True)
    lock.add_argument("--statement", required=True)
    lock.add_argument("--source", required=True)
    lock.add_argument("--frontier", required=True)
    lock.add_argument("--first-kill-test", required=True)

    branch = commands.add_parser("branch-route")
    branch.add_argument("--lane", type=Path, required=True)
    branch.add_argument("--target-id", required=True)
    branch.add_argument("--problem-id", required=True)
    branch.add_argument("--title", required=True)
    branch.add_argument("--statement", required=True)
    branch.add_argument("--source", required=True)
    branch.add_argument("--first-kill-test", required=True)
    branch.add_argument("--reason", required=True)

    record = commands.add_parser("record-node")
    record.add_argument("--lane", type=Path, required=True)
    record.add_argument("--outcome", choices=sorted(NODE_OUTCOMES), required=True)
    record.add_argument("--delta-kind", default="none")
    record.add_argument("--summary", required=True)
    record.add_argument("--evidence", action="append", default=[])

    recycle = commands.add_parser("recycle")
    recycle.add_argument("--lane", type=Path, required=True)
    recycle.add_argument("--reason", required=True)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "validate":
            if bool(args.plan) == bool(args.lane):
                raise StateError("provide exactly one of --plan or --lane")
            errors = validate_plan(args.plan.resolve()) if args.plan else validate_lane(args.lane.resolve())
            payload = {"valid": not errors, "errors": errors}
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 1 if errors else 0
        if args.command == "status":
            lane = read_json(args.lane.resolve())
            errors = validate_lane(args.lane.resolve())
            print(json.dumps({"valid": not errors, "errors": errors, "lane": lane}, ensure_ascii=False, indent=2))
            return 1 if errors else 0
        if args.command == "select":
            payload = select_target(args)
        elif args.command == "lock-route":
            payload = lock_route(args)
        elif args.command == "branch-route":
            payload = branch_route(args)
        elif args.command == "record-node":
            payload = record_node(args)
        elif args.command == "recycle":
            payload = recycle_lane(args)
        else:  # pragma: no cover
            raise AssertionError(args.command)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except StateError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
