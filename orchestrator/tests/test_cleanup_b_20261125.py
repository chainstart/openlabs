"""Clean-up B (2026-11-25): round usage in the tick report (B4)."""

from __future__ import annotations

import json
from types import SimpleNamespace

from openlabs import program_autonomy
from openlabs.engine import TickReport
from openlabs.program import mark_topic_in_review, mark_topic_ready
from test_program_slots import _active_topic, _setup


def _ready(tmp_path, **program):
    paths, db, program_settings, ledger = _setup(tmp_path, **program)
    _active_topic(paths, db, program_settings, ledger, 1)
    mark_topic_in_review(ledger, "topic-1", db=db, decided_by="r")
    mark_topic_ready(ledger, "topic-1", db=db, decided_by="r2", paper_id="paper-1")
    return paths, db, SimpleNamespace(program=program_settings)


def test_round_usage_is_reported_cached_and_never_a_tick_error(tmp_path, monkeypatch) -> None:
    paths, db, settings = _ready(tmp_path, polish_mode=False)
    calls = []

    def fake(paths_, settings_, arguments, environment=None, **_):
        calls.append(arguments)
        return {"papers": [{"paper_id": "paper-1", "target_journal": "J", "used_at_target": 7,
                            "limit": 7, "limit_source": "round_grant", "granted": 14,
                            "grant_status": "expired", "all_targets_total": 15,
                            "grant_condition": {"cycle": "polish-20261123"},
                            "grant_expired_because": ["latest decision at J is ready"]}]}

    monkeypatch.setattr(program_autonomy, "_run_paper_command", fake)
    report = TickReport()
    program_autonomy._report_round_usage(db, paths, settings, report)
    assert calls == [["review", "round-usage", "--with-grants", "--paper-id", "paper-1"]]
    row = report.program["round_usage"]["papers"]["paper-1"]
    assert row["used_at_target"] == 7 and row["all_targets_total"] == 15 and row["granted"] == 14
    assert row["grant_cycle_ended"] == "polish-20261123"    # polish_mode is off
    assert report.program["round_usage"]["cross_journal_budget"] is None
    # Within the refresh window the cached report is shown; no second command.
    report = TickReport()
    program_autonomy._report_round_usage(db, paths, settings, report)
    assert len(calls) == 1 and report.program["round_usage"]["cached"] is True
    # A failure of the command is reported, not a tick error.
    (paths.database / "round-usage.json").write_text(json.dumps({"checked_epoch": 0}))

    def broken(*args, **kwargs):
        raise program_autonomy.DeliveryError("exit 2")

    monkeypatch.setattr(program_autonomy, "_run_paper_command", broken)
    report = TickReport()
    program_autonomy._report_round_usage(db, paths, settings, report)
    assert report.program["round_usage"]["outcome"] == "failed" and report.errors == []


def test_one_hold_reader_for_every_form() -> None:
    from openlabs import holds

    assert holds.topic_hold({"status": "active"}) is None
    new = holds.topic_hold({"status": "paused", "operator_pause": {
        "kind": "topic_pause", "by": "user", "at": "2026-11-23T01:41:06Z", "reason": "polish",
        "quote": "停新实验", "condition": "polish mode ends", "prior_status": "active"}},
        scope="topic-1")
    assert [new[key] for key in holds.HOLD_FIELDS] == [
        "topic_pause", "topic-1", "user", "2026-11-23T01:41:06Z", "停新实验", "polish", None,
        "polish mode ends", new["restore"]]
    assert new["source"] == "operator_pause" and new["resumable"] and not new["expired"]
    old = holds.topic_hold({"status": "paused", "previous_status": "active", "operator_hold": {
        "set_at": "2026-11-19T00:59:30Z", "set_by": "op", "reason": "fewer astro topics",
        "resume": "re-submit the withdrawn jobs"}}, scope="topic-2")
    assert (old["source"], old["by"], old["date"], old["condition"]) == (
        "operator_hold", "op", "2026-11-19T00:59:30Z", "re-submit the withdrawn jobs")
    assert not old["resumable"] and "record it first" in old["restore"]
    bare = holds.topic_hold({"status": "paused"}, since="2026-11-19T01:58:12Z")
    assert bare["source"] == "unrecorded" and bare["date"] == "2026-11-19T01:58:12Z"
    expired = holds.topic_hold({"status": "paused", "operator_pause": {"until": "2026-01-01"}})
    assert expired["expired"] is True
    paper = holds.assignment_hold({"paper_id": "p", "manual_assignment": {
        "hold": True, "by": "owner", "date": "2026-11-24", "quote": "撤回", "reason": "r"}})
    assert (paper["kind"], paper["scope"], paper["source"], paper["quote"]) == (
        "submitter_hold", "p", "registry", "撤回")
    assert holds.assignment_hold({"manual_assignment": {"hold": False}}) is None
    note = holds.assignment_hold(None, [{"active": True, "id": "a",
                                         "notes": "x manual_assignment=hold"}])
    assert note["source"] == "site_assignment_notes" and note["assignment_id"] == "a"
    assert holds.production_pause_kind("operator_pause:claude-main") == "operator_pause"
    assert holds.production_pause_kind("agent_workstream_paused") == "owner_hold"
    assert holds.production_pause_kind("agent_workstream_blocked") == "workstream_state"
    assert holds.production_pause_kind("topic_ready_queue") == "ready_queue"
    assert holds.production_pause_kind("something new") == "other"
    assert set(holds.PRODUCTION_PAUSE_REASONS) >= {"operator_pause", "owner_hold", "other"}
    pause = holds.campaign_pause("production_paused", "review_rounds_exhausted")
    assert pause["reason_kind"] == "rounds_exhausted" and holds.campaign_pause("active", "x") is None
    import pytest

    with pytest.raises(holds.HoldError):
        holds.hold_record("topic_pause", "t", by="u", reason="r", restore="x")  # no end


def test_pause_event_records_the_reason_kind(tmp_path) -> None:
    paths, db, program_settings, ledger = _setup(tmp_path)
    campaign_id = "campaign-x"
    db.register_campaign(campaign_id, domain="ai", title="t")
    db.pause_production_campaign(campaign_id, reason="review_rounds_exhausted")
    with db.connect() as connection:
        row = connection.execute(
            "SELECT payload_json FROM events WHERE entity_id=? AND event_type="
            "'continuous_production_paused' ORDER BY rowid DESC LIMIT 1", (campaign_id,)).fetchone()
    assert json.loads(row[0])["reason_kind"] == "rounds_exhausted"
