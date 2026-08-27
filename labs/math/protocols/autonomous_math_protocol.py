#!/usr/bin/env python3
"""Validate only the durable/evidence envelope of autonomous mathematics work."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


LAB_ROOT = Path(__file__).resolve().parents[1]
FORMAL_SCRIPTS = LAB_ROOT / "tools" / "formal"
COMPUTATION_SCRIPTS = LAB_ROOT / "tools" / "computation"
sys.path.insert(0, str(FORMAL_SCRIPTS))
sys.path.insert(0, str(COMPUTATION_SCRIPTS))

from lean_runtime import (  # noqa: E402
    RECEIPT_SCHEMA as LEAN_RECEIPT_SCHEMA,
    check_receipt as check_lean_receipt,
)
from math_runtime import (  # noqa: E402
    RECEIPT_SCHEMA as COMPUTATION_RECEIPT_SCHEMA,
    check_receipt as check_computation_receipt,
)


STATE_SCHEMA = "openlabs.math_research_workspace.v1"
DYNAMIC_STATE_SCHEMA = "openlabs.project_workstream.v1"
INDEX_SCHEMA = "openlabs.project_research_index.v1"
MODES = {"free_exploration", "portfolio_review", "candidate_maturation"}
STATUSES = {"active", "paused", "completed"}


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected an object: {path}")
    return value


def _configured_states(project_path: Path, project: dict) -> set[Path]:
    return {
        (project_path.parent / str(item.get("state_path") or "")).resolve()
        for item in project.get("workstreams", [])
        if isinstance(item, dict) and str(item.get("state_path") or "").strip()
    }


def _validate_receipts(workstream_path: Path, state: dict, *, replay: bool) -> list[str]:
    raw_receipts = state.get("verification_receipts")
    if not isinstance(raw_receipts, list):
        return ["verification_receipts must be an array"]
    root = workstream_path.parent.resolve()
    errors: list[str] = []
    for index, item in enumerate(raw_receipts):
        if not isinstance(item, str) or not item.strip():
            errors.append(f"verification_receipts[{index}] must be a non-empty relative path")
            continue
        receipt = (root / item).resolve()
        if not receipt.is_relative_to(root) or not receipt.is_file():
            errors.append(f"verification_receipts[{index}] is missing or escapes the workstream")
            continue
        try:
            payload = _read(receipt)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{item}: invalid receipt: {exc}")
            continue
        relative = receipt.relative_to(root).as_posix()
        schema = payload.get("schema_version")
        if schema == LEAN_RECEIPT_SCHEMA:
            errors.extend(
                f"{item}: {error}"
                for error in check_lean_receipt(root, relative, replay=replay)
            )
        elif schema == COMPUTATION_RECEIPT_SCHEMA:
            errors.extend(
                f"{item}: {error}"
                for error in check_computation_receipt(root, relative, replay=replay)
            )
        else:
            errors.append(f"{item}: unregistered mathematics receipt schema {schema!r}")
    return errors


def validate(
    project_path: Path,
    workstream_path: Path,
    *,
    mode: str,
    expected_protocol_id: str = "autonomous-math",
) -> list[str]:
    errors: list[str] = []
    project = _read(project_path)
    state = _read(workstream_path)
    if project.get("schema_version") != "openlabs.project.v1":
        errors.append("unsupported project schema")
    if project.get("domain") != "math":
        errors.append("autonomous mathematics requires project domain math")
    protocol = project.get("protocol")
    if not isinstance(protocol, dict) or protocol.get("id") != expected_protocol_id:
        errors.append(f"project does not select {expected_protocol_id}")
    if state.get("schema_version") not in {STATE_SCHEMA, DYNAMIC_STATE_SCHEMA}:
        errors.append(
            f"workstream schema must be {STATE_SCHEMA} or {DYNAMIC_STATE_SCHEMA}"
        )
    if state.get("project_id") != project.get("project_id"):
        errors.append("workstream project_id differs from its project")
    workstream_id = state.get("workstream_id")
    if not isinstance(workstream_id, str) or not workstream_id.strip():
        errors.append("workstream_id must be a non-empty string")
    if state.get("mode") not in MODES:
        errors.append(f"workstream mode must be one of {sorted(MODES)}")
    if state.get("status") not in STATUSES:
        errors.append(f"workstream status must be one of {sorted(STATUSES)}")
    if not isinstance(state.get("research_log"), list):
        errors.append("research_log must be an array")

    declared = workstream_path.resolve() in _configured_states(project_path, project)
    portfolio = project.get("portfolio")
    dynamic_allowed = (
        isinstance(portfolio, dict)
        and portfolio.get("allow_dynamic_candidate_workstreams") is True
        and state.get("schema_version") == DYNAMIC_STATE_SCHEMA
        and state.get("mode") == "candidate_maturation"
        and isinstance(state.get("source_review_task_id"), str)
        and bool(state.get("source_review_task_id"))
    )
    if not declared and not dynamic_allowed:
        errors.append("workstream is neither declared nor an allowed reviewer-created candidate")

    research_index = project.get("research_index")
    if isinstance(research_index, dict) and str(research_index.get("path") or "").strip():
        index_path = (project_path.parent / str(research_index["path"])).resolve()
        try:
            index = _read(index_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"project research index is invalid: {exc}")
        else:
            if index.get("schema_version") != INDEX_SCHEMA:
                errors.append("project research index has an unsupported schema")
            if not isinstance(index.get("results"), list):
                errors.append("project research index results must be an array")

    errors.extend(_validate_receipts(workstream_path, state, replay=mode == "commit"))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--workstream", type=Path, required=True)
    parser.add_argument("--mode", choices=("discovery", "commit"), required=True)
    parser.add_argument("--protocol-id", default="autonomous-math")
    args = parser.parse_args()
    try:
        errors = validate(
            args.project.resolve(),
            args.workstream.resolve(),
            mode=args.mode,
            expected_protocol_id=args.protocol_id,
        )
    except Exception as exc:  # noqa: BLE001 - protocol errors must fail closed with detail.
        errors = [f"protocol validation failed: {exc}"]
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
