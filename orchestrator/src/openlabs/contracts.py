"""Versioned file contracts shared by the control plane and isolated labs."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

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
    # Proposals, legacy topic_cards (backward compat for in-flight scouts) and independent
    # topic reviews are checked per item by the program controller.
    for field_name in ("topic_proposals", "topic_cards", "reviews"):
        items = payload.get(field_name)
        if items is not None and (
            not isinstance(items, list)
            or any(not isinstance(item, Mapping) for item in items)
        ):
            errors.append(f"{field_name} must be an array of objects")
    return ValidationResult(not errors, tuple(errors), tuple(warnings))


# ---------------------------------------------------------------- research program

TOPIC_PROPOSAL_SCHEMA = "openlabs.topic_proposal.v1"
MAX_BRIEF_CHARS = 6_000
DATA_ACCESS_METHODS = ("direct", "form_or_registration", "restricted")
REVIEW_VERDICTS = frozenset({"go", "no_go"})
LIKELY_BANDS = ("nc", "zone_1", "zone_2", "zones_3_4")
# Where a topic's experiments run (AGENTS.md, "Where computation runs").
COMPUTE_LOCATIONS = ("container_cpu", "container_gpu", "ailab", "wsl_math")
# Kept for legacy admitted topics that still carry admission_conditions and for
# direction-decision / retrospective reopen conditions.
ADMISSION_CONDITION_DUES = ("before_precheck", "before_decisive_analysis", "before_submission")
REOPEN_BASIS_TYPES = frozenset(
    {
        "new_data_source",
        "new_method",
        "venue_policy_change",
        "external_result",
        "line_environment_ready",
    }
)


def _nonnegative_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and value >= 0
    )


def preregistration_sha256(primary_endpoint: Any) -> str:
    """SHA-256 of the canonical JSON of a pre-registered primary-endpoint block."""

    return hashlib.sha256(canonical_json_bytes(primary_endpoint)).hexdigest()


def data_source_identifiers(data_sources: Any) -> list[str]:
    """Stable identifiers (id_or_url / catalog_id / doi / url / name) used by fingerprints."""

    identifiers: list[str] = []
    for item in data_sources if isinstance(data_sources, list) else []:
        if isinstance(item, Mapping):
            identifier = (
                _text(item.get("id_or_url"))
                or _text(item.get("catalog_id"))
                or _text(item.get("doi"))
                or _text(item.get("url"))
                or _text(item.get("name"))
            )
            if identifier:
                identifiers.append(identifier)
        elif isinstance(item, str) and item.strip():
            identifiers.append(item.strip())
    return identifiers


def compute_plan_locations(estimate_or_card: Any) -> tuple[str, ...]:
    """Experiment locations of a proposal's ``compute_estimate`` or legacy ``cost_estimate``."""

    if not isinstance(estimate_or_card, Mapping):
        return ()
    estimate = estimate_or_card.get("compute_estimate")
    if isinstance(estimate, Mapping) and isinstance(estimate.get("locations"), list):
        return tuple(str(item) for item in estimate["locations"] if isinstance(item, str))
    if isinstance(estimate_or_card.get("locations"), list):
        return tuple(str(item) for item in estimate_or_card["locations"] if isinstance(item, str))
    cost = estimate_or_card.get("cost_estimate")
    plan = (
        cost.get("compute_plan") if isinstance(cost, Mapping)
        else estimate_or_card.get("compute_plan")
    )
    locations = plan.get("locations") if isinstance(plan, Mapping) else None
    if not isinstance(locations, list):
        return ()
    return tuple(str(item) for item in locations if isinstance(item, str))


