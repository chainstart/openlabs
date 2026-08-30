#!/usr/bin/env python3
"""Config-driven mathematics research allocation and evidence state machine.

The script deliberately knows no named mathematical workflow.  Policies own
their stage graph, observation vocabulary, budgets, and task envelopes; agents
own the mathematical route and request evidence-backed transitions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

POLICY_SCHEMA = "openlabs.math_research_policy.v1"
BINDING_SCHEMA = "openlabs.math_research_policy_binding.v1"
STATE_SCHEMA = "openlabs.math_research_state.v1"
DECISION_SCHEMA = "openlabs.protocol_hook_decision.v1"
VALIDATION_CONTEXT_SCHEMA = "openlabs.protocol_validation_context.v1"
VALIDATION_CONTEXT_ENV = "OPENLABS_PROTOCOL_VALIDATION_CONTEXT"
IDENTIFIER = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$")
ROLES = {"researcher", "experimenter", "writer", "reviewer"}
SESSION_MODES = {"resume", "fresh"}
HANDOFF_KINDS = {
    "role_handoff",
    "text_revision",
    "evidence_remediation",
    "independent_replication",
    "adversarial_review",
    "portfolio_review",
    "route_reselection",
}
VERDICTS = {"accepted", "rejected", "inconclusive"}
STATUSES = {"active", "paused", "completed"}


class StateMachineError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StateMachineError(f"missing JSON file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise StateMachineError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise StateMachineError(f"JSON file must contain an object: {path}")
    return payload


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, ensure_ascii=False, indent=2, sort_keys=True)
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


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _identifier(value: Any, label: str, errors: list[str]) -> str:
    normalized = _text(value)
    if not IDENTIFIER.fullmatch(normalized):
        errors.append(f"{label} must be a stable identifier")
    return normalized


def _positive_int(value: Any, label: str, errors: list[str]) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        errors.append(f"{label} must be a positive integer")
        return None
    return value


def _safe_relative(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts


def _deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, Mapping) and isinstance(override, Mapping):
        merged = dict(base)
        for key, value in override.items():
            merged[str(key)] = _deep_merge(merged.get(str(key)), value)
        return merged
    return override


def _project_and_binding(project_path: Path) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    project = _read(project_path)
    domain_config = project.get("domain_config")
    if not isinstance(domain_config, Mapping) or not _text(domain_config.get("path")):
        raise StateMachineError("project requires domain_config.path for a research policy")
    binding_path = (project_path.parent / str(domain_config["path"])).resolve()
    binding = _read(binding_path)
    if binding.get("schema_version") != BINDING_SCHEMA:
        raise StateMachineError(f"domain config must use {BINDING_SCHEMA}")
    return project, binding_path, binding


def _load_policy(project_path: Path) -> tuple[dict[str, Any], dict[str, Any], str, Path]:
    project, binding_path, binding = _project_and_binding(project_path)
    configured = binding.get("policy")
    if not isinstance(configured, Mapping):
        raise StateMachineError("policy binding requires a policy object")
    profile = _text(configured.get("profile"))
    inline = configured.get("inline")
    if bool(profile) == bool(inline is not None):
        raise StateMachineError("policy must select exactly one of profile or inline")
    if profile:
        if not IDENTIFIER.fullmatch(profile):
            raise StateMachineError("policy profile must be a stable identifier")
        policy_path = Path(__file__).resolve().parents[1] / "policies" / f"{profile}.json"
        policy = _read(policy_path)
    else:
        if not isinstance(inline, Mapping):
            raise StateMachineError("inline policy must be an object")
        policy_path = binding_path
        policy = dict(inline)
    overrides = configured.get("overrides", {})
    if not isinstance(overrides, Mapping):
        raise StateMachineError("policy overrides must be an object")
    policy = _deep_merge(policy, overrides)
    errors = validate_policy(policy)
    if errors:
        raise StateMachineError("invalid research policy: " + "; ".join(errors))
    return project, policy, _canonical_digest(policy), policy_path


def _validate_condition(
    condition: Any,
    *,
    label: str,
    observation_types: Mapping[str, Any],
    errors: list[str],
) -> None:
    if not isinstance(condition, Mapping):
        errors.append(f"{label} must be an object")
        return
    kind = _identifier(condition.get("kind"), f"{label}.kind", errors)
    if kind and kind not in observation_types:
        errors.append(f"{label}.kind is not declared by observation_types")
    verdict = _text(condition.get("verdict") or "accepted")
    if verdict not in VERDICTS:
        errors.append(f"{label}.verdict must be accepted, rejected, or inconclusive")
    actor_role = condition.get("actor_role")
    if actor_role is not None and _text(actor_role) not in ROLES:
        errors.append(f"{label}.actor_role is invalid")
    if condition.get("min_count") is not None:
        _positive_int(condition.get("min_count"), f"{label}.min_count", errors)
    if not isinstance(condition.get("distinct_source_tasks", False), bool):
        errors.append(f"{label}.distinct_source_tasks must be boolean")


def validate_policy(policy: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(policy, Mapping):
        return ["policy must be an object"]
    if policy.get("schema_version") != POLICY_SCHEMA:
        errors.append(f"schema_version must be {POLICY_SCHEMA}")
    _identifier(policy.get("policy_id"), "policy_id", errors)
    if not _text(policy.get("description")):
        errors.append("description is required")
    initial_stage = _identifier(policy.get("initial_stage"), "initial_stage", errors)
    observation_types = policy.get("observation_types")
    if not isinstance(observation_types, Mapping):
        errors.append("observation_types must be an object")
        observation_types = {}
    for raw_kind, raw_spec in observation_types.items():
        kind = _identifier(raw_kind, "observation_types key", errors)
        if not isinstance(raw_spec, Mapping):
            errors.append(f"observation_types.{kind} must be an object")
            continue
        if not _text(raw_spec.get("description")):
            errors.append(f"observation_types.{kind}.description is required")
        if not isinstance(raw_spec.get("evidence_required", True), bool):
            errors.append(f"observation_types.{kind}.evidence_required must be boolean")
    stages = policy.get("stages")
    if not isinstance(stages, Mapping) or not stages:
        errors.append("stages must be a non-empty object")
        return errors
    stage_ids: set[str] = set()
    for raw_stage in stages:
        stage_ids.add(_identifier(raw_stage, "stages key", errors))
    if initial_stage and initial_stage not in stage_ids:
        errors.append("initial_stage is not declared in stages")
    for raw_stage, raw_spec in stages.items():
        stage = str(raw_stage)
        label = f"stages.{stage}"
        if not isinstance(raw_spec, Mapping):
            errors.append(f"{label} must be an object")
            continue
        terminal = raw_spec.get("terminal", False)
        if not isinstance(terminal, bool):
            errors.append(f"{label}.terminal must be boolean")
            terminal = False
        if not _text(raw_spec.get("description")):
            errors.append(f"{label}.description is required")
        if terminal:
            if raw_spec.get("task") is not None:
                errors.append(f"{label} terminal stages cannot define a task")
            if _text(raw_spec.get("completion")) not in {"paused", "completed"}:
                errors.append(f"{label}.completion must be paused or completed")
        else:
            task = raw_spec.get("task")
            if not isinstance(task, Mapping):
                errors.append(f"{label}.task must be an object")
            else:
                if not _text(task.get("objective")):
                    errors.append(f"{label}.task.objective is required")
                if _text(task.get("agent_role")) not in ROLES:
                    errors.append(f"{label}.task.agent_role is invalid")
                if _text(task.get("session_mode")) not in SESSION_MODES:
                    errors.append(f"{label}.task.session_mode is invalid")
                if _text(task.get("handoff_kind")) not in HANDOFF_KINDS:
                    errors.append(f"{label}.task.handoff_kind is invalid")
                _identifier(task.get("runner"), f"{label}.task.runner", errors)
                _positive_int(task.get("wall_seconds"), f"{label}.task.wall_seconds", errors)
                resources = task.get("resources")
                if resources is not None:
                    if not isinstance(resources, Mapping):
                        errors.append(f"{label}.task.resources must be an object")
                    else:
                        for key in ("cpu_threads", "memory_mib", "scratch_mib"):
                            _positive_int(
                                resources.get(key),
                                f"{label}.task.resources.{key}",
                                errors,
                            )
            budget = raw_spec.get("budget", {})
            if not isinstance(budget, Mapping):
                errors.append(f"{label}.budget must be an object")
            else:
                for key in ("max_tasks", "max_agent_seconds"):
                    if budget.get(key) is not None:
                        _positive_int(budget.get(key), f"{label}.budget.{key}", errors)
                if _text(budget.get("on_exhaustion") or "defer") not in {
                    "pause",
                    "defer",
                    "default",
                }:
                    errors.append(
                        f"{label}.budget.on_exhaustion must be pause, defer, or default"
                    )
        transitions = raw_spec.get("transitions", [])
        if not isinstance(transitions, list):
            errors.append(f"{label}.transitions must be an array")
            continue
        targets: set[str] = set()
        for index, transition in enumerate(transitions):
            prefix = f"{label}.transitions[{index}]"
            if not isinstance(transition, Mapping):
                errors.append(f"{prefix} must be an object")
                continue
            target = _identifier(transition.get("to"), f"{prefix}.to", errors)
            if target and target not in stage_ids:
                errors.append(f"{prefix}.to is not a declared stage")
            if target in targets:
                errors.append(f"{label} has duplicate transition to {target}")
            targets.add(target)
            requires = transition.get("requires", {})
            if not isinstance(requires, Mapping):
                errors.append(f"{prefix}.requires must be an object")
                continue
            for group in ("all", "any"):
                conditions = requires.get(group, [])
                if not isinstance(conditions, list):
                    errors.append(f"{prefix}.requires.{group} must be an array")
                    continue
                for condition_index, condition in enumerate(conditions):
                    _validate_condition(
                        condition,
                        label=f"{prefix}.requires.{group}[{condition_index}]",
                        observation_types=observation_types,
                        errors=errors,
                    )
    portfolio = policy.get("portfolio", {})
    if not isinstance(portfolio, Mapping):
        errors.append("portfolio must be an object")
    else:
        concurrency = portfolio.get("max_concurrent_tasks_by_stage", {})
        if not isinstance(concurrency, Mapping):
            errors.append("portfolio.max_concurrent_tasks_by_stage must be an object")
        else:
            for configured_stage, limit in concurrency.items():
                if str(configured_stage) not in stage_ids:
                    errors.append(
                        "portfolio.max_concurrent_tasks_by_stage contains an unknown stage"
                    )
                _positive_int(
                    limit,
                    f"portfolio.max_concurrent_tasks_by_stage.{configured_stage}",
                    errors,
                )
    return errors


def _condition_matches(observations: list[Mapping[str, Any]], condition: Mapping[str, Any]) -> bool:
    kind = _text(condition.get("kind"))
    verdict = _text(condition.get("verdict") or "accepted")
    actor_role = _text(condition.get("actor_role"))
    minimum = int(condition.get("min_count") or 1)
    matches = [
        item
        for item in observations
        if _text(item.get("kind")) == kind
        and _text(item.get("verdict")) == verdict
        and (not actor_role or _text(item.get("actor_role")) == actor_role)
    ]
    if condition.get("distinct_source_tasks") is True:
        return len({_text(item.get("source_task_id")) for item in matches}) >= minimum
    return len(matches) >= minimum


def _requirements_pass(
    requirements: Mapping[str, Any],
    observations: list[Mapping[str, Any]],
) -> bool:
    all_conditions = requirements.get("all", [])
    any_conditions = requirements.get("any", [])
    return all(_condition_matches(observations, item) for item in all_conditions) and (
        not any_conditions
        or any(_condition_matches(observations, item) for item in any_conditions)
    )


def _transition_spec(
    policy: Mapping[str, Any],
    source: str,
    target: str,
) -> Mapping[str, Any] | None:
    stage = policy["stages"][source]
    return next(
        (
            item
            for item in stage.get("transitions", [])
            if isinstance(item, Mapping) and _text(item.get("to")) == target
        ),
        None,
    )


def validate_state(
    project: Mapping[str, Any],
    state: Any,
    policy: Mapping[str, Any],
    policy_digest: str,
    *,
    state_path: Path,
    require_evidence_files: bool,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(state, Mapping):
        return ["workstream state must be an object"]
    if state.get("schema_version") != STATE_SCHEMA:
        errors.append(f"schema_version must be {STATE_SCHEMA}")
    if _text(state.get("project_id")) != _text(project.get("project_id")):
        errors.append("state project_id does not match project")
    workstream_id = _identifier(state.get("workstream_id"), "workstream_id", errors)
    configured_ids = {
        _text(item.get("workstream_id"))
        for item in project.get("workstreams", [])
        if isinstance(item, Mapping)
    }
    if workstream_id and workstream_id not in configured_ids:
        errors.append("state workstream_id is not declared by project")
    if _text(state.get("policy_id")) != _text(policy.get("policy_id")):
        errors.append("state policy_id does not match bound policy")
    if _text(state.get("policy_digest")) != policy_digest:
        errors.append("state policy_digest does not match the bound policy")
    status = _text(state.get("status"))
    if status not in STATUSES:
        errors.append("status must be active, paused, or completed")
    stage = _text(state.get("stage"))
    stages = policy.get("stages", {})
    if stage not in stages:
        errors.append("state stage is not declared by policy")
    observations_value = state.get("observations")
    if not isinstance(observations_value, list):
        errors.append("observations must be an array")
        observations_value = []
    observations: list[Mapping[str, Any]] = []
    observation_by_id: dict[str, Mapping[str, Any]] = {}
    observation_types = policy.get("observation_types", {})
    for index, item in enumerate(observations_value):
        prefix = f"observations[{index}]"
        if not isinstance(item, Mapping):
            errors.append(f"{prefix} must be an object")
            continue
        observation_id = _identifier(item.get("observation_id"), f"{prefix}.observation_id", errors)
        if observation_id in observation_by_id:
            errors.append(f"duplicate observation_id: {observation_id}")
        kind = _identifier(item.get("kind"), f"{prefix}.kind", errors)
        if kind and kind not in observation_types:
            errors.append(f"{prefix}.kind is not declared by policy")
        if _text(item.get("verdict")) not in VERDICTS:
            errors.append(f"{prefix}.verdict is invalid")
        if _text(item.get("actor_role")) not in ROLES:
            errors.append(f"{prefix}.actor_role is invalid")
        _identifier(item.get("source_task_id"), f"{prefix}.source_task_id", errors)
        if _text(item.get("stage")) not in stages:
            errors.append(f"{prefix}.stage is invalid")
        if not _text(item.get("summary")):
            errors.append(f"{prefix}.summary is required")
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or any(
            not _safe_relative(_text(path)) for path in evidence
        ):
            errors.append(f"{prefix}.evidence must be an array of safe relative paths")
            evidence = []
        spec = observation_types.get(kind, {})
        if isinstance(spec, Mapping) and spec.get("evidence_required", True) and not evidence:
            errors.append(f"{prefix} requires evidence")
        if require_evidence_files:
            for relative in evidence:
                if not (state_path.parent / str(relative)).resolve().is_file():
                    errors.append(f"{prefix}.evidence is missing: {relative}")
        if observation_id:
            observation_by_id[observation_id] = item
        observations.append(item)
    transitions_value = state.get("transitions")
    if not isinstance(transitions_value, list):
        errors.append("transitions must be an array")
        transitions_value = []
    derived_stage = _text(policy.get("initial_stage"))
    for index, item in enumerate(transitions_value):
        prefix = f"transitions[{index}]"
        if not isinstance(item, Mapping):
            errors.append(f"{prefix} must be an object")
            continue
        source = _text(item.get("from"))
        target = _text(item.get("to"))
        if source != derived_stage:
            errors.append(f"{prefix}.from does not follow the prior transition")
        spec = _transition_spec(policy, source, target) if source in stages else None
        if spec is None:
            errors.append(f"{prefix} is not allowed by policy")
        selected_ids = item.get("observation_ids")
        if not isinstance(selected_ids, list) or any(
            not _text(observation_id) for observation_id in selected_ids
        ):
            errors.append(f"{prefix}.observation_ids must be a string array")
            selected_ids = []
        elif len(set(selected_ids)) != len(selected_ids):
            errors.append(f"{prefix}.observation_ids must be unique")
        selected = [
            observation_by_id[observation_id]
            for observation_id in selected_ids
            if observation_id in observation_by_id
        ]
        if len(selected) != len(selected_ids):
            errors.append(f"{prefix} references an unknown observation")
        if any(_text(observation.get("stage")) != source for observation in selected):
            errors.append(f"{prefix} references evidence from a different stage")
        if spec is not None and not _requirements_pass(spec.get("requires", {}), selected):
            errors.append(f"{prefix} does not satisfy its configured evidence gate")
        if not _text(item.get("reason")):
            errors.append(f"{prefix}.reason is required")
        derived_stage = target
    if stage and derived_stage != stage:
        errors.append("state stage does not match its transition history")
    if stage in stages:
        stage_spec = stages[stage]
        terminal = stage_spec.get("terminal", False) is True
        expected_status = _text(stage_spec.get("completion")) if terminal else "active"
        if terminal and status != expected_status:
            errors.append("terminal stage status does not match policy completion")
        if not terminal and status == "completed":
            errors.append("a nonterminal stage cannot have completed status")
    for field in (
        "research_log",
        "verification_receipts",
        "dispositions",
        "policy_rebindings",
    ):
        if not isinstance(state.get(field), list):
            errors.append(f"{field} must be an array")
    receipts = state.get("verification_receipts", [])
    if isinstance(receipts, list) and any(not _safe_relative(_text(item)) for item in receipts):
        errors.append("verification_receipts must contain safe relative paths")
    return errors


def _load_validated(
    project_path: Path,
    state_path: Path,
    *,
    require_evidence_files: bool,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    project, policy, digest, _policy_path = _load_policy(project_path)
    state = _read(state_path)
    errors = validate_state(
        project,
        state,
        policy,
        digest,
        state_path=state_path,
        require_evidence_files=require_evidence_files,
    )
    if errors:
        raise StateMachineError("invalid workstream state: " + "; ".join(errors))
    return project, state, policy, digest


def _validation_context() -> Mapping[str, Any] | None:
    raw = os.environ.get(VALIDATION_CONTEXT_ENV, "").strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StateMachineError(f"invalid protocol validation context: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise StateMachineError("protocol validation context must be an object")
    if payload.get("schema_version") != VALIDATION_CONTEXT_SCHEMA:
        raise StateMachineError("unsupported protocol validation context")
    if payload.get("event") != "attempt_commit":
        raise StateMachineError("unsupported protocol validation event")
    return payload


def _appended_items(
    canonical: Mapping[str, Any],
    candidate: Mapping[str, Any],
    field: str,
    errors: list[str],
) -> list[Any]:
    old_items = canonical.get(field)
    new_items = candidate.get(field)
    if not isinstance(old_items, list) or not isinstance(new_items, list):
        errors.append(f"attempt delta requires array field {field}")
        return []
    if len(new_items) < len(old_items) or new_items[: len(old_items)] != old_items:
        errors.append(f"attempt rewrote immutable {field} history")
        return []
    return new_items[len(old_items) :]


def _session_matches(configured: str, actual: str) -> bool:
    return configured == actual or (configured == "resume" and actual == "fresh")


def _attempt_delta_errors(
    project: Mapping[str, Any],
    state: Mapping[str, Any],
    policy: Mapping[str, Any],
    policy_digest: str,
    *,
    state_path: Path,
) -> list[str]:
    context = _validation_context()
    if context is None:
        return []
    errors: list[str] = []
    task = context.get("task")
    canonical_value = context.get("canonical")
    if not isinstance(task, Mapping) or not isinstance(canonical_value, Mapping):
        return ["protocol validation context requires task and canonical objects"]
    task_id = _text(task.get("task_id"))
    attempt_id = _text(task.get("attempt_id"))
    task_role = _text(task.get("agent_role"))
    task_session = _text(task.get("session_mode"))
    routing_reason = _text(task.get("routing_reason"))
    if not IDENTIFIER.fullmatch(task_id):
        errors.append("validation task_id must be a stable identifier")
    if not IDENTIFIER.fullmatch(attempt_id):
        errors.append("validation attempt_id must be a stable identifier")
    if task_role not in ROLES:
        errors.append("validation agent_role is invalid")
    if task_session not in SESSION_MODES:
        errors.append("validation session_mode is invalid")
    if not IDENTIFIER.fullmatch(routing_reason):
        errors.append("validation routing_reason must be a stable identifier")
    canonical_project_value = _text(canonical_value.get("project_config"))
    canonical_project_path = Path(canonical_project_value).expanduser()
    if not canonical_project_value or not canonical_project_path.is_absolute():
        errors.append("validation canonical project_config must be absolute")
    canonical_state_value = _text(canonical_value.get("workstream_state"))
    canonical_state_path = Path(canonical_state_value).expanduser()
    if not canonical_state_value or not canonical_state_path.is_absolute():
        errors.append("validation canonical workstream_state must be absolute")
        return errors
    canonical_state_path = canonical_state_path.resolve()
    if canonical_state_path == state_path.resolve():
        errors.append("attempt validation requires distinct canonical and staged state paths")
        return errors
    try:
        canonical = _read(canonical_state_path)
    except StateMachineError as exc:
        errors.append(str(exc))
        return errors
    canonical_errors = validate_state(
        project,
        canonical,
        policy,
        policy_digest,
        state_path=canonical_state_path,
        require_evidence_files=True,
    )
    errors.extend(f"canonical state: {item}" for item in canonical_errors)
    if canonical_errors:
        return errors
    for field in (
        "schema_version",
        "project_id",
        "workstream_id",
        "policy_id",
        "policy_digest",
        "created_at",
    ):
        if state.get(field) != canonical.get(field):
            errors.append(f"attempt changed immutable state field {field}")
    appended = {
        field: _appended_items(canonical, state, field, errors)
        for field in (
            "observations",
            "transitions",
            "research_log",
            "verification_receipts",
            "dispositions",
            "policy_rebindings",
        )
    }
    if appended["policy_rebindings"]:
        errors.append("research attempts cannot rebind their allocation policy")
    new_observations = appended["observations"]
    new_transitions = appended["transitions"]
    new_dispositions = appended["dispositions"]
    scientific_change = bool(
        new_observations
        or new_transitions
        or new_dispositions
        or state.get("stage") != canonical.get("stage")
        or state.get("status") != canonical.get("status")
    )
    expected_routing = f"protocol_hook:{policy['policy_id']}:{canonical['stage']}"
    if scientific_change and routing_reason != expected_routing:
        errors.append(
            "attempt routing does not match the canonical configured mathematics stage"
        )
    stages = policy["stages"]

    def envelope(stage_id: str) -> Mapping[str, Any] | None:
        stage_spec = stages.get(stage_id)
        task_spec = stage_spec.get("task") if isinstance(stage_spec, Mapping) else None
        return task_spec if isinstance(task_spec, Mapping) else None

    entered_boundaries: set[str] = set()
    for index, transition in enumerate(new_transitions):
        if not isinstance(transition, Mapping):
            continue
        source = _text(transition.get("from"))
        source_task = envelope(source)
        if source_task is None:
            errors.append(f"new transition {index} starts from a terminal stage")
            continue
        if _text(source_task.get("agent_role")) != task_role or not _session_matches(
            _text(source_task.get("session_mode")), task_session
        ):
            errors.append(f"new transition {index} crosses its scheduled task envelope")
        if source in entered_boundaries:
            errors.append(f"new transition {index} crossed a fresh role/session boundary")
        target = _text(transition.get("to"))
        target_task = envelope(target)
        if target_task is not None and (
            _text(target_task.get("agent_role")) != task_role
            or _text(target_task.get("session_mode")) == "fresh"
        ):
            entered_boundaries.add(target)
    for index, observation in enumerate(new_observations):
        if not isinstance(observation, Mapping):
            continue
        if _text(observation.get("source_task_id")) != task_id:
            errors.append(f"new observation {index} is not bound to the current task_id")
        if _text(observation.get("actor_role")) != task_role:
            errors.append(f"new observation {index} is not bound to the current agent role")
        observation_stage = _text(observation.get("stage"))
        stage_task = envelope(observation_stage)
        if stage_task is None or _text(stage_task.get("agent_role")) != task_role:
            errors.append(f"new observation {index} crosses its configured role boundary")
        elif not _session_matches(_text(stage_task.get("session_mode")), task_session):
            errors.append(f"new observation {index} crosses its configured session boundary")
        if observation_stage in entered_boundaries:
            errors.append(f"new observation {index} was recorded beyond a fresh boundary")
    for index, disposition in enumerate(new_dispositions):
        decision = _text(disposition.get("decision")) if isinstance(disposition, Mapping) else ""
        if decision != "paused_by_research_agent":
            errors.append(f"new disposition {index} is reserved for control-plane action")
    if canonical.get("status") != "active" and scientific_change:
        errors.append("an inactive canonical workstream cannot be changed by a research task")
    terminal_pause = bool(
        new_transitions
        and isinstance(new_transitions[-1], Mapping)
        and isinstance(stages.get(_text(new_transitions[-1].get("to"))), Mapping)
        and stages[_text(new_transitions[-1].get("to"))].get("terminal") is True
        and stages[_text(new_transitions[-1].get("to"))].get("completion") == "paused"
    )
    agent_pause = any(
        isinstance(item, Mapping) and item.get("decision") == "paused_by_research_agent"
        for item in new_dispositions
    )
    if canonical.get("status") == "active" and state.get("status") == "paused":
        if not terminal_pause and not agent_pause:
            errors.append("attempt paused without a terminal transition or pause disposition")
    if agent_pause and state.get("status") != "paused":
        errors.append("pause disposition requires paused workstream status")
    if new_transitions:
        last_transition = new_transitions[-1]
        expected_entered_at = (
            _text(last_transition.get("created_at"))
            if isinstance(last_transition, Mapping)
            else ""
        )
        if state.get("stage_entered_at") != expected_entered_at:
            errors.append("stage_entered_at must match the final appended transition")
    elif state.get("stage_entered_at") != canonical.get("stage_entered_at"):
        errors.append("attempt changed stage_entered_at without a transition")
    return errors


def _validate_command(args: argparse.Namespace) -> int:
    try:
        project, policy, digest, _policy_path = _load_policy(args.project)
        state = _read(args.workstream)
        errors = validate_state(
            project,
            state,
            policy,
            digest,
            state_path=args.workstream,
            require_evidence_files=True,
        )
        if not errors and args.mode == "commit":
            errors.extend(
                _attempt_delta_errors(
                    project,
                    state,
                    policy,
                    digest,
                    state_path=args.workstream,
                )
            )
    except StateMachineError as exc:
        errors = [str(exc)]
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False))
    return 0 if not errors else 1


def _init_command(args: argparse.Namespace) -> int:
    if args.workstream.exists():
        raise StateMachineError(f"workstream state already exists: {args.workstream}")
    project, policy, digest, _policy_path = _load_policy(args.project)
    workstream_id = _text(args.workstream_id)
    if not IDENTIFIER.fullmatch(workstream_id):
        raise StateMachineError("workstream-id must be a stable identifier")
    configured = {
        _text(item.get("workstream_id"))
        for item in project.get("workstreams", [])
        if isinstance(item, Mapping)
    }
    if workstream_id not in configured:
        raise StateMachineError("workstream-id is not declared by project")
    now = _utc_now()
    state = {
        "schema_version": STATE_SCHEMA,
        "project_id": project["project_id"],
        "workstream_id": workstream_id,
        "policy_id": policy["policy_id"],
        "policy_digest": digest,
        "status": "active",
        "stage": policy["initial_stage"],
        "stage_entered_at": now,
        "observations": [],
        "transitions": [],
        "research_log": [],
        "verification_receipts": [],
        "dispositions": [],
        "policy_rebindings": [],
        "created_at": now,
        "updated_at": now,
    }
    _write(args.workstream, state)
    print(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _observe_command(args: argparse.Namespace) -> int:
    _project, state, policy, _digest = _load_validated(
        args.project,
        args.workstream,
        require_evidence_files=True,
    )
    if state["status"] != "active":
        raise StateMachineError("cannot record an observation in an inactive workstream")
    if args.kind not in policy["observation_types"]:
        raise StateMachineError(f"observation kind is not declared by policy: {args.kind}")
    if args.verdict not in VERDICTS:
        raise StateMachineError("verdict must be accepted, rejected, or inconclusive")
    if args.actor_role not in ROLES:
        raise StateMachineError("actor-role is invalid")
    if not IDENTIFIER.fullmatch(args.observation_id):
        raise StateMachineError("observation-id must be a stable identifier")
    if not IDENTIFIER.fullmatch(args.source_task_id):
        raise StateMachineError("source-task-id must be a stable identifier")
    if any(
        item.get("observation_id") == args.observation_id for item in state["observations"]
    ):
        raise StateMachineError(f"duplicate observation-id: {args.observation_id}")
    evidence = list(args.evidence or [])
    if any(not _safe_relative(item) for item in evidence):
        raise StateMachineError("evidence paths must be safe and relative to the workstream")
    for relative in evidence:
        if not (args.workstream.parent / relative).resolve().is_file():
            raise StateMachineError(f"evidence file does not exist: {relative}")
    spec = policy["observation_types"][args.kind]
    if spec.get("evidence_required", True) and not evidence:
        raise StateMachineError(f"observation {args.kind} requires evidence")
    observation = {
        "observation_id": args.observation_id,
        "kind": args.kind,
        "verdict": args.verdict,
        "actor_role": args.actor_role,
        "source_task_id": args.source_task_id,
        "stage": state["stage"],
        "summary": args.summary.strip(),
        "evidence": evidence,
        "created_at": _utc_now(),
    }
    if not observation["summary"]:
        raise StateMachineError("summary is required")
    state["observations"].append(observation)
    state["updated_at"] = _utc_now()
    _write(args.workstream, state)
    print(json.dumps(observation, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _transition_command(args: argparse.Namespace) -> int:
    _project, state, policy, _digest = _load_validated(
        args.project,
        args.workstream,
        require_evidence_files=True,
    )
    if state["status"] != "active":
        raise StateMachineError("cannot transition an inactive workstream")
    source = state["stage"]
    spec = _transition_spec(policy, source, args.to)
    if spec is None:
        raise StateMachineError(f"policy does not allow transition {source} -> {args.to}")
    selected_ids = list(dict.fromkeys(args.observation or []))
    by_id = {item["observation_id"]: item for item in state["observations"]}
    missing = [item for item in selected_ids if item not in by_id]
    if missing:
        raise StateMachineError("unknown observations: " + ", ".join(missing))
    selected = [by_id[item] for item in selected_ids]
    if any(item["stage"] != source for item in selected):
        raise StateMachineError("transition evidence must come from the current stage")
    if not _requirements_pass(spec.get("requires", {}), selected):
        raise StateMachineError("configured evidence gate did not pass")
    now = _utc_now()
    transition = {
        "from": source,
        "to": args.to,
        "reason": args.reason.strip(),
        "observation_ids": selected_ids,
        "created_at": now,
    }
    if not transition["reason"]:
        raise StateMachineError("transition reason is required")
    state["transitions"].append(transition)
    state["stage"] = args.to
    state["stage_entered_at"] = now
    target = policy["stages"][args.to]
    if target.get("terminal", False) is True:
        state["status"] = target["completion"]
    state["updated_at"] = now
    _write(args.workstream, state)
    print(json.dumps(transition, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _pause_command(args: argparse.Namespace) -> int:
    _project, state, _policy, _digest = _load_validated(
        args.project,
        args.workstream,
        require_evidence_files=True,
    )
    if state["status"] != "active":
        raise StateMachineError("workstream is already inactive")
    reason = args.reason.strip()
    if not reason:
        raise StateMachineError("pause reason is required")
    now = _utc_now()
    state["status"] = "paused"
    state["dispositions"].append(
        {"decision": "paused_by_research_agent", "reason": reason, "created_at": now}
    )
    state["updated_at"] = now
    _write(args.workstream, state)
    print(json.dumps(state["dispositions"][-1], ensure_ascii=False, indent=2))
    return 0


def _resume_command(args: argparse.Namespace) -> int:
    _project, state, policy, _digest = _load_validated(
        args.project,
        args.workstream,
        require_evidence_files=True,
    )
    if state["status"] != "paused":
        raise StateMachineError("only a paused workstream can be resumed")
    if policy["stages"][state["stage"]].get("terminal", False) is True:
        raise StateMachineError("a terminal stage requires an explicit state migration")
    reason = args.reason.strip()
    if not reason:
        raise StateMachineError("resume reason is required")
    now = _utc_now()
    state["status"] = "active"
    state["dispositions"].append(
        {"decision": "resumed", "reason": reason, "created_at": now}
    )
    state["updated_at"] = now
    _write(args.workstream, state)
    print(json.dumps(state["dispositions"][-1], ensure_ascii=False, indent=2))
    return 0


def _rebind_command(args: argparse.Namespace) -> int:
    project, policy, new_digest, _policy_path = _load_policy(args.project)
    state = _read(args.workstream)
    old_digest = _text(state.get("policy_digest"))
    if old_digest != args.expected_old_digest:
        raise StateMachineError("expected-old-digest does not match workstream state")
    if _text(state.get("policy_id")) != _text(policy.get("policy_id")):
        raise StateMachineError("rebind cannot change policy_id; use an explicit state migration")
    reason = args.reason.strip()
    if not reason:
        raise StateMachineError("rebind reason is required")
    candidate = dict(state)
    candidate["policy_digest"] = new_digest
    candidate.setdefault("policy_rebindings", [])
    now = _utc_now()
    candidate["policy_rebindings"] = [
        *candidate["policy_rebindings"],
        {
            "old_digest": old_digest,
            "new_digest": new_digest,
            "reason": reason,
            "created_at": now,
        },
    ]
    candidate["updated_at"] = now
    errors = validate_state(
        project,
        candidate,
        policy,
        new_digest,
        state_path=args.workstream,
        require_evidence_files=True,
    )
    if errors:
        raise StateMachineError(
            "new policy is incompatible with existing state: " + "; ".join(errors)
        )
    _write(args.workstream, candidate)
    print(json.dumps(candidate["policy_rebindings"][-1], ensure_ascii=False, indent=2))
    return 0


def _decision_command(args: argparse.Namespace) -> int:
    _project, state, policy, _digest = _load_validated(
        args.project,
        args.workstream,
        require_evidence_files=True,
    )
    try:
        context = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise StateMachineError(f"invalid hook context: {exc}") from exc
    if not isinstance(context, Mapping) or context.get("schema_version") != (
        "openlabs.protocol_hook_context.v1"
    ):
        raise StateMachineError("unsupported hook context")
    if context.get("event") != "continuation":
        raise StateMachineError("research state machine only handles continuation events")
    if state["status"] != "active":
        decision = {
            "schema_version": DECISION_SCHEMA,
            "decision": "pause",
            "reason": f"math_workstream_{state['status']}",
        }
        print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
        return 0
    stage_id = state["stage"]
    stage = policy["stages"][stage_id]
    if stage.get("terminal", False) is True:
        decision = {
            "schema_version": DECISION_SCHEMA,
            "decision": "pause",
            "reason": f"math_terminal_stage:{stage_id}",
        }
        print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
        return 0
    routing_key = f"{policy['policy_id']}:{stage_id}"
    stored_routing_key = f"protocol_hook:{routing_key}"
    portfolio = policy.get("portfolio", {})
    concurrency = (
        portfolio.get("max_concurrent_tasks_by_stage", {})
        if isinstance(portfolio, Mapping)
        else {}
    )
    concurrency_limit = (
        concurrency.get(stage_id) if isinstance(concurrency, Mapping) else None
    )
    if isinstance(concurrency_limit, int):
        active_peers = 0
        peers = context.get("project_workstreams", [])
        if not isinstance(peers, list):
            raise StateMachineError("hook project_workstreams must be an array")
        for peer in peers:
            if not isinstance(peer, Mapping):
                raise StateMachineError("hook project_workstreams entries must be objects")
            if _text(peer.get("campaign_id")) == _text(state.get("workstream_id")):
                continue
            if not (peer.get("has_active_tasks") is True or peer.get("has_queued_tasks") is True):
                continue
            peer_state_value = _text(peer.get("workstream_state_path"))
            if not peer_state_value:
                continue
            peer_state = _read(Path(peer_state_value).expanduser().resolve())
            if (
                _text(peer_state.get("policy_id")) == _text(policy.get("policy_id"))
                and _text(peer_state.get("stage")) == stage_id
                and _text(peer_state.get("status")) == "active"
            ):
                active_peers += 1
        if active_peers >= concurrency_limit:
            decision = {
                "schema_version": DECISION_SCHEMA,
                "decision": "defer",
                "reason": f"math_stage_capacity_wait:{stage_id}",
            }
            print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
            return 0
    routing_usage = context.get("routing_usage", {})
    usage = (
        routing_usage.get(stored_routing_key, {})
        if isinstance(routing_usage, Mapping)
        else {}
    )
    task_count = int(usage.get("task_count") or 0) if isinstance(usage, Mapping) else 0
    agent_seconds = (
        float(usage.get("agent_seconds") or 0) if isinstance(usage, Mapping) else 0.0
    )
    budget = stage.get("budget", {})
    max_tasks = budget.get("max_tasks") if isinstance(budget, Mapping) else None
    max_stage_seconds = (
        budget.get("max_agent_seconds") if isinstance(budget, Mapping) else None
    )
    exhausted = bool(
        (isinstance(max_tasks, int) and task_count >= max_tasks)
        or (
            isinstance(max_stage_seconds, int)
            and agent_seconds + 1 > max_stage_seconds
        )
    )
    if exhausted:
        decision_name = _text(budget.get("on_exhaustion") or "defer")
        decision = {
            "schema_version": DECISION_SCHEMA,
            "decision": decision_name,
            "reason": f"math_stage_budget_exhausted:{stage_id}",
        }
        print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
        return 0
    task = dict(stage["task"])
    configured_wall = int(task["wall_seconds"])
    if isinstance(max_stage_seconds, int):
        configured_wall = min(
            configured_wall,
            max(1, int(max_stage_seconds - agent_seconds)),
        )
    campaign = context.get("campaign", {})
    if isinstance(campaign, Mapping):
        campaign_remaining = int(campaign.get("max_agent_seconds") or 0) - int(
            float(campaign.get("agent_seconds_used") or 0)
        )
        if campaign_remaining > 0:
            configured_wall = min(configured_wall, campaign_remaining)
    configured_objective = str(task["objective"]).strip()
    task["objective"] = (
        f"Operate mathematics workstream {state['workstream_id']} at configured stage "
        f"{stage_id!r} under policy {policy['policy_id']!r}. {configured_objective} "
        "The policy controls allocation and evidence gates only. Own the mathematical route, "
        "intermediate conjectures, tools, falsification strategy, and the decision to transition "
        "or pause. Use the state-machine CLI for every observation and transition; do not edit "
        "state to bypass a gate."
    )
    task["wall_seconds"] = configured_wall
    decision = {
        "schema_version": DECISION_SCHEMA,
        "decision": "continue",
        "reason": f"math_stage_active:{stage_id}",
        "routing_key": routing_key,
        "action": task,
    }
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0


def _status_command(args: argparse.Namespace) -> int:
    _project, state, policy, _digest = _load_validated(
        args.project,
        args.workstream,
        require_evidence_files=True,
    )
    stage = policy["stages"][state["stage"]]
    payload = {
        "project_id": state["project_id"],
        "workstream_id": state["workstream_id"],
        "policy_id": state["policy_id"],
        "status": state["status"],
        "stage": state["stage"],
        "stage_description": stage["description"],
        "observations": len(state["observations"]),
        "transitions": len(state["transitions"]),
        "allowed_transitions": [item["to"] for item in stage.get("transitions", [])],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--project", type=Path, required=True)
    validate.add_argument("--workstream", type=Path, required=True)
    validate.add_argument("--mode", choices=("discovery", "commit"), default="commit")
    validate.set_defaults(func=_validate_command)

    initialize = subparsers.add_parser("init")
    initialize.add_argument("--project", type=Path, required=True)
    initialize.add_argument("--workstream", type=Path, required=True)
    initialize.add_argument("--workstream-id", required=True)
    initialize.set_defaults(func=_init_command)

    observe = subparsers.add_parser("observe")
    observe.add_argument("--project", type=Path, required=True)
    observe.add_argument("--workstream", type=Path, required=True)
    observe.add_argument("--observation-id", required=True)
    observe.add_argument("--kind", required=True)
    observe.add_argument("--verdict", choices=sorted(VERDICTS), required=True)
    observe.add_argument("--actor-role", choices=sorted(ROLES), required=True)
    observe.add_argument("--source-task-id", required=True)
    observe.add_argument("--summary", required=True)
    observe.add_argument("--evidence", action="append", default=[])
    observe.set_defaults(func=_observe_command)

    transition = subparsers.add_parser("transition")
    transition.add_argument("--project", type=Path, required=True)
    transition.add_argument("--workstream", type=Path, required=True)
    transition.add_argument("--to", required=True)
    transition.add_argument("--reason", required=True)
    transition.add_argument("--observation", action="append", default=[])
    transition.set_defaults(func=_transition_command)

    pause = subparsers.add_parser("pause")
    pause.add_argument("--project", type=Path, required=True)
    pause.add_argument("--workstream", type=Path, required=True)
    pause.add_argument("--reason", required=True)
    pause.set_defaults(func=_pause_command)

    resume = subparsers.add_parser("resume")
    resume.add_argument("--project", type=Path, required=True)
    resume.add_argument("--workstream", type=Path, required=True)
    resume.add_argument("--reason", required=True)
    resume.set_defaults(func=_resume_command)

    rebind = subparsers.add_parser("rebind-policy")
    rebind.add_argument("--project", type=Path, required=True)
    rebind.add_argument("--workstream", type=Path, required=True)
    rebind.add_argument("--expected-old-digest", required=True)
    rebind.add_argument("--reason", required=True)
    rebind.set_defaults(func=_rebind_command)

    decide = subparsers.add_parser("decide")
    decide.add_argument("--project", type=Path, required=True)
    decide.add_argument("--workstream", type=Path, required=True)
    decide.set_defaults(func=_decision_command)

    status = subparsers.add_parser("status")
    status.add_argument("--project", type=Path, required=True)
    status.add_argument("--workstream", type=Path, required=True)
    status.set_defaults(func=_status_command)
    return parser


def main() -> int:
    args = _parser().parse_args()
    args.project = args.project.expanduser().resolve()
    args.workstream = args.workstream.expanduser().resolve()
    try:
        return int(args.func(args))
    except (OSError, StateMachineError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
