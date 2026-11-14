"""Versioned file contracts shared by the control plane and isolated labs."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

from .remote_compute import CPU_RANGE, MEMORY_MIB_RANGE

TASK_SCHEMA = "openlabs.task.v3"
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
    # The attempt ends to wait for remote compute jobs it submitted; the
    # orchestrator parks the continuation until every listed job is terminal.
    "awaiting_remote",
}
# These statuses authorize committing a valid attempt checkpoint.  They do not
# mean that a domain objective, theorem, or publication gate was promoted.
COMMITTABLE_RESULT_STATUSES = frozenset(
    {"completed", "succeeded", "needs_replan", "awaiting_remote"}
)
REMOTE_JOB_ID = re.compile(r"^[0-9a-f]{32}$")
MAX_AWAITED_REMOTE_JOBS = 32
# A declared wait longer than this is clipped (seven days).
MAX_REMOTE_WAIT_SECONDS = 7 * 24 * 3600
# Compatibility alias for callers outside this repository.  New code should
# use the semantically precise name above.
PROMOTABLE_RESULT_STATUSES = COMMITTABLE_RESULT_STATUSES
AGENT_ROLES = {"researcher", "experimenter", "writer", "reviewer"}
SESSION_MODES = {"resume", "fresh"}
HANDOFF_KINDS = {
    "role_handoff",
    "text_revision",
    "evidence_remediation",
    "independent_replication",
    "adversarial_review",
    "portfolio_review",
    "route_reselection",
    # A direction decision moved the manuscript to another venue or a short format.
    "retarget",
}
RESOURCE_KEYS = ("cpu_threads", "memory_mib", "scratch_mib")
EXECUTABLE_ARTIFACT_KINDS = frozenset(
    {"verification_script", "reproduction_script", "validator_script"}
)


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


def executable_artifact(artifact: Mapping[str, Any]) -> bool:
    """Return whether an artifact must carry a replayable dependency closure."""

    kind = _text(artifact.get("kind")).lower()
    suffix = PurePosixPath(urlparse(_text(artifact.get("uri"))).path).suffix.lower()
    return kind in EXECUTABLE_ARTIFACT_KINDS or kind.endswith("_script") or suffix in {".py", ".sh"}


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
    transaction = payload.get("transaction")
    if transaction is not None:
        if not isinstance(transaction, Mapping):
            errors.append("transaction must be an object")
        else:
            if transaction.get("mode") != "isolated_attempt_workspace":
                errors.append("transaction.mode must be isolated_attempt_workspace")
            for field_name in (
                "attempt_root",
                "staged_campaign_workspace",
                "canonical_campaign_workspace",
                "promotion_policy",
            ):
                if not _text(transaction.get(field_name)):
                    errors.append(f"transaction.{field_name} must be a non-empty string")
            artifact_policy = transaction.get("artifact_policy")
            if artifact_policy is not None:
                if not isinstance(artifact_policy, Mapping):
                    errors.append("transaction.artifact_policy must be an object")
                else:
                    if artifact_policy.get("schema_version") != "openlabs.artifact_policy.v1":
                        errors.append(
                            "transaction.artifact_policy.schema_version must be "
                            "openlabs.artifact_policy.v1"
                        )
                    for field_name in (
                        "max_data_file_bytes",
                        "max_changed_files",
                        "max_changed_bytes",
                    ):
                        value = artifact_policy.get(field_name)
                        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                            errors.append(
                                f"transaction.artifact_policy.{field_name} must be a positive integer"
                            )
                    suffixes = artifact_policy.get("artifact_only_suffixes")
                    if (
                        not isinstance(suffixes, list)
                        or not suffixes
                        or any(not _text(item) or not str(item).startswith(".") for item in suffixes)
                    ):
                        errors.append(
                            "transaction.artifact_policy.artifact_only_suffixes must be a "
                            "non-empty array of dotted suffixes"
                        )
                    if artifact_policy.get("undeclared_staging_policy") != "reject":
                        errors.append(
                            "transaction.artifact_policy.undeclared_staging_policy must be reject"
                        )
                staging = _text(transaction.get("artifact_staging_root"))
                if not staging or not Path(staging).is_absolute():
                    errors.append("transaction.artifact_staging_root must be an absolute path")
    project = payload.get("project")
    if project is not None:
        if not isinstance(project, Mapping):
            errors.append("project must be an object")
        else:
            for field_name in ("config_path", "workstream_state_path"):
                if not _text(project.get(field_name)):
                    errors.append(f"project.{field_name} must be a non-empty string")
            if not _text(project.get("protocol_id")):
                errors.append("project.protocol_id must be a non-empty string")
            domain_config_path = project.get("domain_config_path")
            if domain_config_path is not None and (
                not _text(domain_config_path)
                or not Path(str(domain_config_path)).is_absolute()
            ):
                errors.append("project.domain_config_path must be null or an absolute path")
            read_resources = project.get("read_resources", [])
            if not isinstance(read_resources, list):
                errors.append("project.read_resources must be an array")
            else:
                labels: list[str] = []
                paths: list[str] = []
                for index, item in enumerate(read_resources):
                    if not isinstance(item, Mapping):
                        errors.append(f"project.read_resources[{index}] must be an object")
                        continue
                    label = _text(item.get("label"))
                    path = _text(item.get("path"))
                    if not label:
                        errors.append(
                            f"project.read_resources[{index}].label must be non-empty"
                        )
                    if not path or not Path(path).is_absolute():
                        errors.append(
                            f"project.read_resources[{index}].path must be absolute"
                        )
                    labels.append(label)
                    paths.append(path)
                if len(labels) != len(set(labels)):
                    errors.append("project.read_resources labels must be unique")
                if len(paths) != len(set(paths)):
                    errors.append("project.read_resources paths must be unique")
    execution_policy = payload.get("execution_policy")
    if execution_policy is not None:
        if not isinstance(execution_policy, Mapping):
            errors.append("execution_policy must be an object")
        else:
            default_mode = _text(execution_policy.get("default_session_mode"))
            if default_mode not in SESSION_MODES:
                errors.append(
                    "execution_policy.default_session_mode must be one of "
                    f"{sorted(SESSION_MODES)}"
                )
            boundaries = execution_policy.get("fresh_session_boundaries")
            if not isinstance(boundaries, list):
                errors.append("execution_policy.fresh_session_boundaries must be an array")
            else:
                normalized_boundaries = [_text(item) for item in boundaries]
                if any(not item for item in normalized_boundaries):
                    errors.append(
                        "execution_policy.fresh_session_boundaries must contain strings"
                    )
                unknown = set(normalized_boundaries) - HANDOFF_KINDS
                if unknown:
                    errors.append(
                        "execution_policy.fresh_session_boundaries contain unknown kinds: "
                        + ", ".join(sorted(unknown))
                    )
                if len(normalized_boundaries) != len(set(normalized_boundaries)):
                    errors.append(
                        "execution_policy.fresh_session_boundaries cannot contain duplicates"
                    )
    if (project is None) != (execution_policy is None):
        errors.append("project and execution_policy must be supplied together")
    attempt = payload.get("attempt")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        errors.append("attempt must be a positive integer")
    budget = payload.get("budget")
    if not isinstance(budget, Mapping):
        errors.append("budget must be an object")
    else:
        wall_seconds = budget.get("wall_seconds")
        if not isinstance(wall_seconds, int) or isinstance(wall_seconds, bool) or wall_seconds < 1:
            errors.append("budget.wall_seconds must be a positive integer")
    resources = payload.get("resources")
    if not isinstance(resources, Mapping):
        errors.append("resources must be an object")
    else:
        for key in RESOURCE_KEYS:
            value = resources.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                errors.append(f"resources.{key} must be a positive integer")
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


def _awaiting_remote_errors(block: Any) -> list[str]:
    """Shape of ``awaiting_remote``: the remote jobs an attempt yields to wait for."""

    if not isinstance(block, Mapping):
        return ["status awaiting_remote requires an awaiting_remote object with job_ids"]
    errors: list[str] = []
    job_ids = block.get("job_ids")
    if not isinstance(job_ids, list) or not job_ids:
        errors.append("awaiting_remote.job_ids must be a non-empty array")
    else:
        if len(job_ids) > MAX_AWAITED_REMOTE_JOBS:
            errors.append(f"awaiting_remote.job_ids lists more than {MAX_AWAITED_REMOTE_JOBS} jobs")
        bad = [item for item in job_ids if not isinstance(item, str) or not REMOTE_JOB_ID.match(item)]
        if bad:
            errors.append("awaiting_remote.job_ids must be 32-character lowercase hex job ids")
        if len(set(map(str, job_ids))) != len(job_ids):
            errors.append("awaiting_remote.job_ids contains duplicates")
    resume = block.get("resume_objective")
    if resume is not None and not _text(resume):
        errors.append("awaiting_remote.resume_objective must be a non-empty string when given")
    max_wait = block.get("max_wait_seconds")
    if max_wait is not None and (
        not isinstance(max_wait, int) or isinstance(max_wait, bool) or max_wait < 60
    ):
        errors.append("awaiting_remote.max_wait_seconds must be an integer of at least 60")
    return errors


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
    reproduction_timeout_total = 0
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
        if status in COMMITTABLE_RESULT_STATUSES and not digest:
            warnings.append(f"{prefix} has no sha256; it cannot support a promoted claim")
        reproduction = artifact.get("reproduction")
        if (
            status in COMMITTABLE_RESULT_STATUSES
            and executable_artifact(artifact)
            and not isinstance(reproduction, Mapping)
        ):
            errors.append(
                f"{prefix}.reproduction must declare the replay command and input closure"
            )
            continue
        if reproduction is not None:
            if not isinstance(reproduction, Mapping):
                errors.append(f"{prefix}.reproduction must be an object")
                continue
            command = reproduction.get("command")
            if (
                not isinstance(command, list)
                or not command
                or any(not _text(item) for item in command)
            ):
                errors.append(f"{prefix}.reproduction.command must be an argv string array")
            elif executable_artifact(artifact) and not any(
                "{artifact}" in str(item) for item in command
            ):
                errors.append(
                    f"{prefix}.reproduction.command must reference the {{artifact}} placeholder"
                )
            inputs = reproduction.get("inputs")
            if not isinstance(inputs, list):
                errors.append(f"{prefix}.reproduction.inputs must be an array")
                inputs = []
            input_paths: set[str] = set()
            for input_index, declared_input in enumerate(inputs):
                input_prefix = f"{prefix}.reproduction.inputs[{input_index}]"
                if not isinstance(declared_input, Mapping):
                    errors.append(f"{input_prefix} must be an object")
                    continue
                relative = _text(declared_input.get("path"))
                if not safe_relative_path(relative):
                    errors.append(f"{input_prefix}.path must be a safe relative path")
                elif relative in input_paths:
                    errors.append(f"{input_prefix}.path is duplicated: {relative}")
                input_paths.add(relative)
                input_digest = _text(declared_input.get("sha256"))
                if not SHA256.fullmatch(input_digest):
                    errors.append(f"{input_prefix}.sha256 must be a lowercase SHA-256 digest")
            timeout_seconds = reproduction.get("timeout_seconds", 120)
            if (
                not isinstance(timeout_seconds, int)
                or isinstance(timeout_seconds, bool)
                or not 1 <= timeout_seconds <= 300
            ):
                errors.append(
                    f"{prefix}.reproduction.timeout_seconds must be an integer from 1 to 300"
                )
            else:
                reproduction_timeout_total += timeout_seconds
            if isinstance(payload.get("openlabs_archive"), Mapping):
                replay = reproduction.get("replay")
                if not isinstance(replay, Mapping) or replay.get("status") != "passed":
                    errors.append(f"{prefix}.reproduction replay did not pass in the archive")
                if not _text(reproduction.get("workspace_uri")):
                    errors.append(f"{prefix}.reproduction.workspace_uri is required in the archive")
    if reproduction_timeout_total > 300:
        errors.append("artifacts reproduction timeout budget must not exceed 300 seconds")

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
        if status == "needs_replan" and not next_actions:
            errors.append("needs_replan requires at least one executable next action")
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
            handoff_kind = action.get("handoff_kind")
            if handoff_kind is not None and _text(handoff_kind) not in HANDOFF_KINDS:
                errors.append(f"{prefix}.handoff_kind must be one of {sorted(HANDOFF_KINDS)}")
            wall_seconds = action.get("wall_seconds")
            if wall_seconds is not None and (
                not isinstance(wall_seconds, int)
                or isinstance(wall_seconds, bool)
                or wall_seconds < 1
            ):
                errors.append(f"{prefix}.wall_seconds must be a positive integer")
            resources = action.get("resources")
            if resources is not None:
                if not isinstance(resources, Mapping):
                    errors.append(f"{prefix}.resources must be an object")
                else:
                    for key in RESOURCE_KEYS:
                        value = resources.get(key)
                        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                            errors.append(f"{prefix}.resources.{key} must be a positive integer")
    if status == "needs_replan" and payload.get("paper_candidate") is True:
        errors.append("needs_replan cannot declare paper_candidate=true")
    if status == "awaiting_remote":
        if payload.get("paper_candidate") is True:
            errors.append("awaiting_remote cannot declare paper_candidate=true")
        errors.extend(_awaiting_remote_errors(payload.get("awaiting_remote")))
    elif payload.get("awaiting_remote") is not None and status != "needs_replan":
        warnings.append("awaiting_remote is ignored unless status is awaiting_remote")
    candidate_branches = payload.get("candidate_branches", [])
    if not isinstance(candidate_branches, list):
        errors.append("candidate_branches must be an array")
    else:
        candidate_ids: set[str] = set()
        for index, branch in enumerate(candidate_branches):
            prefix = f"candidate_branches[{index}]"
            if not isinstance(branch, Mapping):
                errors.append(f"{prefix} must be an object")
                continue
            candidate_id = _identifier(branch.get("candidate_id"), f"{prefix}.candidate_id", errors)
            if candidate_id in candidate_ids:
                errors.append(f"{prefix}.candidate_id is duplicated")
            candidate_ids.add(candidate_id)
            for field_name in ("title", "objective", "rationale"):
                if not _text(branch.get(field_name)):
                    errors.append(f"{prefix}.{field_name} must be a non-empty string")
            source_ids = branch.get("source_result_ids")
            if not isinstance(source_ids, list) or not source_ids:
                errors.append(f"{prefix}.source_result_ids must be a nonempty array")
            elif any(not _text(item) for item in source_ids):
                errors.append(f"{prefix}.source_result_ids must contain non-empty strings")
            resources = branch.get("resources")
            if resources is not None:
                if not isinstance(resources, Mapping):
                    errors.append(f"{prefix}.resources must be an object")
                else:
                    for key in RESOURCE_KEYS:
                        value = resources.get(key)
                        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                            errors.append(f"{prefix}.resources.{key} must be a positive integer")
            wall_seconds = branch.get("wall_seconds")
            if wall_seconds is not None and (
                not isinstance(wall_seconds, int)
                or isinstance(wall_seconds, bool)
                or wall_seconds < 1
            ):
                errors.append(f"{prefix}.wall_seconds must be a positive integer")
            if "admission" in branch:
                if not _text(branch.get("topic_id")):
                    errors.append(f"{prefix}.topic_id is required with an admission decision")
                errors.extend(
                    f"{prefix}.{item}"
                    for item in validate_topic_admission(branch.get("admission")).errors
                )
    for name, validator in (
        ("review_outcome", validate_review_outcome),
        ("direction_decision", validate_direction_decision),
    ):
        if payload.get(name) is not None:
            errors.extend(f"{name}.{item}" for item in validator(payload.get(name)).errors)
    outcome = payload.get("review_outcome")
    if (
        isinstance(outcome, Mapping)
        and payload.get("paper_candidate") is True
        and outcome.get("status") != "ready"
    ):
        errors.append("paper_candidate=true requires review_outcome.status ready")
    verdict = payload.get("primary_endpoint_verdict")
    if verdict is not None and _text(verdict) not in PRIMARY_ENDPOINT_VERDICTS:
        errors.append(
            f"primary_endpoint_verdict must be one of {sorted(PRIMARY_ENDPOINT_VERDICTS)}"
        )
    declared = payload.get("preregistration_sha256")
    if declared is not None and not SHA256.fullmatch(_text(declared)):
        errors.append("preregistration_sha256 must be a lowercase SHA-256 digest")
    topic_cards = payload.get("topic_cards")
    # Card contents are judged per card by the program controller (a bad card is
    # rejected with reasons, not the whole scout result).
    if topic_cards is not None and (
        not isinstance(topic_cards, list)
        or any(not isinstance(item, Mapping) for item in topic_cards)
    ):
        errors.append("topic_cards must be an array of objects")
    return ValidationResult(not errors, tuple(errors), tuple(warnings))


# ---------------------------------------------------------------- research program

TOPIC_CARD_SCHEMA = "openlabs.topic_card.v1"
TOPIC_TIERS = frozenset({"routine", "escalation"})
ADMISSION_VERDICTS = frozenset({"admit", "reject", "hold"})
# Admission policy (skill ``openlabs-topic-admission``). v2 (2026-11-12): routine
# topics are admitted on a stated increment, confirmed data, an identifying
# design and line fit; fixable gaps become ``admission.conditions`` instead of a
# rejection, and holds or fixable rejections return as one revision card.
ADMISSION_POLICY_VERSION = "openlabs.topic_admission_policy.v2"
# When an admission condition must be met (``admission.conditions[].due``).
ADMISSION_CONDITION_DUES = ("before_precheck", "before_decisive_analysis", "before_submission")
REOPEN_BASIS_TYPES = frozenset(
    {
        "new_data_source",
        "new_method",
        "venue_policy_change",
        "external_result",
        # The card's research line got a ready environment (registry/research-lines.yaml).
        "line_environment_ready",
    }
)
PRIMARY_ENDPOINT_FIELDS = ("metric", "matched_baseline", "split", "decision_rule", "stop_rule")
COST_ESTIMATE_FIELDS = ("agent_seconds", "tokens", "gpu_hours", "calendar_days")
# Where a topic's experiments run (AGENTS.md, "Where computation runs").
COMPUTE_LOCATIONS = ("container_cpu", "container_gpu", "ailab", "wsl_math")
AUDIENCE_RECENT_YEARS = 3
# Research-line cards (``research_line`` set): fee evidence levels as in
# registry/research-lines.yaml, and what a licence item may be.
FEE_EVIDENCE_LEVELS = ("verified_journal", "verified_publisher", "secondary", "unverified")
VERIFIED_FEE_LEVELS = frozenset({"verified_journal", "verified_publisher"})
FEE_CHARGE_FIELDS = ("page_charges", "colour_charges", "submission_fee")
LICENSE_ITEM_KINDS = ("software", "weights", "data")
PRECHECK_FIELDS = ("description", "pass_criterion", "budget")


def _normalized_name(value: Any) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", _text(value).casefold()).split())


def _nonnegative_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def preregistration_sha256(primary_endpoint: Any) -> str:
    """SHA-256 of the canonical JSON of a pre-registered primary-endpoint block."""

    return hashlib.sha256(canonical_json_bytes(primary_endpoint)).hexdigest()


def _endpoint_errors(value: Any, label: str) -> list[str]:
    if not isinstance(value, Mapping):
        return [f"{label} must be an object with {', '.join(PRIMARY_ENDPOINT_FIELDS)}"]
    return [
        f"{label}.{name} is missing"
        for name in PRIMARY_ENDPOINT_FIELDS
        if not _text(value.get(name))
    ]


def escalation_venue_names(escalation: Any) -> list[str]:
    """Venue names of ``venues.escalation``: its ``name``, or a ``venues`` list."""

    if not isinstance(escalation, Mapping):
        return []
    names = [_text(escalation.get("name"))] if _text(escalation.get("name")) else []
    listed = escalation.get("venues")
    for item in listed if isinstance(listed, list) else []:
        name = _text(item.get("name")) if isinstance(item, Mapping) else _text(item)
        if name:
            names.append(name)
    return names


def _venue_names(venues: Mapping[str, Any]) -> set[str]:
    names: set[str] = set()
    for item in list(venues.get("routine") or []):
        if isinstance(item, Mapping) and _text(item.get("name")):
            names.add(_normalized_name(item.get("name")))
    names.update(_normalized_name(name) for name in escalation_venue_names(venues.get("escalation")))
    return names


def data_source_identifiers(data_sources: Any) -> list[str]:
    """Stable identifiers (DOI preferred, else URL) used by the topic fingerprint."""

    identifiers: list[str] = []
    for item in data_sources if isinstance(data_sources, list) else []:
        if isinstance(item, Mapping):
            identifier = _text(item.get("doi")) or _text(item.get("url"))
            if identifier:
                identifiers.append(identifier)
    return identifiers


def validate_topic_card(card: Any, *, current_year: int | None = None) -> ValidationResult:
    """Machine check of a topic card's structure (``openlabs.topic_card.v1``).

    The check only establishes that every field the admission gate needs is
    present and well formed; whether the answers are good is the gate's call.
    ``errors`` are gaps that change what admission can judge or a hard limit (no
    question, no pre-registrable primary endpoint, no data source, no target venue,
    no closest prior work, unverified data access, a non-computational topic, the
    compute plan, a line card's precheck, licences and fees, a revision's answers):
    the card is rejected and gets one repair. Everything else is a ``warning``
    recorded with the card and shown to the admission gate (audience evidence,
    data-source version or licence notes, cost numbers, occupancy search, ...).
    Run :func:`normalize_topic_card` first to fix the purely mechanical slips.
    """

    if not isinstance(card, Mapping):
        return ValidationResult(False, ("topic card must be a JSON object",))
    year = current_year or datetime.now(UTC).year
    errors: list[str] = []
    warnings: list[str] = []
    schema = card.get("schema_version")
    if schema is not None and schema != TOPIC_CARD_SCHEMA:
        errors.append(f"schema_version must be {TOPIC_CARD_SCHEMA}")
    if not _text(card.get("question")):
        errors.append("question is missing")

    venues = card.get("venues")
    if not isinstance(venues, Mapping):
        errors.append("venues is missing (two routine candidates, optional escalation)")
        venues = {}
    else:
        routine = venues.get("routine")
        named = [
            item for item in routine if isinstance(item, Mapping) and _text(item.get("name"))
        ] if isinstance(routine, list) else []
        if not named:
            errors.append("venues.routine needs a named routine target venue (two preferred)")
        else:
            if len(named) < 2:
                warnings.append("venues.routine names one routine venue (two preferred)")
            for index, item in enumerate(routine):
                if not isinstance(item, Mapping) or not _text(item.get("name")):
                    warnings.append(f"venues.routine[{index}].name is missing")
        escalation = venues.get("escalation")
        # An escalation names its venue in ``name`` or, for alternatives, a ``venues`` list.
        if escalation is not None and not escalation_venue_names(escalation):
            warnings.append(
                "venues.escalation must be null or an object with a name (or a venues list)"
            )
    venue_names = _venue_names(venues)

    audience = card.get("audience")
    if not isinstance(audience, Mapping):
        warnings.append("audience is missing (who cares, with two recent candidate-venue papers)")
    else:
        if not _text(audience.get("who")):
            warnings.append("audience.who is missing")
        citations = audience.get("citations")
        recent = 0
        if not isinstance(citations, list):
            warnings.append("audience.citations is missing")
            citations = []
        for index, item in enumerate(citations):
            prefix = f"audience.citations[{index}]"
            if not isinstance(item, Mapping) or not _text(item.get("citation")):
                warnings.append(f"{prefix}.citation is missing")
                continue
            published = item.get("year")
            if not isinstance(published, int) or isinstance(published, bool):
                warnings.append(f"{prefix}.year must be an integer")
                continue
            # Readers' papers in other venues are ordinary evidence of the audience; only
            # papers in the candidate venues count towards the venue-readership minimum.
            if _normalized_name(item.get("venue")) not in venue_names:
                continue
            if year - AUDIENCE_RECENT_YEARS <= published <= year:
                recent += 1
        if recent < 2:
            warnings.append(
                "audience.citations needs at least two papers from the last "
                f"{AUDIENCE_RECENT_YEARS} years published in candidate venues"
            )

    prior = card.get("closest_prior_work")
    if not isinstance(prior, list) or not prior:
        errors.append("closest_prior_work is missing")
    else:
        for index, item in enumerate(prior):
            for name in ("citation", "what_it_shows", "our_difference"):
                if not isinstance(item, Mapping) or not _text(item.get(name)):
                    warnings.append(f"closest_prior_work[{index}].{name} is missing")

    decisive = card.get("decisive_analysis")
    if not isinstance(decisive, Mapping):
        errors.append("decisive_analysis is missing")
    else:
        if not _text(decisive.get("description")):
            warnings.append("decisive_analysis.description is missing")
        if decisive.get("data_access_verified") is not True:
            errors.append("decisive_analysis.data_access_verified must be true")
        receipt = decisive.get("access_receipt")
        if (
            not isinstance(receipt, Mapping)
            or not _text(receipt.get("path"))
            or not SHA256.fullmatch(_text(receipt.get("sha256")))
        ):
            errors.append("decisive_analysis.access_receipt needs a path and a sha256")

    errors.extend(_endpoint_errors(card.get("primary_endpoint"), "primary_endpoint"))

    sources = card.get("data_sources")
    if not isinstance(sources, list) or not sources:
        errors.append("data_sources is missing")
    else:
        for index, item in enumerate(sources):
            prefix = f"data_sources[{index}]"
            if not isinstance(item, Mapping):
                errors.append(f"{prefix} must be an object")
                continue
            if not (_text(item.get("doi")) or _text(item.get("url"))):
                errors.append(f"{prefix} needs a stable doi or url")
            for name in ("version", "license"):
                if not _text(item.get(name)):
                    warnings.append(f"{prefix}.{name} is missing")

    if card.get("computational_only") is not True:
        errors.append("computational_only must be true")
    if not _text(card.get("computational_only_rationale")):
        warnings.append(
            "computational_only_rationale is missing (why no wet lab or real-world interaction)"
        )

    cost = card.get("cost_estimate")
    if not isinstance(cost, Mapping):
        errors.append("cost_estimate is missing")
    else:
        for name in COST_ESTIMATE_FIELDS:
            if not _nonnegative_number(cost.get(name)):
                warnings.append(f"cost_estimate.{name} must be a non-negative number")
        if not _text(cost.get("basis")):
            warnings.append("cost_estimate.basis is missing")
        errors.extend(compute_plan_errors(cost))

    assets = card.get("reusable_assets")
    if not isinstance(assets, list):
        warnings.append("reusable_assets must be an array (possibly empty)")

    ledger_check = card.get("ledger_check")
    if not isinstance(ledger_check, Mapping) or not isinstance(
        ledger_check.get("compared_topic_ids"), list
    ):
        warnings.append("ledger_check.compared_topic_ids must be an array")

    if card.get("research_line") is not None:
        errors.extend(research_line_card_errors(card, venues))

    tier = card.get("target_tier")
    if tier is not None and tier not in TOPIC_TIERS:
        warnings.append("target_tier must be routine or escalation")
    if card.get("reopens") is not None:
        basis = card.get("reopen_basis")
        if not _text(card.get("reopens")):
            errors.append("reopens must name the topic_id being reopened")
        if (
            not isinstance(basis, Mapping)
            or _text(basis.get("type")) not in REOPEN_BASIS_TYPES
            or not _text(basis.get("description"))
        ):
            errors.append("reopen_basis needs a type and a description")
    warnings.extend(paper_template_errors(card))
    if card.get("revises") is not None:
        # A revision card answers the reopen conditions of the held or fixably
        # rejected topic it revises (the control plane sets ``revises``).
        if not _text(card.get("revises")):
            errors.append("revises must name the topic_id being revised")
        responses = card.get("condition_responses")
        if not isinstance(responses, list) or not responses:
            errors.append("condition_responses must answer the revised topic's reopen conditions")
            responses = []
        for index, item in enumerate(responses):
            condition = item.get("condition") if isinstance(item, Mapping) else None
            if (
                not isinstance(condition, int)
                or isinstance(condition, bool)
                or condition < 0
                or not _text(item.get("response"))
            ):
                errors.append(
                    f"condition_responses[{index}] needs condition (index into the revised "
                    "topic's reopen_conditions) and response"
                )
    return ValidationResult(not errors, tuple(errors), tuple(warnings))


def _number_from_text(value: Any) -> Any:
    """``"3600"``/``"0.5"`` -> number; anything else unchanged."""

    if isinstance(value, str) and re.fullmatch(r"\s*\d+(\.\d+)?\s*", value):
        number = float(value)
        return int(number) if number.is_integer() else number
    return value


def normalize_topic_card(card: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Fix the purely mechanical slips of a topic card; return the card and what changed.

    Only formatting is touched (schema tag, numbers written as text, an empty
    escalation, an unknown tier, missing empty lists, the one allowed precheck
    ``on_failure``). Nothing the admission gate judges is invented: a missing
    endpoint, data source, venue or receipt stays missing and is an error.
    """

    fixed = copy.deepcopy(dict(card))
    notes: list[str] = []
    if fixed.get("schema_version") not in (None, TOPIC_CARD_SCHEMA):
        notes.append(f"schema_version set to {TOPIC_CARD_SCHEMA}")
        fixed["schema_version"] = TOPIC_CARD_SCHEMA
    audience = fixed.get("audience")
    if isinstance(audience, dict) and isinstance(audience.get("citations"), list):
        for index, item in enumerate(audience["citations"]):
            if isinstance(item, dict) and isinstance(item.get("year"), str):
                year = _number_from_text(item["year"])
                if isinstance(year, int):
                    item["year"] = year
                    notes.append(f"audience.citations[{index}].year read as a number")
    cost = fixed.get("cost_estimate")
    if isinstance(cost, dict):
        for name in COST_ESTIMATE_FIELDS:
            value = _number_from_text(cost.get(name))
            if value is not cost.get(name):
                cost[name] = value
                notes.append(f"cost_estimate.{name} read as a number")
    venues = fixed.get("venues")
    if (
        isinstance(venues, dict)
        and venues.get("escalation") is not None
        and not escalation_venue_names(venues.get("escalation"))
    ):
        venues["escalation"] = None
        notes.append("venues.escalation without a venue name set to null")
    if fixed.get("target_tier") is not None and fixed.get("target_tier") not in TOPIC_TIERS:
        notes.append(f"target_tier {fixed.get('target_tier')!r} dropped (routine or escalation)")
        fixed.pop("target_tier")
    if not isinstance(fixed.get("reusable_assets"), list):
        notes.append("reusable_assets was not an array; set to []")
        fixed["reusable_assets"] = []
    ledger_check = fixed.get("ledger_check")
    if not isinstance(ledger_check, dict):
        fixed["ledger_check"] = {"compared_topic_ids": []}
        notes.append("ledger_check.compared_topic_ids set to []")
    elif not isinstance(ledger_check.get("compared_topic_ids"), list):
        ledger_check["compared_topic_ids"] = []
        notes.append("ledger_check.compared_topic_ids set to []")
    precheck = fixed.get("feasibility_precheck")
    if isinstance(precheck, dict) and not _text(precheck.get("on_failure")):
        precheck["on_failure"] = "freeze"
        notes.append("feasibility_precheck.on_failure set to freeze (the only allowed value)")
    return fixed, notes