def validate_topic_proposal(proposal: Any) -> ValidationResult:
    """Minimal control-plane structural check of a topic proposal (6 machine fields)."""

    if not isinstance(proposal, Mapping):
        return ValidationResult(False, ("topic proposal must be a JSON object",))
    errors: list[str] = []
    schema = proposal.get("schema_version")
    if schema is not None and schema != TOPIC_PROPOSAL_SCHEMA:
        errors.append(f"schema_version must be {TOPIC_PROPOSAL_SCHEMA}")
    if not _text(proposal.get("question")):
        errors.append("question is missing")
    brief = proposal.get("brief")
    if not isinstance(brief, str) or not brief.strip():
        errors.append("brief is missing")
    elif len(brief) > MAX_BRIEF_CHARS:
        errors.append(f"brief exceeds {MAX_BRIEF_CHARS} characters")
    sources = proposal.get("data_sources")
    if not isinstance(sources, list) or not sources:
        errors.append("data_sources must be a non-empty array")
    else:
        for index, item in enumerate(sources):
            prefix = f"data_sources[{index}]"
            if not isinstance(item, Mapping):
                errors.append(f"{prefix} must be an object")
                continue
            if not _text(item.get("id_or_url")):
                errors.append(f"{prefix}.id_or_url is missing")
            access = _text(item.get("access"))
            if access not in DATA_ACCESS_METHODS:
                errors.append(
                    f"{prefix}.access must be one of {', '.join(DATA_ACCESS_METHODS)}"
                )
            for opt in ("catalog_id", "registration"):
                val = item.get(opt)
                if val is not None and not isinstance(val, str):
                    errors.append(f"{prefix}.{opt} must be a string when present")
    estimate = proposal.get("compute_estimate")
    if not isinstance(estimate, Mapping):
        errors.append("compute_estimate is missing (locations, data_gb, agent_hours)")
    else:
        locations = estimate.get("locations")
        if (
            not isinstance(locations, list)
            or not locations
            or any(not isinstance(item, str) or item not in COMPUTE_LOCATIONS
                   for item in locations)
            or len(set(locations)) != len(locations)
        ):
            errors.append(
                "compute_estimate.locations must be a non-empty list of distinct values from "
                + ", ".join(COMPUTE_LOCATIONS)
            )
        if not _nonnegative_number(estimate.get("data_gb")):
            errors.append("compute_estimate.data_gb must be a non-negative number")
        hours = estimate.get("agent_hours")
        if not _nonnegative_number(hours) or float(hours) <= 0:
            errors.append("compute_estimate.agent_hours must be a positive number")
    for opt in ("research_line", "queue_entry_id", "reopens"):
        val = proposal.get(opt)
        if val is not None and not _text(val):
            errors.append(f"{opt} must be null or a non-empty string")
    return ValidationResult(not errors, tuple(errors))


def _legacy_access(source: Mapping[str, Any]) -> tuple[str, str | None]:
    raw_access = source.get("access")
    registration = ""
    if isinstance(raw_access, Mapping):
        method = _text(raw_access.get("method"))
        registration = _text(raw_access.get("registration"))
    elif isinstance(raw_access, str):
        method = raw_access.strip()
    else:
        method = ""
    reg_field = source.get("needs_registration")
    if not registration:
        if isinstance(reg_field, str):
            registration = reg_field.strip()
        else:
            registration = _text(source.get("registration")) or _text(source.get("registration_note"))
    if method not in DATA_ACCESS_METHODS:
        method = "form_or_registration" if (reg_field or registration) else "direct"
    return method, (registration or None)


def _legacy_brief(card: Mapping[str, Any]) -> str:
    """Render a compact one-page Markdown brief from a legacy topic_card JSON."""

    parts: list[str] = []
    question = _text(card.get("question"))
    if question:
        parts.append(f"## 1. Research Question\n{question}")
    why_bits: list[str] = []
    nc_case = card.get("nc_case")
    if isinstance(nc_case, Mapping):
        for key in ("claim", "hook", "why_broad_audience"):
            if _text(nc_case.get(key)):
                why_bits.append(_text(nc_case.get(key)))
    audience = card.get("audience")
    if isinstance(audience, Mapping) and _text(audience.get("who")):
        why_bits.append(f"Audience: {_text(audience.get('who'))}")
    if why_bits:
        parts.append("## 2. Why It Matters\n" + "\n".join(why_bits))
    prior = card.get("closest_prior_work")
    if isinstance(prior, list) and prior:
        lines = []
        for item in prior[:5]:
            if isinstance(item, Mapping):
                cit = _text(item.get("citation")) or _text(item.get("title"))
                diff = _text(item.get("our_difference")) or _text(item.get("what_it_shows"))
                if cit or diff:
                    lines.append(f"- {cit}: {diff}" if cit and diff else f"- {cit or diff}")
        if lines:
            parts.append("## 3. Closest Prior Work & What Is New\n" + "\n".join(lines))
    sources = card.get("data_sources")
    if isinstance(sources, list) and sources:
        lines = []
        for item in sources:
            if isinstance(item, Mapping):
                ident = (_text(item.get("name")) or _text(item.get("id_or_url"))
                         or _text(item.get("doi")) or _text(item.get("url")))
                method, reg = _legacy_access(item)
                line = f"- {ident} ({method})"
                if reg:
                    line += f" — registration: {reg}"
                lines.append(line)
        if lines:
            parts.append("## 4. Data Sources & Access\n" + "\n".join(lines))
    decisive = card.get("decisive_analysis")
    precheck = card.get("feasibility_precheck")
    kill = card.get("kill_test")
    test_bits: list[str] = []
    if isinstance(kill, Mapping) and _text(kill.get("test") or kill.get("description")):
        test_bits.append(_text(kill.get("test") or kill.get("description")))
    if isinstance(precheck, Mapping) and _text(precheck.get("description")):
        test_bits.append(_text(precheck.get("description")))
    if isinstance(decisive, Mapping) and _text(decisive.get("description")):
        test_bits.append(_text(decisive.get("description")))
    if test_bits:
        parts.append("## 5. First Decisive Test (Kill Test)\n" + "\n".join(test_bits))
    stop_bits: list[str] = []
    if isinstance(kill, Mapping) and _text(kill.get("kill_criterion") or kill.get("stop_rule")):
        stop_bits.append(_text(kill.get("kill_criterion") or kill.get("stop_rule")))
    if isinstance(precheck, Mapping) and _text(precheck.get("pass_criterion")):
        stop_bits.append(f"Pass criterion: {_text(precheck.get('pass_criterion'))}")
    endpoint = card.get("primary_endpoint")
    if isinstance(endpoint, Mapping) and _text(endpoint.get("stop_rule")):
        stop_bits.append(_text(endpoint.get("stop_rule")))
    if stop_bits:
        parts.append("## 6. What Result Would Kill This Topic\n" + "\n".join(stop_bits))
    rendered = "\n\n".join(parts).strip() or question
    if len(rendered) > MAX_BRIEF_CHARS:
        rendered = rendered[: MAX_BRIEF_CHARS - 16].rstrip() + "\n...(truncated)"
    return rendered


