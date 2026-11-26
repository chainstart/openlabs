import csv
import json
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from paper_writing.journal_history import (
    canonical_journal, check_journal, guard_target, refresh_history,
)
from paper_writing.registry import _validate_journal_target_policy


@pytest.fixture
def root(tmp_path):
    (tmp_path / "registry").mkdir()
    (tmp_path / "registry/settings.yaml").write_text(yaml.safe_dump({
        "schema_version": "ara.paper_writing.registry.v1",
        "journal_target_policy": {"team_rejection_history": {"enabled": True}},
    }))
    return tmp_path


def paper(pid, journal="European Journal of Combinatorics", status="rejected", attempt_id=None):
    aid = attempt_id or "attempt-" + pid
    return {"paper_id": pid, "title": pid, "submission_attempts": [{
        "id": aid, "journal_name": journal, "status": status,
        "manuscript_number": "number-" + pid,
        "closed_at": "2026-10-15T12:00:00+00:00" if status == "rejected" else None,
    }], "submission_events": []}


def test_deduplicate_letters_and_count_distinct_team_papers(root):
    p = paper("one", "EJC")
    p["submission_events"] = [{"id": "event1", "attempt_id": "attempt-one", "event_type": "rejected",
                               "occurred_at": "2026-10-15T12:00:00+00:00", "payload": {"reason_summary": "Narrow"}}] * 2
    same_paper_again = paper("one", attempt_id="attempt-other")
    refresh_history(root, [p, p, same_paper_again, paper("two"), paper("three")], source="test")
    result = check_journal(root, "EJC")
    assert result["status"] == "excluded"
    assert result["distinct_rejected_papers"] == 3
    assert result["rejected_attempts"] == 4
    with (root / "registry/journal-rejections.csv").open() as stream:
        assert len(list(csv.DictReader(stream))) == 4


def test_two_rejections_warn_without_merging_similar_journals(root):
    refresh_history(root, [paper("a", "DM"), paper("b", "Discrete Mathematics"),
                           paper("c", "SIAM Journal on Discrete Mathematics"),
                           paper("d", "The Electronic Journal of Combinatorics")], source="test")
    assert check_journal(root, "Discrete Mathematics")["status"] == "caution"
    assert check_journal(root, "EJC")["distinct_rejected_papers"] == 0
    assert canonical_journal("JCTB") != canonical_journal("JCTA")
    assert canonical_journal("JACO") != canonical_journal("Ann. Comb.")


def test_conferences_and_closed_attempts_never_exclude_journals(root):
    refresh_history(root, [paper(str(n), "PRICAI 2026") for n in range(4)] +
                    [paper("closed", "EJC", "closed")], source="test")
    assert check_journal(root, "PRICAI 2026")["distinct_rejected_papers"] == 0
    assert check_journal(root, "EJC")["status"] == "eligible"
    ledger = json.loads((root / "registry/journal-rejections.json").read_text())
    assert len(ledger["rejections"]) == 4
    assert all(r["venue_type"] == "conference" for r in ledger["rejections"])


def test_refresh_preserves_prior_refusals_and_missing_evidence(root):
    refresh_history(root, [paper("a")], source="test")
    refresh_history(root, [paper("b")], source="test")
    rows = check_journal(root, "EJC")["rejections"]
    assert len(rows) == 2
    assert all(r["evidence_level"] == "management_status_only" and not r["reason_summary"] for r in rows)


def test_threshold_blocks_new_targets_but_preserves_real_active_attempt(root):
    refresh_history(root, [paper(str(n)) for n in range(3)] +
                    [paper("ongoing", "EJC", "under_review")], source="test")
    policy = {"required_after_basic_draft": False, "team_rejection_history": {"enabled": True}}
    with pytest.raises(ValueError, match="3 distinct papers"):
        _validate_journal_target_policy({"target_journal": "EJC"}, paper_id="new", policy=policy, root=root)
    guard_target(root, {"paper_id": "ongoing", "target_journal": "EJC"})
    guard_target(root, {"paper_id": "0", "target_journal": "EJC"}, preserve_historical_record=True)
    with pytest.raises(ValueError, match="excludes"):
        guard_target(root, {"paper_id": "0", "target_journal": "EJC"})


def test_missing_stale_and_corrupt_ledgers_fail_closed(root):
    with pytest.raises(ValueError, match="unavailable/invalid"):
        guard_target(root, {"paper_id": "x", "target_journal": "EJC"})
    old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    refresh_history(root, [], source="test", checked_at=old)
    with pytest.raises(ValueError, match="stale"):
        check_journal(root, "EJC")
    (root / "registry/journal-rejections.json").write_text('{"schema_version":"wrong"}')
    with pytest.raises(ValueError, match="unavailable/invalid"):
        check_journal(root, "EJC")


