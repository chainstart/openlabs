"""Operator-owned lifecycle controls for bounded production runs."""

from __future__ import annotations

import json
import os
import signal
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .attempts import quarantine_attempt_workspace
from .config import WorkspacePaths
from .contracts import atomic_write_json
from .db import FactoryDB
from .locking import factory_operation_lock


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _is_openlabs_worker(pid: int) -> bool:
    try:
        command = (Path("/proc") / str(pid) / "cmdline").read_bytes().split(b"\0")
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return False
    return b"openlabs" in command and b"_worker" in command


def _terminate_recorded_workers(pids: list[int]) -> list[int]:
    signalled: list[int] = []
    for pid in sorted(set(pids)):
        if pid <= 1 or not _is_openlabs_worker(pid):
            continue
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except ProcessLookupError:
            continue
        signalled.append(pid)
    return signalled


def _systemctl(*arguments: str) -> dict[str, Any]:
    completed = subprocess.run(
        ["systemctl", "--user", *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "arguments": list(arguments),
        "returncode": completed.returncode,
        "stderr": completed.stderr.strip(),
    }


def _pause_projects_for_plan(
    paths: WorkspacePaths,
    plan_path: Path,
) -> list[dict[str, str]]:
    """Pause generic desired-state projects whose domain config is this plan."""

    roots = paths.data / "workspaces"
    candidates = {
        *roots.glob("*/projects/*/project.json"),
        *roots.glob("*/production/*/project.json"),
    }
    paused: list[dict[str, str]] = []
    for project_path in sorted(candidates):
        payload = json.loads(project_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError(f"Invalid project config: {project_path}")
        domain_config = payload.get("domain_config")
        if not isinstance(domain_config, dict):
            continue
        configured = str(domain_config.get("path") or "").strip()
        if not configured or (project_path.parent / configured).resolve() != plan_path:
            continue
        prior_status = str(payload.get("status") or "")
        payload["status"] = "paused"
        atomic_write_json(project_path, payload)
        paused.append(
            {
                "project_id": str(payload.get("project_id") or ""),
                "project_path": str(project_path.resolve()),
                "prior_status": prior_status,
                "final_status": "paused",
            }
        )
    return paused


def _halt_production_locked(
    paths: WorkspacePaths,
    *,
    plan_path: Path,
    reason: str,
    report_path: Path | None = None,
    stop_systemd: bool = True,
) -> dict[str, Any]:
    """Pause one desired-state plan, cancel its work, and stop the local factory."""

    plan_path = plan_path.expanduser().resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if not isinstance(plan, dict) or not str(plan.get("plan_id") or "").strip():
        raise ValueError(f"Invalid production plan: {plan_path}")
    reason = reason.strip()
    if not reason:
        raise ValueError("A halt reason is required")

    stopped_at = _utc_now()
    prior_status = str(plan.get("status") or "")
    plan["status"] = "paused_timebox_complete"
    run_control = plan.setdefault("run_control", {})
    if not isinstance(run_control, dict):
        raise TypeError("plan run_control must be an object")
    run_control.update(
        {
            "actual_stop_at": stopped_at,
            "stop_reason": reason,
            "stop_status": "completed",
        }
    )
    atomic_write_json(plan_path, plan)
    paused_projects = _pause_projects_for_plan(paths, plan_path)
    paused_project_paths = {
        str(Path(item["project_path"]).resolve()) for item in paused_projects
    }

    db = FactoryDB(paths.database_file)
    db.initialize()
    campaigns = []
    for campaign in db.production_campaigns():
        configured = campaign.get("production_plan_path")
        project_configured = campaign.get("project_config_path")
        legacy_match = bool(configured) and (
            Path(str(configured)).expanduser().resolve() == plan_path
        )
        project_match = bool(project_configured) and (
            str(Path(str(project_configured)).expanduser().resolve())
            in paused_project_paths
        )
        if legacy_match or project_match:
            campaigns.append(str(campaign["campaign_id"]))

    queued_cancelled: list[str] = []
    for campaign_id in campaigns:
        queued_cancelled.extend(db.pause_production_campaign(campaign_id, reason=reason))
    active_cancelled = list(db.cancel_active_tasks(campaigns, reason=reason))
    attempt_checkpoints: list[dict[str, Any]] = []
    for item in active_cancelled:
        attempt_id = str(item.get("attempt_id") or "").strip()
        if not attempt_id:
            continue
        checkpoint = quarantine_attempt_workspace(
            paths,
            campaign_id=str(item["campaign_id"]),
            attempt_id=attempt_id,
            reason=f"operator_cancelled:{reason}",
        )
        if checkpoint is not None:
            attempt_checkpoints.append(
                {
                    "task_id": item["task_id"],
                    "campaign_id": item["campaign_id"],
                    "attempt_id": attempt_id,
                    "status": checkpoint.get("status"),
                    "workspace": str(
                        Path(str(checkpoint["staged_campaign_root"])).resolve().parents[2]
                    ),
                }
            )
    worker_pids = [
        int(item["worker_pid"]) for item in active_cancelled if item.get("worker_pid") is not None
    ]
    # Project/plan cancellation is always targeted first.  ``stop_systemd``
    # controls only the factory-wide units; it must not leave the cancelled
    # workers running when an operator deliberately keeps the rest of the
    # factory online.
    signalled = _terminate_recorded_workers(worker_pids)
    systemd: list[dict[str, Any]] = []
    if stop_systemd:
        systemd.append(_systemctl("stop", "openlabs-workers.target"))
        systemd.append(_systemctl("disable", "--now", "openlabs-factory.target"))

    report = {
        "schema_version": "openlabs.production_halt.v1",
        "plan_id": plan["plan_id"],
        "plan_path": str(plan_path),
        "prior_status": prior_status,
        "final_status": plan["status"],
        "reason": reason,
        "stopped_at": stopped_at,
        "projects": paused_projects,
        "campaigns": campaigns,
        "queued_cancelled": sorted(queued_cancelled),
        "active_cancelled": active_cancelled,
        "attempt_checkpoints": attempt_checkpoints,
        "worker_pids_signalled": signalled,
        "systemd": systemd,
    }
    if report_path is not None:
        atomic_write_json(report_path.expanduser().resolve(), report)
    return report


def halt_production(
    paths: WorkspacePaths,
    *,
    plan_path: Path,
    reason: str,
    report_path: Path | None = None,
    stop_systemd: bool = True,
) -> dict[str, Any]:
    """Serialize deadline cancellation against result ingestion and promotion."""

    with factory_operation_lock(paths):
        return _halt_production_locked(
            paths,
            plan_path=plan_path,
            reason=reason,
            report_path=report_path,
            stop_systemd=stop_systemd,
        )


def _halt_project_locked(
    paths: WorkspacePaths,
    *,
    project_path: Path,
    reason: str,
    report_path: Path | None = None,
    stop_systemd: bool = True,
) -> dict[str, Any]:
    """Pause one generic project and atomically cancel its materialized work."""

    project_path = project_path.expanduser().resolve()
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project_id = str(project.get("project_id") or "").strip() if isinstance(project, dict) else ""
    if not project_id:
        raise ValueError(f"Invalid project config: {project_path}")
    reason = reason.strip()
    if not reason:
        raise ValueError("A halt reason is required")

    stopped_at = _utc_now()
    prior_status = str(project.get("status") or "")
    project["status"] = "paused"
    atomic_write_json(project_path, project)

    db = FactoryDB(paths.database_file)
    db.initialize()
    campaigns = sorted(
        str(campaign["campaign_id"])
        for campaign in db.project_campaigns()
        if str(campaign.get("project_config_path") or "")
        and Path(str(campaign["project_config_path"])).expanduser().resolve() == project_path
    )
    queued_cancelled: list[str] = []
    for campaign_id in campaigns:
        queued_cancelled.extend(db.pause_production_campaign(campaign_id, reason=reason))
    active_cancelled = list(db.cancel_active_tasks(campaigns, reason=reason))
    attempt_checkpoints: list[dict[str, Any]] = []
    for item in active_cancelled:
        attempt_id = str(item.get("attempt_id") or "").strip()
        if not attempt_id:
            continue
        checkpoint = quarantine_attempt_workspace(
            paths,
            campaign_id=str(item["campaign_id"]),
            attempt_id=attempt_id,
            reason=f"operator_cancelled:{reason}",
        )
        if checkpoint is not None:
            attempt_checkpoints.append(
                {
                    "task_id": item["task_id"],
                    "campaign_id": item["campaign_id"],
                    "attempt_id": attempt_id,
                    "status": checkpoint.get("status"),
                    "workspace": str(
                        Path(str(checkpoint["staged_campaign_root"])).resolve().parents[2]
                    ),
                }
            )
    worker_pids = [
        int(item["worker_pid"])
        for item in active_cancelled
        if item.get("worker_pid") is not None
    ]
    # Keep project-local cancellation effective even when other projects must
    # remain online.  The factory-wide targets below are optional; the recorded
    # workers belonging to this project are not.
    signalled = _terminate_recorded_workers(worker_pids)
    systemd: list[dict[str, Any]] = []
    if stop_systemd:
        systemd.append(_systemctl("stop", "openlabs-workers.target"))
        systemd.append(_systemctl("disable", "--now", "openlabs-factory.target"))

    report = {
        "schema_version": "openlabs.project_halt.v1",
        "project_id": project_id,
        "project_path": str(project_path),
        "prior_status": prior_status,
        "final_status": "paused",
        "reason": reason,
        "stopped_at": stopped_at,
        "campaigns": campaigns,
        "queued_cancelled": sorted(queued_cancelled),
        "active_cancelled": active_cancelled,
        "attempt_checkpoints": attempt_checkpoints,
        "worker_pids_signalled": signalled,
        "systemd": systemd,
    }
    if report_path is not None:
        atomic_write_json(report_path.expanduser().resolve(), report)
    return report


def halt_project(
    paths: WorkspacePaths,
    *,
    project_path: Path,
    reason: str,
    report_path: Path | None = None,
    stop_systemd: bool = True,
) -> dict[str, Any]:
    """Serialize generic-project cancellation against result ingestion and promotion."""

    with factory_operation_lock(paths):
        return _halt_project_locked(
            paths,
            project_path=project_path,
            reason=reason,
            report_path=report_path,
            stop_systemd=stop_systemd,
        )