def proposal_from_legacy_card(card: Mapping[str, Any]) -> dict[str, Any]:
    """Read-only adapter turning a legacy ``topic_card`` into a ``topic_proposal.v1`` view."""

    if isinstance(card.get("brief"), str) and card["brief"].strip() and isinstance(
        card.get("compute_estimate"), Mapping
    ):
        return dict(card)
    sources: list[dict[str, Any]] = []
    for item in card.get("data_sources") if isinstance(card.get("data_sources"), list) else []:
        if not isinstance(item, Mapping):
            continue
        ident = (
            _text(item.get("id_or_url"))
            or _text(item.get("doi"))
            or _text(item.get("url"))
            or _text(item.get("catalog_id"))
            or _text(item.get("name"))
        )
        method, reg = _legacy_access(item)
        entry: dict[str, Any] = {"id_or_url": ident, "access": method}
        if _text(item.get("catalog_id")):
            entry["catalog_id"] = _text(item.get("catalog_id"))
        if reg:
            entry["registration"] = reg
        if ident:
            sources.append(entry)
    locations = list(compute_plan_locations(card)) or ["container_cpu"]
    volume = card.get("data_volume") if isinstance(card.get("data_volume"), Mapping) else {}
    gb_candidates = [
        float(volume[key]) for key in ("download_gb", "storage_gb")
        if _nonnegative_number(volume.get(key))
    ]
    data_gb = max(gb_candidates) if gb_candidates else 0.0
    cost = card.get("cost_estimate") if isinstance(card.get("cost_estimate"), Mapping) else {}
    secs = cost.get("agent_seconds")
    agent_hours = (
        round(float(secs) / 3600.0, 2)
        if _nonnegative_number(secs) and float(secs) > 0
        else 12.0
    )
    queue_entry_id = _text(card.get("queue_entry_id")) or None
    if not queue_entry_id and isinstance(card.get("candidate_queue_entry"), Mapping):
        q = card["candidate_queue_entry"]
        queue_entry_id = _text(q.get("entry_id") or q.get("id") or q.get("batch_id")) or None
    proposal: dict[str, Any] = {
        "schema_version": TOPIC_PROPOSAL_SCHEMA,
        "question": _text(card.get("question")),
        "brief": _legacy_brief(card),
        "data_sources": sources,
        "compute_estimate": {
            "locations": locations,
            "data_gb": data_gb,
            "agent_hours": agent_hours,
        },
    }
    if _text(card.get("research_line")):
        proposal["research_line"] = _text(card.get("research_line"))
    if _text(card.get("domain")):
        proposal["domain"] = _text(card.get("domain"))
    if queue_entry_id:
        proposal["queue_entry_id"] = queue_entry_id
    if _text(card.get("reopens")):
        proposal["reopens"] = _text(card.get("reopens"))
    return proposal


