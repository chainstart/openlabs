"""Owner mode: one owner agent carries an admitted topic to review or a freeze.

Owner decision 2026-11-14: after admission a single main agent session owns the
topic end to end and decides itself what to do next, including whether to start
sub-agents or ask another model; the control plane no longer splits the work
into maturation, replan, continuation, readiness, writing, remediation and
revision tasks. What stays is: the admission gate (unchanged, before this
module), the hash-bound pre-registered primary endpoint, the cross-family
pre-submission review (``paper_review``, whose comments return to the same
owner session), the cross-family direction decision as a circuit breaker, and
the human confirmation of a submission.

Mechanics, all keyed on ``[program].owner_mode``:

* a ``topic_owner`` task is one *seat* (one agent process, a few hours). It is
  pinned to a concrete runner chosen from ``[program.owner].runners`` (Fable,
  then Opus 5.5, then gpt-6-astra) and resumes the same session seat after seat;
* the owner ends a seat with a small packet (``continuing``, ``awaiting_remote``
  with job ids, ``ready_for_review``, ``frozen`` or ``blocked_human``) that
  :func:`normalize_packet` turns into an ordinary result bundle, filling what the
  control plane knows (identity, hashes of staged files, the ledger's
  pre-registration hash);
* ``awaiting_remote`` parks the seat through the existing remote-wait machinery;
  every other outcome is followed by :func:`ensure_seat` (next seat), a
  ``paper_review`` or nothing (frozen, ready, needs a human);
* :func:`record_seat` computes a mechanical progress fingerprint; after
  ``no_progress_seats`` seats without progress a direction decision is scheduled;
* :func:`supervise` moves a seat whose runner cannot start it for
  ``switch_after_minutes`` to the next usable runner.

With ``owner_mode = "off"`` none of this runs and every path is unchanged.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import budget as budget_control
from .config import OWNER_TASK_TYPE, FactorySettings, WorkspacePaths
from .contracts import (
    IDENTIFIER,
    PRIMARY_ENDPOINT_VERDICTS,
    REMOTE_JOB_ID,
    RESULT_SCHEMA,
    SHA256,
    atomic_write_json,
    executable_artifact,
    sha256_file,
)
from .db import FactoryDB, utc_now
from .projects import load_project, workstream_policy
from .resources import default_task_resources, task_resources

PACKET_SCHEMA = "openlabs.owner_packet.v1"
OWNER_STATUSES = ("continuing", "awaiting_remote", "ready_for_review", "frozen", "blocked_human")
# A manuscript goes to review only with an evaluated endpoint (pending stays in research).
EVALUATED_VERDICTS = frozenset({"met", "failed", "inconclusive"})
WORK_LOG_NAME = "OWNER_LOG.md"
BRIEF_NAME = "OWNER_BRIEF.md"
STATE_META_PREFIX = "owner_state:"
BLOCKED_META_PREFIX = "owner_blocked:"
TRIGGER_NO_PROGRESS = "owner_no_progress"
ROUTING_FIRST = "owner_first_seat"
ROUTING_CONTINUE = "owner_continue"
ROUTING_CONVERTED = "owner_converted"
ROUTING_REVIEW = "owner_review"
ROUTING_REVIEWED = "owner_review_returned"
ROUTING_RETRY = "owner_retry"
# Directory names never part of the progress fingerprint: runtime and outputs.
_DIGEST_SKIP_DIRS = frozenset({".agents", ".codex", ".claude", "attempts", "__pycache__"})
_DIGEST_SKIP_FILES = frozenset({WORK_LOG_NAME, BRIEF_NAME})
_MAX_REMEMBERED_ARTIFACTS = 2000
_LINEAGE_LIMIT = 500


# --------------------------------------------------------------------------- switch


def mode_enabled(settings: FactorySettings) -> bool:
    return settings.program.enabled and settings.program.owner_mode != "off"


def campaign_line(campaign: Mapping[str, Any]) -> str | None:
    path = str(campaign.get("project_config_path") or "").strip()
    if not path:
        return None
    try:
        return load_project(path).research_line
    except (OSError, ValueError, TypeError, KeyError):
        return None


def applies(settings: FactorySettings, campaign: Mapping[str, Any] | None) -> bool:
    """Whether a research-program topic campaign runs in owner mode."""

    if campaign is None or not mode_enabled(settings):
        return False
    if workstream_policy(campaign).get("program_research") is not True:
        return False
    mode = settings.program.owner_mode
    if mode == "all":
        return True
    return campaign_line(campaign) in tuple(mode)


def is_owner_task(task: Mapping[str, Any] | None) -> bool:
    return bool(task) and str(task.get("task_type") or "") == OWNER_TASK_TYPE


# --------------------------------------------------------------------------- packet


def _owner_status(payload: Mapping[str, Any]) -> str | None:
    for key in ("owner_status", "status"):
        value = str(payload.get(key) or "").strip().lower()
        if value in OWNER_STATUSES:
            return value
    packet = payload.get("owner_packet")
    if isinstance(packet, Mapping):
        value = str(packet.get("status") or "").strip().lower()
        if value in OWNER_STATUSES:
            return value
    return None


def _as_uri(value: Any, base: Path | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith("file:"):
        return text
    path = Path(text).expanduser()
    if not path.is_absolute():
        if base is None:
            return None
        path = base / path
    return path.resolve().as_uri()


def _uri_path(uri: str) -> Path | None:
    from urllib.parse import unquote, urlparse

    parsed = urlparse(uri)
    if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
        return None
    return Path(unquote(parsed.path)).resolve()


def _artifacts(
    declared: Any,
    *,
    workspace: Path | None,
    staging_root: Path | None,
) -> list[dict[str, Any]]:
    """Declared artifacts with ids, URIs and hashes completed; staged files added."""

    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_paths: set[Path] = set()
    for index, item in enumerate(declared if isinstance(declared, list) else []):
        if isinstance(item, str):
            item = {"uri": item}
        if not isinstance(item, Mapping):
            continue
        entry = dict(item)
        uri = _as_uri(entry.get("uri") or entry.get("path"), workspace)
        if uri is None:
            continue
        entry.pop("path", None)
        entry["uri"] = uri
        path = _uri_path(uri)
        digest = str(entry.get("sha256") or "").strip().lower()
        if not SHA256.fullmatch(digest):
            if path is None or not path.is_file():
                continue
            entry["sha256"] = sha256_file(path)
        artifact_id = str(entry.get("artifact_id") or "").strip()
        if not IDENTIFIER.fullmatch(artifact_id) or artifact_id in seen_ids:
            artifact_id = f"owner-{index:03d}-{str(entry['sha256'])[:12]}"
        entry["artifact_id"] = artifact_id
        entry.setdefault("kind", "data")
        seen_ids.add(artifact_id)
        if path is not None:
            seen_paths.add(path)
        result.append(entry)
    if staging_root is not None and staging_root.is_dir():
        for candidate in sorted(staging_root.rglob("*")):
            if candidate.is_symlink() or not candidate.is_file():
                continue
            resolved = candidate.resolve()
            if resolved in seen_paths:
                continue
            entry = {"uri": resolved.as_uri(), "kind": "data"}
            if executable_artifact(entry):
                # Scripts need a replay closure the owner must declare itself.
                continue
            digest = sha256_file(resolved)
            artifact_id = f"staged-{digest[:16]}"
            if artifact_id in seen_ids:
                continue
            seen_ids.add(artifact_id)
            result.append({"artifact_id": artifact_id, **entry, "sha256": digest})
    return result


def normalize_packet(
    raw: Mapping[str, Any],
    *,
    expected: Mapping[str, Any],
    preregistration_sha256: str | None = None,
    workspace: Path | None = None,
    staging_root: Path | None = None,
) -> dict[str, Any]:
    """Turn an owner packet into a result bundle; complete what the control plane knows.

    A payload that is not an owner packet (a full bundle, or the lab runner's own
    failure bundle) only gets its identity fields filled. Nothing the owner
    decided is changed: an explicit wrong pre-registration hash stays wrong so the
    result gate still refuses it.
    """

    status = _owner_status(raw)
    identity = {key: value for key, value in expected.items() if value is not None}
    if status is None or raw.get("schema_version") == RESULT_SCHEMA and isinstance(
        raw.get("owner_packet"), Mapping
    ):
        bundle = dict(raw)
        for key, value in identity.items():
            bundle.setdefault(key, value)
        return bundle
    packet = {
        key: value for key, value in raw.items()
        if key not in {"schema_version", *identity}
    }
    packet["schema_version"] = PACKET_SCHEMA
    packet["status"] = status
    summary = str(raw.get("summary") or raw.get("reason") or "").strip()
    bundle: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA,
        **identity,
        "summary": summary or f"Owner seat ended: {status}",
        "artifacts": _artifacts(raw.get("artifacts"), workspace=workspace,
                                staging_root=staging_root),
        "claims": [],
        "next_actions": [],
        "paper_candidate": False,
        "owner_packet": packet,
    }
    declared_verdict = str(raw.get("primary_endpoint_verdict") or "").strip().lower()
    declared_sha = str(raw.get("preregistration_sha256") or "").strip().lower()
    if declared_verdict in PRIMARY_ENDPOINT_VERDICTS:
        bundle["primary_endpoint_verdict"] = declared_verdict
    if declared_sha:
        bundle["preregistration_sha256"] = declared_sha
    if raw.get("paper_id"):
        bundle["paper_id"] = str(raw["paper_id"])
    reason = str(raw.get("reason") or "").strip()
    if status == "awaiting_remote":
        block = raw.get("awaiting_remote") if isinstance(raw.get("awaiting_remote"), Mapping) else {}
        ids = raw.get("job_ids") or block.get("job_ids") or []
        job_ids = [str(item).strip().lower() for item in ids if isinstance(item, str)]
        job_ids = [item for item in dict.fromkeys(job_ids) if REMOTE_JOB_ID.fullmatch(item)]
        if job_ids:
            wait: dict[str, Any] = {
                "job_ids": job_ids,
                "resume_objective": str(
                    raw.get("resume_note") or block.get("resume_objective")
                    or "Continue the topic with the finished jobs' outputs."
                ),
            }
            max_wait = raw.get("max_wait_seconds", block.get("max_wait_seconds"))
            if isinstance(max_wait, int) and not isinstance(max_wait, bool) and max_wait > 0:
                wait["max_wait_seconds"] = max_wait
            bundle["status"] = "awaiting_remote"
            bundle["awaiting_remote"] = wait
        else:
            # No usable job id: nothing to wait for, so the topic simply continues.
            packet["status"] = "continuing"
            packet["control_note"] = "awaiting_remote without a valid 32-hex job id"
            bundle["status"] = "completed"
    elif status == "frozen":
        gate: dict[str, Any] = {"promotion_decision": "freeze", "reason": reason or summary}
        reason_class = str(raw.get("freeze_reason_class") or raw.get("reason_class") or "")
        if reason_class:
            gate["freeze_reason_class"] = reason_class
        for key in ("evidence", "reopen_conditions"):
            if raw.get(key) is not None:
                gate[key] = raw[key]
        bundle["status"] = "completed"
        bundle["gate_result"] = gate
        # A freeze is a promotion: an unstated verdict is "pending" (never
        # evaluated) and the ledger's hash is used when the owner gave none.
        bundle.setdefault("primary_endpoint_verdict", "pending")
        if preregistration_sha256 and not declared_sha:
            bundle["preregistration_sha256"] = preregistration_sha256
    elif status == "blocked_human":
        bundle["status"] = "needs_human"
        bundle["human_intervention"] = {"reason": reason or summary}
        bundle["stop_reason"] = reason or summary
    else:  # continuing, ready_for_review
        bundle["status"] = "completed"
    return bundle


def packet_of(payload: Mapping[str, Any]) -> dict[str, Any]:
    packet = payload.get("owner_packet")
    return dict(packet) if isinstance(packet, Mapping) else {}


# --------------------------------------------------------------------------- lineage


def session_seat(db: FactoryDB, task_id: str | None) -> dict[str, Any] | None:
    """Nearest owner seat with a recorded session in a task's lineage."""

    current = db.task(task_id) if task_id else None
    for _ in range(_LINEAGE_LIMIT):
        if current is None:
            return None
        if is_owner_task(current) and current.get("agent_session_id"):
            return current
        parent = current.get("parent_task_id")
        current = db.task(str(parent)) if parent else None
    return None


