"""Automatic reopening of frozen topics whose freeze reason was a line-level fact.

A topic frozen because of something shared by its whole research line - the line's
control solution did not (yet) meet the topic's pre-registered control criterion, or
the line's shared solver lacked a capability the pre-registered analysis needs -
can continue unchanged once that fact changes. Its pre-registration is not touched:
the reopened owner re-applies the same registered criteria to the new line state.

A frozen topic opts in with ``auto_reopen`` in the topic ledger::

    {"when": [<condition>, ...],     # all must hold
     "max_reopens": 1,               # capped by [program].auto_reopen_max
     "registered": [{"at", "by", "note"}],
     "reopens": [{"at", "conditions", "evidence", "seat"}]}

written either from the owner's freeze packet (``reopen_when``, see the owner
brief) or by ``program reopen-register`` for topics frozen before this existed.
Conditions are deliberately two simple, mechanically evaluated kinds (no rule
language):

``control_receipt``
    ``{"kind": "control_receipt", "receipt": PATH (default: the topic line's
    environment.standard_solver.control_receipt), "checks": [[field, op, value], ...]}``.
    ``field`` is a dotted path into the receipt JSON; ``summary.<...>`` reads the
    receipt's ``results_dir/outputs/<tag>/summary.json``. ``op`` is one of
    ``== != <= >= < >``; a list value is reduced to its maximum for ``<=``/``<`` and
    to its minimum for ``>=``/``>`` (e.g. per-parameter R-hat). A missing field fails.

``line_capability``
    ``{"kind": "line_capability", "line": LINE (default: the topic's line), "key":
    "environment.standard_solver.spot_config"}``: the dotted key in the line's entry of
    registry/research-lines.yaml is present and truthy (a mapping must not say
    ``validated: false``); optional ``"equals": VALUE``.

Each tick (``run_program_pipeline``) the control plane evaluates the frozen topics
that carry conditions. When all hold, a slot is free (the ordinary research-slot
rule), the campaign still has Agent-time budget, the topic runs in owner mode and
its reopen count is below the cap, it moves the topic ``frozen -> active``
(guarded reason ``auto_reopen_conditions_met``), reactivates the campaign and
queues one owner seat in the same session saying which conditions changed. Nothing
else is relaxed: budgets, slots, the stop rule and the pre-registered endpoint are
those of the original topic.
"""

from __future__ import annotations

import copy
import hashlib
import json
import operator
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .config import FactorySettings, WorkspacePaths
from .db import FactoryDB, utc_now
from .program import (
    AUTO_REOPEN_REASON,
    TopicLedger,
    TopicLedgerError,
    find_topic,
    open_topic_ledger,
    parked_program_projects,
    slot_status,
    topics_by_status,
    transition_topic,
)
from .research_lines import line_entry, read_lines_or_none

CONDITION_KINDS = ("control_receipt", "line_capability")
ROUTING_REOPENED = "owner_reopened"
DEFAULT_RECEIPT_KEY = "environment.standard_solver.control_receipt"
# A seat needs at least this much of the campaign's Agent-time budget to be worth starting.
MIN_REMAINING_AGENT_SECONDS = 600
_OPS = {"==": operator.eq, "!=": operator.ne, "<=": operator.le, ">=": operator.ge,
        "<": operator.lt, ">": operator.gt}


class ReopenConditionError(ValueError):
    """A ``reopen_when`` item cannot be evaluated mechanically."""


# --------------------------------------------------------------------------- conditions


