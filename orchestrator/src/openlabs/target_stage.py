"""Research target stages and replay of the unattended delivery criterion.

Stages: ``run_in`` and ``tier2_aim`` (2026-11-22, recorded per line by events, promoted after
an unattended delivery) and ``nc_aim`` (user decision 2026-11-25, UD-20261125-nc-aim: every
topic aims at Nature Communications and the results decide the journal). The current stage
comes from ``[program.funnel].target_stage``: ``nc_aim`` is the single stage of every line;
``line_events`` restores the per-line event mechanism. Topics admitted under an older stage
keep it (their admission record's ``target_stage``), so their grading and delivery replay
as they were admitted.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping

from .db import utc_now

# Start of the run_in observation window (line_events mode only; historical replay).
# The last production fast-forward of P1/P2/S6/G1: S6 a6a3d4f.
CUTOFF = "2026-11-22T01:35:00Z"
RUN_IN = "run_in"
TIER2_AIM = "tier2_aim"
NC_AIM = "nc_aim"
LINE_EVENTS = "line_events"
STAGES = (RUN_IN, TIER2_AIM, NC_AIM)
# Stages whose topics get an acceptance grade before delivery.
GRADED_STAGES = (TIER2_AIM, NC_AIM)
CHANGE = "research_line_target_stage_changed"
LIFECYCLE = ("topic_proposed", "topic_admitted", "topic_activated",
             "topic_in_review", "topic_ready")

TIER2_INSTRUCTION = (
    " For tier2_aim cards, describe in tier_rationale the substantive advance over the "
    "closest recent precedent, accessible data and scale, strong controls, and independent "
    "or external validation. Judge this as a plausible CAS Zone 1–2 contribution even for "
    "template, queue or revision cards. Reject ideas with clearly insufficient contribution. "
    "The actual results will determine the journal tier after research."
)

ADMISSION_INSTRUCTION = (
    " For each tier2_aim admit, set admission.tier2_contribution_supported to true "
    "only after independently checking the named precedent and the available evidence "
    "design. Explain your finding in admission.tier_rationale."
)


def card_errors(card: Mapping, stage: str) -> list[str]:
    rationale = card.get("tier_rationale")
    if stage == TIER2_AIM and (
        not isinstance(rationale, str) or not rationale.strip()
    ):
        return ["tier2_aim requires tier_rationale covering contribution, data and validation"]
    if stage == NC_AIM:
        from .nc_funnel import card_contract_errors

        return card_contract_errors(card)
    return []


def configured_stage(settings) -> str | None:
    """The one stage every line has under ``[program.funnel]``, or None (line events)."""

    funnel = getattr(getattr(settings, "program", None), "funnel", None)
    stage = getattr(funnel, "target_stage", LINE_EVENTS) if funnel is not None else LINE_EVENTS
    return stage if stage in STAGES else None


def scout_instruction(stage: str) -> str:
    if stage == TIER2_AIM:
        return TIER2_INSTRUCTION
    if stage == NC_AIM:
        from .nc_funnel import SCOUT_INSTRUCTION

        return SCOUT_INSTRUCTION
    return ""


def admission_instruction(stages) -> str:
    stages = set(stages)
    text = TIER2_INSTRUCTION + ADMISSION_INSTRUCTION if TIER2_AIM in stages else ""
    if NC_AIM in stages:
        from .nc_funnel import ADMISSION_NC_INSTRUCTION

        text += ADMISSION_NC_INSTRUCTION
    return text


def _state(connection, line: str) -> dict:
    row = connection.execute(
        "SELECT payload_json FROM events WHERE entity_type='research_line' AND entity_id=? "
        "AND event_type=? ORDER BY event_id DESC LIMIT 1", (line, CHANGE),
    ).fetchone()
    return json.loads(row[0]) if row else {"stage": RUN_IN}


def stage_for(db, line: str | None, settings=None) -> str:
    """The stage new cards of ``line`` are judged by (configured stage first)."""

    fixed = configured_stage(settings) if settings is not None else None
    if fixed is not None:
        # A line with nc_aim = false keeps its recorded stage ([program.lines]).
        if settings.program.line(line).nc_aim:
            return fixed
    if not isinstance(line, str) or not line or db is None:
        return RUN_IN
    with db.connect() as connection:
        return _state(connection, line)["stage"]


def set_stage(db, line: str, stage: str, *, by: str, reason: str,
              evidence: Mapping | None = None) -> dict:
    if not line or stage not in STAGES or not by.strip() or not reason.strip():
        raise ValueError("a research line, valid stage, actor and reason are required")
    with db.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        previous = _state(connection, line)
        # A manual reset to run_in starts a new observation window.
        if evidence is not None and (
            previous["stage"] != RUN_IN
            or evidence["proposed_at"] < previous.get("changed_at", "")
        ):
            return previous
        now = utc_now()
        decision = {"previous_stage": previous["stage"], "stage": stage,
                    "by": by.strip(), "reason": reason.strip(), "changed_at": now,
                    "observation_from": now if stage == RUN_IN else previous.get(
                        "observation_from", CUTOFF
                    )}
        if evidence is not None:
            decision["evidence"] = dict(evidence)
        db._event(connection, "research_line", line, CHANGE, decision)
    return decision


def replay(db, document: Mapping, lines) -> dict[str, dict]:
    """Replay recorded decisions using topic and linked task/campaign events."""
    topic_events = defaultdict(list)
    task_events = defaultdict(list)
    with db.connect() as connection:
        connection.execute("BEGIN")
        states = {line: _state(connection, line) for line in lines}
        # Keep all topic milestones, including pre-cutoff events for old deliveries.
        rows = connection.execute(
            """
            SELECT e.*, t.campaign_id AS task_campaign FROM events e
            LEFT JOIN tasks t ON e.entity_type='task' AND t.task_id=e.entity_id
            WHERE e.entity_type='topic'
            OR (e.entity_type='task' AND e.event_type IN (
                'manual_requeue', 'task_enqueued', 'quota_override_task'))
            ORDER BY e.event_id
            """,
        )
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            if item["entity_type"] == "topic":
                topic_events[item["entity_id"]].append(item)
            elif item["entity_type"] == "task":
                task_events[item["entity_id"]].append(item)
                campaign = item["payload"].get("campaign_id") or item["task_campaign"]
                if campaign:
                    task_events[campaign].append(item)
    result = {
        line: {"target_stage": state["stage"], "target_stage_decision": state,
               "run_in_progress": {"cutoff": CUTOFF, "required": 1, "qualified": 0,
                                   "post_cutoff_proposals": 0,
                                   "observation_from": state.get("observation_from", CUTOFF),
                                   "handoffs": [], "qualifying_evidence": []}}
        for line, state in states.items()
    }
    topics = {topic["topic_id"]: topic for topic in document.get("topics") or []}
    for topic in topics.values():
        line = topic.get("research_line")
        if line not in result:
            continue
        progress = result[line]["run_in_progress"]
        events = topic_events[topic["topic_id"]]
        proposed = next((event for event in events if event["event_type"] == LIFECYCLE[0]), None)
        if proposed and proposed["created_at"] >= CUTOFF:
            progress["post_cutoff_proposals"] += 1
        for event in events:
            if event["event_type"] != "handoff_delivered":
                continue
            evidence = _delivery_evidence(topic, event, topics, topic_events, task_events)
            progress["handoffs"].append(evidence)
            if not evidence["blockers"] and evidence["proposed_at"] >= progress["observation_from"]:
                progress["qualifying_evidence"].append(evidence)
    for entry in result.values():
        progress = entry["run_in_progress"]
        progress["qualified"] = len({x["topic_id"] for x in progress["qualifying_evidence"]})
        progress["handoffs"].sort(key=lambda item: item["event_id"])
        progress["qualifying_evidence"].sort(key=lambda item: item["event_id"])
    return result


def _delivery_evidence(topic, delivery, topics, topic_events, task_events) -> dict:
    end = delivery["event_id"]
    events = topic_events[topic["topic_id"]]
    trail = [next((e for e in events if e["event_type"] == kind
                   and e["event_id"] < end), None) for kind in LIFECYCLE]
    proposed, admitted = trail[:2]
    blockers = []
    if not proposed or proposed["created_at"] < CUTOFF:
        blockers.append("proposal_missing_or_before_cutoff")
    if not all(trail) or any(a["event_id"] >= b["event_id"] for a, b in zip(trail, trail[1:])):
        blockers.append("incomplete_lifecycle")
    body = delivery["payload"]
    campaign = body.get("campaign_id")
    if not campaign or any(not e or e["payload"].get("campaign_id") != campaign for e in trail[2:]):
        blockers.append("campaign_link_missing")
    detail = body.get("detail") or {}
    if body.get("decided_by") != "orchestrator:auto_handoff" or not detail.get("package_id"):
        blockers.append("automatic_handoff_receipt_missing")
    ids = {campaign, topic.get("source_task_id"), topic.get("proposer_task_id")}
    related = []
    lineage_start = proposed["created_at"] if proposed else None
    ancestor = topic
    seen = {topic["topic_id"]}
    while ancestor:
        parent = ancestor.get("repair_of") or ancestor.get("revision_of") or ancestor.get("supersedes")
        if not parent:
            break
        if parent in seen or parent not in topics:
            blockers.append("unverifiable_topic_lineage")
            break
        seen.add(parent)
        ancestor = topics[parent]
        earlier = [e for e in topic_events[parent] if e["event_id"] < end]
        related.extend(earlier)
        earlier_proposal = next((e for e in earlier if e["event_type"] == LIFECYCLE[0]), None)
        if not earlier_proposal:
            blockers.append("unverifiable_topic_lineage")
        else:
            lineage_start = min(lineage_start or earlier_proposal["created_at"],
                                earlier_proposal["created_at"])
        ids.update({ancestor.get("source_task_id"), ancestor.get("proposer_task_id")})
        ids.update(e["payload"].get("campaign_id") for e in earlier)
        ids.update(e["payload"].get("decided_by") for e in earlier if e["event_type"] in LIFECYCLE)
    if lineage_start and lineage_start < CUTOFF and proposed and proposed["created_at"] >= CUTOFF:
        blockers.append("topic_lineage_before_cutoff")
    for milestone, routes in ((proposed, {"program_slot_open", "topic_card_repair",
                                          "topic_revision"}),
                              (admitted, {"topic_admission"})):
        if not milestone:
            continue
        actor = milestone["payload"].get("decided_by")
        if milestone is admitted and str(actor).startswith("program:line-ready:"):
            actor = topic.get("admission_task_id")
        ids.add(actor)
        if milestone["created_at"] >= CUTOFF and not any(
            e["event_type"] == "task_enqueued" and e["event_id"] < milestone["event_id"]
            and e["created_at"] >= CUTOFF and e["payload"].get("routing_reason") in routes
            for e in task_events[actor]
        ):
            blockers.append(f"{milestone['event_type']}_automatic_task_missing")
    topic_trail = [e for e in [*events, *related] if e["event_id"] <= end]
    for event in topic_trail:
        payload = event["payload"]
        detail = payload.get("detail") or {}
        ids.update(value for value in (
            payload.get("decided_by"), payload.get("task_id"), detail.get("task_id"),
            detail.get("source_task_id"), detail.get("executed_task_id"),
        ) if isinstance(value, str))
    interventions = {
        e["event_id"]: e["event_type"]
        for e in [*topic_trail, *(e for key in ids if key for e in task_events[key])]
        if e["event_id"] <= end and _manual(e)
    }
    if interventions:
        blockers.append("human_intervention")
    return {"topic_id": topic["topic_id"], "event_id": end,
            "paper_id": detail.get("paper_id"),
            "proposed_at": lineage_start, "delivered_at": delivery["created_at"],
            "blockers": list(dict.fromkeys(blockers)), "interventions": dict(sorted(interventions.items()))}


def _manual(event: Mapping) -> bool:
    kind, payload = event["event_type"], event["payload"]
    actor = str(payload.get("decided_by") or "")
    if actor.startswith(("manual:", "operator:", "human:")):
        return True
    if kind == "release_retry":
        return payload.get("reason") != "code_updated" and not actor.startswith("orchestrator:")
    if kind in {"manual_requeue", "operator_reopen_granted", "quota_override_task",
                "delivered_revision_requested"}:
        return True
    return kind == "task_enqueued" and (
        payload.get("operator_dispatched") is True
        or str(payload.get("routing_reason") or "").startswith(("manual", "operator"))
    )


def refresh(db, document: Mapping, lines, settings=None) -> dict[str, dict]:
    entries = replay(db, document, lines)
    fixed = configured_stage(settings) if settings is not None else None
    if fixed is not None:
        # One configured stage: the run_in replay is history only, nothing is promoted.
        for line, entry in entries.items():
            entry["target_stage"] = stage_for(db, line, settings)
            entry["target_stage_source"] = "[program.funnel].target_stage"
        return entries
    for line, entry in entries.items():
        if entry["target_stage"] != RUN_IN:
            continue
        for evidence in entry["run_in_progress"]["qualifying_evidence"]:
            decision = set_stage(db, line, TIER2_AIM, by="orchestrator",
                                 reason="unattended_delivery", evidence=evidence)
            entry.update(target_stage=decision["stage"], target_stage_decision=decision)
            if decision["stage"] == TIER2_AIM:
                break
    return entries


def admitted_stage(topic: Mapping) -> str:
    admission = topic.get("admission")
    stage = admission.get("target_stage") if isinstance(admission, Mapping) else None
    return stage if stage in STAGES else RUN_IN


def graded_topic(topic: Mapping) -> bool:
    """A topic admitted under a stage whose delivery waits for an acceptance grade."""

    return admitted_stage(topic) in GRADED_STAGES


# Former name (tier2 only); every graded stage now.
tier2_topic = graded_topic

def venue_grade(decision: Mapping, venues: list[dict], *, stage: str = TIER2_AIM,
                settings=None) -> dict | None:
    """Check that the chosen verified journal belongs to the judged evidence band."""
    if stage == NC_AIM:
        from .nc_funnel import nc_grade

        return nc_grade(decision, venues, settings)
    retarget = decision["retarget"]
    journal = retarget["venue_or_format"]
    zone = next((v["cas_2025_zone"] for v in venues if v["journal"] == journal), None)
    bands = {1: "zones_1_2", 2: "zones_1_2", 3: "zones_3_4", 4: "zones_3_4"}
    band = bands.get(zone)
    if band is None or band != retarget.get("achieved_band"):
        return None
    return {"journal": journal, "cas_2025_zone": zone, "achieved_band": band,
            "rationale": decision["rationale"], "why_fits": retarget["why_fits"]}
