"""Owner mode: one owner agent per admitted topic, seat after seat."""

from __future__ import annotations

import importlib.util
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from openlabs import budget as budget_control
from openlabs import codex_hook, owner, remote_wait
from openlabs.config import (
    OWNER_TASK_TYPE,
    OwnerSettings,
    load_program_settings,
)
from openlabs.contracts import (
    RECEIPT_SCHEMA,
    RESULT_SCHEMA,
    atomic_write_json,
    sha256_file,
    validate_result_bundle,
)
from openlabs.db import FactoryDB
from openlabs.program import open_topic_ledger
from test_program_autonomy import (
    _analysis_decision,
    _decide,
    _direction_tasks,
    _finish,
    _lease,
    _outcome,
    _program,
    _topic,
)
from test_research_program_flow import RUNNERS, _tick

CODE_ROOT = Path(__file__).resolve().parents[2]
LEGACY_TYPES = {"candidate_maturation", "replan", "research_continue", "independent_review",
                "paper_readiness", "paper_write", "paper_revision", "evidence_remediation"}
JOB = "a" * 32


def _owner_program(tmp_path, monkeypatch, *, cards: int = 1, owner_settings=None, **program):
    program.setdefault("owner_mode", "all")
    if owner_settings is not None:
        program["owner"] = owner_settings
    return _program(tmp_path, monkeypatch, cards=cards, **program)


def _seat_packet(db: FactoryDB, paths, task_id: str, packet: dict, *, session: str | None = None,
                 artifact: bool = False) -> Path:
    """Fake owner: only the small status packet (no bundle fields) and a receipt."""

    task = db.task(task_id)
    assert task is not None and task["status"] == "leased", task
    attempt_id = str(task["current_attempt_id"])
    root = paths.data / "workspaces" / str(task["domain"]) / str(task["campaign_id"])
    output = root / "attempts" / attempt_id / "result.json"
    body = dict(packet)
    if artifact:
        evidence = root / "evidence" / f"{attempt_id}.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(json.dumps({"seat": task_id}), encoding="utf-8")
        body["artifacts"] = [str(evidence)]
    db.bind_attempt_spec(task_id, attempt_id=attempt_id, lab_id="ai", output_path=str(output))
    db.mark_running(task_id, attempt_id=attempt_id, owner="test", pid=1, lease_seconds=600)
    atomic_write_json(output, body)
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


def _tasks(db: FactoryDB, campaign_id: str) -> list[dict]:
    with db.connect() as connection:
        rows = connection.execute(
            "SELECT * FROM tasks WHERE campaign_id=? ORDER BY rowid", (campaign_id,)
        ).fetchall()
    return [dict(row) for row in rows]


def _latest(db, campaign_id) -> dict:
    return _tasks(db, campaign_id)[-1]


def _first_seat(paths, db, settings, monkeypatch, topic) -> dict:
    seat = _latest(db, topic["campaign_id"])
    assert seat["task_type"] == OWNER_TASK_TYPE
    return _lease(paths, settings, monkeypatch, db, seat["task_id"])


# --------------------------------------------------------------------------- switch and start


def test_owner_mode_off_keeps_the_staged_flow(tmp_path, monkeypatch) -> None:
    paths, db, settings, (topic,) = _program(tmp_path, monkeypatch)
    assert settings.program.owner_mode == "off"
    first = _latest(db, topic["campaign_id"])
    assert first["task_type"] == "candidate_maturation"
    assert not owner.applies(settings, db.campaign(topic["campaign_id"]))
    assert owner.supervise(db, settings, engine_report(), object()) == []


def engine_report():
    from openlabs import engine

    return engine.TickReport()


def test_config_parses_owner_mode_and_rejects_nonsense() -> None:
    assert load_program_settings({}).owner_mode == "off"
    assert load_program_settings({"owner_mode": "all"}).owner_mode == "all"
    parsed = load_program_settings({"owner_mode": ["astro-survey-photometry"],
                                    "owner": {"seat_wall_seconds": 12_600,
                                              "max_topics_per_runner": {"lead_claude": 2},
                                              "runners": ["worker_claude", "lead_gpt"]}})
    assert parsed.owner_mode == ("astro-survey-photometry",)
    assert parsed.owner.seat_wall_seconds == 12_600
    assert parsed.owner.max_topics_per_runner == {"lead_claude": 2}
    assert parsed.owner.runners == ("worker_claude", "lead_gpt")
    for bad in ("sometimes", 3, {"x": 1}):
        with pytest.raises(ValueError):
            load_program_settings({"owner_mode": bad})


