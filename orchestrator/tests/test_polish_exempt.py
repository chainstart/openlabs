"""Polish mode with exempt lines and NC-aim scouting past an empty routine queue (2026-11-25).

User 2026-11-25: "NC产线完整就绪后，你尝试性的试产一篇看看，能不能走通流程". The trial opens one
line while polish mode keeps every other line stopped: ``[program] polish_exempt_lines``, since
2026-11-26 a ``[program.lines.<id>] mode = "full"`` entry.
Under the NC aim a line's routine candidate queues no longer gate its scouts (they read the
literature and the data catalogue broadly).
"""

from __future__ import annotations

import dataclasses
import json

import test_idle_spin as idle
import test_research_lines as lines_tests
import test_research_program_flow as flow
from openlabs import program_flow
from openlabs.config import FunnelSettings, LineSettings, load_program_settings
from openlabs.program_flow import schedule_scouts
from test_parallel_program import NOW
from test_research_program_flow import _tick

LINES = ("engineering-vvuq", "astro-photometry")


def _polish(settings, exempt=()):
    return dataclasses.replace(settings, program=dataclasses.replace(
        settings.program, polish_mode=True,
        lines={line: LineSettings(mode="full") for line in exempt}))


def test_config_and_predicates() -> None:
    assert load_program_settings({}).lines == {}
    program = load_program_settings({"polish_mode": True, "polish_exempt_lines": ["ecg"]})
    assert program.line("ecg").mode == "full"
    assert program.stops("research", "ecg") is False
    assert program.stops("research", "astro") is True
    assert program.stops("research", None) is True  # a legacy topic without a line stays stopped
    assert program.stops("supply") is False
    off = load_program_settings({"polish_exempt_lines": ["ecg"]})
    assert off.stops("research", "astro") is False and off.stops("supply") is False
    assert load_program_settings({"polish_mode": True}).stops("supply") is True


def test_only_the_exempt_line_scouts_under_polish_mode(tmp_path) -> None:
    paths, db, settings = lines_tests._line_program(
        tmp_path, LINES, max_concurrent_scouts=5, candidate_pool_low_water=8,
        scout_min_interval_hours=0)
    assert schedule_scouts(db, paths, _polish(settings), lead_short=False, now=NOW) == (
        [], "polish_mode")
    scheduled, _ = schedule_scouts(db, paths, _polish(settings, ["astro-photometry"]),
                                   lead_short=False, now=NOW)
    assert [item.research_line for item in scheduled] == ["astro-photometry"]
    # An exempt line that is not among the research lines gives no scout at all.
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
        tmp_path, LINES, max_concurrent_scouts=5, candidate_pool_low_water=8,
        scout_min_interval_hours=0)
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


def test_nc_aim_scouts_past_an_empty_routine_queue(tmp_path, monkeypatch) -> None:
    paths, queue_file = idle._queued_line(tmp_path)
    queue_file.write_text(json.dumps({"candidates": [
        {"entry_id": "TIC 1", "ledger_occupancy": {"state": "in_flight"}}]}))
    settings = flow._settings(scout_min_interval_hours=0)
    templates = program_flow.line_templates(
        program_flow.research_lines_document(paths, settings), lines_tests.LINE)
    if any("candidate_queue" not in item for item in templates):
        path = paths.data / "registry" / "research-lines.yaml"
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("        minimum_content:", f"        candidate_queue: "
                                     f"{queue_file}\n        minimum_content:")
                        .replace(f"        candidate_queue: {queue_file}\n"
                                 f"        candidate_queue: {queue_file}\n",
                                 f"        candidate_queue: {queue_file}\n"),
                        encoding="utf-8")
    report = _tick(paths, settings, monkeypatch)
    assert report.program["scout_blocked"] == "candidate_queue_empty"  # routine stage
    nc = dataclasses.replace(settings, program=dataclasses.replace(
        settings.program, funnel=FunnelSettings(target_stage="nc_aim")))
    report = _tick(paths, nc, monkeypatch)
    assert report.errors == []
    (scout,) = report.program["scouts_scheduled"]
    task = flow._db(paths).task(scout["task_id"])
    assert "optional starting points" in task["objective"]
    assert "NC aim" in task["objective"]


