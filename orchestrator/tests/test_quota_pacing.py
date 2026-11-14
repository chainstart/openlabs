"""Owner rule 2026-11-14: 80% ordinary / 90% hard ceilings, front-loaded pacing that
reaches them only on a window's last day, manual overrides, and a quiet pause."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
import test_quota_routing as qr
from openlabs import budget as budget_control
from openlabs import engine
from openlabs.config import DEFAULT_PACE_CURVE, RoutingSettings, parse_pace_curve

NOW = qr.NOW
GPT, CLAUDE = qr.GPT, qr.CLAUDE
WEEK = 10_080
ROUTING = RoutingSettings()


def _reading(used: float, *, day: float, minutes: int = WEEK, observed=NOW, name="seven_day",
             provider=GPT) -> budget_control.WindowReading:
    """A reading ``day`` days into its window (for a 7-day window)."""

    start = NOW - timedelta(days=day)
    return budget_control.WindowReading(
        provider=provider, name=name, used_fraction=used, window_minutes=minutes,
        resets_at=start + timedelta(minutes=minutes), observed_at=observed,
    )


def _allowed(klass: str, day: float, *, minutes: int = WEEK, routing=ROUTING) -> float:
    factor = budget_control.pace_factor(_reading(0.0, day=day, minutes=minutes), routing,
                                        now=NOW)
    return budget_control.window_ceiling(
        routing, klass=klass, protected_window=False, protected_runner=False, factor=factor
    )


def _record_window(db, settings, runner: str, used: float, *, day: float,
                   observed: datetime = NOW, name: str = "seven_day") -> None:
    spec = qr.RUNNERS[runner]
    start = NOW - timedelta(days=day)
    budget_control.record_quota_snapshot(db, settings, {
        "provider": spec.provider, "observed_at": budget_control._iso(observed),
        "model": spec.model, "windows": [
            {"name": name, "used_fraction": used, "window_minutes": WEEK,
             "resets_at": budget_control._iso(start + timedelta(days=7))}]}, runner=runner)


# ------------------------------------------------------------------ the pace line


@pytest.mark.parametrize(
    ("day", "factor"),
    [(1, 0.3125), (2, 0.525), (3, 0.6875), (4, 0.8125), (5, 0.9125), (6, 1.0), (6.5, 1.0)],
)
def test_front_loaded_curve_at_the_end_of_each_day(day, factor) -> None:
    got = budget_control.pace_factor(_reading(0.0, day=day), ROUTING, now=NOW)
    assert got == pytest.approx(factor, abs=2e-4)
    assert _allowed("ordinary", day) == pytest.approx(min(0.8, 0.8 * factor), abs=2e-4)
    assert _allowed("review", day) == pytest.approx(min(0.9, 0.9 * factor), abs=2e-4)
    assert _allowed("decision", day) == _allowed("review", day)


def test_ceilings_are_reached_only_on_the_last_day() -> None:
    # Ends of days 1..5 for ordinary work: about 25, 42, 55, 65, 73 %.
    assert [round(_allowed("ordinary", d), 2) for d in (1, 2, 3, 4, 5)] == [
        0.25, 0.42, 0.55, 0.65, 0.73]
    for hours in range(0, 6 * 24 - 1):
        day = hours / 24
        assert _allowed("ordinary", day) < 0.8
        assert _allowed("review", day) < 0.9
    # Two days before the reset no class has more than 0.9125 of its ceiling:
    # the last part can only be spent in the final day.
    assert _allowed("ordinary", 5) <= 0.8 * 0.9125 + 1e-9
    assert _allowed("review", 5) <= 0.9 * 0.9125 + 1e-9
    assert _allowed("ordinary", 6) == pytest.approx(0.8)
    assert _allowed("decision", 6.9) == pytest.approx(0.9)


def test_start_allowance_lets_a_fresh_window_begin() -> None:
    assert _allowed("ordinary", 0) == pytest.approx(0.05)
    assert _allowed("review", 1 / 24) == pytest.approx(0.05)
    # The floor never lifts the line once the line is above it.
    assert _allowed("ordinary", 1) == pytest.approx(0.8 * 0.3125, abs=2e-4)


def test_short_windows_are_capped_not_paced() -> None:
    five_hour = _reading(0.0, day=10 / 1440, minutes=300)
    assert budget_control.pace_factor(five_hour, ROUTING, now=NOW) is None
    assert _allowed("ordinary", 10 / 1440, minutes=300) == 0.8
    assert _allowed("review", 1 / 24, minutes=300) == 0.9
    # Two days is the shortest paced window.
    assert budget_control.pace_factor(_reading(0.0, day=0.5, minutes=2 * 1440), ROUTING,
                                      now=NOW) is not None


def test_pace_curve_configuration_is_validated(tmp_path) -> None:
    assert parse_pace_curve([[0, 0], [0.8571, 1]]) == ((0.0, 0.0), (0.8571, 1.0))
    for bad in ([[0, 0], [0.5, 0.6], [0.7, 0.5], [0.9, 1]],  # factor decreases
                [[0, 0], [0.9, 0.95]],                       # does not end at 1
                [[0.1, 0], [0.9, 1]],                        # does not start at 0
                [[0, 0], [0.5, 0.5], [0.5, 1]],              # share not increasing
                [[0, 0], [1.2, 1]]):
        with pytest.raises(ValueError, match="pace_curve"):
            parse_pace_curve(bad)
    with pytest.raises(ValueError, match="pace_curve"):
        qr._write_and_load(tmp_path / "bad", "[routing]\npace_curve = [[0, 0], [0.9, 0.95]]\n")
    settings = qr._write_and_load(
        tmp_path / "good",
        "[routing]\nordinary_ceiling = 0.7\nhard_ceiling = 0.85\npace_lead = 0.02\n"
        "pace_curve = [[0, 0], [0.8571, 1]]\noverride_max_ceiling = 1.0\n",
    )
    routing = settings.routing
    assert (routing.ordinary_ceiling, routing.hard_ceiling, routing.pace_lead) == (0.7, 0.85, 0.02)
    assert routing.pace_curve == ((0.0, 0.0), (0.8571, 1.0))
    assert routing.override_max_ceiling == 0.99  # never 100%
    # Linear pacing: halfway to the last day, half the ceiling.
    assert _allowed("ordinary", 3, routing=routing) == pytest.approx(0.35, abs=1e-3)
    defaults = qr._write_and_load(tmp_path / "defaults", "")
    assert defaults.routing.pace_curve == DEFAULT_PACE_CURVE
    assert (defaults.routing.ordinary_ceiling, defaults.routing.hard_ceiling) == (0.8, 0.9)


# --------------------------------------------------------------- availability


def test_three_classes_and_resume_time_on_the_pace_line(tmp_path) -> None:
    _, db = qr._setup(tmp_path)
    settings = qr._settings()
    # End of day 3: ordinary 0.55, review/decision 0.619.
    _record_window(db, settings, "worker_gpt", 0.58, day=3)
    router = budget_control.QuotaRouter.build(db, settings, now=NOW)
    ordinary = router.availability(qr.RUNNERS["worker_gpt"], "ordinary")
    assert (ordinary.state, ordinary.reason) == ("unavailable", "pace")
    assert router.availability(qr.RUNNERS["lead_gpt"], "review").usable
    assert router.availability(qr.RUNNERS["lead_gpt"], "decision").usable
    # 0.58 / 0.8 = 0.725 of the ceiling: between day 3 (0.6875) and day 4 (0.8125).
    expected = NOW - timedelta(days=3) + timedelta(days=7) * (
        0.4286 + (0.5714 - 0.4286) * (0.725 - 0.6875) / (0.8125 - 0.6875))
    assert abs((ordinary.resume_at - expected).total_seconds()) < 60
    later = budget_control.QuotaRouter.build(db, settings, now=expected + timedelta(minutes=5))
    assert later.availability(qr.RUNNERS["worker_gpt"], "ordinary").usable


def test_hard_ceiling_stops_every_class_until_the_reset(tmp_path) -> None:
    _, db = qr._setup(tmp_path)
    settings = qr._settings()
    _record_window(db, settings, "worker_gpt", 0.9, day=6.5)
    router = budget_control.QuotaRouter.build(db, settings, now=NOW)
    for runner, klass in (("worker_gpt", "ordinary"), ("lead_gpt", "review"),
                          ("lead_gpt", "decision")):
        state = router.availability(qr.RUNNERS[runner], klass)
        assert (state.state, state.reason) == ("unavailable", "ceiling")
        assert state.resume_at == NOW + timedelta(days=0.5)


def test_stale_reading_never_bypasses_the_ceiling(tmp_path) -> None:
    _, db = qr._setup(tmp_path)
    settings = qr._settings()
    # Observed 10 h ago (stale) at 0.85 in a window that has not reset: still blocked.
    _record_window(db, settings, "worker_gpt", 0.85, day=6.5, observed=NOW - timedelta(hours=10))
    _record_window(db, settings, "worker_claude", 0.1, day=3, observed=NOW - timedelta(hours=10))
    router = budget_control.QuotaRouter.build(db, settings, now=NOW)
    gpt = router.availability(qr.RUNNERS["worker_gpt"], "ordinary")
    assert (gpt.state, gpt.reason) == ("unavailable", "ceiling")
    assert gpt.windows[0]["stale"] is True
    # A stale reading below its allowance stays unknown (parallelism 1).
    assert router.availability(qr.RUNNERS["worker_claude"], "ordinary").state == "unknown"


def test_fable_keeps_the_stricter_of_its_protection_and_the_pace(tmp_path) -> None:
    _, db = qr._setup(tmp_path)
    settings = qr._settings()
    fable = qr.RUNNERS["lead_claude"]

    def record(shared: float, overage: float, day: float) -> budget_control.QuotaRouter:
        for name, used in (("seven_day", shared), ("seven_day_overage_included", overage)):
            _record_window(db, settings, "lead_claude", used, day=day, name=name,
                           observed=NOW + timedelta(seconds=len(db.events())))
        return budget_control.QuotaRouter.build(db, settings, now=NOW)

    # Late in the window the pace allows 0.82 but Fable reviews stop at 0.60.
    router = record(0.3, 0.62, day=5)
    review = router.availability(fable, "review")
    assert (review.state, review.reason) == ("unavailable", "lead_reserve")
    assert router.availability(fable, "decision").usable
    # Early in the window the pace line (0.25 x 0.9 on day 1) is the stricter one.
    router = record(0.3, 0.3, day=1)
    review = router.availability(fable, "review")
    assert (review.state, review.reason) == ("unavailable", "pace")
    assert router.availability(fable, "decision").state == "unavailable"
    # Reviews on other Claude runners keep Fable's decision reserve (1 - 0.25).
    assert budget_control.window_ceiling(
        settings.routing, klass="review", protected_window=True, protected_runner=False,
        factor=1.0) == 0.75


def test_current_readings_of_2026_11_14_do_not_stall_the_loop(tmp_path) -> None:
    _, db = qr._setup(tmp_path)
    settings = qr._settings()
    moment = datetime.fromisoformat("2026-11-14T04:00:00+00:00")
    reset = "2026-11-16T11:00:00Z"
    budget_control.record_quota_snapshot(db, settings, {
        "provider": CLAUDE, "observed_at": budget_control._iso(moment),
        "model": "claude-fable-5-2", "windows": [
            {"name": "seven_day", "used_fraction": 0.56, "window_minutes": WEEK,
             "resets_at": reset},
            {"name": "seven_day_overage_included", "used_fraction": 0.39,
             "window_minutes": WEEK, "resets_at": reset}]}, runner="lead_claude")
    budget_control.record_quota_snapshot(db, settings, {
        "provider": GPT, "observed_at": budget_control._iso(moment), "model": "gpt-6-astra",
        "windows": [{"name": "seven_day", "used_fraction": 0.0, "window_minutes": WEEK,
                     "resets_at": "2026-11-21T02:56:00Z"}]}, runner="lead_gpt")
    router = budget_control.QuotaRouter.build(db, settings, now=moment)
    for spec in qr.RUNNERS.values():
        for klass in budget_control.TASK_CLASSES:
            if spec.protected and klass != "decision":
                continue  # Fable's own 60% review line is not at issue here
            assert router.availability(spec, klass).usable, (spec.name, klass)
    assert router.pause_summary()["paused"] is False


# ------------------------------------------------------------- pause in the loop


def _blocked_both(db, settings, *, day: float = 2.0) -> None:
    # End of day 2: ordinary 0.42, reviews/decisions 0.4725 -- both families past it.
    for runner in ("worker_gpt", "worker_claude", "lead_claude"):
        _record_window(db, settings, runner, 0.5, day=day)
    _record_window(db, settings, "lead_claude", 0.5, day=day, name="seven_day_overage_included")


def test_both_providers_paced_out_pause_quietly_and_say_when(tmp_path, qr_clock,
                                                             monkeypatch) -> None:
    paths, db = qr._setup(tmp_path)
    settings = replace(qr._settings(), reserve_cpu_threads=0, reserve_memory_mib=0,
                       reserve_scratch_mib=0)
    _blocked_both(db, settings)
    qr._enqueue(db, "research", "c1", runner="balanced")
    qr._enqueue(db, "review", "c2", runner="frontier", task_type="paper_review",
                agent_role="reviewer")
    qr._enqueue(db, "decide", "c3", runner=None, task_type="direction_decision")
    with db.connect() as connection:
        connection.execute("UPDATE tasks SET cpu_threads=0, memory_mib=0, scratch_mib=0")
    launched: list[str] = []
    monkeypatch.setattr(engine, "_launch_task",
                        lambda _db, _p, _s, task, owner: launched.append(task["task_id"]))
    tasks_before = sum(db.status_counts().values())
    reports = [engine.tick(paths, settings) for _ in range(3)]

    assert launched == []
    assert all(report.errors == [] for report in reports)
    assert sum(db.status_counts().values()) == tasks_before  # no replan / decision spawned
    pause = reports[-1].to_dict()["quota_pause"]
    assert pause["all_paused"] is True
    assert all(pause["classes"][k]["reasons"] == ["pace"] for k in ("ordinary", "review"))
    assert "因额度配速暂停" in pause["message"]
    resume = budget_control.parse_time(pause["resume_at"])
    assert NOW < resume < NOW + timedelta(days=1)
    # Every deferral and the pause itself are logged once, not every tick.
    deferred = [e for e in db.events() if e["event_type"] == "routing_deferred"]
    assert len(deferred) == 3
    assert all(e["payload"].get("resume_at") for e in deferred)
    assert [e["event_type"] for e in db.events() if e["entity_id"] == "quota_pause"] == [
        "quota_paused"]
    # The 90% line passes the use first: reviews and decisions resume; ordinary
    # work follows when the 80% line does.
    ordinary_resume = budget_control.parse_time(pause["classes"]["ordinary"]["resume_at"])
    assert ordinary_resume > resume
    qr_clock["now"] = resume + timedelta(minutes=10)
    report = engine.tick(paths, settings)
    assert sorted(launched) == ["decide", "review"] and report.errors == []
    assert report.quota_pause["classes"]["ordinary"]["paused"] is True
    qr_clock["now"] = ordinary_resume + timedelta(minutes=10)
    report = engine.tick(paths, settings)
    assert "research" in launched and report.errors == []
    assert [e["event_type"] for e in db.events() if e["entity_id"] == "quota_pause"] == [
        "quota_paused", "quota_paused", "quota_resumed"]


@pytest.fixture
def qr_clock(monkeypatch):
    state = {"now": NOW}
    monkeypatch.setattr(budget_control, "current_time", lambda: state["now"])
    return state


# ------------------------------------------------------------------ overrides


def test_provider_override_lifts_pacing_expires_and_can_be_revoked(tmp_path, qr_clock) -> None:
    paths, db = qr._setup(tmp_path)
    settings = qr._settings()
    _record_window(db, settings, "worker_gpt", 0.6, day=2)
    spec = qr.RUNNERS["worker_gpt"]
    assert not budget_control.QuotaRouter.build(db, settings, now=NOW).usable(spec, "ordinary")

    with pytest.raises(budget_control.QuotaOverrideError, match="ceiling"):
        budget_control.set_quota_override(db, settings, provider=GPT, until="2026-11-12T00:00Z",
                                          reason="x", ceiling=1.0, now=NOW)
    with pytest.raises(budget_control.QuotaOverrideError, match="future"):
        budget_control.set_quota_override(db, settings, provider=GPT, until="2026-11-10T00:00Z",
                                          reason="x", now=NOW)
    with pytest.raises(budget_control.QuotaOverrideError, match="provider"):
        budget_control.set_quota_override(db, settings, provider="nobody",
                                          until="2026-11-12T00:00Z", reason="x", now=NOW)
    entry = budget_control.set_quota_override(
        db, settings, provider=GPT, until="2026-11-11T12:00Z", reason="burn before reset",
        ceiling=0.97, now=NOW)
    router = budget_control.QuotaRouter.build(db, settings, now=NOW)
    state = router.availability(spec, "ordinary")
    assert state.usable and state.override == 0.97
    assert router.availability(qr.RUNNERS["worker_claude"], "ordinary").override is None
    assert router.provider_summary()[GPT]["override"]["reason"] == "burn before reset"
    # Shown in the tick report.
    report = engine.tick(paths, replace(settings, launch_jobs=False))
    assert report.to_dict()["quota_pause"]["overrides"][GPT]["ceiling"] == 0.97
    # Even an override stops at its own ceiling (never 100%).
    _record_window(db, settings, "worker_gpt", 0.97, day=2, observed=NOW + timedelta(seconds=1))
    state = budget_control.QuotaRouter.build(db, settings, now=NOW).availability(spec, "decision")
    assert (state.state, state.reason) == ("unavailable", "override_ceiling")
    _record_window(db, settings, "worker_gpt", 0.6, day=2, observed=NOW + timedelta(seconds=2))

    # Expiry: ignored after ``until`` and removed by the next tick with one event.
    qr_clock["now"] = NOW + timedelta(hours=7)
    assert budget_control.active_quota_overrides(db, settings, now=qr_clock["now"]) == {}
    report = engine.tick(paths, replace(settings, launch_jobs=False))
    assert report.quota_overrides_expired == [GPT]
    assert budget_control.quota_overrides(db) == {}

    # Revocation before expiry.
    budget_control.set_quota_override(db, settings, provider=GPT, until="2026-11-12T00:00Z",
                                      reason="again", now=qr_clock["now"])
    assert budget_control.revoke_quota_override(db, provider=GPT, reason="done")["ceiling"] == 0.9
    assert budget_control.revoke_quota_override(db, provider=GPT) is None
    kinds = [e["event_type"] for e in db.events() if e["event_type"].startswith("quota_override")]
    assert kinds == ["quota_override_set", "quota_override_expired", "quota_override_set",
                     "quota_override_revoked"]
    assert entry["until"] == "2026-11-11T12:00:00Z"


def test_override_keeps_fables_protection(tmp_path) -> None:
    _, db = qr._setup(tmp_path)
    settings = qr._settings()
    for name, used in (("seven_day", 0.5), ("seven_day_overage_included", 0.65)):
        _record_window(db, settings, "lead_claude", used, day=2, name=name)
    budget_control.set_quota_override(db, settings, provider=CLAUDE, until="2026-11-12T00:00Z",
                                      reason="test", ceiling=0.95, now=NOW)
    router = budget_control.QuotaRouter.build(db, settings, now=NOW)
    fable = qr.RUNNERS["lead_claude"]
    assert router.availability(fable, "review").reason == "lead_reserve"
    assert router.availability(fable, "decision").usable
    assert router.availability(qr.RUNNERS["worker_claude"], "ordinary").usable


def test_manually_flagged_task_breaks_the_pacing_but_not_100_percent(tmp_path) -> None:
    _, db = qr._setup(tmp_path)
    settings = qr._settings()
    _blocked_both(db, settings)
    qr._enqueue(db, "auto", "c1", runner="balanced", priority=5)
    qr._enqueue(db, "manual", "c2", runner="balanced")
    budget_control.mark_task_quota_override(db, "manual", reason="owner asked")
    task, router = qr._claim(db, settings)
    assert task["task_id"] == "manual"
    assert router.decisions["manual"]["manual_quota_override"] is True
    assert router.decisions["manual"]["quota_override"] == 0.99
    assert router.deferred["auto"]["quota_reasons"] == ["pace"]
    with pytest.raises(budget_control.QuotaOverrideError):
        budget_control.mark_task_quota_override(db, "x", reason=" ")
    # At 99% even a flagged task waits.
    for runner in ("worker_gpt", "worker_claude"):
        _record_window(db, settings, runner, 0.99, day=2, observed=NOW + timedelta(seconds=1))
    qr._enqueue(db, "manual2", "c3", runner="balanced")
    budget_control.mark_task_quota_override(db, "manual2", reason="owner asked")
    task, _router = qr._claim(db, settings)
    assert task is None


def test_quota_override_command_sets_lists_and_revokes(tmp_path, monkeypatch, capsys) -> None:
    from openlabs import __main__ as cli

    paths, db = qr._setup(tmp_path)
    settings = qr._settings()
    monkeypatch.setattr(budget_control, "current_time", lambda: NOW)
    monkeypatch.setattr(cli, "workspace_paths", lambda _workspace=None: paths)
    monkeypatch.setattr(cli, "load_settings", lambda _paths: settings)
    assert cli.main(["program", "quota-override", "--provider", GPT, "--until",
                     "2026-11-12T00:00Z", "--ceiling", "0.97", "--reason", "owner"]) == 0
    assert json.loads(capsys.readouterr().out)["set"]["ceiling"] == 0.97
    assert cli.main(["program", "quota-override", "--list"]) == 0
    assert set(json.loads(capsys.readouterr().out)["active"]) == {GPT}
    assert cli.main(["program", "quota-override", "--provider", GPT, "--until",
                     "2026-11-12T00:00Z", "--ceiling", "1.0", "--reason", "x"]) == 1
    capsys.readouterr()
    assert cli.main(["program", "quota-override", "--provider", GPT, "--revoke"]) == 0
    assert json.loads(capsys.readouterr().out)["revoked"]["provider"] == GPT
    assert cli.main(["enqueue", "--campaign-id", "c", "--domain", "math", "--objective", "x",
                     "--quota-override"]) == 1
    capsys.readouterr()
    assert cli.main(["enqueue", "--campaign-id", "c", "--domain", "math", "--objective", "x",
                     "--quota-override", "--quota-override-reason", "owner"]) == 0
    task_id = json.loads(capsys.readouterr().out)["task_id"]
    assert task_id in budget_control._task_overrides(db)
