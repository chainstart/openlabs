"""Research-program back half: stop rules, direction decisions, ready queue and delivery."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from openlabs import budget as budget_control
from openlabs import engine, program_autonomy
from openlabs.contracts import (
    RECEIPT_SCHEMA,
    RESULT_SCHEMA,
    atomic_write_json,
    sha256_file,
    validate_direction_decision,
    validate_review_outcome,
)
from openlabs.db import FactoryDB
from openlabs.portfolio import spawn_candidate_workstreams
from openlabs.program import open_topic_ledger, slot_status
from test_research_program_flow import (
    RECEIPT_SHA,
    RUNNERS,
    TEMPLATE,
    _branch,
    _card,
    _db,
    _install_program,
    _packet,
    _paths,
    _settings,
    _tick,
    _to_admission,
)

DECISION_RECORD = "reviews/unified/p/run/decision.json"


# --------------------------------------------------------------------------- fixtures


def _finish(
    db: FactoryDB,
    paths,
    task_id: str,
    *,
    extra: dict | None = None,
    session: str | None = None,
    supported: bool = True,
) -> Path:
    """Fake agent: a result bundle with one hash-bound artifact and a supported claim."""

    task = db.task(task_id)
    assert task is not None and task["status"] == "leased", task
    attempt_id = str(task["current_attempt_id"])
    root = paths.data / "workspaces" / str(task["domain"]) / str(task["campaign_id"])
    output = root / "attempts" / attempt_id / "result.json"
    evidence = root / "evidence" / f"{attempt_id}.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps({"task": task_id}), encoding="utf-8")
    db.bind_attempt_spec(task_id, attempt_id=attempt_id, lab_id="ai", output_path=str(output))
    db.mark_running(task_id, attempt_id=attempt_id, owner="test", pid=1, lease_seconds=600)
    payload = {
        "schema_version": RESULT_SCHEMA, "task_id": task_id, "campaign_id": task["campaign_id"],
        "lab_id": "ai", "domain": task["domain"], "status": "succeeded",
        "summary": "Fake agent step.",
        "artifacts": [{"artifact_id": "evidence", "kind": "analysis",
                       "uri": evidence.resolve().as_uri(), "sha256": sha256_file(evidence)}],
        "claims": [{"claim_id": "c1", "text": "The endpoint result.",
                    "status": "supported" if supported else "hypothesis",
                    "evidence": ["evidence"] if supported else [], "limitations": []}],
        "next_actions": [], "paper_candidate": False, **(extra or {}),
    }
    atomic_write_json(output, payload)
    runtime = {"duration_seconds": 10.0, "exit_code": 0, "runner": task["runner"]}
    if session:
        runtime["session_id"] = session
    atomic_write_json(paths.result_inbox / f"{attempt_id}.json", {
        "schema_version": RECEIPT_SCHEMA, "task_id": task_id, "attempt_id": attempt_id,
        "campaign_id": task["campaign_id"], "lab_id": "ai", "domain": task["domain"],
        "agent_role": task["agent_role"], "result_path": str(output),
        "sha256": sha256_file(output), "runtime": runtime,
    })
    return output


def _lease(paths, settings, monkeypatch, db, task_id: str) -> dict:
    for _ in range(3):
        task = db.task(task_id)
        if task["status"] == "leased":
            return task
        _tick(paths, settings, monkeypatch)
    task = db.task(task_id)
    assert task["status"] == "leased", task
    return task


def _program(tmp_path, monkeypatch, *, cards: int = 1, tier: str = "routine", **program):
    """Scout, admit ``cards`` topics; return (paths, db, settings, topics in admission order)."""

    paths = _paths(tmp_path)
    _install_program(paths)
    db = _db(paths)
    settings = _settings(**program)
    _, admission, _ = _to_admission(
        paths, db, settings, monkeypatch, [_card(n, RECEIPT_SHA) for n in range(cards)]
    )
    entries = _packet(admission)["topic_cards"]
    from test_research_program_flow import _complete

    _complete(db, paths, admission["task_id"], extra={"candidate_branches": [
        _branch(entry, target_tier=tier) for entry in entries
    ]})
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    ledger = open_topic_ledger(paths, settings.program)
    return paths, db, settings, [ledger.topic(e["topic_id"]) for e in entries]


def _topic(paths, settings, topic_id: str) -> dict:
    return open_topic_ledger(paths, settings.program).topic(topic_id)


def _research_payload(topic: dict, verdict: str = "met", **extra) -> dict:
    return {"paper_candidate": True, "primary_endpoint_verdict": verdict,
            "preregistration_sha256": topic["preregistration_sha256"], **extra}


def _outcome(**override) -> dict:
    outcome = {
        "next_action": None, "status": "revision_required", "review_stalled": False,
        "rounds_for_target": 1, "max_rounds_per_target": 4, "direction_context": None,
        "decision_record": DECISION_RECORD, "decision_record_sha256": "d" * 64,
        "paper_id": "20261111-ai-health-temporal-retrieval",
    }
    outcome.update(override)
    return outcome


CONTEXT = {
    "trigger": "all_referees_reject",
    "strongest_desk_reject_reason": "The temporal split adds no insight beyond Example A 2025.",
    "referee_rejections": [
        {"referee": "opus", "recommendation": "reject",
         "principal_reason": "No external cohort supports the claimed generalisation."},
    ],
    "options": ["targeted_core_analysis", "retarget_or_short_format", "freeze"],
}


def _to_review(paths, db, settings, monkeypatch, topic: dict) -> dict:
    """Research (met) -> readiness -> write -> review scheduled; return the review task."""

    campaign_id = topic["campaign_id"]
    research = db.latest_task(campaign_id)
    _lease(paths, settings, monkeypatch, db, research["task_id"])
    _finish(db, paths, research["task_id"], extra=_research_payload(topic), session="research-1")
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    readiness = db.latest_task(campaign_id)
    assert readiness["task_type"] == "paper_readiness"
    _lease(paths, settings, monkeypatch, db, readiness["task_id"])
    _finish(db, paths, readiness["task_id"], extra={"paper_candidate": True})
    _tick(paths, settings, monkeypatch)
    write = db.latest_task(campaign_id)
    assert write["task_type"] == "paper_write" and write["agent_role"] == "writer"
    _lease(paths, settings, monkeypatch, db, write["task_id"])
    _finish(db, paths, write["task_id"], extra={"paper_candidate": True}, session="writer-1")
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    review = db.latest_task(campaign_id)
    assert review["task_type"] == "paper_review"
    assert _topic(paths, settings, topic["topic_id"])["status"] == "in_review"
    return _lease(paths, settings, monkeypatch, db, review["task_id"])


def _direction_task(db: FactoryDB) -> dict:
    with db.connect() as connection:
        row = connection.execute(
            "SELECT * FROM tasks WHERE task_type='direction_decision' "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    return dict(row)


def _direction_tasks(db: FactoryDB) -> list[dict]:
    with db.connect() as connection:
        rows = connection.execute(
            "SELECT * FROM tasks WHERE task_type='direction_decision' ORDER BY rowid"
        ).fetchall()
    return [dict(row) for row in rows]


def _decide(paths, settings, monkeypatch, db, decision: dict) -> engine.TickReport:
    task = _direction_task(db)
    _lease(paths, settings, monkeypatch, db, task["task_id"])
    _finish(db, paths, task["task_id"], extra={"direction_decision": decision},
            supported=False)
    return _tick(paths, settings, monkeypatch)


def _freeze_decision(reason: str) -> dict:
    return {
        "choice": "freeze", "rationale": "No analysis within budget answers it.",
        "answers_reason": reason,
        "freeze": {"reason_class": "contribution_insufficient", "reopen_conditions": [
            {"type": "new_data_source", "description": "An external cohort with the same codes."}
        ]},
    }


def _analysis_decision(reason: str, seconds: int = 3_600) -> dict:
    return {
        "choice": "targeted_core_analysis", "rationale": "One external cohort decides it.",
        "answers_reason": reason,
        "analysis": {"name": "External cohort validation on eICU",
                     "expected_to_change": "the generalisation objection",
                     "data": "eICU-CRD 2.0 (already accessible)", "budget_seconds": seconds,
                     "success_criterion": "AUROC gap within 0.02 of the internal split"},
    }


def _retarget_decision(reason: str, venue: str = "Artificial Intelligence in Medicine") -> dict:
    return {
        "choice": "retarget_or_short_format", "rationale": "Readers there want this.",
        "answers_reason": reason,
        "retarget": {"venue_or_format": venue, "why_fits": "Clinical-informatics readership."},
    }


def _events(db: FactoryDB, topic_id: str) -> list[str]:
    return [event["event_type"] for event in db.events(entity_type="topic", entity_id=topic_id)]


# --------------------------------------------------------------------------- contracts


def test_contracts_validate_review_outcome_and_direction_decision() -> None:
    assert validate_review_outcome(_outcome()).valid
    bad = validate_review_outcome(_outcome(status="maybe", decision_record_sha256="x"))
    assert any("status" in e for e in bad.errors)
    assert any("decision_record_sha256" in e for e in bad.errors)
    reason = CONTEXT["strongest_desk_reject_reason"]
    for decision in (_freeze_decision(reason), _analysis_decision(reason),
                     _retarget_decision(reason)):
        assert validate_direction_decision(decision).valid, decision
    missing = _analysis_decision(reason)
    del missing["analysis"]["success_criterion"]
    assert "analysis.success_criterion must be a non-empty string" in (
        validate_direction_decision(missing).errors
    )
    no_reopen = _freeze_decision(reason)
    no_reopen["freeze"]["reopen_conditions"] = []
    assert not validate_direction_decision(no_reopen).valid


def test_config_defaults_and_toml(tmp_path) -> None:
    from openlabs.config import load_program_settings

    program = load_program_settings({})
    assert program.max_days_from_admission_to_ready == 28
    assert program.topic_max_agent_seconds == 259_200
    assert program.direction_limits == {"targeted_core_analysis": 1,
                                        "retarget_or_short_format": 2}
    assert program.auto_handoff is False
    custom = load_program_settings({"direction_limits": {"targeted_core_analysis": 0},
                                    "auto_handoff": True})
    assert custom.direction_limits["targeted_core_analysis"] == 0 and custom.auto_handoff
    with pytest.raises(ValueError):
        load_program_settings({"direction_limits": {"other": 1}})


# --------------------------------------------------------------------------- pre-registration


def test_preregistration_hash_must_match_the_ledger(tmp_path, monkeypatch) -> None:
    paths, db, settings, (topic,) = _program(tmp_path, monkeypatch)
    research = db.latest_task(topic["campaign_id"])
    _lease(paths, settings, monkeypatch, db, research["task_id"])
    # The agent also edits its own state file: only the ledger counts.
    state_path = Path(db.campaign(topic["campaign_id"])["workstream_state_path"])
    state = json.loads(state_path.read_text(encoding="utf-8"))
    forged = "f" * 64
    _finish(db, paths, research["task_id"],
            extra=_research_payload(topic, preregistration_sha256=forged), session="r1")
    assert state["preregistration"]["sha256"] == topic["preregistration_sha256"]

    report = _tick(paths, settings, monkeypatch)

    task = db.task(research["task_id"])
    assert task["status"] == "needs_replan"
    assert "preregistration" in db.result_runtime(research["task_id"])["gate_failure_classes"]
    assert "differs from the pre-registration recorded in the topic ledger" in task["last_error"]
    assert not any(db.task(t)["task_type"] == "paper_readiness" for t in report.enqueued)


def test_missing_fields_are_filled_not_bounced_and_unlinked_campaigns_are_unchanged(
    tmp_path, monkeypatch
):
    from openlabs.gates import evaluate_result_bundle, fill_control_plane_fields

    payload = {
        "schema_version": RESULT_SCHEMA, "task_id": "t", "campaign_id": "c", "lab_id": "ai",
        "status": "succeeded", "summary": "s", "artifacts": [], "claims": [],
        "paper_candidate": False, "gate_result": {"promotion_decision": "freeze"},
    }
    # 2026-11-12/13: six results were bounced for these two fields and three lead
    # replans were spent adding them. A missing hash or verdict no longer blocks.
    assert evaluate_result_bundle(payload, preregistration_sha256="a" * 64).passed
    filled, notes = fill_control_plane_fields(payload, "a" * 64)
    assert filled["preregistration_sha256"] == "a" * 64
    assert filled["primary_endpoint_verdict"] == "pending" and len(notes) == 2
    assert evaluate_result_bundle({**payload, "primary_endpoint_verdict": "pending"},
                                  preregistration_sha256="a" * 64).passed
    # A wrong verdict word or a hash that differs from the ledger still blocks.
    assert not evaluate_result_bundle({**payload, "primary_endpoint_verdict": "partly"},
                                      preregistration_sha256="a" * 64).passed
    forged = evaluate_result_bundle({**payload, "preregistration_sha256": "f" * 64},
                                    preregistration_sha256="a" * 64)
    assert not forged.passed and "preregistration" in forged.failure_classes
    # No topic (no expected hash): nothing is filled and the gate is unchanged.
    assert fill_control_plane_fields(payload, None) == (payload, [])
    assert evaluate_result_bundle(payload).passed


def test_paper_candidate_without_verdict_keeps_researching_without_a_replan(
    tmp_path, monkeypatch
):
    paths, db, settings, (topic,) = _program(tmp_path, monkeypatch)
    research = db.latest_task(topic["campaign_id"])
    _lease(paths, settings, monkeypatch, db, research["task_id"])
    _finish(db, paths, research["task_id"], extra={"paper_candidate": True}, session="r1")

    report = _tick(paths, settings, monkeypatch)

    task = db.task(research["task_id"])
    assert task["status"] == "succeeded", task["last_error"]
    runtime = db.result_runtime(research["task_id"])
    assert runtime["control_plane_filled"] == [
        "preregistration_sha256 (from the topic ledger)",
        "primary_endpoint_verdict pending (not stated)",
    ]
    archived = json.loads(Path(task["result_path"]).read_text(encoding="utf-8"))
    assert archived["preregistration_sha256"] == topic["preregistration_sha256"]
    assert not [t for t in report.enqueued if db.task(t)["task_type"] == "paper_readiness"]
    assert not [t for t in report.enqueued if db.task(t)["task_type"] == "replan"]


def test_failed_endpoint_does_not_enter_writing_and_schedules_a_direction_decision(
    tmp_path, monkeypatch
):
    paths, db, settings, (topic,) = _program(tmp_path, monkeypatch)
    research = db.latest_task(topic["campaign_id"])
    _lease(paths, settings, monkeypatch, db, research["task_id"])
    _finish(db, paths, research["task_id"], extra=_research_payload(topic, "failed"),
            session="r1")

    report = _tick(paths, settings, monkeypatch)

    assert report.errors == []
    assert db.task(research["task_id"])["status"] == "succeeded"
    assert not [t for t in report.enqueued if db.task(t)["task_type"] == "paper_readiness"]
    decision = _direction_task(db)
    assert decision["campaign_id"] == "ai-program-direction"
    packet = json.loads(Path(decision["input_path"]).read_text(encoding="utf-8"))
    assert packet["trigger"]["reason"] == "primary_endpoint_failed"
    assert report.program["direction_decisions"][0]["trigger"] == "primary_endpoint_failed"
    assert "direction_decision_scheduled" in _events(db, topic["topic_id"])
    # The topic campaign waits for the decision instead of reseeding research.
    later = _tick(paths, settings, monkeypatch)
    assert {"campaign_id": topic["campaign_id"], "reason": "direction_decision_pending"} in (
        later.production_blocked
    )


def test_inconclusive_endpoint_keeps_researching(tmp_path, monkeypatch) -> None:
    paths, db, settings, (topic,) = _program(tmp_path, monkeypatch)
    research = db.latest_task(topic["campaign_id"])
    _lease(paths, settings, monkeypatch, db, research["task_id"])
    _finish(db, paths, research["task_id"], extra=_research_payload(
        topic, "inconclusive",
        next_actions=[{"objective": "Add the second admission year.", "agent_role": "researcher",
                       "session_mode": "resume"}],
    ), session="r1")
    report = _tick(paths, settings, monkeypatch)
    follow = [db.task(t) for t in report.enqueued]
    assert follow and follow[0]["task_type"] == "research_continue"
    assert not _direction_tasks(db)
    assert "primary_endpoint_inconclusive" in _events(db, topic["topic_id"])


# --------------------------------------------------------------------------- deadline and budget


def test_overdue_topic_gets_exactly_one_direction_decision(tmp_path, monkeypatch) -> None:
    paths, db, settings, (topic,) = _program(tmp_path, monkeypatch)
    later = budget_control.current_time() + timedelta(days=29)
    monkeypatch.setattr(budget_control, "current_time", lambda: later)
    research = db.latest_task(topic["campaign_id"])
    _lease(paths, settings, monkeypatch, db, research["task_id"])
    _finish(db, paths, research["task_id"], extra={"paper_candidate": False})

    report = _tick(paths, settings, monkeypatch)

    tasks = _direction_tasks(db)
    assert len(tasks) == 1
    packet = json.loads(Path(tasks[0]["input_path"]).read_text(encoding="utf-8"))
    assert packet["trigger"]["reason"] == "overdue" and packet["deadline"]["overdue"]
    assert _topic(paths, settings, topic["topic_id"])["status"] == "active"  # not frozen
    assert [d["trigger"] for d in report.program["direction_decisions"]] == ["overdue"]
    # Decide to continue; the overdue trigger never fires again for this topic.
    reason = packet["reasons_to_answer"][0]
    _decide(paths, settings, monkeypatch, db, _retarget_decision(reason))
    for _ in range(2):
        _tick(paths, settings, monkeypatch)
    assert len(_direction_tasks(db)) == 1


def test_budget_exhaustion_routes_to_one_direction_decision(tmp_path, monkeypatch) -> None:
    paths, db, settings, (topic,) = _program(tmp_path, monkeypatch)
    campaign_id = topic["campaign_id"]
    campaign = db.campaign(campaign_id)
    assert campaign["max_agent_seconds"] == 43_200  # card estimate below the 72 h ceiling
    policy = json.loads(campaign["workstream_policy_json"])
    assert policy["max_agent_seconds"] == 43_200
    queued = db.latest_task(campaign_id)
    with db.connect() as connection:
        connection.execute("UPDATE campaigns SET agent_seconds_used=43200 WHERE campaign_id=?",
                           (campaign_id,))
        connection.execute("UPDATE tasks SET status='queued' WHERE task_id=?",
                           (queued["task_id"],))

    report = _tick(paths, settings, monkeypatch)

    assert db.task(queued["task_id"])["status"] == "cancelled"  # not needs_human
    tasks = _direction_tasks(db)
    assert len(tasks) == 1
    assert json.loads(Path(tasks[0]["input_path"]).read_text())["trigger"]["reason"] == (
        "budget_exhausted"
    )
    assert report.program["direction_decisions"][0]["trigger"] == "budget_exhausted"
    _tick(paths, settings, monkeypatch)
    assert len(_direction_tasks(db)) == 1
    # Continuing raises the budget to the hard ceiling; reaching it freezes the topic.
    reason = json.loads(Path(tasks[0]["input_path"]).read_text())["reasons_to_answer"][0]
    _decide(paths, settings, monkeypatch, db, _analysis_decision(reason))
    assert db.campaign(campaign_id)["max_agent_seconds"] == settings.program.topic_max_agent_seconds
    assert db.campaign(campaign_id)["status"] == "active"
    with db.connect() as connection:
        connection.execute("UPDATE campaigns SET agent_seconds_used=? WHERE campaign_id=?",
                           (settings.program.topic_max_agent_seconds, campaign_id))
        connection.execute("UPDATE tasks SET status='cancelled' WHERE campaign_id=? AND "
                           "status IN ('queued','leased')", (campaign_id,))
    _tick(paths, settings, monkeypatch)
    frozen = _topic(paths, settings, topic["topic_id"])
    assert frozen["status"] == "frozen" and frozen["freeze_reason_class"] == "budget_exhausted"
    assert len(_direction_tasks(db)) == 1


# --------------------------------------------------------------------------- explicit freeze


@pytest.mark.parametrize("declared", ["decisive_data_unavailable", None])
def test_explicit_freeze_writes_the_ledger_and_releases_the_slot(tmp_path, monkeypatch, declared):
    paths, db, settings, (topic,) = _program(tmp_path, monkeypatch)
    research = db.latest_task(topic["campaign_id"])
    _lease(paths, settings, monkeypatch, db, research["task_id"])
    receipt = paths.data / "workspaces" / "ai" / "receipt.json"
    receipt.write_text("{}", encoding="utf-8")
    gate_result = {"promotion_decision": "freeze",
                   "evidence": [{"path": str(receipt), "sha256": sha256_file(receipt)}]}
    if declared:
        gate_result["freeze_reason_class"] = declared
    _finish(db, paths, research["task_id"], extra={
        "primary_endpoint_verdict": "inconclusive",
        "preregistration_sha256": topic["preregistration_sha256"], "gate_result": gate_result,
    })
    before = slot_status(open_topic_ledger(paths, settings.program).read(), settings.program)

    report = _tick(paths, settings, monkeypatch)

    frozen = _topic(paths, settings, topic["topic_id"])
    assert frozen["status"] == "frozen"
    assert frozen["freeze_reason_class"] == "decisive_data_unavailable"
    assert {item["path"] for item in frozen["freeze_evidence"]} >= {str(receipt)}
    assert db.campaign(topic["campaign_id"])["status"] == "frozen"
    after = slot_status(open_topic_ledger(paths, settings.program).read(), settings.program)
    assert after.free_slots == before.free_slots + 1
    assert report.program["topics_frozen"][0]["topic_id"] == topic["topic_id"]
    notes = [h for h in frozen["history"] if h.get("kind") == "topic_freeze_noted"]
    if declared is None:
        assert notes and notes[0]["detail"]["reason_class_inferred"] is True
        assert "topic_freeze_noted" in _events(db, topic["topic_id"])
    else:
        assert not notes


# --------------------------------------------------------------------------- review signals


@pytest.mark.parametrize(
    ("outcome", "actions", "trigger"),
    [
        (_outcome(next_action="direction_decision", status="blocked",
                  direction_context=CONTEXT), [], "review_direction_decision"),
        (_outcome(next_action="retarget_required", status="blocked"), [],
         "review_retarget_required"),
        (_outcome(next_action="text_revision", review_stalled=True),
         [{"objective": "Tighten the abstract.", "agent_role": "writer",
           "session_mode": "resume", "handoff_kind": "text_revision"}], "review_stalled"),
        (_outcome(next_action="text_revision", status="blocked", rounds_for_target=4),
         [{"objective": "Tighten the abstract.", "agent_role": "writer",
           "session_mode": "resume", "handoff_kind": "text_revision"}],
         "review_rounds_exhausted"),
    ],
)
def test_review_signals_schedule_a_direction_decision_instead_of_the_writer(
    tmp_path, monkeypatch, outcome, actions, trigger
):
    paths, db, settings, (topic,) = _program(tmp_path, monkeypatch)
    review = _to_review(paths, db, settings, monkeypatch, topic)
    _finish(db, paths, review["task_id"],
            extra={"review_outcome": outcome, "next_actions": actions}, supported=False)

    report = _tick(paths, settings, monkeypatch)

    assert report.errors == []
    assert not [t for t in report.enqueued if db.task(t)["agent_role"] == "writer"]
    decision = _direction_task(db)
    packet = json.loads(Path(decision["input_path"]).read_text(encoding="utf-8"))
    assert packet["trigger"]["reason"] == trigger
    if outcome.get("direction_context"):
        assert CONTEXT["strongest_desk_reject_reason"] in packet["reasons_to_answer"]
        assert packet["direction_context"]["referee_rejections"]
    assert _topic(paths, settings, topic["topic_id"])["status"] == "in_review"


def test_review_without_outcome_keeps_the_legacy_writer_revision(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _program(tmp_path, monkeypatch)
    review = _to_review(paths, db, settings, monkeypatch, topic)
    _finish(db, paths, review["task_id"], extra={"next_actions": [
        {"objective": "Tighten the abstract.", "agent_role": "writer",
         "session_mode": "resume", "handoff_kind": "text_revision"}]}, supported=False)
    report = _tick(paths, settings, monkeypatch)
    follow = [db.task(t) for t in report.enqueued]
    assert follow and follow[0]["task_type"] == "paper_revision"
    assert follow[0]["routing_reason"] == "review_text_revision"
    assert not _direction_tasks(db)


def test_failed_review_without_next_action_is_never_reseeded(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _program(tmp_path, monkeypatch)
    review = _to_review(paths, db, settings, monkeypatch, topic)
    _finish(db, paths, review["task_id"], extra={}, supported=False)
    _tick(paths, settings, monkeypatch)
    report = _tick(paths, settings, monkeypatch)
    assert {"campaign_id": topic["campaign_id"],
            "reason": "paper_review_without_next_action"} in report.production_blocked
    latest = db.latest_task(topic["campaign_id"])
    assert latest["task_id"] == review["task_id"]  # no generic researcher was seeded


# --------------------------------------------------------------------------- decisions


def _review_direction(paths, db, settings, monkeypatch, topic, **outcome):
    review = _to_review(paths, db, settings, monkeypatch, topic)
    _finish(db, paths, review["task_id"], extra={"review_outcome": _outcome(
        next_action="direction_decision", status="blocked", direction_context=CONTEXT,
        **outcome)}, supported=False)
    _tick(paths, settings, monkeypatch)
    return review


def test_direction_decision_goes_to_the_lead_tier_of_another_family(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _program(tmp_path, monkeypatch)
    _review_direction(paths, db, settings, monkeypatch, topic)
    task = _direction_task(db)
    with db.connect() as connection:
        research_runner = connection.execute(
            "SELECT runner FROM tasks WHERE campaign_id=? AND agent_role='researcher' "
            "ORDER BY rowid LIMIT 1", (topic["campaign_id"],),
        ).fetchone()["runner"]
    research_provider = RUNNERS[research_runner].provider
    assert task["agent_role"] == "reviewer" and task["session_mode"] == "fresh"
    assert task["exclude_provider"] == research_provider
    assert task["skill_path"] == "openlabs-direction-decision"
    task = _lease(paths, settings, monkeypatch, db, task["task_id"])
    routed = RUNNERS[task["runner"]]
    assert routed.tier == "lead" and routed.provider != research_provider
    packet = json.loads(Path(task["input_path"]).read_text(encoding="utf-8"))
    assert packet["decisions_remaining"] == {"targeted_core_analysis": 1,
                                             "retarget_or_short_format": 2}
    assert packet["ledger_entry"]["topic_id"] == topic["topic_id"]
    assert packet["routine_fallback"] and packet["budget"]["topic_max_agent_seconds"] == 259_200


def test_targeted_analysis_runs_then_returns_to_the_writer(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _program(tmp_path, monkeypatch)
    review = _review_direction(paths, db, settings, monkeypatch, topic)
    reason = CONTEXT["strongest_desk_reject_reason"]
    report = _decide(paths, settings, monkeypatch, db, _analysis_decision(f"“{reason}”"))
    analysis = db.task(report.program["direction_decisions"][-1]["executed_task_id"])
    assert analysis["task_type"] == "evidence_remediation"
    assert analysis["routing_reason"] == "direction_targeted_analysis"
    assert analysis["campaign_id"] == topic["campaign_id"]
    assert analysis["parent_task_id"] == review["task_id"]
    assert "External cohort validation on eICU" in analysis["objective"]
    assert "AUROC gap within 0.02" in analysis["objective"]
    assert _topic(paths, settings, topic["topic_id"])["status"] == "in_review"
    assert "direction_decided" in _events(db, topic["topic_id"])
    _lease(paths, settings, monkeypatch, db, analysis["task_id"])
    _finish(db, paths, analysis["task_id"])
    after = _tick(paths, settings, monkeypatch)
    revision = [db.task(t) for t in after.enqueued if db.task(t)["agent_role"] == "writer"]
    assert revision and revision[0]["task_type"] == "paper_revision"
    assert revision[0]["session_mode"] == "resume"
    assert revision[0]["routing_reason"] == "review_evidence_completed"


def test_retarget_resumes_the_writer_and_escalation_defaults_to_the_fallback(
    tmp_path, monkeypatch
):
    paths, db, settings, (topic,) = _program(tmp_path, monkeypatch, tier="escalation")
    assert topic["target_tier"] == "escalation"
    _review_direction(paths, db, settings, monkeypatch, topic)
    reason = CONTEXT["referee_rejections"][0]["principal_reason"]
    report = _decide(paths, settings, monkeypatch, db, _retarget_decision(reason, "fallback"))
    revision = db.task(report.program["direction_decisions"][-1]["executed_task_id"])
    assert revision["task_type"] == "paper_revision" and revision["agent_role"] == "writer"
    assert revision["routing_reason"] == "direction_retarget"
    assert revision["session_mode"] == "resume"
    assert "handoff_kind=retarget" in revision["objective"]
    assert "Journal of Biomedical Informatics" in revision["objective"]
    # The new target's indexing, zone and every mandatory charge are verified first.
    assert "page charges" in revision["objective"]
    assert "2025 CAS major-category zone" in revision["objective"]
    assert "program check-fallback" in revision["objective"]


def test_freeze_decision_freezes_and_limits_force_a_freeze(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _program(
        tmp_path, monkeypatch, direction_limits={"targeted_core_analysis": 0,
                                                 "retarget_or_short_format": 2},
    )
    _review_direction(paths, db, settings, monkeypatch, topic)
    reason = CONTEXT["strongest_desk_reject_reason"]
    # A choice whose limit is used up is refused and the topic frozen.
    report = _decide(paths, settings, monkeypatch, db, _analysis_decision(reason))
    frozen = _topic(paths, settings, topic["topic_id"])
    assert frozen["status"] == "frozen"
    assert frozen["freeze_reason_class"] == "contribution_insufficient"
    outcome = report.program["direction_decisions"][-1]
    assert outcome["outcome"] == "rejected_frozen"
    assert outcome["rejection"] == "direction_limit_exhausted"
    assert not [t for t in report.enqueued if db.task(t)["task_type"] == "evidence_remediation"]


def test_targeted_analysis_count_is_enforced_from_routing_usage(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _program(tmp_path, monkeypatch)
    review = _review_direction(paths, db, settings, monkeypatch, topic)
    reason = CONTEXT["strongest_desk_reject_reason"]
    report = _decide(paths, settings, monkeypatch, db, _analysis_decision(reason))
    assert report.program["direction_decisions"][-1]["outcome"] == "executed"
    assert db.campaign_routing_usage(topic["campaign_id"])["direction_targeted_analysis"][
        "task_count"] == 1
    # A second review asks again; a second targeted analysis is out of bounds.
    analysis = db.task(report.program["direction_decisions"][-1]["executed_task_id"])
    with db.connect() as connection:
        connection.execute("UPDATE tasks SET status='cancelled' WHERE task_id=?",
                           (analysis["task_id"],))
    scheduled = program_autonomy.schedule_direction_decision(
        db, paths, settings, engine.TickReport(), topic=_topic(paths, settings, topic["topic_id"]),
        trigger="review_direction_decision", source_task_id=review["task_id"],
        evidence=[], direction_context=CONTEXT, attempt=2,
    )
    assert scheduled is not None
    report = _decide(paths, settings, monkeypatch, db, _analysis_decision(reason))
    assert report.program["direction_decisions"][-1]["rejection"] == "direction_limit_exhausted"
    assert _topic(paths, settings, topic["topic_id"])["status"] == "frozen"


def test_unquoted_reason_is_retried_once_then_frozen(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _program(tmp_path, monkeypatch)
    _review_direction(paths, db, settings, monkeypatch, topic)
    bad = _freeze_decision("A reason nobody wrote down anywhere at all.")
    _decide(paths, settings, monkeypatch, db, bad)
    tasks = _direction_tasks(db)
    assert len(tasks) == 2
    assert json.loads(Path(tasks[1]["input_path"]).read_text())["attempt"] == 2
    assert _topic(paths, settings, topic["topic_id"])["status"] == "in_review"
    _decide(paths, settings, monkeypatch, db, bad)
    frozen = _topic(paths, settings, topic["topic_id"])
    assert frozen["status"] == "frozen" and frozen["freeze_reason_class"] == "review_stalled"
    assert "direction_decision_invalid" in _events(db, topic["topic_id"])


# --------------------------------------------------------------------------- delivery


def _ready(paths, db, settings, monkeypatch, topic) -> engine.TickReport:
    review = _to_review(paths, db, settings, monkeypatch, topic)
    _finish(db, paths, review["task_id"], extra={
        "paper_candidate": True, "review_outcome": _outcome(status="ready")})
    return _tick(paths, settings, monkeypatch)


def test_ready_paper_is_queued_releases_its_slot_and_the_next_topic_starts(
    tmp_path, monkeypatch
):
    paths, db, settings, (first, second) = _program(
        tmp_path, monkeypatch, cards=2, max_active_topics=1
    )
    assert first["status"] == "active" and second["status"] == "admitted"

    report = _ready(paths, db, settings, monkeypatch, first)

    ready = _topic(paths, settings, first["topic_id"])
    assert ready["status"] == "ready_queue"
    assert ready["paper_id"] == "20261111-ai-health-temporal-retrieval"
    assert ready["handoff"]["status"] == "queued"
    assert db.campaign(first["campaign_id"])["status"] == "production_paused"
    assert report.program["ready_queued"][0]["topic_id"] == first["topic_id"]
    assert _topic(paths, settings, second["topic_id"])["status"] == "active"
    assert report.program["handoffs"] == [{"topic_id": first["topic_id"],
                                           "paper_id": ready["paper_id"],
                                           "outcome": "queued_auto_handoff_off"}]
    assert "topic_ready" in _events(db, first["topic_id"])
    # Project synchronization never reactivates the paused campaign.
    _tick(paths, settings, monkeypatch)
    assert db.campaign(first["campaign_id"])["status"] == "production_paused"


def _deliverable(monkeypatch) -> None:
    """The release pipeline finds nothing left to do before delivery (see test_release_pipeline)."""

    monkeypatch.setattr(program_autonomy, "run_release_status", lambda _p, _s, paper_id: {
        "paper_id": paper_id, "version": "1.0.0", "review": {"ready": True, "current": True},
        "support": {"required": False}, "issues": [], "commit_paths": [], "delivered": False})
    monkeypatch.setattr(program_autonomy, "commit_paper_paths", lambda *_a, **_k: None)


def test_auto_handoff_without_handler_retries_a_failure(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _program(tmp_path, monkeypatch, auto_handoff=True)
    _deliverable(monkeypatch)
    monkeypatch.setenv("ARA_PAPER_MANAGE_API_URL", "https://manage.invalid")
    monkeypatch.setenv("ARA_PAPER_MANAGE_API_KEY", "test-key")
    calls: list[str] = []

    def fake_delivery(_paths, _settings, paper_id):
        calls.append(paper_id)
        if len(calls) == 1:
            raise program_autonomy.DeliveryError("Manage API 503: unavailable")
        return {"status": "delivered", "paper_id": paper_id, "package_id": "pkg-1",
                "submission_handler": None, "awaiting_owner_review": True}

    monkeypatch.setattr(program_autonomy, "run_paper_delivery", fake_delivery)
    report = _ready(paths, db, settings, monkeypatch, topic)
    assert report.program["handoffs"][0]["outcome"] == "failed"
    assert _topic(paths, settings, topic["topic_id"])["status"] == "ready_queue"
    retry = _tick(paths, settings, monkeypatch)
    assert retry.program["handoffs"][0]["outcome"] == "delivered"
    done = _topic(paths, settings, topic["topic_id"])
    assert done["handoff"]["status"] == "delivered" and done["handoff"]["attempts"] == 2
    assert done["handoff"]["submission_handler"] is None
    assert done["awaiting_owner_review"] is True
    assert {"handoff_failed", "handoff_delivered"} <= set(_events(db, topic["topic_id"]))
    _tick(paths, settings, monkeypatch)
    assert len(calls) == 2  # delivered once, never again


def test_delivery_attempts_are_bounded(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _program(tmp_path, monkeypatch, auto_handoff=True,
                                             handoff_max_attempts=2)
    _deliverable(monkeypatch)
    monkeypatch.setenv("ARA_PAPER_MANAGE_API_URL", "https://manage.invalid")
    monkeypatch.setenv("ARA_PAPER_MANAGE_API_KEY", "test-key")

    def failing(*_args):
        raise program_autonomy.DeliveryError("Release files differ from Git HEAD")

    monkeypatch.setattr(program_autonomy, "run_paper_delivery", failing)
    _ready(paths, db, settings, monkeypatch, topic)
    for _ in range(3):
        _tick(paths, settings, monkeypatch)
    state = _topic(paths, settings, topic["topic_id"])["handoff"]
    assert state["status"] == "exhausted" and state["attempts"] == 2


def test_delivery_command_sets_the_external_write_switch_only_for_itself(tmp_path, monkeypatch):
    import subprocess

    paths = _paths(tmp_path)
    settings = _settings(paper_writing_command=("paper-writing",))
    seen: dict = {}

    def fake_run(command, **kwargs):
        seen.update(command=command, env=kwargs["env"])
        return subprocess.CompletedProcess(command, 0, json.dumps(
            {"status": "delivered", "submission_handler": None}), "")

    monkeypatch.setattr(program_autonomy.subprocess, "run", fake_run)
    result = program_autonomy.run_paper_delivery(paths, settings, "p")
    assert result["submission_handler"] is None
    assert seen["command"][:4] == ["paper-writing", "program", "deliver", "--paper-id"]
    assert "--handler" not in seen["command"]
    assert seen["env"]["OPENLABS_ENABLE_EXTERNAL_WRITES"] == "1"


def test_assign_handler_command_after_owner_review(tmp_path, monkeypatch):
    from openlabs.__main__ import _parser

    args = _parser().parse_args(["program", "assign-handler", "--paper-id", "p"])
    assert args.handler == "second_author"
    paths, db, settings, (topic,) = _program(tmp_path, monkeypatch, auto_handoff=True)
    _deliverable(monkeypatch)
    monkeypatch.setenv("ARA_PAPER_MANAGE_API_URL", "https://manage.invalid")
    monkeypatch.setenv("ARA_PAPER_MANAGE_API_KEY", "test-key")
    monkeypatch.setattr(program_autonomy, "run_paper_delivery", lambda *_a: {
        "status": "delivered", "package_id": "pkg", "submission_handler": None})
    _ready(paths, db, settings, monkeypatch, topic)
    paper_id = _topic(paths, settings, topic["topic_id"])["paper_id"]
    seen: list = []
    monkeypatch.setattr(program_autonomy, "run_handler_assignment",
                        lambda _p, _s, pid, handler: seen.append((pid, handler)) or {
                            "status": "assigned", "submission_handler": "Qisheng Wang"})
    result = program_autonomy.assign_submission_handler(db, paths, settings, paper_id=paper_id)
    assert seen == [(paper_id, "second_author")]
    assert result["topic_id"] == topic["topic_id"]
    assert _topic(paths, settings, topic["topic_id"])["awaiting_owner_review"] is False
    assert "submission_handler_assigned" in _events(db, topic["topic_id"])


# --------------------------------------------------------------------------- admission gap


def test_enforce_admission_blocks_reviewer_selected_candidates_of_ordinary_projects(tmp_path):
    paths = _paths(tmp_path)
    db = _db(paths)
    root = paths.data / "workspaces" / "ai" / "projects" / "ordinary"
    root.mkdir(parents=True)
    project = json.loads((TEMPLATE / "project.json").read_text(encoding="utf-8"))
    project.update({"project_id": "ordinary", "program": False})
    atomic_write_json(root / "project.json", project)
    for name in ("scout_state.json", "admission_state.json"):
        (root / name).write_text((TEMPLATE / name).read_text(encoding="utf-8"), encoding="utf-8")
    campaign = {"campaign_id": "review", "project_config_path": str(root / "project.json"),
                "workstream_policy_json": json.dumps({"spawn_candidate_workstreams": True})}
    task = {"task_id": "review-1", "agent_role": "reviewer"}
    payload = {"candidate_branches": [{"candidate_id": "idea", "title": "Idea",
                                       "objective": "o", "rationale": "r",
                                       "source_result_ids": ["x"]}]}
    enforced = replace(_settings(enforce_admission=True))
    spawned = spawn_candidate_workstreams(db, paths, enforced, campaign, task, payload,
                                          result_path=root / "r.json")
    assert spawned.campaign_ids == () and spawned.task_ids == ()
    assert spawned.decisions[0]["reason"] == "topic_not_admitted"
    assert [e["event_type"] for e in db.events(entity_type="project", entity_id="ordinary")] == [
        "candidate_blocked_by_admission"
    ]
    # Default behaviour is unchanged (the project is then asked to materialize).
    with pytest.raises(ValueError):
        spawn_candidate_workstreams(db, paths, _settings(), campaign, task, payload,
                                    result_path=root / "r.json")


# --------------------------------------------------------------------------- end to end


def test_end_to_end_research_to_ready_queue(tmp_path, monkeypatch):
    paths, db, settings, (first, second) = _program(
        tmp_path, monkeypatch, cards=2, max_active_topics=1
    )
    report = _ready(paths, db, settings, monkeypatch, first)
    assert report.errors == []
    assert _topic(paths, settings, first["topic_id"])["status"] == "ready_queue"
    statuses = [h.get("to") for h in _topic(paths, settings, first["topic_id"])["history"]
                if "to" in h]
    assert statuses == ["proposed", "admitted", "active", "in_review", "ready_queue"]
    assert _topic(paths, settings, second["topic_id"])["status"] == "active"
    status = slot_status(open_topic_ledger(paths, settings.program).read(), settings.program)
    assert status.ready_unsubmitted == 1 and status.active == 1


def test_end_to_end_contribution_insufficient_freezes_and_releases_the_slot(
    tmp_path, monkeypatch
):
    paths, db, settings, (first, second) = _program(
        tmp_path, monkeypatch, cards=2, max_active_topics=1
    )
    _review_direction(paths, db, settings, monkeypatch, first)
    reason = CONTEXT["strongest_desk_reject_reason"]

    report = _decide(paths, settings, monkeypatch, db, _freeze_decision(reason))

    frozen = _topic(paths, settings, first["topic_id"])
    assert frozen["status"] == "frozen"
    assert frozen["freeze_reason_class"] == "contribution_insufficient"
    assert frozen["reopen_conditions"][0]["type"] == "new_data_source"
    assert db.campaign(first["campaign_id"])["status"] == "frozen"
    assert report.program["direction_decisions"][-1]["outcome"] == "frozen"
    assert report.program["topics_frozen"][0]["topic_id"] == first["topic_id"]
    assert _topic(paths, settings, second["topic_id"])["status"] == "active"
    decided = [h for h in frozen["history"] if h.get("kind") == "direction_decided"]
    assert decided and decided[0]["detail"]["answers_reason"] == reason
    assert {"direction_decision_scheduled", "direction_decided", "topic_frozen"} <= set(
        _events(db, first["topic_id"])
    )


def test_disabled_program_adds_nothing(tmp_path, monkeypatch) -> None:
    from openlabs.config import ProgramSettings

    paths = _paths(tmp_path)
    _install_program(paths)
    _db(paths)
    settings = replace(_settings(), program=ProgramSettings())
    report = _tick(paths, settings, monkeypatch)
    assert report.program == {}
    assert not (paths.artifacts / "program-control").exists()


def test_failed_decision_task_is_retried_once_then_the_topic_freezes(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _program(tmp_path, monkeypatch)
    _review_direction(paths, db, settings, monkeypatch, topic)
    for expected in (2, 2):
        task = _direction_task(db)
        with db.connect() as connection:
            connection.execute("UPDATE tasks SET status='needs_human' WHERE task_id=?",
                               (task["task_id"],))
        _tick(paths, settings, monkeypatch)
        assert len(_direction_tasks(db)) == expected
    frozen = _topic(paths, settings, topic["topic_id"])
    assert frozen["status"] == "frozen" and frozen["freeze_reason_class"] == "review_stalled"
    assert frozen["freeze_evidence"]


def test_topics_of_a_paused_program_project_get_no_stop_rule_decision(tmp_path, monkeypatch):
    """A paused project's topics wait: no overdue decision until the project is active."""

    paths, db, settings, (topic,) = _program(tmp_path, monkeypatch)
    later = budget_control.current_time() + timedelta(days=29)
    monkeypatch.setattr(budget_control, "current_time", lambda: later)
    research = db.latest_task(topic["campaign_id"])
    _lease(paths, settings, monkeypatch, db, research["task_id"])
    _finish(db, paths, research["task_id"], extra={"paper_candidate": False})
    project_path = Path(str(db.campaign(topic["campaign_id"])["project_config_path"]))
    payload = json.loads(project_path.read_text(encoding="utf-8"))
    payload["status"] = "paused"
    project_path.write_text(json.dumps(payload), encoding="utf-8")

    report = _tick(paths, settings, monkeypatch)

    assert _direction_tasks(db) == []
    assert report.program["parked_topics"] == 1
    assert db.campaign(topic["campaign_id"])["status"] == "production_paused"
    assert _topic(paths, settings, topic["topic_id"])["status"] == "active"

    payload["status"] = "active"
    project_path.write_text(json.dumps(payload), encoding="utf-8")
    _tick(paths, settings, monkeypatch)
    assert db.campaign(topic["campaign_id"])["status"] == "active"
    assert len(_direction_tasks(db)) == 1


