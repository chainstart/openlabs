"""Per-provider quota ceilings (``[routing.provider_ceilings.<provider>]``).

Owner request 2026-11-16: Claude's (anthropic) ordinary ceiling in automatic
research goes from 80% to 70%; Codex (openai-codex) keeps 80%, and the 90%
hard ceiling of reviews and decisions stays for both.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import timedelta

import pytest
import test_quota_pacing as qp
import test_quota_routing as qr
from openlabs import budget as budget_control
from openlabs import owner as owner_mode
from openlabs import utilization
from openlabs.config import BudgetSettings, RoutingSettings, parse_provider_ceilings
from test_utilization_routing import _gpt_resets_soon_claude_later

NOW = qr.NOW
GPT, CLAUDE = qr.GPT, qr.CLAUDE
CLAUDE_70 = {CLAUDE: (0.7, 0.9)}

RUNNERS_TOML = """
[runners.lead_claude]
provider = "anthropic"
tier = "lead"
model = "claude-fable-5-2"
[runners.worker_gpt]
provider = "openai-codex"
tier = "worker"
model = "gpt-6.1-sol"
"""


def _settings(**routing):
    return qr._settings(**routing)


def _state(settings, runner: str, klass: str, used: float, *, day: float, tmp_path):
    _, db = qr._setup(tmp_path)
    qp._record_window(db, settings, runner, used, day=day)
    router = budget_control.QuotaRouter.build(db, settings, now=NOW)
    return router.availability(qr.RUNNERS[runner], klass)


# ------------------------------------------------------------------ configuration


def test_without_overrides_every_provider_uses_the_global_pair(tmp_path) -> None:
    routing = RoutingSettings()
    assert routing.provider_ceilings == {}
    assert routing.for_provider(CLAUDE) is routing
    assert routing.ceilings_for(CLAUDE) == routing.ceilings_for(GPT) == (0.8, 0.9)
    loaded = qr._write_and_load(tmp_path, RUNNERS_TOML + "[routing]\nordinary_ceiling = 0.8\n")
    assert loaded.routing.provider_ceilings == {}


def test_provider_override_loads_from_toml(tmp_path) -> None:
    settings = qr._write_and_load(tmp_path / "a", RUNNERS_TOML + """
[routing]
ordinary_ceiling = 0.8
hard_ceiling = 0.9
[routing.provider_ceilings.anthropic]
ordinary_ceiling = 0.7
""")
    routing = settings.routing
    assert (routing.ordinary_ceiling, routing.hard_ceiling) == (0.8, 0.9)
    assert routing.provider_ceilings == {CLAUDE: (0.7, 0.9)}
    assert routing.ceilings_for(CLAUDE) == (0.7, 0.9)
    assert routing.ceilings_for(GPT) == (0.8, 0.9)
    narrowed = routing.for_provider(CLAUDE)
    assert (narrowed.ordinary_ceiling, narrowed.hard_ceiling) == (0.7, 0.9)
    assert routing.for_provider(GPT) is routing
    # A hard override alone lowers an inherited ordinary ceiling to it.
    assert parse_provider_ceilings({GPT: {"hard_ceiling": 0.75}}, ordinary=0.8, hard=0.9) == {
        GPT: (0.75, 0.75)}
    assert parse_provider_ceilings({GPT: {"hard_ceiling": 0.95, "ordinary_ceiling": 0.85}},
                                   ordinary=0.8, hard=0.9) == {GPT: (0.85, 0.95)}


@pytest.mark.parametrize(
    ("table", "message"),
    [
        ({CLAUDE: {"ordinary_ceiling": 0.95}}, "must not exceed its hard_ceiling"),
        ({CLAUDE: {"ordinary_ceiling": 0.8, "hard_ceiling": 0.7}}, "must not exceed"),
        ({CLAUDE: {"ordinary_ceiling": 0}}, r"in \(0, 1\]"),
        ({CLAUDE: {"ordinary_ceiling": 1.5}}, r"in \(0, 1\]"),
        ({CLAUDE: {"ordinary_ceiling": "0.7"}}, "must be a number"),
        ({CLAUDE: {"ordinary_ceiling": True}}, "must be a number"),
        ({CLAUDE: {"ordinary": 0.7}}, "unknown key"),
        ({CLAUDE: 0.7}, "must be a table"),
        ([0.7], "table of provider tables"),
    ],
)
def test_invalid_provider_ceilings_are_rejected(table, message) -> None:
    with pytest.raises(ValueError, match=message):
        parse_provider_ceilings(table, ordinary=0.8, hard=0.9)


def test_unknown_provider_in_provider_ceilings_is_rejected(tmp_path) -> None:
    with pytest.raises(ValueError, match="unknown provider.*claude"):
        qr._write_and_load(tmp_path, RUNNERS_TOML + """
