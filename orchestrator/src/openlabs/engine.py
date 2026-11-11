"""One idempotent factory tick: ingest, recover, lease, launch, and exit."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import budget as budget_control
from .agent_runtime import HOOK_GATED_ADAPTERS, configure_codex_runtime
from .attempts import (
    AttemptWorkspace,
    attempt_artifact_policy,
    attempt_output_path,
    begin_attempt_promotion,
    enforce_campaign_data_boundary,
    finalize_attempt_promotion,
    find_attempt_workspace,
    freeze_result_bundle,
    prepare_attempt_workspace,
    publish_staged_artifacts,
    quarantine_attempt_workspace,
    recover_attempt_promotion,
    rollback_attempt_promotion,
)
from .config import LEGACY_RUNNER_TIERS, FactorySettings, WorkspacePaths
from .contracts import (
    IDENTIFIER,
    TASK_SCHEMA,
    atomic_write_json,
    sha256_file,
    validate_receipt,
    validate_task,
)
from .db import (
    QUOTA_FAILURE_CLASS,
    AttemptDisposition,
    FactoryDB,
    normalize_runner,
    retry_not_before,
)
from .gates import evaluate_result_bundle
from .labs import LabManifest, ProtocolManifest, discover_labs, lab_for_domain
from .locking import factory_operation_lock
from .portfolio import (
    advance_review_cursor,
    index_project_result,
    reconcile_pending_portfolio_review,
    schedule_portfolio_review,
    spawn_candidate_workstreams,
)
from .program import (
    FREEZABLE_STATUSES,
    TopicLedgerError,
    freeze_topic,
    open_topic_ledger,
    run_program_controller,
    topic_for_campaign,
)
from . import assets as asset_library
from . import program_autonomy
from .program_autonomy import DIRECTION_TASK_TYPE, EVIDENCE_REMEDIATION_ROUTINGS
from .program_flow import (
    SCOUT_TASK_TYPE,
    packet_read_resources,
    record_admission_deferral,
    run_program_pipeline,
    workstream_admitted,
)
from .projects import (
    EPISTEMIC_FRESH_BOUNDARIES,
    ExecutionPolicy,
    load_project,
    workstream_policy,
)
from .protocols import run_protocol_hook, validate_protocol_state
from .resources import (
    ResourceVector,
    default_task_resources,
    effective_capacity,
    task_resources,
)


def _timestamp_token() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _inside(path: Path, roots: tuple[Path, ...]) -> bool:
    resolved = path.resolve()
    return any(
        resolved == root.resolve() or resolved.is_relative_to(root.resolve()) for root in roots
    )


@dataclass(frozen=True)
class ActionPlan:
    objective: str
    agent_role: str
    session_mode: str
    handoff_kind: str
    resources: ResourceVector | None = None
    wall_seconds: int | None = None
    runner: str | None = None


@dataclass(frozen=True)
class ProtocolContinuation:
    decision: str
    reason: str
    action: ActionPlan | None = None
    routing_key: str | None = None


@dataclass(frozen=True)
class ProjectWorkstreamBinding:
    project_id: str
    project_path: Path
    workstream_id: str
    title: str
    workstream_path: Path
    domain: str
    priority: int
    protocol_id: str
    primary_skill: str
    execution_policy: ExecutionPolicy
    workstream_policy: dict[str, Any] = field(default_factory=dict)
    legacy_plan_path: Path | None = None


@dataclass(frozen=True)
class AutoTaskRoom:
    allowed: bool
    rolled_over: bool = False
    epoch: int = 1


def _next_action_plan(
    action: object,
    *,
    current_role: str,
    execution_policy: ExecutionPolicy | None = None,
) -> ActionPlan | None:
    """Normalize one bounded successor without weakening role boundaries."""

    policy = execution_policy or ExecutionPolicy()
    if isinstance(action, str) and action.strip():
        normalized = " ".join(action.strip().lower().split())
        if normalized.startswith(
            (
                "no automatic continuation",
                "no continuation is requested",
                "automatic continuation is not requested",
                "do not automatically continue",
                "do not initiate automatic continuation",
            )
        ):
            return None
        return ActionPlan(
            objective=action.strip(),
            agent_role=current_role,
            session_mode=policy.default_session_mode,
            handoff_kind="role_handoff",
        )
    if not isinstance(action, Mapping):
        return None
    objective = str(action.get("objective") or "").strip()
    target_role = str(action.get("agent_role") or "").strip()
    requested_mode = str(
        action.get("session_mode") or policy.default_session_mode
    ).strip()
    handoff_kind = str(action.get("handoff_kind") or "role_handoff").strip()
    if not objective or target_role not in {
        "researcher",
        "experimenter",
        "writer",
        "reviewer",
    }:
        return None
    # A role boundary is an epistemic boundary. Never resume the creator's
    # conversation merely because a result bundle requested it.
    effective_mode = (
        "fresh"
        if target_role != current_role
        or target_role == "reviewer"
        or handoff_kind
        in EPISTEMIC_FRESH_BOUNDARIES.union(policy.fresh_session_boundaries)
        else requested_mode
    )
    if effective_mode not in {"resume", "fresh"}:
        return None
    resources = None
    if isinstance(action.get("resources"), Mapping):
        try:
            resources = ResourceVector.from_mapping(action["resources"])
        except ValueError:
            return None
    requested_wall_seconds = action.get("wall_seconds")
    if requested_wall_seconds is None:
        wall_seconds = None
    elif (
        isinstance(requested_wall_seconds, int)
        and not isinstance(requested_wall_seconds, bool)
        and requested_wall_seconds > 0
    ):
        wall_seconds = requested_wall_seconds
    else:
        return None
    runner_value = action.get("runner")
    if runner_value is None:
        runner = None
    else:
        runner = str(runner_value).strip()
        if not IDENTIFIER.fullmatch(runner):
            return None
    return ActionPlan(
        objective=objective,
        agent_role=target_role,
        session_mode=effective_mode,
        handoff_kind=handoff_kind,
        resources=resources,
        wall_seconds=wall_seconds,
        runner=runner,
    )


def _continuation_task_type(role: str) -> str:
    return {
        "researcher": "research_continue",
        "experimenter": "experiment_continue",
        "writer": "paper_revision",
        "reviewer": "independent_review",
    }[role]


def _explicit_terminal_freeze(payload: Mapping[str, Any]) -> bool:
    """Treat an audited freeze as terminal even when prose appears in next_actions.

    Result bundles historically allowed free-form strings in ``next_actions``.  A
    negative instruction such as "do not promote" is therefore syntactically an
    action unless the scientific decision takes precedence here.
    """

    if str(payload.get("status") or "") not in {"completed", "succeeded"}:
        return False
    gate_result = payload.get("gate_result")
    return isinstance(gate_result, Mapping) and (
        str(gate_result.get("promotion_decision") or "").strip().lower() == "freeze"
    )


def _missing_agent_bundle(
    payload: Mapping[str, Any],
    runtime: Mapping[str, Any],
) -> bool:
    """Identify a runner-level miss before any scientific result was produced."""

    return (
        str(payload.get("status") or "") == "needs_replan"
        and str(runtime.get("failure_class") or "") == "agent_transport"
        and not payload.get("artifacts")
        and not payload.get("claims")
    )


def _quota_failure(
    payload: Mapping[str, Any],
    runtime: Mapping[str, Any],
) -> bool:
    """A provider quota/rate-limit stop before any scientific output existed."""

    return (
        str(runtime.get("failure_class") or "") == QUOTA_FAILURE_CLASS
        and str(payload.get("status") or "") in {"needs_replan", "failed", "needs_human"}
        and not payload.get("artifacts")
        and not payload.get("claims")
    )


def _defer_quota_failure(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    report: TickReport,
    *,
    task: Mapping[str, Any],
    attempt_id: str,
    runtime: dict[str, Any],
    result_path: Path,
    result_sha256: str,
) -> bool:
    """Requeue a quota-failed attempt; False once the consecutive limit is exceeded."""

    task_id = str(task["task_id"])
    runner = normalize_runner(task.get("runner"))
    consecutive = db.consecutive_quota_failures(task_id) + 1
    runtime["consecutive_quota_failures"] = consecutive
    quota = runtime.get("quota") if isinstance(runtime.get("quota"), Mapping) else {}
    if consecutive > settings.budget.quota_retry_limit:
        runtime["quota_retry_exhausted"] = True
        db.update_meta(
            {},
            events=[
                (
                    "task",
                    task_id,
                    "quota_retry_exhausted",
                    {
                        "attempt_id": attempt_id,
                        "runner": runner,
                        "consecutive_quota_failures": consecutive,
                        "quota_retry_limit": settings.budget.quota_retry_limit,
                        "handling": "ordinary_failure",
                        "quota": dict(quota),
                    },
                )
            ],
        )
        return False
    backoff = budget_control.record_quota_failure(
        db,
        settings,
        runner=runner,
        reset_at=runtime.get("quota_reset_at"),
        task_id=task_id,
    )
    runtime["quota_backoff"] = backoff.to_dict()
    attempt_workspace = find_attempt_workspace(
        paths,
        campaign_id=str(task["campaign_id"]),
        attempt_id=attempt_id,
    )
    if attempt_workspace is not None:
        _quarantine_attempt(
            paths,
            report,
            task_id=task_id,
            campaign_id=str(task["campaign_id"]),
            attempt_id=attempt_id,
            reason=f"{QUOTA_FAILURE_CLASS}:{quota.get('kind') or 'unknown'}",
        )
    db.defer_quota_attempt(
        task_id,
        attempt_id=attempt_id,
        not_before=backoff.until,
        result_path=str(result_path),
        result_sha256=result_sha256,
        run_seconds=float(runtime.get("duration_seconds") or 0.0),
        runtime=runtime,
        error=f"{QUOTA_FAILURE_CLASS}:{quota.get('kind') or 'unknown'}",
        consecutive=consecutive,
    )
    report.quota_deferred.append(
        {
            "task_id": task_id,
            "runner": runner,
            "not_before": backoff.until,
            "consecutive_quota_failures": consecutive,
        }
    )
    return True


def _infrastructure_retry_objective(
    db: FactoryDB,
    task: Mapping[str, Any],
) -> str:
    """Recover the nearest non-diagnostic objective from the task lineage."""

    source: Mapping[str, Any] = task
    visited: set[str] = set()
    while str(source.get("routing_reason") or "") == "infrastructure_retry":
        parent_id = str(source.get("parent_task_id") or "")
        if not parent_id or parent_id in visited:
            break
        visited.add(parent_id)
        parent = db.task(parent_id)
        if parent is None:
            break
        source = parent
    original = str(source.get("objective") or task.get("objective") or "").strip()
    return (
        "Retry the unchanged bounded objective after a transport-only failure. "
        "Do not count the failed transport as scientific no-progress. Original objective: "
        f"{original}"
    )


def _successor_resources(
    task: Mapping[str, Any],
    settings: FactorySettings,
    *,
    target_role: str,
    requested: ResourceVector | None = None,
) -> ResourceVector:
    if requested is not None:
        return requested
    if target_role == str(task.get("agent_role") or "researcher"):
        return task_resources(task)
    return default_task_resources(settings)


def _derived_task_id(parent_task_id: str, suffix: str, digest: str) -> str:
    candidate = f"{parent_task_id}:{suffix}"
    return candidate if len(candidate) <= 128 else f"{suffix}:{digest[:32]}"


def _agent_tools(settings: FactorySettings, runner: Any) -> dict[str, Any]:
    """Tool decisions the lab runner applies (Claude: sub-agent tools by tier)."""

    spec = settings.runners.get(normalize_runner(runner))
    tier = budget_control.tier_of(settings, runner)
    allow = spec.subagents_allowed if spec is not None else tier == "lead"
    return {"tier": tier, "allow_subagents": allow}


def _paper_skill(domain: str) -> str | None:
    return {
        "math": "openlabs-math-paper",
        "ai": "openlabs-ai-paper",
        "materials": "openlabs-materials-paper",
        "physics": "openlabs-physics-paper",
        "quant": "openlabs-quant-paper",
        "biology": "openlabs-biology-paper",
    }.get(domain)


def _research_skill(domain: str) -> str | None:
    return {
        "math": "amra-research-loop",
        "ai": "ai-research-loop",
        "materials": "materials-research-loop",
        "physics": "physics-research-loop",
        "quant": "quant-backtest-audit",
        "biology": "biomed-research-loop",
    }.get(domain)


def _prepare_auto_task_room(
    db: FactoryDB,
    campaign_id: str,
    settings: FactorySettings,
    report: TickReport,
    *,
    source_task_id: str | None,
) -> AutoTaskRoom:
    campaign = db.campaign(campaign_id)
    if campaign is None or str(campaign.get("status")) != "active":
        return AutoTaskRoom(False)
    continuous = bool(campaign.get("continuous"))
    epoch = int(campaign.get("production_epoch") or 1)
    task_count = (
        db.current_epoch_task_count(campaign_id) if continuous else db.task_count(campaign_id)
    )
    # Agent time is a campaign-lifetime hard budget.  Epochs bound automatic
    # task counts and preserve lineage; rolling an epoch must never mint more
    # execution time.
    used = float(campaign.get("agent_seconds_used") or 0)
    task_room = task_count < settings.max_auto_tasks_per_campaign
    budget_room = used + 1 <= float(campaign.get("max_agent_seconds") or 0)
    if task_room and budget_room:
        return AutoTaskRoom(True, epoch=epoch)
    if not budget_room or not continuous or db.has_active_tasks(campaign_id):
        return AutoTaskRoom(False, epoch=epoch)
    reason = "automatic_task_window_exhausted"
    new_epoch = db.rollover_campaign_epoch(
        campaign_id,
        reason=reason,
        source_task_id=source_task_id,
    )
    report.rollovers.append(
        {
            "campaign_id": campaign_id,
            "epoch": new_epoch,
            "reason": reason,
        }
    )
    return AutoTaskRoom(True, rolled_over=True, epoch=new_epoch)


@dataclass
class TickReport:
    ingested: list[dict[str, str]] = field(default_factory=list)
    recovered: list[str] = field(default_factory=list)
    quarantined: list[str] = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)
    launched: list[str] = field(default_factory=list)
    enqueued: list[str] = field(default_factory=list)
    budget_stopped: list[str] = field(default_factory=list)
    production_synced: list[str] = field(default_factory=list)
    production_paused: list[str] = field(default_factory=list)
    production_reseeded: list[str] = field(default_factory=list)
    production_blocked: list[dict[str, str]] = field(default_factory=list)
    rollovers: list[dict[str, Any]] = field(default_factory=list)
    attempts_committed: list[dict[str, str]] = field(default_factory=list)
    attempts_quarantined: list[dict[str, str]] = field(default_factory=list)
    attempts_recovered: list[dict[str, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    status_counts: dict[str, int] = field(default_factory=dict)
    resource_capacity: dict[str, int] = field(default_factory=dict)
    resource_reserved: dict[str, int] = field(default_factory=dict)
    # Research-program controller summary; empty while [program] is disabled.
    # Slot counts plus candidate_pool, waiting_admitted, scouts_scheduled,
    # scout_blocked, admissions_scheduled, admissions_waiting, cards_registered,
    # rejected_cards (with reasons), admission_decisions and materialized; the
    # back half adds direction_decisions (scheduled and their outcomes),
    # topics_frozen, ready_queued and handoffs; the release pipeline adds releases
    # (one entry per step taken) and release_exhausted (papers stopped for a human).
    program: dict[str, Any] = field(default_factory=dict)
    # Provider-quota budget: current launch ceiling and per-runner backoff ends.
    effective_parallel: int | None = None
    provider_backoff_until: dict[str, str] = field(default_factory=dict)
    quota_deferred: list[dict[str, Any]] = field(default_factory=list)
    infrastructure_retried: list[dict[str, Any]] = field(default_factory=list)
    # Quota-aware routing (empty while no [runners] table is configured):
    # per-provider newest windows, headroom, pace and reserve state.
    provider_quota: dict[str, dict[str, Any]] = field(default_factory=dict)
    # {"short": bool, "paused_task_types": [...], "runners": {...}}; short=True
    # means no lead runner may take decision work (负责人额度不足).
    lead_quota: dict[str, Any] = field(default_factory=dict)
    routed: list[dict[str, Any]] = field(default_factory=list)
    routing_deferred: list[dict[str, Any]] = field(default_factory=list)
    escalated: list[dict[str, Any]] = field(default_factory=list)
    quota_probes: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = self._base_dict()
        # Routing keys appear only with a [runners] table, so the default report
        # shape is unchanged.
        if self.provider_quota or self.lead_quota or self.routed or self.routing_deferred or (
            self.escalated or self.quota_probes
        ):
            payload.update(
                {
                    "provider_quota": self.provider_quota,
                    "lead_quota": self.lead_quota,
                    "lead_quota_short": bool(self.lead_quota.get("short")),
                    "routed": self.routed,
                    "routing_deferred": self.routing_deferred,
                    "escalated": self.escalated,
                    "quota_probes": self.quota_probes,
                }
            )
        return payload

    def _base_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "openlabs.tick_report.v1",
            "ingested": self.ingested,
            "recovered": self.recovered,
            "quarantined": self.quarantined,
            "cancelled": self.cancelled,
            "launched": self.launched,
            "enqueued": self.enqueued,
            "budget_stopped": self.budget_stopped,
            "production_synced": self.production_synced,
            "production_paused": self.production_paused,
            "production_reseeded": self.production_reseeded,
            "production_blocked": self.production_blocked,
            "rollovers": self.rollovers,
            "attempts_committed": self.attempts_committed,
            "attempts_quarantined": self.attempts_quarantined,
            "attempts_recovered": self.attempts_recovered,
            "errors": self.errors,
            "status_counts": self.status_counts,
            "resource_capacity": self.resource_capacity,
            "resource_reserved": self.resource_reserved,
            "program": self.program,
            "effective_parallel": self.effective_parallel,
            "provider_backoff_until": self.provider_backoff_until,
            "quota_deferred": self.quota_deferred,
            "infrastructure_retried": self.infrastructure_retried,
        }


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"Expected a JSON object: {path}")
    return payload


def _recover_attempt_workspaces(
    db: FactoryDB,
    paths: WorkspacePaths,
    report: TickReport,
) -> None:
    """Reconcile every nonterminal attempt metadata state against the database."""

    root = paths.artifacts / "attempt-workspaces"
    for metadata_path in sorted(root.glob("*/*/attempt-workspace.json")):
        try:
            metadata = _read_json_object(metadata_path)
            status = str(metadata.get("status") or "")
            campaign_id = str(metadata.get("campaign_id") or "")
            attempt_id = str(metadata.get("attempt_id") or "")
            task_id = str(metadata.get("task_id") or "")
            if status == "active":
                attempt = db.attempt_record(attempt_id)
                if attempt is None or str(attempt.get("task_id") or "") != task_id:
                    raise ValueError("active attempt has no matching database record")
                database_status = str(attempt.get("status") or "")
                if database_status in {"leased", "running"}:
                    continue
                if database_status == "succeeded":
                    raise ValueError("active attempt conflicts with a succeeded database result")
                _quarantine_attempt(
                    paths,
                    report,
                    task_id=task_id,
                    campaign_id=campaign_id,
                    attempt_id=attempt_id,
                    reason=f"reconciled_terminal_attempt:{database_status or 'unknown'}",
                )
                continue
            if status not in {"promotion_pending", "promotion_pending_db"}:
                continue
            workspace = find_attempt_workspace(
                paths,
                campaign_id=campaign_id,
                attempt_id=attempt_id,
            )
            if workspace is None:
                raise ValueError("attempt workspace disappeared during recovery")
            task = db.task(task_id)
            committed = bool(
                task
                and task.get("status") == "succeeded"
                and str(task.get("current_attempt_id") or "") == attempt_id
            )
            recovered = recover_attempt_promotion(
                workspace,
                database_committed=committed,
            )
            report.attempts_recovered.append(
                {
                    "task_id": task_id,
                    "attempt_id": attempt_id,
                    "campaign_id": campaign_id,
                    "status": str(recovered.get("status") or "unknown"),
                }
            )
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"Could not recover attempt workspace {metadata_path}: {exc}")


def _active_project_workstreams(
    paths: WorkspacePaths,
    report: TickReport,
) -> list[ProjectWorkstreamBinding]:
    """Discover generic projects, with old math plans retained as an adapter."""

    bindings: list[ProjectWorkstreamBinding] = []
    seen: set[str] = set()
    root = paths.data / "workspaces"
    labs = discover_labs(paths.code)
    project_paths = {
        *root.glob("*/projects/*/project.json"),
        *root.glob("*/production/*/project.json"),
    }
    for project_path in sorted(project_paths):
        try:
            project = load_project(project_path)
            if project.status != "active":
                continue
            lab = lab_for_domain(labs, project.domain)
            domain_root = (root / project.domain).resolve()
            if not _inside(project.path, (domain_root,)):
                raise ValueError("project config is outside its declared domain workspace")
            if project.domain_config_path is not None and not _inside(
                project.domain_config_path,
                (domain_root,),
            ):
                raise ValueError("project domain config escapes its domain workspace")
            for resource in project.read_resources:
                if not _inside(resource.path, (domain_root, paths.code)):
                    raise ValueError(
                        f"project read resource {resource.label!r} escapes its domain workspace"
                    )
            protocol = lab.protocol(project.protocol_id)
            if protocol is None:
                raise ValueError(
                    f"lab {lab.lab_id} does not register protocol {project.protocol_id!r}"
                )
            if protocol.primary_skill != project.primary_skill:
                raise ValueError(
                    f"project primary skill {project.primary_skill!r} differs from protocol "
                    f"registration {protocol.primary_skill!r}"
                )
            selected_skill = lab.skill_path(project.primary_skill)
            if selected_skill is None or not selected_skill.is_file():
                raise ValueError(f"unknown project primary skill: {project.primary_skill}")
            for workstream in project.workstreams:
                if workstream.startup != "active":
                    continue
                if not _inside(workstream.state_path, (domain_root,)):
                    raise ValueError(
                        f"workstream {workstream.workstream_id} escapes its domain workspace"
                    )
                validation = validate_protocol_state(
                    lab,
                    protocol,
                    project_path=project.path,
                    workstream_path=workstream.state_path,
                    mode="discovery",
                )
                if not validation.valid:
                    raise ValueError(
                        f"protocol rejected {workstream.workstream_id}: "
                        + "; ".join(validation.errors)
                    )
                if workstream.workstream_id in seen:
                    raise ValueError(
                        f"workstream {workstream.workstream_id} appears in more than one project"
                    )
                seen.add(workstream.workstream_id)
                bindings.append(
                    ProjectWorkstreamBinding(
                        project_id=project.project_id,
                        project_path=project.path,
                        workstream_id=workstream.workstream_id,
                        title=workstream.title,
                        workstream_path=workstream.state_path,
                        domain=project.domain,
                        priority=workstream.priority,
                        protocol_id=project.protocol_id,
                        primary_skill=project.primary_skill,
                        execution_policy=project.execution,
                        workstream_policy={
                            **workstream.policy(),
                            "objective": workstream.objective or project.objective,
                        },
                    )
                )
        except (
            OSError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
            subprocess.TimeoutExpired,
        ) as exc:
            report.errors.append(f"Invalid project config {project_path}: {exc}")

    for plan_path in sorted(root.glob("*/production/*/production_plan.json")):
        try:
            if (plan_path.parent / "project.json").is_file():
                continue
            plan = _read_json_object(plan_path)
            if str(plan.get("status") or "") != "active":
                continue
            if plan.get("schema_version") != "openlabs.math_production_plan.v1":
                raise ValueError("unsupported production plan schema")
            plan_id = str(plan.get("plan_id") or "").strip()
            lanes = plan.get("lanes")
            if not plan_id or not isinstance(lanes, list):
                raise ValueError("active production plan needs plan_id and lanes")
            domain = plan_path.parents[2].name
            for item in lanes:
                if not isinstance(item, Mapping) or item.get("startup", "active") != "active":
                    continue
                lane_id = str(item.get("lane_id") or "").strip()
                config_path = str(item.get("config_path") or "").strip()
                if not lane_id or not config_path:
                    raise ValueError("active lane needs lane_id and config_path")
                lane_path = (plan_path.parent / config_path).resolve()
                if not _inside(lane_path, (paths.data,)) or not lane_path.is_file():
                    raise ValueError(f"invalid lane path for {lane_id}: {lane_path}")
                lane = _read_json_object(lane_path)
                if lane.get("lane_id") != lane_id or lane.get("plan_id") != plan_id:
                    raise ValueError(f"lane identity mismatch for {lane_id}")
                if str(lane.get("stage") or "") == "terminal":
                    report.production_blocked.append(
                        {"campaign_id": lane_id, "reason": "lane_terminal"}
                    )
                    continue
                if lane_id in seen:
                    raise ValueError(f"lane {lane_id} appears in more than one active plan")
                seen.add(lane_id)
                bindings.append(
                    ProjectWorkstreamBinding(
                        project_id=plan_id,
                        project_path=plan_path.resolve(),
                        workstream_id=lane_id,
                        title=str(
                            (lane.get("theme") or {}).get("name")
                            if isinstance(lane.get("theme"), Mapping)
                            else lane_id
                        )
                        or lane_id,
                        workstream_path=lane_path,
                        domain=domain,
                        priority=int(item.get("priority") or 0),
                        protocol_id="legacy-production-plan",
                        primary_skill="math-production-supervisor",
                        execution_policy=ExecutionPolicy(),
                        workstream_policy={
                            "runtime_skills": [
                                "math-production-supervisor",
                                "amra-research-loop",
                            ]
                        },
                        legacy_plan_path=plan_path.resolve(),
                    )
                )
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            report.errors.append(f"Invalid production plan {plan_path}: {exc}")
    return bindings


def _sync_active_projects(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    report: TickReport,
) -> None:
    bindings = _active_project_workstreams(paths, report)
    desired = {binding.workstream_id for binding in bindings}
    active_project_paths = {
        str(binding.project_path) for binding in bindings if binding.legacy_plan_path is None
    }
    try:
        program_held = program_autonomy.held_campaigns(paths, settings)
    except (OSError, TopicLedgerError, ValueError) as exc:
        report.errors.append(f"program held campaigns: {exc}")
        program_held = set()
    for campaign in db.project_campaigns():
        campaign_id = str(campaign["campaign_id"])
        if campaign_id in desired:
            continue
        if str(campaign.get("status") or "") == "frozen":
            # A frozen topic is terminal for its campaign; never pause/rebind it.
            continue
        if campaign_id in program_held:
            # A ready-queued or submitted topic: its research campaign stays paused.
            continue
        policy = workstream_policy(campaign)
        if (
            policy.get("dynamic") is True
            and str(campaign.get("project_config_path") or "") in active_project_paths
        ):
            try:
                state_status = _workstream_state_status(campaign)
                if state_status in {"paused", "completed"}:
                    if not db.has_active_tasks(campaign_id) and not db.has_queued_tasks(
                        campaign_id
                    ):
                        db.pause_production_campaign(
                            campaign_id,
                            reason=f"agent_workstream_{state_status}",
                        )
                        report.production_paused.append(campaign_id)
                    continue
                project = load_project(str(campaign["project_config_path"]))
                domain_root = (paths.data / "workspaces" / project.domain).resolve()
                for resource in project.read_resources:
                    if not _inside(resource.path, (domain_root, paths.code)):
                        raise ValueError(
                            f"project read resource {resource.label!r} escapes its domain workspace"
                        )
                protocol_errors = _validate_bound_protocol(
                    paths,
                    campaign,
                    mode="discovery",
                )
                if protocol_errors:
                    raise ValueError("; ".join(protocol_errors))
                db.configure_project_campaign(
                    campaign_id,
                    project_config_path=str(project.path),
                    workstream_state_path=str(campaign["workstream_state_path"]),
                    protocol_id=project.protocol_id,
                    primary_skill=project.primary_skill,
                    execution_policy=project.execution.to_dict(),
                    project_id=project.project_id,
                    workstream_policy=policy,
                    priority=int(campaign.get("priority") or 0),
                    max_agent_seconds=(
                        int(policy["max_agent_seconds"])
                        if isinstance(policy.get("max_agent_seconds"), int)
                        and not isinstance(policy.get("max_agent_seconds"), bool)
                        and int(policy["max_agent_seconds"]) > 0
                        else settings.max_campaign_agent_seconds
                    ),
                )
                report.production_synced.append(campaign_id)
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                db.pause_production_campaign(
                    campaign_id,
                    reason=f"dynamic_binding_invalid:{exc}",
                )
                report.production_blocked.append(
                    {"campaign_id": campaign_id, "reason": f"dynamic_binding_invalid:{exc}"}
                )
            continue
        if not bool(campaign.get("continuous")) and str(campaign.get("status")) != "active":
            continue
        db.pause_production_campaign(
            campaign_id,
            reason="lane_not_in_active_production_desired_state",
        )
        report.production_paused.append(campaign_id)

    enforce_admission = settings.program.enabled and settings.program.enforce_admission
    ledger_document: Mapping[str, Any] | None = None
    if enforce_admission:
        try:
            ledger_document = open_topic_ledger(paths, settings.program).read()
        except (OSError, TopicLedgerError) as exc:
            report.errors.append(f"program enforce_admission: {exc}")
            ledger_document = {"topics": []}
    program_project_paths: dict[Path, bool] = {}
    for binding in bindings:
        configured_budget = binding.workstream_policy.get("max_agent_seconds")
        max_agent_seconds = (
            int(configured_budget)
            if isinstance(configured_budget, int)
            and not isinstance(configured_budget, bool)
            and configured_budget > 0
            else settings.max_campaign_agent_seconds
        )
        campaign = db.campaign(binding.workstream_id)
        if campaign is not None and str(campaign.get("status") or "") == "frozen":
            # Like a paused workstream: skip silently and never reactivate it.
            continue
        if (
            enforce_admission
            and campaign is None
            and binding.legacy_plan_path is None
            and str(binding.workstream_policy.get("default_agent_role") or "researcher")
            in {"researcher", "experimenter"}
        ):
            if binding.project_path not in program_project_paths:
                program_project_paths[binding.project_path] = load_project(
                    binding.project_path
                ).program
            if not program_project_paths[binding.project_path] and not workstream_admitted(
                ledger_document or {}, binding.workstream_id
            ):
                # New research starts only behind the admission gate.
                report.production_blocked.append(
                    {
                        "campaign_id": binding.workstream_id,
                        "reason": "topic_not_admitted",
                        "hint": (
                            "submit a topic card (python -m openlabs program submit-card) "
                            "to the admission gate first"
                        ),
                    }
                )
                continue
        if binding.legacy_plan_path is None:
            bound_state_status = str(
                _read_json_object(binding.workstream_path).get("status") or ""
            ).strip()
            if bound_state_status in {"paused", "completed"}:
                if campaign is not None and (
                    bool(campaign.get("continuous"))
                    or str(campaign.get("status") or "") == "active"
                ):
                    db.pause_production_campaign(
                        binding.workstream_id,
                        reason=f"agent_workstream_{bound_state_status}",
                    )
                    report.production_paused.append(binding.workstream_id)
                continue
        if campaign is None:
            db.register_campaign(
                binding.workstream_id,
                domain=binding.domain,
                title=binding.title,
                priority=binding.priority,
                state_path=str(binding.workstream_path.parent),
                source=str(binding.project_path),
                max_agent_seconds=max_agent_seconds,
            )
            campaign = db.campaign(binding.workstream_id)
        if campaign is None or str(campaign.get("domain")) != binding.domain:
            report.production_blocked.append(
                {"campaign_id": binding.workstream_id, "reason": "campaign_domain_mismatch"}
            )
            continue
        campaign_status = str(campaign.get("status"))
        budget_reauthorized = (
            campaign_status == "budget_exhausted"
            and max_agent_seconds > float(campaign.get("agent_seconds_used") or 0)
        )
        if campaign_status not in {"active", "production_paused"} and not budget_reauthorized:
            report.production_blocked.append(
                {
                    "campaign_id": binding.workstream_id,
                    "reason": f"campaign_status_{campaign.get('status')}",
                }
            )
            continue
        if binding.legacy_plan_path is not None:
            db.configure_continuous_campaign(
                binding.workstream_id,
                production_plan_path=str(binding.legacy_plan_path),
                production_lane_path=str(binding.workstream_path),
                priority=binding.priority,
                max_agent_seconds=max_agent_seconds,
            )
        else:
            db.configure_project_campaign(
                binding.workstream_id,
                project_config_path=str(binding.project_path),
                workstream_state_path=str(binding.workstream_path),
                protocol_id=binding.protocol_id,
                primary_skill=binding.primary_skill,
                execution_policy=binding.execution_policy.to_dict(),
                project_id=binding.project_id,
                workstream_policy=binding.workstream_policy,
                priority=binding.priority,
                max_agent_seconds=max_agent_seconds,
            )
        report.production_synced.append(binding.workstream_id)


def _fallback_project_action(
    campaign: Mapping[str, Any],
    execution_policy: ExecutionPolicy,
) -> ActionPlan:
    lane_value = campaign.get("workstream_state_path") or campaign.get("production_lane_path")
    project_value = campaign.get("project_config_path") or campaign.get("production_plan_path")
    lane_path = Path(str(lane_value))
    plan_path = Path(str(project_value))
    if campaign.get("project_config_path"):
        stream_policy = workstream_policy(campaign)
        role = str(stream_policy.get("default_agent_role") or "researcher")
        session_mode = str(
            stream_policy.get("default_session_mode")
            or ("fresh" if role == "reviewer" else execution_policy.default_session_mode)
        )
        configured_objective = str(stream_policy.get("objective") or "").strip()
        objective = (
            f"Own project workstream {campaign['campaign_id']} under protocol "
            f"{campaign.get('protocol_id')} and Skill {campaign.get('primary_skill')}. Read the "
            f"project config {plan_path}, workstream state {lane_path}, durable checkpoints, and "
            "available research index. "
            + (configured_objective + " " if configured_objective else "")
            + "You own every scientific choice: freely create, combine, switch, pause, revive, "
            "or abandon routes and choose any useful installed tool. Treat configured themes and "
            "prior routes as context, never as an exhaustive menu or mandatory sequence. Persist "
            "a truthful evidence-bound checkpoint and an executable continuation when useful."
        )
        resources_value = stream_policy.get("resources")
        resources = (
            ResourceVector.from_mapping(resources_value)
            if isinstance(resources_value, Mapping)
            else None
        )
        wall_seconds_value = stream_policy.get("wall_seconds")
        wall_seconds = (
            int(wall_seconds_value)
            if isinstance(wall_seconds_value, int)
            and not isinstance(wall_seconds_value, bool)
            and wall_seconds_value > 0
            else None
        )
    else:
        resources = None
        wall_seconds = None
        role = "researcher"
        session_mode = execution_policy.default_session_mode
        lane = _read_json_object(lane_path)
        stage = str(lane.get("stage") or "radar")
        cycle = int(lane.get("cycle") or 1)
        if stage not in {"radar", "research"}:
            objective = (
                f"Recover terminal production lane {campaign['campaign_id']} from {lane_path}. "
                "Preserve its terminal evidence and return no successor work. The control plane "
                "must pause this lane until administrator-owned desired state changes."
            )
        else:
            objective = (
                f"Resume active production lane {campaign['campaign_id']} at stage {stage}, cycle "
                f"{cycle}. Read {lane_path}, {plan_path}, all durable lane checkpoints, and the "
                "assigned Skills. Autonomously choose and execute the highest-information "
                "admissible research episode that materially advances or falsifies the lane, "
                "then leave one coherent evidence-bound checkpoint and an executable "
                "continuation. Preserve every configured scientific and transaction gate."
            )
    return ActionPlan(
        objective=objective,
        agent_role=role,
        session_mode=session_mode,
        handoff_kind="role_handoff",
        resources=resources,
        wall_seconds=wall_seconds,
    )


def _workstream_state_status(campaign: Mapping[str, Any]) -> str | None:
    value = str(campaign.get("workstream_state_path") or "").strip()
    if not value:
        return None
    state_path = Path(value).expanduser().resolve()
    if not state_path.is_file():
        return None
    status = str(_read_json_object(state_path).get("status") or "").strip()
    return status or None


def _campaign_runtime_skill_ids(
    lab: LabManifest,
    campaign: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    if campaign is None:
        return ()
    stream_policy = workstream_policy(campaign)
    configured = stream_policy.get("runtime_skills")
    if isinstance(configured, list):
        return tuple(str(item) for item in configured)
    protocol_id = str(campaign.get("protocol_id") or "").strip()
    protocol = lab.protocol(protocol_id) if protocol_id else None
    if protocol is not None:
        return protocol.runtime_skills
    primary = str(campaign.get("primary_skill") or "").strip()
    if primary:
        return (primary,)
    if campaign.get("production_plan_path") or campaign.get("production_lane_path"):
        return tuple(str(item["skill_id"]) for item in lab.skills)
    return ()


def _campaign_execution_policy(campaign: Mapping[str, Any]) -> ExecutionPolicy:
    raw = campaign.get("execution_policy_json")
    if isinstance(raw, str) and raw.strip():
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = None
        if isinstance(value, Mapping):
            boundaries = value.get("fresh_session_boundaries")
            if isinstance(boundaries, list) and all(
                isinstance(item, str) and item.strip() for item in boundaries
            ):
                return ExecutionPolicy(
                    default_session_mode=str(value.get("default_session_mode") or "resume"),
                    fresh_session_boundaries=tuple(item.strip() for item in boundaries),
                )
    return ExecutionPolicy()


def _bound_protocol(
    paths: WorkspacePaths,
    campaign: Mapping[str, Any],
) -> tuple[LabManifest, ProtocolManifest] | None:
    """Resolve a generic project protocol while keeping domain code out of core."""

    project_value = str(campaign.get("project_config_path") or "").strip()
    state_value = str(campaign.get("workstream_state_path") or "").strip()
    protocol_id = str(campaign.get("protocol_id") or "").strip()
    if not project_value and not state_value and not protocol_id:
        return None
    if not project_value or not state_value or not protocol_id:
        raise ValueError("generic project binding is incomplete")
    lab = lab_for_domain(discover_labs(paths.code), str(campaign.get("domain") or ""))
    protocol = lab.protocol(protocol_id)
    if protocol is None:
        raise ValueError(f"lab {lab.lab_id} does not register protocol {protocol_id!r}")
    return lab, protocol


def _campaign_uses_protocol_hook(
    paths: WorkspacePaths,
    campaign: Mapping[str, Any] | None,
    hook_id: str,
) -> bool:
    if campaign is None:
        return False
    binding = _bound_protocol(paths, campaign)
    return bool(binding and binding[1].hook(hook_id) is not None)


def _protocol_continuation(
    db: FactoryDB,
    paths: WorkspacePaths,
    campaign: Mapping[str, Any],
    *,
    latest: Mapping[str, Any] | None,
    latest_result: Mapping[str, Any] | None,
    execution_policy: ExecutionPolicy,
) -> ProtocolContinuation | None:
    """Ask an optional lab hook for a typed scheduling decision.

    Only the transport-level decision and task envelope are interpreted here.
    Stage names, evidence labels, promotion rules, and budget allocation remain
    opaque lab-owned data.
    """

    binding = _bound_protocol(paths, campaign)
    if binding is None:
        return None
    lab, protocol = binding
    if protocol.hook("continuation") is None:
        return None
    campaign_id = str(campaign["campaign_id"])
    latest_summary = None
    if latest is not None:
        latest_summary = {
            key: latest.get(key)
            for key in (
                "task_id",
                "task_type",
                "status",
                "agent_role",
                "session_mode",
                "runner",
                "routing_reason",
                "max_wall_seconds",
                "result_sha256",
            )
        }
    context = {
        "schema_version": "openlabs.protocol_hook_context.v1",
        "event": "continuation",
        "campaign": {
            "campaign_id": campaign_id,
            "domain": campaign.get("domain"),
            "project_id": campaign.get("project_id"),
            "workstream_id": campaign_id,
            "agent_seconds_used": float(campaign.get("agent_seconds_used") or 0),
            "max_agent_seconds": int(campaign.get("max_agent_seconds") or 0),
            "production_epoch": int(campaign.get("production_epoch") or 1),
        },
        "latest_task": latest_summary,
        "latest_result": dict(latest_result) if latest_result is not None else None,
        "routing_usage": db.campaign_routing_usage(campaign_id),
        "project_workstreams": db.project_workstream_activity(
            str(campaign.get("project_id") or "")
        ),
    }
    result = run_protocol_hook(
        lab,
        protocol,
        "continuation",
        project_path=Path(str(campaign["project_config_path"])).expanduser().resolve(),
        workstream_path=Path(str(campaign["workstream_state_path"])).expanduser().resolve(),
        context=context,
    )
    if result is None:  # pragma: no cover - checked above for clarity.
        return None
    if not result.valid:
        raise ValueError("; ".join(result.errors))
    payload = result.payload
    if payload.get("schema_version") != "openlabs.protocol_hook_decision.v1":
        raise ValueError("protocol continuation hook returned an unsupported schema")
    decision = str(payload.get("decision") or "").strip()
    if decision not in {"continue", "pause", "defer", "default"}:
        raise ValueError(
            "protocol continuation decision must be continue, pause, defer, or default"
        )
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise ValueError("protocol continuation decision requires a reason")
    if decision != "continue":
        if payload.get("action") is not None or payload.get("routing_key") is not None:
            raise ValueError("only a continue decision may include action or routing_key")
        return ProtocolContinuation(decision=decision, reason=reason)
    current_role = str(latest.get("agent_role") or "researcher") if latest else "researcher"
    action = _next_action_plan(
        payload.get("action"),
        current_role=current_role,
        execution_policy=execution_policy,
    )
    if action is None:
        raise ValueError("protocol continuation action is invalid")
    routing_key = str(payload.get("routing_key") or "").strip()
    if not IDENTIFIER.fullmatch(routing_key):
        raise ValueError("protocol continuation routing_key is invalid")
    return ProtocolContinuation(
        decision=decision,
        reason=reason,
        action=action,
        routing_key=routing_key,
    )


def _attempt_project_config_errors(
    campaign: Mapping[str, Any],
    attempt_workspace: AttemptWorkspace,
) -> tuple[str, ...]:
    """Keep administrator/control-plane project inputs immutable inside attempts."""

    canonical_project_path = Path(
        str(campaign.get("project_config_path") or "")
    ).expanduser().resolve()
    project = load_project(canonical_project_path)
    canonical_paths = [canonical_project_path]
    if project.domain_config_path is not None:
        canonical_paths.append(project.domain_config_path)
    errors: list[str] = []
    for canonical in canonical_paths:
        staged = Path(str(attempt_workspace.map_path(canonical))).resolve()
        if not staged.is_file():
            errors.append(f"attempt project input is missing: {canonical.name}")
        elif sha256_file(staged) != sha256_file(canonical):
            errors.append(f"attempt modified administrator-owned project input: {canonical.name}")
    return tuple(errors)


def _validate_bound_protocol(
    paths: WorkspacePaths,
    campaign: Mapping[str, Any],
    *,
    attempt_workspace: AttemptWorkspace | None = None,
    task: Mapping[str, Any] | None = None,
    mode: str = "commit",
) -> tuple[str, ...]:
    binding = _bound_protocol(paths, campaign)
    if binding is None:
        return ()
    lab, protocol = binding
    project_path = Path(str(campaign["project_config_path"])).expanduser().resolve()
    state_path = Path(str(campaign["workstream_state_path"])).expanduser().resolve()
    validation_context: dict[str, Any] | None = None
    if attempt_workspace is not None:
        config_errors = _attempt_project_config_errors(campaign, attempt_workspace)
        if config_errors:
            return config_errors
        if task is None:
            return ("attempt protocol validation requires authenticated task identity",)
        validation_context = {
            "schema_version": "openlabs.protocol_validation_context.v1",
            "event": "attempt_commit",
            "task": {
                "task_id": task.get("task_id"),
                "attempt_id": task.get("current_attempt_id"),
                "agent_role": task.get("agent_role"),
                "session_mode": task.get("session_mode"),
                "routing_reason": task.get("routing_reason"),
            },
            "canonical": {
                "project_config": str(project_path),
                "workstream_state": str(state_path),
            },
        }
        project_path = Path(str(attempt_workspace.map_path(project_path))).resolve()
        state_path = Path(str(attempt_workspace.map_path(state_path))).resolve()
    validation = validate_protocol_state(
        lab,
        protocol,
        project_path=project_path,
        workstream_path=state_path,
        mode=mode,
        validation_context=validation_context,
    )
    return validation.errors if not validation.valid else ()


def _binding_repair_objective(task: Mapping[str, Any]) -> str:
    return (
        "Repair only the result-bundle evidence packaging rejected by the OpenLabs gate. "
        "For every artifact named in last_error, materialize the exact referenced bytes under "
        "this campaign workspace, verify the declared SHA-256, and emit file:// URIs to those "
        "present local files. Preserve the prior scientific status, claims, limitations, failed "
        "v1/v2 evidence, and executable next action unchanged. Do not repeat the literature "
        "audit, generate CNF, start a solver, or begin downstream science. Re-run all local "
        "artifact checks before returning. The prior result gate classified this as an artifact "
        f"binding defect. Gate detail: {task.get('last_error')}"
    )


def _production_task_id(campaign_id: str, epoch: int, source: str) -> str:
    digest = hashlib.sha256(f"{campaign_id}\0{epoch}\0{source}".encode()).hexdigest()
    return f"production:{epoch}:{digest[:32]}"


def _worker_unit_name(task: Mapping[str, Any]) -> str:
    identity = f"{task['task_id']}\0{task['current_attempt_id']}"
    digest = hashlib.sha256(identity.encode()).hexdigest()[:24]
    return f"openlabs-worker-{digest}.service"


def _user_systemd_available() -> bool:
    systemctl = shutil.which("systemctl")
    if systemctl is None:
        return False
    completed = subprocess.run(
        [systemctl, "--user", "show-environment"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.returncode == 0


# Same marker bin/openlabs-resource-guard uses to select its container path.
_CONTAINER_MARKER = Path("/.dockerenv")
_CONTAINER_CGROUP = Path("/sys/fs/cgroup")
_MATH_LIMITS = {
    "memory.high": 16 * 1024**3,
    "memory.max": 18 * 1024**3,
    "memory.swap.max": 0,
}


def _in_container() -> bool:
    return _CONTAINER_MARKER.exists()


_PROC_CGROUP = Path("/proc/self/cgroup")
_PARENT_CMDLINE: Path | None = None  # tests override; default is the live parent


def per_command_guard_refusal() -> str | None:
    """Refuse a container tick whose own parent is a per-command resource guard.

    In Docker, workers are plain detached children (no systemd-run). gpu_guard.py
    is a child subreaper that kills every descendant when its command exits, so a
    tick started as ``openlabs-resource-guard -- python -m openlabs tick`` would
    have its workers killed about a second after launch. Run the tick loop inside
    one long-lived guard instead (the tick's parent is then the loop).
    """

    if not _in_container():
        return None
    try:
        source = _PARENT_CMDLINE or Path(f"/proc/{os.getppid()}/cmdline")
        argv = source.read_bytes().split(b"\0")
    except OSError:
        return None
    if not any(Path(item.decode(errors="replace")).name == "gpu_guard.py" for item in argv):
        return None
    return (
        "this tick runs directly under a per-command resource guard inside a container; "
        "the guard would kill every worker it starts when the tick exits. Run ticks from a "
        "loop that is itself inside one long-lived openlabs-resource-guard"
    )


def _inside_worker_slice() -> bool:
    """Same inherited-guard test as bin/openlabs-resource-guard."""

    try:
        text = _PROC_CGROUP.read_text(encoding="utf-8")
    except OSError:
        return False
    return re.search(r"(^|/)openlabs-workers\.slice(/|$)", text, re.MULTILINE) is not None


def _container_math_cgroup_verified(root: Path) -> bool:
    """True only when this cgroup itself enforces the approved math budget."""

    try:
        for name, expected in _MATH_LIMITS.items():
            if (root / name).read_text().strip() != str(expected):
                return False
        pids = (root / "pids.max").read_text().strip()
        return pids != "max" and 0 < int(pids) <= 512
    except (OSError, ValueError):
        return False


def _container_worker_command(
    task: Mapping[str, Any], paths: WorkspacePaths, job_path: Path
) -> list[str]:
    """Verify the Docker cgroup and return the wrapper-guarded worker command.

    Without a systemd user manager the container's own cgroup is the aggregate
    boundary, so its kernel limits are checked here (clear error before any
    launch) and again by bin/openlabs-resource-guard when the worker starts.
    """

    from . import container_guard

    try:
        container_guard.validate(_CONTAINER_CGROUP)
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            f"container resource guard refused worker launch: {exc}"
        ) from exc
    if str(task.get("domain") or "") == "math" and not _container_math_cgroup_verified(
        _CONTAINER_CGROUP
    ):
        raise RuntimeError(
            "Math worker requires the approved shared 16/18 GiB, no-swap math cgroup; "
            "this container has no dedicated math cgroup (its aggregate container limit "
            "is not the math budget), refusing to launch"
        )
    return [
        str(paths.code / "bin" / "openlabs-resource-guard"), "--task-type", "cpu", "--",
        sys.executable, "-m", "openlabs", "_worker", str(job_path),
    ]


def _launch_worker(
    *,
    task: Mapping[str, Any],
    paths: WorkspacePaths,
    job_path: Path,
    log_path: Path,
    environment: Mapping[str, str],
    cpu_ceiling_threads: int | None = None,
) -> int | None:
    """Launch a worker outside the short-lived tick service cgroup when supervised."""

    if _in_container():
        command = _container_worker_command(task, paths, job_path)
        with log_path.open("ab") as log_handle:
            process = subprocess.Popen(
                command,
                cwd=paths.code,
                env=dict(environment),
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        return process.pid

    command = [
        sys.executable, str(Path(__file__).with_name("gpu_guard.py")), "--task-type", "cpu", "--",
        sys.executable, "-m", "openlabs", "_worker", str(job_path),
    ]
    worker_slice = "openlabs-workers.slice"
    if str(task.get("domain") or "") == "math":
        worker_slice = "openlabs-workers-math.slice"
        checked = subprocess.run(
            ["systemctl", "--user", "show", worker_slice,
             "--property=LoadState", "--property=MemoryHigh",
             "--property=MemoryMax", "--property=MemorySwapMax"],
            capture_output=True, text=True, check=False,
        )
        properties = dict(
            line.split("=", 1) for line in checked.stdout.splitlines() if "=" in line
        )
        expected = {"LoadState": "loaded", "MemoryHigh": str(16 * 1024**3),
                    "MemoryMax": str(18 * 1024**3), "MemorySwapMax": "0"}
        if checked.returncode != 0 or any(properties.get(k) != v for k, v in expected.items()):
            raise RuntimeError("Math worker requires the approved shared 16/18 GiB, no-swap slice")
        command = [str(paths.code / "bin" / "openlabs-math-resource-guard"), "--", *command]
    if os.environ.get("INVOCATION_ID") or _user_systemd_available():
        systemd_run = shutil.which("systemd-run")
        if systemd_run is None:
            raise RuntimeError("systemd worker supervision requires systemd-run")
        unit = _worker_unit_name(task)
        reserved = task_resources(task)
        cpu_quota_threads = max(reserved.cpu_threads, int(cpu_ceiling_threads or 0))
        # Codex, Lean, Mathlib and language servers may create many short-lived
        # helper threads.  This is a crash guard, not a research-parallelism knob.
        tasks_max = max(512, reserved.cpu_threads * 128)
        launch = [
            systemd_run,
            "--user",
            "--quiet",
            "--collect",
            "--service-type=exec",
            f"--unit={unit}",
            f"--slice={worker_slice}",
            "--property=PartOf=openlabs-workers.target",
            "--property=KillMode=control-group",
            "--property=OOMPolicy=stop",
            # This is a scheduling estimate and reclaim hint, not a hard wall.
            # Tool adapters (Lean, Sage, SMT) own their phase-specific ceilings;
            # openlabs-workers.slice owns the aggregate hard ceiling.
            f"--property=MemoryHigh={reserved.memory_mib}M",
            f"--property=TasksMax={tasks_max}",
            f"--property=CPUQuota={cpu_quota_threads * 100}%",
            "--property=Nice=5",
            f"--property=StandardOutput=append:{log_path}",
            f"--property=StandardError=append:{log_path}",
            f"--working-directory={paths.code}",
        ]
        excluded = {"INVOCATION_ID", "JOURNAL_STREAM", "SYSTEMD_EXEC_PID"}
        launch.extend(
            f"--setenv={name}"
            for name in sorted(environment)
            if name not in excluded and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
        )
        completed = subprocess.run(
            [*launch, *command],
            cwd=paths.code,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or f"exit code {completed.returncode}"
            raise RuntimeError(f"could not start transient worker {unit}: {detail}")
        shown = subprocess.run(
            ["systemctl", "--user", "show", unit, "--property=MainPID", "--value"],
            capture_output=True,
            text=True,
            check=False,
        )
        try:
            pid = int(shown.stdout.strip())
        except ValueError:
            pid = 0
        return pid or None

    # No container, no systemd: only an already-guarded caller (for example a
    # tick started from bin/openlabs-codex) may start a worker directly, because
    # gpu_guard.py adds no CPU/RAM/pids limit of its own.
    if not _inside_worker_slice():
        raise RuntimeError(
            "no resource guard for the worker: not in a verified container, no systemd "
            "user manager, and this process is not inside openlabs-workers.slice; "
            "refusing to launch"
        )
    with log_path.open("ab") as log_handle:
        process = subprocess.Popen(
            command,
            cwd=paths.code,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return process.pid


def _verified_result_payload(
    task: Mapping[str, Any],
    paths: WorkspacePaths,
) -> dict[str, Any] | None:
    value = str(task.get("result_path") or "").strip()
    if not value:
        return None
    result_path = Path(value).resolve()
    if not _inside(result_path, (paths.data, paths.artifacts)) or not result_path.is_file():
        raise ValueError(f"missing durable result for {task.get('task_id')}: {result_path}")
    expected = str(task.get("result_sha256") or "")
    if expected and sha256_file(result_path) != expected:
        raise ValueError(f"durable result hash changed for {task.get('task_id')}")
    return _read_json_object(result_path)


# Runner-level failure classes that say nothing about the science and are safe to
# retry unchanged. "launch_failed" is the attempt status of a failed worker launch.
INFRASTRUCTURE_FAILURE_CLASSES = frozenset(
    {
        "agent_transport",
        QUOTA_FAILURE_CLASS,
        "agent_connectivity_preflight",
        "agent_interrupted",
        "launch_failed",
    }
)


def _infrastructure_failure(
    db: FactoryDB,
    task: Mapping[str, Any],
) -> tuple[str | None, list[dict[str, str]]]:
    """Classify a blocked task's last attempt; return (class or None, evidence).

    Only classes the runner records explicitly count; anything else (scientific,
    contract, continuity, budget, lease expiry, unknown) returns None so the
    existing needs_human behaviour is kept.
    """

    attempts = db.task_attempts(str(task["task_id"]))
    if not attempts:
        return None, []
    evidence = [
        {"path": str(item["result_path"]), "sha256": str(item["result_sha256"])}
        for item in attempts
        if item.get("result_path") and item.get("result_sha256")
    ][-1:]
    last = attempts[-1]
    if str(last.get("status") or "") == "launch_failed":
        return "launch_failed", evidence
    runtime = last.get("runtime") if isinstance(last.get("runtime"), Mapping) else {}
    failure_class = str(runtime.get("failure_class") or "")
    if failure_class not in INFRASTRUCTURE_FAILURE_CLASSES:
        return None, evidence
    result_path = str(last.get("result_path") or "")
    if result_path:
        try:
            payload = _read_json_object(Path(result_path))
        except (OSError, TypeError, ValueError):
            payload = {}
        if payload.get("artifacts") or payload.get("claims"):
            # The agent produced scientific output; this is not a pure runner miss.
            return None, evidence
    return failure_class, evidence


def _triage_infrastructure_block(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    report: TickReport,
    campaign_id: str,
    latest: Mapping[str, Any],
) -> bool:
    """Retry or freeze a needs_human/quarantined task blocked by infrastructure.

    Returns True when handled (requeued or topic frozen); False keeps the
    existing needs_human behaviour.
    """

    task_id = str(latest["task_id"])
    failure_class, evidence = _infrastructure_failure(db, latest)
    if failure_class is None:
        return False
    retries = db.count_events("task", task_id, "infrastructure_retry")
    limit = settings.budget.infrastructure_retry_limit
    if retries < limit:
        retry = retries + 1
        not_before = retry_not_before(retry, settings.retry_backoff_seconds)
        if db.requeue_infrastructure_task(
            task_id,
            failure_class=failure_class,
            retry_count=retry,
            not_before=not_before,
        ):
            report.infrastructure_retried.append(
                {
                    "task_id": task_id,
                    "campaign_id": campaign_id,
                    "failure_class": failure_class,
                    "retry": retry,
                    "limit": limit,
                }
            )
            return True
        return False
    db.record_event_once(
        "task",
        task_id,
        "infrastructure_retry_exhausted",
        {"failure_class": failure_class, "retries": retries, "limit": limit},
        event_key=f"infrastructure_retry_exhausted:{retries}",
    )
    if not settings.program.enabled:
        return False
    try:
        ledger = open_topic_ledger(paths, settings.program)
        topic = topic_for_campaign(ledger.read(), campaign_id)
        if topic is None or str(topic.get("status") or "") not in FREEZABLE_STATUSES:
            return False
        if not evidence:
            report.errors.append(
                f"Cannot freeze topic {topic.get('topic_id')} for infrastructure: "
                f"task {task_id} has no result evidence"
            )
            return False
        freeze_topic(
            ledger,
            str(topic["topic_id"]),
            db=db,
            reason_class="infrastructure",
            evidence=evidence,
            decided_by="orchestrator:infrastructure_retry_limit",
        )
    except (OSError, TopicLedgerError, KeyError, ValueError) as exc:
        report.errors.append(f"Infrastructure freeze of {campaign_id} failed: {exc}")
        return False
    report.production_blocked.append(
        {"campaign_id": campaign_id, "reason": f"topic_frozen:infrastructure:{failure_class}"}
    )
    return True


def _replenish_continuous_campaign(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    report: TickReport,
    campaign: Mapping[str, Any],
) -> None:
    campaign_id = str(campaign["campaign_id"])
    if db.has_active_tasks(campaign_id):
        return
    latest = db.latest_task(campaign_id)
    if latest and str(latest.get("status")) in {"needs_human", "quarantined"}:
        if _triage_infrastructure_block(db, paths, settings, report, campaign_id, latest):
            return
        report.production_blocked.append(
            {"campaign_id": campaign_id, "reason": str(latest.get("status"))}
        )
        return
    stream_policy = workstream_policy(campaign)
    if stream_policy.get("continuation") == "on_demand":
        # Scheduled by a controller (the research-program topic scout) only.
        return
    if program_autonomy.campaign_on_hold(db, settings, campaign_id):
        # The topic waits for its direction decision; it decides what runs next.
        report.production_blocked.append(
            {"campaign_id": campaign_id, "reason": "direction_decision_pending"}
        )
        return
    latest_status = str(latest.get("status") or "") if latest else ""
    campaign = db.campaign(campaign_id) or dict(campaign)
    state_status = _workstream_state_status(campaign)
    if state_status in {"paused", "completed"}:
        db.pause_production_campaign(
            campaign_id,
            reason=f"agent_workstream_{state_status}",
        )
        report.production_paused.append(campaign_id)
        return
    room = _prepare_auto_task_room(
        db,
        campaign_id,
        settings,
        report,
        source_task_id=(str(latest["task_id"]) if latest else None),
    )
    if not room.allowed:
        report.production_blocked.append(
            {"campaign_id": campaign_id, "reason": "production_window_exhausted"}
        )
        return
    if db.has_queued_tasks(campaign_id):
        return
    if stream_policy.get("continuation") == "review_on_new_results":
        reconciled = reconcile_pending_portfolio_review(
            db,
            paths,
            settings,
            campaign,
        )
        if reconciled.reconciled:
            report.enqueued.extend(reconciled.spawned.task_ids)
            report.production_synced.extend(reconciled.spawned.campaign_ids)
            if reconciled.spawned.decisions:
                report.program.setdefault("admission_decisions", []).extend(
                    reconciled.spawned.decisions
                )
            return
        scheduled = schedule_portfolio_review(
            db,
            paths,
            settings,
            campaign,
            epoch=room.epoch,
        )
        if scheduled.task_id is not None:
            report.enqueued.append(scheduled.task_id)
            report.production_reseeded.append(campaign_id)
            scheduled_task = db.task(scheduled.task_id) or {}
            if str(scheduled_task.get("routing_reason") or "") == "topic_admission":
                report.program.setdefault("admissions_scheduled", []).append(
                    {
                        "task_id": scheduled.task_id,
                        "campaign_id": campaign_id,
                        "exclude_provider": scheduled_task.get("exclude_provider"),
                    }
                )
        elif scheduled.reason is not None:
            report.production_blocked.append(
                {"campaign_id": campaign_id, "reason": scheduled.reason}
            )
        return
    execution_policy = _campaign_execution_policy(campaign)
    payload = _verified_result_payload(latest, paths) if latest else None
    if (
        stream_policy.get("dynamic") is True
        and latest
        and str(latest.get("task_type") or "") == "paper_review"
        and payload
        and payload.get("paper_candidate") is True
    ):
        report.production_blocked.append(
            {"campaign_id": campaign_id, "reason": "candidate_paper_pipeline_complete"}
        )
        return
    current_role = str(latest.get("agent_role") or "researcher") if latest else "researcher"
    status = latest_status
    result_runtime = db.result_runtime(str(latest["task_id"])) if latest else {}
    failure_classes = (
        result_runtime.get("gate_failure_classes") if isinstance(result_runtime, Mapping) else None
    )
    binding_failure = bool(
        latest
        and status == "needs_replan"
        and isinstance(failure_classes, list)
        and "artifact_binding" in failure_classes
    )
    infrastructure_retry = bool(
        latest
        and payload
        and status == "needs_replan"
        and _missing_agent_bundle(payload, result_runtime)
    )
    protocol_continuation = (
        None
        if binding_failure or infrastructure_retry
        else _protocol_continuation(
            db,
            paths,
            campaign,
            latest=latest,
            latest_result=payload,
            execution_policy=execution_policy,
        )
    )
    if protocol_continuation is not None and protocol_continuation.decision in {
        "pause",
        "defer",
    }:
        if protocol_continuation.decision == "pause":
            db.pause_production_campaign(
                campaign_id,
                reason=f"protocol_hook:{protocol_continuation.reason}",
            )
            report.production_paused.append(campaign_id)
        report.production_blocked.append(
            {"campaign_id": campaign_id, "reason": protocol_continuation.reason}
        )
        return
    hook_managed = bool(
        protocol_continuation is not None
        and protocol_continuation.decision == "continue"
    )
    if hook_managed:
        assert protocol_continuation is not None
        action = protocol_continuation.action
    else:
        actions = payload.get("next_actions") if payload else None
        action = (
            _next_action_plan(
                actions[0],
                current_role=current_role,
                execution_policy=execution_policy,
            )
            if isinstance(actions, list) and actions
            else None
        )
        if (
            action is None
            and latest
            and latest_status == "succeeded"
            and str(latest.get("task_type") or "") == "paper_review"
            and not binding_failure
            and not infrastructure_retry
        ):
            # A review that did not pass names its own next step (writer revision,
            # evidence remediation or a direction decision); never reseed a generic
            # researcher from the fallback objective after it.
            report.production_blocked.append(
                {"campaign_id": campaign_id, "reason": "paper_review_without_next_action"}
            )
            return
        action = action or _fallback_project_action(campaign, execution_policy)
    if binding_failure:
        action = ActionPlan(
            objective=_binding_repair_objective(latest),
            agent_role="researcher",
            session_mode="resume",
            handoff_kind="evidence_remediation",
        )
    elif infrastructure_retry:
        assert latest is not None
        action = ActionPlan(
            objective=_infrastructure_retry_objective(db, latest),
            agent_role="researcher",
            session_mode="resume",
            handoff_kind="evidence_remediation",
        )
    elif (
        not hook_managed
        and status == "needs_replan"
        and action is not None
        and action.agent_role != "researcher"
    ):
        action = ActionPlan(
            objective=action.objective,
            agent_role="researcher",
            session_mode="resume",
            handoff_kind=action.handoff_kind,
            resources=action.resources,
            wall_seconds=action.wall_seconds,
            runner=action.runner,
        )
    if action is None:
        return
    if action.agent_role == "writer" and current_role != "writer":
        report.production_blocked.append(
            {"campaign_id": campaign_id, "reason": "unsafe_direct_writer_handoff"}
        )
        return
    if (
        latest
        and action.session_mode == "resume"
        and (
            action.agent_role != current_role
            or not latest.get("agent_session_id")
        )
    ):
        action = ActionPlan(
            objective=action.objective,
            agent_role=action.agent_role,
            session_mode="fresh",
            handoff_kind=action.handoff_kind,
            resources=action.resources,
            wall_seconds=action.wall_seconds,
            runner=action.runner,
        )
    source = (
        str(latest.get("result_sha256") or latest.get("task_id") or "seed") if latest else "seed"
    )
    task_id = _production_task_id(campaign_id, room.epoch, source)
    if db.task(task_id) is not None:
        return
    resources = action.resources or (
        task_resources(latest) if latest else default_task_resources(settings)
    )
    prior_wall_seconds = (
        int(latest.get("max_wall_seconds") or settings.max_task_wall_seconds)
        if latest
        else settings.max_task_wall_seconds
    )
    wall_seconds = min(
        action.wall_seconds or prior_wall_seconds,
        settings.max_task_wall_seconds,
    )
    if action.runner is not None:
        runner = action.runner
    elif status == "needs_replan":
        runner = "frontier"
    elif latest:
        runner = _inherited_runner(latest)
    else:
        runner = "balanced"
    db.enqueue_task(
        task_id=task_id,
        campaign_id=campaign_id,
        domain=str(campaign["domain"]),
        task_type=(
            "replan" if status == "needs_replan" else _continuation_task_type(action.agent_role)
        ),
        objective=action.objective,
        input_path=(
            str(latest.get("result_path"))
            if latest and latest.get("result_path")
            else str(
                Path(
                    str(
                        campaign.get("workstream_state_path")
                        or campaign.get("production_lane_path")
                    )
                ).parent
            )
        ),
        skill_path=(
            str(latest.get("skill_path"))
            if latest and latest.get("skill_path")
            else str(campaign.get("primary_skill") or "math-production-supervisor")
        ),
        runner=runner,
        routing_reason=(
            "production_gate_repair"
            if binding_failure
            else "infrastructure_retry"
            if infrastructure_retry
            else f"protocol_hook:{protocol_continuation.routing_key}"
            if hook_managed and protocol_continuation is not None
            else "production_rollover"
            if room.rolled_over
            else "production_idle_reseed"
        ),
        parent_task_id=(str(latest["task_id"]) if latest else None),
        agent_role=action.agent_role,
        session_mode=action.session_mode,
        priority=int(campaign.get("priority") or 0),
        max_attempts=settings.max_attempts,
        max_wall_seconds=wall_seconds,
        **resources.to_dict(),
    )
    report.enqueued.append(task_id)
    report.production_reseeded.append(campaign_id)


def _replenish_continuous_campaigns(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    report: TickReport,
) -> None:
    for campaign in db.continuous_campaigns():
        campaign_id = str(campaign["campaign_id"])
        try:
            _replenish_continuous_campaign(
                db,
                paths,
                settings,
                report,
                campaign,
            )
        except Exception as exc:  # noqa: BLE001
            report.production_blocked.append(
                {"campaign_id": campaign_id, "reason": "state_recovery_failed"}
            )
            report.errors.append(f"Could not replenish continuous campaign {campaign_id}: {exc}")


def _enqueue_paper_task(
    db: FactoryDB,
    report: TickReport,
    settings: FactorySettings,
    parent: Mapping[str, Any],
    *,
    task_id: str,
    domain: str,
    task_type: str,
    objective: str,
    input_path: str,
    skill_path: str | None,
    routing_reason: str,
    agent_role: str,
    session_mode: str = "fresh",
    session_source_task_id: str | None = None,
    resources: ResourceVector | None = None,
) -> bool:
    if db.task(task_id) is not None:
        return False
    db.enqueue_task(
        task_id=task_id,
        campaign_id=str(parent["campaign_id"]),
        domain=domain,
        task_type=task_type,
        objective=objective,
        input_path=input_path,
        skill_path=skill_path,
        runner="frontier",
        routing_reason=routing_reason,
        parent_task_id=str(parent["task_id"]),
        agent_role=agent_role,
        session_mode=session_mode,
        session_source_task_id=session_source_task_id,
        priority=int(parent.get("priority") or 0) + 1,
        max_attempts=settings.max_attempts,
        max_wall_seconds=settings.max_task_wall_seconds,
        **(resources or default_task_resources(settings)).to_dict(),
    )
    report.enqueued.append(task_id)
    return True


def _archive_receipt(receipt: Path, paths: WorkspacePaths, *, keep: bool) -> None:
    if not keep:
        receipt.unlink(missing_ok=True)
        return
    target = paths.receipt_archive / f"{receipt.stem}-{_timestamp_token()}.json"
    counter = 1
    while target.exists():
        target = paths.receipt_archive / f"{receipt.stem}-{_timestamp_token()}-{counter}.json"
        counter += 1
    receipt.replace(target)


def _quarantine_attempt(
    paths: WorkspacePaths,
    report: TickReport,
    *,
    task_id: str,
    campaign_id: str,
    attempt_id: str,
    reason: str,
) -> None:
    if not attempt_id:
        return
    metadata = quarantine_attempt_workspace(
        paths,
        campaign_id=campaign_id,
        attempt_id=attempt_id,
        reason=reason,
    )
    if metadata is None:
        return
    report.attempts_quarantined.append(
        {
            "task_id": task_id,
            "attempt_id": attempt_id,
            "campaign_id": campaign_id,
            "reason": reason,
        }
    )


def _apply_attempt_disposition(
    paths: WorkspacePaths,
    report: TickReport,
    disposition: AttemptDisposition,
) -> None:
    _quarantine_attempt(
        paths,
        report,
        task_id=disposition.task_id,
        campaign_id=disposition.campaign_id,
        attempt_id=disposition.attempt_id,
        reason=disposition.reason,
    )


def _codex_hook_receipt_status(
    runtime: Mapping[str, Any],
) -> tuple[str | None, str | None]:
    """Return a fatal hook error and an optional compatibility warning.

    The generated agent request already carries the task, Skill,
    transaction and result-path context. SessionStart remains useful as an
    additional Codex context channel, but some non-interactive CLI versions do
    not fire project-local SessionStart while still firing the trusted Stop
    hook. Stop is the authoritative result gate and must always be present.
    """

    agent = "Claude Code" if str(runtime.get("adapter") or "") == "claude" else "Codex"
    hooks = runtime.get("hooks")
    if not isinstance(hooks, Mapping) or hooks.get("schema_version") != (
        "openlabs.hook_runtime.v1"
    ):
        return f"{agent} lifecycle hook receipts are missing or invalid", None
    if hooks.get("stop_passed") is not True:
        return f"{agent} final Stop gate receipt is incomplete", None
    if int(hooks.get("session_start_count") or 0) < 1:
        return (
            None,
            (
                f"{agent} emitted no project-local SessionStart receipt; accepted because the "
                "trusted agent request carried the required context and the final Stop gate passed"
            ),
        )
    return None, None


def ingest_results(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    report: TickReport,
) -> None:
    roots = (paths.data, paths.artifacts)
    for receipt_path in sorted(paths.result_inbox.glob("*.json")):
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt_validation = validate_receipt(receipt)
            if not receipt_validation.valid:
                report.errors.append(
                    f"Invalid receipt {receipt_path.name}: {'; '.join(receipt_validation.errors)}"
                )
                _archive_receipt(receipt_path, paths, keep=settings.archive_result_receipts)
                continue
            task_id = str(receipt["task_id"])
            attempt_id = str(receipt["attempt_id"])
            task = db.task(task_id)
            if task is None:
                raise ValueError(f"Unknown task: {task_id}")
            campaign_binding = db.campaign(str(task["campaign_id"]))
            execution_policy = _campaign_execution_policy(campaign_binding or {})
            protocol_managed_continuation = _campaign_uses_protocol_hook(
                paths,
                campaign_binding,
                "continuation",
            )
            expected = {
                "attempt_id": task.get("current_attempt_id"),
                "campaign_id": task.get("campaign_id"),
                "lab_id": task.get("lab_id"),
                "domain": task.get("domain"),
                "agent_role": task.get("agent_role"),
            }
            if task.get("status") != "running":
                raise ValueError(f"Task {task_id} is not running")
            for key, expected_value in expected.items():
                if receipt.get(key) != expected_value:
                    raise ValueError(
                        f"Receipt {key} mismatch for {task_id}: "
                        f"{receipt.get(key)!r} != {expected_value!r}"
                    )
            runtime = dict(receipt["runtime"])
            _record_quota_reading(db, settings, report, task, runtime)
            result_path = Path(str(receipt["result_path"])).expanduser().resolve()
            actual_sha: str | None = None
            try:
                if not _inside(result_path, roots):
                    raise ValueError(f"Result is outside data/artifact roots: {result_path}")
                configured_output = str(task.get("output_path") or "").strip()
                if not configured_output:
                    raise ValueError(f"Task {task_id} has no bound output path")
                expected_result = Path(configured_output).resolve()
                if result_path != expected_result:
                    raise ValueError(f"Receipt points to the wrong output path for {task_id}")
                actual_sha = sha256_file(result_path)
                if actual_sha != receipt["sha256"]:
                    raise ValueError(f"Result hash mismatch for {task_id}")
                payload = json.loads(result_path.read_text(encoding="utf-8"))
                if not isinstance(payload, Mapping):
                    raise TypeError(f"Result bundle is not an object: {result_path}")
                payload_identity = {
                    "task_id": task_id,
                    "campaign_id": task["campaign_id"],
                    "lab_id": task["lab_id"],
                    "domain": task["domain"],
                }
                for key, expected_value in payload_identity.items():
                    if payload.get(key) != expected_value:
                        raise ValueError(f"Result {key} mismatch for {task_id}")
            except Exception as exc:  # noqa: BLE001
                reason = f"result_rejected:{exc}"
                disposition = db.reject_attempt(
                    task_id,
                    attempt_id=attempt_id,
                    reason=reason,
                    result_path=str(result_path),
                    result_sha256=actual_sha,
                    run_seconds=float(runtime.get("duration_seconds") or 0.0),
                    runtime=runtime,
                    retry_backoff_seconds=settings.retry_backoff_seconds,
                )
                _apply_attempt_disposition(paths, report, disposition)
                if disposition.status == "quarantined":
                    report.quarantined.append(task_id)
                report.errors.append(f"Rejected result for {task_id}: {exc}")
                _archive_receipt(receipt_path, paths, keep=settings.archive_result_receipts)
                continue
            assert actual_sha is not None
            quota_exhausted = False
            if _quota_failure(payload, runtime):
                if _defer_quota_failure(
                    db,
                    paths,
                    settings,
                    report,
                    task=task,
                    attempt_id=attempt_id,
                    runtime=runtime,
                    result_path=result_path,
                    result_sha256=actual_sha,
                ):
                    _archive_receipt(receipt_path, paths, keep=settings.archive_result_receipts)
                    continue
                quota_exhausted = True
            # A research result of an admitted topic is held to the ledger's
            # pre-registration (None: no topic, or the program is disabled).
            preregistration = program_autonomy.expected_preregistration(
                paths, settings, task, report
            )
            gate = evaluate_result_bundle(
                payload, allowed_roots=roots, preregistration_sha256=preregistration
            )
            attempt_workspace = find_attempt_workspace(
                paths,
                campaign_id=str(task["campaign_id"]),
                attempt_id=attempt_id,
            )
            result_status = str(payload.get("status") or "failed")
            runtime_error: str | None = None
            if bool(runtime.get("timed_out")):
                result_status = "needs_replan"
                runtime_error = "Agent process timed out"
            elif int(runtime["exit_code"]) != 0:
                result_status = "failed"
                runtime_error = f"Lab runner exited with code {runtime['exit_code']}"
            if quota_exhausted:
                # Past quota_retry_limit the run is treated as an ordinary failure.
                result_status = "failed"
                runtime_error = runtime_error or (
                    f"agent_quota repeated {runtime.get('consecutive_quota_failures')} times; "
                    "quota retry limit exhausted"
                )
            next_actions = payload.get("next_actions", [])
            current_role = str(task.get("agent_role") or "researcher")
            next_plan = (
                _next_action_plan(
                    next_actions[0],
                    current_role=current_role,
                    execution_policy=execution_policy,
                )
                if isinstance(next_actions, list) and next_actions
                else None
            )
            if (
                result_status in {"completed", "succeeded", "needs_replan"}
                and str(runtime.get("adapter") or "") in HOOK_GATED_ADAPTERS
            ):
                hook_error, hook_warning = _codex_hook_receipt_status(runtime)
                if hook_warning:
                    runtime["hook_receipt_warning"] = hook_warning
                if hook_error:
                    result_status = "needs_replan"
                    runtime_error = hook_error
                    runtime["hook_receipt_error"] = runtime_error
            continuity_required = (
                result_status in {"completed", "succeeded"}
                and current_role != "reviewer"
                and (
                    (current_role == "writer" and payload.get("paper_candidate") is True)
                    or (
                        payload.get("paper_candidate") is not True
                        and next_plan is not None
                        and next_plan.agent_role == current_role
                        and next_plan.session_mode == "resume"
                    )
                )
            )
            if continuity_required and not runtime.get("session_id"):
                result_status = "needs_human"
                runtime["continuity_error"] = "resumable task returned no session_id"
                runtime_error = str(runtime["continuity_error"])

            # The receipt authenticates the agent's private result.  Before a
            # valid completed node or replan checkpoint becomes authoritative,
            # bind every artifact to an immutable archive and atomically promote
            # the staged campaign tree.
            transaction_error: str | None = None
            promotion_pending = False
            promotable = (
                result_status in {"completed", "succeeded", "needs_replan"}
                and gate.passed
                and runtime_error is None
            )
            if promotable:
                try:
                    if campaign_binding is None:
                        raise ValueError("campaign disappeared before protocol validation")
                    protocol_errors = _validate_bound_protocol(
                        paths,
                        campaign_binding,
                        attempt_workspace=attempt_workspace,
                        task=task,
                    )
                    if protocol_errors:
                        runtime["protocol_gate"] = {
                            "passed": False,
                            "errors": list(protocol_errors),
                        }
                        raise ValueError(
                            "protocol_gate_failed:" + "; ".join(protocol_errors)
                        )
                    runtime["protocol_gate"] = {"passed": True, "errors": []}
                    source_payload = payload
                    payload, result_path, actual_sha = freeze_result_bundle(
                        paths,
                        payload,
                        attempt_id=attempt_id,
                        source_result_path=result_path,
                        source_result_sha256=actual_sha,
                        source_workspace=(
                            attempt_workspace.campaign_root
                            if attempt_workspace is not None
                            else None
                        ),
                    )
                    gate = evaluate_result_bundle(
                        payload, allowed_roots=roots, preregistration_sha256=preregistration
                    )
                    if not gate.passed:
                        raise ValueError(
                            "immutable archive failed result gate: " + "; ".join(gate.blockers)
                        )
                    if attempt_workspace is not None:
                        policy = attempt_artifact_policy(attempt_workspace)
                        if policy is not None:
                            # Reject an invalid campaign before publishing any new
                            # object, then recheck after the small reference is added.
                            enforce_campaign_data_boundary(attempt_workspace)
                            reference = publish_staged_artifacts(
                                paths,
                                source_payload,
                                payload,
                                workspace=attempt_workspace,
                                attempt_id=attempt_id,
                            )
                            changed_files = enforce_campaign_data_boundary(attempt_workspace)
                            runtime["artifact_policy"] = {
                                "schema_version": policy["schema_version"],
                                "campaign_changed_files": len(changed_files),
                                "campaign_reference": str(reference) if reference else None,
                            }
                        begin_attempt_promotion(attempt_workspace)
                        promotion_pending = True
                except Exception as exc:  # noqa: BLE001
                    transaction_error = f"attempt_commit_failed:{exc}"
                    result_status = "needs_replan"
                    runtime["transaction_error"] = transaction_error
                    if attempt_workspace is not None:
                        _quarantine_attempt(
                            paths,
                            report,
                            task_id=task_id,
                            campaign_id=str(task["campaign_id"]),
                            attempt_id=attempt_id,
                            reason=transaction_error,
                        )
            elif attempt_workspace is not None:
                reason = runtime_error or (
                    "; ".join(gate.blockers) if gate.blockers else f"result_status:{result_status}"
                )
                _quarantine_attempt(
                    paths,
                    report,
                    task_id=task_id,
                    campaign_id=str(task["campaign_id"]),
                    attempt_id=attempt_id,
                    reason=reason,
                )
            errors = [*gate.blockers]
            if runtime_error:
                errors.append(runtime_error)
            if transaction_error:
                errors.append(transaction_error)
            failure_classes = set(gate.failure_classes)
            if transaction_error and "protocol_gate_failed:" in transaction_error:
                failure_classes.add("protocol_state")
            runtime["gate_failure_classes"] = sorted(failure_classes)
            try:
                final_status = db.ingest_result(
                    task_id,
                    attempt_id=attempt_id,
                    status=result_status,
                    result_path=str(result_path),
                    result_sha256=actual_sha,
                    valid=gate.validation.valid,
                    gate_passed=gate.passed,
                    blockers=list(gate.blockers),
                    run_seconds=float(runtime["duration_seconds"]),
                    runtime=runtime,
                    error="; ".join(errors) if errors else None,
                    retry_backoff_seconds=settings.retry_backoff_seconds,
                )
            except Exception as exc:
                if promotion_pending and attempt_workspace is not None:
                    rollback_attempt_promotion(
                        attempt_workspace,
                        reason=f"database_ingest_failed:{exc}",
                    )
                raise
            if final_status == "queued":
                _maybe_escalate_to_lead(db, settings, report, task)
            if budget_control.is_healthy_result(runtime):
                budget_control.record_healthy_completion(
                    db,
                    settings,
                    runner=task.get("runner"),
                    task_id=task_id,
                )
            if promotion_pending and attempt_workspace is not None:
                if final_status not in {"succeeded", "needs_replan"}:
                    rollback_attempt_promotion(
                        attempt_workspace,
                        reason=f"database_rejected_promotion:{final_status}",
                    )
                    raise ValueError(f"Promoted attempt unexpectedly ingested as {final_status}")
                try:
                    finalize_attempt_promotion(attempt_workspace)
                    report.attempts_committed.append(
                        {
                            "task_id": task_id,
                            "attempt_id": attempt_id,
                            "campaign_id": str(task["campaign_id"]),
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    # The DB and canonical tree already agree.  Keep the rollback
                    # copy and let the next locked tick finish cleanup safely.
                    report.errors.append(
                        f"Could not finalize attempt promotion {attempt_id}: {exc}"
                    )
            task = db.task(task_id) or {}
            domain = str(payload.get("domain") or task.get("domain") or "unknown")
            db.upsert_research_record(
                f"result:{task_id}",
                kind="result",
                domain=domain,
                title=str(payload.get("summary") or task_id),
                status=final_status,
                source_path=str(result_path),
                metadata={
                    "campaign_id": payload.get("campaign_id"),
                    "sha256": actual_sha,
                    "paper_candidate": payload.get("paper_candidate") is True,
                },
            )
            for claim in payload.get("claims", []):
                if not isinstance(claim, Mapping) or not claim.get("claim_id"):
                    continue
                claim_id = str(claim["claim_id"])
                db.upsert_research_record(
                    f"claim:{task_id}:{claim_id}",
                    kind="claim",
                    domain=domain,
                    title=str(claim.get("text") or claim_id),
                    status=str(claim.get("status") or "unsupported"),
                    source_path=str(result_path),
                    metadata={
                        "task_id": task_id,
                        "campaign_id": payload.get("campaign_id"),
                        "evidence": claim.get("evidence", []),
                        "limitations": claim.get("limitations", []),
                    },
                )
            campaign_id = str(payload["campaign_id"])
            task_type = str(task.get("task_type") or "")
            successful = final_status == "succeeded" and gate.passed
            # A topic scout only proposes cards; the program controller owns
            # what happens next (registration, admission), never the result.
            # A direction decision is applied by the program controller below.
            automatic_successors_allowed = task_type not in {
                SCOUT_TASK_TYPE, DIRECTION_TASK_TYPE, asset_library.RETROSPECTIVE_TASK_TYPE
            }
            if task_type == "portfolio_review" and payload.get("paper_candidate") is True:
                report.errors.append(
                    f"Portfolio reviewer {task_id} set paper_candidate=true; ignored for "
                    "scheduling because candidate_branches is the only portfolio handoff"
                )
            if campaign_binding is not None and campaign_binding.get("project_config_path"):
                try:
                    index_project_result(
                        campaign_binding,
                        task,
                        payload,
                        result_path=result_path,
                        result_sha256=actual_sha,
                        final_status=final_status,
                    )
                except Exception as exc:  # noqa: BLE001 - derived index is rebuildable.
                    report.errors.append(f"Could not index project result {task_id}: {exc}")
            if successful and task_type == "paper_review":
                outcome = payload.get("review_outcome")
                try:
                    budget_control.ingest_review_quota(
                        db, settings, paths.data,
                        outcome.get("decision_record") if isinstance(outcome, Mapping) else None,
                        task_id=task_id,
                    )
                except Exception as exc:  # noqa: BLE001 - readings are advisory.
                    report.errors.append(f"Could not read review quota of {task_id}: {exc}")
            program_disposition: str | None = None
            if successful and settings.program.enabled:
                try:
                    program_disposition = program_autonomy.on_result(
                        db, paths, settings, report, task=task, payload=payload,
                        result_path=result_path, result_sha256=actual_sha,
                    )
                except Exception as exc:  # noqa: BLE001 - the result stays authoritative.
                    program_disposition = "handled"
                    report.errors.append(f"Program handling of {task_id} failed: {exc}")
            try:
                # Declared assets_used / assets_broken (no-op unless [program.assets] enabled).
                asset_library.record_result_usage(
                    db, paths, settings, report, task=task, attempt_id=attempt_id,
                    payload=payload, successful=successful,
                )
            except Exception as exc:  # noqa: BLE001 - usage counting is advisory.
                report.errors.append(f"Asset usage of {task_id} not recorded: {exc}")
            # "continue_research": a paper candidate of an admitted topic whose primary
            # endpoint is inconclusive stays in research (within budget and deadline).
            paper_candidate = (
                payload.get("paper_candidate") is True
                and program_disposition != "continue_research"
            )
            candidate_materialization_ok = True
            if (
                successful
                and settings.auto_continue
                and automatic_successors_allowed
                and campaign_binding is not None
                and campaign_binding.get("project_config_path")
            ):
                try:
                    spawned = spawn_candidate_workstreams(
                        db,
                        paths,
                        settings,
                        campaign_binding,
                        task,
                        payload,
                        result_path=result_path,
                    )
                    report.enqueued.extend(spawned.task_ids)
                    report.production_synced.extend(spawned.campaign_ids)
                    if spawned.decisions:
                        report.program.setdefault("admission_decisions", []).extend(
                            spawned.decisions
                        )
                except Exception as exc:  # noqa: BLE001 - result remains authoritative.
                    candidate_materialization_ok = False
                    report.errors.append(
                        f"Could not materialize candidate branches from {task_id}: {exc}"
                    )
            if (
                successful
                and task_type == "portfolio_review"
                and candidate_materialization_ok
            ):
                try:
                    advance_review_cursor(task)
                except Exception as exc:  # noqa: BLE001 - retry review rather than lose result.
                    report.errors.append(f"Could not advance review cursor {task_id}: {exc}")
            agent_closed_workstream = bool(
                campaign_binding is not None
                and _workstream_state_status(campaign_binding) in {"paused", "completed"}
                and payload.get("paper_candidate") is not True
            )
            successor_handled = (
                agent_closed_workstream
                or not automatic_successors_allowed
                or program_disposition == "handled"
            )
            if agent_closed_workstream:
                state_status = _workstream_state_status(campaign_binding or {})
                db.pause_production_campaign(
                    campaign_id,
                    reason=f"agent_workstream_{state_status}",
                )
                report.production_paused.append(campaign_id)
            room = (
                _prepare_auto_task_room(
                    db,
                    campaign_id,
                    settings,
                    report,
                    source_task_id=task_id,
                )
                if automatic_successors_allowed
                else AutoTaskRoom(False, epoch=int(task.get("campaign_epoch") or 1))
            )
            has_room = room.allowed

            # Evidence requested by a paper reviewer returns to the prior writer
            # session when one exists. A pre-writing evidence repair is audited
            # again before a writer is ever created.
            if (
                settings.auto_continue
                and automatic_successors_allowed
                and successful
                and task_type == "evidence_remediation"
                and task.get("routing_reason") in EVIDENCE_REMEDIATION_ROUTINGS
            ):
                successor_handled = True
                if not has_room:
                    report.errors.append(
                        f"Campaign {campaign_id} reached its automatic-task safety limit"
                    )
                else:
                    writer_source = db.nearest_session_source(
                        task_id,
                        agent_role="writer",
                    )
                    if writer_source is not None:
                        successor_id = _derived_task_id(task_id, "paper-revision", actual_sha)
                        source_task = db.task(str(writer_source["task_id"])) or {}
                        _enqueue_paper_task(
                            db,
                            report,
                            settings,
                            task,
                            task_id=successor_id,
                            domain=domain,
                            task_type="paper_revision",
                            objective=(
                                "Resume the same manuscript after the requested evidence "
                                "work. Incorporate only the new hash-bound evidence, preserve "
                                "contrary results, and do not answer beyond the review. "
                                f"The original review is at {task.get('input_path')}."
                            ),
                            input_path=str(result_path),
                            skill_path=_paper_skill(domain),
                            routing_reason="review_evidence_completed",
                            agent_role="writer",
                            session_mode="resume",
                            session_source_task_id=str(writer_source["task_id"]),
                            resources=(task_resources(source_task) if source_task else None),
                        )
                    else:
                        successor_id = _derived_task_id(task_id, "paper-readiness", actual_sha)
                        _enqueue_paper_task(
                            db,
                            report,
                            settings,
                            task,
                            task_id=successor_id,
                            domain=domain,
                            task_type="paper_readiness",
                            objective=(
                                "Independently re-audit the frozen campaign evidence after "
                                "the requested remediation. Return a readiness verdict and "
                                "exact remaining evidence gaps; do not draft the manuscript. "
                                f"The prior readiness review is at {task.get('input_path')}."
                            ),
                            input_path=str(result_path),
                            skill_path=_paper_skill(domain),
                            routing_reason="readiness_evidence_completed",
                            agent_role="reviewer",
                        )

            # A paper candidate advances through explicit epistemic stages. A
            # successful paper_review is terminal: it does not create another
            # writer and therefore cannot loop on paper_candidate=true.
            if (
                successful
                and settings.auto_continue
                and not successor_handled
                and task_type != "portfolio_review"
                and paper_candidate
            ):
                successor_handled = True
                transition: dict[str, str] | None = None
                if current_role in {"researcher", "experimenter"} or (
                    current_role == "reviewer"
                    and task_type not in {"paper_readiness", "paper_review"}
                ):
                    transition = {
                        "suffix": "paper-readiness",
                        "task_type": "paper_readiness",
                        "objective": (
                            "Independently audit the frozen campaign evidence for a defensible "
                            "paper. Return only a readiness verdict and exact evidence gaps; "
                            "do not draft or revise the manuscript."
                        ),
                        "skill": _paper_skill(domain) or "",
                        "routing_reason": "paper_evidence_audit",
                        "agent_role": "reviewer",
                    }
                elif current_role == "reviewer" and task_type == "paper_readiness":
                    transition = {
                        "suffix": "paper-write",
                        "task_type": "paper_write",
                        "objective": (
                            "Write from the independently validated, frozen evidence only. "
                            "Do not broaden claims beyond the audit."
                        ),
                        "skill": _paper_skill(domain) or "",
                        "routing_reason": "independent_audit_passed",
                        "agent_role": "writer",
                    }
                elif current_role == "writer" and task_type in {
                    "paper_write",
                    "paper_revision",
                }:
                    transition = {
                        "suffix": "paper-review",
                        "task_type": "paper_review",
                        "objective": (
                            "Resolve the paper ID from the writer's registered artifacts and run "
                            "`paper-writing review unified-run --paper-id <id>` (add --response for a re-review). "
                            "It runs the preflight, the target-journal editor screen, two blind referees and the "
                            "conservative decision; do not reproduce its stages or edit the manuscript. Return "
                            "paper_candidate=true only for outcome ready; otherwise return exactly one structured "
                            "text_revision or evidence_remediation action, or none for retarget_required/blocked. "
                            "Always copy the paper's registered writing_release into the result field "
                            "`review_outcome` (next_action, status, review_stalled, rounds_for_target, "
                            "max_rounds_per_target, direction_context, decision_record, "
                            "decision_record_sha256, paper_id); the orchestrator decides what follows."
                        ),
                        "skill": "openlabs-paper-review",
                        "routing_reason": "paper_review_scope_selection",
                        "agent_role": "reviewer",
                    }
                elif current_role == "reviewer" and task_type == "paper_review":
                    transition = None
                else:
                    report.errors.append(
                        f"Task {task_id} cannot promote a paper candidate from "
                        f"{current_role}/{task_type}"
                    )

                if transition is not None:
                    if not has_room:
                        report.errors.append(
                            f"Campaign {campaign_id} reached its automatic-task safety limit"
                        )
                    elif transition["skill"]:
                        successor_id = _derived_task_id(
                            task_id,
                            transition["suffix"],
                            actual_sha,
                        )
                        _enqueue_paper_task(
                            db,
                            report,
                            settings,
                            task,
                            task_id=successor_id,
                            domain=domain,
                            task_type=transition["task_type"],
                            objective=transition["objective"],
                            input_path=str(result_path),
                            skill_path=transition["skill"],
                            routing_reason=transition["routing_reason"],
                            agent_role=transition["agent_role"],
                        )
                        if transition["task_type"] == "paper_review" and settings.program.enabled:
                            try:
                                program_autonomy.on_review_scheduled(
                                    db, paths, settings, campaign_id=campaign_id,
                                    review_task_id=successor_id,
                                )
                            except (OSError, TopicLedgerError, ValueError) as exc:
                                report.errors.append(
                                    f"Could not mark topic of {campaign_id} in review: {exc}"
                                )

            # Only a paper reviewer may send a manuscript back across the role
            # boundary, and only to the writer session in its own ancestry.
            if (
                successful
                and settings.auto_continue
                and not successor_handled
                and current_role == "reviewer"
                and task_type in {"paper_readiness", "paper_review"}
                and next_plan is not None
            ):
                successor_handled = True
                target_role = next_plan.agent_role
                if (
                    task_type == "paper_review"
                    and next_plan.handoff_kind == "text_revision"
                    and target_role == "writer"
                ):
                    writer_source = db.nearest_session_source(
                        task_id,
                        agent_role="writer",
                    )
                    if writer_source is None:
                        report.errors.append(
                            f"Paper review {task_id} has no writer session in its lineage"
                        )
                    elif not has_room:
                        report.errors.append(
                            f"Campaign {campaign_id} reached its automatic-task safety limit"
                        )
                    else:
                        successor_id = _derived_task_id(task_id, "paper-revision", actual_sha)
                        source_task = db.task(str(writer_source["task_id"])) or {}
                        _enqueue_paper_task(
                            db,
                            report,
                            settings,
                            task,
                            task_id=successor_id,
                            domain=domain,
                            task_type="paper_revision",
                            objective=next_plan.objective,
                            input_path=str(result_path),
                            skill_path=_paper_skill(domain),
                            routing_reason="review_text_revision",
                            agent_role="writer",
                            session_mode="resume",
                            session_source_task_id=str(writer_source["task_id"]),
                            resources=(
                                next_plan.resources
                                or (task_resources(source_task) if source_task else None)
                            ),
                        )
                elif (
                    task_type in {"paper_readiness", "paper_review"}
                    and next_plan.handoff_kind == "evidence_remediation"
                    and target_role in {"researcher", "experimenter"}
                ):
                    if not has_room:
                        report.errors.append(
                            f"Campaign {campaign_id} reached its automatic-task safety limit"
                        )
                    else:
                        successor_id = _derived_task_id(task_id, "evidence-remediation", actual_sha)
                        _enqueue_paper_task(
                            db,
                            report,
                            settings,
                            task,
                            task_id=successor_id,
                            domain=domain,
                            task_type="evidence_remediation",
                            objective=next_plan.objective,
                            input_path=str(result_path),
                            skill_path=(
                                str(campaign_binding.get("primary_skill") or "")
                                if campaign_binding is not None
                                and campaign_binding.get("project_config_path")
                                else _research_skill(domain)
                            ),
                            routing_reason="review_evidence_remediation",
                            agent_role=target_role,
                            resources=next_plan.resources,
                        )
                else:
                    report.errors.append(
                        f"Reviewer task {task_id} requested an unsafe or ambiguous handoff"
                    )

            can_follow = (
                settings.auto_continue
                and next_plan is not None
                and str(task.get("task_type") or "") != "smoke"
                and current_role != "reviewer"
                and not successor_handled
                and not _explicit_terminal_freeze(payload)
                and not paper_candidate
                and has_room
                and not protocol_managed_continuation
            )
            is_continuation = final_status == "succeeded" and gate.passed
            is_replan = final_status == "needs_replan" and gate.validation.valid
            if can_follow and (is_continuation or is_replan):
                objective = next_plan.objective
                target_role = next_plan.agent_role
                session_mode = next_plan.session_mode
                infrastructure_retry = is_replan and _missing_agent_bundle(payload, runtime)
                if is_replan:
                    target_role = "researcher"
                    if target_role != current_role:
                        session_mode = "fresh"
                    if infrastructure_retry:
                        objective = _infrastructure_retry_objective(db, task)
                elif target_role == "writer" and current_role != "writer":
                    report.errors.append(
                        f"Task {task_id} requested writer handoff without an independent "
                        "paper-readiness review"
                    )
                    report.ingested.append({"task_id": task_id, "status": final_status})
                    _archive_receipt(
                        receipt_path,
                        paths,
                        keep=settings.archive_result_receipts,
                    )
                    continue
                if session_mode == "resume" and (
                    target_role != current_role or not task.get("agent_session_id")
                ):
                    session_mode = "fresh"
                prefix = "replan" if is_replan else "continue"
                follow_task_id = f"{prefix}:{actual_sha[:32]}"
                if db.task(follow_task_id) is None:
                    db.enqueue_task(
                        task_id=follow_task_id,
                        campaign_id=str(payload["campaign_id"]),
                        domain=domain,
                        task_type=("replan" if is_replan else _continuation_task_type(target_role)),
                        objective=objective,
                        input_path=str(result_path),
                        skill_path=(str(task["skill_path"]) if task.get("skill_path") else None),
                        runner=(
                            next_plan.runner
                            or ("frontier" if is_replan else _inherited_runner(task))
                        ),
                        routing_reason=(
                            "production_rollover"
                            if room.rolled_over
                            else "infrastructure_retry"
                            if infrastructure_retry
                            else "gate_replan"
                            if is_replan
                            else "role_handoff"
                            if target_role != current_role
                            else "independent_restart"
                            if session_mode == "fresh"
                            else "validated_continuation"
                        ),
                        parent_task_id=task_id,
                        agent_role=target_role,
                        session_mode=session_mode,
                        priority=int(task.get("priority") or 0),
                        max_attempts=settings.max_attempts,
                        max_wall_seconds=min(
                            next_plan.wall_seconds
                            or int(task.get("max_wall_seconds") or settings.max_task_wall_seconds),
                            settings.max_task_wall_seconds,
                        ),
                        **_successor_resources(
                            task,
                            settings,
                            target_role=target_role,
                            requested=next_plan.resources,
                        ).to_dict(),
                    )
                    report.enqueued.append(follow_task_id)
            report.ingested.append({"task_id": task_id, "status": final_status})
            _archive_receipt(receipt_path, paths, keep=settings.archive_result_receipts)
        # A malformed result must not block receipts from unrelated campaigns.
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"Could not ingest {receipt_path.name}: {exc}")
            try:
                _archive_receipt(
                    receipt_path,
                    paths,
                    keep=settings.archive_result_receipts,
                )
            except OSError as archive_error:
                report.errors.append(
                    f"Could not archive rejected receipt {receipt_path.name}: {archive_error}"
                )


def _write_task_spec(
    paths: WorkspacePaths,
    task: Mapping[str, Any],
    *,
    attempt_workspace: AttemptWorkspace,
    lab_id: str,
    manifest_path: Path,
    skill_path: Path | None,
    output_path: Path,
    wall_seconds: int,
    campaign: Mapping[str, Any] | None = None,
    agent_tools: Mapping[str, Any] | None = None,
    extra_read_resources: list[dict[str, str]] | None = None,
) -> Path:
    agent_workspace = attempt_workspace.campaign_root
    agent_workspace.mkdir(parents=True, exist_ok=True)
    run_metadata_path = output_path.parent / "run-metadata.json"
    transaction = {
        "mode": "isolated_attempt_workspace",
        "attempt_root": str(attempt_workspace.root),
        "staged_campaign_workspace": str(attempt_workspace.campaign_root),
        "canonical_campaign_workspace": str(attempt_workspace.canonical_campaign_root),
        "promotion_policy": "validated_results_and_checkpoints",
    }
    policy = attempt_artifact_policy(attempt_workspace)
    if policy is not None:
        transaction.update(
            {
                "artifact_staging_root": str(attempt_workspace.artifact_staging_root),
                "artifact_policy": dict(policy),
            }
        )
    payload = {
        "schema_version": TASK_SCHEMA,
        "task_id": task["task_id"],
        "attempt_id": task["current_attempt_id"],
        "campaign_id": task["campaign_id"],
        "lab_id": lab_id,
        "domain": task["domain"],
        "task_type": task["task_type"],
        "objective": attempt_workspace.rewrite_text(str(task["objective"])),
        "input_path": attempt_workspace.map_path(task.get("input_path")),
        "output_path": str(output_path),
        "skill_path": str(skill_path) if skill_path else task.get("skill_path"),
        "runner": task.get("runner") or "balanced",
        "lab_manifest": str(manifest_path),
        "attempt": task["attempt"],
        "campaign_epoch": int(task.get("campaign_epoch") or 1),
        "agent_workspace": str(agent_workspace),
        "run_metadata_path": str(run_metadata_path),
        "transaction": transaction,
        "routing_reason": task.get("routing_reason") or "manual",
        "parent_task_id": task.get("parent_task_id"),
        "agent": {
            "role": task.get("agent_role") or "researcher",
            "session_mode": task.get("session_mode") or "resume",
            "session_id": (
                None
                if task.get("agent_role") == "reviewer" or task.get("session_mode") == "fresh"
                else task.get("agent_session_id")
            ),
        },
        "resources": task_resources(task).to_dict(),
        "budget": {"wall_seconds": max(1, int(wall_seconds))},
    }
    if agent_tools is not None:
        payload["agent_tools"] = dict(agent_tools)
    project_path = (
        campaign.get("project_config_path") or campaign.get("production_plan_path")
        if campaign is not None
        else None
    )
    workstream_path = (
        campaign.get("workstream_state_path") or campaign.get("production_lane_path")
        if campaign is not None
        else None
    )
    if bool(project_path) != bool(workstream_path):
        raise ValueError("campaign project/workstream binding is incomplete")
    if project_path and workstream_path:
        assert campaign is not None
        execution_policy = _campaign_execution_policy(campaign)
        project_config = (
            load_project(project_path) if campaign.get("project_config_path") else None
        )
        payload["project"] = {
            "config_path": attempt_workspace.map_path(project_path),
            "workstream_state_path": attempt_workspace.map_path(workstream_path),
            "domain_config_path": (
                attempt_workspace.map_path(project_config.domain_config_path)
                if project_config is not None and project_config.domain_config_path is not None
                else None
            ),
            "protocol_id": campaign.get("protocol_id") or "legacy-production-plan",
            "read_resources": (
                [item.to_dict() for item in project_config.read_resources]
                if project_config is not None
                else []
            ),
        }
        known_paths = {item["path"] for item in payload["project"]["read_resources"]}
        known_labels = {item["label"] for item in payload["project"]["read_resources"]}
        for item in [*packet_read_resources(task.get("input_path")),
                     *(extra_read_resources or [])]:
            if item["path"] not in known_paths and item["label"] not in known_labels:
                payload["project"]["read_resources"].append(item)
                known_paths.add(item["path"])
                known_labels.add(item["label"])
        payload["execution_policy"] = execution_policy.to_dict()
    skill_dirs = [
        paths.code / "orchestrator" / "skills" / "openlabs-research-factory",
    ]
    if str(task.get("agent_role") or "researcher") == "researcher":
        skill_dirs.append(
            paths.code / "orchestrator" / "skills" / "vendor" / "paper-lookup"
        )
    runtime_lab = lab_for_domain(discover_labs(paths.code), str(task["domain"]))
    runtime_skill_ids = _campaign_runtime_skill_ids(runtime_lab, campaign)
    skill_dirs.extend(
        candidate.parent
        for skill_id in runtime_skill_ids
        if skill_id
        and (candidate := runtime_lab.skill_path(skill_id)) is not None
        and candidate.parent not in skill_dirs
    )
    available_skill_dirs = [
        candidate.parent
        for item in runtime_lab.skills
        if (candidate := runtime_lab.skill_path(str(item["skill_id"]))) is not None
    ]
    if skill_path is not None and skill_path.parent not in skill_dirs:
        requested_skill_id = str(task.get("skill_path") or "").strip()
        project_bound = bool(campaign and campaign.get("project_config_path"))
        task_type = str(task.get("task_type") or "")
        paper_skill_ids: set[str] = set()
        if task_type == "paper_review":
            paper_skill_ids.add("openlabs-paper-review")
        elif task_type in {"paper_readiness", "paper_write", "paper_revision"}:
            configured_paper_skill = _paper_skill(str(task.get("domain") or ""))
            if configured_paper_skill:
                paper_skill_ids.add(configured_paper_skill)
        if project_bound and requested_skill_id not in paper_skill_ids:
            raise ValueError(
                f"Project task Skill {requested_skill_id!r} is not activated by protocol "
                f"{campaign.get('protocol_id')!r}"
            )
        skill_dirs.append(skill_path.parent)
    payload["runtime_policy"] = configure_codex_runtime(
        agent_workspace,
        task=payload,
        output_path=output_path,
        skill_dirs=skill_dirs,
        available_skill_dirs=available_skill_dirs,
    )
    validation = validate_task(payload)
    if not validation.valid:
        raise ValueError("; ".join(validation.errors))
    return atomic_write_json(
        paths.job_inbox / f"{task['task_id']}-{task['current_attempt_id']}.json",
        payload,
    )


def _worker_cpu_ceiling_threads(fraction: float | None) -> int | None:
    if fraction is None:
        return None
    return max(1, math.ceil((os.cpu_count() or 1) * fraction))


def _launch_task(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    task: Mapping[str, Any],
    *,
    owner: str,
) -> None:
    labs = discover_labs(paths.code)
    lab = lab_for_domain(labs, str(task["domain"]))
    requested_skill = str(task.get("skill_path") or "").strip() or None
    skill_path = lab.skill_path(requested_skill)
    if requested_skill and skill_path is None:
        raise ValueError(f"Unknown skill {requested_skill!r} for lab {lab.lab_id}")
    campaign = db.campaign(str(task["campaign_id"]))
    if campaign is None:
        raise ValueError(f"Unknown campaign: {task['campaign_id']}")
    attempt_workspace = prepare_attempt_workspace(paths, task, campaign)
    output_path = attempt_output_path(attempt_workspace, task)
    used = float(campaign["agent_seconds_used"])
    remaining = max(0, int(float(campaign["max_agent_seconds"]) - used))
    if remaining < 1:
        raise ValueError(f"Campaign {task['campaign_id']} exhausted its Agent-time budget")
    wall_seconds = min(int(task.get("max_wall_seconds") or 1), remaining)
    db.bind_attempt_spec(
        str(task["task_id"]),
        attempt_id=str(task["current_attempt_id"]),
        lab_id=lab.lab_id,
        output_path=str(output_path),
    )
    job_path = _write_task_spec(
        paths,
        task,
        attempt_workspace=attempt_workspace,
        lab_id=lab.lab_id,
        manifest_path=lab.root / "lab.json",
        skill_path=skill_path,
        output_path=output_path,
        wall_seconds=wall_seconds,
        campaign=campaign,
        agent_tools=_agent_tools(settings, task.get("runner") or "balanced"),
        extra_read_resources=asset_library.research_read_resources(paths, settings, task, campaign),
    )
    log_path = output_path.parent / "worker.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment["OPENLABS_WORKSPACE"] = str(paths.workspace)
    environment["OPENLABS_JOB_SPEC"] = str(job_path)
    reserved = task_resources(task)
    thread_count = str(reserved.cpu_threads)
    for name in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        environment[name] = thread_count
    environment["OPENLABS_MEMORY_MIB"] = str(reserved.memory_mib)
    environment["OPENLABS_SCRATCH_MIB"] = str(reserved.scratch_mib)
    environment["OPENLABS_CPU_THREADS"] = thread_count
    db.mark_running(
        str(task["task_id"]),
        attempt_id=str(task["current_attempt_id"]),
        owner=owner,
        pid=None,
        lease_seconds=settings.lease_seconds,
    )
    worker_pid = _launch_worker(
        task=task,
        paths=paths,
        job_path=job_path,
        log_path=log_path,
        environment=environment,
        cpu_ceiling_threads=_worker_cpu_ceiling_threads(
            lab.worker_cpu_burst_fraction
        ),
    )
    try:
        if worker_pid is not None:
            db.set_worker_pid(
                str(task["task_id"]),
                attempt_id=str(task["current_attempt_id"]),
                pid=worker_pid,
            )
    except Exception:
        if worker_pid is not None:
            try:
                os.kill(worker_pid, 15)
            except ProcessLookupError:
                pass
        raise


def _inherited_runner(task: Mapping[str, Any]) -> str:
    """The runner request a successor inherits.

    A routed task's ``runner`` is the concrete runner the router chose; the
    successor inherits the original request instead, so it is routed afresh
    rather than pinned to the predecessor's family. An escalation tier maps back
    to its legacy alias.
    """

    request = task.get("runner_request")
    if request is None:
        return str(task.get("runner") or "balanced")
    text = str(request).strip()
    if text in TIER_ALIASES:
        return TIER_ALIASES[text]
    return text or "balanced"


TIER_ALIASES = {tier: alias for alias, tier in LEGACY_RUNNER_TIERS.items()}


def _record_quota_reading(
    db: FactoryDB,
    settings: FactorySettings,
    report: TickReport,
    task: Mapping[str, Any],
    runtime: dict[str, Any],
) -> None:
    """Store the receipt's quota snapshot per provider/window; never fails ingestion."""

    try:
        if budget_control.routing_enabled(settings):
            runtime["execution"] = budget_control.execution_record(settings, task, runtime)
        if runtime.get("quota_snapshot") is not None:
            budget_control.record_quota_snapshot(
                db,
                settings,
                runtime["quota_snapshot"],
                runner=runtime.get("runner") or task.get("runner"),
                task_id=str(task["task_id"]),
            )
    except Exception as exc:  # noqa: BLE001 - a reading is advisory
        report.errors.append(f"Could not record quota reading for {task.get('task_id')}: {exc}")


ESCALATION_NOTE = (
    "[Escalated to the lead tier] Diagnose the causes of the previous {count} failed "
    "attempts before continuing; fix the cause, not the symptom. "
    "（诊断前{count}次失败原因后再继续。）"
)


def _maybe_escalate_to_lead(
    db: FactoryDB,
    settings: FactorySettings,
    report: TickReport,
    task: Mapping[str, Any],
) -> None:
    """After N consecutive non-infrastructure failures of a worker-tier task, re-request lead.

    The ordinary retry path requeues the same task (same objective) while
    attempts remain; the next claim routes it to a lead runner with a diagnosis
    preamble. Only active with a ``[runners]`` table.
    """

    threshold = settings.routing.escalate_to_lead_after_failures
    if not budget_control.routing_enabled(settings) or threshold <= 0:
        return
    if budget_control.tier_of(settings, task.get("runner")) != "worker":
        return
    if task.get("runner_request") is None and normalize_runner(task.get("runner")) in (
        settings.runners
    ):
        return  # a caller-pinned runner is never re-routed
    failures: list[str] = []
    for attempt in reversed(db.task_attempts(str(task["task_id"]))):
        status = str(attempt.get("status") or "")
        runtime = attempt.get("runtime") if isinstance(attempt.get("runtime"), Mapping) else {}
        if status in {"quota_deferred", "launch_failed"} or str(
            runtime.get("failure_class") or ""
        ) in INFRASTRUCTURE_FAILURE_CLASSES:
            continue  # infrastructure neither counts nor breaks the streak
        if status not in {"queued", "failed", "quarantined"}:
            break
        failures.append(str(attempt.get("error") or "unspecified failure")[:300])
    if len(failures) < threshold:
        return
    note = ESCALATION_NOTE.format(count=len(failures))
    payload = {
        "consecutive_failures": len(failures),
        "threshold": threshold,
        "recent_errors": failures[:threshold],
    }
    if db.escalate_task_tier(str(task["task_id"]), tier="lead", note=note, payload=payload):
        report.escalated.append({"task_id": str(task["task_id"]), **payload})


def _tick_locked(paths: WorkspacePaths, settings: FactorySettings) -> TickReport:
    paths.ensure_runtime_directories()
    db = FactoryDB(paths.database_file)
    db.initialize()
    report = TickReport()

    _recover_attempt_workspaces(db, paths, report)

    # Active project configs are desired state: bind their workstreams before
    # processing completions so a safety-window boundary can roll over instead of idle.
    _sync_active_projects(db, paths, settings, report)
    report.cancelled.extend(db.cancel_queued_tasks_for_inactive_campaigns())
    # Ingest first so a completed worker is not requeued just because its lease expired.
    ingest_results(db, paths, settings, report)
    recovery = db.recover_expired(settings.retry_backoff_seconds)
    report.recovered.extend(recovery.requeued)
    report.quarantined.extend(recovery.quarantined)
    report.cancelled.extend(recovery.cancelled)
    for disposition in recovery.attempts:
        _apply_attempt_disposition(paths, report, disposition)
    try:
        divert = program_autonomy.budget_divert_campaigns(paths, settings)
    except (OSError, TopicLedgerError, ValueError) as exc:
        report.errors.append(f"program budget routing: {exc}")
        divert = set()
    report.budget_stopped.extend(db.stop_budget_exhausted_tasks(divert))
    # Research-program bookkeeping runs after ingestion so freezes recorded in the
    # topic ledger stop their campaigns before any continuous replenishment.
    run_program_controller(db, paths, settings.program, report)
    # Stop rules (deadline, budget), direction-decision recovery and delivery.
    program_autonomy.run_program_autonomy(db, paths, settings, report)
    # Topic scouts, card intake and ordered materialization of admitted topics.
    run_program_pipeline(db, paths, settings, report)
    # Asset retrospectives and archiving (no-op unless [program.assets] is enabled).
    asset_library.run_assets_tick(db, paths, settings, report)
    if settings.auto_continue:
        _replenish_continuous_campaigns(db, paths, settings, report)

    reserved = db.active_resource_totals()
    resource_capacity = effective_capacity(paths.workspace, settings, reserved)
    report.resource_capacity = resource_capacity.to_dict()

    budget_now = budget_control.current_time()
    launch_limit = budget_control.launch_limit(db, settings)
    backoffs = budget_control.runner_backoffs(db, now=budget_now, settings=settings)
    report.effective_parallel = launch_limit
    report.provider_backoff_until = backoffs
    router: budget_control.QuotaRouter | None = None
    if budget_control.routing_enabled(settings):
        try:
            report.quota_probes = budget_control.probe_stale_providers(
                db, settings, now=budget_now
            )
        except Exception as exc:  # noqa: BLE001 - probing is advisory
            report.errors.append(f"Quota probe failed: {exc}")
        router = budget_control.QuotaRouter.build(db, settings, now=budget_now)
        report.provider_quota = router.provider_summary()
        report.lead_quota = router.lead_summary()
        budget_control.record_lead_shortage(db, router)
    if settings.launch_jobs:
        capacity = max(0, launch_limit - db.active_count())
        owner = f"tick:{socket.gethostname()}:{os.getpid()}"
        rank = (
            router.rank
            if router is not None and router.constrained(launch_limit)
            else None
        )
        for _ in range(capacity):
            if router is not None:
                task = db.claim_next_task(
                    owner=owner,
                    lease_seconds=settings.lease_seconds,
                    max_active=launch_limit,
                    resource_capacity=resource_capacity.to_dict(),
                    route=router.route,
                    rank=rank,
                )
            else:
                task = db.claim_next_task(
                    owner=owner,
                    lease_seconds=settings.lease_seconds,
                    max_active=launch_limit,
                    resource_capacity=resource_capacity.to_dict(),
                    excluded_runners=tuple(backoffs),
                    runner_active_limits=budget_control.probe_limits(db, now=budget_now),
                )
            if task is None:
                break
            if router is not None:
                router.deferred.pop(str(task["task_id"]), None)
                report.routed.append(
                    {
                        "task_id": str(task["task_id"]),
                        **router.decisions.get(
                            str(task["task_id"]), {"runner": str(task.get("runner") or "")}
                        ),
                    }
                )
            try:
                _launch_task(db, paths, settings, task, owner=owner)
                report.launched.append(str(task["task_id"]))
            # A lab-specific launch failure must not crash the scheduler process.
            except Exception as exc:  # noqa: BLE001
                disposition = db.fail_launch(
                    str(task["task_id"]),
                    str(exc),
                    settings.retry_backoff_seconds,
                )
                _apply_attempt_disposition(paths, report, disposition)
                if disposition.status == "quarantined":
                    report.quarantined.append(str(task["task_id"]))
                report.errors.append(f"Could not launch {task['task_id']}: {exc}")
                break

    if router is not None:
        _record_routing_deferrals(db, report, router)
    report.resource_reserved = db.active_resource_totals()
    report.status_counts = db.status_counts()
    return report


def _record_routing_deferrals(
    db: FactoryDB,
    report: TickReport,
    router: budget_control.QuotaRouter,
) -> None:
    """Tasks left queued because no runner fits: one event per task, reason and attempt."""

    for task_id, detail in sorted(router.deferred.items()):
        task = db.task(task_id)
        if task is None or str(task.get("status")) != "queued":
            continue
        entry = {"task_id": task_id, **detail}
        report.routing_deferred.append(entry)
        waiting = record_admission_deferral(db, task, detail)
        if waiting:
            report.program.setdefault("admissions_waiting", []).append(
                {"task_id": task_id, "topic_ids": waiting, **detail}
            )
        db.record_event_once(
            "task",
            task_id,
            "routing_deferred",
            detail,
            event_key=f"{detail.get('reason')}:attempt{int(task.get('attempt') or 0)}",
        )


def tick(paths: WorkspacePaths, settings: FactorySettings) -> TickReport:
    """Run one scheduler mutation under the same lock used by operator halt."""

    with factory_operation_lock(paths):
        return _tick_locked(paths, settings)
