"""Research-program back half: mid-research stop rules, direction decisions and delivery.

Deterministic routing and bookkeeping only. Whether a result failed, which
direction a topic takes after a negative signal and whether a manuscript is
ready are judged by agents; this module

* holds research results of an admitted topic to the pre-registration recorded
  in the topic ledger and acts on the primary-endpoint verdict,
* freezes a topic whose research agent returned an audited freeze,
* watches the calendar limit and the per-topic Agent-time budget,
* turns structured review signals (``review_outcome``) into a
  ``direction_decision`` task for an independent lead-tier reviewer, applies its
  choice through the existing task paths and enforces the per-topic choice
  limits,
* queues review-ready papers, releases their slots and (optionally) delivers
  them to the paper-management site without a submission handler.

Direction decisions run in a small per-domain control campaign
(``<domain>-program-direction``): their Agent time is governance overhead like
the admission gate's and is not charged to the topic budget, so a decision can
still run after a topic exhausted its budget. Every automatic decision writes an
``events`` row and a topic-ledger history entry.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import budget as budget_control
from .config import FactorySettings, WorkspacePaths
from .contracts import (
    FREEZE_REASON_CLASSES,
    REOPEN_BASIS_TYPES,
    atomic_write_json,
    canonical_json_bytes,
    sha256_file,
    validate_direction_decision,
    validate_review_outcome,
)
from .db import FactoryDB, utc_now
from .program import (
    FREEZABLE_STATUSES,
    TopicLedger,
    TopicLedgerError,
    find_topic,
    freeze_topic,
    mark_topic_in_review,
    mark_topic_ready,
    open_topic_ledger,
    record_topic_note,
    topic_for_campaign,
    topics_by_status,
)
from .projects import workstream_policy
from .resources import default_task_resources

DIRECTION_TASK_TYPE = "direction_decision"
DIRECTION_SKILL = "openlabs-direction-decision"
DIRECTION_PACKET_SCHEMA = "openlabs.direction_decision_packet.v1"
DIRECTION_ROUTING_REASON = "direction_decision"
TARGETED_ROUTING = "direction_targeted_analysis"
RETARGET_ROUTING = "direction_retarget"
CHOICE_ROUTING = {
    "targeted_core_analysis": TARGETED_ROUTING,
    "retarget_or_short_format": RETARGET_ROUTING,
}
# Triggers. Calendar and budget triggers fire once per topic; review and
# endpoint triggers fire once per source result.
TRIGGER_ENDPOINT_FAILED = "primary_endpoint_failed"
TRIGGER_OVERDUE = "overdue"
TRIGGER_BUDGET = "budget_exhausted"
TRIGGER_REVIEW_DIRECTION = "review_direction_decision"
TRIGGER_REVIEW_RETARGET = "review_retarget_required"
TRIGGER_REVIEW_STALLED = "review_stalled"
TRIGGER_REVIEW_ROUNDS = "review_rounds_exhausted"
ONCE_PER_TOPIC_TRIGGERS = frozenset({TRIGGER_OVERDUE, TRIGGER_BUDGET})
TRIGGER_FREEZE_CLASS = {
    TRIGGER_ENDPOINT_FAILED: "primary_endpoint_failed",
    TRIGGER_OVERDUE: "overdue",
    TRIGGER_BUDGET: "budget_exhausted",
    TRIGGER_REVIEW_STALLED: "review_stalled",
    TRIGGER_REVIEW_ROUNDS: "review_stalled",
}
CHOICE_FREEZE_CLASS = {
    "targeted_core_analysis": "contribution_insufficient",
    "retarget_or_short_format": "no_eligible_venue",
    "freeze": "contribution_insufficient",
}
# A decision task that fails or returns an unusable decision is retried once
# with a fresh task; then the topic is frozen conservatively.
MAX_DECISION_ATTEMPTS = 2
DECISION_META_PREFIX = "program_direction:"
TRIGGER_META_PREFIX = "program_trigger:"
IN_FLIGHT = ("queued", "leased", "running")
DECISION_FAILED_STATUSES = ("failed", "needs_human", "needs_replan", "quarantined", "cancelled")
RESEARCH_ROLES = frozenset({"researcher", "experimenter"})
EVIDENCE_REMEDIATION_ROUTINGS = frozenset({"review_evidence_remediation", TARGETED_ROUTING})
HELD_STATUSES = ("ready_queue", "submitted")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class DeliveryError(RuntimeError):
    """The paper-writing delivery command failed."""


# --------------------------------------------------------------------------- helpers


def _now() -> datetime:
    return budget_control.current_time()


def _control_root(paths: WorkspacePaths) -> Path:
    return paths.artifacts / "program-control"


def _token(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in value).strip("-._")
    return cleaned or "topic"


def _digest(*parts: Any) -> str:
    return hashlib.sha256("\0".join(str(part) for part in parts).encode()).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected an object: {path}")
    return value


def _evidence(path: Path, sha256: str | None = None) -> dict[str, str]:
    return {"path": str(path), "sha256": sha256 or sha256_file(path)}


def _write_evidence(paths: WorkspacePaths, topic_id: str, kind: str,
                    payload: Mapping[str, Any]) -> dict[str, str]:
    """Hash-bound control-plane evidence for a freeze or trigger without an agent result."""

    body = {"schema_version": "openlabs.program_evidence.v1", "topic_id": topic_id,
            "kind": kind, **dict(payload)}
    digest = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    path = _control_root(paths) / "evidence" / _token(topic_id) / f"{kind}-{digest[:16]}.json"
    if not path.is_file():
        atomic_write_json(path, body)
    return _evidence(path)


def _signed(packet: dict[str, Any]) -> dict[str, Any]:
    packet["content_sha256"] = hashlib.sha256(canonical_json_bytes(packet)).hexdigest()
    return packet


def _verified_packet(path: Path) -> dict[str, Any]:
    packet = _read_object(path)
    claimed = packet.pop("content_sha256", None)
    if packet.get("schema_version") != DIRECTION_PACKET_SCHEMA or claimed != hashlib.sha256(
        canonical_json_bytes(packet)
    ).hexdigest():
        raise ValueError(f"direction packet {path} is not an intact control-plane packet")
    packet["content_sha256"] = claimed
    return packet


def _info(report: Any, key: str) -> list[Any]:
    return report.program.setdefault(key, [])


def _ledger(paths: WorkspacePaths, settings: FactorySettings) -> TopicLedger:
    return open_topic_ledger(paths, settings.program)


def campaign_topic(
    paths: WorkspacePaths,
    settings: FactorySettings,
    campaign_id: str,
) -> dict[str, Any] | None:
    """The ledger topic that owns a research campaign (program enabled only)."""

    if not settings.program.enabled:
        return None
    return topic_for_campaign(_ledger(paths, settings).read(), campaign_id)


def topic_budget_seconds(cost_estimate: Any, settings: FactorySettings) -> int:
    """Smaller of the card's ``cost_estimate.agent_seconds`` and the configured ceiling."""

    cap = int(settings.program.topic_max_agent_seconds)
    estimate = cost_estimate.get("agent_seconds") if isinstance(cost_estimate, Mapping) else None
    if isinstance(estimate, (int, float)) and not isinstance(estimate, bool) and estimate >= 1:
        return max(1, min(cap, int(estimate)))
    return cap


