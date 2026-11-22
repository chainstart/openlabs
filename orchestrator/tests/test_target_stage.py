import json
from dataclasses import replace
from pathlib import Path

import pytest
import test_research_lines as lines
import test_research_program_flow as flow

from openlabs import target_stage
from openlabs.program import open_topic_ledger


def _event(db, scope, key, kind, **payload):
    db.update_meta({}, events=[(scope, key, kind, payload)])


@pytest.mark.parametrize("intervention", [
    None, "manual_requeue", "operator_reopen_granted", "manual_dispatch",
    "release_retry", "before_cutoff", "direction_requeue",
])
def test_replay_promotes_only_an_unattended_post_cutoff_line(tmp_path, monkeypatch, intervention):
    db = flow._db(flow._paths(tmp_path))
    monkeypatch.setattr(target_stage, "CUTOFF", "2000-01-01T00:00:00Z")
    if intervention == "before_cutoff":
        monkeypatch.setattr(target_stage, "CUTOFF", "2099-01-01T00:00:00Z")
    for campaign in ("scout", "review", "research"):
        db.register_campaign(campaign, domain="ai", title=campaign)
    db.enqueue_task(task_id="scout-task", campaign_id="scout", domain="ai",
                    task_type="topic_scout", objective="scout", routing_reason="program_slot_open")
    _event(db, "topic", "topic-a", "topic_proposed", decided_by="scout-task")
    db.enqueue_task(task_id="gate-task", campaign_id="review", domain="ai",
                    task_type="portfolio_review", objective="admit", routing_reason="topic_admission")
    _event(db, "topic", "topic-a", "topic_admitted", decided_by="gate-task")
    _event(db, "topic", "topic-a", "topic_activated", campaign_id="research")
    db.enqueue_task(task_id="research-task", campaign_id="research", domain="ai",
                    task_type="candidate_maturation", objective="research",
                    routing_reason="owner_first_seat",
                    operator_dispatched=intervention == "manual_dispatch")
    if intervention == "manual_requeue":
        _event(db, "task", "research-task", "manual_requeue", by="owner")
    if intervention == "direction_requeue":
        db.enqueue_task(task_id="direction-task", campaign_id="review", domain="ai",
                        task_type="direction_decision", objective="decide")
        _event(db, "topic", "topic-a", "direction_decision_scheduled",
               detail={"task_id": "direction-task"})
        _event(db, "task", "direction-task", "manual_requeue", by="owner")
    if intervention == "operator_reopen_granted":
        _event(db, "topic", "topic-a", intervention, campaign_id="research")
    if intervention == "release_retry":
        _event(db, "topic", "topic-a", intervention, decided_by="manual:owner")
    _event(db, "topic", "topic-a", "release_retry", decided_by="orchestrator:auto_release")
    _event(db, "topic", "topic-a", "topic_in_review", campaign_id="research")
    _event(db, "topic", "topic-a", "topic_ready", campaign_id="research")
    _event(db, "topic", "topic-a", "handoff_delivered", campaign_id="research",
           decided_by="orchestrator:auto_handoff", detail={"paper_id": "paper", "package_id": "pkg"})
    # Rescue after the qualifying delivery and unrelated work in the shared scout
    # campaign cannot invalidate its evidence.
    _event(db, "task", "research-task", "manual_requeue", by="owner")
    document = {"topics": [{"topic_id": "topic-a", "research_line": "line-a"}]}
    names = ("line-a", "line-b")
    initial = target_stage.replay(db, document, names)
    assert initial["line-a"]["target_stage"] == target_stage.RUN_IN
    assert db.events(entity_type="research_line") == []
    result = target_stage.refresh(db, document, names)
    assert target_stage.refresh(db, document, names) == result
    assert result["line-b"]["target_stage"] == target_stage.RUN_IN
    progress = result["line-a"]["run_in_progress"]
    if intervention:
        assert result["line-a"]["target_stage"] == target_stage.RUN_IN
        assert progress["qualified"] == 0
        assert progress["handoffs"][0]["blockers"]
        assert db.events(entity_type="research_line") == []
    else:
        assert result["line-a"]["target_stage"] == target_stage.TIER2_AIM
        assert progress["qualified"] == 1
        assert progress["handoffs"][0]["interventions"] == {}
        event, = db.events(entity_type="research_line")
        assert event["payload"]["evidence"]["paper_id"] == "paper"