SERIES_MIN_MEMBERS = 2


def paper_template_errors(card: Mapping[str, Any]) -> list[str]:
    """Optional ``paper_template`` / ``series`` fields of a templated card.

    ``paper_template`` names a ``paper_templates[].id`` of the card's research line;
    such a card records the occupancy search that shows its system x property
    combination is unreported (``occupancy_search``). ``series`` lists the adjacent
    systems one card covers with one pipeline (one paper per card).
    """

    errors: list[str] = []
    template = card.get("paper_template")
    if template is not None:
        if not _text(template):
            errors.append("paper_template must name a paper_templates id of the research line")
        if not _text(card.get("research_line")):
            errors.append("paper_template needs research_line")
        search = card.get("occupancy_search")
        if not isinstance(search, Mapping):
            errors.append(
                "occupancy_search is missing (queries, databases, searched_at, findings) for a "
                "paper_template card"
            )
        else:
            for name in ("queries", "databases"):
                value = search.get(name)
                if not isinstance(value, list) or not any(_text(item) for item in value):
                    errors.append(f"occupancy_search.{name} must be a non-empty array")
            for name in ("searched_at", "findings"):
                if not _text(search.get(name)):
                    errors.append(f"occupancy_search.{name} is missing")
    series = card.get("series")
    if series is not None:
        members = series.get("members") if isinstance(series, Mapping) else None
        if not isinstance(members, list) or len(
            [item for item in members if _text(item) or isinstance(item, Mapping)]
        ) < SERIES_MIN_MEMBERS:
            errors.append(
                f"series.members must list at least {SERIES_MIN_MEMBERS} adjacent systems"
            )
        if isinstance(series, Mapping) and not _text(series.get("shared_pipeline")):
            errors.append("series.shared_pipeline is missing (what the members share)")
    return errors