def _routine_names(topic: Mapping[str, Any]) -> list[str]:
    names: list[str] = []
    for item in topic.get("routine_fallback") or []:
        name = item.get("name") if isinstance(item, Mapping) else item
        if str(name or "").strip():
            names.append(str(name).strip())
    return names


def _usage(db: FactoryDB, campaign_id: str) -> dict[str, int]:
    usage = db.campaign_routing_usage(campaign_id)
    return {
        choice: int((usage.get(reason) or {}).get("task_count") or 0)
        for choice, reason in CHOICE_ROUTING.items()
    }


def research_provider(db: FactoryDB, settings: FactorySettings, campaign_id: str) -> str | None:
    """Model family of the topic's research executor (``None`` without routing)."""

    if not budget_control.routing_enabled(settings):
        return None
    with db.connect() as connection:
        row = connection.execute(
            """
            SELECT runner FROM tasks
            WHERE campaign_id=? AND agent_role IN ('researcher', 'experimenter')
              AND runner IS NOT NULL AND runner != ''
            ORDER BY CASE WHEN status='succeeded' THEN 0 ELSE 1 END,
                     created_at DESC, rowid DESC
            LIMIT 1
            """,
            (campaign_id,),
        ).fetchone()
    if row is None:
        return None
    return budget_control.provider_of(settings, row["runner"])


# --------------------------------------------------------------------------- decision registry


def _decisions(db: FactoryDB) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for task_id, raw in db.meta_items(DECISION_META_PREFIX).items():
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            result[task_id] = value
    return result


def _set_decision(db: FactoryDB, task_id: str, record: Mapping[str, Any],
                  events: list[tuple[str, str, str, Mapping[str, Any]]] | None = None) -> None:
    db.update_meta(
        {DECISION_META_PREFIX + task_id: json.dumps(dict(record), sort_keys=True)},
        events=events or [],
    )


def pending_decision(db: FactoryDB, campaign_id: str) -> str | None:
    """Task id of an unresolved direction decision for a topic campaign."""

    for task_id, record in sorted(_decisions(db).items()):
        if record.get("campaign_id") == campaign_id and record.get("status") == "pending":
            return task_id
    return None


def campaign_on_hold(db: FactoryDB, settings: FactorySettings, campaign_id: str) -> bool:
    """A topic campaign waits for its direction decision: no successors meanwhile."""

    return settings.program.enabled and pending_decision(db, campaign_id) is not None


def held_campaigns(paths: WorkspacePaths, settings: FactorySettings) -> set[str]:
    """Campaigns of ready-queued or submitted topics; never reactivated by project sync."""

    if not settings.program.enabled:
        return set()
    document = _ledger(paths, settings).read()
    return {
        str(topic["campaign_id"])
        for topic in topics_by_status(document, *HELD_STATUSES)
        if topic.get("campaign_id")
    }


def budget_divert_campaigns(paths: WorkspacePaths, settings: FactorySettings) -> set[str]:
    """Campaigns whose budget exhaustion becomes a direction decision, not needs_human."""

    if not settings.program.enabled:
        return set()
    document = _ledger(paths, settings).read()
    return {
        str(topic["campaign_id"])
        for topic in topics_by_status(document, *FREEZABLE_STATUSES)
        if topic.get("campaign_id")
    }


def _control_campaign(db: FactoryDB, settings: FactorySettings, domain: str) -> str:
    campaign_id = f"{domain}-program-direction"
    campaign = db.campaign(campaign_id)
    budget = settings.max_campaign_agent_seconds
    if campaign is not None:
        used = float(campaign.get("agent_seconds_used") or 0)
        current = int(campaign.get("max_agent_seconds") or 0)
        status = str(campaign.get("status") or "")
        if status not in {"active", "budget_exhausted"} or (
            status == "active" and used + settings.max_task_wall_seconds + 1 <= current
        ):
            # Enough room, or an operator stopped the campaign: leave it as it is
            # (enqueueing into a stopped campaign fails and is reported).
            return campaign_id
        budget = max(current, int(used) + settings.max_campaign_agent_seconds)
    db.register_campaign(
        campaign_id,
        domain=domain,
        title=f"{domain} research-program direction decisions",
        priority=5,
        source="program:direction_decisions",
        max_agent_seconds=budget,
    )
    return campaign_id


# --------------------------------------------------------------------------- scheduling


def _trigger_reason_text(trigger: str, detail: Mapping[str, Any]) -> str:
    texts = {
        TRIGGER_ENDPOINT_FAILED: "The pre-registered primary endpoint failed.",
        TRIGGER_OVERDUE: (
            f"The topic passed {detail.get('max_days')} days from admission "
            f"({detail.get('admitted_at')}) without a review-ready manuscript."
        ),
        TRIGGER_BUDGET: (
            f"The topic used {detail.get('agent_seconds_used')} of its "
            f"{detail.get('max_agent_seconds')} Agent seconds without a review-ready manuscript."
        ),
        TRIGGER_REVIEW_DIRECTION: "The unified review asks for a direction decision.",
        TRIGGER_REVIEW_RETARGET: "The unified review requires a retarget.",
        TRIGGER_REVIEW_STALLED: "The unified review is stalled: scores no longer improve.",
        TRIGGER_REVIEW_ROUNDS: "The unified review used all rounds for this target.",
    }
    return texts.get(trigger, f"Direction decision trigger: {trigger}.")


def _context_reasons(context: Any) -> list[str]:
    reasons: list[str] = []
    if not isinstance(context, Mapping):
        return reasons
    for key in ("strongest_desk_reject_reason", "decision_rationale",
                "significance_for_journal", "advance_over_prior_work"):
        text = str(context.get(key) or "").strip()
        if text:
            reasons.append(text)
    for item in context.get("referee_rejections") or []:
        if isinstance(item, Mapping):
            for key in ("principal_reason", "significance_assessment", "novelty_assessment"):
                text = str(item.get(key) or "").strip()
                if text:
                    reasons.append(text)
            reasons.extend(str(b).strip() for b in item.get("scientific_blockers") or []
                           if str(b).strip())
    return reasons


