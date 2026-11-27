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

Operator grants (``program reopen-grant``, 2026-11-20) are the other way out of
``frozen``: a topic frozen while its manuscript was in review, for a procedural reason
(``review_stalled``, ``overdue``: the review loop or the decision allowance ran out, not
the science), gets one more writer revision. It moves ``frozen -> in_review``
(``operator_reopen_granted``), its campaign is reactivated and the manuscript's writer
gets one seat briefed with the freeze record's revision list; the next unified review
and, if it does not pass, the re-freeze are the ordinary flow. Grants are counted
against ``[program].operator_reopen_max``, apart from automatic reopens, and a granted
topic holds no research slot while it is in review on the grant
(``program.grant_slot_exempt``).
"""

from __future__ import annotations

import copy
import hashlib
import json
import operator
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .config import RESEARCH_STAGE, FactorySettings, WorkspacePaths
from .db import FactoryDB, utc_now
from .program import (
    AUTO_REOPEN_REASON,
    OPERATOR_REOPEN_REASON,
    TopicLedger,
    TopicLedgerError,
    find_topic,
    open_topic_ledger,
    parked_program_projects,
    paused_topic_campaigns,
    record_topic_note,
    slot_status,
    topics_by_status,
    transition_topic,
)
from .research_lines import line_entry, read_lines_or_none

CONDITION_KINDS = ("control_receipt", "line_capability")
ROUTING_REOPENED = "owner_reopened"
ROUTING_OPERATOR_REOPEN = "owner_operator_reopen"
# Operator grants (``program reopen-grant``): the only scope, and the freeze classes that
# are procedural (the review loop or the calendar ran out, not the science).
GRANT_SCOPES = ("text_revision",)
GRANTABLE_FREEZE_CLASSES = frozenset({"review_stalled", "overdue"})
SCIENTIFIC_FREEZE_CLASSES = frozenset({
    "data_access", "method_capability", "negative_result",
    "primary_endpoint_failed", "feasibility_precheck_failed", "decisive_data_unavailable",
    "contribution_insufficient",
})
DEFAULT_RECEIPT_KEY = "environment.standard_solver.control_receipt"
# A seat needs at least this much of the campaign's Agent-time budget to be worth starting.
MIN_REMAINING_AGENT_SECONDS = 600
_OPS = {"==": operator.eq, "!=": operator.ne, "<=": operator.le, ">=": operator.ge,
        "<": operator.lt, ">": operator.gt}


class ReopenConditionError(ValueError):
    """A ``reopen_when`` item cannot be evaluated mechanically."""


class ReopenGrantError(ValueError):
    """An operator reopen grant was refused (the message says why)."""


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
    if cap <= 0 or settings.program.stops(RESEARCH_STAGE):
        # Polish mode (2026-11-23): a frozen topic does not return to research.
        return []
    ledger = open_topic_ledger(paths, settings.program)
    document = ledger.read()
    candidates = [
        topic for topic in topics_by_status(document, "frozen")
        if isinstance(topic.get("auto_reopen"), Mapping) and topic["auto_reopen"].get("when")
        # Polish mode with exempt lines: only an exempt line's topics reopen.
        and not settings.program.stops(RESEARCH_STAGE, topic.get("research_line"))
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
        slots = slot_status(current, settings.program, parked, paused_topic_campaigns(db))
        if not slots.can_materialize or not slots.line_can_materialize(
                topic.get("research_line")):
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
    if _last_move_reason(topic) == OPERATOR_REOPEN_REASON:
        return resume_granted_campaign(db, paths, settings, report, topic=topic)
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


def _last_move_reason(topic: Mapping[str, Any]) -> str | None:
    history = topic.get("history") or []
    last = next((entry for entry in reversed(history)
                 if isinstance(entry, Mapping) and entry.get("to")), None)
    return str(last.get("reason")) if last else None


# --------------------------------------------------------------------------- operator grants


def _latest_unified_review(db: FactoryDB, campaign_id: str) -> dict[str, Any] | None:
    """Newest finished unified review (owner_review) of a campaign, with its outcome."""

    from .owner import ROUTING_REVIEW

    with db.connect() as connection:
        row = connection.execute(
            "SELECT * FROM tasks WHERE campaign_id=? AND task_type='paper_review' "
            "AND routing_reason=? AND status='succeeded' ORDER BY created_at DESC, rowid DESC "
            "LIMIT 1", (campaign_id, ROUTING_REVIEW),
        ).fetchone()
    if row is None:
        return None
    task = dict(row)
    outcome: dict[str, Any] = {}
    try:
        payload = json.loads(Path(str(task.get("result_path") or "")).read_text(encoding="utf-8"))
        if isinstance(payload, Mapping) and isinstance(payload.get("review_outcome"), Mapping):
            outcome = dict(payload["review_outcome"])
    except (OSError, ValueError):
        pass
    return {"task_id": str(task["task_id"]), "result_path": task.get("result_path"),
            "outcome": outcome}


def _grant_note(topic: Mapping[str, Any], grant: Mapping[str, Any],
                review: Mapping[str, Any] | None) -> str:
    from .owner import RESPONSE_NAME, REVISION_RULE

    items = [
        f"({number}) [{item.get('type')}] {str(item.get('description') or '').strip()}"
        for number, item in enumerate(topic.get("reopen_conditions") or [], start=1)
        if isinstance(item, Mapping) and str(item.get("description") or "").strip()
    ]
    evidence = ", ".join(str(item.get("path")) for item in topic.get("freeze_evidence") or []
                         if isinstance(item, Mapping))
    outcome = (review or {}).get("outcome") or {}
    last_review = (
        f" Last unified review: {review.get('result_path')} (round "
        f"{outcome.get('rounds_for_target')} of {outcome.get('max_rounds_per_target')}; decision "
        f"record {outcome.get('decision_record') or 'see the result'})." if review else ""
    )
    return (
        f"Operator grant ({grant['by']}, {grant['at']}): \"{grant['reason']}\". This topic was "
        f"frozen in review ({topic.get('freeze_reason_class')}, {topic.get('frozen_at')}) and is "
        "reopened once for a text revision of its manuscript (scope text_revision). The freeze "
        "record lists what the revision must do: "
        + ("; ".join(items) if items else "see the freeze record")
        + f". Freeze record: {evidence or 'see the topic ledger'}.{last_review} Only the "
        "manuscript items are in scope: conditions that need new data, new compute or a new "
        "method are not part of this grant, so do not run new analyses (re-checking quoted "
        "values against their cited sources is part of the revision). The pre-registration, "
        f"endpoint verdict and evidence are unchanged. Answer each item in {RESPONSE_NAME} "
        "(item -> change) and return ready_for_review: the manuscript goes to the next unified "
        "review round; if that round does not pass, the topic is frozen again as usual."
        + REVISION_RULE
    )


def _writer_runner(db: FactoryDB, settings: FactorySettings, campaign_id: str,
                   parent: Mapping[str, Any] | None) -> str | None:
    """The runner that wrote this topic's manuscript: the writer, else the last owner."""

    from . import owner as owner_mode

    writer = owner_mode.active_writer(db, settings, campaign_id)
    if writer:
        return writer
    source = owner_mode.session_seat(db, str(parent["task_id"])) if parent else None
    source = source or owner_mode.last_seat(db, campaign_id)
    runner = str((source or {}).get("runner") or "")
    return runner or None


