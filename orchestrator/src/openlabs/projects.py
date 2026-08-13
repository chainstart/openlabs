"""Generic project configuration and workstream discovery.

The control plane understands only this small project envelope.  Scientific
state and validation belong to a protocol registered by the selected lab.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import HANDOFF_KINDS, IDENTIFIER


PROJECT_SCHEMA = "openlabs.project.v1"
PROJECT_STATUSES = frozenset({"active", "paused", "retired"})
CHECKPOINT_POLICIES = frozenset({"role_boundary_or_budget", "explicit_checkpoint"})
WORKSTREAM_CONTINUATIONS = frozenset({"continuous", "review_on_new_results"})
AGENT_ROLES = frozenset({"researcher", "experimenter", "writer", "reviewer"})
EPISTEMIC_FRESH_BOUNDARIES = frozenset(
    {
        "independent_replication",
        "adversarial_review",
        "portfolio_review",
        "route_reselection",
    }
)


@dataclass(frozen=True)
class ExecutionPolicy:
    checkpoint_policy: str = "role_boundary_or_budget"
    continue_across_protocol_phases: bool = True
    default_session_mode: str = "resume"
    fresh_session_boundaries: tuple[str, ...] = (
        "independent_replication",
        "adversarial_review",
        "portfolio_review",
        "route_reselection",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_policy": self.checkpoint_policy,
            "continue_across_protocol_phases": self.continue_across_protocol_phases,
            "default_session_mode": self.default_session_mode,
            "fresh_session_boundaries": list(self.fresh_session_boundaries),
        }


@dataclass(frozen=True)
class ProjectWorkstream:
    workstream_id: str
    state_path: Path
    title: str
    startup: str
    priority: int
    objective: str
    agent_role: str
    session_mode: str
    continuation: str
    review_every_results: int
    review_batch_size: int
    spawn_candidate_workstreams: bool

    def policy(self) -> dict[str, Any]:
        return {
            "dynamic": False,
            "objective": self.objective,
            "default_agent_role": self.agent_role,
            "default_session_mode": self.session_mode,
            "continuation": self.continuation,
            "review_every_results": self.review_every_results,
            "review_batch_size": self.review_batch_size,
            "spawn_candidate_workstreams": self.spawn_candidate_workstreams,
        }


@dataclass(frozen=True)
class ProjectReadResource:
    """A project-declared canonical input that agents may inspect but never mutate."""

    label: str
    path: Path

    def to_dict(self) -> dict[str, str]:
        return {"label": self.label, "path": str(self.path)}


@dataclass(frozen=True)
class ProjectConfig:
    project_id: str
    domain: str
    status: str
    objective: str
    protocol_id: str
    primary_skill: str
    path: Path
    execution: ExecutionPolicy
    workstreams: tuple[ProjectWorkstream, ...]
    domain_config_path: Path | None
    research_index_path: Path | None
    research_index_source_campaign_ids: tuple[str, ...]
    read_resources: tuple[ProjectReadResource, ...]
    raw: dict[str, Any]


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _identifier(value: object, field: str) -> str:
    normalized = _text(value)
    if not IDENTIFIER.fullmatch(normalized):
        raise ValueError(f"project {field} is invalid: {normalized!r}")
    return normalized


def _relative_file(base: Path, value: object, field: str) -> Path:
    configured = _text(value)
    if not configured:
        raise ValueError(f"project {field} is required")
    path = (base / configured).resolve()
    if not path.is_file():
        raise ValueError(f"project {field} does not exist: {path}")
    return path


def _relative_resource(base: Path, value: object, field: str) -> Path:
    configured = _text(value)
    if not configured:
        raise ValueError(f"project {field} is required")
    path = (base / configured).resolve()
    if not path.exists() or not (path.is_file() or path.is_dir()):
        raise ValueError(f"project {field} does not exist: {path}")
    return path


def load_project(path: str | Path) -> ProjectConfig:
    project_path = Path(path).expanduser().resolve()
    payload = json.loads(project_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise TypeError(f"Project config must be an object: {project_path}")
    if payload.get("schema_version") != PROJECT_SCHEMA:
        raise ValueError(f"Unsupported project schema in {project_path}")
    project_id = _identifier(payload.get("project_id"), "project_id")
    domain = _text(payload.get("domain"))
    if not domain:
        raise ValueError("project domain is required")
    status = _text(payload.get("status"))
    if status not in PROJECT_STATUSES:
        raise ValueError(f"unknown project status: {status!r}")
    objective = _text(payload.get("objective"))
    if not objective:
        raise ValueError("project objective is required")
    protocol = payload.get("protocol")
    if not isinstance(protocol, Mapping):
        raise ValueError("project protocol must be an object")
    protocol_id = _identifier(protocol.get("id"), "protocol.id")
    primary_skill = _identifier(protocol.get("primary_skill"), "protocol.primary_skill")

    execution_value = payload.get("execution", {})
    if not isinstance(execution_value, Mapping):
        raise ValueError("project execution must be an object")
    checkpoint_policy = _text(
        execution_value.get("checkpoint_policy") or "role_boundary_or_budget"
    )
    if checkpoint_policy not in CHECKPOINT_POLICIES:
        raise ValueError(f"unknown checkpoint policy: {checkpoint_policy!r}")
    default_session_mode = _text(
        execution_value.get("default_session_mode") or "resume"
    )
    if default_session_mode not in {"resume", "fresh"}:
        raise ValueError("project default_session_mode must be resume or fresh")
    boundaries_value = execution_value.get(
        "fresh_session_boundaries",
        list(ExecutionPolicy().fresh_session_boundaries),
    )
    if (
        not isinstance(boundaries_value, list)
        or any(not _text(item) for item in boundaries_value)
    ):
        raise ValueError("project fresh_session_boundaries must be a string array")
    unknown_boundaries = {
        str(item).strip() for item in boundaries_value
    } - HANDOFF_KINDS
    if unknown_boundaries:
        raise ValueError(
            "project fresh_session_boundaries contain unknown handoff kinds: "
            + ", ".join(sorted(unknown_boundaries))
        )
    continuation_value = execution_value.get("continue_across_protocol_phases", True)
    if not isinstance(continuation_value, bool):
        raise ValueError("project continue_across_protocol_phases must be a boolean")
    normalized_boundaries = tuple(str(item).strip() for item in boundaries_value)
    if len(normalized_boundaries) != len(set(normalized_boundaries)):
        raise ValueError("project fresh_session_boundaries cannot contain duplicates")
    execution = ExecutionPolicy(
        checkpoint_policy=checkpoint_policy,
        continue_across_protocol_phases=continuation_value,
        default_session_mode=default_session_mode,
        fresh_session_boundaries=normalized_boundaries,
    )

    domain_config_path: Path | None = None
    domain_config = payload.get("domain_config")
    if domain_config is not None:
        if not isinstance(domain_config, Mapping):
            raise ValueError("project domain_config must be an object")
        domain_config_path = _relative_file(
            project_path.parent,
            domain_config.get("path"),
            "domain_config.path",
        )

    research_index_path: Path | None = None
    research_index_source_campaign_ids: tuple[str, ...] = ()
    research_index = payload.get("research_index")
    if research_index is not None:
        if not isinstance(research_index, Mapping):
            raise ValueError("project research_index must be an object")
        research_index_path = _relative_file(
            project_path.parent,
            research_index.get("path"),
            "research_index.path",
        )
        sources_value = research_index.get("source_campaign_ids", [])
        if (
            not isinstance(sources_value, list)
            or any(not IDENTIFIER.fullmatch(_text(item)) for item in sources_value)
        ):
            raise ValueError(
                "project research_index.source_campaign_ids must be an identifier array"
            )
        research_index_source_campaign_ids = tuple(_text(item) for item in sources_value)
        if len(research_index_source_campaign_ids) != len(
            set(research_index_source_campaign_ids)
        ):
            raise ValueError("project research index source campaigns must be unique")

    read_resources_value = payload.get("read_resources", [])
    if not isinstance(read_resources_value, list):
        raise ValueError("project read_resources must be an array")
    read_resources: list[ProjectReadResource] = []
    resource_labels: set[str] = set()
    resource_paths: set[Path] = set()
    for index, item in enumerate(read_resources_value):
        if not isinstance(item, Mapping):
            raise ValueError(f"project read_resources[{index}] must be an object")
        label = _text(item.get("label"))
        if not label:
            raise ValueError(f"project read_resources[{index}].label is required")
        path_value = _relative_resource(
            project_path.parent,
            item.get("path"),
            f"read_resources[{index}].path",
        )
        if label in resource_labels:
            raise ValueError(f"duplicate project read resource label: {label}")
        if path_value in resource_paths:
            raise ValueError(f"duplicate project read resource path: {path_value}")
        resource_labels.add(label)
        resource_paths.add(path_value)
        read_resources.append(ProjectReadResource(label=label, path=path_value))

    raw_workstreams = payload.get("workstreams")
    if not isinstance(raw_workstreams, list) or not raw_workstreams:
        raise ValueError("project workstreams must be a nonempty array")
    workstreams: list[ProjectWorkstream] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_workstreams):
        if not isinstance(item, Mapping):
            raise ValueError(f"project workstream {index} must be an object")
        workstream_id = _identifier(item.get("workstream_id"), "workstream_id")
        if workstream_id in seen:
            raise ValueError(f"duplicate workstream_id: {workstream_id}")
        seen.add(workstream_id)
        startup = _text(item.get("startup") or "active")
        if startup not in {"active", "paused"}:
            raise ValueError(f"workstream {workstream_id} has invalid startup: {startup}")
        raw_priority = item.get("priority", 0)
        if not isinstance(raw_priority, int) or isinstance(raw_priority, bool):
            raise ValueError(f"workstream {workstream_id} priority must be an integer")
        role = _text(item.get("agent_role") or "researcher")
        if role not in AGENT_ROLES:
            raise ValueError(f"workstream {workstream_id} has invalid agent_role: {role}")
        session_mode = _text(
            item.get("session_mode") or ("fresh" if role == "reviewer" else "resume")
        )
        if session_mode not in {"resume", "fresh"}:
            raise ValueError(
                f"workstream {workstream_id} session_mode must be resume or fresh"
            )
        if role == "reviewer" and session_mode != "fresh":
            raise ValueError(f"workstream {workstream_id} reviewers must start fresh")
        continuation = _text(item.get("continuation") or "continuous")
        if continuation not in WORKSTREAM_CONTINUATIONS:
            raise ValueError(
                f"workstream {workstream_id} has invalid continuation: {continuation}"
            )
        if continuation == "review_on_new_results" and role != "reviewer":
            raise ValueError(
                f"workstream {workstream_id} review_on_new_results requires reviewer role"
            )
        review_every_results = item.get("review_every_results", 1)
        if (
            not isinstance(review_every_results, int)
            or isinstance(review_every_results, bool)
            or review_every_results < 1
        ):
            raise ValueError(
                f"workstream {workstream_id} review_every_results must be positive"
            )
        review_batch_size = item.get("review_batch_size", 32)
        if (
            not isinstance(review_batch_size, int)
            or isinstance(review_batch_size, bool)
            or review_batch_size < 1
        ):
            raise ValueError(
                f"workstream {workstream_id} review_batch_size must be positive"
            )
        spawn_candidates = item.get("spawn_candidate_workstreams", False)
        if not isinstance(spawn_candidates, bool):
            raise ValueError(
                f"workstream {workstream_id} spawn_candidate_workstreams must be boolean"
            )
        if spawn_candidates and role != "reviewer":
            raise ValueError(
                f"workstream {workstream_id} candidate spawning requires reviewer role"
            )
        workstreams.append(
            ProjectWorkstream(
                workstream_id=workstream_id,
                state_path=_relative_file(
                    project_path.parent,
                    item.get("state_path"),
                    f"workstream {workstream_id} state_path",
                ),
                title=_text(item.get("title")) or workstream_id,
                startup=startup,
                priority=int(raw_priority),
                objective=_text(item.get("objective")),
                agent_role=role,
                session_mode=session_mode,
                continuation=continuation,
                review_every_results=int(review_every_results),
                review_batch_size=int(review_batch_size),
                spawn_candidate_workstreams=spawn_candidates,
            )
        )
    return ProjectConfig(
        project_id=project_id,
        domain=domain,
        status=status,
        objective=objective,
        protocol_id=protocol_id,
        primary_skill=primary_skill,
        path=project_path,
        execution=execution,
        workstreams=tuple(workstreams),
        domain_config_path=domain_config_path,
        research_index_path=research_index_path,
        research_index_source_campaign_ids=research_index_source_campaign_ids,
        read_resources=tuple(read_resources),
        raw=dict(payload),
    )


def discover_projects(data_root: str | Path) -> tuple[ProjectConfig, ...]:
    root = Path(data_root).expanduser().resolve() / "workspaces"
    paths = {
        *root.glob("*/projects/*/project.json"),
        *root.glob("*/production/*/project.json"),
    }
    return tuple(load_project(path) for path in sorted(paths))


def workstream_policy(campaign: Mapping[str, Any]) -> dict[str, Any]:
    """Decode the thin scheduling envelope stored with a campaign binding."""

    raw = campaign.get("workstream_policy_json")
    if isinstance(raw, str) and raw.strip():
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return dict(value) if isinstance(value, Mapping) else {}
    return dict(raw) if isinstance(raw, Mapping) else {}
