"""NC-aim topic funnel (user decision 2026-11-25, nc_funnel.py)."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import test_research_lines as lines
import test_research_program_flow as flow

from openlabs import nc_funnel, target_stage
from openlabs.config import FunnelSettings, LineSettings, load_program_settings
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
    program = load_program_settings({"funnel": {"target_mix": {"nc": [3, 4]},
                                                "exempt_lines": ["astro"]}})
    assert program.funnel.target_mix["nc"] == (3, 4)
    assert program.line("astro").nc_aim is False  # legacy funnel.exempt_lines, converted


def test_configured_stage_overrides_line_events_and_keeps_history(tmp_path):
    paths, db, settings = _setup(tmp_path)
    target_stage.set_stage(db, lines.LINE, target_stage.TIER2_AIM, by="owner", reason="old")
    assert target_stage.stage_for(db, lines.LINE) == target_stage.TIER2_AIM
    assert target_stage.stage_for(db, lines.LINE, settings) == target_stage.NC_AIM
    exempt = replace(settings, program=replace(settings.program, funnel=FunnelSettings(),
                                               lines={lines.LINE: LineSettings(nc_aim=False)}))
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


def test_mechanical_screen_records_self_claimed_thresholds_without_rejecting():
    # Pipeline slimming 2026-11-26: the scout's own claims are not a hard stop (L1 rejected
    # 0 of 23 cards on them); the prescreen scores the thresholds independently.
    settings = flow._settings()
    settings = replace(settings, program=replace(settings.program, funnel=FunnelSettings()))
    weak = _nc_card(1)
    weak["nc_case"] = {**weak["nc_case"], "thresholds": {
        **THRESHOLDS, "counterintuitive": {"met": False, "evidence": ""}}}
    reason, errors, extra = nc_funnel.screen_card(settings, weak, {}, {"topics": []}, "nc_aim")
    assert reason is None and errors == []
    assert "counterintuitive" not in extra["nc_screen"]["claimed_thresholds"]
    assert extra["prescreen"]["status"] == "pending"


def test_nc_card_needs_no_feasibility_precheck_and_runs_no_line_precheck(tmp_path, monkeypatch):
    # Pipeline slimming 2026-11-26: the prescreen's kill test replaces both for nc_aim cards.
    paths, db, settings = _setup(tmp_path)
    card = _nc_card()
    card.pop("feasibility_precheck", None)
    from openlabs import program_flow

    monkeypatch.setattr(program_flow, "_run_card_precheck",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("precheck ran")))
    _, report = flow._scout_round(paths, db, settings, monkeypatch, [card])
    assert report.errors == [], report.errors
    registered, = report.program["cards_registered"]
    topic = open_topic_ledger(paths, settings.program).topic(registered["topic_id"])
    assert "precheck" not in topic["card_check"] and "pilot" not in topic["card_check"]
    assert topic["card_check"]["prescreen"]["status"] in {"pending", "scheduled"}


def test_nc_card_fee_and_licence_gaps_are_warnings_not_errors():
    # NC calibration 2026-11-26: routine-venue fee and licence evidence of an nc_aim card is
    # completed at admission; a routine line card still needs it.
    from openlabs.contracts import validate_topic_card

    card = _nc_card()
    card.pop("feasibility_precheck", None)
    card.pop("fee_check", None)
    card.pop("license_check", None)
    nc = validate_topic_card(card, feasibility_precheck=False)
    assert not any("fee_check" in e or "license_check" in e for e in nc.errors), nc.errors
    assert any("fee_check" in w for w in nc.warnings)
    assert any("license_check" in w for w in nc.warnings)
    routine = validate_topic_card(card)
    assert any("fee_check" in e for e in routine.errors)
    assert any("license_check" in e for e in routine.errors)
    card["research_line"] = ""
    assert any(e.startswith("research_line ")
               for e in validate_topic_card(card, feasibility_precheck=False).errors)


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
        " registration: account, access: {kind: web}}\n"
        "  - {id: gone, name: Gone, summary: s, licence: x, status: blocked,"
        " blocked_reason: site refuses, access: {kind: web}}\n", encoding="utf-8")
    entry = {"environment": {"data_catalog": str(catalog)}}
    settings = replace(flow._settings(), program=replace(flow._settings().program,
                                                         funnel=FunnelSettings()))
    ok = _nc_card(data_sources=[{"doi": "10/x", "catalog_id": "open"}])
    assert nc_funnel.data_problems(ok, entry, settings)[0] == []
    # User rule (free data only; registration-needing free sources are listed for the owner):
    # a needs_registration source is a note for the owner, not a rejection (2026-11-26).
    closed = _nc_card(data_sources=[{"doi": "10/x", "catalog_id": "closed"}])
    problems, notes = nc_funnel.data_problems(closed, entry, settings)
    assert problems == []
    assert notes == [{"source": "closed", "status": "needs_registration", "registration": "account",
                      "note": notes[0]["note"]}] and "registration" in notes[0]["note"]
    reason, _, extra = nc_funnel.screen_card(settings, closed, entry, {"topics": []}, "nc_aim")
    assert reason is None and extra["nc_screen"]["data_catalog"][0]["status"] == "needs_registration"
    gone = _nc_card(data_sources=[{"doi": "10/x", "catalog_id": "gone"}])
    problems, _ = nc_funnel.data_problems(gone, entry, settings)
    assert problems and "blocked" in problems[0] and "site refuses" in problems[0]
    reason, _, _ = nc_funnel.screen_card(settings, gone, entry, {"topics": []}, "nc_aim")
    assert reason == nc_funnel.DATA_REJECTION
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
    # The gate checks the prescreen and adds the novelty search; it does not score again.
    assert "Do not score the NC thresholds again" in review["objective"]
    extra = {"novelty_search": _novelty()} if complete else {
        "novelty_search": _novelty(n=12, closest=2)}
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
    assert "nc_assessment" not in topic["admission"]
    state = json.loads(Path(db.campaign(topic["campaign_id"])["workstream_state_path"]).read_text())
    assert state["target_stage"] == "nc_aim"
    assert state["milestones"][0]["kind"] == "decisive"
    assert state["nc_case"]["claim"].startswith("Battery fleets")
    assert state["expected_band"] == "nc"  # the prescreen's band
    assert state["prescreen"]["calibration_match"] == "nc"
    # The kill test is the first stage: no separate feasibility precheck (2026-11-26).
    assert state["prescreen"]["kill_test"]["signal"]["present"] is True
    assert "feasibility_precheck" not in state and "precheck_clock" not in state
    with db.connect() as connection:
        objectives = [row[0] for row in connection.execute(
            "SELECT objective FROM tasks WHERE campaign_id=?", (topic["campaign_id"],))]
    assert objectives and not any("feasibility_precheck" in text for text in objectives)


def _distinct() -> dict:
    fields = _nc_fields(claim="Glacier melt pulses reorder alpine river carbon export "
                              "seasonality across hemispheres.")
    return {"question": "Do meltwater pulses shift the timing of mountain stream carbon "
                        "fluxes?", **fields}


def test_a_backed_off_prescreen_holds_no_slot_and_is_reported_queued(tmp_path, monkeypatch):
    """2026-11-26: four backed-off prescreens of one line filled the global cap and
    were reported as running; the other cards never got a slot."""

    paths, db, settings = _setup(tmp_path, prescreen_max_concurrent=1)
    _, report = flow._scout_round(paths, db, settings, monkeypatch,
                                  [_nc_card(0), _nc_card(1, **_distinct())])
    assert report.errors == [], report.errors
    ledger = open_topic_ledger(paths, settings.program)
    topics = [ledger.topic(item["topic_id"]) for item in report.program["cards_registered"]]
    states = {topic["topic_id"]: topic["card_check"]["prescreen"] for topic in topics}
    held = [topic_id for topic_id, state in states.items() if state["status"] == "scheduled"]
    waiting = [topic_id for topic_id, state in states.items() if state["status"] == "pending"]
    assert len(held) == 1 and len(waiting) == 1, states
    first_task = states[held[0]]["task_id"]

    # Running now: it holds the one slot and is reported with its own status.
    with db.connect() as connection:  # test fixture: the prescreen is claimed
        connection.execute("UPDATE tasks SET status='running', not_before=NULL "
                           "WHERE task_id=?", (first_task,))
    outcomes = {item["topic_id"]: item for item in
                nc_funnel.advance_prescreens(db, paths, settings, flow.engine.TickReport())}
    assert outcomes[held[0]] == {"topic_id": held[0], "status": "running",
                                 "task_id": first_task}
    assert outcomes[waiting[0]]["reason"] == "prescreen_max_concurrent"

    # Backed off into the future (no_progress_backoff): queued, no slot.
    later = (datetime.now(UTC) + timedelta(hours=4)).isoformat(timespec="seconds") \
        .replace("+00:00", "Z")
    with db.connect() as connection:  # test fixture: the backoff the guard writes
        connection.execute("UPDATE tasks SET status='queued', not_before=? WHERE task_id=?",
                           (later, first_task))
    outcomes = {item["topic_id"]: item for item in
                nc_funnel.advance_prescreens(db, paths, settings, flow.engine.TickReport())}
    assert outcomes[held[0]] == {"topic_id": held[0], "status": "queued",
                                 "task_id": first_task, "not_before": later}
    assert outcomes[waiting[0]]["status"] == "scheduled"
    assert open_topic_ledger(paths, settings.program).topic(waiting[0])[
        "card_check"]["prescreen"]["status"] == "scheduled"


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


def test_admission_checks_the_prescreen_instead_of_scoring_again():
    # Pipeline slimming 2026-11-26: the gate does not score the thresholds again.
    settings = replace(flow._settings(), program=replace(flow._settings().program,
                                                         funnel=FunnelSettings()))
    passed = {"status": "pass", "expected_band": "zone_1", "calibration_match": "zone_1",
              "met": ["generality", "benchmark"]}
    assert nc_funnel.admission_problems({"novelty_search": _novelty()}, settings, passed) == []
    gaps = nc_funnel.admission_problems({"novelty_search": _novelty()}, settings, None)
    assert gaps == ["the prescreen (card_check.prescreen) has not passed"]
    assert "papers_screened" in nc_funnel.admission_problems(
        {"novelty_search": _novelty(n=12)}, settings, passed)[0]
    fields = nc_funnel.research_fields({"card": {}, "admission": {}}, passed)
    assert fields["expected_band"] == "zone_1"
    assert fields["prescreen"]["calibration_match"] == "zone_1"
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


def test_prescreen_retry_clears_stale_errors_after_valid_verdict(tmp_path, monkeypatch):
    """A technical failure on attempt 1 (e.g. needs_replan) must not leave stale errors on
    card_check.prescreen once attempt 2 returns a valid pass/fail verdict."""

    paths, db, settings, topic_id, first_task = _to_prescreen(tmp_path, monkeypatch)
    with db.connect() as connection:
        connection.execute(
            "UPDATE tasks SET status='needs_replan', last_error='claims must be an array' "
            "WHERE task_id=?", (first_task["task_id"],))
    report = flow._tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    ledger = open_topic_ledger(paths, settings.program)
    mid = ledger.topic(topic_id)["card_check"]["prescreen"]
    assert mid["status"] == "scheduled" and mid["attempts"] == 2
    assert mid["errors"] == ["task needs_replan"]
    second_task = db.task(mid["task_id"])
    assert second_task is not None and second_task["task_id"] != first_task["task_id"]
    assert "claims: []" in second_task["objective"]
    report = _finish_prescreen(paths, db, settings, monkeypatch, second_task, match="zone_1",
                               band="zone_1")
    assert report.errors == [], report.errors
    final_ps = ledger.topic(topic_id)["card_check"]["prescreen"]
    assert final_ps["status"] == "pass"
    assert "errors" not in final_ps


def test_scout_guidance_steers_away_from_audits_and_requires_nc_framing():
    skill = (Path(__file__).resolve().parents[2]
             / "workflows/paper/skills/openlabs-empirical-topic-scout/SKILL.md").read_text(
                 encoding="utf-8")
    for text in (nc_funnel.SCOUT_INSTRUCTION, skill):
        low = " ".join(text.lower().split())
        assert "overturns a widely used" in low
        assert "headline finding" in low
        assert "across fields" in low or "across multiple fields" in low
        assert "nature communications" in low and "science" in low
        assert "diverse fields" in low or "distinct fields" in low
        assert "needs_registration" in text


def test_per_line_admission_floor_in_prescreen_admission_instructions_and_metrics(tmp_path):
    base = flow._settings()
    settings = replace(
        base,
        program=replace(
            base.program,
            funnel=FunnelSettings(admission_min_band="nc"),
            lines={
                "established": LineSettings(mode="full", slots=2, admission_min_band="zone_2"),
                "open-line": LineSettings(mode="full", slots=1),
            },
        ),
    )
    assert nc_funnel.admission_min_band(settings, "established") == "zone_2"
    assert nc_funnel.admission_min_band(settings, "open-line") == "nc"
    assert nc_funnel.admission_min_band(settings, "unlisted") == "nc"

    # Card L1 screen records the line's effective floor.
    card_est = _nc_card(0, research_line="established")
    card_open = _nc_card(1, research_line="open-line")
    _, _, extra_est = nc_funnel.screen_card(settings, card_est, {}, {"topics": []}, "nc_aim")
    _, _, extra_open = nc_funnel.screen_card(settings, card_open, {}, {"topics": []}, "nc_aim")
    assert extra_est["nc_screen"]["admission_min_band"] == "zone_2"
    assert extra_open["nc_screen"]["admission_min_band"] == "nc"

    # Prescreen calibration cap and final band check use the line's effective floor.
    zone2, digest = _prescreen_result(tmp_path / "k.json", match="zone_2", band="zone_2")
    verdict_est = nc_funnel.evaluate_prescreen(zone2, settings, {digest}, line="established")
    assert verdict_est["status"] == "pass" and verdict_est["expected_band"] == "zone_2"
    assert verdict_est["admission_min_band"] == "zone_2"
    verdict_open = nc_funnel.evaluate_prescreen(zone2, settings, {digest}, line="open-line")
    assert verdict_open["status"] == "fail" and verdict_open["reason"] == nc_funnel.BAND_REJECTION
    assert "below the admission floor nc" in verdict_open["why"]

    # Zone 3-4 still fails Phase A on a zone_2 line (without needing a kill test).
    zone34 = {**zone2, "calibration_match": "zones_3_4", "kill_test": {"ran": False}}
    verdict_low = nc_funnel.evaluate_prescreen(zone34, settings, set(), line="established")
    assert verdict_low["status"] == "fail" and verdict_low["reason"] == nc_funnel.BAND_REJECTION
    assert "below the admission floor zone_2" in verdict_low["why"]

    # Kill-test downgrade: zone_1 -> zone_2 passes on zone_2 line; zone_2 -> zones_3_4 fails.
    z1_null, digest = _prescreen_result(tmp_path / "k2.json", match="zone_1", band="zone_1",
                                        null=0.6)
    v_z1_null = nc_funnel.evaluate_prescreen(z1_null, settings, {digest}, line="established")
    assert v_z1_null["status"] == "pass" and v_z1_null["expected_band"] == "zone_2"
    z2_null, digest = _prescreen_result(tmp_path / "k3.json", match="zone_2", band="zone_2",
                                        null=0.6)
    v_z2_null = nc_funnel.evaluate_prescreen(z2_null, settings, {digest}, line="established")
    assert v_z2_null["status"] == "fail" and v_z2_null["reason"] == nc_funnel.BAND_REJECTION
    assert "below the admission floor zone_2" in v_z2_null["why"]

    # Admission check honors the line's effective floor.
    ps_z2 = {"status": "pass", "expected_band": "zone_2", "calibration_match": "zone_2"}
    assert nc_funnel.admission_problems({"novelty_search": _novelty()}, settings, ps_z2,
                                        line="established") == []
    gaps_open = nc_funnel.admission_problems({"novelty_search": _novelty()}, settings, ps_z2,
                                             line="open-line")
    assert gaps_open and "below the admission floor nc" in gaps_open[0]

    # Instructions reflect each line's effective floor.
    assert "Admission floor: zone_2" in nc_funnel.scout_floor_instruction(settings, "established")
    assert "Admission floor: nc" in nc_funnel.scout_floor_instruction(settings, "open-line")
    est_scout = nc_funnel.scout_instruction(settings, "established")
    assert "line admission floor zone_2" in est_scout
    assert "topics aim high" in est_scout
    assert "would publish in NC" not in est_scout
    assert nc_funnel.scout_instruction(settings, "open-line") == nc_funnel.SCOUT_INSTRUCTION
    assert "Effective admission floor: zone_2" in nc_funnel.admission_instruction(
        settings, "established")
    assert "Effective admission floor: nc" in nc_funnel.admission_instruction(
        settings, "open-line")

    # Metrics expose global floor, configured line_floors, and per-line effective floor.
    stamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    doc = {"topics": [_rejected(0, stamp, line="established"),
                      _rejected(1, stamp, line="open-line")]}
    report = nc_funnel.metrics(doc, settings)
    assert report["admission_min_band"] == "nc"
    assert report["line_floors"] == {"established": "zone_2", "open-line": "nc"}
    assert report["lines"]["established"]["admission_min_band"] == "zone_2"
    assert report["lines"]["open-line"]["admission_min_band"] == "nc"


def test_zone2_line_goes_through_graded_funnel_end_to_end(tmp_path, monkeypatch):
    paths, db, settings = _setup(tmp_path, admission_min_band="nc")
    settings = replace(
        settings,
        program=replace(
            settings.program,
            polish_mode=True,
            lines={lines.LINE: LineSettings(mode="full", slots=2, admission_min_band="zone_2")},
        ),
    )
    assert target_stage.stage_for(db, lines.LINE, settings) == target_stage.NC_AIM

    scout_id, report = flow._scout_round(paths, db, settings, monkeypatch, [_nc_card()])
    assert report.errors == [], report.errors
    scout = db.task(scout_id)
    scout_packet = json.loads(Path(scout["input_path"]).read_text())
    assert scout_packet["admission_min_band"] == "zone_2"
    assert "Admission floor: zone_2" in scout["objective"]
    assert "line admission floor zone_2" in scout["objective"]
    assert report.program["by_line"][lines.LINE]["admission_min_band"] == "zone_2"
    assert report.program["nc_funnel"]["lines"][lines.LINE]["admission_min_band"] == "zone_2"

    registered, = report.program["cards_registered"]
    topic_id = registered["topic_id"]
    topic = open_topic_ledger(paths, settings.program).topic(topic_id)
    assert topic["card_check"]["nc_screen"]["admission_min_band"] == "zone_2"
    prescreen_task = db.task(topic["card_check"]["prescreen"]["task_id"])
    assert "match below zone_2 rejects the card" in prescreen_task["objective"]
    assert json.loads(Path(prescreen_task["input_path"]).read_text())[
        "funnel"]["admission_min_band"] == "zone_2"

    # A zone_2 calibration match + valid kill test passes prescreen and reaches admission.
    report = _finish_prescreen(paths, db, settings, monkeypatch, prescreen_task,
                               match="zone_2", band="zone_2")
    assert report.errors == [], report.errors
    topic = open_topic_ledger(paths, settings.program).topic(topic_id)
    assert topic["card_check"]["prescreen"]["status"] == "pass"
    assert topic["card_check"]["prescreen"]["expected_band"] == "zone_2"

    review = flow._admission_task(db)
    if review["status"] != "leased":
        flow._tick(paths, settings, monkeypatch)
        review = db.task(review["task_id"])
    assert "Effective admission floor: zone_2" in review["objective"]
    entry = flow._packet(review)["topic_cards"][0]
    assert entry["admission_min_band"] == "zone_2"
    branch = flow._branch(entry, novelty_search=_novelty())
    flow._complete(db, paths, review["task_id"], extra={"candidate_branches": [branch]})
    report = flow._tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors

    topic = open_topic_ledger(paths, settings.program).topic(topic_id)
    assert topic["status"] == "active"
    state = json.loads(Path(db.campaign(topic["campaign_id"])["workstream_state_path"]).read_text())
    assert state["target_stage"] == "nc_aim"
    assert state["expected_band"] == "zone_2"

    # Contrast: a line with nc_aim=False keeps its non-nc_aim stage and bypasses NC prescreen.
    exempt = replace(
        settings,
        program=replace(
            settings.program,
            lines={lines.LINE: LineSettings(mode="full", slots=2, nc_aim=False,
                                            admission_min_band="zone_2")},
        ),
    )
    assert target_stage.stage_for(db, lines.LINE, exempt) == target_stage.RUN_IN
    assert nc_funnel.screen_card(exempt, _nc_card(), {}, {"topics": []},
                                 target_stage.RUN_IN) == (None, [], {})