def resume_granted_campaign(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    report: Any,
    *,
    topic: Mapping[str, Any],
) -> str | None:
    """Reactivate a granted topic's campaign and queue the writer's text_revision seat.

    Idempotent (fixed seat id per grant), so a half-done grant is finished by the tick.
    """

    from . import owner as owner_mode

    grant_block = topic.get("reopen_grant") if isinstance(topic.get("reopen_grant"),
                                                         Mapping) else {}
    grants = list(grant_block.get("grants") or [])
    if not grants:
        return None
    grant = grants[-1]
    count = len(grants)
    campaign_id = str(topic.get("campaign_id") or "")
    db.reopen_frozen_campaign(campaign_id, reason=OPERATOR_REOPEN_REASON,
                              topic_id=str(topic["topic_id"]))
    campaign = db.campaign(campaign_id) or {}
    owner_mode.reset_streak(db, campaign_id, reason="operator_reopen_granted")
    parent = db.latest_task(campaign_id)
    return owner_mode.enqueue_seat(
        db, settings, report, campaign=campaign, parent=parent,
        note=_grant_note(topic, grant, _latest_unified_review(db, campaign_id)),
        routing_reason=ROUTING_OPERATOR_REOPEN,
        task_id=owner_mode.seat_id(campaign_id, f"operator-reopen:{count}"),
        runner_override=_writer_runner(db, settings, campaign_id, parent),
    )


