from __future__ import annotations

from datetime import datetime, timezone

from paper_writing.journal_history import venue_type_for
from paper_writing.submission_cadence import DEFAULTS, evaluate_cadence
from paper_writing.submission_monitor import build_report, format_report

NOW = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)


def ledger(active=(), rejections=()):
    return {"active_submissions": list(active), "rejections": list(rejections)}


def test_clear_venue_is_allowed() -> None:
    result = evaluate_cadence(ledger(), venue="Graphs and Combinatorics", paper_id="p", config=DEFAULTS, now=NOW)
    assert result["status"] == "ok" and result["violations"] == []


def test_second_concurrent_team_paper_at_same_venue_is_blocked() -> None:
    active = [{"paper_id": "q", "journal": "Graphs and Combinatorics", "status": "under_review",
               "submitted_at": "2026-09-01T00:00:00+08:00"}]
    result = evaluate_cadence(ledger(active), venue="GCOM", paper_id="p", config=DEFAULTS, now=NOW)
    assert result["status"] == "blocked"
    assert any("already under consideration" in v for v in result["violations"])


def test_paper_already_at_venue_is_exempt() -> None:
    active = [{"paper_id": "p", "journal": "Graphs and Combinatorics", "status": "under_review"}]
    assert evaluate_cadence(ledger(active), venue="Graphs and Combinatorics", paper_id="p",
                            config=DEFAULTS, now=NOW)["status"] == "ok"


def test_recent_same_venue_and_weekly_burst_and_cooldown() -> None:
    rejections = [
        {"paper_id": "a", "journal": "European Journal of Combinatorics", "submitted_at": "2026-10-20T00:00:00Z",
         "rejected_at": "2026-10-25T00:00:00Z"},
        {"paper_id": "p", "journal": "Discrete Mathematics", "submitted_at": "2026-11-01T00:00:00Z",
         "rejected_at": "2026-11-05T00:00:00Z"},
    ]
    active = [{"paper_id": x, "journal": f"J{x}", "status": "submitted", "submitted_at": "2026-11-06T00:00:00Z"}
              for x in ("b", "c")]
    result = evaluate_cadence(ledger(active, rejections), venue="EJC", paper_id="p", config=DEFAULTS, now=NOW)
    text = " ".join(result["violations"])
    assert "minimum spacing 30 days" in text
    assert "3 team submissions in the last 7 days" in text
    assert "was rejected on 2026-11-05" in text
    assert result["next_allowed_at"].startswith("2026-11-19")


def test_conference_names_are_not_counted_as_journals() -> None:
    assert venue_type_for("International Conference on Machine Learning and Data Security (MLDS 2026)") == "conference"
    assert venue_type_for("ICONIP 2026") == "conference"
    assert venue_type_for("Journal of Applied Genetics") == "journal"


def test_monitor_reports_deadlines_stale_and_missing_letters() -> None:
    papers = [
        {"paper_id": "rev", "submission_attempts": [{"id": "a1", "journal_name": "Nuclear Physics B",
                                                      "status": "under_review", "submitted_at": "2026-09-19T00:00:00Z"}],
         "review_rounds": [{"attempt_id": "a1", "decision": "major_revision", "due_at": "2026-11-11T00:00:00Z"}]},
        {"paper_id": "old", "submission_attempts": [{"id": "a2", "journal_name": "Forum Mathematicum",
                                                      "status": "submitted", "submitted_at": "2026-08-16T00:00:00+08:00"}]},
        {"paper_id": "rej", "submission_attempts": [{"id": "a3", "journal_name": "X", "status": "rejected"}],
         "submission_events": []},
    ]
    report = build_report(papers, now=NOW)
    assert report["revision_deadlines"][0]["urgency"] == "urgent"
    assert report["stale_submissions"][0]["paper_id"] == "old"
    assert report["missing_decision_letters"] == [{"paper_id": "rej", "venue": "X",
                                                   "action": "retrieve the decision letter and reviewer reports"}]
    assert "返修截止" in format_report(report)