def last_seat(
    db: FactoryDB, campaign_id: str, *, before: str | None = None
) -> dict[str, Any] | None:
    """Latest owner seat of a topic other than ``before`` (the seat being launched)."""

    with db.connect() as connection:
        row = connection.execute(
            """
            SELECT * FROM tasks WHERE campaign_id=? AND task_type=? AND task_id != ?
              AND attempt > 0
            ORDER BY created_at DESC, rowid DESC LIMIT 1
            """,
            (campaign_id, OWNER_TASK_TYPE, before or ""),
        ).fetchone()
    return dict(row) if row else None


def current_owners(db: FactoryDB, *, exclude_campaign: str | None = None) -> dict[str, set[str]]:
    """Runner -> active campaigns whose latest owner seat is pinned to it."""

    owners: dict[str, set[str]] = {}
    with db.connect() as connection:
        rows = connection.execute(
            """
            SELECT tasks.campaign_id, tasks.runner FROM tasks
            JOIN campaigns USING(campaign_id)
            WHERE tasks.task_type=? AND campaigns.status='active'
            ORDER BY tasks.created_at, tasks.rowid
            """,
            (OWNER_TASK_TYPE,),
        ).fetchall()
    latest: dict[str, str] = {}
    for row in rows:
        latest[str(row["campaign_id"])] = str(row["runner"] or "")
    for campaign_id, runner in latest.items():
        if campaign_id != exclude_campaign and runner:
            owners.setdefault(runner, set()).add(campaign_id)
    return owners