def test_admitted_topic_starts_with_one_owner_seat(tmp_path, monkeypatch) -> None:
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    tasks = _tasks(db, topic["campaign_id"])
    assert [t["task_type"] for t in tasks] == [OWNER_TASK_TYPE]
    seat = tasks[0]
    assert seat["runner"] == "lead_claude"  # Fable first
    assert seat["session_mode"] == "fresh" and seat["agent_role"] == "researcher"
    assert seat["max_wall_seconds"] == 14_400
    assert seat["routing_reason"] == owner.ROUTING_FIRST


def test_owner_mode_by_line_only_applies_to_listed_lines(tmp_path, monkeypatch) -> None:
    paths, db, settings, (topic,) = _owner_program(
        tmp_path, monkeypatch, owner_mode=("astro-survey-photometry",)
    )
    # The template project has no research_line: the staged flow is kept.
    assert _latest(db, topic["campaign_id"])["task_type"] == "candidate_maturation"
    campaign = db.campaign(topic["campaign_id"])
    project = Path(campaign["project_config_path"])
    data = json.loads(project.read_text(encoding="utf-8"))
    data["research_line"] = "astro-survey-photometry"
    project.write_text(json.dumps(data), encoding="utf-8")
    assert owner.applies(settings, campaign)


# --------------------------------------------------------------------------- seats


