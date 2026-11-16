"""One model family configured: reviews and decisions go to a different model of it."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta

from openlabs import budget as budget_control
from openlabs.config import FactorySettings, RoutingSettings, RunnerSpec
from test_quota_routing import (
    CLAUDE,
    GPT,
    NOW,
    RUNNERS,
    _claim,
    _enqueue,
    _record,
    _routed_events,
    _settings,
    _setup,
)

GPT_ONLY = {name: spec for name, spec in RUNNERS.items() if spec.provider == GPT}


def _gpt_settings() -> FactorySettings:
    return replace(_settings(), runners=dict(GPT_ONLY))


def _fresh(db, settings) -> None:
    _record(db, settings, "lead_gpt", {"seven_day": 0.05})


def test_review_of_owner_work_goes_to_another_gpt_model(tmp_path) -> None:
    _paths, db = _setup(tmp_path)
    settings = _gpt_settings()
    _fresh(db, settings)
    _enqueue(db, "seat", "c", runner="lead_gpt", task_type="topic_owner")
    _enqueue(db, "review", "c", runner="frontier", task_type="paper_review",
             parent_task_id="seat", agent_role="reviewer", priority=5)
    task, _router = _claim(db, settings)
    assert task["task_id"] == "review"
    assert task["runner"] == "worker_gpt"  # gpt-6.1-sol, not the author's gpt-6-astra
    event = _routed_events(db, "review")[0]
    assert event["independence"] == "same_family_different_model"
    assert event["producer_model"] == "gpt-6-astra" and event["model"] == "gpt-6.1-sol"
    assert event["requested_tier"] == "lead"


def test_explicit_exclusion_does_not_wait_for_a_missing_family(tmp_path) -> None:
    paths, db = _setup(tmp_path)
    settings = _gpt_settings()
    _fresh(db, settings)
    packet = paths.artifacts / "direction.json"
    packet.write_text(json.dumps({"producer_model": "gpt-6-astra"}), encoding="utf-8")
    _enqueue(db, "decide", "c", runner="frontier", task_type="direction_decision",
             exclude_provider=GPT, agent_role="reviewer", input_path=str(packet))
    task, _router = _claim(db, settings)
    assert task is not None and task["runner"] == "worker_gpt"
    event = _routed_events(db, "decide")[0]
    assert event["excluded_provider"] == GPT
    assert event["independence"] == "same_family_different_model"


def test_admission_by_another_model_than_the_scout_stays_on_its_tier(tmp_path) -> None:
    paths, db = _setup(tmp_path)
    settings = _gpt_settings()
    _fresh(db, settings)
    packet = paths.artifacts / "admission.json"
    packet.write_text(json.dumps({"producer_model": "gpt-6.1-sol"}), encoding="utf-8")
    _enqueue(db, "admit", "c", runner="frontier", task_type="portfolio_review",
             exclude_provider=GPT, agent_role="reviewer", input_path=str(packet))
    task, _router = _claim(db, settings)
    assert task["runner"] == "lead_gpt"
    assert _routed_events(db, "admit")[0]["independence"] == "same_family_different_model"


def test_unknown_producer_model_is_labelled(tmp_path) -> None:
    _paths, db = _setup(tmp_path)
    settings = _gpt_settings()
    _fresh(db, settings)
    _enqueue(db, "admit", "c", runner="frontier", task_type="portfolio_review",
             exclude_provider=GPT, agent_role="reviewer")
    task, _router = _claim(db, settings)
    assert task["runner"] == "lead_gpt"
    assert _routed_events(db, "admit")[0]["independence"] == "same_family_model_unknown"


def test_no_other_model_defers_instead_of_self_review(tmp_path) -> None:
    _paths, db = _setup(tmp_path)
    settings = replace(_settings(), runners={
        "lead_gpt": RunnerSpec("lead_gpt", GPT, "lead", "gpt-6-astra")})
    _fresh(db, settings)
    _enqueue(db, "seat", "c", runner="lead_gpt", task_type="topic_owner")
    _enqueue(db, "review", "c", runner="frontier", task_type="paper_review",
             parent_task_id="seat", agent_role="reviewer", priority=5)
    router = budget_control.QuotaRouter.build(db, settings, now=NOW)
    assert router.route(db.task("review"), {}) is None
    assert router.deferred["review"]["independence"] == "same_family_different_model"


def test_two_families_keep_cross_family_routing(tmp_path) -> None:
    _paths, db = _setup(tmp_path)
    settings = _settings()
    _fresh(db, settings)
    _record(db, settings, "lead_claude", {"seven_day": 0.05})
    _enqueue(db, "decide", "c", runner="frontier", task_type="direction_decision",
             exclude_provider=GPT)
    task, _router = _claim(db, settings)
    assert task["runner"] == "lead_claude"
    assert "independence" not in _routed_events(db, "decide")[0]


# ------------------------------------------- other family out of quota (2026-11-16)


def _claude_out(db, settings, used: dict[str, float] | None = None, **kwargs) -> None:
    """Every Claude runner unavailable: past the 90% hard ceiling (reason ``ceiling``)."""

    _record(db, settings, "lead_claude",
            used or {"five_hour": 0.2, "seven_day": 0.95, "seven_day_overage_included": 0.2},
            **kwargs)


def _admission(paths, db, task_id: str = "admit", producer: str = "gpt-6.1-sol") -> None:
    packet = paths.artifacts / f"{task_id}.json"
    packet.write_text(json.dumps({"producer_model": producer}), encoding="utf-8")
    _enqueue(db, task_id, task_id, runner="frontier", task_type="portfolio_review",
             exclude_provider=GPT, agent_role="reviewer", input_path=str(packet),
             routing_reason="topic_admission")


def test_admission_falls_back_to_another_gpt_model_when_claude_is_out(tmp_path) -> None:
    paths, db = _setup(tmp_path)
    settings = _settings()
    _fresh(db, settings)
    _claude_out(db, settings)
    _admission(paths, db)
    task, _router = _claim(db, settings)
    assert task is not None and task["runner"] == "lead_gpt"  # not the scout's gpt-6.1-sol
    event = _routed_events(db, "admit")[0]
    assert event["independence"] == "same_family_different_model"
    assert event["independence_fallback"] == "other_family_quota_unavailable"
    assert event["producer_model"] == "gpt-6.1-sol" and event["model"] == "gpt-6-astra"
    assert event["excluded_provider"] == GPT
    assert event["unavailable_providers"] == [CLAUDE]
    assert event["other_family_quota_reasons"] == ["ceiling"]
    assert event["other_family_resume_at"] == budget_control._iso(NOW + timedelta(days=2))
    assert "额度不可用" in event["reason"]


def test_review_of_owner_work_and_direction_decision_fall_back(tmp_path) -> None:
    paths, db = _setup(tmp_path)
    settings = _settings()
    _fresh(db, settings)
    _claude_out(db, settings)
    _enqueue(db, "seat", "c", runner="lead_gpt", task_type="topic_owner")
    _enqueue(db, "review", "c", runner="frontier", task_type="paper_review",
             parent_task_id="seat", agent_role="reviewer", priority=5,
             routing_reason="owner_recompute_review")
    task, _router = _claim(db, settings)
    assert task["task_id"] == "review" and task["runner"] == "worker_gpt"
    event = _routed_events(db, "review")[0]
    assert event["producer_model"] == "gpt-6-astra"
    assert event["independence_fallback"] == "other_family_quota_unavailable"

    packet = paths.artifacts / "direction.json"
    packet.write_text(json.dumps({"producer_model": "gpt-6-astra"}), encoding="utf-8")
    _enqueue(db, "decide", "d", runner="frontier", task_type="direction_decision",
             exclude_provider=GPT, agent_role="reviewer", input_path=str(packet))
    task, _router = _claim(db, settings)
    assert task["task_id"] == "decide" and task["runner"] == "worker_gpt"
    assert _routed_events(db, "decide")[0]["independence"] == "same_family_different_model"


def test_claude_backoff_counts_as_quota_unavailable(tmp_path) -> None:
    paths, db = _setup(tmp_path)
    settings = _settings()
    _fresh(db, settings)
    _record(db, settings, "lead_claude", {"seven_day": 0.1})
    _admission(paths, db)
    router = budget_control.QuotaRouter.build(db, settings, now=NOW)
    router.backoffs[CLAUDE] = budget_control._iso(NOW + timedelta(hours=3))
    decision = router.route(db.task("admit"), {})
    assert decision["runner"] == "lead_gpt"
    assert decision["other_family_quota_reasons"] == ["backoff"]
    assert decision["other_family_resume_at"] == budget_control._iso(NOW + timedelta(hours=3))


def test_routing_returns_across_families_once_claude_recovers(tmp_path) -> None:
    paths, db = _setup(tmp_path)
    settings = _settings()
    _fresh(db, settings)
    _claude_out(db, settings)
    _admission(paths, db, "admit1")
    task, _router = _claim(db, settings)
    assert task["runner"] == "lead_gpt"
    # Quota back: the next admission goes to Claude again; the first one stays put.
    later = NOW + timedelta(minutes=5)
    _claude_out(db, settings, {"five_hour": 0.1, "seven_day": 0.1,
                               "seven_day_overage_included": 0.1}, observed=later)
    _admission(paths, db, "admit2")
    task, _router = _claim(db, settings, now=later)
    assert task["task_id"] == "admit2" and task["runner"] == "lead_claude"
    assert "independence" not in _routed_events(db, "admit2")[0]
    assert db.task("admit1")["runner"] == "lead_gpt"


def test_switch_off_keeps_waiting_for_the_other_family(tmp_path) -> None:
    paths, db = _setup(tmp_path)
    settings = _settings(independence_fallback_on_quota=False)
    _fresh(db, settings)
    _claude_out(db, settings)
    _admission(paths, db)
    router = budget_control.QuotaRouter.build(db, settings, now=NOW)
    assert router.route(db.task("admit"), {}) is None
    deferred = router.deferred["admit"]
    assert deferred["reason"] == "no_runner_available"
    assert "independence_fallback" not in deferred


def test_min_wait_holds_the_fallback_while_claude_reopens_soon(tmp_path) -> None:
    paths, db = _setup(tmp_path)
    # The 5-hour window (not paced) at 95% resets in one hour.
    used = {"five_hour": 0.95, "seven_day": 0.1, "seven_day_overage_included": 0.1}
    settings = _settings(independence_fallback_min_wait_minutes=120)
    _fresh(db, settings)
    _claude_out(db, settings, used)
    _admission(paths, db)
    router = budget_control.QuotaRouter.build(db, settings, now=NOW)
    assert router.route(db.task("admit"), {}) is None
    deferred = router.deferred["admit"]
    assert deferred["reason"] == "independent_family_resumes_soon"
    assert deferred["wait_minutes"] == 120
    assert deferred["other_family_resume_at"] == budget_control._iso(NOW + timedelta(hours=1))
    # A shorter wait than the expected reopening: fall back now.
    shorter = _settings(independence_fallback_min_wait_minutes=30)
    router = budget_control.QuotaRouter.build(db, shorter, now=NOW)
    decision = router.route(db.task("admit"), {})
    assert decision["runner"] == "lead_gpt"
    assert decision["independence_fallback"] == "other_family_quota_unavailable"


def test_no_other_model_of_the_family_keeps_waiting(tmp_path) -> None:
    paths, db = _setup(tmp_path)
    runners = {name: spec for name, spec in RUNNERS.items() if spec.provider != GPT}
    runners["lead_gpt"] = RUNNERS["lead_gpt"]
    settings = replace(_settings(), runners=runners)
    _fresh(db, settings)
    _claude_out(db, settings)
    _admission(paths, db, producer="gpt-6-astra")
    router = budget_control.QuotaRouter.build(db, settings, now=NOW)
    assert router.route(db.task("admit"), {}) is None
    deferred = router.deferred["admit"]
    assert deferred["independence"] == "same_family_different_model"
    assert deferred["independence_fallback"] == "other_family_quota_unavailable"
    assert deferred["producer_model"] == "gpt-6-astra"


def test_busy_but_available_other_family_is_waited_for(tmp_path) -> None:
    paths, db = _setup(tmp_path)
    settings = _settings()
    _fresh(db, settings)  # no Claude reading: unknown, one task at a time
    _admission(paths, db)
    router = budget_control.QuotaRouter.build(db, settings, now=NOW)
    assert router.route(db.task("admit"), {"worker_claude": 1}) is None
    assert "independence_fallback" not in router.deferred["admit"]


def test_fallback_settings_load_from_toml(tmp_path) -> None:
    from test_quota_routing import _write_and_load

    loaded = _write_and_load(tmp_path, """
[routing]
independence_fallback_on_quota = false
independence_fallback_min_wait_minutes = 45
""")
    assert loaded.routing.independence_fallback_on_quota is False
    assert loaded.routing.independence_fallback_min_wait_minutes == 45
    assert RoutingSettings().independence_fallback_on_quota is True
