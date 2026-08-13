"""Generic project indexing, periodic review, and agent-selected branch materialization.

This module moves no scientific judgment into the control plane. It observes that results exist,
packages them for a blank reviewer, and executes the reviewer's typed candidate handoff verbatim.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import FactorySettings, WorkspacePaths
from .contracts import atomic_write_json, canonical_json_bytes, sha256_file
from .db import FactoryDB
from .labs import discover_labs, lab_for_domain
from .projects import load_project, workstream_policy
from .protocols import validate_protocol_state
from .resources import ResourceVector, default_task_resources


PROJECT_INDEX_SCHEMA = "openlabs.project_research_index.v1"
REVIEW_PACKET_SCHEMA = "openlabs.portfolio_review_packet.v1"
REVIEW_CURSOR_SCHEMA = "openlabs.portfolio_review_cursor.v1"


@dataclass(frozen=True)
class ReviewSchedule:
    task_id: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class CandidateSpawn:
    campaign_ids: tuple[str, ...] = ()
    task_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReviewReconciliation:
    reconciled: bool = False
    spawned: CandidateSpawn = CandidateSpawn()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected an object: {path}")
    return value


def _verified_review_packet(path: Path) -> dict[str, Any]:
    packet = _read_object(path)
    if packet.get("schema_version") != REVIEW_PACKET_SCHEMA:
        raise ValueError(f"unsupported portfolio review packet: {path}")
    expected = str(packet.get("content_sha256") or "")
    unsigned = dict(packet)
    unsigned.pop("content_sha256", None)
    actual = hashlib.sha256(canonical_json_bytes(unsigned)).hexdigest()
    if not expected or actual != expected:
        raise ValueError(f"portfolio review packet hash mismatch: {path}")
    return packet


def _verified_review_cursor(path: Path) -> dict[str, Any]:
    cursor = _read_object(path)
    if cursor.get("schema_version") != REVIEW_CURSOR_SCHEMA:
        raise ValueError(f"unsupported portfolio review cursor: {path}")
    expected = str(cursor.get("content_sha256") or "")
    unsigned = dict(cursor)
    unsigned.pop("content_sha256", None)
    actual = hashlib.sha256(canonical_json_bytes(unsigned)).hexdigest()
    if not expected or actual != expected:
        raise ValueError(f"portfolio review cursor hash mismatch: {path}")
    return cursor


def project_research_index_path(campaign: Mapping[str, Any]) -> Path | None:
    configured = str(campaign.get("project_config_path") or "").strip()
    if not configured:
        return None
    return load_project(configured).research_index_path


def rebuild_project_research_index(
    db: FactoryDB,
    campaign: Mapping[str, Any],
) -> Path | None:
    """Mechanically rebuild the derived index from succeeded hash-bound results."""

    configured = str(campaign.get("project_config_path") or "").strip()
    if not configured:
        return None
    project = load_project(configured)
    index_path = project.research_index_path
    if index_path is None:
        return None
    campaign_ids = set(project.research_index_source_campaign_ids)
    with db.connect() as connection:
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(campaigns)").fetchall()
        }
        if "project_id" in columns:
            campaign_ids.update(
                str(row["campaign_id"])
                for row in connection.execute(
                    "SELECT campaign_id FROM campaigns WHERE project_id=?",
                    (project.project_id,),
                ).fetchall()
            )
        rows: list[Any] = []
        if campaign_ids:
            placeholders = ",".join("?" for _ in campaign_ids)
            rows = connection.execute(
                f"""
                SELECT task_id, campaign_id, agent_role, task_type, status,
                       result_path, result_sha256, updated_at
                FROM tasks
                WHERE campaign_id IN ({placeholders}) AND status='succeeded'
                ORDER BY updated_at, task_id
                """,
                tuple(sorted(campaign_ids)),
            ).fetchall()
    entries: list[dict[str, Any]] = []
    for row in rows:
        result_path = Path(str(row["result_path"] or "")).expanduser().resolve()
        expected_sha = str(row["result_sha256"] or "")
        if not result_path.is_file() or not expected_sha:
            continue
        actual_sha = sha256_file(result_path)
        if actual_sha != expected_sha:
            continue
        try:
            payload = _read_object(result_path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        entries.append(
            {
                "result_id": str(row["task_id"]),
                "campaign_id": str(row["campaign_id"]),
                "agent_role": str(row["agent_role"] or ""),
                "task_type": str(row["task_type"] or ""),
                "status": "succeeded",
                "summary": payload.get("summary"),
                "claims": payload.get("claims", []),
                "paper_candidate": payload.get("paper_candidate") is True,
                "result_path": str(result_path),
                "sha256": actual_sha,
                "indexed_at": str(row["updated_at"] or ""),
            }
        )
    atomic_write_json(
        index_path,
        {
            "schema_version": PROJECT_INDEX_SCHEMA,
            "project_id": project.project_id,
            "source_campaign_ids": sorted(campaign_ids),
            "results": entries,
            "updated_at": _now(),
        },
    )
    return index_path


def index_project_result(
    campaign: Mapping[str, Any],
    task: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    result_path: Path,
    result_sha256: str,
    final_status: str,
) -> None:
    """Append transport metadata without interpreting the scientific content."""

    index_path = project_research_index_path(campaign)
    if index_path is None:
        return
    try:
        index = _read_object(index_path)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        index = {
            "schema_version": PROJECT_INDEX_SCHEMA,
            "project_id": campaign.get("project_id"),
            "results": [],
        }
    if index.get("schema_version") != PROJECT_INDEX_SCHEMA:
        raise ValueError(f"unsupported project research index: {index_path}")
    entries = index.get("results")
    if not isinstance(entries, list):
        raise ValueError(f"project research index results must be an array: {index_path}")
    task_id = str(task.get("task_id") or payload.get("task_id") or "")
    entry = {
        "result_id": task_id,
        "campaign_id": task.get("campaign_id"),
        "agent_role": task.get("agent_role"),
        "task_type": task.get("task_type"),
        "status": final_status,
        "summary": payload.get("summary"),
        "claims": payload.get("claims", []),
        "paper_candidate": payload.get("paper_candidate") is True,
        "result_path": str(result_path),
        "sha256": result_sha256,
        "indexed_at": _now(),
    }
    for index_number, existing in enumerate(entries):
        if isinstance(existing, Mapping) and existing.get("result_id") == task_id:
            entries[index_number] = entry
            break
    else:
        entries.append(entry)
    index["project_id"] = campaign.get("project_id") or index.get("project_id")
    index["results"] = entries
    index["updated_at"] = entry["indexed_at"]
    atomic_write_json(index_path, index)


def _review_control_root(paths: WorkspacePaths, campaign: Mapping[str, Any]) -> Path:
    project_id = str(campaign.get("project_id") or "project")
    campaign_id = str(campaign.get("campaign_id") or "review")
    project_token = re.sub(r"[^a-zA-Z0-9._-]+", "-", project_id).strip("-._")
    digest = hashlib.sha256(campaign_id.encode()).hexdigest()[:16]
    return paths.artifacts / "portfolio-control" / (project_token or "project") / digest


def _review_cursor_path(paths: WorkspacePaths, campaign: Mapping[str, Any]) -> Path:
    return _review_control_root(paths, campaign) / "review_cursor.json"


def _reviewed_result_ids(paths: WorkspacePaths, campaign: Mapping[str, Any]) -> set[str]:
    path = _review_cursor_path(paths, campaign)
    if not path.is_file():
        return set()
    value = _verified_review_cursor(path).get("reviewed_result_ids", [])
    return {str(item) for item in value if isinstance(item, str) and item}


def advance_review_cursor(task: Mapping[str, Any]) -> bool:
    packet_value = str(task.get("input_path") or "").strip()
    if not packet_value:
        return False
    packet_path = Path(packet_value).resolve()
    if not packet_path.is_file():
        return False
    try:
        packet = _verified_review_packet(packet_path)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    cursor_value = packet.get("cursor_path")
    if not isinstance(cursor_value, str) or not cursor_value:
        return False
    cursor_path = Path(cursor_value).resolve()
    reviewed: set[str] = set()
    if cursor_path.is_file():
        reviewed.update(
            str(item)
            for item in _verified_review_cursor(cursor_path).get("reviewed_result_ids", [])
            if isinstance(item, str) and item
        )
    reviewed.update(
        str(item)
        for item in packet.get("result_ids", [])
        if isinstance(item, str) and item
    )
    cursor = {
        "schema_version": REVIEW_CURSOR_SCHEMA,
        "reviewed_result_ids": sorted(reviewed),
        "last_review_task_id": task.get("task_id"),
        "updated_at": _now(),
    }
    cursor["content_sha256"] = hashlib.sha256(canonical_json_bytes(cursor)).hexdigest()
    atomic_write_json(cursor_path, cursor)
    return True


def _task_id(campaign_id: str, epoch: int, source: str) -> str:
    digest = hashlib.sha256(f"{campaign_id}\0{epoch}\0{source}".encode()).hexdigest()
    return f"production:{epoch}:{digest[:32]}"


def schedule_portfolio_review(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    campaign: Mapping[str, Any],
    *,
    epoch: int,
) -> ReviewSchedule:
    campaign_id = str(campaign["campaign_id"])
    index_path = rebuild_project_research_index(db, campaign)
    if index_path is None or not index_path.is_file():
        return ReviewSchedule(reason="awaiting_project_research_index")
    index = _read_object(index_path)
    entries = index.get("results", [])
    if not isinstance(entries, list):
        raise ValueError("project research index results must be an array")
    reviewed = _reviewed_result_ids(paths, campaign)
    eligible = [
        dict(item)
        for item in entries
        if isinstance(item, Mapping)
        and str(item.get("result_id") or "") not in reviewed
        and str(item.get("campaign_id") or "") != campaign_id
        and str(item.get("agent_role") or "") in {"researcher", "experimenter"}
        and str(item.get("status") or "") == "succeeded"
    ]
    policy = workstream_policy(campaign)
    threshold = int(policy.get("review_every_results") or 1)
    if len(eligible) < threshold:
        return ReviewSchedule(reason="awaiting_new_research_results")
    batch_size = max(1, int(policy.get("review_batch_size") or 32))
    eligible = eligible[:batch_size]
    source_ids = [str(item["result_id"]) for item in eligible]
    digest = hashlib.sha256("\0".join(source_ids).encode()).hexdigest()
    latest = db.latest_task(campaign_id)
    source = digest + (str(latest.get("task_id")) if latest else "")
    task_id = _task_id(campaign_id, epoch, source)
    if db.task(task_id) is not None:
        return ReviewSchedule(reason="review_already_scheduled")
    control_root = _review_control_root(paths, campaign)
    packet_path = control_root / "review-packets" / f"{digest[:24]}.json"
    packet = {
        "schema_version": REVIEW_PACKET_SCHEMA,
        "project_id": campaign.get("project_id"),
        "review_campaign_id": campaign_id,
        "cursor_path": str(_review_cursor_path(paths, campaign)),
        "result_ids": source_ids,
        "results": eligible,
        "created_at": _now(),
    }
    packet["content_sha256"] = hashlib.sha256(canonical_json_bytes(packet)).hexdigest()
    atomic_write_json(packet_path, packet)
    objective = str(policy.get("objective") or "").strip()
    objective = (
        (objective + " " if objective else "")
        + "Independently inspect every result in the supplied review packet and the linked "
        "immutable evidence. You—not the scheduler—decide whether any result, synthesis, negative "
        "theorem, or new bridge deserves a dedicated maturation branch. Record each such judgment "
        "in candidate_branches with a stable candidate_id, exact research objective, rationale, "
        "and source_result_ids. An empty candidate_branches array is a valid scientific verdict. "
        "Do not draft a paper in this review task."
    )
    resources = default_task_resources(settings)
    db.enqueue_task(
        task_id=task_id,
        campaign_id=campaign_id,
        domain=str(campaign["domain"]),
        task_type="portfolio_review",
        objective=objective,
        input_path=str(packet_path),
        skill_path=str(campaign.get("primary_skill") or ""),
        runner="frontier",
        routing_reason="new_project_results_review",
        agent_role="reviewer",
        session_mode="fresh",
        priority=int(campaign.get("priority") or 0),
        max_attempts=settings.max_attempts,
        max_wall_seconds=settings.max_task_wall_seconds,
        **resources.to_dict(),
    )
    return ReviewSchedule(task_id=task_id)


def _candidate_campaign_id(project_id: str, candidate_id: str) -> str:
    readable = re.sub(r"[^a-zA-Z0-9._-]+", "-", candidate_id).strip("-._")[:36]
    digest = hashlib.sha256(f"{project_id}\0{candidate_id}".encode()).hexdigest()[:16]
    prefix = f"{project_id}-candidate-{readable or 'idea'}"
    value = f"{prefix}-{digest}"
    return value if len(value) <= 128 else f"candidate-{digest}"


def spawn_candidate_workstreams(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    source_campaign: Mapping[str, Any],
    task: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    result_path: Path,
) -> CandidateSpawn:
    policy = workstream_policy(source_campaign)
    branches = payload.get("candidate_branches", [])
    if (
        policy.get("spawn_candidate_workstreams") is not True
        or str(task.get("agent_role") or "") != "reviewer"
        or not isinstance(branches, list)
        or not branches
    ):
        return CandidateSpawn()
    project_path = Path(str(source_campaign.get("project_config_path") or "")).resolve()
    project = load_project(project_path)
    if project.status != "active":
        raise ValueError("project is not active; defer candidate materialization")
    portfolio = project.raw.get("portfolio")
    if not isinstance(portfolio, Mapping) or portfolio.get(
        "allow_dynamic_candidate_workstreams"
    ) is not True:
        raise ValueError("project does not allow reviewer-created candidate workstreams")
    known_results: set[str] = set()
    if project.research_index_path is not None:
        known_results.update(
            str(item.get("result_id"))
            for item in _read_object(project.research_index_path).get("results", [])
            if isinstance(item, Mapping)
            and item.get("result_id")
            and str(item.get("status") or "") == "succeeded"
            and str(item.get("agent_role") or "") in {"researcher", "experimenter"}
        )
    packet_path = Path(str(task.get("input_path") or "")).resolve()
    if not packet_path.is_file():
        raise ValueError("portfolio reviewer has no immutable review packet")
    packet = _verified_review_packet(packet_path)
    packet_results = {
        str(item) for item in packet.get("result_ids", []) if isinstance(item, str) and item
    }
    known_results.intersection_update(packet_results)
    labs = discover_labs(paths.code)
    lab = lab_for_domain(labs, project.domain)
    protocol = lab.protocol(project.protocol_id)
    if protocol is None:
        raise ValueError(f"project protocol is not registered: {project.protocol_id}")
    campaign_ids: list[str] = []
    task_ids: list[str] = []
    for raw_branch in branches:
        if not isinstance(raw_branch, Mapping):
            continue
        candidate_id = str(raw_branch.get("candidate_id") or "").strip()
        source_result_ids = {
            str(item) for item in raw_branch.get("source_result_ids", []) if str(item).strip()
        }
        unknown = source_result_ids - known_results
        if unknown:
            raise ValueError(
                f"candidate {candidate_id} cites unknown project results: {sorted(unknown)}"
            )
        campaign_id = _candidate_campaign_id(project.project_id, candidate_id)
        campaign_root = paths.data / "workspaces" / project.domain / campaign_id
        state_path = campaign_root / "research_state.json"
        existing = db.campaign(campaign_id)
        current_validation = (
            validate_protocol_state(
                lab,
                protocol,
                project_path=project.path,
                workstream_path=state_path,
                mode="discovery",
            )
            if state_path.is_file()
            else None
        )
        if current_validation is not None and not current_validation.valid and existing is not None:
            raise ValueError(
                f"candidate {candidate_id} existing state rejected by protocol: "
                + "; ".join(current_validation.errors)
            )
        if current_validation is None or not current_validation.valid:
            campaign_root.mkdir(parents=True, exist_ok=True)
            state_template = portfolio.get("candidate_state_template")
            if not isinstance(state_template, Mapping):
                raise ValueError("project portfolio requires candidate_state_template")
            candidate_state = dict(state_template)
            candidate_state.update(
                {
                    "project_id": project.project_id,
                    "workstream_id": campaign_id,
                    "candidate_id": candidate_id,
                    "title": raw_branch.get("title"),
                    "objective": raw_branch.get("objective"),
                    "rationale": raw_branch.get("rationale"),
                    "source_result_ids": sorted(source_result_ids),
                    "source_review_task_id": task.get("task_id"),
                    "source_review_result": str(result_path),
                    "created_at": _now(),
                }
            )
            pending_state = state_path.with_name(
                f".{state_path.name}.{hashlib.sha256(candidate_id.encode()).hexdigest()[:12]}.pending"
            )
            try:
                atomic_write_json(pending_state, candidate_state)
                validation = validate_protocol_state(
                    lab,
                    protocol,
                    project_path=project.path,
                    workstream_path=pending_state,
                    mode="discovery",
                )
                if not validation.valid:
                    raise ValueError(
                        f"candidate {candidate_id} state rejected by protocol: "
                        + "; ".join(validation.errors)
                    )
                pending_state.replace(state_path)
            finally:
                pending_state.unlink(missing_ok=True)
        if existing is None:
            db.register_campaign(
                campaign_id,
                domain=project.domain,
                title=str(raw_branch.get("title") or candidate_id),
                priority=int(source_campaign.get("priority") or 0) + 1,
                state_path=str(campaign_root),
                source=str(project.path),
                max_agent_seconds=settings.max_campaign_agent_seconds,
            )
        db.configure_project_campaign(
            campaign_id,
            project_config_path=str(project.path),
            workstream_state_path=str(state_path),
            protocol_id=project.protocol_id,
            primary_skill=project.primary_skill,
            execution_policy=project.execution.to_dict(),
            project_id=project.project_id,
            workstream_policy={
                "dynamic": True,
                "continuation": "continuous",
                "default_agent_role": "researcher",
                "default_session_mode": "resume",
                "objective": str(raw_branch.get("objective") or ""),
                "source_review_task_id": task.get("task_id"),
                "candidate_id": candidate_id,
            },
            priority=int(source_campaign.get("priority") or 0) + 1,
        )
        db.upsert_research_record(
            f"candidate:{project.project_id}:{candidate_id}",
            kind="candidate",
            domain=project.domain,
            title=str(raw_branch.get("title") or candidate_id),
            status="maturing",
            source_path=str(result_path),
            metadata={
                "campaign_id": campaign_id,
                "source_review_task_id": task.get("task_id"),
                "source_result_ids": sorted(source_result_ids),
                "rationale": raw_branch.get("rationale"),
            },
        )
        if db.task_count(campaign_id):
            continue
        resources_value = raw_branch.get("resources")
        resources = (
            ResourceVector.from_mapping(resources_value)
            if isinstance(resources_value, Mapping)
            else default_task_resources(settings)
        )
        requested_wall = raw_branch.get("wall_seconds")
        wall_seconds = min(
            int(requested_wall)
            if isinstance(requested_wall, int)
            else settings.max_task_wall_seconds,
            settings.max_task_wall_seconds,
        )
        first_task_id = f"candidate:{hashlib.sha256(campaign_id.encode()).hexdigest()[:32]}"
        maturation_instruction = str(
            portfolio.get("candidate_maturation_instruction") or ""
        ).strip()
        db.enqueue_task(
            task_id=first_task_id,
            campaign_id=campaign_id,
            domain=project.domain,
            task_type="candidate_maturation",
            objective=(
                str(raw_branch.get("objective") or "")
                + " Freely deepen, revise, generalize, falsify, or abandon this reviewer-selected "
                "idea as the evidence warrants. "
                + (maturation_instruction + " " if maturation_instruction else "")
                + "The original free-research workstream continues independently."
            ),
            input_path=str(result_path),
            skill_path=project.primary_skill,
            runner="frontier",
            routing_reason="reviewer_selected_candidate_maturation",
            agent_role="researcher",
            session_mode="fresh",
            priority=int(source_campaign.get("priority") or 0) + 1,
            max_attempts=settings.max_attempts,
            max_wall_seconds=wall_seconds,
            **resources.to_dict(),
        )
        campaign_ids.append(campaign_id)
        task_ids.append(first_task_id)
    return CandidateSpawn(tuple(campaign_ids), tuple(task_ids))


def reconcile_pending_portfolio_review(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    campaign: Mapping[str, Any],
) -> ReviewReconciliation:
    """Retry a succeeded reviewer handoff until branches and cursor are durable."""

    latest = db.latest_task(str(campaign["campaign_id"]))
    if (
        latest is None
        or str(latest.get("task_type") or "") != "portfolio_review"
        or str(latest.get("status") or "") != "succeeded"
    ):
        return ReviewReconciliation()
    packet_value = str(latest.get("input_path") or "").strip()
    result_value = str(latest.get("result_path") or "").strip()
    if not packet_value or not result_value:
        return ReviewReconciliation()
    packet_path = Path(packet_value).resolve()
    result_path = Path(result_value).resolve()
    if not packet_path.is_file() or not result_path.is_file():
        return ReviewReconciliation()
    packet = _verified_review_packet(packet_path)
    reviewed = _reviewed_result_ids(paths, campaign)
    packet_ids = {
        str(item) for item in packet.get("result_ids", []) if isinstance(item, str) and item
    }
    if packet_ids and packet_ids.issubset(reviewed):
        return ReviewReconciliation()
    expected_sha = str(latest.get("result_sha256") or "")
    if not expected_sha or sha256_file(result_path) != expected_sha:
        raise ValueError("pending portfolio review result is not hash-bound")
    payload = _read_object(result_path)
    spawned = spawn_candidate_workstreams(
        db,
        paths,
        settings,
        campaign,
        latest,
        payload,
        result_path=result_path,
    )
    if not advance_review_cursor(latest):
        raise ValueError("could not durably advance portfolio review cursor")
    return ReviewReconciliation(reconciled=True, spawned=spawned)
