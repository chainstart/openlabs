"""One idempotent factory tick: ingest, recover, lease, launch, and exit."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import FactorySettings, WorkspacePaths
from .contracts import (
    TASK_SCHEMA,
    atomic_write_json,
    sha256_file,
    validate_receipt,
    validate_task,
)
from .db import FactoryDB
from .gates import evaluate_result_bundle
from .labs import discover_labs, lab_for_domain


def _timestamp_token() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _inside(path: Path, roots: tuple[Path, ...]) -> bool:
    resolved = path.resolve()
    return any(
        resolved == root.resolve() or resolved.is_relative_to(root.resolve())
        for root in roots
    )


def _next_action_plan(
    action: object,
    *,
    current_role: str,
) -> tuple[str, str, str] | None:
    """Return objective, role, and effective session mode for one bounded successor."""

    if isinstance(action, str) and action.strip():
        return action.strip(), current_role, "resume"
    if not isinstance(action, Mapping):
        return None
    objective = str(action.get("objective") or "").strip()
    target_role = str(action.get("agent_role") or "").strip()
    requested_mode = str(action.get("session_mode") or "").strip()
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
        if target_role != current_role or target_role == "reviewer"
        else requested_mode
    )
    if effective_mode not in {"resume", "fresh"}:
        return None
    return objective, target_role, effective_mode


def _continuation_task_type(role: str) -> str:
    return {
        "researcher": "research_continue",
        "experimenter": "experiment_continue",
        "writer": "paper_revision",
        "reviewer": "independent_review",
    }[role]


@dataclass
class TickReport:
    ingested: list[dict[str, str]] = field(default_factory=list)
    recovered: list[str] = field(default_factory=list)
    quarantined: list[str] = field(default_factory=list)
    launched: list[str] = field(default_factory=list)
    enqueued: list[str] = field(default_factory=list)
    budget_stopped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    status_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "openlabs.tick_report.v1",
            "ingested": self.ingested,
            "recovered": self.recovered,
            "quarantined": self.quarantined,
            "launched": self.launched,
            "enqueued": self.enqueued,
            "budget_stopped": self.budget_stopped,
            "errors": self.errors,
            "status_counts": self.status_counts,
        }


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
            result_path = Path(str(receipt["result_path"])).expanduser().resolve()
            if not _inside(result_path, roots):
                raise ValueError(f"Result is outside data/artifact roots: {result_path}")
            expected_result = Path(str(task.get("output_path") or "")).resolve()
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
            gate = evaluate_result_bundle(payload, allowed_roots=roots)
            runtime = dict(receipt["runtime"])
            result_status = str(payload.get("status") or "failed")
            runtime_error: str | None = None
            if bool(runtime.get("timed_out")):
                result_status = "needs_replan"
                runtime_error = "Agent process timed out"
            elif int(runtime["exit_code"]) != 0:
                result_status = "failed"
                runtime_error = f"Lab runner exited with code {runtime['exit_code']}"
            next_actions = payload.get("next_actions", [])
            current_role = str(task.get("agent_role") or "researcher")
            next_plan = (
                _next_action_plan(next_actions[0], current_role=current_role)
                if isinstance(next_actions, list) and next_actions
                else None
            )
            continuity_required = (
                result_status in {"completed", "succeeded"}
                and current_role != "reviewer"
                and payload.get("paper_candidate") is not True
                and next_plan is not None
                and next_plan[1] == current_role
                and next_plan[2] == "resume"
            )
            if continuity_required and not runtime.get("session_id"):
                result_status = "needs_human"
                runtime["continuity_error"] = "resumable task returned no session_id"
                runtime_error = str(runtime["continuity_error"])
            errors = [*gate.blockers]
            if runtime_error:
                errors.append(runtime_error)
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
            if (
                final_status == "succeeded"
                and gate.passed
                and payload.get("paper_candidate") is True
            ):
                reviewer_passed = (
                    task.get("agent_role") == "reviewer"
                    and task.get("task_type") == "paper_readiness"
                )
                suffix = ":paper-write" if reviewer_passed else ":paper-readiness"
                paper_task_id = f"{task_id}{suffix}"
                if len(paper_task_id) > 128:
                    prefix = "paper-write" if reviewer_passed else "paper-readiness"
                    paper_task_id = f"{prefix}:{actual_sha[:32]}"
                if db.task(paper_task_id) is None:
                    paper_skills = {
                        "math": "openlabs-math-paper",
                        "ai": "openlabs-ai-paper",
                        "materials": "openlabs-materials-paper",
                    }
                    skill = paper_skills.get(domain)
                    if skill:
                        db.enqueue_task(
                            task_id=paper_task_id,
                            campaign_id=str(payload["campaign_id"]),
                            domain=domain,
                            task_type="paper_write" if reviewer_passed else "paper_readiness",
                            objective=(
                                "Write from the independently validated, frozen evidence only. "
                                "Do not broaden claims beyond the audit."
                                if reviewer_passed
                                else "Independently audit the frozen campaign evidence for a "
                                "defensible paper. Return only a readiness verdict and exact "
                                "evidence gaps; do not draft or revise the manuscript."
                            ),
                            input_path=str(result_path),
                            skill_path=skill,
                            runner="frontier",
                            routing_reason=(
                                "independent_audit_passed"
                                if reviewer_passed
                                else "paper_evidence_audit"
                            ),
                            parent_task_id=task_id,
                            agent_role="writer" if reviewer_passed else "reviewer",
                            session_mode="fresh",
                            priority=int(task.get("priority") or 0) + 1,
                            max_attempts=settings.max_attempts,
                            max_wall_seconds=settings.max_task_wall_seconds,
                        )
                        report.enqueued.append(paper_task_id)
            can_follow = (
                settings.auto_continue
                and next_plan is not None
                and str(task.get("task_type") or "") != "smoke"
                and current_role != "reviewer"
                and payload.get("paper_candidate") is not True
                and db.task_count(str(payload["campaign_id"]))
                < settings.max_auto_tasks_per_campaign
            )
            is_continuation = final_status == "succeeded" and gate.passed
            is_replan = final_status == "needs_replan" and gate.validation.valid
            if can_follow and (is_continuation or is_replan):
                objective, target_role, session_mode = next_plan
                if is_replan:
                    target_role = "researcher"
                    session_mode = "fresh"
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
                prefix = "replan" if is_replan else "continue"
                follow_task_id = f"{prefix}:{actual_sha[:32]}"
                if db.task(follow_task_id) is None:
                    db.enqueue_task(
                        task_id=follow_task_id,
                        campaign_id=str(payload["campaign_id"]),
                        domain=domain,
                        task_type=(
                            "replan" if is_replan else _continuation_task_type(target_role)
                        ),
                        objective=objective,
                        input_path=str(result_path),
                        skill_path=(
                            str(task["skill_path"]) if task.get("skill_path") else None
                        ),
                        runner="frontier" if is_replan else str(
                            task.get("runner") or "balanced"
                        ),
                        routing_reason=(
                            "gate_replan"
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
                        max_wall_seconds=settings.max_task_wall_seconds,
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


def _task_output_path(paths: WorkspacePaths, task: Mapping[str, Any]) -> Path:
    attempt_id = str(task.get("current_attempt_id") or "").strip()
    if not attempt_id:
        raise ValueError(f"Task {task.get('task_id')} has no current attempt")
    configured = task.get("requested_output_path")
    if isinstance(configured, str) and configured.strip():
        requested = Path(configured).expanduser().resolve()
        output = requested.parent / "attempts" / attempt_id / requested.name
    else:
        output = (
            paths.data
            / "workspaces"
            / str(task["domain"])
            / str(task["campaign_id"])
            / "results"
            / str(task["task_id"])
            / "attempts"
            / attempt_id
            / "result.json"
        ).resolve()
    campaign_root = (
        paths.data / "workspaces" / str(task["domain"]) / str(task["campaign_id"])
    ).resolve()
    if not _inside(output, (campaign_root,)):
        raise ValueError(f"Task output must be inside its campaign workspace: {output}")
    return output


def _write_task_spec(
    paths: WorkspacePaths,
    task: Mapping[str, Any],
    *,
    lab_id: str,
    manifest_path: Path,
    skill_path: Path | None,
    output_path: Path,
    wall_seconds: int,
) -> Path:
    campaign_workspace = (
        paths.data / "workspaces" / str(task["domain"]) / str(task["campaign_id"])
    ).resolve()
    campaign_workspace.mkdir(parents=True, exist_ok=True)
    agent_workspace = (
        output_path.parent
        if task.get("agent_role") == "reviewer"
        else campaign_workspace
    )
    agent_workspace.mkdir(parents=True, exist_ok=True)
    run_metadata_path = output_path.parent / "run-metadata.json"
    payload = {
        "schema_version": TASK_SCHEMA,
        "task_id": task["task_id"],
        "attempt_id": task["current_attempt_id"],
        "campaign_id": task["campaign_id"],
        "lab_id": lab_id,
        "domain": task["domain"],
        "task_type": task["task_type"],
        "objective": task["objective"],
        "input_path": task.get("input_path"),
        "output_path": str(output_path),
        "skill_path": str(skill_path) if skill_path else task.get("skill_path"),
        "runner": task.get("runner") or "balanced",
        "lab_manifest": str(manifest_path),
        "attempt": task["attempt"],
        "agent_workspace": str(agent_workspace),
        "run_metadata_path": str(run_metadata_path),
        "routing_reason": task.get("routing_reason") or "manual",
        "parent_task_id": task.get("parent_task_id"),
        "agent": {
            "role": task.get("agent_role") or "researcher",
            "session_mode": task.get("session_mode") or "resume",
            "session_id": (
                None
                if task.get("agent_role") == "reviewer"
                or task.get("session_mode") == "fresh"
                else task.get("agent_session_id")
            ),
        },
        "budget": {"wall_seconds": max(1, int(wall_seconds))},
    }
    validation = validate_task(payload)
    if not validation.valid:
        raise ValueError("; ".join(validation.errors))
    return atomic_write_json(
        paths.job_inbox / f"{task['task_id']}-{task['current_attempt_id']}.json",
        payload,
    )


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
    output_path = _task_output_path(paths, task)
    campaign = db.campaign(str(task["campaign_id"]))
    if campaign is None:
        raise ValueError(f"Unknown campaign: {task['campaign_id']}")
    remaining = max(
        0,
        int(float(campaign["max_agent_seconds"]) - float(campaign["agent_seconds_used"])),
    )
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
        lab_id=lab.lab_id,
        manifest_path=lab.root / "lab.json",
        skill_path=skill_path,
        output_path=output_path,
        wall_seconds=wall_seconds,
    )
    log_path = output_path.parent / "worker.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment["OPENLABS_WORKSPACE"] = str(paths.workspace)
    environment["OPENLABS_JOB_SPEC"] = str(job_path)
    db.mark_running(
        str(task["task_id"]),
        attempt_id=str(task["current_attempt_id"]),
        owner=owner,
        pid=None,
        lease_seconds=settings.lease_seconds,
    )
    with log_path.open("ab") as log_handle:
        process = subprocess.Popen(
            [sys.executable, "-m", "openlabs", "_worker", str(job_path)],
            cwd=paths.code,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    try:
        db.set_worker_pid(
            str(task["task_id"]),
            attempt_id=str(task["current_attempt_id"]),
            pid=process.pid,
        )
    except Exception:
        process.terminate()
        raise


def tick(paths: WorkspacePaths, settings: FactorySettings) -> TickReport:
    paths.ensure_runtime_directories()
    db = FactoryDB(paths.database_file)
    db.initialize()
    report = TickReport()

    # Ingest first so a completed worker is not requeued just because its lease expired.
    ingest_results(db, paths, settings, report)
    recovery = db.recover_expired(settings.retry_backoff_seconds)
    report.recovered.extend(recovery.requeued)
    report.quarantined.extend(recovery.quarantined)
    report.budget_stopped.extend(db.stop_budget_exhausted_tasks())

    if settings.launch_jobs:
        capacity = max(0, settings.max_concurrent_jobs - db.active_count())
        owner = f"tick:{socket.gethostname()}:{os.getpid()}"
        for _ in range(capacity):
            task = db.claim_next_task(
                owner=owner,
                lease_seconds=settings.lease_seconds,
                max_active=settings.max_concurrent_jobs,
            )
            if task is None:
                break
            try:
                _launch_task(db, paths, settings, task, owner=owner)
                report.launched.append(str(task["task_id"]))
            # A lab-specific launch failure must not crash the scheduler process.
            except Exception as exc:  # noqa: BLE001
                db.fail_launch(
                    str(task["task_id"]),
                    str(exc),
                    settings.retry_backoff_seconds,
                )
                report.errors.append(f"Could not launch {task['task_id']}: {exc}")
                break

    report.status_counts = db.status_counts()
    return report