def _result_reasons(payload: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(payload, Mapping):
        return []
    reasons = [str(payload.get("summary") or "").strip()]
    for claim in payload.get("claims") or []:
        if isinstance(claim, Mapping) and claim.get("status") in {"refuted", "unsupported"}:
            reasons.append(str(claim.get("text") or "").strip())
    gate_result = payload.get("gate_result")
    if isinstance(gate_result, Mapping):
        reasons.append(str(gate_result.get("reason") or gate_result.get("rationale") or "").strip())
    return [item for item in reasons if item]


def _resource(label: str, path: Path) -> dict[str, str] | None:
    return {"label": label, "path": str(path.resolve()), "sha256": sha256_file(path)} if (
        path.is_file()
    ) else None


def schedule_direction_decision(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    report: Any,
    *,
    topic: Mapping[str, Any],
    trigger: str,
    source_task_id: str,
    evidence: list[dict[str, str]],
    direction_context: Mapping[str, Any] | None = None,
    reasons: list[str] | None = None,
    detail: Mapping[str, Any] | None = None,
    attempt: int = 1,
) -> str | None:
    """Queue one lead-tier ``direction_decision`` for a topic; None if not applicable."""

    topic_id = str(topic["topic_id"])
    campaign_id = str(topic.get("campaign_id") or "")
    if topic.get("status") not in FREEZABLE_STATUSES or not campaign_id:
        return None
    campaign = db.campaign(campaign_id)
    if campaign is None:
        return None
    existing = pending_decision(db, campaign_id)
    if existing is not None:
        return None
    once_key = TRIGGER_META_PREFIX + f"{topic_id}:{trigger}"
    if trigger in ONCE_PER_TOPIC_TRIGGERS and attempt == 1 and db.meta_get(once_key):
        return None
    task_id = f"direction:{_digest(topic_id, trigger, source_task_id, attempt)[:32]}"
    if db.task(task_id) is not None:
        return None
    detail = dict(detail or {})
    trigger_text = _trigger_reason_text(trigger, detail)
    reasons_to_answer = list(dict.fromkeys(
        [trigger_text, *_context_reasons(direction_context), *(reasons or [])]
    ))
    program = settings.program
    usage = _usage(db, campaign_id)
    limits = dict(program.direction_limits)
    used = float(campaign.get("agent_seconds_used") or 0)
    admitted = budget_control.parse_time(topic.get("admitted_at"))
    deadline = admitted + timedelta(days=program.max_days_from_admission_to_ready) if (
        admitted
    ) else None
    registry = paths.data / "registry"
    resources = [
        item for item in (
            _resource("topic-ledger", _ledger(paths, settings).path),
            _resource("team-rejection-ledger", registry / "journal-rejections.json"),
            _resource("reusable-asset-index", paths.data / program.asset_index_path),
            _resource("settings.yaml#research_portfolio", registry / "settings.yaml"),
        ) if item is not None
    ]
    routine = _routine_names(topic)
    exclude = research_provider(db, settings, campaign_id)
    ledger_entry = {
        key: topic.get(key)
        for key in ("topic_id", "domain", "question", "status", "target_tier", "campaign_id",
                    "paper_id", "admitted_at", "preregistration_sha256", "routine_fallback",
                    "cost_estimate", "admission", "history")
    }
    packet = _signed({
        "schema_version": DIRECTION_PACKET_SCHEMA,
        "topic_id": topic_id,
        "campaign_id": campaign_id,
        "domain": topic.get("domain"),
        "trigger": {"reason": trigger, "source_task_id": source_task_id, "detail": detail},
        "attempt": attempt,
        "reasons_to_answer": reasons_to_answer,
        "direction_context": dict(direction_context) if direction_context else None,
        "evidence": list(evidence),
        "ledger_entry": ledger_entry,
        "decisions_used": usage,
        "decision_limits": limits,
        "decisions_remaining": {
            choice: max(0, int(limits.get(choice, 0)) - usage.get(choice, 0))
            for choice in CHOICE_ROUTING
        },
        "budget": {
            "agent_seconds_used": used,
            "max_agent_seconds": int(campaign.get("max_agent_seconds") or 0),
            "topic_max_agent_seconds": program.topic_max_agent_seconds,
            "remaining_hard_seconds": max(0, int(program.topic_max_agent_seconds - used)),
        },
        "deadline": {
            "admitted_at": topic.get("admitted_at"),
            "max_days_from_admission_to_ready": program.max_days_from_admission_to_ready,
            "deadline_at": deadline.isoformat().replace("+00:00", "Z") if deadline else None,
            "overdue": bool(deadline and _now() > deadline),
        },
        "target_tier": topic.get("target_tier"),
        "routine_fallback": topic.get("routine_fallback") or [],
        "escalation_fallback_venue": routine[0] if routine else None,
        "read_resources": resources,
        "research_executor_provider": exclude,
        "options": ["targeted_core_analysis", "retarget_or_short_format", "freeze"],
        "created_at": utc_now(),
    })
    packet_path = (
        _control_root(paths) / "direction-packets" / _token(topic_id) / f"{task_id[10:34]}.json"
    )
    atomic_write_json(packet_path, packet)
    control = _control_campaign(db, settings, str(topic.get("domain") or campaign["domain"]))
    if trigger in {TRIGGER_OVERDUE, TRIGGER_BUDGET}:
        # Research stops while the decision is pending; running work may finish.
        db.cancel_queued_campaign_tasks(campaign_id, reason=f"direction_decision_pending:{trigger}")
    db.enqueue_task(
        task_id=task_id,
        campaign_id=control,
        domain=str(campaign["domain"]),
        task_type=DIRECTION_TASK_TYPE,
        objective=(
            f"Take the direction decision for research-program topic {topic_id} "
            f"(trigger: {trigger}). Read the decision packet at the input path. Return the "
            "result bundle field `direction_decision` with `choice` (targeted_core_analysis, "
            "retarget_or_short_format or freeze), `rationale`, `answers_reason` (quote verbatim "
            "one entry of reasons_to_answer, normally the strongest rejection or failure reason) "
            "and the block of the chosen branch: `analysis` {name, expected_to_change, data, "
            "budget_seconds, success_criterion}, `retarget` {venue_or_format, why_fits} or "
            "`freeze` {reason_class, reopen_conditions[]}. Choices whose decisions_remaining is 0 "
            "are refused and the topic is frozen. Do not run the analysis or edit the manuscript."
        ),
        input_path=str(packet_path),
        skill_path=DIRECTION_SKILL,
        runner="frontier",
        routing_reason=DIRECTION_ROUTING_REASON,
        agent_role="reviewer",
        session_mode="fresh",
        priority=int(campaign.get("priority") or 0) + 2,
        max_attempts=settings.max_attempts,
        max_wall_seconds=min(7_200, settings.max_task_wall_seconds),
        exclude_provider=exclude,
        **default_task_resources(settings).to_dict(),
    )
    record = {
        "status": "pending", "topic_id": topic_id, "campaign_id": campaign_id,
        "trigger": trigger, "source_task_id": source_task_id, "attempt": attempt,
        "packet_path": str(packet_path), "scheduled_at": utc_now(),
    }
    updates = {DECISION_META_PREFIX + task_id: json.dumps(record, sort_keys=True)}
    if trigger in ONCE_PER_TOPIC_TRIGGERS:
        updates[once_key] = task_id
    db.update_meta(updates)
    record_topic_note(
        _ledger(paths, settings), topic_id, db=db, event_type="direction_decision_scheduled",
        reason=trigger, decided_by=f"orchestrator:{trigger}",
        detail={"task_id": task_id, "source_task_id": source_task_id, "attempt": attempt,
                "exclude_provider": exclude},
        evidence=evidence, key=f"scheduled:{task_id}",
    )
    report.enqueued.append(task_id)
    _info(report, "direction_decisions").append(
        {"topic_id": topic_id, "task_id": task_id, "trigger": trigger, "outcome": "scheduled",
         "exclude_provider": exclude}
    )
    return task_id


# --------------------------------------------------------------------------- freezes


def _freeze(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    report: Any,
    *,
    topic_id: str,
    reason_class: str,
    evidence: list[dict[str, str]],
    decided_by: str,
    reopen_conditions: Any = (),
    note: Mapping[str, Any] | None = None,
) -> None:
    ledger = _ledger(paths, settings)
    try:
        conditions = [
            {"type": str(item.get("type")), "description": str(item.get("description"))}
            for item in reopen_conditions or []
            if isinstance(item, Mapping) and str(item.get("type")) in REOPEN_BASIS_TYPES
            and str(item.get("description") or "").strip()
        ]
    except (TypeError, AttributeError):
        conditions = []
    decision = freeze_topic(
        ledger, topic_id, db=db, reason_class=reason_class, evidence=evidence,
        decided_by=decided_by, reopen_conditions=conditions,
    )
    report.cancelled.extend(decision.cancelled_tasks)
    if note:
        record_topic_note(
            ledger, topic_id, db=db, event_type="topic_freeze_noted", reason=reason_class,
            decided_by=decided_by, detail=note, evidence=evidence,
        )
    if decision.changed:
        _info(report, "topics_frozen").append(
            {"topic_id": topic_id, "reason_class": reason_class, "decided_by": decided_by,
             **({"note": dict(note)} if note else {})}
        )


def _freeze_evidence(gate_result: Mapping[str, Any]) -> list[dict[str, str]]:
    items = gate_result.get("evidence")
    if isinstance(items, Mapping):
        items = [items]
    result: list[dict[str, str]] = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, Mapping):
            path = str(item.get("path") or item.get("uri") or "").strip()
            digest = str(item.get("sha256") or "").strip().lower()
            if path and SHA256.fullmatch(digest):
                result.append({"path": path, "sha256": digest})
    return result