[routing.provider_ceilings.claude]
ordinary_ceiling = 0.7
""")
    with pytest.raises(ValueError, match="provider_ceilings.anthropic.*ordinary_ceiling"):
        qr._write_and_load(tmp_path / "b", RUNNERS_TOML + """
[routing.provider_ceilings.anthropic]
ordinary_ceiling = 0.95
""")


# ------------------------------------------------------------------ availability


@pytest.mark.parametrize("runner", ["worker_gpt", "worker_claude", "lead_gpt"])
@pytest.mark.parametrize("klass", ["ordinary", "review", "decision"])
@pytest.mark.parametrize(("used", "day"), [(0.3, 1), (0.58, 3), (0.72, 6.5), (0.86, 6.5)])
def test_overrides_equal_to_the_global_values_change_nothing(tmp_path, runner, klass, used,
                                                             day) -> None:
    base = _state(_settings(), runner, klass, used, day=day, tmp_path=tmp_path / "a")
    same = _state(_settings(provider_ceilings={CLAUDE: (0.8, 0.9), GPT: (0.8, 0.9)}),
                  runner, klass, used, day=day, tmp_path=tmp_path / "b")
    assert same.to_dict() == base.to_dict()


@pytest.mark.parametrize("klass", ["ordinary", "decision"])
@pytest.mark.parametrize(("used", "day"), [(0.3, 1), (0.5, 3), (0.72, 6.5), (0.86, 6.5)])
def test_claude_override_equals_a_global_70_percent_for_claude(tmp_path, klass, used,
                                                               day) -> None:
    globally = _state(_settings(ordinary_ceiling=0.7), "worker_claude", klass, used, day=day,
                      tmp_path=tmp_path / "a")
    per_provider = _state(_settings(provider_ceilings=CLAUDE_70), "worker_claude", klass, used,
                          day=day, tmp_path=tmp_path / "b")
    assert per_provider.to_dict() == globally.to_dict()


def test_claude_ordinary_work_stops_at_70_percent_codex_at_80(tmp_path) -> None:
    settings = _settings(provider_ceilings=CLAUDE_70)
    # Last day: the pace line is at the full ceiling.
    claude = _state(settings, "worker_claude", "ordinary", 0.72, day=6.5, tmp_path=tmp_path / "c")
    assert (claude.state, claude.reason) == ("unavailable", "ceiling")
    assert claude.windows[0]["cap"] == 0.7
    assert claude.resume_at == NOW + timedelta(days=0.5)  # only the reset helps
    below = _state(settings, "worker_claude", "ordinary", 0.69, day=6.5, tmp_path=tmp_path / "d")
    assert below.usable
    gpt = _state(settings, "worker_gpt", "ordinary", 0.72, day=6.5, tmp_path=tmp_path / "g")
    assert gpt.usable and gpt.windows[0]["cap"] == 0.8
    gpt_stop = _state(settings, "worker_gpt", "ordinary", 0.8, day=6.5, tmp_path=tmp_path / "h")
    assert (gpt_stop.state, gpt_stop.reason) == ("unavailable", "ceiling")
    # Without the override the same Claude reading is still usable (0.75: Fable's reserve).
    assert _state(_settings(), "worker_claude", "ordinary", 0.72, day=6.5,
                  tmp_path=tmp_path / "x").usable


def test_claude_pace_line_scales_with_its_own_ceiling(tmp_path) -> None:
    settings = _settings(provider_ceilings=CLAUDE_70)
    # End of day 3 (factor 0.6875): Claude 0.7 x 0.6875 = 0.481, Codex 0.8 x 0.6875 = 0.55.
    claude = _state(settings, "worker_claude", "ordinary", 0.5, day=3, tmp_path=tmp_path / "c")
    assert (claude.state, claude.reason) == ("unavailable", "pace")
    assert claude.windows[0]["ceiling"] == pytest.approx(0.7 * 0.6875, abs=1e-4)
    assert claude.windows[0]["pace_factor"] == pytest.approx(0.6875, abs=1e-4)
    # Resumes where 0.7 x pace(share) passes 0.5: pace factor 0.5 / 0.7 = 0.714.
    factor = 0.5 / 0.7
    expected = NOW - timedelta(days=3) + timedelta(days=7) * (
        0.4286 + (0.5714 - 0.4286) * (factor - 0.6875) / (0.8125 - 0.6875))
    assert abs((claude.resume_at - expected).total_seconds()) < 60
    gpt = _state(settings, "worker_gpt", "ordinary", 0.5, day=3, tmp_path=tmp_path / "g")
    assert gpt.usable
    assert gpt.windows[0]["ceiling"] == pytest.approx(0.8 * 0.6875, abs=1e-4)


def test_reviews_and_decisions_keep_each_providers_hard_ceiling(tmp_path) -> None:
    settings = _settings(provider_ceilings=CLAUDE_70)
    # Claude decisions still go to 90%, ordinary Claude work stopped at 70%.
    decision = _state(settings, "worker_claude", "decision", 0.86, day=6.5,
                      tmp_path=tmp_path / "d")
    assert decision.usable and decision.windows[0]["cap"] == 0.9
    review = _state(settings, "lead_gpt", "review", 0.86, day=6.5, tmp_path=tmp_path / "r")
    assert review.usable and review.windows[0]["cap"] == 0.9
    # A hard override of its own applies to that provider's reviews and decisions only.
    strict = _settings(provider_ceilings={CLAUDE: (0.7, 0.85)})
    held = _state(strict, "worker_claude", "decision", 0.86, day=6.5, tmp_path=tmp_path / "s")
    assert (held.state, held.reason) == ("unavailable", "ceiling")
    assert _state(strict, "lead_gpt", "decision", 0.86, day=6.5, tmp_path=tmp_path / "t").usable


def test_class_ceiling_takes_the_provider(tmp_path) -> None:
    routing = RoutingSettings(provider_ceilings=CLAUDE_70)
    assert budget_control.class_ceiling(routing, "ordinary", CLAUDE) == 0.7
    assert budget_control.class_ceiling(routing, budget_control.OWNER_CLASS, CLAUDE) == 0.7
    assert budget_control.class_ceiling(routing, "review", CLAUDE) == 0.9
    assert budget_control.class_ceiling(routing, "ordinary", GPT) == 0.8
    assert budget_control.class_ceiling(routing, "ordinary") == 0.8


# ------------------------------------------------------------------ reports and overrides


def test_tick_report_window_pace_shows_each_providers_ceiling(tmp_path) -> None:
    _, db = qr._setup(tmp_path)
    settings = _settings(utilization_target=0.9, provider_ceilings=CLAUDE_70)
    for runner in ("worker_gpt", "worker_claude"):
        qp._record_window(db, settings, runner, 0.3, day=6.5)
    router = budget_control.QuotaRouter.build(db, settings, now=NOW)
    summary = router.provider_summary()
    assert summary[CLAUDE]["window_pace"]["seven_day"]["cap"] == 0.7
    assert summary[CLAUDE]["window_pace"]["seven_day"]["ceiling"] == 0.7
    assert summary[GPT]["window_pace"]["seven_day"]["cap"] == 0.8
    pace = utilization.provider_pace(router)
    assert pace[CLAUDE]["windows"]["seven_day"]["cap"] == 0.7
    assert pace[GPT]["windows"]["seven_day"]["cap"] == 0.8


def test_utilization_view_reports_provider_ceilings(tmp_path, monkeypatch, capsys) -> None:
    from openlabs import __main__ as cli

    paths, db = qr._setup(tmp_path)
    settings = replace(_settings(utilization_target=0.9, provider_ceilings=CLAUDE_70),
                       budget=BudgetSettings(max_parallel_agents=8, adaptive_parallel=True))
    _gpt_resets_soon_claude_later(db, settings)
    monkeypatch.setattr(budget_control, "current_time", lambda: NOW)
    monkeypatch.setattr(cli, "workspace_paths", lambda _workspace=None: paths)
    monkeypatch.setattr(cli, "load_settings", lambda _paths: settings)
    monkeypatch.setattr(utilization, "gpu_usage", lambda: None)
    before = hashlib.sha256(paths.database_file.read_bytes()).hexdigest()
    assert cli.main(["program", "utilization", "--no-gpu"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert hashlib.sha256(paths.database_file.read_bytes()).hexdigest() == before
    rule = payload["quota_rule"]
    assert (rule["ordinary_ceiling"], rule["hard_ceiling"]) == (0.8, 0.9)
    assert rule["provider_ceilings"] == {
        CLAUDE: {"ordinary_ceiling": 0.7, "hard_ceiling": 0.9},
        GPT: {"ordinary_ceiling": 0.8, "hard_ceiling": 0.9},
    }
    assert payload["providers"][GPT]["abundance"] == pytest.approx(1.4, rel=1e-3)


def test_quota_override_defaults_to_the_providers_hard_ceiling(tmp_path) -> None:
    _, db = qr._setup(tmp_path)
    settings = _settings(provider_ceilings={CLAUDE: (0.7, 0.85)})
    claude = budget_control.set_quota_override(
        db, settings, provider=CLAUDE, until="2026-11-12T00:00Z", reason="x", now=NOW)
    gpt = budget_control.set_quota_override(
        db, settings, provider=GPT, until="2026-11-12T00:00Z", reason="x", now=NOW)
    assert (claude["ceiling"], gpt["ceiling"]) == (0.85, 0.9)
    # The upper bound is still override_max_ceiling, not the provider's hard ceiling.
    explicit = budget_control.set_quota_override(
        db, settings, provider=CLAUDE, until="2026-11-12T00:00Z", reason="x", ceiling=0.95,
        now=NOW)
    assert explicit["ceiling"] == 0.95
    with pytest.raises(budget_control.QuotaOverrideError, match="ceiling"):
        budget_control.set_quota_override(db, settings, provider=CLAUDE,
                                          until="2026-11-12T00:00Z", reason="x", ceiling=1.0,
                                          now=NOW)


def test_owner_brief_names_each_providers_ceiling() -> None:
    assert owner_mode._owner_ceiling_text(_settings()) == "80%"
    assert owner_mode._owner_ceiling_text(_settings(provider_ceilings=CLAUDE_70)) == (
        "70% (anthropic) / 80% (openai-codex)")
    same = _settings(provider_ceilings={CLAUDE: (0.8, 0.9)})
    assert owner_mode._owner_ceiling_text(same) == "80%"


def test_over_pace_forecast_with_an_open_allowance_still_reads_dispatch_allowed(tmp_path) -> None:
    """2026-11-16: openai-codex showed signal over (projected_above_ceiling) while the router
    kept dispatching owner seats to it; an owner read 'over' as a stop order. The view
    now states the router's own verdict per task class next to the forecast."""

    _, db = qr._setup(tmp_path)
    settings = _settings(utilization_target=0.9, provider_ceilings=CLAUDE_70)
    # Day 2 of 7: allowance 0.8 * 0.525 = 0.42 > 0.35 used, but 0.35 / (2/7) > 0.8.
    qp._record_window(db, settings, "worker_gpt", 0.35, day=2)
    # Claude at its pace line: nothing ordinary may start.
    qp._record_window(db, settings, "worker_claude", 0.6, day=2)
    router = budget_control.QuotaRouter.build(db, settings, now=NOW)
    pace = utilization.provider_pace(router)
    assert pace[GPT]["signal"] == "over" and pace[GPT]["reason"] == "projected_above_ceiling"
    assert pace[GPT]["state"] == "available"
    assert pace[GPT]["dispatch_allowed"][budget_control.OWNER_CLASS] == "yes"
    assert pace[GPT]["dispatch_allowed"]["ordinary"] == "yes"
    assert pace[CLAUDE]["signal"] == "over" and pace[CLAUDE]["state"] == "unavailable"
    assert pace[CLAUDE]["dispatch_allowed"][budget_control.OWNER_CLASS] == "no"
    # The verdict is the router's: an owner seat on the GPT lead is usable.
    assert owner_mode.runner_usable(settings, router, "lead_gpt") == (
        router.usable(qr.RUNNERS["lead_gpt"], budget_control.OWNER_CLASS))
    assert "dispatch_allowed" in pace[GPT]["signal_note"]
