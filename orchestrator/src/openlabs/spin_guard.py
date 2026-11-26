"""Generic no-progress guard and idle-spin metrics (2026-11-16).

Any task chain of one campaign that keeps finishing without progress is backed off
and then stopped for a human, whatever its task type (replan, maturation,
continuation, revision, card repair, ...). Owner seats keep their own breaker
(``owner.py``, ``no_progress_seats``, with its own backoff) and are neutral for the
streak here, but :func:`idle_metrics` counts their no-progress seats as zero output from
the owner breaker's ``owner_seat_recorded`` events; topic scouts have their
empty-draw backoff (``program_flow.scout_supply_blocks``).

A finished task made progress when

- it succeeded with a passed gate and either is a decision task (its decision is the
  product) or its result carries an artifact digest, topic card or paper candidate not
  seen in the campaign's earlier results (input/source documents do not count), or
- it yielded on remote/local jobs none of the campaign's earlier results named.

``needs_replan``, ``needs_human``, ``failed``, ``quarantined`` and yields on old jobs
are no progress; ``cancelled`` and unfinished tasks are skipped. Timestamps, task ids
and summaries are never compared, so a rewritten summary is not progress.

The streak is the number of consecutive most-recent no-progress tasks. From
``[factory].no_progress_backoff_after`` on, the campaign's queued tasks wait
(``no_progress_backoff_minutes``, last value repeats, counted from the last non-neutral
finish, so a finishing scout or owner seat does not push the wait further);
at ``no_progress_escalate_after`` they stop as ``needs_human`` (``no_progress_circuit``),
which also stops continuous replenishment of the campaign until a human acts.

Same-state stalls (2026-11-20). The owner breaker's no-progress streak is reset by a
direction decision or a review request, so a decision that changes nothing let the same
loop run again (topic-943f53cf: three decisions in one day). :func:`state_signature` is
the one definition of "the topic is where it was": owner seats record it
(``owner.record_seat``: ``signature``, ``signature_streak``, reset only when the signature
changes) and ``owner.after_result`` escalates on it (``[factory].stall_signature_repeats``,
``stall_seats_after_decision``). :func:`stuck_report` puts all four guards - owner breaker,
same-state stall, this module's campaign streak, the replan backoff - into one tick
report list (``program.stuck_topics``) and lists every non-terminal ledger topic without
an executable next step (``program.topics_without_next_step``).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import FactorySettings
from .db import FactoryDB

DECISION_TASK_TYPES = frozenset({
    "direction_decision", "portfolio_review", "paper_review", "independent_review",
    "paper_readiness", "topic_admission",
    # A prescreen's product is its verdict (nc_funnel.advance_prescreens); a card stopped
    # at phase A is the funnel moving, not a spin. Line-level "every card fails" is the
    # funnel stall backoff's job (nc_funnel.scout_blocks), which limits scouts only.
    "topic_prescreen",
})
NEUTRAL_TASK_TYPES = frozenset({"topic_owner", "topic_scout", "smoke"})
FINISHED_STATUSES = ("succeeded", "needs_replan", "needs_human", "failed", "quarantined",
                     "yielded")
SOURCE_KINDS = ("source", "input")
CIRCUIT_ERROR = "no_progress_circuit"
HISTORY_LIMIT = 60
# Fields of a state signature (see :func:`state_signature`).
SIGNATURE_FIELDS = ("task_class", "phase", "status", "digest", "jobs", "review_stage",
                    "review_round", "writing", "ledger")
SIGNATURE_VERSION = 1


def state_signature(fields: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """``(sha256, normalized fields)`` of where a topic stands after one task.

    Only control-plane facts: task class, declared phase, packet status, the digest of
    the research files (bookkeeping excluded, ``owner.workspace_digest``), the job ids
    the result names, review stage and round, the writer record's status, the ledger
    status. Summaries, timestamps and task ids are never part of it, so a rewritten
    summary or a refreshed log is the same state.
    """

    normalized: dict[str, Any] = {}
    for key in SIGNATURE_FIELDS:
        value = fields.get(key)
        if isinstance(value, (list, tuple, set, frozenset)):
            value = sorted({str(item) for item in value})
        elif value is not None and not isinstance(value, (str, int, float, bool)):
            value = str(value)
        normalized[key] = value
    digest = hashlib.sha256(json.dumps({"v": SIGNATURE_VERSION, **normalized},
                                       sort_keys=True).encode()).hexdigest()
    return digest, normalized


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _payload(task: Mapping[str, Any]) -> dict[str, Any] | None:
    path = Path(str(task.get("result_path") or ""))
    if not str(task.get("result_path") or "") or not path.is_file():
        return None
    try:
        data = path.read_bytes()
        expected = str(task.get("result_sha256") or "")
        if expected and hashlib.sha256(data).hexdigest() != expected:
            return None
        payload = json.loads(data)
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def result_products(payload: Mapping[str, Any] | None) -> set[str]:
    """What a result adds: non-source artifact digests, card digests, paper flag."""

    if not payload:
        return set()
    products: set[str] = set()
    for item in payload.get("artifacts") or []:
        if not isinstance(item, Mapping) or item.get("external_reference"):
            continue  # a cited input from outside the roots is not a product
        if item.get("volatile_state"):
            continue  # nor is cited live run state, whose hash changes every tick
        kind = str(item.get("kind") or "").lower()
        digest = str(item.get("sha256") or "")
        if digest and not any(word in kind for word in SOURCE_KINDS):
            products.add("artifact:" + digest)
    for card in payload.get("topic_cards") or []:
        products.add("card:" + hashlib.sha256(
            json.dumps(card, sort_keys=True, default=str).encode()).hexdigest())
    if payload.get("paper_candidate") is True:
        products.add("paper_candidate")
    return products


def yielded_jobs(payload: Mapping[str, Any] | None) -> set[str]:
    block = (payload or {}).get("awaiting_remote")
    if not isinstance(block, Mapping):
        return set()
    return {str(item) for item in block.get("job_ids") or []}


def classify(campaign_tasks: list[dict[str, Any]]) -> list[tuple[dict[str, Any], bool | None]]:
    """``[(task, progress)]`` oldest first; ``None`` = neutral (skipped by the streak)."""

    seen_products: set[str] = set()
    seen_jobs: set[str] = set()
    out: list[tuple[dict[str, Any], bool | None]] = []
    for task in campaign_tasks:
        status = str(task.get("status") or "")
        task_type = str(task.get("task_type") or "")
        neutral = task_type in NEUTRAL_TASK_TYPES
        payload = _payload(task) if status in {"succeeded", "yielded"} and not neutral else None
        products = result_products(payload)
        jobs = yielded_jobs(payload)
        if neutral:
            progress: bool | None = None
        elif status == "succeeded":
            progress = task_type in DECISION_TASK_TYPES or bool(products - seen_products)
        elif status == "yielded":
            progress = bool(jobs - seen_jobs)
        else:
            progress = False
        seen_products |= products
        seen_jobs |= jobs
        out.append((task, progress))
    return out


def _campaign_history(
    db: FactoryDB, campaign_id: str, limit: int = HISTORY_LIMIT
) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in FINISHED_STATUSES)
    with db.connect() as connection:
        rows = connection.execute(
            f"SELECT * FROM tasks WHERE campaign_id=? AND status IN ({placeholders}) "  # noqa: S608
            "ORDER BY updated_at DESC, rowid DESC LIMIT ?",
            (campaign_id, *FINISHED_STATUSES, limit),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def no_progress_streak(db: FactoryDB, campaign_id: str) -> tuple[int, dict[str, Any] | None]:
    """``(consecutive no-progress tasks, the most recent finished non-neutral task)``."""

    classified = classify(_campaign_history(db, campaign_id))
    streak = 0
    for _task, progress in reversed(classified):
        if progress is None:
            continue
        if progress:
            break
        streak += 1
    latest = next((task for task, progress in reversed(classified) if progress is not None),
                  None)
    return streak, latest


def _delay_minutes(settings: FactorySettings, streak: int) -> int:
    steps = settings.no_progress_backoff_minutes
    if not steps:
        return 0
    index = min(streak - settings.no_progress_backoff_after, len(steps) - 1)
    return int(steps[max(0, index)])


def guard_queued_tasks(
    db: FactoryDB,
    settings: FactorySettings,
    report: Any,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Back off or stop the queued tasks of campaigns on a no-progress streak."""

    after = settings.no_progress_backoff_after
    if after <= 0:
        return []
    moment = now or _now()
    with db.connect() as connection:
        rows = connection.execute(
            "SELECT * FROM tasks WHERE status='queued' ORDER BY campaign_id, created_at"
        ).fetchall()
    queued: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        task = dict(row)
        if str(task.get("task_type") or "") in NEUTRAL_TASK_TYPES:
            continue
        queued.setdefault(str(task["campaign_id"]), []).append(task)
    actions: list[dict[str, Any]] = []
    for campaign_id, tasks in sorted(queued.items()):
        streak, latest = no_progress_streak(db, campaign_id)
        if streak < after:
            continue
        escalate = settings.no_progress_escalate_after
        base = {
            "campaign_id": campaign_id,
            "consecutive_no_progress": streak,
            "last_task_id": str((latest or {}).get("task_id") or ""),
            "last_task_type": str((latest or {}).get("task_type") or ""),
        }
        for task in tasks:
            task_id = str(task["task_id"])
            if escalate and streak >= escalate:
                detail = {**base, "task_id": task_id, "reason": CIRCUIT_ERROR,
                          "threshold": escalate}
                if db.hold_queued_task(
                    task_id, status="needs_human",
                    error=(f"{CIRCUIT_ERROR}: {streak} consecutive tasks of this campaign "
                           "ended without progress (no new artifact, card or job)"),
                    event_type="no_progress_circuit_open", detail=detail,
                ):
                    actions.append(detail)
                continue
            finished = _parse(str((latest or {}).get("updated_at") or "")) or moment
            until = finished + timedelta(minutes=_delay_minutes(settings, streak))
            current = _parse(task.get("not_before"))
            if until <= moment or (current is not None and current >= until):
                continue
            detail = {**base, "task_id": task_id, "reason": "no_progress_backoff",
                      "not_before": _iso(until)}
            if db.hold_queued_task(task_id, not_before=_iso(until),
                                   event_type="no_progress_backoff", detail=detail):
                actions.append(detail)
    for item in actions:
        report.production_blocked.append({k: v for k, v in item.items() if k != "threshold"})
    return actions