# --------------------------------------------------------------------------- ingest hooks


def expected_preregistration(
    paths: WorkspacePaths,
    settings: FactorySettings,
    task: Mapping[str, Any],
    report: Any,
) -> str | None:
    """Ledger pre-registration hash a research result of this campaign must carry."""

    if not settings.program.enabled or str(task.get("agent_role") or "") not in RESEARCH_ROLES:
        return None
    try:
        topic = campaign_topic(paths, settings, str(task.get("campaign_id") or ""))
    except (OSError, TopicLedgerError, ValueError) as exc:
        report.errors.append(f"program pre-registration lookup: {exc}")
        return None
    digest = str((topic or {}).get("preregistration_sha256") or "")
    return digest if SHA256.fullmatch(digest) else None


def on_result(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    report: Any,
    *,
    task: Mapping[str, Any],
    payload: Mapping[str, Any],
    result_path: Path,
    result_sha256: str,
) -> str | None:
    """Program handling of one successful result.

    Returns ``"handled"`` when the program took the next step (no ordinary
    successor may be created), ``"continue_research"`` when a paper candidate
    must not enter the paper pipeline but research may continue, else None.
    """

    if not settings.program.enabled:
        return None
    task_type = str(task.get("task_type") or "")
    if task_type == DIRECTION_TASK_TYPE:
        apply_direction_decision(
            db, paths, settings, report, task=task, payload=payload,
            result_path=result_path, result_sha256=result_sha256,
        )
        return "handled"
    topic = campaign_topic(paths, settings, str(task.get("campaign_id") or ""))
    if topic is None or topic.get("status") not in FREEZABLE_STATUSES:
        return None
    role = str(task.get("agent_role") or "")
    evidence = [_evidence(result_path, result_sha256)]
    if role in RESEARCH_ROLES:
        return _on_research_result(db, paths, settings, report, topic=topic, task=task,
                                   payload=payload, evidence=evidence)
    if role == "reviewer" and task_type == "paper_review":
        return _on_review_result(db, paths, settings, report, topic=topic, task=task,
                                 payload=payload, evidence=evidence)
    if campaign_on_hold(db, settings, str(topic["campaign_id"])):
        return "handled"
    return None


def _on_research_result(db, paths, settings, report, *, topic, task, payload, evidence):
    topic_id = str(topic["topic_id"])
    task_id = str(task["task_id"])
    gate_result = payload.get("gate_result")
    if (
        isinstance(gate_result, Mapping)
        and str(gate_result.get("promotion_decision") or "").strip().lower() == "freeze"
    ):
        declared = str(gate_result.get("freeze_reason_class") or gate_result.get("reason_class")
                       or "").strip()
        note: dict[str, Any] | None = None
        reason_class = declared
        if reason_class not in FREEZE_REASON_CLASSES:
            # Without a usable class the evidence-backed reading is used, never the
            # judgement "contribution_insufficient".
            verdict = str(payload.get("primary_endpoint_verdict") or "")
            reason_class = (
                "primary_endpoint_failed" if verdict == "failed" else "decisive_data_unavailable"
            )
            note = {"reason_class_inferred": True, "declared_reason_class": declared or None,
                    "primary_endpoint_verdict": verdict or None}
        declared_evidence = _freeze_evidence(gate_result)
        if not declared_evidence:
            note = {**(note or {}), "evidence_missing": True}
        _freeze(
            db, paths, settings, report, topic_id=topic_id, reason_class=reason_class,
            evidence=[*declared_evidence, *evidence], decided_by=task_id,
            reopen_conditions=gate_result.get("reopen_conditions"), note=note,
        )
        return "handled"
    if campaign_on_hold(db, settings, str(topic["campaign_id"])):
        return "handled"
    if (
        str(task.get("task_type") or "") == "evidence_remediation"
        and str(task.get("routing_reason") or "") in EVIDENCE_REMEDIATION_ROUTINGS
    ):
        return None  # the existing remediation flow returns to the writer / readiness
    if payload.get("paper_candidate") is not True:
        return None
    verdict = str(payload.get("primary_endpoint_verdict") or "")
    if verdict == "met":
        return None
    if verdict == "failed":
        schedule_direction_decision(
            db, paths, settings, report, topic=topic, trigger=TRIGGER_ENDPOINT_FAILED,
            source_task_id=task_id, evidence=evidence, reasons=_result_reasons(payload),
            detail={"primary_endpoint_verdict": verdict},
        )
        return "handled"
    db.record_event_once(
        "topic", topic_id, "primary_endpoint_inconclusive",
        {"task_id": task_id, "handling": "continue_research_within_budget_and_deadline"},
        event_key=task_id,
    )
    return "continue_research"


REVIEW_TRIGGER_ORDER = (
    (TRIGGER_REVIEW_ROUNDS, lambda o: o.get("status") == "blocked" and o.get("next_action") not in
     {"direction_decision", "retarget_required"}),
    (TRIGGER_REVIEW_DIRECTION, lambda o: o.get("next_action") == "direction_decision"),
    (TRIGGER_REVIEW_RETARGET, lambda o: o.get("next_action") == "retarget_required"),
    (TRIGGER_REVIEW_STALLED, lambda o: o.get("review_stalled") is True),
)


def review_trigger(outcome: Mapping[str, Any]) -> str | None:
    """Direction trigger named by a structured review outcome (None: ordinary flow)."""

    for trigger, matches in REVIEW_TRIGGER_ORDER:
        if matches(outcome):
            return trigger
    return None