# --------------------------------------------------------------------------- research needs_human


BLOCKED = {
    "status": "needs_human",
    "summary": "The precheck job is still queued; no verdict exists.",
    "human_intervention": {"reason": "A lead decision is needed to continue or pause the topic.",
                           "required_action": "Decide whether to wait for the job or freeze."},
}


def _blocked_research(paths, db, settings, monkeypatch, topic) -> dict:
    research = db.latest_task(topic["campaign_id"])
    _lease(paths, settings, monkeypatch, db, research["task_id"])
    _finish(db, paths, research["task_id"], extra=dict(BLOCKED))
    return research


def test_research_needs_human_becomes_one_direction_decision_and_a_freeze_frees_the_slot(
    tmp_path, monkeypatch
):
    paths, db, settings, (first, second) = _program(
        tmp_path, monkeypatch, cards=2, max_active_topics=1
    )
    assert first["status"] == "active" and second["status"] == "admitted"
    research = _blocked_research(paths, db, settings, monkeypatch, first)

    report = _tick(paths, settings, monkeypatch)

    assert db.task(research["task_id"])["status"] == "needs_human"
    tasks = _direction_tasks(db)
    assert len(tasks) == 1
    packet = json.loads(Path(tasks[0]["input_path"]).read_text(encoding="utf-8"))
    assert packet["trigger"]["reason"] == "research_needs_human"
    assert packet["trigger"]["source_task_id"] == research["task_id"]
    assert BLOCKED["human_intervention"]["reason"] in packet["reasons_to_answer"]
    assert BLOCKED["summary"] in packet["reasons_to_answer"]
    assert [d["trigger"] for d in report.program["direction_decisions"]] == [
        "research_needs_human"
    ]
    assert _topic(paths, settings, first["topic_id"])["status"] == "active"
    _tick(paths, settings, monkeypatch)
    assert len(_direction_tasks(db)) == 1  # once per source result

    _decide(paths, settings, monkeypatch, db, _freeze_decision(BLOCKED["summary"]))

    frozen = _topic(paths, settings, first["topic_id"])
    assert frozen["status"] == "frozen"
    assert frozen["freeze_reason_class"] == "contribution_insufficient"
    assert _topic(paths, settings, second["topic_id"])["status"] == "active"
    for _ in range(2):
        _tick(paths, settings, monkeypatch)
    assert len(_direction_tasks(db)) == 1


