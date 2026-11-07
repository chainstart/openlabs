"""Read-only monitor for ongoing submissions, revision deadlines and missing decision letters.

Revisions produced every accepted paper in the 2026-11 audit (Scientific Reports after major
revision, Mathematics after minor revision), while some attempts sat for months without a
status change.  This report surfaces both.  It never contacts journals or edits the site.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REVISION_DECISIONS = {"major_revision", "minor_revision", "revise_resubmit", "revision_requested"}
DEFAULT_THRESHOLDS = {
    "submitted_without_review_days": 45,
    "under_review_days": 120,
    "resubmitted_days": 90,
    "revision_warning_days": 10,
}


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def build_report(papers: Iterable[Mapping[str, Any]], *, now: datetime | None = None,
                 thresholds: Mapping[str, int] | None = None) -> dict[str, Any]:
    moment = now or datetime.now(timezone.utc)
    limits = {**DEFAULT_THRESHOLDS, **dict(thresholds or {})}
    stale, deadlines, missing_letters, active = [], [], [], []
    for paper in papers:
        pid = str(paper.get("paper_id") or "")
        attempts = {a.get("id"): a for a in paper.get("submission_attempts") or []}
        events = list(paper.get("submission_events") or [])
        for attempt in attempts.values():
            status = attempt.get("status")
            journal = attempt.get("journal_name") or ""
            if status in {"submitted", "under_review", "resubmitted"}:
                since = _time(attempt.get("submitted_at")) or _time(attempt.get("updated_at"))
                days = (moment - since).days if since else None
                active.append({"paper_id": pid, "title": paper.get("title"), "venue": journal,
                               "status": status, "days": days})
                limit = {"submitted": limits["submitted_without_review_days"],
                         "under_review": limits["under_review_days"],
                         "resubmitted": limits["resubmitted_days"]}[status]
                if days is None:
                    stale.append({"paper_id": pid, "venue": journal, "status": status, "days": None,
                                  "action": "record the actual submission date from the portal"})
                elif days > limit:
                    stale.append({"paper_id": pid, "venue": journal, "status": status, "days": days,
                                  "action": f"check the portal; send a polite status inquiry (> {limit} days)"})
            if status == "rejected":
                letters = [e for e in events if e.get("attempt_id") == attempt.get("id")
                           and e.get("event_type") == "rejected"]
                if not letters:
                    missing_letters.append({"paper_id": pid, "venue": journal,
                                            "action": "retrieve the decision letter and reviewer reports"})
        for round_ in paper.get("review_rounds") or []:
            if round_.get("decision") not in REVISION_DECISIONS or round_.get("response_submitted_at"):
                continue
            attempt = attempts.get(round_.get("attempt_id")) or {}
            if attempt.get("status") in {"resubmitted", "accepted", "published", "rejected", "withdrawn"}:
                continue
            due = _time(round_.get("due_at"))
            days_left = (due - moment).days if due else None
            urgency = ("overdue" if days_left is not None and days_left < 0 else
                       "urgent" if days_left is not None and days_left <= limits["revision_warning_days"] else
                       "unknown_due_date" if days_left is None else "scheduled")
            deadlines.append({"paper_id": pid, "venue": attempt.get("journal_name"),
                              "decision": round_.get("decision"), "due_at": round_.get("due_at"),
                              "days_left": days_left, "urgency": urgency})
    deadlines.sort(key=lambda r: (r["days_left"] is None, r["days_left"] if r["days_left"] is not None else 0))
    stale.sort(key=lambda r: -(r["days"] or 10**6))
    return {"checked_at": moment.isoformat(), "thresholds": limits, "active_submissions": len(active),
            "revision_deadlines": deadlines, "stale_submissions": stale,
            "missing_decision_letters": missing_letters, "active": active}


def load_snapshot(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, Mapping):
        data = data.get("data", data.get("papers"))
    if not isinstance(data, list):
        raise ValueError("snapshot must be a list of management-site paper details")
    return data


def format_report(report: Mapping[str, Any]) -> str:
    lines = [f"# 投稿监控 {report['checked_at'][:16]}", "",
             f"在审/已投：{report['active_submissions']} 次", "", "## 返修截止"]
    lines += [f"- [{r['urgency']}] {r['paper_id']} @ {r['venue']}：{r['decision']}，截止 {r['due_at'] or '未知'}"
              f"（剩 {r['days_left']} 天）" for r in report["revision_deadlines"]] or ["- 无"]
    lines += ["", "## 长时间无进展"]
    lines += [f"- {r['paper_id']} @ {r['venue']}：{r['status']} {r['days']} 天 → {r['action']}"
              for r in report["stale_submissions"]] or ["- 无"]
    lines += ["", f"## 缺决定信（{len(report['missing_decision_letters'])}）"]
    lines += [f"- {r['paper_id']} @ {r['venue']}" for r in report["missing_decision_letters"]] or ["- 无"]
    return "\n".join(lines) + "\n"
