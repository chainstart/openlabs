"""Trusted, Skill-supplied authority policies for epistemic phase boundaries.

The control plane does not know what a mathematical phase means.  A domain
Skill may publish a small declarative policy that maps its durable state to the
roles allowed to continue.  Hooks and the scheduler consume the same policy so
the semantic gate is both visible to Codex and enforced after transport.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

AUTHORITY_POLICY_SCHEMA = "openlabs.authority_policy.v1"
AGENT_ROLES = frozenset({"researcher", "experimenter", "writer", "reviewer"})
SESSION_MODES = frozenset({"resume", "fresh"})
HANDOFF_KINDS = frozenset(
    {
        "role_handoff",
        "text_revision",
        "evidence_remediation",
        "independent_replication",
        "adversarial_review",
        "portfolio_review",
        "route_reselection",
    }
)


@dataclass(frozen=True)
class AuthorityRequirement:
    policy_id: str
    policy_path: str
    state_path: str
    phase: str
    allowed_roles: tuple[str, ...]
    default_role: str
    required_session_mode: str | None = None
    required_handoff_kind: str | None = None
    objective: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": AUTHORITY_POLICY_SCHEMA,
            "policy_id": self.policy_id,
            "policy_path": self.policy_path,
            "state_path": self.state_path,
            "phase": self.phase,
            "allowed_roles": list(self.allowed_roles),
            "default_role": self.default_role,
            "required_session_mode": self.required_session_mode,
            "required_handoff_kind": self.required_handoff_kind,
            "objective": self.objective,
        }

    @classmethod
    def from_mapping(cls, value: object) -> AuthorityRequirement | None:
        if not isinstance(value, Mapping):
            return None
        roles = value.get("allowed_roles")
        if not isinstance(roles, list) or not roles:
            return None
        normalized = tuple(str(item) for item in roles)
        default = str(value.get("default_role") or "")
        if any(item not in AGENT_ROLES for item in normalized) or default not in normalized:
            return None
        mode = value.get("required_session_mode")
        kind = value.get("required_handoff_kind")
        objective = str(value.get("objective") or "").strip() or None
        if mode is not None and str(mode) not in SESSION_MODES:
            return None
        if kind is not None and str(kind) not in HANDOFF_KINDS:
            return None
        return cls(
            policy_id=str(value.get("policy_id") or ""),
            policy_path=str(value.get("policy_path") or ""),
            state_path=str(value.get("state_path") or ""),
            phase=str(value.get("phase") or ""),
            allowed_roles=normalized,
            default_role=default,
            required_session_mode=(str(mode) if mode is not None else None),
            required_handoff_kind=(str(kind) if kind is not None else None),
            objective=objective,
        )


def authority_policy_paths(skill_dirs: Iterable[Path]) -> tuple[Path, ...]:
    """Return declarative policies only from the trusted Skill source roots."""

    policies: list[Path] = []
    for raw in skill_dirs:
        candidate = raw.expanduser().resolve() / "authority-policy.json"
        if candidate.is_file():
            policies.append(candidate)
    return tuple(policies)


def _policy(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unreadable authority policy {path}: {exc}") from exc
    if not isinstance(value, Mapping) or value.get("schema_version") != AUTHORITY_POLICY_SCHEMA:
        raise ValueError(f"Invalid authority policy schema: {path}")
    if not str(value.get("policy_id") or "").strip():
        raise ValueError(f"Authority policy has no policy_id: {path}")
    if not str(value.get("state_glob") or "").strip():
        raise ValueError(f"Authority policy has no state_glob: {path}")
    phases = value.get("phase_authority")
    if not isinstance(phases, Mapping) or not phases:
        raise ValueError(f"Authority policy has no phase_authority: {path}")
    return value


def resolve_workspace_authority(
    workspace: Path,
    policy_paths: Iterable[Path],
) -> AuthorityRequirement | None:
    """Resolve the newest active state governed by the installed policies."""

    root = workspace.expanduser().resolve()
    candidates: list[tuple[str, str, AuthorityRequirement]] = []
    for raw_policy_path in policy_paths:
        policy_path = raw_policy_path.expanduser().resolve()
        policy = _policy(policy_path)
        state_glob = str(policy["state_glob"])
        expected_schema = str(policy.get("state_schema_version") or "")
        phase_field = str(policy.get("phase_field") or "phase")
        phase_authority = policy["phase_authority"]
        raw_excluded_parts = policy.get("exclude_path_parts", [])
        if not isinstance(raw_excluded_parts, list) or any(
            not isinstance(item, str) or not item.strip() for item in raw_excluded_parts
        ):
            raise ValueError(f"{policy_path}: exclude_path_parts must be a string array")
        excluded_parts = {str(item) for item in raw_excluded_parts}
        for state_path in root.glob(state_glob):
            if not state_path.is_file() or state_path.is_symlink():
                continue
            relative = state_path.relative_to(root)
            if relative.parts[:1] and relative.parts[0] in {".agents", ".codex", "results"}:
                continue
            if excluded_parts.intersection(relative.parts):
                continue
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(state, Mapping):
                continue
            if expected_schema and state.get("schema_version") != expected_schema:
                continue
            phase = str(state.get(phase_field) or "")
            raw_requirement = phase_authority.get(phase)
            if not isinstance(raw_requirement, Mapping) or raw_requirement.get("terminal") is True:
                continue
            roles = raw_requirement.get("allowed_roles")
            if not isinstance(roles, list) or not roles:
                raise ValueError(f"{policy_path}: {phase} has no allowed_roles")
            allowed_roles = tuple(str(item) for item in roles)
            default_role = str(raw_requirement.get("default_role") or allowed_roles[0])
            if (
                any(role not in AGENT_ROLES for role in allowed_roles)
                or default_role not in allowed_roles
            ):
                raise ValueError(f"{policy_path}: {phase} has invalid role authority")
            required_mode = raw_requirement.get("required_session_mode")
            required_kind = raw_requirement.get("required_handoff_kind")
            objective = str(raw_requirement.get("objective") or "").strip() or None
            if required_mode is not None and str(required_mode) not in SESSION_MODES:
                raise ValueError(f"{policy_path}: {phase} has invalid session authority")
            if required_kind is not None and str(required_kind) not in HANDOFF_KINDS:
                raise ValueError(f"{policy_path}: {phase} has invalid handoff authority")
            requirement = AuthorityRequirement(
                policy_id=str(policy["policy_id"]),
                policy_path=str(policy_path),
                state_path=relative.as_posix(),
                phase=phase,
                allowed_roles=allowed_roles,
                default_role=default_role,
                required_session_mode=(str(required_mode) if required_mode is not None else None),
                required_handoff_kind=(str(required_kind) if required_kind is not None else None),
                objective=objective,
            )
            candidates.append(
                (str(state.get("updated_at") or ""), relative.as_posix(), requirement)
            )
    return max(candidates, key=lambda item: (item[0], item[1]))[2] if candidates else None


def task_authority_errors(
    *,
    role: object,
    session_mode: object,
    authority: AuthorityRequirement | None,
) -> list[str]:
    if authority is None:
        return []
    errors: list[str] = []
    normalized_role = str(role or "")
    normalized_mode = str(session_mode or "")
    if normalized_role not in authority.allowed_roles:
        errors.append(
            f"phase {authority.phase} allows roles {list(authority.allowed_roles)}, "
            f"not {normalized_role!r}"
        )
    if (
        authority.required_session_mode is not None
        and normalized_mode != authority.required_session_mode
    ):
        errors.append(
            f"phase {authority.phase} requires session_mode {authority.required_session_mode!r}"
        )
    return errors


def action_authority_errors(
    payload: Mapping[str, Any],
    *,
    current_role: str,
    authority: AuthorityRequirement | None,
) -> list[str]:
    """Check the first executable successor against the resulting phase."""

    if authority is None or str(payload.get("status") or "") not in {
        "completed",
        "succeeded",
    }:
        return []
    actions = payload.get("next_actions")
    if not isinstance(actions, list) or not actions:
        return [f"active phase {authority.phase} requires one executable next action"]
    action = actions[0]
    if isinstance(action, str):
        role = current_role
        mode = "resume"
        kind = "role_handoff"
    elif isinstance(action, Mapping):
        role = str(action.get("agent_role") or "")
        mode = str(action.get("session_mode") or "")
        kind = str(action.get("handoff_kind") or "role_handoff")
    else:
        return ["the first next action is not executable"]
    errors = task_authority_errors(role=role, session_mode=mode, authority=authority)
    if authority.required_handoff_kind is not None and kind != authority.required_handoff_kind:
        errors.append(
            f"phase {authority.phase} requires handoff_kind {authority.required_handoff_kind!r}"
        )
    return errors


def enforce_action_authority(
    *,
    agent_role: str,
    session_mode: str,
    handoff_kind: str,
    authority: AuthorityRequirement | None,
) -> tuple[str, str, str, list[str]]:
    """Normalize scheduler values as a last-resort deterministic safety gate."""

    if authority is None:
        return agent_role, session_mode, handoff_kind, []
    changes: list[str] = []
    if agent_role not in authority.allowed_roles:
        changes.append(f"agent_role:{agent_role}->{authority.default_role}")
        agent_role = authority.default_role
    if (
        authority.required_session_mode is not None
        and session_mode != authority.required_session_mode
    ):
        changes.append(f"session_mode:{session_mode}->{authority.required_session_mode}")
        session_mode = authority.required_session_mode
    if (
        authority.required_handoff_kind is not None
        and handoff_kind != authority.required_handoff_kind
    ):
        changes.append(f"handoff_kind:{handoff_kind}->{authority.required_handoff_kind}")
        handoff_kind = authority.required_handoff_kind
    return agent_role, session_mode, handoff_kind, changes
