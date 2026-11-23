"""Site submitter assignments follow readiness; operator registration of a submission.

User rule (2026-11-23): "当处于'尚未投稿'状态的论文，不要分配投稿人，只有通过门禁，状态改为
'可投稿'后，才分配投稿人".

The management site assigns the second declared author when a paper is first created
(server side). ``paper-writing program sync-site-assignments`` (paper_writing.site_assignments)
corrects that through the regular assignment endpoint: no active submitter while a paper is not
ready to submit (the admin service account holds a placeholder that records the default
submitter), the recorded original submitter -- else the second author -- once it is. The
release pipeline's delivery calls it for the delivered paper; every tick calls it for all
pre-submission papers (:func:`sync_tick`); ``program sync-site-assignments`` runs it by hand.

``program mark-submitted`` records that a delivered paper was submitted to a journal: the topic
moves ``ready_queue -> submitted`` (:func:`openlabs.program.mark_topic_submitted`) with a
receipt as evidence.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import FactorySettings, WorkspacePaths
from .contracts import atomic_write_json
from .db import FactoryDB, utc_now
from .program import TopicLedgerError, mark_topic_submitted, record_topic_note


class SiteAssignmentError(ValueError):
    """The step cannot run (credentials, command failure, unknown paper)."""


def _log_path(paths: WorkspacePaths) -> Path:
    return paths.database / "site-assignments.jsonl"


def run_sync(paths: WorkspacePaths, settings: FactorySettings, *,
             paper_ids: Iterable[str] = (), apply: bool = False) -> dict[str, Any]:
    """Run ``paper-writing program sync-site-assignments`` (dry run unless ``apply``)."""

    from .program_autonomy import (DELIVERY_ENVIRONMENT, DeliveryError, _run_paper_command,
                                   pipeline_credentials)

    credentials, refused = pipeline_credentials(settings, DELIVERY_ENVIRONMENT)
    missing = [name for name in DELIVERY_ENVIRONMENT if name not in credentials]
    if missing:
        raise SiteAssignmentError(f"credentials missing: {missing}"
                                  + (f" ({refused})" if refused else ""))
    arguments = ["program", "sync-site-assignments", "--log", str(_log_path(paths))]
    for paper_id in paper_ids:
        arguments += ["--paper-id", str(paper_id)]
    environment = dict(credentials)
    if apply:
        arguments.append("--apply")
        environment["OPENLABS_ENABLE_EXTERNAL_WRITES"] = "1"
    try:
        return _run_paper_command(paths, settings, arguments, environment=environment,
                                  timeout=600)
    except DeliveryError as exc:
        raise SiteAssignmentError(str(exc)) from exc


def _note_changes(db: FactoryDB, paths: WorkspacePaths, settings: FactorySettings,
                  changed: Iterable[Mapping[str, Any]]) -> None:
    from .program_autonomy import _ledger

    ledger = _ledger(paths, settings)
    topics = ledger.read().get("topics") or []
    for entry in changed:
        paper_id = str(entry.get("paper_id") or "")
        topic = next((item for item in topics
                      if paper_id and paper_id in {str(item.get("paper_id") or ""),
                                                   str((item.get("handoff") or {})
                                                       .get("paper_id") or "")}), None)
        if topic is None:
            continue
        action = str(entry.get("action"))
        person = entry.get("target") or entry.get("default_submitter") or {}
        record_topic_note(
            ledger, str(topic["topic_id"]), db=db,
            event_type=f"site_assignment_{'parked' if action == 'park' else 'assigned'}",
            reason="site_assignment_follows_readiness", decided_by="orchestrator:site_assignment",
            detail={"paper_id": paper_id, "action": action, "submitter": person.get("name"),
                    "submitter_source": person.get("source"),
                    "reasons": list(entry.get("reasons") or [])[:5],
                    "assignment_id": entry.get("assignment_id")},
            key=f"site_assignment:{paper_id}:{entry.get('assignment_id')}",
        )


def sync_tick(db: FactoryDB, paths: WorkspacePaths, settings: FactorySettings,
              report: Any) -> None:
    """Per-tick reconciliation; under ``[program] auto_handoff`` (its external-write grant)."""

    info = report.program.setdefault("site_assignments", {})
    if not settings.program.auto_handoff:
        info["outcome"] = "skipped_auto_handoff_off"
        return
    try:
        result = run_sync(paths, settings, apply=True)
    except SiteAssignmentError as exc:
        info.update(outcome="failed", error=str(exc)[:400])
        return
    changed = list(result.get("changed") or [])
    info.update(
        outcome="ok" if result.get("ok") else "partial",
        checked=len(result.get("papers") or []),
        changed=[{key: entry.get(key) for key in ("paper_id", "action", "target",
                                                  "default_submitter", "reasons")}
                 for entry in changed],
        blocked=[{"paper_id": e.get("paper_id"), "why": e.get("why")}
                 for e in result.get("blocked") or []],
        errors=list(result.get("errors") or [])[:10],
        warnings=list(result.get("warnings") or [])[:5],
    )
    if changed:
        _note_changes(db, paths, settings, changed)


def operator_sync(db: FactoryDB, paths: WorkspacePaths, settings: FactorySettings, *,
                  paper_ids: Iterable[str] = (), apply: bool = False) -> dict[str, Any]:
    result = run_sync(paths, settings, paper_ids=paper_ids, apply=apply)
    if apply and result.get("changed"):
        _note_changes(db, paths, settings, result["changed"])
    return result


def _data_evidence(paths: WorkspacePaths, values: Iterable[str]) -> list[dict[str, str]]:
    items = []
    root = Path(paths.data).resolve()
    for value in values:
        relative = Path(str(value))
        if relative.is_absolute() or ".." in relative.parts:
            raise SiteAssignmentError(f"evidence must be a path inside the data repository: {value}")
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise SiteAssignmentError(f"evidence file missing: {value}")
        items.append({"path": relative.as_posix(),
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return items


def mark_submitted(db: FactoryDB, paths: WorkspacePaths, settings: FactorySettings, *,
                   paper_id: str, journal: str, by: str, reason: str,
                   evidence: Iterable[str] = (), submitted_by: str | None = None,
                   version: str | None = None) -> dict[str, Any]:
    """``ready_queue -> submitted`` for the topic of ``paper_id`` with a written receipt."""

    from .program_autonomy import _ledger

    for name, value in (("paper_id", paper_id), ("journal", journal), ("by", by),
                        ("reason", reason)):
        if not str(value or "").strip():
            raise SiteAssignmentError(f"{name} is required")
    ledger = _ledger(paths, settings)
    topics = ledger.read().get("topics") or []
    matches = [item for item in topics
               if paper_id in {str(item.get("paper_id") or ""),
                               str((item.get("handoff") or {}).get("paper_id") or "")}]
    if len(matches) != 1:
        raise SiteAssignmentError(f"{len(matches)} topics carry paper {paper_id}; expected one")
    topic = matches[0]
    topic_id = str(topic["topic_id"])
    if topic.get("status") == "submitted":
        return {"schema_version": "openlabs.program_mark_submitted.v1", "topic_id": topic_id,
                "paper_id": paper_id, "status": "already_submitted"}
    if topic.get("status") != "ready_queue":
        raise SiteAssignmentError(
            f"topic {topic_id} is {topic.get('status')}; only a ready_queue topic (a delivered "
            "paper) can be marked submitted")
    items = _data_evidence(paths, evidence)
    handoff = dict(topic.get("handoff") or {})
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "schema_version": "openlabs.program_mark_submitted.v1",
        "topic_id": topic_id, "paper_id": paper_id, "journal": journal.strip(),
        "submitted_by": submitted_by, "version": version or handoff.get("version"),
        "package_id": handoff.get("package_id"), "recorded_by": by, "reason": reason,
        "recorded_at": utc_now(), "evidence": items,
    }
    receipt_path = paths.database / "receipts" / "mark-submitted" / f"{paper_id}-{stamp}.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(receipt_path, receipt)
    digest = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    try:
        decision = mark_topic_submitted(
            ledger, topic_id, db=db, decided_by=f"manual:{by}",
            evidence=[*items, {"path": str(receipt_path), "sha256": digest}])
    except TopicLedgerError as exc:
        raise SiteAssignmentError(str(exc)) from exc
    record_topic_note(
        ledger, topic_id, db=db, event_type="submission_registered", reason=reason,
        decided_by=f"manual:{by}",
        detail={"paper_id": paper_id, "journal": journal.strip(), "submitted_by": submitted_by,
                "version": receipt["version"], "receipt": str(receipt_path)},
        key=f"submission_registered:{paper_id}:{journal.strip()}",
    )
    return {"schema_version": "openlabs.program_mark_submitted.v1", "topic_id": topic_id,
            "paper_id": paper_id, "status": "submitted", "receipt": str(receipt_path),
            "receipt_sha256": digest, "changed": bool(getattr(decision, "changed", True)),
            "journal": journal.strip(), "version": receipt["version"]}