def test_manual_switch_records_actor_and_starts_new_observation_window(tmp_path, monkeypatch):
    from openlabs import __main__ as cli

    paths, db, settings = lines._line_setup(tmp_path, "ready")
    settings = replace(settings, program=replace(settings.program, research_lines=(lines.LINE,)))
    monkeypatch.setattr(cli, "workspace_paths", lambda _: paths)
    monkeypatch.setattr(cli, "load_settings", lambda _: settings)
    command = ["program", "target-stage", "--line", lines.LINE]
    assert cli.main([*command, "--stage", "tier2_aim", "--by", "owner"]) == 1
    assert cli.main(command) == 0
    assert db.events(entity_type="research_line") == []
    for stage in target_stage.TIER2_AIM, target_stage.RUN_IN:
        assert cli.main([*command, "--stage", stage, "--by", "owner", "--reason", "check"]) == 0
    assert target_stage.set_stage(
        db, lines.LINE, target_stage.TIER2_AIM, by="orchestrator",
        reason="unattended_delivery", evidence={"proposed_at": "2000-01-01T00:00:00Z"},
    )["stage"] == target_stage.RUN_IN
    first, second = db.events(entity_type="research_line")
    assert first["payload"]["by"] == "owner"
    assert second["payload"]["reason"] == "check"
    assert second["payload"]["previous_stage"] == target_stage.TIER2_AIM



def test_tier2_card_without_rationale_gets_a_repair_task(tmp_path, monkeypatch):
    paths, db, settings = lines._line_setup(tmp_path, "ready")
    target_stage.set_stage(db, lines.LINE, target_stage.TIER2_AIM, by="owner", reason="test")
    _, report = flow._scout_round(paths, db, settings, monkeypatch, [lines._line_card()])
    assert report.errors == []
    repair, = report.program["card_repairs"]
    assert repair["outcome"] == "scheduled"
    assert "tier2_aim requires tier_rationale" in db.task(repair["task_id"])["objective"] or any(
        "tier2_aim requires tier_rationale" in reason
        for reason in flow._packet(db.task(repair["task_id"]))["errors"]
    )


@pytest.mark.parametrize("supported", [True, False])
def test_admission_requires_independent_tier2_assessment(tmp_path, monkeypatch, supported):
    paths, db, settings = lines._line_setup(tmp_path, "ready")
    target_stage.set_stage(db, lines.LINE, target_stage.TIER2_AIM, by="owner", reason="test")
    card = lines._line_card(
        target_tier="routine", tier_rationale="A new operating threshold tested on two cohorts."
    )
    scout_id, review, report = flow._to_admission(paths, db, settings, monkeypatch, [card])
    assert report.errors == []
    assert report.program["by_line"][lines.LINE]["target_stage"] == target_stage.TIER2_AIM
    assert flow._packet(db.task(scout_id))["target_stage"] == target_stage.TIER2_AIM
    entry = flow._packet(review)["topic_cards"][0]
    assert entry["target_stage"] == target_stage.TIER2_AIM
    assert "external validation" in review["objective"]
    branch = flow._branch(entry)
    branch["admission"]["tier2_contribution_supported"] = supported
    flow._complete(db, paths, review["task_id"], extra={"candidate_branches": [branch]})
    report = flow._tick(paths, settings, monkeypatch)
    assert report.errors == []
    topic = open_topic_ledger(paths, settings.program).topic(entry["topic_id"])
    assert topic["status"] == ("active" if supported else "rejected")
    if supported:
        campaign = db.campaign(topic["campaign_id"])
        state = json.loads(Path(campaign["workstream_state_path"]).read_text())
        assert state["target_stage"] == target_stage.TIER2_AIM
        assert state["preregistration"]["sha256"] == topic["preregistration_sha256"]