def owner_seat_progress(db: FactoryDB, *, since: str) -> dict[str, bool]:
    """``{seat task id: made progress}`` from ``owner_seat_recorded`` events since ``since``."""

    with db.connect() as connection:
        rows = connection.execute(
            "SELECT payload_json FROM events WHERE event_type='owner_seat_recorded' "
            "AND created_at >= ? ORDER BY event_id",
            (since,),
        ).fetchall()
    result: dict[str, bool] = {}
    for row in rows:
        try:
            payload = json.loads(row[0] or "{}")
        except ValueError:
            continue
        if isinstance(payload, dict) and payload.get("task_id"):
            result[str(payload["task_id"])] = bool(payload.get("progress"))
    return result


def idle_metrics(
    db: FactoryDB,
    *,
    accepted_cards_by_task: Mapping[str, int] | None = None,
    hours: int = 24,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Per task type over the last ``hours``: attempts, zero-output attempts, agent hours.

    Zero output: the attempt's task finished without progress (see ``classify``); a
    topic scout is zero output when no card it returned stands in the ledger as
    anything but rejected (``accepted_cards_by_task``); an owner seat when the owner
    breaker recorded it without progress (:func:`owner_seat_progress`). Unfinished attempts are not
    counted as zero output.
    """

    moment = now or _now()
    since = _iso(moment - timedelta(hours=hours))
    with db.connect() as connection:
        rows = [dict(row) for row in connection.execute(
            """
            SELECT a.task_id, a.run_seconds, a.finished_at, t.task_type, t.campaign_id,
                   t.status
            FROM task_attempts a JOIN tasks t ON t.task_id = a.task_id
            WHERE a.finished_at IS NOT NULL AND a.finished_at >= ?
            """,
            (since,),
        ).fetchall()]
    progress: dict[str, bool | None] = {}
    for campaign_id in sorted({str(row["campaign_id"]) for row in rows}):
        for task, value in classify(_campaign_history(db, campaign_id, limit=500)):
            progress[str(task["task_id"])] = value
    owner_progress = owner_seat_progress(db, since=since)
    cards = accepted_cards_by_task or {}
    by_type: dict[str, dict[str, Any]] = {}
    for row in rows:
        task_type = str(row["task_type"] or "")
        entry = by_type.setdefault(task_type, {
            "attempts": 0, "zero_output": 0, "agent_hours": 0.0, "zero_output_agent_hours": 0.0,
        })
        seconds = float(row["run_seconds"] or 0)
        entry["attempts"] += 1
        entry["agent_hours"] += seconds / 3600
        task_id = str(row["task_id"])
        if task_type == "topic_scout":
            zero = cards.get(task_id, 0) == 0 and str(row["status"]) in FINISHED_STATUSES
        elif task_type == "topic_owner":
            # The owner breaker's own verdict (owner.record_seat), latest per seat.
            zero = owner_progress.get(task_id) is False
        else:
            zero = progress.get(task_id) is False
        if zero:
            entry["zero_output"] += 1
            entry["zero_output_agent_hours"] += seconds / 3600
    for entry in by_type.values():
        entry["agent_hours"] = round(entry["agent_hours"], 2)
        entry["zero_output_agent_hours"] = round(entry["zero_output_agent_hours"], 2)
    total = {
        key: round(sum(entry[key] for entry in by_type.values()), 2)
        for key in ("attempts", "zero_output", "agent_hours", "zero_output_agent_hours")
    }
    return {"window_hours": hours, "since": since, "by_task_type": by_type, "total": total}


# --------------------------------------------------------------------------- one report

LIVE_STATUSES = ("queued", "leased", "running", "awaiting_remote")
NON_TERMINAL_TOPIC_STATUSES = ("admitted", "active", "in_review", "ready_queue")
# The engine's replan backoff starts at this many consecutive needs_replan results.
REPLAN_STUCK_AFTER = 3


def stuck_report(
    db: FactoryDB,
    paths: Any,
    settings: FactorySettings,
    *,
    guard_actions: list[Mapping[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """``{"stuck_topics": [...], "topics_without_next_step": [...]}`` for the tick report.

    ``stuck_topics`` gathers every guard in one list, each row with its ``source``:
    ``same_state`` (owner seats with an unchanged :func:`state_signature`; ``stopped`` when
    no further seat is queued), ``owner_no_progress`` (the owner breaker's streak),
    ``campaign_no_progress`` (this module's backoff/circuit, from ``guard_actions``) and
    ``replan_backoff`` (consecutive needs_replan). ``topics_without_next_step`` lists
    the ledger topics in admitted/active/in_review/ready_queue with nothing that would move
    them: no live task, no pending direction decision, no delivery step or human
    confirmation ahead (a paused or missing campaign, a stalled owner, an exhausted
    release, an admitted card never materialized within ``reconcile_stale_days``).
    """

    from . import owner as owner_mode
    from .program import open_topic_ledger
    from .program_autonomy import pending_decision

    moment = now or _now()
    stuck: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    document = open_topic_ledger(paths, settings.program).read()
    marks = ",".join("?" for _ in LIVE_STATUSES)
    with db.connect() as connection:
        live = {str(row[0]): int(row[1]) for row in connection.execute(
            f"SELECT campaign_id, COUNT(*) FROM tasks WHERE status IN ({marks}) "  # noqa: S608
            "GROUP BY campaign_id", LIVE_STATUSES).fetchall()}
        campaigns = {str(row[0]): str(row[1]) for row in connection.execute(
            "SELECT campaign_id, status FROM campaigns").fetchall()}
    repeats = settings.stall_signature_repeats
    stale = timedelta(days=settings.program.reconcile_stale_days)
    for topic in document.get("topics") or []:
        status = str(topic.get("status") or "")
        if status not in NON_TERMINAL_TOPIC_STATUSES:
            continue
        topic_id = str(topic.get("topic_id") or "")
        campaign_id = str(topic.get("campaign_id") or "")
        base = {"topic_id": topic_id, "campaign_id": campaign_id or None, "status": status}
        state = owner_mode.owner_state(db, campaign_id) if campaign_id else {}
        stall = owner_mode.stalled(state)
        streak = int(state.get("signature_streak") or 0)
        if stall is not None:
            stuck.append({**base, "source": "same_state", "action": "stopped",
                          "since": stall.get("stopped_at"), "signature_streak": streak,
                          "state": dict(state.get("signature_fields") or {}),
                          "decision_task": stall.get("decision_task")})
        elif repeats and streak >= repeats:
            stuck.append({**base, "source": "same_state", "action": "watching",
                          "signature_streak": streak,
                          "state": dict(state.get("signature_fields") or {})})
        if int(state.get("no_progress_streak") or 0) >= 2:
            stuck.append({**base, "source": "owner_no_progress",
                          "no_progress_streak": int(state.get("no_progress_streak") or 0),
                          "threshold": settings.program.owner.no_progress_seats})
        reason = _missing_next_step(db, topic, campaigns, live, stall, pending_decision,
                                    moment=moment, stale=stale)
        if reason is not None:
            row = {**base, "reason": reason, "campaign_status": campaigns.get(campaign_id)}
            if reason in {"no_live_task", "owner_stalled"}:
                row.update(_blocked_task_hint(db, campaign_id))
            missing.append(row)
    for action in guard_actions or []:
        stuck.append({"campaign_id": action.get("campaign_id"), "source": "campaign_no_progress",
                      "action": action.get("reason"),
                      "consecutive_no_progress": action.get("consecutive_no_progress"),
                      "last_task_type": action.get("last_task_type")})
    for campaign_id, campaign_status in sorted(campaigns.items()):
        if campaign_status != "active":
            continue
        replans = db.replan_streak(campaign_id)
        if replans >= REPLAN_STUCK_AFTER:
            stuck.append({"campaign_id": campaign_id, "source": "replan_backoff",
                          "consecutive_needs_replan": replans})
    return {"stuck_topics": stuck, "topics_without_next_step": missing}


def _blocked_task_hint(db: FactoryDB, campaign_id: str) -> dict[str, Any]:
    """The campaign's latest task when it stopped quarantined/needs_human for a reason the
    infrastructure triage does not retry, with the command that queues it again."""

    from .engine import _infrastructure_failure

    try:
        with db.connect() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE campaign_id=? ORDER BY updated_at DESC, rowid DESC "
                "LIMIT 1", (campaign_id,)).fetchone()
    except Exception:  # noqa: BLE001 - the hint is advisory
        return {}
    if row is None or str(row["status"]) not in {"quarantined", "needs_human"}:
        return {}
    latest = dict(row)
    try:
        failure_class, _ = _infrastructure_failure(db, latest)
    except Exception:  # noqa: BLE001 - the hint is advisory
        failure_class = None
    if failure_class is not None:
        return {}
    flag = " --allow-needs-human" if latest["status"] == "needs_human" else ""
    return {
        "blocked_task": {"task_id": latest["task_id"], "task_type": latest["task_type"],
                         "status": latest["status"]},
        "suggested_command": (f"python -m openlabs program requeue {latest['task_id']}"
                              f"{flag} --reason \"<what was fixed>\""),
    }


def _missing_next_step(
    db: FactoryDB,
    topic: Mapping[str, Any],
    campaigns: Mapping[str, str],
    live: Mapping[str, int],
    stall: Mapping[str, Any] | None,
    pending_decision: Any,
    *,
    moment: datetime,
    stale: timedelta,
) -> str | None:
    """Why a non-terminal topic has no executable next step, or None when it has one."""

    status = str(topic.get("status") or "")
    campaign_id = str(topic.get("campaign_id") or "")
    if status == "ready_queue":
        release = topic.get("release") if isinstance(topic.get("release"), Mapping) else {}
        handoff = topic.get("handoff") if isinstance(topic.get("handoff"), Mapping) else {}
        if "exhausted" in {str(release.get("status") or ""), str(handoff.get("status") or "")}:
            return "release_exhausted"
        return None  # the delivery pipeline, then a human confirmation
    if campaign_id and live.get(campaign_id):
        return None
    if campaign_id and pending_decision(db, campaign_id) is not None:
        return None
    if not campaign_id or campaign_id not in campaigns:
        admitted = _parse(str(topic.get("admitted_at") or ""))
        if status == "admitted" and admitted is not None and moment - admitted < stale:
            return None  # waits for its materialization slot
        return "no_campaign"
    if campaigns[campaign_id] != "active":
        return f"campaign_{campaigns[campaign_id]}"
    if stall is not None:
        return "owner_stalled"
    return "no_live_task"