def test_nc_aim_line_with_one_slot_scouts_a_pool_of_cards(tmp_path) -> None:
    common = dict(max_concurrent_scouts=1, candidate_pool_low_water=4, scout_min_interval_hours=0,
                  lines={"astro-photometry": LineSettings(slots=1)})
    paths, db, settings = lines_tests._line_program(tmp_path, ("astro-photometry",), **common)
    (routine,), _ = schedule_scouts(db, paths, settings, lead_short=False, now=NOW)
    packet = json.loads(open(db.task(routine.task_id)["input_path"], encoding="utf-8").read())
    assert packet["max_cards"] == 1  # routine stage: one card per free slot

    paths, db, settings = lines_tests._line_program(tmp_path / "nc", ("astro-photometry",),
                                                    **common)
    nc = dataclasses.replace(settings, program=dataclasses.replace(
        settings.program, funnel=FunnelSettings(target_stage="nc_aim")))
    (scout,), _ = schedule_scouts(db, paths, nc, lead_short=False, now=NOW)
    packet = json.loads(open(db.task(scout.task_id)["input_path"], encoding="utf-8").read())
    assert packet["max_cards"] == 4  # NC aim: the funnel pool, not one card per slot
    assert packet["line_free_slots"] == 1
    # No free slot: no scout, pool or not.
    assert program_flow.line_scout_room(
        type("S", (), {"line_free_slots": lambda self, line: 0})(), {"topics": []},
        "astro-photometry", funnel_pool=4) == 0


def test_prescreen_findings_reach_later_scouts(tmp_path) -> None:
    from dataclasses import replace

    from openlabs import nc_funnel
    from test_nc_funnel import _prescreen_result

    settings = replace(flow._settings(), program=replace(flow._settings().program,
                                                         funnel=FunnelSettings()))
    few, digest = _prescreen_result(tmp_path / "k.json", met=("benchmark",))
    few["summary"] = "a protocol detail of one benchmark; not general"
    verdict = nc_funnel.evaluate_prescreen(few, settings, {digest})
    assert verdict["status"] == "fail" and verdict["summary"].startswith("a protocol detail")
    judged = {"topic_id": "t1", "status": "rejected",
              "card_check": {"prescreen": {**verdict, "attempts": 1}}}
    waiting = {"topic_id": "t2", "status": "proposed",
               "card_check": {"prescreen": {"status": "scheduled"}}}
    snapshot = program_flow._ledger_snapshot({"topics": [judged, waiting]})
    feedback = snapshot[0]["screen_feedback"]
    assert feedback["met"] == ["benchmark"] and "required" in feedback["why"]
    assert feedback["summary"].startswith("a protocol detail")
    assert "screen_feedback" not in snapshot[1]
    assert "screen_feedback" in nc_funnel.SCOUT_INSTRUCTION


def test_prescreen_is_review_class() -> None:
    from openlabs import budget

    settings = flow._settings()
    assert budget.task_class(settings, {"task_type": "topic_prescreen",
                                        "agent_role": "researcher"}) == "review"
    assert budget.task_class(settings, {"task_type": "topic_scout",
                                        "agent_role": "researcher"}) == "ordinary"


def test_prescreens_of_one_scout_campaign_run_side_by_side(tmp_path) -> None:
    import test_quota_routing as qr

    _, db = qr._setup(tmp_path)
    for n in range(2):
        qr._enqueue(db, f"p{n}", "gate", runner="balanced", task_type="topic_prescreen",
                    routing_reason="topic_prescreen")
    assert db.claim_next_task(owner="t", lease_seconds=60)["task_id"] == "p0"
    second = db.claim_next_task(owner="t", lease_seconds=60)
    assert second is not None and second["task_id"] == "p1"


def test_a_phase_a_stop_on_the_calibration_match_is_judged_not_invalid(tmp_path) -> None:
    from dataclasses import replace

    from openlabs import nc_funnel
    from test_nc_funnel import _prescreen_result

    settings = replace(flow._settings(), program=replace(flow._settings().program,
                                                         funnel=FunnelSettings()))
    result, _ = _prescreen_result(tmp_path / "k.json", met=("benchmark", "resource"))
    result["calibration_match"] = "zone_2"
    result["calibration_neighbours"] = ["N4-z2", "N2"]
    result["kill_test"] = {"ran": False, "signal": {"present": None}, "result_artifact": None}
    verdict = nc_funnel.evaluate_prescreen(result, settings, set())
    assert verdict["status"] == "fail" and verdict["reason"] == nc_funnel.BAND_REJECTION
    assert verdict["expected_band"] == "zone_2" and "N4-z2" in verdict["why"]


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