def research_line_card_errors(card: Mapping[str, Any], venues: Mapping[str, Any]) -> list[str]:
    """Fields a research-line card adds: the decisive precheck, licences and fees.

    ``feasibility_precheck`` is the cheap decisive analysis run first after
    admission (failure freezes the topic); ``license_check`` covers every
    software package, model weight and dataset; ``fee_check`` covers page,
    colour and submission charges of every routine venue, and at least one
    routine venue must have a verified fee-free route.
    """

    errors: list[str] = []
    if not _text(card.get("research_line")):
        errors.append("research_line must name a line of registry/research-lines.yaml")
    precheck = card.get("feasibility_precheck")
    if not isinstance(precheck, Mapping):
        errors.append(
            "feasibility_precheck is missing (description, pass_criterion, budget, "
            "on_failure: freeze)"
        )
    else:
        for name in PRECHECK_FIELDS:
            if not _text(precheck.get(name)):
                errors.append(f"feasibility_precheck.{name} is missing")
        if _text(precheck.get("on_failure")) != "freeze":
            errors.append("feasibility_precheck.on_failure must be freeze")
    licenses = card.get("license_check")
    if not isinstance(licenses, Mapping):
        errors.append("license_check is missing (items, blacklist_checked)")
    else:
        items = licenses.get("items")
        if not isinstance(items, list) or not items:
            errors.append("license_check.items must list every software, weight and dataset used")
            items = []
        for index, item in enumerate(items):
            prefix = f"license_check.items[{index}]"
            if not isinstance(item, Mapping):
                errors.append(f"{prefix} must be an object")
                continue
            for name in ("name", "license", "evidence"):
                if not _text(item.get(name)):
                    errors.append(f"{prefix}.{name} is missing")
            if _text(item.get("kind")) not in LICENSE_ITEM_KINDS:
                errors.append(f"{prefix}.kind must be one of {', '.join(LICENSE_ITEM_KINDS)}")
            if item.get("allowed") is not True:
                errors.append(f"{prefix}.allowed must be true (a blocked item cannot be used)")
        if licenses.get("blacklist_checked") is not True:
            errors.append("license_check.blacklist_checked must be true")
    fees = card.get("fee_check")
    routine = {
        _normalized_name(item.get("name"))
        for item in (venues.get("routine") or [])
        if isinstance(item, Mapping) and _text(item.get("name"))
    }
    if not isinstance(fees, list) or not fees:
        errors.append("fee_check must cover every routine venue")
        return errors
    covered: set[str] = set()
    verified_free = False
    for index, item in enumerate(fees):
        prefix = f"fee_check[{index}]"
        if not isinstance(item, Mapping) or not _text(item.get("venue")):
            errors.append(f"{prefix}.venue is missing")
            continue
        name = _normalized_name(item.get("venue"))
        covered.add(name)
        for field_name in (*FEE_CHARGE_FIELDS, "evidence"):
            if not _text(item.get(field_name)):
                errors.append(f"{prefix}.{field_name} is missing")
        level = _text(item.get("evidence_level"))
        if level not in FEE_EVIDENCE_LEVELS:
            errors.append(f"{prefix}.evidence_level must be one of {', '.join(FEE_EVIDENCE_LEVELS)}")
        free = item.get("fee_free_route")
        if free is False:
            errors.append(f"{prefix}: a venue with a mandatory fee cannot be a candidate")
        elif free is not True and free != "unverified":
            errors.append(f"{prefix}.fee_free_route must be true or \"unverified\"")
        if free is True and level in VERIFIED_FEE_LEVELS and name in routine:
            verified_free = True
    missing = sorted(routine - covered)
    if missing:
        errors.append("fee_check does not cover routine venue(s): " + ", ".join(missing))
    if routine and not verified_free:
        errors.append(
            "fee_check needs at least one routine venue with fee_free_route true and "
            "evidence_level verified_journal or verified_publisher"
        )
    return errors