def _on_review_result(db, paths, settings, report, *, topic, task, payload, evidence):
    outcome = payload.get("review_outcome")
    if outcome is None and payload.get("paper_candidate") is True:
        # A legacy ready bundle (no review_outcome) still ends the review: the
        # paper-side handoff gate re-validates the bound writing_release.
        queue_ready_topic(db, paths, settings, report, topic=topic, task=task,
                          outcome={}, payload=payload, evidence=evidence)
        return "handled"
    if not isinstance(outcome, Mapping) or not validate_review_outcome(outcome).valid:
        return None  # legacy result bundle: existing behaviour
    record = str(outcome.get("decision_record") or "")
    record_path = paths.data / record
    if record and record_path.is_file() and sha256_file(record_path) != str(
        outcome.get("decision_record_sha256")
    ):
        report.errors.append(
            f"Paper review {task.get('task_id')} review_outcome does not match "
            f"{record}; treated as a legacy result"
        )
        return None
    if record and record_path.is_file():
        evidence = [*evidence, _evidence(record_path)]
    if payload.get("paper_candidate") is True and outcome.get("status") == "ready":
        queue_ready_topic(db, paths, settings, report, topic=topic, task=task,
                          outcome=outcome, payload=payload, evidence=evidence)
        return "handled"
    trigger = review_trigger(outcome)
    if trigger is None:
        return None
    schedule_direction_decision(
        db, paths, settings, report, topic=topic, trigger=trigger,
        source_task_id=str(task["task_id"]), evidence=evidence,
        direction_context=outcome.get("direction_context")
        if isinstance(outcome.get("direction_context"), Mapping) else None,
        detail={key: outcome.get(key) for key in (
            "next_action", "status", "review_stalled", "rounds_for_target",
            "max_rounds_per_target", "decision_record", "decision_record_sha256", "paper_id",
        )},
    )
    return "handled"


def on_review_scheduled(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    *,
    campaign_id: str,
    review_task_id: str,
) -> None:
    """``active -> in_review`` when a topic's manuscript enters the unified review."""

    topic = campaign_topic(paths, settings, campaign_id)
    if topic is None or topic.get("status") != "active":
        return
    mark_topic_in_review(_ledger(paths, settings), str(topic["topic_id"]), db=db,
                         decided_by=review_task_id)


def queue_ready_topic(db, paths, settings, report, *, topic, task, outcome, payload, evidence):
    """Review ready: ``ready_queue``, pause the campaign (slot released), queue delivery."""

    ledger = _ledger(paths, settings)
    topic_id = str(topic["topic_id"])
    task_id = str(task["task_id"])
    paper_id = str(outcome.get("paper_id") or payload.get("paper_id") or topic.get("paper_id")
                   or "").strip() or None
    if topic.get("status") == "active":
        mark_topic_in_review(ledger, topic_id, db=db, decided_by=task_id, paper_id=paper_id)
    mark_topic_ready(ledger, topic_id, db=db, decided_by=task_id, paper_id=paper_id,
                     evidence=evidence)
    campaign_id = str(topic.get("campaign_id") or "")
    if campaign_id and db.campaign(campaign_id) is not None:
        report.cancelled.extend(
            db.pause_production_campaign(campaign_id, reason="topic_ready_queue")
        )
        report.production_paused.append(campaign_id)
    record_topic_note(
        ledger, topic_id, db=db, event_type="handoff_queued", reason="review_passed",
        decided_by=task_id,
        detail={"paper_id": paper_id, "auto_handoff": settings.program.auto_handoff},
        updates={"handoff": {"status": "queued", "attempts": 0, "paper_id": paper_id,
                             "queued_at": utc_now()}},
        key=f"handoff_queued:{task_id}",
    )
    _info(report, "ready_queued").append(
        {"topic_id": topic_id, "paper_id": paper_id, "campaign_id": campaign_id,
         "review_task_id": task_id}
    )


# --------------------------------------------------------------------------- applying decisions


def _normalized(text: Any) -> str:
    value = str(text or "").strip().strip("\"'“”‘’「」").strip()
    return " ".join(value.split()).casefold()


def quotes_a_reason(answer: Any, reasons: list[str]) -> bool:
    """``answers_reason`` quotes one listed reason verbatim (whitespace-insensitive)."""

    quoted = _normalized(answer)
    if len(quoted) < 8:
        return False
    return any(quoted in _normalized(reason) for reason in reasons if _normalized(reason))


def _set_campaign_budget(db: FactoryDB, campaign: Mapping[str, Any], maximum: int) -> None:
    policy = dict(workstream_policy(campaign))
    policy["max_agent_seconds"] = int(maximum)
    execution = campaign.get("execution_policy_json")
    try:
        execution_policy = json.loads(execution) if isinstance(execution, str) and execution else {}
    except json.JSONDecodeError:
        execution_policy = {}
    db.configure_project_campaign(
        str(campaign["campaign_id"]),
        project_config_path=str(campaign.get("project_config_path") or ""),
        workstream_state_path=str(campaign.get("workstream_state_path") or ""),
        protocol_id=str(campaign.get("protocol_id") or ""),
        primary_skill=str(campaign.get("primary_skill") or ""),
        execution_policy=execution_policy if isinstance(execution_policy, Mapping) else {},
        project_id=campaign.get("project_id"),
        workstream_policy=policy,
        priority=int(campaign.get("priority") or 0),
        max_agent_seconds=int(maximum),
    )


def _reject_choice(choice: str, *, used: Mapping[str, int],
                   limits: Mapping[str, int], decision: Mapping[str, Any],
                   campaign: Mapping[str, Any], settings: FactorySettings) -> str | None:
    if choice in CHOICE_ROUTING and used.get(choice, 0) >= int(limits.get(choice, 0)):
        return "direction_limit_exhausted"
    cap = int(settings.program.topic_max_agent_seconds)
    spent = float(campaign.get("agent_seconds_used") or 0)
    if choice == "targeted_core_analysis":
        seconds = int((decision.get("analysis") or {}).get("budget_seconds") or 0)
        if spent + seconds > cap:
            return "analysis_exceeds_topic_budget"
    if choice == "retarget_or_short_format" and spent + 1 > cap:
        return "topic_budget_exhausted"
    return None