def test_continuing_seat_resumes_the_same_session_without_any_replan(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _seat_packet(db, paths, seat["task_id"], {"status": "continuing"}, session="owner-s1",
                 artifact=True)
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    nxt = _latest(db, topic["campaign_id"])
    assert nxt["task_type"] == OWNER_TASK_TYPE
    assert nxt["session_mode"] == "resume" and nxt["agent_session_id"] == "owner-s1"
    assert nxt["runner"] == seat["runner"] and nxt["parent_task_id"] == seat["task_id"]
    assert nxt["routing_reason"] == owner.ROUTING_CONTINUE
    assert not {t["task_type"] for t in _tasks(db, topic["campaign_id"])} & LEGACY_TYPES
    stored = json.loads(Path(db.task(seat["task_id"])["result_path"]).read_text())
    assert stored["owner_packet"]["status"] == "continuing"
    assert validate_result_bundle(stored).valid


def test_awaiting_remote_parks_the_seat_and_wakes_the_same_session(tmp_path, monkeypatch):
    queue = tmp_path / "remote-queue"
    (queue / "jobs" / JOB).mkdir(parents=True)
    monkeypatch.setenv("OPENLABS_REMOTE_QUEUE", str(queue))
    (queue / "jobs" / JOB / "request.json").write_text(json.dumps(
        {"job_id": JOB, "resources": {"cpu_threads": 2, "wall_seconds": 3600}}))
    (queue / "jobs" / JOB / "status.json").write_text(json.dumps(
        {"job_id": JOB, "state": "running", "updated_at": "2026-11-14T00:00:00Z"}))
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _seat_packet(db, paths, seat["task_id"], {"status": "awaiting_remote", "job_ids": [JOB],
                                              "resume_note": "Fit the posterior."},
                 session="owner-s1")
    _tick(paths, settings, monkeypatch)
    parked = _latest(db, topic["campaign_id"])
    assert parked["task_type"] == OWNER_TASK_TYPE and parked["status"] == "awaiting_remote"
    assert parked["session_mode"] == "resume" and parked["agent_session_id"] == "owner-s1"
    assert parked["runner"] == seat["runner"]
    assert db.task(seat["task_id"])["status"] == "yielded"
    (queue / "jobs" / JOB / "status.json").write_text(json.dumps(
        {"job_id": JOB, "state": "succeeded", "updated_at": "2026-11-14T01:00:00Z"}))
    _tick(paths, settings, monkeypatch)
    woken = db.task(parked["task_id"])
    assert woken["status"] in {"queued", "leased"}
    assert "Fit the posterior." in woken["objective"] and JOB in woken["objective"]
    assert remote_wait.default_queue_root() == queue


def test_no_progress_seats_trip_the_direction_decision(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _owner_program(
        tmp_path, monkeypatch, owner_settings=OwnerSettings(no_progress_seats=2)
    )
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _seat_packet(db, paths, seat["task_id"], {"status": "continuing"}, session="s1")
    _tick(paths, settings, monkeypatch)
    assert not _direction_tasks(db)
    second = _lease(paths, settings, monkeypatch, db, _latest(db, topic["campaign_id"])["task_id"])
    _seat_packet(db, paths, second["task_id"], {"status": "continuing"}, session="s1")
    _tick(paths, settings, monkeypatch)
    decisions = _direction_tasks(db)
    assert len(decisions) == 1
    packet = json.loads(Path(decisions[0]["input_path"]).read_text(encoding="utf-8"))
    assert packet["trigger"]["reason"] == owner.TRIGGER_NO_PROGRESS
    # Cross-family: the owner ran on Claude, the decision may not.
    assert decisions[0]["exclude_provider"] == RUNNERS["lead_claude"].provider
    # No seat while the decision is pending.
    assert _latest(db, topic["campaign_id"])["task_id"] == second["task_id"]
    reason = packet["reasons_to_answer"][0]
    report = _decide(paths, settings, monkeypatch, db, _analysis_decision(reason))
    executed = db.task(report.program["direction_decisions"][-1]["executed_task_id"])
    assert executed["task_type"] == OWNER_TASK_TYPE
    assert executed["routing_reason"] == "direction_targeted_analysis"
    assert executed["session_mode"] == "resume" and executed["agent_session_id"] == "s1"
    assert "External cohort validation on eICU" in executed["objective"]
    assert owner.owner_state(db, topic["campaign_id"])["no_progress_streak"] == 0


def test_ready_for_review_goes_to_another_family_and_comments_return_to_the_owner(
    tmp_path, monkeypatch
):
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _seat_packet(db, paths, seat["task_id"], {
        "status": "ready_for_review", "paper_id": "20261114-ai-owner",
        "primary_endpoint_verdict": "met"}, session="s1", artifact=True)
    _tick(paths, settings, monkeypatch)
    review = _latest(db, topic["campaign_id"])
    assert review["task_type"] == "paper_review" and review["parent_task_id"] == seat["task_id"]
    assert "20261114-ai-owner" in review["objective"]
    assert topic["preregistration_sha256"] in review["objective"]
    assert _topic(paths, settings, topic["topic_id"])["status"] == "in_review"
    review = _lease(paths, settings, monkeypatch, db, review["task_id"])
    assert RUNNERS[review["runner"]].provider != RUNNERS[seat["runner"]].provider
    _finish(db, paths, review["task_id"], supported=False, extra={
        "review_outcome": _outcome(next_action="text_revision"),
        "next_actions": [{"objective": "Tighten the abstract.", "agent_role": "writer",
                          "session_mode": "resume", "handoff_kind": "text_revision"}]})
    _tick(paths, settings, monkeypatch)
    back = _latest(db, topic["campaign_id"])
    assert back["task_type"] == OWNER_TASK_TYPE and back["routing_reason"] == owner.ROUTING_REVIEWED
    assert back["session_mode"] == "resume" and back["agent_session_id"] == "s1"
    assert "Tighten the abstract." in back["objective"]
    assert not {t["task_type"] for t in _tasks(db, topic["campaign_id"])} & LEGACY_TYPES
    # Second round passes: the topic is ready and its campaign pauses.
    back = _lease(paths, settings, monkeypatch, db, back["task_id"])
    _seat_packet(db, paths, back["task_id"], {
        "status": "ready_for_review", "paper_id": "20261114-ai-owner",
        "primary_endpoint_verdict": "met"}, session="s1", artifact=True)
    _tick(paths, settings, monkeypatch)
    second = _lease(paths, settings, monkeypatch, db, _latest(db, topic["campaign_id"])["task_id"])
    assert second["task_type"] == "paper_review"
    _finish(db, paths, second["task_id"], extra={
        "paper_candidate": True, "review_outcome": _outcome(status="ready")})
    _tick(paths, settings, monkeypatch)
    assert _topic(paths, settings, topic["topic_id"])["status"] == "ready_queue"
    assert db.campaign(topic["campaign_id"])["status"] == "production_paused"


def test_ready_for_review_needs_an_endpoint_verdict(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _seat_packet(db, paths, seat["task_id"], {"status": "ready_for_review",
                                              "primary_endpoint_verdict": "pending"},
                 session="s1")
    _tick(paths, settings, monkeypatch)
    nxt = _latest(db, topic["campaign_id"])
    assert nxt["task_type"] == OWNER_TASK_TYPE and "primary_endpoint_verdict" in nxt["objective"]


def test_frozen_packet_freezes_with_the_ledger_hash(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _seat_packet(db, paths, seat["task_id"], {
        "status": "frozen", "freeze_reason_class": "feasibility_precheck_failed",
        "reason": "The control target was not reproduced within its uncertainties."},
        session="s1", artifact=True)
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    frozen = _topic(paths, settings, topic["topic_id"])
    assert frozen["status"] == "frozen"
    stored = json.loads(Path(db.task(seat["task_id"])["result_path"]).read_text())
    assert stored["preregistration_sha256"] == topic["preregistration_sha256"]
    assert stored["primary_endpoint_verdict"] == "pending"  # unstated: never evaluated


def test_failed_gate_returns_to_the_owner_not_to_a_replan(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    # A wrong hash is a real integrity failure: refused, then back to the owner.
    _seat_packet(db, paths, seat["task_id"], {"status": "frozen", "reason": "x",
                                              "preregistration_sha256": "f" * 64}, session="s1")
    _tick(paths, settings, monkeypatch)
    assert db.task(seat["task_id"])["status"] == "needs_replan"
    nxt = _latest(db, topic["campaign_id"])
    assert nxt["task_type"] == OWNER_TASK_TYPE and nxt["routing_reason"] == owner.ROUTING_RETRY
    assert _topic(paths, settings, topic["topic_id"])["status"] == "active"


# --------------------------------------------------------------------------- owners and quota


def test_fable_owns_at_most_one_topic_by_default(tmp_path, monkeypatch):
    paths, db, settings, topics = _owner_program(tmp_path, monkeypatch, cards=2)
    runners = [_latest(db, t["campaign_id"])["runner"] for t in topics]
    assert runners == ["lead_claude", "worker_claude"]


def test_blocked_owner_moves_to_the_next_runner_after_the_threshold(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _seat_packet(db, paths, seat["task_id"], {"status": "continuing"}, session="s1",
                 artifact=True)
    _tick(paths, replace(settings, launch_jobs=False), monkeypatch)
    queued = _latest(db, topic["campaign_id"])
    assert queued["status"] == "queued" and queued["runner"] == "lead_claude"
    blocked = {"lead_claude"}
    monkeypatch.setattr(owner, "runner_usable",
                        lambda _settings, _router, name: name not in blocked)
    now = datetime.now(UTC)
    report = engine_report()
    assert owner.supervise(db, settings, report, object(), now=now) == []
    assert owner.supervise(db, settings, report, object(), now=now + timedelta(minutes=90)) == []
    moves = owner.supervise(db, settings, report, object(), now=now + timedelta(minutes=121))
    assert moves and moves[0]["to_runner"] == "worker_claude" and moves[0]["keep_session"]
    moved = db.task(queued["task_id"])
    assert moved["runner"] == "worker_claude" and moved["agent_session_id"] == "s1"
    blocked.add("worker_claude")
    later = now + timedelta(minutes=121)
    owner.supervise(db, settings, report, object(), now=later)
    owner.supervise(db, settings, report, object(), now=later + timedelta(minutes=121))
    moved = db.task(queued["task_id"])
    assert moved["runner"] == "lead_gpt"
    assert moved["session_mode"] == "fresh" and moved["agent_session_id"] is None


def test_owner_seats_are_ordinary_work_without_fables_review_ceiling() -> None:
    from openlabs.config import FactorySettings, ProgramSettings, RoutingSettings

    settings = FactorySettings(program=ProgramSettings(enabled=True))
    klass = budget_control.task_class(settings, {"task_type": OWNER_TASK_TYPE,
                                                 "agent_role": "researcher"})
    assert klass == budget_control.OWNER_CLASS
    routing = RoutingSettings()
    assert budget_control.class_ceiling(routing, klass) == routing.ordinary_ceiling
    assert budget_control.protection_limit(
        routing, klass=klass, protected_window=True, protected_runner=True
    ) == pytest.approx(1 - routing.lead_decision_reserve)
    assert budget_control.protection_limit(
        routing, klass="ordinary", protected_window=True, protected_runner=True
    ) == routing.lead_review_ceiling


# --------------------------------------------------------------------------- conversion


def test_in_flight_topic_converts_at_its_next_successor(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _program(tmp_path, monkeypatch)
    legacy = _latest(db, topic["campaign_id"])
    assert legacy["task_type"] == "candidate_maturation"
    legacy = _lease(paths, settings, monkeypatch, db, legacy["task_id"])
    settings = replace(settings, program=replace(settings.program, owner_mode="all"))
    _finish(db, paths, legacy["task_id"], session="legacy-1", extra={
        "next_actions": [{"objective": "Run the decisive analysis.", "agent_role": "researcher",
                          "session_mode": "resume"}]})
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    seat = _latest(db, topic["campaign_id"])
    assert seat["task_type"] == OWNER_TASK_TYPE and seat["routing_reason"] == owner.ROUTING_CONVERTED
    assert seat["session_mode"] == "fresh" and seat["parent_task_id"] == legacy["task_id"]
    assert seat["input_path"] == db.task(legacy["task_id"])["result_path"]


def test_in_flight_yield_parks_an_owner_seat_with_its_job_ids(tmp_path, monkeypatch):
    queue = tmp_path / "remote-queue"
    (queue / "jobs" / JOB).mkdir(parents=True)
    monkeypatch.setenv("OPENLABS_REMOTE_QUEUE", str(queue))
    (queue / "jobs" / JOB / "status.json").write_text(json.dumps(
        {"job_id": JOB, "state": "running", "updated_at": "2026-11-14T00:00:00Z"}))
    paths, db, settings, (topic,) = _program(tmp_path, monkeypatch)
    legacy = _lease(paths, settings, monkeypatch, db, _latest(db, topic["campaign_id"])["task_id"])
    settings = replace(settings, program=replace(settings.program, owner_mode="all"))
    _finish(db, paths, legacy["task_id"], session="legacy-1", extra={
        "status": "awaiting_remote",
        "awaiting_remote": {"job_ids": [JOB], "resume_objective": "Collect the fits."}})
    _tick(paths, settings, monkeypatch)
    parked = _latest(db, topic["campaign_id"])
    assert parked["task_type"] == OWNER_TASK_TYPE and parked["status"] == "awaiting_remote"
    assert parked["session_mode"] == "fresh" and JOB in parked["objective"]


# --------------------------------------------------------------------------- packet and brief


def test_minimal_packet_becomes_a_valid_bundle_with_staged_hashes(tmp_path) -> None:
    staging = tmp_path / "artifact-stage"
    (staging / "chains").mkdir(parents=True)
    (staging / "chains" / "posterior.npz").write_bytes(b"\x00\x01")
    (staging / "fit.py").write_text("print(1)\n")  # needs a replay closure: not auto-declared
    expected = {"task_id": "t1", "campaign_id": "c1", "lab_id": "ai", "domain": "ai"}
    bundle = owner.normalize_packet({"status": "continuing"}, expected=expected,
                                    staging_root=staging)
    assert validate_result_bundle(bundle).valid, validate_result_bundle(bundle).errors
    assert [a["sha256"] for a in bundle["artifacts"]] == [
        sha256_file(staging / "chains" / "posterior.npz")]
    assert bundle["status"] == "completed" and bundle["paper_candidate"] is False
    blocked = owner.normalize_packet({"status": "blocked_human", "reason": "MAST is down"},
                                     expected=expected)
    assert blocked["status"] == "needs_human" and validate_result_bundle(blocked).valid
    waiting = owner.normalize_packet({"status": "awaiting_remote", "job_ids": ["nope"]},
                                     expected=expected)
    assert waiting["status"] == "completed"
    assert waiting["owner_packet"]["status"] == "continuing"
    full = {"schema_version": RESULT_SCHEMA, **expected, "status": "needs_replan",
            "summary": "runner failure", "artifacts": [], "claims": [],
            "next_actions": ["retry"]}
    assert owner.normalize_packet(full, expected=expected) == full
    again = owner.normalize_packet(bundle, expected=expected)
    assert again == bundle


def _spec(tmp_path, task_id: str = "owner:1") -> dict:
    staged = tmp_path / "attempt" / "workspaces" / "ai" / "c1"
    staged.mkdir(parents=True)
    return {
        "task_id": task_id, "attempt_id": "a1", "campaign_id": "c1", "objective": "Start.",
        "input_path": "/x/result.json", "output_path": str(staged / "results" / "r.json"),
        "transaction": {"staged_campaign_workspace": str(staged),
                        "artifact_staging_root": str(tmp_path / "attempt" / "artifact-stage"),
                        "canonical_campaign_workspace": "/data/workspaces/ai/c1"},
    }


def test_brief_is_short_has_the_four_parts_and_forces_no_skill(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    seat = _latest(db, topic["campaign_id"])
    campaign = db.campaign(topic["campaign_id"])
    spec = _spec(tmp_path, seat["task_id"])
    block = owner.spec_block(paths, settings, task=seat, spec=spec, campaign=campaign,
                             wall_seconds=14_400, db=db)
    request = block["request"]
    body = request.split("\n---\n")[0]
    # About 4 KB in production (shorter roots); the test roots are long tmp paths.
    assert len(body.encode("utf-8")) <= 4_400, len(body.encode("utf-8"))
    for heading in ("## Goal", "## Resources", "## Tools", "## Hard limits", "## Ending a seat"):
        assert heading in request
    assert "Invoke" not in request and "Skill tool" not in request
    assert topic["preregistration_sha256"] in request
    assert "codex exec -m gpt-6.1-sol" in request and "Agent tool" in request
    assert "program utilization" in request and "download-submit" in request
    assert block["claude_subagent_model"] == "claude-opus-5-5"
    assert (Path(spec["transaction"]["staged_campaign_workspace"]) / owner.BRIEF_NAME).is_file()
    # A Codex owner gets its native sub-agents, explicitly authorized.
    gpt = dict(seat, runner="lead_gpt")
    gpt_block = owner.spec_block(paths, settings, task=gpt, spec=_spec(tmp_path / "g"),
                                 campaign=campaign, wall_seconds=600, db=db)
    assert "spawn_agent" in gpt_block["request"] and "explicitly authorized" in gpt_block["request"]
    # A resumed seat gets only the short next-seat message.
    resumed = dict(seat, session_mode="resume", agent_session_id="s1")
    short = owner.spec_block(paths, settings, task=resumed, spec=_spec(tmp_path / "r"),
                             campaign=campaign, wall_seconds=600, db=db)
    assert "## Hard limits" not in short["request"] and len(short["request"]) < 1_500


def _lab_runner():
    path = CODE_ROOT / "packages" / "research-core" / "lab_runner.py"
    spec = importlib.util.spec_from_file_location("owner_lab_runner", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_lab_runner_sends_the_brief_and_the_subagent_default(tmp_path) -> None:
    runner = _lab_runner()
    task = {"task_type": OWNER_TASK_TYPE, "owner": {"request": "BRIEF", "claude_subagent_model":
                                                     "claude-opus-5-5"},
            "lab_manifest": str(CODE_ROOT / "labs" / "ai" / "lab.json"),
            "agent": {"role": "researcher", "session_mode": "fresh"}}
    assert runner._agent_request(task, {"domain": "ai"}, tmp_path / "r.json", "claude") == "BRIEF"
    env = runner._agent_environment(task, "claude")
    assert env["CLAUDE_CODE_SUBAGENT_MODEL"] == "claude-opus-5-5"
    assert runner._agent_environment(task, "codex") is None
    assert runner._agent_environment({"task_type": "research"}, "claude") is None
    assert runner.claude_allowed_tools(allow_subagents=True)[-2:] == ("Task", "Agent")


def test_stop_hook_completes_the_packet_and_passes(tmp_path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    result = workspace / "results" / "r.json"
    atomic_write_json(result, {"status": "continuing", "summary": "Fitted two targets."})
    expected = {"schema_version": RESULT_SCHEMA, "task_id": "t1", "campaign_id": "c1",
                "lab_id": "ai", "domain": "ai"}
    context = {"result_path": str(result), "agent_workspace": str(workspace),
               "expected_result": expected, "protocol_binding": None,
               "owner": {"artifact_staging_root": None, "preregistration_sha256": None,
                         "work_log": str(workspace / owner.WORK_LOG_NAME), "deadline": "x"}}
    assert codex_hook._stop_gate_problems(context) == []
    stored = json.loads(result.read_text())
    assert stored["schema_version"] == RESULT_SCHEMA and stored["owner_packet"]["status"] == (
        "continuing")
    message = codex_hook._session_context(context, "claude")["hookSpecificOutput"]
    assert "owner seat" in message["additionalContext"] and "Invoke" not in message[
        "additionalContext"]


def test_workspace_digest_ignores_the_log_and_outputs(tmp_path) -> None:
    root = tmp_path / "c"
    (root / "results" / "t" / "attempts" / "a").mkdir(parents=True)
    (root / "fits").mkdir()
    (root / "fits" / "x.json").write_text("1")
    first = owner.workspace_digest(root)
    (root / owner.WORK_LOG_NAME).write_text("log")
    (root / "results" / "t" / "attempts" / "a" / "result.json").write_text("{}")
    assert owner.workspace_digest(root) == first
    (root / "fits" / "x.json").write_text("2")
    assert owner.workspace_digest(root) != first


def test_ledger_unchanged_by_owner_mode_off(tmp_path, monkeypatch) -> None:
    paths, db, settings, (topic,) = _program(tmp_path, monkeypatch)
    ledger = open_topic_ledger(paths, settings.program).read()
    assert all(t.get("status") != "frozen" for t in ledger["topics"])


def test_legacy_replan_of_an_owner_topic_becomes_an_owner_seat(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _program(tmp_path, monkeypatch)
    legacy = _lease(paths, settings, monkeypatch, db, _latest(db, topic["campaign_id"])["task_id"])
    settings = replace(settings, program=replace(settings.program, owner_mode="all"))
    _finish(db, paths, legacy["task_id"], session="legacy-1", extra={
        "status": "needs_replan", "next_actions": ["Choose another target."]})
    _tick(paths, settings, monkeypatch)
    types = [t["task_type"] for t in _tasks(db, topic["campaign_id"])]
    assert types == ["candidate_maturation", OWNER_TASK_TYPE]


def test_fresh_successor_seat_gets_a_handover_note(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _seat_packet(db, paths, seat["task_id"], {"status": "continuing"}, session="s1",
                 artifact=True)
    _tick(paths, replace(settings, launch_jobs=False), monkeypatch)
    queued = _latest(db, topic["campaign_id"])
    db.reassign_queued_task(queued["task_id"], runner="lead_gpt", fresh_session=True,
                            event="owner_runner_switched")
    fresh = db.task(queued["task_id"])
    block = owner.spec_block(paths, settings, task=fresh, spec=_spec(tmp_path, fresh["task_id"]),
                             campaign=db.campaign(topic["campaign_id"]), wall_seconds=600, db=db)
    assert "A previous owner session (lead_claude" in block["request"]
    assert owner.WORK_LOG_NAME in block["request"] and "spawn_agent" in block["request"]
