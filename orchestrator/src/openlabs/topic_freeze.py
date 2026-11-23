"""Operator freeze of one topic on a recorded owner decision (2026-11-23).

The owner may decide, after reviewing a paper, that a topic should stop for a scientific
reason (for example ``contribution_insufficient``: the 2026-11-12 freezes and, on
2026-11-23, the PHM bearing topic). ``program freeze-topic`` records that decision through
the same :func:`openlabs.program.freeze_topic` transition the research owner uses
(``active|in_review -> frozen``): the ledger gets the reason class, the hash-bound evidence
(files in the data repository, typically the paper's ``revisions/FREEZE-<date>.md`` and the
assessment it cites) and the reopen conditions; the campaign is frozen, its queued seats are
cancelled and the topic no longer holds a research slot. It refuses while a task of the
campaign is running. Reopening is a new decision (``reopens``/``reopen-grant`` rules), never
an edit of the freeze.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .config import FactorySettings, WorkspacePaths
from .db import FactoryDB
from .program import (
    FREEZE_REASON_CLASSES,
    REOPEN_CONDITION_TYPES,
    TopicLedgerError,
    freeze_topic,
    open_topic_ledger,
)
from .topic_pause import _running_tasks

FREEZABLE = ("active", "in_review")


class TopicFreezeError(ValueError):
    """The topic cannot be frozen by the operator in its current state."""


def _evidence(paths: WorkspacePaths, values: Iterable[str]) -> list[dict[str, str]]:
    items = []
    root = Path(paths.data).resolve()
    for value in values:
        relative = Path(str(value))
        if relative.is_absolute() or ".." in relative.parts:
            raise TopicFreezeError(f"evidence must be a path inside the data repository: {value}")
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise TopicFreezeError(f"evidence file missing: {value}")
        items.append({"path": relative.as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    if not items:
        raise TopicFreezeError("at least one --evidence file is required")
    return items


def _conditions(values: Iterable[str]) -> list[dict[str, str]]:
    result = []
    for value in values:
        kind, _, description = str(value).partition("=")
        if kind.strip() not in REOPEN_CONDITION_TYPES or not description.strip():
            raise TopicFreezeError(
                f"--reopen-condition must be TYPE=description with TYPE in {sorted(REOPEN_CONDITION_TYPES)}")
        result.append({"type": kind.strip(), "description": description.strip()})
    return result


def operator_freeze(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    *,
    topic_id: str,
    reason_class: str,
    evidence: Iterable[str],
    by: str,
    reason: str,
    reopen_conditions: Iterable[str] = (),
) -> dict[str, Any]:
    if not str(by).strip() or not str(reason).strip():
        raise TopicFreezeError("--by and --reason are required")
    if reason_class not in FREEZE_REASON_CLASSES:
        raise TopicFreezeError(f"--reason-class must be one of {sorted(FREEZE_REASON_CLASSES)}")
    ledger = open_topic_ledger(paths, settings.program)
    topic = ledger.topic(topic_id)
    if topic is None:
        raise TopicFreezeError(f"unknown topic {topic_id}")
    status = topic.get("status")
    if status == "frozen":
        return {"schema_version": "openlabs.program_topic_freeze.v1", "topic_id": topic_id,
                "status": "already_frozen", "freeze_reason_class": topic.get("freeze_reason_class")}
    if status not in FREEZABLE:
        raise TopicFreezeError(f"topic {topic_id} is {status!r}; only {FREEZABLE} topics are frozen here")
    items = _evidence(paths, evidence)
    conditions = _conditions(reopen_conditions)
    campaign_id = str(topic.get("campaign_id") or "")
    if campaign_id and db.campaign(campaign_id) is not None:
        running = _running_tasks(db, campaign_id)
        if running:
            raise TopicFreezeError("tasks of this campaign are running (" + ", ".join(running)
                                   + "); freeze after they finish")
    decision = freeze_topic(ledger, topic_id, db=db, reason_class=reason_class, evidence=items,
                            decided_by=f"operator:{by}", reopen_conditions=conditions)
    return {"schema_version": "openlabs.program_topic_freeze.v1", "topic_id": topic_id,
            "status": decision.status, "changed": decision.changed, "from_status": status,
            "freeze_reason_class": reason_class, "reason": reason, "decided_by": f"operator:{by}",
            "evidence": items, "reopen_conditions": conditions,
            "cancelled_tasks": list(decision.cancelled_tasks)}
