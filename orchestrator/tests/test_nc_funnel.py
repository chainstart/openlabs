"""NC-aim topic funnel (user decision 2026-11-25, nc_funnel.py)."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import test_research_lines as lines
import test_research_program_flow as flow

from openlabs import nc_funnel, target_stage
from openlabs.config import FunnelSettings, load_program_settings
from openlabs.program import open_topic_ledger

THRESHOLDS = {
    "generality": {"met": True, "evidence": "every ISO market of three continents"},
    "counterintuitive": {"met": True, "evidence": "more storage lowers its own value"},
    "scale": {"met": False, "evidence": "same order as the largest prior study"},
    "benchmark": {"met": False, "evidence": ""},
    "resource": {"met": False, "evidence": ""},
}


def _nc_fields(**case) -> dict:
    return {
        "nc_case": {
            "claim": "Battery fleets erode their own arbitrage value within two years.",
            "alternative_claim": "Arbitrage value is stable once fleets pass a size threshold.",
            "challenges": "the planning assumption of constant storage spreads",
            "benchmark": "the operator's integrated system plan storage value",
            "thresholds": THRESHOLDS, "exemplars": ["N6", "N7"], **case,
        },
        "data_volume": {"total_gb": 40, "largest_file_gb": 2, "proxy_expected": False,
                        "offpeak_days": 0, "ailab_storage_gb": 60},
        "kill_test": {"signal": "spread change after staggered entry",
                      "null_model": "seasonal spread climatology",
                      "ceiling": "perfect-foresight arbitrage value",
                      "pass_rule": "effect > 2 SE and null explains < 80%", "core_hours": 1},
        "milestones": [{"name": "staggered DiD on three markets", "kind": "decisive",
                        "agent_hours": 6, "core_hours": 20, "model_usd": 15}],
    }


def _nc_card(n: int = 0, **override) -> dict:
    card = lines._line_card(n)
    card.update(_nc_fields())
    card.update(override)
    return card


def _setup(tmp_path, **funnel):
    paths, db, settings = lines._line_setup(tmp_path, "ready")
    settings = replace(settings, program=replace(
        settings.program, funnel=FunnelSettings(**funnel)))
    return paths, db, settings


def _prescreen_result(path: Path, *, present=True, met=("generality", "counterintuitive"),
                      verdict="clear", band="nc", null=0.2, reachable=True, match="nc",
                      known=None) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"effect": 0.31}\n', encoding="utf-8")
    import hashlib

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    null_baseline = {"explained_fraction": null}
    if known is not None:
        null_baseline.update(determined_by_known_relation=True, relation=known)
    return {
        **({"calibration_match": match, "calibration_neighbours": ["N2", "S2"]}
           if match is not None else {}),
        "novelty_quick": {"verdict": verdict, "papers_screened": 30,
                          "closest": [{"citation": "A 2025", "year": 2025, "overlap": "one market"}]},
        "thresholds": {key: {"met": key in met, "evidence": "checked" if key in met else ""}
                       for key in nc_funnel.THRESHOLDS},
        "kill_test": {"ran": True, "signal": {"present": present, "estimate": 0.31},
                      "null_baseline": null_baseline,
                      "ceiling": {"value": 0.9, "claim_reachable": reachable},
                      "used_core_hours": 0.5,
                      "result_artifact": {"path": str(path), "sha256": digest}},
        "expected_band": band, "summary": "ok",
    }, digest


def _novelty(n=50, closest=5) -> dict:
    return {"window_years": 3, "papers_screened": n, "queries": ["storage arbitrage erosion"],
            "closest": [{"citation": f"Paper {i} 2025", "year": 2025, "doi_or_url": "x",
                         "what_it_shows": "one market", "our_increment": "three markets"}
                        for i in range(closest)],
            "increment": "First multi-market staggered-entry estimate."}


def _assessment(band="nc", met=("generality", "counterintuitive", "benchmark"),
                match="same") -> dict:
    return {"thresholds": {key: {"met": key in met, "evidence": "seen" if key in met else ""}
                           for key in nc_funnel.THRESHOLDS},
            "met_count": len(met), "expected_band": band,
            **({"calibration_match": band if match == "same" else match,
                "calibration_neighbours": ["N2"]} if match is not None else {})}


# --------------------------------------------------------------------------- settings / stage


def test_default_stage_is_nc_aim_and_config_is_validated():
    settings = load_program_settings({})
    assert settings.funnel.target_stage == "nc_aim"
    assert target_stage.configured_stage(replace(flow._settings(), program=settings)) == "nc_aim"
    assert load_program_settings({"funnel": {"target_stage": "line_events"}}).funnel.target_stage \
        == "line_events"
    with pytest.raises(ValueError):
        load_program_settings({"funnel": {"target_stage": "tier2_aim"}})
    with pytest.raises(ValueError):
        load_program_settings({"funnel": {"admission_min_band": "zone_9"}})
    parsed = load_program_settings({"funnel": {"target_mix": {"nc": [3, 4]},
                                               "exempt_lines": ["astro"]}}).funnel
    assert parsed.target_mix["nc"] == (3, 4) and parsed.exempt_lines == ("astro",)


def test_configured_stage_overrides_line_events_and_keeps_history(tmp_path):
    paths, db, settings = _setup(tmp_path)
    target_stage.set_stage(db, lines.LINE, target_stage.TIER2_AIM, by="owner", reason="old")
    assert target_stage.stage_for(db, lines.LINE) == target_stage.TIER2_AIM
    assert target_stage.stage_for(db, lines.LINE, settings) == target_stage.NC_AIM
    exempt = replace(settings, program=replace(settings.program, funnel=FunnelSettings(
        exempt_lines=(lines.LINE,))))
    assert target_stage.stage_for(db, lines.LINE, exempt) == target_stage.TIER2_AIM
    entries = target_stage.refresh(db, {"topics": []}, [lines.LINE], settings)
    assert entries[lines.LINE]["target_stage"] == target_stage.NC_AIM
    assert len(db.events(entity_type="research_line")) == 1  # nothing promoted
    assert target_stage.graded_topic({"admission": {"target_stage": "nc_aim"}})
    assert target_stage.graded_topic({"admission": {"target_stage": "tier2_aim"}})
    assert not target_stage.graded_topic({"admission": {"target_stage": "run_in"}})


# --------------------------------------------------------------------------- L1


def test_card_without_nc_case_gets_one_repair(tmp_path, monkeypatch):
    paths, db, settings = _setup(tmp_path)
    scout_id, report = flow._scout_round(paths, db, settings, monkeypatch, [lines._line_card()])
    assert "NC aim" in db.task(scout_id)["objective"]
    repair, = report.program["card_repairs"]
    assert repair["outcome"] == "scheduled"
    errors = flow._packet(db.task(repair["task_id"]))["errors"]
    assert any("nc_case" in item for item in errors)
    assert any("milestones" in item for item in errors)


def test_mechanical_screen_rejects_small_and_low_cards(tmp_path, monkeypatch):
    paths, db, settings = _setup(tmp_path)
    weak = _nc_card(1)
    weak["nc_case"] = {**weak["nc_case"], "thresholds": {
        **THRESHOLDS, "counterintuitive": {"met": False, "evidence": ""}}}
    _, report = flow._scout_round(paths, db, settings, monkeypatch, [weak])
    rejected, = report.program["rejected_cards"]
    assert rejected["reason"] == nc_funnel.THRESHOLD_REJECTION
    topic = open_topic_ledger(paths, settings.program).topic(rejected["topic_id"])
    assert topic["card_repair"]["status"] == "not_repairable"


def test_capacity_and_near_duplicate_screens():
    settings = flow._settings()
    settings = replace(settings, program=replace(settings.program, funnel=FunnelSettings()))
    big = _nc_card(data_volume={"total_gb": 5000})
    reason, errors, _ = nc_funnel.screen_card(settings, big, {}, {"topics": []}, "nc_aim")
    assert reason == nc_funnel.CAPACITY_REJECTION and "total_gb" in errors[0]
    card = _nc_card()
    document = {"topics": [{"topic_id": "topic-old", "research_line": card["research_line"],
                            "status": "frozen", "question": card["question"],
                            "history": [{"to": "frozen", "reason": "contribution_insufficient"}]}]}
    reason, errors, _ = nc_funnel.screen_card(settings, card, {}, document, "nc_aim")
    assert reason == nc_funnel.DUPLICATE_REJECTION and "topic-old" in errors[0]
    document["topics"][0]["history"] = [{"to": "rejected", "reason": "card_invalid"}]
    document["topics"][0]["status"] = "rejected"
    reason, _, extra = nc_funnel.screen_card(settings, card, {}, document, "nc_aim")
    assert reason is None and extra["nc_screen"]["similar_topics"]
    assert extra["prescreen"]["status"] == "pending"


def test_data_catalogue_screen(tmp_path):
    catalog = tmp_path / "catalog.yaml"
    catalog.write_text(
        "schema_version: openlabs.data_catalog.v1\nline: x\nsources:\n"
        "  - {id: open, name: Open, summary: s, licence: CC-BY, status: catalogued,"
        " access: {kind: web}}\n"
        "  - {id: closed, name: Closed, summary: s, licence: DUA, status: needs_registration,"
        " registration: account, access: {kind: web}}\n", encoding="utf-8")
    entry = {"environment": {"data_catalog": str(catalog)}}
    settings = replace(flow._settings(), program=replace(flow._settings().program,
                                                         funnel=FunnelSettings()))
    ok = _nc_card(data_sources=[{"doi": "10/x", "catalog_id": "open"}])
    assert nc_funnel.data_problems(ok, entry, settings)[0] == []
    closed = _nc_card(data_sources=[{"doi": "10/x", "catalog_id": "closed"}])
    assert "needs_registration" in nc_funnel.data_problems(closed, entry, settings)[0][0]
    unknown = _nc_card(data_sources=[{"doi": "10/x"}])
    assert nc_funnel.data_problems(unknown, entry, settings)[0]
    candidate = _nc_card(data_sources=[{"doi": "10/x", "catalog_candidate": True}])
    problems, notes = nc_funnel.data_problems(candidate, entry, settings)
    assert problems == [] and "catalog_candidate" in notes[0]["note"]


# --------------------------------------------------------------------------- L2+L3 and L4


def _to_prescreen(tmp_path, monkeypatch):
    paths, db, settings = _setup(tmp_path)
    _, report = flow._scout_round(paths, db, settings, monkeypatch, [_nc_card()])
    assert report.errors == [], report.errors
    registered, = report.program["cards_registered"]
    topic_id = registered["topic_id"]
    topic = open_topic_ledger(paths, settings.program).topic(topic_id)
    assert topic["card_check"]["target_stage"] == "nc_aim"
    prescreen = topic["card_check"]["prescreen"]
    assert prescreen["status"] == "scheduled", prescreen
    task = db.task(prescreen["task_id"])
    assert task["task_type"] == nc_funnel.PRESCREEN_TASK_TYPE
    assert task["skill_path"] == "openlabs-topic-admission"
    assert task["exclude_provider"] == topic["proposer_provider"]
    # The card is held from the admission review until its prescreen is judged.
    with db.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM tasks WHERE routing_reason='topic_admission'").fetchone()[0] == 0
    return paths, db, settings, topic_id, task


def _finish_prescreen(paths, db, settings, monkeypatch, task, **kwargs):
    if db.task(task["task_id"])["status"] != "leased":
        flow._tick(paths, settings, monkeypatch)
    out = paths.data / "workspaces" / "kill.json"
    result, digest = _prescreen_result(out, **kwargs)
    flow._complete(db, paths, task["task_id"], extra={"topic_prescreen": result},
                   receipt_files={"kill.json": out.read_bytes()})
    return flow._tick(paths, settings, monkeypatch)


def test_kill_test_without_signal_is_a_hard_stop(tmp_path, monkeypatch):
    paths, db, settings, topic_id, task = _to_prescreen(tmp_path, monkeypatch)
    report = _finish_prescreen(paths, db, settings, monkeypatch, task, present=False)
    assert report.errors == [], report.errors
    topic = open_topic_ledger(paths, settings.program).topic(topic_id)
    assert topic["status"] == "rejected"
    assert topic["history"][-1]["reason"] == nc_funnel.KILL_TEST_REJECTION
    assert topic["card_check"]["prescreen"]["status"] == "fail"


@pytest.mark.parametrize("complete", [True, False])
def test_prescreened_card_goes_to_nc_admission(tmp_path, monkeypatch, complete):
    paths, db, settings, topic_id, task = _to_prescreen(tmp_path, monkeypatch)
    report = _finish_prescreen(paths, db, settings, monkeypatch, task)
    assert report.errors == [], report.errors
    topic = open_topic_ledger(paths, settings.program).topic(topic_id)
    assert topic["card_check"]["prescreen"]["status"] == "pass"
    assert topic["card_check"]["prescreen"]["expected_band"] == "nc"
    review = flow._admission_task(db)
    if review["status"] != "leased":
        flow._tick(paths, settings, monkeypatch)
        review = db.task(review["task_id"])
    assert "Nature Communications bar" in review["objective"]
    assert "calibration_match" in review["objective"]  # one ruler with the grade
    assert "calibration_match" in task["objective"]  # the prescreen asks for it too
    assert "determined_by_known_relation" in task["objective"]
    entry = flow._packet(review)["topic_cards"][0]
    assert entry["target_stage"] == "nc_aim"
    assert entry["card_check"]["prescreen"]["status"] == "pass"
    extra = {"novelty_search": _novelty(), "nc_assessment": _assessment()} if complete else {
        "novelty_search": _novelty(n=12, closest=2), "nc_assessment": _assessment(band="zone_2")}
    branch = flow._branch(entry, **extra)
    flow._complete(db, paths, review["task_id"], extra={"candidate_branches": [branch]})
    report = flow._tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    topic = open_topic_ledger(paths, settings.program).topic(topic_id)
    if not complete:
        assert topic["status"] == "rejected"
        assert topic["history"][-1]["reason"] == nc_funnel.ADMISSION_REJECTION
        assert "papers_screened" in topic["admission"]["strongest_rejection_reason"]
        return
    assert topic["status"] == "active"
    assert topic["admission"]["nc_assessment"]["expected_band"] == "nc"
    state = json.loads(Path(db.campaign(topic["campaign_id"])["workstream_state_path"]).read_text())
    assert state["target_stage"] == "nc_aim"
    assert state["milestones"][0]["kind"] == "decisive"
    assert state["nc_case"]["claim"].startswith("Battery fleets")
    assert state["expected_band"] == "nc"


def test_evaluate_prescreen_rules(tmp_path):
    settings = replace(flow._settings(), program=replace(flow._settings().program,
                                                         funnel=FunnelSettings()))
    result, digest = _prescreen_result(tmp_path / "k.json")
    assert nc_funnel.evaluate_prescreen(result, settings, {digest})["status"] == "pass"
    assert nc_funnel.evaluate_prescreen(result, settings, set())["status"] == "invalid"
    few, digest = _prescreen_result(tmp_path / "k.json", met=("scale",))
    assert nc_funnel.evaluate_prescreen(few, settings, {digest})["reason"] == \
        nc_funnel.PRESCREEN_REJECTION
    scooped, digest = _prescreen_result(tmp_path / "k.json", verdict="scooped")
    assert nc_funnel.evaluate_prescreen(scooped, settings, {digest})["status"] == "fail"
    null, digest = _prescreen_result(tmp_path / "k.json", null=0.9)
    verdict = nc_funnel.evaluate_prescreen(null, settings, {digest})
    assert verdict["status"] == "pass" and verdict["expected_band"] == "zone_1"
    low, digest = _prescreen_result(tmp_path / "k.json", band="zone_2")
    assert nc_funnel.evaluate_prescreen(low, settings, {digest})["reason"] == \
        nc_funnel.BAND_REJECTION


def test_prescreen_uses_the_calibration_ruler(tmp_path):
    """NC trial 2026-11-25: placed no higher than its calibration match, as in the grade."""

    settings = replace(flow._settings(), program=replace(flow._settings().program,
                                                         funnel=FunnelSettings()))
    assert FunnelSettings().null_explained_max == 0.5
    missing, digest = _prescreen_result(tmp_path / "k.json", match=None)
    verdict = nc_funnel.evaluate_prescreen(missing, settings, {digest})
    assert verdict["status"] == "invalid" and "calibration_match" in verdict["errors"][0]
    capped, digest = _prescreen_result(tmp_path / "k.json", match="zone_1")
    verdict = nc_funnel.evaluate_prescreen(capped, settings, {digest})
    assert verdict["status"] == "pass" and verdict["expected_band"] == "zone_1"
    assert verdict["claimed_band"] == "nc" and verdict["calibration_match"] == "zone_1"
    # The trial's ECG card: claimed zone_1, calibration says zones 3-4 -> rejected.
    low, digest = _prescreen_result(tmp_path / "k.json", band="zone_1", match="zones_3_4")
    verdict = nc_funnel.evaluate_prescreen(low, settings, {digest})
    assert verdict["reason"] == nc_funnel.BAND_REJECTION and "zones_3_4" in verdict["why"]
    # The kill test's downgrade applies below nc too, at the stricter 0.5 threshold.
    null, digest = _prescreen_result(tmp_path / "k.json", band="zone_1", match="zone_1", null=0.6)
    assert nc_funnel.evaluate_prescreen(null, settings, {digest})["reason"] == \
        nc_funnel.BAND_REJECTION
    under, digest = _prescreen_result(tmp_path / "k.json", null=0.4)
    assert nc_funnel.evaluate_prescreen(under, settings, {digest})["expected_band"] == "nc"
    # A signal fixed by a known relation is explained by the null model.
    known, digest = _prescreen_result(tmp_path / "k.json", null=0.1,
                                      known="98.5% is predicted by RR (QTc formula)")
    verdict = nc_funnel.evaluate_prescreen(known, settings, {digest})
    assert verdict["kill_test"]["null_explained"] == 1.0 and verdict["expected_band"] == "zone_1"
    assert "known relation" in verdict["downgrades"][0]


def test_admission_uses_the_calibration_ruler():
    settings = replace(flow._settings(), program=replace(flow._settings().program,
                                                         funnel=FunnelSettings()))
    ok = {"novelty_search": _novelty(), "nc_assessment": _assessment(band="zone_1")}
    assert nc_funnel.admission_problems(ok, settings) == []
    missing = {"novelty_search": _novelty(), "nc_assessment": _assessment(match=None)}
    assert any("calibration_match" in gap for gap in nc_funnel.admission_problems(
        missing, settings))
    low = {"novelty_search": _novelty(),
           "nc_assessment": _assessment(band="zone_1", match="zones_3_4")}
    gaps = nc_funnel.admission_problems(low, settings)
    assert gaps and "zones_3_4" in gaps[0] and "calibration match" in gaps[0]
    capped = nc_funnel.research_fields(
        {"card": {}, "admission": {"nc_assessment": _assessment(band="nc", match="zone_1")}})
    assert capped["expected_band"] == "zone_1"
    assert nc_funnel.calibrated_band("nc", "zone_2") == "zone_2"
    assert nc_funnel.calibrated_band("zone_2", "nc") == "zone_2"
    assert nc_funnel.calibrated_band("nc", "bogus") == "zones_3_4"


# --------------------------------------------------------------------------- L6


def _decision(band, journal, *, met=("generality", "counterintuitive"), match="nc",
              confidence="high"):
    return {"rationale": "evidence", "retarget": {
        "venue_or_format": journal, "why_fits": "scope", "achieved_band": band,
        "nc_scorecard": {key: {"met": key in met, "evidence": "e" if key in met else ""}
                         for key in nc_funnel.THRESHOLDS},
        "calibration_match": match, "calibration_neighbours": ["N6"], "confidence": confidence}}


def test_nc_grade_is_a_hard_rule():
    settings = replace(flow._settings(), program=replace(flow._settings().program,
                                                         funnel=FunnelSettings()))
    venues = [{"journal": "Nature Communications", "cas_2025_zone": 1},
              {"journal": "Applied Energy", "cas_2025_zone": 1},
              {"journal": "Energy", "cas_2025_zone": 2},
              {"journal": "Energies", "cas_2025_zone": 4}]
    grade = nc_funnel.nc_grade(_decision("nc", "Nature Communications"), venues, settings)
    assert grade["achieved_band"] == "nc" and grade["met_thresholds"]
    assert nc_funnel.nc_grade(_decision("nc", "Nature Communications", confidence="medium"),
                              venues, settings) is None
    assert nc_funnel.nc_grade(_decision("nc", "Nature Communications", met=("scale",)),
                              venues, settings) is None
    assert nc_funnel.nc_grade(_decision("nc", "Nature Communications", match="zone_1"),
                              venues, settings) is None
    assert nc_funnel.nc_grade(_decision("nc", "Applied Energy"), venues, settings) is None
    assert nc_funnel.nc_grade(_decision("zone_1", "Applied Energy", match="zone_1"),
                              venues, settings)["cas_2025_zone"] == 1
    assert nc_funnel.nc_grade(_decision("zone_1", "Nature Communications"), venues,
                              settings) is None
    assert nc_funnel.nc_grade(_decision("zone_2", "Energy"), venues, settings)
    assert nc_funnel.nc_grade(_decision("zones_3_4", "Energies"), venues, settings)
    assert nc_funnel.nc_grade(_decision("zones_3_4", "Energy"), venues, settings) is None
    # The same ruler as the funnel: never above the calibration match.
    assert nc_funnel.nc_grade(_decision("zone_1", "Applied Energy", match="zone_2"),
                              venues, settings) is None
    assert target_stage.venue_grade(_decision("zone_2", "Energy"), venues, stage="nc_aim",
                                    settings=settings)["achieved_band"] == "zone_2"


# --------------------------------------------------------------------------- L0 and metrics


def _rejected(n, at, reason="card_prescreen_failed", line=lines.LINE):
    return {"topic_id": f"topic-{n}", "research_line": line, "status": "rejected",
            "card_check": {"target_stage": "nc_aim"},
            "history": [{"to": "proposed", "at": at, "reason": "topic_card_submitted"},
                        {"to": "rejected", "at": at, "reason": reason}]}


def test_funnel_stall_backs_off_scouting_and_metrics(tmp_path):
    paths, db, settings = _setup(tmp_path, stall_zero_pass_after=3, stall_backoff_hours=24,
                                 scout_weekly_usd_per_line=0)
    now = datetime.now(UTC)
    stamp = (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    document = {"topics": [_rejected(i, stamp) for i in range(3)]}
    from openlabs.program_flow import program_projects

    projects = program_projects(paths)
    blocks = nc_funnel.scout_blocks(db, paths, settings, projects, document, moment=now)
    block, = blocks.values()
    assert block["reason"] == "funnel_stall_backoff" and block["zero_pass_cards"] == 3
    later = now + timedelta(hours=30)
    assert nc_funnel.scout_blocks(db, paths, settings, projects, document, moment=later) == {}
    document["topics"].append({**_rejected(9, stamp), "status": "active",
                               "history": [{"to": "proposed", "at": stamp},
                                           {"to": "admitted", "at": stamp},
                                           {"to": "active", "at": stamp}],
                               "admission": {"target_stage": "nc_aim",
                                             "nc_assessment": {"expected_band": "zone_1"}}})
    assert nc_funnel.scout_blocks(db, paths, settings, projects, document, moment=now) == {}
    report = nc_funnel.metrics(document, settings)
    row = report["lines"][lines.LINE]
    assert row["nc_aim"]["candidates"] == 4 and row["nc_aim"]["admitted"] == 1
    assert row["expected_band_at_admission"] == {"zone_1": 1}
    assert report["target_mix_per_10"]["nc"] == [2, 3]


@pytest.mark.parametrize("confidence", ["high", "medium"])
def test_ready_nc_manuscript_is_graded_against_the_calibration_set(tmp_path, monkeypatch,
                                                                    confidence):
    import test_program_autonomy as autonomy
    from openlabs import program_autonomy

    paths, db, settings, (topic,) = autonomy._program(tmp_path, monkeypatch, auto_handoff=True)
    settings = replace(settings, program=replace(settings.program, funnel=FunnelSettings()))
    (paths.data / "registry").mkdir(parents=True, exist_ok=True)
    (paths.data / nc_funnel.CALIBRATION_PATH).write_text("papers: []\n", encoding="utf-8")
    monkeypatch.setattr(target_stage, "tier2_topic", lambda _: True)
    monkeypatch.setattr(target_stage, "admitted_stage", lambda _: "nc_aim")
    autonomy._deliverable(monkeypatch)
    release_status = program_autonomy.run_release_status
    monkeypatch.setattr(program_autonomy, "run_release_status", lambda *args: {
        **release_status(*args), "target_journal": "Nature Communications"})
    monkeypatch.setenv("ARA_PAPER_MANAGE_API_URL", "https://manage.invalid")
    monkeypatch.setenv("ARA_PAPER_MANAGE_API_KEY", "test-key")
    monkeypatch.setattr(program_autonomy, "run_paper_delivery", lambda _p, _s, paper_id: {
        "status": "delivered", "paper_id": paper_id, "package_id": "pkg-nc",
        "submission_handler": None, "awaiting_owner_review": True})
    original = program_autonomy._run_paper_command

    def paper_command(*args, **kwargs):
        if args[2] == ["venue", "alternatives"]:
            return {"venues": [{"journal": "Nature Communications", "cas_2025_zone": 1},
                               {"journal": "Zone 2 Journal", "cas_2025_zone": 2}]}
        return original(*args, **kwargs)

    monkeypatch.setattr(program_autonomy, "_run_paper_command", paper_command)
    review = autonomy._to_review(paths, db, settings, monkeypatch, topic)
    autonomy._finish(db, paths, review["task_id"], extra={
        "paper_candidate": True, "review_outcome": autonomy._outcome(
            status="ready", target_journal="Nature Communications")})
    report = autonomy._tick(paths, settings, monkeypatch)
    assert report.errors == []
    pending = autonomy._direction_task(db)
    packet = flow._packet(pending)
    assert packet["grading"]["stage"] == "nc_aim"
    assert "venue-calibration" in {item["label"] for item in packet["read_resources"]}
    assert "calibration" in pending["objective"]
    decision = autonomy._retarget_decision(packet["reasons_to_answer"][0],
                                           "Nature Communications")
    decision["retarget"].update(_decision("nc", "Nature Communications",
                                          confidence=confidence)["retarget"])
    report = autonomy._decide(paths, settings, monkeypatch, db, decision)
    assert report.errors == []
    outcomes = [item["outcome"] for item in report.program["direction_decisions"]]
    topic = autonomy._topic(paths, settings, topic["topic_id"])
    if confidence == "high":
        assert outcomes[0] == "venue_retained"
        assert topic["venue_grade"]["achieved_band"] == "nc"
        assert topic["handoff"]["status"] == "delivered"
    else:
        assert "invalid" in outcomes  # the NC band without high confidence is refused
        assert not topic.get("venue_grade")