def test_configured_threshold_and_conference_gate_exemption(root):
    refresh_history(root, [paper(str(n), "DM") for n in range(3)], source="test")
    policy = {"team_rejection_history": {"enabled": True, "exclude_after_distinct_papers": 4,
                                         "caution_after_distinct_papers": 2}}
    assert check_journal(root, "DM", policy=policy)["status"] == "caution"
    guard_target(root, {"target_journal": "DM", "venue_type": "conference"})


@pytest.mark.parametrize("name", ["Eur.J.Comb.", "European J. Combin.", "EJC"])
def test_abbreviations_cannot_bypass_team_exclusion(root, name):
    refresh_history(root, [paper(str(n)) for n in range(3)], source="test")
    assert check_journal(root, name)["status"] == "excluded"


def test_unified_preflight_blocks_before_build_even_for_historical_target(root, monkeypatch):
    from paper_writing import review_flow
    refresh_history(root, [paper(str(n)) for n in range(3)], source="test")
    monkeypatch.setattr(review_flow, "load_registry", lambda *a, **kw: {})
    monkeypatch.setattr(review_flow, "load_paper_metadata", lambda *a, **kw: {"paper_id": "0", "target_journal": "EJC"})
    def forbidden_build(*args):
        pytest.fail("Excluded target reached the compiler")
    monkeypatch.setattr(review_flow, "_build", forbidden_build)
    with pytest.raises(ValueError, match="excludes"):
        review_flow.preflight("0", root, root / "build")


def test_handoff_does_not_reuse_ready_gate_at_excluded_venue(root, monkeypatch):
    from paper_writing import handoff
    refresh_history(root, [paper(str(n)) for n in range(3)], source="test")
    metadata = {"paper_id": "0", "target_journal": "EJC", "writing_release": {"status": "ready"}}
    monkeypatch.setattr(handoff, "load_paper_metadata", lambda *a, **kw: metadata)
    monkeypatch.setattr(handoff, "load_registry", lambda *a, **kw: {})
    with pytest.raises(ValueError, match="excludes"):
        handoff.validate_release_preconditions("0", root=root)