def compute_plan_locations(cost_estimate: Any) -> tuple[str, ...]:
    """Locations named by ``cost_estimate.compute_plan`` (``()`` when absent or malformed)."""

    if not isinstance(cost_estimate, Mapping):
        return ()
    plan = cost_estimate.get("compute_plan")
    locations = plan.get("locations") if isinstance(plan, Mapping) else None
    if not isinstance(locations, list):
        return ()
    return tuple(str(item) for item in locations if isinstance(item, str))


def compute_plan_errors(cost: Mapping[str, Any]) -> list[str]:
    """``cost_estimate.compute_plan``: where the experiments run and rough sizes per place."""

    plan = cost.get("compute_plan")
    if not isinstance(plan, Mapping):
        return [
            "cost_estimate.compute_plan is missing (locations: "
            + ", ".join(COMPUTE_LOCATIONS) + ")"
        ]
    errors: list[str] = []
    locations = plan.get("locations")
    if (
        not isinstance(locations, list)
        or not locations
        or any(item not in COMPUTE_LOCATIONS for item in locations)
        or len(set(locations)) != len(locations)
    ):
        errors.append(
            "cost_estimate.compute_plan.locations must be a non-empty list of distinct values from "
            + ", ".join(COMPUTE_LOCATIONS)
        )
        locations = []
    if "container_gpu" in locations:
        memory = plan.get("gpu_memory_mib")
        if not _nonnegative_number(memory) or memory <= 0:
            errors.append("cost_estimate.compute_plan.gpu_memory_mib must be a positive number "
                          "when container_gpu is used")
    elif _nonnegative_number(cost.get("gpu_hours")) and cost["gpu_hours"] > 0:
        errors.append("cost_estimate.gpu_hours > 0 needs container_gpu in compute_plan.locations")
    if "ailab" in locations:
        ailab = plan.get("ailab")
        if not isinstance(ailab, Mapping):
            errors.append("cost_estimate.compute_plan.ailab needs cpus, memory_mib and hours")
        else:
            cpus, memory, hours = ailab.get("cpus"), ailab.get("memory_mib"), ailab.get("hours")
            if not (isinstance(cpus, int) and not isinstance(cpus, bool)
                    and CPU_RANGE[0] <= cpus <= CPU_RANGE[1]):
                errors.append(
                    f"cost_estimate.compute_plan.ailab.cpus must be {CPU_RANGE[0]}-{CPU_RANGE[1]}"
                )
            if not (_nonnegative_number(memory)
                    and MEMORY_MIB_RANGE[0] <= memory <= MEMORY_MIB_RANGE[1]):
                errors.append(
                    "cost_estimate.compute_plan.ailab.memory_mib must be "
                    f"{MEMORY_MIB_RANGE[0]}-{MEMORY_MIB_RANGE[1]}"
                )
            if not _nonnegative_number(hours) or hours <= 0:
                errors.append("cost_estimate.compute_plan.ailab.hours must be a positive number")
    return errors


