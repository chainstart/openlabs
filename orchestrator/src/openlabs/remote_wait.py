"""Park a task while the compute jobs it waits for are still queued or running.

Jobs are ailab jobs (``bin/openlabs-remote``) or local background jobs
(``bin/openlabs-local``, ``openlabs.local_compute``); both are identified by a
32-hex job id and expose the same ``status.json``.

An agent that has submitted ailab jobs (``bin/openlabs-remote submit``) and has nothing
useful to do until they finish ends its attempt with ``status: "awaiting_remote"`` and
``awaiting_remote.job_ids``. The orchestrator then creates the continuation task in
status ``awaiting_remote``: it is never claimed, charges no Agent time, consumes no
attempt and triggers no replan or direction decision. Every tick reads the listed jobs'
``status.json`` (read only) and, once all of them are terminal (succeeded, failed,
withdrawn or missing), releases the continuation to ``queued`` with the job outcomes
prepended to its objective, resuming the same Agent session.

A wait has a deadline: the longest declared job wall time plus a queue margin (or the
agent's ``max_wait_seconds``), extended while a job is running, never beyond seven days.
An expired wait is released once with a note; if the resumed agent yields again on the
same jobs, the next continuation stops for a human instead.

The topic's calendar deadline is unaffected: it counts from admission regardless.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .contracts import MAX_REMOTE_WAIT_SECONDS, REMOTE_JOB_ID

WAIT_META_PREFIX = "remote_wait:"
# Queue margin added to the longest declared job wall time.
QUEUE_SLACK_SECONDS = 24 * 3600
# Used when a job's request.json does not declare its wall time.
DEFAULT_JOB_WALL_SECONDS = 6 * 3600
# A running job may finish up to this long after its declared wall time.
RUNNING_GRACE_SECONDS = 3600
TERMINAL_STATES = frozenset({"succeeded", "failed", "withdrawn", "missing"})
RESEARCH_ROLES = frozenset({"researcher", "experimenter"})
_JOB_ID_IN_TEXT = re.compile(r"(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])")


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def default_queue_root() -> Path:
    from .remote_compute import default_queue_root as queue_root

    return queue_root()


def local_queue_root() -> Path:
    from .local_compute import default_queue_root as queue_root

    return queue_root()


def job_state(
    queue_root: Path, job_id: str, *, local_root: Path | None = None
) -> dict[str, Any]:
    """Read-only view of one job: state, error, declared wall time and result path.

    The id is looked up in the ailab queue first, then in the local background
    queue (``openlabs.local_compute``); both use the same layout.
    """

    directory = Path(queue_root) / "jobs" / job_id
    backend = "ailab"
    if REMOTE_JOB_ID.match(job_id) and not directory.is_dir():
        local = (local_root or local_queue_root()) / "jobs" / job_id
        if local.is_dir():
            directory, backend = local, "local"
    view: dict[str, Any] = {
        "job_id": job_id,
        "backend": backend,
        "result_dir": str(directory / "result"),
    }
    if not REMOTE_JOB_ID.match(job_id) or not directory.is_dir():
        return {**view, "state": "missing"}
    try:
        request = json.loads((directory / "request.json").read_text(encoding="utf-8"))
        wall = int((request.get("resources") or {}).get("wall_seconds") or 0)
        if wall > 0:
            view["wall_seconds"] = wall
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    try:
        if any(directory.glob("WITHDRAWN*")):
            return {**view, "state": "withdrawn"}
    except OSError:
        pass
    try:
        status = json.loads((directory / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {**view, "state": "unknown"}
    if not isinstance(status, Mapping):
        return {**view, "state": "unknown"}
    state = str(status.get("state") or "unknown")
    view["state"] = state if state in {"queued", "running", "succeeded", "failed"} else "unknown"
    if status.get("updated_at"):
        view["updated_at"] = str(status["updated_at"])
    if status.get("error"):
        view["error"] = str(status["error"])[:500]
    if status.get("receipt_sha256"):
        view["receipt_sha256"] = str(status["receipt_sha256"])
    return view


def is_terminal(view: Mapping[str, Any]) -> bool:
    return str(view.get("state")) in TERMINAL_STATES


def initial_deadline(
    views: Iterable[Mapping[str, Any]],
    *,
    since: datetime,
    max_wait_seconds: int | None = None,
) -> datetime:
    longest = max(
        (int(view.get("wall_seconds") or DEFAULT_JOB_WALL_SECONDS) for view in views),
        default=DEFAULT_JOB_WALL_SECONDS,
    )
    seconds = int(max_wait_seconds) if max_wait_seconds else longest + QUEUE_SLACK_SECONDS
    return since + timedelta(seconds=min(seconds, MAX_REMOTE_WAIT_SECONDS))


def effective_deadline(
    record: Mapping[str, Any],
    views: Iterable[Mapping[str, Any]],
) -> datetime:
    """Stored deadline, extended while a job runs (up to the seven-day ceiling)."""

    since = _parse(record.get("since")) or _now()
    deadline = _parse(record.get("deadline")) or initial_deadline([], since=since)
    for view in views:
        started = _parse(view.get("updated_at"))
        if view.get("state") == "running" and started is not None:
            wall = int(view.get("wall_seconds") or DEFAULT_JOB_WALL_SECONDS)
            deadline = max(deadline, started + timedelta(seconds=wall + RUNNING_GRACE_SECONDS))
    return min(deadline, since + timedelta(seconds=MAX_REMOTE_WAIT_SECONDS))


def pending_job_ids(payload: Mapping[str, Any], queue_root: Path) -> list[str]:
    """Remote jobs named in a result that exist in the queue and are not yet terminal.

    Used to recognise a ``needs_replan`` result whose real conclusion is "wait for
    job X": such a result parks like an explicit ``awaiting_remote`` yield instead of
    starting another replan.
    """

    texts: list[str] = [str(payload.get("summary") or "")]
    for action in payload.get("next_actions") or []:
        if isinstance(action, Mapping):
            texts.append(str(action.get("objective") or ""))
        else:
            texts.append(str(action))
    block = payload.get("awaiting_remote")
    if isinstance(block, Mapping) and isinstance(block.get("job_ids"), list):
        texts.extend(str(item) for item in block["job_ids"])
    found: list[str] = []
    for text in texts:
        for job_id in _JOB_ID_IN_TEXT.findall(text):
            if job_id not in found:
                found.append(job_id)
    pending = []
    for job_id in found:
        view = job_state(queue_root, job_id)
        if view["state"] in {"queued", "running"}:
            pending.append(job_id)
    return pending


def wait_record(db: Any, task_id: str) -> dict[str, Any] | None:
    raw = db.meta_get(WAIT_META_PREFIX + task_id)
    if not raw:
        return None
    try:
        record = json.loads(raw)
    except ValueError:
        return None
    return record if isinstance(record, dict) else None


def repeated_expired_wait(db: Any, task_id: str, job_ids: Iterable[str]) -> bool:
    """True when ``task_id`` was released from an expired wait on any of ``job_ids``."""

    record = wait_record(db, task_id)
    if not record or not record.get("expired"):
        return False
    return bool(set(record.get("job_ids") or ()) & set(job_ids))


def build_record(
    *,
    job_ids: list[str],
    queue_root: Path,
    source_task_id: str,
    source_attempt_id: str,
    origin: str,
    max_wait_seconds: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    since = now or _now()
    views = [job_state(queue_root, job_id) for job_id in job_ids]
    return {
        "job_ids": list(job_ids),
        "queue_root": str(queue_root),
        "since": _iso(since),
        "deadline": _iso(initial_deadline(views, since=since, max_wait_seconds=max_wait_seconds)),
        "source_task_id": source_task_id,
        "source_attempt_id": source_attempt_id,
        "origin": origin,
        "states_at_start": {view["job_id"]: view["state"] for view in views},
    }


def parked_objective(job_ids: list[str], objective: str) -> str:
    return (
        "[Parked by the orchestrator until remote jobs "
        + ", ".join(job_ids)
        + " finish; their outcomes are added here before this task starts.]\n\n"
        + objective
    )


def _outcome_note(views: list[Mapping[str, Any]], *, expired: bool, now: datetime) -> str:
    lines = []
    for view in views:
        line = f"- {view['job_id']} ({view.get('backend', 'ailab')}): {view['state']}"
        if view.get("error"):
            line += f" (error: {view['error']})"
        if view["state"] in {"succeeded", "failed"}:
            line += f"; result files under {view['result_dir']}"
        lines.append(line)
    if expired:
        head = (
            f"The remote wait reached its deadline at {_iso(now)} before every job finished. "
            "Decide from the states below: use finished outputs, withdraw or resubmit a stuck "
            "job with a smaller budget, or replan. Yielding again on the same jobs stops the "
            "topic for a human."
        )
    else:
        head = (
            f"Every remote job this task waited for is terminal (checked {_iso(now)}). Read "
            "each receipt and log before using the outputs; a failed, withdrawn or missing "
            "job is a result to record, not to hide."
        )
    return head + "\n" + "\n".join(lines)


def _strip_parked_prefix(objective: str) -> str:
    if objective.startswith("[Parked by the orchestrator"):
        _, _, rest = objective.partition("]\n\n")
        return rest or objective
    return objective


def release_ready_waits(
    db: Any,
    *,
    now: datetime | None = None,
    queue_root: Path | None = None,
) -> dict[str, Any]:
    """Release parked tasks whose jobs are all terminal or whose wait expired.

    Reads only the queue's ``status.json``/``request.json`` files; never writes there.
    """

    moment = now or _now()
    summary: dict[str, Any] = {"released": [], "expired": [], "waiting": []}
    for task in db.awaiting_remote_tasks():
        task_id = str(task["task_id"])
        record = wait_record(db, task_id)
        if record is None:
            # A parked task without its wait record cannot be checked: run it.
            db.release_awaiting_task(
                task_id,
                objective=_strip_parked_prefix(str(task["objective"])),
                event={"reason": "wait_record_missing"},
            )
            summary["released"].append(task_id)
            continue
        root = Path(str(record.get("queue_root") or queue_root or default_queue_root()))
        views = [job_state(root, str(job_id)) for job_id in record.get("job_ids") or []]
        done = all(is_terminal(view) for view in views)
        deadline = effective_deadline(record, views)
        expired = not done and moment >= deadline
        if not done and not expired:
            summary["waiting"].append(
                {
                    "task_id": task_id,
                    "pending": [v["job_id"] for v in views if not is_terminal(v)],
                    "deadline": _iso(deadline),
                }
            )
            continue
        note = _outcome_note(views, expired=expired, now=moment)
        objective = note + "\n\n" + _strip_parked_prefix(str(task["objective"]))
        states = {view["job_id"]: view["state"] for view in views}
        if db.release_awaiting_task(
            task_id,
            objective=objective,
            event={"expired": expired, "job_states": states},
        ):
            db.update_meta(
                {
                    WAIT_META_PREFIX + task_id: json.dumps(
                        {
                            **record,
                            "released_at": _iso(moment),
                            "expired": expired,
                            "job_states": states,
                        },
                        sort_keys=True,
                    )
                }
            )
            summary["expired" if expired else "released"].append(task_id)
    return summary
