"""Ledger and task-record reconciliation: ``program reconcile`` (2026-11-20, W3).

The topic ledger and the task table drift from what happened when work is finished
outside the automatic path (a paper delivered by hand, topics parked when the program
was re-planned, stops for a human that were later bypassed). This module lists such
drift and, only with ``--apply``, corrects it through the ordinary transition functions:

* ``mark_delivered``: a topic in ``active``/``in_review`` whose paper (``paper_id`` of the
  ledger, the owner state or the campaign's ``research_state.json``) has a delivery
  receipt ``papers/<paper_id>/releases/pkg_*.json`` -> ``ready_queue`` with the receipt as
  evidence and a delivered ``handoff`` (:func:`program.mark_topic_delivered`); the human
  submission confirmation stays ahead of it;
* ``archive``: an ``admitted``/``active`` topic without a running campaign (missing or
  not ``active``), with no live task and no activity for ``reconcile_stale_days`` ->
  ``frozen`` with reason class ``legacy_archived`` (:func:`program.freeze_topic`; the
  history stays, no automatic reopen). A topic a person holds (its ``research_state.json``
  status ``paused``: ``program pause-topic``'s ``operator_pause``, an ``operator_hold``, or
  no record; read through :func:`openlabs.holds.topic_hold`) is not parked: it is only
  reported, never archived here (2026-11-25: the ``reconcile_operator_pause_days`` knob is
  gone; a hold whose ``until`` passed is reported as expired for a person to decide);
* ``record_delivery``: a ``ready_queue`` topic whose handoff is not ``delivered`` although
  the paper's registry record shows its current version delivered (``delivery.version``
  equals ``version``, the same test as ``paper-writing program release-status``) and the
  matching receipt ``papers/<paper_id>/releases/pkg_*.json`` exists (a delivery made by
  hand) -> handoff ``delivered``, release ``done`` (:func:`program.record_topic_note`, the
  note the release pipeline itself writes), so turning ``auto_handoff`` on does not
  deliver the version again. A release writer task still queued or running is reported
  instead (cancel it first with ``program cancel-task``);
* ``close``: a ``needs_human`` task that no topic in research owns (its topic is ready,
  submitted, frozen or absent, or its campaign is not active) and that is stale or was
  bypassed by a recorded release retry -> ``cancelled`` (:meth:`FactoryDB.close_needs_human`;
  the row, its attempts and result stay);
* ``annotate``: a ``needs_replan`` record of the same kind -> one ``reconcile_annotated``
  event, status unchanged;
* ``report``: drift that needs a person (a paused topic with a manuscript in review, a
  delivered paper whose campaign still runs) is listed without a change.

The dry run (default) only reads: the database is opened read-only by the CLI.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import FactorySettings, WorkspacePaths
from . import delivery_facts
from .db import FactoryDB, utc_now
from .holds import topic_hold

SCHEMA = "openlabs.program_reconcile.v1"
DECIDER = "manual:program-reconcile"
LIVE_STATUSES = ("queued", "leased", "running", "awaiting_remote")
RESEARCH_STATUSES = frozenset({"admitted", "active", "in_review"})


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _iso(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _paper_id(db: FactoryDB, topic: Mapping[str, Any],
              campaign: Mapping[str, Any] | None) -> tuple[str | None, str | None]:
    """``(paper_id, where it came from)`` for a topic, or ``(None, None)``."""

    from .owner import owner_state

    if str(topic.get("paper_id") or "").strip():
        return str(topic["paper_id"]).strip(), "ledger"
    campaign_id = str(topic.get("campaign_id") or "")
    if campaign_id:
        value = str(owner_state(db, campaign_id).get("paper_id") or "").strip()
        if value:
            return value, "owner_state"
    state_path = str((campaign or {}).get("workstream_state_path") or "")
    if state_path:
        value = str(_read_json(Path(state_path)).get("paper_id") or "").strip()
        if value:
            return value, "research_state.json"
    return None, None


def delivery_receipts(paths: WorkspacePaths, paper_id: str) -> list[dict[str, Any]]:
    """Delivery receipts of a paper, oldest first: path, sha256, version, released_at."""

    return delivery_facts.receipts(paths.data, paper_id)


def registered_delivery(paths: WorkspacePaths, paper_id: str) -> dict[str, Any] | None:
    """The paper's current version and its ``delivery`` block when that version is the
    delivered one, with the matching receipt; else None (openlabs.delivery_facts, the one
    definition of "delivered" that ``release-status`` uses too)."""

    import yaml

    path = paths.data / "registry" / "papers" / f"{paper_id}.yaml"
    if not paper_id or "/" in paper_id or not path.is_file():
        return None
    try:
        record = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    found = delivery_facts.current_delivery(record, delivery_receipts(paths, paper_id))
    return None if found is None else {**found, "registry": str(path)}


def _operator_pause(campaign: Mapping[str, Any] | None,
                    scope: str = "") -> dict[str, Any] | None:
    """How a person holds a topic's research (the unified hold record, holds.topic_hold).

    The campaign's ``research_state.json`` has ``status`` ``paused``: by ``program
    pause-topic`` (``operator_pause``), by the hand-written ``operator_hold`` of
    2026-11-19, or without a record. Only a person or an owner agent writes that status,
    so each form is a hold, not a parked legacy topic.
    """

    state_path = str((campaign or {}).get("workstream_state_path") or "")
    if not state_path:
        return None
    return topic_hold(_read_json(Path(state_path)), scope=scope)


def _campaign_rows(db: FactoryDB) -> tuple[dict[str, dict[str, Any]], dict[str, int],
                                            dict[str, str]]:
    marks = ",".join("?" for _ in LIVE_STATUSES)
    with db.connect() as connection:
        campaigns = {str(row["campaign_id"]): dict(row) for row in connection.execute(
            "SELECT * FROM campaigns").fetchall()}
        live = {str(row[0]): int(row[1]) for row in connection.execute(
            f"SELECT campaign_id, COUNT(*) FROM tasks WHERE status IN ({marks}) "  # noqa: S608
            "GROUP BY campaign_id", LIVE_STATUSES).fetchall()}
        last = {str(row[0]): str(row[1] or "") for row in connection.execute(
            "SELECT campaign_id, MAX(updated_at) FROM tasks GROUP BY campaign_id").fetchall()}
    return campaigns, live, last


def _last_activity(topic: Mapping[str, Any], last_task: str | None) -> datetime | None:
    moments = [_parse(entry.get("at")) for entry in topic.get("history") or []
               if isinstance(entry, Mapping)]
    moments.append(_parse(last_task))
    found = [moment for moment in moments if moment is not None]
    return max(found) if found else None


def plan(db: FactoryDB, paths: WorkspacePaths, settings: FactorySettings, *,
         now: datetime | None = None) -> dict[str, Any]:
    """The reconciliation plan: one row per proposed change or reported drift."""

    from .program import open_topic_ledger

    moment = now or datetime.now(UTC)
    stale = timedelta(days=settings.program.reconcile_stale_days)
    document = open_topic_ledger(paths, settings.program).read()
    topics = [topic for topic in document.get("topics") or [] if isinstance(topic, Mapping)]
    campaigns, live, last = _campaign_rows(db)
    by_campaign = {str(topic.get("campaign_id")): topic for topic in topics
                   if topic.get("campaign_id")}
    rows: list[dict[str, Any]] = []
    for topic in topics:
        status = str(topic.get("status") or "")
        topic_id = str(topic.get("topic_id") or "")
        campaign_id = str(topic.get("campaign_id") or "")
        campaign = campaigns.get(campaign_id)
        campaign_status = str((campaign or {}).get("status") or "") or None
        running = live.get(campaign_id, 0)
        activity = _last_activity(topic, last.get(campaign_id))
        base = {"kind": "topic", "id": topic_id, "current": status,
                "campaign_id": campaign_id or None, "campaign_status": campaign_status,
                "live_tasks": running, "last_activity": _iso(activity)}
        if status in {"active", "in_review"}:
            paper_id, source = _paper_id(db, topic, campaign)
            receipts = delivery_receipts(paths, paper_id) if paper_id else []
            revision = topic.get("delivered_revision") or {}
            if revision:
                # All deliveries up through the requested revision's baseline are historical.
                baseline = next((i for i, r in enumerate(receipts)
                                 if r["package_id"] == revision["package_id"]), None)
                receipts = receipts[baseline + 1:] if baseline is not None else []
            if receipts:
                latest = receipts[-1]
                basis = (f"delivery receipt {Path(latest['path']).name} (version "
                         f"{latest['version']}, released {latest['released_at']}) for paper "
                         f"{paper_id} (paper_id from {source})")
                if running:
                    rows.append({**base, "action": "report", "proposed": status,
                                 "basis": basis + f"; {running} live task(s): not changed"})
                    continue
                rows.append({**base, "action": "mark_delivered", "proposed": "ready_queue",
                             "paper_id": paper_id, "paper_id_source": source,
                             "receipt": latest, "basis": basis})
                continue
        if status == "ready_queue":
            handoff = topic.get("handoff") if isinstance(topic.get("handoff"), Mapping) else {}
            if str(handoff.get("status") or "queued") != "delivered":
                paper_id = str(handoff.get("paper_id") or "").strip() or None
                source = "handoff" if paper_id else None
                if paper_id is None:
                    paper_id, source = _paper_id(db, topic, campaign)
                found = registered_delivery(paths, paper_id) if paper_id else None
                if found:
                    release = topic.get("release") if isinstance(topic.get("release"),
                                                                  Mapping) else {}
                    basis = (f"registry {Path(found['registry']).name}: version "
                             f"{found['version']} delivered as {found['package_id']} "
                             f"({found['delivered_at']}), receipt "
                             f"{Path(found['receipt']['path']).name}; ledger handoff "
                             f"{handoff.get('status') or 'queued'}, release "
                             f"{release.get('status') or 'none'}")
                    writer = str(release.get("writer_task_id") or "")
                    writer_status = str((db.task(writer) or {}).get("status") or "") \
                        if writer else ""
                    if writer_status in LIVE_STATUSES:
                        rows.append({**base, "action": "report", "proposed": status,
                                     "basis": basis + f"; release writer {writer} is "
                                              f"{writer_status}: cancel it first (program "
                                              "cancel-task)"})
                    else:
                        rows.append({**base, "action": "record_delivery",
                                     "proposed": "ready_queue (handoff delivered)",
                                     "paper_id": paper_id, "paper_id_source": source,
                                     "delivery": found, "basis": basis})
            continue
        if status in {"admitted", "active"} and not running and campaign_status != "active":
            idle = activity is None or moment - activity >= stale
            where = ("no campaign" if campaign is None else f"campaign {campaign_status}")
            pause = (_operator_pause(campaign, str(topic.get("topic_id") or ""))
                     if status == "active" else None)
            if pause is not None:
                # A held topic is never archived here (2026-11-25, B3: P01 retired). A hold
                # whose ``until`` has passed is reported for a person to resume or close.
                if pause["source"] != "unrecorded":
                    held = (f"{where}, {pause['source']} by {pause.get('by')} since "
                            f"{pause.get('date')} ({str(pause.get('reason') or '')[:120]})")
                else:
                    held = (f"{where}, research_state paused without a pause record (last "
                            f"activity {_iso(activity) or 'unknown'})")
                ends = (f"until {pause['until']}" if pause.get("until")
                        else f"until: {pause['condition']}" if pause.get("condition")
                        else "no end recorded")
                basis = (f"{held}: hold expired ({ends}); resume it or decide by hand"
                         if pause.get("expired") else f"{held}: held, not archived ({ends})")
                rows.append({**base, "action": "report", "proposed": status,
                             "operator_pause": pause["source"] if pause["source"] != "unrecorded"
                             else "paused", "hold": {key: pause.get(key) for key in (
                                 "kind", "by", "date", "until", "condition", "expired")},
                             "basis": basis})
                continue
            if idle:
                rows.append({**base, "action": "archive", "proposed": "frozen",
                             "reason_class": "legacy_archived",
                             "basis": f"{where}, no live task, last activity "
                                      f"{_iso(activity) or 'unknown'} (stale after "
                                      f"{settings.program.reconcile_stale_days:g} d)"})
            else:
                rows.append({**base, "action": "report", "proposed": status,
                             "basis": f"{where}, no live task, recent activity "
                                      f"{_iso(activity)}: left as is (paused recently)"})
            continue
        if status == "in_review" and not running and campaign_status != "active":
            rows.append({**base, "action": "report", "proposed": status,
                         "basis": f"manuscript in review, campaign {campaign_status}, no live "
                                  f"task since {_iso(activity)}: a person decides (resume, "
                                  "deliver or freeze)"})
    rows.extend(_task_rows(db, paths, settings, campaigns=campaigns, by_campaign=by_campaign,
                           topics=topics, moment=moment, stale=stale))
    counts: dict[str, int] = {}
    for row in rows:
        key = f"{row['kind']}:{row['action']}"
        counts[key] = counts.get(key, 0) + 1
    return {"schema_version": SCHEMA, "generated_at": _iso(moment), "dry_run": True,
            "stale_days": settings.program.reconcile_stale_days,
            "counts": dict(sorted(counts.items())), "rows": rows}


def _bypassed(topics: list[Mapping[str, Any]]) -> str:
    """Text of every recorded release retry (a bypassed stop names its task there)."""

    parts = []
    for topic in topics:
        release = topic.get("release")
        if isinstance(release, Mapping):
            parts.append(json.dumps(release.get("retries") or [], sort_keys=True))
        for entry in topic.get("history") or []:
            if isinstance(entry, Mapping) and entry.get("kind") == "release_retry":
                parts.append(json.dumps(entry, sort_keys=True, default=str))
    return "\n".join(parts)


def _release_bypass(task: Mapping[str, Any], topics: list[Mapping[str, Any]]) -> str | None:
    """A release-pipeline task whose topic's release was retried after it, or is done."""

    marker = "/release-packets/"
    path = str(task.get("input_path") or "")
    if marker not in path:
        return None
    topic_id = path.split(marker, 1)[1].split("/", 1)[0]
    topic = next((item for item in topics if item.get("topic_id") == topic_id), None)
    release = (topic or {}).get("release")
    if not isinstance(release, Mapping):
        return None
    updated = _parse(task.get("updated_at"))
    later = [entry for entry in release.get("retries") or [] if isinstance(entry, Mapping)
             and updated is not None and (_parse(entry.get("at")) or updated) > updated]
    if later:
        return f"release of {topic_id} retried after it ({later[0].get('at')})"
    if str(release.get("status") or "") == "done":
        return f"release of {topic_id} done"
    return None


