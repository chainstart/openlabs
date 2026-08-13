#!/usr/bin/env python3
"""Validate one generic OpenLabs project workstream using the AMRA math protocol."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


LAB_ROOT = Path(__file__).resolve().parents[1]
FORMAL_SCRIPTS = LAB_ROOT / "tools" / "formal"
COMPUTATION_SCRIPTS = LAB_ROOT / "tools" / "computation"
AMRA_SCRIPTS = LAB_ROOT / "skills" / "amra-research-loop" / "scripts"
PRODUCTION_SCRIPTS = LAB_ROOT / "skills" / "math-production-supervisor" / "scripts"
sys.path.insert(0, str(FORMAL_SCRIPTS))
sys.path.insert(0, str(COMPUTATION_SCRIPTS))
sys.path.insert(0, str(AMRA_SCRIPTS))
sys.path.insert(0, str(PRODUCTION_SCRIPTS))

from loop_core import validate_campaign_integrity  # noqa: E402
from lean_runtime import (  # noqa: E402
    RECEIPT_SCHEMA as LEAN_RECEIPT_SCHEMA,
    check_receipt as check_lean_receipt,
)
from math_runtime import (  # noqa: E402
    RECEIPT_SCHEMA as COMPUTATION_RECEIPT_SCHEMA,
    check_receipt as check_computation_receipt,
)
from production_lane import (  # noqa: E402
    _effective_node_policy,
    _research_budget_metrics,
    read_json,
    validate_lane,
    validate_plan,
)


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected an object: {path}")
    return value


def _validate_formalization(
    lane_root: Path,
    campaign: Path,
    *,
    mode: str,
) -> list[str]:
    """Bind a passed AMRA formalization claim to a replayed Lean receipt."""

    audit_path = campaign / "audit.json"
    if not audit_path.is_file():
        return []
    audit = _read(audit_path)
    formalization = audit.get("formalization_check")
    if not isinstance(formalization, dict) or formalization.get("status") != "passed":
        return []
    evidence = formalization.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return ["passed formalization has no Lean verification receipt"]
    receipts: list[Path] = []
    for item in evidence:
        if not isinstance(item, str) or not item.strip():
            continue
        candidate = (campaign / item).resolve()
        if not candidate.is_file() or not candidate.is_relative_to(lane_root):
            continue
        try:
            payload = _read(candidate)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if payload.get("schema_version") == LEAN_RECEIPT_SCHEMA:
            receipts.append(candidate)
    if not receipts:
        return ["passed formalization evidence contains no OpenLabs Lean v1 receipt"]
    errors: list[str] = []
    for receipt in receipts:
        relative = receipt.relative_to(lane_root).as_posix()
        errors.extend(
            f"{relative}: {item}"
            for item in check_lean_receipt(
                lane_root,
                relative,
                replay=mode == "commit",
            )
        )
    return errors


def _validate_computations(
    lane_root: Path,
    campaign: Path,
    *,
    mode: str,
) -> list[str]:
    """Replay every AMRA computation explicitly classified as passed."""

    audit_path = campaign / "audit.json"
    if not audit_path.is_file():
        return []
    audit = _read(audit_path)
    checks = audit.get("computation_checks")
    if checks is None:
        return []
    if not isinstance(checks, list):
        return ["computation_checks must be an array"]
    errors: list[str] = []
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            errors.append(f"computation_checks[{index}] must be an object")
            continue
        if check.get("status") != "passed":
            continue
        evidence = check.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append(f"passed computation_checks[{index}] has no receipt")
            continue
        receipts: list[Path] = []
        for item in evidence:
            if not isinstance(item, str) or not item.strip():
                continue
            candidate = (campaign / item).resolve()
            if not candidate.is_file() or not candidate.is_relative_to(lane_root):
                continue
            try:
                payload = _read(candidate)
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
            if payload.get("schema_version") == COMPUTATION_RECEIPT_SCHEMA:
                receipts.append(candidate)
        if not receipts:
            errors.append(
                f"passed computation_checks[{index}] contains no OpenLabs computation receipt"
            )
            continue
        for receipt in receipts:
            relative = receipt.relative_to(lane_root).as_posix()
            errors.extend(
                f"{relative}: {item}"
                for item in check_computation_receipt(
                    lane_root,
                    relative,
                    replay=mode == "commit",
                )
            )
    return errors


def validate(project_path: Path, workstream_path: Path, *, mode: str) -> list[str]:
    errors: list[str] = []
    project = _read(project_path)
    if project.get("schema_version") != "openlabs.project.v1":
        return ["unsupported project schema"]
    if project.get("domain") != "math":
        errors.append("AMRA math protocol requires project domain math")
    protocol = project.get("protocol")
    if not isinstance(protocol, dict) or protocol.get("id") != "amra-math":
        errors.append("project does not select the amra-math protocol")
    configured_states = {
        (project_path.parent / str(item.get("state_path") or "")).resolve()
        for item in project.get("workstreams", [])
        if isinstance(item, dict)
    }
    if workstream_path.resolve() not in configured_states:
        errors.append("workstream state is not declared by the project")

    domain_config = project.get("domain_config")
    plan_path = None
    if isinstance(domain_config, dict) and str(domain_config.get("path") or "").strip():
        plan_path = (project_path.parent / str(domain_config["path"])).resolve()
        errors.extend(f"plan: {item}" for item in validate_plan(plan_path))
    errors.extend(f"lane: {item}" for item in validate_lane(workstream_path))
    if errors:
        return errors

    lane = read_json(workstream_path)
    selected = lane.get("selected_target")
    if lane.get("stage") == "research" and isinstance(selected, dict):
        campaign = (workstream_path.parent / str(selected.get("amra_campaign") or "")).resolve()
        errors.extend(
            f"amra: {item}" for item in validate_campaign_integrity(campaign)
        )
        errors.extend(
            f"lean: {item}"
            for item in _validate_formalization(
                workstream_path.parent,
                campaign,
                mode=mode,
            )
        )
        errors.extend(
            f"computation: {item}"
            for item in _validate_computations(
                workstream_path.parent,
                campaign,
                mode=mode,
            )
        )
        if not errors and mode == "commit":
            state = _read(campaign / "campaign_state.json")
            budget = _research_budget_metrics(
                lane,
                _effective_node_policy(workstream_path, lane),
            )
            continuation = lane.get("continuation_gate")
            continuation_status = (
                continuation.get("status") if isinstance(continuation, dict) else None
            )
            if (
                budget["freeze_reasons"]
                and state.get("phase") not in {"frozen", "promotion", "independent_audit"}
                and continuation_status != "independent_audit_required"
            ):
                errors.append(
                    "research budget is exhausted but the AMRA target is neither frozen nor "
                    "waiting for independent audit: " + ", ".join(budget["freeze_reasons"])
                )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--workstream", type=Path, required=True)
    parser.add_argument("--mode", choices=("discovery", "commit"), required=True)
    args = parser.parse_args()
    try:
        errors = validate(
            args.project.resolve(),
            args.workstream.resolve(),
            mode=args.mode,
        )
    except Exception as exc:  # noqa: BLE001 - validator must fail closed with a reason.
        errors = [f"protocol validation failed: {exc}"]
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