def apply_direction_decision(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    report: Any,
    *,
    task: Mapping[str, Any],
    payload: Mapping[str, Any],
    result_path: Path,
    result_sha256: str,
) -> str:
    """Apply one direction decision through the existing task paths; return its outcome."""

    task_id = str(task["task_id"])
    record = _decisions(db).get(task_id)
    if record is not None and record.get("status") != "pending":
        return str(record.get("outcome") or record.get("status"))
    packet = _verified_packet(Path(str(task.get("input_path") or "")))
    topic_id = str(packet["topic_id"])
    record = dict(record or {
        "topic_id": topic_id, "campaign_id": packet["campaign_id"],
        "trigger": packet["trigger"]["reason"],
        "source_task_id": packet["trigger"]["source_task_id"],
        "attempt": int(packet.get("attempt") or 1), "packet_path": str(task.get("input_path")),
    })
    ledger = _ledger(paths, settings)
    topic = find_topic(ledger.read(), topic_id)
    trigger = str(record["trigger"])
    evidence = [_evidence(result_path, result_sha256)]

    def finish(outcome: str, detail: Mapping[str, Any]) -> str:
        _set_decision(db, task_id, {**record, "status": "resolved", "outcome": outcome,
                                    "resolved_at": utc_now()})
        _info(report, "direction_decisions").append(
            {"topic_id": topic_id, "task_id": task_id, "trigger": trigger, "outcome": outcome,
             **dict(detail)}
        )
        return outcome

    if topic is None or topic.get("status") not in FREEZABLE_STATUSES:
        return finish("ignored_topic_not_open", {"status": (topic or {}).get("status")})
    decision = payload.get("direction_decision")
    problems = list(validate_direction_decision(decision).errors) if decision is not None else [
        "direction_decision is missing"
    ]
    if not problems and not quotes_a_reason(
        decision.get("answers_reason"), list(packet.get("reasons_to_answer") or [])
    ):
        problems.append("answers_reason does not quote one of reasons_to_answer verbatim")
    if problems:
        db.record_event_once("topic", topic_id, "direction_decision_invalid",
                             {"task_id": task_id, "errors": problems}, event_key=task_id)
        _retry_or_freeze(db, paths, settings, report, record=record, topic=topic,
                         task_id=task_id, reason="direction_decision_invalid",
                         evidence=evidence)
        return finish("invalid", {"errors": problems})
    assert isinstance(decision, Mapping)
    choice = str(decision["choice"])
    campaign_id = str(topic["campaign_id"])
    campaign = db.campaign(campaign_id) or {}
    used = _usage(db, campaign_id)
    limits = dict(settings.program.direction_limits)
    summary = {
        "choice": choice, "rationale": decision.get("rationale"),
        "answers_reason": decision.get("answers_reason"), "decisions_used": used,
        "decision_limits": limits,
    }
    rejection = _reject_choice(choice, used=used, limits=limits, decision=decision,
                               campaign=campaign, settings=settings)
    if rejection is not None:
        reason_class = (
            "budget_exhausted" if rejection != "direction_limit_exhausted"
            else TRIGGER_FREEZE_CLASS.get(trigger, CHOICE_FREEZE_CLASS[choice])
        )
        record_topic_note(
            ledger, topic_id, db=db, event_type="direction_decided", reason=rejection,
            decided_by=task_id, detail={**summary, "accepted": False, "trigger": trigger},
            evidence=evidence, key=f"decided:{task_id}",
        )
        _freeze(db, paths, settings, report, topic_id=topic_id, reason_class=reason_class,
                evidence=evidence, decided_by=task_id,
                note={"direction_choice_rejected": choice, "rejection": rejection})
        return finish("rejected_frozen", {"choice": choice, "rejection": rejection,
                                          "reason_class": reason_class})
    executed: str | None = None
    if choice == "freeze":
        freeze = decision["freeze"]
        record_topic_note(
            ledger, topic_id, db=db, event_type="direction_decided", reason=choice,
            decided_by=task_id, detail={**summary, "accepted": True, "trigger": trigger},
            evidence=evidence, key=f"decided:{task_id}",
        )
        _freeze(db, paths, settings, report, topic_id=topic_id,
                reason_class=str(freeze["reason_class"]), evidence=evidence,
                decided_by=task_id, reopen_conditions=freeze.get("reopen_conditions"))
        return finish("frozen", {"choice": choice, "reason_class": freeze["reason_class"]})
    source_task_id = str(record["source_task_id"])
    if trigger == TRIGGER_BUDGET or float(campaign.get("agent_seconds_used") or 0) + 1 > float(
        campaign.get("max_agent_seconds") or 0
    ):
        # Continuing after a budget stop: the remaining room up to the hard ceiling.
        _set_campaign_budget(db, campaign, settings.program.topic_max_agent_seconds)
    elif choice == "targeted_core_analysis":
        wanted = float(campaign.get("agent_seconds_used") or 0) + int(
            decision["analysis"]["budget_seconds"]
        )
        if wanted > float(campaign.get("max_agent_seconds") or 0):
            _set_campaign_budget(
                db, campaign, min(settings.program.topic_max_agent_seconds, int(wanted) + 1)
            )
    campaign = db.campaign(campaign_id) or campaign
    if str(campaign.get("status") or "") != "active":
        _set_campaign_budget(db, campaign, int(campaign.get("max_agent_seconds") or 1))
        campaign = db.campaign(campaign_id) or campaign
    if choice == "targeted_core_analysis":
        executed = _enqueue_targeted_analysis(
            db, settings, campaign=campaign, decision=decision, decision_task_id=task_id,
            source_task_id=source_task_id, input_path=result_path,
        )
    else:
        executed = _enqueue_retarget(
            db, settings, topic=topic, campaign=campaign, decision=decision,
            decision_task_id=task_id, source_task_id=source_task_id, input_path=result_path,
        )
    report.enqueued.append(executed)
    record_topic_note(
        ledger, topic_id, db=db, event_type="direction_decided", reason=choice,
        decided_by=task_id,
        detail={**summary, "accepted": True, "trigger": trigger, "executed_task_id": executed},
        evidence=evidence, key=f"decided:{task_id}",
    )
    return finish("executed", {"choice": choice, "executed_task_id": executed})


def _enqueue_targeted_analysis(db, settings, *, campaign, decision, decision_task_id,
                               source_task_id, input_path) -> str:
    analysis = decision["analysis"]
    task_id = f"{decision_task_id}:targeted-analysis"
    if db.task(task_id) is not None:
        return task_id
    source = db.task(source_task_id) or {}
    db.enqueue_task(
        task_id=task_id,
        campaign_id=str(campaign["campaign_id"]),
        domain=str(campaign["domain"]),
        task_type="evidence_remediation",
        objective=(
            f"Run exactly one named analysis chosen by the direction decision: "
            f"{analysis['name']}. It is expected to change: {analysis['expected_to_change']}. "
            f"Data: {analysis['data']}. Success criterion: {analysis['success_criterion']}. "
            f"Budget: {analysis['budget_seconds']} Agent seconds. Report the result against "
            "the success criterion honestly, including a negative one; keep the pre-registered "
            "primary endpoint unchanged and do not broaden the question. The decision is at the "
            "input path."
        ),
        input_path=str(input_path),
        skill_path=str(campaign.get("primary_skill") or "") or None,
        runner="balanced",
        routing_reason=TARGETED_ROUTING,
        parent_task_id=source_task_id if source else None,
        agent_role="researcher",
        session_mode="fresh",
        priority=int(campaign.get("priority") or 0) + 1,
        max_attempts=settings.max_attempts,
        max_wall_seconds=max(60, min(int(analysis["budget_seconds"]),
                                     settings.max_task_wall_seconds)),
        **default_task_resources(settings).to_dict(),
    )
    return task_id