def grant_operator_reopen(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    *,
    topic_id: str,
    reason: str,
    by: str,
    scope: str = "text_revision",
    report: Any = None,
) -> dict[str, Any]:
    """``program reopen-grant``: one more writer revision for a topic frozen in review.

    Accepted only for a topic frozen from ``in_review`` for a procedural reason
    (:data:`GRANTABLE_FREEZE_CLASSES`), in owner mode, with Agent-time budget and a
    unified review round left, below ``[program].operator_reopen_max`` grants (counted
    apart from automatic reopens). The topic moves ``frozen -> in_review``
    (``operator_reopen_granted``) with ``reopen_grant`` {scope, slot_exempt, grants}; it
    holds no research slot while it is in review on the grant
    (``program.grant_slot_exempt``). The campaign is reactivated and the manuscript's
    writer gets one seat whose brief is the freeze record's revision list and this
    grant's reason; the rest (unified review, re-freeze) is the ordinary flow.
    """

    from . import owner as owner_mode

    reason = str(reason or "").strip()
    by = str(by or "").strip()
    if not reason or not by:
        raise ReopenGrantError("--reason and --by are required")
    if scope not in GRANT_SCOPES:
        raise ReopenGrantError(f"scope must be one of {list(GRANT_SCOPES)}")
    limit = int(settings.program.operator_reopen_max)
    if limit <= 0:
        raise ReopenGrantError("operator reopen grants are off ([program] operator_reopen_max = 0)")
    ledger = open_topic_ledger(paths, settings.program)
    document = ledger.read()
    topic = find_topic(document, topic_id)
    if topic is None:
        raise ReopenGrantError(f"unknown topic {topic_id}")
    if topic.get("status") != "frozen":
        raise ReopenGrantError(f"topic {topic_id} is {topic.get('status')}, not frozen")
    reason_class = str(topic.get("freeze_reason_class") or "")
    if reason_class in SCIENTIFIC_FREEZE_CLASSES:
        raise ReopenGrantError(
            f"topic {topic_id} was frozen for a scientific reason ({reason_class}); a text "
            "revision cannot answer it. Reopen it with a new card that declares `reopens`.")
    if reason_class not in GRANTABLE_FREEZE_CLASSES:
        raise ReopenGrantError(
            f"topic {topic_id} was frozen as {reason_class or 'unknown'}, which is not a "
            f"procedural review/deadline exhaustion ({sorted(GRANTABLE_FREEZE_CLASSES)}); "
            "a text-revision grant does not answer it")
    moves = [entry for entry in topic.get("history") or []
             if isinstance(entry, Mapping) and entry.get("to")]
    if not moves or moves[-1].get("to") != "frozen" or moves[-1].get("from") != "in_review":
        raise ReopenGrantError(
            f"topic {topic_id} was not frozen while its manuscript was in review; there is no "
            "manuscript revision to grant")
    if any(other.get("supersedes") == topic_id and other.get("status") != "rejected"
           for other in document.get("topics") or []):
        raise ReopenGrantError(f"topic {topic_id} is superseded by a newer topic")
    if str(topic.get("program_project_id") or "") in parked_program_projects(paths):
        raise ReopenGrantError(f"the program project of topic {topic_id} is paused")
    previous = topic.get("reopen_grant") if isinstance(topic.get("reopen_grant"),
                                                       Mapping) else {}
    done = len(previous.get("grants") or [])
    if done >= limit:
        raise ReopenGrantError(
            f"topic {topic_id} already had {done} operator grant(s); [program] "
            f"operator_reopen_max = {limit}")
    campaign_id = str(topic.get("campaign_id") or "")
    campaign = db.campaign(campaign_id) if campaign_id else None
    if campaign is None:
        raise ReopenGrantError(f"campaign {campaign_id or '?'} of topic {topic_id} is missing")
    if not owner_mode.applies(settings, campaign):
        raise ReopenGrantError(f"topic {topic_id} does not run in owner mode")
    if _campaign_budget_left(campaign) < MIN_REMAINING_AGENT_SECONDS:
        raise ReopenGrantError(f"campaign {campaign_id} has no Agent-time budget left")
    review = _latest_unified_review(db, campaign_id)
    outcome = (review or {}).get("outcome") or {}
    try:
        rounds = int(outcome.get("rounds_for_target"))
        maximum = int(outcome.get("max_rounds_per_target"))
    except (TypeError, ValueError):
        rounds = maximum = None
    if rounds is not None and maximum is not None and rounds >= maximum:
        raise ReopenGrantError(
            f"the last unified review was round {rounds} of {maximum} for its target: no "
            "review round is left, so a revision could not be reviewed")
    decided_by = f"operator:{by}"
    grant = {"at": utc_now(), "by": by, "reason": reason[:600], "scope": scope,
             "freeze_reason_class": reason_class, "frozen_at": topic.get("frozen_at")}
    block = {**copy.deepcopy(dict(previous)), "scope": scope, "slot_exempt": True,
             "grants": [*list(previous.get("grants") or []), grant]}
    decision = transition_topic(
        ledger, topic_id, "in_review", db=db, reason=OPERATOR_REOPEN_REASON,
        decided_by=decided_by, evidence=topic.get("freeze_evidence") or [],
        updates={"reopen_grant": block},
    )
    current = ledger.topic(topic_id) or {}
    seat = resume_granted_campaign(db, paths, settings, report, topic=current)
    record_topic_note(
        ledger, topic_id, db=db, event_type="operator_reopen_granted",
        reason=OPERATOR_REOPEN_REASON, decided_by=decided_by,
        detail={"by": by, "reason": reason[:600], "scope": scope, "count": done + 1,
                "max": limit, "seat": seat, "slot_exempt": True},
        key=f"operator_reopen:{topic_id}:{done + 1}",
    )
    return {"schema_version": "openlabs.program_reopen_grant.v1", "topic_id": topic_id,
            "status": decision.status, "changed": decision.changed,
            "campaign_id": campaign_id, "seat": seat, "grant": grant,
            "grants_used": done + 1, "operator_reopen_max": limit}


