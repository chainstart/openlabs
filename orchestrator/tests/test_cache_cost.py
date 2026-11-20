"""Cache-cost measures of 2026-11-20: short continuations, same-model sessions, context size."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from openlabs import budget as budget_control
from openlabs import owner
from openlabs.config import OwnerSettings, RunnerSpec, load_program_settings
from openlabs.contracts import atomic_write_json
from openlabs.db import FactoryDB
from test_owner_mode import (
    _first_seat,
    _latest,
    _owner_program,
    _seat_packet,
    engine_report,
)
from test_research_program_flow import _tick

SHORT = OwnerSettings(short_resume_context_tokens=100_000, short_resume_gap_minutes=10,
                      short_resume_max_tokens_read=1_000_000)


def _finish(paths, db, task_id: str, *, context: int | None, read: int = 50_000,
            session: str = "s1") -> None:
    """A continuing seat whose runtime reports its final context and tokens read."""

    _seat_packet(db, paths, task_id, {"status": "continuing"}, session=session, artifact=True)
    attempt_id = str(db.task(task_id)["current_attempt_id"])
    receipt_path = paths.result_inbox / f"{attempt_id}.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["runtime"].update({"adapter": "claude", "input_tokens": read})
    if context is not None:
        receipt["runtime"]["last_context_tokens"] = context
    atomic_write_json(receipt_path, receipt)


def _next_seat(tmp_path, monkeypatch, owner_settings, *, context, read=50_000):
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch,
                                                   owner_settings=owner_settings)
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _finish(paths, db, seat["task_id"], context=context, read=read)
    _tick(paths, replace(settings, launch_jobs=False), monkeypatch)
    return paths, db, settings, seat, _latest(db, topic["campaign_id"])


def test_config_defaults_keep_short_resume_off_and_parse_overrides():
    defaults = OwnerSettings()
    assert defaults.short_resume_context_tokens == 0
    assert defaults.session_max_seats == 1
    parsed = load_program_settings({"owner": {"short_resume_context_tokens": 100_000,
                                              "short_resume_gap_minutes": 5,
                                              "short_resume_max_tokens_read": 800_000}})
    assert parsed.owner.short_resume_context_tokens == 100_000
    assert parsed.owner.short_resume_gap_minutes == 5
    assert parsed.owner.short_resume_max_tokens_read == 800_000


def test_short_resume_off_by_default_every_seat_is_fresh(tmp_path, monkeypatch):
    _paths, _db, _settings, _seat, nxt = _next_seat(tmp_path, monkeypatch, OwnerSettings(),
                                                    context=20_000)
    assert nxt["session_mode"] == "fresh" and nxt["agent_session_id"] is None


def test_small_recent_same_model_seat_resumes_its_session(tmp_path, monkeypatch):
    _paths, db, _settings, seat, nxt = _next_seat(tmp_path, monkeypatch, SHORT,
                                                  context=40_000)
    assert nxt["parent_task_id"] == seat["task_id"]
    assert nxt["session_mode"] == "resume" and nxt["agent_session_id"] == "s1"
    assert db.meta_get(owner.SHORT_RESUME_META_PREFIX + nxt["task_id"])


def test_large_context_or_unknown_context_starts_fresh(tmp_path, monkeypatch):
    _p, _d, _s, _seat, big = _next_seat(tmp_path / "big", monkeypatch, SHORT,
                                        context=150_000)
    assert big["session_mode"] == "fresh"
    _p, _d, _s, _seat, unknown = _next_seat(tmp_path / "unknown", monkeypatch, SHORT,
                                            context=None)
    assert unknown["session_mode"] == "fresh"


def test_session_read_cap_stops_the_snowball(tmp_path, monkeypatch):
    _p, _d, _s, _seat, nxt = _next_seat(tmp_path, monkeypatch, SHORT, context=40_000,
                                        read=1_200_000)
    assert nxt["session_mode"] == "fresh"


def test_gap_and_model_rules_of_short_resume(tmp_path, monkeypatch):
    paths, db, settings, seat, nxt = _next_seat(tmp_path, monkeypatch, SHORT, context=40_000)
    source = db.task(seat["task_id"])
    chain = owner.session_tasks(db, source)
    later = datetime.now(UTC) + timedelta(minutes=30)
    assert owner.short_resume(db, settings, source, chain, now=later) == (
        False, "short_resume:gap")
    # The same model is required: a runner of another model in the config drops it.
    other = dict(settings.runners)
    runner = str(source["runner"])
    other[runner] = replace(other[runner], model="another-model")
    assert owner._seat_model(replace(settings, runners=other), source) == "another-model"


def test_queued_short_resume_turns_fresh_after_the_gap(tmp_path, monkeypatch):
    _paths, db, settings, _seat, nxt = _next_seat(tmp_path, monkeypatch, SHORT,
                                                  context=40_000)
    assert nxt["status"] == "queued" and nxt["session_mode"] == "resume"
    report = engine_report()
    assert owner.expire_short_resumes(db, settings, report, now=datetime.now(UTC)) == []
    expired = owner.expire_short_resumes(db, settings, report,
                                         now=datetime.now(UTC) + timedelta(minutes=11))
    assert expired == [nxt["task_id"]]
    task = db.task(nxt["task_id"])
    assert task["session_mode"] == "fresh" and task["agent_session_id"] is None
    assert db.meta_get(owner.SHORT_RESUME_META_PREFIX + nxt["task_id"]) is None


def test_router_drops_the_session_when_the_model_changes(tmp_path):
    from openlabs.config import FactorySettings

    runners = {
        "lead_claude": RunnerSpec("lead_claude", "anthropic", "lead", "claude-fable-5-2"),
        "worker_claude": RunnerSpec("worker_claude", "anthropic", "worker", "claude-opus-5-5"),
        "twin_claude": RunnerSpec("twin_claude", "anthropic", "worker", "claude-opus-5-5"),
    }
    settings = replace(FactorySettings(), runners=runners)
    db = FactoryDB(tmp_path / "f.sqlite")
    db.initialize()
    router = budget_control.QuotaRouter(db=db, settings=settings, now=datetime.now(UTC))
    task = {"task_id": "t1", "session_mode": "resume", "agent_session_id": "s1",
            "runner": "worker_claude", "session_source_task_id": None}
    assert router._session_model_changed(task, "lead_claude")
    assert not router._session_model_changed(task, "twin_claude")
    assert not router._session_model_changed(task, "worker_claude")
    assert not router._session_model_changed(dict(task, session_mode="fresh"), "lead_claude")


def test_claim_applies_a_fresh_session_decision(tmp_path):
    db = FactoryDB(tmp_path / "f.sqlite")
    db.initialize()
    db.register_campaign("c1", domain="ai", title="C1")
    db.enqueue_task(task_id="t1", campaign_id="c1", domain="ai", task_type="smoke",
                    objective="x", runner="worker_claude", session_mode="fresh")
    with db.connect() as connection:
        connection.execute("UPDATE tasks SET session_mode='resume', agent_session_id='s1' "
                           "WHERE task_id='t1'")
    claimed = db.claim_next_task(
        owner="test", lease_seconds=60,
        route=lambda _task, _active: {"runner": "lead_claude", "fresh_session": True,
                                      "session_dropped": "model_changed"})
    assert claimed and claimed["runner"] == "lead_claude"
    assert claimed["session_mode"] == "fresh" and claimed["agent_session_id"] is None


def _lab_runner():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "packages" / "research-core" / "lab_runner.py"
    spec = importlib.util.spec_from_file_location("lab_runner_cache_cost", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_runtime_records_the_final_context_size(tmp_path):
    runner = _lab_runner()
    stream = tmp_path / "claude.log"
    usage = {"input_tokens": 3, "cache_read_input_tokens": 40_000,
             "cache_creation_input_tokens": 2_000, "output_tokens": 50}
    stream.write_text("\n".join(json.dumps(item) for item in [
        {"type": "assistant", "parent_tool_use_id": None,
         "message": {"usage": dict(usage, cache_read_input_tokens=10_000)}},
        {"type": "assistant", "parent_tool_use_id": None, "message": {"usage": usage}},
        # A sub-agent's request is another conversation.
        {"type": "assistant", "parent_tool_use_id": "toolu_1",
         "message": {"usage": dict(usage, cache_read_input_tokens=900_000)}},
        {"type": "result", "session_id": "s", "usage": usage},
    ]) + "\n")
    assert runner._jsonl_runtime(stream)["last_context_tokens"] == 42_003
    session = tmp_path / "rollout-x-abc.jsonl"
    session.write_text("\n".join(json.dumps(item) for item in [
        {"type": "event_msg", "payload": {"type": "token_count", "info": {
            "last_token_usage": {"input_tokens": 30_000, "cached_input_tokens": 29_000}}}},
        {"type": "event_msg", "payload": {"type": "token_count", "info": {
            "last_token_usage": {"input_tokens": 64_000, "cached_input_tokens": 60_000}}}},
        {"type": "event_msg", "payload": {"type": "token_count", "info": None}},
    ]) + "\n")
    assert runner.codex_session_last_context(session) == 64_000
