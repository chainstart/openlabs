#!/usr/bin/env python3
"""Validate the durable evidence envelope of an OpenLabs Quant workstream."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "tools"))

from trial_ledger import is_sha256, read_object, sha256_file, validate_ledger  # noqa: E402

STATE_SCHEMA = "openlabs.quant_research_workspace.v1"
DYNAMIC_STATE_SCHEMA = "openlabs.project_workstream.v1"
DATA_SCHEMA = "openlabs.quant_data_snapshot.v1"
RECEIPT_SCHEMA = "openlabs.quant_backtest_receipt.v1"
INDEX_SCHEMA = "openlabs.project_research_index.v1"
MODES = {
    "hypothesis_discovery",
    "portfolio_review",
    "candidate_maturation",
    "independent_replication",
}
STATUSES = {"active", "paused", "completed"}
TRIAL_STAGES = {"pilot", "validation", "confirmation"}


def _configured_states(project_path: Path, project: dict[str, Any]) -> set[Path]:
    return {
        (project_path.parent / str(item.get("state_path") or "")).resolve()
        for item in project.get("workstreams", [])
        if isinstance(item, dict) and str(item.get("state_path") or "").strip()
    }


def _resolve_relative(root: Path, raw: Any, field: str, errors: list[str]) -> Path | None:
    if not isinstance(raw, str) or not raw.strip() or Path(raw).is_absolute():
        errors.append(f"{field} must be a non-empty relative path")
        return None
    candidate = (root / raw).resolve()
    if not candidate.is_relative_to(root):
        errors.append(f"{field} escapes the workstream")
        return None
    if not candidate.is_file():
        errors.append(f"{field} is missing")
        return None
    return candidate


def _validate_data_manifest(payload: dict[str, Any], label: str) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != DATA_SCHEMA:
        errors.append(f"{label}: schema must be {DATA_SCHEMA}")
    for field in (
        "dataset_id",
        "provider",
        "source_url",
        "acquired_at_utc",
        "license_or_terms",
        "artifact_uri",
        "frequency",
        "universe_policy",
    ):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            errors.append(f"{label}: {field} must be a non-empty string")
    if isinstance(payload.get("source_url"), str):
        if urlparse(payload["source_url"]).scheme not in {"http", "https"}:
            errors.append(f"{label}: source_url must use http or https")
    if isinstance(payload.get("artifact_uri"), str):
        if urlparse(payload["artifact_uri"]).scheme not in {"file", "http", "https", "s3"}:
            errors.append(f"{label}: artifact_uri must have a registered URI scheme")
    if not is_sha256(payload.get("sha256")):
        errors.append(f"{label}: sha256 must be a lowercase SHA-256")
    time_range = payload.get("time_range")
    if not isinstance(time_range, dict) or any(
        not isinstance(time_range.get(field), str) or not time_range[field].strip()
        for field in ("start", "end")
    ):
        errors.append(f"{label}: time_range requires non-empty start and end")
    point_in_time = payload.get("point_in_time")
    if not isinstance(point_in_time, dict):
        errors.append(f"{label}: point_in_time must be an object")
    else:
        for field in ("available_at_field", "revisions_policy", "survivor_policy"):
            if not isinstance(point_in_time.get(field), str) or not point_in_time[field].strip():
                errors.append(f"{label}: point_in_time.{field} must be non-empty")
    return errors


def _validate_receipt(
    payload: dict[str, Any],
    label: str,
    *,
    root: Path,
    trials: dict[str, dict[str, Any]],
    replay: bool,
) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != RECEIPT_SCHEMA:
        errors.append(f"{label}: schema must be {RECEIPT_SCHEMA}")
    trial_id = payload.get("trial_id")
    if not isinstance(trial_id, str) or trial_id not in trials:
        errors.append(f"{label}: trial_id is not registered in the trial ledger")
        trial: dict[str, Any] = {}
    else:
        trial = trials[trial_id]
    stage = payload.get("stage")
    if stage not in TRIAL_STAGES:
        errors.append(f"{label}: stage must be one of {sorted(TRIAL_STAGES)}")
    if trial and stage != trial.get("stage"):
        errors.append(f"{label}: receipt stage differs from its registered trial")
    if payload.get("status") not in {"PASS", "FAIL", "INCONCLUSIVE"}:
        errors.append(f"{label}: status must be PASS, FAIL or INCONCLUSIVE")

    inputs = payload.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        errors.append(f"{label}: inputs must be a non-empty array")
    else:
        for index, item in enumerate(inputs):
            prefix = f"{label}: inputs[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{prefix} must be an object")
                continue
            resolved = _resolve_relative(root, item.get("path"), f"{prefix}.path", errors)
            if not is_sha256(item.get("sha256")):
                errors.append(f"{prefix}.sha256 must be a lowercase SHA-256")
            elif replay and resolved is not None and sha256_file(resolved) != item["sha256"]:
                errors.append(f"{prefix}.sha256 does not match the frozen input")

    execution = payload.get("execution")
    if not isinstance(execution, dict):
        errors.append(f"{label}: execution must be an object")
    else:
        if execution.get("costs_included") is not True:
            errors.append(f"{label}: execution.costs_included must be true")
        lag = execution.get("execution_lag_bars")
        if not isinstance(lag, int) or isinstance(lag, bool) or lag < 1:
            errors.append(f"{label}: execution.execution_lag_bars must be at least one")
        if not isinstance(execution.get("slippage_model"), str) or not execution[
            "slippage_model"
        ].strip():
            errors.append(f"{label}: execution.slippage_model must be non-empty")

    leakage = payload.get("leakage_checks")
    required_checks = {
        "lookahead_detected": False,
        "point_in_time_verified": True,
        "survivorship_controlled": True,
    }
    if not isinstance(leakage, dict):
        errors.append(f"{label}: leakage_checks must be an object")
    else:
        for field, expected in required_checks.items():
            if leakage.get(field) is not expected:
                errors.append(f"{label}: leakage_checks.{field} must be {str(expected).lower()}")

    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        errors.append(f"{label}: metrics must be an object")
    else:
        for field in ("gross_return", "net_return", "sharpe", "max_drawdown", "turnover"):
            value = metrics.get(field)
            invalid_number = not isinstance(value, (int, float)) or isinstance(value, bool)
            if value is not None and invalid_number:
                errors.append(f"{label}: metrics.{field} must be numeric or null")

    if stage == "confirmation":
        if payload.get("holdout_policy") != "untouched_once":
            errors.append(f"{label}: confirmation holdout_policy must be untouched_once")
        if not isinstance(payload.get("multiplicity_method"), str) or not payload[
            "multiplicity_method"
        ].strip():
            errors.append(f"{label}: confirmation multiplicity_method must be non-empty")
    return errors


def _validate_research_index(project_path: Path, project: dict[str, Any]) -> list[str]:
    research_index = project.get("research_index")
    if not isinstance(research_index, dict) or not str(research_index.get("path") or "").strip():
        return []
    try:
        index = read_object((project_path.parent / str(research_index["path"])).resolve())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"project research index is invalid: {exc}"]
    errors: list[str] = []
    if index.get("schema_version") != INDEX_SCHEMA:
        errors.append("project research index has an unsupported schema")
    if not isinstance(index.get("results"), list):
        errors.append("project research index results must be an array")
    return errors


def validate(project_path: Path, workstream_path: Path, *, mode: str) -> list[str]:
    project = read_object(project_path)
    state = read_object(workstream_path)
    errors: list[str] = []

    if project.get("schema_version") != "openlabs.project.v1":
        errors.append("unsupported project schema")
    if project.get("domain") != "quant":
        errors.append("autonomous quantitative finance requires project domain quant")
    protocol = project.get("protocol")
    if not isinstance(protocol, dict) or protocol.get("id") != "autonomous-quant":
        errors.append("project does not select autonomous-quant")
    if state.get("schema_version") not in {STATE_SCHEMA, DYNAMIC_STATE_SCHEMA}:
        errors.append(f"workstream schema must be {STATE_SCHEMA} or {DYNAMIC_STATE_SCHEMA}")
    if state.get("project_id") != project.get("project_id"):
        errors.append("workstream project_id differs from its project")
    workstream_id = state.get("workstream_id")
    if not isinstance(workstream_id, str) or not workstream_id.strip():
        errors.append("workstream_id must be a non-empty string")
        workstream_id = ""
    if state.get("mode") not in MODES:
        errors.append(f"workstream mode must be one of {sorted(MODES)}")
    if state.get("status") not in STATUSES:
        errors.append(f"workstream status must be one of {sorted(STATUSES)}")
    if not isinstance(state.get("research_question"), str) or not state[
        "research_question"
    ].strip():
        errors.append("research_question must be a non-empty string")
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

    root = workstream_path.parent.resolve()
    ledger_path = _resolve_relative(root, state.get("trial_ledger"), "trial_ledger", errors)
    trials: dict[str, dict[str, Any]] = {}
    if ledger_path is not None:
        try:
            ledger = read_object(ledger_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"trial_ledger is invalid: {exc}")
        else:
            errors.extend(
                f"trial_ledger: {error}"
                for error in validate_ledger(
                    ledger,
                    project_id=str(project.get("project_id") or ""),
                    workstream_id=workstream_id,
                )
            )
            trials = {
                item["trial_id"]: item
                for item in ledger.get("trials", [])
                if isinstance(item, dict) and isinstance(item.get("trial_id"), str)
            }

    data_manifests = state.get("data_manifests")
    if not isinstance(data_manifests, list) or not data_manifests:
        errors.append("data_manifests must be a non-empty array")
    else:
        dataset_ids: list[str] = []
        for index, raw in enumerate(data_manifests):
            label = f"data_manifests[{index}]"
            path = _resolve_relative(root, raw, label, errors)
            if path is None:
                continue
            try:
                manifest = read_object(path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"{label}: invalid manifest: {exc}")
                continue
            errors.extend(_validate_data_manifest(manifest, label))
            if isinstance(manifest.get("dataset_id"), str):
                dataset_ids.append(manifest["dataset_id"])
        if len(dataset_ids) != len(set(dataset_ids)):
            errors.append("data manifest dataset_id values must be unique")

    receipts = state.get("backtest_receipts")
    if not isinstance(receipts, list):
        errors.append("backtest_receipts must be an array")
    else:
        receipt_trials: list[str] = []
        for index, raw in enumerate(receipts):
            label = f"backtest_receipts[{index}]"
            path = _resolve_relative(root, raw, label, errors)
            if path is None:
                continue
            try:
                receipt = read_object(path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"{label}: invalid receipt: {exc}")
                continue
            errors.extend(
                _validate_receipt(
                    receipt,
                    label,
                    root=root,
                    trials=trials,
                    replay=mode == "commit",
                )
            )
            if isinstance(receipt.get("trial_id"), str):
                receipt_trials.append(receipt["trial_id"])
        if len(receipt_trials) != len(set(receipt_trials)):
            errors.append("only one canonical backtest receipt is allowed per trial")

        candidates = state.get("paper_candidates", [])
        if not isinstance(candidates, list):
            errors.append("paper_candidates must be an array")
        else:
            for index, candidate in enumerate(candidates):
                if not isinstance(candidate, dict):
                    errors.append(f"paper_candidates[{index}] must be an object")
                    continue
                trial_id = candidate.get("trial_id")
                if trial_id not in receipt_trials:
                    errors.append(
                        f"paper_candidates[{index}].trial_id must have a canonical receipt"
                    )
                if candidate.get("independent_audit") is not True:
                    errors.append(f"paper_candidates[{index}].independent_audit must be true")

    errors.extend(_validate_research_index(project_path, project))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--workstream", type=Path, required=True)
    parser.add_argument("--mode", choices=("discovery", "commit"), required=True)
    args = parser.parse_args()
    try:
        errors = validate(args.project.resolve(), args.workstream.resolve(), mode=args.mode)
    except Exception as exc:  # noqa: BLE001 - protocol failures must fail closed with detail.
        errors = [f"protocol validation failed: {exc}"]
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