def validate_topic_admission(admission: Any) -> ValidationResult:
    """Structure of one admission-gate decision (``candidate_branches[i].admission``)."""

    if not isinstance(admission, Mapping):
        return ValidationResult(False, ("admission must be an object",))
    errors: list[str] = []
    verdict = _text(admission.get("verdict"))
    if verdict not in ADMISSION_VERDICTS:
        errors.append("admission.verdict must be admit, reject or hold")
    if not _text(admission.get("strongest_rejection_reason")):
        errors.append("admission.strongest_rejection_reason is missing")
    if not isinstance(admission.get("data_access_confirmed"), bool):
        errors.append("admission.data_access_confirmed must be a boolean")
    cost = admission.get("cost_judgement")
    if (
        not isinstance(cost, Mapping)
        or not isinstance(cost.get("proportionate"), bool)
        or not _text(cost.get("rationale"))
    ):
        errors.append("admission.cost_judgement needs proportionate (boolean) and rationale")
    checked = admission.get("closest_prior_work_checked")
    if not isinstance(checked, list):
        errors.append("admission.closest_prior_work_checked must be an array")
        checked = []
    for index, item in enumerate(checked):
        if not isinstance(item, Mapping) or not _text(item.get("citation")) or not _text(
            item.get("assessment")
        ):
            errors.append(
                f"admission.closest_prior_work_checked[{index}] needs citation and assessment"
            )
    conditions = admission.get("reopen_conditions", [])
    if not isinstance(conditions, list):
        errors.append("admission.reopen_conditions must be an array")
        conditions = []
    for index, item in enumerate(conditions):
        if (
            not isinstance(item, Mapping)
            or _text(item.get("type")) not in REOPEN_BASIS_TYPES
            or not _text(item.get("description"))
        ):
            errors.append(f"admission.reopen_conditions[{index}] needs a type and description")
    if verdict == "hold" and not conditions:
        errors.append("admission.reopen_conditions is required for hold")
    errors.extend(admission_condition_errors(admission.get("conditions")))
    revisable = admission.get("revisable")
    if revisable is not None and not isinstance(revisable, bool):
        errors.append("admission.revisable must be a boolean when present")
    if verdict == "admit":
        if _text(admission.get("target_tier")) not in TOPIC_TIERS:
            errors.append("admission.target_tier must be escalation or routine")
        if not _text(admission.get("tier_rationale")):
            errors.append("admission.tier_rationale is missing")
        if not checked:
            errors.append("admission.closest_prior_work_checked must not be empty for admit")
        preregistration = admission.get("preregistration")
        if not isinstance(preregistration, Mapping):
            errors.append("admission.preregistration is missing")
        else:
            endpoint = preregistration.get("primary_endpoint")
            endpoint_errors = _endpoint_errors(
                endpoint, "admission.preregistration.primary_endpoint"
            )
            errors.extend(endpoint_errors)
            digest = _text(preregistration.get("sha256"))
            if not SHA256.fullmatch(digest):
                errors.append("admission.preregistration.sha256 must be a SHA-256 digest")
            elif not endpoint_errors and digest != preregistration_sha256(endpoint):
                errors.append(
                    "admission.preregistration.sha256 does not match the primary_endpoint block"
                )
    return ValidationResult(not errors, tuple(errors))