def _task_rows(db: FactoryDB, paths: WorkspacePaths, settings: FactorySettings, *,
               campaigns: Mapping[str, Mapping[str, Any]],
               by_campaign: Mapping[str, Mapping[str, Any]],
               topics: list[Mapping[str, Any]], moment: datetime,
               stale: timedelta) -> list[dict[str, Any]]:
    retries = _bypassed(topics)
    with db.connect() as connection:
        tasks = [dict(row) for row in connection.execute(
            "SELECT task_id, task_type, campaign_id, status, updated_at, last_error, "
            "routing_reason, input_path FROM tasks "
            "WHERE status IN ('needs_human', 'needs_replan') ORDER BY updated_at, rowid"
        ).fetchall()]
    rows = []
    for task in tasks:
        campaign_id = str(task.get("campaign_id") or "")
        topic = by_campaign.get(campaign_id)
        topic_status = str((topic or {}).get("status") or "") or None
        campaign_status = str((campaigns.get(campaign_id) or {}).get("status") or "") or None
        updated = _parse(task.get("updated_at"))
        old = updated is None or moment - updated >= stale
        in_research = topic_status in RESEARCH_STATUSES and campaign_status == "active"
        base = {"kind": "task", "id": str(task["task_id"]), "task_type": task.get("task_type"),
                "current": task.get("status"), "campaign_id": campaign_id or None,
                "campaign_status": campaign_status, "topic_id": (topic or {}).get("topic_id"),
                "topic_status": topic_status, "updated_at": task.get("updated_at")}
        if in_research:
            continue
        released = _release_bypass(task, topics)
        if topic_status in {"ready_queue", "submitted", "frozen"}:
            why = f"topic {topic_status}"
        elif str(task["task_id"]) in retries:
            why = "bypassed by a recorded release retry"
        elif released:
            why = released
        elif topic is None and old:
            why = "no topic (control or release campaign), stale"
        elif old:
            why = f"campaign {campaign_status}, topic {topic_status}, stale"
        else:
            continue
        basis = (f"{why}; last update {task.get('updated_at')}; "
                 f"{str(task.get('last_error') or '')[:160]}").strip("; ")
        if task.get("status") == "needs_human":
            rows.append({**base, "action": "close", "proposed": "cancelled", "basis": basis})
        else:
            rows.append({**base, "action": "annotate", "proposed": "needs_replan (annotated)",
                         "basis": basis})
    return rows