def repair_half_done_reopens(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    report: Any,
) -> list[str]:
    """Finish a reopen whose ledger move happened but whose campaign is still frozen."""

    repaired: list[str] = []
    ledger = open_topic_ledger(paths, settings.program)
    for topic in topics_by_status(ledger.read(), "active", "in_review"):
        expected = (AUTO_REOPEN_REASON if topic.get("status") == "active"
                    else OPERATOR_REOPEN_REASON)
        if _last_move_reason(topic) != expected:
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
    "GRANTABLE_FREEZE_CLASSES",
    "ROUTING_OPERATOR_REOPEN",
    "ROUTING_REOPENED",
    "ReopenConditionError",
    "ReopenGrantError",
    "auto_reopen_block",
    "check_report",
    "evaluate",
    "grant_operator_reopen",
    "normalize_conditions",
    "register_auto_reopen",
    "reopen_ready_topics",
    "repair_half_done_reopens",
    "resume_granted_campaign",
]


def request_delivered_revision(db, paths, settings, topic_id, package_id, reason, by, target_zone=None, *, journal_event_key=None):
    """Bind the request to one delivered package. The tick owns slot allocation."""
    from . import owner
    from .program_reconcile import delivery_receipts

    ledger = open_topic_ledger(paths, settings.program)
    topic = ledger.topic(topic_id) or {}
    handoff = topic.get("handoff") or {}
    journal_revision = bool(journal_event_key and any(
        item.get("kind") == "journal_correspondence" and item.get("reason") == "revision_requested"
        and item.get("event_key") == "mail:" + journal_event_key for item in topic.get("history", [])
    ))
    prior = topic.get("delivered_revision") or {}
    if not all(str(x).strip() for x in (package_id, reason, by)):
        raise ReopenGrantError("package, reason and operator are required")
    if prior.get("package_id") == package_id:
        if prior["reason"] != reason or prior["by"] != by or prior.get("target_zone") != target_zone:
            raise ReopenGrantError("this package already has a different revision request")
        return prior
    campaign = db.campaign(str(topic.get("campaign_id") or "")) or {}
    receipts = delivery_receipts(paths, str(topic.get("paper_id") or ""))
    if (topic.get("status") != "ready_queue" or handoff.get("status") != "delivered"
            or (handoff.get("submission_handler") and not journal_revision) or handoff.get("package_id") != package_id
            or not receipts or receipts[-1]["package_id"] != package_id
            or campaign.get("status") != "production_paused" or not owner.applies(settings, campaign)):
        raise ReopenGrantError("expected a delivered owner topic with matching latest receipt and no handler")
    request = {"package_id": package_id, "version": receipts[-1]["version"], "reason": reason,
               "by": by, "target_zone": target_zone, "requested_at": utc_now()}
    if journal_revision:
        request["journal_event_key"] = journal_event_key
    record_topic_note(ledger, topic_id, db=db, event_type="delivered_revision_requested",
                      reason="operator_request", decided_by=f"operator:{by}", detail=request,
                      updates={"delivered_revision": request}, key=f"revise:{package_id}")
    saved = ledger.topic(topic_id)["delivered_revision"]
    if any(saved.get(key) != request[key] for key in ("by", "reason", "target_zone")):
        raise ReopenGrantError("this package already has a different revision request")
    return saved


