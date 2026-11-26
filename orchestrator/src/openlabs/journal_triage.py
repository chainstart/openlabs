"""Model triage of the journal letters journal_mail leaves to a person (2026-11-26).

The journal_mail service stays a resident, deterministic process. A letter its rules cannot
settle (held, undecided, unmatched, unreadable) is queued in the ``review`` table of its
events.sqlite; with ``[program] journal_mail_model_review`` on, it also carries a redacted
brief and ``model_state='pending'`` (paper_writing.journal_triage). Each tick this step

* collects finished ``journal_mail_triage`` tasks: the model's answer for every letter goes
  into the row (``model``, ``model_state='done'``); a task that failed, was cancelled or left
  no hash-bound result marks its letters ``failed`` (the digest then says "模型无结论");
* hands up to :data:`BATCH` pending letters to one new task when none is in flight. The task
  runs on the light tier (``DEFAULT_TASK_TIERS``), so routing, quota accounting, quota
  deferral, retries and logs are those of every other task; the model exits when it is done.

The answer is validated (schema, verbatim evidence) by the service when it writes the digest;
nothing here changes the site, the ledger or the service's events.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from .config import FactorySettings, WorkspacePaths, dispatch_runner
from .contracts import atomic_write_json, sha256_file
from .db import FactoryDB, utc_now
from .resources import default_task_resources

TASK_TYPE = "journal_mail_triage"
ROUTING_REASON = "journal_mail_triage"
SKILL = "openlabs-journal-mail-triage"
PACKET_SCHEMA = "openlabs.journal_mail_triage_packet.v1"
CAMPAIGN_ID = "ai-journal-mail-triage"
DOMAIN = "ai"
BATCH = 20
# Task statuses after which a task gives no answer.
GIVES_NO_ANSWER = frozenset({"failed", "needs_human", "needs_replan", "quarantined", "cancelled",
                             "launch_failed", "result_rejected"})
COLUMNS = frozenset({"brief", "model_state", "model", "model_task"})


def journal_state(paths: WorkspacePaths) -> Path:
    """events.sqlite of the journal_mail service (site_assignment.journal_mail_state)."""

    return paths.settings_file.parent / "state" / "journal-mail" / "events.sqlite"


def _campaign(db: FactoryDB, settings: FactorySettings) -> str:
    """The control campaign of the triage tasks (as assets._control_campaign)."""

    campaign = db.campaign(CAMPAIGN_ID)
    if campaign is not None:
        used = float(campaign.get("agent_seconds_used") or 0)
        current = int(campaign.get("max_agent_seconds") or 0)
        status = str(campaign.get("status") or "")
        if status not in {"active", "budget_exhausted"} or (
            status == "active" and used + settings.max_task_wall_seconds + 1 <= current
        ):
            return CAMPAIGN_ID
        budget = max(current, int(used) + settings.max_campaign_agent_seconds)
    else:
        budget = settings.max_campaign_agent_seconds
    db.register_campaign(CAMPAIGN_ID, domain=DOMAIN, title="journal mail letters read by a model",
                         priority=0, source="program:journal_mail_triage",
                         max_agent_seconds=budget)
    return CAMPAIGN_ID


def _answers(task: dict[str, Any]) -> dict[str, Any] | None:
    """key -> answer of a succeeded task's hash-bound result, or None."""

    result_path = Path(str(task.get("result_path") or ""))
    expected = str(task.get("result_sha256") or "")
    if not result_path.is_file() or not expected or sha256_file(result_path) != expected:
        return None
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    items = payload.get("journal_triage") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return None
    return {str(item["key"]): item for item in items if isinstance(item, dict) and item.get("key")}


def collect(db: FactoryDB, journal: sqlite3.Connection) -> dict[str, int]:
    """Write the answers of finished triage tasks into their letters' review rows."""

    counts = {"answered": 0, "failed": 0, "requeued": 0}
    groups: dict[str, list[str]] = {}
    for key, task_id in journal.execute(
        "SELECT key, model_task FROM review WHERE model_state='dispatched'"
    ).fetchall():
        groups.setdefault(str(task_id or ""), []).append(str(key))
    for task_id, keys in groups.items():
        task = db.task(task_id) if task_id else None
        if task is None:
            # The task never got written (a crash between the two steps): ask again.
            journal.executemany("UPDATE review SET model_state='pending', model_task=NULL "
                                "WHERE key=? AND model_state='dispatched'", [(k,) for k in keys])
            counts["requeued"] += len(keys)
            continue
        status = str(task.get("status") or "")
        if status == "succeeded":
            answers = _answers(task)
        elif status in GIVES_NO_ANSWER:
            answers = None
        else:
            continue  # queued, leased, running, quota_deferred, ...
        for key in keys:
            answer = (answers or {}).get(key)
            if answer is None:
                answer = {"error": (f"任务 {status}" if answers is None and status != "succeeded"
                                    else "任务结果无此信的结论")}
            state = "done" if "error" not in answer else "failed"
            journal.execute("UPDATE review SET model=?, model_state=? WHERE key=? AND model_state='dispatched' "
                            "AND model_task=?", (json.dumps(answer, ensure_ascii=False)[:20_000], state,
                                                 key, task_id))
            counts["answered" if state == "done" else "failed"] += 1
    journal.commit()
    return counts


