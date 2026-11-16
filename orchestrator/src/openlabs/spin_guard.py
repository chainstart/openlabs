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
(``no_progress_backoff_minutes``, last value repeats, counted from the last finish);
at ``no_progress_escalate_after`` they stop as ``needs_human`` (``no_progress_circuit``),
which also stops continuous replenishment of the campaign until a human acts.
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
})
NEUTRAL_TASK_TYPES = frozenset({"topic_owner", "topic_scout", "smoke"})
FINISHED_STATUSES = ("succeeded", "needs_replan", "needs_human", "failed", "quarantined",
                     "yielded")
SOURCE_KINDS = ("source", "input")
CIRCUIT_ERROR = "no_progress_circuit"
HISTORY_LIMIT = 60


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
    """``(consecutive no-progress tasks, the most recent finished task)``."""

    classified = classify(_campaign_history(db, campaign_id))
    streak = 0
    for _task, progress in reversed(classified):
        if progress is None:
            continue
        if progress:
            break
        streak += 1
    latest = classified[-1][0] if classified else None
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
