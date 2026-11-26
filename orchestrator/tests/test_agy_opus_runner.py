"""Claude Opus through the Antigravity CLI (``worker_agy_opus``, 2026-11-26).

User 2026-11-26: "本账号的claude额度不多了，你多用用反重力，而且可以用里面的gemini模型和opus 5.5模型，
它们似乎是分开的两个额度池". The runner is the Claude (``anthropic``) family for review
independence, but draws quota from agy's "Claude and GPT models" pool (``3p-weekly``,
``3p-5h``): neither the account's Claude windows nor the Gemini pool, and a quota hit
there does not stop the Gemini runners.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from openlabs import budget as budget_control
from openlabs.config import (
    ANTIGRAVITY_PROVIDER,
    RunnerSpec,
    load_runner_specs,
    model_identity,
)
from test_antigravity_adapter import GEMINI, GEMINI_WINDOWS
from test_quota_routing import (
    CLAUDE,
    NOW,
    RUNNERS,
    _claim,
    _enqueue,
    _record,
    _routed_events,
    _settings,
    _setup,
)

POOL = ("3p-weekly", "3p-5h")
AGY_OPUS = RunnerSpec("worker_agy_opus", ANTIGRAVITY_PROVIDER, "worker", "claude-opus-5-5-high",
                      windows=POOL, family_override=CLAUDE)


def _settings_with_agy(**routing):
    gemini = {name: replace(spec, overflow=False, task_classes=()) for name, spec in GEMINI.items()}
    return replace(_settings(**routing),
                   runners={**RUNNERS, **gemini, "worker_agy_opus": AGY_OPUS})


def _pool_quota(db, settings, used: float = 0.1) -> None:
    budget_control.record_quota_snapshot(db, settings, {
        "provider": ANTIGRAVITY_PROVIDER, "observed_at": budget_control._iso(NOW),
        "windows": [{"name": name, "used_fraction": used, "window_minutes": 10080,
                     "resets_at": budget_control._iso(NOW + timedelta(days=2))}
                    for name in (*GEMINI_WINDOWS, *POOL)]}, runner="worker_gemini")


def _claude_out(db, settings) -> None:
    for runner in ("worker_claude", "lead_claude", "light_claude"):
        _record(db, settings, runner, {"five_hour": 0.99, "seven_day": 0.99,
                                       "seven_day_overage_included": 0.99})


def test_config_keys_family_and_pool() -> None:
    specs = load_runner_specs({
        "worker_agy_opus": {"provider": ANTIGRAVITY_PROVIDER, "tier": "worker",
                            "model": "claude-opus-5-5-high", "family": "anthropic",
                            "windows": list(POOL), "overflow": False},
    })
    spec = specs["worker_agy_opus"]
    assert spec.family == CLAUDE and spec.provider == ANTIGRAVITY_PROVIDER
    assert spec.quota_key == f"{ANTIGRAVITY_PROVIDER}:3p"
    # The Gemini runners keep the plain provider key; the account's Claude its own provider.
    assert GEMINI["worker_gemini"].quota_key == ANTIGRAVITY_PROVIDER
    assert RUNNERS["worker_claude"].quota_key == CLAUDE
    observed = (*GEMINI_WINDOWS, *POOL, "gemini-argon-wtu-weekly")
    assert budget_control.runner_windows(spec, {**GEMINI, spec.name: spec}, observed) == (
        "3p-5h", "3p-weekly")


def test_model_identity_ignores_the_effort_suffix() -> None:
    assert model_identity("claude-opus-5-5-high") == model_identity("claude-opus-5-5")
    assert model_identity("gemini-4-neon-xhigh") == "gemini-4-neon"
    assert model_identity("gpt-6.2-sol") == "gpt-6.2-sol"
    assert model_identity(None) == ""


def test_router_reads_the_3p_pool_for_the_runner(tmp_path) -> None:
    _paths_, db = _setup(tmp_path)
    settings = _settings_with_agy()
    budget_control.record_quota_snapshot(db, settings, {
        "provider": ANTIGRAVITY_PROVIDER, "observed_at": budget_control._iso(NOW),
        "windows": [
            {"name": "gemini-weekly", "used_fraction": 0.01, "window_minutes": 10080,
             "resets_at": budget_control._iso(NOW + timedelta(days=2))},
            {"name": "3p-weekly", "used_fraction": 0.95, "window_minutes": 10080,
             "resets_at": budget_control._iso(NOW + timedelta(days=2))}]}, runner="worker_gemini")
    router = budget_control.QuotaRouter.build(db, settings, now=NOW)
    opus = router.availability(AGY_OPUS, "ordinary")
    assert opus.binding_window == "3p-weekly" and not opus.usable
    assert router.availability(settings.runners["worker_gemini"], "ordinary").usable
    # The provider summary still stands for the Gemini pool.
    assert budget_control.shared_probe_spec(
        settings.runners.values(), ANTIGRAVITY_PROVIDER).name == "worker_gemini"


def test_a_3p_quota_hit_does_not_stop_the_gemini_runners(tmp_path) -> None:
    _paths_, db = _setup(tmp_path)
    settings = _settings_with_agy()
    _pool_quota(db, settings)
    backoff = budget_control.record_quota_failure(db, settings, runner="worker_agy_opus", now=NOW)
    assert backoff.provider == f"{ANTIGRAVITY_PROVIDER}:3p"
    router = budget_control.QuotaRouter.build(db, settings, now=NOW)
    assert not router.usable(AGY_OPUS, "ordinary")
    assert router.usable(settings.runners["worker_gemini"], "ordinary")
    blocked = budget_control.blocked_runner_names(db, settings, now=NOW)
    assert "worker_agy_opus" in blocked and "worker_gemini" not in blocked
    # A healthy agy-Opus completion after the backoff clears its own pool's keys only.
    later = NOW + timedelta(hours=6)
    budget_control.record_quota_failure(db, settings, runner="worker_gemini", now=later)
    budget_control.record_healthy_completion(db, settings, runner="worker_agy_opus", now=later)
    router = budget_control.QuotaRouter.build(db, settings, now=later)
    assert router.usable(AGY_OPUS, "ordinary")
    assert not router.usable(settings.runners["worker_gemini"], "ordinary")


def test_agy_opus_never_reviews_claude_work_and_vice_versa(tmp_path) -> None:
    _paths_, db = _setup(tmp_path)
    settings = _settings_with_agy()
    for runner in ("worker_gpt", "lead_gpt"):
        _record(db, settings, runner, {"seven_day": 0.05})
    _record(db, settings, "worker_claude", {"five_hour": 0.1, "seven_day": 0.1})
    _pool_quota(db, settings)
    _enqueue(db, "draft", "c", runner="worker_claude")
    _enqueue(db, "review", "c", runner="balanced", task_type="paper_review",
             parent_task_id="draft", agent_role="reviewer", priority=5)
    task, _router = _claim(db, settings)
    assert task["task_id"] == "review"
    assert settings.runners[task["runner"]].family != CLAUDE
    _enqueue(db, "draft2", "d", runner="worker_agy_opus")
    _enqueue(db, "review2", "d", runner="balanced", task_type="paper_review",
             parent_task_id="draft2", agent_role="reviewer", priority=5)
    task, _router = _claim(db, settings)
    assert task["task_id"] == "review2"
    assert task["runner"] not in {"worker_claude", "lead_claude", "light_claude"}
    assert _routed_events(db, "review2")[0]["excluded_provider"] == CLAUDE


def test_same_family_fallback_does_not_count_agy_opus_as_another_model(tmp_path) -> None:
    # GPT and Gemini out of quota: the review of an Opus draft falls back inside the Claude
    # family to another model - never Opus through agy (the same model, another tool).
    _paths_, db = _setup(tmp_path)
    settings = _settings_with_agy()
    # As on cc-sg since 2026-11-23: the Claude lead is Opus too (no protected Fable).
    settings = replace(settings, runners={
        **settings.runners,
        "lead_claude": RunnerSpec("lead_claude", CLAUDE, "lead", "claude-opus-5-5")})
    for runner in ("worker_gpt", "lead_gpt", "light_gpt"):
        _record(db, settings, runner, {"seven_day": 0.99})
    # The 3p pool is free, the Gemini pool full.
    budget_control.record_quota_snapshot(db, settings, {
        "provider": ANTIGRAVITY_PROVIDER, "observed_at": budget_control._iso(NOW),
        "windows": [{"name": name, "used_fraction": 0.0 if name in POOL else 0.99,
                     "window_minutes": 10080,
                     "resets_at": budget_control._iso(NOW + timedelta(days=2))}
                    for name in (*GEMINI_WINDOWS, *POOL)]}, runner="worker_gemini")
    for runner in ("worker_claude", "lead_claude", "light_claude"):
        _record(db, settings, runner, {"five_hour": 0.1, "seven_day": 0.1,
                                       "seven_day_overage_included": 0.1})
    _enqueue(db, "draft", "c", runner="worker_claude")
    _enqueue(db, "review", "c", runner="balanced", task_type="paper_review",
             parent_task_id="draft", agent_role="reviewer", priority=5)
    task, _router = _claim(db, settings)
    assert task["task_id"] == "review" and task["runner"] == "light_claude"
    event = _routed_events(db, "review")[0]
    assert event["independence"] == "same_family_different_model"


def test_resumed_gemini_conversation_stays_on_gemini(tmp_path) -> None:
    _paths_, db = _setup(tmp_path)
    settings = _settings_with_agy()
    for runner in ("worker_gpt", "lead_gpt", "light_gpt"):
        _record(db, settings, runner, {"seven_day": 0.05})
    _claude_out(db, settings)
    # The Gemini pool is full, the 3p pool free: the resume waits for Gemini, it is not
    # continued by Opus through the same agy tool.
    budget_control.record_quota_snapshot(db, settings, {
        "provider": ANTIGRAVITY_PROVIDER, "observed_at": budget_control._iso(NOW),
        "windows": [{"name": name, "used_fraction": 0.0 if name in POOL else 0.99,
                     "window_minutes": 10080,
                     "resets_at": budget_control._iso(NOW + timedelta(days=2))}
                    for name in (*GEMINI_WINDOWS, *POOL)]}, runner="worker_gemini")
    _enqueue(db, "first", "c", runner="worker_gemini")
    with db.connect() as connection:
        connection.execute("UPDATE tasks SET status='succeeded', agent_session_id='conv-1' "
                           "WHERE task_id='first'")
    _enqueue(db, "next", "c", runner="balanced", session_mode="resume", parent_task_id="first",
             session_source_task_id="first")
    task, router = _claim(db, settings)
    assert task is None
    assert router.deferred["next"]["sticky_provider"] == ANTIGRAVITY_PROVIDER


def test_ordinary_worker_task_goes_to_agy_opus_when_the_account_claude_is_short(tmp_path) -> None:
    _paths_, db = _setup(tmp_path)
    settings = _settings_with_agy()
    for runner in ("worker_gpt", "lead_gpt", "light_gpt"):
        _record(db, settings, runner, {"seven_day": 0.99})
    _claude_out(db, settings)
    budget_control.record_quota_snapshot(db, settings, {
        "provider": ANTIGRAVITY_PROVIDER, "observed_at": budget_control._iso(NOW),
        "windows": [{"name": name, "used_fraction": 0.02 if name in POOL else 0.99,
                     "window_minutes": 10080,
                     "resets_at": budget_control._iso(NOW + timedelta(days=2))}
                    for name in (*GEMINI_WINDOWS, *POOL)]}, runner="worker_gemini")
    _enqueue(db, "work", "c", runner="balanced")
    task, _router = _claim(db, settings)
    assert task["runner"] == "worker_agy_opus"