def validate_topic_review(review: Any) -> ValidationResult:
    """Minimal check of one independent topic review entry (``reviews[]``)."""

    if not isinstance(review, Mapping):
        return ValidationResult(False, ("review must be an object",))
    errors: list[str] = []
    if not _text(review.get("topic_id")):
        errors.append("topic_id is missing")
    verdict = _text(review.get("verdict"))
    if verdict not in REVIEW_VERDICTS:
        errors.append(f"verdict must be one of {sorted(REVIEW_VERDICTS)}")
    if not _text(review.get("rationale")):
        errors.append("rationale is missing")
    band = review.get("likely_band")
    if band is not None and _text(band) not in LIKELY_BANDS:
        errors.append(f"likely_band must be null or one of {', '.join(LIKELY_BANDS)}")
    needs_reg = review.get("needs_registration")
    if needs_reg is not None:
        if not isinstance(needs_reg, list):
            errors.append("needs_registration must be an array")
        else:
            for index, item in enumerate(needs_reg):
                if not isinstance(item, Mapping) or not _text(item.get("source")):
                    errors.append(
                        f"needs_registration[{index}] must be an object with a non-empty source"
                    )
    return ValidationResult(not errors, tuple(errors))


def admission_conditions(admission: Any) -> list[dict[str, str]]:
    """Normalized conditions of a legacy admit (``[]`` for simplified topics or none)."""

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
FREEZE_REASON_CATEGORIES = (
    "data_access",
    "method_capability",
    "negative_result",
    "resources_exhausted",
)
FREEZE_REASON_CATEGORY_DEFINITIONS: dict[str, str] = {
    "data_access": (
        "Decisive dataset cannot be obtained: requires a free access form or registration "
        "(e.g. Living Planet Database 2026), is restricted/paywalled, or is a public release "
        "missing a required decisive field (e.g. Challenge-2021 Georgia missing patient-linkage "
        "map, or archive lacking point-in-time price vintages)."
    ),
    "method_capability": (
        "Solver, pipeline, or methodological limitation, or failure to reproduce a published "
        "baseline/control within tolerance (e.g. mandatory shared solver lacking recovery or "
        "spot+third-light support, uncalibrated conversion, or FEMTO/Paderborn baseline "
        "reproduction miss)."
    ),
    "negative_result": (
        "Analysis ran on available data and yielded a failed, null, negligible, inconclusive, "
        "or insufficient scientific result (e.g. primary endpoint failed, 95% CI spanning zero, "
        "negligible 0.002% effect below materiality threshold, contribution insufficient, or no "
        "eligible venue for the achieved result)."
    ),
    "resources_exhausted": (
        "Compute allocation, agent-time budget, calendar deadline, provider quota/pacing, "
        "review-round cap, or infrastructure capacity was exhausted before a decisive result "
        "could be reached (e.g. core-hour allocation exhausted, quota pacing halt, or review "
        "rounds exhausted)."
    ),
}
FREEZE_REASON_TO_CATEGORY: dict[str, str] = {
    # Four primary freeze classes (preferred for new freezes and direction decisions).
    "data_access": "data_access",
    "method_capability": "method_capability",
    "negative_result": "negative_result",
    "resources_exhausted": "resources_exhausted",
    # Existing granular reason codes kept for backward compatibility and mapped onto the four.
    "decisive_data_unavailable": "data_access",
    "feasibility_precheck_failed": "method_capability",
    "primary_endpoint_failed": "negative_result",
    "contribution_insufficient": "negative_result",
    "no_eligible_venue": "negative_result",
    "budget_exhausted": "resources_exhausted",
    "overdue": "resources_exhausted",
    "review_stalled": "resources_exhausted",
    "infrastructure": "resources_exhausted",
}
FREEZE_REASON_CLASSES = frozenset(FREEZE_REASON_TO_CATEGORY)


def freeze_reason_category(reason_class: Any) -> str | None:
    """Map a freeze reason code onto one of the four primary freeze classes (or None)."""

    return FREEZE_REASON_TO_CATEGORY.get(_text(reason_class))
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
            reason_class = _text(freeze.get("reason_class"))
            if reason_class not in FREEZE_REASON_CLASSES:
                errors.append(
                    "freeze.reason_class must be one of the four classes "
                    f"{list(FREEZE_REASON_CATEGORIES)} (or a mapped legacy code in "
                    f"{sorted(FREEZE_REASON_CLASSES)})"
                )
            elif freeze.get("reason_category") is not None:
                declared_category = _text(freeze.get("reason_category"))
                expected_category = freeze_reason_category(reason_class)
                if declared_category not in FREEZE_REASON_CATEGORIES:
                    errors.append(
                        f"freeze.reason_category must be one of {list(FREEZE_REASON_CATEGORIES)}"
                    )
                elif expected_category and declared_category != expected_category:
                    errors.append(
                        f"freeze.reason_category {declared_category!r} does not match "
                        f"freeze.reason_class {reason_class!r} (expected {expected_category!r})"
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
