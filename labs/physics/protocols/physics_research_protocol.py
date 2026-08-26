#!/usr/bin/env python3
"""Validate the durable evidence envelope of an OpenLabs Physics workstream."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

STATE_SCHEMA = "openlabs.physics_research_workspace.v1"
DATA_SCHEMA = "openlabs.physics_dataset.v1"
COMPUTATION_SCHEMA = "openlabs.physics_computation.v1"
MODES = {
    "problem_selection",
    "hypothesis_discovery",
    "candidate_maturation",
    "independent_replication",
}
STATUSES = {"active", "paused", "completed"}
CLAIM_STATUSES = {"conjecture", "provisional", "supported", "verified", "refuted"}
EVIDENCE_KINDS = {
    "analytic_derivation",
    "symbolic_computation",
    "numerical_computation",
    "public_experimental_data",
    "public_observational_data",
    "independent_replication",
    "counterexample",
}
SHA256 = re.compile(r"[0-9a-f]{64}")


def read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _configured_states(project_path: Path, project: dict[str, Any]) -> set[Path]:
    return {
        (project_path.parent / str(item.get("state_path") or "")).resolve()
        for item in project.get("workstreams", [])
        if isinstance(item, dict) and _text(item.get("state_path"))
    }


def _relative_file(root: Path, raw: Any, field: str, errors: list[str]) -> Path | None:
    if not _text(raw) or Path(str(raw)).is_absolute():
        errors.append(f"{field} must be a non-empty relative path")
        return None
    candidate = (root / str(raw)).resolve()
    if not candidate.is_relative_to(root):
        errors.append(f"{field} escapes the workstream")
        return None
    if not candidate.is_file():
        errors.append(f"{field} is missing")
        return None
    return candidate


def _verify_record(
    value: Any,
    *,
    label: str,
    root: Path,
    replay: bool,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return [f"{label} must be an object"]
    path = _relative_file(root, value.get("path"), f"{label}.path", errors)
    digest = value.get("sha256")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        errors.append(f"{label}.sha256 must be lowercase SHA-256")
    elif replay and path is not None and sha256_file(path) != digest:
        errors.append(f"{label}.sha256 does not match the file")
    size = value.get("bytes")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        errors.append(f"{label}.bytes must be a non-negative integer")
    elif replay and path is not None and path.stat().st_size != size:
        errors.append(f"{label}.bytes does not match the file")
    return errors


def _artifact_file(payload: dict[str, Any]) -> Path | None:
    if _text(payload.get("artifact_uri")):
        parsed = urlparse(str(payload["artifact_uri"]))
        if parsed.scheme == "file":
            return Path(unquote(parsed.path)).resolve()
    return None


def _validate_data(payload: dict[str, Any], *, label: str, root: Path, replay: bool) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != DATA_SCHEMA:
        errors.append(f"{label}: schema must be {DATA_SCHEMA}")
    for field in (
        "dataset_id",
        "provider",
        "source_url",
        "acquired_at_utc",
        "license_or_terms",
        "citation",
    ):
        if not _text(payload.get(field)):
            errors.append(f"{label}: {field} must be a non-empty string")
    if _text(payload.get("source_url")) and urlparse(str(payload["source_url"])).scheme not in {
        "http",
        "https",
    }:
        errors.append(f"{label}: source_url must use http or https")
    if payload.get("access_scope") not in {"public", "public_with_terms"}:
        errors.append(f"{label}: access_scope must be public or public_with_terms")
    if payload.get("raw_immutable") is not True:
        errors.append(f"{label}: raw_immutable must be true")
    digest = payload.get("sha256")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        errors.append(f"{label}: sha256 must be lowercase SHA-256")
    size = payload.get("bytes")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        errors.append(f"{label}: bytes must be a non-negative integer")

    artifact: Path | None = None
    if _text(payload.get("artifact_path")):
        artifact = _relative_file(root, payload["artifact_path"], f"{label}: artifact_path", errors)
    elif _text(payload.get("artifact_uri")):
        parsed = urlparse(str(payload["artifact_uri"]))
        if parsed.scheme not in {"file", "http", "https"}:
            errors.append(f"{label}: artifact_uri must use file, http or https")
        artifact = _artifact_file(payload)
        if replay and parsed.scheme == "file" and (artifact is None or not artifact.is_file()):
            errors.append(f"{label}: file artifact_uri is missing")
    else:
        errors.append(f"{label}: artifact_path or artifact_uri is required")
    if replay and artifact is not None and artifact.is_file() and isinstance(digest, str):
        if sha256_file(artifact) != digest:
            errors.append(f"{label}: sha256 does not match the raw artifact")
        if isinstance(size, int) and artifact.stat().st_size != size:
            errors.append(f"{label}: bytes does not match the raw artifact")
    return errors


def _validate_computation(
    payload: dict[str, Any], *, label: str, root: Path, replay: bool
) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != COMPUTATION_SCHEMA:
        errors.append(f"{label}: schema must be {COMPUTATION_SCHEMA}")
    for field in ("receipt_id", "recorded_at_utc", "precision"):
        if not _text(payload.get(field)):
            errors.append(f"{label}: {field} must be a non-empty string")
    command = payload.get("command")
    if not isinstance(command, list) or not command or any(not _text(item) for item in command):
        errors.append(f"{label}: command must be a non-empty string array")
    errors.extend(
        _verify_record(payload.get("code"), label=f"{label}: code", root=root, replay=replay)
    )
    errors.extend(
        _verify_record(
            payload.get("environment_lock"),
            label=f"{label}: environment_lock",
            root=root,
            replay=replay,
        )
    )
    for field in ("inputs", "outputs"):
        records = payload.get(field)
        if not isinstance(records, list) or (field == "outputs" and not records):
            qualifier = "a non-empty" if field == "outputs" else "an"
            errors.append(f"{label}: {field} must be {qualifier} array")
            continue
        for index, record in enumerate(records):
            errors.extend(
                _verify_record(
                    record,
                    label=f"{label}: {field}[{index}]",
                    root=root,
                    replay=replay,
                )
            )
    controls = payload.get("numerical_controls")
    if not isinstance(controls, dict):
        errors.append(f"{label}: numerical_controls must be an object")
    else:
        if controls.get("dimensional_analysis") is not True:
            errors.append(f"{label}: numerical_controls.dimensional_analysis must be true")
        for field in ("convergence", "uncertainty_budget"):
            if not _text(controls.get(field)):
                errors.append(f"{label}: numerical_controls.{field} must be non-empty")
    if payload.get("status") not in {"PASS", "FAIL", "INCONCLUSIVE"}:
        errors.append(f"{label}: status must be PASS, FAIL or INCONCLUSIVE")
    return errors


def _validate_claims(state: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    evidence = state.get("evidence_routes")
    if not isinstance(evidence, list):
        return ["evidence_routes must be an array"]
    evidence_by_id: dict[str, dict[str, Any]] = {}
    for index, route in enumerate(evidence):
        label = f"evidence_routes[{index}]"
        if not isinstance(route, dict):
            errors.append(f"{label} must be an object")
            continue
        evidence_id = route.get("evidence_id")
        if not _text(evidence_id) or evidence_id in evidence_by_id:
            errors.append(f"{label}.evidence_id must be non-empty and unique")
            continue
        evidence_by_id[str(evidence_id)] = route
        if route.get("kind") not in EVIDENCE_KINDS:
            errors.append(f"{label}.kind must be one of {sorted(EVIDENCE_KINDS)}")
        if not _text(route.get("independence_group")):
            errors.append(f"{label}.independence_group must be non-empty")
        if not _text(route.get("artifact")):
            errors.append(f"{label}.artifact must be non-empty")

    claims = state.get("claims")
    if not isinstance(claims, list):
        return errors + ["claims must be an array"]
    claim_ids: set[str] = set()
    verified: set[str] = set()
    for index, claim in enumerate(claims):
        label = f"claims[{index}]"
        if not isinstance(claim, dict):
            errors.append(f"{label} must be an object")
            continue
        claim_id = claim.get("claim_id")
        if not _text(claim_id) or claim_id in claim_ids:
            errors.append(f"{label}.claim_id must be non-empty and unique")
            continue
        claim_ids.add(str(claim_id))
        status = claim.get("status")
        if status not in CLAIM_STATUSES:
            errors.append(f"{label}.status must be one of {sorted(CLAIM_STATUSES)}")
        if not _text(claim.get("statement")):
            errors.append(f"{label}.statement must be non-empty")
        ids = claim.get("evidence_ids")
        if not isinstance(ids, list) or any(item not in evidence_by_id for item in ids):
            errors.append(f"{label}.evidence_ids must reference registered evidence routes")
            ids = []
        required = 2 if status == "verified" else 1 if status in {"supported", "refuted"} else 0
        groups = {
            str(evidence_by_id[item].get("independence_group"))
            for item in ids
            if item in evidence_by_id
        }
        if len(groups) < required:
            errors.append(f"{label}: {status} requires {required} independent evidence route(s)")
        if status == "verified":
            verified.add(str(claim_id))
    candidates = state.get("paper_candidates")
    if not isinstance(candidates, list) or any(item not in verified for item in candidates):
        errors.append("paper_candidates must be an array containing only verified claim IDs")
    return errors


def validate(project_path: Path, workstream_path: Path, *, mode: str) -> list[str]:
    project = read_object(project_path)
    state = read_object(workstream_path)
    errors: list[str] = []
    if project.get("schema_version") != "openlabs.project.v1":
        errors.append("unsupported project schema")
    if project.get("domain") != "physics":
        errors.append("autonomous physics requires project domain physics")
    protocol = project.get("protocol")
    if not isinstance(protocol, dict) or protocol.get("id") != "autonomous-physics":
        errors.append("project does not select autonomous-physics")
    if state.get("schema_version") != STATE_SCHEMA:
        errors.append(f"workstream schema must be {STATE_SCHEMA}")
    if state.get("project_id") != project.get("project_id"):
        errors.append("workstream project_id differs from its project")
    if workstream_path.resolve() not in _configured_states(project_path, project):
        errors.append("workstream is not declared by the project")
    if not _text(state.get("workstream_id")):
        errors.append("workstream_id must be a non-empty string")
    if state.get("mode") not in MODES:
        errors.append(f"workstream mode must be one of {sorted(MODES)}")
    if state.get("status") not in STATUSES:
        errors.append(f"workstream status must be one of {sorted(STATUSES)}")
    if not _text(state.get("research_question")):
        errors.append("research_question must be a non-empty string")
    for field in ("assumptions", "failed_routes", "research_log"):
        if not isinstance(state.get(field), list):
            errors.append(f"{field} must be an array")
    if not isinstance(state.get("conventions"), dict):
        errors.append("conventions must be an object")
    prior_art = state.get("prior_art")
    if not isinstance(prior_art, dict):
        errors.append("prior_art must be an object")
    else:
        for field in ("checked_at_utc", "closest_work", "open_status"):
            if not _text(prior_art.get(field)):
                errors.append(f"prior_art.{field} must be non-empty")
        if prior_art.get("open_status") not in {"current_open", "uncertain", "not_open"}:
            errors.append("prior_art.open_status must be current_open, uncertain or not_open")

    root = workstream_path.parent.resolve()
    replay = mode == "commit"
    for field, validator in (
        ("data_manifests", _validate_data),
        ("computation_receipts", _validate_computation),
    ):
        paths = state.get(field)
        if not isinstance(paths, list):
            errors.append(f"{field} must be an array")
            continue
        for index, raw in enumerate(paths):
            path = _relative_file(root, raw, f"{field}[{index}]", errors)
            if path is None:
                continue
            try:
                payload = read_object(path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"{field}[{index}] is invalid: {exc}")
                continue
            errors.extend(validator(payload, label=f"{field}[{index}]", root=root, replay=replay))
    errors.extend(_validate_claims(state))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--workstream", type=Path, required=True)
    parser.add_argument("--mode", choices=("discovery", "commit"), required=True)
    args = parser.parse_args()
    try:
        errors = validate(args.project.resolve(), args.workstream.resolve(), mode=args.mode)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors = [str(exc)]
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
