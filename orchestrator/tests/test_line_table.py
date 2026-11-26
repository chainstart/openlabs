"""One line-state table ``[program.lines.<id>]`` (slimming batch 2, 2026-11-26).

User 2026-11-26: "1-开始" (maintenance/20261126-pipeline-slimming/REPORT.md section 3, P2: the
line states in one table, polish_mode only the global default, three predicates in one). The
legacy keys are still read for one version; the consistency tests below show that the cc-sg
instance gets the same decision for every line and stage before and after the conversion, and
with the proposed table written out.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from openlabs.config import EVERY_LINE, LINE_STAGES, LineSettings, load_program_settings

INSTANCE = Path("/workspace/openlabs/openlabs-instances/cc-sg/openlabs.toml")

# The line keys of the cc-sg instance on 2026-11-26 (TM-T15 and its amendment).
SNAPSHOT = {
    "polish_mode": True,
    "polish_exempt_lines": ["ml-evaluation-protocols", "power-market-backtest"],
    "polish_supply_only_lines": ["astro-survey-photometry", "phm-evaluation-audit",
                                 "open-nc-directions"],
    "line_max_active_topics": {"astro-survey-photometry": 1, "power-market-backtest": 1,
                               "phm-evaluation-audit": 1, "ml-evaluation-protocols": 1,
                               "open-nc-directions": 1},
    "research_lines": ["ml-evaluation-protocols", "power-market-backtest",
                       "astro-survey-photometry", "phm-evaluation-audit", "open-nc-directions"],
    "funnel": {"target_stage": "nc_aim", "exempt_lines": []},
}

# The same instance written as the table (the proposed migration in BATCH2.md).
PROPOSED = """
polish_mode = true
[funnel]
target_stage = "nc_aim"
[lines.ml-evaluation-protocols]
mode = "full"
slots = 1
[lines.power-market-backtest]
mode = "full"
slots = 1
[lines.astro-survey-photometry]
mode = "supply_only"
slots = 1
[lines.phm-evaluation-audit]
mode = "supply_only"
slots = 1
[lines.open-nc-directions]
mode = "supply_only"
slots = 1
"""


def _legacy_decisions(program: dict, line) -> dict:
    """The three removed predicates and the removed keys, as main had them on 2026-11-26."""

    polish = program.get("polish_mode", False) is True
    exempt = tuple(program.get("polish_exempt_lines") or ())
    supply_only = tuple(program.get("polish_supply_only_lines") or ())
    named = isinstance(line, str) and bool(line)

    def polish_blocks(line):
        return polish and not (named and line in exempt)

    def polish_blocks_supply(line):
        return polish_blocks(line) and not (named and line in supply_only)

    return {
        "research": polish_blocks(line),
        "supply": polish_blocks_supply(line),
        "all": polish and not exempt and not supply_only,
        "slots": dict(program.get("line_max_active_topics") or {}).get(line),
        "nc_aim": line not in tuple((program.get("funnel") or {}).get("exempt_lines") or ()),
    }


def _new_decisions(settings, line) -> dict:
    return {
        "research": settings.stops("research", line),
        "supply": settings.stops("supply", line),
        "all": settings.stops("supply"),
        "slots": settings.line_max_active_topics.get(line),
        "nc_aim": settings.line(line).nc_aim,
    }


def _probe_lines(program: dict) -> list:
    named = set(program.get("research_lines") or ())
    for key in ("polish_exempt_lines", "polish_supply_only_lines"):
        named.update(program.get(key) or ())
    named.update(program.get("line_max_active_topics") or {})
    return [*sorted(named), "an-unlisted-line", "", None]


def _assert_same(program: dict, settings) -> None:
    for line in _probe_lines(program):
        assert _new_decisions(settings, line) == _legacy_decisions(program, line), line
    assert settings.research_lines == tuple(program.get("research_lines") or ())


@pytest.mark.parametrize("polish_mode", [True, False])
def test_snapshot_converts_to_the_same_decisions(polish_mode) -> None:
    program = {**SNAPSHOT, "polish_mode": polish_mode}
    settings = load_program_settings(program)
    _assert_same(program, settings)
    assert settings.config_warnings and "converted" in settings.config_warnings[0]


def test_live_instance_converts_to_the_same_decisions() -> None:
    if not INSTANCE.is_file():
        pytest.skip("cc-sg instance configuration not present")
    program = tomllib.loads(INSTANCE.read_text(encoding="utf-8"))["program"]
    settings = load_program_settings(program)
    _assert_same(program, settings)


def test_the_proposed_table_gives_the_same_decisions() -> None:
    table = load_program_settings(tomllib.loads(PROPOSED))
    assert table.config_warnings == ()
    _assert_same(SNAPSHOT, table)
    assert table.lines == load_program_settings(SNAPSHOT).lines
    if INSTANCE.is_file():
        live = tomllib.loads(INSTANCE.read_text(encoding="utf-8"))["program"]
        if {key: live.get(key) for key in SNAPSHOT if key != "funnel"} == {
                key: value for key, value in SNAPSHOT.items() if key != "funnel"}:
            _assert_same(live, table)


def test_table_modes_and_defaults() -> None:
    settings = load_program_settings({"polish_mode": False, "lines": {
        "a": {"mode": "full", "slots": 2}, "b": {"mode": "supply_only"},
        "c": {"mode": "polish", "nc_aim": False}, "d": {"mode": "off"}}})
    assert settings.research_lines == ("a", "b", "c")  # "off" leaves the scout rotation
    assert settings.line_max_active_topics == {"a": 2}
    decisions = {line: (settings.stops("supply", line), settings.stops("research", line))
                 for line in ("a", "b", "c", "d", "unlisted", None)}
    assert decisions == {"a": (False, False), "b": (False, True), "c": (True, True),
                         "d": (True, True), "unlisted": (False, False), None: (False, False)}
    assert settings.line("c").nc_aim is False and settings.line("x").nc_aim is True
    assert settings.stops("supply") is False  # "a" and unlisted lines still get supply
    stopped = load_program_settings({"polish_mode": True, "lines": {"a": {"mode": "polish"}}})
    assert stopped.stops("supply") is True and stopped.stops("research", EVERY_LINE) is True
    assert stopped.line("unlisted") == LineSettings(mode="polish")
    assert set(LINE_STAGES) == {"supply", "research"}


def test_table_wins_over_legacy_keys_with_a_warning() -> None:
    settings = load_program_settings({
        "research_lines": ["x"], "polish_exempt_lines": ["x"],
        "lines": {"a": {"mode": "full"}}})
    assert settings.research_lines == ("a",) and set(settings.lines) == {"a"}
    (warning,) = settings.config_warnings
    assert "ignores" in warning and "research_lines" in warning
    assert load_program_settings({"research_lines": []}).config_warnings == ()


@pytest.mark.parametrize("bad", [
    {"a": {"mode": "paused"}}, {"a": {"slots": -1}}, {"a": {"slots": True}},
    {"a": {"nc_aim": "no"}}, {"a": {"seats": 1}}, {"a": "full"}, ["a"],
])
def test_table_rejects_nonsense(bad) -> None:
    with pytest.raises(ValueError, match="program.lines"):
        load_program_settings({"lines": bad})


def test_tick_reports_the_conversion_warning(tmp_path, monkeypatch) -> None:
    import dataclasses

    import test_research_program_flow as flow

    paths = flow._paths(tmp_path)
    flow._install_program(paths)
    legacy = load_program_settings({"enabled": True, "research_lines": ["x"]})
    settings = dataclasses.replace(flow._settings(), program=dataclasses.replace(
        flow._settings().program, config_warnings=legacy.config_warnings))
    report = flow._tick(paths, settings, monkeypatch)
    assert any("converted to [program.lines]" in item for item in report.warnings)
