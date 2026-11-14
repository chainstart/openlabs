"""Quota-aware routing: provider backoff, headroom, reserves, Fable protection, escalation."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from openlabs import budget as budget_control
from openlabs import engine
from openlabs.config import (
    BudgetSettings,
    FactorySettings,
    RoutingSettings,
    RunnerSpec,
    WorkspacePaths,
    load_settings,
)
from openlabs.contracts import RECEIPT_SCHEMA, RESULT_SCHEMA, atomic_write_json, sha256_file
from openlabs.db import FactoryDB
from openlabs.engine import TickReport, ingest_results

NOW = datetime(2026, 11, 11, 6, 0, 0, tzinfo=UTC)
GPT, CLAUDE = "openai-codex", "anthropic"
RUNNERS = {
    "lead_gpt": RunnerSpec("lead_gpt", GPT, "lead", "gpt-6-astra"),
    "lead_claude": RunnerSpec(
        "lead_claude", CLAUDE, "lead", "claude-fable-5-2",
        windows=("seven_day_overage_included",), protected=True,
    ),
    "worker_gpt": RunnerSpec("worker_gpt", GPT, "worker", "gpt-6.1-sol"),
    "worker_claude": RunnerSpec("worker_claude", CLAUDE, "worker", "claude-opus-5-5"),
    "light_gpt": RunnerSpec("light_gpt", GPT, "light", "gpt-light"),
    "light_claude": RunnerSpec("light_claude", CLAUDE, "light", "claude-haiku-5-5"),
}
WINDOW_SHAPE = {
    # name: (window_minutes, time to reset) -- not overspeed at moderate usage.
    "five_hour": (300, timedelta(hours=1)),
    "seven_day": (10080, timedelta(days=2)),
}


def _settings(**routing) -> FactorySettings:
    return FactorySettings(
        max_worker_processes=8,
        retry_backoff_seconds=0,
        budget=BudgetSettings(max_parallel_agents=4),
        runners=dict(RUNNERS),
        routing=replace(RoutingSettings(), **routing),
    )


def _paths(tmp_path: Path) -> WorkspacePaths:
    paths = WorkspacePaths(
        workspace=tmp_path,
        code=tmp_path / "openlabs",
        data=tmp_path / "data",
        artifacts=tmp_path / "artifacts",
        database=tmp_path / "database",
        database_file=tmp_path / "database" / "live" / "factory.sqlite",
    )
    paths.ensure_runtime_directories()
    return paths


def _setup(tmp_path: Path) -> tuple[WorkspacePaths, FactoryDB]:
    paths = _paths(tmp_path)
    db = FactoryDB(paths.database_file)
    db.initialize()
    return paths, db


def _snapshot(provider: str, model: str, used: dict[str, float], *,
              observed: datetime = NOW) -> dict:
    windows = []
    for name, fraction in used.items():
        minutes, until = WINDOW_SHAPE.get(name, (10080, timedelta(days=2)))
        windows.append(
            {"name": name, "used_fraction": fraction, "window_minutes": minutes,
             "resets_at": budget_control._iso(observed + until)}
        )
    return {"provider": provider, "observed_at": budget_control._iso(observed),
            "model": model, "windows": windows}


def _record(db, settings, runner: str, used: dict[str, float], **kwargs) -> None:
    spec = RUNNERS[runner]
    budget_control.record_quota_snapshot(
        db, settings, _snapshot(spec.provider, spec.model, used, **kwargs), runner=runner
    )


def _enqueue(db: FactoryDB, task_id: str, campaign_id: str, *, runner: str | None = "balanced",
             task_type: str = "research", priority: int = 0, **kwargs) -> None:
    if db.campaign(campaign_id) is None:
        db.register_campaign(campaign_id, domain="math", title=campaign_id)
    db.enqueue_task(
        task_id=task_id, campaign_id=campaign_id, domain="math", task_type=task_type,
        objective="Bounded step.", runner=runner, priority=priority, **kwargs,
    )


def _claim(db: FactoryDB, settings: FactorySettings, *, now: datetime = NOW, rank: bool = False):
    router = budget_control.QuotaRouter.build(db, settings, now=now)
    task = db.claim_next_task(
        owner="test", lease_seconds=600, route=router.route,
        rank=router.rank if rank else None,
    )
    return task, router


def _routed_events(db: FactoryDB, task_id: str) -> list[dict]:
    return [e["payload"] for e in db.events() if e["event_type"] == "task_routed"
            and e["entity_id"] == task_id]


@pytest.fixture
def clock(monkeypatch):
    state = {"now": NOW}
    monkeypatch.setattr(budget_control, "current_time", lambda: state["now"])
    return state


# ---------------------------------------------------------------- readings


def test_snapshot_is_stored_per_provider_through_ingest_and_survives_restart(
    tmp_path, clock
) -> None:
    paths, db = _setup(tmp_path)
    settings = replace(_settings(), auto_continue=False)
    _enqueue(db, "t", "c", runner="worker_claude")
    attempt_id, output = _start(db, paths, "t")
    snapshot = _snapshot(CLAUDE, "claude-opus-5-5", {"five_hour": 0.41, "seven_day": 0.38})
    snapshot["provider"] = "anthropic-raw-name"  # the runner's configured provider wins
    _deliver(paths, db, "t", attempt_id, output, status="failed",
             extra={"quota_snapshot": snapshot, "input_tokens": 10, "adapter": "claude"})
    report = TickReport()
    ingest_results(db, paths, settings, report)
    assert report.errors == []

    reopened = FactoryDB(paths.database_file)
    reopened.initialize()
    readings = budget_control.quota_readings(reopened)
    assert set(readings) == {CLAUDE}
    assert readings[CLAUDE]["five_hour"].used_fraction == 0.41
    assert readings[CLAUDE]["seven_day"].task_id == "t"
    runtime = reopened.task_attempts("t")[-1]["runtime"]
    assert runtime["execution"] == {
        "runner": "worker_claude", "provider": CLAUDE, "tier": "worker",
        "model": "claude-opus-5-5",
    }


def test_cheap_model_reading_does_not_replace_fable_window(tmp_path) -> None:
    _paths_, db = _setup(tmp_path)
    settings = _settings()
    _record(db, settings, "lead_claude",
            {"five_hour": 0.41, "seven_day": 0.38, "seven_day_overage_included": 0.61})
    _record(db, settings, "light_claude", {"five_hour": 0.44, "seven_day": 0.39},
            observed=NOW + timedelta(hours=1))
    # An older reading never wins either.
    _record(db, settings, "worker_claude", {"five_hour": 0.05},
            observed=NOW - timedelta(hours=1))
    readings = budget_control.quota_readings(db)[CLAUDE]
    assert readings["five_hour"].used_fraction == 0.44
    assert readings["five_hour"].model == "claude-haiku-5-5"
    overage = readings["seven_day_overage_included"]
    assert (overage.used_fraction, overage.model) == (0.61, "claude-fable-5-2")
    assert overage.observed_at == NOW


def test_unknown_window_is_stored_and_constrains_availability(tmp_path) -> None:
    _paths_, db = _setup(tmp_path)
    settings = _settings()
    _record(db, settings, "worker_claude", {"seven_day": 0.2, "mystery_window": 0.9})
    router = budget_control.QuotaRouter.build(db, settings, now=NOW)
    state = router.availability(RUNNERS["worker_claude"], "ordinary")
    assert state.state == "unavailable" and state.binding_window == "mystery_window"
    # The Fable-only window does not constrain the other Claude runners.
    _record(db, settings, "lead_claude", {"seven_day_overage_included": 0.99})
    names = budget_control.runner_windows(
        RUNNERS["worker_claude"], RUNNERS, budget_control.quota_readings(db)[CLAUDE]
    )
    assert "seven_day_overage_included" not in names and "mystery_window" in names


# ---------------------------------------------------------------- backoff


def test_runners_of_one_provider_share_backoff_and_legacy_keys_fold_in(tmp_path) -> None:
    _paths_, db = _setup(tmp_path)
    settings = _settings()
    result = budget_control.record_quota_failure(db, settings, runner="worker_claude", now=NOW)
    assert result.provider == CLAUDE
    assert set(budget_control.runner_backoffs(db, now=NOW, settings=settings)) == {CLAUDE}
    blocked = set(budget_control.blocked_runner_names(db, settings, now=NOW))
    assert {"lead_claude", "worker_claude", "light_claude"} <= blocked
    assert not blocked & {"lead_gpt", "worker_gpt", "light_gpt"}
    _enqueue(db, "t", "c", runner="balanced")
    task, _router = _claim(db, settings, now=NOW + timedelta(minutes=1))
    assert task is not None and task["runner"] == "worker_gpt"  # Claude is backing off
    # A second Claude tier hitting the limit does not escalate again.
    echo = budget_control.record_quota_failure(db, settings, runner="lead_claude", now=NOW)
    assert not echo.escalated
    # Previous-release per-runner key: frontier was a Codex command.
    db.update_meta({"provider_backoff_until:frontier": budget_control._iso(NOW + timedelta(hours=1)),
                    "provider_probe:frontier": "1"})
    assert set(budget_control.runner_backoffs(db, now=NOW, settings=settings)) == {CLAUDE, GPT}
    later = NOW + timedelta(hours=2)
    assert GPT in budget_control.probe_limits(db, now=later, settings=settings)
    budget_control.record_healthy_completion(db, settings, runner="worker_gpt", now=later)
    assert "frontier" not in db.meta_items(budget_control.PROBE_PREFIX)


# ---------------------------------------------------------------- selection


def test_family_with_more_headroom_is_selected(tmp_path) -> None:
    _paths_, db = _setup(tmp_path)
    settings = _settings()
    _record(db, settings, "worker_gpt", {"seven_day": 0.2})
    _record(db, settings, "worker_claude", {"five_hour": 0.5, "seven_day": 0.5})
    _enqueue(db, "a", "c1", runner="balanced")
    task, _router = _claim(db, settings)
    assert task["runner"] == "worker_gpt" and task["runner_request"] == "balanced"
    assert _routed_events(db, "a")[0]["provider"] == GPT
    _record(db, settings, "worker_gpt", {"seven_day": 0.7}, observed=NOW + timedelta(minutes=1))
    _enqueue(db, "b", "c2", runner=None)
    task, _router = _claim(db, settings)
    assert task["runner"] == "worker_claude" and task["runner_request"] == ""


def test_pinned_runner_is_not_rerouted(tmp_path) -> None:
    _paths_, db = _setup(tmp_path)
    settings = _settings()
    _record(db, settings, "worker_gpt", {"seven_day": 0.1})
    _record(db, settings, "worker_claude", {"five_hour": 0.6, "seven_day": 0.6})
    _enqueue(db, "p", "c", runner="worker_claude")
    task, _router = _claim(db, settings)
    assert task["runner"] == "worker_claude" and task["runner_request"] is None
    assert _routed_events(db, "p")[0]["pinned"] is True


def test_independence_constraint_is_respected(tmp_path) -> None:
    _paths_, db = _setup(tmp_path)
    settings = _settings()
    _record(db, settings, "lead_gpt", {"seven_day": 0.05})
    _record(db, settings, "lead_claude",
            {"five_hour": 0.3, "seven_day": 0.3, "seven_day_overage_included": 0.3})
    _enqueue(db, "draft", "c", runner="worker_gpt")
    _enqueue(db, "review", "c", runner="frontier", task_type="paper_review",
             parent_task_id="draft", agent_role="reviewer", priority=5)
    task, _router = _claim(db, settings)
    assert task["task_id"] == "review" and task["runner"] == "lead_claude"
    assert _routed_events(db, "review")[0]["excluded_provider"] == GPT
    # An explicit declaration holds for any task class.
    _enqueue(db, "x", "c2", runner="balanced", exclude_provider=GPT)
    task, _router = _claim(db, settings)
    assert task["task_id"] == "x" and task["runner"] == "worker_claude"


def test_resumed_session_stays_with_its_family(tmp_path) -> None:
    _paths_, db = _setup(tmp_path)
    settings = _settings()
    _record(db, settings, "worker_gpt", {"seven_day": 0.05})
    _record(db, settings, "worker_claude", {"five_hour": 0.5, "seven_day": 0.5})
    _enqueue(db, "first", "c", runner="worker_claude")
    with db.connect() as connection:
        connection.execute(
            "UPDATE tasks SET agent_session_id='sess-1', status='succeeded' WHERE task_id='first'"
        )
    _enqueue(db, "next", "c", runner="balanced", parent_task_id="first")
    task, router = _claim(db, settings)
    assert task["task_id"] == "next" and task["agent_session_id"] == "sess-1"
    assert task["runner"] == "worker_claude"
    assert router.decisions["next"]["session_provider"] == CLAUDE


# ---------------------------------------------------------------- reserves


def test_paced_ordinary_ceiling_blocks_ordinary_work_but_not_reviews(tmp_path) -> None:
    _paths_, db = _setup(tmp_path)
    settings = _settings()
    # Two days before the reset: ordinary 0.8 x 0.9125 = 0.73, reviews 0.82
    # (Claude's weekly window also keeps Fable's 25% decision reserve).
    _record(db, settings, "worker_gpt", {"seven_day": 0.78})
    _record(db, settings, "worker_claude", {"five_hour": 0.2, "seven_day": 0.78})
    _enqueue(db, "research", "c1", runner="balanced", priority=9)
    _enqueue(db, "review", "c2", runner="frontier", task_type="paper_review",
             agent_role="reviewer")
    task, router = _claim(db, settings)
    assert task["task_id"] == "review" and task["runner"] == "lead_gpt"
    assert router.deferred["research"]["reason"] == "no_runner_available"
    assert db.task("research")["status"] == "queued"


def test_pace_line_blocks_ordinary_work_before_reviews(tmp_path) -> None:
    def reading(used: float, to_reset: timedelta) -> budget_control.WindowReading:
        return budget_control.WindowReading(
            provider=GPT, name="seven_day", used_fraction=used, window_minutes=10080,
            resets_at=NOW + to_reset, observed_at=NOW,
        )

    # 50% used after 2 of 7 days -> 175% by the reset.
    assert budget_control.projected_fraction_at_reset(
        reading(0.5, timedelta(days=5)), now=NOW) == pytest.approx(1.75)
    assert budget_control.is_overspeed(reading(0.5, timedelta(days=5)), now=NOW)
    assert not budget_control.is_overspeed(reading(0.5, timedelta(days=1)), now=NOW)
    # A burst in the first minutes is not extrapolated over the whole week.
    assert not budget_control.is_overspeed(
        reading(0.05, timedelta(days=7) - timedelta(minutes=1)), now=NOW)

    _paths_, db = _setup(tmp_path)
    settings = _settings()
    db.update_meta({})
    # End of day 2: ordinary may use 0.8 x 0.525 = 0.42, reviews 0.9 x 0.525.
    budget_control.record_quota_snapshot(db, settings, {
        "provider": GPT, "observed_at": budget_control._iso(NOW), "windows": [
            {"name": "seven_day", "used_fraction": 0.45, "window_minutes": 10080,
             "resets_at": budget_control._iso(NOW + timedelta(days=5))}]})
    router = budget_control.QuotaRouter.build(db, settings, now=NOW)
    ordinary = router.availability(RUNNERS["worker_gpt"], "ordinary")
    assert (ordinary.state, ordinary.reason, ordinary.overspeed) == (
        "unavailable", "pace", True)
    assert router.availability(RUNNERS["lead_gpt"], "review").state == "available"
    assert router.provider_summary()[GPT]["overspeed"] is True


def test_stale_reading_allows_dispatch_with_parallelism_one(tmp_path) -> None:
    _paths_, db = _setup(tmp_path)
    settings = _settings()
    _record(db, settings, "worker_gpt", {"seven_day": 0.95})
    _record(db, settings, "worker_claude", {"five_hour": 0.1, "seven_day": 0.1},
            observed=NOW - timedelta(hours=7))
    for index in range(3):
        _enqueue(db, f"t{index}", f"c{index}", runner="balanced")
    first, router = _claim(db, settings)
    assert first["runner"] == "worker_claude"
    assert router.availability(RUNNERS["worker_claude"], "ordinary").state == "unknown"
    second, router = _claim(db, settings)
    assert second is None
    assert set(router.deferred) == {"t1", "t2"}


def test_both_families_unavailable_leaves_task_queued_with_event(
    tmp_path, clock, monkeypatch
) -> None:
    paths, db = _setup(tmp_path)
    settings = replace(_settings(), reserve_cpu_threads=0, reserve_memory_mib=0,
                       reserve_scratch_mib=0, auto_continue=False)
    _record(db, settings, "worker_gpt", {"seven_day": 0.95})
    _record(db, settings, "worker_claude", {"five_hour": 0.2, "seven_day": 0.95})
    _enqueue(db, "t", "c", runner="balanced")
    with db.connect() as connection:
        connection.execute("UPDATE tasks SET cpu_threads=0, memory_mib=0, scratch_mib=0")
    launched: list[str] = []
    monkeypatch.setattr(engine, "_launch_task",
                        lambda _db, _p, _s, task, owner: launched.append(task["task_id"]))
    report = engine.tick(paths, settings)
    report_again = engine.tick(paths, settings)

    assert launched == [] and report.errors == []
    assert db.task("t")["status"] == "queued" and db.task("t")["runner"] == "balanced"
    assert report.routing_deferred[0]["task_id"] == "t"
    assert report_again.routing_deferred
    events = [e for e in db.events() if e["event_type"] == "routing_deferred"]
    assert len(events) == 1 and events[0]["payload"]["reason"] == "no_runner_available"
    payload = report.to_dict()
    assert payload["provider_quota"][GPT]["below_reserve"] is True
    # 95% is past the 90% hard ceiling: no class may run anywhere until the reset.
    assert payload["lead_quota_short"] is True
    assert payload["quota_pause"]["all_paused"] is True
    assert payload["quota_pause"]["resume_at"] == budget_control._iso(NOW + timedelta(days=2))


# ------------------------------------------------------------ Fable protection


FABLE = RUNNERS["lead_claude"]


def _fable(db, settings, overage: float, *, shared: float = 0.2) -> None:
    _record(db, settings, "lead_claude",
            {"five_hour": shared, "seven_day": shared, "seven_day_overage_included": overage})


def test_fable_review_line_and_decision_reserve(tmp_path) -> None:
    _paths_, db = _setup(tmp_path)
    settings = _settings()
    _fable(db, settings, 0.5)
    state = budget_control.lead_availability(db, settings, now=NOW)["lead_claude"]
    assert (state["review"], state["decision"]) == (True, True)
    _fable(db, settings, 0.65)
    state = budget_control.lead_availability(db, settings, now=NOW)["lead_claude"]
    assert (state["review"], state["decision"]) == (False, True)
    _fable(db, settings, 0.8)
    state = budget_control.lead_availability(db, settings, now=NOW)["lead_claude"]
    assert (state["review"], state["decision"]) == (False, True)
    # Decisions stop at the paced hard ceiling too (0.9 x 0.9125 two days out).
    _fable(db, settings, 0.83)
    state = budget_control.lead_availability(db, settings, now=NOW)["lead_claude"]
    assert (state["review"], state["decision"]) == (False, False)
    # Reviews may not spend the decision reserve of a window Fable depends on,
    # whichever Claude runner they use.
    routing = settings.routing
    assert budget_control.window_ceiling(
        routing, klass="review", protected_window=True, protected_runner=False) == 0.75
    assert budget_control.window_ceiling(
        routing, klass="review", protected_window=True, protected_runner=True) == 0.60
    assert budget_control.window_ceiling(
        routing, klass="decision", protected_window=True, protected_runner=True) == 0.9
    assert budget_control.window_ceiling(
        routing, klass="ordinary", protected_window=False, protected_runner=False) == 0.8


def test_claude_review_downgrades_to_worker_when_fable_is_reserved(tmp_path) -> None:
    _paths_, db = _setup(tmp_path)
    settings = _settings()
    _fable(db, settings, 0.65)
    _record(db, settings, "lead_gpt", {"seven_day": 0.1})
    _enqueue(db, "draft", "c", runner="worker_gpt")
    _enqueue(db, "review", "c", runner="frontier", task_type="paper_review",
             parent_task_id="draft", agent_role="reviewer", priority=5)
    task, _router = _claim(db, settings)
    assert task["task_id"] == "review" and task["runner"] == "worker_claude"
    event = _routed_events(db, "review")[0]
    assert event["downgraded_for_lead_reserve"] is True
    assert event["requested_tier"] == "lead" and event["tier"] == "worker"
    assert "因负责人额度保留而降级" in event["reason"]


def test_decision_moves_to_lead_gpt_inside_fable_reserve(tmp_path) -> None:
    _paths_, db = _setup(tmp_path)
    settings = _settings()
    _record(db, settings, "lead_gpt", {"seven_day": 0.6})
    _fable(db, settings, 0.5)
    _enqueue(db, "d1", "c1", runner=None, task_type="topic_admission")
    task, _router = _claim(db, settings)
    assert task["runner"] == "lead_claude"  # Fable leads while above its reserve
    _fable(db, settings, 0.8)
    _enqueue(db, "d2", "c2", runner=None, task_type="direction_decision")
    task, _router = _claim(db, settings)
    assert task["runner"] == "lead_gpt"
    assert _routed_events(db, "d2")[0]["reassigned_from"] == ["lead_claude"]
    # When lead_gpt is excluded by independence, Fable spends its reserve.
    _enqueue(db, "d3", "c3", runner=None, task_type="direction_decision", exclude_provider=GPT)
    task, _router = _claim(db, settings)
    assert task["runner"] == "lead_claude"


def test_no_lead_available_pauses_admission_and_scans_only(tmp_path, clock, monkeypatch) -> None:
    paths, db = _setup(tmp_path)
    settings = replace(_settings(), reserve_cpu_threads=0, reserve_memory_mib=0,
                       reserve_scratch_mib=0, auto_continue=False)
    _record(db, settings, "lead_gpt", {"seven_day": 1.0})
    _fable(db, settings, 1.0)
    _enqueue(db, "admit", "c1", runner=None, task_type="topic_admission", priority=9)
    _enqueue(db, "scan", "c2", runner=None, task_type="literature_scan", priority=8)
    _enqueue(db, "research", "c3", runner="balanced")
    with db.connect() as connection:
        connection.execute("UPDATE tasks SET cpu_threads=0, memory_mib=0, scratch_mib=0")
    launched: list[str] = []
    monkeypatch.setattr(engine, "_launch_task",
                        lambda _db, _p, _s, task, owner: launched.append(task["task_id"]))
    report = engine.tick(paths, settings)

    assert launched == ["research"]
    assert db.task("research")["runner"] == "worker_claude"
    assert report.lead_quota["short"] is True
    assert report.to_dict()["lead_quota_short"] is True
    assert set(report.lead_quota["paused_task_types"]) >= {"topic_admission", "literature_scan"}
    reasons = {item["task_id"]: item["reason"] for item in report.routing_deferred}
    assert reasons == {"admit": "lead_quota_short", "scan": "lead_quota_short"}
    assert [e["event_type"] for e in db.events() if e["entity_id"] == "lead_quota"] == [
        "lead_quota_short"]
    # Recovery is recorded once as well.
    _record(db, settings, "lead_gpt", {"seven_day": 0.3}, observed=NOW + timedelta(minutes=1))
    report = engine.tick(paths, settings)
    assert report.lead_quota["short"] is False
    assert [e["event_type"] for e in db.events() if e["entity_id"] == "lead_quota"] == [
        "lead_quota_short", "lead_quota_restored"]


def test_probe_never_uses_fable_and_runs_only_when_stale(tmp_path) -> None:
    with pytest.raises(ValueError, match="protected model"):
        _write_and_load(tmp_path / "bad", '[routing.probe_commands]\n'
                        'anthropic = ["claude", "-p", "ok", "--model", "claude-fable-5-2"]\n')
    _paths_, db = _setup(tmp_path)
    settings = _settings(probe_commands={CLAUDE: ("claude", "-p", "ok", "--model",
                                                  "claude-haiku-5-5")})
    calls: list[list[str]] = []

    class Completed:
        stdout = (
            '{"type":"system","model":"claude-haiku-5-5"}\n'
            '{"type":"rate_limit_event","rate_limit_info":{"unifiedWindows":{'
            '"five_hour":{"utilization":0.2,"resetsAt":1794385800}}}}\n'
        )

    def fake_run(command, **_kwargs):
        calls.append(command)
        return Completed()

    first = budget_control.probe_stale_providers(db, settings, now=NOW, run=fake_run)
    assert first == {CLAUDE: "recorded"} and len(calls) == 1
    assert budget_control.quota_readings(db)[CLAUDE]["five_hour"].used_fraction == 0.2
    # Fresh now: no further probe on the next tick.
    assert budget_control.probe_stale_providers(db, settings, now=NOW, run=fake_run) == {}
    assert len(calls) == 1


def _write_and_load(root: Path, text: str):
    paths = WorkspacePaths(workspace=root, code=root / "openlabs", data=root / "d",
                           artifacts=root / "a", database=root / "db",
                           database_file=root / "db" / "f")
    config = paths.code / "config" / "openlabs.toml"
    config.parent.mkdir(parents=True)
    config.write_text(text, encoding="utf-8")
    return load_settings(paths)


def test_runner_and_routing_tables_load_from_toml(tmp_path) -> None:
    settings = _write_and_load(tmp_path, """