def normalize_conditions(value: Any) -> list[dict[str, Any]]:
    """Validated copy of a ``reopen_when`` list; raises on anything not evaluable."""

    if value in (None, ""):
        return []
    if isinstance(value, Mapping):
        value = [value]
    if not isinstance(value, list):
        raise ReopenConditionError("reopen_when must be a list of conditions")
    result: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise ReopenConditionError(f"reopen_when[{index}] must be an object")
        kind = str(item.get("kind") or "").strip()
        if kind not in CONDITION_KINDS:
            raise ReopenConditionError(
                f"reopen_when[{index}].kind must be one of {list(CONDITION_KINDS)}")
        clean: dict[str, Any] = {"kind": kind}
        if item.get("description"):
            clean["description"] = str(item["description"]).strip()[:600]
        if kind == "control_receipt":
            if item.get("receipt"):
                clean["receipt"] = str(item["receipt"]).strip()
            checks = item.get("checks")
            if not isinstance(checks, list) or not checks:
                raise ReopenConditionError(f"reopen_when[{index}].checks must be a non-empty list")
            clean_checks = []
            for number, check in enumerate(checks):
                if not (isinstance(check, (list, tuple)) and len(check) == 3):
                    raise ReopenConditionError(
                        f"reopen_when[{index}].checks[{number}] must be [field, op, value]")
                field, op, expected = check
                if not isinstance(field, str) or not field.strip() or op not in _OPS:
                    raise ReopenConditionError(
                        f"reopen_when[{index}].checks[{number}]: field must be a dotted path, "
                        f"op one of {sorted(_OPS)}")
                if isinstance(expected, (dict, list)):
                    raise ReopenConditionError(
                        f"reopen_when[{index}].checks[{number}]: value must be a scalar")
                clean_checks.append([field.strip(), op, expected])
            clean["checks"] = clean_checks
        else:
            key = str(item.get("key") or "").strip()
            if not key:
                raise ReopenConditionError(f"reopen_when[{index}].key is required")
            clean["key"] = key
            if item.get("line"):
                clean["line"] = str(item["line"]).strip()
            if "equals" in item:
                if isinstance(item["equals"], (dict, list)):
                    raise ReopenConditionError(f"reopen_when[{index}].equals must be a scalar")
                clean["equals"] = item["equals"]
        result.append(clean)
    return result


def _dotted(document: Any, path: str) -> tuple[bool, Any]:
    current = document
    for part in path.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return False, None
    return True, current


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _compare(actual: Any, op: str, expected: Any) -> bool:
    if isinstance(actual, list):
        numbers = [item for item in actual if isinstance(item, (int, float))
                   and not isinstance(item, bool)]
        if not numbers or len(numbers) != len(actual):
            return False
        actual = max(numbers) if op in {"<=", "<"} else min(numbers) if op in {">=", ">"} else actual
    try:
        return bool(_OPS[op](actual, expected))
    except TypeError:
        return False


def _receipt_document(path: Path) -> dict[str, Any]:
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(receipt, dict):
        raise ValueError("receipt is not a JSON object")
    document = dict(receipt)
    results = str(receipt.get("results_dir") or "").strip()
    tag = str(receipt.get("tag") or "").strip()
    if results and tag:
        summary = Path(results) / "outputs" / tag / "summary.json"
        if summary.is_file():
            document["summary"] = json.loads(summary.read_text(encoding="utf-8"))
    return document


def evaluate_condition(
    condition: Mapping[str, Any],
    *,
    topic: Mapping[str, Any],
    lines_document: Mapping[str, Any] | None,
    lines_path: Path | None,
) -> dict[str, Any]:
    """``{"met": bool, "detail": str, "evidence": {path, sha256} | None}`` for one condition."""

    kind = condition.get("kind")
    line = str(condition.get("line") or topic.get("research_line") or "")
    entry = line_entry(lines_document, line) if lines_document and line else None
    if kind == "line_capability":
        if entry is None:
            return {"met": False, "detail": f"line {line or '?'} not in research-lines", "evidence": None}
        present, value = _dotted(entry, str(condition["key"]))
        if "equals" in condition:
            met = present and value == condition["equals"]
        else:
            met = present and bool(value) and not (
                isinstance(value, Mapping) and value.get("validated") is False)
        sha = _sha256(lines_path) if lines_path else None
        return {"met": bool(met),
                "detail": f"{line}:{condition['key']} = {json.dumps(value, default=str)[:200]}"
                if present else f"{line}:{condition['key']} absent",
                "evidence": {"path": str(lines_path), "sha256": sha} if met and sha else None}
    if kind == "control_receipt":
        receipt = str(condition.get("receipt") or "")
        if not receipt and entry is not None:
            present, value = _dotted(entry, DEFAULT_RECEIPT_KEY)
            receipt = str(value or "") if present else ""
        if not receipt:
            return {"met": False, "detail": "no control receipt path", "evidence": None}
        path = Path(receipt)
        try:
            document = _receipt_document(path)
        except (OSError, ValueError) as exc:
            return {"met": False, "detail": f"receipt unreadable: {exc}", "evidence": None}
        failed = []
        for field, op, expected in condition["checks"]:
            present, actual = _dotted(document, field)
            if not present or not _compare(actual, op, expected):
                shown = json.dumps(actual, default=str)[:80] if present else "missing"
                failed.append(f"{field} {op} {expected} (is {shown})")
        sha = _sha256(path)
        detail = (f"{path.name} job {document.get('job_id')}: "
                  + ("all checks pass" if not failed else "fails " + "; ".join(failed)))
        return {"met": not failed, "detail": detail,
                "evidence": {"path": str(path), "sha256": sha} if not failed and sha else None}
    return {"met": False, "detail": f"unknown kind {kind!r}", "evidence": None}