def admission_condition_errors(value: Any) -> list[str]:
    """``admission.conditions``: fixable gaps an admit carries (``description``, ``due``)."""

    if value is None:
        return []
    if not isinstance(value, list):
        return ["admission.conditions must be an array"]
    errors: list[str] = []
    for index, item in enumerate(value):
        if (
            not isinstance(item, Mapping)
            or not _text(item.get("description"))
            or _text(item.get("due")) not in ADMISSION_CONDITION_DUES
        ):
            errors.append(
                f"admission.conditions[{index}] needs a description and due "
                f"({', '.join(ADMISSION_CONDITION_DUES)})"
            )
    return errors


def admission_conditions(admission: Any) -> list[dict[str, str]]:
    """Normalized conditions of an admit (``[]`` for other verdicts or none)."""

    if not isinstance(admission, Mapping) or _text(admission.get("verdict")) not in ("admit", ""):
        return []
    items = admission.get("conditions")
    return [
        {"description": _text(item.get("description")), "due": _text(item.get("due"))}
        for item in (items if isinstance(items, list) else [])
        if isinstance(item, Mapping) and _text(item.get("description"))
        and _text(item.get("due")) in ADMISSION_CONDITION_DUES
    ]


# ---------------------------------------------------------------- autonomous back half

# ``pending``: the endpoint has not been evaluated yet (a freeze before the analysis,
# a paper candidate whose verdict the researcher still owes; neither enters writing).
PRIMARY_ENDPOINT_VERDICTS = frozenset({"met", "failed", "inconclusive", "pending"})
FREEZE_REASON_CLASSES = frozenset(
    {
        "primary_endpoint_failed",
        "decisive_data_unavailable",
        "overdue",
        "contribution_insufficient",
        "no_eligible_venue",
        "review_stalled",
        "infrastructure",
        # The hard per-topic Agent-time ceiling was reached.
        "budget_exhausted",
        # A research-line card's feasibility precheck missed its pass criterion.
        "feasibility_precheck_failed",
    }
)
REVIEW_NEXT_ACTIONS = frozenset(
    {"text_revision", "evidence_remediation", "retarget_required", "direction_decision"}
)
REVIEW_RELEASE_STATUSES = frozenset({"ready", "revision_required", "blocked"})
DIRECTION_CHOICES = ("targeted_core_analysis", "retarget_or_short_format", "freeze")
DIRECTION_ANALYSIS_FIELDS = ("name", "expected_to_change", "data", "success_criterion")