# --------------------------------------------------------------------------- runner choice


def _router(db: FactoryDB, settings: FactorySettings,
            router: budget_control.QuotaRouter | None) -> budget_control.QuotaRouter | None:
    if router is not None:
        return router
    if not budget_control.routing_enabled(settings):
        return None
    return budget_control.QuotaRouter.build(db, settings)


def runner_usable(
    settings: FactorySettings,
    router: budget_control.QuotaRouter | None,
    name: str,
) -> bool:
    spec = settings.runners.get(name)
    if spec is None:
        return False
    if router is None:
        return True
    return router.usable(spec, budget_control.OWNER_CLASS)


def _under_cap(settings: FactorySettings, owners: Mapping[str, set[str]], name: str) -> bool:
    limit = settings.program.owner.max_topics_per_runner.get(name)
    return limit is None or len(owners.get(name, set())) < int(limit)


def choose_runner(
    db: FactoryDB,
    settings: FactorySettings,
    *,
    campaign_id: str,
    exclude: Iterable[str] = (),
    router: budget_control.QuotaRouter | None = None,
    require_usable: bool = False,
) -> str | None:
    """First owner runner (preference order) under its topic cap and usable now.

    Without ``require_usable`` a runner that is only over its quota allowance is
    still returned when none is usable (the seat waits and may switch later);
    ``None`` without a ``[runners]`` table (the legacy ``frontier`` alias is used).
    """

    if not settings.runners:
        return None
    current = _router(db, settings, router)
    owners = current_owners(db, exclude_campaign=campaign_id)
    skipped = set(exclude)
    candidates = [
        name for name in settings.program.owner.runners
        if name in settings.runners and name not in skipped and _under_cap(settings, owners, name)
    ]
    for name in candidates:
        if runner_usable(settings, current, name):
            return name
    if require_usable or not candidates:
        return None
    return candidates[0]


# --------------------------------------------------------------------------- seats


def _seat_id(campaign_id: str, source: str) -> str:
    digest = hashlib.sha256(f"{campaign_id}\0{source}".encode()).hexdigest()
    return f"owner:{digest[:40]}"


def enqueue_seat(
    db: FactoryDB,
    settings: FactorySettings,
    report: Any,
    *,
    campaign: Mapping[str, Any],
    parent: Mapping[str, Any] | None,
    note: str,
    routing_reason: str,
    input_path: str | None = None,
    task_id: str | None = None,
    initial_status: str = "queued",
    last_error: str | None = None,
    not_before: str | None = None,
    router: budget_control.QuotaRouter | None = None,
) -> str | None:
    """Queue the next seat of a topic: same session and runner when there is one."""

    campaign_id = str(campaign["campaign_id"])
    identifier = task_id or _seat_id(campaign_id, str((parent or {}).get("task_id") or "seed"))
    if db.task(identifier) is not None:
        return None
    parent_id = str(parent["task_id"]) if parent else None
    source = session_seat(db, parent_id) if parent_id else None
    runner: str | None = None
    session_mode = "fresh"
    session_source: str | None = None
    if source is not None:
        runner = str(source.get("runner") or "") or None
        session_mode = "resume"
        session_source = str(source["task_id"])
    elif is_owner_task(parent):
        # No recorded session (the CLI reported none): same owner, fresh session.
        runner = str((parent or {}).get("runner") or "") or None
    if runner is None:
        runner = choose_runner(db, settings, campaign_id=campaign_id, router=router) or "frontier"
    resources = task_resources(source) if source else default_task_resources(settings)
    db.enqueue_task(
        task_id=identifier,
        campaign_id=campaign_id,
        domain=str(campaign["domain"]),
        task_type=OWNER_TASK_TYPE,
        objective=note.strip() or "Continue owning this topic.",
        input_path=input_path or (str(parent.get("result_path")) if parent and parent.get(
            "result_path") else None),
        skill_path=str(campaign.get("primary_skill") or "") or None,
        runner=runner,
        routing_reason=routing_reason,
        parent_task_id=parent_id,
        agent_role="researcher",
        session_mode=session_mode,
        session_source_task_id=session_source,
        priority=int(campaign.get("priority") or 0),
        max_attempts=settings.max_attempts,
        max_wall_seconds=min(settings.program.owner.seat_wall_seconds,
                             settings.max_task_wall_seconds),
        initial_status=initial_status,
        last_error=last_error,
        not_before=not_before,
        **resources.to_dict(),
    )
    if report is None:
        return identifier
    report.enqueued.append(identifier)
    report.program.setdefault("owner_seats", []).append(
        {"task_id": identifier, "campaign_id": campaign_id, "runner": runner,
         "session_mode": session_mode, "routing_reason": routing_reason}
    )
    return identifier


