"""Read-only research line funnel from recorded milestones."""
from collections import Counter, defaultdict

import yaml

from .contracts import IDENTIFIER
from .delivery_facts import ever_delivered
from .usage import _review_runs, attempt_figures, campaign_core_hours, normalized_attempts

STAGES = {
    "active": "started", "frozen": "frozen", "in_review": "sent_for_review",
    "ready_queue": "ready", "submitted": "human_confirmed_submission",
}
PILOT_RESULTS = {"card_pilot_pass", "card_pilot_fail", "card_pilot_reused", "card_pilot_failed"}
DECISIONS = {"accepted", "rejected", "desk_rejected", "major_revision", "minor_revision",
             "revise_and_resubmit", "revision_requested"}


def _line(topic):
    return topic.get("research_line") or f"legacy:{topic.get('domain') or 'unknown'}"


def funnel(document, data):
    lines = {}
    submission_events = defaultdict(list)
    for topic in document["topics"]:
        line = _line(topic)
        stages = lines.setdefault(line, defaultdict(set))
        topic_id = topic["topic_id"]
        paper_id = topic.get("paper_id")
        history = topic["history"]
        states = {topic["status"], *(entry.get("to") for entry in history)}
        reasons = {entry.get("reason") for entry in history}
        stages["candidates"].add(topic_id)
        for state, stage in STAGES.items():
            if state in states:
                stages[stage].add(topic_id if stage in {"started", "frozen"} else paper_id or topic_id)
        if reasons & PILOT_RESULTS:
            stages["pilot_completed"].add(topic_id)
        if paper_id and ever_delivered(topic):  # delivery_facts (B5): any version, ever
            stages["delivered"].add(paper_id)
        if not paper_id or not IDENTIFIER.fullmatch(paper_id):
            continue
        try:
            paper = yaml.safe_load((data / "registry" / "papers" / f"{paper_id}.yaml").read_text())
        except (OSError, UnicodeError, yaml.YAMLError):
            stages["missing_paper_record"].add(paper_id)
            continue
        if not isinstance(paper, dict):
            stages["missing_paper_record"].add(paper_id)
            continue
        events = [event for event in paper.get("submission_events") or [] if isinstance(event, dict)]
        types = {event.get("event_type") for event in events}
        rejections = paper.get("journal_rejections") or []
        if types & {"submitted", "resubmitted"} or rejections:
            stages["human_confirmed_submission"].add(paper_id)
        if rejections or types & DECISIONS or any(
            isinstance(review, dict) and review.get("decision") in DECISIONS
            for review in paper.get("review_rounds") or []
        ):
            stages["decision_received"].add(paper_id)
        if events and not any(item["paper_id"] == paper_id for item in submission_events[line]):
            submission_events[line].append({
                "paper_id": paper_id,
                "events": [{key: str(event[key]) if event.get(key) is not None else None
                            for key in ("event_type", "attempt_id", "occurred_at")}
                           for event in events],
            })
    keys = ("candidates", "pilot_completed", "started", "frozen", "sent_for_review", "ready",
            "delivered", "human_confirmed_submission", "decision_received", "missing_paper_record")
    return {line: {**{key: len(stages[key]) for key in keys},
                   "submission_events": submission_events[line]}
            for line, stages in sorted(lines.items())}


def with_costs(document, db, paths, settings):
    """Attribute observed costs and expose coverage gaps explicitly."""
    lines = funnel(document, paths.data)
    owners = {}
    pilot_hours = defaultdict(dict)
    for topic in document["topics"]:
        line = _line(topic)
        for key in ("campaign_id", "proposer_task_id", "source_task_id", "admission_task_id"):
            if topic.get(key):
                owners.setdefault(topic[key], set()).add(line)
        for entry in topic["history"]:
            if entry.get("reason") not in PILOT_RESULTS:
                continue
            detail = entry.get("detail") or {}
            hours, job = detail.get("used_core_hours"), detail.get("job_id")
            if job and isinstance(hours, (float, int)):
                pilot_hours[line][job] = hours
    for event in db.events(entity_type="program"):
        if event["event_type"] == "topic_scout_scheduled":
            payload = event["payload"]
            if payload.get("task_id") and payload.get("research_line"):
                owners[payload["task_id"]] = {payload["research_line"]}
    costs = defaultdict(Counter)
    review_usage = _review_runs(db, paths.data)
    for attempt in normalized_attempts(db):
        if not attempt["finished_at"] or attempt["status"] == "quota_deferred":
            continue
        attribution = owners.get(attempt["task_id"]) or owners.get(attempt["campaign_id"]) or set()
        line = next(iter(attribution)) if len(attribution) == 1 else "unattributed"
        row = costs[line]
        figures = attempt_figures(attempt, settings)
        if figures["has_usage"] and figures["equivalent_usd"] is not None:
            row["model_usd_equivalent"] += figures["equivalent_usd"]
        else:
            row["missing_model_attempts"] += 1
        for role in review_usage.pop(attempt["task_id"], []):
            if role["equivalent_usd"] is None:
                row["unpriced_review_roles"] += 1
            else:
                row["model_usd_equivalent"] += role["equivalent_usd"]
        if attempt["run_seconds"] is not None:
            row["agent_wall_hours"] += figures["agent_seconds"] / 3600
        else:
            row["missing_wall_attempts"] += 1
    campaigns = {topic["campaign_id"]: db.campaign(topic["campaign_id"]) or {}
                 for topic in document["topics"] if topic.get("campaign_id")}
    groups = {campaign: next(iter(owners[campaign])) if len(owners[campaign]) == 1
              else "unattributed" for campaign in campaigns}
    core_hours = campaign_core_hours(
        db, campaigns, attempt_root=paths.attempt_workspaces, job_groups=groups
    )
    for campaign, hours in core_hours.items():
        if hours > 0:
            costs[groups[campaign]]["cpu_core_hours"] += hours
    for line, jobs in pilot_hours.items():
        costs[line]["cpu_core_hours"] += sum(jobs.values())
    for line, row in lines.items():
        observed = {key: round(costs[line][key], 3) if key in costs[line] else None
                    for key in ("model_usd_equivalent", "cpu_core_hours", "agent_wall_hours")}
        observed["human_review_hours"] = None
        row["observed_cost"] = observed
        row["missing_model_attempts"] = costs[line]["missing_model_attempts"]
        row["missing_wall_attempts"] = costs[line]["missing_wall_attempts"]
        row["unpriced_review_roles"] = costs[line]["unpriced_review_roles"]
        for stage, unit in (("delivered", "paper"), ("started", "started_topic")):
            row[f"observed_cost_per_{unit}"] = {
                key: round(value / row[stage], 3) if value is not None and row[stage] else None
                for key, value in observed.items()
            }
    return {
        "lines": lines,
        "unattributed": {line: dict(cost) for line, cost in costs.items() if line not in lines},
        "coverage": "Recorded ledger and local paper registry only. Site-only journal events "
                    "may be missing. Wall time sums agent attempts. Shared jobs are counted once "
                    "per line. Unlinked jobs, reviewer usage and human hours may be missing.",
    }
