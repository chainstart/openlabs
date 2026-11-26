"""NC admission floor and broader, multi-family scouting (user 2026-11-26).

User 2026-11-26: "接下来的出题希望选题至少是够nc档次的" (admission floor nc) and "现在出题选题慢，
是不是并行工作的规模不够，并行agent数量，扩大搜索范围，更多的集思广益" (several scouts per line,
rotated over the model families; more lines open for supply only).
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import replace
from pathlib import Path

import test_nc_funnel as nc
import test_parallel_program as parallel
import test_quota_routing as routing
import test_research_lines as lines_tests
import test_research_program_flow as flow
from openlabs import budget as budget_control
from openlabs import nc_funnel, program_flow
from openlabs.config import FunnelSettings, RunnerSpec, load_program_settings
from openlabs.program import open_topic_ledger
from openlabs.program_flow import schedule_scouts
from test_parallel_program import NOW

LINES = ("engineering-vvuq", "astro-photometry")
GEMINI = RunnerSpec("worker_gemini", "google-antigravity", "worker", "gemini-4-hydrogen-high",
                    windows=("gemini-weekly",), overflow=True, task_classes=("review", "owner"))
RUNNERS = {**flow.RUNNERS, "worker_gemini": GEMINI}
ROTATION = ("worker_gpt", "worker_gemini", "worker_claude")


def _packets(db) -> list[dict]:
    return [json.loads(Path(task["input_path"]).read_text()) for task in parallel._scouts(db)]


def _with(settings, **program):
    return replace(settings, program=replace(settings.program, **program))


# --------------------------------------------------------------------------- settings


def test_config_keys_and_polish_predicates() -> None:
    default = load_program_settings({})
    assert default.max_scouts_per_line == 1 and default.scout_runners == ()
    assert default.polish_supply_only_lines == ()
    program = load_program_settings({
        "polish_mode": True, "polish_exempt_lines": ["ecg"],
        "polish_supply_only_lines": ["astro", "open"], "max_scouts_per_line": 2,
        "scout_runners": ["worker_gpt", "worker_gemini", "worker_gpt"]})
    assert program.max_scouts_per_line == 2
    assert program.scout_runners == ("worker_gpt", "worker_gemini")
    # A supply-only line scouts and is admitted, but starts no research.
    assert program.polish_blocks_supply("astro") is False
    assert program.polish_blocks("astro") is True
    assert program.polish_blocks_supply("ecg") is False and program.polish_blocks("ecg") is False
    assert program.polish_blocks_supply("power") is True
    only = load_program_settings({"polish_mode": True, "polish_supply_only_lines": ["astro"]})
    assert only.polish_blocks_all() is False
    assert load_program_settings({"funnel": {"admission_min_band": "nc"}}).funnel \
        .admission_min_band == "nc"


# --------------------------------------------------------------------------- scheduling


def test_two_scouts_per_line_on_different_families(tmp_path) -> None:
    paths, db, settings = lines_tests._line_program(
        tmp_path, LINES, max_concurrent_scouts=4, candidate_pool_low_water=8,
        scout_min_interval_hours=1, max_scouts_per_line=2, scout_runners=ROTATION)
    settings = replace(settings, runners=dict(RUNNERS))
    scheduled, reason = schedule_scouts(db, paths, settings, lead_short=False, now=NOW)
    assert len(scheduled) == 4 and reason == "max_concurrent_scouts"
    by_line: dict[str, list[str]] = {}
    for packet in _packets(db):
        by_line.setdefault(packet["research_line"], []).append(packet["preferred_runner"])
    assert set(by_line) == set(LINES)
    for runners in by_line.values():
        assert len(runners) == 2 and len(set(runners)) == 2  # never one family twice
    # Across the program the three families share the four scouts (2/1/1).
    counts = sorted(sum(r.count(name) for r in by_line.values()) for name in ROTATION)
    assert counts == [1, 1, 2]
    events = [e["payload"] for e in db.events() if e["event_type"] == "topic_scout_scheduled"]
    assert all(e["preferred_family"] for e in events)
    # The lines are full now: nothing more this tick.
    assert schedule_scouts(db, paths, settings, lead_short=False, now=NOW)[0] == []


def test_a_line_rotates_its_family_scout_after_scout(tmp_path) -> None:
    paths, db, settings = lines_tests._line_program(
        tmp_path, LINES[:1], max_concurrent_scouts=1, candidate_pool_low_water=8,
        scout_min_interval_hours=0, scout_runners=ROTATION)
    settings = replace(settings, runners=dict(RUNNERS))
    seen = []
    for _ in range(4):
        scheduled, _ = schedule_scouts(db, paths, settings, lead_short=False, now=NOW)
        assert len(scheduled) == 1
        seen.append(json.loads(Path(db.task(scheduled[0].task_id)["input_path"]).read_text())
                    ["preferred_runner"])
        with db.connect() as connection:
            connection.execute("UPDATE tasks SET status='succeeded' WHERE task_type='topic_scout'")
    assert seen[:3] == list(ROTATION) and seen[3] == ROTATION[0]


def test_without_scout_runners_nothing_is_preferred(tmp_path) -> None:
    paths, db, settings = lines_tests._line_program(
        tmp_path, LINES, max_concurrent_scouts=4, candidate_pool_low_water=8,
        scout_min_interval_hours=1)
    scheduled, _ = schedule_scouts(db, paths, settings, lead_short=False, now=NOW)
    assert len(scheduled) == 2  # one per line, as before
    assert all("preferred_runner" not in packet for packet in _packets(db))


def test_supply_only_line_scouts_under_polish_mode_and_is_not_cancelled(tmp_path,
                                                                        monkeypatch) -> None:
    paths, db, settings = lines_tests._line_program(
        tmp_path, LINES, max_concurrent_scouts=5, candidate_pool_low_water=8,
        scout_min_interval_hours=0)
    polish = _with(settings, polish_mode=True, polish_supply_only_lines=("astro-photometry",))
    scheduled, _ = schedule_scouts(db, paths, polish, lead_short=False, now=NOW)
    assert [item.research_line for item in scheduled] == ["astro-photometry"]
    with db.connect() as connection:
        connection.execute("UPDATE tasks SET status='queued' WHERE task_type='topic_scout'")
    report = flow._tick(paths, polish, monkeypatch)
    assert report.errors == []
    info = report.program["polish_mode"]
    assert info["supply_only_lines"] == ["astro-photometry"] and info["cancelled"] == []


# --------------------------------------------------------------------------- routing


def _scout(db, paths, task_id: str, preferred: str | None, **kwargs) -> None:
    packet = paths.data / f"{task_id}.json"
    packet.write_text(json.dumps({"preferred_runner": preferred} if preferred else {}))
    routing._enqueue(db, task_id, f"scout-{task_id}", task_type="topic_scout",
                     input_path=str(packet), **kwargs)


def _route_settings():
    return replace(routing._settings(), runners={**routing.RUNNERS, "worker_gemini": GEMINI})


def test_router_takes_the_preferred_runner_even_an_overflow_one(tmp_path) -> None:
    paths, db = routing._setup(tmp_path)
    settings = _route_settings()
    routing._record(db, settings, "worker_gpt", {"seven_day": 0.1})
    routing._record(db, settings, "worker_claude", {"five_hour": 0.2, "seven_day": 0.2})
    budget_control.record_quota_snapshot(db, settings, routing._snapshot(
        "google-antigravity", GEMINI.model, {"gemini-weekly": 0.1}), runner="worker_gemini")
    _scout(db, paths, "s1", "worker_gemini")
    task, router = routing._claim(db, settings)
    assert task["task_id"] == "s1" and task["runner"] == "worker_gemini"
    assert router.decisions["s1"]["preferred_runner"] == "worker_gemini"
    # Without a preference the overflow Gemini runner is never chosen for a scout.
    _scout(db, paths, "s2", None)
    task, _router = routing._claim(db, settings)
    assert task["runner"] in {"worker_gpt", "worker_claude"}


def test_router_falls_back_when_the_preferred_runner_is_out_of_quota(tmp_path) -> None:
    paths, db = routing._setup(tmp_path)
    settings = _route_settings()
    routing._record(db, settings, "worker_gpt", {"seven_day": 0.1})
    routing._record(db, settings, "worker_claude", {"five_hour": 0.99, "seven_day": 0.99})
    _scout(db, paths, "s1", "worker_claude")
    task, router = routing._claim(db, settings)
    assert task["runner"] == "worker_gpt"
    assert router.decisions["s1"]["preferred_runner_unavailable"] == "worker_claude"


def test_preference_applies_to_scouts_only(tmp_path) -> None:
    paths, db = routing._setup(tmp_path)
    settings = _route_settings()
    routing._record(db, settings, "worker_gpt", {"seven_day": 0.1})
    routing._record(db, settings, "worker_claude", {"five_hour": 0.6, "seven_day": 0.6})
    packet = paths.data / "r.json"
    packet.write_text(json.dumps({"preferred_runner": "worker_claude"}))
    routing._enqueue(db, "r", "c", task_type="research", input_path=str(packet))
    task, _router = routing._claim(db, settings)
    assert task["runner"] == "worker_gpt"


# --------------------------------------------------------------------------- NC floor


def _nc_floor_settings():
    base = flow._settings()
    return replace(base, program=replace(base.program,
                                         funnel=FunnelSettings(admission_min_band="nc")))


def test_nc_floor_in_the_prescreen(tmp_path) -> None:
    settings = _nc_floor_settings()
    ok, digest = nc._prescreen_result(tmp_path / "k.json")
    assert nc_funnel.evaluate_prescreen(ok, settings, {digest})["status"] == "pass"
    # A Zone 1 calibration match stops phase A under the nc floor (it passed under zone_1).
    zone1, digest = nc._prescreen_result(tmp_path / "k.json", match="zone_1")
    verdict = nc_funnel.evaluate_prescreen(zone1, settings, {digest})
    assert verdict["status"] == "fail" and verdict["reason"] == nc_funnel.BAND_REJECTION
    assert "below the admission floor nc" in verdict["why"]
    # The kill test's one-step downgrade (null model explains most of it) now rejects.
    null, digest = nc._prescreen_result(tmp_path / "k.json", null=0.9)
    verdict = nc_funnel.evaluate_prescreen(null, settings, {digest})
    assert verdict["reason"] == nc_funnel.BAND_REJECTION and verdict["expected_band"] == "zone_1"
    unreachable, digest = nc._prescreen_result(tmp_path / "k.json", reachable=False)
    assert nc_funnel.evaluate_prescreen(unreachable, settings, {digest})["reason"] == \
        nc_funnel.BAND_REJECTION
    claimed, digest = nc._prescreen_result(tmp_path / "k.json", band="zone_1")
    assert nc_funnel.evaluate_prescreen(claimed, settings, {digest})["reason"] == \
        nc_funnel.BAND_REJECTION


def test_nc_floor_at_admission_and_in_the_instructions() -> None:
    settings = _nc_floor_settings()
    ok = {"novelty_search": nc._novelty(), "nc_assessment": nc._assessment(band="nc")}
    assert nc_funnel.admission_problems(ok, settings) == []
    zone1 = {"novelty_search": nc._novelty(), "nc_assessment": nc._assessment(band="zone_1")}
    gaps = nc_funnel.admission_problems(zone1, settings)
    assert gaps and "below the admission floor nc" in gaps[0]
    capped = {"novelty_search": nc._novelty(),
              "nc_assessment": nc._assessment(band="nc", match="zone_1")}
    assert "calibration match zone_1" in nc_funnel.admission_problems(capped, settings)[0]
    assert "below nc" in nc_funnel.admission_instruction(settings)
    assert "Admission floor: nc" in nc_funnel.scout_floor_instruction(settings)
    # After research the data still grade the journal: the grade knows nothing of the floor.
    grade = nc_funnel.nc_grade(
        {"rationale": "e", "retarget": {
            "venue_or_format": "Some Zone 1 Journal", "why_fits": "scope",
            "achieved_band": "zone_1", "calibration_match": "zone_1",
            "calibration_neighbours": ["S1"], "confidence": "medium",
            "nc_scorecard": {key: {"met": True, "evidence": "e"} for key in nc_funnel.THRESHOLDS}}},
        [{"journal": "Some Zone 1 Journal", "cas_2025_zone": 1}], settings)
    assert grade is not None and grade["achieved_band"] == "zone_1"


def test_nc_floor_end_to_end_and_supply_only_admits_without_research(tmp_path,
                                                                      monkeypatch) -> None:
    paths, db, settings = nc._setup(tmp_path, admission_min_band="nc")
    settings = _with(settings, polish_mode=True,
                     polish_supply_only_lines=(lines_tests.LINE,))
    _, report = flow._scout_round(paths, db, settings, monkeypatch, [nc._nc_card()])
    assert report.errors == [], report.errors
    registered, = report.program["cards_registered"]
    topic_id = registered["topic_id"]
    scout = next(task for task in parallel._scouts(db))
    assert "Admission floor: nc" in scout["objective"]
    topic = open_topic_ledger(paths, settings.program).topic(topic_id)
    task = db.task(topic["card_check"]["prescreen"]["task_id"])
    assert "match below nc rejects the card" in task["objective"]
    assert json.loads(Path(task["input_path"]).read_text())["funnel"]["admission_min_band"] == "nc"
    report = nc._finish_prescreen(paths, db, settings, monkeypatch, task)
    assert report.errors == [], report.errors
    review = flow._admission_task(db)
    if review["status"] != "leased":
        flow._tick(paths, settings, monkeypatch)
        review = db.task(review["task_id"])
    assert "below nc" in review["objective"]
    entry = flow._packet(review)["topic_cards"][0]
    branch = flow._branch(entry, novelty_search=nc._novelty(),
                          nc_assessment=nc._assessment(band="nc"))
    flow._complete(db, paths, review["task_id"], extra={"candidate_branches": [branch]})
    report = flow._tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    topic = open_topic_ledger(paths, settings.program).topic(topic_id)
    # Admitted, but a supply-only line starts no research under polish mode.
    assert topic["status"] == "admitted" and not topic.get("campaign_id")
    exempt = _with(settings, polish_exempt_lines=(lines_tests.LINE,))
    report = flow._tick(paths, exempt, monkeypatch)
    assert open_topic_ledger(paths, settings.program).topic(topic_id)["status"] == "active"


def test_supply_only_admission_review_is_scheduled(tmp_path) -> None:
    paths, db, settings = lines_tests._line_program(tmp_path, LINES)
    campaign = next(item for item in db.campaigns()
                    if str(item["campaign_id"]).startswith("engineering-vvuq-")
                    and "admission" in str(item["campaign_id"]))
    polish = dataclasses.replace(settings, program=dataclasses.replace(
        settings.program, polish_mode=True, polish_supply_only_lines=("engineering-vvuq",)))
    assert program_flow.schedule_topic_admission(
        db, paths, polish, campaign, epoch=1).reason != "polish_mode"