def _optional_count(value: Any) -> bool:
    return value is None or (isinstance(value, int) and not isinstance(value, bool) and value >= 0)


def validate_review_outcome(value: Any) -> ValidationResult:
    """``review_outcome`` of a paper_review result: the registry's writing_release, copied.

    Fields: ``next_action`` (null or text_revision / evidence_remediation /
    retarget_required / direction_decision), ``status`` (ready /
    revision_required / blocked), ``review_stalled``, ``rounds_for_target``,
    ``max_rounds_per_target``, ``direction_context``, ``decision_record`` and
    ``decision_record_sha256``; optional ``paper_id``.
    """

    if not isinstance(value, Mapping):
        return ValidationResult(False, ("must be an object copied from writing_release",))
    errors: list[str] = []
    action = value.get("next_action")
    if action is not None and _text(action) not in REVIEW_NEXT_ACTIONS:
        errors.append(f"next_action must be null or one of {sorted(REVIEW_NEXT_ACTIONS)}")
    if _text(value.get("status")) not in REVIEW_RELEASE_STATUSES:
        errors.append(f"status must be one of {sorted(REVIEW_RELEASE_STATUSES)}")
    if not isinstance(value.get("review_stalled", False), bool):
        errors.append("review_stalled must be a boolean")
    for name in ("rounds_for_target", "max_rounds_per_target"):
        if not _optional_count(value.get(name)):
            errors.append(f"{name} must be null or a non-negative integer")
    context = value.get("direction_context")
    if context is not None and not isinstance(context, Mapping):
        errors.append("direction_context must be null or an object")
    if not _text(value.get("decision_record")):
        errors.append("decision_record must name the unified decision record")
    if not SHA256.fullmatch(_text(value.get("decision_record_sha256"))):
        errors.append("decision_record_sha256 must be a lowercase SHA-256 digest")
    paper_id = value.get("paper_id")
    if paper_id is not None and not _text(paper_id):
        errors.append("paper_id must be a non-empty string when present")
    return ValidationResult(not errors, tuple(errors))