def first_seat(
    db: FactoryDB,
    settings: FactorySettings,
    *,
    campaign_id: str,
    task_id: str,
    objective: str,
    input_path: str | None,
    priority: int,
    resources: Any,
) -> str:
    """The first seat of a freshly materialized topic (replaces candidate_maturation)."""

    campaign = db.campaign(campaign_id) or {}
    runner = choose_runner(db, settings, campaign_id=campaign_id) or "frontier"
    db.enqueue_task(
        task_id=task_id,
        campaign_id=campaign_id,
        domain=str(campaign["domain"]),
        task_type=OWNER_TASK_TYPE,
        objective=objective,
        input_path=input_path,
        skill_path=str(campaign.get("primary_skill") or "") or None,
        runner=runner,
        routing_reason=ROUTING_FIRST,
        agent_role="researcher",
        session_mode="fresh",
        priority=priority,
        max_attempts=settings.max_attempts,
        max_wall_seconds=min(settings.program.owner.seat_wall_seconds,
                             settings.max_task_wall_seconds),
        **resources.to_dict(),
    )
    return task_id


# --------------------------------------------------------------------------- progress


def workspace_digest(root: Path | None) -> str | None:
    """Fingerprint of a campaign workspace's research files (log, brief, outputs excluded)."""

    if root is None or not root.is_dir():
        return None
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in _DIGEST_SKIP_DIRS for part in relative.parts):
            continue
        if path.is_symlink() or not path.is_file():
            continue
        if path.name in _DIGEST_SKIP_FILES or path.name.endswith(".pending"):
            continue
        digest.update(relative.as_posix().encode())
        digest.update(b"\0")
        digest.update(sha256_file(path).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def owner_state(db: FactoryDB, campaign_id: str) -> dict[str, Any]:
    raw = db.meta_get(STATE_META_PREFIX + campaign_id)
    try:
        value = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        value = {}
    return value if isinstance(value, dict) else {}


def _store_state(db: FactoryDB, campaign_id: str, state: Mapping[str, Any],
                 event: tuple[str, Mapping[str, Any]] | None = None) -> None:
    events = [("campaign", campaign_id, event[0], dict(event[1]))] if event else []
    db.update_meta({STATE_META_PREFIX + campaign_id: json.dumps(dict(state), sort_keys=True)},
                   events=events)


def record_seat(
    db: FactoryDB,
    *,
    task: Mapping[str, Any],
    payload: Mapping[str, Any],
    final_status: str,
    workspace_root: Path | None,
    promoted: bool,
) -> dict[str, Any]:
    """Update the no-progress streak of a topic after one finished seat.

    Progress (the streak resets) when the seat's promoted workspace digest differs
    from the last one, it declared an artifact hash not seen before, it started
    after remote/local jobs finished (``remote_wait``), or it yielded on new jobs.
    A seat whose work was not promoted (timeout, failed gate) never counts as
    progress.
    """

    campaign_id = str(task["campaign_id"])
    state = owner_state(db, campaign_id)
    known = set(state.get("artifact_hashes") or [])
    digest = workspace_digest(workspace_root) if promoted else None
    new_hashes = [
        str(item.get("sha256")) for item in payload.get("artifacts") or []
        if isinstance(item, Mapping) and SHA256.fullmatch(str(item.get("sha256") or ""))
        and str(item.get("sha256")) not in known
    ] if promoted else []
    reasons: list[str] = []
    if promoted and digest is not None and digest != state.get("digest"):
        reasons.append("workspace_changed")
    if new_hashes:
        reasons.append("new_artifacts")
    if str(task.get("routing_reason") or "") == "remote_wait":
        reasons.append("jobs_finished")
    if final_status == "yielded":
        reasons.append("jobs_submitted")
    streak = 0 if reasons else int(state.get("no_progress_streak") or 0) + 1
    remembered = list(dict.fromkeys([*(state.get("artifact_hashes") or []), *new_hashes]))
    updated = {
        **state,
        "digest": digest if digest is not None else state.get("digest"),
        "no_progress_streak": streak,
        "seats": int(state.get("seats") or 0) + 1,
        "last_task_id": str(task["task_id"]),
        "last_runner": str(task.get("runner") or ""),
        "last_progress": reasons,
        "artifact_hashes": remembered[-_MAX_REMEMBERED_ARTIFACTS:],
        "updated_at": utc_now(),
    }
    _store_state(db, campaign_id, updated, ("owner_seat_recorded", {
        "task_id": str(task["task_id"]), "final_status": final_status,
        "progress": reasons, "no_progress_streak": streak,
    }))
    return updated


def reset_streak(db: FactoryDB, campaign_id: str, *, reason: str) -> None:
    state = owner_state(db, campaign_id)
    if int(state.get("no_progress_streak") or 0) == 0:
        return
    _store_state(db, campaign_id, {**state, "no_progress_streak": 0, "reset_reason": reason})


# --------------------------------------------------------------------------- after a result


def _topic(paths: WorkspacePaths, settings: FactorySettings, campaign_id: str) -> dict | None:
    from .program_autonomy import campaign_topic

    return campaign_topic(paths, settings, campaign_id)


def _breaker(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    report: Any,
    *,
    task: Mapping[str, Any],
    state: Mapping[str, Any],
    result_path: Path,
    result_sha256: str,
) -> bool:
    """Schedule the direction decision once the no-progress streak is long enough."""

    from .program_autonomy import schedule_direction_decision

    if int(state.get("no_progress_streak") or 0) < settings.program.owner.no_progress_seats:
        return False
    topic = _topic(paths, settings, str(task["campaign_id"]))
    if topic is None:
        return False
    scheduled = schedule_direction_decision(
        db, paths, settings, report, topic=topic, trigger=TRIGGER_NO_PROGRESS,
        source_task_id=str(task["task_id"]),
        evidence=[{"path": str(result_path), "sha256": result_sha256}],
        reasons=[str(state.get("summary") or "")] if state.get("summary") else None,
        detail={"no_progress_streak": int(state.get("no_progress_streak") or 0),
                "seats": int(state.get("seats") or 0),
                "threshold": settings.program.owner.no_progress_seats},
    )
    return scheduled is not None


def _review_objective(packet: Mapping[str, Any], topic: Mapping[str, Any] | None) -> str:
    paper = str(packet.get("paper_id") or "").strip()
    sha = str((topic or {}).get("preregistration_sha256") or "")
    return (
        (f"The owner names paper ID {paper}. " if paper else
         "Resolve the paper ID from the owner's registered artifacts. ")
        + "Run `paper-writing review unified-run --paper-id <id>` (add --response for a "
        "re-review). It runs the preflight, the target-journal editor screen, two blind "
        "referees and the conservative decision; do not reproduce its stages or edit the "
        "manuscript. Also check that the manuscript reports the pre-registered primary "
        f"endpoint unchanged (research_state.json `preregistration`, sha256 {sha or 'n/a'}) "
        "and that no simulated or synthetic data is presented as observation. Return "
        "paper_candidate=true only for outcome ready; otherwise return exactly one structured "
        "text_revision or evidence_remediation action, or none for retarget_required/blocked. "
        "Always copy the paper's registered writing_release into the result field "
        "`review_outcome` (next_action, status, review_stalled, rounds_for_target, "
        "max_rounds_per_target, direction_context, decision_record, decision_record_sha256, "
        "paper_id); the orchestrator decides what follows."
    )


def _enqueue_review(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    report: Any,
    *,
    task: Mapping[str, Any],
    packet: Mapping[str, Any],
    result_path: Path,
) -> str | None:
    from . import program_autonomy

    review_id = _seat_id(str(task["campaign_id"]), "review:" + str(task["task_id"]))
    review_id = "owner-review:" + review_id.split(":", 1)[1]
    if db.task(review_id) is not None:
        return None
    campaign = db.campaign(str(task["campaign_id"])) or {}
    topic = _topic(paths, settings, str(task["campaign_id"]))
    db.enqueue_task(
        task_id=review_id,
        campaign_id=str(task["campaign_id"]),
        domain=str(task["domain"]),
        task_type="paper_review",
        objective=_review_objective(packet, topic),
        input_path=str(result_path),
        skill_path="openlabs-paper-review",
        runner="frontier",
        routing_reason=ROUTING_REVIEW,
        parent_task_id=str(task["task_id"]),
        agent_role="reviewer",
        session_mode="fresh",
        priority=int(campaign.get("priority") or 0) + 1,
        max_attempts=settings.max_attempts,
        max_wall_seconds=settings.max_task_wall_seconds,
        **default_task_resources(settings).to_dict(),
    )
    report.enqueued.append(review_id)
    try:
        program_autonomy.on_review_scheduled(
            db, paths, settings, campaign_id=str(task["campaign_id"]), review_task_id=review_id
        )
    except (OSError, ValueError) as exc:
        report.errors.append(f"Could not mark topic of {task['campaign_id']} in review: {exc}")
    return review_id


def _review_note(payload: Mapping[str, Any], result_path: Path) -> str:
    outcome = payload.get("review_outcome") if isinstance(payload.get("review_outcome"),
                                                         Mapping) else {}
    action = payload.get("next_actions") or []
    first = action[0] if isinstance(action, list) and action else None
    requested = (
        first.get("objective") if isinstance(first, Mapping) else first
    ) if first else None
    return (
        "The independent pre-submission review returned "
        f"status {outcome.get('status') or 'unknown'}, next action "
        f"{outcome.get('next_action') or 'none'} (round {outcome.get('rounds_for_target')}"
        f" of {outcome.get('max_rounds_per_target')}). Review result: {result_path}; decision "
        f"record: {outcome.get('decision_record') or 'see the result'}."
        + (f" Requested: {str(requested)[:1500]}" if requested else "")
        + " Address it in the manuscript or the evidence as you judge right, keep contrary "
        "results, and return ready_for_review when it is ready for the re-review."
    )


def after_result(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    report: Any,
    *,
    task: Mapping[str, Any],
    payload: Mapping[str, Any],
    final_status: str,
    successful: bool,
    program_disposition: str | None,
    result_path: Path,
    result_sha256: str,
    workspace_root: Path | None,
    has_room: bool,
) -> bool:
    """Successor of any result of an owner-mode topic; True when it was handled.

    Handles owner seats, the owner's paper review, and (conversion) every legacy
    research task of an owner-mode topic. A ``yielded`` result is left to the
    remote-wait parking, which creates the next owner seat itself.
    """

    if final_status == "yielded":
        if is_owner_task(task):
            record_seat(db, task=task, payload=payload, final_status=final_status,
                        workspace_root=workspace_root, promoted=True)
        return False
    campaign = db.campaign(str(task["campaign_id"]))
    if campaign is None:
        return True
    task_type = str(task.get("task_type") or "")
    if program_disposition == "handled":
        if is_owner_task(task):
            record_seat(db, task=task, payload=payload, final_status=final_status,
                        workspace_root=workspace_root, promoted=successful)
        return True
    if final_status == "failed" and is_owner_task(task):
        # Out of attempts: a seat without progress; replenishment starts the next one
        # unless the breaker sends the topic to a direction decision.
        state = record_seat(db, task=task, payload=payload, final_status=final_status,
                            workspace_root=workspace_root, promoted=False)
        _breaker(db, paths, settings, report, task=task, state=state,
                 result_path=result_path, result_sha256=result_sha256)
        return True
    if final_status in {"queued", "needs_human", "quarantined", "failed", "cancelled"}:
        # Retried as is, or stopped: the direction decision (needs_human) or the
        # infrastructure triage takes it from here.
        return True
    if str(campaign.get("status") or "") != "active":
        return True
    if not has_room:
        report.errors.append(f"Campaign {campaign['campaign_id']} reached its automatic-task "
                             "safety limit (owner seat deferred to replenishment)")
        return True
    if task_type == "paper_review":
        if successful:
            note = _review_note(payload, result_path)
            routing = ROUTING_REVIEWED
        else:
            note = (f"The pre-submission review task {task['task_id']} ended {final_status} "
                    f"without a decision ({str(task.get('last_error') or '')[:300]}). Return "
                    "ready_for_review again when you want it re-run.")
            routing = ROUTING_RETRY
        enqueue_seat(db, settings, report, campaign=campaign, parent=task, note=note,
                     routing_reason=routing, input_path=str(result_path))
        return True
    if not is_owner_task(task):
        # Conversion of an in-flight topic: its next step is an owner seat.
        note = (
            "You take over this admitted topic, which ran so far as separate staged tasks; "
            f"the last one ({task_type}, {task['task_id']}) ended {final_status} with the "
            f"result at the input path. Its state is in research_state.json and the campaign "
            "workspace; earlier remote job ids are in its results."
        )
        enqueue_seat(db, settings, report, campaign=campaign, parent=task, note=note,
                     routing_reason=ROUTING_CONVERTED, input_path=str(result_path))
        return True
    packet = packet_of(payload)
    state = record_seat(db, task=task, payload=payload, final_status=final_status,
                        workspace_root=workspace_root, promoted=successful)
    status = str(packet.get("status") or "")
    if successful and status == "ready_for_review":
        verdict = str(packet.get("primary_endpoint_verdict") or "").strip().lower()
        if verdict not in EVALUATED_VERDICTS:
            enqueue_seat(
                db, settings, report, campaign=campaign, parent=task, routing_reason=ROUTING_RETRY,
                note=("ready_for_review needs primary_endpoint_verdict met, failed or "
                      "inconclusive (the manuscript reports the pre-registered endpoint); state "
                      "it and return ready_for_review again."),
            )
            return True
        reset_streak(db, str(task["campaign_id"]), reason="review_requested")
        _enqueue_review(db, paths, settings, report, task=task, packet=packet,
                        result_path=result_path)
        return True
    if _breaker(db, paths, settings, report, task=task,
                state={**state, "summary": payload.get("summary")},
                result_path=result_path, result_sha256=result_sha256):
        return True
    if successful:
        note = str(packet.get("resume_note") or packet.get("next_step") or "").strip() or (
            "Continue owning the topic from where the last seat stopped (your work log).")
        enqueue_seat(db, settings, report, campaign=campaign, parent=task, note=note,
                     routing_reason=ROUTING_CONTINUE, input_path=str(result_path))
        return True
    errors = "; ".join(
        str(item) for item in (payload.get("blockers") or [])
    ) or str(task.get("last_error") or payload.get("summary") or final_status)
    enqueue_seat(
        db, settings, report, campaign=campaign, parent=task, routing_reason=ROUTING_RETRY,
        note=(f"The last seat's result was not accepted ({final_status}: {errors[:1500]}); its "
              "workspace changes were not promoted. Fix what the message names and continue; "
              "leave the status JSON before the seat deadline."),
    )
    return True


def replenish(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    report: Any,
    *,
    campaign: Mapping[str, Any],
    latest: Mapping[str, Any] | None,
) -> None:
    """An owner-mode topic with nothing queued or running gets its next seat."""

    if latest is None:
        note = "Start owning this admitted topic."
        routing = ROUTING_FIRST
    elif is_owner_task(latest) and str(latest.get("status")) == "succeeded":
        note = "Continue owning the topic from where the last seat stopped (your work log)."
        routing = ROUTING_CONTINUE
    else:
        note = (f"Continue the topic after task {latest['task_id']} "
                f"({latest.get('task_type')}) ended {latest.get('status')}; its result, if any, "
                "is at the input path.")
        routing = ROUTING_CONVERTED if not is_owner_task(latest) else ROUTING_RETRY
    seat = enqueue_seat(db, settings, report, campaign=campaign, parent=latest, note=note,
                        routing_reason=routing,
                        task_id=_seat_id(str(campaign["campaign_id"]), "replenish:" + str(
                            (latest or {}).get("task_id") or "seed")))
    if seat is not None:
        report.production_reseeded.append(str(campaign["campaign_id"]))


# --------------------------------------------------------------------------- switching


def _blocked_since(db: FactoryDB, task_id: str) -> datetime | None:
    return budget_control.parse_time(db.meta_get(BLOCKED_META_PREFIX + task_id))


def supervise(
    db: FactoryDB,
    settings: FactorySettings,
    report: Any,
    router: budget_control.QuotaRouter | None,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Move a queued seat to the next usable runner once its own is blocked too long."""

    if not mode_enabled(settings) or router is None:
        return []
    moment = now or datetime.now(UTC)
    owner = settings.program.owner
    moves: list[dict[str, Any]] = []
    with db.connect() as connection:
        rows = [dict(row) for row in connection.execute(
            "SELECT * FROM tasks WHERE task_type=? AND status='queued'", (OWNER_TASK_TYPE,)
        ).fetchall()]
    for task in rows:
        task_id = str(task["task_id"])
        not_before = budget_control.parse_time(task.get("not_before"))
        if not_before is not None and not_before > moment:
            continue
        runner = str(task.get("runner") or "")
        owners = current_owners(db, exclude_campaign=str(task["campaign_id"]))
        if runner in settings.runners and runner_usable(settings, router, runner) and (
            _under_cap(settings, owners, runner)
        ):
            if db.meta_get(BLOCKED_META_PREFIX + task_id) is not None:
                db.update_meta({BLOCKED_META_PREFIX + task_id: None})
            continue
        since = _blocked_since(db, task_id)
        if since is None:
            db.update_meta({BLOCKED_META_PREFIX + task_id: budget_control._iso(moment)})
            since = moment
        if runner in settings.runners and moment - since < timedelta(
            minutes=owner.switch_after_minutes
        ):
            continue
        target = choose_runner(db, settings, campaign_id=str(task["campaign_id"]),
                               exclude=[runner], router=router, require_usable=True)
        if target is None:
            continue
        old = settings.runners.get(runner)
        new = settings.runners[target]
        keep = bool(
            owner.keep_session_within_provider and old is not None
            and old.provider == new.provider and task.get("session_mode") == "resume"
            and task.get("agent_session_id")
        )
        detail = {"from_runner": runner, "to_runner": target, "keep_session": keep,
                  "blocked_since": budget_control._iso(since),
                  "reason": "owner runner unavailable"}
        if db.reassign_queued_task(task_id, runner=target, fresh_session=not keep,
                                   event="owner_runner_switched", detail=detail):
            db.update_meta({BLOCKED_META_PREFIX + task_id: None})
            moves.append({"task_id": task_id, **detail})
    if moves:
        report.program.setdefault("owner_switches", []).extend(moves)
    return moves


# --------------------------------------------------------------------------- the brief


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _short(value: Any, limit: int) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False,
                                                           sort_keys=True)
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _venue_names(value: Any) -> list[str]:
    names: list[str] = []
    for item in value if isinstance(value, list) else [value] if value else []:
        name = item.get("name") if isinstance(item, Mapping) else item
        if str(name or "").strip():
            names.append(str(name).strip())
    return names


def _line_tools(paths: WorkspacePaths, settings: FactorySettings, line: str | None) -> list[str]:
    """Pointers into the research line's own definition (never a copy of its rules)."""

    if not line:
        return []
    from .research_lines import line_entry, read_lines_or_none

    entry = line_entry(read_lines_or_none(paths.data / settings.program.research_lines_path),
                       line) or {}
    environment = entry.get("environment") if isinstance(entry.get("environment"), Mapping) else {}
    items: list[str] = []
    solver = environment.get("standard_solver")
    if isinstance(solver, Mapping):
        for key in ("entry", "analysis_library"):
            if isinstance(solver.get(key), str):
                items.append(f"{key.replace('_', ' ')}: {_short(solver[key], 100)}")
    for key in ("sop",):
        if isinstance(environment.get(key), str):
            items.append(f"{key}: {_short(environment[key], 140)}")
    return items


def brief_paths(task: Mapping[str, Any]) -> dict[str, str]:
    transaction = task.get("transaction") if isinstance(task.get("transaction"), Mapping) else {}
    staged = Path(str(transaction.get("staged_campaign_workspace") or task.get(
        "agent_workspace") or "."))
    return {
        "staged": str(staged),
        "staging": str(transaction.get("artifact_staging_root") or ""),
        "canonical": str(transaction.get("canonical_campaign_workspace") or ""),
        "work_log": str(staged / WORK_LOG_NAME),
        "brief": str(staged / BRIEF_NAME),
        "result": str(task.get("output_path") or ""),
    }


def render_brief(
    paths: WorkspacePaths,
    settings: FactorySettings,
    *,
    task: Mapping[str, Any],
    campaign: Mapping[str, Any],
    topic: Mapping[str, Any] | None,
    adapter_family: str | None,
    deadline: datetime,
    handover: str | None = None,
) -> str:
    """The owner's whole brief: goal, resources, tools, hard limits (about 4 KB)."""

    owner = settings.program.owner
    state = _read_json(Path(str(campaign.get("workstream_state_path") or "")))
    prereg = state.get("preregistration") if isinstance(state.get("preregistration"),
                                                        Mapping) else {}
    line = str(state.get("research_line") or campaign_line(campaign) or "")
    where = brief_paths(task)
    code = paths.code
    sha = str((topic or {}).get("preregistration_sha256") or prereg.get("sha256") or "n/a")
    routine = ", ".join(_venue_names(state.get("routine_fallback"))[:4]) or "see research_state.json"
    escalation = ", ".join(_venue_names(state.get("escalation_target"))[:2])
    conditions = state.get("admission_conditions") or []
    used = int(float(campaign.get("agent_seconds_used") or 0))
    maximum = int(campaign.get("max_agent_seconds") or 0)
    tools = _line_tools(paths, settings, line)
    sub = owner.claude_subagent_model or "the session model"
    if adapter_family == "openai-codex":
        models = (
            f"  - You are explicitly authorized to start sub-agents with spawn_agent; set "
            f"`model` to \"{owner.codex_helper_model}\" (or \"{owner.codex_light_model}\" for "
            "simple work) unless the step needs your own model."
        )
    else:
        models = (
            "  - Claude sub-agents: the Agent tool, `model` \"haiku\", \"sonnet\" or \"opus\" "
            f"(default {sub}).\n"
            f"  - GPT through Codex: `codex exec -m {owner.codex_helper_model} -c "
            "approval_policy='\"never\"' --sandbox danger-full-access --skip-git-repo-check "
            "-C DIR -o ANSWER.md - < PROMPT.md` (cheaper: "
            f"`-m {owner.codex_light_model}`; long runs in the background)."
        )
    precheck = (" The card's feasibility_precheck (research_state.json) decides first whether "
                "the topic goes on." if state.get("feasibility_precheck") else "")
    lines = [
        f"# Topic owner: {(topic or {}).get('topic_id') or state.get('topic_id') or campaign['campaign_id']}",
        "",
        "You own this admitted topic end to end; how to get there is your decision.",
        "",
        "## Goal",
        "One manuscript, on the research line's paper template, that a venue on the line's "
        "list would publish - or an early, honest verdict that it cannot be done, and why."
        + precheck,
        f"- Question: {_short(state.get('question') or campaign.get('title') or '', 220)}",
        f"- Pre-registered primary endpoint (sha256 {sha}): "
        f"{_short(prereg.get('primary_endpoint') or prereg, 240)} (full: research_state.json "
        "`preregistration`).",
        f"- Target: {state.get('target_tier') or 'routine'}; venues: {routine}"
        + (f"; escalation: {escalation}" if escalation else "") + f". Admission conditions: "
        f"{len(conditions) if isinstance(conditions, list) else 0} (`admission_conditions`).",
        f"- Budget: {used}/{maximum} Agent seconds used; this seat ends by "
        f"{deadline.strftime('%Y-%m-%d %H:%M')} UTC.",
        "",
        "## Resources",
        f"CODE={code}, DATA={paths.data}.",
        "- Compute: ailab first, keep it full: `CODE/bin/openlabs-remote submit --source DIR "
        "--cpus N --memory-mib M --timeout-seconds S -- CMD` (overflows here itself; "
        "CODE/docs/REMOTE_COMPUTE.md). GPU, no approval: `CODE/bin/openlabs-resource-guard "
        "--task-type gpu --gpu-memory-mib N --gpu-device 0 -- CMD`. Do not wait in the session "
        "for long jobs: end the seat awaiting_remote; it resumes when they finish.",
        "- Models: use sub-agents or another model whenever it is worth it.",
        models,
        "- Quota: `PYTHONPATH=CODE/orchestrator/src python3 -m openlabs program utilization "
        "--no-gpu` (read-only, `providers`). Work stops at 80% on a paced line; near it prefer "
        "cheaper models and fewer parallel agents.",
        "",
        "## Tools",
        f"- Line `{line or 'n/a'}`: DATA/{settings.program.research_lines_path} -> "
        "`environment`; use its shared entries, do not fork them:",
        *[f"  - {item}" for item in tools],
        f"- Reusable assets: DATA/{settings.program.asset_index_path}. Downloads: "
        "`/workspace/.download-bridge/download-submit --url URL --output /workspace/... "
        "--route auto --wait`.",
        "- Manuscripts: `paper-writing` CLI (CODE/workflows/paper/skills/openlabs-paper-writing/"
        "SKILL.md). Skills and CODE/AGENTS.md are optional references and checklists.",
        "",
        "## Hard limits",
        "1. Every download goes through the download bridge; never change network, proxy or "
        "firewall settings.",
        "2. Never print, copy or send credentials.",
        "3. Heavy work on ailab/the queue or in the resource guard; GPU only through its lock.",
        "4. Never fabricate data, results, citations or reviews; never pass simulated or "
        "synthetic data off as observations or results; report negative results as they are.",
        "5. The pre-registered primary endpoint is fixed; never rewrite it (verdict may stay "
        "pending).",
        "6. Paid publication only in a 2025 CAS zone-1 journal; otherwise a verified fee-free "
        "route.",
        "7. Submission, payment, authorship, external publication: stop and leave it to a human.",
        "8. Never approve your own manuscript: return ready_for_review; another model family "
        "reviews it and its comments come back to this session.",
        "",
        "## Ending a seat",
        f"Keep {WORK_LOG_NAME} in the writable workspace current (done, evidence, decisions, next "
        "step) for a successor or a direction decision, then write JSON to the result path: "
        "`{\"status\": \"continuing|awaiting_remote|ready_for_review|frozen|blocked_human\", "
        "\"summary\", \"job_ids\", \"paper_id\", \"primary_endpoint_verdict\": "
        "\"met|failed|inconclusive|pending\", \"reason\"}`. Only status is required (job_ids, "
        "reason where they apply); the control plane fills the rest.",
    ]
    if handover:
        lines += ["", "## This seat", handover]
    return "\n".join(lines) + "\n"


def render_seat_footer(task: Mapping[str, Any], *, deadline: datetime) -> str:
    where = brief_paths(task)
    return (
        "\n---\n"
        f"Seat {task.get('task_id')} (attempt {task.get('attempt_id')}), ends by "
        f"{deadline.strftime('%Y-%m-%d %H:%M')} UTC.\n"
        f"- result path (the status JSON): `{where['result']}`\n"
        f"- writable campaign workspace: `{where['staged']}` (promoted when the result passes)\n"
        f"- large outputs (datasets, chains, archives): `{where['staging']}`\n"
        f"- canonical campaign, read-only: `{where['canonical']}`\n"
        f"- input of this seat: `{task.get('input_path')}`\n"
    )


def spec_block(
    paths: WorkspacePaths,
    settings: FactorySettings,
    *,
    task: Mapping[str, Any],
    spec: Mapping[str, Any],
    campaign: Mapping[str, Any],
    wall_seconds: int,
    db: FactoryDB,
) -> dict[str, Any]:
    """``owner`` block of a seat's task spec: the rendered request and runtime facts."""

    spec_view = dict(spec)
    deadline = datetime.now(UTC) + timedelta(seconds=max(60, int(wall_seconds)))
    topic = _topic(paths, settings, str(campaign["campaign_id"]))
    spec_runner = settings.runners.get(str(task.get("runner") or ""))
    family = spec_runner.provider if spec_runner is not None else None
    resumed = bool(
        str(task.get("session_mode") or "") == "resume" and task.get("agent_session_id")
    )
    note = str(spec.get("objective") or task.get("objective") or "").strip()
    where = brief_paths(spec_view)
    if resumed:
        request = (
            f"# Topic owner: next seat\n\n{note}\n\nYour brief is unchanged ({BRIEF_NAME} in "
            f"the writable workspace); the paths below are new for this seat. Update "
            f"{WORK_LOG_NAME} there, then write the status JSON.\n"
        )
    else:
        previous = last_seat(db, str(campaign["campaign_id"]), before=str(task["task_id"]))
        handover = note
        if previous is not None:
            handover = (
                f"A previous owner session ({previous.get('runner')}, seat "
                f"{previous['task_id']}) ran this topic; read the work log {WORK_LOG_NAME} and "
                f"research_state.json first. {note}"
            )
        request = render_brief(paths, settings, task=spec_view, campaign=campaign, topic=topic,
                               adapter_family=family, deadline=deadline, handover=handover)
        brief_file = Path(where["brief"])
        if brief_file.parent.is_dir():
            brief_file.write_text(request, encoding="utf-8")
    request += render_seat_footer(spec_view, deadline=deadline)
    sha = str((topic or {}).get("preregistration_sha256") or "")
    return {
        "schema_version": PACKET_SCHEMA,
        "request": request,
        "fresh": not resumed,
        "work_log": where["work_log"],
        "preregistration_sha256": sha if SHA256.fullmatch(sha) else None,
        "artifact_staging_root": where["staging"] or None,
        "claude_subagent_model": settings.program.owner.claude_subagent_model,
        "deadline": deadline.isoformat().replace("+00:00", "Z"),
    }


def hook_normalize(context: Mapping[str, Any]) -> None:
    """Stop-hook side: rewrite the owner's packet at the result path into a bundle."""

    block = context.get("owner")
    if not isinstance(block, Mapping):
        return
    path = Path(str(context.get("result_path") or "")).expanduser()
    if not path.is_file():
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(raw, Mapping):
        return
    staging = str(block.get("artifact_staging_root") or "").strip()
    bundle = normalize_packet(
        raw,
        expected=dict(context.get("expected_result") or {}),
        preregistration_sha256=block.get("preregistration_sha256"),
        workspace=Path(str(context.get("agent_workspace") or ".")),
        staging_root=Path(staging) if staging else None,
    )
    if bundle != raw:
        atomic_write_json(path, bundle)


__all__ = [
    "OWNER_STATUSES",
    "PACKET_SCHEMA",
    "TRIGGER_NO_PROGRESS",
    "after_result",
    "applies",
    "choose_runner",
    "enqueue_seat",
    "first_seat",
    "hook_normalize",
    "normalize_packet",
    "record_seat",
    "render_brief",
    "replenish",
    "spec_block",
    "supervise",
    "workspace_digest",
]