def test_cli_check_returns_exclusion_and_caution_statuses(root, capsys):
    from paper_writing.__main__ import main
    refresh_history(root, [paper(str(n)) for n in range(3)] +
                    [paper("d1", "DM"), paper("d2", "DM")], source="test")
    assert main(["journal-history", "check", "--root", str(root), "--journal", "EJC"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "excluded"
    assert main(["journal-history", "check", "--root", str(root), "--journal", "DM"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "caution"


def _event(eid, aid, kind, frm, to, at, created=None, **payload):
    return {"id": eid, "attempt_id": aid, "event_type": kind, "from_status": frm, "to_status": to,
            "occurred_at": at, "created_at": created or at, "payload": payload}


def _row(root, attempt_id):
    ledger = json.loads((root / "registry/journal-rejections.json").read_text())
    return next(r for r in ledger["rejections"] if r["attempt_id"] == attempt_id)


def test_freeze_display_corrections_do_not_move_the_rejection(root):
    # 20260907 hypercube JCTA (2026-11-26): the freeze archived the rejected attempt, took it back
    # (closed -> rejected) and wrote a display correction (rejected -> rejected, abandoned).
    # The refresh dated the rejection 15:27:32 from the display event; the decision was 12:05:37.
    p = paper("hypercube", "JCTA")
    a = "attempt-hypercube"
    p["submission_attempts"][0]["closed_at"] = "2026-11-26T15:27:32+08:00"
    p["submission_events"] = [
        _event("e1", a, "accepted", "submitted", "accepted", "2026-11-26T12:05:37+08:00"),
        _event("e2", a, "status_corrected", "accepted", "rejected", "2026-11-26T12:05:37+08:00",
               "2026-11-26T14:00:00+08:00", source_submission_status="rejected"),
        _event("e3", a, "status_corrected", "rejected", "closed", "2026-11-26T15:21:01+08:00",
               source_submission_status="abandoned"),
        _event("e4", a, "status_corrected", "closed", "rejected", "2026-11-26T15:24:54+08:00"),
        _event("e5", a, "status_corrected", "rejected", "rejected", "2026-11-26T15:27:32+08:00",
               source_submission_status="abandoned", decision_at="2026-11-26T12:05:37+08:00"),
    ]
    refresh_history(root, [p], source="test")
    row = _row(root, a)
    assert (row["rejected_at"], row["source_event_id"]) == ("2026-11-26T12:05:37+08:00", "e2")
    from paper_writing.journal_history import is_rejection_event
    assert not is_rejection_event(p["submission_events"][3])
    assert not is_rejection_event(p["submission_events"][4])


def test_rejection_archived_by_a_freeze_still_counts(root):
    # DM_37722 (2026-11-26): registered rejected, then archived (rejected -> closed). The
    # refresh read only attempts still rejected, so the row had to be written by hand.
    p = paper("dm", "Discrete Mathematics", status="closed")
    a = "attempt-dm"
    p["submission_attempts"][0]["closed_at"] = "2026-11-26T16:08:39+08:00"
    p["submission_events"] = [
        _event("s", a, "submitted", "preparing", "submitted", "2026-06-11T13:36:54+08:00"),
        _event("r", a, "rejected", "submitted", "rejected", "2026-06-16T04:36:29+08:00", reason_summary="Desk"),
        _event("c", a, "status_corrected", "rejected", "closed", "2026-11-26T16:08:39+08:00",
               source_submission_status="abandoned", decision="rejected"),
    ]
    withdrawn = paper("withdrawn", "Discrete Mathematics", status="closed")
    withdrawn["submission_events"] = [
        _event("w", "attempt-withdrawn", "status_corrected", "submitted", "closed", "2026-10-01T00:00:00+00:00")]
    refresh_history(root, [p, withdrawn], source="test")
    row = _row(root, a)
    assert (row["rejected_at"], row["source_event_id"], row["reason_summary"]) == (
        "2026-06-16T04:36:29+08:00", "r", "Desk")
    assert check_journal(root, "Discrete Mathematics")["distinct_rejected_papers"] == 1


def test_archived_import_keeps_the_decision_date_of_the_archive_event(root):
    # 20260525mathgraph0004 EJC: the only rejection is an import (2026-07-25); the freeze's
    # archive event kept the attempt's earlier closed_at (06-05) as decision_at.
    p = paper("ejc", "EJC", status="closed")
    a = "attempt-ejc"
    p["submission_attempts"][0]["closed_at"] = "2026-11-26T15:21:01+08:00"
    p["submission_events"] = [
        _event("i", a, "status_corrected", None, "rejected", "2026-07-25T22:45:06+08:00"),
        _event("c", a, "status_corrected", "rejected", "closed", "2026-11-26T15:21:01+08:00",
               decision_at="2026-06-05T00:00:00+08:00"),
    ]
    refresh_history(root, [p], source="test")
    assert _row(root, a)["rejected_at"] == "2026-06-05T00:00:00+08:00"


def test_import_time_does_not_replace_the_recorded_decision_date(root):
    # JSS 01203: registered by an import on 2026-07-20 (status_corrected) with the attempt's
    # closed_at 06-04; the refresh moved the rejection to 07-20.
    p = paper("jss", "Journal of Systems and Software")
    a = "attempt-jss"
    p["submission_attempts"][0]["closed_at"] = "2026-06-04T00:00:00+08:00"
    p["submission_events"] = [_event("i", a, "status_corrected", None, "rejected", "2026-07-20T19:30:00+08:00")]
    refresh_history(root, [p], source="test")
    assert _row(root, a)["rejected_at"] == "2026-06-04T00:00:00+08:00"
    # The journal's own rejected event keeps its time; a reconciliation restating it at the
    # same time does not replace it as the source.
    q = paper("aam", "AAM")
    b = "attempt-aam"
    q["submission_events"] = [
        _event("letter", b, "rejected", "submitted", "rejected", "2026-09-02T20:30:32+08:00", "2026-09-03T08:42:02+08:00"),
        _event("restate", b, "status_corrected", "submitted", "rejected", "2026-09-02T20:30:32+08:00",
               "2026-09-11T16:19:13+08:00"),
    ]
    refresh_history(root, [p, q], source="test")
    assert (_row(root, b)["rejected_at"], _row(root, b)["source_event_id"]) == ("2026-09-02T20:30:32+08:00", "letter")


def test_archived_attempt_without_a_rejection_event_is_dated_by_its_decision(root):
    # 20260309aillm0004 IJMLC: rejected by a decision_received event (no letter on the site),
    # then archived by the freeze; the row stays management_status_only at the decision time.
    p = paper("ijmlc", "International Journal of Machine Learning and Cybernetics", status="closed")
    a = "attempt-ijmlc"
    p["submission_attempts"][0]["closed_at"] = "2026-11-26T18:00:00+08:00"
    p["submission_events"] = [
        _event("d", a, "decision_received", "submitted", "rejected", "2026-11-09T18:57:46+08:00"),
        _event("c", a, "status_corrected", "rejected", "closed", "2026-11-26T18:00:00+08:00",
               source_submission_status="abandoned"),
    ]
    refresh_history(root, [p], source="test")
    row = _row(root, a)
    assert (row["rejected_at"], row["evidence_level"]) == ("2026-11-09T18:57:46+08:00", "management_status_only")