def _enqueue_retarget(db, settings, *, topic, campaign, decision, decision_task_id,
                      source_task_id, input_path) -> str:
    from .engine import _paper_skill

    retarget = decision["retarget"]
    requested = str(retarget.get("venue_or_format") or "").strip()
    routine = _routine_names(topic)
    target = requested
    if str(topic.get("target_tier") or "") == "escalation" and (
        not requested or requested.casefold() in {"fallback", "fallback_venue", "routine",
                                                  "routine_fallback", "default"}
    ):
        target = routine[0] if routine else requested
    fallback_note = (
        f" This topic was admitted on the escalation track; unless the decision names another "
        f"eligible routine venue or a short format, retarget to its registered fallback venue "
        f"{routine[0]!r} and mark target_escalation as superseded by the fallback."
        if str(topic.get("target_tier") or "") == "escalation" and routine else ""
    )
    objective = (
        f"handoff_kind=retarget. Retarget the manuscript to {target} "
        f"(direction decision: {retarget['why_fits']}). Refresh and check the team rejection "
        "history (`paper-writing journal-history sync`/`check`) and the venue policy before "
        "changing the target, convert the canonical manuscript to the new venue or format, and "
        "keep every claim inside the frozen evidence." + fallback_note
    )
    domain = str(campaign["domain"])
    writer_source = db.nearest_session_source(source_task_id, agent_role="writer") if (
        db.task(source_task_id)
    ) else None
    if writer_source is not None:
        task_id = f"{decision_task_id}:retarget"
        if db.task(task_id) is None:
            source_task = db.task(str(writer_source["task_id"])) or {}
            db.enqueue_task(
                task_id=task_id,
                campaign_id=str(campaign["campaign_id"]),
                domain=domain,
                task_type="paper_revision",
                objective=objective,
                input_path=str(input_path),
                skill_path=_paper_skill(domain),
                runner="frontier",
                routing_reason=RETARGET_ROUTING,
                parent_task_id=source_task_id,
                agent_role="writer",
                session_mode="resume",
                session_source_task_id=str(writer_source["task_id"]),
                priority=int(campaign.get("priority") or 0) + 1,
                max_attempts=settings.max_attempts,
                max_wall_seconds=settings.max_task_wall_seconds,
                cpu_threads=int(source_task.get("cpu_threads") or 1),
                memory_mib=int(source_task.get("memory_mib") or 1024),
                scratch_mib=int(source_task.get("scratch_mib") or 1024),
            )
        return task_id
    # No manuscript yet (e.g. after a failed endpoint): an independent readiness
    # audit for the new venue or short format comes before any writer.
    task_id = f"{decision_task_id}:retarget-readiness"
    if db.task(task_id) is None:
        db.enqueue_task(
            task_id=task_id,
            campaign_id=str(campaign["campaign_id"]),
            domain=domain,
            task_type="paper_readiness",
            objective=(
                objective + " No manuscript exists yet: independently audit whether the frozen "
                "evidence supports a paper in this venue or format; return a readiness verdict "
                "and exact gaps, and do not draft."
            ),
            input_path=str(input_path),
            skill_path=_paper_skill(domain),
            runner="frontier",
            routing_reason=RETARGET_ROUTING,
            parent_task_id=source_task_id if db.task(source_task_id) else None,
            agent_role="reviewer",
            session_mode="fresh",
            priority=int(campaign.get("priority") or 0) + 1,
            max_attempts=settings.max_attempts,
            max_wall_seconds=settings.max_task_wall_seconds,
            **default_task_resources(settings).to_dict(),
        )
    return task_id


def _retry_or_freeze(db, paths, settings, report, *, record, topic, task_id, reason, evidence):
    attempt = int(record.get("attempt") or 1)
    trigger = str(record.get("trigger"))
    if attempt < MAX_DECISION_ATTEMPTS:
        # Resolve first so the retry is not blocked by its own pending record.
        _set_decision(db, task_id, {**record, "status": "resolved", "outcome": reason,
                                    "resolved_at": utc_now()})
        packet = _verified_packet(Path(str(record["packet_path"])))
        retried = schedule_direction_decision(
            db, paths, settings, report, topic=topic, trigger=trigger,
            source_task_id=str(record["source_task_id"]),
            evidence=list(packet.get("evidence") or []),
            direction_context=packet.get("direction_context"),
            reasons=list(packet.get("reasons_to_answer") or []),
            detail=dict(packet["trigger"].get("detail") or {}), attempt=attempt + 1,
        )
        if retried is not None:
            return
    reason_class = TRIGGER_FREEZE_CLASS.get(trigger, "contribution_insufficient")
    if reason_class == "contribution_insufficient":
        # No independent judgement exists: do not record one.
        reason_class = "review_stalled" if trigger.startswith("review_") else "infrastructure"
    _freeze(db, paths, settings, report, topic_id=str(topic["topic_id"]),
            reason_class=reason_class, evidence=evidence,
            decided_by=f"orchestrator:{reason}",
            note={"direction_decision_unavailable": reason, "attempts": attempt})


# --------------------------------------------------------------------------- controller tick


def _check_limits(db, paths, settings, report) -> None:
    program = settings.program
    ledger = _ledger(paths, settings)
    now = _now()
    for topic in topics_by_status(ledger.read(), *FREEZABLE_STATUSES):
        topic_id = str(topic["topic_id"])
        campaign_id = str(topic.get("campaign_id") or "")
        campaign = db.campaign(campaign_id) if campaign_id else None
        if campaign is None or str(campaign.get("status") or "") == "frozen":
            continue
        if pending_decision(db, campaign_id) is not None:
            continue
        latest = db.latest_task(campaign_id)
        if latest is None:
            continue
        used = float(campaign.get("agent_seconds_used") or 0)
        maximum = float(campaign.get("max_agent_seconds") or 0)
        cap = float(program.topic_max_agent_seconds)
        if used + 1 > maximum and not db.has_active_tasks(campaign_id):
            detail = {"agent_seconds_used": round(used, 1), "max_agent_seconds": int(maximum),
                      "topic_max_agent_seconds": int(cap)}
            evidence = [_write_evidence(paths, topic_id, "budget", detail)]
            if maximum < cap and not db.meta_get(TRIGGER_META_PREFIX
                                                 + f"{topic_id}:{TRIGGER_BUDGET}"):
                schedule_direction_decision(
                    db, paths, settings, report, topic=topic, trigger=TRIGGER_BUDGET,
                    source_task_id=str(latest["task_id"]), evidence=evidence, detail=detail,
                )
            else:
                _freeze(db, paths, settings, report, topic_id=topic_id,
                        reason_class="budget_exhausted", evidence=evidence,
                        decided_by="orchestrator:topic_budget_ceiling", note=detail)
            continue
        admitted = budget_control.parse_time(topic.get("admitted_at"))
        if admitted is None:
            continue
        if now - admitted > timedelta(days=program.max_days_from_admission_to_ready):
            detail = {"admitted_at": topic.get("admitted_at"),
                      "max_days": program.max_days_from_admission_to_ready,
                      "checked_at": now.isoformat().replace("+00:00", "Z")}
            if db.meta_get(TRIGGER_META_PREFIX + f"{topic_id}:{TRIGGER_OVERDUE}"):
                continue
            schedule_direction_decision(
                db, paths, settings, report, topic=topic, trigger=TRIGGER_OVERDUE,
                source_task_id=str(latest["task_id"]),
                evidence=[_write_evidence(paths, topic_id, "overdue",
                                          {k: v for k, v in detail.items() if k != "checked_at"})],
                detail=detail,
            )


def _check_decision_tasks(db, paths, settings, report) -> None:
    """Retry or freeze after failed decision tasks; apply results a crash left unapplied."""

    ledger = _ledger(paths, settings)
    for task_id, record in sorted(_decisions(db).items()):
        if record.get("status") != "pending":
            continue
        task = db.task(task_id)
        if task is None or str(task.get("status")) in IN_FLIGHT:
            continue
        topic = find_topic(ledger.read(), str(record.get("topic_id")))
        if topic is None or topic.get("status") not in FREEZABLE_STATUSES:
            _set_decision(db, task_id, {**record, "status": "resolved",
                                        "outcome": "ignored_topic_not_open",
                                        "resolved_at": utc_now()})
            continue
        status = str(task.get("status"))
        if status == "succeeded" and task.get("result_path"):
            result_path = Path(str(task["result_path"]))
            try:
                payload = _read_object(result_path)
                apply_direction_decision(
                    db, paths, settings, report, task=task, payload=payload,
                    result_path=result_path, result_sha256=sha256_file(result_path),
                )
            except (OSError, TypeError, ValueError, KeyError, TopicLedgerError) as exc:
                report.errors.append(f"Could not apply direction decision {task_id}: {exc}")
            continue
        if status in DECISION_FAILED_STATUSES:
            evidence = [_evidence(Path(str(record["packet_path"])))]
            _retry_or_freeze(db, paths, settings, report, record=record, topic=topic,
                             task_id=task_id, reason=f"direction_task_{status}",
                             evidence=evidence)
            current = _decisions(db).get(task_id) or record
            if current.get("status") == "pending":
                _set_decision(db, task_id, {**record, "status": "resolved",
                                            "outcome": f"task_{status}",
                                            "resolved_at": utc_now()})


