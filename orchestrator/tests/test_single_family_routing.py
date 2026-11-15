"""One model family configured: reviews and decisions go to a different model of it."""

from __future__ import annotations

import json
from dataclasses import replace

from openlabs import budget as budget_control
from openlabs.config import FactorySettings, RunnerSpec
from test_quota_routing import (
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
