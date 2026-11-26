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
import stat as stat_module
import subprocess
import time
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import assets as asset_library
from . import budget as budget_control
from .config import FactorySettings, WorkspacePaths, dispatch_runner
from .contracts import (
    FREEZE_REASON_CLASSES,
    REOPEN_BASIS_TYPES,
    admission_conditions,
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
    parked_program_projects,
    record_topic_note,
    return_topic_to_review,
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
TRIGGER_VENUE_GRADE = "review_venue_grade"
# NC aim (user 2026-11-25, nc_grading.py): the journal is graded before writing; review ready
# then goes straight to the queue (no re-check since 2026-11-26).
TRIGGER_PRE_WRITING_GRADE = "pre_writing_grade"
GRADE_TRIGGERS = frozenset({TRIGGER_VENUE_GRADE, TRIGGER_PRE_WRITING_GRADE})
# A research executor stopped with needs_human on a scientific/process question
# (not an infrastructure miss): the lead decides instead of the topic waiting
# for the 28-day calendar trigger while it holds a slot (2026-11-14: two astro
# topics held slots this way). Fires once per source result.
TRIGGER_RESEARCH_BLOCKED = "research_needs_human"
ONCE_PER_TOPIC_TRIGGERS = frozenset({TRIGGER_OVERDUE, TRIGGER_BUDGET})
TRIGGER_FREEZE_CLASS = {
    TRIGGER_ENDPOINT_FAILED: "primary_endpoint_failed",
    TRIGGER_OVERDUE: "overdue",
    TRIGGER_BUDGET: "budget_exhausted",
    TRIGGER_REVIEW_STALLED: "review_stalled",
    TRIGGER_REVIEW_ROUNDS: "review_stalled",
    # Owner recompute review loop (owner.py).
    "owner_review_rounds_exhausted": "review_stalled",
    "owner_review_rejected": "review_stalled",
    # Line-level shared facts (line_facts.py): a decision that runs out of choices freezes
    # the topic for the precheck it could not pass.
    "line_reference_review": "feasibility_precheck_failed",
    "criterion_borderline": "feasibility_precheck_failed",
    "line_block_expired": "feasibility_precheck_failed",
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
IN_FLIGHT = ("queued", "leased", "running", "awaiting_remote")
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
    return paths.program_control


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

    runner = _research_runner(db, settings, campaign_id)
    return None if runner is None else budget_control.family_of(settings, runner)


def research_model(db: FactoryDB, settings: FactorySettings, campaign_id: str) -> str | None:
    """Model of the topic's research executor, when its runner names one."""

    runner = _research_runner(db, settings, campaign_id)
    spec = settings.runners.get(runner) if runner is not None else None
    return spec.model if spec is not None and spec.model else None


def _research_runner(db: FactoryDB, settings: FactorySettings, campaign_id: str) -> str | None:
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
    return str(row["runner"])


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
    """A topic campaign waits for its direction decision, or for a line-level block on the
    shared reference its precheck failed against (``line_facts``): no successors meanwhile."""

    if not settings.program.enabled:
        return False
    from . import line_facts

    return pending_decision(db, campaign_id) is not None or line_facts.campaign_waiting(
        db, campaign_id)


def hold_reason(db: FactoryDB, settings: FactorySettings, campaign_id: str) -> str:
    """Why :func:`campaign_on_hold` holds a campaign (for the tick report)."""

    from . import line_facts

    if line_facts.campaign_waiting(db, campaign_id) and pending_decision(db, campaign_id) is None:
        return "line_block_wait"
    return "direction_decision_pending"


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
        TRIGGER_VENUE_GRADE: "Assess which journal tier the completed evidence supports.",
        TRIGGER_PRE_WRITING_GRADE: (
            "Before writing: assess which journal tier the completed research supports."),
        "owner_review_rejected": (
            "The independent recompute review rejected the manuscript: its main conclusion "
            "does not hold and the reviewer sees no revision of this topic that rescues it."
        ),
        "owner_review_rounds_exhausted": (
            f"The independent recompute review still judged the manuscript major revision in "
            f"round {detail.get('round')} of {detail.get('max_rounds')}."
        ),
        "owner_no_progress": (
            f"The topic owner finished {detail.get('no_progress_streak')} consecutive seats "
            "without new evidence (unchanged workspace, no new artifact, no finished job)."
        ),
        "owner_stalled": (
            f"The topic stayed in the same state for {detail.get('signature_streak')} "
            "consecutive owner seats (same phase, packet status, research files, jobs, review "
            "stage, writer and ledger status), across earlier decisions. The diagnosis is in "
            "the trigger detail; choose a step that changes the state, or freeze."
        ),
        TRIGGER_RESEARCH_BLOCKED: (
            "The research executor stopped with needs_human instead of continuing; decide "
            "whether one targeted step continues the topic or it is frozen."
        ),
    }
    if trigger in texts:
        return texts[trigger]
    from . import line_facts

    return line_facts.trigger_reason_text(trigger, detail) or (
        f"Direction decision trigger: {trigger}.")


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


def _blocked_reasons(payload: Mapping[str, Any]) -> list[str]:
    """Reasons a needs_human research result gives, for ``reasons_to_answer``."""

    reasons = _result_reasons(payload)
    intervention = payload.get("human_intervention")
    if isinstance(intervention, Mapping):
        for key in ("reason", "required_action"):
            text = str(intervention.get(key) or "").strip()
            if text:
                reasons.append(text)
    text = str(payload.get("stop_reason") or "").strip()
    if text:
        reasons.append(text)
    return list(dict.fromkeys(reasons))


def _research_block(
    db: FactoryDB,
    campaign: Mapping[str, Any],
    latest: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, str]]] | None:
    """(payload, evidence) when a researcher ended the topic's work with needs_human.

    Only an agent-written needs_human result of an active campaign counts: runner
    failures (any recorded ``failure_class``, launch failures) stay with the
    infrastructure triage, and a campaign an operator paused is left alone.
    """

    if (
        str(latest.get("status") or "") != "needs_human"
        or str(latest.get("agent_role") or "") not in RESEARCH_ROLES
        or str(campaign.get("status") or "") != "active"
    ):
        return None
    attempts = db.task_attempts(str(latest["task_id"]))
    if not attempts:
        return None
    last = attempts[-1]
    runtime = last.get("runtime") if isinstance(last.get("runtime"), Mapping) else {}
    if str(last.get("status") or "") == "launch_failed" or runtime.get("failure_class"):
        return None
    result_path = str(last.get("result_path") or latest.get("result_path") or "")
    if not result_path:
        return None
    path = Path(result_path)
    try:
        payload = _read_object(path)
    except (OSError, TypeError, ValueError):
        return None
    if str(payload.get("status") or "") != "needs_human":
        return None
    return payload, [_evidence(path, str(last.get("result_sha256") or "") or None)]


def _resource(label: str, path: Path) -> dict[str, str] | None:
    return {"label": label, "path": str(path.resolve()), "sha256": sha256_file(path)} if (
        path.is_file()
    ) else None


def _nc_grading_packet(settings: FactorySettings, topic: Mapping[str, Any]) -> dict[str, Any]:
    from .nc_funnel import grading_packet

    return grading_packet(settings, topic)


def _nc_grading_instruction(trigger: str = TRIGGER_VENUE_GRADE) -> str:
    from .nc_funnel import GRADE_INSTRUCTION
    from .nc_grading import PRE_WRITING_INSTRUCTION

    if trigger == TRIGGER_PRE_WRITING_GRADE:
        return GRADE_INSTRUCTION.replace("this manuscript looks like", "this research looks like") \
            + PRE_WRITING_INSTRUCTION
    return GRADE_INSTRUCTION


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
    grading = trigger in GRADE_TRIGGERS
    from . import target_stage as _stages

    nc_grading = grading and _stages.admitted_stage(topic) == _stages.NC_AIM
    if nc_grading:
        from .nc_funnel import calibration_resource

        resources.extend(item for item in [calibration_resource(paths)] if item is not None)
    cap = trigger in {TRIGGER_REVIEW_ROUNDS, "owner_review_rounds_exhausted"}
    options = ["retarget_or_short_format", "freeze"]
    candidates = []
    zone = (topic.get("delivered_revision") or {}).get("target_zone")
    if grading:
        candidates = _run_paper_command(paths, settings, ["venue", "alternatives"],
                                        json_flag=False)["venues"]
    elif cap and (registry / "verified-venues.yaml").is_file():
        target = detail.get("target_journal") or (direction_context or {}).get("target_journal")
        args = ["venue", "alternatives"]
        if zone:
            args.extend(["--zone", str(zone)])
        if target:
            args.extend(["--exclude", str(target)])
        candidates = _run_paper_command(paths, settings, args, json_flag=False)["venues"]
    if not grading and not cap:
        options.insert(0, "targeted_core_analysis")
    routine = _routine_names(topic)
    exclude = research_provider(db, settings, campaign_id)
    work_log = Path(str(campaign.get("state_path") or "")) / "OWNER_LOG.md"
    if campaign.get("state_path") and work_log.is_file():
        # Owner mode: the owner's own log is the shortest account of the topic.
        evidence = [*evidence, _evidence(work_log)]
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
        **asset_library.packet_fields(paths, settings, domains=[str(topic.get("domain") or "")],
                                      topic=topic),
        "research_executor_provider": exclude,
        # Read by the router when only one model family is configured (same family,
        # different model).
        "producer_model": research_model(db, settings, campaign_id),
        "options": options,
        **({"delivered_revision": topic["delivered_revision"]} if topic.get("delivered_revision") else {}),
        **({"verified_alternatives": candidates,
            "short_format_value": None if zone or grading else "short_format"} if cap or grading else {}),
        **({"grading": {**_nc_grading_packet(settings, topic),
                        "point": "pre_writing" if trigger == TRIGGER_PRE_WRITING_GRADE
                        else "after_review"}}
           if nc_grading else {}),
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
            + (" For this exhausted cycle choose freeze, or set venue_or_format to an exact "
               + ("verified_alternatives journal name. Read the operator revision and assess subject fit."
                  if zone else "verified_alternatives journal name or short_format. Preserve the target cap.")
               if cap else "")
            + (" The manuscript cleared review. Use retarget_or_short_format to record the "
               "chosen exact journal name, including when keeping the current target. Set "
               "retarget.achieved_band to \"zones_1_2\" or \"zones_3_4\" and choose a verified "
               "journal in that band. Assess the actual increment over the closest recent work, "
               "data scale, controls, external validation and strength of the result. Explain "
               "this grading with specific evidence in rationale, and explain journal scope in "
               "retarget.why_fits. Zones 3–4 are successful delivery when the evidence supports "
               "that band. If no suitable verified journal exists in the supported band, "
               "use freeze with no_eligible_venue and a concrete reopen condition. "
               "Preserve the review, writing and figure standards." if grading and not nc_grading
               else "")
            + (_nc_grading_instruction(trigger) if nc_grading else "")
        ),
        input_path=str(packet_path),
        skill_path=DIRECTION_SKILL,
        runner=dispatch_runner(settings, DIRECTION_TASK_TYPE, DIRECTION_ROUTING_REASON,
                               "frontier"),
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
    reopen_when: Any = None,
) -> None:
    from .reopen import ReopenConditionError, normalize_conditions

    ledger = _ledger(paths, settings)
    try:
        when = normalize_conditions(reopen_when)
    except ReopenConditionError as exc:
        # An unusable condition never blocks the freeze; the topic just will not reopen.
        when = []
        note = {**dict(note or {}), "reopen_when_invalid": str(exc)[:300]}
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
        decided_by=decided_by, reopen_conditions=conditions, reopen_when=when,
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
    if str(task.get("routing_reason") or "") == RELEASE_FIX_ROUTING:
        return "handled"  # the release pipeline re-checks the paper itself
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
                                   payload=payload, evidence=evidence,
                                   result_path=result_path, result_sha256=result_sha256)
    if role == "reviewer" and task_type == "paper_review" and str(
        task.get("routing_reason") or ""
    ) == "owner_recompute_review":
        return None  # the owner's recompute review loop (owner.py) takes the next step
    if role == "reviewer" and task_type == "paper_review":
        return _on_review_result(db, paths, settings, report, topic=topic, task=task,
                                 payload=payload, evidence=evidence)
    if campaign_on_hold(db, settings, str(topic["campaign_id"])):
        return "handled"
    return None


def _on_research_result(db, paths, settings, report, *, topic, task, payload, evidence,
                        result_path=None, result_sha256=None):
    from . import line_facts

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
            if verdict == "met":
                # A completed endpoint does not establish that decisive data were missing.
                reason_class = "unspecified"
            note = {"reason_class_inferred": True, "declared_reason_class": declared or None,
                    "primary_endpoint_verdict": verdict or None}
        declared_evidence = _freeze_evidence(gate_result)
        # A precheck that failed on the line's shared reference, while a named job is still
        # queued, or by less than the measurement's uncertainty is not frozen here.
        try:
            intercepted = line_facts.intercept_precheck_freeze(
                db, paths, settings, report, topic=topic, task=task, payload=payload,
                evidence=[*declared_evidence, *evidence], reason_class=reason_class,
                result_path=result_path, result_sha256=result_sha256,
            )
        except Exception as exc:  # noqa: BLE001 - the requested freeze still applies
            intercepted = None
            report.errors.append(f"Line-fact check of {task_id} failed: {exc}")
        if intercepted is not None:
            return intercepted
        if not declared_evidence:
            note = {**(note or {}), "evidence_missing": True}
        _freeze(
            db, paths, settings, report, topic_id=topic_id, reason_class=reason_class,
            evidence=[*declared_evidence, *evidence], decided_by=task_id,
            reopen_conditions=gate_result.get("reopen_conditions"), note=note,
            reopen_when=gate_result.get("reopen_when"),
        )
        return "handled"
    try:
        line_facts.on_progress(db, paths, settings, report, topic=topic, payload=payload)
    except Exception as exc:  # noqa: BLE001 - advisory: the block stays until released
        report.errors.append(f"Line-block progress check of {task_id} failed: {exc}")
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

    used, limit = outcome.get("rounds_for_target"), outcome.get("max_rounds_per_target")
    if outcome.get("status") == "blocked" and limit and used is not None and used >= limit:
        return TRIGGER_REVIEW_ROUNDS
    for trigger, matches in REVIEW_TRIGGER_ORDER:
        if matches(outcome):
            return trigger
    return None


