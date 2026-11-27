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
import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .config import FactorySettings, WorkspacePaths
from .db import FactoryDB, utc_now
from .program import (
    FREEZE_REASON_CATEGORIES,
    FREEZE_REASON_CLASSES,
    REOPEN_CONDITION_TYPES,
    TopicLedgerError,
    freeze_reason_category,
    freeze_topic,
    open_topic_ledger,
    topics_by_status,
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
                "status": "already_frozen",
                "freeze_reason_class": topic.get("freeze_reason_class"),
                "freeze_reason_category": topic.get("freeze_reason_category")
                or freeze_reason_category(topic.get("freeze_reason_class"))}
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
            "freeze_reason_class": reason_class,
            "freeze_reason_category": freeze_reason_category(reason_class),
            "reason": reason, "decided_by": f"operator:{by}",
            "evidence": items, "reopen_conditions": conditions,
            "cancelled_tasks": list(decision.cancelled_tasks)}


# --------------------------------------------------------------------------- read-only backfill


_RESOURCES_PATTERNS = (
    re.compile(r"compute[_ ]budget[_ ]exhausted|core[- ]hour allocation is exhausted", re.I),
    re.compile(r"provider quota pacing|resource pacing|signal=over|quota exhausted", re.I),
    re.compile(r"review[_ ]rounds[_ ]exhausted|used all (?:four )?rounds", re.I),
    re.compile(r"agent[- ]time budget.*exhausted|budget_exhausted|deadline reached", re.I),
)
_DATA_ACCESS_PATTERNS = (
    re.compile(r"access form|portal form|requires a human recipient|needs_registration", re.I),
    re.compile(r"no verified patient-linkage map|patient grouping cannot be verified", re.I),
    re.compile(r"cannot establish price vintage|historical delivery at commitment", re.I),
    re.compile(r"restricted access|paywall|missing required field", re.I),
)
_NEGATIVE_RESULT_PATTERNS = (
    re.compile(r"primary_endpoint_inconclusive|interval includes zero|spans zero", re.I),
    re.compile(r"rules out the material|below 2%|negligible|primary_endpoint_failed", re.I),
    re.compile(r"contribution_insufficient|no_eligible_venue", re.I),
)
_METHOD_PATTERNS = (
    re.compile(r"feasibility_precheck_failed|shared[_ ]solver|spot[- ]like asymmetry|spot asymmetry", re.I),
    re.compile(r"reproduction (?:miss|tolerance|stop rule|criteria not met)|was not reproduced", re.I),
    re.compile(r"uncalibrated|line capability|precision gate|pseudo-tests", re.I),
    re.compile(r"soc path failures|outside the model's feasible region|common feasible support", re.I),
)


