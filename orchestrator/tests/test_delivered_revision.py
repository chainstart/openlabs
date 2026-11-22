import json

import pytest

from openlabs import program, reopen
from test_owner_mode import _owner_program


@pytest.mark.parametrize("journal", [False, True])
def test_delivered_revision_is_package_bound_and_resumes_once(tmp_path, monkeypatch, journal):
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    ledger = program.open_topic_ledger(paths, settings.program)
    topic_id = topic["topic_id"]
    campaign_id = topic["campaign_id"]
    paper = "test-paper"
    package = "pkg_test"
    program.mark_topic_in_review(ledger, topic_id, db=db, decided_by="owner", paper_id=paper)
    program.mark_topic_ready(ledger, topic_id, db=db, decided_by="review", paper_id=paper)
    db.pause_production_campaign(campaign_id, reason="ready")
    handoff = {"status": "delivered", "package_id": package}
    if journal:
        handoff["submission_handler"] = "assigned author"
        program.record_topic_note(ledger, topic_id, db=db, event_type="journal_correspondence",
                                  reason="revision_requested", decided_by="journal-mail", key="mail:"+"a"*64)
    program.record_topic_note(ledger, topic_id, db=db, event_type="test", reason="delivered",
                              decided_by="release", updates={"handoff": handoff})
    folder = paths.data / "papers" / paper / "releases"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / (package + ".json")).write_text(json.dumps(
        {"paper_id": paper, "package_id": package, "version": "0.1.0"}))
    args = db, paths, settings, topic_id
    with pytest.raises(reopen.ReopenGrantError):
        reopen.request_delivered_revision(*args, "stale", "extra analysis", "operator")
    kwargs = {"journal_event_key": "a"*64} if journal else {}
    if journal:
        with pytest.raises(reopen.ReopenGrantError):
            reopen.request_delivered_revision(*args, package, "extra analysis", "operator")
    request = reopen.request_delivered_revision(*args, package, "extra analysis", "operator", **kwargs)
    row, = reopen.advance_delivered_revisions(db, paths, settings, None)
    assert "extra analysis" in db.task(row["task_id"])["objective"]
    assert ledger.topic(topic_id)["status"] == "active"
    assert db.campaign(campaign_id)["status"] == "active"
    from openlabs.program_reconcile import plan
    db.pause_production_campaign(campaign_id, reason="test between seats")
    assert not any(item["action"] == "mark_delivered" and item["id"] == topic_id
                   for item in plan(db, paths, settings)["rows"])
    assert reopen.request_delivered_revision(*args, package, "extra analysis", "operator", **kwargs) == request
    assert reopen.advance_delivered_revisions(db, paths, settings, None) == []