def evaluate(
    topic: Mapping[str, Any],
    *,
    lines_document: Mapping[str, Any] | None,
    lines_path: Path | None,
) -> list[dict[str, Any]]:
    block = topic.get("auto_reopen") if isinstance(topic.get("auto_reopen"), Mapping) else {}
    return [
        {"condition": dict(item), **evaluate_condition(
            item, topic=topic, lines_document=lines_document, lines_path=lines_path)}
        for item in block.get("when") or [] if isinstance(item, Mapping)
    ]


# --------------------------------------------------------------------------- registration


def auto_reopen_block(
    conditions: Iterable[Mapping[str, Any]],
    *,
    decided_by: str,
    note: str = "",
    max_reopens: int = 1,
    previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The ledger's ``auto_reopen`` value; keeps the reopen history of ``previous``."""

    block = copy.deepcopy(dict(previous or {}))
    block["when"] = normalize_conditions(list(conditions))
    block["max_reopens"] = max(0, int(max_reopens))
    block.setdefault("reopens", [])
    block.setdefault("registered", []).append(
        {"at": utc_now(), "by": decided_by, **({"note": note[:600]} if note else {})})
    return block


def register_auto_reopen(
    ledger: TopicLedger,
    topic_id: str,
    conditions: Iterable[Mapping[str, Any]],
    *,
    decided_by: str,
    note: str = "",
    max_reopens: int = 1,
) -> dict[str, Any]:
    """Attach (or replace) the reopen conditions of a frozen topic. Ledger only.

    Writes the topic's ``auto_reopen`` and one history note; nothing in the factory
    database changes (the reopen itself records its events when it happens).
    """

    if not decided_by:
        raise TopicLedgerError("decided_by is required")
    with ledger.transaction() as document:
        topic = find_topic(document, topic_id)
        if topic is None:
            raise TopicLedgerError(f"unknown topic {topic_id}")
        if topic.get("status") != "frozen":
            raise TopicLedgerError(f"topic {topic_id} is {topic.get('status')}, not frozen")
        block = auto_reopen_block(conditions, decided_by=decided_by, note=note,
                                  max_reopens=max_reopens, previous=topic.get("auto_reopen"))
        topic["auto_reopen"] = block
        topic.setdefault("history", []).append({
            "at": utc_now(), "status": "frozen", "kind": "auto_reopen_registered",
            "reason": "auto_reopen_registered", "decided_by": decided_by,
            "detail": {"when": block["when"], "max_reopens": block["max_reopens"],
                       **({"note": note[:600]} if note else {})},
            "evidence": [],
        })
        return copy.deepcopy(block)


# --------------------------------------------------------------------------- the tick


def _note(topic: Mapping[str, Any], results: list[dict[str, Any]], count: int) -> str:
    changed = "; ".join(
        f"[{item['condition']['kind']}] {item['condition'].get('description') or ''} "
        f"-> {item['detail']}".replace("  ", " ")
        for item in results
    )
    return (
        "This topic was frozen for a research-line fact that has now changed, so the control "
        f"plane reopened it (automatic reopen {count}). Conditions now met: {changed}. "
        "Your pre-registration, primary endpoint, stop rule and budget are unchanged: re-read "
        "the freeze in your work log, re-apply exactly the criterion that failed (as "
        "registered) to the new line state, and continue the precheck from there. If the "
        "registered criterion still fails, or the change does not answer the freeze, end the "
        "seat frozen again with the evidence; do not widen tolerances or rewrite the endpoint."
    )


def _campaign_budget_left(campaign: Mapping[str, Any]) -> float:
    maximum = float(campaign.get("max_agent_seconds") or 0)
    used = float(campaign.get("agent_seconds_used") or 0)
    return maximum - used if maximum > 0 else float("inf")


def reopen_ready_topics(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    report: Any,
) -> list[dict[str, Any]]:
    """Reopen frozen topics whose ``auto_reopen`` conditions all hold (one tick)."""

    from . import owner as owner_mode

    cap = int(settings.program.auto_reopen_max)
    if cap <= 0:
        return []
    ledger = open_topic_ledger(paths, settings.program)
    document = ledger.read()
    candidates = [
        topic for topic in topics_by_status(document, "frozen")
        if isinstance(topic.get("auto_reopen"), Mapping) and topic["auto_reopen"].get("when")
    ]
    outcomes: list[dict[str, Any]] = []
    if not candidates:
        return outcomes
    lines_path = paths.data / settings.program.research_lines_path
    lines_document = read_lines_or_none(lines_path)
    parked = parked_program_projects(paths)
    for topic in candidates:
        topic_id = str(topic["topic_id"])
        block = topic["auto_reopen"]
        done = len(block.get("reopens") or [])
        limit = min(cap, int(block.get("max_reopens", 1) or 0))
        outcome: dict[str, Any] = {"topic_id": topic_id}
        if done >= limit:
            outcomes.append({**outcome, "outcome": "reopen_limit_reached", "reopens": done})
            continue
        if any(other.get("supersedes") == topic_id and other.get("status") != "rejected"
               for other in document.get("topics") or []):
            outcomes.append({**outcome, "outcome": "superseded"})
            continue
        if str(topic.get("program_project_id") or "") in parked:
            outcomes.append({**outcome, "outcome": "project_parked"})
            continue
        results = evaluate(topic, lines_document=lines_document, lines_path=lines_path)
        unmet = [item["detail"] for item in results if not item["met"]]
        if unmet:
            outcomes.append({**outcome, "outcome": "conditions_unmet", "unmet": unmet})
            continue
        campaign_id = str(topic.get("campaign_id") or "")
        campaign = db.campaign(campaign_id) if campaign_id else None
        if campaign is None:
            outcomes.append({**outcome, "outcome": "campaign_missing"})
            continue
        if not owner_mode.applies(settings, campaign):
            outcomes.append({**outcome, "outcome": "not_owner_mode"})
            continue
        if _campaign_budget_left(campaign) < MIN_REMAINING_AGENT_SECONDS:
            outcomes.append({**outcome, "outcome": "budget_exhausted"})
            continue
        current = ledger.read()
        if not slot_status(current, settings.program, parked).can_materialize:
            outcomes.append({**outcome, "outcome": "waiting_for_slot"})
            continue
        evidence = [item["evidence"] for item in results if item.get("evidence")]
        record = {"at": utc_now(), "count": done + 1,
                  "conditions": [{"kind": item["condition"]["kind"], "detail": item["detail"]}
                                 for item in results],
                  "evidence": evidence}
        new_block = copy.deepcopy(dict(block))
        new_block["reopens"] = [*list(block.get("reopens") or []), record]
        decision = transition_topic(
            ledger, topic_id, "active", db=db, reason=AUTO_REOPEN_REASON,
            decided_by=f"program:auto-reopen:{done + 1}", evidence=evidence,
            updates={"auto_reopen": new_block},
        )
        if not decision.changed:
            outcomes.append({**outcome, "outcome": "already_reopened"})
            continue
        seat = resume_reopened_campaign(db, paths, settings, report, topic_id=topic_id,
                                        results=results, count=done + 1)
        outcomes.append({**outcome, "outcome": "reopened", "count": done + 1,
                         "campaign_id": campaign_id, "seat": seat})
    return outcomes


def resume_reopened_campaign(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    report: Any,
    *,
    topic_id: str,
    results: list[dict[str, Any]] | None = None,
    count: int | None = None,
) -> str | None:
    """Reactivate the campaign of a reopened topic and queue its owner's seat (idempotent)."""

    from . import owner as owner_mode

    ledger = open_topic_ledger(paths, settings.program)
    topic = ledger.topic(topic_id) or {}
    block = topic.get("auto_reopen") if isinstance(topic.get("auto_reopen"), Mapping) else {}
    reopens = list(block.get("reopens") or [])
    if count is None:
        count = len(reopens)
    if results is None:
        last = reopens[-1] if reopens else {}
        results = [{"condition": {"kind": item.get("kind")}, "detail": item.get("detail")}
                   for item in last.get("conditions") or []]
    campaign_id = str(topic.get("campaign_id") or "")
    db.reopen_frozen_campaign(campaign_id, reason=AUTO_REOPEN_REASON, topic_id=topic_id)
    campaign = db.campaign(campaign_id) or {}
    latest = db.latest_task(campaign_id)
    seat = owner_mode.enqueue_seat(
        db, settings, report, campaign=campaign, parent=latest,
        note=_note(topic, results, count), routing_reason=ROUTING_REOPENED,
        task_id=owner_mode.seat_id(campaign_id, f"reopen:{count}"),
    )
    return seat


def repair_half_done_reopens(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    report: Any,
) -> list[str]:
    """Finish a reopen whose ledger move happened but whose campaign is still frozen."""

    repaired: list[str] = []
    ledger = open_topic_ledger(paths, settings.program)
    for topic in topics_by_status(ledger.read(), "active"):
        history = topic.get("history") or []
        last_move = next((entry for entry in reversed(history) if entry.get("to")), None)
        if not last_move or last_move.get("reason") != AUTO_REOPEN_REASON:
            continue
        campaign = db.campaign(str(topic.get("campaign_id") or "")) or {}
        if str(campaign.get("status") or "") != "frozen":
            continue
        resume_reopened_campaign(db, paths, settings, report, topic_id=str(topic["topic_id"]))
        repaired.append(str(topic["topic_id"]))
    return repaired


def check_report(paths: WorkspacePaths, settings: FactorySettings) -> dict[str, Any]:
    """Read-only evaluation of every frozen topic's conditions (``program reopen-check``)."""

    ledger = open_topic_ledger(paths, settings.program)
    lines_path = paths.data / settings.program.research_lines_path
    lines_document = read_lines_or_none(lines_path)
    rows = []
    for topic in topics_by_status(ledger.read(), "frozen"):
        block = topic.get("auto_reopen") if isinstance(topic.get("auto_reopen"), Mapping) else None
        if not block:
            continue
        results = evaluate(topic, lines_document=lines_document, lines_path=lines_path)
        rows.append({
            "topic_id": topic["topic_id"], "freeze_reason_class": topic.get("freeze_reason_class"),
            "reopens": len(block.get("reopens") or []), "max_reopens": block.get("max_reopens"),
            "all_met": bool(results) and all(item["met"] for item in results),
            "conditions": [{"kind": item["condition"]["kind"], "met": item["met"],
                            "detail": item["detail"]} for item in results],
        })
    return {"schema_version": "openlabs.program_reopen_check.v1", "ledger": str(ledger.path),
            "auto_reopen_max": settings.program.auto_reopen_max, "topics": rows}


__all__ = [
    "CONDITION_KINDS",
    "ROUTING_REOPENED",
    "ReopenConditionError",
    "auto_reopen_block",
    "check_report",
    "evaluate",
    "normalize_conditions",
    "register_auto_reopen",
    "reopen_ready_topics",
    "repair_half_done_reopens",
]
