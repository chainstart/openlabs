"""``[routing.provider_preference]``: a time-boxed "chores to one provider first" rule
(user 2026-11-26, "杂活可以多派gpt")."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
import test_quota_routing as qr
from openlabs import budget as budget_control
from openlabs.config import ProviderPreference, load_routing_settings

NOW = qr.NOW
GPT, CLAUDE = qr.GPT, qr.CLAUDE
CHORES = frozenset({"replan", "paper_figure_repair", "topic_scout", "paper_review"})


def _preference(**kwargs) -> ProviderPreference:
    values = {"provider": GPT, "until": NOW + timedelta(days=2),
              "tiers": frozenset({"light"}), "task_types": CHORES}
    values.update(kwargs)
    return ProviderPreference(**values)


def _settings(preference: ProviderPreference | None = None):
    return qr._settings(utilization_target=0.9, pace_curve=((0.0, 1.0),),
                        provider_preference=preference or _preference())


def _claude_more_abundant(db, settings) -> None:
    for runner in ("worker_gpt", "light_gpt"):
        qr._record(db, settings, runner, {"seven_day": 0.6})
    for runner in ("worker_claude", "light_claude"):
        qr._record(db, settings, runner, {"seven_day": 0.05})


def _route(db, settings, task_id: str, *, active=None, **enqueue):
    enqueue.setdefault("runner", None)
    qr._enqueue(db, task_id, "c-" + task_id, **enqueue)
    router = budget_control.QuotaRouter.build(db, settings, now=NOW)
    return router.route(db.task(task_id), dict(active or {}))


def test_without_a_preference_claude_would_take_the_chore(tmp_path) -> None:
    _, db = qr._setup(tmp_path)
    settings = qr._settings(utilization_target=0.9, pace_curve=((0.0, 1.0),))
    _claude_more_abundant(db, settings)
    assert _route(db, settings, "t", task_type="data_curation")["provider"] == CLAUDE


def test_light_tier_and_listed_worker_chores_go_to_the_preferred_provider(tmp_path) -> None:
    _, db = qr._setup(tmp_path)
    settings = _settings()
    _claude_more_abundant(db, settings)
    light = _route(db, settings, "l", task_type="data_curation")
    assert light["runner"] == "light_gpt"
    assert light["provider_preference"] == GPT
    assert light["provider_preference_until"] == budget_control._iso(NOW + timedelta(days=2))
    # Busy GPT still gets it: the preference overrides the abundance spread.
    replan = _route(db, settings, "r", task_type="replan", routing_reason="gate_replan",
                    active={"worker_gpt": 3})
    assert replan["runner"] == "worker_gpt" and replan["tier"] == "worker"


def test_unlisted_worker_tasks_are_routed_as_usual(tmp_path) -> None:
    _, db = qr._setup(tmp_path)
    settings = _settings()
    _claude_more_abundant(db, settings)
    decision = _route(db, settings, "w", task_type="paper_writing")
    assert decision["provider"] == CLAUDE and "provider_preference" not in decision


def test_excluded_types_and_reasons_are_left_out(tmp_path) -> None:
    _, db = qr._setup(tmp_path)
    settings = _settings(_preference(exclude_task_types=frozenset({"format_fix:release_format_fix"})))
    _claude_more_abundant(db, settings)
    out = _route(db, settings, "f1", task_type="format_fix", routing_reason="release_format_fix")
    assert out["provider"] == CLAUDE
    assert _route(db, settings, "f2", task_type="format_fix")["provider"] == GPT


def test_expired_preference_is_inert(tmp_path) -> None:
    _, db = qr._setup(tmp_path)
    settings = _settings(_preference(until=NOW))
    _claude_more_abundant(db, settings)
    decision = _route(db, settings, "t", task_type="data_curation")
    assert decision["provider"] == CLAUDE and "provider_preference" not in decision


def test_preferred_provider_out_of_quota_falls_back(tmp_path) -> None:
    _, db = qr._setup(tmp_path)
    settings = _settings()
    for runner in ("worker_gpt", "light_gpt"):
        qr._record(db, settings, runner, {"seven_day": 0.85})  # past the 80 % ceiling
    for runner in ("worker_claude", "light_claude"):
        qr._record(db, settings, runner, {"seven_day": 0.05})
    decision = _route(db, settings, "t", task_type="data_curation")
    assert decision["provider"] == CLAUDE
    assert decision["provider_preference_unavailable"] == GPT


def test_preferred_provider_parallel_limit_falls_back(tmp_path) -> None:
    _, db = qr._setup(tmp_path)
    settings = _settings()
    # No GPT reading: unknown quota allows one GPT agent at a time.
    for runner in ("worker_claude", "light_claude"):
        qr._record(db, settings, runner, {"seven_day": 0.05})
    first = _route(db, settings, "a", task_type="data_curation")
    assert first["provider"] == GPT
    second = _route(db, settings, "b", task_type="data_curation", active={"light_gpt": 1})
    assert second["provider"] == CLAUDE
    assert second["provider_preference_unavailable"] == GPT


def test_reviews_keep_excluding_the_author_family(tmp_path) -> None:
    _, db = qr._setup(tmp_path)
    settings = _settings()
    # GPT the more abundant here, so only the author-family exclusion keeps it off.
    for runner in ("lead_gpt", "worker_gpt"):
        qr._record(db, settings, runner, {"seven_day": 0.05})
    for runner in ("lead_claude", "worker_claude"):
        qr._record(db, settings, runner, {"seven_day": 0.3})
    control = _route(db, settings, "rev0", task_type="paper_review")
    assert control["provider"] == GPT
    qr._enqueue(db, "author", "c-rev", runner="worker_gpt", task_type="paper_writing")
    # paper_review is even listed in task_types: the review class still wins.
    qr._enqueue(db, "rev", "c-rev", runner=None, task_type="paper_review",
                parent_task_id="author", agent_role="reviewer")
    router = budget_control.QuotaRouter.build(db, settings, now=NOW)
    decision = router.route(db.task("rev"), {})
    assert decision["provider"] == CLAUDE and "provider_preference" not in decision
    explicit = _route(db, settings, "rev2", task_type="paper_review", exclude_provider=GPT)
    assert explicit["provider"] == CLAUDE


def test_scouts_keep_their_own_rotation(tmp_path) -> None:
    paths, db = qr._setup(tmp_path)
    settings = _settings()
    _claude_more_abundant(db, settings)
    packet = paths.data / "s.json"
    packet.write_text(json.dumps({"preferred_runner": "worker_claude"}))
    decision = _route(db, settings, "s", task_type="topic_scout", input_path=str(packet))
    assert decision["runner"] == "worker_claude" and "provider_preference" not in decision
    # A scout without a packet preference is not pulled to GPT either.
    plain = _route(db, settings, "s2", task_type="topic_scout")
    assert plain["provider"] == CLAUDE and "provider_preference" not in plain


def test_parse_provider_preference() -> None:
    routing = load_routing_settings({"provider_preference": {
        "provider": GPT, "until": "2026-11-28T03:03:00Z", "tiers": ["light"],
        "task_types": ["replan", "format_fix:release_format_fix"],
        "exclude_task_types": ["paper_writing"], "reason": "user 2026-11-26",
    }})
    pref = routing.provider_preference
    assert pref is not None and pref.provider == GPT
    assert budget_control._iso(pref.until) == "2026-11-28T03:03:00Z"
    assert pref.tiers == {"light"} and "format_fix:release_format_fix" in pref.task_types
    assert pref.matches("replan", "gate_replan", "worker")
    assert pref.matches("data_download", "", "light")
    assert not pref.matches("paper_writing", "", "light")
    assert load_routing_settings({}).provider_preference is None


@pytest.mark.parametrize("table", [
    {"until": "2026-11-28T03:03:00Z", "tiers": ["light"]},  # no provider
    {"provider": GPT, "until": "2026-11-28T03:03:00", "tiers": ["light"]},  # naive time
    {"provider": GPT, "until": "soon", "tiers": ["light"]},
    {"provider": GPT, "until": "2026-11-28T03:03:00Z"},  # nothing to match
    {"provider": GPT, "until": "2026-11-28T03:03:00Z", "tiers": ["cheapest"]},
    {"provider": GPT, "until": "2026-11-28T03:03:00Z", "task_types": ["replan:nope"]},
])
def test_invalid_provider_preference_is_rejected(table) -> None:
    with pytest.raises(ValueError):
        load_routing_settings({"provider_preference": table})
