"""The registry follows the management site's submission status (2026-11-26). Synthetic fixtures."""
from __future__ import annotations

import yaml

from paper_writing import submission_status


def _registry(root, paper_id, record):
    path = root / "registry" / "papers" / f"{paper_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"paper_id": paper_id, **record}, sort_keys=False))
    return path


def _site(paper_id, *attempts, events=()):
    return {"paper_id": paper_id, "packages": [{"id": "pk1", "version": "1.2.0"}],
            "submission_attempts": list(attempts), "submission_events": list(events)}


SUBMITTED = {"id": "a1", "attempt_no": 1, "journal_name": "Synthetic Astronomy", "status": "submitted",
             "manuscript_number": None, "submitted_at": "2026-11-25T16:29:13+08:00", "package_id": "pk1"}


def test_submitted_paper_gets_its_external_status_and_stale_fields_corrected(tmp_path):
    path = _registry(tmp_path, "p", {
        "submission_preparation": {"journal": "Synthetic Astronomy", "portal_status": "not_submitted"},
        "submission_package": {"version": "1.2.0", "not_submitted": True}, "notes": ["kept"]})
    plan = submission_status.reconcile(tmp_path, [_site("p", SUBMITTED)])
    assert [c["fields"] for c in plan["changed"]] == [[
        "external_submission", "submission_package.not_submitted", "submission_preparation.portal_status"]]
    assert yaml.safe_load(path.read_text())["submission_package"]["not_submitted"] is True  # dry run
    result = submission_status.reconcile(tmp_path, [_site("p", SUBMITTED)], apply=True)
    assert result["changed"][0]["path"] == "registry/papers/p.yaml"
    record = yaml.safe_load(path.read_text())
    external = record["external_submission"]
    assert (external["status"], external["journal"], external["submission_attempt_id"]) == (
        "submitted", "Synthetic Astronomy", "a1")
    assert record["submission_preparation"]["portal_status"] == "submitted"
    assert record["submission_preparation"]["portal_status_history"][0]["status"] == "submitted"
    assert record["submission_package"]["not_submitted"] is False
    assert record["submission_package"]["submitted_to"] == "Synthetic Astronomy"
    assert record["notes"] == ["kept"]
    # Current now: a second run changes nothing.
    assert submission_status.reconcile(tmp_path, [_site("p", SUBMITTED)], apply=True)["changed"] == []
    # The journal's number arrives later (journal_mail): filled in, no history entry.
    numbered = dict(SUBMITTED, manuscript_number="SA-D-26-00471")
    assert submission_status.reconcile(tmp_path, [_site("p", numbered)], apply=True)["changed"]
    external = yaml.safe_load(path.read_text())["external_submission"]
    assert external["manuscript_number"] == "SA-D-26-00471" and "history" not in external


def test_rejection_moves_the_block_to_history_and_closed_keeps_the_decision(tmp_path):
    path = _registry(tmp_path, "p", {"external_submission": {
        "status": "submitted", "journal": "Synthetic Astronomy", "submission_attempt_id": "a1",
        "source": "hand registration"}})
    rejected = dict(SUBMITTED, status="closed", manuscript_number="SA-D-26-1", closed_at="2026-12-20T00:00:00+08:00")
    events = [{"attempt_id": "a1", "event_type": "status_corrected", "to_status": "closed"},
              {"attempt_id": "a1", "event_type": "rejected", "to_status": "rejected",
               "occurred_at": "2026-12-01T09:00:00+08:00"}]
    submission_status.reconcile(tmp_path, [_site("p", rejected, events=events)], apply=True)
    external = yaml.safe_load(path.read_text())["external_submission"]
    assert (external["status"], external["site_status"], external["decision_at"]) == (
        "rejected", "closed", "2026-12-01T09:00:00+08:00")
    assert external["manuscript_number"] == "SA-D-26-1"
    assert external["history"][0]["status"] == "submitted"


def test_latest_attempt_by_number_and_preparing_is_not_a_submission(tmp_path):
    _registry(tmp_path, "p", {})
    first = dict(SUBMITTED, status="rejected", closed_at="2026-10-01T00:00:00+00:00")
    second = dict(SUBMITTED, id="a2", attempt_no=2, journal_name="Second Letters", status="revision_preparing")
    preparing = dict(SUBMITTED, id="a3", attempt_no=3, status="preparing")
    result = submission_status.reconcile(tmp_path, [_site("p", second, first, preparing)])
    assert result["changed"][0]["to"] == "revision_requested"
    _registry(tmp_path, "q", {"submission_preparation": {"portal_status": "not_submitted"}})
    assert submission_status.reconcile(tmp_path, [_site("q", preparing)])["changed"] == []


def test_package_of_another_version_stays_not_submitted(tmp_path):
    path = _registry(tmp_path, "p", {"submission_package": {"version": "2.0.0", "not_submitted": True},
                                     "submission_preparation": {"journal": "Next Journal",
                                                                "portal_status": "not_submitted"}})
    rejected = dict(SUBMITTED, status="rejected", closed_at="2026-10-01T00:00:00+00:00")
    result = submission_status.reconcile(tmp_path, [_site("p", rejected)], apply=True)
    assert result["changed"][0]["fields"] == ["external_submission"]
    record = yaml.safe_load(path.read_text())
    assert record["submission_package"]["not_submitted"] is True
    assert record["submission_preparation"]["portal_status"] == "not_submitted"


def test_letter_of_a_paper_without_topic_is_kept_once(tmp_path):
    path = _registry(tmp_path, "p", {})
    first = submission_status.record_correspondence(tmp_path, "p", message_key="d" * 64,
                                                    status="submitted", manuscript_id="SA-D-26-1")
    again = submission_status.record_correspondence(tmp_path, "p", message_key="d" * 64,
                                                    status="submitted", manuscript_id="SA-D-26-1")
    assert (first["status"], again["status"]) == ("recorded", "already_recorded")
    items = yaml.safe_load(path.read_text())["journal_correspondence"]
    assert len(items) == 1 and items[0]["event_key"] == "mail:" + "d" * 64