@pytest.mark.parametrize(("zone", "band", "valid"), [
    (1, "zones_1_2", True), (2, "zones_1_2", True),
    (3, "zones_3_4", True), (4, "zones_3_4", True),
    (2, "zones_3_4", False), (3, "zones_1_2", False), (None, "zones_3_4", False),
])
def test_achieved_evidence_band_matches_verified_journal(zone, band, valid):
    venues = [{"journal": "Journal", "cas_2025_zone": zone}] if zone else []
    decision = {"rationale": "Evidence", "retarget": {"venue_or_format": "Journal",
                "achieved_band": band, "why_fits": "Scope"}}
    assert (target_stage.venue_grade(decision, venues) is not None) is valid


@pytest.mark.parametrize(("current", "expected"), [
    ("Zone 3 Journal", "venue_retained"), ("Zone 2 Journal", "executed"),
])
def test_ready_tier2_manuscript_can_deliver_in_zone3(tmp_path, monkeypatch, current, expected):
    import test_program_autonomy as autonomy
    from openlabs import program_autonomy

    paths, db, settings, (topic,) = autonomy._program(tmp_path, monkeypatch, auto_handoff=True)
    monkeypatch.setattr(target_stage, "tier2_topic", lambda _: True)
    autonomy._deliverable(monkeypatch)
    release_status = program_autonomy.run_release_status
    monkeypatch.setattr(program_autonomy, "run_release_status", lambda *args: {
        **release_status(*args), "target_journal": current,
    })
    monkeypatch.setenv("ARA_PAPER_MANAGE_API_URL", "https://manage.invalid")
    monkeypatch.setenv("ARA_PAPER_MANAGE_API_KEY", "test-key")
    monkeypatch.setattr(program_autonomy, "run_paper_delivery", lambda _p, _s, paper_id: {
        "status": "delivered", "paper_id": paper_id, "package_id": "pkg-zone-3",
        "submission_handler": None, "awaiting_owner_review": True,
    })
    original = program_autonomy._run_paper_command

    def paper_command(*args, **kwargs):
        if args[2] == ["venue", "alternatives"]:
            return {"venues": [{"journal": "Zone 3 Journal", "cas_2025_zone": 3}]}
        return original(*args, **kwargs)

    monkeypatch.setattr(program_autonomy, "_run_paper_command", paper_command)
    review = autonomy._to_review(paths, db, settings, monkeypatch, topic)
    autonomy._finish(db, paths, review["task_id"], extra={
        "paper_candidate": True, "review_outcome": autonomy._outcome(
            status="ready", target_journal=current)})
    report = autonomy._tick(paths, settings, monkeypatch)
    assert report.errors == []
    pending = autonomy._direction_task(db)
    packet = flow._packet(pending)
    decision = autonomy._retarget_decision(packet["reasons_to_answer"][0], "Zone 3 Journal")
    decision["retarget"]["achieved_band"] = "zones_3_4"
    report = autonomy._decide(paths, settings, monkeypatch, db, decision)
    assert report.errors == []
    assert report.program["direction_decisions"][0]["outcome"] == expected
    topic = autonomy._topic(paths, settings, topic["topic_id"])
    assert topic["venue_grade"]["cas_2025_zone"] == 3
    if expected == "venue_retained":
        assert topic["status"] == "ready_queue"
        assert topic["handoff"]["status"] == "delivered"
        assert topic["handoff"]["package_id"] == "pkg-zone-3"
        assert topic["handoff"]["submission_handler"] is None
    else:
        assert topic["status"] == "in_review"
        assert db.task(pending["task_id"] + ":retarget") is not None