# --------------------------------------------------------------------------- delivery


def run_paper_delivery(
    paths: WorkspacePaths,
    settings: FactorySettings,
    paper_id: str,
) -> dict[str, Any]:
    """Run ``paper-writing program deliver`` (never assigns a submission handler).

    ``[program] auto_handoff = true`` is the standing authorization for this one
    external write, so ``OPENLABS_ENABLE_EXTERNAL_WRITES=1`` is set for this call
    only. Credentials come from the environment (``ARA_PAPER_MANAGE_API_URL``,
    ``ARA_PAPER_MANAGE_API_KEY``).
    """

    return _run_paper_command(
        paths, settings, ["program", "deliver", "--paper-id", paper_id],
        environment={"OPENLABS_ENABLE_EXTERNAL_WRITES": "1"},
    )


def run_handler_assignment(
    paths: WorkspacePaths,
    settings: FactorySettings,
    paper_id: str,
    handler: str,
) -> dict[str, Any]:
    return _run_paper_command(
        paths, settings,
        ["program", "assign-handler", "--paper-id", paper_id, "--handler", handler],
    )


def _run_paper_command(paths: WorkspacePaths, settings: FactorySettings,
                       arguments: list[str],
                       environment: Mapping[str, str] | None = None) -> dict[str, Any]:
    command = [*settings.program.paper_writing_command, *arguments, "--root", str(paths.data),
               "--json"]
    try:
        completed = subprocess.run(
            command, cwd=str(paths.data), env={**os.environ, **dict(environment or {})},
            capture_output=True,
            text=True, timeout=1_800, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DeliveryError(f"{' '.join(command[:3])} could not run: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[-800:]
        raise DeliveryError(f"exit {completed.returncode}: {detail}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise DeliveryError("paper-writing returned no JSON result") from exc
    if not isinstance(payload, dict):
        raise DeliveryError("paper-writing returned a non-object result")
    return payload


DELIVERY_ENVIRONMENT = ("ARA_PAPER_MANAGE_API_URL", "ARA_PAPER_MANAGE_API_KEY")


def _deliver_ready(db, paths, settings, report) -> None:
    program = settings.program
    ledger = _ledger(paths, settings)
    for topic in topics_by_status(ledger.read(), "ready_queue"):
        topic_id = str(topic["topic_id"])
        state = dict(topic.get("handoff") or {})
        status = str(state.get("status") or "queued")
        paper_id = str(state.get("paper_id") or topic.get("paper_id") or "").strip()
        entry = {"topic_id": topic_id, "paper_id": paper_id or None}
        if status in {"delivered", "exhausted"}:
            continue
        if not program.auto_handoff:
            _info(report, "handoffs").append({**entry, "outcome": "queued_auto_handoff_off"})
            continue
        if not paper_id:
            _info(report, "handoffs").append({**entry, "outcome": "blocked_paper_id_unknown"})
            db.record_event_once("topic", topic_id, "handoff_blocked",
                                 {"reason": "paper_id_unknown"}, event_key="paper_id_unknown")
            continue
        missing = [name for name in DELIVERY_ENVIRONMENT if not os.environ.get(name, "").strip()]
        if missing:
            _info(report, "handoffs").append({**entry, "outcome": "waiting_credentials",
                                               "missing": missing})
            db.record_event_once("topic", topic_id, "handoff_blocked",
                                 {"reason": "credentials_missing", "missing": missing},
                                 event_key="credentials_missing")
            continue
        attempts = int(state.get("attempts") or 0) + 1
        try:
            result = run_paper_delivery(paths, settings, paper_id)
            if result.get("submission_handler") not in (None, ""):
                raise DeliveryError("delivery reported a submission handler; refusing it")
        except DeliveryError as exc:
            final = attempts >= program.handoff_max_attempts
            new_state = {**state, "status": "exhausted" if final else "failed",
                         "attempts": attempts, "last_error": str(exc)[:800],
                         "last_attempt_at": utc_now(), "paper_id": paper_id}
            record_topic_note(
                ledger, topic_id, db=db, event_type="handoff_failed", reason="delivery_failed",
                decided_by="orchestrator:auto_handoff",
                detail={"attempt": attempts, "error": str(exc)[:800], "final": final},
                updates={"handoff": new_state}, key=f"handoff_failed:{attempts}",
            )
            _info(report, "handoffs").append({**entry, "outcome": "failed", "attempt": attempts,
                                               "final": final, "error": str(exc)[:300]})
            continue
        new_state = {**state, "status": "delivered", "attempts": attempts,
                     "delivered_at": utc_now(), "paper_id": paper_id,
                     "package_id": result.get("package_id"), "submission_handler": None,
                     "receipt": result.get("receipt")}
        record_topic_note(
            ledger, topic_id, db=db, event_type="handoff_delivered", reason="auto_handoff",
            decided_by="orchestrator:auto_handoff",
            detail={"paper_id": paper_id, "package_id": result.get("package_id"),
                    "awaiting_owner_review": True, "submission_handler": None},
            updates={"handoff": new_state, "awaiting_owner_review": True},
            key=f"handoff_delivered:{paper_id}:{result.get('package_id')}",
        )
        _info(report, "handoffs").append({**entry, "outcome": "delivered",
                                           "package_id": result.get("package_id")})


def assign_submission_handler(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    *,
    paper_id: str,
    handler: str = "second_author",
    assigned_by: str = "owner",
) -> dict[str, Any]:
    """After the owner's review: assign the paper's submission handler (default second author)."""

    result = run_handler_assignment(paths, settings, paper_id, handler)
    ledger = _ledger(paths, settings)
    document = ledger.read()
    topic = next((item for item in document.get("topics") or []
                  if str(item.get("paper_id") or "") == paper_id
                  or str((item.get("handoff") or {}).get("paper_id") or "") == paper_id), None)
    if topic is not None:
        record_topic_note(
            ledger, str(topic["topic_id"]), db=db, event_type="submission_handler_assigned",
            reason="owner_review_completed", decided_by=f"manual:{assigned_by}",
            detail={"paper_id": paper_id, "handler": handler,
                    "assigned": result.get("submission_handler")},
            updates={"awaiting_owner_review": False},
        )
    return {"schema_version": "openlabs.program_handler_assignment.v1",
            "topic_id": topic.get("topic_id") if topic else None, **result}


def run_program_autonomy(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    report: Any,
) -> None:
    """Per-tick stop rules, decision recovery and delivery. Disabled: touches nothing."""

    if not settings.program.enabled:
        return
    for name, step in (("limits", _check_limits), ("decisions", _check_decision_tasks),
                       ("delivery", _deliver_ready)):
        try:
            step(db, paths, settings, report)
        except (OSError, TopicLedgerError, KeyError, TypeError, ValueError,
                json.JSONDecodeError) as exc:
            report.errors.append(f"program autonomy ({name}): {exc}")
    for key in ("direction_decisions", "topics_frozen", "ready_queued", "handoffs"):
        report.program.setdefault(key, [])