def advance_delivered_revisions(db, paths, settings, report):
    """Allocate a normal research slot, recover a paused campaign and enqueue one owner."""
    from . import owner

    ledger = open_topic_ledger(paths, settings.program)
    outcomes = []
    for topic in topics_by_status(ledger.read(), "ready_queue", "active"):
        request = topic.get("delivered_revision") or {}
        if not request:
            continue
        campaign_id = topic["campaign_id"]
        task_id = owner.seat_id(campaign_id, "revision:" + request["package_id"])
        if db.task(task_id):
            continue
        campaign = db.campaign(campaign_id) or {}
        if topic["status"] == "ready_queue":
            handoff = topic.get("handoff") or {}
            if (handoff.get("status") != "delivered" or (handoff.get("submission_handler") and not request.get("journal_event_key"))
                    or handoff.get("package_id") != request["package_id"]):
                continue
            slots = slot_status(ledger.read(), settings.program, parked_program_projects(paths),
                                paused_topic_campaigns(db))
            if (not slots.can_materialize or not slots.line_can_materialize(topic.get("research_line"))
                    or _campaign_budget_left(campaign) < MIN_REMAINING_AGENT_SECONDS):
                outcomes.append({"topic_id": topic["topic_id"], "status": "waiting_for_capacity"})
                continue
            transition_topic(ledger, topic["topic_id"], "active", db=db,
                             reason="delivered_revision_requested", decided_by="operator:" + request["by"],
                             updates={"handoff": {**handoff, "status": "under_revision"}})
        elif _last_move_reason(topic) != "delivered_revision_requested":
            continue
        db.resume_paused_campaign(campaign_id, reason="delivered_revision_requested")
        owner.reset_review_cycle(db, campaign_id, reason="supplementary research")

        note = (f"Revise existing paper {topic['paper_id']}, delivered version {request['version']}. "
                f"In the writable campaign workspace, bring in the delivered registry record, paper and "
                f"review history for this paper from {paths.data} before starting the revision. "
                "Retain the delivery block and published Zenodo identity for the release pipeline. "
                "Begin paper start-revision once against that baseline before edits. "
                "Preserve preregistration, primary evidence and review history. Label new analyses exploratory. "
                "Return ready_for_review through the normal unified review and release workflow. "
                + request["reason"])
        owner.enqueue_seat(db, settings, report, campaign=campaign, parent=db.latest_task(campaign_id),
                           note=note, routing_reason=ROUTING_REOPENED, task_id=task_id)
        outcomes.append({"topic_id": topic["topic_id"], "task_id": task_id})
    return outcomes
