#!/usr/bin/env python3
"""Validate and derive an objective OpenLabs physics problem verdict."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SCHEMA = "openlabs.physics_problem_resolution.v1"
OPEN_VERDICT = "open"
ROUTE_VERDICTS = {
    "solved_positive",
    "solved_negative",
    "superseded",
    "not_well_posed",
}
PROBLEM_VERDICTS = {OPEN_VERDICT, *ROUTE_VERDICTS}
CRITERION_STATUSES = {"met", "not_met", "inconclusive", "blocked"}
ROUND_STATUSES = {"not_started", "in_progress", "completed", "blocked"}
TASK_STATUSES = {
    "not_started",
    "queued",
    "running",
    "succeeded",
    "needs_replan",
    "needs_human",
    "quarantined",
    "cancelled",
}


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _criteria(
    value: Any,
    *,
    label: str,
    errors: list[str],
    evidence_root: Path | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        errors.append(f"{label} must be a non-empty array")
        return []
    parsed: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for index, item in enumerate(value):
        item_label = f"{label}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_label} must be an object")
            continue
        identifier = item.get("criterion_id")
        if not _text(identifier) or str(identifier) in identifiers:
            errors.append(f"{item_label}.criterion_id must be non-empty and unique within its list")
        else:
            identifiers.add(str(identifier))
        if not _text(item.get("statement")):
            errors.append(f"{item_label}.statement must be non-empty")
        status = item.get("status")
        if status not in CRITERION_STATUSES:
            errors.append(f"{item_label}.status must be one of {sorted(CRITERION_STATUSES)}")
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or any(not _text(record) for record in evidence):
            errors.append(f"{item_label}.evidence must be a string array")
        elif status == "met" and not evidence:
            errors.append(f"{item_label}.evidence must not be empty when status is met")
        if isinstance(evidence, list) and evidence_root is not None:
            for evidence_index, record in enumerate(evidence):
                if not _text(record):
                    continue
                relative = Path(str(record))
                candidate = (evidence_root / relative).resolve()
                if relative.is_absolute() or not candidate.is_relative_to(evidence_root.resolve()):
                    errors.append(
                        f"{item_label}.evidence[{evidence_index}] must stay inside the workstream"
                    )
                elif not candidate.is_file():
                    errors.append(f"{item_label}.evidence[{evidence_index}] is missing")
        parsed.append(item)
    return parsed


def derive_problem_verdict(
    payload: dict[str, Any],
    *,
    evidence_root: Path | None = None,
) -> tuple[str, list[str]]:
    """Return the only verdict justified by completed resolution routes."""

    errors: list[str] = []
    routes = payload.get("resolution_routes")
    if not isinstance(routes, list) or not routes:
        return OPEN_VERDICT, ["resolution_routes must be a non-empty array"]
    completed: list[tuple[str, str]] = []
    route_ids: set[str] = set()
    for index, route in enumerate(routes):
        label = f"resolution_routes[{index}]"
        if not isinstance(route, dict):
            errors.append(f"{label} must be an object")
            continue
        route_id = route.get("route_id")
        if not _text(route_id) or str(route_id) in route_ids:
            errors.append(f"{label}.route_id must be non-empty and unique")
        else:
            route_ids.add(str(route_id))
        verdict = route.get("verdict_if_complete")
        if verdict not in ROUTE_VERDICTS:
            errors.append(f"{label}.verdict_if_complete must be one of {sorted(ROUTE_VERDICTS)}")
        criteria = _criteria(
            route.get("criteria"),
            label=f"{label}.criteria",
            errors=errors,
            evidence_root=evidence_root,
        )
        if criteria and all(item.get("status") == "met" for item in criteria):
            completed.append((str(route_id), str(verdict)))
    completed_verdicts = {verdict for _, verdict in completed}
    if len(completed_verdicts) > 1:
        details = ", ".join(f"{route_id}:{verdict}" for route_id, verdict in completed)
        errors.append(f"conflicting completed resolution routes: {details}")
        return OPEN_VERDICT, errors
    if completed:
        return completed[0][1], errors
    return OPEN_VERDICT, errors


def validate_resolution(payload: Any, *, evidence_root: Path | None = None) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["resolution decision must be an object"]
    if payload.get("schema_version") != SCHEMA:
        errors.append(f"schema_version must be {SCHEMA}")
    for field in ("decision_id", "problem_id", "as_of_utc", "rationale"):
        if not _text(payload.get(field)):
            errors.append(f"{field} must be a non-empty string")
    scope = payload.get("scope")
    if not isinstance(scope, dict):
        errors.append("scope must be an object")
    else:
        for field in ("question_version", "current_question", "historical_prompt_status"):
            if not _text(scope.get(field)):
                errors.append(f"scope.{field} must be a non-empty string")

    declared = payload.get("problem_verdict")
    if declared not in PROBLEM_VERDICTS:
        errors.append(f"problem_verdict must be one of {sorted(PROBLEM_VERDICTS)}")
    derived, route_errors = derive_problem_verdict(payload, evidence_root=evidence_root)
    errors.extend(route_errors)
    if declared in PROBLEM_VERDICTS and declared != derived:
        errors.append(
            f"problem_verdict {declared!r} disagrees with machine-derived verdict {derived!r}"
        )

    latest_round = payload.get("latest_round")
    if not isinstance(latest_round, dict):
        errors.append("latest_round must be an object")
    else:
        for field in ("round_id", "task_id", "summary"):
            if not _text(latest_round.get(field)):
                errors.append(f"latest_round.{field} must be a non-empty string")
        if latest_round.get("task_status") not in TASK_STATUSES:
            errors.append(f"latest_round.task_status must be one of {sorted(TASK_STATUSES)}")
        round_status = latest_round.get("round_status")
        if round_status not in ROUND_STATUSES:
            errors.append(f"latest_round.round_status must be one of {sorted(ROUND_STATUSES)}")
        rule = latest_round.get("completion_rule")
        if rule not in {"all", "any"}:
            errors.append("latest_round.completion_rule must be all or any")
        criteria = _criteria(
            latest_round.get("criteria"),
            label="latest_round.criteria",
            errors=errors,
            evidence_root=evidence_root,
        )
        met = [item.get("status") == "met" for item in criteria]
        complete = bool(met) and (all(met) if rule == "all" else any(met))
        if round_status == "completed" and not complete:
            errors.append("latest_round is completed but its completion rule is not satisfied")
        if round_status == "blocked" and not any(
            item.get("status") == "blocked" for item in criteria
        ):
            errors.append("latest_round is blocked but no round criterion is blocked")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("decision", type=Path)
    args = parser.parse_args()
    try:
        payload = json.loads(args.decision.read_text(encoding="utf-8"))
        errors = validate_resolution(payload, evidence_root=args.decision.parent.resolve())
        derived = (
            derive_problem_verdict(payload, evidence_root=args.decision.parent.resolve())[0]
            if isinstance(payload, dict)
            else OPEN_VERDICT
        )
    except (OSError, json.JSONDecodeError) as exc:
        errors = [str(exc)]
        derived = OPEN_VERDICT
    print(
        json.dumps(
            {"valid": not errors, "derived_problem_verdict": derived, "errors": errors},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
