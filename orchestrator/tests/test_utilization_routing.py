"""Use-before-reset routing: relative abundance against a utilization target, the
spread of work between providers, and refreshed or extrapolated stale readings."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import test_quota_routing as qr
from openlabs import budget as budget_control

NOW = qr.NOW
GPT, CLAUDE = qr.GPT, qr.CLAUDE


def _window(name: str, used: float, *, minutes: int, resets_in: timedelta) -> dict:
    return {"name": name, "used_fraction": used, "window_minutes": minutes,
            "resets_at": budget_control._iso(NOW + resets_in)}


def _reading(db, settings, runner: str, *windows: dict, observed: datetime = NOW) -> None:
    spec = qr.RUNNERS[runner]
    budget_control.record_quota_snapshot(
        db, settings,
        {"provider": spec.provider, "observed_at": budget_control._iso(observed),
         "model": spec.model, "windows": list(windows)},
        runner=runner,
    )


def _gpt_resets_soon_claude_later(db, settings) -> None:
    """GPT: 60% used, resets in 1 day. Claude: 5% used, resets in 6 days."""

    week = 10_080
    _reading(db, settings, "worker_gpt", _window("seven_day", 0.6, minutes=week,
                                                 resets_in=timedelta(days=1)))
    _reading(db, settings, "worker_claude", _window("seven_day", 0.05, minutes=week,
                                                    resets_in=timedelta(days=6)),
             _window("five_hour", 0.1, minutes=300, resets_in=timedelta(hours=2)))


def _route(db, settings, task_id: str, active=None, **enqueue):
    if db.task(task_id) is None:
        qr._enqueue(db, task_id, "c-" + task_id, **enqueue)
    router = budget_control.QuotaRouter.build(db, settings, now=NOW)
    return router.route(db.task(task_id), dict(active or {})), router

# --------------------------------------------------------------------------- routing


def test_target_zero_keeps_headroom_ranking(tmp_path) -> None:
    _, db = qr._setup(tmp_path)
    settings = qr._settings()
    _gpt_resets_soon_claude_later(db, settings)
    decision, _ = _route(db, settings, "t")
    assert decision["provider"] == CLAUDE  # more headroom (0.70 vs 0.25)
    assert "abundance" not in decision


def test_provider_resetting_soon_with_quota_left_is_preferred(tmp_path) -> None:
    _, db = qr._setup(tmp_path)
    settings = qr._settings(utilization_target=0.9)
    _gpt_resets_soon_claude_later(db, settings)
    decision, router = _route(db, settings, "t")
    assert decision["provider"] == GPT
    gpt = router.availability(qr.RUNNERS["worker_gpt"], "ordinary")
    claude = router.availability(qr.RUNNERS["worker_claude"], "ordinary")
    # (0.85 - 0.6) / (1/7) vs (0.75 - 0.05) / (6/7): Claude's ceiling carries
    # Fable's decision reserve because Fable shares its weekly window.
    assert gpt.abundance == pytest.approx(1.75, rel=1e-3)
    assert claude.abundance == pytest.approx(0.70 / (6 / 7), rel=1e-3)
    assert decision["abundance"] == pytest.approx(1.75, rel=1e-3)


def test_work_is_spread_in_proportion_to_abundance(tmp_path) -> None:
    _, db = qr._setup(tmp_path)
    settings = qr._settings(utilization_target=0.9)
    _gpt_resets_soon_claude_later(db, settings)
    one, _ = _route(db, settings, "t1", active={"worker_gpt": 1})
    assert one["provider"] == GPT  # GPT's share (~68%) is not yet filled
    two, _ = _route(db, settings, "t2", active={"worker_gpt": 2})
    assert two["provider"] == CLAUDE  # the less abundant family gets its share too


def test_target_and_reserves_bound_ordinary_work_not_reviews(tmp_path) -> None:
    _, db = qr._setup(tmp_path)
    settings = qr._settings(utilization_target=0.8)
    week = 10_080
    _reading(db, settings, "worker_gpt", _window("seven_day", 0.82, minutes=week,
                                                 resets_in=timedelta(hours=12)))
    _reading(db, settings, "worker_claude", _window("seven_day", 0.05, minutes=week,
                                                    resets_in=timedelta(days=6)))
    decision, router = _route(db, settings, "t")
    assert decision["provider"] == CLAUDE
    state = router.availability(qr.RUNNERS["worker_gpt"], "ordinary")
    assert state.state == "unavailable" and state.reason == "reserve"
    # Past the target GPT still takes reviews (only the review reserve applies).
    assert router.availability(qr.RUNNERS["lead_gpt"], "review").usable


def test_independence_still_excludes_the_producer_family(tmp_path) -> None:
    _, db = qr._setup(tmp_path)
    settings = qr._settings(utilization_target=0.9)
    _gpt_resets_soon_claude_later(db, settings)
    decision, _ = _route(db, settings, "rev", runner=None, task_type="paper_review",
                         exclude_provider=GPT)
    assert decision["provider"] == CLAUDE


def test_a_window_near_reset_with_quota_left_is_not_overspeed() -> None:
    reading = budget_control.WindowReading(
        provider=GPT, name="seven_day", used_fraction=0.5, window_minutes=10_080,
        resets_at=NOW + timedelta(hours=3), observed_at=NOW,
    )
    assert not budget_control.is_overspeed(reading, now=NOW)
    assert budget_control.window_abundance(reading, 0.9, now=NOW) == pytest.approx(
        0.4 / (3 / 168), rel=1e-3
    )


def test_five_hour_window_binds_a_runner_before_the_weekly_one(tmp_path) -> None:
    _, db = qr._setup(tmp_path)
    settings = qr._settings(utilization_target=0.9)
    week = 10_080
    _reading(db, settings, "worker_claude",
             _window("seven_day", 0.1, minutes=week, resets_in=timedelta(hours=10)),
             _window("five_hour", 0.7, minutes=300, resets_in=timedelta(hours=4)))
    router = budget_control.QuotaRouter.build(db, settings, now=NOW)
    state = router.availability(qr.RUNNERS["worker_claude"], "ordinary")
    five = next(w for w in state.windows if w["name"] == "five_hour")
    assert state.abundance == pytest.approx(five["abundance"])


# --------------------------------------------------------------------------- stale readings


def test_stale_reading_is_extrapolated_instead_of_limiting_to_one(tmp_path) -> None:
    _, db = qr._setup(tmp_path)
    settings = qr._settings(stale_estimate_hours=48)
    observed = NOW - timedelta(hours=10)
    _reading(db, settings, "worker_gpt", {
        "name": "seven_day", "used_fraction": 0.5, "window_minutes": 10_080,
        "resets_at": budget_control._iso(NOW + timedelta(days=2)),
    }, observed=observed)
    router = budget_control.QuotaRouter.build(db, settings, now=NOW)
    state = router.availability(qr.RUNNERS["worker_gpt"], "ordinary")
    assert state.state == "available" and state.estimated
    estimate = router.readings[GPT]["seven_day"]
    # The instance ran nothing since the reading (loop stopped): no extrapolation.
    assert estimate.used_fraction == pytest.approx(0.5)
    assert estimate.estimated_from == observed
    # Not limited to one task in flight.
    assert router._limit_ok(qr.RUNNERS["worker_gpt"], state, {"worker_gpt": 3})
    # Off by default, and never for readings older than the limit.
    for hours, age in ((0, 10), (48, 60)):
        _, db2 = qr._setup(tmp_path / f"h{hours}-{age}")
        s2 = qr._settings(stale_estimate_hours=hours)
        _reading(db2, s2, "worker_gpt", {
            "name": "seven_day", "used_fraction": 0.5, "window_minutes": 10_080,
            "resets_at": budget_control._iso(NOW + timedelta(days=2)),
        }, observed=NOW - timedelta(hours=age))
        r2 = budget_control.QuotaRouter.build(db2, s2, now=NOW)
        assert r2.availability(qr.RUNNERS["worker_gpt"], "ordinary").state == "unknown"


def test_extrapolation_adds_this_instances_agent_hours(tmp_path) -> None:
    _, db = qr._setup(tmp_path)
    settings = qr._settings(stale_estimate_hours=48, estimate_fraction_per_agent_hour=0.01)
    observed = NOW - timedelta(hours=8)
    window = {"name": "seven_day", "used_fraction": 0.5, "window_minutes": 10_080,
              "resets_at": budget_control._iso(NOW + timedelta(days=2))}
    _reading(db, settings, "worker_gpt", window, observed=observed)
    base = budget_control.QuotaRouter.build(db, settings, now=NOW).readings[GPT]["seven_day"]
    qr._enqueue(db, "g", "cg", runner="worker_gpt")
    db.claim_next_task(owner="t", lease_seconds=60)
    with db.connect() as connection:
        connection.execute(
            "INSERT INTO task_attempts (attempt_id, task_id, attempt_number, status, lease_owner,"
            " started_at, finished_at, created_at) VALUES ('a', 'g', 9, 'succeeded', 't', ?, ?, ?)",
            (budget_control._iso(NOW - timedelta(hours=4)),
             budget_control._iso(NOW - timedelta(hours=2)), budget_control._iso(NOW)),
        )
    with_usage = budget_control.QuotaRouter.build(db, settings, now=NOW).readings[GPT]
    # Own 2 agent-hours, plus the window's average pace (0.5 over 112 h) for the
    # 2 h the instance was actually active -- not for all 8 h since the reading.
    assert with_usage["seven_day"].used_fraction == pytest.approx(
        base.used_fraction + 2 * 0.01 + 0.5 / 112 * 2, rel=1e-3
    )


def test_stopped_loop_and_dead_workers_do_not_inflate_stale_readings(tmp_path) -> None:
    _, db = qr._setup(tmp_path)
    settings = qr._settings(stale_estimate_hours=48, estimate_fraction_per_agent_hour=0.01)
    observed = NOW - timedelta(hours=40)
    window = {"name": "seven_day", "used_fraction": 0.84, "window_minutes": 10_080,
              "resets_at": budget_control._iso(NOW + timedelta(days=3))}
    _reading(db, settings, "worker_gpt", window, observed=observed)
    qr._enqueue(db, "g", "cg", runner="worker_gpt")
    db.claim_next_task(owner="t", lease_seconds=60)
    with db.connect() as connection:
        # A worker that died with the loop: never finished, lease long expired.
        connection.execute(
            "UPDATE tasks SET status='running', current_attempt_id='dead', lease_expires_at=?"
            " WHERE task_id='g'",
            (budget_control._iso(NOW - timedelta(hours=38)),),
        )
        connection.execute(
            "INSERT INTO task_attempts (attempt_id, task_id, attempt_number, status, lease_owner,"
            " started_at, created_at) VALUES ('dead', 'g', 9, 'running', 't', ?, ?)",
            (budget_control._iso(NOW - timedelta(hours=39)), budget_control._iso(NOW)),
        )
    estimate = budget_control.QuotaRouter.build(db, settings, now=NOW).readings[GPT]
    # One hour of real activity, not 39 hours of a dead lease.
    assert estimate["seven_day"].used_fraction == pytest.approx(
        0.84 + 0.01 + 0.84 / 56 * 1, rel=1e-3
    )
    assert estimate["seven_day"].used_fraction < 0.9


def test_stale_extrapolation_is_capped(tmp_path) -> None:
    _, db = qr._setup(tmp_path)
    settings = qr._settings(stale_estimate_hours=48, estimate_fraction_per_agent_hour=0.05)
    observed = NOW - timedelta(hours=20)
    window = {"name": "seven_day", "used_fraction": 0.5, "window_minutes": 10_080,
              "resets_at": budget_control._iso(NOW + timedelta(days=3))}
    _reading(db, settings, "worker_gpt", window, observed=observed)
    qr._enqueue(db, "g", "cg", runner="worker_gpt")
    with db.connect() as connection:
        for index in range(6):
            connection.execute(
                "INSERT INTO task_attempts (attempt_id, task_id, attempt_number, status,"
                " lease_owner, started_at, finished_at, created_at)"
                " VALUES (?, 'g', ?, 'succeeded', 't', ?, ?, ?)",
                (f"a{index}", index + 1, budget_control._iso(NOW - timedelta(hours=19)),
                 budget_control._iso(NOW - timedelta(hours=1)), budget_control._iso(NOW)),
            )
    estimate = budget_control.QuotaRouter.build(db, settings, now=NOW).readings[GPT]
    assert estimate["seven_day"].used_fraction == pytest.approx(
        0.5 + budget_control.STALE_ESTIMATE_MAX_INCREASE
    )


def test_stale_codex_reading_is_refreshed_on_its_own_interval(tmp_path, monkeypatch) -> None:
    _, db = qr._setup(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(budget_control, "probe_quota",
                        lambda settings, provider, run=None: calls.append(provider))
    settings = qr._settings(codex_sessions_dir=str(tmp_path), stale_refresh_minutes=10,
                            probe_idle_minutes=360)
    for minutes in (0, 5, 11):
        budget_control.probe_stale_providers(db, settings, now=NOW + timedelta(minutes=minutes))
    assert calls == [GPT, GPT]
    _, db2 = qr._setup(tmp_path / "default")
    calls.clear()
    default = qr._settings(codex_sessions_dir=str(tmp_path))
    for minutes in (0, 11):
        budget_control.probe_stale_providers(db2, default, now=NOW + timedelta(minutes=minutes))
    assert calls == [GPT]

