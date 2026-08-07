"""Versioned file contracts shared by the control plane and isolated labs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

TASK_SCHEMA = "openlabs.task.v2"
RESULT_SCHEMA = "openlabs.result_bundle.v1"
RECEIPT_SCHEMA = "openlabs.result_receipt.v2"
IDENTIFIER = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
RESULT_STATUSES = {
    "completed",
    "succeeded",
    "failed",
    "needs_replan",
    "needs_human",
    "quarantined",
}
AGENT_ROLES = {"researcher", "experimenter", "writer", "reviewer"}
SESSION_MODES = {"resume", "fresh"}


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


def canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write_json(path: str | Path, payload: Any) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return target


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _identifier(value: Any, label: str, errors: list[str]) -> str:
    text = _text(value)
    if not text or not IDENTIFIER.fullmatch(text):
        errors.append(f"{label} must match {IDENTIFIER.pattern}")
    return text


def safe_relative_path(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(value.strip()) and not path.is_absolute() and ".." not in path.parts


def validate_task(payload: Any) -> ValidationResult:
    if not isinstance(payload, Mapping):
        return ValidationResult(False, ("task must be a JSON object",))
    errors: list[str] = []
    warnings: list[str] = []
    if payload.get("schema_version") != TASK_SCHEMA:
        errors.append(f"schema_version must be {TASK_SCHEMA}")
    _identifier(payload.get("task_id"), "task_id", errors)
    _identifier(payload.get("attempt_id"), "attempt_id", errors)
    _identifier(payload.get("campaign_id"), "campaign_id", errors)
    _identifier(payload.get("lab_id"), "lab_id", errors)
    if not _text(payload.get("domain")):
        errors.append("domain must be a non-empty string")
    if not _text(payload.get("task_type")):
        errors.append("task_type must be a non-empty string")
    if not _text(payload.get("objective")):
        errors.append("objective must be a non-empty string")
    output = _text(payload.get("output_path"))
    if not output:
        errors.append("output_path must be a non-empty string")
    for field_name in ("lab_manifest", "agent_workspace", "run_metadata_path"):
        if not _text(payload.get(field_name)):
            errors.append(f"{field_name} must be a non-empty string")
    attempt = payload.get("attempt")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        errors.append("attempt must be a positive integer")
    budget = payload.get("budget")
    if not isinstance(budget, Mapping):
        errors.append("budget must be an object")
    else:
        wall_seconds = budget.get("wall_seconds")
        if (
            not isinstance(wall_seconds, int)
            or isinstance(wall_seconds, bool)
            or wall_seconds < 1
        ):
            errors.append("budget.wall_seconds must be a positive integer")
    agent = payload.get("agent")
    if not isinstance(agent, Mapping):
        errors.append("agent must be an object")
    else:
        role = _text(agent.get("role"))
        mode = _text(agent.get("session_mode"))
        session_id = agent.get("session_id")
        if role not in AGENT_ROLES:
            errors.append(f"agent.role must be one of {sorted(AGENT_ROLES)}")
        if mode not in SESSION_MODES:
            errors.append(f"agent.session_mode must be one of {sorted(SESSION_MODES)}")
        if session_id is not None and not _text(session_id):
            errors.append("agent.session_id must be null or a non-empty string")
        if role == "reviewer" and (mode != "fresh" or session_id is not None):
            errors.append("reviewer tasks must start with a blank session")
        if mode == "fresh" and session_id is not None:
            errors.append("fresh tasks cannot receive a prior session_id")
    if not payload.get("skill_path"):
        warnings.append("task has no skill_path; the lab must provide its own procedure")
    return ValidationResult(not errors, tuple(errors), tuple(warnings))


def validate_result_bundle(payload: Any) -> ValidationResult:
    if not isinstance(payload, Mapping):
        return ValidationResult(False, ("result bundle must be a JSON object",))
    errors: list[str] = []
    warnings: list[str] = []
    if payload.get("schema_version") != RESULT_SCHEMA:
        errors.append(f"schema_version must be {RESULT_SCHEMA}")
    _identifier(payload.get("task_id"), "task_id", errors)
    _identifier(payload.get("campaign_id"), "campaign_id", errors)
    _identifier(payload.get("lab_id"), "lab_id", errors)
    status = _text(payload.get("status"))
    if status not in RESULT_STATUSES:
        errors.append(f"status must be one of {sorted(RESULT_STATUSES)}")
    if not _text(payload.get("summary")):
        errors.append("summary must be a non-empty string")

    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        errors.append("artifacts must be an array")
        artifacts = []
    artifact_ids: set[str] = set()
    for index, artifact in enumerate(artifacts):
        prefix = f"artifacts[{index}]"
        if not isinstance(artifact, Mapping):
            errors.append(f"{prefix} must be an object")
            continue
        artifact_id = _identifier(artifact.get("artifact_id"), f"{prefix}.artifact_id", errors)
        if artifact_id in artifact_ids:
            errors.append(f"{prefix}.artifact_id is duplicated: {artifact_id}")
        artifact_ids.add(artifact_id)
        uri = _text(artifact.get("uri"))
        if not uri:
            errors.append(f"{prefix}.uri must be a non-empty string")
        digest = _text(artifact.get("sha256"))
        if digest and not SHA256.fullmatch(digest):
            errors.append(f"{prefix}.sha256 must be a lowercase SHA-256 digest")
        if status in {"completed", "succeeded"} and not digest:
            warnings.append(f"{prefix} has no sha256; it cannot support a promoted claim")

    claims = payload.get("claims")
    if not isinstance(claims, list):
        errors.append("claims must be an array")
        claims = []
    for index, claim in enumerate(claims):
        prefix = f"claims[{index}]"
        if not isinstance(claim, Mapping):
            errors.append(f"{prefix} must be an object")
            continue
        _identifier(claim.get("claim_id"), f"{prefix}.claim_id", errors)
        if not _text(claim.get("text")):
            errors.append(f"{prefix}.text must be a non-empty string")
        claim_status = _text(claim.get("status"))
        if claim_status not in {"hypothesis", "unsupported", "supported", "verified", "refuted"}:
            errors.append(
                f"{prefix}.status must be hypothesis, unsupported, supported, verified, or refuted"
            )
        evidence = claim.get("evidence")
        if not isinstance(evidence, list):
            errors.append(f"{prefix}.evidence must be an array")
            evidence = []
        missing = [ref for ref in evidence if not isinstance(ref, str) or ref not in artifact_ids]
        if missing:
            errors.append(f"{prefix}.evidence references unknown artifacts: {missing}")
        if claim_status in {"supported", "verified", "refuted"} and not evidence:
            errors.append(f"{prefix} requires evidence for status {claim_status}")
        limitations = claim.get("limitations")
        if not isinstance(limitations, list):
            errors.append(f"{prefix}.limitations must be an array")
        elif any(not _text(item) for item in limitations):
            errors.append(f"{prefix}.limitations must contain only non-empty strings")

    next_actions = payload.get("next_actions", [])
    if not isinstance(next_actions, list):
        errors.append("next_actions must be an array")
    else:
        for index, action in enumerate(next_actions):
            prefix = f"next_actions[{index}]"
            if isinstance(action, str):
                if not _text(action):
                    errors.append(f"{prefix} must be a non-empty string")
                continue
            if not isinstance(action, Mapping):
                errors.append(f"{prefix} must be a string or role handoff object")
                continue
            if not _text(action.get("objective")):
                errors.append(f"{prefix}.objective must be a non-empty string")
            role = _text(action.get("agent_role"))
            mode = _text(action.get("session_mode"))
            if role not in AGENT_ROLES:
                errors.append(f"{prefix}.agent_role must be one of {sorted(AGENT_ROLES)}")
            if mode not in SESSION_MODES:
                errors.append(f"{prefix}.session_mode must be one of {sorted(SESSION_MODES)}")
            if role == "reviewer" and mode != "fresh":
                errors.append(f"{prefix}: reviewer handoffs must start fresh")
    return ValidationResult(not errors, tuple(errors), tuple(warnings))


def validate_receipt(payload: Any) -> ValidationResult:
    if not isinstance(payload, Mapping):
        return ValidationResult(False, ("receipt must be a JSON object",))
    errors: list[str] = []
    if payload.get("schema_version") != RECEIPT_SCHEMA:
        errors.append(f"schema_version must be {RECEIPT_SCHEMA}")
    _identifier(payload.get("task_id"), "task_id", errors)
    _identifier(payload.get("attempt_id"), "attempt_id", errors)
    _identifier(payload.get("campaign_id"), "campaign_id", errors)
    _identifier(payload.get("lab_id"), "lab_id", errors)
    if not _text(payload.get("domain")):
        errors.append("domain must be a non-empty string")
    if _text(payload.get("agent_role")) not in AGENT_ROLES:
        errors.append(f"agent_role must be one of {sorted(AGENT_ROLES)}")
    if not _text(payload.get("result_path")):
        errors.append("result_path must be a non-empty string")
    if not SHA256.fullmatch(_text(payload.get("sha256"))):
        errors.append("sha256 must be a lowercase SHA-256 digest")
    runtime = payload.get("runtime")
    if not isinstance(runtime, Mapping):
        errors.append("runtime must be an object")
    else:
        duration = runtime.get("duration_seconds")
        if (
            not isinstance(duration, (int, float))
            or isinstance(duration, bool)
            or duration < 0
        ):
            errors.append("runtime.duration_seconds must be a non-negative number")
        exit_code = runtime.get("exit_code")
        if not isinstance(exit_code, int) or isinstance(exit_code, bool):
            errors.append("runtime.exit_code must be an integer")
        session_id = runtime.get("session_id")
        if session_id is not None and not _text(session_id):
            errors.append("runtime.session_id must be null or a non-empty string")
    return ValidationResult(not errors, tuple(errors))


def artifact_digests(payload: Mapping[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for artifact in payload.get("artifacts", []):
        mapping = _mapping(artifact)
        artifact_id = _text(mapping.get("artifact_id"))
        digest = _text(mapping.get("sha256"))
        if artifact_id and digest:
            result[artifact_id] = digest
    return result