def validate_direction_decision(value: Any) -> ValidationResult:
    """``direction_decision`` of a direction_decision task (one choice, one branch block)."""

    if not isinstance(value, Mapping):
        return ValidationResult(False, ("must be an object",))
    errors: list[str] = []
    choice = _text(value.get("choice"))
    if choice not in DIRECTION_CHOICES:
        errors.append(f"choice must be one of {list(DIRECTION_CHOICES)}")
    for name in ("rationale", "answers_reason"):
        if not _text(value.get(name)):
            errors.append(f"{name} must be a non-empty string")
    if choice == "targeted_core_analysis":
        analysis = value.get("analysis")
        if not isinstance(analysis, Mapping):
            errors.append("analysis is required for targeted_core_analysis")
        else:
            for name in DIRECTION_ANALYSIS_FIELDS:
                if not _text(analysis.get(name)):
                    errors.append(f"analysis.{name} must be a non-empty string")
            seconds = analysis.get("budget_seconds")
            if not isinstance(seconds, int) or isinstance(seconds, bool) or seconds < 1:
                errors.append("analysis.budget_seconds must be a positive integer")
    elif choice == "retarget_or_short_format":
        retarget = value.get("retarget")
        if not isinstance(retarget, Mapping):
            errors.append("retarget is required for retarget_or_short_format")
        else:
            for name in ("venue_or_format", "why_fits"):
                if not _text(retarget.get(name)):
                    errors.append(f"retarget.{name} must be a non-empty string")
    elif choice == "freeze":
        freeze = value.get("freeze")
        if not isinstance(freeze, Mapping):
            errors.append("freeze is required for freeze")
        else:
            if _text(freeze.get("reason_class")) not in FREEZE_REASON_CLASSES:
                errors.append(
                    f"freeze.reason_class must be one of {sorted(FREEZE_REASON_CLASSES)}"
                )
            conditions = freeze.get("reopen_conditions")
            if not isinstance(conditions, list) or not conditions:
                errors.append("freeze.reopen_conditions must name at least one reopen condition")
            else:
                for index, item in enumerate(conditions):
                    if (
                        not isinstance(item, Mapping)
                        or _text(item.get("type")) not in REOPEN_BASIS_TYPES
                        or not _text(item.get("description"))
                    ):
                        errors.append(
                            f"freeze.reopen_conditions[{index}] needs a type "
                            f"({', '.join(sorted(REOPEN_BASIS_TYPES))}) and a description"
                        )
    return ValidationResult(not errors, tuple(errors))


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
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration < 0:
            errors.append("runtime.duration_seconds must be a non-negative number")
        exit_code = runtime.get("exit_code")
        if not isinstance(exit_code, int) or isinstance(exit_code, bool):
            errors.append("runtime.exit_code must be an integer")
        session_id = runtime.get("session_id")
        if session_id is not None and not _text(session_id):
            errors.append("runtime.session_id must be null or a non-empty string")
        hooks = runtime.get("hooks")
        if hooks is not None:
            if not isinstance(hooks, Mapping):
                errors.append("runtime.hooks must be an object")
            else:
                if hooks.get("schema_version") != "openlabs.hook_runtime.v1":
                    errors.append("runtime.hooks has an unsupported schema_version")
                events = hooks.get("events")
                if not isinstance(events, list) or any(
                    not isinstance(event, Mapping) for event in events
                ):
                    errors.append("runtime.hooks.events must be an array of objects")
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


# ---------------------------------------------------------------- reusable assets

TOOL_ASSET_KINDS = ("data_loader", "analysis", "figure", "pipeline")
TEXT_ASSET_KINDS = ("lesson", "negative_result")
ASSET_KINDS = TOOL_ASSET_KINDS + TEXT_ASSET_KINDS
ASSET_TEXT_LIMITS = {"title": 120, "summary": 240, "entrypoint": 240, "usage": 400}
ASSET_BODY_MAX_CHARS = 1_500


def _short_text(value: Any, name: str, errors: list[str], *, required: bool = True) -> None:
    text = _text(value)
    if not text:
        if required:
            errors.append(f"{name} must be a non-empty string")
        return
    limit = ASSET_TEXT_LIMITS.get(name)
    if limit and len(text) > limit:
        errors.append(f"{name} is longer than {limit} characters")
    if name in {"title", "summary"} and "\n" in text:
        errors.append(f"{name} must be one line")


def _string_list(value: Any, name: str, errors: list[str], *, required: bool) -> None:
    if value is None and not required:
        return
    if not isinstance(value, list) or any(not _text(item) for item in value):
        errors.append(f"{name} must be an array of non-empty strings")
    elif required and not value:
        errors.append(f"{name} must not be empty")


def validate_asset_proposal(value: Any) -> ValidationResult:
    """Structure of one ``asset_proposals[]`` entry of a topic retrospective.

    Tool kinds (data_loader, analysis, figure, pipeline) need ``source_paths``,
    ``entrypoint``, ``usage`` and a ``verification`` block naming the minimal
    command that was run and its hash-bound receipt. ``lesson`` needs a short
    ``body``; ``negative_result`` needs ``negative`` {question, attempted,
    why_failed, retry_when[]}. Whether the files are where they claim to be is
    checked at registration, not here.
    """

    if not isinstance(value, Mapping):
        return ValidationResult(False, ("asset proposal must be an object",))
    errors: list[str] = []
    kind = _text(value.get("kind"))
    if kind not in ASSET_KINDS:
        errors.append(f"kind must be one of {list(ASSET_KINDS)}")
    for name in ("title", "summary"):
        _short_text(value.get(name), name, errors)
    _string_list(value.get("domains"), "domains", errors, required=True)
    for name in ("data_sources", "methods"):
        _string_list(value.get(name), name, errors, required=False)
    requirements = value.get("requirements")
    if requirements is not None and not isinstance(requirements, (str, Mapping)):
        errors.append("requirements must be a string or an object")
    body = value.get("body")
    if body is not None and (not isinstance(body, str) or len(body) > ASSET_BODY_MAX_CHARS):
        errors.append(f"body must be a string of at most {ASSET_BODY_MAX_CHARS} characters")
    if kind in TOOL_ASSET_KINDS:
        _string_list(value.get("source_paths"), "source_paths", errors, required=True)
        for name in ("entrypoint", "usage"):
            _short_text(value.get(name), name, errors)
        verification = value.get("verification")
        if not isinstance(verification, Mapping):
            errors.append("verification is required for a tool asset (command and receipt)")
        else:
            if not _text(verification.get("command")):
                errors.append("verification.command must be a non-empty string")
            receipt = verification.get("receipt")
            if (
                not isinstance(receipt, Mapping)
                or not _text(receipt.get("path"))
                or not SHA256.fullmatch(_text(receipt.get("sha256")))
            ):
                errors.append("verification.receipt needs a path and a sha256")
    elif kind == "lesson":
        if not _text(body):
            errors.append("body is required for a lesson")
    elif kind == "negative_result":
        negative = value.get("negative")
        if not isinstance(negative, Mapping):
            errors.append("negative is required for a negative_result")
        else:
            for name in ("question", "attempted", "why_failed"):
                text = _text(negative.get(name))
                if not text:
                    errors.append(f"negative.{name} must be a non-empty string")
                elif len(text) > ASSET_BODY_MAX_CHARS:
                    errors.append(f"negative.{name} is longer than {ASSET_BODY_MAX_CHARS}")
            retry = negative.get("retry_when")
            if not isinstance(retry, list) or not retry:
                errors.append("negative.retry_when must name at least one condition")
            else:
                for index, item in enumerate(retry):
                    if (
                        not isinstance(item, Mapping)
                        or _text(item.get("type")) not in REOPEN_BASIS_TYPES
                        or not _text(item.get("description"))
                    ):
                        errors.append(
                            f"negative.retry_when[{index}] needs a type "
                            f"({', '.join(sorted(REOPEN_BASIS_TYPES))}) and a description"
                        )
    if kind in TEXT_ASSET_KINDS and value.get("source_paths"):
        _string_list(value.get("source_paths"), "source_paths", errors, required=False)
    supersedes = value.get("supersedes")
    if supersedes is not None and not _text(supersedes):
        errors.append("supersedes must be null or an asset_id")
    return ValidationResult(not errors, tuple(errors))
