"""Operator pause and resume of one topic in research (2026-11-23, polish mode).

The owner asked to stop new experiments and polish the papers already written. A topic
in research without a manuscript is held, not frozen: its ledger status (``active``),
pre-registration, budget and workspace stay as they are. ``program pause-topic`` sets
the campaign's ``research_state.json`` ``status`` to ``paused`` (with an
``operator_pause`` record), pauses the campaign (queued seats are cancelled) and notes
the decision in the topic ledger. A paused topic holds no research slot
(:func:`openlabs.program.paused_topic_campaigns`), and project synchronization keeps the
campaign paused while the state says so. ``program pause-topic --resume`` reverses it:
state ``active`` again, the campaign resumed; the next tick's synchronization restores
continuous renewal and the owner gets the next seat as usual.

Older holds (2026-11-24): the hand-written ``operator_hold`` of 2026-11-19 and a
``paused`` status without any record are not resumable as such. ``pause-topic`` on such a
topic records them as a regular ``operator_pause`` (status and campaign stay paused; the
original hold is kept inside the record), after which ``--resume`` works like for any
other pause. ``dry_run`` reports what a pause or resume would do and writes nothing.

Hold record (2026-11-25, B3): a new ``operator_pause`` carries the unified fields of
:mod:`openlabs.holds` (kind, scope, by, date, quote, reason, until or condition, restore);
every reader goes through :func:`openlabs.holds.topic_hold`, which also reads the older forms.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from datetime import UTC, datetime
from typing import Any

from .config import FactorySettings, WorkspacePaths
from .contracts import atomic_write_json
from .db import FactoryDB, utc_now
from .holds import TOPIC_RESTORE, topic_hold
from .program import open_topic_ledger, record_topic_note

IN_FLIGHT = ("leased", "running")


class TopicPauseError(ValueError):
    """The topic cannot be paused or resumed in its current state."""


def _state_path(campaign: Mapping[str, Any]) -> Path:
    value = str(campaign.get("workstream_state_path") or "").strip()
    if not value:
        raise TopicPauseError("campaign has no research_state.json path")
    return Path(value)


def _read_state(path: Path) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TopicPauseError(f"cannot read {path}: {exc}") from exc
    if not isinstance(state, dict):
        raise TopicPauseError(f"{path} is not a JSON object")
    return state


def _running_tasks(db: FactoryDB, campaign_id: str) -> list[str]:
    with db.connect() as connection:
        rows = connection.execute(
            "SELECT task_id FROM tasks WHERE campaign_id=? AND status IN (?, ?) "
            "ORDER BY task_id", (campaign_id, *IN_FLIGHT)).fetchall()
    return [str(row["task_id"]) for row in rows]


def _legacy_hold(path: Path, state: Mapping[str, Any]) -> dict[str, Any] | None:
    """A paused state without an ``operator_pause``: the hold's form, start and prior status
    (read through :func:`openlabs.holds.topic_hold`)."""

    if state.get("status") != "paused" or isinstance(state.get("operator_pause"), Mapping):
        return None
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        mtime = None
    hold = topic_hold(state, since=mtime)
    if hold is None:
        return None
    if hold["source"] == "operator_hold":
        return {"form": "operator_hold", "since": hold["date"],
                "since_source": "operator_hold.set_at", "by": hold["by"],
                "prior_status": hold["prior_status"], "hold": hold["detail"]}
    return {"form": "unrecorded", "since": hold["date"],
            "since_source": "research_state.json modification time (paused at or before)",
            "by": None, "prior_status": hold["prior_status"], "hold": None}


def _hold_fields(settings: FactorySettings, topic_id: str, *, quote: str | None,
                 until: str | None, condition: str | None) -> dict[str, Any]:
    """The unified hold fields of a new pause record (openlabs.holds, 2026-11-25)."""

    if until is not None and not str(until).strip():
        until = None
    if until is not None:
        try:
            datetime.fromisoformat(str(until).replace("Z", "+00:00"))
        except ValueError as exc:
            raise TopicPauseError(f"--until is not an ISO date: {until}") from exc
    if not until and not str(condition or "").strip():
        condition = ("polish mode ends and the user agrees to resume new research"
                     if settings.program.polish_mode
                     else "a person resumes it (program pause-topic --resume)")
    return {"kind": "topic_pause", "scope": topic_id, "quote": quote or None,
            "until": until or None, "condition": condition or None,
            "restore": TOPIC_RESTORE.format(scope=topic_id)}


def _queued_tasks(db: FactoryDB, campaign_id: str) -> list[str]:
    with db.connect() as connection:
        rows = connection.execute(
            "SELECT task_id FROM tasks WHERE campaign_id=? AND status IN ('queued', "
            "'awaiting_remote') ORDER BY task_id", (campaign_id,)).fetchall()
    return [str(row["task_id"]) for row in rows]


def pause_topic(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    *,
    topic_id: str,
    reason: str,
    by: str,
    resume: bool = False,
    dry_run: bool = False,
    quote: str | None = None,
    until: str | None = None,
    condition: str | None = None,
) -> dict[str, Any]:
    """Pause (or, with ``resume``, resume) one active topic's research campaign.

    A topic already held by an older form (``operator_hold`` or a bare ``paused``) gets a
    regular ``operator_pause`` record instead; it stays paused. ``dry_run`` writes nothing.
    """

    if not str(reason).strip() or not str(by).strip():
        raise TopicPauseError("--reason and --by are required")
    ledger = open_topic_ledger(paths, settings.program)
    topic = ledger.topic(topic_id)
    if topic is None:
        raise TopicPauseError(f"unknown topic {topic_id}")
    if topic.get("status") != "active":
        raise TopicPauseError(
            f"topic {topic_id} is {topic.get('status')!r}; only an active topic in research "
            "is paused or resumed here")
    campaign_id = str(topic.get("campaign_id") or "")
    campaign = db.campaign(campaign_id) if campaign_id else None
    if campaign is None:
        raise TopicPauseError(f"topic {topic_id} has no campaign")
    path = _state_path(campaign)
    state = _read_state(path)
    now = utc_now()
    result: dict[str, Any] = {
        "schema_version": "openlabs.program_topic_pause.v1",
        "topic_id": topic_id, "campaign_id": campaign_id, "research_state": str(path),
    }
    if dry_run:
        result["dry_run"] = True
    if not resume:
        if state.get("status") == "paused" and isinstance(state.get("operator_pause"), Mapping):
            return {**result, "status": "already_paused", "operator_pause": state["operator_pause"]}
        legacy = _legacy_hold(path, state)
        if legacy is not None:
            if str(campaign.get("status")) != "production_paused":
                raise TopicPauseError(
                    f"research_state is paused ({legacy['form']}) but the campaign is "
                    f"{campaign.get('status')!r}; resolve that by hand first")
            record = {**_hold_fields(settings, topic_id, quote=quote, until=until,
                                     condition=condition),
                      "by": by, "reason": reason, "at": legacy["since"] or now,
                      "date": legacy["since"] or now,
                      "at_source": legacy["since_source"] if legacy["since"] else "recorded_at",
                      "prior_status": legacy["prior_status"], "recorded_at": now,
                      "recorded_from": legacy["form"]}
            if legacy["hold"] is not None:
                record["operator_hold"] = legacy["hold"]
            if dry_run:
                return {**result, "status": "would_record_pause", "operator_pause": record}
            updated = {key: value for key, value in state.items() if key != "operator_hold"}
            atomic_write_json(path, {**updated, "status": "paused", "operator_pause": record})
            record_topic_note(ledger, topic_id, db=db, event_type="topic_operator_pause_recorded",
                              reason="operator_pause", decided_by=f"operator:{by}",
                              detail={key: value for key, value in record.items()
                                      if key != "operator_hold"},
                              key=f"operator_pause_recorded:{now}")
            return {**result, "status": "pause_recorded", "operator_pause": record}
        if state.get("status") != "active":
            raise TopicPauseError(
                f"research_state status is {state.get('status')!r}, not 'active'")
        if str(campaign.get("status")) not in {"active", "production_paused"}:
            raise TopicPauseError(f"campaign status is {campaign.get('status')!r}")
        running = _running_tasks(db, campaign_id)
        if running:
            raise TopicPauseError(
                "tasks of this campaign are running (" + ", ".join(running)
                + "); pause after they finish")
        record = {**_hold_fields(settings, topic_id, quote=quote, until=until,
                                 condition=condition),
                  "by": by, "reason": reason, "at": now, "date": now, "prior_status": "active"}
        if dry_run:
            return {**result, "status": "would_pause", "operator_pause": record,
                    "would_cancel": _queued_tasks(db, campaign_id)}
        atomic_write_json(path, {**state, "status": "paused", "operator_pause": record})
        cancelled = db.pause_production_campaign(campaign_id, reason=f"operator_pause:{by}")
        record_topic_note(ledger, topic_id, db=db, event_type="topic_operator_paused",
                          reason="operator_pause", decided_by=f"operator:{by}",
                          detail={**record, "cancelled_tasks": list(cancelled)},
                          key=f"operator_pause:{now}")
        return {**result, "status": "paused", "operator_pause": record,
                "cancelled_tasks": list(cancelled)}
    pause = state.get("operator_pause")
    if state.get("status") != "paused" or not isinstance(pause, Mapping):
        legacy = _legacy_hold(path, state)
        if legacy is not None:
            raise TopicPauseError(
                f"research_state is paused by an older {legacy['form']} without an "
                "operator_pause record; record it first with pause-topic (without --resume)")
        raise TopicPauseError(
            "research_state is not under an operator pause (status "
            f"{state.get('status')!r}); nothing to resume")
    resumed = {**dict(pause), "resumed_at": now, "resumed_by": by, "resume_reason": reason}
    if dry_run:
        hold = pause.get("operator_hold") if isinstance(pause.get("operator_hold"), Mapping) else {}
        return {**result, "status": "would_resume", "operator_pause": dict(pause),
                "prior_status": str(pause.get("prior_status") or "active"),
                "campaign_status": campaign.get("status"),
                "resume_note": hold.get("resume")}
    history = [item for item in state.get("operator_pause_history") or []
               if isinstance(item, Mapping)]
    updated = {key: value for key, value in state.items() if key != "operator_pause"}
    updated.update({"status": str(pause.get("prior_status") or "active"),
                    "operator_pause_history": [*history, resumed]})
    atomic_write_json(path, updated)
    changed = db.resume_paused_campaign(campaign_id, reason=f"operator_resume:{by}")
    record_topic_note(ledger, topic_id, db=db, event_type="topic_operator_resumed",
                      reason="operator_resume", decided_by=f"operator:{by}",
                      detail=resumed, key=f"operator_resume:{now}")
    return {**result, "status": "resumed", "campaign_resumed": changed, "operator_pause": resumed}
