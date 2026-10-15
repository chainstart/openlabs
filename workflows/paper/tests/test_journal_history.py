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