def apply(db: FactoryDB, paths: WorkspacePaths, settings: FactorySettings,
          planned: Mapping[str, Any]) -> dict[str, Any]:
    """Carry out a plan (``--apply``) through the ordinary transition functions."""

    from .program import (freeze_topic, mark_topic_delivered, open_topic_ledger,
                          record_topic_note)
    from .program_autonomy import _write_evidence

    ledger = open_topic_ledger(paths, settings.program)
    done: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for row in planned.get("rows") or []:
        action = row.get("action")
        try:
            if action == "mark_delivered":
                receipt = row["receipt"]
                evidence = [{"path": receipt["path"], "sha256": receipt["sha256"]}]
                handoff = {"status": "delivered", "paper_id": row["paper_id"],
                           "package_id": receipt.get("package_id"),
                           "receipt": receipt["path"], "delivered_at": receipt.get("released_at"),
                           "source": "program_reconcile", "attempts": 0, "last_error": None}
                release = {"status": "done", "stage": "done", "source": "program_reconcile",
                           "updated_at": utc_now(), "last_error": None}
                mark_topic_delivered(ledger, str(row["id"]), db=db, decided_by=DECIDER,
                                     paper_id=str(row["paper_id"]), evidence=evidence,
                                     handoff=handoff, release=release)
                campaign_id = str(row.get("campaign_id") or "")
                if campaign_id and (db.campaign(campaign_id) or {}).get("status") == "active":
                    db.pause_production_campaign(campaign_id, reason="topic_ready_queue")
            elif action == "record_delivery":
                found = row["delivery"]
                receipt = found["receipt"]
                topic = ledger.topic(str(row["id"])) or {}
                if topic.get("status") != "ready_queue":
                    raise ValueError(f"topic is {topic.get('status')!r}, not ready_queue")
                release_before = dict(topic.get("release") or {})
                handoff = {**dict(topic.get("handoff") or {}), "status": "delivered",
                           "paper_id": row["paper_id"], "package_id": found["package_id"],
                           "receipt": receipt["path"], "delivered_at": found["delivered_at"],
                           "submission_handler": None, "last_error": None,
                           "source": "program_reconcile"}
                release = {**release_before, "status": "done", "stage": "done",
                           "writer_task_id": None, "waiting_for": None,
                           "waiting_detail": None, "last_error": None,
                           "source": "program_reconcile",
                           "seq": int(release_before.get("seq") or 0) + 1,
                           "updated_at": utc_now()}
                record_topic_note(
                    ledger, str(row["id"]), db=db, event_type="handoff_delivered",
                    reason="program_reconcile", decided_by=DECIDER,
                    detail={"paper_id": row["paper_id"], "package_id": found["package_id"],
                            "version": found["version"], "awaiting_owner_review": True,
                            "submission_handler": None, "basis": row["basis"],
                            "previous_handoff_status": (topic.get("handoff") or {}).get(
                                "status"),
                            "previous_release_status": release_before.get("status")},
                    evidence=[{"path": receipt["path"], "sha256": receipt["sha256"]}],
                    updates={"handoff": handoff, "release": release,
                             "awaiting_owner_review": True},
                    key=f"handoff_delivered:{row['paper_id']}:{found['package_id']}")
            elif action == "archive":
                evidence = _write_evidence(paths, str(row["id"]), "reconcile-archive", {
                    "basis": row["basis"], "campaign_id": row.get("campaign_id"),
                    "campaign_status": row.get("campaign_status"),
                    "last_activity": row.get("last_activity"), "decided_by": DECIDER})
                freeze_topic(ledger, str(row["id"]), db=db, reason_class="legacy_archived",
                             evidence=[evidence], decided_by=DECIDER)
            elif action == "close":
                db.close_needs_human(str(row["id"]), reason=str(row["basis"])[:300],
                                     detail={"by": DECIDER, "topic_id": row.get("topic_id")})
            elif action == "annotate":
                db.record_event_once("task", str(row["id"]), "reconcile_annotated",
                                     {"by": DECIDER, "basis": row["basis"],
                                      "topic_id": row.get("topic_id")},
                                     event_key=f"reconcile:{row['id']}")
            else:
                continue
        except Exception as exc:  # noqa: BLE001 - one row's failure must not stop the rest.
            errors.append({"id": row.get("id"), "action": action, "error": str(exc)})
            continue
        done.append({"id": row.get("id"), "action": action})
    return {"schema_version": SCHEMA, "applied_at": utc_now(), "dry_run": False,
            "applied": done, "errors": errors}


def render(planned: Mapping[str, Any]) -> str:
    """The dry-run list as plain text: topic/task, current, proposed, basis."""

    lines = [f"program reconcile - dry run {planned.get('generated_at')} (stale after "
             f"{planned.get('stale_days')} d). Nothing was written; --apply carries it out.",
             "", "Counts:"]
    for key, value in (planned.get("counts") or {}).items():
        lines.append(f"  {key}: {value}")
    for kind, title in (("topic", "Topics"), ("task", "Task records")):
        rows = [row for row in planned.get("rows") or [] if row.get("kind") == kind]
        lines += ["", f"{title} ({len(rows)}):"]
        for row in rows:
            extra = f" [{row.get('task_type')}]" if kind == "task" else ""
            lines.append(f"- {row['action']}: {row['id']}{extra}: {row.get('current')} -> "
                         f"{row.get('proposed')}")
            lines.append(f"    basis: {row.get('basis')}")
    return "\n".join(lines) + "\n"


__all__ = ["apply", "delivery_receipts", "plan", "registered_delivery", "render"]