def _schedule_cap(db, paths, settings, report, topic, cap, evidence, reasons=None):
    campaign = str(topic["campaign_id"])
    pending = pending_decision(db, campaign)
    if pending:
        return pending
    path = paths.data / cap["decision_record"]
    if not path.is_file() or sha256_file(path) != cap["decision_record_sha256"]:
        raise DeliveryError("the exhausted target's last decision cannot be verified")
    task = schedule_direction_decision(
        db, paths, settings, report, topic=topic, trigger=TRIGGER_REVIEW_ROUNDS,
        source_task_id=cap["decision_record_sha256"], evidence=[*evidence, _evidence(path)],
        direction_context=cap["direction_context"], reasons=reasons, detail=dict(cap))
    if not task:
        raise DeliveryError("could not schedule the exhausted target's direction decision")
    return task


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
    if trigger == TRIGGER_REVIEW_ROUNDS and record_path.is_file():
        last = json.loads(record_path.read_text())
        outcome = {**outcome, "target_journal": last.get("target_journal"),
                   "direction_context": {**(outcome.get("direction_context") or {}),
                                         "latest_decision": last.get("merged")}}
    schedule_direction_decision(
        db, paths, settings, report, topic=topic, trigger=trigger,
        source_task_id=str(task["task_id"]), evidence=evidence,
        direction_context=outcome.get("direction_context")
        if isinstance(outcome.get("direction_context"), Mapping) else None,
        detail={key: outcome.get(key) for key in (
            "next_action", "status", "review_stalled", "rounds_for_target",
            "max_rounds_per_target", "decision_record", "decision_record_sha256", "paper_id", "target_journal",
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


def submission_conditions(topic: Mapping[str, Any]) -> list[dict[str, str]]:
    """Admission conditions due ``before_submission`` (open blockers of the handoff)."""

    admission = topic.get("admission") if isinstance(topic.get("admission"), Mapping) else {}
    return [item for item in admission_conditions(admission)
            if item.get("due") == "before_submission"]


def queue_ready_topic(db, paths, settings, report, *, topic, task, outcome, payload, evidence):
    """Review ready: ``ready_queue``, pause the campaign (slot released), queue delivery."""

    ledger = _ledger(paths, settings)
    topic_id = str(topic["topic_id"])
    task_id = str(task["task_id"])
    paper_id = str(outcome.get("paper_id") or payload.get("paper_id") or topic.get("paper_id")
                   or "").strip() or None
    from . import target_stage

    if target_stage.tier2_topic(topic):
        journal = outcome.get("target_journal")
        decision_record = outcome.get("decision_record")
        if isinstance(decision_record, str) and decision_record:
            decision_path = paths.data / decision_record
            if decision_path.is_file():
                journal = json.loads(decision_path.read_text()).get("target_journal") or journal
        grade = topic.get("venue_grade") or {}
        from .nc_grading import GRADED_BEFORE_WRITING

        # Graded before writing: review ready goes straight to the queue (no re-check).
        if grade.get("point") not in GRADED_BEFORE_WRITING and (
                not grade or grade.get("journal") != journal):
            schedule_direction_decision(
                db, paths, settings, report, topic=topic, trigger=TRIGGER_VENUE_GRADE,
                source_task_id=task_id, evidence=evidence,
                detail={"paper_id": paper_id, "target_journal": journal,
                        "review_outcome": dict(outcome)},
            )
            return
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
        detail={"paper_id": paper_id, "auto_handoff": settings.program.auto_handoff,
                "submission_conditions": submission_conditions(topic)},
        updates={"handoff": {"status": "queued", "attempts": 0, "paper_id": paper_id,
                             "queued_at": utc_now(), "review_task_id": task_id,
                             # The owner confirms these before a submission handler is set.
                             "submission_conditions": submission_conditions(topic)},
                 "release": {"status": "pending", "stage": "check", "attempts": {},
                             "writer_rounds": 0, "seq": int((topic.get("release") or {}).get("seq", -1)) + 1,
                             **{k: v for k, v in (topic.get("release") or {}).items()
                                if k == "adopted_revision_package"}}},
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
        from . import line_facts

        try:
            line_facts.after_decision(db, paths, settings, report, topic_id=topic_id,
                                      trigger=trigger, outcome=outcome)
        except Exception as exc:  # noqa: BLE001 - advisory
            report.errors.append(f"Line-block update after {task_id} failed: {exc}")
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
    if not problems and "verified_alternatives" in packet:
        allowed = {entry["journal"] for entry in packet["verified_alternatives"]}
        if packet.get("short_format_value") == "short_format":
            allowed.add("short_format")
        if decision["choice"] not in packet["options"] or (
            decision["choice"] == "retarget_or_short_format" and
            decision["retarget"]["venue_or_format"] not in allowed
        ):
            problems.append("choose an exact verified journal" if trigger in GRADE_TRIGGERS
                            else "choose a verified alternative, short_format or freeze")
    grade = None
    if not problems and trigger in GRADE_TRIGGERS:
        from .target_stage import venue_grade

        if decision["choice"] == "freeze":
            if decision["freeze"]["reason_class"] != "no_eligible_venue":
                problems.append("acceptance grading may freeze only when no verified journal fits")
        else:
            from .target_stage import admitted_stage

            stage = admitted_stage(topic)
            grade = venue_grade(decision, packet["verified_alternatives"], stage=stage,
                                settings=settings)
            if grade is not None and stage == "nc_aim":
                from .nc_grading import POINT_AFTER_REVIEW, POINT_PRE_WRITING, venue_format

                grade = {**grade, "point": POINT_PRE_WRITING
                         if trigger == TRIGGER_PRE_WRITING_GRADE else POINT_AFTER_REVIEW,
                         **({"format": form} if (form := venue_format(
                             paths, grade["journal"])) else {})}
            if grade is None:
                problems.append("the selected journal must be verified and match retarget.achieved_band"
                                + (" (NC band: the scorecard, calibration match and confidence "
                                   "must support it; see grading.rules)" if stage == "nc_aim"
                                   else ""))
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
    if grade is not None:
        detail = packet["trigger"]["detail"]
        record_topic_note(
            ledger, topic_id, db=db, event_type="venue_grade_decided", reason=grade["achieved_band"],
            decided_by=task_id, detail=grade, evidence=[*packet["evidence"], *evidence],
            updates={"venue_grade": grade}, key=f"venue_grade:{task_id}",
        )
        if trigger == TRIGGER_PRE_WRITING_GRADE:
            from .nc_grading import resume_writing

            seat = resume_writing(db, paths, settings, report, topic=topic,
                                  source_task_id=str(record["source_task_id"]), detail=detail,
                                  grade=grade, reason="graded")
            return finish("venue_graded_before_writing", {"venue_grade": grade, "seat": seat})
        if grade["journal"] == detail.get("target_journal"):
            queue_ready_topic(
                db, paths, settings, report, topic={**topic, "venue_grade": grade},
                task={"task_id": record["source_task_id"]},
                outcome={**detail["review_outcome"], "target_journal": grade["journal"]},
                payload={"paper_id": detail.get("paper_id")}, evidence=packet["evidence"],
            )
            return finish("venue_retained", {"venue_grade": grade})
    # The first acceptance grade gets one journal choice even after exploratory retargets.
    first_grade = grade is not None and not topic.get("venue_grade")
    rejection = _reject_choice(choice, used={} if first_grade else used,
                               limits={choice: 1} if first_grade else limits,
                               decision=decision, campaign=campaign, settings=settings)
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
                decided_by=task_id, reopen_conditions=freeze.get("reopen_conditions"),
                reopen_when=freeze.get("reopen_when"))
        return finish("frozen", {"choice": choice, "reason_class": freeze["reason_class"]})
    source_task_id = str(record["source_task_id"])
    if trigger == TRIGGER_REVIEW_ROUNDS and not db.task(source_task_id):
        source_task_id = str((topic.get("handoff") or {}).get("review_task_id") or source_task_id)
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
    from . import owner as owner_mode

    if owner_mode.applies(settings, campaign):
        # The owner runs the chosen step itself, in its own session.
        owner_mode.reset_streak(db, str(campaign["campaign_id"]), reason=decision_task_id)
        owner_mode.reset_review_cycle(db, str(campaign["campaign_id"]), reason=decision_task_id)
        owner_mode.enqueue_seat(
            db, settings, None, campaign=campaign, parent=source or None,
            note=(
                f"Direction decision {decision_task_id} (input path) continues the topic with "
                f"exactly one targeted analysis: {analysis['name']}. Expected to change: "
                f"{analysis['expected_to_change']}. Data: {analysis['data']}. Success "
                f"criterion: {analysis['success_criterion']}. Budget: "
                f"{analysis['budget_seconds']} Agent seconds. Report it against the criterion "
                "honestly, including a negative result; keep the pre-registered endpoint; then "
                "write up or freeze as the evidence says."
            ),
            routing_reason=TARGETED_ROUTING, input_path=str(input_path), task_id=task_id,
        )
        return task_id
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
        runner=dispatch_runner(settings, "evidence_remediation", TARGETED_ROUTING, "balanced"),
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
    from .target_stage import tier2_topic

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
        f"{routine[0]!r} and mark target_escalation as superseded by the fallback. Before "
        f"switching to it run `paper-writing program check-fallback --paper-id <id>` (add "
        f"`--fallback-evidence <file>` to complete an older record); it must pass."
        if str(topic.get("target_tier") or "") == "escalation" and routine and not tier2_topic(topic)
        else ""
    )
    objective = (
        f"handoff_kind=retarget. Retarget the manuscript to {target} "
        f"(direction decision: {retarget['why_fits']}). Refresh and check the team rejection "
        "history (`paper-writing journal-history sync`/`check`) and the venue policy before "
        "changing the target. Look the target up in the local registry of verified journals "
        "first (`paper-writing venue lookup --journal <name>`; verified ones: `paper-writing "
        "venue alternatives`). Otherwise verify item by item and record, with sources, the new "
        "target's indexing (SCIE), its 2025 CAS major-category zone and every mandatory author "
        "charge (APC, page charges, colour charges, submission fees) before registering it; "
        "\"no APC\" on an open-access page does not rule out a page charge. A publisher page "
        "that refuses the request (HTTP 403/406) is recorded with `paper-writing venue "
        "mark-pending` and is no reason to stop for a human: continue with the target pending "
        "verification or choose a verified alternative. Convert the canonical "
        "manuscript to the new venue or format, and keep every claim inside the frozen "
        "evidence." + fallback_note
    )
    domain = str(campaign["domain"])
    from . import owner as owner_mode

    if owner_mode.applies(settings, campaign):
        task_id = f"{decision_task_id}:retarget"
        owner_mode.reset_streak(db, str(campaign["campaign_id"]), reason=decision_task_id)
        owner_mode.reset_review_cycle(db, str(campaign["campaign_id"]),
                                      reason=decision_task_id, keep_passed=True)
        owner_mode.enqueue_seat(
            db, settings, None, campaign=campaign, parent=db.task(source_task_id),
            note=f"Direction decision {decision_task_id} (input path): " + objective,
            routing_reason=RETARGET_ROUTING, input_path=str(input_path), task_id=task_id,
        )
        return task_id
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
                runner=dispatch_runner(settings, "paper_revision", RETARGET_ROUTING, "frontier"),
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
            runner=dispatch_runner(settings, "paper_readiness", RETARGET_ROUTING, "frontier"),
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
    if trigger == TRIGGER_PRE_WRITING_GRADE:
        # No grade could be taken: writing goes on; the review-time grade is the fallback.
        from .nc_grading import resume_writing

        packet = _verified_packet(Path(str(record["packet_path"])))
        _set_decision(db, task_id, {**record, "status": "resolved", "outcome": reason,
                                    "resolved_at": utc_now()})
        resume_writing(db, paths, settings, report, topic=topic,
                       source_task_id=str(record["source_task_id"]),
                       detail=dict(packet["trigger"].get("detail") or {}), grade=None,
                       reason=reason)
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
    parked = parked_program_projects(paths)
    for topic in topics_by_status(ledger.read(), *FREEZABLE_STATUSES):
        if str(topic.get("program_project_id") or "") in parked:
            # A paused program project: its topics wait without budget/deadline decisions.
            continue
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
        if (
            used + 1 > maximum
            and not db.has_active_tasks(campaign_id)
            # A continuation parked on remote jobs is decided after they finish.
            and not db.has_awaiting_remote_tasks(campaign_id)
        ):
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
        blocked = _research_block(db, campaign, latest)
        if blocked is not None:
            payload, evidence = blocked
            schedule_direction_decision(
                db, paths, settings, report, topic=topic, trigger=TRIGGER_RESEARCH_BLOCKED,
                source_task_id=str(latest["task_id"]), evidence=evidence,
                reasons=_blocked_reasons(payload),
                detail={"task_status": "needs_human", "task_type": latest.get("task_type")},
            )
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
    only. Credentials (``ARA_PAPER_MANAGE_API_URL``, ``ARA_PAPER_MANAGE_API_KEY``) come
    from the environment or ``[program] credentials_file`` (:func:`pipeline_credentials`)
    and are passed to this child process only.
    """

    credentials, _ = pipeline_credentials(settings, DELIVERY_ENVIRONMENT)
    return _run_paper_command(
        paths, settings, ["program", "deliver", "--paper-id", paper_id],
        environment={**credentials, "OPENLABS_ENABLE_EXTERNAL_WRITES": "1"},
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


# Lines the resource guard (bin/openlabs-resource-guard: container_guard.py, gpu_guard.py)
# writes to stderr before it starts the command. They say the guard admitted the command,
# not why it failed, and on 2026-11-20 a delivery failure was recorded as nothing but these
# lines ("blocked by the resource guard") while the real error was elsewhere.
_GUARD_BANNERS = ("OpenLabs container guard:", "OpenLabs resource guard:",
                  "OpenLabs GPU guard: task-type=")


def command_error_detail(stdout: str | None, stderr: str | None, *, limit: int = 1000) -> str:
    """Why a paper-writing command failed: its JSON ``error``, else its own output.

    The resource-guard admission banners are dropped; a guard refusal (``OpenLabs GPU
    guard: STOP: ...``) is kept. Empty output says so instead of quoting the banner.
    """

    parts: list[str] = []
    text = (stdout or "").strip()
    if text:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, Mapping) and payload.get("error"):
            parts.append(str(payload["error"]).strip()[-700:])
        else:
            parts.append(text[-700:])
    own = "\n".join(line for line in (stderr or "").splitlines()
                    if line.strip() and not line.strip().startswith(_GUARD_BANNERS)).strip()
    if own:
        parts.append(own[-700:])
    if not parts:
        guarded = any(line.strip().startswith(_GUARD_BANNERS)
                      for line in (stderr or "").splitlines())
        return ("no output from the command" + (" (only the resource guard's admission banner, "
                                                  "i.e. the guard let it run)" if guarded else ""))
    return " | ".join(parts)[-limit:]


def _run_paper_command(paths: WorkspacePaths, settings: FactorySettings,
                       arguments: list[str],
                       environment: Mapping[str, str] | None = None, *,
                       json_flag: bool = True, timeout: int = 1_800,
                       accept: tuple[int, ...] = (0,)) -> dict[str, Any]:
    """Run one paper-writing command and return its JSON object.

    ``environment`` is added for this child process only. Commands without a
    ``--json`` option (``zenodo``, ``review unified-run``) print JSON anyway.
    """

    command = [*settings.program.paper_writing_command, *arguments, "--root", str(paths.data)]
    if json_flag:
        command.append("--json")
    try:
        completed = subprocess.run(
            command, cwd=str(paths.data),
            env={**os.environ, **dict(environment or {}), "OPENLABS_REVIEW_DATA": str(paths.data)},
            capture_output=True,
            text=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DeliveryError(f"{' '.join(command[:3])} could not run: {exc}") from exc
    if completed.returncode not in accept:
        raise DeliveryError(f"exit {completed.returncode}: "
                            f"{command_error_detail(completed.stdout, completed.stderr)}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise DeliveryError("paper-writing returned no JSON result") from exc
    if not isinstance(payload, dict):
        raise DeliveryError("paper-writing returned a non-object result")
    return payload


DELIVERY_ENVIRONMENT = ("ARA_PAPER_MANAGE_API_URL", "ARA_PAPER_MANAGE_API_KEY")
ZENODO_TOKEN_ENVIRONMENT = "ZENODO_ACCESS_TOKEN"
# The only names ``[program] credentials_file`` may supply (anything else in it is ignored).
PIPELINE_CREDENTIAL_NAMES = (*DELIVERY_ENVIRONMENT, ZENODO_TOKEN_ENVIRONMENT)


def _credentials_file_values(path: Path) -> tuple[dict[str, str], str | None]:
    """Allowed NAME=VALUE pairs of a credentials file, or ``({}, why)`` when it is refused.

    Refused: missing, not a regular file (symlinks included), owned by another user, or
    readable/writable by group or others. Values never appear in the reason.
    """

    try:
        info = path.lstat()
    except OSError:
        return {}, "credentials_file_missing"
    if not stat_module.S_ISREG(info.st_mode):
        return {}, "credentials_file_not_regular"
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        return {}, "credentials_file_foreign_owner"
    if info.st_mode & 0o077:
        return {}, "credentials_file_mode_not_0600"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}, "credentials_file_unreadable"
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if name in PIPELINE_CREDENTIAL_NAMES and value:
            values[name] = value
    return values, None


def pipeline_credentials(settings: FactorySettings,
                         names: tuple[str, ...]) -> tuple[dict[str, str], str | None]:
    """``names`` -> value for the release pipeline's child processes.

    The tick's environment first, then ``[program] credentials_file``. The values are
    returned for one child process's environment and never written into ``os.environ``
    (research seats inherit the tick's environment). The second item says why the file
    was refused (``None`` when it was read or is not configured).
    """

    values = {name: os.environ[name].strip() for name in names
              if os.environ.get(name, "").strip()}
    refused = None
    configured = settings.program.credentials_file
    if configured and len(values) < len(names):
        from_file, refused = _credentials_file_values(Path(configured))
        for name in names:
            if name not in values and name in from_file:
                values[name] = from_file[name]
    return values, refused


def code_revision(paths: WorkspacePaths) -> str | None:
    """The orchestrator code's Git commit (the loop loads the code afresh every tick)."""

    try:
        completed = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(paths.code),
                                   capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    revision = completed.stdout.strip()
    return revision if completed.returncode == 0 and revision else None


# An exhausted release stage or delivery is tried again by itself when the code changed
# since it stopped (the two 2026-11-20 stops were both cured by a code fix and then
# needed a human `release-retry`): once per new revision, at most this many times per
# topic. Anything else that stopped still waits for a human.
RELEASE_CODE_RETRIES = 2


def _code_update_retry(db, paths, settings, ledger, topic) -> dict[str, Any] | None:
    """Reset an exhausted release/delivery after a code update; the updated topic or None."""

    release = dict(topic.get("release") or {})
    handoff = dict(topic.get("handoff") or {})
    release_stopped = release.get("status") == "exhausted"
    handoff_stopped = handoff.get("status") == "exhausted"
    if not (release_stopped or handoff_stopped):
        return None
    used = int(release.get("code_retries") or 0)
    if used >= RELEASE_CODE_RETRIES:
        return None
    current = code_revision(paths)
    if not current:
        return None
    stopped_at = [str(block.get("exhausted_code_revision") or "")
                  for block, stopped in ((release, release_stopped), (handoff, handoff_stopped))
                  if stopped]
    # Only a stop recorded with its revision, and only when every stopped part ran on an
    # older code than the current one.
    if not stopped_at or any(not item or item == current for item in stopped_at):
        return None
    topic_id = str(topic["topic_id"])
    by = "orchestrator:code_update"
    stage = str(release.get("stage") or "check")
    updates: dict[str, Any] = {}
    new_release = {**release, "code_retries": used + 1,
                   "seq": int(release.get("seq") or 0) + 1, "updated_at": utc_now()}
    if release_stopped:
        attempts = dict(release.get("attempts") or {})
        retry = {"at": utc_now(), "by": by, "reason": "code updated since the stop",
                 "stage": stage, "previous_status": release.get("status"),
                 "previous_attempts": dict(attempts), "previous_error": release.get("last_error"),
                 "from_revision": release.get("exhausted_code_revision"), "to_revision": current}
        attempts.pop(stage, None)
        new_release.update({"status": "pending", "attempts": attempts, "last_error": None,
                            "waiting_for": None, "waiting_detail": None,
                            "retries": [*list(release.get("retries") or []), retry][-10:]})
        if stage == "form_fix_writer":
            new_release["writer_rounds"] = 0
    updates["release"] = new_release
    if handoff_stopped:
        updates["handoff"] = {**handoff, "status": "queued", "attempts": 0,
                              "previous_error": handoff.get("last_error"), "last_error": None}
    record_topic_note(
        ledger, topic_id, db=db, event_type="release_retry", reason="code_updated",
        decided_by=by,
        detail={"paper_id": str(handoff.get("paper_id") or topic.get("paper_id") or ""),
                "stage": stage, "release_reset": release_stopped, "handoff_reset": handoff_stopped,
                "to_revision": current, "code_retry": used + 1,
                "code_retries_max": RELEASE_CODE_RETRIES},
        updates=updates, key=f"release_code_retry:{topic_id}:{current}",
    )
    return ledger.topic(topic_id)


def _registered_topic_paper(db, paths, topic):
    from .paper_figures import draft_paper_id
    from .program_reconcile import _paper_id

    campaign = db.campaign(str(topic.get("campaign_id") or ""))
    paper_id, _ = _paper_id(db, topic, campaign)
    if not paper_id and campaign:
        paper_id = draft_paper_id(paths, campaign)
    if paper_id and re.fullmatch(r"[\w.-]+", paper_id) and paper_id not in {".", ".."}:
        return paper_id
    return None


def queue_registered_ready(db, paths, settings, report, topic_id, *, automatic=False):
    """Queue a bound decision applied outside a factory review task."""
    from .target_stage import tier2_topic

    topic = find_topic(_ledger(paths, settings).read(), topic_id)
    if topic and topic.get("status") == "ready_queue":
        return {"topic_id": topic_id, "status": "ready_queue", "changed": False}
    if not topic or topic.get("status") != "in_review":
        raise DeliveryError(f"Topic {topic_id} is not in review")
    paper_id = _registered_topic_paper(db, paths, topic)
    if not paper_id:
        raise DeliveryError(f"Topic {topic_id} has no uniquely linked paper")
    campaign = str(topic.get("campaign_id") or "")
    if db.has_active_tasks(campaign) or pending_decision(db, campaign):
        raise DeliveryError(f"Topic {topic_id} has active work")
    status = run_release_status(paths, settings, paper_id)
    review = status["review"]
    # The one deliverability verdict (paper_writing.deliverable, B5); an older paper-writing
    # without it reports the same fields under review/frozen.
    verdict = status.get("deliverable") or {
        "frozen": status.get("frozen"), "decision_current": review.get("decision_current"),
        "review_mode": review.get("review_mode")}
    if (verdict.get("frozen") or not verdict.get("decision_current")
            or (automatic and verdict.get("review_mode") not in AUTO_QUEUED_REVIEW_MODES)):
        raise DeliveryError(f"Paper {paper_id} has no eligible current ready decision")
    if tier2_topic(topic) and (topic.get("venue_grade") or {}).get("journal") != status.get("target_journal"):
        raise DeliveryError(f"Paper {paper_id} needs a recorded acceptance grade")
    source = "registered-review:" + review["decision_sha256"]
    evidence = [_write_evidence(paths, topic_id, "registered-review", {
        "paper_id": paper_id, "version": status["version"], "review": review,
    })]
    queue_ready_topic(db, paths, settings, report, topic=topic, task={"task_id": source},
                      outcome={"paper_id": paper_id, "target_journal": status.get("target_journal")},
                      payload={}, evidence=evidence)
    return {"topic_id": topic_id, "paper_id": paper_id, "status": "ready_queue", "changed": True}


# Ready decisions applied outside a factory review task that the tick queues for delivery:
# offline resyntheses and presentation reviews (2026-11-23), both bound and re-validated.
AUTO_QUEUED_REVIEW_MODES = frozenset({"resynthesize", "presentation"})


def _queue_resynthesized(db, paths, settings, report):
    import yaml

    for topic in topics_by_status(_ledger(paths, settings).read(), "in_review"):
        paper_id = _registered_topic_paper(db, paths, topic)
        if not paper_id:
            continue
        for suffix in (".yaml", ".yml", ".json"):
            path = paths.data / "registry" / "papers" / (paper_id + suffix)
            if not path.is_file():
                continue
            try:
                record = yaml.safe_load(path.read_text())
            except (OSError, yaml.YAMLError) as exc:
                _info(report, "registered_review_waiting").append({
                    "topic_id": topic["topic_id"], "reason": f"Cannot read paper registry: {type(exc).__name__}",
                })
                break
            release = record.get("writing_release") if isinstance(record, Mapping) else None
            if (isinstance(release, Mapping) and release.get("status") == "ready"
                    and release.get("review_mode") in AUTO_QUEUED_REVIEW_MODES):
                try:
                    queue_registered_ready(db, paths, settings, report, topic["topic_id"], automatic=True)
                except DeliveryError as exc:
                    _info(report, "registered_review_waiting").append({
                        "topic_id": topic["topic_id"], "reason": str(exc),
                    })
            break


def _deliver_ready(db, paths, settings, report) -> None:
    program = settings.program
    ledger = _ledger(paths, settings)
    for topic in topics_by_status(ledger.read(), "ready_queue"):
        repair_id = (topic.get("delivery_repair") or {}).get("task_id")
        if repair_id and (db.task(repair_id) or {}).get("status") in IN_FLIGHT:
            continue
        if program.auto_handoff:
            topic = _code_update_retry(db, paths, settings, ledger, topic) or topic
        topic_id = str(topic["topic_id"])
        state = dict(topic.get("handoff") or {})
        status = str(state.get("status") or "queued")
        paper_id = str(state.get("paper_id") or topic.get("paper_id") or "").strip()
        entry = {"topic_id": topic_id, "paper_id": paper_id or None}
        release_status = str((topic.get("release") or {}).get("status") or "")
        if status == "exhausted" or (status == "delivered" and release_status != "commit_pending"):
            continue
        if not program.auto_handoff:
            _info(report, "handoffs").append({**entry, "outcome": "queued_auto_handoff_off"})
            continue
        if not paper_id:
            _info(report, "handoffs").append({**entry, "outcome": "blocked_paper_id_unknown"})
            db.record_event_once("topic", topic_id, "handoff_blocked",
                                 {"reason": "paper_id_unknown"}, event_key="paper_id_unknown")
            continue
        _ReleasePipeline(db, paths, settings, report, ledger, topic, paper_id).advance()


# --------------------------------------------------------------------------- delivery chain state
#
# Every paper between review ``ready`` and a finished delivery is in exactly one of:
#   in_progress  - the pipeline takes its next step this or the next tick (or a writer /
#                  full review it started is running);
#   auto_retry   - a step failed and is retried by itself (attempt n of a bounded number);
#   waiting      - it waits for a named condition outside the pipeline (credentials, a
#                  setting, an external service);
#   needs_human  - it stopped and the entry says what a person has to do.
# Nothing is left without one of these; a state the classifier does not know is reported
# as needs_human ("unrecognized") and as a tick error, so a new failure mode cannot sit
# unowned.

# waiting_for -> (state, condition or action). Conditions that only a person can
# satisfy are needs_human; the rest are waiting.
_WAIT_STATES: dict[str, tuple[str, str]] = {
    "control_plane": ("waiting", "restore delivery inputs or environment; the next tick checks again: {issues}"),
    "waiting_credentials": ("waiting", "credentials {missing}, in the scheduler environment or "
                                       "[program] credentials_file{file}"),
    "git_identity_missing": ("waiting", "a Git identity: [program.git] user_name/user_email in "
                                        "the instance settings, or user.name/user.email in the "
                                        "data repository"),
    "auto_release_off": ("waiting", "[program] auto_release = true (or run the Zenodo step "
                                    "by hand)"),
    "no_standing_authorization": ("waiting", "registry/settings.yaml#support_publication."
                                             "standing_production_release_authorization: true"),
    "support_release_none": ("waiting", "[program] support_release = \"zenodo\" (the paper has a "
                                        "support record but deposits are switched off)"),
    "paper_not_found": ("waiting", "the paper's registry record in the data repository or in "
                                   "the topic's campaign workspace"),
    # A tier-2 topic (target_stage.tier2_topic) is delivered only after a lead direction
    # decision (trigger review_venue_grade) has recorded the acceptance grade for the current
    # target journal in the topic's venue_grade; the review outcome schedules that decision.
    "venue_grade_pending": ("waiting", "a recorded acceptance grade (topic venue_grade) for the "
                                       "current target journal from the review_venue_grade "
                                       "direction decision"),
    "needs_owner": ("needs_human", "fix the listed delivery-exit problems by hand (they are not "
                                   "text fixes a writer may make): {issues}"),
    "layout_unsupported": ("needs_human", "move the workspace paper under papers/<paper_id>/ (or "
                                          "decide to drop it); adopt refuses its layout"),
    "support_record_exists": ("needs_human", "decide on the existing support record "
                                             "(support_release = \"none\" cannot waive it)"),
    "manuscript_cites_deposit": ("needs_human", "remove the Zenodo deposit from the "
                                                "data-availability text or switch support_release "
                                                "back to \"zenodo\""),
    "adopt_blocked": ("needs_human", "read the adopt refusal in the topic history and lay the "
                                     "workspace paper out so it can be adopted"),
    "support_waiver_blocked": ("needs_human", "read the waiver refusal in the topic history and "
                                              "decide on the support record"),
}


def _format_condition(template: str, detail: Mapping[str, Any]) -> str:
    missing = (", ".join(str(item) for item in detail.get("missing") or [])
               or "see the topic history")
    issues = "; ".join(str(item) for item in detail.get("issues") or [])[:400] or "see the history"
    refused = str(detail.get("credentials_file") or "")
    text = template.format(missing=missing, issues=issues,
                           file=f" (file refused: {refused})" if refused else "")
    hint = str(detail.get("hint") or "").strip()
    return f"{text} ({hint})" if hint and hint not in text else text


def _retry_hint(paper_id: str) -> str:
    return (f"then `python -m openlabs program release-retry --paper-id {paper_id} --by <name> "
            "--reason <what was fixed>` (a code fix merged to main is retried automatically, "
            f"at most {RELEASE_CODE_RETRIES} times)")


def delivery_chain_state(db: FactoryDB, settings: FactorySettings,
                         topic: Mapping[str, Any]) -> dict[str, Any] | None:
    """The delivery-chain state of one topic (None: not in the chain, or finished)."""

    program = settings.program
    status = str(topic.get("status") or "")
    release = dict(topic.get("release") or {})
    handoff = dict(topic.get("handoff") or {})
    paper_id = str(handoff.get("paper_id") or topic.get("paper_id") or "") or None
    base = {"topic_id": str(topic.get("topic_id") or ""), "paper_id": paper_id,
            "stage": release.get("stage") or None}
    release_status = str(release.get("status") or "")
    handoff_status = str(handoff.get("status") or "queued")
    if status == "in_review" and release_status == "returned_to_review":
        campaign_id = topic.get("campaign_id")
        pending = pending_decision(db, str(campaign_id)) if campaign_id else None
        if pending:
            return {**base, "state": "in_progress", "owner": pending,
                    "detail": "awaiting direction decision"}
        if release.get("direction_task_id"):
            # The direction controller owns retries, the chosen successor, and freeze.
            return None
        # The pipeline handed the paper to a full review; that review task owns it.
        tasks = [str((entry.get("detail") or {}).get("review_task_id") or "")
                 for entry in topic.get("history") or []
                 if entry.get("kind") == "release_returned_to_review"]
        task_id = next((item for item in reversed(tasks) if item), "")
        task_status = str((db.task(task_id) or {}).get("status") or "missing") if task_id else ""
        if task_status in IN_FLIGHT or task_status == "succeeded":
            return {**base, "state": "in_progress", "owner": task_id,
                    "detail": f"full release review {task_status}"}
        return {**base, "state": "needs_human",
                "action": (f"the full review the pipeline queued ({task_id or 'none'}) ended "
                           f"{task_status or 'without a task'}; review the paper, or run "
                           f"`program release-retry --paper-id {paper_id}` if it is ready and "
                           "current")}
    if status != "ready_queue":
        return None
    if handoff_status == "delivered" and release_status != "commit_pending":
        return None
    if not program.auto_handoff:
        return {**base, "state": "waiting", "condition": "[program] auto_handoff = true"}
    if not paper_id:
        return {**base, "state": "needs_human",
                "action": "record the paper_id of this ready topic (handoff.paper_id)"}
    attempts = dict(release.get("attempts") or {})
    if handoff_status == "exhausted":
        return {**base, "stage": "deliver", "state": "waiting",
                "condition": ("resolve the delivery error "
                           f"({str(handoff.get('last_error') or '')[:300]}); "
                           f"{_retry_hint(paper_id)}")}
    if release_status == "exhausted":
        if release.get("stage") == "form_fix_writer" and release.get("unresolved_manuscript_issues"):
            return {**base, "state": "needs_human", "action": str(release["last_error"])}
        return {**base, "state": "waiting",
                "condition": (f"resolve the {release.get('stage')} error "
                           f"({str(release.get('last_error') or '')[:300]}); "
                           f"{_retry_hint(paper_id)}")}
    if handoff_status == "failed":
        return {**base, "stage": "deliver", "state": "auto_retry",
                "attempt": int(handoff.get("attempts") or 0),
                "max_attempts": program.handoff_max_attempts,
                "last_error": str(handoff.get("last_error") or "")[:300]}
    if release_status == "failed":
        stage = str(release.get("stage") or "")
        return {**base, "state": "auto_retry", "attempt": int(attempts.get(stage) or 0),
                "max_attempts": program.release_max_attempts,
                "last_error": str(release.get("last_error") or "")[:300]}
    if release_status == "commit_pending":
        return {**base, "state": "auto_retry", "detail": "delivered; the record commit is retried",
                "last_error": str(release.get("last_error") or "")[:300]}
    if release_status == "waiting" and release.get("writer_task_id"):
        task_id = str(release["writer_task_id"])
        task_status = str((db.task(task_id) or {}).get("status") or "missing")
        return {**base, "state": "in_progress", "owner": task_id,
                "detail": f"formal-fix writer {task_status}"}
    if release_status == "waiting":
        reason = str(release.get("waiting_for") or "")
        detail = dict(release.get("waiting_detail") or {})
        known = _WAIT_STATES.get(reason)
        if known is None:
            return {**base, "state": "needs_human", "unrecognized": True,
                    "action": (f"the pipeline waits for {reason or 'an unnamed condition'!r}, "
                               "which has no known owner; read the topic history")}
        state, template = known
        key = "condition" if state == "waiting" else "action"
        return {**base, "state": state, "waiting_for": reason,
                key: _format_condition(template, detail)}
    if release_status in {"", "pending", "running"} or (release_status == "done"
                                                        and handoff_status != "delivered"):
        return {**base, "state": "in_progress"}
    return {**base, "state": "needs_human", "unrecognized": True,
            "action": (f"unrecognized release state {release_status!r} / delivery "
                       f"{handoff_status!r}; read the topic history")}


def _writer_sources(root: Path, paper_id: str) -> dict[str, str]:
    """Bind proposed text replacements to this paper's current manuscript bytes."""
    directory = root / "papers" / paper_id / "manuscript"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", paper_id) or directory.resolve() != directory:
        return {}
    return {p.relative_to(root).as_posix(): sha256_file(p) for p in sorted(directory.rglob("*"))
            if p.suffix in {".tex", ".bib"} and p.resolve() == p and p.is_file()}


def _apply_writer_files(db, paths, task_id: str) -> int:
    """Import named text artifacts from an ingested bundle, checking their base and hash."""
    import tempfile
    from urllib.parse import unquote, urlparse

    task = db.task(task_id) or {}
    packet_path = task.get("input_path")
    bundle_path = db.result_bundle_path(task_id)
    if not packet_path or not bundle_path:
        return 0
    packet = _read_object(Path(packet_path))
    sources = packet.get("source_sha256") or {}
    if not sources:
        return 0
    bundle = Path(bundle_path)
    paper = paths.data / "papers" / packet["paper_id"] / "manuscript"
    changes = []
    for artifact in _read_object(bundle).get("artifacts") or []:
        name = str(artifact.get("artifact_id") or "")
        if not name.startswith("edit-"):
            continue
        targets = [relative for relative in sources
                   if name == "edit-" + hashlib.sha256(relative.encode()).hexdigest()[:16]]
        if len(targets) != 1:
            raise ReleaseError("Unrecognized delivery text artifact")
        relative = targets[0]
        target = paths.data / relative
        uri = urlparse(str(artifact.get("uri") or ""))
        origin = Path(unquote(uri.path)).resolve()
        if (target.resolve() != target or not target.is_relative_to(paper)
                or uri.scheme != "file" or uri.netloc or not origin.is_relative_to(bundle.parent / "artifacts")
                or not origin.is_file() or origin.stat().st_size > 4 * 1024 * 1024
                or sha256_file(origin) != artifact.get("sha256")):
            raise ReleaseError("Unsafe or changed delivery text artifact")
        current = sha256_file(target)
        if current == artifact["sha256"]:
            continue
        if current != sources[relative]:
            raise ReleaseError("Delivery writer base changed: " + relative)
        changes.append((target, origin.read_bytes()))
    for target, content in changes:
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as output:
            output.write(content)
        os.chmod(output.name, target.stat().st_mode)
        os.replace(output.name, target)
    return len(changes)


def _repair_delivery(db, paths, settings, report) -> None:
    """Give a stopped topic two scoped repair attempts under its original gates.

    The repair is an author-side text fix (task class ``ordinary``, role ``writer``), so no
    model family is excluded: the cross-family rule binds reviews and decisions, which the
    router derives itself (``QuotaRouter._excluded_provider``), and the controller rechecks
    every original gate afterwards. Until 2026-11-24 the seat excluded ``anthropic`` (left
    over from the 2026-11-20 Claude suspension, now expired), although Claude Opus writes
    the manuscripts (user 2026-11-19).
    """
    if not settings.program.auto_handoff or not settings.program.auto_release:
        return
    ledger = _ledger(paths, settings)
    for topic in ledger.read().get("topics") or []:
        item = delivery_chain_state(db, settings, topic)
        repair = topic.get("delivery_repair") or {}
        if not item or item["state"] != "needs_human":
            continue
        topic_id = topic["topic_id"]
        used = int(repair.get("attempt") or 0)
        task_id = repair.get("task_id")
        task = db.task(task_id) if task_id else None
        if task and task["status"] in IN_FLIGHT:
            continue
        if topic.get("status") == "in_review" and item.get("paper_id"):
            try:
                status = run_release_status(paths, settings, item["paper_id"])
                if (status.get("review") or {}).get("exhausted_review"):
                    result = _retry_returned_review(
                        db, paths, settings, ledger, topic, paper_id=item["paper_id"],
                        by=RELEASE_DECIDER, reason="recover exhausted release review", status=status)
                    _info(report, "releases").append(result)
                    continue
            except DeliveryError as exc:
                _info(report, "delivery_repairs").append({"topic_id": topic_id, "error": str(exc)})
        if task and task["status"] == "succeeded" and not repair.get("checked"):
            try:
                _apply_writer_files(db, paths, task_id)
            except (ReleaseError, OSError, ValueError) as exc:
                _info(report, "delivery_repairs").append({"task_id": task_id, "error": str(exc)})
            record_topic_note(ledger, topic_id, db=db, event_type="delivery_repair_checked",
                              reason="recheck_original_gates", decided_by=RELEASE_DECIDER,
                              updates={"delivery_repair": {**repair, "checked": True}},
                              detail={"task_id": task_id}, key=f"delivery_repair_checked:{task_id}")
            stopped = {"failed", "exhausted"}
            if item.get("paper_id") and (topic.get("status") == "in_review"
                    or (topic.get("release") or {}).get("status") in stopped
                    or (topic.get("handoff") or {}).get("status") in stopped):
                try:
                    retry_release(db, paths, settings, paper_id=item["paper_id"],
                                  by="delivery-repair", reason=f"Recheck after {task_id}")
                except DeliveryError as exc:
                    _info(report, "delivery_repairs").append({"task_id": task_id, "error": str(exc)})
            continue
        if item.get("stage") != "form_fix_writer":
            continue
        if used >= 2:
            _info(report, "delivery_repairs").append({"topic_id": topic_id, "outcome": "needs_human",
                                                     "attempts": used, "action": item["action"]})
            continue
        domain = str(topic.get("domain") or "")
        task_id = f"delivery-repair:{topic_id}:{used + 1}"
        if db.task(task_id) is None:
            paper_id = str(item.get("paper_id") or "")
            packet_path = _control_root(paths) / "release-packets" / _token(topic_id) / f"repair-{used + 1}.json"
            atomic_write_json(packet_path, {"paper_id": paper_id, "canonical_root": str(paths.data),
                                            "source_sha256": _writer_sources(paths.data, paper_id),
                                            "error": item["action"]})
            db.enqueue_task(task_id=task_id, input_path=str(packet_path), campaign_id=_release_campaign(db, settings, domain),
                            domain=domain, task_type=RELEASE_FIX_TASK_TYPE,
                            objective=(f"Repair delivery for topic {topic_id}, paper {item.get('paper_id')}, "
                                       f"stage {item.get('stage')}. Action: {item['action']}. "
                                       "Inspect the release history and repair only paper files or public "
                                       "support registration. Use registered declaration defaults and actual "
                                       "runtime evidence. If a human decision is required, return the "
                                       "specific blocker. Read canonical_root from the input packet. Return each changed "
                                       "TeX or Bib file as an artifact with ID edit- followed by the first 16 "
                                       "hex digits of SHA-256 of its registry-relative UTF-8 path. "
                                       "Preserve scientific results and review bindings. "
                                       "Never edit the topic ledger, database, configuration, credentials "
                                       "or attestations. Do not publish, submit, assign a handler, or "
                                       "invoke release commands. The controller rechecks all gates."),
                            runner=dispatch_runner(settings, RELEASE_FIX_TASK_TYPE, RELEASE_FIX_ROUTING, "cheap"),
                            routing_reason=RELEASE_FIX_ROUTING,
                            agent_role="writer", session_mode="fresh", max_attempts=1,
                            max_wall_seconds=min(7200, settings.max_task_wall_seconds),
                            **default_task_resources(settings).to_dict())
            report.enqueued.append(task_id)
        repair = {"task_id": task_id, "attempt": used + 1, "stage": item.get("stage")}
        record_topic_note(ledger, topic_id, db=db, event_type="delivery_repair_scheduled",
                          reason="delivery_needs_human", decided_by=RELEASE_DECIDER,
                          updates={"delivery_repair": repair}, detail={**repair, "action": item["action"]},
                          key=task_id)


def report_delivery_chain(db, paths, settings, report) -> None:
    """``program.delivery_chain`` (every paper in the chain) and ``delivery_stuck``."""

    document = _ledger(paths, settings).read()
    chain: list[dict[str, Any]] = []
    for topic in document.get("topics") or []:
        if str(topic.get("status") or "") not in {"ready_queue", "in_review"}:
            continue
        item = delivery_chain_state(db, settings, topic)
        if item is None:
            continue
        repair = topic.get("delivery_repair") or {}
        if repair:
            task = db.task(repair["task_id"]) or {}
            item["repair"] = {**repair, "status": task.get("status"), "max_attempts": 2}
            if item["state"] == "needs_human" and task.get("status") in IN_FLIGHT:
                item.update(state="in_progress", owner=repair["task_id"])
        chain.append(item)
        if item.get("unrecognized") and item["state"] == "needs_human":
            report.errors.append(
                f"Delivery chain: {item['paper_id']} (topic {item['topic_id']}) has no owner: "
                f"{item['action']}")
    from .paper_figures import latest_metrics
    report.program["figure_metrics"] = latest_metrics(db)
    from .program_funnel import funnel
    report.program["funnel"] = {
        line: {key: count for key, count in row.items() if key != "submission_events"}
        for line, row in funnel(document, paths.data).items()
    }
    report.program["delivery_chain"] = chain
    report.program["delivery_stuck"] = [item for item in chain
                                        if item["state"] in {"waiting", "needs_human"}]


# --------------------------------------------------------------------------- release pipeline
#
# Between review ``ready`` and the delivery to the management site the paper still
# needs its delivery-exit formal problems fixed, its Zenodo support material
# published and cited, a review binding to the final manuscript and a clean Git
# tree. With ``auto_handoff`` on, the controller drives these steps itself. Every
# step re-reads the paper's state (``paper-writing program release-status``), so
# a step that crashed or failed is simply taken again on the next tick; every
# step writes a topic-history note and an event; failures per stage and writer
# rounds are bounded by ``release_max_attempts`` and delivery attempts by
# ``handoff_max_attempts``.

RELEASE_FIX_ROUTING = "release_format_fix"
RELEASE_FIX_TASK_TYPE = "format_fix"
RELEASE_REVIEW_ROUTING = "release_full_review"
RELEASE_DECIDER = "orchestrator:release_pipeline"
# Bound on pipeline steps within one tick (each step is a short command, except
# the delta review); the remainder continues on the next tick.
RELEASE_STEPS_PER_TICK = 8


class ReleaseError(RuntimeError):
    """One release-pipeline step failed (counts against ``release_max_attempts``)."""


class ReleaseWait(Exception):
    """The pipeline waits for something outside it (no attempt is consumed)."""

    def __init__(self, stage: str, reason: str, detail: Mapping[str, Any] | None = None):
        super().__init__(reason)
        self.stage, self.reason, self.detail = stage, reason, dict(detail or {})


def run_release_status(paths: WorkspacePaths, settings: FactorySettings,
                       paper_id: str) -> dict[str, Any]:
    return _run_paper_command(paths, settings,
                              ["program", "release-status", "--paper-id", paper_id])


def run_zenodo_step(paths: WorkspacePaths, settings: FactorySettings, action: str,
                    paper_id: str) -> dict[str, Any]:
    """``zenodo prepare`` / ``zenodo release`` on production; the write switch is for this call only."""

    arguments = ["zenodo", action, "--paper-id", paper_id, "--environment", "production",
                 "--confirm-production"]
    if action == "release":
        arguments += ["--confirm-paper-id", paper_id]
    credentials, _ = pipeline_credentials(settings, (ZENODO_TOKEN_ENVIRONMENT,))
    return _run_paper_command(paths, settings, arguments,
                              environment={**credentials, "OPENLABS_ENABLE_EXTERNAL_WRITES": "1"},
                              json_flag=False)


def run_paper_adopt(paths: WorkspacePaths, settings: FactorySettings, paper_id: str,
                    source: Path, manifests: list[str], previous_package: str | None = None) -> dict[str, Any]:
    """``program adopt``: copy a campaign-workspace paper into the data repository."""

    arguments = ["program", "adopt", "--paper-id", paper_id, "--source", str(source)]
    if previous_package:
        arguments += ["--previous-package", previous_package]
    for manifest in manifests:
        arguments += ["--artifact-manifest", manifest]
    return _run_paper_command(paths, settings, arguments)


def run_support_source_relocation(paths: WorkspacePaths, settings: FactorySettings,
                                  paper_id: str) -> dict[str, Any]:
    """``program relocate-support-sources``: registry paths to adopt's support copies."""

    return _run_paper_command(paths, settings,
                              ["program", "relocate-support-sources", "--paper-id", paper_id])


def run_oversize_payload_binding(paths: WorkspacePaths, settings: FactorySettings,
                                 paper_id: str) -> dict[str, Any]:
    """``program bind-oversize-payloads``: files over the Git blob limit go to artifacts."""

    return _run_paper_command(paths, settings,
                              ["program", "bind-oversize-payloads", "--paper-id", paper_id])


def run_release_artifact_binding(paths: WorkspacePaths, settings: FactorySettings,
                                 paper_id: str) -> dict[str, Any]:
    """``program bind-release-artifacts``: freeze the ignored release PDF/.bbl."""

    return _run_paper_command(paths, settings,
                              ["program", "bind-release-artifacts", "--paper-id", paper_id])


def run_support_waiver(paths: WorkspacePaths, settings: FactorySettings,
                       paper_id: str) -> dict[str, Any]:
    """``program waive-support``: support.publication.mode not_required (no deposit)."""

    return _run_paper_command(paths, settings, [
        "program", "waive-support", "--paper-id", paper_id,
        "--reason", settings.program.support_none_reason,
        "--decided-by", "orchestrator:support_release=none",
    ])


def run_support_check(paths: WorkspacePaths, settings: FactorySettings,
                      paper_id: str) -> dict[str, Any]:
    return _run_paper_command(paths, settings, ["support-check", "--paper-id", paper_id],
                              accept=(0, 1))


def run_delta_review(paths: WorkspacePaths, settings: FactorySettings,
                     paper_id: str) -> dict[str, Any]:
    """``review unified-run --delta-only``: never starts the editor or the referees."""

    return _run_paper_command(
        paths, settings, ["review", "unified-run", "--paper-id", paper_id, "--delta-only"],
        json_flag=False, timeout=settings.program.release_review_timeout_seconds,
    )


def _git(root: Path, *arguments: str, identity: tuple[str, str] | None = None,
         check: bool = True) -> str:
    command = ["git"]
    if identity is not None:
        command += ["-c", f"user.name={identity[0]}", "-c", f"user.email={identity[1]}"]
    try:
        completed = subprocess.run([*command, *arguments], cwd=str(root), capture_output=True,
                                   text=True, timeout=300, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReleaseError(f"git {arguments[0]} could not run: {exc}") from exc
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[-400:]
        raise ReleaseError(f"git {arguments[0]} failed: {detail}")
    return completed.stdout


def git_identity(paths: WorkspacePaths, settings: FactorySettings) -> tuple[str, str]:
    """``[program.git]`` identity, else the data repository's own; neither: wait."""

    program = settings.program
    name = program.git_user_name or _git(paths.data, "config", "user.name", check=False).strip()
    email = program.git_user_email or _git(paths.data, "config", "user.email",
                                           check=False).strip()
    if not name or not email:
        raise ReleaseWait("commit", "git_identity_missing", {
            "hint": "set [program.git] user_name and user_email in config/openlabs.toml, or "
                    "user.name/user.email in the data repository"})
    return name, email


def commit_paper_paths(paths: WorkspacePaths, settings: FactorySettings, *, paper_id: str,
                       version: str, action: str, topic_id: str,
                       commit_paths: list[str]) -> str | None:
    """One local commit of exactly this paper's paths (plus the topic ledger); never pushed.

    Only the listed paths are staged (``git add -A -- <paths>``) and committed
    (``git commit --only``), so changes elsewhere in the work tree, staged or not,
    are left exactly as they were. Returns the new commit, or None when the
    paper's paths are already clean.
    """

    root = paths.data
    scope: list[str] = []
    for raw in commit_paths:
        relative = str(raw).strip().strip("/")
        if not relative or relative.startswith("..") or Path(relative).is_absolute():
            raise ReleaseError(f"refusing to commit a path outside the data repository: {raw}")
        if relative not in scope:
            scope.append(relative)
    # A path counts only when git knows a file under it (tracked, including a
    # deleted one, or untracked and not ignored). An empty directory, or one with
    # only ignored files, exists on disk but makes `git commit --only` fail with
    # "pathspec ... did not match any file(s) known to git".
    def known(item: str) -> bool:
        return bool(_git(root, "ls-files", "--cached", "--others", "--exclude-standard",
                         "--", item).strip())

    present = [item for item in scope if known(item)]
    if not present:
        return None
    if not _git(root, "status", "--porcelain=v1", "--untracked-files=all", "--",
                *present).strip():
        return None
    identity = git_identity(paths, settings)
    ledger_path = (paths.data / settings.program.ledger_path).resolve()
    try:
        ledger_relative = ledger_path.relative_to(root.resolve()).as_posix()
    except ValueError:
        ledger_relative = None
    # The ledger rides along only when Git tracks it or would track it: an instance
    # ledger the data repository ignores on purpose (runtime state) is never forced in,
    # and naming an ignored, untracked path makes `git add` fail outright.
    if (ledger_relative and ledger_path.is_file() and ledger_relative not in present
            and known(ledger_relative)):
        present.append(ledger_relative)
    fields = {"action": action, "paper_id": paper_id, "version": version or "?",
              "topic_id": topic_id}
    message = settings.program.git_message.format(**fields) + (
        "\n\nLocal commit by the OpenLabs release pipeline (not pushed).\n"
        f"Paper: {paper_id}\nVersion: {version or '?'}\nAction: {action}\nTopic: {topic_id}\n"
        "\nCo-Authored-By: GPT (Codex) via Claude Code orchestration"
    )
    _git(root, "add", "-A", "--", *present)
    _git(root, "commit", "-q", "--only", "-m", message, "--", *present, identity=identity)
    return _git(root, "rev-parse", "HEAD").strip()


def _release_campaign(db: FactoryDB, settings: FactorySettings, domain: str) -> str:
    """Per-domain campaign for formal-fix writers (governance overhead, like decisions)."""

    campaign_id = f"{domain}-program-release"
    campaign = db.campaign(campaign_id)
    budget = settings.max_campaign_agent_seconds
    if campaign is not None:
        used = float(campaign.get("agent_seconds_used") or 0)
        current = int(campaign.get("max_agent_seconds") or 0)
        status = str(campaign.get("status") or "")
        if status not in {"active", "budget_exhausted"} or (
            status == "active" and used + settings.max_task_wall_seconds + 1 <= current
        ):
            return campaign_id
        budget = max(current, int(used) + settings.max_campaign_agent_seconds)
    db.register_campaign(
        campaign_id, domain=domain, title=f"{domain} research-program release fixes",
        priority=5, source="program:release_pipeline", max_agent_seconds=budget,
    )
    return campaign_id


class _ReleasePipeline:
    """One ready-queued topic's way from review ``ready`` to delivery."""

    def __init__(self, db, paths, settings, report, ledger, topic, paper_id):
        self.db, self.paths, self.settings, self.report = db, paths, settings, report
        self.ledger, self.topic, self.paper_id = ledger, topic, paper_id
        self.topic_id = str(topic["topic_id"])
        self.state = dict(topic.get("release") or {})
        self.state.setdefault("status", "pending")
        self.state["attempts"] = dict(self.state.get("attempts") or {})
        self.handoff = dict(topic.get("handoff") or {})
        self.stage = str(self.state.get("stage") or "check")
        self.version = ""

    # ------------------------------------------------------------------ bookkeeping

    def entry(self, outcome: str, **extra: Any) -> dict[str, Any]:
        item = {"topic_id": self.topic_id, "paper_id": self.paper_id, "stage": self.stage,
                "outcome": outcome, **extra}
        _info(self.report, "releases").append(item)
        return item

    def save(self, event: str | None, reason: str, *, detail: Mapping[str, Any] | None = None,
             evidence: Any = None, **changes: Any) -> None:
        new = {**self.state, **changes}
        quiet = {k: v for k, v in new.items() if k not in {"seq", "updated_at"}}
        if event is None:
            current = {k: v for k, v in self.state.items() if k not in {"seq", "updated_at"}}
            if quiet == current:
                return  # waiting in the same place: no new history entry per tick
            event = "release_waiting"
        new["seq"] = int(self.state.get("seq") or 0) + 1
        new["updated_at"] = utc_now()
        record_topic_note(
            self.ledger, self.topic_id, db=self.db, event_type=event, reason=reason,
            decided_by=RELEASE_DECIDER, detail={"paper_id": self.paper_id, **dict(detail or {})},
            evidence=evidence, updates={"release": new},
            key=f"{event}:{self.topic_id}:{new['seq']}",
        )
        self.state = new

    def failure(self, exc: BaseException) -> None:
        attempts = dict(self.state.get("attempts") or {})
        attempts[self.stage] = int(attempts.get(self.stage) or 0) + 1
        final = attempts[self.stage] >= self.settings.program.release_max_attempts
        error = str(exc)[:800]
        marks = {"exhausted_code_revision": code_revision(self.paths)} if final else {}
        self.save("release_exhausted" if final else "release_failed", f"{self.stage}_failed",
                  detail={"stage": self.stage, "attempt": attempts[self.stage], "error": error,
                          "final": final},
                  attempts=attempts, last_error=error, stage=self.stage, unresolved_manuscript_issues=False,
                  status="exhausted" if final else "failed", **marks)
        self.entry("exhausted" if final else "failed", attempt=attempts[self.stage],
                   error=error[:300])
        if final:
            self.exhausted_report(error)

    def exhausted_report(self, error: str) -> None:
        _info(self.report, "release_exhausted").append(
            {"topic_id": self.topic_id, "paper_id": self.paper_id, "stage": self.stage,
             "error": error[:300]})
        if self.settings.program.auto_release and int((self.topic.get("delivery_repair") or {}).get("attempt") or 0) < 2:
            return
        self.report.errors.append(
            f"Release pipeline for {self.paper_id} (topic {self.topic_id}) stopped at "
            f"{self.stage} after {self.settings.program.release_max_attempts} attempts; "
            f"a human must resolve: {error[:300]}"
        )

    def wait(self, wait: ReleaseWait) -> None:
        self.stage = wait.stage
        # What exactly is awaited (missing variables, the hint) stays in the state, so the
        # tick report can name the condition without reading the history.
        waiting_detail = {key: wait.detail[key] for key in ("missing", "hint", "issues",
                                                         "credentials_file")
                          if wait.detail.get(key)}
        self.save(None, wait.reason, detail={"stage": wait.stage, **wait.detail},
                  status="waiting", stage=wait.stage, waiting_for=wait.reason,
                  waiting_detail=waiting_detail or None)
        self.entry(f"waiting_{wait.reason}", **wait.detail)

    def commit(self, status: Mapping[str, Any], action: str) -> str | None:
        previous, self.stage = self.stage, "commit"
        sha = commit_paper_paths(
            self.paths, self.settings, paper_id=self.paper_id,
            version=str(status.get("version") or self.version), action=action,
            topic_id=self.topic_id, commit_paths=list(status.get("commit_paths") or []),
        )
        if sha:
            commits = [*list(self.state.get("commits") or []), {"sha": sha, "action": action}]
            self.save("release_committed", action, detail={"commit": sha, "action": action},
                      commits=commits[-10:])
            self.entry("committed", commit=sha, action=action)
        self.stage = previous
        return sha

    # ------------------------------------------------------------------ driver

    def advance(self) -> None:
        if self.state.get("status") == "exhausted":
            self.entry("exhausted", error=str(self.state.get("last_error") or "")[:300])
            _info(self.report, "release_exhausted").append(
                {"topic_id": self.topic_id, "paper_id": self.paper_id,
                 "stage": self.stage, "error": str(self.state.get("last_error") or "")[:300]})
            return
        for _ in range(RELEASE_STEPS_PER_TICK):
            try:
                if not self.step():
                    return
            except ReleaseWait as wait:
                self.wait(wait)
                return
            except (ReleaseError, DeliveryError) as exc:
                self.failure(exc)
                return
        self.entry("continues_next_tick")

    def step(self) -> bool:
        """Take the next step; True: continue within this tick."""

        if self.writer_pending():
            return False
        if self.adopt_if_needed():
            return True
        self.stage = "check"
        status = run_release_status(self.paths, self.settings, self.paper_id)
        self.version = str(status.get("version") or "")
        if status.get("delivered"):
            self.finish_delivered(status)
            return False
        review = dict(status.get("review") or {})
        support = dict(status.get("support") or {})
        issues = [item for item in status.get("issues") or [] if isinstance(item, Mapping)]
        if not review.get("ready"):
            self.return_to_review(status, {"reason": "writing_release is no longer ready",
                                           "problems": review.get("problems") or []})
            return False
        from .target_stage import tier2_topic

        graded_journal = (self.topic.get("venue_grade") or {}).get("journal")
        if tier2_topic(self.topic) and (
            not graded_journal or graded_journal != status.get("target_journal")
        ):
            raise ReleaseWait("check", "venue_grade_pending",
                              {"hint": "The current target needs a recorded acceptance grade."})
        if support.get("published_package_stale"):
            self.stage = "support_prepare"
            raise ReleaseError(
                "Cannot reuse the published support version. Restore the registered package "
                "and sources or select a new support release version: "
                f"{support['published_package_stale']}"
            )
        if (self.settings.program.support_release == "none" and support.get("required")
                and not support.get("published")):
            self.waive_support()
            return True
        if status.get("support_sources_unadopted"):
            # Owner papers register support sources relative to their campaign workspace;
            # adopt copies them under papers/<id>/support-materials/ and the registry is
            # pointed there (reviewed names kept, so the review binding holds) before
            # zenodo prepare reads them (PMB-13B, 2026-11-20).
            self.stage = "relocate_support"
            result = run_support_source_relocation(self.paths, self.settings, self.paper_id)
            if result.get("status") not in {"relocated", "not_needed"}:
                raise ReleaseError("support source relocation failed: "
                                   f"{str(result.get('error') or result)[:400]}")
            self.save("release_support_sources_relocated", "adopted_support_sources",
                      stage=self.stage, status="running",
                      detail={"relocated": result.get("relocated"),
                              "matches_review": result.get("matches_review")})
            self.entry("support_sources_relocated",
                       files=len(result.get("relocated") or []),
                       matches_review=result.get("matches_review"))
            return True
        if status.get("oversize_payloads_unbound"):
            # The data repository refuses blobs over 5 MiB; such a file (an 8 MB
            # formal-check evidence body stopped PMB-13B, 2026-11-20) is bound to the
            # artifact store by path, size and SHA-256 and ignored before any commit.
            self.stage = "bind_payloads"
            result = run_oversize_payload_binding(self.paths, self.settings, self.paper_id)
            if result.get("status") not in {"bound", "not_needed"}:
                raise ReleaseError("oversize payload binding failed: "
                                   f"{str(result.get('error') or result)[:400]}")
            self.save("release_payloads_bound", "oversize_files_bound_to_artifacts",
                      stage=self.stage, status="running",
                      detail={"files": result.get("files"), "manifest": result.get("manifest"),
                              "manifest_sha256": result.get("manifest_sha256")})
            self.entry("payloads_bound", files=len(result.get("files") or []))
            return True
        publication_metadata = any(item.get("remedy") == "publication_metadata" for item in issues)
        if (publication_metadata or status.get("publication_metadata_pending")) and not support.get("prepare_needed"):
            self.stage = "publication_metadata"
            result = _run_paper_command(self.paths, self.settings,
                                        ["program", "prepare-publication-metadata", "--paper-id", self.paper_id])
            if result.get("status") not in {"projected", "bound"}:
                raise ReleaseError("Publication metadata preparation did not complete")
            self.entry("publication_metadata", status=result["status"])
            return True
        infrastructure = [item for item in issues if item.get("remedy") == "control_plane"]
        if infrastructure:
            raise ReleaseWait(self.stage, "control_plane",
                              {"issues": [str(item.get("text") or "")[:300] for item in infrastructure]})
        human = [item for item in issues if item.get("remedy") == "human"]
        if human:
            raise ReleaseWait("form_fix", "needs_owner",
                              {"issues": [str(item.get("text") or "")[:300] for item in human]})
        prepare = support.get("prepare_needed") or any(
            item.get("remedy") == "zenodo_prepare" for item in issues)
        if prepare:
            self.stage = "support_prepare"
            self.require_zenodo(support)
            self.commit(status, "commit-before-zenodo-prepare")
            result = run_zenodo_step(self.paths, self.settings, "prepare", self.paper_id)
            self.save("release_support_prepared", "zenodo_prepare", stage=self.stage,
                      status="running",
                      detail={"reserved_version_doi": result.get("reserved_version_doi"),
                              "archive_sha256": result.get("archive_sha256")})
            self.entry("support_prepared", version_doi=result.get("reserved_version_doi"))
            return True
        writer = [item for item in issues if item.get("remedy") == "writer"]
        ai_issues = any(str(item.get("code") or "").startswith(
            ("STYLE-AI-DISCLOSURE-", "STYLE-AI-DECLARATION-", "AI-USE-UNVERIFIED")) for item in writer)
        if ai_issues or status.get("missing_default_contributions"):
            command = ["program", "apply-default-declarations", "--paper-id", self.paper_id]
            if not ai_issues:
                command.append("--contributions-only")
            result = _run_paper_command(self.paths, self.settings, command)
            if result.get("changed"):
                self.entry("default_declarations_applied")
                return True
        if writer:
            self.schedule_writer(status, writer)
            return False
        if not review.get("current"):
            self.stage = "delta_review"
            result = run_delta_review(self.paths, self.settings, self.paper_id)
            if result.get("run_dir"):
                budget_control.ingest_review_quota(
                    self.db, self.settings, self.paths.data,
                    f"{result['run_dir']}/decision.json", task_id=None)
            if result.get("outcome") == "ready" and result.get("review_mode") == "delta":
                self.save("release_delta_review", "delta_review_ready", stage=self.stage,
                          status="running",
                          detail={"run_dir": result.get("run_dir"),
                                  "decision_sha256": result.get("decision_sha256")})
                self.entry("delta_review_ready", run_dir=result.get("run_dir"))
                return True
            if result.get("outcome") == "review_round_blocked" and result.get("next_action") == "wait":
                # An in-flight unified review owns this paper; retry on a later tick.
                self.entry("delta_review_waiting", reason="unified_review_active")
                return False
            if result.get("outcome") in {"full_review_required", TRIGGER_REVIEW_ROUNDS}:
                # The change is outside the delta rule: only a full review can judge it.
                self.return_to_review(status, {
                    "reason": "the post-ready change needs a full review",
                    "outcome": result.get("outcome"), "review_mode": result.get("review_mode"),
                    "run_dir": result.get("run_dir"), "exhausted_review": result.get("review_outcome"),
                    "full_review_reasons": result.get("full_review_reasons") or []})
                return False
            # preflight_failed, formal_check_blocked, ...: a preflight, environment or
            # verification problem, not a scientific one; retried, then left to a human.
            raise ReleaseError(
                f"delta review did not pass: outcome={result.get('outcome')!r} "
                f"review_mode={result.get('review_mode')!r} run_dir={result.get('run_dir')!r}")
        if status.get("release_artifacts_unbound"):
            # `zenodo release` and delivery take only Git-frozen release files; the
            # ignored PDF/.bbl are frozen through a content-addressed manifest instead,
            # bound before the Zenodo release (its gate checks them) and committed by
            # commit-before-zenodo-release, or by release-ready when no deposit is made.
            self.stage = "bind_artifacts"
            result = run_release_artifact_binding(self.paths, self.settings, self.paper_id)
            if result.get("status") not in {"bound", "not_needed"}:
                raise ReleaseError("release artifact binding failed: "
                                   f"{str(result.get('error') or result)[:400]}")
            self.save("release_artifacts_bound", "ignored_release_files_frozen",
                      stage=self.stage, status="running",
                      detail={"files": result.get("files"), "manifest": result.get("manifest")})
            self.entry("artifacts_bound", files=len(result.get("files") or []))
            return True
        if support.get("release_needed"):
            self.stage = "support_release"
            self.require_zenodo(support)
            check = run_support_check(self.paths, self.settings, self.paper_id)
            if not check.get("valid"):
                first = next(iter(check.get("errors") or []), {})
                raise ReleaseError(f"support-check failed: {first.get('code')}: "
                                   f"{first.get('message')}")
            self.commit(status, "commit-before-zenodo-release")
            result = run_zenodo_step(self.paths, self.settings, "release", self.paper_id)
            self.save("release_support_published", "zenodo_release", stage=self.stage,
                      status="running",
                      detail={"version_doi": result.get("version_doi"),
                              "concept_doi": result.get("concept_doi"),
                              "receipt": result.get("receipt")})
            self.entry("support_published", version_doi=result.get("version_doi"))
            # The DOI/receipt registry update is committed by the next step.
            return True
        if self.prepare_submission_materials(status):
            return True
        self.commit(status, "release-ready")
        self.deliver(status)
        return False

    def prepare_submission_materials(self, status: Mapping[str, Any]) -> bool:
        """Draft the cover letter and reviewers, verify the single-file LaTeX (投稿包, 2026-11-25).

        Once per manuscript version, before delivery. Advisory: a failure is recorded and the
        package then carries a template and a note; delivery goes on. True: re-check this tick.
        """
        materials = status.get("submission_materials")
        if not isinstance(materials, Mapping) or not materials.get("pending") or materials.get("legacy"):
            return False
        version = str(status.get("version") or self.version)
        if self.state.get("submission_materials_attempted") == version:
            return False  # tried for this version; the package says what is missing
        self.stage = "submission_materials"
        try:
            result = _run_paper_command(self.paths, self.settings,
                                        ["submission", "prepare", "--paper-id", self.paper_id],
                                        timeout=3_600)
            detail = {"flatten": (result.get("flatten") or {}).get("status"),
                      "draft": (result.get("draft") or {}).get("status"),
                      "reviewers": (result.get("draft") or {}).get("reviewers_kept")}
        except DeliveryError as exc:
            detail = {"error": str(exc)[:400]}
        self.save("release_submission_materials", "submission_package_materials", stage=self.stage,
                  status="running", submission_materials_attempted=version, detail=detail)
        self.entry("submission_materials", **detail)
        return True

    # ------------------------------------------------------------------ steps

    def adopt_if_needed(self) -> bool:
        """Copy the paper from its campaign workspace when the data root lacks it.

        Owner-mode papers are written and reviewed in the campaign workspace (not
        tracked by Git); delivery and commits work on the data repository root.
        True: adopted in this step.
        """

        registry = self.paths.data / "registry" / "papers"
        request = self.topic.get("delivered_revision") or {}
        current_package = request.get("package_id")
        if current_package and self.state.get("adopted_revision_package") == current_package:
            return False
        if not current_package and any((registry / f"{self.paper_id}{suffix}").is_file()
               for suffix in (".yaml", ".yml", ".json")):
            return False
        self.stage = "adopt"
        workspace = asset_library.topic_workspace(self.db, self.paths, self.topic)
        if workspace is None or not any(
                (workspace / "registry" / "papers" / f"{self.paper_id}{suffix}").is_file()
                for suffix in (".yaml", ".yml", ".json")):
            raise ReleaseWait("adopt", "paper_not_found", {
                "hint": f"no registry record for {self.paper_id} in the data repository or in "
                        f"the topic's campaign workspace {workspace}"})
        review_task = str(self.handoff.get("review_task_id") or "")
        bundle = self.db.result_bundle_path(review_task) if review_task else None
        # The ready review's bundle first, then the campaign's other archived results
        # (an owner seat's private review root holds the figures and build products the
        # snapshot binds); adopt keeps only hash- or snapshot-verified files.
        manifests = [bundle] if bundle else []
        campaign_id = str(self.topic.get("campaign_id") or "")
        for path in (self.db.campaign_result_bundle_paths(campaign_id) if campaign_id else []):
            if path not in manifests:
                manifests.append(path)
        args = (self.paths, self.settings, self.paper_id, workspace, manifests)
        if current_package:
            result = run_paper_adopt(*args, previous_package=current_package)
        else:
            result = run_paper_adopt(*args)
        if result.get("status") == "blocked":
            raise ReleaseWait("adopt", str(result.get("reason") or "adopt_blocked"), {
                "detail": str(result.get("detail") or "")[:400], "source": str(workspace),
                "hint": "the workspace paper cannot be adopted as laid out; the owner decides"})
        if result.get("status") != "adopted":
            raise ReleaseError(f"adopt failed: {str(result.get('error') or result)[:400]}")
        detail = {"source": str(workspace), "review_bundle": bundle,
                  **{key: result.get(key) for key in (
                      "copied", "evidence_restored", "evidence_missing", "pdf_restored",
                      "support_sources_copied_to", "support_sources_missing")}}
        self.save("release_paper_adopted", "workspace_paper_adopted", stage=self.stage,
                  status="running", detail=detail, adopted_revision_package=current_package)
        self.entry("adopted", copied=result.get("copied"), pdf_restored=result.get("pdf_restored"),
                   evidence_missing=len(result.get("evidence_missing") or []))
        return True

    def waive_support(self) -> None:
        """``support_release = "none"``: record that no public deposit is made."""

        self.stage = "support_waiver"
        result = run_support_waiver(self.paths, self.settings, self.paper_id)
        outcome = str(result.get("status") or "")
        if outcome == "blocked":
            raise ReleaseWait(self.stage, str(result.get("reason") or "support_waiver_blocked"),
                              {"detail": str(result.get("detail") or "")[:400],
                               "hint": "[program] support_release = \"none\": the owner decides"})
        if outcome not in {"waived", "unchanged"}:
            raise ReleaseError(f"support waiver failed: {str(result.get('error') or result)[:400]}")
        self.save("release_support_waived", "support_release_none", stage=self.stage,
                  status="running", detail={"mode": "not_required", "outcome": outcome,
                                            "reason": result.get("reason")})
        self.entry("support_waived", waiver=outcome)

    def require_zenodo(self, support: Mapping[str, Any]) -> None:
        if self.settings.program.support_release == "none":
            raise ReleaseWait(self.stage, "support_release_none",
                              {"hint": "[program] support_release = \"none\": no Zenodo step"})
        if not self.settings.program.auto_release:
            raise ReleaseWait(self.stage, "auto_release_off",
                              {"hint": "[program] auto_release = false: run the Zenodo step by hand"})
        if support.get("standing_production_release_authorization") is not True:
            raise ReleaseWait(self.stage, "no_standing_authorization", {
                "hint": "registry/settings.yaml#support_publication."
                        "standing_production_release_authorization is not true"})
        found, refused = pipeline_credentials(self.settings, (ZENODO_TOKEN_ENVIRONMENT,))
        if ZENODO_TOKEN_ENVIRONMENT not in found:
            detail: dict[str, Any] = {"missing": [ZENODO_TOKEN_ENVIRONMENT]}
            if refused:
                detail["credentials_file"] = refused
            raise ReleaseWait(self.stage, "waiting_credentials", detail)

    def writer_pending(self) -> bool:
        task_id = str(self.state.get("writer_task_id") or "")
        if not task_id:
            return False
        task = self.db.task(task_id)
        status = str(task.get("status")) if task else "missing"
        if status in IN_FLIGHT:
            self.stage = "form_fix_writer"
            self.entry("waiting_writer", task_id=task_id)
            return True
        self.stage = "form_fix_writer"
        error = None
        if status == "succeeded":
            try:
                _apply_writer_files(self.db, self.paths, task_id)
            except (ReleaseError, ValueError, OSError) as exc:
                error = str(exc)
        self.save("release_writer_finished", status, stage=self.stage, writer_task_id=None,
                  detail={"task_id": task_id, "status": status, "import_error": error})
        if error:
            self.failure(ReleaseError(error))
            return True
        if status != "succeeded":
            self.failure(ReleaseError(f"formal-fix writer {task_id} ended {status}"))
            return True  # this tick stops; the next one re-checks and may retry
        return False

    def schedule_writer(self, status: Mapping[str, Any], issues: list[Mapping[str, Any]]) -> None:
        self.stage = "form_fix_writer"
        rounds = int(self.state.get("writer_rounds") or 0)
        texts = [str(item.get("text") or item.get("message") or "") for item in issues]
        if rounds >= self.settings.program.release_max_attempts:
            error = (f"{len(issues)} formal problem(s) remain after {rounds} writer round(s): "
                     + "; ".join(texts[:3]))
            attempts = {**dict(self.state.get("attempts") or {}),
                        self.stage: self.settings.program.release_max_attempts}
            self.save("release_exhausted", "writer_rounds_exhausted", stage=self.stage,
                      status="exhausted", attempts=attempts, last_error=error[:800],
                      detail={"issues": texts[:20]}, unresolved_manuscript_issues=True,
                      exhausted_code_revision=code_revision(self.paths))
            self.entry("exhausted", error=error[:300])
            self.exhausted_report(error)
            return
        domain = str(self.topic.get("domain") or "")
        packet = {
            "schema_version": "openlabs.release_fix_packet.v1",
            "topic_id": self.topic_id, "paper_id": self.paper_id,
            "version": status.get("version"), "round": rounds + 1,
            "scope": status.get("writer_scope"),
            "canonical_root": str(self.paths.data),
            "source_sha256": _writer_sources(self.paths.data, self.paper_id),
            "issues": [{key: item.get(key) for key in ("code", "location", "message", "text",
                                                       "files") if item.get(key) is not None}
                       for item in issues],
            "notes_not_blocking": status.get("notes") or [],
            "support": {key: (status.get("support") or {}).get(key)
                        for key in ("status", "version_doi", "mode")},
            "created_at": utc_now(),
        }
        digest = hashlib.sha256(canonical_json_bytes(
            {k: v for k, v in packet.items() if k != "created_at"})).hexdigest()
        packet_path = (_control_root(self.paths) / "release-packets" / _token(self.topic_id)
                       / f"round-{rounds + 1}-{digest[:12]}.json")
        atomic_write_json(packet_path, packet)
        task_id = f"release-fix:{_digest(self.topic_id, self.paper_id, rounds + 1, digest)[:32]}"
        if self.db.task(task_id) is None:
            campaign = _release_campaign(self.db, self.settings, domain)
            from .engine import _paper_skill

            self.db.enqueue_task(
                task_id=task_id, campaign_id=campaign, domain=domain,
                task_type=RELEASE_FIX_TASK_TYPE,
                objective=(
                    f"Paper {self.paper_id} passed the unified review. Fix only the "
                    f"{len(issues)} delivery-exit formal problem(s) listed in the packet at the "
                    "input path. Read canonical_root and source_sha256 from this packet. Work on copies of "
                    "the exact canonical sources. Return each changed TeX or Bib file as an artifact "
                    "with artifact_id edit- followed by the first 16 lowercase hex digits of SHA-256 "
                    "of its registry-relative path encoded as UTF-8. Do not change any number, "
                    "table, figure content, result, claim or conclusion, nor the title. Do not run "
                    "the review, Zenodo or delivery commands and do not commit; the orchestrator "
                    "re-checks, re-reviews the change (delta review) and commits. Return a result "
                    "bundle that lists, per problem, what you changed."
                ),
                input_path=str(packet_path),
                skill_path=_paper_skill(domain) or "openlabs-paper-writing",
                runner=dispatch_runner(self.settings, RELEASE_FIX_TASK_TYPE,
                                       RELEASE_FIX_ROUTING, "cheap"),
                routing_reason=RELEASE_FIX_ROUTING, agent_role="writer",
                session_mode="fresh",
                priority=int(self.topic.get("priority") or 0) + 1,
                max_attempts=self.settings.max_attempts,
                max_wall_seconds=min(7_200, self.settings.max_task_wall_seconds),
                **default_task_resources(self.settings).to_dict(),
            )
            self.report.enqueued.append(task_id)
        self.save("release_writer_scheduled", "formal_fixes_need_text", stage=self.stage,
                  status="waiting", writer_task_id=task_id, writer_rounds=rounds + 1,
                  detail={"task_id": task_id, "issues": texts[:20],
                          "packet": str(packet_path)},
                  evidence=[_evidence(packet_path)])
        self.entry("writer_scheduled", task_id=task_id, issues=len(issues))

    def return_to_review(self, status: Mapping[str, Any], detail: Mapping[str, Any]) -> None:
        """``ready_queue -> in_review`` and one full unified review in the topic's campaign."""

        self.stage = "full_review"
        campaign_id = str(self.topic.get("campaign_id") or "")
        evidence = [_write_evidence(self.paths, self.topic_id, "release-full-review",
                                    {"paper_id": self.paper_id, "canonical_root": str(self.paths.data), **dict(detail)})]
        marker = _digest(self.topic_id, self.paper_id, json.dumps(dict(detail), sort_keys=True,
                                                                  default=str))
        state = {**self.state, "status": "returned_to_review", "stage": self.stage,
                 "seq": int(self.state.get("seq") or 0) + 1, "updated_at": utc_now()}
        cap = detail.get("exhausted_review") or (status.get("review") or {}).get("exhausted_review")
        return_topic_to_review(
            self.ledger, self.topic_id, db=self.db, decided_by=f"{RELEASE_DECIDER}:{marker[:16]}",
            evidence=evidence,
            updates={"release": state,
                     "handoff": {**self.handoff, "status": "returned_to_review"}},
        )
        self.state = state
        task_id = None
        if cap:
            topic = find_topic(self.ledger.read(), self.topic_id)
            task_id = _schedule_cap(self.db, self.paths, self.settings, self.report, topic, cap,
                                    evidence, detail.get("full_review_reasons"))
            state["direction_task_id"] = task_id
        campaign = self.db.campaign(campaign_id) if campaign_id else None
        if campaign is not None and not cap:
            self.db.resume_paused_campaign(campaign_id, reason="release_full_review_required")
            task_id = f"release-review:{marker[:32]}"
            if self.db.task(task_id) is None:
                parent = str(self.handoff.get("review_task_id") or "")
                self.db.enqueue_task(
                    task_id=task_id, campaign_id=campaign_id, domain=str(campaign["domain"]),
                    task_type="paper_review",
                    objective=(
                        "A change after the ready review (formal fixes or the support-material "
                        "citation) is beyond the delta review; the packet at the input path names "
                        "why. Run `paper-writing review unified-run --paper-id "
                        f"{self.paper_id} --root {self.paths.data}` as an ordinary full review on the "
                        "canonical release sources. Load the instance LaTeX environment before building. "
                        "If this root is unavailable, report the access error. Do not review a different "
                        "campaign snapshot. Do not edit the "
                        "manuscript. For a same-venue re-review prepare the decision-bound JSON --response "
                        "from the registered revision and evidence. For review_round_blocked, copy round_guard verbatim into the result, return paper_candidate=false and stop this attempt. "
                        "Ask the writer or researcher for any missing revision evidence. For cooldown alone, "
                        "return no next action. Do not copy the prior writing_release as a fresh result. "
                        "For other outcomes return paper_candidate=true only for outcome ready, and copy "
                        "unified-run's review_outcome when present, otherwise the registered writing_release, into `review_outcome` (next_action, "
                        "status, review_stalled, rounds_for_target, max_rounds_per_target, "
                        "direction_context, decision_record, decision_record_sha256, paper_id)."
                    ),
                    input_path=evidence[0]["path"], skill_path="openlabs-paper-review",
                    runner=dispatch_runner(self.settings, "paper_review",
                                           RELEASE_REVIEW_ROUTING, "frontier"),
                    routing_reason=RELEASE_REVIEW_ROUTING,
                    parent_task_id=parent if parent and self.db.task(parent) else None,
                    agent_role="reviewer", session_mode="fresh",
                    priority=int(campaign.get("priority") or 0) + 1,
                    max_attempts=self.settings.max_attempts,
                    max_wall_seconds=self.settings.max_task_wall_seconds,
                    **default_task_resources(self.settings).to_dict(),
                )
                self.report.enqueued.append(task_id)
        task_detail = {"direction_task_id" if cap else "review_task_id": task_id}
        record_topic_note(
            self.ledger, self.topic_id, db=self.db, event_type="release_returned_to_review",
            reason="full_review_required", decided_by=RELEASE_DECIDER,
            detail={"paper_id": self.paper_id, **task_detail, **dict(detail)},
            updates={"release": state} if cap else None,
            evidence=evidence, key=f"release_returned_to_review:{marker}",
        )
        self.entry("returned_to_review", **task_detail,
                   reasons=list(detail.get("full_review_reasons") or [])[:5])

    def deliver(self, status: Mapping[str, Any]) -> None:
        self.stage = "deliver"
        found, refused = pipeline_credentials(self.settings, DELIVERY_ENVIRONMENT)
        missing = [name for name in DELIVERY_ENVIRONMENT if name not in found]
        if missing:
            extra = {"credentials_file": refused} if refused else {}
            _info(self.report, "handoffs").append(
                {"topic_id": self.topic_id, "paper_id": self.paper_id,
                 "outcome": "waiting_credentials", "missing": missing, **extra})
            self.db.record_event_once("topic", self.topic_id, "handoff_blocked",
                                      {"reason": "credentials_missing", "missing": missing,
                                       **extra},
                                      event_key="credentials_missing")
            raise ReleaseWait("deliver", "waiting_credentials", {"missing": missing, **extra})
        state = self.handoff
        attempts = int(state.get("attempts") or 0) + 1
        entry = {"topic_id": self.topic_id, "paper_id": self.paper_id}
        try:
            result = run_paper_delivery(self.paths, self.settings, self.paper_id)
            if result.get("submission_handler") not in (None, ""):
                raise DeliveryError("delivery reported a submission handler; refusing it")
        except DeliveryError as exc:
            final = attempts >= self.settings.program.handoff_max_attempts
            new_state = {**state, "status": "exhausted" if final else "failed",
                         "attempts": attempts, "last_error": str(exc)[:800],
                         "last_attempt_at": utc_now(), "paper_id": self.paper_id}
            if final:
                new_state["exhausted_code_revision"] = code_revision(self.paths)
            record_topic_note(
                self.ledger, self.topic_id, db=self.db, event_type="handoff_failed",
                reason="delivery_failed", decided_by="orchestrator:auto_handoff",
                detail={"attempt": attempts, "error": str(exc)[:800], "final": final},
                updates={"handoff": new_state}, key=f"handoff_failed:{attempts}",
            )
            self.handoff = new_state
            _info(self.report, "handoffs").append({**entry, "outcome": "failed",
                                                    "attempt": attempts, "final": final,
                                                    "error": str(exc)[:300]})
            if final:
                self.exhausted_report(f"delivery failed {attempts} times: {exc}")
            return
        self.mark_delivered(result, attempts)
        # The registry's new ``delivery`` block (and an approved escalation) is
        # committed at once, so a later ``handoff sync`` finds a clean tree.
        self.commit_after_delivery(status)

    def mark_delivered(self, result: Mapping[str, Any], attempts: int) -> None:
        new_state = {**self.handoff, "status": "delivered", "attempts": attempts,
                     "delivered_at": utc_now(), "paper_id": self.paper_id,
                     "package_id": result.get("package_id"), "submission_handler": None,
                     "receipt": result.get("receipt")}
        record_topic_note(
            self.ledger, self.topic_id, db=self.db, event_type="handoff_delivered",
            reason="auto_handoff", decided_by="orchestrator:auto_handoff",
            detail={"paper_id": self.paper_id, "package_id": result.get("package_id"),
                    "awaiting_owner_review": True, "submission_handler": None},
            updates={"handoff": new_state, "awaiting_owner_review": True},
            key=f"handoff_delivered:{self.paper_id}:{result.get('package_id')}",
        )
        self.handoff = new_state
        _info(self.report, "handoffs").append({"topic_id": self.topic_id,
                                                "paper_id": self.paper_id,
                                                "outcome": "delivered",
                                                "package_id": result.get("package_id")})

    def commit_after_delivery(self, status: Mapping[str, Any]) -> None:
        self.stage = "commit_after_delivery"
        try:
            self.commit(status, "record-delivery")
        except (ReleaseWait, ReleaseError) as exc:
            # Delivered either way; the commit is retried on the next tick.
            self.save("release_commit_pending", "commit_after_delivery_failed",
                      stage=self.stage, status="commit_pending",
                      detail={"error": str(exc)[:400]}, last_error=str(exc)[:800])
            self.entry("commit_pending", error=str(exc)[:300])
            return
        from .paper_figures import harvest, record_review_metrics
        binding = status.get("figure_review_binding") or {}
        record_review_metrics(self.db, self.paths, {}, binding.get("decision"), binding.get("sha256"))
        candidates = harvest(self.paths, self.settings, self.paper_id, binding)
        if candidates:
            _info(self.report, "figure_harvest").extend(candidates)
        self.save("release_done", "delivered", stage="done", status="done",
                  detail={"package_id": self.handoff.get("package_id")})
        self.entry("done", package_id=self.handoff.get("package_id"))

    def finish_delivered(self, status: Mapping[str, Any]) -> None:
        """The current version is already delivered (e.g. a crash after delivery)."""

        delivery = dict(status.get("delivery") or {})
        if self.handoff.get("status") != "delivered":
            self.mark_delivered(delivery, int(self.handoff.get("attempts") or 0) + 1)
        self.commit_after_delivery(status)


def retry_release(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    *,
    paper_id: str,
    by: str,
    reason: str,
) -> dict[str, Any]:
    """After a human resolved the cause: let an exhausted release pipeline try again.

    The topic's ``release`` goes back to ``pending`` with the stopped stage's
    attempts cleared (writer rounds too when the writer stage stopped); an exhausted
    delivery (``handoff``) goes back to ``queued`` with its attempts cleared. The
    previous error, stage and attempts are kept in ``release.retries``. Nothing else
    changes; the next tick re-reads the paper's actual state.

    Two more cases (see ``_retry_new_version`` and ``_retry_returned_review``): a
    topic delivered at an earlier version whose paper has a newer one, and a topic
    the pipeline returned to review although its paper is ready and current.
    """

    reason = str(reason or "").strip()
    if not reason:
        raise DeliveryError("a release retry needs its reason")
    ledger = _ledger(paths, settings)
    document = ledger.read()
    topic = next((item for item in topics_by_status(document, "ready_queue")
                  if paper_id in {str(item.get("paper_id") or ""),
                                  str((item.get("handoff") or {}).get("paper_id") or "")}), None)
    if topic is None:
        returned = next((item for item in topics_by_status(document, "in_review")
                         if str((item.get("handoff") or {}).get("paper_id") or "") == paper_id),
                        None)
        if returned is not None:
            return _retry_returned_review(db, paths, settings, ledger, returned,
                                          paper_id=paper_id, by=by, reason=reason)
        raise DeliveryError(f"no ready-queued or returned-to-review topic holds paper {paper_id}")
    topic_id = str(topic["topic_id"])
    release = dict(topic.get("release") or {})
    handoff = dict(topic.get("handoff") or {})
    release_stopped = release.get("status") in {"exhausted", "failed"}
    handoff_stopped = handoff.get("status") in {"exhausted", "failed"}
    if not release_stopped and not handoff_stopped and handoff.get("status") == "delivered":
        return _retry_new_version(db, paths, settings, ledger, topic,
                                  paper_id=paper_id, by=by, reason=reason)
    if not release_stopped and not handoff_stopped:
        raise DeliveryError(
            f"paper {paper_id}: release is {release.get('status') or 'pending'!r} and delivery "
            f"is {handoff.get('status') or 'queued'!r}; nothing stopped to retry")
    decided_by = f"manual:{by}"
    updates: dict[str, Any] = {}
    stage = str(release.get("stage") or "check")
    if release_stopped:
        attempts = dict(release.get("attempts") or {})
        retry = {"at": utc_now(), "by": decided_by, "reason": reason, "stage": stage,
                 "previous_status": release.get("status"), "previous_attempts": dict(attempts),
                 "previous_error": release.get("last_error")}
        attempts.pop(stage, None)
        new_release = {**release, "status": "pending", "attempts": attempts,
                       "last_error": None, "waiting_for": None,
                       "retries": [*list(release.get("retries") or []), retry][-10:],
                       "seq": int(release.get("seq") or 0) + 1, "updated_at": utc_now()}
        if stage == "form_fix_writer":
            new_release["writer_rounds"] = 0
        updates["release"] = new_release
    if handoff_stopped:
        updates["handoff"] = {**handoff, "status": "queued", "attempts": 0,
                              "previous_error": handoff.get("last_error"), "last_error": None}
    record_topic_note(
        ledger, topic_id, db=db, event_type="release_retry", reason="human_resolved",
        decided_by=decided_by,
        detail={"paper_id": paper_id, "reason": reason, "stage": stage,
                "release_reset": release_stopped, "handoff_reset": handoff_stopped},
        updates=updates,
        key=f"release_retry:{topic_id}:{int(release.get('seq') or 0)}:{handoff.get('attempts')}",
    )
    return {"schema_version": "openlabs.program_release_retry.v1", "topic_id": topic_id,
            "paper_id": paper_id, "stage": stage, "release_reset": release_stopped,
            "handoff_reset": handoff_stopped}


def _reset_release(release: Mapping[str, Any], retry: Mapping[str, Any]) -> dict[str, Any]:
    """A fresh ``pending``/``check`` release state that keeps its history and its seq order.

    ``seq`` keeps increasing (never back to 0): the pipeline's history keys contain it,
    and a repeated key would be taken as already written.
    """

    return {**dict(release), "status": "pending", "stage": "check", "attempts": {},
            "writer_rounds": 0, "last_error": None, "waiting_for": None,
            "retries": [*list(release.get("retries") or []), dict(retry)][-10:],
            "seq": int(release.get("seq") or 0) + 1, "updated_at": utc_now()}


def _retry_new_version(db, paths, settings, ledger, topic, *, paper_id: str, by: str,
                       reason: str) -> dict[str, Any]:
    """A delivered topic whose paper has a newer version: queue its delivery again.

    Refused when the paper's release status shows the current version delivered, or
    when the registry records no earlier delivered version to compare with.
    """

    topic_id = str(topic["topic_id"])
    release = dict(topic.get("release") or {})
    handoff = dict(topic.get("handoff") or {})
    status = run_release_status(paths, settings, paper_id)
    version = str(status.get("version") or "")
    delivered_version = str((status.get("delivery") or {}).get("version") or "")
    if status.get("frozen"):
        raise DeliveryError(f"paper {paper_id} is frozen: {status['frozen']}")
    if status.get("delivered"):
        raise DeliveryError(
            f"paper {paper_id}: version {version} is already delivered "
            f"(package {(status.get('delivery') or {}).get('package_id')}); nothing stopped to retry")
    if not delivered_version:
        raise DeliveryError(
            f"paper {paper_id}: the topic's delivery is recorded but the paper registry has no "
            "delivered version; a human must reconcile the two first")
    if delivered_version == version:
        raise DeliveryError(
            f"paper {paper_id}: version {version} has a delivery block without a package id; "
            "a human must reconcile it first")
    decided_by = f"manual:{by}"
    retry = {"at": utc_now(), "by": decided_by, "reason": reason, "kind": "new_version",
             "stage": release.get("stage"), "previous_status": release.get("status"),
             "previous_delivered_version": delivered_version, "version": version}
    new_handoff = {**handoff, "status": "queued", "attempts": 0, "last_error": None,
                   "previous_package_id": handoff.get("package_id"),
                   "previous_delivered_version": delivered_version,
                   "package_id": None, "receipt": None, "delivered_at": None}
    new_release = _reset_release(release, retry)
    record_topic_note(
        ledger, topic_id, db=db, event_type="release_retry", reason="new_paper_version",
        decided_by=decided_by,
        detail={"paper_id": paper_id, "reason": reason, "kind": "new_version",
                "previous_delivered_version": delivered_version, "version": version,
                "previous_package_id": handoff.get("package_id")},
        updates={"release": new_release, "handoff": new_handoff},
        key=f"release_retry:{topic_id}:new_version:{version}:{new_release['seq']}",
    )
    return {"schema_version": "openlabs.program_release_retry.v1", "topic_id": topic_id,
            "paper_id": paper_id, "kind": "new_version", "stage": "check",
            "release_reset": True, "handoff_reset": True,
            "previous_delivered_version": delivered_version, "version": version}


def _retry_returned_review(db, paths, settings, ledger, topic, *, paper_id: str, by: str,
                           reason: str, status=None) -> dict[str, Any]:
    """The pipeline sent the topic back to review, yet the paper is ready and current.

    The topic goes ``in_review -> ready_queue``; its campaign is paused again, which
    cancels the queued ``release-review:`` full review; delivery is queued. Refused
    unless the release was returned to review, the registered review is ready and
    bound to the current manuscript, and no such full review is running.
    """

    topic_id = str(topic["topic_id"])
    release = dict(topic.get("release") or {})
    handoff = dict(topic.get("handoff") or {})
    if release.get("status") != "returned_to_review":
        raise DeliveryError(
            f"topic {topic_id} holds paper {paper_id} in review, but its release is "
            f"{release.get('status') or 'pending'!r}, not 'returned_to_review'; nothing to retry")
    if status is None:
        status = run_release_status(paths, settings, paper_id)
    review = dict(status.get("review") or {})
    if status.get("frozen"):
        raise DeliveryError(f"paper {paper_id} is frozen: {status['frozen']}")
    review_tasks = list(dict.fromkeys(
        str((entry.get("detail") or {}).get("review_task_id") or "")
        for entry in topic.get("history") or []
        if entry.get("kind") == "release_returned_to_review"
        and (entry.get("detail") or {}).get("review_task_id")))
    running = [task_id for task_id in review_tasks
               if (db.task(task_id) or {}).get("status") in {"leased", "running"}]
    if running:
        raise DeliveryError(
            f"paper {paper_id}: the full review {', '.join(running)} is already running; let it "
            "finish (a ready result queues delivery) or stop it through the control plane first")
    pending = pending_decision(db, str(topic["campaign_id"]))
    if pending:
        return {"schema_version": "openlabs.program_release_retry.v1", "kind": "direction_pending",
                "paper_id": paper_id, "topic_id": topic_id, "direction_task_id": pending}
    cap = review.get("exhausted_review")
    if cap and review.get("ready") and not review.get("current"):
        delta = run_delta_review(paths, settings, paper_id)
        if delta.get("outcome") == "ready":
            review = run_release_status(paths, settings, paper_id)["review"]
            cap = None
        elif delta.get("outcome") != TRIGGER_REVIEW_ROUNDS:
            raise DeliveryError(f"delta review ended with {delta.get('outcome')!r}")
    if cap:
        for previous_id, previous in _decisions(db).items():
            if (previous.get("campaign_id") == topic["campaign_id"] and
                    previous.get("trigger") == TRIGGER_REVIEW_ROUNDS and
                    previous.get("source_task_id") == cap["decision_record_sha256"] and
                    previous.get("outcome") == "executed"):
                return {"schema_version": "openlabs.program_release_retry.v1",
                        "kind": "direction_executed", "topic_id": topic_id,
                        "paper_id": paper_id, "direction_task_id": previous_id}
        from .engine import TickReport
        evidence = [_write_evidence(paths, topic_id, "release-retry-direction", {
            "paper_id": paper_id, "by": by, "reason": reason, "review": cap})]
        task_id = _schedule_cap(db, paths, settings, TickReport(), topic, cap, evidence)
        db.pause_production_campaign(str(topic["campaign_id"]), reason="review_rounds_exhausted")
        record_topic_note(
            ledger, topic_id, db=db, event_type="release_retry", reason=TRIGGER_REVIEW_ROUNDS,
            decided_by=by, updates={"release": {**release, "direction_task_id": task_id}},
            detail={"paper_id": paper_id, "direction_task_id": task_id}, evidence=evidence,
            key=f"release_retry_direction:{task_id}")
        return {"schema_version": "openlabs.program_release_retry.v1", "kind": "direction_pending",
                "paper_id": paper_id, "topic_id": topic_id, "direction_task_id": task_id}
    if not (review.get("ready") and review.get("current")):
        problems = "; ".join(str(item) for item in review.get("problems") or [])[:400]
        raise DeliveryError(
            f"paper {paper_id}: the registered review is not ready and current "
            f"(ready={bool(review.get('ready'))}, current={bool(review.get('current'))}"
            f"{': ' + problems if problems else ''}); the full review has to decide")
    decided_by = f"manual:{by}"
    evidence = [_write_evidence(paths, topic_id, "release-retry-ready", {
        "paper_id": paper_id, "reason": reason, "by": decided_by, "version": status.get("version"),
        "review": {key: review.get(key) for key in ("ready", "current", "review_mode",
                                                    "decision_record", "version")}})]
    mark_topic_ready(ledger, topic_id, db=db, decided_by=decided_by, paper_id=paper_id,
                     evidence=evidence)
    campaign_id = str(topic.get("campaign_id") or "")
    cancelled: list[str] = []
    if campaign_id and db.campaign(campaign_id) is not None:
        cancelled = list(db.pause_production_campaign(campaign_id, reason="release_retry_ready"))
    # pause cancels queued and awaiting-remote work; nothing else is left pending
    # (running reviews were refused above), so every release review is now settled.
    review_task_status = {task_id: (db.task(task_id) or {}).get("status") for task_id in review_tasks}
    retry = {"at": utc_now(), "by": decided_by, "reason": reason, "kind": "returned_review_ready",
             "stage": release.get("stage"), "previous_status": release.get("status"),
             "cancelled_tasks": cancelled}
    new_release = _reset_release(release, retry)
    new_handoff = {**handoff, "status": "queued", "attempts": 0, "paper_id": paper_id,
                   "last_error": None, "queued_at": utc_now()}
    record_topic_note(
        ledger, topic_id, db=db, event_type="release_retry", reason="review_ready_and_current",
        decided_by=decided_by,
        detail={"paper_id": paper_id, "reason": reason, "kind": "returned_review_ready",
                "campaign_id": campaign_id or None, "cancelled_tasks": cancelled,
                "release_review_tasks": review_task_status},
        evidence=evidence, updates={"release": new_release, "handoff": new_handoff},
        key=f"release_retry:{topic_id}:returned_review:{new_release['seq']}",
    )
    return {"schema_version": "openlabs.program_release_retry.v1", "topic_id": topic_id,
            "paper_id": paper_id, "kind": "returned_review_ready", "stage": "check",
            "release_reset": True, "handoff_reset": True, "campaign_id": campaign_id or None,
            "campaign_paused": bool(campaign_id and db.campaign(campaign_id) is not None),
            "cancelled_tasks": cancelled,
            "release_review_cancelled": [task_id for task_id in review_tasks
                                         if task_id in cancelled],
            "release_review_tasks": review_task_status}


def assign_submission_handler(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    *,
    paper_id: str,
    handler: str = "second_author",
    assigned_by: str = "owner",
    conditions_met: bool = False,
) -> dict[str, Any]:
    """After the owner's review: assign the paper's submission handler (default second author).

    Admission conditions due ``before_submission`` block the assignment until the
    owner states they are met (``conditions_met``).
    """

    ledger = _ledger(paths, settings)
    document = ledger.read()
    topic = next((item for item in document.get("topics") or []
                  if str(item.get("paper_id") or "") == paper_id
                  or str((item.get("handoff") or {}).get("paper_id") or "") == paper_id), None)
    blockers = submission_conditions(topic) if topic is not None else []
    if blockers and not conditions_met:
        raise DeliveryError(
            f"{len(blockers)} admission condition(s) due before submission are open: "
            + "; ".join(item["description"] for item in blockers)
            + " (confirm with --conditions-met once they are met)"
        )
    result = run_handler_assignment(paths, settings, paper_id, handler)
    if topic is not None:
        record_topic_note(
            ledger, str(topic["topic_id"]), db=db, event_type="submission_handler_assigned",
            reason="owner_review_completed", decided_by=f"manual:{assigned_by}",
            detail={"paper_id": paper_id, "handler": handler,
                    "assigned": result.get("submission_handler"),
                    "submission_conditions_confirmed": blockers},
            updates={"awaiting_owner_review": False},
        )
    return {"schema_version": "openlabs.program_handler_assignment.v1",
            "topic_id": topic.get("topic_id") if topic else None, **result}


def _sync_site_assignments(db, paths, settings, report) -> None:
    """Site submitter assignments follow readiness (user rule 2026-11-23; site_assignment.py)."""

    from .site_assignment import sync_tick

    sync_tick(db, paths, settings, report)


ROUND_USAGE_STATUSES = frozenset({"active", "in_review", "ready_queue"})
# The round report reads every decision record of the papers it lists: refresh it at most this
# often and show the last result in between.
ROUND_USAGE_REFRESH_SECONDS = 1_800


def _sync_submission_status(db, paths, settings, report) -> None:
    """The registry follows the site's submission status (2026-11-26; submission_status.py)."""

    from .submission_status import sync_tick

    sync_tick(db, paths, settings, report)


def _report_round_usage(db, paths, settings, report) -> None:
    """Rounds per paper (B4, 2026-11-25): used at the target journal, the limit in force (a
    round grant and whether it expired), and the cross-journal total -- reported only, there
    is no cross-journal budget (user 2026-11-25: "不要设跨刊总轮次"). Never a tick error."""

    info = report.program.setdefault("round_usage", {})
    cache = paths.database / "round-usage.json"
    try:
        cached = json.loads(cache.read_text(encoding="utf-8"))
        age = time.time() - float(cached.get("checked_epoch") or 0)
    except (OSError, ValueError, TypeError, AttributeError):
        cached, age = None, None
    if cached is not None and age is not None and 0 <= age < ROUND_USAGE_REFRESH_SECONDS:
        info.update({key: cached.get(key) for key in ("outcome", "papers", "checked_at")},
                    cross_journal_budget=None, cached=True)
        return
    topics = _ledger(paths, settings).read().get("topics") or []
    paper_ids = sorted({str(item.get("paper_id") or (item.get("handoff") or {}).get("paper_id"))
                        for item in topics if item.get("status") in ROUND_USAGE_STATUSES
                        and (item.get("paper_id") or (item.get("handoff") or {}).get("paper_id"))})
    arguments = ["review", "round-usage", "--with-grants"]
    for paper_id in paper_ids:
        arguments += ["--paper-id", paper_id]
    try:
        result = _run_paper_command(paths, settings, arguments, timeout=300)
    except DeliveryError as exc:
        info.update(outcome="failed", error=str(exc)[:300])
        return
    rows: dict[str, dict[str, Any]] = {}
    for entry in result.get("papers") or []:
        if not isinstance(entry, dict) or not entry.get("paper_id"):
            continue
        row = {key: entry.get(key) for key in (
            "target_journal", "used_at_target", "limit", "limit_source", "granted",
            "grant_status", "grant_expired_because", "all_targets_total", "error", "grant_error")
            if entry.get(key) is not None}
        condition = entry.get("grant_condition") or {}
        if condition.get("cycle") and not settings.program.polish_mode:
            row["grant_cycle_ended"] = condition["cycle"]
        if entry.get("extension_refused"):
            row["extension_refused"] = entry["extension_refused"]
        rows[str(entry["paper_id"])] = row
    info.update(outcome="ok", papers=rows, checked_at=utc_now(), cross_journal_budget=None)
    try:
        atomic_write_json(cache, {**info, "checked_epoch": time.time()})
    except OSError:
        pass


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
                       ("registered_reviews", _queue_resynthesized), ("delivery", _deliver_ready),
                       ("delivery_repairs", _repair_delivery), ("site_assignments", _sync_site_assignments),
                       ("submission_status", _sync_submission_status),
                       ("delivery_chain", report_delivery_chain),
                       ("round_usage", _report_round_usage)):
        try:
            step(db, paths, settings, report)
        except (OSError, TopicLedgerError, KeyError, TypeError, ValueError,
                json.JSONDecodeError) as exc:
            report.errors.append(f"program autonomy ({name}): {exc}")
    for key in ("direction_decisions", "topics_frozen", "ready_queued", "handoffs", "releases",
                "release_exhausted", "delivery_chain", "delivery_stuck"):
        report.program.setdefault(key, [])