def test_research_needs_human_can_continue_with_one_targeted_step(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _program(tmp_path, monkeypatch)
    research = _blocked_research(paths, db, settings, monkeypatch, topic)
    _tick(paths, settings, monkeypatch)

    report = _decide(paths, settings, monkeypatch, db, _analysis_decision(BLOCKED["summary"]))

    analysis = db.task(report.program["direction_decisions"][-1]["executed_task_id"])
    assert analysis["campaign_id"] == topic["campaign_id"]
    assert analysis["routing_reason"] == "direction_targeted_analysis"
    assert analysis["parent_task_id"] == research["task_id"]
    assert _topic(paths, settings, topic["topic_id"])["status"] == "active"
    _tick(paths, settings, monkeypatch)
    assert len(_direction_tasks(db)) == 1


def test_research_needs_human_of_a_paused_campaign_gets_no_decision(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _program(tmp_path, monkeypatch)
    _blocked_research(paths, db, settings, monkeypatch, topic)
    project_path = Path(str(db.campaign(topic["campaign_id"])["project_config_path"]))
    payload = json.loads(project_path.read_text(encoding="utf-8"))
    payload["status"] = "paused"
    project_path.write_text(json.dumps(payload), encoding="utf-8")

    _tick(paths, settings, monkeypatch)

    assert _direction_tasks(db) == []
    assert _topic(paths, settings, topic["topic_id"])["status"] == "active"


def test_needs_human_from_a_runner_failure_is_left_to_the_infrastructure_triage(
    tmp_path, monkeypatch
):
    paths, db, settings, (topic,) = _program(tmp_path, monkeypatch)
    research = _blocked_research(paths, db, settings, monkeypatch, topic)
    _tick(paths, settings, monkeypatch)
    attempts = db.task_attempts(research["task_id"])
    assert attempts
    campaign = db.campaign(topic["campaign_id"])
    latest = db.task(research["task_id"])
    assert latest["status"] == "needs_human"
    assert program_autonomy._research_block(db, campaign, latest) is not None
    with db.connect() as connection:
        connection.execute(
            "UPDATE task_attempts SET runtime_json=? WHERE attempt_id=?",
            (json.dumps({"failure_class": "lab_runtime_setup"}), attempts[-1]["attempt_id"]),
        )
    assert program_autonomy._research_block(db, campaign, latest) is None
