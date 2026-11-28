"""Line-state table ``[program.lines.<id>]`` (mode, slots) and 8-key ``[program.supply]``."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from openlabs.config import (
    EVERY_LINE,
    LINE_STAGES,
    LineSettings,
    SupplySettings,
    load_program_settings,
)

INSTANCE = Path("/workspace/openlabs/openlabs-instances/cc-sg/openlabs.toml")


def test_table_modes_and_defaults() -> None:
    settings = load_program_settings({"polish_mode": False, "lines": {
        "a": {"mode": "full", "slots": 2},
        "b": {"mode": "supply_only"},
        "c": {"mode": "polish"},
        "d": {"mode": "off"},
    }})
    assert settings.config_warnings == ()
    assert settings.research_lines == ("a", "b", "c")  # "off" leaves the scout rotation
    assert settings.line_max_active_topics == {"a": 2}
    decisions = {
        line: (settings.stops("supply", line), settings.stops("research", line))
        for line in ("a", "b", "c", "d", "unlisted", None)
    }
    assert decisions == {
        "a": (False, False),
        "b": (False, True),
        "c": (True, True),
        "d": (True, True),
        "unlisted": (False, False),
        None: (False, False),
    }
    assert settings.stops("supply") is False  # "a" and unlisted lines still get supply
    stopped = load_program_settings({"polish_mode": True, "lines": {"a": {"mode": "polish"}}})
    assert stopped.stops("supply") is True and stopped.stops("research", EVERY_LINE) is True
    assert stopped.line("unlisted") == LineSettings(mode="polish")
    assert set(LINE_STAGES) == {"supply", "research"}


def test_supply_settings_eight_keys_and_defaults() -> None:
    defaults = load_program_settings({})
    assert defaults.config_warnings == ()
    assert defaults.grade_before_writing is True
    assert defaults.nc_journals == ("Nature Communications",)
    assert defaults.supply == SupplySettings(
        max_concurrent_scouts=2,
        scout_min_interval_hours=1.0,
        candidate_pool_size=4,
        scout_runners=(),
        scout_weekly_usd_per_line=100.0,
        max_topic_data_gb=2000.0,
        dedup_similarity=0.8,
        max_concurrent_reviews=4,
    )
    custom = load_program_settings(tomllib.loads("""
grade_before_writing = false
nc_journals = ["Nature Communications", "Science Advances"]
[supply]
max_concurrent_scouts = 3
scout_min_interval_hours = 0.5
candidate_pool_size = 5
scout_runners = ["worker_gemini"]
scout_weekly_usd_per_line = 120
max_topic_data_gb = 1500
dedup_similarity = 0.75
max_concurrent_reviews = 6
"""))
    assert custom.config_warnings == ()
    assert custom.grade_before_writing is False
    assert custom.nc_journals == ("Nature Communications", "Science Advances")
    assert custom.supply == SupplySettings(
        max_concurrent_scouts=3,
        scout_min_interval_hours=0.5,
        candidate_pool_size=5,
        scout_runners=("worker_gemini",),
        scout_weekly_usd_per_line=120.0,
        max_topic_data_gb=1500.0,
        dedup_similarity=0.75,
        max_concurrent_reviews=6,
    )


def test_removed_keys_warn_and_fallback_during_migration() -> None:
    raw = tomllib.loads("""
polish_mode = true
candidate_pool_low_water = 6
scout_min_interval_hours = 0.5
max_concurrent_scouts = 2
scout_runners = ["worker_gemini"]
[funnel]
scout_weekly_usd_per_line = 300
max_topic_data_gb = 1500
dedup_reject_similarity = 0.85
prescreen_max_concurrent = 4
grade_before_writing = false
nc_journals = ["Nature Communications"]
[lines.ml-evaluation-protocols]
mode = "full"
slots = 2
admission_min_band = "zone_2"
nc_aim = false
""")
    settings = load_program_settings(raw)
    assert settings.line("ml-evaluation-protocols") == LineSettings(mode="full", slots=2)
    assert settings.supply == SupplySettings(
        max_concurrent_scouts=2,
        scout_min_interval_hours=0.5,
        candidate_pool_size=6,
        scout_runners=("worker_gemini",),
        scout_weekly_usd_per_line=300.0,
        max_topic_data_gb=1500.0,
        dedup_similarity=0.85,
        max_concurrent_reviews=4,
    )
    assert settings.grade_before_writing is False
    assert any("[program] ignores removed key(s)" in w for w in settings.config_warnings)
    assert any("[program.funnel] was removed" in w for w in settings.config_warnings)
    assert any("[program.lines.ml-evaluation-protocols] ignores removed" in w
               for w in settings.config_warnings)


def test_live_instance_config_loads_cleanly() -> None:
    if not INSTANCE.is_file():
        pytest.skip("cc-sg instance configuration not present")
    program = tomllib.loads(INSTANCE.read_text(encoding="utf-8"))["program"]
    settings = load_program_settings(program)
    assert "open-nc-directions" in settings.lines
    assert settings.supply.max_topic_data_gb > 0
    assert settings.grade_before_writing is True


@pytest.mark.parametrize("bad", [
    {"a": {"mode": "paused"}},
    {"a": {"slots": -1}},
    {"a": {"slots": True}},
    {"a": {"seats": 1}},
    {"a": "full"},
    ["a"],
])
def test_table_rejects_nonsense(bad) -> None:
    with pytest.raises(ValueError, match="program.lines"):
        load_program_settings({"lines": bad})


def test_supply_rejects_unknown_key() -> None:
    with pytest.raises(ValueError, match="program.supply"):
        load_program_settings({"supply": {"not_a_real_key": 1}})


def test_tick_reports_config_warning(tmp_path, monkeypatch) -> None:
    import dataclasses

    import test_research_program_flow as flow

    paths = flow._paths(tmp_path)
    flow._install_program(paths)
    legacy = load_program_settings({"enabled": True, "research_lines": ["x"]})
    settings = dataclasses.replace(
        flow._settings(),
        program=dataclasses.replace(
            flow._settings().program, config_warnings=legacy.config_warnings
        ),
    )
    report = flow._tick(paths, settings, monkeypatch)
    assert any("ignores removed key(s)" in item for item in report.warnings)