def _in_flight(db: FactoryDB) -> bool:
    with db.connect() as connection:
        row = connection.execute(
            "SELECT 1 FROM tasks WHERE task_type=? AND status NOT IN ('succeeded', 'failed', "
            "'needs_human', 'needs_replan', 'quarantined', 'cancelled', 'launch_failed', "
            "'result_rejected') LIMIT 1",
            (TASK_TYPE,),
        ).fetchone()
    return row is not None


def dispatch(db: FactoryDB, paths: WorkspacePaths, settings: FactorySettings,
             journal: sqlite3.Connection) -> str | None:
    """One task for up to BATCH pending letters, unless a triage task is in flight."""

    if _in_flight(db):
        return None
    rows = journal.execute(
        "SELECT key, brief FROM review WHERE model_state='pending' AND brief IS NOT NULL "
        "ORDER BY rowid LIMIT ?", (BATCH,)
    ).fetchall()
    if not rows:
        return None
    letters = []
    for key, brief in rows:
        try:
            letters.append({"key": str(key), "letter": json.loads(brief)})
        except ValueError:
            journal.execute("UPDATE review SET model_state='failed', model=? WHERE key=?",
                            (json.dumps({"error": "摘要无法读取"}, ensure_ascii=False), key))
    if not letters:
        journal.commit()
        return None
    keys = [item["key"] for item in letters]
    task_id = "journal-triage:" + hashlib.sha256("\n".join(keys).encode()).hexdigest()[:32]
    if db.task(task_id) is None:
        folder = paths.program_control / "journal-mail-triage"
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        packet_path = folder / f"{task_id.split(':', 1)[1]}.json"
        atomic_write_json(packet_path, {"schema_version": PACKET_SCHEMA, "task_id": task_id,
                                        "letters": letters, "created_at": utc_now()})
        os.chmod(packet_path, 0o600)
        db.enqueue_task(
            task_id=task_id,
            campaign_id=_campaign(db, settings),
            domain=DOMAIN,
            task_type=TASK_TYPE,
            objective=(
                f"Read the {len(letters)} journal letters in the packet at the input path and "
                "classify each as the Skill openlabs-journal-mail-triage defines. Return "
                "`journal_triage` in the result bundle: one answer object per letter, keyed by "
                "its `key`, with evidence quoted word for word from that letter's subject or "
                "sentences. Read nothing else, contact no one and change nothing: a person "
                "registers the outcome."
            ),
            input_path=str(packet_path),
            skill_path=SKILL,
            runner=dispatch_runner(settings, TASK_TYPE, ROUTING_REASON, "cheap"),
            routing_reason=ROUTING_REASON,
            agent_role="researcher",
            session_mode="fresh",
            priority=0,
            max_attempts=2,
            max_wall_seconds=min(1_800, settings.max_task_wall_seconds),
            **default_task_resources(settings).to_dict(),
        )
    journal.executemany("UPDATE review SET model_state='dispatched', model_task=? "
                        "WHERE key=? AND model_state='pending'", [(task_id, k) for k in keys])
    journal.commit()
    return task_id


def triage_tick(db: FactoryDB, paths: WorkspacePaths, settings: FactorySettings,
                report: Any) -> None:
    """Collect finished triage tasks and dispatch the next batch (never a tick error)."""

    info = report.program.setdefault("journal_mail_triage", {})
    if not getattr(settings.program, "journal_mail_model_review", False):
        info["outcome"] = "skipped_journal_mail_model_review_off"
        return
    state = journal_state(paths)
    if not state.is_file():
        info["outcome"] = "no_journal_state"
        return
    try:
        with sqlite3.connect(state, timeout=10) as journal:
            present = {row[1] for row in journal.execute("PRAGMA table_info(review)")}
            if not COLUMNS <= present:
                info["outcome"] = "journal_mail_not_upgraded"
                return
            info.update(collect(db, journal))
            task_id = dispatch(db, paths, settings, journal)
            info["outcome"] = "ok"
            if task_id:
                info["dispatched"] = task_id
                report.enqueued.append(task_id)
    except (OSError, sqlite3.Error, ValueError) as exc:
        info.update(outcome="failed", error=f"{type(exc).__name__}: {exc}"[:300])