[runners.lead_claude]
provider = "anthropic"
tier = "lead"
model = "claude-fable-5-2"
[runners.worker_claude]
provider = "anthropic"
tier = "worker"
model = "claude-opus-5-5"
windows = ["custom_window"]
[routing]
lead_review_ceiling = 0.5
[routing.task_tiers]
dataset_refresh = "light"
""")
    assert settings.runners["lead_claude"].protected is True
    assert settings.runners["lead_claude"].windows == ("seven_day_overage_included",)
    assert settings.runners["worker_claude"].windows == ("custom_window",)
    assert settings.runners["worker_claude"].protected is False
    assert settings.routing.lead_review_ceiling == 0.5
    assert settings.routing.task_tiers["dataset_refresh"] == "light"
    assert settings.routing.task_tiers["paper_review"] == "lead"
    shipped = load_settings(WorkspacePaths(
        workspace=tmp_path, code=Path(__file__).resolve().parents[2], data=tmp_path / "d",
        artifacts=tmp_path / "a", database=tmp_path / "db", database_file=tmp_path / "db" / "f",
    ))
    assert shipped.runners == {}  # routing stays inert in the shipped configuration
    assert shipped.routing.lead_decision_reserve == 0.25


# ---------------------------------------------------------------- escalation


def test_worker_task_escalates_to_lead_after_two_failures(tmp_path, clock) -> None:
    paths, db = _setup(tmp_path)
    settings = replace(_settings(), auto_continue=False)
    _enqueue(db, "t", "c", runner="balanced", max_attempts=4)
    for round_number in (1, 2):
        task, _router = _claim(db, settings)
        assert task["runner"] in {"worker_gpt", "worker_claude"}
        attempt_id, output = _bind(db, paths, task)
        _deliver(paths, db, "t", attempt_id, output, status="failed")
        report = TickReport()
        ingest_results(db, paths, settings, report)
        assert db.task("t")["status"] == "queued"
    assert report.escalated and report.escalated[0]["consecutive_failures"] == 2
    escalated = db.task("t")
    assert escalated["runner_request"] == "lead"
    assert escalated["objective"].startswith("[Escalated to the lead tier] Diagnose")
    assert "诊断前2次失败原因后再继续" in escalated["objective"]
    task, _router = _claim(db, settings)
    assert task["runner"] in {"lead_gpt", "lead_claude"}
    assert [e["event_type"] for e in db.events() if e["event_type"] == "task_escalated"] == [
        "task_escalated"]
    # A third failure on the lead tier does not escalate again or re-prefix.
    attempt_id, output = _bind(db, paths, task)
    _deliver(paths, db, "t", attempt_id, output, status="failed")
    ingest_results(db, paths, settings, TickReport())
    assert db.task("t")["objective"].count("[Escalated") == 1


def test_infrastructure_failures_do_not_count_towards_escalation(tmp_path, clock) -> None:
    paths, db = _setup(tmp_path)
    settings = replace(_settings(), auto_continue=False)
    _enqueue(db, "t", "c", runner="balanced", max_attempts=4)
    for failure_class in ("agent_transport", None):
        task, _router = _claim(db, settings)
        attempt_id, output = _bind(db, paths, task)
        _deliver(paths, db, "t", attempt_id, output, status="failed",
                 extra={"failure_class": failure_class} if failure_class else {})
        ingest_results(db, paths, settings, TickReport())
    assert db.task("t")["runner_request"] != "lead"


# ---------------------------------------------------------------- comparison


def test_execution_summary_aggregates_by_provider_and_tier(tmp_path) -> None:
    paths, db = _setup(tmp_path)
    settings = _settings()
    rows = [
        ("a", "worker_gpt", "succeeded", 100, 10, 30.0),
        ("b", "worker_gpt", "needs_human", 50, 5, 10.0),
        ("c", "worker_claude", "succeeded", 70, 7, 20.0),
    ]
    for task_id, runner, status, tokens_in, tokens_out, seconds in rows:
        _enqueue(db, task_id, f"camp-{task_id}", runner=runner)
        attempt_id, output = _start(db, paths, task_id)
        atomic_write_json(output, {"schema_version": RESULT_SCHEMA, "task_id": task_id,
                                   "status": status, "artifacts": [], "claims": []})
        db.ingest_result(
            task_id, attempt_id=attempt_id, status=status, result_path=str(output),
            result_sha256=sha256_file(output), valid=True, gate_passed=True, blockers=[],
            run_seconds=seconds,
            runtime={"runner": runner, "input_tokens": tokens_in, "output_tokens": tokens_out,
                     "model": RUNNERS[runner].model},
        )
    summary = {(row["provider"], row["tier"]): row
               for row in budget_control.execution_summary(db, settings)}
    gpt = summary[(GPT, "worker")]
    assert (gpt["attempts"], gpt["tasks"], gpt["succeeded"]) == (2, 2, 1)
    assert gpt["success_rate"] == 0.5
    assert (gpt["input_tokens"], gpt["output_tokens"]) == (150, 15)
    assert gpt["run_seconds"] == 40.0 and gpt["mean_run_seconds"] == 20.0
    assert gpt["models"] == ["gpt-6.1-sol"]
    claude = summary[(CLAUDE, "worker")]
    assert (claude["attempts"], claude["success_rate"], claude["input_tokens"]) == (1, 1.0, 70)


# ---------------------------------------------------------------- defaults


def test_default_configuration_schedules_exactly_as_before(tmp_path, clock, monkeypatch) -> None:
    paths, db = _setup(tmp_path)
    settings = FactorySettings(max_worker_processes=8, retry_backoff_seconds=0,
                               reserve_cpu_threads=0, reserve_memory_mib=0,
                               reserve_scratch_mib=0, auto_continue=False)
    assert settings.runners == {} and not budget_control.routing_enabled(settings)
    _enqueue(db, "low", "c1", runner="balanced", priority=0)
    _enqueue(db, "high", "c2", runner="frontier", priority=3)
    _enqueue(db, "scan", "c3", runner="cheap", task_type="literature_scan", priority=1)
    with db.connect() as connection:
        connection.execute("UPDATE tasks SET cpu_threads=0, memory_mib=0, scratch_mib=0")
    launched: list[str] = []
    monkeypatch.setattr(engine, "_launch_task",
                        lambda _db, _p, _s, task, owner: launched.append(task["task_id"]))
    report = engine.tick(paths, settings)
    assert launched == ["high", "scan", "low"]
    assert [db.task(t)["runner"] for t in launched] == ["frontier", "cheap", "balanced"]
    assert all(db.task(t)["runner_request"] is None for t in launched)
    assert not {"task_routed", "routing_deferred", "lead_quota_short"} & {
        e["event_type"] for e in db.events()}
    assert "provider_quota" not in report.to_dict()
    assert db.meta_items("quota_") == {}


# ---------------------------------------------------------------- helpers


def _bind(db: FactoryDB, paths: WorkspacePaths, task: dict) -> tuple[str, Path]:
    task_id = str(task["task_id"])
    attempt_id = str(task["current_attempt_id"])
    output = paths.data / "workspaces" / "math" / str(task["campaign_id"]) / attempt_id / "r.json"
    db.bind_attempt_spec(task_id, attempt_id=attempt_id, lab_id="math", output_path=str(output))
    db.mark_running(task_id, attempt_id=attempt_id, owner="test", pid=1, lease_seconds=600)
    return attempt_id, output


def _start(db: FactoryDB, paths: WorkspacePaths, task_id: str) -> tuple[str, Path]:
    task = db.claim_next_task(owner="test", lease_seconds=600)
    assert task is not None and task["task_id"] == task_id
    return _bind(db, paths, task)


def _deliver(paths: WorkspacePaths, db: FactoryDB, task_id: str, attempt_id: str, output: Path,
             *, status: str, extra: dict | None = None) -> None:
    task = db.task(task_id)
    atomic_write_json(output, {
        "schema_version": RESULT_SCHEMA, "task_id": task_id, "campaign_id": task["campaign_id"],
        "lab_id": "math", "domain": "math", "status": status, "summary": "Agent step.",
        "artifacts": [], "claims": [], "next_actions": [],
    })
    runtime = {"duration_seconds": 2.0, "exit_code": 0, "runner": task["runner"],
               **(extra or {})}
    atomic_write_json(paths.result_inbox / f"{attempt_id}.json", {
        "schema_version": RECEIPT_SCHEMA, "task_id": task_id, "attempt_id": attempt_id,
        "campaign_id": task["campaign_id"], "lab_id": "math", "domain": "math",
        "agent_role": "researcher", "result_path": str(output),
        "sha256": sha256_file(output), "runtime": runtime,
    })


def test_claim_order_under_limited_parallelism(tmp_path) -> None:
    _paths_, db = _setup(tmp_path)
    settings = _settings()
    for runner in ("lead_gpt", "worker_gpt"):
        _record(db, settings, runner, {"seven_day": 0.1})
    _fable(db, settings, 0.1, shared=0.15)
    _enqueue(db, "scan", "c1", runner=None, task_type="literature_scan", priority=9)
    _enqueue(db, "admit", "c2", runner=None, task_type="topic_admission", priority=8)
    _enqueue(db, "research", "c3", runner="balanced", priority=7)
    _enqueue(db, "writing", "c4", runner="frontier", task_type="paper_revision", priority=0,
             agent_role="writer")
    _enqueue(db, "review", "c5", runner="frontier", task_type="paper_review", priority=0,
             agent_role="reviewer")
    router = budget_control.QuotaRouter.build(db, settings, now=NOW)
    assert router.constrained(2) and not router.constrained(4)
    order = []
    for _ in range(5):
        task, _router = _claim(db, settings, rank=True)
        order.append(task["task_id"])
    # review / near-submission writing (rank 3) > research > admission > scan,
    # whatever the campaign priorities say.
    assert set(order[:2]) == {"writing", "review"}
    assert order[2:] == ["research", "admit", "scan"]
    # Writing is worker-tier work: GPT has the larger ordinary headroom here.
    assert db.task("writing")["runner"] == "worker_gpt"
