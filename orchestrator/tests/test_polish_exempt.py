"""Polish mode with exempt lines (2026-11-25) and figure rebuild."""

from __future__ import annotations

import dataclasses

import test_research_lines as lines_tests
import test_research_program_flow as flow
from openlabs import program_flow
from openlabs.config import LineSettings, SupplySettings, load_program_settings
from openlabs.program_flow import schedule_scouts
from test_parallel_program import NOW
from test_research_program_flow import _tick

LINES = ("engineering-vvuq", "astro-photometry")


def _polish(settings, exempt=()):
    lines = {line: LineSettings(mode="polish") for line in settings.program.lines}
    for line in exempt:
        lines[line] = LineSettings(mode="full")
    return dataclasses.replace(settings, program=dataclasses.replace(
        settings.program, polish_mode=True, lines=lines))


def test_config_and_predicates() -> None:
    assert load_program_settings({}).lines == {}
    program = load_program_settings({"polish_mode": True, "lines": {"ecg": {"mode": "full"}}})
    assert program.line("ecg").mode == "full"
    assert program.stops("research", "ecg") is False
    assert program.stops("research", "astro") is True
    assert program.stops("research", None) is True
    assert program.stops("supply") is False
    off = load_program_settings({"lines": {"ecg": {"mode": "full"}}})
    assert off.stops("research", "astro") is False and off.stops("supply") is False
    assert load_program_settings({"polish_mode": True}).stops("supply") is True


def test_only_the_exempt_line_scouts_under_polish_mode(tmp_path) -> None:
    paths, db, settings = lines_tests._line_program(
        tmp_path, LINES,
        supply=SupplySettings(max_concurrent_scouts=5, candidate_pool_size=8, scout_min_interval_hours=0),
    )
    assert schedule_scouts(db, paths, _polish(settings), lead_short=False, now=NOW) == (
        [], "polish_mode")
    scheduled, _ = schedule_scouts(db, paths, _polish(settings, ["astro-photometry"]),
                                   lead_short=False, now=NOW)
    assert [item.research_line for item in scheduled] == ["astro-photometry"]
    assert schedule_scouts(db, paths, _polish(settings, ["other"]), lead_short=False,
                           now=NOW) == ([], "polish_mode")


def test_admission_review_only_for_an_exempt_line(tmp_path) -> None:
    paths, db, settings = lines_tests._line_program(tmp_path, LINES)
    campaign = next(item for item in db.campaigns()
                    if str(item["campaign_id"]).startswith("engineering-vvuq-")
                    and "admission" in str(item["campaign_id"]))
    blocked = program_flow.schedule_topic_admission(
        db, paths, _polish(settings, ["astro-photometry"]), campaign, epoch=1)
    assert blocked.reason == "polish_mode"
    allowed = program_flow.schedule_topic_admission(
        db, paths, _polish(settings, ["engineering-vvuq"]), campaign, epoch=1)
    assert allowed.reason != "polish_mode"


def test_polish_report_keeps_exempt_scouts_queued(tmp_path, monkeypatch) -> None:
    paths, db, settings = lines_tests._line_program(
        tmp_path, LINES,
        supply=SupplySettings(max_concurrent_scouts=5, candidate_pool_size=8, scout_min_interval_hours=0),
    )
    scheduled, _ = schedule_scouts(db, paths, settings, lead_short=False, now=NOW)
    assert len(scheduled) == 2
    with db.connect() as connection:
        connection.execute("UPDATE tasks SET status='queued' WHERE task_type='topic_scout'")
    report = _tick(paths, _polish(settings, ["astro-photometry"]), monkeypatch)
    assert report.errors == []
    info = report.program["polish_mode"]
    assert info["exempt_lines"] == ["astro-photometry"]
    by_line = {item.research_line: item.task_id for item in scheduled}
    assert info["cancelled"] == [by_line["engineering-vvuq"]]
    assert db.task(by_line["astro-photometry"])["status"] != "cancelled"


def test_control_plane_renders_figures_a_campaign_draft_lacks(tmp_path, monkeypatch) -> None:
    from openlabs import paper_figures, program_autonomy

    paths = flow._paths(tmp_path)
    draft = tmp_path / "campaign"
    draft.mkdir()
    calls = []
    built = {"done": False}

    def run(p, settings, arguments, **kwargs):
        calls.append((str(p.data), arguments))
        if arguments[:2] == ["figures", "build"]:
            built["done"] = True
        return {}

    def check(p, settings, paper_id, root):
        return {"blocking": [] if built["done"] else [{"code": "FIG-NOT-BUILT", "figure": "f"}]}

    monkeypatch.setattr(program_autonomy, "_run_paper_command", run)
    monkeypatch.setattr(paper_figures, "check", check)
    settings = flow._settings()
    audit = paper_figures.rebuild_unbuilt(paths, settings, "p1", draft, check(paths, settings, "p1", draft))
    assert audit["blocking"] == [] and audit["rebuilt_by_control_plane"] is True
    assert calls == [(str(draft), ["figures", "build", "p1", "--no-manifest"])]
    # The shared data repository and an audit without FIG-NOT-BUILT are left alone.
    calls.clear()
    assert paper_figures.rebuild_unbuilt(paths, settings, "p1", paths.data,
                                         {"blocking": [{"code": "FIG-NOT-BUILT"}]})["blocking"]
    assert calls == []
    # A draft whose PDFs exist is rendered again too (a changed source keeps a stale PDF).
    assert paper_figures.rebuild_unbuilt(paths, settings, "p1", draft, {"blocking": []})[
        "rebuilt_by_control_plane"] is True
    assert calls == [(str(draft), ["figures", "build", "p1", "--no-manifest"])]