def _read_evidence_payloads(topic: Mapping[str, Any]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for item in topic.get("freeze_evidence") or []:
        if not isinstance(item, Mapping):
            continue
        raw_path = str(item.get("path") or "").strip()
        if raw_path.startswith("file://"):
            raw_path = raw_path[7:]
        if not raw_path or not raw_path.endswith(".json"):
            continue
        path = Path(raw_path)
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            payloads.append(data)
    return payloads


def _clip(text: str, limit: int = 240) -> str:
    compact = " ".join(str(text or "").split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "\u2026"


def classify_historical_freeze(
    topic: Mapping[str, Any],
    *,
    evidence_payloads: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Read-only evidence-backed classification of one historical frozen topic.

    Returns ``{topic_id, research_line, frozen_at, decided_by, recorded_reason_class,
    inferred_in_ledger, declared_reason_class, primary_endpoint_verdict,
    recommended_class, basis, evidence_summary}``. Does not mutate ``topic``.
    """

    payloads = (
        [dict(p) for p in evidence_payloads]
        if evidence_payloads is not None
        else _read_evidence_payloads(topic)
    )
    history = [h for h in (topic.get("history") or []) if isinstance(h, Mapping)]
    inferred = False
    declared: str | None = None
    verdict: str | None = None
    history_texts: list[str] = []
    for entry in history:
        detail = entry.get("detail") if isinstance(entry.get("detail"), Mapping) else {}
        if entry.get("kind") == "topic_freeze_noted":
            if detail.get("reason_class_inferred"):
                inferred = True
            if detail.get("declared_reason_class"):
                declared = str(detail["declared_reason_class"])
            if detail.get("primary_endpoint_verdict"):
                verdict = str(detail["primary_endpoint_verdict"])
        if entry.get("kind") == "direction_decided" or "direction" in str(entry.get("decided_by") or ""):
            for key in ("answers_reason", "rationale"):
                if detail.get(key):
                    history_texts.append(str(detail[key]))
        if entry.get("reason"):
            history_texts.append(str(entry["reason"]))

    owner_declared: str | None = None
    summaries: list[str] = []
    reasons: list[str] = []
    for payload in payloads:
        if payload.get("primary_endpoint_verdict") and not verdict:
            verdict = str(payload["primary_endpoint_verdict"])
        if payload.get("summary"):
            summaries.append(str(payload["summary"]))
        gate = payload.get("gate_result") if isinstance(payload.get("gate_result"), Mapping) else {}
        if gate.get("reason"):
            reasons.append(str(gate["reason"]))
        if gate.get("freeze_reason_class") and not declared:
            declared = str(gate["freeze_reason_class"])
        owner_pkt = (
            payload.get("owner_packet") if isinstance(payload.get("owner_packet"), Mapping) else {}
        )
        owner_gate = (
            owner_pkt.get("gate_result") if isinstance(owner_pkt.get("gate_result"), Mapping) else {}
        )
        if owner_gate.get("freeze_reason_class"):
            owner_declared = str(owner_gate["freeze_reason_class"])
        if owner_pkt.get("reason"):
            reasons.append(str(owner_pkt["reason"]))
        decision = (
            payload.get("direction_decision")
            if isinstance(payload.get("direction_decision"), Mapping)
            else {}
        )
        for key in ("answers_reason", "rationale"):
            if decision.get(key):
                reasons.append(str(decision[key]))

    # Classify from the freeze evidence itself first; fall back to ledger history only
    # when no freeze evidence payload text is available (avoids earlier non-freezing
    # direction decisions overriding the actual freeze cause).
    primary_parts = [
        part for part in (declared or "", owner_declared or "", *reasons, *summaries)
        if part
    ]
    corpus = " | ".join(primary_parts if primary_parts else history_texts)
    evidence_summary = _clip(reasons[0] if reasons else (summaries[0] if summaries else ""))

    recommended = "method_capability"
    basis = "methodological or solver limitation in freeze evidence"

    if any(pat.search(corpus) for pat in _DATA_ACCESS_PATTERNS):
        recommended = "data_access"
        basis = "decisive dataset access gated (form/registration) or missing required field"
    elif any(pat.search(corpus) for pat in _RESOURCES_PATTERNS):
        recommended = "resources_exhausted"
        basis = "compute/agent budget, provider quota pacing, or review-round cap exhausted"
    elif (
        declared == "primary_endpoint_inconclusive"
        or verdict == "failed"
        or any(pat.search(corpus) for pat in _NEGATIVE_RESULT_PATTERNS)
    ):
        recommended = "negative_result"
        basis = "analysis completed with failed, null/inconclusive, or negligible effect"
    elif owner_declared == "feasibility_precheck_failed" or any(
        pat.search(corpus) for pat in _METHOD_PATTERNS
    ):
        recommended = "method_capability"
        basis = "solver/pipeline limitation, control/baseline reproduction miss, or model feasibility limit"
    else:
        mapped = freeze_reason_category(declared or owner_declared or topic.get("freeze_reason_class"))
        if mapped in FREEZE_REASON_CATEGORIES:
            recommended = mapped
            basis = "mapped from recorded freeze_reason_class"

    return {
        "topic_id": str(topic.get("topic_id") or ""),
        "research_line": topic.get("research_line") or topic.get("program_project_id"),
        "frozen_at": topic.get("frozen_at"),
        "decided_by": topic.get("decided_by"),
        "recorded_reason_class": topic.get("freeze_reason_class"),
        "inferred_in_ledger": inferred,
        "declared_reason_class": declared or owner_declared,
        "primary_endpoint_verdict": verdict,
        "recommended_class": recommended,
        "basis": basis,
        "evidence_summary": evidence_summary,
    }


def freeze_backfill_report(
    paths: WorkspacePaths,
    settings: FactorySettings,
    *,
    recorded_reason_class: str = "decisive_data_unavailable",
) -> dict[str, Any]:
    """Read-only backfill report classifying historical freezes into the four classes.

    Never writes or rewrites the topic ledger.
    """

    ledger = open_topic_ledger(paths, settings.program)
    document = ledger.read()
    frozen = topics_by_status(document, "frozen")
    targets = [
        topic for topic in frozen
        if not recorded_reason_class or topic.get("freeze_reason_class") == recorded_reason_class
    ]
    rows = [classify_historical_freeze(topic) for topic in targets]
    rows.sort(key=lambda row: (str(row.get("frozen_at") or ""), row["topic_id"]))
    counts = Counter(row["recommended_class"] for row in rows)
    return {
        "schema_version": "openlabs.freeze_backfill_report.v1",
        "generated_at": utc_now(),
        "read_only": True,
        "ledger": str(ledger.path),
        "filter_recorded_reason_class": recorded_reason_class or None,
        "total_frozen_topics": len(frozen),
        "matched_topics": len(rows),
        "by_recommended_class": {name: counts.get(name, 0) for name in FREEZE_REASON_CATEGORIES},
        "topics": rows,
        "note": (
            "Read-only backfill classification. Topic-ledger history was not rewritten."
        ),
    }
